"""Public catalog, auth, learning endpoints (docs/07 §2–3)."""
from __future__ import annotations

from typing import Any
import hashlib

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Attempt,
    AuthSession,
    Bookmark,
    Collection,
    CollectionItem,
    ContentReport,
    CurriculumRelease,
    CurriculumSystem,
    Evaluation,
    KnowledgeNode,
    MistakeMark,
    Problem,
    ProblemRevision,
    RevisionPart,
    Submission,
    User,
)
from ..services import catalog, learning
from ..services.errors import ApiError
from ..services.security import create_csrf_token, csrf_cookie_name, session_cookie_name, valid_csrf_token
from ..services.search import search
from .common import (
    current_user,
    db,
    dec,
    hash_password,
    idempotent,
    issue_token,
    optional_user,
    revision_public_view,
    user_out,
    verify_password,
)

router = APIRouter(prefix="/api/v1")


# ─────────────────────────── auth ───────────────────────────
class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)


def _authenticate(s: Session, body: Credentials, action: str) -> User:
    learning.rate_limit(f"auth-user:{action}:{body.username.lower()}", 20)
    user = s.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise ApiError("AUTH_REQUIRED", "invalid username or password")
    return user


def _revoke_token(s: Session, token: str | None) -> None:
    if not token:
        return
    session = s.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
    if session:
        session.revoked = True


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=session_cookie_name(), value=token, max_age=settings.session_ttl_hours * 3600,
        httponly=True, secure=settings.cookie_secure, samesite="lax", path="/",
    )


@router.get("/auth/csrf")
def csrf_bootstrap(request: Request, response: Response):
    """Issue/reuse a signed, JS-readable CSRF token; it is not an authentication credential."""
    existing = request.cookies.get(csrf_cookie_name())
    token = existing if valid_csrf_token(existing) else create_csrf_token()
    response.set_cookie(
        key=csrf_cookie_name(), value=token, max_age=settings.session_ttl_hours * 3600,
        httponly=False, secure=settings.cookie_secure, samesite="strict", path="/",
    )
    return {"csrf_token": token}


@router.post("/auth/register", status_code=201)
def register(body: Credentials, request: Request, response: Response, s: Session = Depends(db)):
    if s.scalar(select(User).where(User.username == body.username)):
        raise ApiError("CONFLICT", "username taken")
    learning.rate_limit(f"register-user:{body.username.lower()}", 10)
    user = User(username=body.username, display_name=body.display_name or body.username, roles=",student,",
                password_hash=hash_password(body.password))
    s.add(user)
    s.flush()
    old_token = request.cookies.get(session_cookie_name())
    _revoke_token(s, old_token)
    _set_session_cookie(response, issue_token(s, user))
    return {"user": user_out(user)}


@router.post("/auth/login")
def login(body: Credentials, request: Request, response: Response, s: Session = Depends(db)):
    user = _authenticate(s, body, "login")
    # Rotate an existing browser session on re-authentication.
    _revoke_token(s, request.cookies.get(session_cookie_name()))
    _set_session_cookie(response, issue_token(s, user))
    return {"user": user_out(user)}


@router.post("/auth/token")
def issue_api_token(body: Credentials, s: Session = Depends(db)):
    """Explicit non-browser compatibility endpoint. Never use from the SPA."""
    user = _authenticate(s, body, "login")
    return {"token": issue_token(s, user), "user": user_out(user)}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, authorization: str | None = Header(default=None),
           s: Session = Depends(db)):
    if authorization and authorization.lower().startswith("bearer "):
        _revoke_token(s, authorization.split(" ", 1)[1].strip())
    _revoke_token(s, request.cookies.get(session_cookie_name()))
    response.delete_cookie(key=session_cookie_name(), path="/", secure=settings.cookie_secure,
                           httponly=True, samesite="lax")
    response.delete_cookie(key=csrf_cookie_name(), path="/", secure=settings.cookie_secure,
                           httponly=False, samesite="strict")
    response.status_code = 204
    return response


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


