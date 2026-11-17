# LeetMath 产品与工程设计文档集

> 版本：v0.1 · 状态：设计草案（尚未实现） · 更新：2026-11-17
>
> 首期业务场景为上海高中数学；技术与内容模型从第一天支持多学段、多地域、多来源、多版本。

## 阅读顺序

| 序号 | 文档 | 目标读者 | 核心内容 |
|---|---|---|---|
| 00 | [产品战略与边界](00-product-strategy.md) | 产品/负责人 | 愿景、定位、阶段、指标、非目标 |
| 01 | [Phase 1 详细 PRD](01-phase1-prd.md) | 全体 | 需求、优先级、业务规则、验收 |
| 02 | [用户旅程与交互规格](02-user-journeys-ux.md) | 设计/前端/QA | 页面、状态、交互、异常 |
| 03 | [数学题目内容契约](03-content-contract.md) | 题库/后端 | 题组、小问、表达式、版本、元数据 |
| 04 | [数据库与索引设计](04-data-model.md) | 后端/DBA | ER、实体、唯一约束、索引、演进 |
| 05 | [多题库接入与治理](05-ingestion-and-governance.md) | 数据工程/教研 | Connector、去重、权利、审核、回滚 |
| 06 | [判题和评分规格](06-judging-and-rubrics.md) | 算法/教研 | 答案类型、CAS、步骤评分、人工复核 |
| 07 | [API 契约](07-api-contract.md) | 前后端 | REST 接口、幂等、错误、分页、权限 |
| 08 | [CMS 与运营后台](08-cms-and-rbac.md) | 教研/运营 | 角色、工单、审核、发布与审计 |
| 09 | [检索、题单与学习记录](09-search-and-learning.md) | 产品/算法 | 搜索、进度、错题、学习数据 |
| 10 | [阶段路线图与验收](10-delivery-roadmap.md) | 项目管理 | Epic、迭代、依赖、Definition of Done |
| 11 | [质量、安全与运维](11-quality-security-ops.md) | QA/SRE/安全 | 测试矩阵、版权、未成年人数据、SLO |
| 12 | [后续阶段与 ADR](12-future-phases-and-adrs.md) | 架构/负责人 | AI、Manim、国际化、架构决策 |

## Phase 1.5：Reasoning Practice（逐步骤间隔训练）

这是在 Phase 1 题库、发布版本、内容治理与判题基础上增加的**独立设计提案**；**不替代**上述 00–12 文档，也不改变正式考试评分原则。文档所述本地 MVP 和学习算法均不能视为生产能力。

- [概览与阅读顺序](reasoning-practice/README.md)
- [完整产品 PRD 与学生端交互](reasoning-practice/PRODUCT_PRD.md)
- [竞品调研、现有 PRD 差异与 ADR](reasoning-practice/RESEARCH_AND_DECISIONS.md)
- [学习 Schema、事件与 API 设计](reasoning-practice/LEARNING_SCHEMA.md)
- [PostgreSQL 学习模块扩展 DDL 草案](reasoning-practice/postgres_learning_extension.sql)
- [步骤自评计分、间隔复习与知识画像算法](reasoning-practice/ALGORITHMS.md)
- [阶段实施与验收路线图](reasoning-practice/IMPLEMENTATION_ROADMAP.md)

## 可机读样例

- [上海高中三问函数题](examples/problem-sh-function-001.json)：题干、题目版本、小问、答案、评分规则、来源。
- [题库批次清单](examples/import-manifest.json)：多来源接入的示例导入配置。
- [MVP OpenAPI 草案](examples/openapi.yaml)：重点请求/响应和错误模型。

## 文档约定

- P0 = MVP 上线阻塞；P1 = 正式开放前建议完成；P2 = 后续增强。
- FR = 功能需求；NFR = 非功能需求；AC = 验收标准；ADR = 架构决策。
- “目标值”均为建议验收门槛，不是当前已达成绩。
- 接口与表名是规范草案；任何变更必须同步更新相关示例、数据库迁移和契约测试。
- 上海题库是第一批内容，不等于上海官方题库；版权、授权与“真题”标签需要逐条有证据。
- 历史学生提交永久关联到原发布版本，发布后不得静默改题或改答案。

## 变更机制

每个功能至少有：用户故事、FR 编号、明确状态机、API/数据契约、AC、可追溯测试案例。破坏兼容性需开 ADR 并列明迁移方案。PR 模板中勾选：契约校验、数学复核、版权检查、可访问性与监控更新。
