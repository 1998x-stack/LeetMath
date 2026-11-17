-- LeetMath physical schema (postgresql), generated from leetmath/models.py

CREATE TABLE assets (
	id VARCHAR(36) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	object_key VARCHAR(512) NOT NULL, 
	media_type VARCHAR(64) NOT NULL, 
	size_bytes INTEGER NOT NULL, 
	license_ref VARCHAR(128), 
	scan_status VARCHAR(16) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (sha256), 
	UNIQUE (object_key)
);

CREATE TABLE curriculum_systems (
	id VARCHAR(36) NOT NULL, 
	code VARCHAR(64) NOT NULL, 
	region VARCHAR(32) NOT NULL, 
	grade_band VARCHAR(32) NOT NULL, 
	label VARCHAR(128) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);

CREATE TABLE idempotency_records (
	scope VARCHAR(160) NOT NULL, 
	key VARCHAR(128) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	status_code INTEGER NOT NULL, 
	response JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (scope, key)
);

CREATE TABLE outbox_events (
	id VARCHAR(36) NOT NULL, 
	topic VARCHAR(64) NOT NULL, 
	payload JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE TABLE sources (
	id VARCHAR(36) NOT NULL, 
	code VARCHAR(128) NOT NULL, 
	name VARCHAR(256) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	homepage VARCHAR(512), 
	owner VARCHAR(256), 
	status VARCHAR(16) NOT NULL, 
	default_visibility VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);

CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	username VARCHAR(64) NOT NULL, 
	display_name VARCHAR(128) NOT NULL, 
	roles VARCHAR(256) NOT NULL, 
	password_hash VARCHAR(256) NOT NULL, 
	privacy_flags JSON NOT NULL, 
	timezone VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (username)
);

CREATE TABLE audit_events (
	id VARCHAR(36) NOT NULL, 
	actor_id VARCHAR(36), 
	action VARCHAR(64) NOT NULL, 
	entity_type VARCHAR(48) NOT NULL, 
	entity_id VARCHAR(64) NOT NULL, 
	before_hash VARCHAR(64), 
	after_hash VARCHAR(64), 
	meta JSON NOT NULL, 
	request_id VARCHAR(64), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
);

CREATE INDEX ix_audit_entity ON audit_events (entity_type, entity_id, created_at);
CREATE TABLE auth_sessions (
	token_hash VARCHAR(64) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked BOOLEAN NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id);
CREATE TABLE collections (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36), 
	slug VARCHAR(128) NOT NULL, 
	title VARCHAR(256) NOT NULL, 
	description TEXT NOT NULL, 
	kind VARCHAR(24) NOT NULL, 
	visibility VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	UNIQUE (slug)
);

CREATE TABLE curriculum_releases (
	id VARCHAR(36) NOT NULL, 
	system_id VARCHAR(36) NOT NULL, 
	release_code VARCHAR(64) NOT NULL, 
	label VARCHAR(128) NOT NULL, 
	source_ref VARCHAR(256), 
	PRIMARY KEY (id), 
	UNIQUE (system_id, release_code), 
	FOREIGN KEY(system_id) REFERENCES curriculum_systems (id)
);

CREATE TABLE import_batches (
	id VARCHAR(36) NOT NULL, 
	source_id VARCHAR(36) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	manifest JSON NOT NULL, 
	manifest_hash VARCHAR(64) NOT NULL, 
	importer_version VARCHAR(32) NOT NULL, 
	dry_run BOOLEAN NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	counts JSON NOT NULL, 
	initiated_by VARCHAR(36) NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id), 
	UNIQUE (idempotency_key), 
	FOREIGN KEY(initiated_by) REFERENCES users (id)
);

CREATE TABLE problems (
	id VARCHAR(36) NOT NULL, 
	display_id VARCHAR(32) NOT NULL, 
	slug VARCHAR(160) NOT NULL, 
	grade_band VARCHAR(32) NOT NULL, 
	subject VARCHAR(32) NOT NULL, 
	visibility VARCHAR(16) NOT NULL, 
	current_public_revision_id VARCHAR(36), 
	takedown_hold BOOLEAN NOT NULL, 
	takedown_reason TEXT, 
	created_by VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (display_id), 
	UNIQUE (slug), 
	FOREIGN KEY(created_by) REFERENCES users (id)
);

