"""ORM models — physical realisation of docs/04-data-model.md (+ reasoning-practice learning domain).

Portable across SQLite (dev/test) and PostgreSQL (prod). UUIDs are stored as 36-char strings.
Export PostgreSQL DDL with:  python -m leetmath.cli ddl --dialect postgresql
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


UUID = String(36)
TS = DateTime(timezone=True)
SCORE = Numeric(8, 2)

REVISION_STATUSES = (
    "draft",
    "in_math_review",
    "in_rights_review",
    "approved",
    "published",
    "archived",
    "retracted",
)
RESPONSE_TYPES = (
    "single_choice",
    "multiple_choice",
    "integer",
    "decimal",
    "rational",
    "expression",
    "equation_set",
    "interval",
    "set",
    "matrix",
    "vector",
    "short_text",
    "proof",
    "derivation",
    "drawing",
)
EVAL_STATUSES = (
    "queued",
    "running",
    "accepted",
    "rejected",
    "partial",
    "invalid_response",
    "pending_review",
    "engine_error",
    "cancelled",
)
ROLES = ("student", "editor", "reviewer", "rights_reviewer", "source_manager", "admin", "auditor")


# ───────────────────────────── identity ─────────────────────────────
class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # A user may hold several roles, stored as a sorted comma list (",editor,reviewer,").
    roles: Mapped[str] = mapped_column(String(256), nullable=False, default=",student,")
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    privacy_flags: Mapped[dict] = mapped_column(JSON, default=dict)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    @property
    def role_set(self) -> set[str]:
        return {r for r in self.roles.split(",") if r}


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    scope: Mapped[str] = mapped_column(String(160), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


# ───────────────────────────── A. sources & governance ─────────────────────────────
class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # internal/partner/open_license/document/teacher_private/legacy
    homepage: Mapped[str | None] = mapped_column(String(512))
    owner: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/disabled
    default_visibility: Mapped[str] = mapped_column(String(16), default="public")  # teacher_private → private
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class RightsGrant(Base):
    __tablename__ = "rights_grants"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    source_id: Mapped[str] = mapped_column(UUID, ForeignKey("sources.id"), nullable=False, index=True)
    grant_type: Mapped[str] = mapped_column(String(32), nullable=False)  # original/license/contract/open_license
    scope: Mapped[str] = mapped_column(String(256), default="")
    territory: Mapped[str] = mapped_column(String(64), default="WORLD")
    permitted_actions: Mapped[list] = mapped_column(JSON, default=list)  # display/reproduce/adapt/redistribute/export/commercial
    # Denormalised from permitted_actions so the public rights filter stays in SQL (exact pagination).
    allows_display: Mapped[bool] = mapped_column(Boolean, default=False)
    attribution_text: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[datetime | None] = mapped_column(TS)
    valid_to: Mapped[datetime | None] = mapped_column(TS)
    evidence_ref: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="active")  # pending/active/revoked
    reviewed_by: Mapped[str | None] = mapped_column(UUID, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class SourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(UUID, ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    latest_source_revision: Mapped[str | None] = mapped_column(String(128))
    canonical_problem_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("problems.id"))
    relation_to_problem: Mapped[str | None] = mapped_column(String(32))  # origin/exact_duplicate/adapted_from
    tombstoned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class SourceRecordRevision(Base):
    __tablename__ = "source_record_revisions"
    __table_args__ = (UniqueConstraint("source_record_id", "external_revision"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    source_record_id: Mapped[str] = mapped_column(UUID, ForeignKey("source_records.id"), nullable=False)
    external_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_payload: Mapped[dict | None] = mapped_column(JSON)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    batch_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("import_batches.id"))
    problem_revision_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("problem_revisions.id"))
    imported_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(UUID, ForeignKey("sources.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    importer_version: Mapped[str] = mapped_column(String(32), nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(24), default="created")  # created/running/completed/completed_with_errors/failed
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    initiated_by: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class ImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (UniqueConstraint("batch_id", "file_path", "row_no"), Index("ix_import_rows_batch_state", "batch_id", "state"))
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(UUID, ForeignKey("import_batches.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_record_key: Mapped[str | None] = mapped_column(String(256), index=True)
    raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # outcome: retained/new_record/new_revision/duplicate_candidate/rejected/quarantined/validated(dry-run)/failed
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(48))
    error_detail: Mapped[dict | None] = mapped_column(JSON)
    outcome_entity_type: Mapped[str | None] = mapped_column(String(48))
    outcome_entity_id: Mapped[str | None] = mapped_column(UUID)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"
    __table_args__ = (Index("ix_dup_status_score", "status", "score"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    left_source_record_revision_id: Mapped[str] = mapped_column(
        UUID, ForeignKey("source_record_revisions.id"), nullable=False, index=True
    )
    right_problem_id: Mapped[str] = mapped_column(UUID, ForeignKey("problems.id"), nullable=False)
    level: Mapped[str] = mapped_column(String(8), nullable=False)  # L1 exact / L2 near
    score: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="pending")  # pending/resolved/deferred
    decision: Mapped[str | None] = mapped_column(String(32))  # exact_duplicate/independent/isomorphic_to/adapted_from
    decision_reason: Mapped[str | None] = mapped_column(Text)
    reviewer_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(TS)


class ContentReport(Base):
    __tablename__ = "content_reports"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    reporter_id: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    problem_revision_id: Mapped[str] = mapped_column(UUID, ForeignKey("problem_revisions.id"), nullable=False)
    revision_part_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("revision_parts.id"))
    evaluation_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("evaluations.id"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # wrong_answer/ambiguous/missing_image/misjudged/rights/other
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(4), default="P2")
    state: Mapped[str] = mapped_column(String(16), default="open")  # open/triaged/resolved/rejected
    public_note: Mapped[str | None] = mapped_column(Text)
    internal_note: Mapped[str | None] = mapped_column(Text)
    reviewer_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("users.id"))
    resolution: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    """Append-only. No API updates or deletes these rows."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    actor_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_hash: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class WorkflowEvent(Base):
    __tablename__ = "content_workflow_events"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    revision_id: Mapped[str] = mapped_column(UUID, ForeignKey("problem_revisions.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(24), nullable=False)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(TS)


# ───────────────────────────── B. canonical problems ─────────────────────────────
class Problem(Base):
    __tablename__ = "problems"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    display_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    grade_band: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(32), nullable=False, default="mathematics")
    visibility: Mapped[str] = mapped_column(String(16), default="public")  # public/private
    current_public_revision_id: Mapped[str | None] = mapped_column(
        UUID, ForeignKey("problem_revisions.id", use_alter=True, name="fk_problem_current_rev")
    )
    takedown_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    takedown_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(UUID, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(TS)


class SlugAlias(Base):
    """Old slugs are never re-used (docs/01 §4.1)."""

    __tablename__ = "problem_slug_aliases"
    slug: Mapped[str] = mapped_column(String(160), primary_key=True)
    problem_id: Mapped[str] = mapped_column(UUID, ForeignKey("problems.id"), nullable=False)


class ProblemRevision(Base):
    __tablename__ = "problem_revisions"
    __table_args__ = (
        UniqueConstraint("problem_id", "revision_no"),
        CheckConstraint("revision_no > 0", name="ck_revision_no_pos"),
        CheckConstraint(
            "status IN ('draft','in_math_review','in_rights_review','approved','published','archived','retracted')",
            name="ck_revision_status",
        ),
        Index("ix_rev_status_pub", "status", "published_at"),
    )
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    problem_id: Mapped[str] = mapped_column(UUID, ForeignKey("problems.id"), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    shared_statement: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    platform_difficulty: Mapped[int | None] = mapped_column(Integer)
    revision_kind: Mapped[str] = mapped_column(String(24), default="initial")  # initial/semantic/presentation
    change_note: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    rights_grant_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("rights_grants.id"))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(UUID, ForeignKey("users.id"))
    math_reviewer_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("users.id"))
    rights_reviewer_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("users.id"))
    review_note: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(TS)
    retracted_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    parts: Mapped[list["RevisionPart"]] = relationship(
        back_populates="revision", order_by="RevisionPart.display_order", cascade="all, delete-orphan"
    )


