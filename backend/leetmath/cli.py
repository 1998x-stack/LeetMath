"""LeetMath CLI.

  python -m leetmath.cli init-db                       # dev: create tables directly
  python -m leetmath.cli migrate                       # prod: alembic upgrade head
  python -m leetmath.cli seed [--reset]
  python -m leetmath.cli validate FILE_OR_DIR...        # Contract v1 schema + preflight (+ golden cases)
  python -m leetmath.cli export-fixtures                # write seed docs to fixtures/positive
  python -m leetmath.cli import MANIFEST.json [--as ops] # run an import batch from a manifest + files beside it
  python -m leetmath.cli ddl --dialect postgresql       # print physical DDL
  python -m leetmath.cli serve [--port 8000]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from .config import ROOT, settings
from .db import Base, create_all, get_engine, session_scope


def cmd_validate(paths: list[str]) -> int:
    from .content.contract import preflight

    files: list[Path] = []
    for p in map(Path, paths):
        files += sorted(p.rglob("*.json")) if p.is_dir() else [p]
    bad = 0
    for f in files:
        doc = json.loads(f.read_text("utf-8"))
        issues = preflight(doc)
        blocking = [i for i in issues if i["severity"] == "blocking"]
        mark = "FAIL" if blocking else "ok  "
        print(f"{mark} {f}  ({len(blocking)} blocking, {len(issues) - len(blocking)} warnings)")
        for i in blocking:
            print(f"     ✗ {i['code']} {i['path']}: {i['message']}")
        bad += bool(blocking)
    return 1 if bad else 0


def seed(reset: bool = False) -> dict:
    from .api.common import hash_password
    from .models import (Collection, CollectionItem, CurriculumRelease, CurriculumSystem, KnowledgeEdge, KnowledgeNode,
                         Problem, RightsGrant, Source, SourceRecord, User)
    from .seed_data import CURRICULUM, GRANT, SOURCE, USERS, build_problems
    from .content.contract import NORMALIZER_VERSION, content_hash
    from .models import SourceRecordRevision
    from .services import catalog
    from .services.storage import put_bytes

    if reset:
        Base.metadata.drop_all(get_engine())
    if os.environ.get("LEETMATH_AUTO_CREATE", "1") == "1":
        create_all()
    with session_scope() as s:
        if s.scalar(select(User).where(User.username == "admin")):
            return {"status": "already seeded"}
        users = {}
        for username, pw, display, roles in USERS:
            u = User(username=username, display_name=display, roles="," + ",".join(roles) + ",", password_hash=hash_password(pw))
            s.add(u)
            users[username] = u
        s.flush()
        cs = CurriculumSystem(**CURRICULUM["system"])
        s.add(cs)
        s.flush()
        rel = CurriculumRelease(system_id=cs.id, **CURRICULUM["release"])
        s.add(rel)
        s.flush()
        nodes = {}
        for code, parent, title in CURRICULUM["nodes"]:
            n = KnowledgeNode(release_id=rel.id, external_code=code, title=title,
                              parent_id=nodes[parent].id if parent else None, level=2 if parent else 1)
            s.add(n)
            s.flush()
            nodes[code] = n
        for a, b, t in CURRICULUM["edges"]:
            s.add(KnowledgeEdge(from_node_id=nodes[a].id, to_node_id=nodes[b].id, relation_type=t))
        src = Source(code=SOURCE, name="LeetMath 原创演示题库", kind="internal", owner="LeetMath 教研组")
        partner = Source(code="demo-partner-csv", name="演示合作方（CSV，虚构）", kind="partner", owner="Demo Partner Ltd. (fictional)")
        s.add_all([src, partner])
        s.flush()
        s.add(RightsGrant(code=GRANT, source_id=src.id, grant_type="original", scope="原创演示内容，平台内展示与练习",
                          permitted_actions=["display", "reproduce", "adapt", "export"], status="active",
                          attribution_text="LeetMath 原创演示题（非官方试题）", evidence_ref="internal://originals/demo",
                          reviewed_by=users["rights"].id))
        s.add(RightsGrant(code="demo-partner-2026", source_id=partner.id, grant_type="contract", scope="演示合同：平台内展示",
                          permitted_actions=["display"], status="active", territory="CN",
                          valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc), valid_to=datetime(2027, 12, 31, tzinfo=timezone.utc),
                          attribution_text="题目由演示合作方提供（虚构）", evidence_ref="contracts/demo-partner-2026.pdf",
                          reviewed_by=users["rights"].id))
        s.flush()
        published = []
        for d in build_problems():
            rev = catalog.create_problem(s, d, users["editor"])
            s.flush()
            sr = SourceRecord(source_id=src.id, external_id=d["source_record_refs"][0]["external_id"],
                              latest_source_revision="1", canonical_problem_id=rev.problem_id, relation_to_problem="origin")
            s.add(sr)
            s.flush()
            raw = json.dumps(d, ensure_ascii=False, sort_keys=True).encode("utf-8")
            key, raw_sha = put_bytes(raw, "raw")
            s.add(SourceRecordRevision(source_record_id=sr.id, external_revision="1", raw_object_key=key, raw_sha256=raw_sha,
                                       adapter_version="seed", normalizer_version=NORMALIZER_VERSION, normalized_payload=d,
                                       content_hash=content_hash(d), problem_revision_id=rev.id))
            catalog.submit_review(s, rev, users["editor"], "seed")
            catalog.approve_math(s, rev, users["reviewer"], "seed review")
            catalog.approve_rights(s, rev, users["rights"], "original content")
            catalog.publish(s, rev, users["reviewer"])
            published.append(rev)
        s.flush()
        by_disp = {s.get(Problem, r.problem_id).display_id: r.problem_id for r in published}
        lists = [
            ("derivatives-starter", "导数入门专题", "从求导到单调性与切线", ["LM-SH-000001", "LM-SH-000012"]),
            ("sh-pilot-mixed", "上海试点综合练习（原创）", "覆盖全部自动判题题型的综合题单",
             sorted(by_disp)),
        ]
        for slug, title, desc, ids in lists:
            c = Collection(owner_id=users["editor"].id, slug=slug, title=title, description=desc, kind="official")
            s.add(c)
            s.flush()
            for i, disp in enumerate(ids, start=1):
                s.add(CollectionItem(collection_id=c.id, problem_id=by_disp[disp], ordinal=i))
        return {"status": "seeded", "problems": len(published), "users": [u[0] for u in USERS]}


def cmd_export_fixtures() -> None:
    from .seed_data import build_problems

    out = ROOT / "fixtures" / "positive"
    out.mkdir(parents=True, exist_ok=True)
    for d in build_problems():
        (out / f"{d['problem']['display_id'] if 'display_id' in d['problem'] else 'doc'}.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"wrote {len(build_problems())} fixtures to {out}")


def cmd_import(manifest_path: str, username: str) -> int:
    from .models import User
    from .services.ingestion import load_files_from_dir, run_import

    mp = Path(manifest_path)
    manifest = json.loads(mp.read_text("utf-8"))
    files = load_files_from_dir(manifest, mp.parent)
    with session_scope() as s:
        user = s.scalar(select(User).where(User.username == username))
        batch, replayed = run_import(s, manifest, files, user)
        print(json.dumps({"batch_id": batch.id, "replayed": replayed, "state": batch.state, "counts": batch.counts}, ensure_ascii=False, indent=2))
    return 0


def cmd_ddl(dialect: str) -> None:
    from sqlalchemy.schema import CreateIndex, CreateTable

    from . import models  # noqa: F401

    if dialect == "postgresql":
        from sqlalchemy.dialects import postgresql as d
    else:
        from sqlalchemy.dialects import sqlite as d
    dia = d.dialect()
    print(f"-- LeetMath physical schema ({dialect}), generated from leetmath/models.py\n")
    for t in Base.metadata.sorted_tables:
        print(str(CreateTable(t).compile(dialect=dia)).strip() + ";\n")
        for ix in sorted(t.indexes, key=lambda i: i.name):  # stable order: index sets are unordered
            print(str(CreateIndex(ix).compile(dialect=dia)).strip() + ";")
    if dialect == "postgresql":
        print("""
