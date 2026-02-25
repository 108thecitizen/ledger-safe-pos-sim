# Architecture

Ledger-Safe is intentionally small, but it models the parts that make enterprise ingestion trustworthy and supportable.

## One-sentence overview

**Every event arrival is captured in Bronze, then either processed idempotently or quarantined for controlled operator replay.**

## System diagram

```mermaid
flowchart LR
  subgraph Producers
    POS[POS / upstream producer]
  end

  subgraph Ingestion
    API[FastAPI ingestion API]
    OPS[Streamlit ops console]
  end

  subgraph Postgres["Postgres 16 (system of record)"]
    RAW[(events_raw - Bronze)]
    EP[(events_processed - idempotency state)]
    EX[(exceptions - quarantine queue)]
    AUD[(audit_log - action trail)]
  end

  POS -->|POST /v1/events| API
  API -->|append-only write| RAW
  API -->|upsert state| EP
  API -->|quarantine on conflict| EX
  API -->|audit actions| AUD

  OPS -->|GET /v1/health| API
  OPS -->|GET /v1/exceptions| API
  OPS -->|GET /v1/exceptions/{exception_id}| API
  OPS -->|POST /v1/exceptions/{exception_id}/resolve| API
```

## Why the architecture is shaped this way

### 1) Bronze is append-only by design

`events_raw` exists so the ingestion system can always answer:
- What did we receive?
- When did we receive it?
- How many times did it retry?
- What payload did we actually see?

This is foundational for auditability, incident response, and safe replay/backfill.

### 2) Idempotency lives in a dedicated operational spine

`events_processed` is the canonical state per `(tenant_id, idempotency_key)`.

This lets the API safely respond to retries without double-processing, and it gives operators a stable place to reason about processing status.

### 3) Quarantine is an operational product

`exceptions` turns ambiguity into an operator workflow:
- detect a risky condition,
- hold the idempotency key,
- surface it in the queue,
- resolve and optionally replay under audit control.

### 4) Health signals are first-class

`GET /v1/health` returns counters that support dashboards and alerts:
- raw arrivals (volume)
- open exceptions (operational risk)
- processed vs quarantined vs ignored keys (correctness state)

## What is intentionally not included yet

This simulator focuses on the ingestion guardrails, not full ledger accounting:
- Silver ledger tables (normalized sales, returns, corrections)
- Gold reporting outputs (daily net sales, store KPIs)
- Late event ordering rules, windowing, and backfills beyond the operational replay loop
