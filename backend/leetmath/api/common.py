"""Shared API plumbing: DB session per request, auth, idempotency, serializers."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from decimal import Decimal

from fastapi import Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..content.contract import canonical_json, sha256_text
from ..models import (
    AuthSession,
    IdempotencyRecord,
    KnowledgeNode,
    Problem,
    ProblemRevision,
    RevisionKnowledge,
    RightsGrant,
    Source,
    SourceRecord,
    Submission,
    User,
    utcnow,
)
from ..services.errors import ApiError


def db(request: Request) -> Session:
    return request.state.db


# ─────────────────────────── passwords & tokens ───────────────────────────
def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _algo, n, r, p, salt, dk = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(dk)))
        return hmac.compare_digest(calc.hex(), dk)
    except (ValueError, TypeError):
        return False


def issue_token(s: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    s.add(AuthSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                      expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours)))
    return token


def _user_from_token(s: Session, token: str | None) -> User | None:
    if not token:
        return None
    sess = s.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
    if sess is None or sess.revoked:
        return None
    exp = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=utcnow().tzinfo)
    if exp <= utcnow():
        return None
    return s.get(User, sess.user_id)


def _request_token(request: Request, authorization: str | None) -> tuple[str | None, str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip(), "bearer"
    from ..services.security import session_cookie_name
    return request.cookies.get(session_cookie_name()), "cookie"


def optional_user(request: Request, authorization: str | None = Header(default=None)) -> User | None:
    token, mode = _request_token(request, authorization)
    request.state.auth_mode = mode if token else "anonymous"
    return _user_from_token(request.state.db, token)


def current_user(request: Request, authorization: str | None = Header(default=None)) -> User:
    token, mode = _request_token(request, authorization)
    request.state.auth_mode = mode if token else "anonymous"
    u = _user_from_token(request.state.db, token)
    if u is None:
        raise ApiError("AUTH_REQUIRED", "login required")
    return u


# ─────────────────────────── generic idempotency ───────────────────────────
def idempotent(s: Session, scope: str, key: str | None, body: dict, fn) -> tuple[int, dict]:
    """Replay-safe POST. Same key + same body → stored response; same key + other body → 409."""
    if not key:
        return fn()
    if not 8 <= len(key) <= 128:
        raise ApiError("VALIDATION_FAILED", "Idempotency-Key must be 8..128 chars")
    h = sha256_text(canonical_json(body))
    rec = s.get(IdempotencyRecord, (scope, key))
    if rec is not None:
        if rec.request_hash != h:
            raise ApiError("IDEMPOTENCY_CONFLICT", "Idempotency-Key reused with a different request")
        return rec.status_code, rec.response
    status, resp = fn()
    s.add(IdempotencyRecord(scope=scope, key=key, request_hash=h, status_code=status, response=resp))
    return status, resp


# ─────────────────────────── serializers ───────────────────────────
def dec(v) -> str | None:
    return None if v is None else str(Decimal(v).quantize(Decimal("0.01")))


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "roles": sorted(u.role_set)}


def knowledge_summaries(s: Session, rev: ProblemRevision) -> list[dict]:
    rows = s.execute(select(KnowledgeNode, RevisionKnowledge.relation_type)
                     .join(RevisionKnowledge, RevisionKnowledge.knowledge_node_id == KnowledgeNode.id)
                     .where(RevisionKnowledge.revision_id == rev.id)).all()
    return [{"id": n.id, "code": n.external_code, "title": n.title, "relation": rel} for n, rel in rows]


def source_attribution(s: Session, problem: Problem, rev: ProblemRevision) -> list[dict]:
    out = []
    grant = s.get(RightsGrant, rev.rights_grant_id) if rev.rights_grant_id else None
    for sr in s.scalars(select(SourceRecord).where(SourceRecord.canonical_problem_id == problem.id)):
        src = s.get(Source, sr.source_id)
        out.append({"source": src.name, "source_code": src.code, "kind": src.kind, "relation": sr.relation_to_problem,
                    "external_id": sr.external_id if src.kind != "teacher_private" else None})
    if not out:
        for ref in (rev.content_metadata or {}).get("_source_record_refs", []):
            src = s.scalar(select(Source).where(Source.code == ref["source_code"]))
            out.append({"source": src.name if src else ref["source_code"], "source_code": ref["source_code"],
                        "kind": src.kind if src else None, "relation": "origin", "note": ref.get("note")})
    if grant and grant.attribution_text:
        out.append({"attribution": grant.attribution_text})
    return out


def input_hint(part) -> dict:
    spec = part.answer_specs[-1]
    hint = {"response_type": part.response_type, "grading_mode": spec.grading_mode}
    if part.response_type in ("expression", "interval", "set", "equation_set"):
        hint["variables"] = spec.spec.get("assumptions", {})
        if spec.spec.get("solve_for"):
            hint["solve_for"] = spec.spec["solve_for"]
    if spec.spec.get("tolerance"):
        hint["tolerance"] = spec.spec["tolerance"]
    if spec.spec.get("unit"):
        hint["unit"] = spec.spec["unit"]
    return hint


def solutions_visible(s: Session, rev: ProblemRevision, part_id: str, user: User | None) -> bool:
    policy = (rev.content_metadata or {}).get("solution_visibility", "after_submit")
    if policy == "always":
        return True
    if user is None:
        return False
    if user.role_set & {"editor", "reviewer", "admin"}:
        return True
    if policy == "teacher_release":
        return False
    return s.scalar(select(Submission.id).where(Submission.user_id == user.id, Submission.revision_part_id == part_id).limit(1)) is not None


def revision_public_view(s: Session, problem: Problem, rev: ProblemRevision, user: User | None) -> dict:
    parts = []
    for p in rev.parts:
        pd = {"id": p.id, "logical_part_id": p.logical_part_id, "part_key": p.part_key, "display_order": p.display_order,
              "response_type": p.response_type, "max_score": dec(p.max_score), "prompt": p.prompt,
              "input": input_hint(p), "grading_suspended": p.grading_suspended, "knowledge_codes": p.knowledge_codes}
        if p.options:
            pd["options"] = p.options
        if solutions_visible(s, rev, p.id, user):
            pd["solutions"] = [{"type": so.solution_type, **so.content} for so in p.solutions]
        else:
            pd["solutions_locked"] = bool(p.solutions)
        parts.append(pd)
    md = rev.content_metadata or {}
    return {
        "id": rev.id, "revision_no": rev.revision_no, "locale": rev.locale, "title": rev.title,
        "status": rev.status, "published_at": rev.published_at.isoformat() if rev.published_at else None,
        "shared_statement": rev.shared_statement, "parts": parts,
        "difficulty": rev.platform_difficulty, "region_hints": md.get("region_hints", []),
        "problem_type": md.get("problem_type", []), "tags": md.get("tags", []),
        "verified_exam": bool(md.get("verified_exam")),
        "knowledge": knowledge_summaries(s, rev),
        "source_attribution": source_attribution(s, problem, rev),
        "visible_solutions_policy": md.get("solution_visibility", "after_submit"),
        "total_score": dec(sum(Decimal(p.max_score) for p in rev.parts)),
    }
