-- VisionField Copilot — local store.
-- Tables 1–12 are the schema from §14 of the specification, verbatim.
-- Everything below the marked divider is an addition this implementation
-- needs (vectors, stored images, generated reports, live sessions).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  display_name TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  title TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS machines (
  id TEXT PRIMARY KEY,
  name TEXT,
  manufacturer TEXT,
  model TEXT,
  serial_number TEXT,
  metadata_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  machine_id TEXT,
  title TEXT,
  status TEXT,
  summary TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inspections (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  summary TEXT
);

CREATE TABLE IF NOT EXISTS findings (
  id TEXT PRIMARY KEY,
  inspection_id TEXT NOT NULL,
  type TEXT,
  description TEXT NOT NULL,
  confidence REAL,
  source_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS measurements (
  id TEXT PRIMARY KEY,
  inspection_id TEXT NOT NULL,
  name TEXT NOT NULL,
  value REAL,
  unit TEXT,
  source TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  mime_type TEXT,
  path TEXT NOT NULL,
  checksum TEXT,
  page_count INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_chunks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  page_start INTEGER,
  page_end INTEGER,
  content TEXT NOT NULL,
  metadata_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  job_id TEXT,
  memory_type TEXT NOT NULL,
  content TEXT NOT NULL,
  confidence REAL,
  source_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
  id TEXT PRIMARY KEY,
  conversation_id TEXT,
  tool_name TEXT NOT NULL,
  arguments_json TEXT,
  result_json TEXT,
  duration_ms INTEGER,
  created_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Additions required by this implementation.
-- ---------------------------------------------------------------------------

-- §14: "Vector rows should reference document_chunks.id and memories.id."
-- owner_kind is 'document_chunk' or 'memory'; the vector is stored as a raw
-- float32 buffer so the table works with or without sqlite-vec present.
CREATE TABLE IF NOT EXISTS vectors (
  id TEXT PRIMARY KEY,
  owner_kind TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  dim INTEGER NOT NULL,
  model TEXT NOT NULL,
  embedding BLOB NOT NULL,
  norm REAL NOT NULL,
  created_at TEXT NOT NULL
);

-- Stored photo / live frames kept out of the conversation blob.
CREATE TABLE IF NOT EXISTS images (
  id TEXT PRIMARY KEY,
  conversation_id TEXT,
  inspection_id TEXT,
  path TEXT NOT NULL,
  mime_type TEXT,
  width INTEGER,
  height INTEGER,
  source TEXT,
  checksum TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_pages (
  document_id TEXT NOT NULL,
  page_number INTEGER NOT NULL,
  image_path TEXT,
  width INTEGER,
  height INTEGER,
  has_text INTEGER DEFAULT 0,
  PRIMARY KEY (document_id, page_number)
);

CREATE TABLE IF NOT EXISTS reports (
  id TEXT PRIMARY KEY,
  job_id TEXT,
  inspection_id TEXT,
  title TEXT,
  format TEXT,
  path TEXT NOT NULL,
  summary TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS live_sessions (
  id TEXT PRIMARY KEY,
  conversation_id TEXT,
  inspection_id TEXT,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  frames_seen INTEGER DEFAULT 0,
  vlm_calls INTEGER DEFAULT 0,
  state_json TEXT
);

CREATE INDEX IF NOT EXISTS ix_messages_conv       ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS ix_chunks_doc          ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS ix_vectors_owner       ON vectors(owner_kind, owner_id);
CREATE INDEX IF NOT EXISTS ix_memories_job        ON memories(job_id, memory_type);
CREATE INDEX IF NOT EXISTS ix_findings_inspection ON findings(inspection_id);
CREATE INDEX IF NOT EXISTS ix_measure_inspection  ON measurements(inspection_id);
CREATE INDEX IF NOT EXISTS ix_inspections_job     ON inspections(job_id);
CREATE INDEX IF NOT EXISTS ix_jobs_machine        ON jobs(machine_id, updated_at);
CREATE INDEX IF NOT EXISTS ix_toolcalls_conv      ON tool_calls(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS ix_images_conv         ON images(conversation_id);
CREATE INDEX IF NOT EXISTS ix_reports_job         ON reports(job_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
  content,
  chunk_id UNINDEXED,
  document_id UNINDEXED,
  tokenize = 'porter unicode61'
);
