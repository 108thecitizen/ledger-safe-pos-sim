import os
import json
import hashlib
import copy
from datetime import datetime
from typing import Any, Dict, Optional, List

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import FastAPI, Request, HTTPException, Query, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict, ValidationError

DATABASE_URL = os.getenv("DATABASE_URL", "")

# MVP: accept these event types; anything else gets quarantined.
ALLOWED_EVENT_TYPES = {"SALE", "RETURN", "CORRECTION", "CANCEL", "VOID"}

# MVP: implement only these operator actions (we can add the others later).
ALLOWED_RESOLUTION_ACTIONS = {
    "mark_resolved_no_replay",
    "override_and_replay",
}


def canonical_json(obj: Any) -> str:
    """Stable JSON serialization for hashing (order-independent)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def json_merge_patch(target: Any, patch: Any) -> Any:
    """
    RFC 7396 style JSON Merge Patch.
    - If patch is a dict: merge recursively
    - If patch value is null: delete key
    - Otherwise: replace
    """
    if not isinstance(patch, dict):
        return patch

    if not isinstance(target, dict):
        target = {}

    result = copy.deepcopy(target)
    for k, v in patch.items():
        if v is None:
            result.pop(k, None)
        elif isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = json_merge_patch(result.get(k), v)
        else:
            result[k] = copy.deepcopy(v)
    return result


class EventIn(BaseModel):
    """
    Minimal envelope validation for Step 2/3.
    Extra fields are allowed and preserved in Bronze payload_json.
    """
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    schema_version: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    source_system: str = Field(min_length=1)

    event_id: str = Field(min_length=1)
    source_event_id: Optional[str] = None

    event_type: str = Field(min_length=1)
    occurred_at: datetime

    txn_id: str = Field(min_length=1)


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: str = Field(min_length=1)
    actor: str = Field(min_length=1)  # e.g. "operator:bill"
    resolution_notes: str = Field(default="")

    # Optional: patch to apply before replay (json merge patch)
    override_patch: Dict[str, Any] = Field(default_factory=dict)

    # Optional: which raw_id to treat as canonical for replay (useful for idempotency conflicts)
    canonical_raw_id: Optional[int] = None


app = FastAPI(title="Ledger-Safe Ingestion API", version="0.3.0")


def _connect() -> psycopg.Connection:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(DATABASE_URL, connect_timeout=3)


def _create_exception_and_quarantine(
    *,
    conn: psycopg.Connection,
    tenant_id: str,
    raw_id: int,
    idempotency_key: str,
    reason_code: str,
    details: Dict[str, Any],
    actor: str = "system",
) -> str:
    """Creates an open exception and marks the idempotency record quarantined."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO exceptions (
              tenant_id, raw_id, idempotency_key,
              reason_code, details_json,
              status
            )
            VALUES (%s, %s, %s, %s, %s, 'open')
            RETURNING exception_id::text;
            """,
            (tenant_id, raw_id, idempotency_key, reason_code, Jsonb(details)),
        )
        exception_id = cur.fetchone()[0]

        cur.execute(
            """
            UPDATE events_processed
               SET status = 'quarantined',
                   last_error_code = %s,
                   last_exception_id = %s,
                   processed_at = NULL
             WHERE tenant_id = %s
               AND idempotency_key = %s;
            """,
            (reason_code, exception_id, tenant_id, idempotency_key),
        )

        cur.execute(
            """
            INSERT INTO audit_log (actor, action, object_type, object_id, notes, after_json)
            VALUES (%s, 'quarantine', 'exception', %s, %s, %s);
            """,
            (actor, exception_id, reason_code, Jsonb({"reason_code": reason_code, "raw_id": raw_id})),
        )

    return exception_id


def _fetch_events_raw(conn: psycopg.Connection, raw_id: int) -> Optional[Dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT raw_id, tenant_id, store_id, source_system, schema_version,
                   received_at, occurred_at,
                   event_id, source_event_id, event_type, txn_id,
                   payload_hash, payload_json
            FROM events_raw
            WHERE raw_id = %s;
            """,
            (raw_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


@app.get("/v1/health")
def health() -> Dict[str, Any]:
    """Health + useful counters."""
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT now();")
                db_now = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM events_raw;")
                raw_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM exceptions WHERE status = 'open';")
                open_ex = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT
                      COUNT(*) FILTER (WHERE status = 'processed') AS processed,
                      COUNT(*) FILTER (WHERE status = 'quarantined') AS quarantined,
                      COUNT(*) FILTER (WHERE status = 'ignored') AS ignored
                    FROM events_processed;
                    """
                )
                row = cur.fetchone()
                processed_keys = int(row[0] or 0)
                quarantined_keys = int(row[1] or 0)
                ignored_keys = int(row[2] or 0)

        return {
            "status": "ok",
            "db": "ok",
            "db_time": db_now.isoformat(),
            "counts": {
                "events_raw": raw_count,
                "exceptions_open": open_ex,
                "idempotency": {
                    "processed": processed_keys,
                    "quarantined": quarantined_keys,
                    "ignored": ignored_keys,
                },
            },
        }

    except Exception as e:
        return {"status": "degraded", "db": "error", "error": str(e)}


@app.post("/v1/events")
async def ingest_event(request: Request) -> JSONResponse:
    """
    Step 2 behavior:
    1) Write raw payload to Bronze (events_raw)
    2) Enforce idempotency using events_processed
       - Same idempotency_key + same payload_hash => duplicate (safe)
       - Same idempotency_key + different payload_hash => quarantine
    3) Quarantine unknown event types
    """
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail={"error": "INVALID_JSON"})

    payload_hash = sha256_hex(canonical_json(payload))

    try:
        event = EventIn.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail={"error": "VALIDATION_ERROR", "details": e.errors()})

    tenant_id = event.tenant_id
    store_id = event.store_id
    source_system = event.source_system
    schema_version = event.schema_version
    occurred_at = event.occurred_at
    event_id = event.event_id
    source_event_id = event.source_event_id
    txn_id = event.txn_id
    event_type = event.event_type.upper().strip()

    idempotency_key = event_id  # MVP decision

    with _connect() as conn:
        with conn.transaction():
            # 1) Bronze write (always append)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO events_raw (
                      tenant_id, store_id, source_system,
                      schema_version, occurred_at,
                      event_id, source_event_id, event_type, txn_id,
                      payload_hash, payload_json
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING raw_id;
                    """,
                    (
                        tenant_id,
                        store_id,
                        source_system,
                        schema_version,
                        occurred_at,
                        event_id,
                        source_event_id,
                        event_type,
                        txn_id,
                        payload_hash,
                        Jsonb(payload),
                    ),
                )
                raw_id = int(cur.fetchone()[0])

            # 2) Idempotency upsert
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO events_processed (
                      tenant_id, idempotency_key,
                      first_seen_at, last_seen_at,
                      status, first_raw_id, last_raw_id,
                      payload_hash_first, payload_hash_last,
                      processed_at, last_error_code, last_exception_id
                    )
                    VALUES (%(tenant_id)s, %(id_key)s,
                            now(), now(),
                            'processed', %(raw_id)s, %(raw_id)s,
                            %(hash)s, %(hash)s,
                            now(), NULL, NULL)
                    ON CONFLICT (tenant_id, idempotency_key)
                    DO UPDATE SET
                      last_seen_at = now(),
                      last_raw_id = EXCLUDED.last_raw_id,
                      payload_hash_last = EXCLUDED.payload_hash_last
                    RETURNING
                      (xmax = 0) AS inserted,
                      status,
                      first_raw_id,
                      last_raw_id,
                      payload_hash_first,
                      last_exception_id::text;
                    """,
                    {"tenant_id": tenant_id, "id_key": idempotency_key, "raw_id": raw_id, "hash": payload_hash},
                )
                inserted, current_status, first_raw_id, last_raw_id, payload_hash_first, last_exception_id = cur.fetchone()

            # 3) First time: minimal gates
            if inserted:
                if event_type not in ALLOWED_EVENT_TYPES:
                    ex_id = _create_exception_and_quarantine(
                        conn=conn,
                        tenant_id=tenant_id,
                        raw_id=raw_id,
                        idempotency_key=idempotency_key,
                        reason_code="UNKNOWN_EVENT_TYPE",
                        details={
                            "event_type": event_type,
                            "allowed_event_types": sorted(list(ALLOWED_EVENT_TYPES)),
                            "message": "Event type is not supported by the ingestion simulator MVP.",
                        },
                    )
                    return JSONResponse(
                        status_code=202,
                        content={
                            "tenant_id": tenant_id,
                            "idempotency_key": idempotency_key,
                            "raw_id": raw_id,
                            "result": "quarantined",
                            "exception_id": ex_id,
                            "reason_code": "UNKNOWN_EVENT_TYPE",
                        },
                    )

                return JSONResponse(
                    status_code=201,
                    content={
                        "tenant_id": tenant_id,
                        "idempotency_key": idempotency_key,
                        "raw_id": raw_id,
                        "result": "processed",
                        "exception_id": None,
                        "reason_code": None,
                    },
                )

            # Seen before
            if payload_hash_first == payload_hash:
                if current_status == "quarantined":
                    return JSONResponse(
                        status_code=202,
                        content={
                            "tenant_id": tenant_id,
                            "idempotency_key": idempotency_key,
                            "raw_id": raw_id,
                            "result": "quarantined",
                            "exception_id": last_exception_id,
                            "reason_code": "ALREADY_QUARANTINED",
                        },
                    )

                return JSONResponse(
                    status_code=200,
                    content={
                        "tenant_id": tenant_id,
                        "idempotency_key": idempotency_key,
                        "raw_id": raw_id,
                        "result": "duplicate",
                        "exception_id": None,
                        "reason_code": None,
                    },
                )

            # Conflicting duplicate => quarantine
            ex_id = _create_exception_and_quarantine(
                conn=conn,
                tenant_id=tenant_id,
                raw_id=raw_id,
                idempotency_key=idempotency_key,
                reason_code="IDEMPOTENCY_CONFLICT",
                details={
                    "message": "Same idempotency_key seen with different payload hash.",
                    "existing_payload_hash": payload_hash_first,
                    "new_payload_hash": payload_hash,
                    "first_raw_id": int(first_raw_id),
                    "new_raw_id": int(raw_id),
                },
            )
            return JSONResponse(
                status_code=202,
                content={
                    "tenant_id": tenant_id,
                    "idempotency_key": idempotency_key,
                    "raw_id": raw_id,
                    "result": "quarantined",
                    "exception_id": ex_id,
                    "reason_code": "IDEMPOTENCY_CONFLICT",
                },
            )


@app.get("/v1/exceptions")
def list_exceptions(
    status: str = Query(default="open"),
    tenant_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> Dict[str, Any]:
    if status not in ("open", "resolved"):
        raise HTTPException(status_code=400, detail={"error": "INVALID_STATUS", "allowed": ["open", "resolved"]})

    sql = """
      SELECT
        exception_id::text AS exception_id,
        tenant_id,
        raw_id,
        idempotency_key,
        reason_code,
        status,
        assigned_to,
        created_at,
        resolved_at,
        replay_attempts,
        last_replay_status
      FROM exceptions
      WHERE status = %s
    """
    params: List[Any] = [status]

    if tenant_id:
        sql += " AND tenant_id = %s"
        params.append(tenant_id)

    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)

    with _connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    return {"items": rows}


@app.get("/v1/exceptions/{exception_id}")
def get_exception_detail(
    exception_id: str = Path(..., min_length=10),
) -> Dict[str, Any]:
    """
    Returns:
    - exception row
    - raw event row tied to exception.raw_id
    - events_processed row for (tenant_id, idempotency_key)
    - first_raw_event + last_raw_event (handy for idempotency conflicts)
    """
    with _connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                  exception_id::text AS exception_id,
                  tenant_id,
                  raw_id,
                  idempotency_key,
                  reason_code,
                  details_json,
                  override_patch,
                  status,
                  assigned_to,
                  created_at,
                  resolved_at,
                  resolution_action,
                  resolution_notes,
                  resolution_actor,
                  replay_attempts,
                  last_replay_at,
                  last_replay_status
                FROM exceptions
                WHERE exception_id = %s;
                """,
                (exception_id,),
            )
            ex = cur.fetchone()
            if not ex:
                raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "exception_id": exception_id})

            ex = dict(ex)
            raw_event = _fetch_events_raw(conn, int(ex["raw_id"]))

            cur.execute(
                """
                SELECT
                  tenant_id,
                  idempotency_key,
                  first_raw_id,
                  last_raw_id,
                  status,
                  first_seen_at,
                  last_seen_at,
                  processed_at,
                  payload_hash_first,
                  payload_hash_last,
                  last_error_code,
                  last_exception_id::text AS last_exception_id
                FROM events_processed
                WHERE tenant_id = %s AND idempotency_key = %s;
                """,
                (ex["tenant_id"], ex["idempotency_key"]),
            )
            ep = cur.fetchone()
            ep = dict(ep) if ep else None

            first_raw_event = _fetch_events_raw(conn, int(ep["first_raw_id"])) if ep else None
            last_raw_event = _fetch_events_raw(conn, int(ep["last_raw_id"])) if ep else None

    return {
        "exception": ex,
        "raw_event": raw_event,
        "events_processed": ep,
        "first_raw_event": first_raw_event,
        "last_raw_event": last_raw_event,
    }


