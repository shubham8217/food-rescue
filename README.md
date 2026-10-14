# 🍲 FoodRescue - Navi Mumbai

Matches surplus food from restaurants, cafes, supermarkets and bakeries with NGOs, food banks and
community kitchens. A data-engineering project: ingest → clean → events → match → live dashboard.

> This repository contains the first ~50% of the final stack. See [PROGRESS.md](PROGRESS.md).

## Architecture (built part)

```
simulator ──CSV──▶ data/inbox/          (ready for NiFi later)
    └────HTTP───▶ POST /ingest/batch ─▶ MongoDB (raw rows)
                                      ─▶ Polars cleaning ─▶ PostgreSQL (clean) + rejected_rows (reason)
                                      ─▶ RabbitMQ "donation.created" ─▶ matching worker ─▶ matches (top 5)
FastAPI (REST + WebSocket) ◀──▶ React dashboard (donor / NGO / admin live demo)
```

## Run it

Prerequisites: Docker Desktop (WSL2). PowerShell:

```powershell
Copy-Item .env.example .env        # once (sets COMPOSE_PROFILES=core)
docker compose up -d --build
```

| What | URL |
|---|---|
| App | http://localhost:5173 |
| API docs (Swagger) | http://localhost:8000/docs |
| RabbitMQ UI | http://localhost:15672 (guest / guest) |
| PostgreSQL | `localhost:5433` (foodrescue / foodrescue) |
| MongoDB | `localhost:27017` db `foodrescue` |

Demo logins (password `demo123`): `donor@foodrescue.demo`, `ngo@foodrescue.demo`, `admin@foodrescue.demo`.
Database migrations run automatically on backend start; demo accounts and NGOs are seeded.

Compose profiles: `core` (this build), `search`, `pipeline`, `all` (reserved for the next phase).
`.env` sets `COMPOSE_PROFILES=core`, so a plain `docker compose up` works; or use `docker compose --profile core up`.

## Live demo

Sign in as admin → **▶ Start Live Demo**. Defaults: 10 minutes, one batch every 30 s (20 batches), 15–40 donations
and 3–8 NGO needs per batch, ~10% dirty rows. Speed 1x / 2x / 5x; **Stop** any time.
Batches are written to `data/inbox/*.csv` and also POSTed to `/ingest/batch`; if the HTTP call fails the runner
falls back to in-process ingestion so the demo never stops.

## Tests

```powershell
docker compose build backend      # once, installs dependencies
./scripts/test.ps1                # pytest: cleaning, matching, auth, ingest → match flow, simulator
```

## Useful commands

```powershell
docker compose logs -f worker                         # watch matching
docker compose exec postgres psql -U foodrescue       # inspect data
docker compose down -v                                # wipe everything incl. volumes
# new migration after changing models:
docker compose run --rm backend alembic revision --autogenerate -m "describe change"
```

## Repo layout

```
backend/    FastAPI app, services (cleaning, ingest, matching, workflow), worker, Alembic, tests
simulator/  batch generator, demo runner, simulated-NGO lifecycle
frontend/   React + Vite (Leaflet map), served by nginx in Docker
data/inbox/ CSV drop folder (NiFi will watch this)
```
