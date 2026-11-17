import multiprocessing
import os
import socket
import time
import uuid

import httpx

import pytest

from leetmath.services.errors import ApiError
from leetmath.services.rate_limit import RateLimiter


def test_two_independent_limiter_instances_share_atomic_redis_window():
    redis_url = os.environ.get("LEETMATH_REDIS_URL")
    if not redis_url:
        pytest.skip("set LEETMATH_REDIS_URL to exercise cross-process Redis semantics")
    key = "integration:" + uuid.uuid4().hex
    first = RateLimiter(redis_url)
    second = RateLimiter(redis_url)
    try:
        first.check(key, 2)
        second.check(key, 2)
        with pytest.raises(ApiError) as exc:
            first.check(key, 2)
        assert exc.value.code == "RATE_LIMITED"
        assert exc.value.details["retry_after_s"] >= 1
    finally:
        first.close()
        second.close()


def test_production_rate_limit_fails_closed_without_shared_backend():
    limiter = RateLimiter("", production=True)
    with pytest.raises(ApiError) as exc:
        limiter.check("missing-redis", 1)
    assert exc.value.code == "RATE_LIMIT_BACKEND_UNAVAILABLE"
    assert exc.value.status == 503


def test_local_fallback_is_windowed_and_does_not_leak_raw_keys():
    limiter = RateLimiter("", production=False)
    key = "private-user-id:" + uuid.uuid4().hex
    limiter.check(key, 1)
    with pytest.raises(ApiError) as exc:
        limiter.check(key, 1)
    assert exc.value.code == "RATE_LIMITED"
    assert key not in str(limiter._local.keys())

def _serve_api_process(port: int) -> None:
    """Each spawned worker owns an independent Python process and Redis client."""
    import uvicorn

    from leetmath.app import create_app

    uvicorn.run(
        create_app(init_db=False),
        host="127.0.0.1",
        port=port,
        log_level="error",
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_api(url: str, process) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not process.is_alive():
            raise RuntimeError("API worker exited before becoming ready")
        try:
            if httpx.get(url + "/api/health", timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.05)
    raise RuntimeError("API worker did not become ready within 15 seconds")


def test_two_independent_api_processes_share_ip_rate_limit(app):
    """Ten registration writes across two processes; the eleventh is rejected by shared Redis."""
    if not os.environ.get("LEETMATH_REDIS_URL"):
        pytest.skip("set LEETMATH_REDIS_URL to exercise two-process API rate limiting")
    ctx = multiprocessing.get_context("spawn")
    ports = (_free_port(), _free_port())
    processes = [
        ctx.Process(target=_serve_api_process, args=(port,), daemon=True)
        for port in ports
    ]
    clients = []
    try:
        for process in processes:
            process.start()
        urls = [f"http://127.0.0.1:{port}" for port in ports]
        for url, process in zip(urls, processes):
            _wait_for_api(url, process)
        clients = [httpx.Client(base_url=url, timeout=10) for url in urls]
        csrf = [client.get("/api/v1/auth/csrf").json()["csrf_token"] for client in clients]
        forwarded_ip = "198.51.100.77"
        for i in range(10):
            index = i % 2
            response = clients[index].post(
                "/api/v1/auth/register",
                json={"username": "n2r" + uuid.uuid4().hex[:16], "password": "longenough-password"},
                headers={"X-CSRF-Token": csrf[index], "X-Forwarded-For": forwarded_ip},
            )
            assert response.status_code == 201, response.text
        blocked = clients[1].post(
            "/api/v1/auth/register",
            json={"username": "n2r" + uuid.uuid4().hex[:16], "password": "longenough-password"},
            headers={"X-CSRF-Token": csrf[1], "X-Forwarded-For": forwarded_ip},
        )
        assert blocked.status_code == 429, blocked.text
        assert blocked.headers.get("Retry-After")
        assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    finally:
        for client in clients:
            client.close()
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=10)


def test_configured_but_unreachable_redis_fails_closed():
    limiter = RateLimiter("redis://127.0.0.1:1/0", production=True)
    try:
        with pytest.raises(ApiError) as exc:
            limiter.check("redis-outage:" + uuid.uuid4().hex, 1)
        assert exc.value.code == "RATE_LIMIT_BACKEND_UNAVAILABLE"
        assert exc.value.status == 503
    finally:
        limiter.close()

