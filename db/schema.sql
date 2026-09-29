CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------- service graph (semantic memory) ----------
CREATE TABLE IF NOT EXISTS services (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  owner_team TEXT,
  description TEXT,
  architecture_epoch INT NOT NULL DEFAULT 1   -- bump when the service is re-architected
);

CREATE TABLE IF NOT EXISTS service_dependencies (
  service_id INT REFERENCES services(id) ON DELETE CASCADE,
  depends_on_id INT REFERENCES services(id) ON DELETE CASCADE,
  PRIMARY KEY (service_id, depends_on_id)
);

-- ---------- runbooks (procedural memory) ----------
CREATE TABLE IF NOT EXISTS runbooks (
  id TEXT PRIMARY KEY,                         -- e.g. RB-db-pool-exhaustion
  title TEXT NOT NULL,
  body_md TEXT NOT NULL,
  services TEXT[] NOT NULL DEFAULT '{}',
  emb vector(384),
  success_count INT NOT NULL DEFAULT 0,
  failure_count INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- incidents (episodic memory) ----------
CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY,                         -- INC-0001
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'confirmed',    -- confirmed | archived
  severity TEXT,                               -- sev1..sev4 | unknown
  started_at TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ,
  time_to_resolve_min INT,
  symptoms TEXT[] NOT NULL DEFAULT '{}',
  error_messages TEXT[] NOT NULL DEFAULT '{}',        -- normalised
  error_fingerprints TEXT[] NOT NULL DEFAULT '{}',    -- stack + message fingerprints
  services TEXT[] NOT NULL DEFAULT '{}',
  trigger_type TEXT,                           -- deploy|config_change|traffic_spike|dependency|infra|unknown
  trigger_ref TEXT,                            -- commit sha, deploy tag, change id
  root_cause TEXT,
  root_cause_category TEXT,
  resolution_steps TEXT[] NOT NULL DEFAULT '{}',
  runbook_ids TEXT[] NOT NULL DEFAULT '{}',
  fix_worked BOOLEAN,
  lessons TEXT,
  source_docs JSONB NOT NULL DEFAULT '[]',     -- [{type, id, sha256}]
  symptom_text TEXT NOT NULL,                  -- text that was embedded into emb_symptom
  full_text TEXT NOT NULL,                     -- text embedded into emb_full and used for FTS
  emb_symptom vector(384) NOT NULL,
  emb_full vector(384) NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', full_text)) STORED,
  weight REAL NOT NULL DEFAULT 1.0,            -- recency/staleness weight set by nightly job
  architecture_epoch INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS incidents_emb_symptom_idx ON incidents USING hnsw (emb_symptom vector_cosine_ops);
CREATE INDEX IF NOT EXISTS incidents_tsv_idx ON incidents USING gin (tsv);
CREATE INDEX IF NOT EXISTS incidents_fp_idx ON incidents USING gin (error_fingerprints);
CREATE INDEX IF NOT EXISTS incidents_services_idx ON incidents USING gin (services);

-- ---------- code memory ----------
CREATE TABLE IF NOT EXISTS code_changes (
  id SERIAL PRIMARY KEY,
  repo TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  author TEXT,
  committed_at TIMESTAMPTZ,
  message TEXT,
  files TEXT[] NOT NULL DEFAULT '{}',
  functions TEXT[] NOT NULL DEFAULT '{}',
  diff_summary TEXT,
  emb vector(384),
  UNIQUE (repo, commit_sha)
);

CREATE TABLE IF NOT EXISTS incident_code_links (
  incident_id TEXT REFERENCES incidents(id) ON DELETE CASCADE,
  code_change_id INT REFERENCES code_changes(id) ON DELETE CASCADE,
  link_type TEXT NOT NULL,                     -- caused_by | fixed_by | involved
  PRIMARY KEY (incident_id, code_change_id, link_type)
);

CREATE TABLE IF NOT EXISTS incident_files (
  incident_id TEXT REFERENCES incidents(id) ON DELETE CASCADE,
  file_path TEXT NOT NULL,
  function_name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'involved',       -- root_cause | involved | fix
  PRIMARY KEY (incident_id, file_path, function_name, role)
);
CREATE INDEX IF NOT EXISTS incident_files_path_idx ON incident_files (file_path);

-- ---------- consolidated knowledge (semantic memory) ----------
CREATE TABLE IF NOT EXISTS patterns (
  id SERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  rule_text TEXT NOT NULL,
  exceptions_text TEXT,                        -- when the rule does NOT hold
  trigger_signals TEXT[] NOT NULL DEFAULT '{}',
  recommended_checks TEXT[] NOT NULL DEFAULT '{}',
  recommended_runbooks TEXT[] NOT NULL DEFAULT '{}',
  member_incident_ids TEXT[] NOT NULL,
  confidence REAL,
  emb vector(384),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- live incidents (durable pointer for working memory) ----------
CREATE TABLE IF NOT EXISTS live_incidents (
  id TEXT PRIMARY KEY,                         -- LIVE-YYYYMMDD-NNN
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',         -- open | resolved | postmortem_draft | confirmed
  slack_channel TEXT,
  slack_thread_ts TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  resolution JSONB,                            -- human inputs from resolve step
  postmortem_draft JSONB
);

-- ---------- agent outputs and learning signals ----------
CREATE TABLE IF NOT EXISTS suggestions (
  id SERIAL PRIMARY KEY,
  live_incident_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  query_text TEXT,
  retrieved JSONB,                             -- ids + score breakdowns
  response JSONB,                              -- validated Analysis
  model TEXT,
  latency_ms INT,
  tokens_in INT,
  tokens_out INT
);

CREATE TABLE IF NOT EXISTS feedback (
  id SERIAL PRIMARY KEY,
  suggestion_id INT REFERENCES suggestions(id) ON DELETE CASCADE,
  runbook_id TEXT,
  helpful BOOLEAN NOT NULL,
  comment TEXT,
  user_ref TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
