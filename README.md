# Ledger-Safe POS Event Ingestion Simulator

A locally runnable ingestion system that models enterprise POS realities: retries, duplicates, returns/reversals, quarantine + operator replay, and operational health signals.

## Run locally (Docker Desktop)
```powershell
docker compose up -d --build
```

## Verify
API health: http://localhost:8000/v1/health
UI: http://localhost:8501

## Stop
```powershell
docker compose down
```

## Reset DB (rerun schema init scripts)
```powershell
docker compose down -v
docker compose up -d --build
```
