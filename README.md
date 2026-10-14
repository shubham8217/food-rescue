# 🍲 FoodRescue

**A platform that matches surplus food from restaurants, cafes, supermarkets and bakeries with NGOs, food banks and community kitchens in Navi Mumbai.**

Every day, good food is thrown away while people nearby go hungry. FoodRescue lets donors list surplus food, automatically finds the best nearby NGOs for it, and tracks the donation until it is delivered. It is also a data-engineering project: data is ingested, cleaned, streamed as events, matched and shown live on a dashboard.

> Status: about half of the planned stack is built (see [PROGRESS.md](PROGRESS.md) for what is done and what comes next).

## What it does

- **Donors** list surplus food (type, quantity, expiry, area) and follow its status: listed → matched → accepted → picked up → delivered.
- **NGOs** see a ranked list of nearby donations, accept them, and track pickup. They can also post what they need.
- **Admins** run a live demo: simulated restaurants and NGOs generate batches of data, and the dashboard shows counters (kg rescued, meals), a live event log, rejected rows with reasons, and a map of donations.

### How matching works
For each new donation, the worker keeps NGOs within **15 km** that need that food type and can reach it before it expires, then scores them:

`score = 0.4 × distance + 0.35 × urgency + 0.25 × quantity fit`

The top 5 matches are saved for the donor and NGOs to see.

### Data pipeline
```
CSV / API ─▶ MongoDB (raw rows) ─▶ Polars cleaning ─▶ PostgreSQL (clean data)
                                        └─▶ rejected rows + reason
PostgreSQL ─▶ RabbitMQ "donation.created" ─▶ matching worker ─▶ top-5 matches
FastAPI (REST + WebSocket) ─▶ React dashboard (donor / NGO / admin)
```
Dirty data (duplicates, expired or unsafe food, unknown categories, missing fields) is rejected with a clear reason instead of being silently dropped.

## Tech stack

FastAPI · SQLAlchemy · Alembic · PostgreSQL · MongoDB · RabbitMQ · Polars · React · Vite · Leaflet · Docker Compose.
Planned next: Apache NiFi, Airflow, Delta Lake, DuckDB, Elasticsearch.

## Run it

Needs Docker Desktop. In PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

| What | URL |
|---|---|
| App | http://localhost:5173 |
| API docs | http://localhost:8000/docs |
| RabbitMQ UI | http://localhost:15672 (guest / guest) |

Demo logins (password `demo123`): `donor@foodrescue.demo`, `ngo@foodrescue.demo`, `admin@foodrescue.demo`.

**Try the live demo:** sign in as admin and press **▶ Start Live Demo**.

## Tests

```powershell
./scripts/test.ps1
```

## Project layout

```
backend/    API, cleaning, matching, worker, migrations, tests
simulator/  demo data generator and live-demo runner
frontend/   React dashboard
data/inbox/ CSV drop folder for the simulator
```