CREATE TABLE rights_grants (
	id VARCHAR(36) NOT NULL, 
	code VARCHAR(128) NOT NULL, 
	source_id VARCHAR(36) NOT NULL, 
	grant_type VARCHAR(32) NOT NULL, 
	scope VARCHAR(256) NOT NULL, 
	territory VARCHAR(64) NOT NULL, 
	permitted_actions JSON NOT NULL, 
	allows_display BOOLEAN NOT NULL, 
	attribution_text TEXT, 
	valid_from TIMESTAMP WITH TIME ZONE, 
	valid_to TIMESTAMP WITH TIME ZONE, 
	evidence_ref VARCHAR(512), 
	status VARCHAR(16) NOT NULL, 
	reviewed_by VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code), 
	FOREIGN KEY(source_id) REFERENCES sources (id), 
	FOREIGN KEY(reviewed_by) REFERENCES users (id)
);

CREATE INDEX ix_rights_grants_source_id ON rights_grants (source_id);
CREATE TABLE bookmarks (
	user_id VARCHAR(36) NOT NULL, 
	problem_id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id, problem_id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(problem_id) REFERENCES problems (id)
);

CREATE TABLE collection_items (
	collection_id VARCHAR(36) NOT NULL, 
	problem_id VARCHAR(36) NOT NULL, 
	ordinal INTEGER NOT NULL, 
	PRIMARY KEY (collection_id, problem_id), 
	UNIQUE (collection_id, ordinal), 
	FOREIGN KEY(collection_id) REFERENCES collections (id), 
	FOREIGN KEY(problem_id) REFERENCES problems (id)
);

CREATE TABLE import_rows (
	id VARCHAR(36) NOT NULL, 
	batch_id VARCHAR(36) NOT NULL, 
	file_path VARCHAR(512) NOT NULL, 
	row_no INTEGER NOT NULL, 
	source_record_key VARCHAR(256), 
	raw_sha256 VARCHAR(64) NOT NULL, 
	raw_object_key VARCHAR(512) NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	stage VARCHAR(24) NOT NULL, 
	error_code VARCHAR(48), 
	error_detail JSON, 
	outcome_entity_type VARCHAR(48), 
	outcome_entity_id VARCHAR(36), 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (batch_id, file_path, row_no), 
	FOREIGN KEY(batch_id) REFERENCES import_batches (id)
);

CREATE INDEX ix_import_rows_batch_state ON import_rows (batch_id, state);
CREATE INDEX ix_import_rows_source_record_key ON import_rows (source_record_key);
CREATE TABLE knowledge_nodes (
	id VARCHAR(36) NOT NULL, 
	release_id VARCHAR(36) NOT NULL, 
	external_code VARCHAR(64) NOT NULL, 
	parent_id VARCHAR(36), 
	title VARCHAR(128) NOT NULL, 
	level INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (release_id, external_code), 
	FOREIGN KEY(release_id) REFERENCES curriculum_releases (id), 
	FOREIGN KEY(parent_id) REFERENCES knowledge_nodes (id)
);

CREATE TABLE logical_parts (
	id VARCHAR(36) NOT NULL, 
	problem_id VARCHAR(36) NOT NULL, 
	stable_label VARCHAR(64), 
	PRIMARY KEY (id), 
	FOREIGN KEY(problem_id) REFERENCES problems (id)
);

CREATE INDEX ix_logical_parts_problem_id ON logical_parts (problem_id);
CREATE TABLE problem_relations (
	id VARCHAR(36) NOT NULL, 
	from_problem_id VARCHAR(36) NOT NULL, 
	to_problem_id VARCHAR(36) NOT NULL, 
	relation_type VARCHAR(32) NOT NULL, 
	decision_by VARCHAR(36) NOT NULL, 
	reason TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (from_problem_id, to_problem_id, relation_type), 
	FOREIGN KEY(from_problem_id) REFERENCES problems (id), 
	FOREIGN KEY(to_problem_id) REFERENCES problems (id), 
	FOREIGN KEY(decision_by) REFERENCES users (id)
);