# ─────────────────────────── catalog ───────────────────────────
def _summary(s: Session, d, user: User | None, progress: dict | None) -> dict:
    out = {"id": d.problem_id, "display_id": d.display_id, "slug": d.slug, "title": d.title,
           "difficulty": d.difficulty or None, "grade_band": d.grade_band,
           "region_hints": [r for r in d.region_hints.split(",") if r], "part_count": d.part_count,
           "response_types": [r for r in d.response_types.split(",") if r],
           "knowledge_summaries": [k for k in d.knowledge_text.split(" ") if k][:6],
           "has_solution": d.has_solution, "current_public_revision_id": d.revision_id,
           "updated_at": d.updated_at.isoformat()}
    if user is not None and progress is not None:
        rev = s.get(ProblemRevision, d.revision_id)
        states = [progress.get(p.id) for p in rev.parts]
        if all(st and st["accepted_count"] for st in states):
            out["attempted_state"] = "completed"
        elif any(states):
            out["attempted_state"] = "attempted"
        else:
            out["attempted_state"] = "not_started"
    return out


@router.get("/problems")
def list_problems(
    query: str | None = None, grade_band: str | None = None, region: str | None = None,
    knowledge_id: str | None = None, difficulty_min: int | None = Query(None, ge=1, le=10),
    difficulty_max: int | None = Query(None, ge=1, le=10), response_type: str | None = None,
    source_kind: str | None = None, has_solution: bool | None = None, attempted: bool | None = None,
    sort: str | None = None, limit: int = Query(20, ge=1, le=100), cursor: str | None = None,
    s: Session = Depends(db), user: User | None = Depends(optional_user),
):
    res = search(s, query=query, grade_band=grade_band, region=region, knowledge_id=knowledge_id,
                 difficulty_min=difficulty_min, difficulty_max=difficulty_max, response_type=response_type,
                 source_kind=source_kind, has_solution=has_solution, attempted=attempted,
                 user_id=user.id if user else None, sort=sort, limit=limit, cursor=cursor)
    progress = learning.part_progress(s, user.id) if user else None
    return {"items": [_summary(s, d, user, progress) for d in res["items"]], "next_cursor": res["next_cursor"],
            "has_more": res["has_more"], "sort": res["sort"]}


@router.get("/problems/{slug}")
def get_problem(slug: str, s: Session = Depends(db), user: User | None = Depends(optional_user)):
    problem = catalog.find_problem_by_slug(s, slug)
    rev = catalog.public_revision(s, problem)
    if rev is None:
        raise ApiError("NOT_FOUND", "problem not found")  # same answer for missing/retracted/rights-held/private
    out = {"id": problem.id, "display_id": problem.display_id, "slug": problem.slug,
           "canonical_url": f"/problems/{problem.slug}", "grade_band": problem.grade_band,
           "current_revision": revision_public_view(s, problem, rev, user)}
    if user is not None:
        out["progress"] = learning.problem_progress(s, user.id, rev)
        out["bookmarked"] = s.get(Bookmark, (user.id, problem.id)) is not None
    return out


@router.get("/problems/{slug}/revisions/{revision_id}")
def get_problem_revision(slug: str, revision_id: str, s: Session = Depends(db), user: User = Depends(current_user)):
    """Historical revision: visible to staff, or to students who answered it; rights must still allow display."""
    problem = catalog.find_problem_by_slug(s, slug)
    rev = s.get(ProblemRevision, revision_id)
    if problem is None or rev is None or rev.problem_id != problem.id or rev.status not in ("published", "archived", "retracted"):
        raise ApiError("NOT_FOUND", "revision not found")
    staff = bool(user.role_set & {"editor", "reviewer", "admin"})
    answered = s.scalar(select(Attempt.id).where(Attempt.user_id == user.id, Attempt.problem_revision_id == rev.id).limit(1))
    if not (staff or answered):
        raise ApiError("NOT_FOUND", "revision not found")
    from ..services.rights import grant_allows
    from ..models import RightsGrant

    ok, _ = grant_allows(s.get(RightsGrant, rev.rights_grant_id) if rev.rights_grant_id else None, "display")
    if rev.status == "retracted" or problem.takedown_hold or not ok:
        return {"id": rev.id, "revision_no": rev.revision_no, "status": rev.status, "content_withheld": True,
                "message": "题目已下架或暂不可展示"}
    return revision_public_view(s, problem, rev, user)


