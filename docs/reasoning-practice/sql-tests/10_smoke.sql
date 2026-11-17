-- Smoke tests for the v0.3 learning-domain DDL. Every expectation names the SQLSTATE it must raise.
-- Run through run.sh (own database, whole script in one rolled-back transaction).
\set ON_ERROR_STOP on
\set QUIET on
BEGIN;
\i 00_stub_dependencies.sql
\i ../postgres_learning_extension.sql

CREATE FUNCTION t_expect(p_label text, p_sql text, p_state text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE v_state text;
BEGIN
  BEGIN
    EXECUTE p_sql;
    RAISE EXCEPTION 'TEST FAILED [%]: expected SQLSTATE % but the statement succeeded', p_label, p_state
      USING ERRCODE = 'XX999';
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_state = RETURNED_SQLSTATE;
    IF v_state = 'XX999' THEN RAISE; END IF;
    IF v_state <> p_state THEN
      RAISE EXCEPTION 'TEST FAILED [%]: expected % got % (%)', p_label, p_state, v_state, SQLERRM
        USING ERRCODE = 'XX999';
    END IF;
    RAISE NOTICE 'ok   [%] -> %', p_label, v_state;
  END;
END $$;

-- ---- seed -----------------------------------------------------------------
INSERT INTO users (id, auth_subject) VALUES
  ('10000000-0000-0000-0000-00000000000a', 'local:a'),
  ('10000000-0000-0000-0000-00000000000b', 'local:b');
INSERT INTO problems VALUES ('20000000-0000-0000-0000-000000000001');
INSERT INTO problem_revisions VALUES ('21000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001');
INSERT INTO revision_parts VALUES
  ('22000000-0000-0000-0000-000000000001', '21000000-0000-0000-0000-000000000001', 3.00),
  ('22000000-0000-0000-0000-000000000002', '21000000-0000-0000-0000-000000000001', 5.00);
INSERT INTO knowledge_nodes VALUES
  ('30000000-0000-0000-0000-000000000001'), ('30000000-0000-0000-0000-000000000002');

INSERT INTO reasoning_paths (id, revision_part_id, approach, version_no, status, content_hash) VALUES
  ('40000000-0000-0000-0000-000000000001', '22000000-0000-0000-0000-000000000001', 'direct',   1, 'draft', 'h1'),
  ('40000000-0000-0000-0000-000000000002', '22000000-0000-0000-0000-000000000002', 'badsum',   1, 'draft', 'h2'),
  ('40000000-0000-0000-0000-000000000003', '22000000-0000-0000-0000-000000000001', 'cycle',    1, 'draft', 'h3'),
  ('40000000-0000-0000-0000-000000000004', '22000000-0000-0000-0000-000000000001', 'nolink',   1, 'draft', 'h4');
INSERT INTO reasoning_steps (id, reasoning_path_id, semantic_key, step_order, recall_cue, reference_reasoning, max_points, criticality, content_hash) VALUES
  ('50000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001', 'product_rule', 1, '{}', '{}', 1.00, 'supporting', 's1'),
  ('50000000-0000-0000-0000-000000000002', '40000000-0000-0000-0000-000000000001', 'final_form',   2, '{}', '{}', 2.00, 'key',        's2'),
  ('50000000-0000-0000-0000-000000000003', '40000000-0000-0000-0000-000000000002', 'only_step',    1, '{}', '{}', 2.00, 'key',        's3'),
  ('50000000-0000-0000-0000-000000000004', '40000000-0000-0000-0000-000000000003', 'x',            1, '{}', '{}', 1.50, 'key',        's4'),
  ('50000000-0000-0000-0000-000000000005', '40000000-0000-0000-0000-000000000003', 'y',            2, '{}', '{}', 1.50, 'key',        's5'),
  ('50000000-0000-0000-0000-000000000006', '40000000-0000-0000-0000-000000000004', 'z',            1, '{}', '{}', 3.00, 'key',        's6');
INSERT INTO step_knowledge_links VALUES
  ('50000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 'tested', 1),
  ('50000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000001', 'tested', 1),
  ('50000000-0000-0000-0000-000000000003', '30000000-0000-0000-0000-000000000001', 'tested', 1),
  ('50000000-0000-0000-0000-000000000004', '30000000-0000-0000-0000-000000000001', 'tested', 1),
  ('50000000-0000-0000-0000-000000000005', '30000000-0000-0000-0000-000000000001', 'tested', 1);
INSERT INTO step_dependencies VALUES
  ('50000000-0000-0000-0000-000000000002', '50000000-0000-0000-0000-000000000001'),
  ('50000000-0000-0000-0000-000000000004', '50000000-0000-0000-0000-000000000005'),
  ('50000000-0000-0000-0000-000000000005', '50000000-0000-0000-0000-000000000004');

-- ---- publish gate ---------------------------------------------------------
SELECT t_expect('publish rejected: step points 2 <> part max 5',
  $$UPDATE reasoning_paths SET status='published' WHERE id='40000000-0000-0000-0000-000000000002'$$, '23514');
SELECT t_expect('publish rejected: dependency cycle',
  $$UPDATE reasoning_paths SET status='published' WHERE id='40000000-0000-0000-0000-000000000003'$$, '23514');
SELECT t_expect('publish rejected: step tests no knowledge node',
  $$UPDATE reasoning_paths SET status='published' WHERE id='40000000-0000-0000-0000-000000000004'$$, '23514');
UPDATE reasoning_paths SET status='published' WHERE id='40000000-0000-0000-0000-000000000001';
DO $$ BEGIN
  ASSERT (SELECT published_at IS NOT NULL FROM reasoning_paths WHERE id='40000000-0000-0000-0000-000000000001'),
    'published_at should be stamped on publish';
  RAISE NOTICE 'ok   [valid path publishes, published_at stamped]';
END $$;

-- ---- published content is immutable --------------------------------------
SELECT t_expect('published step cannot be edited',
  $$UPDATE reasoning_steps SET max_points=1 WHERE id='50000000-0000-0000-0000-000000000001'$$, '55000');
SELECT t_expect('step cannot be added to a published path',
  $$INSERT INTO reasoning_steps (id, reasoning_path_id, semantic_key, step_order, recall_cue, reference_reasoning, max_points, content_hash)
    VALUES (gen_random_uuid(), '40000000-0000-0000-0000-000000000001', 'extra', 3, '{}', '{}', 1, 'x')$$, '55000');
SELECT t_expect('knowledge link cannot be added under a published path',
  $$INSERT INTO step_knowledge_links VALUES ('50000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000002','related',0.5)$$, '55000');
SELECT t_expect('published path cannot return to draft',
  $$UPDATE reasoning_paths SET status='draft' WHERE id='40000000-0000-0000-0000-000000000001'$$, '55000');

-- ---- attempts, cards, review events --------------------------------------
INSERT INTO training_sessions (id, user_id, mode) VALUES
  ('80000000-0000-0000-0000-00000000000b', '10000000-0000-0000-0000-00000000000b', 'mixed');
SELECT t_expect('attempt cannot join another user''s session',
  $$INSERT INTO learning_attempts (id, user_id, problem_revision_id, session_id, status, sequence_policy, algorithm_version)
    VALUES (gen_random_uuid(), '10000000-0000-0000-0000-00000000000a', '21000000-0000-0000-0000-000000000001',
            '80000000-0000-0000-0000-00000000000b', 'active', 'linear', 'v0')$$, '23503');
INSERT INTO learning_attempts (id, user_id, problem_revision_id, status, sequence_policy, algorithm_version) VALUES
  ('60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-00000000000a', '21000000-0000-0000-0000-000000000001', 'active', 'linear', 'v0');
INSERT INTO learning_attempt_cards VALUES
  ('60000000-0000-0000-0000-000000000001', 1, '50000000-0000-0000-0000-000000000001', 1.00),
  ('60000000-0000-0000-0000-000000000001', 2, '50000000-0000-0000-0000-000000000002', 2.00);

SELECT t_expect('event cannot be written as another user',
  $$INSERT INTO step_review_events (id, attempt_id, user_id, step_id, sequence_no, commit_rating, post_check, self_score, max_points, fsrs_grade, content_snapshot_hash, scheduler_version, client_event_id)
    VALUES (gen_random_uuid(), '60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-00000000000b',
            '50000000-0000-0000-0000-000000000001', 1, 'know', 'match', 1, 1, 'good', 'h', 'v0', gen_random_uuid())$$, '23503');
SELECT t_expect('event cannot reference a step that is not a card of the attempt',
  $$INSERT INTO step_review_events (id, attempt_id, user_id, step_id, sequence_no, commit_rating, post_check, self_score, max_points, fsrs_grade, content_snapshot_hash, scheduler_version, client_event_id)
    VALUES (gen_random_uuid(), '60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-00000000000a',
            '50000000-0000-0000-0000-000000000003', 1, 'know', 'match', 1, 1, 'good', 'h', 'v0', gen_random_uuid())$$, '23503');
SELECT t_expect('unsure must not carry a post-check',
  $$INSERT INTO step_review_events (id, attempt_id, user_id, step_id, sequence_no, commit_rating, post_check, self_score, max_points, fsrs_grade, content_snapshot_hash, scheduler_version, client_event_id)
    VALUES (gen_random_uuid(), '60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-00000000000a',
            '50000000-0000-0000-0000-000000000001', 1, 'unsure', 'match', 0, 1, 'again', 'h', 'v0', gen_random_uuid())$$, '23514');
SELECT t_expect('know requires a post-check',
  $$INSERT INTO step_review_events (id, attempt_id, user_id, step_id, sequence_no, commit_rating, post_check, self_score, max_points, fsrs_grade, content_snapshot_hash, scheduler_version, client_event_id)
    VALUES (gen_random_uuid(), '60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-00000000000a',
            '50000000-0000-0000-0000-000000000001', 1, 'know', NULL, 1, 1, 'good', 'h', 'v0', gen_random_uuid())$$, '23514');
SELECT t_expect('self_score cannot exceed max_points',
  $$INSERT INTO step_review_events (id, attempt_id, user_id, step_id, sequence_no, commit_rating, post_check, self_score, max_points, fsrs_grade, content_snapshot_hash, scheduler_version, client_event_id)
    VALUES (gen_random_uuid(), '60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-00000000000a',
            '50000000-0000-0000-0000-000000000001', 1, 'know', 'match', 1.5, 1, 'good', 'h', 'v0', gen_random_uuid())$$, '23514');

INSERT INTO step_review_events (id, attempt_id, user_id, step_id, sequence_no, commit_rating, post_check, self_score, max_points, fsrs_grade, content_snapshot_hash, scheduler_version, client_event_id) VALUES
  ('70000000-0000-0000-0000-000000000001', '60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-00000000000a',
   '50000000-0000-0000-0000-000000000001', 1, 'know', 'match', 1.00, 1.00, 'good', 'h', 'v0', '90000000-0000-0000-0000-000000000001');

SELECT t_expect('a second ORIGINAL event for the same card is rejected',
  $$INSERT INTO step_review_events (id, attempt_id, user_id, step_id, sequence_no, commit_rating, post_check, self_score, max_points, fsrs_grade, content_snapshot_hash, scheduler_version, client_event_id)
    VALUES (gen_random_uuid(), '60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-00000000000a',
            '50000000-0000-0000-0000-000000000001', 1, 'fuzzy', 'partial', 0.45, 1, 'hard', 'h', 'v0', gen_random_uuid())$$, '23505');
SELECT t_expect('replayed client_event_id is rejected (idempotency)',
  $$INSERT INTO step_review_events (id, attempt_id, user_id, step_id, sequence_no, commit_rating, post_check, self_score, max_points, fsrs_grade, content_snapshot_hash, scheduler_version, client_event_id)
    VALUES (gen_random_uuid(), '60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-00000000000a',
            '50000000-0000-0000-0000-000000000002', 2, 'know', 'match', 2, 2, 'good', 'h', 'v0', '90000000-0000-0000-0000-000000000001')$$, '23505');
SELECT t_expect('a correction must target the same card (sequence_no)',
  $$INSERT INTO step_review_events (id, attempt_id, user_id, step_id, sequence_no, commit_rating, post_check, self_score, max_points, fsrs_grade, content_snapshot_hash, scheduler_version, client_event_id, supersedes_event_id)
    VALUES (gen_random_uuid(), '60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-00000000000a',
            '50000000-0000-0000-0000-000000000002', 2, 'fuzzy', 'partial', 0.9, 2, 'hard', 'h', 'v0', gen_random_uuid(),
            '70000000-0000-0000-0000-000000000001')$$, '23503');

-- the case v0.2 could not express: a correction event
INSERT INTO step_review_events (id, attempt_id, user_id, step_id, sequence_no, commit_rating, post_check, self_score, max_points, fsrs_grade, content_snapshot_hash, scheduler_version, client_event_id, supersedes_event_id) VALUES
  ('70000000-0000-0000-0000-000000000002', '60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-00000000000a',
   '50000000-0000-0000-0000-000000000001', 1, 'fuzzy', 'partial', 0.45, 1.00, 'hard', 'h', 'v0', '90000000-0000-0000-0000-000000000002',
   '70000000-0000-0000-0000-000000000001');
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM step_review_events WHERE attempt_id='60000000-0000-0000-0000-000000000001') = 2,
    'history keeps both the original and the correction';
  ASSERT (SELECT id FROM effective_step_review_events WHERE attempt_id='60000000-0000-0000-0000-000000000001' AND sequence_no=1)
         = '70000000-0000-0000-0000-000000000002', 'effective view must return the correction';
  RAISE NOTICE 'ok   [correction appended; effective view returns the head of the chain]';
END $$;
SELECT t_expect('an event can be corrected only once (linear chain)',
  $$INSERT INTO step_review_events (id, attempt_id, user_id, step_id, sequence_no, commit_rating, post_check, self_score, max_points, fsrs_grade, content_snapshot_hash, scheduler_version, client_event_id, supersedes_event_id)
    VALUES (gen_random_uuid(), '60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-00000000000a',
            '50000000-0000-0000-0000-000000000001', 1, 'know', 'match', 1, 1, 'good', 'h', 'v0', gen_random_uuid(),
            '70000000-0000-0000-0000-000000000001')$$, '23505');
SELECT t_expect('review events are append-only: UPDATE',
  $$UPDATE step_review_events SET self_score = 0 WHERE id='70000000-0000-0000-0000-000000000001'$$, '55000');
SELECT t_expect('review events are append-only: DELETE',
  $$DELETE FROM step_review_events WHERE id='70000000-0000-0000-0000-000000000001'$$, '55000');

-- ---- XP: a correction cannot earn the same XP twice on one local day ------
INSERT INTO learning_xp_awards (id, user_id, step_id, review_event_id, reward_type, points, local_day) VALUES
  (gen_random_uuid(), '10000000-0000-0000-0000-00000000000a', '50000000-0000-0000-0000-000000000001',
   '70000000-0000-0000-0000-000000000002', 'step_first_review', 6, '2026-11-17');
SELECT t_expect('XP: same user, step, local day, reward type only once',
  $$INSERT INTO learning_xp_awards (id, user_id, step_id, review_event_id, reward_type, points, local_day)
    VALUES (gen_random_uuid(), '10000000-0000-0000-0000-00000000000a', '50000000-0000-0000-0000-000000000001',
            '70000000-0000-0000-0000-000000000001', 'step_first_review', 6, '2026-11-17')$$, '23505');
SELECT t_expect('XP awards are append-only',
  $$UPDATE learning_xp_awards SET points = 99$$, '55000');

-- ---- evidence -------------------------------------------------------------
INSERT INTO knowledge_evidence (id, user_id, knowledge_node_id, evidence_kind, source_event_id, source_step_id, observed_result, evidence_weight, model_version) VALUES
  (gen_random_uuid(), '10000000-0000-0000-0000-00000000000a', '30000000-0000-0000-0000-000000000001', 'self_rating',
   '70000000-0000-0000-0000-000000000002', '50000000-0000-0000-0000-000000000001', 0.45, 1, 'v0');
SELECT t_expect('evidence derivation is idempotent',
  $$INSERT INTO knowledge_evidence (id, user_id, knowledge_node_id, evidence_kind, source_event_id, observed_result, evidence_weight, model_version)
    VALUES (gen_random_uuid(), '10000000-0000-0000-0000-00000000000a', '30000000-0000-0000-0000-000000000001', 'self_rating',
            '70000000-0000-0000-0000-000000000002', 0.45, 1, 'v0')$$, '23505');
SELECT t_expect('evidence is append-only',
  $$UPDATE knowledge_evidence SET evidence_weight = 5$$, '55000');

-- ---- scheduling state -----------------------------------------------------
INSERT INTO step_review_state (user_id, step_id, scheduler_version, state, due_at, stability, difficulty, reps, last_grade, last_event_id) VALUES
  ('10000000-0000-0000-0000-00000000000a', '50000000-0000-0000-0000-000000000001', 'fsrs-test', 'review', now() + interval '3 days', 2.4, 5.1, 1, 'hard',
   '70000000-0000-0000-0000-000000000002');
SELECT t_expect('invalid FSRS grade is rejected',
  $$UPDATE step_review_state SET last_grade = 'great'$$, '23514');

-- ---- tags, decks, auth ----------------------------------------------------
SELECT t_expect('tag slug must be lowercase ascii',
  $$INSERT INTO tags (id, slug, label, kind) VALUES (gen_random_uuid(), 'Bad Slug', 'x', 'topic')$$, '23514');
INSERT INTO tags (id, slug, label, kind) VALUES (gen_random_uuid(), 'ellipse-chord', '椭圆弦长', 'topic');
SELECT t_expect('system deck must not have an owner',
  $$INSERT INTO decks (id, owner_id, title, kind) VALUES (gen_random_uuid(), '10000000-0000-0000-0000-00000000000a', 't', 'system')$$, '23514');
SELECT t_expect('personal deck must have an owner',
  $$INSERT INTO decks (id, owner_id, title, kind) VALUES (gen_random_uuid(), NULL, 't', 'personal')$$, '23514');
INSERT INTO decks (id, owner_id, title, kind, filter_json) VALUES
  (gen_random_uuid(), NULL, '导数 · 全部', 'system', '{"tags_any":["derivative"]}');
SELECT t_expect('usernames must be lowercase',
  $$INSERT INTO local_credentials (user_id, username, password_hash) VALUES ('10000000-0000-0000-0000-00000000000a', 'Alice', 'x')$$, '23514');
SELECT t_expect('session must expire after it was created',
  $$INSERT INTO auth_sessions (id, user_id, token_hash, csrf_hash, created_at, expires_at)
    VALUES (gen_random_uuid(), '10000000-0000-0000-0000-00000000000a', '\x01', '\x02', now(), now() - interval '1 minute')$$, '23514');

DO $$ BEGIN RAISE NOTICE 'ALL SMOKE TESTS PASSED'; END $$;
ROLLBACK;
