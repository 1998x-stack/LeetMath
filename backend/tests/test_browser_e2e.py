"""Real-browser regression coverage for N2 (mobile math layout + teacher CMS auth)."""
from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

pytestmark = pytest.mark.skipif(
    os.environ.get("LEETMATH_RUN_BROWSER_TESTS") != "1",
    reason="browser E2E is enabled in the dedicated Playwright CI job",
)

ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts" / "e2e"


@pytest.fixture(scope="module")
def live_server(app):
    """Serve the actual FastAPI + static SPA over HTTP for Chromium."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.setblocking(False)
    host, port = sock.getsockname()
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        if not thread.is_alive():
            raise RuntimeError("uvicorn exited before the browser server became ready")
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("uvicorn did not start within 15 seconds")
    try:
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


def _browser():
    from playwright.sync_api import sync_playwright

    manager = sync_playwright()
    playwright = manager.start()
    try:
        browser = playwright.chromium.launch(headless=True)
    except Exception:
        manager.stop()
        raise
    return manager, playwright, browser


def _no_horizontal_overflow(page):
    return page.evaluate(
        "() => ({width: window.innerWidth, document: document.documentElement.scrollWidth, "
        "body: document.body.scrollWidth})"
    )


def _save_failure(page, name):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(ARTIFACTS / f"{name}-failure.png"), full_page=True)
    except Exception:
        pass


def test_mobile_problem_page_renders_katex_without_viewport_overflow(live_server):
    manager, playwright, browser = _browser()
    context = browser.new_context(viewport={"width": 375, "height": 812}, device_scale_factor=1)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    try:
        response = page.goto(
            live_server + "/problems/function-x-log-x-minus-a-x",
            wait_until="networkidle",
            timeout=30000,
        )
        assert response and response.status == 200
        page.locator(".katex").first.wait_for(state="visible", timeout=15000)
        assert page.get_by_role("heading", name="含参数函数的导数、单调性与不等式").count() == 1
        sizes = _no_horizontal_overflow(page)
        assert sizes["document"] <= sizes["width"], f"mobile document overflow: {sizes}"
        assert sizes["body"] <= sizes["width"], f"mobile body overflow: {sizes}"
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(ARTIFACTS / "problem-mobile-375.png"), full_page=True)
    except Exception:
        _save_failure(page, "problem-mobile-375")
        raise
    finally:
        context.tracing.stop(path=str(ARTIFACTS / "problem-mobile.trace.zip"))
        context.close()
        browser.close()
        manager.stop()


def test_teacher_login_uses_httponly_cookie_and_structured_cms_renders_formula(live_server):
    manager, playwright, browser = _browser()
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    try:
        response = page.goto(live_server + "/login", wait_until="networkidle", timeout=30000)
        assert response and response.status == 200
        page.locator('input[autocomplete="username"]').fill("editor")
        page.locator('input[autocomplete="current-password"]').fill("editor-pass-123")
        page.locator('button[type="submit"]').click()
        page.get_by_role("link", name="后台").wait_for(state="visible", timeout=15000)

        cookies = context.cookies()
        session = next(cookie for cookie in cookies if cookie["name"] == "leetmath_session")
        csrf = next(cookie for cookie in cookies if cookie["name"] == "leetmath_csrf")
        assert session["httpOnly"] is True
        assert session["sameSite"].lower() == "lax"
        assert csrf["httpOnly"] is False
        assert page.evaluate("() => document.cookie").find("leetmath_session") == -1
        assert len(page.evaluate("() => Object.keys(sessionStorage).concat(Object.keys(localStorage))")) == 0

        page.goto(live_server + "/admin/problems", wait_until="networkidle", timeout=30000)
        page.get_by_role("button", name="新建题目").click()
        page.get_by_label("题目标题").wait_for(state="visible", timeout=15000)
        page.get_by_label("题目标题").fill("N2 浏览器验收：含参数函数")
        page.get_by_label("行内公式 LaTeX #2").fill(r"\frac{x^2+1}{x-1}")
        page.locator(".cms-preview .katex").first.wait_for(state="visible", timeout=15000)
        page.set_viewport_size({"width": 375, "height": 812})
        sizes = _no_horizontal_overflow(page)
        assert sizes["document"] <= sizes["width"], f"mobile CMS document overflow: {sizes}"
        assert sizes["body"] <= sizes["width"], f"mobile CMS body overflow: {sizes}"
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(ARTIFACTS / "teacher-cms-mobile-375.png"), full_page=True)
        page.get_by_role("button", name="保存草稿").click()
        page.get_by_text("已保存（版本锁", exact=False).wait_for(state="visible", timeout=15000)
    except Exception:
        _save_failure(page, "teacher-cms")
        raise
    finally:
        context.tracing.stop(path=str(ARTIFACTS / "teacher-cms.trace.zip"))
        context.close()
        browser.close()
        manager.stop()
