"""Multi-source ingestion acceptance (docs/05 §10 samples A–F, docs/01 UC-03 / AC-003)."""
import copy
import csv
import hashlib
import io
import json
import uuid

from conftest import ROOT, load_fixture


def sha(b: str) -> str:
    return hashlib.sha256(b.encode("utf-8")).hexdigest()


def manifest(source: str, grant: str, files: dict[str, str], adapter="contract-jsonl-v1", dry_run=False, version=None, fmt="jsonl"):
    return {"manifest_schema_version": "1.0", "source_code": source, "dataset_id": "ds-" + source,
            "dataset_version": version or "v1", "locale": "zh-CN", "rights_grant_ref": grant, "input_format": fmt,
            "adapter_version": adapter, "normalizer_version": "math-normalizer-v1", "dry_run": dry_run,
            "files": [{"path": p, "sha256": sha(c)} for p, c in files.items()]}


def new_source(client, H, kind="partner", actions=("display",)):
    code = "src-" + uuid.uuid4().hex[:8]
    assert client.post("/api/v1/admin/sources", json={"code": code, "name": code, "kind": kind}, headers=H("ops")).status_code == 201
    g = client.post("/api/v1/admin/rights-grants", json={"code": code + "-g", "source_code": code, "grant_type": "contract",
                                                         "permitted_actions": list(actions)}, headers=H("rights"))
    assert g.status_code == 201, g.text
    return code, code + "-g", g.json()["id"]


def contract_line(source: str, ext: str, ver: str = "1", fixture="LM-SH-000006.json", mutate=None) -> str:
    d = copy.deepcopy(load_fixture(fixture))
    d["problem"].pop("display_id", None)
    d["problem"].pop("slug", None)
    d["source_record_refs"] = [{"source_code": source, "external_id": ext, "external_revision": ver}]
    if mutate:
        mutate(d)
    return json.dumps(d, ensure_ascii=False)


def run(client, H, m, files, user="ops", path="/api/v1/admin/imports"):
    return client.post(path, json={"manifest": m, "files": files}, headers=H(user))


def rows(client, H, bid):
    return client.get(f"/api/v1/admin/imports/{bid}/rows", headers=H("ops")).json()["items"]


def unique_stmt(d, tag):
    d["revision"]["shared_statement"] = {"blocks": [{"type": "paragraph", "spans": [{"type": "text", "text": f"独立题干 {tag} " * 3}]}]}


def test_sample_a_replay_five_times_one_record(client, H):
    src, grant, _ = new_source(client, H)
    tag = uuid.uuid4().hex
    files = {"a.jsonl": contract_line(src, "A-1", mutate=lambda d: unique_stmt(d, tag)) + "\n"}
    ids = set()
    for i in range(5):
        m = manifest(src, grant, files, version=f"v1-run{i}")  # distinct batches, same records
        r = run(client, H, m, files)
        assert r.status_code == 202, r.text
        ids.add(r.json()["batch_id"])
        st = [x["state"] for x in rows(client, H, r.json()["batch_id"])]
        assert st == (["new_record"] if i == 0 else ["retained"])
    assert len(ids) == 5
    srcs = client.get("/api/v1/admin/sources", headers=H("ops")).json()["items"]
    assert next(s for s in srcs if s["code"] == src)["record_count"] == 1
    # identical manifest → same batch replayed (batch-level idempotency)
    m = manifest(src, grant, files, version="v1-run0")
    r = run(client, H, m, files)
    assert r.json()["replayed"] is True and r.json()["batch_id"] in ids


def test_sample_b_second_source_same_problem_is_candidate_not_merge(client, H):
    src1, g1, _ = new_source(client, H)
    src2, g2, _ = new_source(client, H)
    tag = uuid.uuid4().hex
    f1 = {"x.jsonl": contract_line(src1, "S1-1", mutate=lambda d: unique_stmt(d, tag)) + "\n"}
    f2 = {"y.jsonl": contract_line(src2, "S2-9", mutate=lambda d: unique_stmt(d, tag)) + "\n"}
    b1 = run(client, H, manifest(src1, g1, f1), f1).json()
    b2 = run(client, H, manifest(src2, g2, f2), f2).json()
    r1, r2 = rows(client, H, b1["batch_id"])[0], rows(client, H, b2["batch_id"])[0]
    assert r1["state"] == "new_record" and r2["state"] == "duplicate_candidate"
    assert r2["error_detail"]["level"] == "L1"
    dups = client.get("/api/v1/admin/duplicates", headers=H("reviewer")).json()["items"]
    cand = next(c for c in dups if c["left"]["source"] == src2)
    assert cand["level"] == "L1"
    res = client.post(f"/api/v1/admin/duplicates/{cand['id']}/resolve",
                      json={"decision": "exact_duplicate", "reason": "人工比对一致"}, headers=H("reviewer"))
    assert res.status_code == 200
    prob = client.get(f"/api/v1/admin/problems/{cand['right']['problem_id']}", headers=H("reviewer")).json()
    attributions = {(s["source"], s["relation"]) for s in prob["source_records"]}
    assert (src1, "origin") in attributions and (src2, "exact_duplicate") in attributions  # second source keeps attribution


