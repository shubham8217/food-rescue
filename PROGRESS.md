# FoodRescue: Progress

## ✅ Done

| Area | What exists | Where |
|---|---|---|
| Docker setup | Profiles `core`, `pipeline`, `search`, `all`; health checks; one-command start | `docker-compose.yml`, `scripts/up-all.ps1` |
| Auth | JWT + bcrypt; roles donor / ngo / admin; guards on API and pages; service key (`X-API-Key`) for NiFi and Airflow | `routers/auth.py`, `deps.py`, `frontend/src/auth.jsx` |
| Data models | User, Donor, NGO, Donation, Request, Match, IngestBatch, RejectedRow, Event, AnalyticsSnapshot, QualityReport (Alembic 0001, 0002) | `models/`, `alembic/versions/` |
| Status flow | listed → matched → accepted → picked_up → delivered (+ expired); NGOs can accept or decline | `services/workflow.py` |
| Ingestion | `POST /ingest/batch` (JSON, CSV, file upload); raw rows saved to MongoDB first; donors can upload CSV from the UI | `routers/ingest.py`, `services/ingest.py` |
| **Apache NiFi** | Flow built through the REST API: ListFile → FetchFile (archive) → InvokeHTTP → failed files saved | `nifi/deploy_flow.py`, compose `nifi`, `nifi-init` |
| Polars cleaning | Required fields, dedupe (batch + database), categories, expired / unsafe rejection, coordinate fill; reasons stored | `services/cleaning.py` |
| Events + matching | `donation.created` on RabbitMQ; worker: 15 km, expiry, category, score 0.4 / 0.35 / 0.25, top 5; sweeper self-heals | `services/matching.py`, `worker/consumer.py` |
| **Delta Lake** | Versioned history of every donation and status change; time travel endpoint; compaction; cross-process write lock | `services/history.py`, `routers/history.py` |
| **Airflow** | DAGs: expire stale (10 min), analytics snapshot (15 min), Delta compaction (hourly), data quality + reindex (daily) | `airflow/dags/`, `routers/ops.py` |
| **DuckDB + Polars analytics** | Summary, by area / category, timeline, funnel, rejection reasons, top donors / NGOs | `services/analytics.py`, `routers/analytics.py` |
| **Elasticsearch** | Indexing on create and on every status change, reindex, text / filter / distance search; NGO + admin search box | `services/search.py`, `routers/search.py`, `SearchBox.jsx` |
| Forecasting | Recency-weighted surplus forecast by area and hour (outlier-capped) + history backfill | `services/forecast.py` |
| Live demo simulator | Start / stop, 1x / 2x / 5x, 20 batches, ~10% dirty data, CSV to `data/inbox/` + direct API with fallback, simulated NGOs | `simulator/` |
| Frontend | Login; Donor; NGO (matches, accept / decline, pickups, needs, search); Admin live demo; **Analytics** (charts, funnel, forecast); **Pipeline health**; map with clustering, match lines, NGO markers, filters, 15 km radius | `frontend/src/` |
| Production setup | `docker-compose.prod.yml` (Caddy HTTPS, no host DB ports, mandatory secrets, resource limits, no demo accounts, simulator off), backups, CI | `docker-compose.prod.yml`, `deploy/`, `scripts/backup.*`, `.github/workflows/ci.yml` |
| Docs | README (full setup), architecture diagram, ER diagram, demo script, screenshots | `README.md`, `docs/` |
| Tests | About 120 backend tests: cleaning, matching, auth, ingest → match flow, simulator, Delta history (including multi-process writes), analytics, forecast, search, ops, health, production flags | `backend/tests/` |

## How it was verified
* Backend test suite in Docker; frontend `npm run build` in the Docker image.
* Core stack end to end: live demo at 5x, 20 batches, Delta history written by backend and worker together, analytics, forecast, health page.
* Core + Elasticsearch + Airflow: reindex, text / geo / status search, live indexing during the demo, all four DAGs run successfully (Delta compaction removed small files, snapshot and quality report stored).
* Core + NiFi: `nifi-init` deployed the flow (4 processors RUNNING and VALID); with the simulator in CSV-only mode, 8 CSV files were picked up from `data/inbox/`, archived to `data/archive/` and ingested through the API (8 batches with source `api`, 0 failed files, direct path unused); the NiFi canvas shows 20 files processed in a later run.
* `docker-compose.prod.yml` is validated with `docker compose config`; its safety rules (weak secret refusal, no demo accounts, demo disabled) are covered by tests. The production stack itself was not run on a server.

## 🐞 Known limitations
- NiFi runs over plain HTTP without login and Airflow uses SQLite with the SequentialExecutor: fine for a local demo, not for production.
- The whole stack with every profile at once needs roughly 8 GB of Docker memory and about 10 GB of free disk; each profile was verified separately on the development machine, which has little free disk.
- Delta, Elasticsearch and MongoDB writes are best effort: if one is down, the pipeline continues but that store can miss data (use `POST /search/reindex` to rebuild search).
- The simulator runs inside one backend process (single uvicorn worker); the demo NGO account also takes part in the simulation.
- Start Live Demo clears previous donations unless the checkbox is unticked; backfilled history is kept.
- The forecast is a simple explainable baseline learned from synthetic data, not a trained model.
- The frontend has no automated unit tests; it is covered by the build in CI and by the screenshot script.
- Map tiles need internet access.

## 🎤 Demo
See [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).