CREATE TABLE problem_revisions (
	id VARCHAR(36) NOT NULL, 
	problem_id VARCHAR(36) NOT NULL, 
	revision_no INTEGER NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	locale VARCHAR(16) NOT NULL, 
	title VARCHAR(256) NOT NULL, 
	shared_statement JSON NOT NULL, 
	content_metadata JSON NOT NULL, 
	platform_difficulty INTEGER, 
	revision_kind VARCHAR(24) NOT NULL, 
	change_note TEXT, 
	content_hash VARCHAR(64), 
	rights_grant_id VARCHAR(36), 
	lock_version INTEGER NOT NULL, 
	created_by VARCHAR(36), 
	math_reviewer_id VARCHAR(36), 
	rights_reviewer_id VARCHAR(36), 
	review_note TEXT, 
	published_at TIMESTAMP WITH TIME ZONE, 
	retracted_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (problem_id, revision_no), 
	CONSTRAINT ck_revision_no_pos CHECK (revision_no > 0), 
	CONSTRAINT ck_revision_status CHECK (status IN ('draft','in_math_review','in_rights_review','approved','published','archived','retracted')), 
	FOREIGN KEY(problem_id) REFERENCES problems (id), 
	FOREIGN KEY(rights_grant_id) REFERENCES rights_grants (id), 
	FOREIGN KEY(created_by) REFERENCES users (id), 
	FOREIGN KEY(math_reviewer_id) REFERENCES users (id), 
	FOREIGN KEY(rights_reviewer_id) REFERENCES users (id)
);

CREATE INDEX ix_rev_status_pub ON problem_revisions (status, published_at);
CREATE TABLE problem_slug_aliases (
	slug VARCHAR(160) NOT NULL, 
	problem_id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (slug), 
	FOREIGN KEY(problem_id) REFERENCES problems (id)
);

CREATE TABLE source_records (
	id VARCHAR(36) NOT NULL, 
	source_id VARCHAR(36) NOT NULL, 
	external_id VARCHAR(256) NOT NULL, 
	latest_source_revision VARCHAR(128), 
	canonical_problem_id VARCHAR(36), 
	relation_to_problem VARCHAR(32), 
	tombstoned BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (source_id, external_id), 
	FOREIGN KEY(source_id) REFERENCES sources (id), 
	FOREIGN KEY(canonical_problem_id) REFERENCES problems (id)
);

CREATE TABLE attempts (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	problem_revision_id VARCHAR(36) NOT NULL, 
	mode VARCHAR(16) NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(problem_revision_id) REFERENCES problem_revisions (id)
);

CREATE INDEX ix_attempts_user_id ON attempts (user_id);
CREATE TABLE content_workflow_events (
	id VARCHAR(36) NOT NULL, 
	revision_id VARCHAR(36) NOT NULL, 
	from_status VARCHAR(24) NOT NULL, 
	to_status VARCHAR(24) NOT NULL, 
	actor_id VARCHAR(36) NOT NULL, 
	reason TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(revision_id) REFERENCES problem_revisions (id), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
);

CREATE INDEX ix_content_workflow_events_revision_id ON content_workflow_events (revision_id);
CREATE TABLE knowledge_edges (
	from_node_id VARCHAR(36) NOT NULL, 
	to_node_id VARCHAR(36) NOT NULL, 
	relation_type VARCHAR(24) NOT NULL, 
	PRIMARY KEY (from_node_id, to_node_id, relation_type), 
	FOREIGN KEY(from_node_id) REFERENCES knowledge_nodes (id), 
	FOREIGN KEY(to_node_id) REFERENCES knowledge_nodes (id)
);

CREATE TABLE learning_attempts (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	problem_revision_id VARCHAR(36), 
	mode VARCHAR(16) NOT NULL, 
	card_ids JSON NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(problem_revision_id) REFERENCES problem_revisions (id)
);

CREATE INDEX ix_learning_attempts_user_id ON learning_attempts (user_id);
CREATE TABLE revision_assets (
	revision_id VARCHAR(36) NOT NULL, 
	asset_id VARCHAR(36) NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	alt_text TEXT, 
	PRIMARY KEY (revision_id, asset_id, role), 
	FOREIGN KEY(revision_id) REFERENCES problem_revisions (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id)
);

