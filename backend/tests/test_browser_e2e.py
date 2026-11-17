"""Real-browser regression coverage for N2: math layout, CMS workflow and auth."""
from __future__ import annotations

import json
import os
import re
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
    return manager, browser


def _login(page, base_url, username, password):
    response = page.goto(base_url + "/login", wait_until="networkidle", timeout=30000)
    assert response and response.status == 200
    page.locator('input[autocomplete="username"]').fill(username)
    page.locator('input[autocomplete="current-password"]').fill(password)
    page.locator('button[type="submit"]').click()
    page.get_by_role("link", name="后台").wait_for(state="visible", timeout=15000)


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
    manager, browser = _browser()
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
        page.screenshot(path=str(ARTIFACTS / "problem-mobile-375.png"), full_page=True)
    except Exception:
        _save_failure(page, "problem-mobile-375")
        raise
    finally:
        context.tracing.stop(path=str(ARTIFACTS / "problem-mobile.trace.zip"))
        context.close()
        browser.close()
        manager.stop()


def test_teacher_full_review_publish_revision_and_cookie_flow(live_server):
    manager, browser = _browser()
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    editor_page = context.new_page()
    reviewer_context = browser.new_context(viewport={"width": 1280, "height": 900})
    rights_context = browser.new_context(viewport={"width": 1280, "height": 900})
    reviewer_page = reviewer_context.new_page()
    rights_page = rights_context.new_page()
    try:
        _login(editor_page, live_server, "editor", "editor-pass-123")
        cookies = context.cookies()
        session = next(cookie for cookie in cookies if cookie["name"] == "leetmath_session")
        csrf = next(cookie for cookie in cookies if cookie["name"] == "leetmath_csrf")
        assert session["httpOnly"] is True
        assert session["sameSite"].lower() == "lax"
        assert csrf["httpOnly"] is False
        assert csrf["sameSite"].lower() == "strict"
        assert "leetmath_session" not in editor_page.evaluate("() => document.cookie")
        assert len(editor_page.evaluate("() => Object.keys(sessionStorage).concat(Object.keys(localStorage))")) == 0

        editor_page.goto(live_server + "/admin/problems", wait_until="networkidle", timeout=30000)
        editor_page.get_by_role("button", name="新建题目").click()
        editor_page.get_by_label("题目标题").wait_for(state="visible", timeout=15000)
        revision_id = re.search(r"/admin/edit/([^/?#]+)", editor_page.url).group(1)

        # Inject a valid table block through advanced JSON, switch to the form and back,
        # and verify that unsupported rich media is preserved losslessly.
        editor_page.get_by_label("编辑模式").select_option(label="高级 JSON")
        raw = editor_page.locator('textarea[aria-label="题目 Content Contract JSON"]')
        document = json.loads(raw.input_value())
        document["revision"]["shared_statement"]["blocks"].append({
            "type": "table",
            "rows": [[ [{"type": "text", "text": "e2e-table-preserved"}] ]],
        })
        raw.fill(json.dumps(document, ensure_ascii=False, indent=2))
        editor_page.get_by_label("编辑模式").select_option(label="结构化表单")
        editor_page.get_by_text("该区块仅预览，数据保持不变", exact=False).wait_for(state="visible")
        editor_page.get_by_label("编辑模式").select_option(label="高级 JSON")
        assert "e2e-table-preserved" in raw.input_value()
        editor_page.get_by_label("编辑模式").select_option(label="结构化表单")

        # Edit title, MathRichText, standard answer; verify safe text rendering (no HTML execution).
        xss_text = 'E2E 正文 <img src=x onerror=window.__leetmathXss=1>'
        editor_page.get_by_label("题目标题").fill("N2 浏览器验收：<img src=x onerror=window.__leetmathXss=1>")
        editor_page.get_by_label("正文 #1").first.fill(xss_text)
        assert editor_page.locator('.cms-preview img[src="x"]').count() == 0
        assert editor_page.evaluate("() => window.__leetmathXss || null") is None
        editor_page.get_by_label("正文 #1").first.fill("已知函数 ")
        editor_page.get_by_label("行内公式 LaTeX #2").fill(r"\frac{x^2+1}{x-1}")
        editor_page.get_by_label("参考答案 · expected").fill("2x - 2")
        editor_page.locator(".cms-preview .katex").first.wait_for(state="visible", timeout=15000)
        assert editor_page.locator('.cms-preview img[src="x"]').count() == 0

        editor_page.get_by_role("button", name="预检当前内容").click()
        editor_page.get_by_text("无阻断项", exact=False).wait_for(state="visible", timeout=15000)
        editor_page.get_by_role("button", name="保存草稿").click()
        editor_page.get_by_text("已保存（版本锁", exact=False).wait_for(state="visible", timeout=15000)
        editor_page.get_by_role("button", name="送审").click()
        editor_page.get_by_text("in_math_review", exact=False).wait_for(state="visible", timeout=15000)

        # A different reviewer performs the math gate.
        _login(reviewer_page, live_server, "reviewer", "reviewer-pass-123")
        reviewer_page.goto(live_server + f"/admin/edit/{revision_id}", wait_until="networkidle")
        reviewer_page.get_by_role("button", name="数学审核通过").click()
        reviewer_page.get_by_text("in_rights_review", exact=False).wait_for(state="visible", timeout=15000)

        # A distinct rights reviewer performs the rights gate.
        _login(rights_page, live_server, "rights", "rights-pass-123")
        rights_page.goto(live_server + f"/admin/edit/{revision_id}", wait_until="networkidle")
        rights_page.get_by_role("button", name="版权审核通过").click()
        rights_page.get_by_text("approved", exact=False).wait_for(state="visible", timeout=15000)

        # Reviewer publishes only after both gates have passed.
        reviewer_page.goto(live_server + f"/admin/edit/{revision_id}", wait_until="networkidle")
        reviewer_page.get_by_role("button", name="发布").click()
        reviewer_page.get_by_text("published", exact=False).wait_for(state="visible", timeout=15000)
        row = reviewer_page.evaluate(
            """async (rid) => {
              const response = await fetch('/api/v1/admin/problem-revisions/' + rid);
              return await response.json();
            }""",
            revision_id,
        )
        assert row["status"] == "published"
        slug = row["slug"]

        # Published revisions are read-only; a new revision keeps the previous version
        # available for a field-level comparison.
        editor_page.goto(live_server + f"/admin/edit/{revision_id}", wait_until="networkidle")
        assert editor_page.get_by_label("题目标题").is_disabled()
        editor_page.get_by_role("button", name="基于此创建新修订").click()
        editor_page.get_by_label("题目标题").wait_for(state="visible", timeout=15000)
        editor_page.get_by_text("相对上一版本的差异", exact=False).wait_for(state="visible", timeout=15000)
        editor_page.get_by_label("题目标题").fill("N2 浏览器验收：含参数函数（修订）")
        editor_page.get_by_text("相对上一版本的差异 · 1 处", exact=False).wait_for(state="visible", timeout=15000)

        # Public content uses text nodes and KaTeX's trust=false rendering.
        editor_page.goto(live_server + "/problems/" + slug, wait_until="networkidle")
        editor_page.locator(".katex").first.wait_for(state="visible", timeout=15000)
        assert editor_page.locator('img[src="x"]').count() == 0
        assert editor_page.evaluate("() => window.__leetmathXss || null") is None
        editor_page.set_viewport_size({"width": 375, "height": 812})
        sizes = _no_horizontal_overflow(editor_page)
        assert sizes["document"] <= sizes["width"], f"mobile CMS/public page overflow: {sizes}"
        assert sizes["body"] <= sizes["width"], f"mobile body overflow: {sizes}"
        editor_page.screenshot(path=str(ARTIFACTS / "teacher-review-publish-mobile-375.png"), full_page=True)

        # SPA logout/re-login without a document reload exercises the in-memory CSRF reset.
        with editor_page.expect_response(lambda response: response.url.endswith("/api/v1/auth/logout")) as logout_response:
            editor_page.get_by_role("button", name="退出").click()
        assert logout_response.value.status == 204
        editor_page.get_by_role("link", name="登录 / 注册").click()
        editor_page.locator('input[autocomplete="username"]').fill("editor")
        editor_page.locator('input[autocomplete="current-password"]').fill("editor-pass-123")
        editor_page.locator('button[type="submit"]').click()
        editor_page.get_by_role("link", name="后台").wait_for(state="visible", timeout=15000)
        me = editor_page.evaluate(
            """async () => {
              const response = await fetch('/api/v1/me', {credentials: 'same-origin'});
              return response.status;
            }"""
        )
        assert me == 200

    except Exception:
        _save_failure(editor_page, "teacher-review-publish")
        _save_failure(reviewer_page, "reviewer")
        _save_failure(rights_page, "rights-reviewer")
        raise
    finally:
        context.tracing.stop(path=str(ARTIFACTS / "teacher-review-publish.trace.zip"))
        reviewer_context.close()
        rights_context.close()
        context.close()
        browser.close()
        manager.stop()


