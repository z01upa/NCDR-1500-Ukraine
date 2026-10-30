PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS project_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS baseline_facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  claim TEXT NOT NULL,
  evidence_status TEXT NOT NULL,
  source_reference TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_templates (
  task_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  priority INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  source_size INTEGER NOT NULL,
  started_utc TEXT NOT NULL,
  finished_utc TEXT,
  status TEXT NOT NULL,
  stage TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS records (
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  sector INTEGER NOT NULL,
  span INTEGER NOT NULL,
  block_type INTEGER NOT NULL,
  compression INTEGER NOT NULL,
  logical_size INTEGER NOT NULL,
  zlib_valid INTEGER,
  PRIMARY KEY(run_id, sector)
);
CREATE INDEX IF NOT EXISTS idx_records_type_comp ON records(run_id, block_type, compression);
CREATE TABLE IF NOT EXISTS tasks (
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  task_id TEXT NOT NULL,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  updated_utc TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(run_id, task_id)
);
CREATE TABLE IF NOT EXISTS model_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  round_no INTEGER NOT NULL,
  model TEXT NOT NULL,
  prompt_sha256 TEXT NOT NULL,
  response_json TEXT NOT NULL,
  parse_status TEXT NOT NULL,
  created_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hypotheses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  round_no INTEGER NOT NULL,
  claim TEXT NOT NULL,
  expected_if_true TEXT NOT NULL,
  falsifier TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'CANDIDATE',
  created_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  round_no INTEGER NOT NULL,
  tool TEXT NOT NULL,
  params_json TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  UNIQUE(run_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS artifacts (
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  relative_path TEXT NOT NULL,
  sha256 TEXT,
  byte_size INTEGER,
  description TEXT NOT NULL DEFAULT '',
  created_utc TEXT NOT NULL,
  PRIMARY KEY(run_id, relative_path)
);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  category TEXT NOT NULL,
  body TEXT NOT NULL,
  created_utc TEXT NOT NULL
);