-- Defence in depth: published revisions are immutable at the database layer too (docs/04 §3).
CREATE OR REPLACE FUNCTION forbid_frozen_revision_edit() RETURNS trigger AS $$
BEGIN
  IF OLD.status IN ('published','archived','retracted') AND (
       NEW.title IS DISTINCT FROM OLD.title OR NEW.shared_statement::text IS DISTINCT FROM OLD.shared_statement::text
       OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR NEW.rights_grant_id IS DISTINCT FROM OLD.rights_grant_id) THEN
    RAISE EXCEPTION 'revision % is %, content is immutable', OLD.id, OLD.status;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_problem_revisions_immutable BEFORE UPDATE ON problem_revisions
  FOR EACH ROW EXECUTE FUNCTION forbid_frozen_revision_edit();
REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC;""")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="leetmath")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    sub.add_parser("migrate")
    sp = sub.add_parser("seed")
    sp.add_argument("--reset", action="store_true")
    vp = sub.add_parser("validate")
    vp.add_argument("paths", nargs="+")
    sub.add_parser("export-fixtures")
    ip = sub.add_parser("import")
    ip.add_argument("manifest")
    ip.add_argument("--as", dest="username", default="ops")
    dp = sub.add_parser("ddl")
    dp.add_argument("--dialect", default="postgresql", choices=["postgresql", "sqlite"])
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    if a.cmd == "init-db":
        create_all()
        print(f"database ready: {settings.database_url}")
    elif a.cmd == "migrate":
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config(str(ROOT / "backend" / "alembic.ini")), "head")
        print(f"migrated: {settings.database_url}")
    elif a.cmd == "seed":
        print(json.dumps(seed(a.reset), ensure_ascii=False))
    elif a.cmd == "validate":
        return cmd_validate(a.paths)
    elif a.cmd == "export-fixtures":
        cmd_export_fixtures()
    elif a.cmd == "import":
        return cmd_import(a.manifest, a.username)
    elif a.cmd == "ddl":
        cmd_ddl(a.dialect)
    elif a.cmd == "serve":
        import uvicorn

        from .app import create_app

        seed()
        uvicorn.run(create_app(), host=a.host, port=a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
