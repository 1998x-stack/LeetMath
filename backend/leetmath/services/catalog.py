"""Problem identity, revisions, workflow & publishing (docs/01 UC-01, docs/03, docs/04 §3, docs/08 §3).

Invariants enforced here (and by the before_flush guard below):
* Published/archived/retracted revisions are content-immutable; edits create a new draft revision.
* logical_part_id is stable across revisions; revision_part_id is per revision.
* Publishing requires: approved status, two distinct gates (math + rights), no self-approval,
  zero blocking preflight issues, and a rights grant valid *now* for `display`.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..content.contract import content_hash, preflight
from ..content.richtext import to_plain_text
from ..models import (
    AnswerSpec,
    CurriculumRelease,
    CurriculumSystem,
    KnowledgeNode,
    LogicalPart,
    Problem,
    ProblemRevision,
    ReasoningStep,
    RevisionKnowledge,
    RevisionPart,
    RightsGrant,
    SearchDocument,
    SlugAlias,
    Solution,
    Source,
    SourceRecord,
    User,
    WorkflowEvent,
    utcnow,
)
from .audit import audit, outbox
from .errors import ApiError
from .rights import grant_allows, grant_by_ref

FROZEN = {"published", "archived", "retracted"}
# Columns that may still change on a frozen revision (status transitions + bookkeeping only).
_MUTABLE_ON_FROZEN = {
    ProblemRevision: {"status", "retracted_at", "updated_at", "review_note", "published_at", "lock_version"},
    RevisionPart: {"grading_suspended"},
}


@event.listens_for(Session, "before_flush")
def _immutability_guard(session: Session, _ctx, _instances):  # pragma: no cover - exercised via tests
    from sqlalchemy import inspect as sa_inspect

    for obj in list(session.dirty) + list(session.deleted):
        rev: ProblemRevision | None = None
        if isinstance(obj, ProblemRevision):
            rev = obj
            hist_status = sa_inspect(obj).attrs.status.history
            old_status = hist_status.deleted[0] if hist_status.deleted else obj.status
            if old_status not in FROZEN:
                continue
        elif isinstance(obj, (RevisionPart, AnswerSpec, Solution, ReasoningStep)):
            part_rev_id = getattr(obj, "problem_revision_id", None)
            if part_rev_id is None:
                part = obj if isinstance(obj, RevisionPart) else session.get(RevisionPart, obj.revision_part_id)
                part_rev_id = part.problem_revision_id if part else None
            rev = session.get(ProblemRevision, part_rev_id) if part_rev_id else None
            if rev is None or rev.status not in FROZEN:
                continue
        else:
            continue
        if obj in session.deleted:
            raise ApiError("INVALID_STATE", "published content cannot be deleted; retract instead")
        allowed = _MUTABLE_ON_FROZEN.get(type(obj), set())
        state = sa_inspect(obj)
        changed = {a.key for a in state.attrs if a.history.has_changes()} - allowed
        changed -= {"parts", "answer_specs", "solutions", "revision"}  # relationship bookkeeping
        if changed:
            raise ApiError("INVALID_STATE", f"revision is {rev.status}; content is immutable (changed: {sorted(changed)})")


# ─────────────────────────── helpers ───────────────────────────
def _region_prefix(doc: dict) -> str:
    for r in doc["revision"]["content_metadata"].get("region_hints", []):
        m = re.match(r"^[A-Z]{2}-([A-Z]{2,4})$", r)
        if m:
            return m.group(1)
    return "GEN"


def _next_display_id(s: Session, prefix: str) -> str:
    like = f"LM-{prefix}-%"
    rows = s.scalars(select(Problem.display_id).where(Problem.display_id.like(like))).all()
    n = max((int(r.rsplit("-", 1)[1]) for r in rows), default=0) + 1
    return f"LM-{prefix}-{n:06d}"


def _slug_taken(s: Session, slug: str, problem_id: str | None = None) -> bool:
    p = s.scalar(select(Problem).where(Problem.slug == slug))
    if p and p.id != problem_id:
        return True
    a = s.get(SlugAlias, slug)
    return bool(a and a.problem_id != problem_id)


def _knowledge_node(s: Session, system_code: str, release_code: str, code: str) -> KnowledgeNode | None:
    return s.scalar(
        select(KnowledgeNode)
        .join(CurriculumRelease, KnowledgeNode.release_id == CurriculumRelease.id)
        .join(CurriculumSystem, CurriculumRelease.system_id == CurriculumSystem.id)
        .where(CurriculumSystem.code == system_code, CurriculumRelease.release_code == release_code,
               KnowledgeNode.external_code == code)
    )


def _record_workflow(s: Session, rev: ProblemRevision, to: str, actor: User, reason: str | None = None) -> None:
    s.add(WorkflowEvent(revision_id=rev.id, from_status=rev.status, to_status=to, actor_id=actor.id, reason=reason))
    audit(s, actor.id, f"revision.{to}", "problem_revision", rev.id, meta_from=rev.status, reason=reason)
    rev.status = to
    rev.updated_at = utcnow()


def require_roles(user: User | None, *roles: str) -> User:
    if user is None:
        raise ApiError("AUTH_REQUIRED", "login required")
    if not (user.role_set & (set(roles) | {"admin"})):
        raise ApiError("FORBIDDEN", f"requires role: {' / '.join(roles)}")
    return user


# ─────────────────────────── doc → DB ───────────────────────────
def _write_parts(s: Session, problem: Problem, rev: ProblemRevision, doc: dict, prev: ProblemRevision | None) -> None:
    prev_by_key: dict[str, str] = {}
    if prev is not None:
        prev_by_key = {p.part_key: p.logical_part_id for p in prev.parts}
    existing_logical = {lp.id for lp in s.scalars(select(LogicalPart).where(LogicalPart.problem_id == problem.id))}
    for pd in sorted(doc["revision"]["parts"], key=lambda p: p["display_order"]):
        lid = pd.get("logical_part_id")
        if lid and lid not in existing_logical:
            if s.get(LogicalPart, lid) is not None:  # belongs to another problem → never reuse
                lid = None
            else:
                s.add(LogicalPart(id=lid, problem_id=problem.id, stable_label=pd["part_key"]))
                existing_logical.add(lid)
        if not lid:
            lid = prev_by_key.get(pd["part_key"])
        if not lid:
            lp = LogicalPart(problem_id=problem.id, stable_label=pd["part_key"])
            s.add(lp)
            s.flush()
            lid = lp.id
            existing_logical.add(lid)
        part = RevisionPart(
            problem_revision_id=rev.id,
            logical_part_id=lid,
            part_key=pd["part_key"],
            display_order=pd["display_order"],
            prompt=pd["prompt"],
            response_type=pd["response_type"],
            max_score=Decimal(pd["max_score"]),
            options=pd.get("options"),
            knowledge_codes=pd.get("knowledge_codes")
            or [m["knowledge_code"] for m in doc["revision"]["content_metadata"].get("curriculum_mappings", [])
                if m.get("relation_type", "tested") == "tested"],
        )
        if pd.get("id") and s.get(RevisionPart, pd["id"]) is None:
            part.id = pd["id"]
        rev.parts.append(part)
        s.flush()
        spec = dict(pd["answer_spec"])
        rubric = pd.get("rubric")
        part.answer_specs.append(
            AnswerSpec(
                spec_version=spec.pop("spec_version", 1),
                grading_mode=spec.pop("grading_mode"),
                checker_type=spec.pop("checker_type"),
                spec=spec,
                rubric=rubric,
                rubric_sum=sum(Decimal(c["max_points"]) for c in rubric["criteria"]) if rubric else None,
            )
        )
        for sol in pd.get("solutions") or []:
            part.solutions.append(
                Solution(solution_type=sol["type"], content={"steps": sol["steps"]},
                         validation_state=sol.get("review_state", "unreviewed"))
            )
        for st in pd.get("reasoning_steps") or []:
            s.add(ReasoningStep(
                revision_part_id=part.id, semantic_key=st["semantic_key"], step_order=st["order"],
                recall_cue=st["recall_cue"], reference_latex=st["reference_latex"],
                explanation=st.get("explanation", ""), max_points=Decimal(st["max_points"]),
                criticality=st.get("criticality", "normal"), knowledge_codes=st.get("knowledge_codes", []),
            ))


def _write_revision_body(s: Session, problem: Problem, rev: ProblemRevision, doc: dict, prev: ProblemRevision | None):
    r = doc["revision"]
    md = r["content_metadata"]
    rev.title = r["title"]
    rev.locale = r["locale"]
    rev.shared_statement = r["shared_statement"]
    rev.content_metadata = md
    rev.platform_difficulty = (md.get("platform_difficulty") or {}).get("value")
    rev.revision_kind = r.get("revision_kind", "initial" if prev is None else "semantic")
    rev.change_note = r.get("change_note")
    rev.content_metadata = {**md, "_source_record_refs": doc["source_record_refs"],
                            "_rights_policy_ref": doc["rights_policy_ref"], "_assets": doc.get("assets", []),
                            "_lineage": doc.get("lineage", [])}
    grant = grant_by_ref(s, doc["rights_policy_ref"])
    rev.rights_grant_id = grant.id if grant else None
    rev.content_hash = content_hash(doc)
    s.flush()
    _write_parts(s, problem, rev, doc, prev)
    for m in md.get("curriculum_mappings", []):
        node = _knowledge_node(s, m["curriculum_code"], m["release_code"], m["knowledge_code"])
        if node and not s.get(RevisionKnowledge, (rev.id, node.id, m.get("relation_type", "tested"))):
            s.add(RevisionKnowledge(revision_id=rev.id, knowledge_node_id=node.id,
                                    relation_type=m.get("relation_type", "tested"),
                                    weight=Decimal(str(m.get("weight", 1)))))


def create_problem(s: Session, doc: dict, actor: User, visibility: str | None = None) -> ProblemRevision:
    pd = doc["problem"]
    display_id = pd.get("display_id")
    if display_id and s.scalar(select(Problem).where(Problem.display_id == display_id)):
        display_id = None
    display_id = display_id or _next_display_id(s, _region_prefix(doc))
    slug = pd.get("slug")
    if not slug or _slug_taken(s, slug):
        slug = display_id.lower()
    problem = Problem(display_id=display_id, slug=slug, grade_band=pd["grade_band"],
                      subject=pd.get("subject", "mathematics"),
                      visibility=visibility or pd.get("visibility", "public"), created_by=actor.id)
    if pd.get("id") and s.get(Problem, pd["id"]) is None:
        problem.id = pd["id"]
    s.add(problem)
    s.flush()
    rev = ProblemRevision(problem_id=problem.id, revision_no=1, status="draft", title="", shared_statement={},
                          created_by=actor.id)
    if doc["revision"].get("id") and s.get(ProblemRevision, doc["revision"]["id"]) is None:
        rev.id = doc["revision"]["id"]
    s.add(rev)
    _write_revision_body(s, problem, rev, doc, None)
    audit(s, actor.id, "problem.create", "problem", problem.id, after={"display_id": display_id})
    return rev


def update_draft(s: Session, rev: ProblemRevision, doc: dict, actor: User, if_match: int | None) -> ProblemRevision:
    if rev.status != "draft":
        raise ApiError("INVALID_STATE", f"only drafts are editable (status={rev.status}); create a new revision")
    if if_match is None:
        raise ApiError("VALIDATION_FAILED", "If-Match header with lock_version is required", status=428)
    if int(if_match) != rev.lock_version:
        raise ApiError("EDIT_CONFLICT", "draft was modified by someone else",
                       {"current_lock_version": rev.lock_version, "updated_at": rev.updated_at.isoformat()})
    before = rev.content_hash
    problem = s.get(Problem, rev.problem_id)
    for part in list(rev.parts):
        for st in s.scalars(select(ReasoningStep).where(ReasoningStep.revision_part_id == part.id)):
            s.delete(st)
    s.execute(RevisionKnowledge.__table__.delete().where(RevisionKnowledge.revision_id == rev.id))
    rev.parts.clear()
    s.flush()
    prev = _previous_revision(s, rev)
    _write_revision_body(s, problem, rev, doc, prev)
    rev.lock_version += 1
    rev.updated_at = utcnow()
    audit(s, actor.id, "revision.edit", "problem_revision", rev.id, before=before, after=rev.content_hash)
    return rev


def _previous_revision(s: Session, rev: ProblemRevision) -> ProblemRevision | None:
    return s.scalar(select(ProblemRevision).where(ProblemRevision.problem_id == rev.problem_id,
                                                  ProblemRevision.revision_no < rev.revision_no)
                    .order_by(ProblemRevision.revision_no.desc()).limit(1))


def new_revision(s: Session, problem: Problem, actor: User, doc: dict | None = None) -> ProblemRevision:
    open_draft = s.scalar(select(ProblemRevision).where(ProblemRevision.problem_id == problem.id,
                                                        ProblemRevision.status.in_(("draft", "in_math_review", "in_rights_review", "approved"))))
    if open_draft:
        raise ApiError("INVALID_STATE", "an unpublished revision already exists", {"revision_id": open_draft.id})
    latest = s.scalar(select(ProblemRevision).where(ProblemRevision.problem_id == problem.id)
                      .order_by(ProblemRevision.revision_no.desc()).limit(1))
    base_doc = doc or revision_to_doc(s, latest)
    base_doc["revision"].pop("id", None)
    for p in base_doc["revision"]["parts"]:
        p.pop("id", None)
    rev = ProblemRevision(problem_id=problem.id, revision_no=latest.revision_no + 1, status="draft", title="",
                          shared_statement={}, created_by=actor.id)
    s.add(rev)
    _write_revision_body(s, problem, rev, base_doc, latest)
    audit(s, actor.id, "revision.create", "problem_revision", rev.id, base_revision=latest.id)
    return rev


# ─────────────────────────── DB → doc ───────────────────────────
def revision_to_doc(s: Session, rev: ProblemRevision) -> dict:
    problem = s.get(Problem, rev.problem_id)
    md = dict(rev.content_metadata or {})
    refs = md.pop("_source_record_refs", [])
    rights_ref = md.pop("_rights_policy_ref", None)
    assets = md.pop("_assets", [])
    lineage = md.pop("_lineage", [])
    parts = []
    for p in rev.parts:
        spec = p.answer_specs[-1]
        pd = {
            "id": p.id, "logical_part_id": p.logical_part_id, "part_key": p.part_key,
            "display_order": p.display_order, "response_type": p.response_type,
            "max_score": str(Decimal(p.max_score).quantize(Decimal("0.01"))), "prompt": p.prompt,
            "answer_spec": {"spec_version": spec.spec_version, "grading_mode": spec.grading_mode,
                            "checker_type": spec.checker_type, **spec.spec},
            "solutions": [{"type": so.solution_type, "review_state": so.validation_state, **so.content} for so in p.solutions],
        }
        if p.options:
            pd["options"] = p.options
        if p.knowledge_codes:
            pd["knowledge_codes"] = p.knowledge_codes
        if spec.rubric:
            pd["rubric"] = spec.rubric
        steps = s.scalars(select(ReasoningStep).where(ReasoningStep.revision_part_id == p.id)
                          .order_by(ReasoningStep.step_order)).all()
        if steps:
            pd["reasoning_steps"] = [
                {"semantic_key": st.semantic_key, "order": st.step_order, "recall_cue": st.recall_cue,
                 "reference_latex": st.reference_latex, "explanation": st.explanation,
                 "max_points": str(Decimal(st.max_points).quantize(Decimal("0.01"))),
                 "criticality": st.criticality, "knowledge_codes": st.knowledge_codes} for st in steps]
        parts.append(pd)
    doc = {
        "schema_version": "1.0.0",
        "problem": {"id": problem.id, "display_id": problem.display_id, "slug": problem.slug,
                    "grade_band": problem.grade_band, "subject": problem.subject, "visibility": problem.visibility},
        "revision": {"id": rev.id, "revision_no": rev.revision_no, "status": rev.status, "locale": rev.locale,
                     "title": rev.title, "shared_statement": rev.shared_statement, "content_metadata": md,
                     "revision_kind": rev.revision_kind, "parts": parts},
        "source_record_refs": refs,
        "rights_policy_ref": rights_ref or "",
        "assets": assets,
        "lineage": lineage,
    }
    if rev.change_note:
        doc["revision"]["change_note"] = rev.change_note
    return doc


# ─────────────────────────── preflight with DB context ───────────────────────────
def full_preflight(s: Session, rev: ProblemRevision) -> list[dict]:
    doc = revision_to_doc(s, rev)
    issues = preflight(doc)
    grant = s.get(RightsGrant, rev.rights_grant_id) if rev.rights_grant_id else None
    if grant is None:
        issues.append({"code": "RIGHTS_MISSING", "severity": "blocking", "path": "/rights_policy_ref",
                       "message": "no rights grant registered for this revision"})
    elif grant.status == "revoked":
        issues.append({"code": "RIGHTS_REVOKED", "severity": "blocking", "path": "/rights_policy_ref",
                       "message": "rights grant revoked"})
    for m in doc["revision"]["content_metadata"].get("curriculum_mappings", []):
        if _knowledge_node(s, m["curriculum_code"], m["release_code"], m["knowledge_code"]) is None:
            issues.append({"code": "KNOWLEDGE_UNKNOWN", "severity": "warning", "path": "/revision/content_metadata",
                           "message": f"unknown knowledge node {m['knowledge_code']}"})
    for ref in doc["source_record_refs"]:
        src = s.scalar(select(Source).where(Source.code == ref["source_code"]))
        if src is None:
            issues.append({"code": "SOURCE_UNKNOWN", "severity": "blocking", "path": "/source_record_refs",
                           "message": f"source {ref['source_code']} not registered"})
        elif src.status != "active":
            issues.append({"code": "SOURCE_DISABLED", "severity": "blocking", "path": "/source_record_refs",
                           "message": f"source {ref['source_code']} disabled"})
    return issues


def _blocking(issues: list[dict]) -> list[dict]:
    return [i for i in issues if i["severity"] == "blocking"]


# ─────────────────────────── workflow transitions ───────────────────────────
def submit_review(s: Session, rev: ProblemRevision, actor: User, note: str | None = None) -> list[dict]:
    require_roles(actor, "editor", "source_manager")
    if rev.status != "draft":
        raise ApiError("INVALID_STATE", f"cannot submit from {rev.status}")
    issues = full_preflight(s, rev)
    if _blocking(issues):
        audit(s, actor.id, "revision.preflight_failed", "problem_revision", rev.id, issues=len(issues))
        raise ApiError("PREFLIGHT_FAILED", "blocking issues must be fixed before review", {"issues": issues})
    warnings = [i for i in issues if i["severity"] == "warning"]
    _record_workflow(s, rev, "in_math_review", actor, note or (f"{len(warnings)} warning(s)" if warnings else None))
    return issues


def approve_math(s: Session, rev: ProblemRevision, actor: User, note: str | None = None) -> None:
    require_roles(actor, "reviewer")
    if rev.status != "in_math_review":
        raise ApiError("INVALID_STATE", f"not in math review (status={rev.status})")
    if actor.id == rev.created_by:
        raise ApiError("SELF_APPROVAL_FORBIDDEN", "reviewers cannot approve their own content")
    rev.math_reviewer_id = actor.id
    rev.review_note = note
    _record_workflow(s, rev, "in_rights_review", actor, note)


def approve_rights(s: Session, rev: ProblemRevision, actor: User, note: str | None = None) -> None:
    require_roles(actor, "rights_reviewer")
    if rev.status != "in_rights_review":
        raise ApiError("INVALID_STATE", f"not in rights review (status={rev.status})")
    if actor.id == rev.created_by:
        raise ApiError("SELF_APPROVAL_FORBIDDEN", "reviewers cannot approve their own content")
    if settings.require_distinct_reviewers and actor.id == rev.math_reviewer_id:
        raise ApiError("SELF_APPROVAL_FORBIDDEN", "math and rights gates need two different reviewers")
    grant = s.get(RightsGrant, rev.rights_grant_id) if rev.rights_grant_id else None
    ok, why = grant_allows(grant, "display")
    if not ok:
        raise ApiError("RIGHTS_HOLD", f"rights gate failed: {why}")
    rev.rights_reviewer_id = actor.id
    _record_workflow(s, rev, "approved", actor, note)


def reject(s: Session, rev: ProblemRevision, actor: User, reason: str) -> None:
    require_roles(actor, "reviewer", "rights_reviewer")
    if rev.status not in ("in_math_review", "in_rights_review", "approved"):
        raise ApiError("INVALID_STATE", f"cannot reject from {rev.status}")
    if not reason or not reason.strip():
        raise ApiError("VALIDATION_FAILED", "a rejection reason is required")
    rev.math_reviewer_id = None
    rev.rights_reviewer_id = None
    rev.review_note = reason
    _record_workflow(s, rev, "draft", actor, f"changes requested: {reason}")


def publish(s: Session, rev: ProblemRevision, actor: User) -> ProblemRevision:
    require_roles(actor, "reviewer")
    if rev.status != "approved":
        raise ApiError("INVALID_STATE", f"only approved revisions can be published (status={rev.status})")
    if not (rev.math_reviewer_id and rev.rights_reviewer_id):
        raise ApiError("INVALID_STATE", "both math and rights gates must be passed")
    issues = _blocking(full_preflight(s, rev))
    if issues:
        raise ApiError("PREFLIGHT_FAILED", "blocking issues", {"issues": issues})
    grant = s.get(RightsGrant, rev.rights_grant_id)
    ok, why = grant_allows(grant, "display")
    if not ok:
        raise ApiError("RIGHTS_HOLD", f"rights gate failed: {why}")
    problem = s.get(Problem, rev.problem_id)
    previous = s.get(ProblemRevision, problem.current_public_revision_id) if problem.current_public_revision_id else None
    rev.content_hash = content_hash(revision_to_doc(s, rev))
    rev.published_at = utcnow()
    _record_workflow(s, rev, "published", actor)
    if previous is not None and previous.id != rev.id and previous.status == "published":
        _record_workflow(s, previous, "archived", actor, f"superseded by revision {rev.revision_no}")
    problem.current_public_revision_id = rev.id
    s.flush()
    rebuild_search_document(s, problem)
    outbox(s, "problem.published", problem_id=problem.id, revision_id=rev.id)
    return rev


def retract(s: Session, rev: ProblemRevision, actor: User, reason: str) -> None:
    require_roles(actor, "reviewer", "rights_reviewer")
    if rev.status != "published":
        raise ApiError("INVALID_STATE", f"only published revisions can be retracted (status={rev.status})")
    if not reason:
        raise ApiError("VALIDATION_FAILED", "a retraction reason is required")
    problem = s.get(Problem, rev.problem_id)
    rev.retracted_at = utcnow()
    _record_workflow(s, rev, "retracted", actor, reason)
    if problem.current_public_revision_id == rev.id:
        problem.current_public_revision_id = None
    s.flush()
    rebuild_search_document(s, problem)
    outbox(s, "problem.retracted", problem_id=problem.id, revision_id=rev.id)


def set_takedown_hold(s: Session, problem: Problem, actor: User, hold: bool, reason: str) -> None:
    require_roles(actor, "rights_reviewer")
    problem.takedown_hold = hold
    problem.takedown_reason = reason if hold else None
    audit(s, actor.id, "problem.rights_hold" if hold else "problem.rights_release", "problem", problem.id, reason=reason)
    s.flush()
    rebuild_search_document(s, problem)


def set_grading_suspended(s: Session, part: RevisionPart, actor: User, suspended: bool, reason: str) -> None:
    require_roles(actor, "reviewer")
    part.grading_suspended = suspended
    audit(s, actor.id, "part.grading_suspended" if suspended else "part.grading_resumed", "revision_part", part.id, reason=reason)


# ─────────────────────────── public visibility ───────────────────────────
def public_revision(s: Session, problem: Problem | None) -> ProblemRevision | None:
    """The single gate every public read goes through (AC-005)."""
    if problem is None or problem.deleted_at or problem.visibility != "public" or problem.takedown_hold:
        return None
    if not problem.current_public_revision_id:
        return None
    rev = s.get(ProblemRevision, problem.current_public_revision_id)
    if rev is None or rev.status != "published":
        return None
    grant = s.get(RightsGrant, rev.rights_grant_id) if rev.rights_grant_id else None
    ok, _ = grant_allows(grant, "display")
    return rev if ok else None


def find_problem_by_slug(s: Session, slug: str) -> Problem | None:
    p = s.scalar(select(Problem).where(Problem.slug == slug))
    if p is None:
        alias = s.get(SlugAlias, slug)
        p = s.get(Problem, alias.problem_id) if alias else None
    if p is None:
        p = s.scalar(select(Problem).where(Problem.display_id == slug.upper()))
    return p


def rename_slug(s: Session, problem: Problem, new_slug: str, actor: User) -> None:
    require_roles(actor, "editor")
    if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", new_slug):
        raise ApiError("VALIDATION_FAILED", "invalid slug")
    if _slug_taken(s, new_slug, problem.id):
        raise ApiError("CONFLICT", "slug already used (slugs are never re-used)")
    if s.get(SlugAlias, problem.slug) is None:
        s.add(SlugAlias(slug=problem.slug, problem_id=problem.id))
    problem.slug = new_slug
    audit(s, actor.id, "problem.rename_slug", "problem", problem.id, slug=new_slug)
    s.flush()
    rebuild_search_document(s, problem)


# ─────────────────────────── search read-model ───────────────────────────
def rebuild_search_document(s: Session, problem: Problem) -> None:
    existing = s.get(SearchDocument, problem.id)
    rev = s.get(ProblemRevision, problem.current_public_revision_id) if problem.current_public_revision_id else None
    if rev is None or rev.status != "published" or problem.takedown_hold or problem.visibility != "public":
        if existing:
            s.delete(existing)
        return
    nodes = s.execute(
        select(KnowledgeNode.id, KnowledgeNode.title, KnowledgeNode.external_code)
        .join(RevisionKnowledge, RevisionKnowledge.knowledge_node_id == KnowledgeNode.id)
        .where(RevisionKnowledge.revision_id == rev.id)
    ).all()
    # Include ancestors so filtering by a chapter node finds problems tagged with its children.
    ids = set()
    for nid, _t, _c in nodes:
        cur = s.get(KnowledgeNode, nid)
        while cur is not None:
            ids.add(cur.id)
            cur = s.get(KnowledgeNode, cur.parent_id) if cur.parent_id else None
    body = [to_plain_text(rev.shared_statement)] + [to_plain_text(p.prompt) for p in rev.parts]
    md = rev.content_metadata or {}
    src_kind = "internal"
    sr = s.scalar(select(SourceRecord).where(SourceRecord.canonical_problem_id == problem.id).limit(1))
    if sr:
        src = s.get(Source, sr.source_id)
        src_kind = src.kind if src else src_kind
    doc = existing or SearchDocument(problem_id=problem.id)
    doc.revision_id = rev.id
    doc.display_id = problem.display_id
    doc.slug = problem.slug
    doc.title = rev.title
    doc.body_text = " ".join(body)
    doc.knowledge_text = " ".join(f"{t} {c}" for _i, t, c in nodes)
    doc.knowledge_ids = "," + ",".join(sorted(ids)) + ","
    doc.grade_band = problem.grade_band
    doc.region_hints = "," + ",".join(md.get("region_hints", [])) + ","
    doc.response_types = "," + ",".join(sorted({p.response_type for p in rev.parts})) + ","
    doc.difficulty = rev.platform_difficulty or 0
    doc.part_count = len(rev.parts)
    doc.has_solution = all(p.solutions for p in rev.parts)
    doc.source_kind = src_kind
    doc.rights_grant_id = rev.rights_grant_id
    doc.updated_at = rev.published_at or utcnow()
    if existing is None:
        s.add(doc)


def problem_count(s: Session) -> int:
    return s.scalar(select(func.count()).select_from(Problem)) or 0


def now() -> datetime:
    return datetime.now(timezone.utc)
