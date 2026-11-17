"""Phase 1.5 Reasoning Practice (docs/reasoning-practice/ALGORITHMS.md §7 unit-test list)."""
import uuid
from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from leetmath.db import session_scope
from leetmath.models import Evaluation, StepReviewState, User


def _register_bearer(app, prefix):
    username = prefix + uuid.uuid4().hex[:6]
    password = "longenough1"
    with TestClient(app) as browser:
        csrf = browser.get("/api/v1/auth/csrf").json()["csrf_token"]
        registered = browser.post(
            "/api/v1/auth/register",
            json={"username": username, "password": password},
            headers={"X-CSRF-Token": csrf},
        )
        assert registered.status_code == 201, registered.text
        token_response = browser.post(
            "/api/v1/auth/token",
            json={"username": username, "password": password},
        )
        assert token_response.status_code == 200, token_response.text
        return username, token_response.json()["token"]


def _start(client, H, user="student", slug="function-x-log-x-minus-a-x"):
    rid = client.get(f"/api/v1/problems/{slug}").json()["current_revision"]["id"]
    r = client.post("/api/v1/learning/attempts", json={"problem_revision_id": rid, "mode": "full"}, headers=H(user))
    assert r.status_code == 201, r.text
    return r.json()


def _rate(client, H, att, card, rating, user="student", eid=None):
    return client.post(f"/api/v1/learning/attempts/{att}/step-reviews",
                       json={"event_id": eid or uuid.uuid4().hex, "step_id": card["step_id"], "rating": rating}, headers=H(user))


def test_catalog_lists_problems_with_steps(client):
    items = client.get("/api/v1/learning/catalog").json()["items"]
    assert {"LM-SH-000001", "LM-SH-000008", "LM-SH-000012"} <= {i["display_id"] for i in items}


def test_score_conservation_and_hidden_references(client, H):
    v = _start(client, H)
    assert Decimal(v["self_recall_max"]) == Decimal("14.00")  # Σ step points = Σ part max scores
    assert all("reference_latex" not in c for c in v["cards"])   # nothing revealed before rating
    assert v["score_label"].startswith("主观自评")


def test_full_session_scoring_xp_schedule_and_profile(app, client):
    username, token = _register_bearer(app, "rp")
    hdr = {"Authorization": f"Bearer {token}"}
    rid = client.get("/api/v1/problems/function-x-log-x-minus-a-x").json()["current_revision"]["id"]
    v = client.post("/api/v1/learning/attempts", json={"problem_revision_id": rid}, headers=hdr).json()
    ratings = ["know", "fuzzy", "unsure", "know", "know", "fuzzy", "know", "unsure"]
    total_xp = 0
    for card, rating in zip(v["cards"], ratings, strict=True):
        r = client.post(f"/api/v1/learning/attempts/{v['attempt_id']}/step-reviews",
                        json={"event_id": uuid.uuid4().hex, "step_id": card["step_id"], "rating": rating}, headers=hdr).json()
        assert r["reference_latex"]  # revealed after commit
        expected = (Decimal(card["max_points"]) * {"know": Decimal(1), "fuzzy": Decimal("0.45"), "unsure": Decimal(0)}[rating]).quantize(Decimal("0.01"))
        assert Decimal(r["self_score"]) == expected
        total_xp += r["xp_awarded"]
        assert r["xp_awarded"] == 5 + min(5, int(Decimal(card["max_points"])))  # independent of rating
    v2 = client.get(f"/api/v1/learning/attempts/{v['attempt_id']}", headers=hdr).json()
    # 1 + 0.9 + 0 + 2 + 1 + 1.35 + 1 + 0 = 7.25
    assert Decimal(v2["self_recall_score"]) == Decimal("7.25")
    fb = client.post(f"/api/v1/learning/attempts/{v['attempt_id']}/knowledge-feedback",
                     json={"levels": {c: 3 for c in v2["knowledge_codes"]}}, headers=hdr)
    assert fb.status_code == 200 and fb.json()["state"] == "completed"
    prof = client.get("/api/v1/learning/profile", headers=hdr).json()
    assert prof["xp_total"] == total_xp and prof["reviews_total"] == 8
    assert "非考试正确率" in prof["label"]
    assert all(k["low_sample"] in (True, False) and 0 <= k["evidence_index"] <= 100 for k in prof["knowledge"])
    assert prof["weak_key_steps"]  # the fuzzy/unsure key steps show up
    # self-ratings never become official evaluations
    with session_scope() as s:
        uid = s.query(User).filter_by(username=username).one().id
        from leetmath.models import Submission
        assert s.query(Submission).filter_by(user_id=uid).count() == 0
        assert s.query(Evaluation).join(Submission, Evaluation.submission_id == Submission.id).filter(Submission.user_id == uid).count() == 0


