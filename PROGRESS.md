# FoodRescue: Progress report

**Overall completion of the FULL project: ≈ 50 %**
(core pipeline + live demo + role-based UI are done; NiFi, Airflow, Delta Lake, DuckDB analytics and Elasticsearch are not started.)

## ✅ DONE

| Area | What exists | Files / endpoints |
|---|---|---|
| Repo + infra | Compose `core` profile: postgres, mongo, rabbitmq, backend, worker, frontend; healthchecks; `.env.example`; profiles `search`/`pipeline`/`all` reserved | `docker-compose.yml`, `.env.example`, `backend/Dockerfile`, `frontend/Dockerfile`, `CLAUDE.md`, `README.md` |
| Auth | JWT login, bcrypt, roles donor/ngo/admin, guards on backend (`require_roles`) and frontend (`<Protected roles>`), WS requires admin token. Seed: `donor@/ngo@/admin@foodrescue.demo` / `demo123` | `routers/auth.py`, `deps.py`, `security.py`, `seed.py`, `frontend/src/auth.jsx` |
| Data models + Alembic | User, Donor, NGO, Donation (food_type, category, quantity_kg, expiry_time, lat, lng, area, status), Request, Match, IngestBatch, RejectedRow, Event; migration `0001` runs on backend start | `models/__init__.py`, `alembic/versions/0001_initial_schema.py` |
| Status flow | listed → matched → accepted → picked_up → delivered (+ `expired` exit), transitions enforced | `services/workflow.py`, `PATCH /donations/{id}/status`, `POST /matches/{id}/accept` |
| Ingestion | `POST /ingest/batch` accepts JSON, raw CSV body, or multipart CSV/JSON file; **raw rows → MongoDB first** | `routers/ingest.py`, `services/ingest.py`, `services/mongo.py` |
| Polars cleaning | required fields, numeric/date parsing, category standardisation (aliases), unsafe-item + expired + <1 h shelf-life rejection, in-batch **and** cross-batch dedupe, coordinate imputation from area, service-area bbox; rejected rows stored with reason | `services/cleaning.py`, table `rejected_rows`, `GET /ingest/rejected` |
| Clean → Postgres → RabbitMQ | after commit, one `donation.created` per donation; payload copy in Mongo `events` | `services/events.py` |
| Matching worker | consumes queue; radius 15 km (haversine), category + expiry/travel-time filters, score = 0.4 distance + 0.35 urgency + 0.25 quantity-fit, top 5 saved; 30 s sweeper re-matches anything missed | `services/matching.py`, `worker/consumer.py` |
| Live demo simulator | admin Start/Stop, 1x/2x/5x; 10 min, batch / 30 s (20 batches); 15–40 donations + 3–8 needs per batch across 7 Navi Mumbai areas; lunch/dinner-weighted volume; ~10 % dirty rows (duplicates, expired, bad category, missing fields, unsafe); CSV to `data/inbox/` (atomic write) **and** direct `/ingest/batch`, with in-process fallback; simulated NGOs auto-accept then picked_up → delivered | `simulator/generator.py`, `runner.py`, `lifecycle.py`, `routers/demo.py` (`/demo/start|stop|speed|status|reset`) |
| Live updates | WebSocket `/ws/live` (1 s push) with automatic polling fallback `/admin/live` | `routers/demo.py`, `Admin.jsx` |
| Frontend | Login; Donor (create donation, my donations with status steps + match list); NGO (ranked matches with score breakdown, accept, pickup tracking, post a need); Admin (live demo controls, 6 counters incl. meals = kg/0.4, pipeline status counts, live event log, rejected-rows table, Leaflet donation map coloured by status) | `frontend/src/pages/*`, `components/*` |
| Tests | **74 pytest tests**: cleaning, matching score/filters, auth + role guards + WebSocket auth, ingest → Mongo → Postgres → event → worker → accept → deliver flow, simulator volume/dirty-rate/lifecycle, runner fallback + stop | `backend/tests/`, run with `./scripts/test.ps1` |
| Extension points | stub notes for NiFi / Delta / Airflow / DuckDB / Elasticsearch | `backend/app/extensions/README.md`, `SIM_DIRECT_INGEST` flag, compose comments |

### Improvement passes (what was found and fixed)
1. **Pass 1: first real end-to-end run in Docker.** Found: Postgres rejected `SELECT … FOR UPDATE` on the eager-joined donor (→ every accept failed); standing NGO needs were being "used up" after 100 kg, so ~20 % of donations stayed unmatched; pika INFO log spam; admin checkbox label layout; weak JWT default secret. Fixed all, added a regression test for standing needs. Verified a clean `docker compose down -v` → `up --build` → seed → 20-batch demo with 0 errors in logs and live-payload latency 20–65 ms.
2. **Pass 2: UI click-through of every role** (admin start/stop/live log/map/counters, donor create + match view, NGO accept → picked up → delivered, frontend role guard redirects). Added donor "Finding NGOs…" hint, server-side `quantity_kg` bounds, tests for the demo endpoints.
3. **Pass 3: chaos test.** Stopped RabbitMQ for 20 s during a 5x demo: 5 batches hit the outage, ingestion kept going (data safe in Postgres/Mongo), the sweeper matched them after the broker returned: 20/20 batches, 435 donations, 0 stuck in `listed`. Added tests for the runner fallback (HTTP down) and stop.

