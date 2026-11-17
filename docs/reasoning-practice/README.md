# LeetMath · Reasoning Practice 文档集

> 版本：v0.2 设计提案｜2026-11-17｜状态：独立专项，**不等于生产已上线**。

## 定位

Reasoning Practice 是 LeetMath 的 Phase 1.5 学习体验专项：在已审校的 `Problem → Revision → Part → Solution` 题库基础上，抽取**有版本的推理步骤卡**，进行主动回忆、自我评估和到期复习。复习产生的自评分与正式数学判题评价彼此独立。目标是发现学生“卡在关键哪一步”，而不是让学生背住整道题。

## 阅读顺序

1. [产品 PRD 与交互规范](PRODUCT_PRD.md)：练题界面、进度与 XP、三档自评、学习档案、几何可视化与本地账户。
2. [竞品调研与决策](RESEARCH_AND_DECISIONS.md)：对比 hashcards-local、Product Hunt/HN 意见以及与 Phase 1 规划冲突的 ADR。
3. [学习 Schema 与 API](LEARNING_SCHEMA.md)：Step / Card / Review Event / Knowledge Evidence 的关联关系、幂等与权限边界。
4. [评分、复习、知识画像算法](ALGORITHMS.md)：重点步骤权重、自评/正式成绩隔离、复习调度与算法版本。
5. [扩展 PostgreSQL DDL 草案](postgres_learning_extension.sql)：为主库增加独立 Learning 域的候选 SQL；**还不是可直接执行的生产迁移**。
6. [实施路线图](IMPLEMENTATION_ROADMAP.md)：分阶段交付与回归/安全验收。

## 与原 LeetMath 的契约

- 权威规范仍见 [Phase 1 文档](../README.md) 与 [数学题库契约](../03-content-contract.md)、[数据模型](../04-data-model.md)、[数学评分](../06-judging-and-rubrics.md)。
- 已发布题目、答案、步骤与评分规则必须不可变或通过新版本修订；历史记录引用原版本。
- 学生点击“知道/模糊/不确定”记录的是**自报回忆证据**，绝不写入正式 `evaluations` 冒充数学成绩。
- 标签用于检索；课程知识点、本体先修关系、错因代码和步骤对应关系分别建模。
- 首期 1/3/7 天重复日程不等于 FSRS；正式 FSRS 引入后应保存算法版本与审计事件。
- 2D/3D 可视化必须安全、可降级；版权、未成年人隐私和访问控制沿用主规范。

## 范围说明

此分支仅发布设计文档和 DDL 草案，不包含上一轮本地可运行原型的源代码、预装依赖、数据库或视频资源。上线前仍需 PostgreSQL 迁移演练、数学与内容审核、浏览器交互测试和安全验收。
