# LeetMath 交接说明（HANDOFF）

> 交接日期：2026-11-17 · 交接基线：`main` 分支（含本文件的提交）· 依据文档：[docs/13 实施计划与状态 v0.2](docs/13-implementation-plan-and-status.md)
> 交付形态：**可运行 MVP（本地 / 试点环境）**，**不是生产上线**。任何对外表述、对外演示与招生宣传都不得超出该范围。

本文写给接手人：现在到哪一步、如何 15 分钟自证可运行、哪些不变量不能碰、还差什么、下一步先做什么。

> N1 PR #2 已合并，结构化 CMS 与 CI 已进入 main。N2 的 Issues #3/#4 正在分支 feat/n2-e2e-cookie-redis 实施；浏览器 E2E、Cookie/CSRF 与 Redis 双进程测试必须以该分支 PR checks 的真实结果为准，不能把代码已提交等同于验收完成。详细源码调用链见 [docs/15](docs/15-n2-source-flow-security-and-browser-e2e.md)。
产品与设计细节在 00–13 号文档里，本文只记录“当下状态与动作”。§1 的每条结论都附本次实测命令与结果，可复现。

---

## 0. 现状速览

### 0.1 仓库状态

- 本次交接把此前**完全未提交**的 MVP 实现（后端、前端、契约、fixtures、容器化、生成物、文档）整理为按层次拆分的提交并推送到 `origin/main`。
- 工作树在交接后应为干净状态；本地运行时产物（`var/`、`*.db`、`.venv/`、`.DS_Store`）已写入 `.gitignore`，不得入库。
- 提交前的 `main` 只有 00–12 号设计文档；`docs/13` 与本实现同在本次交付。

### 0.2 已具备的能力（P0 + Phase 1.5 v0）

内容契约 v1（Schema + MathRichText 安全 + 阻断/警告预检 + 内容 hash）· 题目身份与不可变版本（ORM 守卫 + PG 触发器）· 草稿→数学审核→版权审核→已批准→发布（禁自审、双人门禁、撤稿、版权冻结、暂停判题）· 查询时实时权利门禁 · 安全判题引擎（自写解析器无 `eval`、定义域感知符号等价、forkserver 沙箱、单选/多选/数值/表达式/区间/解集，证明与推导转人工、评测追加式可重判）· 多源导入（Manifest + sha256、双层幂等、L0/L1/L2 去重候选、版本冲突、逐行报告、dry-run）· 学生端 SPA（搜索游标分页、多小问作答、LaTeX 预览、错题/收藏/进度/举报）· 推理步骤卡训练（自评与正式成绩隔离、1/3/7 天调度、兄弟卡埋藏）。

### 0.3 明确不具备（不要假设）

N1 已具备常用字段结构化 CMS、MathRichText 预览与 revision diff；N2 分支已实现 Playwright 浏览器编审、HttpOnly Cookie/CSRF、Redis 共享限流的候选代码，但在 PR CI/双进程测试通过前仍不可视为已验收。仍未具备：批量编辑/局部批注 · 媒体上传/病毒扫描/签名 URL · 异步判题队列/SSE · 中文分词与公式检索 · 备份恢复演练 · 生产监控告警与 SLO 压测 · 未成年人数据合规审查 · FSRS/几何可视化/Manim。详见 [docs/13 §6](docs/13-implementation-plan-and-status.md)。

---

## 1. 15 分钟自验（本次交接已在 Python 3.12.15 上实测）

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

| 检查 | 命令 | 本次实测结果（2026-11-17） |
|---|---|---|
| 自动化测试（SQLite，默认） | `cd backend && python -m pytest -q` | `245 passed, 1 warning in 10.16s` |
| 自动化测试（PostgreSQL 16） | `LEETMATH_TEST_DATABASE_URL=postgresql+psycopg2://leetmath:leetmath@127.0.0.1:<port>/leetmath python -m pytest -q` | `245 passed, 1 warning in 14.48s`（`docker run postgres:16`） |
| 用例分布 | `python -m pytest --collect-only -q` | contract 41 / grading 146 / api_flow 19 / workflow_rights 17 / ingestion 15 / reasoning 7 = 245 |
| 契约正例（含黄金判题） | `PYTHONPATH=backend python -m leetmath.cli validate fixtures/positive` | 13/13 `ok`，`0 blocking, 0 warnings` |
| 迁移升/无漂移/降 | `cd backend && alembic upgrade head && alembic check && alembic downgrade base` | SQLite 全通过（`No new upgrade operations detected.`）；PG 仅在容器启动时跑过 `upgrade head`（日志已见），**未**在 PG 上单独复跑 down/check |
| DDL 导出可复现 | `python -m leetmath.cli ddl --dialect postgresql` | 671 行，与 `docs/generated/schema.postgresql.sql` 逐字节一致，且连续两次运行结果一致 |
| OpenAPI 与实现一致 | `python -c "from leetmath.app import create_app; print(len(create_app().openapi()['paths']))"` | 66 paths，与 `docs/generated/openapi.json` 逐字节相同 |
| 本地起服务 | `PORT=18000 ./scripts/run-local.sh` | `/` 200、`/api/docs` 200、`POST /api/v1/auth/login` 200 |
| 容器起服务 | `docker compose up -d --build` | `db` healthy、`app` up；容器内 `/api/docs` 200、登录 200、`GET /api/v1/problems` 返回 3 条 |

