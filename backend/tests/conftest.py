import copy
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
_tmp = tempfile.mkdtemp(prefix="leetmath-test-")
# Set LEETMATH_TEST_DATABASE_URL=postgresql+psycopg2://… to run the suite against PostgreSQL.
os.environ["LEETMATH_DATABASE_URL"] = os.environ.get("LEETMATH_TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["LEETMATH_STORAGE_DIR"] = f"{_tmp}/objects"
os.environ["LEETMATH_RATE_LIMIT_PER_MIN"] = "100000"
os.environ.setdefault("LEETMATH_ENV", "test")
os.environ.setdefault("LEETMATH_COOKIE_SECURE", "0")
os.environ.setdefault("LEETMATH_CSRF_SECRET", "leetmath-test-csrf-secret-at-least-32-chars")

from fastapi.testclient import TestClient  # noqa: E402

from leetmath import cli  # noqa: E402
from leetmath.app import create_app  # noqa: E402

PASSWORDS = {"admin": "admin-pass-123", "editor": "editor-pass-123", "reviewer": "reviewer-pass-123",
             "rights": "rights-pass-123", "ops": "ops-pass-123", "auditor": "auditor-pass-123",
             "student": "student-pass-123", "student2": "student-pass-123"}


@pytest.fixture(scope="session")
def app():
    cli.seed(reset=True)
    return create_app()


@pytest.fixture(scope="session")
def client(app):
    return TestClient(app)


@pytest.fixture(scope="session")
def tokens(client):
    out = {}
    for u, pw in PASSWORDS.items():
        r = client.post("/api/v1/auth/token", json={"username": u, "password": pw})
        assert r.status_code == 200, r.text
        out[u] = r.json()["token"]
    return out


@pytest.fixture(scope="session")
def H(tokens):
    def headers(user: str, **extra):
        h = {"Authorization": f"Bearer {tokens[user]}"}
        h.update({k.replace("_", "-"): v for k, v in extra.items()})
        return h
    return headers


def load_fixture(name: str) -> dict:
    return json.loads((ROOT / "fixtures" / "positive" / name).read_text("utf-8"))


@pytest.fixture()
def fresh_doc():
    """A positive fixture with a fresh identity, so tests can mutate state without collisions."""
    def make(name: str = "LM-SH-000005.json", region: str = "CN-SH") -> dict:
        d = copy.deepcopy(load_fixture(name))
        tag = uuid.uuid4().hex[:8]
        d["problem"].pop("display_id", None)
        d["problem"]["slug"] = f"t-{tag}"
        d["revision"]["title"] += f" #{tag}"
        d["revision"]["content_metadata"]["region_hints"] = [region]
        d["source_record_refs"][0]["external_id"] = f"test-{tag}"
        return d
    return make


@pytest.fixture()
def publish(client, H):
    """Create + review + publish a document through the real API; returns the admin revision row."""
    def run(doc: dict) -> dict:
        r = client.post("/api/v1/admin/problems", json={"document": doc}, headers=H("editor"))
        assert r.status_code == 201, r.text
        rid = r.json()["revision_id"]
        for user, path in [("editor", "submit-review"), ("reviewer", "approve"), ("rights", "approve"), ("reviewer", "publish")]:
            rr = client.post(f"/api/v1/admin/problem-revisions/{rid}/{path}", json={}, headers=H(user))
            assert rr.status_code == 200, (path, rr.text)
        return rr.json()
    return run