CREATE TABLE revision_knowledge (
	revision_id VARCHAR(36) NOT NULL, 
	knowledge_node_id VARCHAR(36) NOT NULL, 
	relation_type VARCHAR(24) NOT NULL, 
	weight NUMERIC(6, 4) NOT NULL, 
	PRIMARY KEY (revision_id, knowledge_node_id, relation_type), 
	FOREIGN KEY(revision_id) REFERENCES problem_revisions (id), 
	FOREIGN KEY(knowledge_node_id) REFERENCES knowledge_nodes (id)
);

CREATE TABLE revision_parts (
	id VARCHAR(36) NOT NULL, 
	problem_revision_id VARCHAR(36) NOT NULL, 
	logical_part_id VARCHAR(36) NOT NULL, 
	part_key VARCHAR(16) NOT NULL, 
	display_order INTEGER NOT NULL, 
	prompt JSON NOT NULL, 
	response_type VARCHAR(32) NOT NULL, 
	max_score NUMERIC(8, 2) NOT NULL, 
	options JSON, 
	knowledge_codes JSON NOT NULL, 
	grading_suspended BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (problem_revision_id, logical_part_id), 
	UNIQUE (problem_revision_id, display_order), 
	CONSTRAINT ck_part_order_pos CHECK (display_order > 0), 
	CONSTRAINT ck_part_max_score_pos CHECK (max_score > 0), 
	FOREIGN KEY(problem_revision_id) REFERENCES problem_revisions (id), 
	FOREIGN KEY(logical_part_id) REFERENCES logical_parts (id)
);

CREATE TABLE search_documents (
	problem_id VARCHAR(36) NOT NULL, 
	revision_id VARCHAR(36) NOT NULL, 
	display_id VARCHAR(32) NOT NULL, 
	slug VARCHAR(160) NOT NULL, 
	title VARCHAR(256) NOT NULL, 
	body_text TEXT NOT NULL, 
	knowledge_text TEXT NOT NULL, 
	knowledge_ids TEXT NOT NULL, 
	grade_band VARCHAR(32) NOT NULL, 
	region_hints VARCHAR(256) NOT NULL, 
	response_types VARCHAR(256) NOT NULL, 
	difficulty INTEGER NOT NULL, 
	part_count INTEGER NOT NULL, 
	has_solution BOOLEAN NOT NULL, 
	source_kind VARCHAR(32) NOT NULL, 
	rights_grant_id VARCHAR(36), 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (problem_id), 
	FOREIGN KEY(problem_id) REFERENCES problems (id), 
	FOREIGN KEY(revision_id) REFERENCES problem_revisions (id), 
	FOREIGN KEY(rights_grant_id) REFERENCES rights_grants (id)
);

CREATE INDEX ix_search_diff ON search_documents (difficulty);
CREATE INDEX ix_search_display ON search_documents (display_id);
CREATE TABLE source_record_revisions (
	id VARCHAR(36) NOT NULL, 
	source_record_id VARCHAR(36) NOT NULL, 
	external_revision VARCHAR(128) NOT NULL, 
	raw_object_key VARCHAR(512) NOT NULL, 
	raw_sha256 VARCHAR(64) NOT NULL, 
	adapter_version VARCHAR(64) NOT NULL, 
	normalizer_version VARCHAR(64) NOT NULL, 
	normalized_payload JSON, 
	content_hash VARCHAR(64), 
	batch_id VARCHAR(36), 
	problem_revision_id VARCHAR(36), 
	imported_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (source_record_id, external_revision), 
	FOREIGN KEY(source_record_id) REFERENCES source_records (id), 
	FOREIGN KEY(batch_id) REFERENCES import_batches (id), 
	FOREIGN KEY(problem_revision_id) REFERENCES problem_revisions (id)
);

