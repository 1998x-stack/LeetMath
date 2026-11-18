"""Attempts, submissions, evaluations, bookmarks, mistakes, progress, reports (docs/06, docs/09)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..content.contract import canonical_json, sha256_text
from ..grading.engine import grade
from ..models import (
    AnswerSpec,
    Attempt,
    Bookmark,
    ContentReport,
    Evaluation,
    KnowledgeNode,
    MistakeMark,
    Problem,
    ProblemRevision,
    RevisionKnowledge,
    RevisionPart,
    Submission,
    User,
    utcnow,
)
from .audit import audit
from .catalog import public_revision, require_roles
from .errors import ApiError
from .rate_limit import rate_limit

MATH_VERDICTS = {"accepted", "rejected", "partial"}

# Shared Redis-backed rate limiter; dev-only local fallback is isolated in services/rate_limit.py.

# ─────────────────────────── attempts & submissions ───────────────────────────
def _assert_revision_playable(s: Session, rev: ProblemRevision) -> None:
    problem = s.get(Problem, rev.problem_id)
    if rev.status == "retracted":
        raise ApiError("CONTENT_RETRACTED", "this problem has been retracted")
    current = public_revision(s, problem)
    if current is None:
        if rev.status in ("published", "archived") and (problem.takedown_hold or problem.current_public_revision_id == rev.id):
            raise ApiError("RIGHTS_HOLD", "this problem is temporarily unavailable")
        if rev.status == "archived":
            raise ApiError("REVISION_SUPERSEDED", "a newer revision exists", {"current_revision_id": problem.current_public_revision_id})
        raise ApiError("NOT_FOUND", "problem not found")
    if current.id != rev.id:
        raise ApiError("REVISION_SUPERSEDED", "a newer revision exists", {"current_revision_id": current.id})


def create_attempt(s: Session, user: User, problem_revision_id: str, mode: str = "practice") -> Attempt:
    rev = s.get(ProblemRevision, problem_revision_id)
    if rev is None:
        raise ApiError("NOT_FOUND", "revision not found")
    _assert_revision_playable(s, rev)
    att = Attempt(user_id=user.id, problem_revision_id=rev.id, mode=mode)
    s.add(att)
    s.flush()
    return att


def _latest_eval(s: Session, submission_id: str) -> Evaluation | None:
    return s.scalar(select(Evaluation).where(Evaluation.submission_id == submission_id)
                    .order_by(Evaluation.created_at.desc(), Evaluation.id.desc()).limit(1))


def submit(s: Session, user: User, attempt_id: str, revision_part_id: str, response: dict, idem_key: str) -> tuple[Submission, Evaluation, bool]:
    """Returns (submission, evaluation, replayed)."""
    if not idem_key or not (8 <= len(idem_key) <= 128):
        raise ApiError("VALIDATION_FAILED", "Idempotency-Key header (8..128 chars) is required")
    att = s.get(Attempt, attempt_id)
    if att is None or att.user_id != user.id:  # never reveal other users' attempts
        raise ApiError("NOT_FOUND", "attempt not found")
    req_hash = sha256_text(canonical_json({"part": revision_part_id, "response": response}))
    existing = s.scalar(select(Submission).where(Submission.attempt_id == att.id, Submission.idempotency_key == idem_key))
    if existing is not None:
        if sha256_text(canonical_json({"part": existing.revision_part_id, "response": existing.response})) != req_hash:
            raise ApiError("IDEMPOTENCY_CONFLICT", "Idempotency-Key reused with a different request body")
        return existing, _latest_eval(s, existing.id), True
    part = s.get(RevisionPart, revision_part_id)
    if part is None or part.problem_revision_id != att.problem_revision_id:
        raise ApiError("VALIDATION_FAILED", "revision_part_id does not belong to this attempt's revision")
    if not isinstance(response, dict) or not isinstance(response.get("input"), str):
        raise ApiError("VALIDATION_FAILED", "response.input must be a string")
    rev = s.get(ProblemRevision, att.problem_revision_id)
    _assert_revision_playable(s, rev)
    rate_limit(f"submit:user:{user.id}")
    spec: AnswerSpec = part.answer_specs[-1]
    sub = Submission(attempt_id=att.id, user_id=user.id, revision_part_id=part.id, answer_spec_id=spec.id,
                     response={"type": response.get("type", part.response_type), "input": response["input"][:2000]},
                     idempotency_key=idem_key)
    s.add(sub)
    s.flush()
    if part.grading_suspended:
        from ..grading.checkers import pending

        result = pending(Decimal(part.max_score), "GRADING_SUSPENDED", "该小问自动判题已暂停，提交将人工复核")
    else:
        option_ids = {o["id"] for o in (part.options or [])}
        result = grade(part.response_type, spec.grading_mode, spec.checker_type, spec.spec, response["input"],
                       Decimal(part.max_score), option_ids)
    ev = Evaluation(
        submission_id=sub.id, grader_name=result.grader_name, grader_version=result.grader_version,
        state=result.status, result_code=result.result_code,
        score=Decimal(result.score) if result.score is not None else None, max_score=Decimal(result.max_score),
        feedback={"message": result.message, **_public_details(result.details)},
    )
    s.add(ev)
    s.flush()
    _update_mistake(s, user.id, part.id, sub.id, ev.state)
    return sub, ev, False


def _public_details(details: dict) -> dict:
    # Never leak the hidden expected answer or internal sample points.
    return {k: v for k, v in details.items() if k in ("assumptions", "hybrid", "missing", "extra", "tolerance")}


def _update_mistake(s: Session, user_id: str, part_id: str, sub_id: str, state: str) -> None:
    """Only completed math verdicts rejected/partial create a mistake mark (docs/09 §6)."""
    mark = s.get(MistakeMark, (user_id, part_id))
    if state in ("rejected", "partial") and mark is None:
        s.add(MistakeMark(user_id=user_id, revision_part_id=part_id, origin_submission_id=sub_id))


def append_evaluation(s: Session, actor: User, submission: Submission, state: str, score: Decimal | None,
                      reason: str, matched: list[str] | None = None, regrade: bool = False) -> Evaluation:
    """Manual grading / regrade. Appends; never edits a previous evaluation (docs/06 §6)."""
    require_roles(actor, "reviewer")
    if state not in MATH_VERDICTS | {"pending_review"}:
        raise ApiError("VALIDATION_FAILED", "invalid evaluation state")
    part = s.get(RevisionPart, submission.revision_part_id)
    max_score = Decimal(part.max_score)
    if state in MATH_VERDICTS:
        if score is None or not (Decimal(0) <= score <= max_score):
            raise ApiError("VALIDATION_FAILED", f"score must be within 0..{max_score}")
        if state == "accepted" and score != max_score:
            raise ApiError("VALIDATION_FAILED", "accepted requires full score; use partial")
    if not reason:
        raise ApiError("VALIDATION_FAILED", "reason required")
    prev = _latest_eval(s, submission.id)
    ev = Evaluation(submission_id=submission.id, grader_name="human" if not regrade else "regrade",
                    grader_version="manual-1", state=state, result_code="MANUAL_REGRADE" if regrade else "MANUAL",
                    score=score, max_score=max_score,
                    feedback={"message": "评分已修订" if regrade else "教师已批改", "matched_criteria": matched or []},
                    evaluator_id=actor.id, previous_evaluation_id=prev.id if prev else None, reason=reason)
    s.add(ev)
    s.flush()
    audit(s, actor.id, "evaluation.append", "submission", submission.id, previous=prev.id if prev else None, state=state)
    _update_mistake(s, submission.user_id, part.id, submission.id, state)
    return ev


def regrade_submission(s: Session, actor: User, submission: Submission, reason: str) -> Evaluation:
    """Re-run the deterministic grader with the *original* answer spec; append the new result."""
    require_roles(actor, "reviewer")
    part = s.get(RevisionPart, submission.revision_part_id)
    spec = s.get(AnswerSpec, submission.answer_spec_id)
    r = grade(part.response_type, spec.grading_mode, spec.checker_type, spec.spec, submission.response["input"],
              Decimal(part.max_score), {o["id"] for o in part.options or []})
    prev = _latest_eval(s, submission.id)
    ev = Evaluation(submission_id=submission.id, grader_name=r.grader_name, grader_version=r.grader_version,
                    state=r.status, result_code=r.result_code,
                    score=Decimal(r.score) if r.score is not None else None, max_score=Decimal(r.max_score),
                    feedback={"message": "评分已修订：" + r.message}, evaluator_id=actor.id,
                    previous_evaluation_id=prev.id if prev else None, reason=reason)
    s.add(ev)
    s.flush()
    audit(s, actor.id, "evaluation.regrade", "submission", submission.id, previous=prev.id if prev else None)
    return ev


def manual_queue(s: Session, limit: int = 50) -> list[tuple[Submission, Evaluation]]:
    subs = s.scalars(select(Submission).order_by(Submission.created_at.asc())).all()
    out = []
    for sub in subs:
        ev = _latest_eval(s, sub.id)
        if ev and ev.state == "pending_review":
            out.append((sub, ev))
        if len(out) >= limit:
            break
    return out


# ─────────────────────────── personal learning ───────────────────────────
def toggle_bookmark(s: Session, user: User, problem_id: str, on: bool) -> None:
    problem = s.get(Problem, problem_id)
    if on:
        if public_revision(s, problem) is None:
            raise ApiError("NOT_FOUND", "problem not found")
        if s.get(Bookmark, (user.id, problem_id)) is None:
            s.add(Bookmark(user_id=user.id, problem_id=problem_id))
    else:
        b = s.get(Bookmark, (user.id, problem_id))
        if b:
            s.delete(b)


def part_progress(s: Session, user_id: str) -> dict[str, dict]:
    """Per revision_part: attempts, accepted count, latest effective state."""
    out: dict[str, dict] = {}
    subs = s.scalars(select(Submission).where(Submission.user_id == user_id).order_by(Submission.created_at)).all()
    for sub in subs:
        ev = _latest_eval(s, sub.id)
        st = out.setdefault(sub.revision_part_id, {"attempt_count": 0, "accepted_count": 0, "latest_state": None,
                                                   "last_attempt_at": None, "best_score": None})
        st["attempt_count"] += 1
        if ev and ev.state == "accepted":
            st["accepted_count"] += 1
        st["latest_state"] = ev.state if ev else None
        st["last_attempt_at"] = sub.created_at.isoformat()
        if ev and ev.score is not None:
            st["best_score"] = str(max(Decimal(st["best_score"] or 0), Decimal(ev.score)))
    return out


def knowledge_progress(s: Session, user_id: str) -> list[dict]:
    """P0: attempts/correct ratio per *tested* knowledge node, with explicit sample size (docs/09 §5)."""
    pp = part_progress(s, user_id)
    agg: dict[str, dict] = {}
    for part_id, st in pp.items():
        part = s.get(RevisionPart, part_id)
        nodes = s.scalars(select(KnowledgeNode).join(RevisionKnowledge, RevisionKnowledge.knowledge_node_id == KnowledgeNode.id)
                          .where(RevisionKnowledge.revision_id == part.problem_revision_id,
                                 RevisionKnowledge.relation_type == "tested")).all()
        codes = set(part.knowledge_codes or [])
        for n in nodes:
            if codes and n.external_code not in codes:
                continue
            a = agg.setdefault(n.id, {"knowledge_id": n.id, "code": n.external_code, "title": n.title,
                                      "parts_attempted": 0, "parts_accepted": 0, "submissions": 0})
            a["parts_attempted"] += 1
            a["submissions"] += st["attempt_count"]
            a["parts_accepted"] += 1 if st["accepted_count"] else 0
    for a in agg.values():
        a["accuracy"] = round(a["parts_accepted"] / a["parts_attempted"], 3) if a["parts_attempted"] else None
        a["low_sample"] = a["parts_attempted"] < 5
    return sorted(agg.values(), key=lambda x: x["code"])


def problem_progress(s: Session, user_id: str, rev: ProblemRevision) -> dict:
    """Group-level: a problem is 'completed' only if *every* part is accepted (no 1-of-3 = solved)."""
    pp = part_progress(s, user_id)
    parts = {p.id: pp.get(p.id) for p in rev.parts}
    accepted = sum(1 for v in parts.values() if v and v["accepted_count"])
    return {"parts": parts, "parts_accepted": accepted, "part_count": len(parts),
            "completed": accepted == len(parts) and len(parts) > 0}


def create_report(s: Session, user: User, problem_revision_id: str, kind: str, description: str,
                  revision_part_id: str | None = None, evaluation_id: str | None = None) -> ContentReport:
    rev = s.get(ProblemRevision, problem_revision_id)
    if rev is None or rev.status not in ("published", "archived", "retracted"):
        raise ApiError("NOT_FOUND", "revision not found")
    kinds = {"wrong_answer", "ambiguous", "missing_image", "misjudged", "rights", "typo", "other"}
    if kind not in kinds:
        raise ApiError("VALIDATION_FAILED", f"kind must be one of {sorted(kinds)}")
    if revision_part_id:
        part = s.get(RevisionPart, revision_part_id)
        if part is None or part.problem_revision_id != rev.id:
            raise ApiError("VALIDATION_FAILED", "part does not belong to revision")
    if evaluation_id:
        ev = s.get(Evaluation, evaluation_id)
        sub = s.get(Submission, ev.submission_id) if ev else None
        if sub is None or sub.user_id != user.id:
            raise ApiError("VALIDATION_FAILED", "evaluation not found")
    severity = "P0" if kind in ("wrong_answer", "rights", "misjudged") else "P1" if kind == "ambiguous" else "P2"
    r = ContentReport(reporter_id=user.id, problem_revision_id=rev.id, revision_part_id=revision_part_id,
                      evaluation_id=evaluation_id, kind=kind, description=description[:4000], severity=severity)
    s.add(r)
    s.flush()
    audit(s, user.id, "report.create", "content_report", r.id, severity=severity)
    return r


def resolve_report(s: Session, actor: User, report: ContentReport, state: str, resolution: str,
                   public_note: str | None, internal_note: str | None) -> None:
    require_roles(actor, "reviewer", "rights_reviewer")
    if state not in ("triaged", "resolved", "rejected"):
        raise ApiError("VALIDATION_FAILED", "invalid state")
    report.state = state
    report.resolution = resolution
    report.public_note = public_note
    report.internal_note = internal_note
    report.reviewer_id = actor.id
    report.updated_at = utcnow()
    audit(s, actor.id, f"report.{state}", "content_report", report.id, resolution=resolution)
