# FoodRescue: Remaining Work (detailed)

This document lists only what is **not built yet**, with the purpose, exact steps, files to touch, and how to check it works.

**Already available to build on:** CSV files in `data/inbox/`, raw rows in MongoDB, clean data in PostgreSQL, `donation.created` events in RabbitMQ, the matching worker, the live demo simulator and the React dashboard.

Suggested order: 1 NiFi → 2 Delta Lake → 3 Airflow → 4 DuckDB analytics → 5 Elasticsearch → 6 Pipeline-health page → 7 Map polish → 8 Forecasting → 9 Deployment → 10 Final docs.

---

## 1. Apache NiFi (ingestion)

**Purpose:** NiFi becomes the official file-ingestion tool. It watches `data/inbox/` and sends every CSV to the API, instead of the simulator posting directly.

**Steps**
1. Add a `nifi` service to `docker-compose.yml` (image `apache/nifi`, profiles `[pipeline, all]`, port `8443`, mount `./data/inbox:/data/inbox` and a new `./data/archive`).
2. Build the flow in the NiFi UI:
   - `ListFile` (directory `/data/inbox`, filter `.*\.csv`) → `FetchFile`
   - `InvokeHTTP` (POST `http://backend:8000/ingest/batch`, content type `text/csv`, header `Authorization: Bearer <admin token>`)
   - On success → `PutFile` to `/data/archive`; on failure → retry queue, then `/data/failed`.
3. Export the flow as JSON into `nifi/flow.json` so it can be re-imported.
4. Set `SIM_DIRECT_INGEST=false` in `.env` so NiFi is the only path (the dedupe logic already prevents double-loading if both are on).
5. Optional: a service account for NiFi (long-lived token or a dedicated `ingest` role) instead of the admin token.

**Files:** `docker-compose.yml`, `nifi/flow.json` (new), `.env`, README section.
**Done when:** starting the live demo makes CSVs appear in `data/inbox/`, NiFi moves them to `data/archive/`, and the admin counters still increase.

---

## 2. Delta Lake (history and versions)

**Purpose:** keep a versioned history of donations and every status change (time travel), separate from the current state in PostgreSQL.

**Steps**
1. Add the `deltalake` Python package to `backend/requirements.txt`.
2. Create `backend/app/services/history.py` with `record_donations(rows)` and `record_status_change(donation_id, old, new, ts)` writing to `data/delta/donation_history` and `data/delta/status_events` (mounted volume).
3. Call it after the DB commit in `services/ingest.py::ingest_rows` (new donations) and in `services/workflow.py` (`accept_match`, `advance_status`) and the expiry sweep in `simulator/lifecycle.py`.
4. Wrap calls in try/except so a Delta failure never breaks ingestion.
5. Add `GET /history/donations/{id}` that reads all versions of one donation (use `DeltaTable(...).history()` and `load_version`).
6. Add `OPTIMIZE`/vacuum helper for the Airflow DAG (see 3).

**Files:** `history.py` (new), `ingest.py`, `workflow.py`, `lifecycle.py`, `routers/history.py` (new), `docker-compose.yml` (volume).
**Done when:** after a demo run, `data/delta/` contains Delta tables and a donation's full status timeline can be read back by version.

---

## 3. Apache Airflow (orchestration)

**Purpose:** schedule and monitor the batch jobs of the pipeline.

**Steps**
1. Add `airflow` (webserver + scheduler, LocalExecutor, metadata in the existing Postgres under a separate `airflow` database) to compose with profile `pipeline`; mount `./pipeline/dags`.
2. Write DAGs in `pipeline/dags/`:
   - `delta_snapshot` (hourly): compact/optimise Delta tables, write a daily snapshot.
   - `analytics_refresh` (every 15 min): rebuild DuckDB aggregate tables (see 4).
   - `expire_stale_donations` (every 10 min): mark expired donations.
   - `data_quality_report` (daily): rejected-row counts by reason, duplicate rate, written to a table/CSV.
3. DAG tasks import the same service functions used by the API (mount `backend/app` into the Airflow image or call the API).
4. Add Airflow link and DAG screenshots to the docs.

**Files:** `pipeline/dags/*.py` (new), `docker-compose.yml`, `pipeline/Dockerfile` (new).
**Done when:** DAGs appear in the Airflow UI, run on schedule and succeed.

---

## 4. DuckDB + Polars analytics and charts

**Purpose:** fast analytics over the history, shown as charts.

**Steps**
1. Add `duckdb` to requirements. Create `backend/app/services/analytics.py` that opens DuckDB, reads Delta tables (via `delta_scan`) or PostgreSQL, and returns Polars DataFrames.
2. Metrics to compute: kg rescued and meals per day / area / category; acceptance rate; average time listed → accepted → delivered; top donors and NGOs; rejection reasons; surplus by hour of day.
3. Add `routers/analytics.py` with `GET /analytics/summary`, `/analytics/by-area`, `/analytics/timeline`, `/analytics/rejections`, `/analytics/funnel` (admin only).
4. Frontend: new `Analytics.jsx` page (add a chart library such as `recharts`) with bar, line and funnel charts; add a link in the admin layout.
5. Tests: feed a small known Delta/Postgres dataset and assert the numbers.