class LogicalPart(Base):
    __tablename__ = "logical_parts"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    problem_id: Mapped[str] = mapped_column(UUID, ForeignKey("problems.id"), nullable=False, index=True)
    stable_label: Mapped[str | None] = mapped_column(String(64))


class RevisionPart(Base):
    __tablename__ = "revision_parts"
    __table_args__ = (
        UniqueConstraint("problem_revision_id", "logical_part_id"),
        UniqueConstraint("problem_revision_id", "display_order"),
        CheckConstraint("display_order > 0", name="ck_part_order_pos"),
        CheckConstraint("max_score > 0", name="ck_part_max_score_pos"),
    )
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    problem_revision_id: Mapped[str] = mapped_column(UUID, ForeignKey("problem_revisions.id"), nullable=False)
    logical_part_id: Mapped[str] = mapped_column(UUID, ForeignKey("logical_parts.id"), nullable=False)
    part_key: Mapped[str] = mapped_column(String(16), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[dict] = mapped_column(JSON, nullable=False)
    response_type: Mapped[str] = mapped_column(String(32), nullable=False)
    max_score: Mapped[Decimal] = mapped_column(SCORE, nullable=False)
    options: Mapped[list | None] = mapped_column(JSON)  # choice options [{id, content}]
    knowledge_codes: Mapped[list] = mapped_column(JSON, default=list)
    # Emergency switch (docs/01 UC-04): pause automatic grading without retracting.
    grading_suspended: Mapped[bool] = mapped_column(Boolean, default=False)

    revision: Mapped[ProblemRevision] = relationship(back_populates="parts")
    answer_specs: Mapped[list["AnswerSpec"]] = relationship(
        order_by="AnswerSpec.spec_version", cascade="all, delete-orphan"
    )
    solutions: Mapped[list["Solution"]] = relationship(cascade="all, delete-orphan")


class AnswerSpec(Base):
    __tablename__ = "answer_specs"
    __table_args__ = (UniqueConstraint("revision_part_id", "spec_version"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    revision_part_id: Mapped[str] = mapped_column(UUID, ForeignKey("revision_parts.id"), nullable=False)
    spec_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    grading_mode: Mapped[str] = mapped_column(String(16), nullable=False)  # automatic/manual/hybrid/practice_only
    checker_type: Mapped[str] = mapped_column(String(48), nullable=False)
    spec: Mapped[dict] = mapped_column(JSON, nullable=False)  # expected answer + checker config (hidden)
    rubric: Mapped[dict | None] = mapped_column(JSON)  # {version, criteria[], policy}
    rubric_sum: Mapped[Decimal | None] = mapped_column(SCORE)


class Solution(Base):
    __tablename__ = "solutions"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    revision_part_id: Mapped[str] = mapped_column(UUID, ForeignKey("revision_parts.id"), nullable=False)
    solution_type: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    validation_state: Mapped[str] = mapped_column(String(32), default="unreviewed")
    reviewer_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("users.id"))


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    license_ref: Mapped[str | None] = mapped_column(String(128))
    scan_status: Mapped[str] = mapped_column(String(16), default="clean")


class RevisionAsset(Base):
    __tablename__ = "revision_assets"
    revision_id: Mapped[str] = mapped_column(UUID, ForeignKey("problem_revisions.id"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(UUID, ForeignKey("assets.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    alt_text: Mapped[str | None] = mapped_column(Text)


class ProblemRelation(Base):
    __tablename__ = "problem_relations"
    __table_args__ = (UniqueConstraint("from_problem_id", "to_problem_id", "relation_type"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    from_problem_id: Mapped[str] = mapped_column(UUID, ForeignKey("problems.id"), nullable=False)
    to_problem_id: Mapped[str] = mapped_column(UUID, ForeignKey("problems.id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_by: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


# ───────────────────────────── C. curriculum & learning ─────────────────────────────
class CurriculumSystem(Base):
    __tablename__ = "curriculum_systems"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    region: Mapped[str] = mapped_column(String(32), nullable=False)
    grade_band: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)


class CurriculumRelease(Base):
    __tablename__ = "curriculum_releases"
    __table_args__ = (UniqueConstraint("system_id", "release_code"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    system_id: Mapped[str] = mapped_column(UUID, ForeignKey("curriculum_systems.id"), nullable=False)
    release_code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), default="")
    source_ref: Mapped[str | None] = mapped_column(String(256))


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    __table_args__ = (UniqueConstraint("release_id", "external_code"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    release_id: Mapped[str] = mapped_column(UUID, ForeignKey("curriculum_releases.id"), nullable=False)
    external_code: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("knowledge_nodes.id"))
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1)


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"
    from_node_id: Mapped[str] = mapped_column(UUID, ForeignKey("knowledge_nodes.id"), primary_key=True)
    to_node_id: Mapped[str] = mapped_column(UUID, ForeignKey("knowledge_nodes.id"), primary_key=True)
    relation_type: Mapped[str] = mapped_column(String(24), primary_key=True)


class RevisionKnowledge(Base):
    __tablename__ = "revision_knowledge"
    revision_id: Mapped[str] = mapped_column(UUID, ForeignKey("problem_revisions.id"), primary_key=True)
    knowledge_node_id: Mapped[str] = mapped_column(UUID, ForeignKey("knowledge_nodes.id"), primary_key=True)
    relation_type: Mapped[str] = mapped_column(String(24), primary_key=True, default="tested")
    weight: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("1"))


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    problem_revision_id: Mapped[str] = mapped_column(UUID, ForeignKey("problem_revisions.id"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="practice")
    state: Mapped[str] = mapped_column(String(16), default="open")
    started_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("attempt_id", "idempotency_key"),
        Index("ix_sub_attempt_created", "attempt_id", "created_at"),
        Index("ix_sub_user_created", "user_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    attempt_id: Mapped[str] = mapped_column(UUID, ForeignKey("attempts.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), nullable=False)
    revision_part_id: Mapped[str] = mapped_column(UUID, ForeignKey("revision_parts.id"), nullable=False)
    answer_spec_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("answer_specs.id"))
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Evaluation(Base):
    """Append-only: regrades add rows that point to previous_evaluation_id."""

    __tablename__ = "evaluations"
    __table_args__ = (Index("ix_eval_sub_created", "submission_id", "created_at"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    submission_id: Mapped[str] = mapped_column(UUID, ForeignKey("submissions.id"), nullable=False)
    grader_name: Mapped[str] = mapped_column(String(48), nullable=False)
    grader_version: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    result_code: Mapped[str | None] = mapped_column(String(48))
    score: Mapped[Decimal | None] = mapped_column(SCORE)
    max_score: Mapped[Decimal] = mapped_column(SCORE, nullable=False)
    feedback: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    evaluator_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("users.id"))
    previous_evaluation_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("evaluations.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Collection(Base):
    __tablename__ = "collections"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    owner_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("users.id"))
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(24), default="official")  # official/knowledge/teacher/personal
    visibility: Mapped[str] = mapped_column(String(16), default="public")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class CollectionItem(Base):
    __tablename__ = "collection_items"
    __table_args__ = (UniqueConstraint("collection_id", "ordinal"),)
    collection_id: Mapped[str] = mapped_column(UUID, ForeignKey("collections.id"), primary_key=True)
    problem_id: Mapped[str] = mapped_column(UUID, ForeignKey("problems.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class Bookmark(Base):
    __tablename__ = "bookmarks"
    user_id: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), primary_key=True)
    problem_id: Mapped[str] = mapped_column(UUID, ForeignKey("problems.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class MistakeMark(Base):
    __tablename__ = "mistake_marks"
    user_id: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), primary_key=True)
    revision_part_id: Mapped[str] = mapped_column(UUID, ForeignKey("revision_parts.id"), primary_key=True)
    origin_submission_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("submissions.id"))
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class SearchDocument(Base):
    """Rebuildable read model; Postgres tables stay the source of truth (docs/04 §6)."""

    __tablename__ = "search_documents"
    __table_args__ = (Index("ix_search_display", "display_id"), Index("ix_search_diff", "difficulty"))
    problem_id: Mapped[str] = mapped_column(UUID, ForeignKey("problems.id"), primary_key=True)
    revision_id: Mapped[str] = mapped_column(UUID, ForeignKey("problem_revisions.id"), nullable=False)
    display_id: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_text: Mapped[str] = mapped_column(Text, default="")
    knowledge_ids: Mapped[str] = mapped_column(Text, default=",")  # ",id1,id2,"
    grade_band: Mapped[str] = mapped_column(String(32), nullable=False)
    region_hints: Mapped[str] = mapped_column(String(256), default=",")
    response_types: Mapped[str] = mapped_column(String(256), default=",")
    difficulty: Mapped[int] = mapped_column(Integer, default=0)
    part_count: Mapped[int] = mapped_column(Integer, nullable=False)
    has_solution: Mapped[bool] = mapped_column(Boolean, default=False)
    source_kind: Mapped[str] = mapped_column(String(32), default="internal")
    rights_grant_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("rights_grants.id"))
    updated_at: Mapped[datetime] = mapped_column(TS, nullable=False)


# ───────────────────────────── Phase 1.5 reasoning practice ─────────────────────────────
class ReasoningStep(Base):
    __tablename__ = "reasoning_steps"
    __table_args__ = (
        UniqueConstraint("revision_part_id", "step_order"),
        UniqueConstraint("revision_part_id", "semantic_key"),
    )
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    revision_part_id: Mapped[str] = mapped_column(UUID, ForeignKey("revision_parts.id"), nullable=False)
    semantic_key: Mapped[str] = mapped_column(String(96), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    recall_cue: Mapped[str] = mapped_column(Text, nullable=False)
    reference_latex: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="")
    max_points: Mapped[Decimal] = mapped_column(SCORE, nullable=False)
    criticality: Mapped[str] = mapped_column(String(16), default="normal")  # normal/key
    knowledge_codes: Mapped[list] = mapped_column(JSON, default=list)


class LearningAttempt(Base):
    __tablename__ = "learning_attempts"
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    problem_revision_id: Mapped[str | None] = mapped_column(UUID, ForeignKey("problem_revisions.id"))
    mode: Mapped[str] = mapped_column(String(16), default="full")  # full / due
    card_ids: Mapped[list] = mapped_column(JSON, nullable=False)  # frozen order of step ids
    state: Mapped[str] = mapped_column(String(16), default="open")
    started_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class StepReviewEvent(Base):
    __tablename__ = "step_review_events"
    __table_args__ = (UniqueConstraint("attempt_id", "step_id"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True)  # client event_id → idempotent
    user_id: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(UUID, ForeignKey("learning_attempts.id"), nullable=False)
    step_id: Mapped[str] = mapped_column(UUID, ForeignKey("reasoning_steps.id"), nullable=False)
    rating: Mapped[str] = mapped_column(String(8), nullable=False)  # know/fuzzy/unsure
    revealed_before_rating: Mapped[bool] = mapped_column(Boolean, default=False)
    max_points: Mapped[Decimal] = mapped_column(SCORE, nullable=False)
    self_score: Mapped[Decimal] = mapped_column(SCORE, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(24), default="v0-local")
    occurred_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class StepReviewState(Base):
    __tablename__ = "step_review_state"
    user_id: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), primary_key=True)
    step_id: Mapped[str] = mapped_column(UUID, ForeignKey("reasoning_steps.id"), primary_key=True)
    scheduler_version: Mapped[str] = mapped_column(String(24), primary_key=True, default="fixed-1-3-7")
    due_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    last_rating: Mapped[str] = mapped_column(String(8), nullable=False)


class KnowledgeSelfAssessment(Base):
    __tablename__ = "knowledge_self_assessments"
    __table_args__ = (UniqueConstraint("attempt_id", "knowledge_code"),)
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(UUID, ForeignKey("learning_attempts.id"), nullable=False)
    knowledge_code: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class XpAward(Base):
    __tablename__ = "learning_xp_awards"
    user_id: Mapped[str] = mapped_column(UUID, ForeignKey("users.id"), primary_key=True)
    step_id: Mapped[str] = mapped_column(UUID, ForeignKey("reasoning_steps.id"), primary_key=True)
    local_day: Mapped[str] = mapped_column(String(10), primary_key=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)


from sqlalchemy import event as _event  # noqa: E402


@_event.listens_for(RightsGrant, "before_insert")
@_event.listens_for(RightsGrant, "before_update")
def _sync_allows_display(_mapper, _conn, target: RightsGrant) -> None:
    target.allows_display = "display" in (target.permitted_actions or [])
