"""Process-isolated execution for CAS work (docs/06 §3, docs/11 §3).

Each grading call forks a child with RLIMIT_AS / RLIMIT_CPU, no inherited sockets used, and a
wall-clock timeout. SymPy is not itself a sandbox; the parser never evaluates code, and this
process boundary bounds resource exhaustion (huge expressions, pathological simplify).
Production: run the same entrypoint inside a network-less container.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import resource
from decimal import Decimal

from ..config import settings
from .checkers import GradeResult, _sandbox_entry, pending


def _child(conn, payload, mem_mb: int, cpu_s: int):  # pragma: no cover - runs in child
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
    except (ValueError, OSError):
        pass
    try:
        conn.send(("ok", _sandbox_entry(payload)))
    except MemoryError:
        conn.send(("err", "MEMORY_LIMIT"))
    except Exception as e:  # noqa: BLE001
        conn.send(("err", f"{type(e).__name__}"))
    finally:
        conn.close()
        os._exit(0)


_CTX = None


def _context():
    """forkserver: children fork from a clean single-threaded server (never from the threaded web
    process), with SymPy preloaded so each grading call stays cheap."""
    global _CTX
    if _CTX is None:
        method = os.environ.get("LEETMATH_SANDBOX_START", "forkserver")
        _CTX = mp.get_context(method)
        if method == "forkserver":
            _CTX.set_forkserver_preload(["leetmath.grading.sandbox", "sympy"])
    return _CTX


def run_sandboxed(payload: dict, timeout_s: float | None = None) -> GradeResult:
    timeout_s = timeout_s or settings.grader_timeout_s
    max_score = Decimal(payload["max_score"])
    ctx = _context()
    parent, child = ctx.Pipe(duplex=False)
    p = ctx.Process(
        target=_child, args=(child, payload, settings.grader_memory_mb, int(timeout_s) + 1), daemon=True
    )
    p.start()
    child.close()
    try:
        if parent.poll(timeout_s):
            kind, value = parent.recv()
        else:
            kind, value = "timeout", None
    except EOFError:
        kind, value = "err", "CRASHED"
    finally:
        if p.is_alive():
            p.kill()
        p.join(1)
        parent.close()
    if kind == "ok":
        return GradeResult(**value)
    if kind == "timeout":
        return pending(max_score, "MATH_PARSER_TIMEOUT", "判题超时，已转人工复核（不计为错误）")
    if value == "MEMORY_LIMIT":
        return pending(max_score, "RESOURCE_LIMIT", "表达式过于复杂，已转人工复核")
    return GradeResult("engine_error", None, str(max_score.quantize(Decimal("0.01"))), "GRADER_UNAVAILABLE",
                       "判题引擎异常（不计为错误）", {"reason": value})
