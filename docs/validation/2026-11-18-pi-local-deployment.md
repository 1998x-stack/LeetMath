# 本机全栈部署与验收报告｜2026-11-18（Pi Agent）

> 执行者：Pi coding agent（model `iagent/standard`，thinking `high`；注册表中无 `deepseek-flash`，见 §2）
> 基线：`origin/feat/n2-e2e-cookie-redis` @ `08caab892daded21139a91b05fa461460d7ff0e1`（PR #5 head）
> `origin/main` @ `d8b09f813b44e2620084e2cf6e246ad6ac56f19f`
> 结果分支：`fix/pi-local-n2-validation-20261118`
> 结论：**本机完整部署成功，N2 浏览器 E2E 由 1 failed/12 passed 修复为 13 passed；4 个真实缺陷已修复，0 个 P0 遗留。**

本报告只记录本轮实际执行过的命令与结果。截图、trace、原始日志保存在
`artifacts/local-validation/2026-11-18/`（已加入 `.gitignore`，**未上传远端**，路径仅供本机复核）。

---

## 1. 环境（可复现信息）

| 项 | 值 |
|---|---|
| 操作系统 | macOS 27.3（Darwin 27.3.0，arm64），10 vCPU，16 GiB RAM |
| git | 2.54.0 (Apple Git-157) |
| Python | 3.12.15（`/opt/homebrew/bin/python3.12`，仓库内 `.venv`）；系统 `python3` 为 3.9.6，未使用 |
| Node.js | v26.13.1（npm 11.20.0） |
| Docker | 29.9.1；Docker Compose v5.6.0 |
| Playwright | chromium 159.0.8154.6（`python -m playwright install chromium`） |
| 其他工具 | `gh`（已登录 1998x-stack）、`psql`/`pg_isready`、`redis-cli`、`jq`、`curl` 均存在 |
| Pi | `command -v pi` → `/opt/homebrew/bin/pi`；`PI_MODEL=iagent/standard`、`PI_PROVIDER=iagent`、`PI_REASONING_LEVEL=high` |

## 2. 模型可用性说明（不虚构）

- 任务要求的 model id `deepseek-flash` 在本机 Pi 注册表（`~/.pi/agent/models.json`）中**不存在**。
- 注册表内最接近的可用模型为 `iagent` provider 下的 **`deepseek.v.4-b300/DeepSeek-V4-Flash`**（name: `DeepSeek-V4-Flash (gateway, vision)`）。
- 本会话实际运行在 `iagent/standard`（Pi 会话模型无法在会话内切换）。因此本轮**未**用 DeepSeek Flash 执行，也未声称使用过它；如需该模型，可用 `pi --model deepseek.v.4-b300/DeepSeek-V4-Flash` 启动新会话。视觉复核（截图判读）建议交给具备 vision 的该模型或人工。

## 3. 部署方式与状态

### 3.1 Docker Compose（PostgreSQL 16 + Redis 7 + FastAPI + SPA）

`docker-compose.yml` 的 app 端口固定映射 `8000:8000`，但本机 **8000 已被用户其它进程占用**
（`lsof -nP -iTCP:8000` → `hashcards pid=97932`）。按"不得终止用户已有进程"的约束，使用**临时覆盖文件**
（`/tmp/lm-compose-override.yml`，不写入仓库）改映射到 18000：

```bash
docker compose -f docker-compose.yml -f /tmp/lm-compose-override.yml config --quiet   # exit 0
docker compose -f docker-compose.yml -f /tmp/lm-compose-override.yml up -d --build    # exit 0
docker compose ps
# app    Up   0.0.0.0:18000->8000/tcp
# db     Up (healthy)  5432/tcp
# redis  Up (healthy)  6379/tcp
```

- 未执行任何 `down -v`、未删除 `leetmath_pgdata`/`leetmath_objects`/`leetmath_redisdata` 卷；原有的
  `已 seeded` 状态被复用（`{"status": "already seeded"}`），没有重复灌入演示数据。
- 应用启动日志：`migrated: postgresql+psycopg2://leetmath:***@db:5432/leetmath` → seed（幂等）→ `Uvicorn running on http://0.0.0.0:8000`。
- Redis 日志：`Ready to accept connections tcp`，healthcheck 通过。

### 3.2 HTTP 探测（真实 HTTP，非 TestClient）

| 路径 | 状态 | 内容类型 |
|---|---|---|
| `/` | 200 | text/html 1249B（SPA 外壳） |
| `/login`、`/admin/problems`、`/problems/{slug}` | 200 | text/html（SPA 路由） |
| `/api/health` | 200 | `{"status":"ok"}` |
| `/api/docs` | 200 | Swagger UI |
| `/api/openapi.json` | 200 | application/json 55834B（68 paths） |
| `/api/v1/problems` | 200 | 15 条，游标分页 `next_cursor` 存在 |
| `/api/v1/problems/function-x-log-x-minus-a-x` | 200 | 3 个小问 |
| `/static/app.js`、`/static/vendor/katex/katex.min.js` | 200 | 本地 KaTeX，无外部 CDN |

### 3.3 原生路径（SQLite + `scripts/run-local.sh`）