@router.get("/knowledge")
def knowledge_tree(curriculum_release_id: str | None = None, s: Session = Depends(db)):
    stmt = select(KnowledgeNode, CurriculumRelease, CurriculumSystem).join(
        CurriculumRelease, KnowledgeNode.release_id == CurriculumRelease.id).join(
        CurriculumSystem, CurriculumRelease.system_id == CurriculumSystem.id)
    if curriculum_release_id:
        stmt = stmt.where(CurriculumRelease.id == curriculum_release_id)
    out: dict[str, dict] = {}
    for n, r, sysm in s.execute(stmt.order_by(KnowledgeNode.external_code)).all():
        rel = out.setdefault(r.id, {"release_id": r.id, "release_code": r.release_code, "label": r.label,
                                    "system": {"code": sysm.code, "label": sysm.label, "region": sysm.region,
                                               "grade_band": sysm.grade_band}, "nodes": []})
        rel["nodes"].append({"id": n.id, "code": n.external_code, "title": n.title, "parent_id": n.parent_id, "level": n.level})
    return {"releases": list(out.values())}


@router.get("/collections")
def list_collections(s: Session = Depends(db)):
    cols = s.scalars(select(Collection).where(Collection.visibility == "public").order_by(Collection.title)).all()
    return {"items": [{"id": c.id, "slug": c.slug, "title": c.title, "description": c.description, "kind": c.kind} for c in cols]}


@router.get("/collections/{cid}")
def get_collection(cid: str, s: Session = Depends(db), user: User | None = Depends(optional_user)):
    c = s.get(Collection, cid) or s.scalar(select(Collection).where(Collection.slug == cid))
    if c is None or (c.visibility != "public" and (user is None or user.id != c.owner_id)):
        raise ApiError("NOT_FOUND", "collection not found")
    items = []
    for it in s.scalars(select(CollectionItem).where(CollectionItem.collection_id == c.id).order_by(CollectionItem.ordinal)):
        p = s.get(Problem, it.problem_id)
        rev = catalog.public_revision(s, p)
        if rev is None:  # re-check visibility + rights on every read (docs/09 §4)
            continue
        items.append({"ordinal": it.ordinal, "problem_id": p.id, "display_id": p.display_id, "slug": p.slug,
                      "title": rev.title, "difficulty": rev.platform_difficulty, "revision_id": rev.id})
    return {"id": c.id, "slug": c.slug, "title": c.title, "description": c.description, "kind": c.kind, "items": items}


# ─────────────────────────── attempts & submissions ───────────────────────────
class AttemptIn(BaseModel):
    problem_revision_id: str
    mode: str = "practice"


@router.post("/attempts", status_code=201)
def create_attempt(body: AttemptIn, response: Response, s: Session = Depends(db), user: User = Depends(current_user),
                   idempotency_key: str | None = Header(default=None)):
    def run():
        att = learning.create_attempt(s, user, body.problem_revision_id, body.mode)
        return 201, {"attempt_id": att.id, "problem_revision_id": att.problem_revision_id}

    status, out = idempotent(s, f"attempt:{user.id}", idempotency_key, body.model_dump(), run)
    response.status_code = status
    return out


class ResponseIn(BaseModel):
    type: str | None = None
    input: str = Field(max_length=2000)


class SubmitIn(BaseModel):
    revision_part_id: str
    response: ResponseIn


def _eval_out(ev: Evaluation | None) -> dict | None:
    if ev is None:
        return None
    return {"evaluation_id": ev.id, "status": ev.state, "score": dec(ev.score), "max_score": dec(ev.max_score),
            "result_code": ev.result_code, "checker_version": f"{ev.grader_name}/{ev.grader_version}",
            "message": (ev.feedback or {}).get("message"), "matched_criteria": (ev.feedback or {}).get("matched_criteria", []),
            "regrade_eligible": ev.state in ("rejected", "partial", "pending_review"),
            "previous_evaluation_id": ev.previous_evaluation_id, "created_at": ev.created_at.isoformat(),
            "is_math_verdict": ev.state in learning.MATH_VERDICTS}


@router.post("/attempts/{attempt_id}/submissions")
def submit(attempt_id: str, body: SubmitIn, response: Response, s: Session = Depends(db),
           user: User = Depends(current_user), idempotency_key: str | None = Header(default=None)):
    sub, ev, replayed = learning.submit(s, user, attempt_id, body.revision_part_id, body.response.model_dump(), idempotency_key or "")
    response.status_code = 200
    return {"submission_id": sub.id, "evaluation_id": ev.id if ev else None, "status": ev.state if ev else "queued",
            "poll_url": f"/api/v1/submissions/{sub.id}", "replayed": replayed, "evaluation": _eval_out(ev)}


def _own_submission(s: Session, user: User, sid: str) -> Submission:
    sub = s.get(Submission, sid)
    if sub is None or (sub.user_id != user.id and not (user.role_set & {"reviewer", "admin"})):
        raise ApiError("NOT_FOUND", "submission not found")
    return sub


