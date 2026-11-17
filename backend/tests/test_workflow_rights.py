"""CMS workflow, immutability, rights gate, retraction (docs/08 §9, docs/01 AC-002/005/006)."""
import uuid
from datetime import datetime, timedelta, timezone


def _create(client, H, doc):
    r = client.post("/api/v1/admin/problems", json={"document": doc}, headers=H("editor"))
    assert r.status_code == 201, r.text
    return r.json()


def _go(client, H, rid, user, action, **body):
    return client.post(f"/api/v1/admin/problem-revisions/{rid}/{action}", json=body, headers=H(user))


def test_reviewer_cannot_approve_own_content(client, H, fresh_doc, tokens):
    # admin creates (admin also holds reviewer powers) → admin must not approve it
    r = client.post("/api/v1/admin/problems", json={"document": fresh_doc()}, headers=H("admin"))
    rid = r.json()["revision_id"]
    assert _go(client, H, rid, "admin", "submit-review").status_code == 200
    r = _go(client, H, rid, "admin", "approve")
    assert r.status_code == 403 and r.json()["error"]["code"] == "SELF_APPROVAL_FORBIDDEN"


def test_math_and_rights_need_distinct_reviewers(client, H, fresh_doc):
    rid = _create(client, H, fresh_doc())["revision_id"]
    _go(client, H, rid, "editor", "submit-review")
    assert _go(client, H, rid, "admin", "approve").status_code == 200  # math gate by admin
    r = _go(client, H, rid, "admin", "approve")  # same person tries rights gate
    assert r.status_code == 403


def test_students_and_editors_cannot_publish(client, H, fresh_doc):
    rid = _create(client, H, fresh_doc())["revision_id"]
    assert _go(client, H, rid, "student", "submit-review").status_code == 403
    _go(client, H, rid, "editor", "submit-review")
    assert _go(client, H, rid, "editor", "approve").status_code == 403
    assert _go(client, H, rid, "editor", "publish").status_code == 403


def test_cannot_publish_before_rights_review(client, H, fresh_doc):
    rid = _create(client, H, fresh_doc())["revision_id"]
    _go(client, H, rid, "editor", "submit-review")
    _go(client, H, rid, "reviewer", "approve")
    r = _go(client, H, rid, "reviewer", "publish")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"


def test_preflight_blocks_submit_with_field_locations(client, H, fresh_doc):
    d = fresh_doc()
    d["revision"]["parts"][0]["rubric"] = {"version": 1, "criteria": [{"id": "C1", "description": "x", "max_points": "1.00"}]}
    rid = _create(client, H, d)["revision_id"]
    r = _go(client, H, rid, "editor", "submit-review")
    assert r.status_code == 422
    issues = r.json()["error"]["details"]["issues"]
    assert any(i["code"] == "RUBRIC_SUM_MISMATCH" and i["path"].startswith("/revision/parts/0") for i in issues)


def test_reject_requires_reason_and_returns_to_draft(client, H, fresh_doc):
    rid = _create(client, H, fresh_doc())["revision_id"]
    _go(client, H, rid, "editor", "submit-review")
    assert _go(client, H, rid, "reviewer", "reject", reason="").status_code == 422
    r = _go(client, H, rid, "reviewer", "reject", reason="第3问定义域写错")
    assert r.json()["status"] == "draft" and "定义域" in r.json()["review_note"]


def test_optimistic_lock_edit_conflict(client, H, fresh_doc):
    created = _create(client, H, fresh_doc())
    rid = created["revision_id"]
    doc = created["document"]
    r1 = client.patch(f"/api/v1/admin/problem-revisions/{rid}", json={"document": doc}, headers=H("editor", If_Match='"1"'))
    assert r1.status_code == 200 and r1.headers["ETag"] == '"2"'
    r2 = client.patch(f"/api/v1/admin/problem-revisions/{rid}", json={"document": doc}, headers=H("editor", If_Match='"1"'))
    assert r2.status_code == 412 and r2.json()["error"]["code"] == "EDIT_CONFLICT"


