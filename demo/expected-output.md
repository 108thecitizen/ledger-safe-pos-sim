# Expected demo outputs

This file is here so reviewers can compare without running the project.

> Notes:
> - `raw_id` and `exception_id` values will differ on every run.
> - The important thing is the status code and `result` field.

## Step 0: health before posts

`GET /v1/health` should return `status=ok` with counts near zero.

## Step 1: first arrival (processed)

`POST /v1/events` returns **201**:

```json
{
  "tenant_id": "tenant_demo",
  "idempotency_key": "evt-1001",
  "raw_id": 1,
  "result": "processed",
  "exception_id": null,
  "reason_code": null
}
```

## Step 2: exact retry (duplicate)

`POST /v1/events` returns **200**:

```json
{
  "tenant_id": "tenant_demo",
  "idempotency_key": "evt-1001",
  "raw_id": 2,
  "result": "duplicate",
  "exception_id": null,
  "reason_code": null
}
```

## Step 3: conflicting duplicate (quarantine)

`POST /v1/events` returns **202**:

```json
{
  "tenant_id": "tenant_demo",
  "idempotency_key": "evt-1001",
  "raw_id": 3,
  "result": "quarantined",
  "exception_id": "EXAMPLE-UUID",
  "reason_code": "IDEMPOTENCY_CONFLICT"
}
```

## Step 4: unknown event type (quarantine)

`POST /v1/events` returns **202**:

```json
{
  "tenant_id": "tenant_demo",
  "idempotency_key": "evt-2001",
  "raw_id": 4,
  "result": "quarantined",
  "exception_id": "EXAMPLE-UUID",
  "reason_code": "UNKNOWN_EVENT_TYPE"
}
```

## Step 5: health after posts

`GET /v1/health` should reflect:
- `events_raw` increased by 4
- `exceptions_open` increased by 2
- `idempotency.processed` increased by 1
- `idempotency.quarantined` increased by 1
