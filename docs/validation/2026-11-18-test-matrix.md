# 测试矩阵与执行结果｜2026-11-18（Pi Agent 本机验收）

基线 `08caab892daded21139a91b05fa461460d7ff0e1`（PR #5 head）→ 修复分支
`fix/pi-local-n2-validation-20261118` @ `8a15ffc`（本文件所在提交之前的最后一个代码提交）。

所有命令均在仓库根目录或注明的工作目录执行；`LEETMATH_REDIS_URL=redis://127.0.0.1:16379/0`（隔离 Redis），
数据库连接见各行。

## 1. 静态与契约

| # | 检查 | 命令（含工作目录） | 结果 | 退出码 |
|---|---|---|---|---|
| 1 | Python 编译 | `.venv/bin/python -m compileall -q backend/leetmath backend/tests` | 无输出 | 0 |
| 2 | Ruff（CI 规则集） | `.venv/bin/ruff check --select E4,E7,E9,F821,F822,F823 backend/leetmath backend/tests` | `All checks passed!` | 0 |
| 3 | JS 语法 app | `node --check frontend/app.js` | 通过 | 0 |
| 4 | JS 语法 CMS | `node --check frontend/cms-editor.js` | 通过 | 0 |
| 5 | Node CMS 单测 | `node --test frontend/tests/*.test.cjs` | `pass 7 / fail 0`（修复前 5 个，新增 2 个回归用例） | 0 |
| 6 | 内容契约 | `PYTHONPATH=backend .venv/bin/python -m leetmath.cli validate fixtures/positive` | 13/13 `ok`，`0 blocking, 0 warnings` | 0 |
| 7 | DDL 可复现 | `.venv/bin/python -m leetmath.cli ddl --dialect postgresql \| diff -u docs/generated/schema.postgresql.sql -` | 无差异（671 行） | 0 |
| 8 | OpenAPI 与实现一致 | 见 CI 内联脚本（`create_app().openapi()` 与 `docs/generated/openapi.json` 比对） | `OpenAPI matches: 68 paths` | 0 |

## 2. 数据库与迁移

| # | 检查 | 命令 | 结果 |
|---|---|---|---|
| 9 | SQLite 全量 | `cd backend && python -m pytest -q` | **255 passed, 3 skipped**（11.21s） |
| 10 | PostgreSQL 16 全量 | `cd backend && LEETMATH_TEST_DATABASE_URL=postgresql+psycopg2://leetmath:leetmath@127.0.0.1:15432/leetmath python -m pytest -q` | **255 passed, 3 skipped**（19.56s） |
| 11 | Alembic（隔离 SQLite） | `cd backend && LEETMATH_DATABASE_URL=sqlite:////tmp/lm-alembic-sqlite.db alembic upgrade head && alembic check && alembic downgrade base && alembic upgrade head` | 升/降/再升成功，`No new upgrade operations detected.` |
| 12 | Alembic（隔离 PG16） | 同上，`LEETMATH_DATABASE_URL=postgresql+psycopg2://leetmath:leetmath@127.0.0.1:15432/leetmath_alembic` | 同上 |
| 13 | 数据库口令/演示账号 | Compose 中 `postgres` 口令为本地值；`auth_sessions` 只存 SHA-256（见安全报告） | 仅本地/试点，生产必须替换 |

> 3 个 skipped 全部是 `backend/tests/test_browser_e2e.py` 的浏览器用例（默认关闭，需
> `LEETMATH_RUN_BROWSER_TESTS=1`）。不是被掩盖的失败。

## 3. 浏览器 E2E（真实 Chromium + 真实 Uvicorn + PostgreSQL + Redis）

CI parity 命令（与 `.github/workflows/ci.yml` quality job 相同）：

```bash
LEETMATH_RUN_BROWSER_TESTS=1 LEETMATH_REQUIRE_BROWSER=1 PYTHONPATH=backend \
  .venv/bin/python -m pytest -q backend/tests/test_browser_e2e.py \
  backend/tests/test_auth_security.py backend/tests/test_rate_limit.py
```

| 阶段 | 结果 |
|---|---|
| 修复前（CI Run 44095520961 与本机复现一致） | `1 failed, 12 passed` — strict mode violation on `get_by_label("行内公式 LaTeX #2")` |
| 修复后（本机，最终提交树） | **`13 passed`**（16.27s） |

用例清单（`artifacts/local-validation/2026-11-18/n2-test-inventory.txt`）：

