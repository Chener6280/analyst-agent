CREATE TABLE IF NOT EXISTS analyst (
  analyst_id TEXT PRIMARY KEY,
  institution TEXT,
  role TEXT,
  team_members TEXT,
  official_accounts TEXT,
  active INT
);

CREATE TABLE IF NOT EXISTS scan (
  scan_id TEXT PRIMARY KEY,
  iso_year INT,
  iso_week INT,
  window_start TEXT,
  window_end TEXT,
  mode TEXT,
  is_weekly INT,
  run_version TEXT,
  schema_version INT,
  model_version TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS stance (
  scan_id TEXT,
  analyst_id TEXT,
  dim_key TEXT,
  type TEXT,
  value INT,
  label TEXT,
  confidence TEXT,
  coverage TEXT,
  text_access TEXT,
  attribution_confidence TEXT,
  evidence_ref TEXT,
  verbatim TEXT,
  PRIMARY KEY (scan_id, analyst_id, dim_key)
);

CREATE TABLE IF NOT EXISTS stance_selection (
  scan_id TEXT,
  analyst_id TEXT,
  dim_key TEXT,
  tag_text TEXT,
  tag_canonical_id TEXT,
  lean INT,
  evidence_ref TEXT,
  verbatim TEXT
);

CREATE INDEX IF NOT EXISTS idx_stance_selection_scan_dim
ON stance_selection(scan_id, dim_key);

CREATE INDEX IF NOT EXISTS idx_stance_selection_entity
ON stance_selection(scan_id, tag_canonical_id);

CREATE TABLE IF NOT EXISTS source (
  scan_id TEXT,
  analyst_id TEXT,
  source_id TEXT,
  title TEXT,
  date TEXT,
  source TEXT,
  source_type TEXT,
  url TEXT,
  adapter_mode TEXT,
  text_access TEXT,
  attribution_confidence TEXT,
  escalated INT,
  PRIMARY KEY (scan_id, analyst_id, source_id)
);

CREATE TABLE IF NOT EXISTS intra_window_change (
  scan_id TEXT,
  analyst_id TEXT,
  dim_key TEXT,
  from_label TEXT,
  to_label TEXT,
  note TEXT,
  from_ref TEXT,
  to_ref TEXT
);
