"""Import pipeline (docs/05 §4): register → archive → parse → normalise → validate → identity → dedup → rights → drafts.

Guarantees:
* batch idempotency key = sha256(source + dataset + version + files + adapter + normaliser + dry_run)
* record idempotency = (source_id, external_id, external_revision); replays are 'retained', never new rows
* per-row SAVEPOINT: one bad row never rolls back the others; every row has state + stage + error code
* similarity only *proposes* duplicate candidates — nothing is merged automatically
* nothing is published by the importer
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import ROOT
from ..content.contract import NORMALIZER_VERSION, canonical_json, content_hash, preflight, schema_major, sha256_text, statement_fingerprint
from ..models import (
    DuplicateCandidate,
    ImportBatch,
    ImportRow,
    Problem,
    ProblemRelation,
    ProblemRevision,
    RightsGrant,
    Source,
    SourceRecord,
    SourceRecordRevision,
    User,
    utcnow,
)
from . import catalog
from .adapters import ADAPTERS, SUPPORTED_NORMALIZERS, AdapterError, IntakeRecord, RawRow
from .audit import audit
from .errors import ApiError
from .rights import grant_allows, grant_by_ref
from .storage import get_bytes, put_bytes

IMPORTER_VERSION = "importer-1.0.0"
NEAR_DUP_THRESHOLD = 0.55  # candidate-only; must be calibrated on labelled data before any policy use


@lru_cache(maxsize=1)
def _manifest_validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads((ROOT / "content-schema" / "v1" / "import-manifest.schema.json").read_text("utf-8")))


def batch_key(m: dict) -> str:
    files = sorted(f"{f['path']}:{f['sha256']}" for f in m["files"])
    return sha256_text(canonical_json([m["source_code"], m["dataset_id"], m["dataset_version"], files,
                                       m["adapter_version"], m["normalizer_version"], bool(m.get("dry_run", True))]))


def _trigrams(s: str) -> set[str]:
    return {s[i:i + 3] for i in range(max(0, len(s) - 2))}


def similarity(a: str, b: str) -> float:
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass
class Ctx:
    s: Session
    batch: ImportBatch
    source: Source
    grant: RightsGrant | None
    grant_ok: bool
    grant_reason: str
    actor: User
    dry_run: bool
    fingerprints: dict[str, tuple[str, str]]  # problem_id → (fingerprint, content_hash)


def _load_fingerprints(s: Session) -> dict[str, tuple[str, str]]:
    out = {}
    for p in s.scalars(select(Problem).where(Problem.deleted_at.is_(None))):
        rev = s.scalar(select(ProblemRevision).where(ProblemRevision.problem_id == p.id)
                       .order_by(ProblemRevision.revision_no.desc()).limit(1))
        if rev:
            doc = catalog.revision_to_doc(s, rev)
            out[p.id] = (statement_fingerprint(doc), rev.content_hash or "")
    return out


def validate_manifest(s: Session, manifest: dict, files: dict[str, bytes]) -> tuple[Source, list[dict]]:
    errs = [e.message for e in _manifest_validator().iter_errors(manifest)]
    if errs:
        raise ApiError("IMPORT_SCHEMA_MISMATCH", "manifest invalid", {"errors": errs[:20]})
    source = s.scalar(select(Source).where(Source.code == manifest["source_code"]))
    if source is None or source.status != "active":
        raise ApiError("IMPORT_SCHEMA_MISMATCH", f"source {manifest['source_code']} not registered or disabled")
    if manifest["adapter_version"] not in ADAPTERS:
        raise ApiError("IMPORT_SCHEMA_MISMATCH", f"unknown adapter {manifest['adapter_version']}", {"available": sorted(ADAPTERS)})
    if manifest["normalizer_version"] not in SUPPORTED_NORMALIZERS:
        raise ApiError("IMPORT_SCHEMA_MISMATCH", f"unsupported normalizer {manifest['normalizer_version']}")
    mismatches = []
    for f in manifest["files"]:
        data = files.get(f["path"])
        if data is None:
            mismatches.append({"path": f["path"], "error": "missing"})
        elif sha256_text(data) != f["sha256"]:
            mismatches.append({"path": f["path"], "error": "sha256 mismatch", "actual": sha256_text(data)})
    if mismatches:
        raise ApiError("IMPORT_FILE_HASH_MISMATCH", "file hashes do not match manifest", {"files": mismatches})
    return source, mismatches


def run_import(s: Session, manifest: dict, files: dict[str, bytes], actor: User) -> tuple[ImportBatch, bool]:
    """Returns (batch, replayed)."""
    catalog.require_roles(actor, "source_manager")
    source, _ = validate_manifest(s, manifest, files)
    key = batch_key(manifest)
    existing = s.scalar(select(ImportBatch).where(ImportBatch.idempotency_key == key))
    if existing is not None:
        return existing, True
    dry_run = bool(manifest.get("dry_run", True))
    batch = ImportBatch(source_id=source.id, idempotency_key=key, manifest=manifest,
                        manifest_hash=sha256_text(canonical_json(manifest)), importer_version=IMPORTER_VERSION,
                        dry_run=dry_run, state="running", initiated_by=actor.id)
    s.add(batch)
    s.flush()
    audit(s, actor.id, "import.start", "import_batch", batch.id, dry_run=dry_run, source=source.code)
    grant = grant_by_ref(s, manifest["rights_grant_ref"])
    if grant is not None and grant.source_id != source.id:
        grant = None
    ok, why = grant_allows(grant, "display") if grant else (False, "NO_GRANT")
    if grant is not None and grant.status == "active" and not ok and why.startswith("ACTION_NOT_PERMITTED"):
        ok, why = True, "PRIVATE_ONLY"  # e.g. teacher_private: may be stored, never public
    ctx = Ctx(s, batch, source, grant, ok, why, actor, dry_run, _load_fingerprints(s))
    adapter = ADAPTERS[manifest["adapter_version"]]
    for f in manifest["files"]:
        data = files[f["path"]]
        put_bytes(data, "imports")
        try:
            rows = list(adapter.rows(data))
        except AdapterError as e:
            _row(ctx, f["path"], 0, None, data, "rejected", e.stage, e.code, {"message": e.message})
            continue
        except UnicodeDecodeError:
            _row(ctx, f["path"], 0, None, data, "rejected", "parse", "PARSE_FAILED", {"message": "file is not UTF-8"})
            continue
        except Exception as e:  # noqa: BLE001 — an adapter bug must surface as a failed file, never a 500
            _row(ctx, f["path"], 0, None, data, "rejected", "parse", "PARSE_FAILED", {"message": f"adapter error: {type(e).__name__}"})
            continue
        for raw in rows:
            _process_row(ctx, f["path"], raw)
    _finish(s, batch)
    return batch, False


def _row(ctx: Ctx, path: str, row_no: int, key: str | None, raw: bytes, state: str, stage: str,
         code: str | None = None, detail: dict | None = None, entity: tuple[str, str] | None = None) -> ImportRow:
    obj_key, sha = put_bytes(raw, "raw")
    r = ctx.s.scalar(select(ImportRow).where(ImportRow.batch_id == ctx.batch.id, ImportRow.row_no == row_no,
                                             ImportRow.file_path == path))
    if r is None:
        r = ImportRow(batch_id=ctx.batch.id, file_path=path, row_no=row_no, raw_sha256=sha, raw_object_key=obj_key,
                      state=state, stage=stage)
        ctx.s.add(r)
    r.source_record_key = key
    r.state, r.stage, r.error_code, r.error_detail = state, stage, code, detail
    r.outcome_entity_type, r.outcome_entity_id = (entity or (None, None))
    r.updated_at = utcnow()
    ctx.s.flush()
    return r


def _process_row(ctx: Ctx, path: str, raw: RawRow) -> ImportRow:
    s = ctx.s
    adapter = ADAPTERS[ctx.batch.manifest["adapter_version"]]
    try:
        rec: IntakeRecord = adapter.parse(raw, ctx.source.code)
    except AdapterError as e:
        return _row(ctx, path, raw.row_no, raw.key_hint, raw.raw, "rejected", e.stage, e.code, {"message": e.message})
    key = f"{rec.external_id}@{rec.external_revision}"
    doc = rec.doc
    doc["rights_policy_ref"] = ctx.batch.manifest["rights_grant_ref"]
    major = schema_major(doc)
    if major != 1:
        return _row(ctx, path, raw.row_no, key, raw.raw, "quarantined", "normalize", "IMPORT_SCHEMA_MISMATCH",
                    {"message": f"unsupported schema major {major}"})
    issues = preflight(doc)
    blocking = [i for i in issues if i["severity"] == "blocking"]
    if blocking:
        return _row(ctx, path, raw.row_no, key, raw.raw, "rejected", "validate", "NEEDS_FIX", {"issues": blocking[:20]})
    warnings = [i["code"] for i in issues if i["severity"] == "warning"] + rec.warnings
    sp = s.begin_nested()
    try:
        result = _identity_and_store(ctx, path, raw, rec, key, warnings)
        if ctx.dry_run:
            sp.rollback()
            state, stage, code, detail = result.state, result.stage, result.error_code, result.error_detail
            return _row(ctx, path, raw.row_no, key, raw.raw, state, stage, code, {**(detail or {}), "dry_run": True})
        sp.commit()
        return result
    except ApiError as e:
        sp.rollback()
        return _row(ctx, path, raw.row_no, key, raw.raw, "failed", "store", e.code, {"message": e.message, **e.details})
    except Exception as e:  # noqa: BLE001 — row isolation: an unexpected bug must not sink the batch
        sp.rollback()
        return _row(ctx, path, raw.row_no, key, raw.raw, "failed", "store", "INTERNAL_ERROR", {"message": type(e).__name__})


def _identity_and_store(ctx: Ctx, path: str, raw: RawRow, rec: IntakeRecord, key: str, warnings: list) -> ImportRow:
    s = ctx.s
    doc = rec.doc
    chash = content_hash(doc)
    obj_key, raw_sha = put_bytes(raw.raw, "raw")
    sr = s.scalar(select(SourceRecord).where(SourceRecord.source_id == ctx.source.id, SourceRecord.external_id == rec.external_id))
    detail = {"warnings": warnings} if warnings else {}

    # ── L0 source identity ──
    if sr is not None:
        srr = s.scalar(select(SourceRecordRevision).where(SourceRecordRevision.source_record_id == sr.id,
                                                          SourceRecordRevision.external_revision == rec.external_revision))
        if srr is not None:
            if srr.content_hash == chash:
                return _row(ctx, path, raw.row_no, key, raw.raw, "retained", "identity", None, detail, ("source_record", sr.id))
            return _row(ctx, path, raw.row_no, key, raw.raw, "failed", "identity", "SOURCE_VERSION_CONFLICT",
                        {"message": "same external revision but different content; ask the source to bump its version",
                         "existing_hash": srr.content_hash, "incoming_hash": chash}, ("source_record", sr.id))
        srr = _new_srr(ctx, sr, rec, obj_key, raw_sha, chash)
        sr.latest_source_revision = rec.external_revision
        if not ctx.grant_ok:
            return _row(ctx, path, raw.row_no, key, raw.raw, "quarantined", "rights", "RIGHTS_HOLD",
                        {"reason": ctx.grant_reason}, ("source_record_revision", srr.id))
        if sr.canonical_problem_id and sr.relation_to_problem == "origin":
            problem = s.get(Problem, sr.canonical_problem_id)
            latest = s.scalar(select(ProblemRevision).where(ProblemRevision.problem_id == problem.id)
                              .order_by(ProblemRevision.revision_no.desc()).limit(1))
            if latest and latest.content_hash == chash:
                return _row(ctx, path, raw.row_no, key, raw.raw, "retained", "identity", None,
                            {**detail, "note": "new source version with identical content"}, ("source_record_revision", srr.id))
            try:
                rev = catalog.new_revision(s, problem, ctx.actor, doc)
            except ApiError as e:
                return _row(ctx, path, raw.row_no, key, raw.raw, "new_revision", "review", "OPEN_DRAFT_EXISTS",
                            {"message": e.message, **e.details}, ("source_record_revision", srr.id))
            srr.problem_revision_id = rev.id
            return _row(ctx, path, raw.row_no, key, raw.raw, "new_revision", "review", None,
                        {**detail, "message": "source changed; new draft revision awaits human diff review"},
                        ("problem_revision", rev.id))
        return _row(ctx, path, raw.row_no, key, raw.raw, "new_revision", "review", None,
                    {**detail, "message": "new source version of an unmapped record"}, ("source_record_revision", srr.id))

    # ── new source record ──
    sr = SourceRecord(source_id=ctx.source.id, external_id=rec.external_id, latest_source_revision=rec.external_revision)
    s.add(sr)
    s.flush()
    srr = _new_srr(ctx, sr, rec, obj_key, raw_sha, chash)
    if not ctx.grant_ok:
        return _row(ctx, path, raw.row_no, key, raw.raw, "quarantined", "rights", "RIGHTS_HOLD",
                    {"reason": ctx.grant_reason}, ("source_record_revision", srr.id))

    # ── L1 exact normalised content ──
    fp = statement_fingerprint(doc)
    exact = [pid for pid, (f, h) in ctx.fingerprints.items() if f == fp or h == chash]
    if exact:
        for pid in exact[:3]:
            s.add(DuplicateCandidate(left_source_record_revision_id=srr.id, right_problem_id=pid, level="L1", score=1,
                                     signals={"fingerprint_equal": ctx.fingerprints[pid][0] == fp,
                                              "content_hash_equal": ctx.fingerprints[pid][1] == chash}))
        return _row(ctx, path, raw.row_no, key, raw.raw, "duplicate_candidate", "review", None,
                    {**detail, "candidates": exact[:3], "level": "L1"}, ("source_record_revision", srr.id))

    # ── create draft (never published by the importer) ──
    rev = catalog.create_problem(s, doc, ctx.actor, visibility=ctx.source.default_visibility if ctx.grant_reason != "PRIVATE_ONLY" else "private")
    sr.canonical_problem_id = rev.problem_id
    sr.relation_to_problem = "origin"
    srr.problem_revision_id = rev.id
    # ── L2 near-duplicate signals (candidates only) ──
    near = sorted(((similarity(fp, f), pid) for pid, (f, _h) in ctx.fingerprints.items()), reverse=True)
    near = [(sc, pid) for sc, pid in near if sc >= NEAR_DUP_THRESHOLD][:3]
    for sc, pid in near:
        s.add(DuplicateCandidate(left_source_record_revision_id=srr.id, right_problem_id=pid, level="L2",
                                 score=round(sc, 4), signals={"trigram_jaccard": round(sc, 4), "draft_problem_id": rev.problem_id}))
    ctx.fingerprints[rev.problem_id] = (fp, chash)
    state = "duplicate_candidate" if near else "new_record"
    return _row(ctx, path, raw.row_no, key, raw.raw, state, "review", None,
                {**detail, **({"candidates": [p for _, p in near], "level": "L2"} if near else {})},
                ("problem_revision", rev.id))


def _new_srr(ctx: Ctx, sr: SourceRecord, rec: IntakeRecord, obj_key: str, raw_sha: str, chash: str) -> SourceRecordRevision:
    m = ctx.batch.manifest
    srr = SourceRecordRevision(source_record_id=sr.id, external_revision=rec.external_revision, raw_object_key=obj_key,
                               raw_sha256=raw_sha, adapter_version=m["adapter_version"],
                               normalizer_version=m["normalizer_version"], normalized_payload=rec.doc,
                               content_hash=chash, batch_id=ctx.batch.id)
    ctx.s.add(srr)
    ctx.s.flush()
    return srr


def _finish(s: Session, batch: ImportBatch) -> None:
    rows = s.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id)).all()
    counts: dict[str, int] = {"read": len(rows)}
    for r in rows:
        counts[r.state] = counts.get(r.state, 0) + 1
    batch.counts = counts
    batch.state = "completed_with_errors" if any(r.state in ("failed", "rejected") for r in rows) else "completed"
    batch.finished_at = utcnow()


def retry_failed(s: Session, batch: ImportBatch, actor: User) -> ImportBatch:
    catalog.require_roles(actor, "source_manager")
    source = s.get(Source, batch.source_id)
    grant = grant_by_ref(s, batch.manifest["rights_grant_ref"])
    ok, why = grant_allows(grant, "display") if grant else (False, "NO_GRANT")
    ctx = Ctx(s, batch, source, grant, ok, why, actor, batch.dry_run, _load_fingerprints(s))
    for r in s.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id, ImportRow.state.in_(("failed", "rejected")))).all():
        if r.row_no == 0:
            continue
        _process_row(ctx, r.file_path, RawRow(r.row_no, get_bytes(r.raw_object_key), r.source_record_key))
    _finish(s, batch)
    audit(s, actor.id, "import.retry_failed", "import_batch", batch.id)
    return batch


def resolve_duplicate(s: Session, cand: DuplicateCandidate, actor: User, decision: str, reason: str) -> DuplicateCandidate:
    """Human decision (docs/05 §5). Never deletes the second source's attribution."""
    catalog.require_roles(actor, "reviewer", "source_manager")
    if cand.status == "resolved":
        raise ApiError("INVALID_STATE", "candidate already resolved")
    if decision not in ("exact_duplicate", "independent", "isomorphic_to", "adapted_from", "defer"):
        raise ApiError("VALIDATION_FAILED", "invalid decision")
    if not reason:
        raise ApiError("VALIDATION_FAILED", "reason required")
    srr = s.get(SourceRecordRevision, cand.left_source_record_revision_id)
    sr = s.get(SourceRecord, srr.source_record_id)
    if decision == "defer":
        cand.status = "deferred"
    else:
        draft_pid = cand.signals.get("draft_problem_id") or (sr.canonical_problem_id if sr.relation_to_problem == "origin" else None)
        if decision == "exact_duplicate":
            if draft_pid and draft_pid != cand.right_problem_id:
                raise ApiError("INVALID_STATE", "this record already produced its own draft; mark as related instead",
                               {"draft_problem_id": draft_pid})
            sr.canonical_problem_id = cand.right_problem_id
            sr.relation_to_problem = "exact_duplicate"
        else:
            if not draft_pid:
                rev = catalog.create_problem(s, srr.normalized_payload, actor)
                srr.problem_revision_id = rev.id
                sr.canonical_problem_id = rev.problem_id
                sr.relation_to_problem = "origin"
                draft_pid = rev.problem_id
            if decision in ("isomorphic_to", "adapted_from"):
                s.add(ProblemRelation(from_problem_id=draft_pid, to_problem_id=cand.right_problem_id,
                                      relation_type=decision, decision_by=actor.id, reason=reason))
        cand.status = "resolved"
    cand.decision = decision
    cand.decision_reason = reason
    cand.reviewer_id = actor.id
    cand.resolved_at = utcnow()
    audit(s, actor.id, "duplicate.resolve", "duplicate_candidate", cand.id, decision=decision, reason=reason)
    # Resolving one candidate of an L1 group auto-closes the siblings only if they point to the same record.
    return cand


def load_files_from_dir(manifest: dict, base: Path) -> dict[str, bytes]:
    return {f["path"]: (base / f["path"]).read_bytes() for f in manifest["files"] if (base / f["path"]).is_file()}


__all__ = ["run_import", "retry_failed", "resolve_duplicate", "batch_key", "similarity", "NORMALIZER_VERSION"]