> 提示：若本机 8000 端口被占用，用 `PORT=18000 ./scripts/run-local.sh`；容器方式请先释放 8000。

### 1.1 运行环境与配置

- **Python 3.12**（Dockerfile 固定 `python:3.12-slim`）。本次验证在 3.12.15。文档未声明最低版本，仓库也没有锁文件——见 §4.2 第 4、5 条。
- 依赖：`requirements.txt`（运行）、`requirements-dev.txt`（+pytest/httpx/ruff）。本次解析到 fastapi 0.163.1、SQLAlchemy 2.1.9、alembic 1.20.1、sympy 1.14.0、jsonschema 4.26.0、pydantic 2.14.3、pytest 9.2.0、ruff 0.17.5，全绿。
- 数据库：生产 PostgreSQL 15+/16；开发与测试 SQLite。对象存储默认本地内容寻址目录 `var/objects`（生产换 S3）。
- 环境变量（`backend/leetmath/config.py`）：`LEETMATH_DATABASE_URL`、`LEETMATH_STORAGE_DIR`、`LEETMATH_SESSION_TTL_HOURS`(72)、`LEETMATH_GRADER_TIMEOUT_S`(4)、`LEETMATH_GRADER_MEMORY_MB`(512)、`LEETMATH_DISTINCT_REVIEWERS`(1)、`LEETMATH_RATE_LIMIT_PER_MIN`(120)、`LEETMATH_ENV`、`LEETMATH_COOKIE_SECURE`、`LEETMATH_REDIS_URL`、`LEETMATH_CSRF_SECRET`、`LEETMATH_AUTO_CREATE`(1；生产必须 0)、测试用 `LEETMATH_TEST_DATABASE_URL`、`LEETMATH_SANDBOX_START`(forkserver)。生产必须 Secure Cookie、共享 Redis、唯一 32+ 字符 CSRF secret；反向代理按真实地址配置 `FORWARDED_ALLOW_IPS`。
- 演示账号（`seed` 生成，**仅本地/试点**，生产必须更换）：`student`/`student2`、`editor`、`reviewer`、`rights`、`ops`、`auditor`、`admin`，口令见 README 与 `backend/tests/conftest.py`。`docker-compose.yml` 中的 PG 口令同样是本地值。
- CLI：`init-db`、`migrate`、`seed`、`validate`、`export-fixtures`、`import`、`ddl`、`serve`（`PYTHONPATH=backend`）。

---

## 2. 不要破坏的不变量（改动前必读）

1. **单一公开门禁**：所有公开读取（列表、详情、题单、收藏、错题、复习卡）必须经过 `services/catalog.py::public_revision()` 或等价 SQL 谓词——已发布 + 当前版本 + 公开 + 无冻结 + 授权**此刻**有效且允许 display。授权到期要立即生效，不允许依赖后台任务。
2. **判题先建 AST，再交给 SymPy**：分母、对数/根号参数、`tan` 极点等定义域约束必须在自动化简（`x/x→1`）之前记录；符号等价但定义域不同 → `pending_review`，**既不判正确也不判错误**。随机采样只为找反例。
3. **评测追加式**：人工批改与重判只追加 `evaluations` 行并指向 `previous_evaluation_id`，最新一条为有效判定；历史提交永远关联原发布版本（新版本不得改写历史）。
4. **导入从不发布**：适配器只产出 Contract v1 草稿；相似度只产出去重**候选**，任何合并都要人工决定且保留双方来源归属。
5. **自评与成绩隔离**（Phase 1.5）：推理卡自评不得进入 `evaluations`，诚实自评不扣 XP，XP 与评级脱钩。

---

## 3. 代码地图

