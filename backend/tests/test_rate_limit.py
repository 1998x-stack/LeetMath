import os
import uuid

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
