# LeetMath

> 数学版 LeetCode：可扩展的数学题库、数学解题评测、教研内容治理与学习平台。

**当前状态：可运行 MVP（本地 / 试点环境），尚未生产上线。** N1（CI + 结构化教师编辑器）已合并，见 [docs/14](docs/14-next-iteration-ci-and-cms.md)；N2（浏览器编审 E2E、Cookie/CSRF、Redis 共享限流）候选实现与源码因果分析见 [docs/15](docs/15-n2-source-flow-security-and-browser-e2e.md)，验收状态以对应 PR checks 为准。首期以上海高中数学为内容试点；内容契约从一开始支持多地区、多学段、多教材、多来源。所有新增题源都应具备合法授权/出处并经过数学审校。实现状态、验收追溯与已知差距见 **[docs/13 实施计划与状态](docs/13-implementation-plan-and-status.md)**；接手人请先读 **[HANDOFF.md](HANDOFF.md)**。

## 快速开始

```bash
pip install -r requirements-dev.txt
./scripts/run-local.sh            # SQLite + 演示数据 → http://127.0.0.1:8000
```

或使用 PostgreSQL 16：`docker compose up --build`（自动执行 Alembic 迁移与演示数据初始化）。

| 演示账号 | 密码 | 角色 |
|---|---|---|
| student / student2 | student-pass-123 | 学生 |
| editor | editor-pass-123 | 教研编辑（建稿、送审） |
| reviewer | reviewer-pass-123 | 数学审校（审核、发布、人工批改） |
| rights | rights-pass-123 | 版权审核 |
| ops | ops-pass-123 | 题源运营（来源、导入） |
| auditor / admin | auditor-pass-123 / admin-pass-123 | 审计 / 管理员 |

API 文档：`/api/docs`（OpenAPI 导出见 `docs/generated/openapi.json`）。

### 常用命令

```bash
export PYTHONPATH=backend
python -m leetmath.cli validate fixtures/positive                         # 内容契约：Schema + 预检 + 黄金判题用例
python -m leetmath.cli import docs/examples/imports/partner-csv/manifest.json   # 演示合作方 CSV 导入
python -m leetmath.cli migrate                                            # Alembic upgrade head（生产）
python -m leetmath.cli ddl --dialect postgresql                           # 导出物理 DDL
cd backend && python -m pytest -q                                         # 245 项测试；设 LEETMATH_TEST_DATABASE_URL 可在 PostgreSQL 上跑
```

## 已实现（Phase 1 P0 + Phase 1.5 v0）

- **内容契约 v1**：JSON Schema、MathRichText（禁止 HTML/危险 LaTeX）、阻断/警告预检（字段定位）、规范化内容 hash。
- **题目身份与不可变版本**：Problem / Revision / 逻辑小问 / 版本小问；发布后内容不可改（ORM 守卫 + PostgreSQL 触发器）。
- **审核工作流**：草稿 → 数学审核 → 版权审核 → 已批准 → 发布；禁止自审，两道门禁需不同审核人；撤稿、版权冻结、暂停判题。
- **权利门禁**：授权按动作/有效期/状态判定，查询时实时校验——到期即不可见，历史成绩保留。
- **判题引擎**：自写安全解析器（不使用 eval）、定义域感知的符号等价、反例检测、forkserver 资源沙箱；单选/多选（可部分得分）/整数/分数/小数容差/表达式/区间/解集；证明与推导进入人工批改，评测追加式可重判。
- **多源导入**：Manifest + sha256、批次与记录双层幂等、JSONL/演示 JSONL/CSV 适配器、L0/L1/L2 去重候选（不自动合并）、版本冲突、授权隔离、逐行报告导出、失败重试、dry-run。
- **学生端**：搜索筛选（稳定游标分页）、多小问作答与 LaTeX 预览、解析策略、收藏、错题、知识点进度、举报。
- **推理步骤训练（Phase 1.5）**：步骤卡自评与正式成绩严格隔离、1/3/7 天复习、兄弟卡埋藏、诚实不扣 XP、自评证据画像。

## 目录

```text
backend/leetmath/     FastAPI 模块化单体（api · services · grading · content · models）
backend/migrations/   Alembic 迁移        backend/tests/  自动化测试
content-schema/v1/    题目与导入清单 JSON Schema
fixtures/             契约正例 / 反例      frontend/  无构建 SPA（KaTeX 本地化）
docs/                 产品与工程设计 00–13、示例、generated/（DDL、OpenAPI）
```

## 产品规划

- **Phase 1（本期）**：题目身份与不可变版本、多小问、答案与评分规则、题库搜索/题单、个人提交记录、CMS、可插拔题源接入及审校。
- **Phase 2**：AI 教师工作台，经过审核的数学解题教学素材、Manim 分镜/源码/渲染视频。
- **Phase 3**：步骤级学习诊断、知识图谱、个性化训练与交互数学实验。

设计文档从 **[文档总目录](docs/README.md)** 开始；Phase 1.5 专项见 [Reasoning Practice](docs/reasoning-practice/README.md)。

## 建设准则

1. 统一内部 Problem ID；第三方题号存各自 Source 命名空间。
2. 一个题目可以有多小问，每一问可独立评分、解析与学习记录。
3. 发布版本不可变，历史答题严格绑定题目和判题器版本。
4. 所有题目具备可追踪来源、版权/授权、审核证据和内容质量状态。
5. 导入全链路可重放、可审计、可隔离；不得根据相似度直接自动合并。
6. 不可确定的符号推理与证明题进入人工复核，不将 AI 猜测作为分数依据。

## 参与

欢迎基于文档提出 Issue/PR。所有产品和数据契约更新需要同步修订相关 JSON 示例、OpenAPI、迁移与测试。演示题目均为原创示例，非官方试题。