CREATE INDEX ix_source_record_revisions_content_hash ON source_record_revisions (content_hash);
CREATE TABLE answer_specs (
	id VARCHAR(36) NOT NULL, 
	revision_part_id VARCHAR(36) NOT NULL, 
	spec_version INTEGER NOT NULL, 
	grading_mode VARCHAR(16) NOT NULL, 
	checker_type VARCHAR(48) NOT NULL, 
	spec JSON NOT NULL, 
	rubric JSON, 
	rubric_sum NUMERIC(8, 2), 
	PRIMARY KEY (id), 
	UNIQUE (revision_part_id, spec_version), 
	FOREIGN KEY(revision_part_id) REFERENCES revision_parts (id)
);

CREATE TABLE duplicate_candidates (
	id VARCHAR(36) NOT NULL, 
	left_source_record_revision_id VARCHAR(36) NOT NULL, 
	right_problem_id VARCHAR(36) NOT NULL, 
	level VARCHAR(8) NOT NULL, 
	score NUMERIC(6, 4) NOT NULL, 
	signals JSON NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	decision VARCHAR(32), 
	decision_reason TEXT, 
	reviewer_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(left_source_record_revision_id) REFERENCES source_record_revisions (id), 
	FOREIGN KEY(right_problem_id) REFERENCES problems (id), 
	FOREIGN KEY(reviewer_id) REFERENCES users (id)
);

CREATE INDEX ix_dup_status_score ON duplicate_candidates (status, score);
CREATE INDEX ix_duplicate_candidates_left_source_record_revision_id ON duplicate_candidates (left_source_record_revision_id);
CREATE TABLE knowledge_self_assessments (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	attempt_id VARCHAR(36) NOT NULL, 
	knowledge_code VARCHAR(64) NOT NULL, 
	level INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (attempt_id, knowledge_code), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(attempt_id) REFERENCES learning_attempts (id)
);

CREATE INDEX ix_knowledge_self_assessments_user_id ON knowledge_self_assessments (user_id);
CREATE TABLE reasoning_steps (
	id VARCHAR(36) NOT NULL, 
	revision_part_id VARCHAR(36) NOT NULL, 
	semantic_key VARCHAR(96) NOT NULL, 
	step_order INTEGER NOT NULL, 
	recall_cue TEXT NOT NULL, 
	reference_latex TEXT NOT NULL, 
	explanation TEXT NOT NULL, 
	max_points NUMERIC(8, 2) NOT NULL, 
	criticality VARCHAR(16) NOT NULL, 
	knowledge_codes JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (revision_part_id, step_order), 
	UNIQUE (revision_part_id, semantic_key), 
	FOREIGN KEY(revision_part_id) REFERENCES revision_parts (id)
);

CREATE TABLE solutions (
	id VARCHAR(36) NOT NULL, 
	revision_part_id VARCHAR(36) NOT NULL, 
	solution_type VARCHAR(24) NOT NULL, 
	content JSON NOT NULL, 
	validation_state VARCHAR(32) NOT NULL, 
	reviewer_id VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(revision_part_id) REFERENCES revision_parts (id), 
	FOREIGN KEY(reviewer_id) REFERENCES users (id)
);

CREATE TABLE learning_xp_awards (
	user_id VARCHAR(36) NOT NULL, 
	step_id VARCHAR(36) NOT NULL, 
	local_day VARCHAR(10) NOT NULL, 
	amount INTEGER NOT NULL, 
	PRIMARY KEY (user_id, step_id, local_day), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(step_id) REFERENCES reasoning_steps (id)
);

