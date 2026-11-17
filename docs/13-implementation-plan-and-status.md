# 13｜实施计划、当前实现状态与验收追溯

版本 v0.2 · 2026-11-17 · 状态：**可运行 MVP（本地/试点环境）**，不是生产上线。

> **2026-11-17 N1 增补**：本分支新增 CI 质量门禁、结构化 CMS 编辑、版本差异与 Node 模型测试；详情见 [docs/14](14-next-iteration-ci-and-cms.md)。本文件中 245/245 是先前 HANDOFF 的实测记录，新增 CI 结果不能据此推定为绿。Playwright 和生产安全仍未验收。

本文件记录基于 00–12 号设计文档与 Phase 1.5 专项完成的第一版实现：分步计划、架构、各 PRD 条目的实现位置、验收用例与测试的对应关系，以及**尚未完成**的事项。

---

## 1. 分步实施计划（按依赖顺序执行）

| 步骤 | 对应路线图 | 内容 | 产出 |
|---|---|---|---|
| S1 基础标准 | P1.0 / E01 | Contract v1 JSON Schema、MathRichText 安全校验、内容 hash、预检规则、正/反例 fixtures、ORM 数据模型（docs/04 全部实体） | `content-schema/v1/`、`backend/leetmath/content/`、`models.py`、`fixtures/` |
| S2 判题引擎 | P1.3 / E04 | 自写递归下降解析器（无 eval）、定义域约束追踪、SymPy 等价 + 反例检测、forkserver 沙箱（CPU/内存/超时）、选择/数值/区间/集合判题 | `backend/leetmath/grading/` |
| S3 内容治理 | P1.1 / E02 | 草稿→数学审核→版权审核→已批准→发布；禁止自审、双人门禁、阻断预检、发布不可变（ORM 守卫 + PG 触发器）、撤稿/版权冻结/暂停判题、乐观锁、审计 | `services/catalog.py`、`services/rights.py`、`services/audit.py` |
| S4 多源接入 | P1.4 / E05 | Manifest 校验 + sha256、批次幂等、三个适配器、L0/L1/L2 去重候选、版本冲突、隔离、逐行状态/导出、失败重试、dry-run | `services/ingestion.py`、`services/adapters.py` |
| S5 API 与学习 | P1.2–P1.3 / E03–E04 | REST v1（66 个路径）、Bearer 会话、RBAC、统一错误体、幂等键、游标分页搜索、提交/追加式评测、错题/收藏/进度/举报、人工批改与重判 | `backend/leetmath/api/`、`services/learning.py`、`services/search.py` |
| S6 Phase 1.5 | reasoning-practice R0 | 推理步骤卡、知道/模糊/不确定自评（与正式成绩隔离）、1/3/7 天调度、同小问兄弟卡埋藏、XP 与评级脱钩、自评证据指数画像 | `services/reasoning.py`、`api/reasoning_routes.py` |
| S7 前端与种子 | P1.2 | 无构建步骤的 SPA（学生端 + 后台）、本地化 KaTeX、13 道原创示例题（覆盖全部 P0 自动题型）、试点知识点树、题单、角色账号 | `frontend/`、`seed_data.py` |
| S8 硬化与交付 | P1.5 / E06 | 245 项自动化测试（SQLite + PostgreSQL 16 双跑）、Alembic 基线迁移（升/降/无漂移校验）、Docker/Compose、CI、DDL 与 OpenAPI 导出 | `backend/tests/`、`backend/migrations/`、`.github/workflows/ci.yml` |

## 2. 架构（模块化单体）

```text
frontend/ (SPA, KaTeX vendored, CSP self-only)
   │  /api/v1  Bearer token
backend/leetmath/app.py  ── 请求级事务中间件 · request_id · 安全响应头 · 统一错误体
   ├─ api/public.py            题库/详情/作答/个人学习/举报
   ├─ api/admin.py             CMS/审核/来源授权/导入/去重/批改/审计/仪表盘
   ├─ api/reasoning_routes.py  Phase 1.5 推理训练
   ├─ services/catalog.py      身份·版本·工作流·发布·可见性单一门禁 public_revision()
   ├─ services/search.py       读模型 + 查询时权利校验 + keyset 游标
   ├─ services/learning.py     attempts/submissions/evaluations(追加式)/错题/进度
   ├─ services/ingestion.py    导入流水线（逐行 SAVEPOINT）
   ├─ services/reasoning.py    推理卡调度与画像
   ├─ grading/                 mathparse(无eval) → checkers → sandbox(forkserver+rlimit)
   └─ content/                 schema + preflight + hash + richtext 安全
PostgreSQL 15+/16（生产）| SQLite（开发/测试）· 对象存储（本地内容寻址，生产换 S3）
```