def _submission_out(s: Session, sub: Submission, with_history: bool = False) -> dict:
    part = s.get(RevisionPart, sub.revision_part_id)
    rev = s.get(ProblemRevision, part.problem_revision_id)
    problem = s.get(Problem, rev.problem_id)
    evs = s.scalars(select(Evaluation).where(Evaluation.submission_id == sub.id).order_by(Evaluation.created_at)).all()
    latest = evs[-1] if evs else None
    current = catalog.public_revision(s, problem)
    out = {"id": sub.id, "attempt_id": sub.attempt_id, "revision_part_id": sub.revision_part_id,
           "problem_revision_id": rev.id, "revision_no": rev.revision_no, "part_key": part.part_key,
           "answer_spec_id": sub.answer_spec_id, "response": sub.response, "created_at": sub.created_at.isoformat(),
           "status": latest.state if latest else "queued", "score": dec(latest.score) if latest else None,
           "max_score": dec(part.max_score), "evaluation_id": latest.id if latest else None,
           "evaluation": _eval_out(latest),
           "problem": {"display_id": problem.display_id, "slug": problem.slug,
                       "title": rev.title if current is not None else None,
                       "available": current is not None,
                       "superseded": current is not None and current.id != rev.id,
                       "notice": None if current is not None else "题目已下架"}}
    if with_history:
        out["evaluations"] = [_eval_out(e) for e in evs]
    return out


@router.get("/submissions/{sid}")
def get_submission(sid: str, s: Session = Depends(db), user: User = Depends(current_user)):
    return _submission_out(s, _own_submission(s, user, sid), with_history=True)


@router.get("/submissions/{sid}/evaluations")
def get_evaluations(sid: str, s: Session = Depends(db), user: User = Depends(current_user)):
    sub = _own_submission(s, user, sid)
    evs = s.scalars(select(Evaluation).where(Evaluation.submission_id == sub.id).order_by(Evaluation.created_at)).all()
    return {"items": [_eval_out(e) for e in evs]}


@router.get("/me/submissions")
def my_submissions(limit: int = Query(20, ge=1, le=100), cursor: str | None = None, s: Session = Depends(db),
                   user: User = Depends(current_user)):
    stmt = select(Submission).where(Submission.user_id == user.id)
    if cursor:
        try:
            ts, sid = cursor.split("|", 1)
        except ValueError as e:
            raise ApiError("VALIDATION_FAILED", "invalid cursor") from e
        from datetime import datetime

        t = datetime.fromisoformat(ts)
        stmt = stmt.where((Submission.created_at < t) | ((Submission.created_at == t) & (Submission.id < sid)))
    subs = s.scalars(stmt.order_by(Submission.created_at.desc(), Submission.id.desc()).limit(limit + 1)).all()
    more = len(subs) > limit
    subs = subs[:limit]
    nxt = f"{subs[-1].created_at.isoformat()}|{subs[-1].id}" if more and subs else None
    return {"items": [_submission_out(s, x) for x in subs], "next_cursor": nxt, "has_more": more}


# ─────────────────────────── bookmarks / mistakes / progress ───────────────────────────
@router.put("/me/bookmarks/{problem_id}", status_code=204)
def add_bookmark(problem_id: str, s: Session = Depends(db), user: User = Depends(current_user)):
    learning.toggle_bookmark(s, user, problem_id, True)
    return Response(status_code=204)


@router.delete("/me/bookmarks/{problem_id}", status_code=204)
def del_bookmark(problem_id: str, s: Session = Depends(db), user: User = Depends(current_user)):
    learning.toggle_bookmark(s, user, problem_id, False)
    return Response(status_code=204)


@router.get("/me/bookmarks")
def my_bookmarks(s: Session = Depends(db), user: User = Depends(current_user)):
    out = []
    for b in s.scalars(select(Bookmark).where(Bookmark.user_id == user.id).order_by(Bookmark.created_at.desc())):
        p = s.get(Problem, b.problem_id)
        rev = catalog.public_revision(s, p)
        out.append({"problem_id": p.id, "display_id": p.display_id, "slug": p.slug,
                    "title": rev.title if rev else None, "available": rev is not None,
                    "created_at": b.created_at.isoformat()})
    return {"items": out}