def test_sample_c_semantic_change_needs_human_review(client, H):
    src, g, _ = new_source(client, H)
    tag = uuid.uuid4().hex[:6]

    def stmt(rel):
        def m(d):
            d["revision"]["shared_statement"] = {"blocks": [{"type": "paragraph", "spans": [
                {"type": "text", "text": f"题 {tag}：已知函数"}, {"type": "inline_math", "latex": "f(x)=x\\ln x-ax"},
                {"type": "text", "text": "，其中"}, {"type": "inline_math", "latex": f"x{rel}0"},
                {"type": "text", "text": "，求函数的最小值并讨论单调性与参数取值范围。"}]}]}
        return m
    f1 = {"c1.jsonl": contract_line(src, "C-1", mutate=stmt(">")) + "\n"}
    f2 = {"c2.jsonl": contract_line(src, "C-2", mutate=stmt("\\geq")) + "\n"}
    run(client, H, manifest(src, g, f1), f1)
    b = run(client, H, manifest(src, g, f2, version="v2"), f2).json()
    r = rows(client, H, b["batch_id"])[0]
    assert r["state"] == "duplicate_candidate" and r["error_detail"]["level"] == "L2"
    assert r["outcome_entity_type"] == "problem_revision"  # separate draft, nothing merged


def test_sample_d_expired_rights_quarantines(client, H):
    src, g, gid = new_source(client, H)
    client.post(f"/api/v1/admin/rights-grants/{gid}/status", json={"status": "revoked", "reason": "授权撤回"}, headers=H("rights"))
    f = {"d.jsonl": contract_line(src, "D-1", mutate=lambda d: unique_stmt(d, uuid.uuid4().hex)) + "\n"}
    b = run(client, H, manifest(src, g, f), f).json()
    r = rows(client, H, b["batch_id"])[0]
    assert r["state"] == "quarantined" and r["error_code"] == "RIGHTS_HOLD"


def test_sample_e_bad_rows_isolated_and_exportable(client, H):
    src, g, _ = new_source(client, H)
    lines = []
    bad = set()
    for i in range(60):
        if i % 12 == 5:
            lines.append("{not json")
            bad.add(i + 1)
        elif i % 12 == 7:
            lines.append(contract_line(src, f"E-{i}", fixture="LM-SH-000003.json",
                                       mutate=lambda d: d["revision"]["parts"][0]["answer_spec"].update(expected="Z")))
            bad.add(i + 1)
        else:
            t = uuid.uuid4().hex
            lines.append(contract_line(src, f"E-{i}", fixture="LM-SH-000003.json",
                                       mutate=lambda d, t=t: unique_stmt(d, t)))
    f = {"e.jsonl": "\n".join(lines) + "\n"}
    b = run(client, H, manifest(src, g, f), f).json()
    assert b["status"] == "completed_with_errors"
    rs = rows(client, H, b["batch_id"])
    assert len(rs) == 60
    failed = {r["row_no"] for r in rs if r["state"] == "rejected"}
    assert failed == bad
    assert {r["error_code"] for r in rs if r["state"] == "rejected"} == {"PARSE_FAILED", "NEEDS_FIX"}
    assert sum(1 for r in rs if r["state"] in ("new_record", "duplicate_candidate")) == 60 - len(bad)
    csv_text = client.get(f"/api/v1/admin/imports/{b['batch_id']}/rows?format=csv", headers=H("ops")).text
    exported = list(csv.DictReader(io.StringIO(csv_text)))
    assert len(exported) == 60 and {"stage", "error_code"} <= set(exported[0])
    # retry-failed re-processes only failed rows and never duplicates good ones
    before = client.get("/api/v1/admin/sources", headers=H("ops")).json()["items"]
    client.post(f"/api/v1/admin/imports/{b['batch_id']}/retry-failed", headers=H("ops"))
    after = client.get("/api/v1/admin/sources", headers=H("ops")).json()["items"]
    assert next(s for s in before if s["code"] == src)["record_count"] == next(s for s in after if s["code"] == src)["record_count"]