关键设计选择：
- **单一公开门禁**：所有公开读取（列表、详情、题单、收藏、错题、复习卡）都经过 `public_revision()` 或等价 SQL 谓词——已发布 + 当前版本 + 公开 + 无冻结 + 授权在**此刻**有效且允许 display。授权到期无需任何后台任务即刻生效。
- **判题先建 AST 再交给 SymPy**：在 SymPy 自动化简（`x/x→1`）之前记录分母、对数/根号参数、`tan` 极点等定义域约束；符号等价但定义域不同 → `pending_review`，绝不判“正确”，也不判“错误”。随机采样只用来找反例。
- **评测追加式**：人工批改、重判都追加 `evaluations` 行并指向 `previous_evaluation_id`；最新一条为有效判定。
- **导入从不发布**：适配器只产出 Contract v1 草稿；相似度只生成候选，任何合并都需要人工决定并保留双方来源归属。

## 3. PRD 功能项实现状态（docs/01 §2）

| ID | P0 范围 | 状态 | 说明 |
|---|---|---|---|
| FR-001 账号 | 登录、基础角色、游客阅读 | ✅ | scrypt 口令、哈希存储的会话令牌、7 种角色可叠加；第三方登录未做（P1） |
| FR-002 题目 | 题组+多小问、富文本、草稿/发布版本 | ✅ | 媒体资产表已建，上传/扫描流程未做 |
| FR-003 元数据 | 学段/地区/课程/难度/知识点/题型 | ✅ | 课程 release 版本化，知识点父子 + 先修边 |
| FR-004 搜索 | 关键词+筛选+排序+分页 | ✅ | 中文分词/同义词为 P1；MVP 用 LIKE |
| FR-005 阅读 | 题目页、公式、逐问输入 | ✅ | LaTeX 实时预览、移动端单列 |
| FR-006 评分 | 数值/单选/多选/符号表达式 | ✅ | 另含区间、有限集合/解集；证明/推导走人工 |
| FR-007 题解 | 每问解析、标准答案 | ✅ | 可见策略 after_submit / always / teacher_release |
| FR-008 学习记录 | 历史、最近练习、收藏、错题 | ✅ | 小问级 + 题组级统计（部分正确≠全对） |
| FR-009 题单 | 人工题单、稳定顺序 | ✅ | 读取时逐条复核可见性与授权 |
| FR-010 CMS | 编辑、预览、审校、发布、撤稿、审计 | ✅* | *编辑器为 JSON + 实时预检；结构化表单编辑器为 P1 |
| FR-011 题源 | 来源注册、授权、唯一外部键、原始留档 | ✅ | |
| FR-012 批量导入 | CSV/JSON(L) 模板、预检、逐行结果、幂等重放 | ✅ | 定时同步、PDF/OCR 为 P1+ |
| FR-013 去重 | 来源唯一键 + 精确哈希 + 人工合并 | ✅ | 另含 L2 三元组相似候选（阈值待标定） |
| FR-014 运营 | 质量队列、导入进度、版权处置、错误报告 | ✅ | 仪表盘仅聚合数据 |
| FR-015 API/安全 | REST v1、审计、RBAC、限流、备份 | ✅* | *限流为进程内实现；备份恢复为运维流程，未自动化演练 |

## 4. 验收追溯（AC → 自动化测试）

