# LeetMath Reasoning Practice — 竞品调研与架构差异

研究时间：2026-11-17。文档区分：①直接读过 GitHub 的事实，②产品讨论中的个别用户评论，③我们自己的设计建议。所有外链为原始入口，不能将个别评论视为统计学结论。

## 1. 已核对的两个仓库

- [LeetMath PRD 分支](https://github.com/1998x-stack/LeetMath/tree/docs/phase1-prd-and-content-platform)（检查 commit: `367f6009a1f35d41e6ff545b20a1284069240358`）有 README + `docs/00`～`docs/12` 共 13 篇专项规范、JSON/OpenAPI 例子。其 README 明确说处在设计阶段，并未上线产品。
- [hashcards-local](https://github.com/1998x-stack/hashcards-local)（检查 main，当时 HEAD 为 `ea7c0ac7e6eb9db35db30d24e6054cb42c31e8d1`）以 Rust、SQLite、文本卡片、本地 Web Drill、KaTeX、FSRS 做轻量间隔重复。`src/schema.sql` 的三张主表：cards、sessions、reviews；练习选项 Forgot / Hard / Good / Easy。README 指出卡片以文本 hash 定位，修改文本会重置进度；支持 sibling burial、Cloze、图片和复习历史。

## 2. LeetMath 现有规范与新需求对照

| 原规范 | 已确定设计 | 本次需求产生的差异 | 建议处理 |
|---|---|---|---|
| `00-product-strategy` / `01-phase1-prd` | Phase 1 题库、CMS、正确性判题；Phase 3 才有学生逐步骤诊断 | 用户要求步骤复习是最先感知的核心功能 | 新设 `Phase 1.5: Reasoning Practice` 的独立纵向试点；不重写 Phase 1 的题库治理规则 |
| `03-content-contract` | Problem / immutable Revision / logical Part / AnswerSpec / Solution | 缺少可复习的稳定 Reasoning Step 身份、提问用的 Recall Cue 和具体权重 | 添加 StepRevision/ReasoningCard + criterion links，绝不修改已发布 Revision |
| `04-data-model` | PostgreSQL 权威库、attempt/submission/evaluation、rights | 缺逐步复习事件、知识自评、调度状态、XP、能力证据 | 在 learning schema 下追加规范化表，复用标准用户与内容主键 |
| `06-judging-and-rubrics` | 数学正确性与手工证明评分，评测有版本 | “知道/模糊/不确定”不是数学判题 | 创建 `recall_self_rating`（自报）与 `evaluation`（验证）两个独立事实源 |
| `09-search-and-learning` | 知识点筛选、提交历史、正确率，禁止过度声称掌握度 | 需要历史曲线、雷达、推荐 | 标示证据指数、样本量、置信度、可解释的推荐原因 |
| `11-quality-security-ops` | 未成年人隐私、版权范围、XSS/IDOR、角色权限 | 需要本地用户和学生训练事件 | 小规模本地 demo 与公网生产明确分离；全量安全边界仍适用 |
| `12-future-phases-and-adrs` | Manim / interactive / steps 分 Phase 2/3 | 本次要先有几何可视化 + 步骤卡体验 | 2D Canvas + Three.js 在 Phase 1.5 作为可降级组件，不依赖 AI 或视频渲染 |

## 3. Product Hunt、Hacker News 研究摘要

| 来源（直接网址） | 可观察的个别评论主题 | 设计推断及应验证假设 |
|---|---|---|
| [RemNote Product Hunt](https://www.producthunt.com/products/remnote) | 笔记卡片一体化有用；评论也抱怨操作复杂、标签和组织信息难懂 | 让“学生练习”和“教师内容编辑”分成不同工作台，学生界面不出现复杂配置 |
| [Mochi Product Hunt](https://www.producthunt.com/products/mochi) | Markdown 制卡低摩擦，个别用户反映同步可靠性问题 | 卡片即时入库、幂等提交、断网处理和可靠历史比动效重要 |
| [Knowt Product Hunt](https://www.producthunt.com/products/knowt) | 快速生成问答很吸引人，用户反映生成题含糊及注册摩擦 | 生成步骤需数学教师审校；访客只读浏览、本地快速创建账号 |
| [Math Academy HN](https://news.ycombinator.com/item?id=41534847) | 对自适应薄弱点识别有正面反馈，也有 XP 惩罚感、加载慢、移动端体验的抱怨 | 分数不惩罚诚实自评，XP 鼓励参与而非点击“会了”；复习队列低延迟 |
| [数学/算法题间隔重复 HN](https://news.ycombinator.com/item?id=21219204) | 有人认为应复习一般化的模式，而非逐字记住完整解答 | 关键思维转折点作为最小练习单元；隔离兄弟步骤；同构变式防止记忆污染 |
| [Spaced Repetition HN](https://news.ycombinator.com/item?id=19827910) | 评论指出原题重复会让人记忆表面特征，无法迁移 | 用变式题与间隔回忆测验检验泛化，不能把记住题目等同理解概念 |

**研究限制**：以上主要是公开用户反馈中出现过的问题，不是分层随机样本；没有据此估算留存率、市场规模或用户满意度。

## 4. 推荐决策记录

### ADR-R01：知识标签 ≠ 概念节点 ≠ 错因

`knowledge_nodes` 是有课程版本、先修边的本体节点；`content_tags` 是搜索和组织便利标签；`mistake_codes` 是教学诊断，往往映射多个知识点。重复训练优先使用 `tested knowledge`、`step_dependencies` 与实际观测，不以自由文本 tags 作为唯一调度来源。

### ADR-R02：Self-rating 与 mathematical grading 隔离

“我知道”代表用户主观回忆信心，不意味着已独立作对。屏幕显示“自评步骤分”；正式成绩只来自经校验 submission/evaluation，数学证明题不可将用户自信点选变成标准得分。保存 `evidence_type`、`grader_version` 和 `source_confidence`。

### ADR-R03：保存不可变步骤版本

现有内容不可变 Revision 原则继续适用。教学编辑调整思路、顺序、cue、重要度时形成新的 `reasoning_step_revisions`；旧复习仍绑定旧版本。建立手工审校的 `supersedes` 映射后才能转移调度状态，防止单纯 hash 变化导致历史消失。

### ADR-R04：FSRS 只是记忆调度，不是数学能力评分

后续使用官方兼容 FSRS 库调度每张卡，保留 stability / difficulty / due 与 scheduler_version。知识能力模型独立，用教师分值权重、经过验证的独立作答、练习提示、自评和样本量作为证据。MVP 的固定 1/3/7 天是刻意简化，**不是 FSRS**。

### ADR-R05：可持续的轻度游戏感

清楚展示进度、关键步骤、XP 和当次反馈；每日建议 10–15 分钟，可随时停止并保留学习记录；不设计无穷刷题和惩罚式连续签到。未成年人默认不设公开排行榜。

## 5. 关键用户访谈与可用性验证（下阶段）

应观察 8–12 位不同数学基础的学生以及 3–5 位教师；不是已完成的研究。重点测量：在步骤尚未揭晓时能否理解操作、是否认为自评代表考试分数、是否能区分“看懂”和“独立想出”、3D 旋转是否改善空间几何理解、能否在手机 375px 宽完成整题、错误/恢复时是否丢失进度，以及 7 日后变式题表现。