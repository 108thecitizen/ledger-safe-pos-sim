# LinkedIn carousel (slide-by-slide copy)

Format: 10 slides, outcome-driven, exec-friendly.

## Slide 1 - Title
**Ledger-Safe POS Event Ingestion Simulator**  
Trustworthy ingestion for messy POS and event streams.

Callouts:
- Idempotency
- Quarantine
- Replay
- Audit trail
- Health metrics

## Slide 2 - The problem
POS events are not clean:
- retries and duplicates
- late arrivals
- conflicting corrections and reversals
- upstream bugs (unstable payloads)

If ingestion is wrong, your ledger, dashboards, and customer promises are wrong.

## Slide 3 - What "ledger-safe ingestion" means
Guardrails that prevent silent corruption:
1) Capture everything (Bronze)
2) Enforce idempotency (per tenant)
3) Quarantine ambiguity
4) Enable controlled replay/backfill
5) Audit every decision
6) Expose health signals for ops

## Slide 4 - Architecture (overview)
Producer -> Ingestion API -> Postgres:
- events_raw (Bronze)
- events_processed (idempotency)
- exceptions (quarantine)
- audit_log (traceability)

Ops Console:
- exceptions queue
- detail view
- resolve and replay

## Slide 5 - Idempotency in practice
Same event posted twice:
- first arrival -> 201 processed
- exact retry -> 200 duplicate

Result:
- no double-posting
- raw arrivals still preserved for audit

## Slide 6 - Conflict handling (the key demo)
Same event_id, different payload:
- API returns 202 quarantined
- reason_code = IDEMPOTENCY_CONFLICT
- exception_id created

Result:
- correctness protected
- operator gets a clean queue item to resolve

## Slide 7 - Operator workflow
Operators can:
- review the raw payload that triggered quarantine
- compare FIRST vs LAST payload (conflict)
- choose canonical event
- apply an override patch (optional)
- resolve + replay, or resolve without replay

Every step is auditable.

## Slide 8 - Observability signals
`GET /v1/health` exposes counters:
- events_raw volume
- exceptions_open (risk)
- idempotency breakdown: processed / quarantined / ignored

These metrics are what make ingestion operational, not just functional.

## Slide 9 - 60-second demo flow
1) `docker compose up -d --build`
2) Run `demo/run-demo.ps1`
3) Watch:
   - 201 processed
   - 200 duplicate
   - 202 quarantined (conflict)
4) Open Ops Console and resolve + replay

## Slide 10 - What is next
Planned phases:
- Silver ledger tables (normalized transaction model)
- Gold metrics (daily net sales, reconciliation)
- Expanded reason codes and validation rules
- Per-tenant operational dashboards

CTA:
- Repo: github.com/108thecitizen/ledger-safe-pos-sim
- Run locally in one command