def test_ac002_new_revision_keeps_history(client, H, fresh_doc, publish):
    row = publish(fresh_doc())
    slug, rev1 = row["slug"], row["revision_id"]
    detail = client.get(f"/api/v1/problems/{slug}").json()
    part1 = detail["current_revision"]["parts"][0]
    att = client.post("/api/v1/attempts", json={"problem_revision_id": rev1}, headers=H("student")).json()["attempt_id"]
    sub = client.post(f"/api/v1/attempts/{att}/submissions", json={"revision_part_id": part1["id"], "response": {"input": "39"}},
                      headers=H("student", Idempotency_Key=uuid.uuid4().hex)).json()
    # published revisions cannot be edited in place
    pdoc = client.get(f"/api/v1/admin/problem-revisions/{rev1}", headers=H("editor")).json()["document"]
    r = client.patch(f"/api/v1/admin/problem-revisions/{rev1}", json={"document": pdoc}, headers=H("editor", If_Match='"1"'))
    assert r.status_code == 409
    # revise the answer → new revision
    nr = client.post(f"/api/v1/admin/problems/{row['problem_id']}/revisions", headers=H("editor")).json()
    rev2 = nr["revision_id"]
    d2 = nr["document"]
    d2["revision"]["change_note"] = "修订第1问表述"
    d2["revision"]["parts"][0]["prompt"]["blocks"][0]["spans"][0]["text"] = "求第 10 项 "
    client.patch(f"/api/v1/admin/problem-revisions/{rev2}", json={"document": d2}, headers=H("editor", If_Match=f'"{nr["lock_version"]}"'))
    for user, path in [("editor", "submit-review"), ("reviewer", "approve"), ("rights", "approve"), ("reviewer", "publish")]:
        assert _go(client, H, rev2, user, path).status_code == 200
    new = client.get(f"/api/v1/problems/{slug}").json()["current_revision"]
    assert new["id"] == rev2 and new["revision_no"] == 2
    assert new["parts"][0]["logical_part_id"] == part1["logical_part_id"]  # stable logical identity
    assert new["parts"][0]["id"] != part1["id"]  # new version-scoped part id
    old = client.get(f"/api/v1/submissions/{sub['submission_id']}", headers=H("student")).json()
    assert old["revision_part_id"] == part1["id"] and old["revision_no"] == 1
    assert old["score"] == "3.00" and old["evaluation"]["checker_version"].endswith("1.0.0")
    assert old["problem"]["superseded"] is True
    # old attempt can no longer submit: 409 REVISION_SUPERSEDED
    r = client.post(f"/api/v1/attempts/{att}/submissions", json={"revision_part_id": part1["id"], "response": {"input": "39"}},
                    headers=H("student", Idempotency_Key=uuid.uuid4().hex))
    assert r.status_code == 409 and r.json()["error"]["code"] == "REVISION_SUPERSEDED"
    # the student can still view the old revision they answered
    hist = client.get(f"/api/v1/problems/{slug}/revisions/{rev1}", headers=H("student"))
    assert hist.status_code == 200 and hist.json()["revision_no"] == 1
    assert client.get(f"/api/v1/problems/{slug}/revisions/{rev1}", headers=H("student2")).status_code == 404


def test_ac005_retracted_content_unreachable(client, H, fresh_doc, publish):
    row = publish(fresh_doc())
    slug, rid, pid = row["slug"], row["revision_id"], row["problem_id"]
    att = client.post("/api/v1/attempts", json={"problem_revision_id": rid}, headers=H("student")).json()["attempt_id"]
    part = client.get(f"/api/v1/problems/{slug}").json()["current_revision"]["parts"][0]["id"]
    client.put(f"/api/v1/me/bookmarks/{pid}", headers=H("student"))
    assert _go(client, H, rid, "reviewer", "retract", reason="答案有误").status_code == 200
    assert client.get(f"/api/v1/problems/{slug}").status_code == 404
    assert slug not in {i["slug"] for i in client.get("/api/v1/problems?limit=100").json()["items"]}
    r = client.post(f"/api/v1/attempts/{att}/submissions", json={"revision_part_id": part, "response": {"input": "39"}},
                    headers=H("student", Idempotency_Key=uuid.uuid4().hex))
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONTENT_RETRACTED"
    bm = [b for b in client.get("/api/v1/me/bookmarks", headers=H("student")).json()["items"] if b["problem_id"] == pid][0]
    assert bm["available"] is False and bm["title"] is None  # hidden, not leaked
    hist = client.get(f"/api/v1/problems/{slug}/revisions/{rid}", headers=H("student")).json()
    assert hist["content_withheld"] is True and "parts" not in hist