| 位置 | 职责 | 对应文档 |
|---|---|---|
| `backend/leetmath/app.py` | 请求级事务中间件、request_id、安全响应头、CSRF、按 IP/操作分类限流 | 07、15 |
| `backend/leetmath/services/security.py`、`rate_limit.py` | HMAC CSRF、Cookie 规则、Redis 原子限流与生产 fail-closed | 15 |
| `backend/leetmath/api/public.py` / `admin.py` / `reasoning_routes.py` | 公开 API / 运营后台 / Phase 1.5 推理训练 | 07、08、reasoning-practice |
| `backend/leetmath/services/catalog.py` | 身份·版本·工作流·发布·可见性单一门禁 | 04、08 |
| `backend/leetmath/services/rights.py`、`audit.py` | 授权判定与留档、审计事件 | 05、08 |
| `backend/leetmath/services/ingestion.py`、`adapters.py` | 导入流水线（逐行 SAVEPOINT）、三类适配器 | 05 |
| `backend/leetmath/grading/` | `mathparse`（无 eval）→ `checkers` → `sandbox`（forkserver + rlimit） | 06 |
| `backend/leetmath/content/` | Schema 校验、预检、内容 hash、MathRichText 安全 | 03 |
| `backend/leetmath/services/learning.py`、`search.py`、`reasoning.py` | 作答/错题/进度、读模型 + 游标分页、推理卡调度 | 09、reasoning-practice |
| `backend/leetmath/models.py`、`migrations/` | docs/04 全部实体；Alembic 基线迁移（含不可变触发器） | 04 |
| `backend/tests/` | N1 基线 245 项测试（SQLite + PostgreSQL 双跑）；N2 新增浏览器/Cookie/Redis 测试，验收状态见 PR checks | 10、11、15 |
| `content-schema/v1/`、`fixtures/` | 题目与导入清单 JSON Schema、正/反例与黄金判题用例 | 03、05、06 |
| `frontend/` | 无构建 SPA（学生端 + 后台），KaTeX 本地化，CSP self-only | 02 |
| `docker-compose.yml`、`Dockerfile`、`scripts/run-local.sh` | 本地与容器启动路径 | 10、11 |

验收追溯（AC → 测试名）见 [docs/13 §4](docs/13-implementation-plan-and-status.md)；新增功能必须在同一 PR 内补上对应测试与追溯表条目。

---

## 4. 本次交接发现的问题

### 4.1 已在本交接中修复（各带验证）

1. **`docker compose up --build` 启动即崩溃**（阻塞文档化启动路径）：`objects` 命名卷首次挂到 `/app/var/objects` 时属主为 root，而容器以 `leetmath`(uid 10001) 运行，seed 写原始归档时报
   `PermissionError: [Errno 13] Permission denied: '/app/var/objects/raw'`，容器退出；此时 `docker compose ps` 只剩 `db`。
   修复：`Dockerfile` 预建挂载点 `mkdir -p /app/var/objects`（`chown -R leetmath /app/var` 已覆盖），使空命名卷初始化时继承 `leetmath` 属主。
   验证：重建后 `app` 保持 up，容器内 `/api/docs`、登录、`/api/v1/problems` 均 200。
2. **`cli ddl` 输出不可复现**：原实现 `for ix in t.indexes` 遍历无序集合，索引顺序随进程变化（同一 models.py 两次导出结果不同）。
   修复：按索引名排序。验证：连续两次输出逐字节一致，并已重新生成 `docs/generated/schema.postgresql.sql`。
   影响面：AC-008 若要“生成物 diff/无漂移进 CI”，此前会随机失败。

### 4.2 未修复，需接手人决策

1. **N1 候选分支已补 `.github/workflows/ci.yml`**：quality（契约、DDL/OpenAPI 漂移、关键 Ruff、JS+Node）与 SQLite/PostgreSQL 16（迁移、测试）两类工作已提交；**GitHub PR #2 首次 CI（Run #44077042871）已全部通过**：SQLite 245/245、PostgreSQL 16 245/245、quality（含 5 个 Node CMS 单测）成功；尚未完成浏览器手测，且以 PR 是否合并作为主分支现状判断。新增教师端常用字段表单和差异审阅，详见 [docs/14](docs/14-next-iteration-ci-and-cms.md)；原有 CMS 双审与版权门禁不变。
2. **N2 Issue #3/#4 候选实现已在 feat/n2-e2e-cookie-redis**：新增真实 Chromium 的教师建稿→数学审核→版权审核→发布闭环、375px KaTeX/页面溢出断言、复杂 table block 无损切换、发布只读/新 revision diff、两个编辑会话 If-Match 冲突；认证改为 HttpOnly Cookie + CSRF，限流改为 Redis Lua，并增加两个独立 Uvicorn 进程共享限流桶的测试。**当前尚未获得该分支 PR 的 GitHub Actions 结果**，不得宣称已通过。详见 [docs/15](docs/15-n2-source-flow-security-and-browser-e2e.md)。
3. **文档与实现的既有落差**（照旧，见 [docs/13 §5](docs/13-implementation-plan-and-status.md)）：示例身份冲突（`demo-source.jsonl` 与 `problem-sh-function-001.json` 声明同一 `(leetmath-original-demo, demo-func-001, version "1")`，导入被判 `SOURCE_VERSION_CONFLICT`）；demo JSONL 无答案只能生成 `practice_only` 草稿；`x/x` 类定义域差异实现为 `pending_review` 而非 `rejected`（策略可在 `check_expression` 调整，需教研确认）。
4. **依赖无上界、无锁文件**：`requirements*.txt` 只有下界。本次全新解析到 fastapi 0.163.1 / SQLAlchemy 2.1.9 / pytest 9.2.0 仍全绿，但下次安装可能跨大版本。建议加锁文件后再进 CI。
5. **Python 版本未声明，且 lint 未配置**：Dockerfile 固定 3.12，README 未写最低版本，仓库无 `pyproject.toml`/`requires-python`。因此 `ruff`（在 `requirements-dev.txt` 里）只能跑默认规则集：本次 `ruff check backend/leetmath backend/tests` 报 **182 项**，其中 135 项是 `B008`（FastAPI `Depends()` 作默认参数的固有写法，需 `extend-immutable-calls` 或显式忽略），其余多为 `UP*/I001/RUF100` 等可自动修复项。当前 lint 不构成任何门禁——建议补 `pyproject.toml`（`requires-python = ">=3.12"` + ruff 规则集与忽略项），再决定是否纳入 CI。
6. **判题回归集 146 例**，低于 docs/06 §9 建议的 300+ 人工标注用例；L2 相似阈值 0.55 未经标注数据标定。

