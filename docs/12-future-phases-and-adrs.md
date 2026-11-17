# 12｜Phase 2/3 对接规划与架构决策记录（ADR）

本文件明确“现在预留接口、未来再实现”的边界，不把尚未验证的 AI/Manim 方案塞进 Phase 1 上线范围。

## 1. 三阶段长期定位

Phase 1：题库 + 小问 + 判题 + CMS + 多源治理 + 学习事件。
Phase 2：教师工作台，题解校验、分镜、Manim 源码、视频、交互素材资源管理。
Phase 3：AI 个性化数学导师，步骤级诊断、错因分类、知识路径、可交互数学实验与题目推荐。

## 2. Phase 2 资源模型预留

增加 instructional_assets：
- id、revision_part_id nullable、problem_revision_id、asset_type（storyboard/manim_source/mp4/thumbnail/interactive）、object_key、source_hash、renderer_version、validation_status、review_status、license_ref、creator_id、created_at。
- rendering_jobs：id、source_asset_id、engine（manim）、engine_version、container_image_digest、status、parameters_json、result_asset_id、logs_asset_id、error_code、started_at、finished_at。
- lesson_plans：curriculum_release_id、knowledge_node_ids、problem_revision_ids、teaching_goals、step_timing、reviewer_id。

Manim MCP 只受理受控源代码、在隔离容器/限额环境执行，产生不可变源码哈希与 MP4 对象；视频失败不影响题目正文、提交或判题。中文字体、LaTeX 包、渲染分辨率、音轨和字幕配置要版本化。素材可绑定题组或具体子问，支持一问多个视频版本。

## 3. Phase 3 学习模型预留

student_step_events（user、attempt、part revision、step order、redacted response、inferred_error_code、feedback event）；knowledge_observations（knowledge node、evidence source、confidence、model version）；recommendation_runs（input snapshot、algorithm version、candidate IDs、explanation）。这些是方向性实体，不意味着立刻收集所有数据；学生原始推理过程涉及隐私，必须先做教育数据治理和明确同意。

误区知识图谱：错误分类基于数学概念而非简单关键词；例如“求导乘积公式遗漏”“忽略定义域”“把必要条件当充分条件”。模型建议不自动改变已审校标准答案与成绩。

## 4. ADR-001：PostgreSQL 是权威库

决定：结构化实体和历史版本在 PostgreSQL；原始题源与媒体在对象存储；全文/向量搜索只作为可重建索引。原因：跨源去重、事务、约束、审计和发布版本优先。替代：全文文档库；弃用原因：跨源引用和版本强约束复杂。升级触发：实测数据库瓶颈而非凭预估拆分微服务。

## 5. ADR-002：内容契约优先于来源格式

决定：每个源通过 Adapter 转换到统一 MathContentContract v1。保留 raw archive 和 adapter/normalizer 版本。原因：从上海扩至其他地区无需改学生端结构。拒绝：每个题库独立 tables 或仅凭 source_id 做用户可见题目 ID。

## 6. ADR-003：发布版本不可变

决定：发布 snapshot 不允许原地更新；新内容 revision + 旧提交引用。原因：成绩可复现，版权/质量争议可追溯。代价：存储与迁移复杂度略增；通过对象去重和版本视图缓解。

## 7. ADR-004：数学判题必须分类型、分置信度

决定：确定性数值/结构判定优先，符号计算使用安全解析和定义域，无法证明则待复核。拒绝：单个 LLM 直接输出“正确/错误”的高风险评分策略。Phase 2 AI 仅辅助教研和学生提示，影响成绩需严格校验和可申诉。

## 8. ADR-005：版权和可见性单独建模

决定：来源记录、授权、内容状态、公开展示决定分别建模；展示策略按使用场景求交集。拒绝：一个 boolean is_public 代表所有版权权利。权利变更应可即时撤下搜索与素材访问，不影响审计链。

## 9. ADR-006：模块化单体先于微服务

决定：同一后端代码库明确分 domain 模块（catalog, ingestion, grading, learning, auth, moderation），外部计算如渲染/判题用隔离异步 worker。拆分条件：有经观测的吞吐/安全/团队边界，且有契约和可观测性证明。避免一开始跨微服务分布式事务。

## 10. 面向新增题库的演进原则

扩展优先顺序：新增 Source + Adapter → 审核 curriculum mapping → rights gate → 运行 normalize/validate → 生成 SourceRecord/duplicate candidates → 人工审核 → 发布 Revision → 索引/前台可见。永不因“题库扩大”而以批量 UPDATE 重写历史提交的引用对象。

## 11. 尚待决策（Decision Log）

- 是否兼容 IMS QTI 作为导入导出格式；只考虑格式映射，不把复杂 QTI 运行时作为 MVP。
- 课程目录版本依据和上海高中标签审核责任人。
- 对合作方授权最小证据字段、到期/撤稿合同条款。
- 证明类题的人工复核 SLA 与是否允许学生提交草稿证明。
- 是否开放课堂/学校 tenant；在隐私合规与校方授权明确后决定。
- 搜索引擎切换门槛（量化 P95、索引延迟、运营成本后再选型）。
