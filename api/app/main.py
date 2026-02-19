import os
from typing import Any, Dict

import psycopg
from fastapi import FastAPI

DATABASE_URL = os.getenv("DATABASE_URL", "")

app = FastAPI(title="Ledger-Safe Ingestion API", version="0.1.0")


@app.get("/v1/health")
def health() -> Dict[str, Any]:
    """
    Step-1 smoke test:
    - Prove API is up
    - Prove DB connection works
    - Return a couple of lightweight counters for UI sanity checks
    """
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT now();")
                db_now = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM events_raw;")
                raw_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM exceptions WHERE status = 'open';")
                open_ex = cur.fetchone()[0]

        return {
            "status": "ok",
            "db": "ok",
            "db_time": db_now.isoformat(),
            "counts": {"events_raw": raw_count, "exceptions_open": open_ex},
        }

    except Exception as e:
        return {"status": "degraded", "db": "error", "error": str(e)}
