# 03｜数学题目内容契约（Math Content Contract v1）

状态：规范草案 · 必须在批量导入前冻结 v1.0 语义。参见 examples/problem-sh-function-001.json。

## 1. 第一原则

（1）“题源记录”不是“平台题目”；（2）“题目稳定身份”不是“发布版本”；（3）“子问逻辑身份”不是“版本中的子问快照”；（4）“展示 LaTeX”不是“数学表达式 AST”；（5）“标准答案”不是“评分策略”；（6）“内容质量”不等于“展示授权”。

## 2. Math Item 层级与不变量

~~~text
Source ─── SourceRecord ─── SourceRecordRevision
                    \          |
                     \   canonical mapping
                      v
Problem (stable ID) ── ProblemRevision (immutable after publish)
                          ├── shared_statement
                          ├── RevisionPart[*] -> AnswerSpec / Rubric / Solution
                          ├── AssetReferences[*]
                          └── CurriculumMappings / Tags
~~~

- Problem.id = UUID / ULID，永不使用来源自带题号；display_id 为用户可见编号（唯一，不可复用）。
- ProblemRevision.id = UUID，(problem_id, version_no) 唯一；content_hash 用规范序列化后 sha256 计算。
- RevisionPart.id = UUID（版本内实体）；logical_part_id 在不同修订间表示同一语义小问；part_key（"1","2","3"）是展示序号，随排序可变，不用于历史提交外键。
- 默认一份题组有 1…N 个 Part；单问题也视为只有一个 Part。
- Submissions 引用精确的 revision_part_id 和 answer_spec_id（若不存在则允许待人工评分）、grader_version。
- 更新已发布内容创建新版本；任何媒体替换也产生明确可审核的新修订。
- 原版题全文及来源记录受许可约束，必要时不得对公网输出。

## 3. 公共内容字段

| 字段 | 必填 | 说明 |
|---|---|---|
| schema_version | 是 | 使用语义版本 v1.x |
| problem.id/display_id/slug | 是 | 内部 ID、用户题号、URL 别名 |
| problem.grade_band | 是 | primary/junior_high/senior_high/undergrad 等注册词表 |
| revision.revision_no/status | 是 | 版本号与草稿、发布状态 |
| revision.locale | 是 | zh-CN / en 等 BCP 47 |
| revision.shared_statement | 是 | MathRichText（可空但 Part 内容不可空） |
| revision.parts | 是 | 长度 >= 1、稳定 logical_part_id |
| revision.content_metadata | 是 | 编目、难度、题型、学科、审校 |
| source_record_refs | 是 | 原创同样需要内部来源 |
| rights_policy_ref | 是 | 可见性/许可范围 |
| assets | 否 | 图片、SVG、附件的对象引用及校验和 |
| lineage | 否 | 改编自/重复/同构/翻译等关系 |

## 4. MathRichText 规范

存为有结构的块（blocks），不将未经净化的整段 HTML 直接存数据库。最小 block 类型：
- paragraph: spans(text, inline_math, emphasis, link)；
- display_math: latex（必填）、alt_text（强烈建议），可选 canonical_expr；
- image: asset_id、alt、宽高、license_ref；
- table: 结构化 rows/cells；
- list: 有序/无序；
- diagram: asset_id + semantic_geometry（可选）。

MathRichText 保存编辑结构，服务端输出可净化 Markdown/KaTeX 表示；任何自定义 HTML、JS、data URL、远程图床默认禁止。所有公式 LaTeX 经渲染预检，保存原始文字以便回溯。不得使用简单字符串 trim/lowercase 将数学题判定为“完全重复”。

## 5. 题目种类与答案语义

response_type 标准词表：
- single_choice / multiple_choice：选项 ID 与正确集合，支持“多选少选部分得分”策略版本；
- integer / decimal / rational：数值、容差、有效数字、单位、分母不为 0；
- expression：LaTeX 展示 + 安全解析 canonical_expr，变量假设、定义域与等价范围；
- equation_set / interval / set：顺序无关集合/区间等价，开闭区间与定义域；
- matrix / vector：维度、顺序与分量判定；
- short_text：默认人工审核，词面匹配仅用于非数学语义字段；
- proof / derivation：证明文本、结构化步骤和 rubric；P0 无可靠全自动判分承诺；
- drawing / geometry_construction：保存向量/坐标几何对象；P1+ 先人工审核。

每个 Part 具有 answer_spec_version、grading_mode（automatic/manual/hybrid/practice_only）、max_score、solutions[]、rubric criteria[]。判题器返回 accepted/rejected/partial/pending_review/invalid_response（词汇以 06 号文档为准），不把 parse_error 当 rejected。

## 6. 元数据与课程映射

课程是独立版本化对象：curriculum_system（如 CN-SH-SENIOR-HIGH） → curriculum_release（年份/教材版） → knowledge_nodes（章节、知识点）+ knowledge_edges(prerequisite/related)。ProblemRevision 可以映射多个 curriculum_release；按 tested/related/prerequisite 给关系类型和权重。

分开记录：platform_difficulty(1…10,评估来源) / source_difficulty(原文)；题型、综合程度、预计用时、知识点、年级是独立维度。考试年份/官方真题身份必须有证据字段 verified_by 和 verification_ref，不得从题目文本推断。

## 7. 多语言、变体、重复

localizations 指向同一个逻辑 Problem 但分别修订本地化文本；数学模型不变才允许共享答案规则，否则建立 Variant problem。ProblemRelation：
- exact_duplicate：同内容不同来源，SourceRecord 可映射同一个 Problem；
- adapted_from：非完全相同的合法改编；
- isomorphic_to：方法相近但数值/条件变化；
- translation_of：语义一致且已校核；
- prerequisite_to / companion_of：教学关系。
关联仅在人工确认时生效，保留决定人、理由和证据。软合并保留所有 source IDs、版权范围与历史 URL 映射。

## 8. 内容合法性校验

阻断：缺失可用授权、缺题干或全部小问为空、Part 没有合法输入类型、发布时无可验证答案/人工评分方案、无内容 hash、引用不存在附件、数学渲染致命错误、评测假设不完整或自动判题黄金样例失败。

警告：无 alt、缺难度评定、知识点过少、多来源相似度高、无详细解析、OCR 未全人工核对、题目语言混杂。警告可以被 Reviewer 理由覆盖，阻断项不可豁免（需要修订规则/ADR）。

## 9. 内容版本升级与兼容

schema_version v1.0 以后仅添加可选字段为 minor；字段含义变更、必填字段变更为 major；导入端应支持至少当前和前一个 major 的转换器，失败时保留原始记录并进入隔离队列。规范化算法独立记录 normalizer_version，以便重建 hash / similarity 索引；改变算法不重写原始数据。

## 10. 推荐目录

content-schema/v1/problem.schema.json、part.schema.json、answer-spec.schema.json；fixtures/positive 与 fixtures/negative；对每条样例同时做 JSON Schema + 数学渲染 + 判题 fixture 测试。
