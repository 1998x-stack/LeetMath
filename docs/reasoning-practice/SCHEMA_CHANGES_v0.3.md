# Learning schema v0.3：相对 v0.2 的变更与验证

状态：设计草案。SQL 已在 PostgreSQL 16 上用 `sql-tests/` 做冒烟测试（依赖表用桩代替），**不是** Alembic 迁移，也未覆盖真实主库表。

## 已复现的 v0.2 缺陷（针对原 `postgres_learning_extension.sql`）

| 编号 | 缺陷 | v0.2 实测结果 |
|---|---|---|
| R1 | 事件可以写成“别人的 user_id，挂在我的 attempt 上” | 插入成功 |
| R2 | 事件可以引用不属于该 attempt 的步骤 | 插入成功 |
| R3 | 文档要求“追加纠正事件”，但 `UNIQUE(attempt_id, sequence_no)` 使纠正无法写入 | 唯一约束报错 |
| R4 | 同一路径内无法存放同一步骤的第二个版本 | `UNIQUE(path, step_order)` 报错 |
| R5 | 无任何触发器：发布后可改步骤，分值不守恒也能发布；`step_criteria_links`、标签、牌组表都不存在 | 触发器数量 0 |

## v0.3 的修复

- 事件表：`(attempt_id, user_id)` 与 `(attempt_id, sequence_no, step_id)` 两个复合外键；原始事件每张卡唯一（部分唯一索引），纠正事件通过 `supersedes_event_id` 追加，每个事件至多被纠正一次；视图 `effective_step_review_events` 返回链尾；表为只追加（触发器）。
- 两阶段自评：`commit_rating`、`post_check`（选“没想到”时必须为空，否则必填）、`fsrs_grade`、独立的 `revealed_before_rating`，`self_score <= max_points`。
- 发布门禁 `learning_assert_path_publishable`：步骤分值之和等于小问 `max_score`；依赖不出路径且无环；每步至少一个 `tested` 知识点。已发布路径及其步骤、依赖、知识点链接不可修改，只允许退役。
- 步骤不再带自己的 `version_no`：新版本 = 新的 path 版本，`supersedes_step_id` 指向上一版本的步骤。
- 新增 `step_criteria_links`（按 `(rubric_id, criterion_key)` 关联，因为 04 号文档里 rubric 准则是 JSONB，无法做外键）。
- 新增标签与牌组：`tags`、`problem_tags`、`step_tags`、`mistake_codes`、`mistake_code_knowledge`、`step_mistake_links`、`decks`、`deck_user_settings`、`training_sessions`。
- 新增 `learning_user_prefs`（时区、每日起始小时、每日上限、目标保留率）、`local_credentials`、`auth_sessions`（仅本地部署）。
- `step_review_state` 增加 FSRS 状态字段、搁置、埋藏；XP 改为按用户本地日、按步骤去重，并且为只追加。
- 知识证据增加 `reliability`、`source_step_id`、`probe` 类型；快照拆成 `recall_retention` 与 `verified_accuracy` 两个指标。

## 仍未解决（留给 R1/R2）

- 04 号文档的 `problem_revisions.status` CHECK 只有 6 个值，与 08 号文档的审核流程不一致，需拆成内容状态、审核流转、权利状态三个字段。
- `users.role` 单列与 08 号文档的 7 个角色不匹配，需 `user_roles(user_id, role, scope)`。
- 探针表（`step_probes`）、semantic_geometry 的 JSON Schema 尚未编写。

## 运行测试

```bash
cd docs/reasoning-practice/sql-tests
PGHOST=... PGPORT=... PGUSER=... ./run.sh   # 需要能 createdb 的 PostgreSQL 15+
```