def test_sample_f_version_conflict(client, H):
    src, g, _ = new_source(client, H)
    t = uuid.uuid4().hex
    f1 = {"f.jsonl": contract_line(src, "F-1", ver="7", mutate=lambda d: unique_stmt(d, t)) + "\n"}
    run(client, H, manifest(src, g, f1), f1)

    def changed(d):
        unique_stmt(d, t)
        d["revision"]["title"] = "篡改后的标题"
    f2 = {"f.jsonl": contract_line(src, "F-1", ver="7", mutate=changed) + "\n"}
    b = run(client, H, manifest(src, g, f2, version="v2"), f2).json()
    r = rows(client, H, b["batch_id"])[0]
    assert r["state"] == "failed" and r["error_code"] == "SOURCE_VERSION_CONFLICT"


def test_new_source_version_creates_draft_revision(client, H):
    src, g, _ = new_source(client, H)
    t = uuid.uuid4().hex
    f1 = {"n.jsonl": contract_line(src, "N-1", ver="1", mutate=lambda d: unique_stmt(d, t)) + "\n"}
    b1 = run(client, H, manifest(src, g, f1), f1).json()
    pr = rows(client, H, b1["batch_id"])[0]["outcome_entity_id"]

    def v2(d):
        unique_stmt(d, t)
        d["revision"]["title"] = "来源修订后的标题"
    f2 = {"n.jsonl": contract_line(src, "N-1", ver="2", mutate=v2) + "\n"}
    b2 = run(client, H, manifest(src, g, f2, version="v2"), f2).json()
    r = rows(client, H, b2["batch_id"])[0]
    # the first draft is still open → change is queued for manual diff, not silently applied
    assert r["state"] == "new_revision" and r["error_code"] == "OPEN_DRAFT_EXISTS"
    assert pr


def test_file_hash_mismatch_rejected_before_queue(client, H):
    src, g, _ = new_source(client, H)
    f = {"h.jsonl": contract_line(src, "H-1") + "\n"}
    m = manifest(src, g, f)
    m["files"][0]["sha256"] = "0" * 64
    r = run(client, H, m, f)
    assert r.status_code == 422 and r.json()["error"]["code"] == "IMPORT_FILE_HASH_MISMATCH"


def test_manifest_schema_and_roles(client, H):
    src, g, _ = new_source(client, H)
    f = {"r.jsonl": contract_line(src, "R-1") + "\n"}
    m = manifest(src, g, f)
    assert run(client, H, m, f, user="editor").status_code == 403
    bad = dict(m)
    bad.pop("dataset_id")
    assert run(client, H, bad, f).json()["error"]["code"] == "IMPORT_SCHEMA_MISMATCH"


def test_dry_run_writes_nothing(client, H):
    src, g, _ = new_source(client, H)
    f = {"dr.jsonl": contract_line(src, "DR-1", mutate=lambda d: unique_stmt(d, uuid.uuid4().hex)) + "\n"}
    b = run(client, H, manifest(src, g, f, dry_run=True), f, path="/api/v1/admin/imports/dry-run").json()
    assert b["dry_run"] is True
    r = rows(client, H, b["batch_id"])[0]
    assert r["state"] == "new_record" and r["error_detail"]["dry_run"] is True
    srcs = client.get("/api/v1/admin/sources", headers=H("ops")).json()["items"]
    assert next(s for s in srcs if s["code"] == src)["record_count"] == 0


def test_repo_example_manifest_imports_as_is(client, H):
    """docs/examples/import-manifest.json + demo-source.jsonl, unchanged (dry_run=true in the file)."""
    m = json.loads((ROOT / "docs/examples/import-manifest.json").read_text("utf-8"))
    files = {"demo-source.jsonl": (ROOT / "docs/examples/demo-source.jsonl").read_text("utf-8")}
    r = run(client, H, m, files)
    assert r.status_code == 202, r.text
    rs = rows(client, H, r.json()["batch_id"])
    # Finding: demo-source.jsonl and problem-sh-function-001.json both claim
    # (leetmath-original-demo, demo-func-001, version "1") with different content → rule F.
    assert len(rs) == 1 and rs[0]["state"] == "failed" and rs[0]["error_code"] == "SOURCE_VERSION_CONFLICT"
    assert rs[0]["error_detail"]["dry_run"] is True