| 验收项 | 测试 |
|---|---|
| AC-001 多小问完整呈现、来源/答案/解析齐全 | `test_api_flow::test_ac001_problem_detail_multi_part_with_attribution`；种子题全部通过预检（含黄金用例） |
| AC-002 新版本不改写历史提交 | `test_workflow_rights::test_ac002_new_revision_keeps_history` |
| AC-003 重复导入不重复、相似题进人工 | `test_ingestion::test_sample_a_*`、`test_sample_b_*`、`test_sample_c_*` |
| AC-004 判题黄金样例、不支持题型明确人工 | `test_grading.py`（146 例）；`test_manual_types_pending` |
| AC-005 未授权/撤回内容不可达 | `test_ac005_retracted_content_unreachable`、`test_rights_expiry_*`、`test_rights_hold_and_release` |
| AC-006 写接口校验角色、重大操作有审计 | `test_students_and_editors_cannot_publish`、`test_audit_log_*`、`test_manifest_schema_and_roles` |
| AC-007 筛选分页稳定、公式渲染 | `test_ac007_stable_pagination_and_filters`、`test_pagination_updated_desc_cursor`；Playwright 桌面/375px 截图检查 |
| AC-008 迁移/幂等/访问控制/契约进 CI | N1 已在本分支增加 `.github/workflows/ci.yml`（SQLite + PostgreSQL 16 测试、alembic upgrade/check/downgrade、DDL/OpenAPI 漂移），是否通过请看 PR checks；另含 Node 模型测试 |
| docs/05 §10 样本 A–F | `test_ingestion::test_sample_a…f` 一一对应 |
| docs/06 §8 判题样例 1–10 | `test_grading::EXPR` 前 10 行 + `test_engine_timeout_is_not_a_math_error` + `INVALID` |
| docs/08 §9 CMS 用例 | `test_reviewer_cannot_approve_own_content`、`test_optimistic_lock_edit_conflict`、`test_cannot_publish_before_rights_review` 等 |
| docs/09 §9 学习数据 | `test_rejected_creates_mistake_and_partial_not_completed`、`test_idor_other_students_data`、`test_manual_grading_and_regrade_append_only` |
| Phase 1.5 ALGORITHMS §7 | `test_reasoning.py`（分数守恒、0/0.45/1、幂等不重复 XP、顺序与追加、兄弟埋藏、自评不入 evaluations） |

运行：`cd backend && python -m pytest -q`（SQLite），或设置 `LEETMATH_TEST_DATABASE_URL=postgresql+psycopg2://…` 在 PostgreSQL 上运行。本次交付在两种数据库上均 245/245 通过。

## 5. 实现中发现的问题

1. **示例数据身份冲突**：`docs/examples/demo-source.jsonl` 与 `docs/examples/problem-sh-function-001.json` 都声明 `(leetmath-original-demo, demo-func-001, version "1")`，内容却不同。按 docs/05 规则 F，导入流水线将其判为 `SOURCE_VERSION_CONFLICT`（见 `test_repo_example_manifest_imports_as_is`）。建议给 JSONL 示例改用不同的 `external_id` 或版本号。
2. **demo JSONL 格式不含答案**：适配器只能生成 `practice_only` 草稿（占位满分 1.00，并在逐行报告中警告），需要编辑补全答案后才能送审。
3. 文档 06 §2 将 `x/x` 一类定义域差异描述为“不能无条件通过”；实现选择 `pending_review`（转人工），而非 `rejected`，以免把数学上“几乎正确”的答案记为错题。若教研希望直接判错，可在 `check_expression` 中调整策略。

## 6. 尚未完成 / 已知差距（不得视为已上线能力）

- N1 候选分支已有结构化 CMS **常用字段**表单、MathRichText 实时预览、未保存与上一修订差异；**批量编辑、局部批注、复杂媒体可视编辑未做**。浏览器实测与 375px Playwright 仍待完成。
- 媒体上传、病毒扫描、短效签名 URL；`assets` 表已建但无上传接口。
- 会话令牌存于浏览器 sessionStorage；生产应改为 httpOnly Cookie + CSRF。
- 限流为进程内实现，多实例部署需 Redis 等共享存储；判题为同步执行（`grade` 有沙箱与超时，但无任务队列/SSE）。
- 搜索使用 LIKE；中文分词、同义词、公式结构检索需搜索引擎与评测集。
- 判题回归集 146 例，低于 docs/06 §9 建议的 300+ 人工标注用例；L2 相似阈值（0.55）未经标注数据标定。
- 备份恢复演练、压测（SLO）、监控告警、未成年人数据合规审查均未执行。
- Phase 1.5 仅实现 v0-local 规则（固定 1/3/7 天），FSRS、推荐排序、2D/3D 几何可视化、Manim 未实现。
- 13 道种子题为原创演示内容，数学经作者核对，仍需教研人工审校后方可用于真实教学。
