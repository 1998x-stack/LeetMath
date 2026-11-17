"""CMS / sources / imports / review / grading-queue endpoints (docs/07 §4, docs/08). All writes check roles server-side."""
from __future__ import annotations

import base64
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..content.contract import preflight
from ..models import (
    AuditEvent,
    Collection,
    CollectionItem,
    ContentReport,
    DuplicateCandidate,
    Evaluation,
    ImportBatch,
    ImportRow,
    Problem,
    ProblemRevision,
    RevisionPart,
    RightsGrant,
    Source,
    SourceRecord,
    SourceRecordRevision,
    Submission,
    User,
    WorkflowEvent,
    utcnow,
)
from ..services import catalog, ingestion, learning
from ..services.audit import audit
from ..services.catalog import require_roles
from ..services.errors import ApiError
from .common import current_user, db, dec, idempotent, user_out

router = APIRouter(prefix="/api/v1/admin")
STAFF = ("editor", "reviewer", "rights_reviewer", "source_manager", "auditor")


def _rev(s: Session, rid: str) -> ProblemRevision:
    rev = s.get(ProblemRevision, rid)
    if rev is None:
        raise ApiError("NOT_FOUND", "revision not found")
    return rev


def _rev_row(s: Session, rev: ProblemRevision) -> dict:
    p = s.get(Problem, rev.problem_id)
    return {"revision_id": rev.id, "problem_id": p.id, "display_id": p.display_id, "slug": p.slug, "title": rev.title,
            "revision_no": rev.revision_no, "status": rev.status, "lock_version": rev.lock_version,
            "created_by": rev.created_by, "math_reviewer_id": rev.math_reviewer_id, "rights_reviewer_id": rev.rights_reviewer_id,
            "review_note": rev.review_note, "updated_at": rev.updated_at.isoformat(),
            "published_at": rev.published_at.isoformat() if rev.published_at else None,
            "is_current_public": p.current_public_revision_id == rev.id, "takedown_hold": p.takedown_hold,
            "visibility": p.visibility}


# ─────────────────────────── problems & revisions ───────────────────────────
@router.get("/problems")
def admin_list(status: str | None = None, q: str | None = None, limit: int = Query(50, ge=1, le=200),
               s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, *STAFF)
    stmt = select(ProblemRevision).join(Problem, Problem.id == ProblemRevision.problem_id)
    if status:
        stmt = stmt.where(ProblemRevision.status == status)
    if q:
        stmt = stmt.where((ProblemRevision.title.like(f"%{q}%")) | (Problem.display_id.like(f"%{q.upper()}%")))
    revs = s.scalars(stmt.order_by(Problem.display_id, ProblemRevision.revision_no.desc()).limit(limit)).all()
    return {"items": [_rev_row(s, r) for r in revs]}


class DocIn(BaseModel):
    document: dict


@router.post("/preflight")
def preflight_doc(body: DocIn, user: User = Depends(current_user)):
    require_roles(user, "editor", "reviewer", "source_manager")
    issues = preflight(body.document)
    return {"ok": not any(i["severity"] == "blocking" for i in issues), "issues": issues}


@router.post("/problems", status_code=201)
def admin_create(body: DocIn, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "editor")
    from ..content.contract import schema_issues

    errs = schema_issues(body.document)
    if errs:
        raise ApiError("VALIDATION_FAILED", "document does not match Content Contract v1", {"issues": errs})
    rev = catalog.create_problem(s, body.document, user)
    s.flush()
    return {**_rev_row(s, rev), "document": catalog.revision_to_doc(s, rev)}


@router.get("/problems/{pid}")
def admin_get_problem(pid: str, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, *STAFF)
    p = s.get(Problem, pid) or catalog.find_problem_by_slug(s, pid)
    if p is None:
        raise ApiError("NOT_FOUND", "problem not found")
    revs = s.scalars(select(ProblemRevision).where(ProblemRevision.problem_id == p.id).order_by(ProblemRevision.revision_no)).all()
    srs = s.scalars(select(SourceRecord).where(SourceRecord.canonical_problem_id == p.id)).all()
    return {"problem": {"id": p.id, "display_id": p.display_id, "slug": p.slug, "visibility": p.visibility,
                        "takedown_hold": p.takedown_hold, "current_public_revision_id": p.current_public_revision_id},
            "revisions": [_rev_row(s, r) for r in revs],
            "source_records": [{"id": sr.id, "source": s.get(Source, sr.source_id).code, "external_id": sr.external_id,
                                "relation": sr.relation_to_problem, "latest_source_revision": sr.latest_source_revision} for sr in srs]}