@router.get("/me/mistakes")
def my_mistakes(s: Session = Depends(db), user: User = Depends(current_user)):
    out = []
    for m in s.scalars(select(MistakeMark).where(MistakeMark.user_id == user.id).order_by(MistakeMark.created_at.desc())):
        part = s.get(RevisionPart, m.revision_part_id)
        rev = s.get(ProblemRevision, part.problem_revision_id)
        p = s.get(Problem, rev.problem_id)
        cur = catalog.public_revision(s, p)
        out.append({"revision_part_id": part.id, "part_key": part.part_key, "problem_id": p.id,
                    "display_id": p.display_id, "slug": p.slug, "title": rev.title if cur else None,
                    "available": cur is not None, "revision_no": rev.revision_no,
                    "current_revision_no": cur.revision_no if cur else None,
                    "changed_since": bool(cur and cur.id != rev.id),
                    "origin_submission_id": m.origin_submission_id, "manual": m.manual})
    return {"items": out}


@router.put("/me/mistakes/{part_id}", status_code=204)
def add_mistake(part_id: str, s: Session = Depends(db), user: User = Depends(current_user)):
    part = s.get(RevisionPart, part_id)
    if part is None:
        raise ApiError("NOT_FOUND", "part not found")
    if s.get(MistakeMark, (user.id, part_id)) is None:
        s.add(MistakeMark(user_id=user.id, revision_part_id=part_id, manual=True))
    return Response(status_code=204)


@router.delete("/me/mistakes/{part_id}", status_code=204)
def del_mistake(part_id: str, s: Session = Depends(db), user: User = Depends(current_user)):
    m = s.get(MistakeMark, (user.id, part_id))
    if m:
        s.delete(m)
    return Response(status_code=204)


@router.get("/me/progress")
def my_progress(knowledge_id: str | None = None, s: Session = Depends(db), user: User = Depends(current_user)):
    kp = learning.knowledge_progress(s, user.id)
    if knowledge_id:
        kp = [k for k in kp if k["knowledge_id"] == knowledge_id]
    recent = s.scalars(select(Attempt).where(Attempt.user_id == user.id).order_by(Attempt.started_at.desc()).limit(10)).all()
    rec = []
    for a in recent:
        rev = s.get(ProblemRevision, a.problem_revision_id)
        p = s.get(Problem, rev.problem_id)
        cur = catalog.public_revision(s, p)
        rec.append({"attempt_id": a.id, "display_id": p.display_id, "slug": p.slug, "title": rev.title if cur else None,
                    "available": cur is not None, "started_at": a.started_at.isoformat()})
    return {"knowledge": kp, "recent_attempts": rec,
            "note": "按知识点统计的尝试与正确次数，样本不足时仅供参考，不等价于真实掌握度"}


# ─────────────────────────── content reports ───────────────────────────
class ReportIn(BaseModel):
    problem_revision_id: str
    revision_part_id: str | None = None
    evaluation_id: str | None = None
    kind: str
    description: str = Field(default="", max_length=4000)


def _report_out(r: ContentReport, staff: bool) -> dict:
    out = {"id": r.id, "kind": r.kind, "severity": r.severity, "state": r.state, "public_note": r.public_note,
           "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(),
           "problem_revision_id": r.problem_revision_id, "revision_part_id": r.revision_part_id}
    if staff:
        out.update(internal_note=r.internal_note, description=r.description, resolution=r.resolution, reporter_id=r.reporter_id)
    return out


@router.post("/content-reports", status_code=201)
def create_report(body: ReportIn, s: Session = Depends(db), user: User = Depends(current_user)):
    learning.rate_limit(f"report:{user.id}", 20)
    r = learning.create_report(s, user, body.problem_revision_id, body.kind, body.description, body.revision_part_id, body.evaluation_id)
    return _report_out(r, False)


@router.get("/content-reports/{rid}")
def get_report(rid: str, s: Session = Depends(db), user: User = Depends(current_user)):
    r = s.get(ContentReport, rid)
    staff = bool(user.role_set & {"reviewer", "rights_reviewer", "admin"})
    if r is None or (r.reporter_id != user.id and not staff):
        raise ApiError("NOT_FOUND", "report not found")
    return _report_out(r, staff)


@router.get("/me/content-reports")
def my_reports(s: Session = Depends(db), user: User = Depends(current_user)):
    rs = s.scalars(select(ContentReport).where(ContentReport.reporter_id == user.id).order_by(ContentReport.created_at.desc())).all()
    return {"items": [_report_out(r, False) for r in rs]}


def _unused(*_: Any) -> None:  # keep linters calm about re-exported helpers
    return None