def test_rights_expiry_blocks_immediately_without_touching_history(client, H, fresh_doc, publish):
    code = "exp-" + uuid.uuid4().hex[:6]
    client.post("/api/v1/admin/sources", json={"code": code, "name": "Expiring partner", "kind": "partner"}, headers=H("ops"))
    g = client.post("/api/v1/admin/rights-grants", json={"code": code + "-g", "source_code": code, "grant_type": "contract",
                                                         "permitted_actions": ["display"]}, headers=H("rights")).json()
    assert g["display_ok"]
    d = fresh_doc()
    d["source_record_refs"] = [{"source_code": code, "external_id": "x1"}]
    d["rights_policy_ref"] = code + "-g"
    row = publish(d)
    slug = row["slug"]
    att = client.post("/api/v1/attempts", json={"problem_revision_id": row["revision_id"]}, headers=H("student")).json()["attempt_id"]
    part = client.get(f"/api/v1/problems/{slug}").json()["current_revision"]["parts"][0]["id"]
    sub = client.post(f"/api/v1/attempts/{att}/submissions", json={"revision_part_id": part, "response": {"input": "39"}},
                      headers=H("student", Idempotency_Key=uuid.uuid4().hex)).json()
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    client.post(f"/api/v1/admin/rights-grants/{g['id']}/status", json={"status": "active", "reason": "合同到期", "valid_to": past},
                headers=H("rights"))
    assert client.get(f"/api/v1/problems/{slug}").status_code == 404
    assert slug not in {i["slug"] for i in client.get("/api/v1/problems?limit=100").json()["items"]}
    s = client.get(f"/api/v1/submissions/{sub['submission_id']}", headers=H("student")).json()
    assert s["score"] == "3.00" and s["problem"]["available"] is False and s["problem"]["title"] is None


def test_rights_hold_and_release(client, H, fresh_doc, publish):
    row = publish(fresh_doc())
    r = client.post(f"/api/v1/admin/problems/{row['problem_id']}/rights-hold", json={"hold": True, "reason": "侵权投诉"},
                    headers=H("rights"))
    assert r.status_code == 200
    assert client.get(f"/api/v1/problems/{row['slug']}").status_code == 404
    client.post(f"/api/v1/admin/problems/{row['problem_id']}/rights-hold", json={"hold": False, "reason": "投诉不成立"},
                headers=H("rights"))
    assert client.get(f"/api/v1/problems/{row['slug']}").status_code == 200
    # only rights reviewers (or admin) can place a hold
    assert client.post(f"/api/v1/admin/problems/{row['problem_id']}/rights-hold", json={"hold": True, "reason": "x"},
                       headers=H("editor")).status_code == 403