def test_order_enforced_and_append_only(client, H):
    v = _start(client, H, user="student2")
    c0, c1 = v["cards"][0], v["cards"][1]
    r = _rate(client, H, v["attempt_id"], c1, "know", user="student2")
    assert r.status_code == 422  # cannot jump to a future answer
    eid = uuid.uuid4().hex
    assert _rate(client, H, v["attempt_id"], c0, "know", user="student2", eid=eid).status_code == 200
    again = _rate(client, H, v["attempt_id"], c0, "know", user="student2", eid=eid).json()
    assert again["replayed"] is True and again["xp_awarded"] == 0   # idempotent, no double XP
    conflict = _rate(client, H, v["attempt_id"], c0, "unsure", user="student2", eid=eid)
    assert conflict.status_code == 409
    rerate = _rate(client, H, v["attempt_id"], c0, "unsure", user="student2")
    assert rerate.status_code == 409  # ratings are append-only within an attempt


def test_xp_once_per_step_per_day(client, H):
    v1 = _start(client, H, slug="cubic-tangent-and-extrema")
    first = _rate(client, H, v1["attempt_id"], v1["cards"][0], "know").json()
    v2 = _start(client, H, slug="cubic-tangent-and-extrema")
    second = _rate(client, H, v2["attempt_id"], v2["cards"][0], "know").json()
    assert first["xp_awarded"] >= 0 and second["xp_awarded"] == 0


def test_invalid_rating_and_ownership(client, H):
    v = _start(client, H)
    r = client.post(f"/api/v1/learning/attempts/{v['attempt_id']}/step-reviews",
                    json={"event_id": uuid.uuid4().hex, "step_id": v["cards"][0]["step_id"], "rating": "maybe"}, headers=H("student"))
    assert r.status_code == 422
    assert client.get(f"/api/v1/learning/attempts/{v['attempt_id']}", headers=H("student2")).status_code == 404


def test_due_queue_with_sibling_burial(app, client):
    username, token = _register_bearer(app, "due")
    hdr = {"Authorization": f"Bearer {token}"}
    rid = client.get("/api/v1/problems/ellipse-focal-chord-area").json()["current_revision"]["id"]
    v = client.post("/api/v1/learning/attempts", json={"problem_revision_id": rid}, headers=hdr).json()
    for c in v["cards"]:
        client.post(f"/api/v1/learning/attempts/{v['attempt_id']}/step-reviews",
                    json={"event_id": uuid.uuid4().hex, "step_id": c["step_id"], "rating": "unsure"}, headers=hdr)
    assert client.post("/api/v1/learning/attempts", json={"mode": "due"}, headers=hdr).status_code == 404  # due tomorrow
    with session_scope() as s:  # time-travel: make everything due
        uid = s.query(User).filter_by(username=reg["user"]["username"]).one().id
        for st in s.query(StepReviewState).filter_by(user_id=uid):
            st.due_at = st.due_at - timedelta(days=2)
    due = client.post("/api/v1/learning/attempts", json={"mode": "due"}, headers=hdr).json()
    parts = [c["part_id"] for c in due["cards"]]
    assert len(parts) == len(set(parts)) == 3  # one card per part (7 steps across 3 parts)