def test_two_editors_receive_precondition_failure_without_losing_input(live_server):
    manager, browser = _browser()
    first_context = browser.new_context(viewport={"width": 1280, "height": 900})
    second_context = browser.new_context(viewport={"width": 1280, "height": 900})
    first_page = first_context.new_page()
    second_page = second_context.new_page()
    try:
        _login(first_page, live_server, "editor", "editor-pass-123")
        first_page.goto(live_server + "/admin/problems", wait_until="networkidle")
        first_page.get_by_role("button", name="新建题目").click()
        first_page.get_by_label("题目标题").wait_for(state="visible", timeout=15000)
        revision_id = re.search(r"/admin/edit/([^/?#]+)", first_page.url).group(1)

        _login(second_page, live_server, "admin", "admin-pass-123")
        second_page.goto(live_server + f"/admin/edit/{revision_id}", wait_until="networkidle")
        first_page.get_by_label("题目标题").fill("编辑者 A 的版本")
        second_page.get_by_label("题目标题").fill("编辑者 B 的本地输入")
        first_page.get_by_role("button", name="保存草稿").click()
        first_page.get_by_text("已保存（版本锁", exact=False).wait_for(state="visible", timeout=15000)

        statuses = []
        second_page.on(
            "response",
            lambda response: statuses.append(response.status)
            if response.request.method == "PATCH" and "/problem-revisions/" in response.url
            else None,
        )
        second_page.get_by_role("button", name="保存草稿").click()
        second_page.get_by_text("草稿已被他人修改", exact=False).wait_for(state="visible", timeout=15000)
        assert 412 in statuses  # EDIT_CONFLICT is an HTTP precondition failure.
        assert second_page.get_by_label("题目标题").input_value() == "编辑者 B 的本地输入"
    except Exception:
        _save_failure(first_page, "editor-a-conflict")
        _save_failure(second_page, "editor-b-conflict")
        raise
    finally:
        first_context.close()
        second_context.close()
        browser.close()
        manager.stop()
