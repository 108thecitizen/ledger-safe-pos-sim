# Data model (Bronze to Gold roadmap)

This project starts with the operational spine needed for trustworthy ingestion.

## Current tables (MVP operational spine)

### `events_raw` (Bronze)

**Purpose:** append-only capture of every request payload as received.

**What it enables:** auditability, replay/backfill, investigation, and "show me exactly what arrived."

**Key fields (high-level):**
- `raw_id` (surrogate key)
- `tenant_id`, `store_id`, `source_system`
- `schema_version`
- `received_at`, `occurred_at`
- `event_id`, `source_event_id`
- `event_type`, `txn_id`
- `payload_hash`, `payload_json`

### `events_processed` (Operational state)

**Purpose:** idempotency and processing state per tenant and idempotency key.

**What it enables:** safe retries, conflict detection, stable processing semantics.

**Key fields (high-level):**
- `tenant_id`, `idempotency_key`
- `status` (`processed`, `quarantined`, `ignored`)
- `first_seen_at`, `last_seen_at`
- `first_raw_id`, `last_raw_id`
- `payload_hash_first`, `payload_hash_last`
- `processed_at`
- `last_error_code`, `last_exception_id`

### `exceptions` (Quarantine queue)

**Purpose:** hold risky events for operator review and controlled replay.

**Key fields (high-level):**
- `exception_id`
- `tenant_id`, `raw_id`, `idempotency_key`
- `reason_code`
- `details_json` (machine-readable context)
- `status` (`open`, `resolved`)
- `assigned_to` (optional)
- `replay_attempts`, `last_replay_at`, `last_replay_status`
- `resolution_action`, `resolution_notes`, `resolution_actor`
- `override_patch` (JSON merge patch applied during replay)

### `audit_log` (Audit trail)

**Purpose:** record operator and system actions in a human-readable way.

**Typical actions:**
- quarantine
- resolve_no_replay
- resolve_and_replay

## Roadmap: Bronze -> Silver -> Gold

### Bronze (now)

- `events_raw`

### Operational spine (now)

- `events_processed`
- `exceptions`
- `audit_log`

### Silver (future)

Normalize to a durable ledger representation that is friendly to downstream analytics.

Candidate tables:
- `ledger_transactions` (sales, returns, corrections)
- `ledger_line_items` (SKU-level detail where provided)
- `ledger_references` (link returns and corrections to originals)

Core silver invariants:
- idempotent posting rules
- returns reference original sale
- cannot exceed original (for partial returns)

### Gold (future)

Outcome-driven metrics and reconciliations.

Examples:
- daily net sales by tenant/store
- return rate and correction rate
- ingestion health by tenant (exceptions, retries, duplicates)
- reconciliation views: Bronze volume vs Silver posted vs Gold aggregates

## What a reviewer should take away

You can add more transformation layers later, but without this operational spine, you do not have ingestion you can trust.
