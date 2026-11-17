-- LeetMath learning domain (Reasoning Practice) — PostgreSQL 15+ — REVISED DRAFT v0.3
--
-- Requires canonical tables from docs/04-data-model.md (UUID keys):
--   users(id), problems(id), revision_parts(id, max_score numeric(8,2)),
--   solutions(id), rubrics(id), knowledge_nodes(id)
-- Smoke-tested on PostgreSQL 16 with docs/reasoning-practice/sql-tests/ (stub dependencies).
-- Still a draft, not an Alembic migration. Changes vs v0.2 are listed in
-- docs/reasoning-practice/SCHEMA_CHANGES_v0.3.md.
--
-- Deliberately NOT "CREATE TABLE IF NOT EXISTS": a migration that meets an existing
-- table with a different shape must fail loudly, not silently skip.

-- ===========================================================================
-- A. Per-user learning preferences (timezone drives due dates, calendar and XP days)
-- ===========================================================================
CREATE TABLE learning_user_prefs (
  user_id uuid PRIMARY KEY REFERENCES users(id),
  timezone text NOT NULL,                      -- IANA name, set from the client; no default on purpose
  day_start_hour smallint NOT NULL DEFAULT 4 CHECK (day_start_hour BETWEEN 0 AND 23),
  show_xp boolean NOT NULL DEFAULT true,
  desired_retention real NOT NULL DEFAULT 0.90 CHECK (desired_retention BETWEEN 0.70 AND 0.99),
  new_per_day integer NOT NULL DEFAULT 10 CHECK (new_per_day >= 0),
  reviews_per_day integer NOT NULL DEFAULT 100 CHECK (reviews_per_day >= 0),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- ===========================================================================
-- B. Local credentials and sessions (local / self-hosted deployment only).
--    04-data-model assumes users.auth_subject comes from an external IdP; local users
--    get auth_subject = 'local:' || id. Passwords: argon2id encoded string only.
-- ===========================================================================
CREATE TABLE local_credentials (
  user_id uuid PRIMARY KEY REFERENCES users(id),
  username text NOT NULL CHECK (username = lower(username) AND length(username) BETWEEN 3 AND 32),
  password_hash text NOT NULL,
  failed_attempts integer NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
  locked_until timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_local_credentials_username ON local_credentials (username);

CREATE TABLE auth_sessions (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  token_hash bytea NOT NULL UNIQUE,            -- SHA-256 of the session token; the token is never stored
  csrf_hash bytea NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  CHECK (expires_at > created_at)
);
CREATE INDEX ix_auth_sessions_user ON auth_sessions (user_id) WHERE revoked_at IS NULL;

-- ===========================================================================
-- C. Reasoning content. A published path is immutable; a new step version means a
--    new path version (steps carry no version_no of their own).
-- ===========================================================================
CREATE TABLE reasoning_paths (
  id uuid PRIMARY KEY,
  revision_part_id uuid NOT NULL REFERENCES revision_parts(id),
  solution_id uuid REFERENCES solutions(id),
  approach text NOT NULL,
  version_no integer NOT NULL CHECK (version_no > 0),
  status text NOT NULL CHECK (status IN ('draft','reviewed','published','retired')),
  content_hash text NOT NULL,
  reviewer_id uuid REFERENCES users(id),
  published_at timestamptz,
  UNIQUE (revision_part_id, approach, version_no)
);

CREATE TABLE reasoning_steps (
  id uuid PRIMARY KEY,
  reasoning_path_id uuid NOT NULL REFERENCES reasoning_paths(id),
  semantic_key text NOT NULL,
  step_order integer NOT NULL CHECK (step_order > 0),
  recall_cue jsonb NOT NULL,
  reference_reasoning jsonb NOT NULL,
  max_points numeric(8,2) NOT NULL CHECK (max_points > 0),
  criticality text NOT NULL DEFAULT 'supporting' CHECK (criticality IN ('supporting','key','hinge')),
  content_hash text NOT NULL,
  supersedes_step_id uuid REFERENCES reasoning_steps(id),   -- step in the previous path version
  UNIQUE (reasoning_path_id, step_order),
  UNIQUE (reasoning_path_id, semantic_key)
);

CREATE TABLE step_dependencies (
  step_id uuid NOT NULL REFERENCES reasoning_steps(id),
  prerequisite_step_id uuid NOT NULL REFERENCES reasoning_steps(id),
  PRIMARY KEY (step_id, prerequisite_step_id),
  CHECK (step_id <> prerequisite_step_id)
);

CREATE TABLE step_knowledge_links (
  step_id uuid NOT NULL REFERENCES reasoning_steps(id),
  knowledge_node_id uuid NOT NULL REFERENCES knowledge_nodes(id),
  relation text NOT NULL CHECK (relation IN ('tested','prerequisite','related')),
  relevance_weight numeric(7,5) NOT NULL CHECK (relevance_weight > 0 AND relevance_weight <= 1),
  PRIMARY KEY (step_id, knowledge_node_id, relation)
);
CREATE INDEX ix_step_knowledge ON step_knowledge_links (knowledge_node_id, relation);

-- 04-data-model stores rubric criteria as JSONB, so a criterion cannot be a foreign key:
-- link by (rubric_id, criterion_key) and validate the key in the application at publish time.
CREATE TABLE step_criteria_links (
  step_id uuid NOT NULL REFERENCES reasoning_steps(id),
  rubric_id uuid NOT NULL REFERENCES rubrics(id),
  criterion_key text NOT NULL,
  score_weight numeric(7,5) NOT NULL CHECK (score_weight > 0 AND score_weight <= 1),
  rationale text,
  PRIMARY KEY (step_id, rubric_id, criterion_key)
);

-- Publish gate: step points sum to the part's max_score, dependencies stay inside the path
-- and form a DAG, every step tests at least one knowledge node.
CREATE FUNCTION learning_assert_path_publishable(p_path uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
  v_part_max numeric;
  v_sum numeric;
  v_cnt integer;
  v_bad integer;
BEGIN
  SELECT rp.max_score INTO v_part_max
    FROM reasoning_paths p JOIN revision_parts rp ON rp.id = p.revision_part_id
   WHERE p.id = p_path;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'reasoning path % not found', p_path USING ERRCODE = 'P0002';
  END IF;

  SELECT count(*), coalesce(sum(max_points), 0) INTO v_cnt, v_sum
    FROM reasoning_steps WHERE reasoning_path_id = p_path;
  IF v_cnt = 0 THEN
    RAISE EXCEPTION 'reasoning path % has no steps', p_path USING ERRCODE = '23514';
  END IF;
  IF v_sum <> v_part_max THEN
    RAISE EXCEPTION 'step points sum % does not equal part max_score % (path %)', v_sum, v_part_max, p_path
      USING ERRCODE = '23514';
  END IF;

  SELECT count(*) INTO v_bad
    FROM step_dependencies d
    JOIN reasoning_steps s ON s.id = d.step_id
    JOIN reasoning_steps q ON q.id = d.prerequisite_step_id
   WHERE s.reasoning_path_id = p_path AND q.reasoning_path_id <> p_path;
  IF v_bad > 0 THEN
    RAISE EXCEPTION 'path % has dependencies that leave the path', p_path USING ERRCODE = '23514';
  END IF;

  IF EXISTS (
    WITH RECURSIVE walk(origin, cur, depth) AS (
      SELECT d.step_id, d.prerequisite_step_id, 1
        FROM step_dependencies d JOIN reasoning_steps s ON s.id = d.step_id
       WHERE s.reasoning_path_id = p_path
      UNION ALL
      SELECT w.origin, d.prerequisite_step_id, w.depth + 1
        FROM walk w JOIN step_dependencies d ON d.step_id = w.cur
       WHERE w.depth < 1000
    )
    SELECT 1 FROM walk WHERE origin = cur
  ) THEN
    RAISE EXCEPTION 'path % has a dependency cycle', p_path USING ERRCODE = '23514';
  END IF;

  SELECT count(*) INTO v_bad
    FROM reasoning_steps s
   WHERE s.reasoning_path_id = p_path
     AND NOT EXISTS (SELECT 1 FROM step_knowledge_links k WHERE k.step_id = s.id AND k.relation = 'tested');
  IF v_bad > 0 THEN
    RAISE EXCEPTION '% step(s) in path % test no knowledge node', v_bad, p_path USING ERRCODE = '23514';
  END IF;
END $$;

CREATE FUNCTION learning_guard_path_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status = 'published' THEN
    IF NEW.status NOT IN ('published','retired')
       OR NEW.revision_part_id IS DISTINCT FROM OLD.revision_part_id
       OR NEW.approach IS DISTINCT FROM OLD.approach
       OR NEW.version_no IS DISTINCT FROM OLD.version_no
       OR NEW.content_hash IS DISTINCT FROM OLD.content_hash THEN
      RAISE EXCEPTION 'published reasoning path % is immutable (only retirement is allowed)', OLD.id
        USING ERRCODE = '55000';
    END IF;
  ELSIF NEW.status = 'published' THEN
    PERFORM learning_assert_path_publishable(NEW.id);
    NEW.published_at := coalesce(NEW.published_at, now());
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_reasoning_paths_guard
  BEFORE UPDATE ON reasoning_paths
  FOR EACH ROW EXECUTE FUNCTION learning_guard_path_update();

-- Content under a published path cannot be inserted, changed or deleted.
CREATE FUNCTION learning_guard_published_content() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_row jsonb;
  v_step uuid;
  v_path uuid;
  v_status text;
BEGIN
  v_row := to_jsonb(CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END);
  IF TG_TABLE_NAME = 'reasoning_steps' THEN
    v_path := (v_row ->> 'reasoning_path_id')::uuid;
  ELSE
    v_step := (v_row ->> 'step_id')::uuid;
    SELECT reasoning_path_id INTO v_path FROM reasoning_steps WHERE id = v_step;
  END IF;
  SELECT status INTO v_status FROM reasoning_paths WHERE id = v_path;
  IF v_status = 'published' THEN
    RAISE EXCEPTION '% cannot change: reasoning path % is published', TG_TABLE_NAME, v_path
      USING ERRCODE = '55000';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER trg_steps_published_guard BEFORE INSERT OR UPDATE OR DELETE ON reasoning_steps
  FOR EACH ROW EXECUTE FUNCTION learning_guard_published_content();
CREATE TRIGGER trg_deps_published_guard BEFORE INSERT OR UPDATE OR DELETE ON step_dependencies
  FOR EACH ROW EXECUTE FUNCTION learning_guard_published_content();
CREATE TRIGGER trg_klinks_published_guard BEFORE INSERT OR UPDATE OR DELETE ON step_knowledge_links
  FOR EACH ROW EXECUTE FUNCTION learning_guard_published_content();
CREATE TRIGGER trg_clinks_published_guard BEFORE INSERT OR UPDATE OR DELETE ON step_criteria_links
  FOR EACH ROW EXECUTE FUNCTION learning_guard_published_content();

-- ===========================================================================
-- D. Tags, mistake codes, decks, sessions.
--    Tags choose WHICH cards to drill; due dates always come from the review state.
-- ===========================================================================
CREATE TABLE tags (
  id uuid PRIMARY KEY,
  slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9_-]*$'),
  label text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('topic','method','geometry_view','difficulty')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE problem_tags (
  problem_id uuid NOT NULL REFERENCES problems(id),
  tag_id uuid NOT NULL REFERENCES tags(id),
  PRIMARY KEY (problem_id, tag_id)
);
CREATE INDEX ix_problem_tags_tag ON problem_tags (tag_id);
CREATE TABLE step_tags (
  step_id uuid NOT NULL REFERENCES reasoning_steps(id),
  tag_id uuid NOT NULL REFERENCES tags(id),
  PRIMARY KEY (step_id, tag_id)
);
CREATE INDEX ix_step_tags_tag ON step_tags (tag_id);

CREATE TABLE mistake_codes (
  id uuid PRIMARY KEY,
  code text NOT NULL UNIQUE,
  label text NOT NULL,
  description text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE mistake_code_knowledge (
  mistake_code_id uuid NOT NULL REFERENCES mistake_codes(id),
  knowledge_node_id uuid NOT NULL REFERENCES knowledge_nodes(id),
  weight numeric(7,5) NOT NULL DEFAULT 1 CHECK (weight > 0 AND weight <= 1),
  PRIMARY KEY (mistake_code_id, knowledge_node_id)
);
CREATE TABLE step_mistake_links (
  step_id uuid NOT NULL REFERENCES reasoning_steps(id),
  mistake_code_id uuid NOT NULL REFERENCES mistake_codes(id),
  role text NOT NULL CHECK (role IN ('distractor','hint')),
  PRIMARY KEY (step_id, mistake_code_id, role)
);

CREATE TABLE decks (
  id uuid PRIMARY KEY,
  owner_id uuid REFERENCES users(id),
  title text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('system','personal','teacher')),
  filter_json jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {tags_all, tags_any, knowledge_node_ids, difficulty, geometry_view}
  new_per_day integer CHECK (new_per_day >= 0),
  reviews_per_day integer CHECK (reviews_per_day >= 0),
  desired_retention real CHECK (desired_retention BETWEEN 0.70 AND 0.99),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((kind = 'system') = (owner_id IS NULL))
);
CREATE TABLE deck_user_settings (
  user_id uuid NOT NULL REFERENCES users(id),
  deck_id uuid NOT NULL REFERENCES decks(id),
  new_per_day integer CHECK (new_per_day >= 0),
  reviews_per_day integer CHECK (reviews_per_day >= 0),
  desired_retention real CHECK (desired_retention BETWEEN 0.70 AND 0.99),
  PRIMARY KEY (user_id, deck_id)
);

CREATE TABLE training_sessions (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  deck_id uuid REFERENCES decks(id),
  mode text NOT NULL CHECK (mode IN ('learn','review','mixed','by_tag')),
  planned_new integer NOT NULL DEFAULT 0 CHECK (planned_new >= 0),
  planned_review integer NOT NULL DEFAULT 0 CHECK (planned_review >= 0),
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  CHECK (ended_at IS NULL OR ended_at >= started_at),
  UNIQUE (id, user_id)
);

-- ===========================================================================
-- E. Attempts, cards and the append-only review log
-- ===========================================================================
CREATE TABLE learning_attempts (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  problem_revision_id uuid NOT NULL REFERENCES problem_revisions(id),
  session_id uuid,
  status text NOT NULL CHECK (status IN ('active','awaiting_feedback','finished','abandoned')),
  sequence_policy text NOT NULL,
  algorithm_version text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  UNIQUE (id, user_id),
  FOREIGN KEY (session_id, user_id) REFERENCES training_sessions (id, user_id)
);
CREATE INDEX ix_learning_attempts_user ON learning_attempts (user_id, started_at DESC);

CREATE TABLE learning_attempt_cards (
  attempt_id uuid NOT NULL REFERENCES learning_attempts(id),
  sequence_no integer NOT NULL CHECK (sequence_no > 0),
  step_id uuid NOT NULL REFERENCES reasoning_steps(id),
  allocated_max_points numeric(8,2) NOT NULL CHECK (allocated_max_points > 0),
  PRIMARY KEY (attempt_id, sequence_no),
  UNIQUE (attempt_id, step_id),
  UNIQUE (attempt_id, sequence_no, step_id)        -- target of the composite FK from review events
);

-- Two-phase self-assessment: the learner commits a confidence, the reference is revealed,
-- then the learner compares. self_score is derived from both (docs 4.1), never from the click alone.
-- Append-only: a correction is a NEW row whose supersedes_event_id points at the row it replaces.
CREATE TABLE step_review_events (
  id uuid PRIMARY KEY,
  attempt_id uuid NOT NULL,
  user_id uuid NOT NULL,
  step_id uuid NOT NULL,
  sequence_no integer NOT NULL CHECK (sequence_no > 0),
  commit_rating text NOT NULL CHECK (commit_rating IN ('know','fuzzy','unsure')),
  post_check text CHECK (post_check IN ('match','partial','mismatch')),
  self_score numeric(8,2) NOT NULL CHECK (self_score >= 0),
  max_points numeric(8,2) NOT NULL CHECK (max_points > 0),
  fsrs_grade text NOT NULL CHECK (fsrs_grade IN ('again','hard','good','easy')),
  revealed_before_rating boolean NOT NULL DEFAULT false,
  hint_count integer NOT NULL DEFAULT 0 CHECK (hint_count >= 0),
  content_snapshot_hash text NOT NULL,
  scheduler_version text NOT NULL,
  client_event_id uuid NOT NULL,
  supersedes_event_id uuid,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  CHECK (self_score <= max_points),
  CHECK ((commit_rating = 'unsure') = (post_check IS NULL)),
  UNIQUE (id, attempt_id, sequence_no),
  UNIQUE (attempt_id, client_event_id),
  FOREIGN KEY (attempt_id, user_id) REFERENCES learning_attempts (id, user_id),
  FOREIGN KEY (attempt_id, sequence_no, step_id)
    REFERENCES learning_attempt_cards (attempt_id, sequence_no, step_id),
  FOREIGN KEY (supersedes_event_id, attempt_id, sequence_no)
    REFERENCES step_review_events (id, attempt_id, sequence_no)
);
-- one original event per card; each event can be corrected at most once (linear chain)
CREATE UNIQUE INDEX ux_review_original_per_card
  ON step_review_events (attempt_id, sequence_no) WHERE supersedes_event_id IS NULL;
CREATE UNIQUE INDEX ux_review_single_correction
  ON step_review_events (supersedes_event_id) WHERE supersedes_event_id IS NOT NULL;
CREATE INDEX ix_reviews_user ON step_review_events (user_id, occurred_at DESC);

CREATE VIEW effective_step_review_events AS
  SELECT e.* FROM step_review_events e
   WHERE NOT EXISTS (SELECT 1 FROM step_review_events c WHERE c.supersedes_event_id = e.id);

CREATE FUNCTION learning_forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END $$;
CREATE TRIGGER trg_review_events_append_only
  BEFORE UPDATE OR DELETE ON step_review_events
  FOR EACH ROW EXECUTE FUNCTION learning_forbid_mutation();

CREATE TABLE knowledge_self_assessments (
  id uuid PRIMARY KEY,
  attempt_id uuid NOT NULL,
  user_id uuid NOT NULL,
  knowledge_node_id uuid NOT NULL REFERENCES knowledge_nodes(id),
  level smallint NOT NULL CHECK (level BETWEEN 1 AND 4),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (attempt_id, knowledge_node_id),
  FOREIGN KEY (attempt_id, user_id) REFERENCES learning_attempts (id, user_id)
);

-- ===========================================================================
-- F. Scheduling state (rebuildable by replaying effective review events)
-- ===========================================================================
CREATE TABLE step_review_state (
  user_id uuid NOT NULL REFERENCES users(id),
  step_id uuid NOT NULL REFERENCES reasoning_steps(id),
  scheduler_version text NOT NULL,
  state text NOT NULL DEFAULT 'new' CHECK (state IN ('new','learning','review','relearning')),
  due_at timestamptz NOT NULL,
  stability real CHECK (stability IS NULL OR stability >= 0),
  difficulty real CHECK (difficulty IS NULL OR difficulty > 0),
  reps integer NOT NULL DEFAULT 0 CHECK (reps >= 0),
  lapses integer NOT NULL DEFAULT 0 CHECK (lapses >= 0),
  last_grade text CHECK (last_grade IS NULL OR last_grade IN ('again','hard','good','easy')),
  last_reviewed_at timestamptz,
  last_event_id uuid REFERENCES step_review_events(id),
  suspended_at timestamptz,
  buried_until timestamptz,
  PRIMARY KEY (user_id, step_id, scheduler_version)
);
CREATE INDEX ix_review_due ON step_review_state (user_id, due_at) WHERE suspended_at IS NULL;

-- ===========================================================================
-- G. Evidence, snapshots, XP, recommendations
-- ===========================================================================
CREATE TABLE knowledge_evidence (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  knowledge_node_id uuid NOT NULL REFERENCES knowledge_nodes(id),
  evidence_kind text NOT NULL
    CHECK (evidence_kind IN ('self_rating','self_assessment','probe','verified_submission','teacher_assessment')),
  source_event_id uuid,                                  -- polymorphic by evidence_kind
  source_step_id uuid REFERENCES reasoning_steps(id),
  observed_result real NOT NULL CHECK (observed_result >= 0 AND observed_result <= 1),
  evidence_weight real NOT NULL CHECK (evidence_weight > 0),
  reliability real NOT NULL DEFAULT 1 CHECK (reliability >= 0 AND reliability <= 1),
  model_version text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (evidence_kind, source_event_id, knowledge_node_id)   -- derivation is idempotent
);
CREATE INDEX ix_knowledge_evidence_user
  ON knowledge_evidence (user_id, knowledge_node_id, occurred_at DESC);
CREATE TRIGGER trg_knowledge_evidence_append_only
  BEFORE UPDATE OR DELETE ON knowledge_evidence
  FOR EACH ROW EXECUTE FUNCTION learning_forbid_mutation();

-- Two numbers per node: recall retention (FSRS retrievability aggregate) and verified accuracy.
CREATE TABLE knowledge_state_snapshots (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  knowledge_node_id uuid NOT NULL REFERENCES knowledge_nodes(id),
  model_version text NOT NULL,
  metric text NOT NULL CHECK (metric IN ('recall_retention','verified_accuracy')),
  estimate real CHECK (estimate BETWEEN 0 AND 1),
  uncertainty real,
  evidence_count integer NOT NULL CHECK (evidence_count >= 0),
  input_hash text NOT NULL,
  computed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, knowledge_node_id, model_version, metric, computed_at)
);
CREATE INDEX ix_knowledge_snapshots_latest
  ON knowledge_state_snapshots (user_id, knowledge_node_id, model_version, metric, computed_at DESC);

-- XP is independent of the rating chosen. local_day is the learner's own calendar day
-- (computed from learning_user_prefs.timezone and day_start_hour by the application).
CREATE TABLE learning_xp_awards (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  step_id uuid NOT NULL REFERENCES reasoning_steps(id),
  review_event_id uuid NOT NULL REFERENCES step_review_events(id),
  reward_type text NOT NULL,
  points integer NOT NULL CHECK (points >= 0),
  local_day date NOT NULL,
  awarded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (review_event_id, reward_type),
  UNIQUE (user_id, step_id, local_day, reward_type)
);
CREATE TRIGGER trg_xp_awards_append_only
  BEFORE UPDATE OR DELETE ON learning_xp_awards
  FOR EACH ROW EXECUTE FUNCTION learning_forbid_mutation();

CREATE TABLE recommendation_runs (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  input_snapshot_hash text NOT NULL,
  algorithm_version text NOT NULL,
  output_json jsonb NOT NULL,
  explanation text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
