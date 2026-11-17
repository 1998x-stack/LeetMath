# 06｜数学答案判题与评分规则 PRD

版本 v0.1。原则：**可确定验证的自动判题优先；不可确定的输出 pending_review，而不是编造“正确/错误”。** 判题的所有输入、策略、评分规则与引擎版本均可追溯。

## 1. 判题状态与语义

evaluation.status ∈ queued / running / accepted / rejected / partial / invalid_response / pending_review / engine_error / cancelled。只有 accepted/rejected/partial 是数学判定；invalid_response 指格式/类型不合法，engine_error 指系统/引擎不可用，不记录成学生数学错误。score 是 0..max_score，pending_review 时可为空。

## 2. 各题型判定矩阵

| response_type | P0 策略 | 容差/特殊点 | 不支持时 |
|---|---|---|---|
| single_choice | 选项 ID 精确比较 | 选项文字可变，ID 稳定 | invalid |
| multiple_choice | 集合比较，默认全对才满分 | 可配置部分得分 | manual |
| integer | 安全解析整数 | 正负号/前导 0 | invalid |
| rational | 约分后精确比较 | 0 分母非法 | invalid |
| decimal | Decimal 比较 | abs/relative tolerance 明示 | manual |
| expression | SymPy 安全白名单解析 + 化简 | 变量定义域、极点、函数分支 | pending_review |
| interval/set | 区间端点、开闭、有序性/集合无序 | 无穷、并集、空集 | pending_review |
| equation_set | 解集归一和候选验根 | 增根/漏根 | pending_review |
| matrix/vector | 形状与分量逐项判断 | 可配置符号等价 | pending_review |
| derivation | 人工 rubric 或已验证结构化中间步骤 | 论证依赖、步骤分 | pending_review |
| proof | 人工按评分点审核 | 不依赖大模型自信度 | pending_review |
| drawing | 人工/受控几何约束验证 | 几何退化情形 | pending_review |

## 3. 表达式判题规范

执行顺序：解析输入（限定 token、函数与深度）→ 检查变量、参数假设、单位和定义域 → 表达式规范化 → exact symbolic relation → 若无法证明等价，按策略执行随机/确定性数值反例检查 → 仍不确定则 pending_review。

数学判定：对于应答式与标准式 A, B，先验证定义域在题目所给假设内兼容，然后尝试 simplify(A-B) == 0。仅出现多个数值点接近 **不能证明恒等**；随机采样只可用于发现反例或提示审查，不可单独作为严格正确依据。复杂表达式的分支、对数、绝对值、三角周期、矩阵和根式要专门测试。需保存假设与解析器版本。

安全：不得调用 Python eval/exec，不允许将用户输入作为可执行代码；SymPy parser 要使用显式安全 token/函数白名单和独立无网络沙箱、资源限额、时间限额、内存限额、最大表达式树深度与输入长度。SymPy 本身的数学 API 不自动构成安全沙箱。

## 4. 评分规则结构

Rubric = criteria[]，每条包括 criterion_id、description、max_points、evidence_required、dependencies[]、mistake_codes[]、manual_or_auto、partial_rules。rubric 的总分严格等于 Part.max_score。变更 rubric 新建 spec version；旧 Submission 按原 spec 解释。

实例（函数与导数）：
- Part 1：乘积求导 1 分，求导结果正确 2 分；也可配置“最终式正确=满分”的互斥策略，避免双重计算。
- Part 2：临界点 x=e^(a-1) 2 分；导数符号正确 2 分；最小值 -e^(a-1) 1 分。
- Part 3：指出利用函数最小值并有推导 3 分；定义域/参数域说明 1 分；正确得出不等式并讨论等号条件 2 分。

以上是教学示例，不是任何官方试卷既定评分标准。

## 5. 反馈内容与可解释性

返回 evaluation_id, status, score, max_score, result_code, checker_version, message, matched_criteria[], unmatched_criteria[], evidence_refs[], regrade_eligible。前台不要泄露私有题库隐藏答案、内部敏感测试数据、其他学生答案。初次答题的解析展示遵循题目策略（提交后/教师开放/始终公开）。

## 6. 人工复核与争议

proof/derivation 类型或符号引擎不确定 → manual_queue（可由人工读题、步骤、标准解和 rubrics）；两位审核意见不一致则升级教研负责人。学生报告可指向一次 evaluation；重大误判可批量创建 regrade_job，不覆盖旧结果，追加新 evaluation 并记录 reason, evaluator, time, previous_evaluation_id。前台显示“评分已修订”。

## 7. 引擎接口与任务状态

~~~json
{
  "submission_id": "uuid",
  "revision_part_id": "uuid",
  "answer_spec_id": "uuid",
  "grader": {"name": "sympy", "version": "1.0.0"},
  "response": {"type": "expression", "input": "ln(x)+1-a"},
  "constraints": {"assumptions": {"x": "positive", "a": "real"}},
  "idempotency_key": "client-generated-uuid"
}
~~~

提交先事务性存数据库并返回 202/结果 ID；后台判题异步执行，通过 evaluation 状态轮询或 SSE 推送。重复同一个 submission + grader version 不能重复计分。重判必须指定新 revision/原因，保留事件链。

## 8. 测试数据（黄金样本必须含正确/错误/边界）

1. f'(x)=ln(x)+1-a，与 ln(x)-(a-1) 等价。
2. ln(x)+1-a 与 ln(abs(x))+1-a 在 x>0 条件下通常可等价，必须验证假设；不要去掉 x>0。
3. x/(x) 与 1 在 x=0 的定义域不同，不能无条件通过。
4. sqrt(x^2) 与 x 在 x∈R 不等价。
5. tan(x) 与 sin(x)/cos(x) 在极点讨论中需检查定义域。
6. (x-1)/(x-1)=1 非全域恒等。
7. 数值 1/3 与 0.333 在精确模式不等价，但容差模式根据明确 epsilon 判定。
8. 接收到非法代码/巨型表达式被拒绝，不能执行。
9. 引擎超时变 pending_review/engine_error，不能记数学错误。
10. 任一已发布答案规则更新后，历史判分仍可展示原版本和重判结果。

## 9. MVP 退出门槛

P0 自动题型以 300+ 已人工标注的正反/边界用例进行自动回归（用例数量为建议目标），严重误判 0；证明题必须具备人工工作流或明确声明不提供评分；平均排队时长、超时、false-positive 申诉有持续监控。
