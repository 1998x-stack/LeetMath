# 09｜检索、题单、练习与学习数据产品规格

## 1. 搜索体验：多题源只展示统一学习对象

检索实体以 Problem 的当前合法公开 Revision 为主；SourceRecord 用于追溯但不单独占据学生列表。同一原题若被多个合法来源引用，只展示一次规范题卡，保留必要来源归属。改编题/同构题通常作为独立 Problem，可通过“相似题”关联。

支持：title/body/题号关键词、课程版本、学段、地区、年级、题型、知识点、多选标签、难度区间、来源类型、题目年份、是否有答案解析、是否做过。搜索参数支持 URL 可分享；默认只显示 public + rights valid + published。

## 2. 搜索排序

P0：相关度、最近更新、难度升降、题号顺序。相关度规则：精确题号 > 标题/知识点 > 题干命中，取稳定排名策略；结果并列时以 display_id 和 id 保证 cursor 排序稳定。不得将来源付费或导入时间单独视为“更权威”的数学质量。

P1：中文同义词词典、错别字纠正、多知识点布尔筛选、公式文本/结构搜索、相似题检索，需独立评测集。搜索内部不得把不具有相应许可的受限原文泄露在 snippets。

## 3. 知识点与不同地区映射

用户选择“上海高中数学 → 某版课程目录 → 导数”时，搜索用 release_id + knowledge_node_id，而不是仅比对“导数”字符串。跨教材的节点通过 mapping 表连接可比概念，带映射关系 exact/close/broader/narrower 与人工审核者。学段与地区不等同于版权地域限制；课程归属与 rights_scope 必须分开。

## 4. 题单

Collection 元数据：id、title、description、owner_id、visibility、curriculum_release_id、created_at、updated_at。CollectionItem：problem_id、ordinal、可选 recommended_revision_id、讲解策略。发布后推荐 revision 不冻结用户答题的 revision；学生打开题目时服务端提供精确 revision ID。导入的原试卷视作 ExamPaper/Collection 专门子类，保留题号、分数、总时长，不在 MVP 做完整考试监考。

题单类型：官方专题、知识点训练、教师指定、个人收藏、错题集（动态）。公开题单的每个条目发布前再次检查题目的 visibility 与 rights。

## 5. 学习记录与误区标签

一轮 Attempt 表示学生打开某版本题目的练习会话；允许同题多次 Attempt。Submission 一次具体小问提交；Evaluation 是可追加的判分记录，regrade 不删除旧评测。进度汇总：attempt_count、accepted_count、latest_state、time_spent（显式或可靠测量，否则不统计）、last_attempt_at。小问与题组分开计算，避免“三小问只对一问”记为整题完全正确。

知识点表现 P0 仅基于 RevisionPart 的 tested 节点展示尝试次数与正确比例，注明样本不足；不以此声称严谨的能力值。P2 可引入 Bayesian Knowledge Tracing/IRT，但需要题目校准与测试数据。

## 6. 错题与重做

错误定义：已完成数学判定且 rejected/partial；invalid_response、engine_error、pending_review 不能自动加错题。错题支持人工加入/移除，记录 origin_submission_id 和 revision_part_id；遇到题目新版本，回顾显示原作答版本与当前可练习版本间的变化提示。

## 7. 学生数据保留与导出

提供按本人账户查询历史；根据适用法律/合同定义用户删除和数据保留流程。分析事件采用去标识/最小化策略，不将原始答案长期发给非必要的第三方分析工具。对未成年人学习数据，明确监护、地区法域及学校授权边界；学校/教师端默认不能浏览所有学生细粒度日志。

## 8. 事件埋点与漏斗

核心事件：search_performed（过滤条件与匿名聚合）、problem_viewed、attempt_started、part_submitted、evaluation_finalized、solution_viewed、bookmark_toggled、content_reported。禁止把学生答卷全文放进通用 analytics 事件。漏斗：search → detail → attempt → submission → result → second_attempt；分析分母含 eligible public problem。

## 9. 验收标准

- 多来源 exact duplicate 仅一条公共结果；不同变量/条件的变体仍独立展示。
- 搜索筛选刷新后不丢状态；无结果和无权限状态区分。
- 部分得分小问不导致题组错误统计为全对。
- 重判后历史可见两个 evaluation，最新有效判定被聚合采用并可追溯。
- 学生 A 无法访问学生 B 的详细 submissions/progress/bookmarks。
