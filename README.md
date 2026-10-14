# 🍲 FoodRescue

**A platform that matches surplus food from restaurants, cafes, supermarkets and bakeries with NGOs, food banks and community kitchens in Navi Mumbai.**

Donors list surplus food, the system finds the best nearby NGOs for it, and the donation is tracked until it is delivered. It is also a data-engineering project: data is ingested, cleaned, sent as events, matched and shown live on a dashboard.

## What is done so far

- **Login and roles:** JWT login with donor, NGO and admin roles; pages and APIs are protected by role.
- **Donor page:** create a donation, see my donations, their status and the matched NGOs.
- **NGO page:** see ranked matches with score breakdown, accept, track pickup and delivery, post a need.
- **Admin live demo:** start / stop, speed 1x / 2x / 5x, counters (batches, accepted / rejected rows, matches, kg rescued, meals), live event log, rejected-rows table with reasons, map of donations.
- **Ingestion:** `POST /ingest/batch` accepts CSV or JSON; raw rows are stored in MongoDB first.
- **Cleaning (Polars):** required fields, duplicates, category standardisation, expired / unsafe food rejected with a reason.
- **Storage and events:** clean data in PostgreSQL, then a `donation.created` event is published to RabbitMQ.
- **Matching worker:** 15 km radius, expiry and food-type filters, `score = 0.4 × distance + 0.35 × urgency + 0.25 × quantity fit`, top 5 saved.
- **Simulator:** generates batches of Navi Mumbai donations and NGO needs (with ~10% dirty data), writes CSVs to `data/inbox/` and sends them to the API; simulated NGOs accept and deliver.
- **Tests:** 74 pytest tests.

```
CSV / API ─▶ MongoDB (raw) ─▶ Polars cleaning ─▶ PostgreSQL ─▶ RabbitMQ ─▶ matching worker ─▶ top-5 matches
                                  └─▶ rejected rows + reason
FastAPI (REST + WebSocket) ─▶ React dashboard
```

## What is remaining

Apache NiFi (watch `data/inbox/`), Airflow DAGs, Delta Lake history, DuckDB + Polars analytics and charts, Elasticsearch search, pipeline-health page, map polish (match lines, clustering), forecasting, deployment, final docs and diagram. Details are in [PROGRESS.md](PROGRESS.md).

## Setup and run

### 1. Install
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (with WSL2 on Windows) and [Git](https://git-scm.com/).
- Make sure ports **5173, 8000, 5433, 27017, 5672, 15672** are free.

### 2. Get the code
```powershell
git clone https://github.com/shubham8217/food-rescue.git
cd food-rescue
```

### 3. Configure
```powershell
Copy-Item .env.example .env
```

### 4. Start everything
```powershell
docker compose up -d --build
```
The first build takes a few minutes. Database tables and demo accounts are created automatically. Check that all containers are healthy:
```powershell
docker compose ps
```

### 5. Open the app

| What | URL |
|---|---|
| App | http://localhost:5173 |
| API docs | http://localhost:8000/docs |
| RabbitMQ UI | http://localhost:15672 (guest / guest) |
| PostgreSQL | localhost:5433 (foodrescue / foodrescue) |
| MongoDB | localhost:27017 |

Demo logins (password `demo123`): `donor@foodrescue.demo`, `ngo@foodrescue.demo`, `admin@foodrescue.demo`.

### 6. Try it
1. **Donor:** sign in, list a donation, watch it become *Matched*.
2. **NGO:** sign in, accept the donation, mark picked up, then delivered.
3. **Admin:** sign in, press **▶ Start Live Demo** (default: 10 minutes, one batch every 30 s). Use **Stop** and the 1x / 2x / 5x buttons to control it. New CSV files appear in `data/inbox/`.

### 7. Run the tests
```powershell
./scripts/test.ps1
```
(needs `docker compose build backend` to have been run once, which step 4 does.)

### Stop / reset
```powershell
docker compose down        # stop
docker compose down -v     # stop and delete all data
```

### Useful commands
```powershell
docker compose logs -f worker      # watch the matching worker
docker compose logs -f backend     # API logs
docker compose exec postgres psql -U foodrescue   # inspect the database
```

## Project layout

```
backend/    API, cleaning, matching, worker, migrations, tests
simulator/  demo data generator and live-demo runner
frontend/   React dashboard
data/inbox/ CSV drop folder for the simulator
```

## Tech stack

FastAPI · SQLAlchemy · Alembic · PostgreSQL · MongoDB · RabbitMQ · Polars · React · Vite · Leaflet · Docker Compose