@router.post("/problems/{pid}/revisions", status_code=201)
def admin_new_revision(pid: str, body: DocIn | None = None, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "editor")
    p = s.get(Problem, pid)
    if p is None:
        raise ApiError("NOT_FOUND", "problem not found")
    rev = catalog.new_revision(s, p, user, body.document if body else None)
    s.flush()
    return {**_rev_row(s, rev), "document": catalog.revision_to_doc(s, rev)}


@router.get("/problem-revisions/{rid}")
def admin_get_revision(rid: str, response: Response, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, *STAFF)
    rev = _rev(s, rid)
    response.headers["ETag"] = f'"{rev.lock_version}"'
    events = s.scalars(select(WorkflowEvent).where(WorkflowEvent.revision_id == rev.id).order_by(WorkflowEvent.created_at)).all()
    return {**_rev_row(s, rev), "document": catalog.revision_to_doc(s, rev),
            "workflow": [{"from": e.from_status, "to": e.to_status, "actor_id": e.actor_id, "reason": e.reason,
                          "at": e.created_at.isoformat()} for e in events]}


@router.patch("/problem-revisions/{rid}")
def admin_edit_revision(rid: str, body: DocIn, response: Response, s: Session = Depends(db),
                        user: User = Depends(current_user), if_match: str | None = Header(default=None)):
    require_roles(user, "editor")
    from ..content.contract import schema_issues

    errs = schema_issues(body.document)
    if errs:
        raise ApiError("VALIDATION_FAILED", "document does not match Content Contract v1", {"issues": errs})
    rev = _rev(s, rid)
    lv = int(if_match.strip('"W/ ')) if if_match and if_match.strip('"W/ ').isdigit() else None
    catalog.update_draft(s, rev, body.document, user, lv)
    s.flush()
    response.headers["ETag"] = f'"{rev.lock_version}"'
    return {**_rev_row(s, rev), "document": catalog.revision_to_doc(s, rev)}


@router.post("/problem-revisions/{rid}/preflight")
def admin_preflight_revision(rid: str, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, *STAFF)
    issues = catalog.full_preflight(s, _rev(s, rid))
    return {"ok": not any(i["severity"] == "blocking" for i in issues), "issues": issues}


class NoteIn(BaseModel):
    note: str | None = None
    reason: str | None = None


@router.post("/problem-revisions/{rid}/submit-review")
def submit_review(rid: str, body: NoteIn | None = None, s: Session = Depends(db), user: User = Depends(current_user)):
    rev = _rev(s, rid)
    issues = catalog.submit_review(s, rev, user, body.note if body else None)
    return {**_rev_row(s, rev), "warnings": [i for i in issues if i["severity"] == "warning"]}


@router.post("/problem-revisions/{rid}/approve")
def approve(rid: str, body: NoteIn | None = None, s: Session = Depends(db), user: User = Depends(current_user)):
    """Approves the *current* gate: math review → rights review → approved."""
    rev = _rev(s, rid)
    note = body.note if body else None
    if rev.status == "in_math_review":
        catalog.approve_math(s, rev, user, note)
    elif rev.status == "in_rights_review":
        catalog.approve_rights(s, rev, user, note)
    else:
        raise ApiError("INVALID_STATE", f"nothing to approve in status {rev.status}")
    return _rev_row(s, rev)


@router.post("/problem-revisions/{rid}/reject")
def reject(rid: str, body: NoteIn, s: Session = Depends(db), user: User = Depends(current_user)):
    rev = _rev(s, rid)
    catalog.reject(s, rev, user, body.reason or body.note or "")
    return _rev_row(s, rev)


@router.post("/problem-revisions/{rid}/publish")
def publish(rid: str, response: Response, s: Session = Depends(db), user: User = Depends(current_user),
            idempotency_key: str | None = Header(default=None)):
    def run():
        rev = _rev(s, rid)
        catalog.publish(s, rev, user)
        return 200, _rev_row(s, rev)

    status, out = idempotent(s, f"publish:{rid}", idempotency_key, {"rid": rid}, run)
    response.status_code = status
    return out


