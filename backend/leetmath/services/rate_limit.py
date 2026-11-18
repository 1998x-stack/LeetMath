"""Atomic shared rate limiting (Redis sliding window) with dev-only local fallback."""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from collections import defaultdict, deque

from ..config import settings
from .errors import ApiError

_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local window_ms = tonumber(ARGV[1]) * 1000
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window_ms)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
  local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry_ms = window_ms
  if first[2] then retry_ms = math.max(1, tonumber(first[2]) + window_ms - now) end
  return {0, math.ceil(retry_ms / 1000)}
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window_ms + 1000)
return {1, 0}
"""


class RateLimiter:
    def __init__(self, redis_url: str | None = None, *, production: bool | None = None):
        self.redis_url = settings.redis_url if redis_url is None else redis_url
        self.production = settings.environment == "production" if production is None else production
        self._redis = None
        self._local: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        if self.redis_url:
            try:
                from redis import Redis
                self._redis = Redis.from_url(
                    self.redis_url, decode_responses=True,
                    socket_connect_timeout=1, socket_timeout=1, health_check_interval=30,
                )
            except Exception as exc:
                raise ApiError("RATE_LIMIT_BACKEND_UNAVAILABLE", "rate limit backend unavailable", status=503) from exc

    def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("limit and window_seconds must be positive")
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        if self._redis is not None:
            redis_key = "leetmath:ratelimit:v1:" + digest
            try:
                allowed, retry_after = self._redis.eval(
                    _LUA, 1, redis_key, window_seconds, limit, uuid.uuid4().hex
                )
            except Exception as exc:
                # Never silently fall back to per-process buckets when Redis was configured:
                # that would turn a partial outage into a distributed bypass.
                raise ApiError("RATE_LIMIT_BACKEND_UNAVAILABLE", "rate limit backend unavailable", status=503) from exc
            if int(allowed) == 0:
                raise ApiError("RATE_LIMITED", "too many requests, slow down",
                                {"retry_after_s": max(1, int(retry_after))})
            return

        if self.production:
            raise ApiError("RATE_LIMIT_BACKEND_UNAVAILABLE", "shared rate limit backend is required", status=503)
        # Explicit development/test fallback only. This is intentionally process-local.
        now = time.monotonic()
        with self._lock:
            bucket = self._local[digest]
            while bucket and now - bucket[0] >= window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                retry = int(window_seconds - (now - bucket[0])) + 1
                raise ApiError("RATE_LIMITED", "too many requests, slow down", {"retry_after_s": max(1, retry)})
            bucket.append(now)

    def close(self) -> None:
        if self._redis is not None:
            self._redis.close()


_default_limiter: RateLimiter | None = None
_default_lock = threading.Lock()


def get_limiter() -> RateLimiter:
    global _default_limiter
    if _default_limiter is None:
        with _default_lock:
            if _default_limiter is None:
                _default_limiter = RateLimiter()
    return _default_limiter


def rate_limit(key: str, per_minute: int | None = None) -> None:
    get_limiter().check(key, per_minute or settings.rate_limit_per_minute)
