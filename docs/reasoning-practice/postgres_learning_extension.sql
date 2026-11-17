-- PROPOSED PostgreSQL learning-domain extension for LeetMath.
-- Requires existing canonical tables: users(id), problem_revisions(id), revision_parts(id),
-- solutions(id), knowledge_nodes(id). Existing physical types are assumed UUID.
-- This SQL is an architectural draft, not a tested Alembic migration.
CREATE TABLE IF NOT EXISTS reasoning_paths (
 id uuid PRIMARY KEY, revision_part_id uuid NOT NULL REFERENCES revision_parts(id),
 solution_id uuid REFERENCES solutions(id), approach text NOT NULL,
 version_no integer NOT NULL CHECK(version_no>0),
 status text NOT NULL CHECK(status IN ('draft','reviewed','published','retired')),
 content_hash text NOT NULL, reviewer_id uuid REFERENCES users(id),
 UNIQUE(revision_part_id,approach,version_no)
);
CREATE TABLE IF NOT EXISTS reasoning_steps (
 id uuid PRIMARY KEY, reasoning_path_id uuid NOT NULL REFERENCES reasoning_paths(id),
 semantic_key text NOT NULL, step_order integer NOT NULL CHECK(step_order>0),
 version_no integer NOT NULL DEFAULT 1 CHECK(version_no>0),
 recall_cue jsonb NOT NULL, reference_reasoning jsonb NOT NULL,
 max_points numeric(8,2) NOT NULL CHECK(max_points>0),
 criticality text NOT NULL DEFAULT 'supporting' CHECK(criticality IN ('supporting','key','hinge')),
 content_hash text NOT NULL, supersedes_step_id uuid REFERENCES reasoning_steps(id),
 UNIQUE(reasoning_path_id,step_order), UNIQUE(reasoning_path_id,semantic_key,version_no)
);
CREATE TABLE IF NOT EXISTS step_dependencies (
 step_id uuid NOT NULL REFERENCES reasoning_steps(id),
 prerequisite_step_id uuid NOT NULL REFERENCES reasoning_steps(id),
 PRIMARY KEY(step_id,prerequisite_step_id), CHECK(step_id<>prerequisite_step_id)
);
-- A DAG cycle detector and step score-sum validation must run as transaction-bound publish guards.
CREATE TABLE IF NOT EXISTS step_knowledge_links (
 step_id uuid NOT NULL REFERENCES reasoning_steps(id),
 knowledge_node_id uuid NOT NULL REFERENCES knowledge_nodes(id),
 relation text NOT NULL CHECK(relation IN ('tested','prerequisite','related')),
 relevance_weight numeric(7,5) NOT NULL CHECK(relevance_weight>0 AND relevance_weight<=1),
 PRIMARY KEY(step_id,knowledge_node_id,relation)
);
CREATE INDEX IF NOT EXISTS ix_step_knowledge ON step_knowledge_links(knowledge_node_id,relation);
CREATE TABLE IF NOT EXISTS learning_attempts (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
 problem_revision_id uuid NOT NULL REFERENCES problem_revisions(id),
 status text NOT NULL CHECK(status IN ('active','awaiting_feedback','finished','abandoned')),
 sequence_policy text NOT NULL, algorithm_version text NOT NULL,
 started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz
);
CREATE INDEX IF NOT EXISTS ix_learning_attempts_user ON learning_attempts(user_id,started_at DESC);
CREATE TABLE IF NOT EXISTS learning_attempt_cards (
 attempt_id uuid NOT NULL REFERENCES learning_attempts(id), sequence_no integer NOT NULL CHECK(sequence_no>0),
 step_id uuid NOT NULL REFERENCES reasoning_steps(id),
 allocated_max_points numeric(8,2) NOT NULL CHECK(allocated_max_points>0),
 PRIMARY KEY(attempt_id,sequence_no), UNIQUE(attempt_id,step_id)
);
CREATE TABLE IF NOT EXISTS step_review_events (
 id uuid PRIMARY KEY, attempt_id uuid NOT NULL REFERENCES learning_attempts(id),
 step_id uuid NOT NULL REFERENCES reasoning_steps(id),
 sequence_no integer NOT NULL, user_id uuid NOT NULL REFERENCES users(id),
 rating text NOT NULL CHECK(rating IN ('know','fuzzy','unsure')),
 self_score numeric(8,2) NOT NULL CHECK(self_score>=0), max_points numeric(8,2) NOT NULL CHECK(max_points>0),
 reveal_count integer NOT NULL DEFAULT 1 CHECK(reveal_count>=0),
 hint_count integer NOT NULL DEFAULT 0 CHECK(hint_count>=0),
 event_source text NOT NULL DEFAULT 'self_report',
 content_snapshot_hash text NOT NULL, scheduler_version text NOT NULL,
 client_event_id uuid NOT NULL,
 occurred_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(attempt_id,sequence_no), UNIQUE(attempt_id,client_event_id)
);
CREATE INDEX IF NOT EXISTS ix_reviews_user ON step_review_events(user_id,occurred_at DESC);
CREATE TABLE IF NOT EXISTS knowledge_self_assessments (
 id uuid PRIMARY KEY, attempt_id uuid NOT NULL REFERENCES learning_attempts(id),
 user_id uuid NOT NULL REFERENCES users(id), knowledge_node_id uuid NOT NULL REFERENCES knowledge_nodes(id),
 level smallint NOT NULL CHECK(level BETWEEN 1 AND 4),
 occurred_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(attempt_id,knowledge_node_id)
);
CREATE TABLE IF NOT EXISTS step_review_state (
 user_id uuid NOT NULL REFERENCES users(id), step_id uuid NOT NULL REFERENCES reasoning_steps(id),
 scheduler_version text NOT NULL, due_at timestamptz NOT NULL,
 stability real CHECK(stability>=0), difficulty real,
 review_count integer NOT NULL DEFAULT 0 CHECK(review_count>=0),
 last_grade text, last_reviewed_at timestamptz,
 PRIMARY KEY(user_id,step_id,scheduler_version)
);
CREATE INDEX IF NOT EXISTS ix_review_due ON step_review_state(user_id,due_at);
CREATE TABLE IF NOT EXISTS knowledge_evidence (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
 knowledge_node_id uuid NOT NULL REFERENCES knowledge_nodes(id),
 evidence_kind text NOT NULL CHECK(evidence_kind IN ('self_rating','self_assessment','verified_submission','teacher_assessment')),
 source_event_id uuid, observed_result real NOT NULL CHECK(observed_result>=0 AND observed_result<=1),
 evidence_weight real NOT NULL CHECK(evidence_weight>0),
 model_version text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_knowledge_evidence_user ON knowledge_evidence(user_id,knowledge_node_id,occurred_at DESC);
CREATE TABLE IF NOT EXISTS knowledge_state_snapshots (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
 knowledge_node_id uuid NOT NULL REFERENCES knowledge_nodes(id),
 model_version text NOT NULL, estimate real CHECK(estimate BETWEEN 0 AND 1),
 uncertainty real, evidence_count integer NOT NULL CHECK(evidence_count>=0),
 input_hash text NOT NULL, computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS learning_xp_awards (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
 review_event_id uuid NOT NULL UNIQUE REFERENCES step_review_events(id),
 reward_type text NOT NULL, points integer NOT NULL CHECK(points>=0),
 awarded_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS recommendation_runs (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
 input_snapshot_hash text NOT NULL, algorithm_version text NOT NULL,
 output_json jsonb NOT NULL, explanation text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);