@router.post("/problem-revisions/{rid}/retract")
def retract(rid: str, body: NoteIn, s: Session = Depends(db), user: User = Depends(current_user)):
    rev = _rev(s, rid)
    catalog.retract(s, rev, user, body.reason or "")
    return _rev_row(s, rev)


class HoldIn(BaseModel):
    hold: bool
    reason: str = Field(min_length=1)


@router.post("/problems/{pid}/rights-hold")
def rights_hold(pid: str, body: HoldIn, s: Session = Depends(db), user: User = Depends(current_user)):
    p = s.get(Problem, pid)
    if p is None:
        raise ApiError("NOT_FOUND", "problem not found")
    catalog.set_takedown_hold(s, p, user, body.hold, body.reason)
    return {"problem_id": p.id, "takedown_hold": p.takedown_hold}


class SlugIn(BaseModel):
    slug: str


@router.post("/problems/{pid}/slug")
def rename_slug(pid: str, body: SlugIn, s: Session = Depends(db), user: User = Depends(current_user)):
    p = s.get(Problem, pid)
    if p is None:
        raise ApiError("NOT_FOUND", "problem not found")
    catalog.rename_slug(s, p, body.slug, user)
    return {"problem_id": p.id, "slug": p.slug}


class SuspendIn(BaseModel):
    suspended: bool
    reason: str = Field(min_length=1)


@router.post("/revision-parts/{part_id}/grading")
def suspend_grading(part_id: str, body: SuspendIn, s: Session = Depends(db), user: User = Depends(current_user)):
    part = s.get(RevisionPart, part_id)
    if part is None:
        raise ApiError("NOT_FOUND", "part not found")
    catalog.set_grading_suspended(s, part, user, body.suspended, body.reason)
    return {"revision_part_id": part.id, "grading_suspended": part.grading_suspended}


@router.get("/reviews")
def review_queue(stage: str = "math", s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "reviewer", "rights_reviewer")
    status = {"math": "in_math_review", "rights": "in_rights_review", "publish": "approved"}.get(stage)
    if status is None:
        raise ApiError("VALIDATION_FAILED", "stage must be math|rights|publish")
    revs = s.scalars(select(ProblemRevision).where(ProblemRevision.status == status).order_by(ProblemRevision.updated_at)).all()
    now = utcnow()
    out = []
    for r in revs:
        row = _rev_row(s, r)
        upd = r.updated_at if r.updated_at.tzinfo else r.updated_at.replace(tzinfo=now.tzinfo)
        row["age_hours"] = round((now - upd).total_seconds() / 3600, 1)
        row["is_own"] = r.created_by == user.id
        out.append(row)
    return {"items": out}


# ─────────────────────────── sources & rights ───────────────────────────
class SourceIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{1,127}$")
    name: str
    kind: str = Field(pattern=r"^(internal|partner|open_license|document|teacher_private|legacy)$")
    homepage: str | None = None
    owner: str | None = None


@router.get("/sources")
def list_sources(s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, *STAFF)
    out = []
    for src in s.scalars(select(Source).order_by(Source.code)):
        grants = s.scalars(select(RightsGrant).where(RightsGrant.source_id == src.id)).all()
        n = s.scalar(select(func.count()).select_from(SourceRecord).where(SourceRecord.source_id == src.id))
        out.append({"id": src.id, "code": src.code, "name": src.name, "kind": src.kind, "status": src.status,
                    "default_visibility": src.default_visibility, "record_count": n,
                    "grants": [_grant_out(g) for g in grants]})
    return {"items": out}


def _grant_out(g: RightsGrant) -> dict:
    from ..services.rights import grant_allows

    ok, why = grant_allows(g, "display")
    return {"id": g.id, "code": g.code, "grant_type": g.grant_type, "scope": g.scope, "territory": g.territory,
            "permitted_actions": g.permitted_actions, "valid_from": g.valid_from.isoformat() if g.valid_from else None,
            "valid_to": g.valid_to.isoformat() if g.valid_to else None, "status": g.status,
            "attribution_text": g.attribution_text, "evidence_ref": g.evidence_ref, "display_ok": ok, "display_reason": why}