@app.post("/v1/exceptions/{exception_id}/resolve")
def resolve_exception(
    body: ResolveIn,
    exception_id: str = Path(..., min_length=10),
) -> Dict[str, Any]:
    """
    Operator resolution + optional replay:
    - mark_resolved_no_replay: close exception and mark idempotency key ignored
    - override_and_replay: choose canonical raw event (or default), apply patch, mark processed
    """
    if body.action not in ALLOWED_RESOLUTION_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail={"error": "INVALID_ACTION", "allowed": sorted(list(ALLOWED_RESOLUTION_ACTIONS))},
        )

    with _connect() as conn:
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                      exception_id::text AS exception_id,
                      tenant_id,
                      raw_id,
                      idempotency_key,
                      reason_code,
                      status,
                      replay_attempts
                    FROM exceptions
                    WHERE exception_id = %s;
                    """,
                    (exception_id,),
                )
                ex = cur.fetchone()
                if not ex:
                    raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "exception_id": exception_id})

                ex = dict(ex)
                if ex["status"] != "open":
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "ALREADY_RESOLVED", "exception_id": exception_id, "status": ex["status"]},
                    )

                cur.execute(
                    """
                    SELECT
                      tenant_id,
                      idempotency_key,
                      first_raw_id,
                      last_raw_id,
                      status,
                      payload_hash_first,
                      payload_hash_last
                    FROM events_processed
                    WHERE tenant_id = %s AND idempotency_key = %s;
                    """,
                    (ex["tenant_id"], ex["idempotency_key"]),
                )
                ep = cur.fetchone()
                if not ep:
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "MISSING_IDEMPOTENCY_RECORD", "idempotency_key": ex["idempotency_key"]},
                    )
                ep = dict(ep)

                now = datetime.utcnow().isoformat() + "Z"

                # ---- Action: resolve without replay (ignore) ----
                if body.action == "mark_resolved_no_replay":
                    cur.execute(
                        """
                        UPDATE exceptions
                           SET status = 'resolved',
                               resolved_at = now(),
                               resolution_action = %s,
                               resolution_notes = %s,
                               resolution_actor = %s,
                               last_replay_status = 'not_replayed'
                         WHERE exception_id = %s;
                        """,
                        (body.action, body.resolution_notes, body.actor, exception_id),
                    )

                    cur.execute(
                        """
                        UPDATE events_processed
                           SET status = 'ignored',
                               processed_at = now(),
                               last_error_code = 'IGNORED_BY_OPERATOR',
                               last_exception_id = %s
                         WHERE tenant_id = %s AND idempotency_key = %s;
                        """,
                        (exception_id, ex["tenant_id"], ex["idempotency_key"]),
                    )

                    cur.execute(
                        """
                        INSERT INTO audit_log (actor, action, object_type, object_id, notes, after_json)
                        VALUES (%s, 'resolve_no_replay', 'exception', %s, %s, %s);
                        """,
                        (
                            body.actor,
                            exception_id,
                            body.resolution_notes,
                            Jsonb(
                                {
                                    "action": body.action,
                                    "idempotency_key": ex["idempotency_key"],
                                    "decision_time": now,
                                }
                            ),
                        ),
                    )

                    return {
                        "exception_id": exception_id,
                        "status": "resolved",
                        "replay": {"attempted": False},
                    }

                # ---- Action: override + replay ----
                canonical_raw_id = int(body.canonical_raw_id) if body.canonical_raw_id else int(ex["raw_id"])

                canonical_raw = _fetch_events_raw(conn, canonical_raw_id)
                if not canonical_raw:
                    raise HTTPException(
                        status_code=400,
                        detail={"error": "INVALID_CANONICAL_RAW_ID", "canonical_raw_id": canonical_raw_id},
                    )

                if canonical_raw["tenant_id"] != ex["tenant_id"]:
                    raise HTTPException(
                        status_code=400,
                        detail={"error": "CANONICAL_RAW_TENANT_MISMATCH", "canonical_raw_id": canonical_raw_id},
                    )

                final_payload = json_merge_patch(canonical_raw["payload_json"], body.override_patch or {})
                final_hash = sha256_hex(canonical_json(final_payload))

                final_event_type = str(final_payload.get("event_type", "")).upper().strip()
                if not final_event_type:
                    raise HTTPException(status_code=400, detail={"error": "MISSING_EVENT_TYPE_IN_PAYLOAD"})
                if final_event_type not in ALLOWED_EVENT_TYPES:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "REPLAY_VALIDATION_FAILED",
                            "reason_code": "UNKNOWN_EVENT_TYPE",
                            "event_type": final_event_type,
                            "allowed_event_types": sorted(list(ALLOWED_EVENT_TYPES)),
                        },
                    )

                # Mark canonical choice by updating payload_hash_first to the selected+patched payload hash.
                # This prevents future duplicates of the canonical payload from re-quarantining.
                cur.execute(
                    """
                    UPDATE events_processed
                       SET status = 'processed',
                           processed_at = now(),
                           payload_hash_first = %s,
                           payload_hash_last = %s,
                           last_error_code = NULL,
                           last_exception_id = NULL
                     WHERE tenant_id = %s AND idempotency_key = %s;
                    """,
                    (final_hash, final_hash, ex["tenant_id"], ex["idempotency_key"]),
                )

                cur.execute(
                    """
                    UPDATE exceptions
                       SET status = 'resolved',
                           resolved_at = now(),
                           resolution_action = %s,
                           resolution_notes = %s,
                           resolution_actor = %s,
                           override_patch = %s,
                           replay_attempts = replay_attempts + 1,
                           last_replay_at = now(),
                           last_replay_status = 'processed'
                     WHERE exception_id = %s;
                    """,
                    (body.action, body.resolution_notes, body.actor, Jsonb(body.override_patch or {}), exception_id),
                )

                cur.execute(
                    """
                    INSERT INTO audit_log (actor, action, object_type, object_id, notes, after_json)
                    VALUES (%s, 'resolve_and_replay', 'exception', %s, %s, %s);
                    """,
                    (
                        body.actor,
                        exception_id,
                        body.resolution_notes,
                        Jsonb(
                            {
                                "action": body.action,
                                "idempotency_key": ex["idempotency_key"],
                                "canonical_raw_id": canonical_raw_id,
                                "final_payload_hash": final_hash,
                                "decision_time": now,
                            }
                        ),
                    ),
                )

                return {
                    "exception_id": exception_id,
                    "status": "resolved",
                    "replay": {
                        "attempted": True,
                        "result": "processed",
                        "canonical_raw_id": canonical_raw_id,
                        "final_payload_hash": final_hash,
                    },
                }