---

## 5. 建议的下一步（按优先级）

| 优先级 | 任务 | 为什么现在做 | 入口 | 完成判据 |
|---|---|---|---|---|
| P0 | N1 CI 候选已编写，待 PR checks 验证 | 245 项测试与无漂移校验此前未自动化 | `.github/workflows/ci.yml`、Alembic、生成物 | 必须看到 quality、SQLite、PostgreSQL 16 全绿 |
| P0 | N1 已有常用字段表单 + 差异视图；后续补批量编辑与浏览器 E2E | 降低日常 JSON 编辑门槛，保留高级模式 | `frontend/cms-editor.js`、`app.js`、docs/14 | 数学公式/375px/双审核人工验收后再宣告完成 |
| P0 | 会话改 httpOnly Cookie + CSRF；限流换共享存储；判题改异步队列 | 多实例部署与真实用户的前置条件（当前 sessionStorage + 进程内限流） | `app.py`、`api/common.py`、`grading/` | 双实例压测通过且令牌不可被 JS 读取 |
| P1 | 媒体上传 + 病毒扫描 + 短效签名 URL | FR-002 缺口（`assets` 表已建、无接口） | `services/storage.py`、`api/admin.py` | 上传→扫描→引用→签名访问闭环 |
| P1 | 判题回归集扩到 300+ 人工标注 + L2 阈值标定 | 判题与去重质量缺客观基线 | `backend/tests/test_grading.py`、`services/ingestion.py` | 标注集与阈值报告入库 |
| P1 | 搜索：中文分词/同义词/公式结构 | MVP 用 `LIKE`，真实检索体验不足 | `services/search.py` | 检索评测集达标 |
| P1 | 备份恢复演练、压测（SLO）、监控告警、未成年人数据合规审查 | docs/11 的运营门槛，目前**一项都没做** | 运维流程 | 演练报告 + SLO 报告 + 合规结论 |
| P2 | Phase 1.5：FSRS、推荐排序、2D/3D 几何、Manim | 当前仅 v0-local 固定 1/3/7 天规则 | `services/reasoning.py` | 见 reasoning-practice 路线图 |

---

## 6. 交接确认清单

- [ ] 我已具备仓库写权限，并能执行 `git push origin main`。
- [ ] 我已按 §1 在本机复现全部检查（SQLite 与 PostgreSQL 两条路径）。
- [ ] 我已确认演示账号、PG 口令仅用于本地/试点，生产前必须更换，且已纳入密钥管理计划。
- [ ] 我已明确生产目标环境：PostgreSQL 版本、对象存储、域名与 CSP、限流存储（Redis 等）。
- [ ] 我已与教研/版权接口人对齐：内容人工审校流程、版权证据留存、`pending_review` 判题策略。
- [ ] 我已就 §4.2 的 1–6 项决定处理顺序，并把结论写回 `docs/13`（保持文档与实现一致）。

---

## 7. 文档索引

- 设计文档总目录：[docs/README.md](docs/README.md)（00–13 号，含 Phase 1.5 专项）
- 实施计划、架构、AC→测试追溯、已知差距：[docs/13](docs/13-implementation-plan-and-status.md)
- 可机读产物：`docs/generated/openapi.json`（66 paths）、`docs/generated/schema.postgresql.sql`（DDL + 不可变触发器）
- 示例与导入样例：`docs/examples/`、`docs/examples/imports/`、`fixtures/positive|negative/`