@router.post("/sources", status_code=201)
def create_source(body: SourceIn, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "source_manager")
    if s.scalar(select(Source).where(Source.code == body.code)):
        raise ApiError("CONFLICT", "source code exists")
    src = Source(**body.model_dump(), default_visibility="private" if body.kind == "teacher_private" else "public")
    s.add(src)
    s.flush()
    audit(s, user.id, "source.create", "source", src.id, code=src.code)
    return {"id": src.id, "code": src.code}


class SourceStatusIn(BaseModel):
    status: str = Field(pattern=r"^(active|disabled)$")


@router.post("/sources/{sid}/status")
def source_status(sid: str, body: SourceStatusIn, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "source_manager")
    src = s.get(Source, sid)
    if src is None:
        raise ApiError("NOT_FOUND", "source not found")
    src.status = body.status
    audit(s, user.id, "source.status", "source", src.id, status=body.status)
    return {"id": src.id, "status": src.status}


class GrantIn(BaseModel):
    code: str
    source_code: str
    grant_type: str
    scope: str = ""
    territory: str = "WORLD"
    permitted_actions: list[str]
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    evidence_ref: str | None = None
    attribution_text: str | None = None


@router.post("/rights-grants", status_code=201)
def create_grant(body: GrantIn, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "source_manager", "rights_reviewer")
    from ..services.rights import ACTIONS

    src = s.scalar(select(Source).where(Source.code == body.source_code))
    if src is None:
        raise ApiError("VALIDATION_FAILED", "unknown source")
    if not set(body.permitted_actions) <= set(ACTIONS):
        raise ApiError("VALIDATION_FAILED", f"actions must be within {ACTIONS}")
    if s.scalar(select(RightsGrant).where(RightsGrant.code == body.code)):
        raise ApiError("CONFLICT", "grant code exists")
    # A grant becomes active only after a rights reviewer accepts the evidence.
    status = "active" if "rights_reviewer" in user.role_set or "admin" in user.role_set else "pending"
    g = RightsGrant(code=body.code, source_id=src.id, grant_type=body.grant_type, scope=body.scope, territory=body.territory,
                    permitted_actions=body.permitted_actions, valid_from=body.valid_from, valid_to=body.valid_to,
                    evidence_ref=body.evidence_ref, attribution_text=body.attribution_text, status=status,
                    reviewed_by=user.id if status == "active" else None)
    s.add(g)
    s.flush()
    audit(s, user.id, "rights.create", "rights_grant", g.id, status=status)
    return _grant_out(g)


class GrantStatusIn(BaseModel):
    status: str = Field(pattern=r"^(active|revoked|pending)$")
    reason: str = Field(min_length=1)
    valid_to: datetime | None = None


@router.post("/rights-grants/{gid}/status")
def grant_status(gid: str, body: GrantStatusIn, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "rights_reviewer")
    g = s.get(RightsGrant, gid) or s.scalar(select(RightsGrant).where(RightsGrant.code == gid))
    if g is None:
        raise ApiError("NOT_FOUND", "grant not found")
    g.status = body.status
    if body.valid_to is not None:
        g.valid_to = body.valid_to
    g.reviewed_by = user.id
    audit(s, user.id, "rights.status", "rights_grant", g.id, status=body.status, reason=body.reason)
    return _grant_out(g)


# ─────────────────────────── imports ───────────────────────────
class ImportIn(BaseModel):
    manifest: dict
    files: dict[str, str]  # path → UTF-8 text, or "base64:<data>"


def _decode_files(files: dict[str, str]) -> dict[str, bytes]:
    out = {}
    for path, content in files.items():
        if content.startswith("base64:"):
            out[path] = base64.b64decode(content[7:])
        else:
            out[path] = content.encode("utf-8")
    return out


def _batch_out(b: ImportBatch, replayed: bool = False) -> dict:
    return {"batch_id": b.id, "status": b.state, "dry_run": b.dry_run, "counts": b.counts, "replayed": replayed,
            "idempotency_key": b.idempotency_key, "importer_version": b.importer_version,
            "dataset": f"{b.manifest['dataset_id']}@{b.manifest['dataset_version']}",
            "adapter_version": b.manifest["adapter_version"], "started_at": b.started_at.isoformat(),
            "finished_at": b.finished_at.isoformat() if b.finished_at else None}