```text
test_browser_e2e.py::test_mobile_problem_page_renders_katex_without_viewport_overflow
test_browser_e2e.py::test_teacher_full_review_publish_revision_and_cookie_flow
test_browser_e2e.py::test_two_editors_receive_precondition_failure_without_losing_input
test_auth_security.py::test_browser_login_sets_httponly_cookie_and_never_returns_session_token
test_auth_security.py::test_logout_revokes_session_immediately_and_clears_cookies
test_auth_security.py::test_cookie_writes_require_valid_csrf_and_same_origin
test_auth_security.py::test_explicit_bearer_compatibility_endpoint_remains_available
test_auth_security.py::test_reauthentication_rotates_cookie_and_revokes_previous_session
test_rate_limit.py::test_two_independent_limiter_instances_share_atomic_redis_window
test_rate_limit.py::test_production_rate_limit_fails_closed_without_shared_backend
test_rate_limit.py::test_local_fallback_is_windowed_and_does_not_leak_raw_keys
test_rate_limit.py::test_two_independent_api_processes_share_ip_rate_limit
test_rate_limit.py::test_configured_but_unreachable_redis_fails_closed
```

N2 完成判据（docs/15 §7）逐条对应：

| 判据 | 证据 | 状态 |
|---|---|---|
| Actions quality / SQLite / PG16 全绿 | 本机三组全绿 + **远端 CI run 44232322979 三个 job 全 pass**（browser `13 passed, 1 warning in 20.24s`；sqlite `255 passed, 3 skipped`；postgres16 `255 passed, 3 skipped`；`OpenAPI matches: 68 paths`） | 通过 |
| Chromium desktop + 375px 全通过 | `13 passed` + 响应式 24/24 | 通过 |
| editor→reviewer→rights→publish 闭环 | `test_teacher_full_review_publish_revision_and_cookie_flow` | 通过 |
| table block 无损 / published 只读 / 新 revision diff 正确 | 同上 + 修复 LM-002 | 通过 |
| 两编辑器 412 EDIT_CONFLICT 且保留输入 | `test_two_editors_receive_precondition_failure_without_losing_input` | 通过 |
| Cookie/CSRF/登出撤销/轮换/legacy 清理 | `test_auth_security.py` 5 例 + 安全探针 17/17 | 通过 |
| 两独立 API 进程共享限流桶 / Redis 故障 fail closed | `test_rate_limit.py`（含 `test_two_independent_api_processes_share_ip_rate_limit`、`test_configured_but_unreachable_redis_fails_closed`） | 通过 |
| 原有 IDOR/版权 gate/RBAC/判题 sandbox 回归 | 255 passed（SQLite 与 PG16 各一次） | 通过 |
| 部署文档、OpenAPI 与代码一致 | DDL/OpenAPI diff 无差异 | 通过 |

## 4. 功能验收（真实浏览器，Compose 栈：PG16 + Redis + Uvicorn）

`artifacts/local-validation/2026-11-18/student-acceptance.json` → **46/46 通过**

- P0-A 浏览/搜索/多小问/来源展示/KaTeX：7 项
- P0-D 判题：8 项（等价形式、顺序等价、错误答案、不可解析、题设定义域下等价、定义域不同转人工、人工推导题 pending、x:real 下 `x/x+2x-3` → pending_review）
- P0-A 学习记录：错题、收藏、进度、提交历史：4 项
- P0-E 登出后会话失效、受保护页跳转登录：2 项
- P0-C 响应式：8 个页面 × 3 视口 = 24 项

## 5. 判题引擎语义抽查（直接调用 checker，非 HTTP）

| 标准答案 | 学生作答 | 题设假设 | 结果 | 期望 |
|---|---|---|---|---|
| `ln(x)+1-a` | `ln(x^2)/2+1-a` | `x>0` | `accepted`「在题设条件下符号等价」 | 正确（题设已限定 x>0） |
| `ln(x)+1-a` | `ln(x^2)/2+1-a` | `x: real` | `pending_review`「表达式定义域与标准答案不同」 | 正确（不得自动判对） |
| `1` | `x/x` | `x: real` | `pending_review` | 正确（docs/06 §2） |
| `1` | `x/x` | `x>0` | `accepted` | 正确 |
| `2x-2` | `2*(x-1)` | `x: real` | `accepted` | 正确 |
| `2x-2` | `2x+2` | `x: real` | `rejected` | 正确 |
| `2x-2` | `2x-` | `x: real` | `invalid_response`「格式解析失败」 | 正确 |
| `2*sin(x+pi/3)` | `2sin(x+pi/3)` | `x: real` | `accepted` | 正确 |

定义域不变量未被削弱：取消项导致定义域不同时一律转人工，既不自动判对也不判错。

## 6. 安全与限流探针（Compose 栈，真实 HTTP）

`artifacts/local-validation/2026-11-18/security-probe.json` → **17/17 通过**（明细见安全报告）。

## 7. 记录口径

- 每条结果都可在本机重跑；命令与工作目录见上表。
- 未使用 `sleep` 掩盖竞态；E2E 断言全部等待确定性状态（revision 状态 hook、网络响应、DOM 区域）。
- 未删除任何既有安全断言；本轮新增 2 个 Node 回归用例 + 2 个浏览器断言。
