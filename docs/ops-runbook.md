# Ops workflow runbook

This runbook is intentionally compact. It is designed so an operator can make safe decisions quickly and leave an audit trail.

## Primary operator loop

### 1) Check health

Call:
- `GET /v1/health`

Watch these signals:
- `exceptions_open`: should trend toward zero
- idempotency breakdown:
  - `processed`: healthy baseline
  - `quarantined`: risk requiring attention
  - `ignored`: conscious operator decisions

### 2) Work the exceptions queue

Call:
- `GET /v1/exceptions?status=open`

In the Ops Console:
- filter by tenant if needed
- select an exception to view detail

### 3) Inspect exception detail

Call:
- `GET /v1/exceptions/{exception_id}`

Review:
- reason code and details
- raw payload
- idempotency state (`events_processed`)
- for conflicts, compare FIRST vs LAST raw payload side-by-side

### 4) Choose a resolution

All resolutions require:
- `actor` (who made the decision)
- `resolution_notes` (why)

Actions:
- `mark_resolved_no_replay`
  - closes exception
  - marks idempotency key `ignored`
  - keeps the raw arrival for audit

- `override_and_replay`
  - choose canonical raw event (or default to exception.raw_id)
  - optionally apply `override_patch` (JSON merge patch)
  - validates event_type allowlist
  - marks idempotency key `processed`
  - closes exception
  - increments replay attempts

Call:
- `POST /v1/exceptions/{exception_id}/resolve`

### 5) Verify closure

- exception should move to status `resolved`
- `/v1/health` should show reduced open exceptions
- idempotency should reflect `processed` or `ignored`

## Practical triage guidance

### IDEMPOTENCY_CONFLICT

Questions to answer:
- Is the LAST event a legitimate correction that should be canonical?
- Is the FIRST event the only valid one and the LAST is an upstream bug?
- Is there a stable rule by tenant or source system?

Typical decision:
- choose canonical event
- replay
- record notes indicating why canonical was selected

### UNKNOWN_EVENT_TYPE

Questions to answer:
- Is this truly a new valid type, or noise?
- If valid, do we need to extend supported types?

Typical decision:
- resolve no replay for now, then backlog support work if needed

## Audit principles (the "trust" part)

- Never resolve without notes in real operations.
- Always record who made the decision.
- Prefer replay with a canonical choice over ignoring when the event represents real money.
- Treat overrides as exceptional, and use them to capture learnings into new validation rules.