@router.post("/imports/dry-run", status_code=202)
def import_dry_run(body: ImportIn, s: Session = Depends(db), user: User = Depends(current_user)):
    m = {**body.manifest, "dry_run": True}
    batch, replayed = ingestion.run_import(s, m, _decode_files(body.files), user)
    return _batch_out(batch, replayed)


@router.post("/imports", status_code=202)
def import_create(body: ImportIn, s: Session = Depends(db), user: User = Depends(current_user)):
    batch, replayed = ingestion.run_import(s, body.manifest, _decode_files(body.files), user)
    return _batch_out(batch, replayed)


@router.get("/imports")
def import_list(s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "source_manager", "reviewer")
    bs = s.scalars(select(ImportBatch).order_by(ImportBatch.started_at.desc()).limit(100)).all()
    return {"items": [_batch_out(b) for b in bs]}


@router.get("/imports/{bid}")
def import_get(bid: str, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "source_manager", "reviewer")
    b = s.get(ImportBatch, bid)
    if b is None:
        raise ApiError("NOT_FOUND", "batch not found")
    return {**_batch_out(b), "manifest": b.manifest}


@router.get("/imports/{bid}/rows")
def import_rows(bid: str, state: str | None = None, format: str = "json", s: Session = Depends(db),
                user: User = Depends(current_user)):
    require_roles(user, "source_manager", "reviewer")
    stmt = select(ImportRow).where(ImportRow.batch_id == bid)
    if state:
        stmt = stmt.where(ImportRow.state == state)
    rows = s.scalars(stmt.order_by(ImportRow.file_path, ImportRow.row_no)).all()
    items = [{"file": r.file_path, "row_no": r.row_no, "source_record_key": r.source_record_key, "state": r.state,
              "stage": r.stage, "error_code": r.error_code, "error_detail": r.error_detail,
              "outcome_entity_type": r.outcome_entity_type, "outcome_entity_id": r.outcome_entity_id,
              "raw_sha256": r.raw_sha256} for r in rows]
    if format == "csv":
        import csv
        import io
        import json as _json

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["file", "row_no", "source_record_key", "state", "stage", "error_code", "error_detail", "outcome_entity_id"])
        for it in items:
            w.writerow([it["file"], it["row_no"], it["source_record_key"], it["state"], it["stage"], it["error_code"],
                        _json.dumps(it["error_detail"], ensure_ascii=False) if it["error_detail"] else "", it["outcome_entity_id"]])
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="import-{bid}.csv"'})
    return {"items": items}


@router.post("/imports/{bid}/retry-failed", status_code=202)
def import_retry(bid: str, s: Session = Depends(db), user: User = Depends(current_user)):
    b = s.get(ImportBatch, bid)
    if b is None:
        raise ApiError("NOT_FOUND", "batch not found")
    ingestion.retry_failed(s, b, user)
    return _batch_out(b)


# ─────────────────────────── duplicates ───────────────────────────
@router.get("/duplicates")
def duplicates(status: str = "pending", s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "reviewer", "source_manager")
    cands = s.scalars(select(DuplicateCandidate).where(DuplicateCandidate.status == status)
                      .order_by(DuplicateCandidate.score.desc(), DuplicateCandidate.created_at)).all()
    out = []
    for c in cands:
        srr = s.get(SourceRecordRevision, c.left_source_record_revision_id)
        sr = s.get(SourceRecord, srr.source_record_id)
        right = s.get(Problem, c.right_problem_id)
        right_rev = s.scalar(select(ProblemRevision).where(ProblemRevision.problem_id == right.id)
                             .order_by(ProblemRevision.revision_no.desc()).limit(1))
        out.append({"id": c.id, "level": c.level, "score": float(c.score), "signals": c.signals, "status": c.status,
                    "left": {"source": s.get(Source, sr.source_id).code, "external_id": sr.external_id,
                             "external_revision": srr.external_revision, "title": (srr.normalized_payload or {}).get("revision", {}).get("title"),
                             "document": srr.normalized_payload},
                    "right": {"problem_id": right.id, "display_id": right.display_id, "title": right_rev.title if right_rev else None,
                              "document": catalog.revision_to_doc(s, right_rev) if right_rev else None},
                    "decision": c.decision, "decision_reason": c.decision_reason})
    return {"items": out}


class ResolveIn(BaseModel):
    decision: str
    reason: str = Field(min_length=1)