```bash
PATH="$PWD/.venv/bin:$PATH" PORT=18001 ./scripts/run-local.sh   # 8000 被占用 → 18001
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18001/api/health   # 200
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18001/             # 200
POST /api/v1/auth/token → 200（bearer 兼容路径）
python -m leetmath.cli seed → {"status": "already seeded"}   # 幂等
```

差异：原生路径默认**未配置 Redis**（`LEETMATH_REDIS_URL` 未设置）→ 使用文档明确的开发态进程内限流
（不具备多实例一致性）；Compose 路径配置共享 Redis。SQLite 数据落在 `var/`（已 gitignore）。

### 3.4 隔离测试资源（不触碰用户数据）

| 资源 | 端口 | 用途 |
|---|---|---|
| `lm-test-pg`（postgres:16，临时容器） | 15432 | PostgreSQL 全量测试、Alembic |
| `lm-test-redis`（redis:7-alpine，临时容器） | 16379 | 限流/CSRF/浏览器 E2E 的 `LEETMATH_REDIS_URL` |

本机 6379 上已有用户自己的 `redis-server`（pid 57950），测试**未**写入该实例；5432 上已有 Homebrew
postgres，测试**未**连接该实例。

## 4. 本轮通过 / 失败 / 跳过

| 范围 | 结果 |
|---|---|
| 服务部署（PG16 + Redis7 + FastAPI + SPA） | ✅ 通过（§3） |
| 数据库迁移 / ORM drift / downgrade（SQLite + PG16） | ✅ 通过 |
| 内容契约 13 正例 + 黄金判题 | ✅ 通过 |
| 生成物一致性（DDL、OpenAPI） | ✅ 通过 |
| 学生端功能验收（浏览器） | ✅ 46/46 |
| 教师 CMS 全流程（浏览器） | ✅ 通过（编辑→数学审核→版权审核→发布→只读→新修订→diff→412） |
| 响应式（1280/768/375，8 个页面） | ✅ 24/24 无横向溢出 |
| 安全（Cookie/CSRF/Origin/429/Bearer/hash） | ✅ 17/17 |
| 自动化测试（SQLite / PG16） | ✅ 255 passed, 3 skipped（均为浏览器用例，默认跳过） |
| N2 浏览器 E2E（CI parity） | ✅ 13 passed（修复前 CI：1 failed, 12 passed） |
| 生产 HTTPS/Secure cookie/__Host- 前缀 | ⏭️ 未执行（本机无 HTTPS 终止，属未覆盖范围，非失败） |
| 视觉像素级审阅（公式排版美观） | ⏭️ 未执行（本轮模型无 vision，仅程序化断言 + 截图留档，需人工/视觉模型复核） |

## 5. 未解决风险（P1/P2）与未覆盖范围

- **P1**：限流阈值为初值，未按学校 NAT/代理流量校准；`Retry-After` 已验证但未做压测（SLO 未测）。
- **P1**：媒体上传/扫描/签名 URL、异步判题队列、备份恢复演练、未成年人数据合规审查仍未实现（继承 docs/13 §6）。
- **P2**：`GET /openapi.json` 被 SPA catch-all 命中，返回 index.html（200 text/html）而不是规范 JSON；规范在
  `/api/openapi.json`。API 使用者容易误判，建议对已知 API 前缀返回 404 JSON。
- **P2**：`#toast` 仅以 `opacity: 0` 隐藏且文本保留，旧的提示文本会留在 DOM 中，容易造成测试断言或读屏
  播报读到过期消息。
- **P2**：依赖无锁文件（`requirements*.txt` 只有下界），ruff 仅以 CI 选定的 E4/E7/E9/F82x 规则作为门禁。
- **P2**：CI 的 quality job 同时承担契约、生成物、JS、浏览器 E2E 与安全测试，失败定位成本高，建议拆分。
- **未覆盖**：Windows/Linux 本机路径、Firefox/WebKit/Safari、真机 iOS/Android、生产反向代理
  `FORWARDED_ALLOW_IPS` 行为、多实例部署。

## 6. 复现清单（本报告全部证据）

```bash
# 0) 环境
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium

# 1) 全栈
docker compose -f docker-compose.yml -f /tmp/lm-compose-override.yml up -d --build

# 2) 隔离测试资源
docker run -d --name lm-test-redis -p 16379:6379 redis:7-alpine
docker run -d --name lm-test-pg -p 15432:5432 -e POSTGRES_USER=leetmath -e POSTGRES_PASSWORD=leetmath -e POSTGRES_DB=leetmath postgres:16

# 3) 自动化
export LEETMATH_REDIS_URL=redis://127.0.0.1:16379/0
LEETMATH_RUN_BROWSER_TESTS=1 LEETMATH_REQUIRE_BROWSER=1 PYTHONPATH=backend \
  .venv/bin/python -m pytest -q backend/tests/test_browser_e2e.py backend/tests/test_auth_security.py backend/tests/test_rate_limit.py
(cd backend && python -m pytest -q)
(cd backend && LEETMATH_TEST_DATABASE_URL=postgresql+psycopg2://leetmath:leetmath@127.0.0.1:15432/leetmath python -m pytest -q)

# 4) 功能与安全探针（脚本保存在 artifacts 目录所引用的本地路径）
.venv/bin/python /tmp/lm-student-acceptance.py http://127.0.0.1:18000   # 46/46
.venv/bin/python /tmp/lm-security-probe.py http://127.0.0.1:18000       # 17/17
```
