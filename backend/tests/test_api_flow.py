"""End-to-end API flows mapped to docs/01 AC-001…AC-008 and docs/09 acceptance."""
import uuid


def test_health_and_catalog(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    r = client.get("/api/v1/problems")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 13
    assert items[0]["display_id"] == "LM-SH-000001"


def test_ac001_problem_detail_multi_part_with_attribution(client):
    d = client.get("/api/v1/problems/function-x-log-x-minus-a-x").json()
    rev = d["current_revision"]
    assert [p["part_key"] for p in rev["parts"]] == ["1", "2", "3"]
    assert rev["total_score"] == "14.00"
    assert rev["source_attribution"], "every public problem shows its source"
    # hidden grading config never leaks to the public
    blob = str(d)
    assert "canonical_expr" not in blob and "golden_cases" not in blob and "expected" not in blob
    # solutions are locked until the student submits (after_submit policy)
    assert all("solutions" not in p for p in rev["parts"])


def test_lookup_by_display_id(client):
    assert client.get("/api/v1/problems/LM-SH-000003").status_code == 200


def test_anonymous_cannot_submit(client):
    d = client.get("/api/v1/problems/log-function-domain-choice").json()
    r = client.post("/api/v1/attempts", json={"problem_revision_id": d["current_revision"]["id"]})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_REQUIRED"
    assert r.json()["error"]["request_id"]


def _attempt(client, H, slug, user="student"):
    d = client.get(f"/api/v1/problems/{slug}", headers=H(user)).json()
    rev = d["current_revision"]
    r = client.post("/api/v1/attempts", json={"problem_revision_id": rev["id"]}, headers=H(user))
    assert r.status_code == 201, r.text
    return r.json()["attempt_id"], rev


def _submit(client, H, att, part_id, text, user="student", key=None):
    return client.post(f"/api/v1/attempts/{att}/submissions",
                       json={"revision_part_id": part_id, "response": {"input": text}},
                       headers=H(user, Idempotency_Key=key or uuid.uuid4().hex))


def test_submit_expression_accepted_and_solutions_unlock(client, H):
    att, rev = _attempt(client, H, "function-x-log-x-minus-a-x")
    p1 = rev["parts"][0]
    r = _submit(client, H, att, p1["id"], "\\ln x - (a-1)")
    assert r.status_code == 200, r.text
    ev = r.json()["evaluation"]
    assert ev["status"] == "accepted" and ev["score"] == "3.00"
    d = client.get("/api/v1/problems/function-x-log-x-minus-a-x", headers=H("student")).json()
    assert "solutions" in d["current_revision"]["parts"][0]
    assert "solutions" not in d["current_revision"]["parts"][1]


def test_proof_goes_to_pending_review_not_wrong(client, H):
    att, rev = _attempt(client, H, "function-x-log-x-minus-a-x")
    r = _submit(client, H, att, rev["parts"][2]["id"], "由第二问最小值可得……")
    ev = r.json()["evaluation"]
    assert ev["status"] == "pending_review" and ev["score"] is None and not ev["is_math_verdict"]
    mistakes = client.get("/api/v1/me/mistakes", headers=H("student")).json()["items"]
    assert rev["parts"][2]["id"] not in {m["revision_part_id"] for m in mistakes}


def test_invalid_input_is_not_a_mistake(client, H):
    att, rev = _attempt(client, H, "cubic-tangent-and-extrema")
    r = _submit(client, H, att, rev["parts"][0]["id"], "import os")
    assert r.json()["evaluation"]["status"] == "invalid_response"
    mistakes = client.get("/api/v1/me/mistakes", headers=H("student")).json()["items"]
    assert rev["parts"][0]["id"] not in {m["revision_part_id"] for m in mistakes}


def test_rejected_creates_mistake_and_partial_not_completed(client, H):
    att, rev = _attempt(client, H, "odd-functions-multiple-choice", user="student2")
    r = _submit(client, H, att, rev["parts"][0]["id"], "A,B", user="student2")
    ev = r.json()["evaluation"]
    assert ev["status"] == "partial" and ev["score"] == "4.00"
    mistakes = client.get("/api/v1/me/mistakes", headers=H("student2")).json()["items"]
    assert rev["parts"][0]["id"] in {m["revision_part_id"] for m in mistakes}
    d = client.get("/api/v1/problems/odd-functions-multiple-choice", headers=H("student2")).json()
    assert d["progress"]["completed"] is False


def test_idempotent_submission(client, H):
    att, rev = _attempt(client, H, "arithmetic-sequence-basics")
    pid = rev["parts"][0]["id"]
    key = uuid.uuid4().hex
    a = _submit(client, H, att, pid, "39", key=key).json()
    b = _submit(client, H, att, pid, "39", key=key).json()
    assert a["submission_id"] == b["submission_id"] and b["replayed"] is True
    c = _submit(client, H, att, pid, "40", key=key)
    assert c.status_code == 409 and c.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    subs = client.get("/api/v1/me/submissions?limit=100", headers=H("student")).json()["items"]
    assert sum(1 for x in subs if x["id"] == a["submission_id"]) == 1


def test_part_must_belong_to_attempt(client, H):
    att, _ = _attempt(client, H, "arithmetic-sequence-basics")
    other = client.get("/api/v1/problems/draw-two-balls-probability").json()["current_revision"]["parts"][0]["id"]
    r = _submit(client, H, att, other, "3/10")
    assert r.status_code == 422


def test_idor_other_students_data(client, H):
    att, rev = _attempt(client, H, "draw-two-balls-probability", user="student")
    sub = _submit(client, H, att, rev["parts"][0]["id"], "3/10").json()
    # student2 cannot read student's submission or use student's attempt
    assert client.get(f"/api/v1/submissions/{sub['submission_id']}", headers=H("student2")).status_code == 404
    assert _submit(client, H, att, rev["parts"][0]["id"], "3/10", user="student2").status_code == 404
    # each user's history only contains their own rows
    mine = client.get("/api/v1/me/submissions?limit=100", headers=H("student2")).json()["items"]
    assert sub["submission_id"] not in {x["id"] for x in mine}


def test_bookmarks(client, H):
    pid = client.get("/api/v1/problems/LM-SH-000009").json()["id"]
    assert client.put(f"/api/v1/me/bookmarks/{pid}", headers=H("student")).status_code == 204
    assert client.put(f"/api/v1/me/bookmarks/{pid}", headers=H("student")).status_code == 204  # idempotent
    items = client.get("/api/v1/me/bookmarks", headers=H("student")).json()["items"]
    assert [i["problem_id"] for i in items].count(pid) == 1
    assert client.delete(f"/api/v1/me/bookmarks/{pid}", headers=H("student")).status_code == 204


def test_ac007_stable_pagination_and_filters(client):
    seen, cursor = [], None
    while True:
        url = "/api/v1/problems?limit=4&sort=difficulty_desc" + (f"&cursor={cursor}" if cursor else "")
        body = client.get(url).json()
        seen += [i["id"] for i in body["items"]]
        if not body["has_more"]:
            break
        cursor = body["next_cursor"]
    full = [i["id"] for i in client.get("/api/v1/problems?limit=100&sort=difficulty_desc").json()["items"]]
    assert seen == full and len(set(seen)) == len(seen)
    diffs = [i["difficulty"] for i in client.get("/api/v1/problems?limit=100&sort=difficulty_desc").json()["items"]]
    assert diffs == sorted(diffs, reverse=True)
    r = client.get("/api/v1/problems?difficulty_min=4&difficulty_max=5&response_type=expression").json()["items"]
    assert r and all(4 <= i["difficulty"] <= 5 and "expression" in i["response_types"] for i in r)


def test_pagination_updated_desc_cursor(client):
    a = client.get("/api/v1/problems?limit=5&sort=updated_desc").json()
    b = client.get(f"/api/v1/problems?limit=5&sort=updated_desc&cursor={a['next_cursor']}").json()
    assert not set(i["id"] for i in a["items"]) & set(i["id"] for i in b["items"])


def test_search_relevance_and_knowledge_filter(client):
    r = client.get("/api/v1/problems?query=LM-SH-000008").json()["items"]
    assert r[0]["display_id"] == "LM-SH-000008"
    r = client.get("/api/v1/problems", params={"query": "椭圆"}).json()["items"]
    assert any(i["display_id"] == "LM-SH-000008" for i in r)
    tree = client.get("/api/v1/knowledge").json()["releases"][0]["nodes"]
    deriv = next(n for n in tree if n["code"] == "DERIVATIVES")  # parent chapter
    ids = {i["display_id"] for i in client.get(f"/api/v1/problems?knowledge_id={deriv['id']}").json()["items"]}
    assert {"LM-SH-000001", "LM-SH-000012"} <= ids
    assert client.get("/api/v1/problems?query=zzzz-no-hit").json()["items"] == []


def test_collections_and_progress(client, H):
    cols = client.get("/api/v1/collections").json()["items"]
    c = client.get(f"/api/v1/collections/{cols[0]['id']}").json()
    assert c["items"] and [i["ordinal"] for i in c["items"]] == sorted(i["ordinal"] for i in c["items"])
    prog = client.get("/api/v1/me/progress", headers=H("student")).json()
    assert "knowledge" in prog and all("low_sample" in k for k in prog["knowledge"])


def test_content_report_flow(client, H):
    d = client.get("/api/v1/problems/LM-SH-000010").json()
    r = client.post("/api/v1/content-reports", json={"problem_revision_id": d["current_revision"]["id"],
                                                     "revision_part_id": d["current_revision"]["parts"][1]["id"],
                                                     "kind": "ambiguous", "description": "端点表述不清"}, headers=H("student"))
    assert r.status_code == 201
    rid = r.json()["id"]
    assert client.get(f"/api/v1/content-reports/{rid}", headers=H("student2")).status_code == 404
    rr = client.post(f"/api/v1/admin/content-reports/{rid}/resolve",
                     json={"state": "resolved", "resolution": "wording_clarified", "public_note": "已在新版本中澄清",
                           "internal_note": "内部讨论：…"}, headers=H("reviewer"))
    assert rr.status_code == 200
    mine = client.get(f"/api/v1/content-reports/{rid}", headers=H("student")).json()
    assert mine["state"] == "resolved" and mine["public_note"] and "internal_note" not in mine


def test_security_headers_and_error_shape(client):
    r = client.get("/api/v1/problems/does-not-exist")
    assert r.status_code == 404
    assert set(r.json()["error"]) == {"code", "message", "request_id", "details"}
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_register_login(client):
    name = "u" + uuid.uuid4().hex[:8]
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    r = client.post("/api/v1/auth/register", json={"username": name, "password": "longenough1"}, headers=headers)
    assert r.status_code == 201 and r.json()["user"]["roles"] == ["student"]
    assert "token" not in r.json()
    bad = client.post("/api/v1/auth/login", json={"username": name, "password": "wrongwrong"}, headers=headers)
    assert bad.status_code == 401
