import hashlib

from fastapi.testclient import TestClient

from leetmath.models import AuthSession
from leetmath.services.security import csrf_cookie_name, session_cookie_name


def test_browser_login_sets_httponly_cookie_and_never_returns_session_token(app):
    with TestClient(app) as browser:
        csrf = browser.get("/api/v1/auth/csrf").json()["csrf_token"]
        response = browser.post(
            "/api/v1/auth/login",
            json={"username": "student", "password": "student-pass-123"},
            headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
        )
        assert response.status_code == 200, response.text
        assert "token" not in response.json()
        assert response.json()["user"]["username"] == "student"
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(value for value in cookies if value.startswith(session_cookie_name() + "="))
        assert "httponly" in session_cookie.lower()
        assert "samesite=lax" in session_cookie.lower()
        assert "path=/" in session_cookie.lower()
        assert browser.get("/api/v1/me").json()["username"] == "student"
        assert browser.cookies.get(session_cookie_name())
        assert browser.cookies.get(csrf_cookie_name())


def test_logout_revokes_session_immediately_and_clears_cookies(app):
    with TestClient(app) as browser:
        csrf = browser.get("/api/v1/auth/csrf").json()["csrf_token"]
        login = browser.post("/api/v1/auth/login",
                             json={"username": "student", "password": "student-pass-123"},
                             headers={"X-CSRF-Token": csrf})
        assert login.status_code == 200
        raw = browser.cookies.get(session_cookie_name())
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        logout = browser.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 204
        assert browser.get("/api/v1/me").status_code == 401
        with TestClient(app) as second:
            assert second.get("/api/v1/me", headers={"Authorization": "Bearer " + raw}).status_code == 401
        # Session row remains as a revocation record; it is not physically deleted.
        from leetmath.db import new_session
        s = new_session()
        try:
            row = s.get(AuthSession, token_hash)
            assert row is not None and row.revoked is True
        finally:
            s.close()


def test_cookie_writes_require_valid_csrf_and_same_origin(app):
    with TestClient(app) as browser:
        login_body = {"username": "student", "password": "student-pass-123"}
        assert browser.post("/api/v1/auth/login", json=login_body).status_code == 403
        csrf = browser.get("/api/v1/auth/csrf").json()["csrf_token"]
        assert browser.post("/api/v1/auth/login", json=login_body,
                            headers={"X-CSRF-Token": "forged"}).status_code == 403
        assert browser.post("/api/v1/auth/login", json=login_body,
                            headers={"X-CSRF-Token": csrf, "Origin": "https://attacker.example"}).status_code == 403
        valid = browser.post("/api/v1/auth/login", json=login_body,
                             headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"})
        assert valid.status_code == 200


def test_explicit_bearer_compatibility_endpoint_remains_available(client):
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post("/api/v1/auth/token",
                           json={"username": "student", "password": "student-pass-123"},
                           headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert response.json()["token"]
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer " + response.json()["token"]}).status_code == 200

def test_reauthentication_rotates_cookie_and_revokes_previous_session(app):
    with TestClient(app) as browser:
        csrf = browser.get("/api/v1/auth/csrf").json()["csrf_token"]
        body = {"username": "student", "password": "student-pass-123"}
        first = browser.post("/api/v1/auth/login", json=body, headers={"X-CSRF-Token": csrf})
        assert first.status_code == 200
        old_token = browser.cookies.get(session_cookie_name())
        second = browser.post("/api/v1/auth/login", json=body, headers={"X-CSRF-Token": csrf})
        assert second.status_code == 200
        new_token = browser.cookies.get(session_cookie_name())
        assert old_token and new_token and old_token != new_token
        assert browser.get("/api/v1/me").status_code == 200
        with TestClient(app) as stale_client:
            stale = stale_client.get("/api/v1/me", headers={"Authorization": "Bearer " + old_token})
            assert stale.status_code == 401