def test_demo_adapter_normalizes_to_practice_only_draft(client, H):
    src, g, _ = new_source(client, H)
    line = (ROOT / "docs/examples/demo-source.jsonl").read_text("utf-8").replace("demo-func-001", "demo-func-x")
    files = {"demo.jsonl": line}
    r = run(client, H, manifest(src, g, files, adapter="demo-jsonl-v1"), files)
    row = rows(client, H, r.json()["batch_id"])[0]
    assert row["state"] in ("new_record", "duplicate_candidate")
    assert any("practice_only" in w for w in row["error_detail"]["warnings"])
    doc = client.get(f"/api/v1/admin/problem-revisions/{row['outcome_entity_id']}", headers=H("editor")).json()["document"]
    spans = doc["revision"]["parts"][2]["prompt"]["blocks"][0]["spans"]
    assert any(sp["type"] == "inline_math" and "\\ln" in sp["latex"] for sp in spans)


def test_csv_partner_adapter(client, H):
    src, g, _ = new_source(client, H)
    t = uuid.uuid4().hex[:6]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["external_id", "version", "title", "region", "statement", "part_key", "prompt", "response_type", "max_score",
                "checker_type", "expected", "assumptions", "options", "knowledge_code", "difficulty", "solution",
                "curriculum_code", "release_code"])
    w.writerow([f"P-{t}", "1", f"CSV 题 {t}", "CN-BJ", f"已知 $g(x)=x^2+2x$ ({t})", "1", "求 $g'(x)$", "expression", "4",
                "symbolic_equivalence", "2x+2", '{"x":"real"}', "", "DERIV-RULES", "3", "g'(x)=2x+2", "CN-SH-SENIOR-HIGH", "DEMO-2026"])
    w.writerow([f"P-{t}", "1", f"CSV 题 {t}", "CN-BJ", "", "2", "$g(x)$ 的最小值", "integer", "2", "integer_exact", "-1", "", "", "", "", "", "", ""])
    w.writerow(["", "1", "缺 ID", "", "", "1", "x", "integer", "1", "integer_exact", "1", "", "", "", "", "", "", ""])
    files = {"p.csv": buf.getvalue()}
    b = run(client, H, manifest(src, g, files, adapter="csv-simple-v1", fmt="csv"), files).json()
    rs = rows(client, H, b["batch_id"])
    assert [r["state"] for r in rs] == ["new_record", "rejected"]
    doc = client.get(f"/api/v1/admin/problem-revisions/{rs[0]['outcome_entity_id']}", headers=H("editor")).json()["document"]
    assert len(doc["revision"]["parts"]) == 2 and doc["problem"]["display_id"].startswith("LM-BJ-")
    assert doc["revision"]["status"] == "draft"  # importer never publishes


def test_teacher_private_source_stays_private(client, H):
    src, g, _ = new_source(client, H, kind="teacher_private", actions=("reproduce",))
    f = {"tp.jsonl": contract_line(src, "TP-1", mutate=lambda d: unique_stmt(d, uuid.uuid4().hex)) + "\n"}
    b = run(client, H, manifest(src, g, f), f).json()
    r = rows(client, H, b["batch_id"])[0]
    assert r["state"] == "new_record"
    rev = client.get(f"/api/v1/admin/problem-revisions/{r['outcome_entity_id']}", headers=H("editor")).json()
    assert rev["visibility"] == "private"


def test_csv_extra_fields_rejects_only_that_record(client, H):
    src, g, _ = new_source(client, H)
    t = uuid.uuid4().hex[:6]
    text = ("external_id,title,part_key,prompt,response_type,max_score,checker_type,expected\n"
            f"OK-{t},题 {t},1,求 $1+1$,integer,1,integer_exact,2\n"
            f"BAD-{t},集合 {{1,2,3}} 未加引号,1,x,integer,1,integer_exact,1\n")
    files = {"x.csv": text}
    b = run(client, H, manifest(src, g, files, adapter="csv-simple-v1", fmt="csv"), files)
    assert b.status_code == 202
    rs = rows(client, H, b.json()["batch_id"])
    assert [r["state"] for r in rs] == ["new_record", "rejected"]
    assert "more field" in rs[1]["error_detail"]["message"]