@router.post("/duplicates/{cid}/resolve")
def resolve_dup(cid: str, body: ResolveIn, s: Session = Depends(db), user: User = Depends(current_user)):
    c = s.get(DuplicateCandidate, cid)
    if c is None:
        raise ApiError("NOT_FOUND", "candidate not found")
    ingestion.resolve_duplicate(s, c, user, body.decision, body.reason)
    return {"id": c.id, "status": c.status, "decision": c.decision}


# ─────────────────────────── grading queue ───────────────────────────
@router.get("/grading-queue")
def grading_queue(s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "reviewer")
    out = []
    for sub, ev in learning.manual_queue(s):
        part = s.get(RevisionPart, sub.revision_part_id)
        rev = s.get(ProblemRevision, part.problem_revision_id)
        spec = part.answer_specs[-1]
        out.append({"submission_id": sub.id, "evaluation_id": ev.id, "result_code": ev.result_code,
                    "created_at": sub.created_at.isoformat(), "response": sub.response,
                    "problem": {"title": rev.title, "revision_no": rev.revision_no, "part_key": part.part_key,
                                "prompt": part.prompt, "max_score": dec(part.max_score), "rubric": spec.rubric,
                                "expected": spec.spec.get("expected_latex") or spec.spec.get("expected"),
                                "solutions": [so.content for so in part.solutions]},
                    "own_submission": sub.user_id == user.id})
    return {"items": out}


class GradeIn(BaseModel):
    state: str
    score: str | None = None
    reason: str = Field(min_length=1)
    matched_criteria: list[str] = []


@router.post("/submissions/{sid}/evaluations", status_code=201)
def manual_grade(sid: str, body: GradeIn, s: Session = Depends(db), user: User = Depends(current_user)):
    sub = s.get(Submission, sid)
    if sub is None:
        raise ApiError("NOT_FOUND", "submission not found")
    if sub.user_id == user.id:
        raise ApiError("SELF_APPROVAL_FORBIDDEN", "cannot grade your own submission")
    ev = learning.append_evaluation(s, user, sub, body.state, Decimal(body.score) if body.score is not None else None,
                                    body.reason, body.matched_criteria)
    return {"evaluation_id": ev.id, "status": ev.state, "score": dec(ev.score), "previous_evaluation_id": ev.previous_evaluation_id}


class RegradeIn(BaseModel):
    reason: str = Field(min_length=1)
    submission_ids: list[str] | None = None
    revision_part_id: str | None = None


@router.post("/regrade-jobs", status_code=202)
def regrade_job(body: RegradeIn, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "reviewer")
    ids = list(body.submission_ids or [])
    if body.revision_part_id:
        ids += s.scalars(select(Submission.id).where(Submission.revision_part_id == body.revision_part_id)).all()
    results = []
    for sid in dict.fromkeys(ids):
        sub = s.get(Submission, sid)
        if sub:
            ev = learning.regrade_submission(s, user, sub, body.reason)
            results.append({"submission_id": sid, "evaluation_id": ev.id, "status": ev.state})
    return {"job": {"status": "completed", "count": len(results)}, "results": results}


# ─────────────────────────── reports ───────────────────────────
@router.get("/content-reports")
def admin_reports(state: str | None = "open", s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "reviewer", "rights_reviewer")
    stmt = select(ContentReport)
    if state:
        stmt = stmt.where(ContentReport.state == state)
    rs = s.scalars(stmt.order_by(ContentReport.severity, ContentReport.created_at)).all()
    return {"items": [{"id": r.id, "kind": r.kind, "severity": r.severity, "state": r.state, "description": r.description,
                       "problem_revision_id": r.problem_revision_id, "revision_part_id": r.revision_part_id,
                       "evaluation_id": r.evaluation_id, "created_at": r.created_at.isoformat()} for r in rs]}


class ResolveReportIn(BaseModel):
    state: str
    resolution: str
    public_note: str | None = None
    internal_note: str | None = None


@router.post("/content-reports/{rid}/resolve")
def resolve_report(rid: str, body: ResolveReportIn, s: Session = Depends(db), user: User = Depends(current_user)):
    r = s.get(ContentReport, rid)
    if r is None:
        raise ApiError("NOT_FOUND", "report not found")
    learning.resolve_report(s, user, r, body.state, body.resolution, body.public_note, body.internal_note)
    return {"id": r.id, "state": r.state}