def test_publish_blocked_without_display_right(client, H, fresh_doc):
    code = "nodisp-" + uuid.uuid4().hex[:6]
    client.post("/api/v1/admin/sources", json={"code": code, "name": "Private teacher bank", "kind": "teacher_private"}, headers=H("ops"))
    client.post("/api/v1/admin/rights-grants", json={"code": code + "-g", "source_code": code, "grant_type": "license",
                                                     "permitted_actions": ["reproduce"]}, headers=H("rights"))
    d = fresh_doc()
    d["source_record_refs"] = [{"source_code": code, "external_id": "p1"}]
    d["rights_policy_ref"] = code + "-g"
    rid = _create(client, H, d)["revision_id"]
    _go(client, H, rid, "editor", "submit-review")
    _go(client, H, rid, "reviewer", "approve")
    r = _go(client, H, rid, "rights", "approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "RIGHTS_HOLD"


def test_suspend_grading(client, H, fresh_doc, publish):
    row = publish(fresh_doc())
    det = client.get(f"/api/v1/problems/{row['slug']}").json()["current_revision"]
    part = det["parts"][0]["id"]
    assert client.post(f"/api/v1/admin/revision-parts/{part}/grading", json={"suspended": True, "reason": "答案存疑"},
                       headers=H("reviewer")).status_code == 200
    att = client.post("/api/v1/attempts", json={"problem_revision_id": det["id"]}, headers=H("student")).json()["attempt_id"]
    ev = client.post(f"/api/v1/attempts/{att}/submissions", json={"revision_part_id": part, "response": {"input": "39"}},
                     headers=H("student", Idempotency_Key=uuid.uuid4().hex)).json()["evaluation"]
    assert ev["status"] == "pending_review" and ev["result_code"] == "GRADING_SUSPENDED"


def test_manual_grading_and_regrade_append_only(client, H):
    d = client.get("/api/v1/problems/function-x-log-x-minus-a-x", headers=H("student2")).json()["current_revision"]
    att = client.post("/api/v1/attempts", json={"problem_revision_id": d["id"]}, headers=H("student2")).json()["attempt_id"]
    sub = client.post(f"/api/v1/attempts/{att}/submissions", json={"revision_part_id": d["parts"][1]["id"],
                      "response": {"input": "x=e^{a-1} 处取最小值 -e^{a-1}"}},
                      headers=H("student2", Idempotency_Key=uuid.uuid4().hex)).json()
    q = client.get("/api/v1/admin/grading-queue", headers=H("reviewer")).json()["items"]
    assert sub["submission_id"] in {i["submission_id"] for i in q}
    assert client.get("/api/v1/admin/grading-queue", headers=H("student")).status_code == 403
    bad = client.post(f"/api/v1/admin/submissions/{sub['submission_id']}/evaluations",
                      json={"state": "accepted", "score": "3.00", "reason": "x"}, headers=H("reviewer"))
    assert bad.status_code == 422  # accepted must be full marks
    ok = client.post(f"/api/v1/admin/submissions/{sub['submission_id']}/evaluations",
                     json={"state": "partial", "score": "3.00", "reason": "缺少单调性论证", "matched_criteria": ["P2-C1", "P2-C3"]},
                     headers=H("reviewer"))
    assert ok.status_code == 201
    hist = client.get(f"/api/v1/submissions/{sub['submission_id']}/evaluations", headers=H("student2")).json()["items"]
    assert [h["status"] for h in hist] == ["pending_review", "partial"]
    assert hist[1]["previous_evaluation_id"] == hist[0]["evaluation_id"]
    latest = client.get(f"/api/v1/submissions/{sub['submission_id']}", headers=H("student2")).json()
    assert latest["status"] == "partial" and latest["score"] == "3.00"


def test_audit_log_records_actions_and_is_role_protected(client, H):
    r = client.get("/api/v1/admin/audit-events?entity_type=problem_revision", headers=H("auditor"))
    assert r.status_code == 200 and any(e["action"] == "revision.published" for e in r.json()["items"])
    assert client.get("/api/v1/admin/audit-events", headers=H("editor")).status_code == 403


def test_slug_rename_keeps_old_url_and_never_reuses(client, H, fresh_doc, publish):
    row = publish(fresh_doc())
    new = "renamed-" + uuid.uuid4().hex[:6]
    assert client.post(f"/api/v1/admin/problems/{row['problem_id']}/slug", json={"slug": new}, headers=H("editor")).status_code == 200
    old = client.get(f"/api/v1/problems/{row['slug']}").json()
    assert old["slug"] == new and old["canonical_url"] == f"/problems/{new}"
    other = publish(fresh_doc())
    r = client.post(f"/api/v1/admin/problems/{other['problem_id']}/slug", json={"slug": row["slug"]}, headers=H("editor"))
    assert r.status_code == 409


def test_dashboard_aggregates_only(client, H):
    d = client.get("/api/v1/admin/dashboard", headers=H("reviewer")).json()
    assert "revisions_by_status" in d and "published" in d["revisions_by_status"]
    assert client.get("/api/v1/admin/dashboard", headers=H("student")).status_code == 403
