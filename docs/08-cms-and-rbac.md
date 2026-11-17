# 08｜CMS、审核工作台、权限与运营流程

## 1. CMS 目标

让教研者在不写 SQL、不手写 JSON 的情况下完成“录入 → 预检 → 复核 → 发布 → 修改 → 撤稿”。让数据运营通过统一入口接入大量题库，而无需接触数据库生产写权限。

## 2. 角色与最小授权

student：自己的书签/答题/举报；
editor：指定组织/课程 scope 下建稿和送审；
reviewer：指定学段/专题审核题目数学内容；
rights_reviewer：授权文件/展示权限审核；
source_manager：来源/连接器与导入批次；
admin：系统级配置与应急撤稿；
auditor：只读审计和访问报表。

多租户预留 tenant_id / visibility_scope：public, organization, class, private。P0 可仅 public/private + admin scope，但 API 不允许绕过 tenant。Editor 不能给自己审批的稿件盖审核章。发布涉及版权/重大修改至少数学与权利两个独立 gate；同一个人同时兼任角色时仍需两位不同审核者（策略可配置）。

## 3. 审核工作流

状态：
draft → preflight_failed / ready_for_review → in_math_review → in_rights_review → approved → published。
驳回：in_*_review → changes_requested → draft；
应急：published → rights_hold / suspended / retracted；
修订：published → 新 draft revision → 审核 → 新 published，不改变老 revision。

每个状态变更必须写 content_workflow_events (from/to, actor, reason, timestamp, revision_id)；前台所有内容访问先经过 rights gate，再查发布状态。

## 4. 核心编辑器字段与验证

题目层：title、source、external_id、grade_band、region、curriculum_release、difficulty、source_exam_metadata、visibility、rights policy。

题干层：MathRichText blocks、图像引用、语义条件（可选）、安全 LaTeX 预览。

小问层：logical_part_id、顺序、正文、response_type、max_score、answer_spec、rubric criteria、solutions；右侧即时验证分数总和/表达式解析与数学条件。

发布前清单：每小问有答案或人工判分策略；每份标准解经过教研验证；所有媒体可访问且版权允许；知识点映射/难度可解释；疑似重复有处理结论；来源和授权有效；校验器黄金样例通过。任何未通过阻断项显示字段定位和修复建议。

## 5. 批量审核

支持按来源、批次、章节、难度、审核状态筛选；快捷键“通过/退回/下一条”；相似候选并列展示原始题和现有题，操作可选择：独立、新增 relation、确认 exact duplicate/映射、延后审查。批处理发布必须逐条通过权利门禁；审批失败的条目保持原状态，并提供导出报告。

## 6. 内容问题与申诉

学生举报/系统检测进入 content_reports 队列：severity P0（重大答案错误、侵权、敏感信息、越权访问）、P1（表述歧义）、P2（排版）。P0 立即支持 suspend 自动判题或撤稿；后续修订发布需标明修订原因、影响的旧提交与是否触发 regrade。举报人只能看到公开处理状态和必要说明，不可看审核人员内部讨论。

## 7. 运营仪表盘

展示：待审核队列长度/龄、各源校验失败分布、版权到期前通知、疑似重复积压、发布内容质量分布、题目被举报率、判题待复核总量。指标可按 source/curriculum/grade_band 筛选；运营数据只显示聚合数，学生个人信息需专项授权。

## 8. 审计与合规

至少记录：谁访问了受限原件、谁改了哪一个字段、谁批准、哪份授权支持发布、哪条来源映射决定被更改。审计日志不可由普通 admin 控制台编辑或清空。导出题目需重新通过用途与地域许可门禁，不是“能看到就能导出”。

## 9. CMS 验收用例

- Reviewer 不能批准本人创建的题，即便尝试修改请求参数。
- 改已发布标准答案时自动新建 Revision，旧 Submission 不变。
- 并发两个编辑保存同一 Revision 时，一人收到 edit conflict。
- 未过 rights review 不能 publish。
- 权利到期后前台搜索立即不返回该题，直链无法获取正文。
- 批量通过中有一题不合规则只隔离该题并生成完整操作日志。