**Files:** `analytics.py`, `routers/analytics.py`, `frontend/src/pages/Analytics.jsx`, `tests/test_analytics.py`.
**Done when:** the Analytics page shows correct charts after a demo run.

---

## 5. Elasticsearch (search)

**Purpose:** fast text and filter search over donations and NGOs.

**Steps**
1. Add `elasticsearch` (single node, security off for local) to compose with profile `search`; add the `elasticsearch` Python client.
2. Create `backend/app/services/search.py`: index mapping for donations (`food_type`, `category`, `area`, `status`, `quantity_kg`, `expiry_time`, `location` as `geo_point`) and NGOs.
3. Index each donation in the worker (`worker/consumer.py`) when it consumes `donation.created`, and update the document on status changes. Add a one-time `reindex` command.
4. Add `GET /search/donations?q=&category=&area=&status=&near=lat,lng&radius_km=` and `GET /search/ngos`.
5. Frontend: search box with filters on the NGO and admin pages.

**Files:** `search.py`, `routers/search.py`, `worker/consumer.py`, `docker-compose.yml`, frontend search component.
**Done when:** typing "biryani" finds matching donations within a second and filters/geo-radius work.

---

## 6. Pipeline-health page

**Purpose:** show that every stage of the pipeline is working.

**Steps**
1. Backend `GET /health/pipeline` (admin): queue depth and consumers from the RabbitMQ management API (`/api/queues`), MongoDB and PostgreSQL row counts, last batch time, ingest throughput (rows/min), reject rate over time, worker lag (oldest unmatched donation age), NiFi/Airflow status when enabled.
2. Frontend `Pipeline.jsx`: status cards (green/red), a small throughput chart and a recent-batches table.
3. Add alerts (e.g. red when queue depth keeps growing or no batch for 2 minutes).

**Files:** `routers/pipeline.py`, `frontend/src/pages/Pipeline.jsx`.
**Done when:** stopping RabbitMQ turns the RabbitMQ card red and the page recovers when it is started again.

---

## 7. Map polish

**Steps**
1. Draw a line from each accepted donation to its NGO (Leaflet `Polyline`, colour by status).
2. Cluster markers (`react-leaflet-cluster`) so hundreds of pins stay readable.
3. Show NGO markers (different shape) and a 15 km radius circle when a donation is selected.
4. Filters: status, category, area; legend click to hide a status.
5. Return `accepted_ngo` coordinates in the live payload (`services/stats.py`).

**Files:** `frontend/src/components/MapView.jsx`, `services/stats.py`.

---

## 8. Forecasting

**Purpose:** predict surplus per area and hour so NGOs can plan pickups.

**Steps**
1. Build an hourly history table per area from Delta (or Postgres).
2. Baseline: Polars rolling averages by (area, weekday, hour). Better: a small model (e.g. `statsmodels` or `prophet`).
3. Add `GET /forecast?area=&hours=24` and a chart on the analytics page; add an Airflow DAG to retrain daily.
4. Because the simulator data is synthetic, generate a few days of history first (simulator option to backfill).

**Files:** `services/forecast.py`, `routers/forecast.py`, `pipeline/dags/forecast_train.py`, chart in `Analytics.jsx`.

---

## 9. Deployment

**Steps**
1. Production compose file (`docker-compose.prod.yml`): no exposed DB ports, strong passwords via secrets, restart policies, resource limits.
2. HTTPS reverse proxy (Caddy or nginx + Let's Encrypt), single public domain.
3. Replace the demo JWT secret and seed passwords; disable the demo accounts in production.
4. Run the backend with several workers: move the simulator runner to its own service first.
5. CI (GitHub Actions): build images, run `./scripts/test.ps1`-equivalent tests, lint.
6. Backups for PostgreSQL and MongoDB volumes.

---

## 10. Final documentation

- Architecture diagram (all components: NiFi, Python/Polars, RabbitMQ, PostgreSQL, MongoDB, Delta Lake, Airflow, DuckDB, matching engine, FastAPI, Elasticsearch, React).
- ER diagram of the database tables.
- API reference (export from `/docs`).
- Final demo script and screenshots.
- Update README and PROGRESS.md when each item above is finished.

---

## Small improvements to do along the way

- Let donors upload a CSV from the UI (the API already supports it).
- Re-run matching automatically when a new NGO need is created or an NGO accepts/declines (currently only still-unmatched donations are re-matched).
- NGO "decline" button.
- Move the WebSocket token out of the URL (use a short-lived ticket).
- Pin exact dependency versions (lock file).
- Add frontend tests (Vitest / Playwright) for the main flows.
