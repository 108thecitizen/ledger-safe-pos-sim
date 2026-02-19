CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- --- Bronze (raw events) ---
CREATE TABLE IF NOT EXISTS events_raw (
  raw_id         BIGSERIAL PRIMARY KEY,

  tenant_id      TEXT NOT NULL,
  store_id       TEXT NOT NULL,
  source_system  TEXT NOT NULL,

  schema_version TEXT NOT NULL,
  received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  occurred_at    TIMESTAMPTZ NOT NULL,

  event_id       TEXT NOT NULL,
  source_event_id TEXT,
  event_type     TEXT NOT NULL,
  txn_id         TEXT NOT NULL,

  payload_hash   TEXT NOT NULL,
  payload_json   JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_raw_tenant_event
  ON events_raw (tenant_id, event_id);

CREATE INDEX IF NOT EXISTS idx_events_raw_tenant_received
  ON events_raw (tenant_id, received_at);

-- --- Operational state (idempotency + exceptions + audit) ---
CREATE TABLE IF NOT EXISTS events_processed (
  tenant_id         TEXT NOT NULL,
  idempotency_key   TEXT NOT NULL,

  first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  status            TEXT NOT NULL CHECK (status IN ('processed','quarantined','ignored')),
  first_raw_id      BIGINT NOT NULL REFERENCES events_raw(raw_id),
  last_raw_id       BIGINT NOT NULL REFERENCES events_raw(raw_id),

  payload_hash_first TEXT NOT NULL,
  payload_hash_last  TEXT NOT NULL,

  processed_at      TIMESTAMPTZ,
  last_error_code   TEXT,
  last_exception_id UUID,

  PRIMARY KEY (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS exceptions (
  exception_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  tenant_id         TEXT NOT NULL,
  raw_id            BIGINT NOT NULL REFERENCES events_raw(raw_id),
  idempotency_key   TEXT NOT NULL,

  reason_code       TEXT NOT NULL,
  details_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
  override_patch    JSONB NOT NULL DEFAULT '{}'::jsonb,

  status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
  assigned_to       TEXT,

  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at       TIMESTAMPTZ,

  resolution_action TEXT,
  resolution_notes  TEXT,
  resolution_actor  TEXT,

  replay_attempts   INT NOT NULL DEFAULT 0,
  last_replay_at    TIMESTAMPTZ,
  last_replay_status TEXT
);

CREATE INDEX IF NOT EXISTS idx_exceptions_queue
  ON exceptions (status, tenant_id, created_at);

CREATE TABLE IF NOT EXISTS audit_log (
  audit_id       BIGSERIAL PRIMARY KEY,
  occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

  actor          TEXT NOT NULL,
  action         TEXT NOT NULL,
  object_type    TEXT NOT NULL,
  object_id      TEXT NOT NULL,

  before_json    JSONB,
  after_json     JSONB,
  notes          TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_object
  ON audit_log (object_type, object_id);