CREATE TABLE step_review_events (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	attempt_id VARCHAR(36) NOT NULL, 
	step_id VARCHAR(36) NOT NULL, 
	rating VARCHAR(8) NOT NULL, 
	revealed_before_rating BOOLEAN NOT NULL, 
	max_points NUMERIC(8, 2) NOT NULL, 
	self_score NUMERIC(8, 2) NOT NULL, 
	algorithm_version VARCHAR(24) NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (attempt_id, step_id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(attempt_id) REFERENCES learning_attempts (id), 
	FOREIGN KEY(step_id) REFERENCES reasoning_steps (id)
);

CREATE INDEX ix_step_review_events_user_id ON step_review_events (user_id);
CREATE TABLE step_review_state (
	user_id VARCHAR(36) NOT NULL, 
	step_id VARCHAR(36) NOT NULL, 
	scheduler_version VARCHAR(24) NOT NULL, 
	due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	review_count INTEGER NOT NULL, 
	last_rating VARCHAR(8) NOT NULL, 
	PRIMARY KEY (user_id, step_id, scheduler_version), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(step_id) REFERENCES reasoning_steps (id)
);

CREATE TABLE submissions (
	id VARCHAR(36) NOT NULL, 
	attempt_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	revision_part_id VARCHAR(36) NOT NULL, 
	answer_spec_id VARCHAR(36), 
	response JSON NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (attempt_id, idempotency_key), 
	FOREIGN KEY(attempt_id) REFERENCES attempts (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(revision_part_id) REFERENCES revision_parts (id), 
	FOREIGN KEY(answer_spec_id) REFERENCES answer_specs (id)
);

CREATE INDEX ix_sub_attempt_created ON submissions (attempt_id, created_at);
CREATE INDEX ix_sub_user_created ON submissions (user_id, created_at);
CREATE TABLE evaluations (
	id VARCHAR(36) NOT NULL, 
	submission_id VARCHAR(36) NOT NULL, 
	grader_name VARCHAR(48) NOT NULL, 
	grader_version VARCHAR(24) NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	result_code VARCHAR(48), 
	score NUMERIC(8, 2), 
	max_score NUMERIC(8, 2) NOT NULL, 
	feedback JSON NOT NULL, 
	confidence NUMERIC(4, 3), 
	evaluator_id VARCHAR(36), 
	previous_evaluation_id VARCHAR(36), 
	reason TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(submission_id) REFERENCES submissions (id), 
	FOREIGN KEY(evaluator_id) REFERENCES users (id), 
	FOREIGN KEY(previous_evaluation_id) REFERENCES evaluations (id)
);

CREATE INDEX ix_eval_sub_created ON evaluations (submission_id, created_at);
CREATE TABLE mistake_marks (
	user_id VARCHAR(36) NOT NULL, 
	revision_part_id VARCHAR(36) NOT NULL, 
	origin_submission_id VARCHAR(36), 
	manual BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id, revision_part_id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(revision_part_id) REFERENCES revision_parts (id), 
	FOREIGN KEY(origin_submission_id) REFERENCES submissions (id)
);

CREATE TABLE content_reports (
	id VARCHAR(36) NOT NULL, 
	reporter_id VARCHAR(36) NOT NULL, 
	problem_revision_id VARCHAR(36) NOT NULL, 
	revision_part_id VARCHAR(36), 
	evaluation_id VARCHAR(36), 
	kind VARCHAR(32) NOT NULL, 
	description TEXT NOT NULL, 
	severity VARCHAR(4) NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	public_note TEXT, 
	internal_note TEXT, 
	reviewer_id VARCHAR(36), 
	resolution VARCHAR(64), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(reporter_id) REFERENCES users (id), 
	FOREIGN KEY(problem_revision_id) REFERENCES problem_revisions (id), 
	FOREIGN KEY(revision_part_id) REFERENCES revision_parts (id), 
	FOREIGN KEY(evaluation_id) REFERENCES evaluations (id), 
	FOREIGN KEY(reviewer_id) REFERENCES users (id)
);

CREATE INDEX ix_content_reports_reporter_id ON content_reports (reporter_id);

-- Defence in depth: published revisions are immutable at the database layer too (docs/04 §3).
CREATE OR REPLACE FUNCTION forbid_frozen_revision_edit() RETURNS trigger AS $$
BEGIN
  IF OLD.status IN ('published','archived','retracted') AND (
       NEW.title IS DISTINCT FROM OLD.title OR NEW.shared_statement::text IS DISTINCT FROM OLD.shared_statement::text
       OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR NEW.rights_grant_id IS DISTINCT FROM OLD.rights_grant_id) THEN
    RAISE EXCEPTION 'revision % is %, content is immutable', OLD.id, OLD.status;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_problem_revisions_immutable BEFORE UPDATE ON problem_revisions
  FOR EACH ROW EXECUTE FUNCTION forbid_frozen_revision_edit();
REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC;