# ─────────────────────────── collections ───────────────────────────
class CollectionIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str
    description: str = ""
    kind: str = "official"
    visibility: str = "public"
    problem_ids: list[str]


@router.post("/collections", status_code=201)
def create_collection(body: CollectionIn, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "editor")
    if s.scalar(select(Collection).where(Collection.slug == body.slug)):
        raise ApiError("CONFLICT", "slug exists")
    c = Collection(owner_id=user.id, slug=body.slug, title=body.title, description=body.description, kind=body.kind,
                   visibility=body.visibility)
    s.add(c)
    s.flush()
    for i, pid in enumerate(dict.fromkeys(body.problem_ids), start=1):
        if s.get(Problem, pid) is None:
            raise ApiError("VALIDATION_FAILED", f"unknown problem {pid}")
        s.add(CollectionItem(collection_id=c.id, problem_id=pid, ordinal=i))
    audit(s, user.id, "collection.create", "collection", c.id)
    return {"id": c.id, "slug": c.slug}


# ─────────────────────────── audit, users, dashboard ───────────────────────────
@router.get("/audit-events")
def audit_events(entity_type: str | None = None, entity_id: str | None = None, limit: int = Query(100, ge=1, le=500),
                 s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "auditor")
    stmt = select(AuditEvent)
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    evs = s.scalars(stmt.order_by(AuditEvent.created_at.desc()).limit(limit)).all()
    return {"items": [{"id": e.id, "actor_id": e.actor_id, "action": e.action, "entity_type": e.entity_type,
                       "entity_id": e.entity_id, "before_hash": e.before_hash, "after_hash": e.after_hash,
                       "meta": e.meta, "request_id": e.request_id, "created_at": e.created_at.isoformat()} for e in evs]}


@router.get("/users")
def users(s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "admin")
    return {"items": [user_out(u) for u in s.scalars(select(User).order_by(User.username))]}


class RolesIn(BaseModel):
    roles: list[str]


@router.post("/users/{uid}/roles")
def set_roles(uid: str, body: RolesIn, s: Session = Depends(db), user: User = Depends(current_user)):
    require_roles(user, "admin")
    from ..models import ROLES

    if not set(body.roles) <= set(ROLES):
        raise ApiError("VALIDATION_FAILED", f"roles must be within {ROLES}")
    u = s.get(User, uid)
    if u is None:
        raise ApiError("NOT_FOUND", "user not found")
    u.roles = "," + ",".join(sorted(set(body.roles))) + ","
    audit(s, user.id, "user.roles", "user", u.id, roles=sorted(set(body.roles)))
    return user_out(u)


@router.get("/dashboard")
def dashboard(s: Session = Depends(db), user: User = Depends(current_user)):
    """Aggregates only — no per-student data (docs/08 §7)."""
    require_roles(user, *STAFF)
    by_status = dict(s.execute(select(ProblemRevision.status, func.count()).group_by(ProblemRevision.status)).all())
    eval_states = dict(s.execute(select(Evaluation.state, func.count()).group_by(Evaluation.state)).all())
    rows = dict(s.execute(select(ImportRow.state, func.count()).group_by(ImportRow.state)).all())
    from datetime import timedelta

    soon = utcnow() + timedelta(days=30)
    expiring = s.scalars(select(RightsGrant).where(RightsGrant.status == "active", RightsGrant.valid_to.is_not(None),
                                                   RightsGrant.valid_to <= soon)).all()
    return {
        "revisions_by_status": by_status,
        "pending_math_review": by_status.get("in_math_review", 0),
        "pending_rights_review": by_status.get("in_rights_review", 0),
        "duplicate_backlog": s.scalar(select(func.count()).select_from(DuplicateCandidate).where(DuplicateCandidate.status == "pending")),
        "open_reports_by_severity": dict(s.execute(select(ContentReport.severity, func.count()).where(ContentReport.state == "open")
                                                   .group_by(ContentReport.severity)).all()),
        "evaluations_by_state": eval_states,
        "pending_manual_grading": eval_states.get("pending_review", 0),
        "import_rows_by_state": rows,
        "rights_expiring_30d": [_grant_out(g) for g in expiring],
        "held_problems": s.scalar(select(func.count()).select_from(Problem).where(Problem.takedown_hold.is_(True))),
    }
