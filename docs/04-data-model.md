# 04｜PostgreSQL 数据模型、ER 关系与演进

版本 v0.1 · PostgreSQL 15+ 推荐。此文档是逻辑结构与关键 DDL 示例，不是已经执行过的完整迁移文件。实现时以 Alembic migration + CI 初始化数据库为准。

## 1. 领域划分与 ER

~~~mermaid
erDiagram
  SOURCES ||--o{ SOURCE_RECORDS : owns
  SOURCE_RECORDS ||--o{ SOURCE_RECORD_REVISIONS : has
  SOURCE_RECORDS }o--|| PROBLEMS : maps_to
  PROBLEMS ||--o{ PROBLEM_REVISIONS : publishes
  PROBLEM_REVISIONS ||--o{ REVISION_PARTS : contains
  REVISION_PARTS ||--o{ ANSWER_SPECS : defines
  REVISION_PARTS ||--o{ SOLUTIONS : explains
  PROBLEM_REVISIONS ||--o{ REVISION_ASSETS : attaches
  ASSETS ||--o{ REVISION_ASSETS : referenced
  CURRICULUM_RELEASES ||--o{ KNOWLEDGE_NODES : contains
  KNOWLEDGE_NODES ||--o{ REVISION_KNOWLEDGE : mapped
  PROBLEM_REVISIONS ||--o{ REVISION_KNOWLEDGE : tested
  USERS ||--o{ ATTEMPTS : starts
  ATTEMPTS ||--o{ SUBMISSIONS : includes
  REVISION_PARTS ||--o{ SUBMISSIONS : answered
  SUBMISSIONS ||--o{ EVALUATIONS : evaluated
  IMPORT_BATCHES ||--o{ IMPORT_ROWS : processes
  SOURCES ||--o{ IMPORT_BATCHES : imports
~~~

## 2. 实体清单与必要约束

### A. 来源与治理
- sources(id, code UNIQUE, name, kind, homepage, owner, status, created_at)。
- rights_grants(id, source_id, grant_type, scope, territory, permitted_actions, valid_from, valid_to, evidence_asset_id, status)；可多条授权，按具体使用场景判定有效许可。
- source_records(id, source_id, external_id, latest_source_revision, canonical_problem_id nullable, created_at)，UNIQUE(source_id, external_id)。
- source_record_revisions(id, source_record_id, external_revision, raw_asset_id, raw_sha256, normalizer_version, normalized_payload, imported_at)，UNIQUE(source_record_id, external_revision)，来源无版本号时用带内容 hash 的伪版本。
- import_batches(id, source_id, manifest_hash, importer_version, initiated_by, state, counts_json, started_at, finished_at)。
- import_rows(id, batch_id, source_record_key, row_no, raw_sha256, state, error_code, outcome_entity_id)，UNIQUE(batch_id, row_no)。
- duplicate_candidates(id, left_source_record_revision_id, right_problem_id, score, signals_json, status, reviewer_id, decision_reason)。
- content_reports(id, reporter_id, problem_revision_id, revision_part_id nullable, kind, severity, state, reviewer_id, resolution)。
- audit_events(id, actor_id, action, entity_type, entity_id, before_hash, after_hash, metadata, created_at)，仅追加。

### B. 规范题目
- problems(id UUID PK, display_id UNIQUE, slug UNIQUE, grade_band, subject, created_at, deleted_at nullable)。
- problem_revisions(id UUID PK, problem_id FK, revision_no, status, locale, shared_statement JSONB, title, content_hash, rights_grant_id, published_at, created_by, UNIQUE(problem_id, revision_no))。
- logical_parts(id UUID PK, problem_id FK, stable_label nullable)。
- revision_parts(id UUID PK, problem_revision_id FK, logical_part_id FK, display_order, prompt JSONB, response_type, max_score, UNIQUE(problem_revision_id, logical_part_id), UNIQUE(problem_revision_id, display_order))。
- answer_specs(id UUID PK, revision_part_id FK, spec_version, grading_mode, schema JSONB, checker_config JSONB, UNIQUE(revision_part_id, spec_version))。
- rubrics(id UUID PK, answer_spec_id FK, rubric_version, criteria JSONB, sum_score, reviewer_id)。
- solutions(id UUID PK, revision_part_id FK, solution_type, content JSONB, validation_state, reviewer_id)。
- assets(id UUID PK, sha256 UNIQUE, object_key UNIQUE, media_type, size_bytes, license_ref, scan_status)。
- revision_assets(revision_id, asset_id, role, alt_text, PRIMARY KEY(revision_id, asset_id, role))。
- problem_relations(id, from_problem_id, to_problem_id, relation_type, decision_by, reason, UNIQUE(from_problem_id,to_problem_id,relation_type))。

### C. 课程与学习
- curriculum_systems(id, code UNIQUE, region, grade_band, label)。
- curriculum_releases(id, system_id, release_code, valid_from, source_ref)。
- knowledge_nodes(id, release_id, external_code, parent_id nullable, title, level, UNIQUE(release_id,external_code))。
- knowledge_edges(from_node_id,to_node_id,relation_type, UNIQUE(from_node_id,to_node_id,relation_type))。
- revision_knowledge(revision_id, knowledge_node_id, relation_type, weight)。
- users(id, auth_subject UNIQUE, role, privacy_flags, created_at)。
- attempts(id, user_id, problem_revision_id, state, started_at, finished_at)。
- submissions(id, attempt_id, revision_part_id, answer_spec_id nullable, response JSONB, idempotency_key, created_at, UNIQUE(attempt_id,idempotency_key))。
- evaluations(id, submission_id, grader_name, grader_version, state, score, max_score, feedback JSONB, confidence nullable, created_at)。
- collections(id, owner_id, slug, title, visibility) + collection_items(collection_id, problem_id, ordinal)。
- bookmarks(user_id, problem_id, created_at, PK(user_id,problem_id))；mistake_marks(user_id, revision_part_id, origin_submission_id)。
- security_events / content_access_logs：必要时独立保留策略，避免在原始 audit_events 里收集不必要的学生敏感数据。

## 3. 发布快照 + 数据隔离

Draft revision 的文本可以编辑；Publish 事务锁定 revision，验证所有引用与答案，复制必要快照/计算 hash，切换状态并更新 problems.current_public_revision_id（可以只引用一个默认区域/语言主版本）。发布版本数据库层通过触发器/权限阻止正文修改；仅允许权限管理通过独立 rights decision 覆盖公开可见状态。

SourceRecord 的 raw_payload 不直接对普通题库 API 输出。前台公开题要求：problem_revision.status='published' 且有效 rights_grant 允许 display，且无 takedown hold。私有和授权限范围资源的对象存储必须采用短效签名 URL 并逐请求验证范围。

## 4. 关键 SQL 草图

~~~sql
CREATE TABLE problems (
  id uuid PRIMARY KEY,
  display_id text NOT NULL UNIQUE,
  slug text NOT NULL UNIQUE,
  grade_band text NOT NULL,
  subject text NOT NULL DEFAULT 'mathematics',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE problem_revisions (
  id uuid PRIMARY KEY,
  problem_id uuid NOT NULL REFERENCES problems(id),
  revision_no integer NOT NULL CHECK (revision_no > 0),
  status text NOT NULL CHECK (
    status IN ('draft','in_review','approved','published','archived','retracted')
  ),
  locale text NOT NULL DEFAULT 'zh-CN',
  title text NOT NULL,
  shared_statement jsonb NOT NULL,
  content_hash text,
  published_at timestamptz,
  UNIQUE(problem_id, revision_no)
);

CREATE TABLE logical_parts (
  id uuid PRIMARY KEY,
  problem_id uuid NOT NULL REFERENCES problems(id)
);
CREATE TABLE revision_parts (
  id uuid PRIMARY KEY,
  problem_revision_id uuid NOT NULL REFERENCES problem_revisions(id),
  logical_part_id uuid NOT NULL REFERENCES logical_parts(id),
  display_order integer NOT NULL CHECK (display_order > 0),
  prompt jsonb NOT NULL,
  response_type text NOT NULL,
  max_score numeric(8,2) NOT NULL CHECK (max_score > 0),
  UNIQUE(problem_revision_id, logical_part_id),
  UNIQUE(problem_revision_id, display_order)
);
~~~

重要：示例只覆盖核心表；并非可执行的全量生产 schema。物理 schema 应添加外键复合约束保证 logical_part_id 所属 problem 与 revision 的 problem_id 一致；对枚举词表采用版本化 code table 或 CHECK + 迁移。

## 5. 索引设计（建议）

- source_records：唯一 (source_id, external_id)；import_rows：(batch_id,state)、(source_record_key)。
- problem_revisions：(problem_id,revision_no DESC)、(status,published_at DESC)、对 JSONB 结构化字段仅按真正查询路径添加 GIN。
- search_documents：预计算 title/body/part/knowledge 文本，中文分词与高亮优先选择专门搜索引擎；MVP 可用 Postgres trigram + 标准化关键词，不假定默认中文 FTS 理想。
- submissions：(user_id 通过 attempt 关联的分页策略)、(attempt_id,created_at DESC)；evaluations：(submission_id,created_at DESC)。
- duplicate_candidates：(status,score DESC)，(left_source_record_revision_id)。
- audit_events：(entity_type,entity_id,created_at DESC)。

## 6. 容量与分区策略

MVP 10 万题、百万提交规模可从单 PostgreSQL + object storage 起步（是容量规划目标，不是性能保证）。提交增长明显后先做 index/归档/冷热分离，再考虑按 created_at 对 submissions/evaluations 按月分区。图片、原始 PDF、Manim 代码/视频不进入数据库大字段；放对象存储并维护 sha256、内容签名和引用关系。

搜索如需中文分词、公式或相似检索再引入 OpenSearch/Meilisearch/pgvector，采用 outbox 增量重建，Postgres 仍是权威数据源。

## 7. 事务与一致性

发布：一次事务内完成 revision 状态校验、题目公开版本指针切换、outbox event；订阅者可重试且幂等。导入：逐条 upsert SourceRecord，记录导入行结果；不能因为一行失败回滚整批成功记录。收藏：用户与题目唯一约束 + 幂等 UPSERT。判题：提交先落库后发 evaluation job；同一 submission + grader_version 重试不重复计分。

## 8. 迁移与历史稳定

Alembic migrations 前滚、必要时可补偿回滚；禁止直接 DROP 仍被历史作答引用的 RevisionPart/AnswerSpec/Grader。字段变更采用 expand → backfill → dual read → cutover → contract。源外部 ID 更名必须留 alias，不覆盖历史 source_record_id。权利过期不删除内容记录，但前台访问立即阻断，并按合同/法律的保留政策处理。
