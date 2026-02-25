# Reason codes catalog

Reason codes are the "operational language" of ingestion. They let the system quarantine safely and let operators resolve consistently.

## Current reason codes

### `IDEMPOTENCY_CONFLICT`

**Trigger:** same `(tenant_id, event_id)` received again with a different payload hash.

**Why it matters:** a retry that is not identical is a correctness risk. It could represent:
- an upstream correction being sent with the same event_id
- a bug in the producer generating unstable payloads
- a duplicate ID collision

**Default action:** quarantine the idempotency key and require operator decision.

**Operator resolution options:**
- choose canonical raw event (FIRST vs LAST)
- optionally apply an override patch (JSON merge patch)
- resolve + replay (marks idempotency as processed)
- resolve no replay (ignore, if the event should never post)

---

### `UNKNOWN_EVENT_TYPE`

**Trigger:** event_type is not supported by the simulator's MVP allowlist.

**Why it matters:** unknown event semantics should not silently post to a ledger.

**Default action:** quarantine.

**Operator resolution options:**
- resolve no replay (ignore)
- or expand allowlist and event handling in a future iteration

---

## Status and error codes used in state tracking

These are not reason codes, but they appear in API responses and operational views.

### `ALREADY_QUARANTINED`

**Meaning:** an identical retry arrived while the idempotency key is quarantined.

### `IGNORED_BY_OPERATOR`

**Meaning:** an operator resolved an exception without replay.

## Suggested future reason codes

These are common in enterprise POS ingestion systems and fit the roadmap:

- `SCHEMA_VALIDATION_FAILED` (missing required fields or type mismatch)
- `MISSING_REFERENCE` (return or correction references unknown original txn)
- `CANNOT_EXCEED_ORIGINAL` (partial return exceeds original quantity/amount)
- `TOTALS_MISMATCH` (line items do not reconcile to basket total)
- `LATE_EVENT_OUTSIDE_WINDOW` (arrived beyond allowed correction window)
- `DUPLICATE_SOURCE_EVENT_ID` (collision at source event ID level)
