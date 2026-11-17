-- Minimal stand-ins for the canonical tables of docs/04-data-model.md, used ONLY to smoke-test
-- postgres_learning_extension.sql on an empty database. Not the real schema.
CREATE TABLE users (id uuid PRIMARY KEY, auth_subject text NOT NULL UNIQUE, role text NOT NULL DEFAULT 'student');
CREATE TABLE problems (id uuid PRIMARY KEY);
CREATE TABLE problem_revisions (id uuid PRIMARY KEY, problem_id uuid NOT NULL REFERENCES problems(id));
CREATE TABLE revision_parts (
  id uuid PRIMARY KEY,
  problem_revision_id uuid NOT NULL REFERENCES problem_revisions(id),
  max_score numeric(8,2) NOT NULL CHECK (max_score > 0)
);
CREATE TABLE solutions (id uuid PRIMARY KEY);
CREATE TABLE rubrics (id uuid PRIMARY KEY);
CREATE TABLE knowledge_nodes (id uuid PRIMARY KEY);