## ⏳ REMAINING (≈ 50 %)

| Item | How to build it |
|---|---|
| **Apache NiFi flow** | Add `nifi` service (profile `pipeline`); `ListFile/FetchFile` on `./data/inbox` → `InvokeHTTP` multipart POST to `backend:8000/ingest/batch` with an admin token; move done files to `data/archive`. Set `SIM_DIRECT_INGEST=false`. |
| **Delta Lake snapshots** | `deltalake` package; hook after commit in `services/ingest.py` and `services/workflow.py` appending donation/status rows to `data/delta/donation_history` (time travel = versions). |
| **Airflow DAGs** | `airflow` service (profile `pipeline`); DAGs: hourly Delta snapshot, analytics refresh, expire stale donations, data-quality report. Reuse functions in `services/`. |
| **DuckDB + Polars analytics + charts** | Query Delta/Postgres with DuckDB; `/analytics/*` routers (rescued kg by area/category/time, rejection reasons, match latency); charts page in React. |
| **Elasticsearch search** | `elasticsearch` service (profile `search`); index donations/NGOs from the worker; `/search` endpoint + search box. |
| Full pipeline-health page | Queue depth (RabbitMQ management API), batch throughput, reject rate over time, worker lag, per-store counts. |
| Map polish | Match lines donation → NGO, marker clustering, NGO markers, filters. |
| Forecasting | Hourly surplus forecast per area from Delta history (Polars rolling means → simple ARIMA/Prophet). |
| Deployment | Production compose, secrets, HTTPS reverse proxy, CI. |
| Final docs | Architecture diagram, demo script PDF, ER diagram. |

## 🐞 Known issues / limitations
- All state lives in one backend process for the simulator (single uvicorn worker). Running several workers would need the runner moved to its own service.
- The demo NGO account (`ngo@foodrescue.demo`) also takes part in the simulation, so the simulator may accept matches before you click on them (use a manual donation while the demo is **stopped** to show a manual accept).
- "Start Live Demo" clears previous donations/events by default (checkbox to keep them).
- WebSocket token is passed as a query parameter (fine locally; use a ticket/cookie in production).
- Matching is evaluated once per donation (plus the sweeper); a new NGO need only re-matches donations that are still `listed` with no matches.
- Donors cannot yet bulk-upload from the UI (the API supports it).
- OpenStreetMap tiles need internet access.
- Dependencies in `requirements.txt` use minimum versions, not a lock file.
- Browser-pane screenshots were flaky in this session, so UI checks used DOM reads plus a few screenshots rather than a full screenshot suite.

## ▶️ How to run
```powershell
cd C:\Users\shubh\Downloads\foodrescue
Copy-Item .env.example .env          # once
docker compose up -d --build         # first build takes a few minutes
./scripts/test.ps1                   # 74 tests (needs the backend image built once)
docker compose down                  # stop (add -v to wipe data)
```
| What | URL |
|---|---|
| App | http://localhost:5173 |
| API docs | http://localhost:8000/docs |
| RabbitMQ UI | http://localhost:15672 (guest/guest) |
| Postgres | localhost:5433 (foodrescue/foodrescue) |
| MongoDB | localhost:27017 |

Logins (password `demo123`): `donor@foodrescue.demo`, `ngo@foodrescue.demo`, `admin@foodrescue.demo`.

## 🎤 Demo script (≈ 8 min)
1. **Architecture (1 min).** Show the README diagram: simulator → CSV + API → Mongo (raw) → Polars → Postgres → RabbitMQ → matching worker → dashboard.
2. **Donor (1 min).** Sign in as donor, list "Veg biryani · 24 kg · Vashi". Within seconds the status becomes *Matched*; click the row to show the 5 ranked NGOs with distance and score.
3. **NGO (1 min).** Sign in as NGO: the donation is in *Ranked matches* with the score breakdown (distance / urgency / fit). Click **Accept**, then *Mark picked up* → *Mark delivered*.
4. **Live demo (4 min).** Sign in as admin, choose **Lunch rush**, speed 2x, press **▶ Start Live Demo**. Point out: batch counter and countdown; counters (accepted rows, rejected rows, matches, kg rescued, meals); the colour-changing pins on the Leaflet map; the event log (`ingest` → `match` → `accepted` → `picked_up` → `delivered`); the **Rejected rows** table with reasons (duplicate, expired, unknown category, unsafe, missing field). Show `data/inbox/*.csv` filling up (ready for NiFi) and RabbitMQ UI at :15672 (queue `donation.created`). Change speed to 5x live.
5. **Resilience (1 min, optional).** `docker compose stop rabbitmq` during the demo: ingestion continues (warning in the log); `docker compose start rabbitmq`: the worker sweeper catches up.
6. **Close.** Mention what comes next: NiFi, Delta Lake, Airflow, DuckDB analytics, Elasticsearch.
