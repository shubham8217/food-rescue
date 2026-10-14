# FoodRescue - working notes for Claude

College data-engineering project: surplus food (restaurants, bakeries, supermarkets) -> NGOs in Navi Mumbai.
This repo holds **~50%** of the final stack. See `PROGRESS.md` for what is done / remaining.

## Stack in this repo (core profile)
FastAPI + SQLAlchemy + Alembic (backend) · PostgreSQL (clean data) · MongoDB (raw rows + event payloads) ·
RabbitMQ (`donation.created`) · matching worker · Polars (cleaning) · simulator · React + Vite + Leaflet.
NOT built yet (leave extension points only): NiFi, Airflow, Delta Lake, DuckDB analytics, Elasticsearch.

## Layout
- `backend/app/services/cleaning.py` - pure Polars cleaning (no DB). `ingest.py` - raw->Mongo, clean->Postgres, publish event.
- `backend/app/services/matching.py` - `score = 0.4*distance + 0.35*urgency + 0.25*fit`, 15 km radius, top 5.
- `backend/app/services/workflow.py` - accept match, picked_up, delivered (shared by API + simulator).
- `backend/app/worker/consumer.py` - RabbitMQ consumer + 30 s sweeper (self-heals if the broker was down).
- `simulator/` - generator (CSV + rows), `runner.py` (demo loop), `lifecycle.py` (simulated NGOs). Imported by the backend.
- `frontend/src/pages/` - Login, Donor, Ngo, Admin (live demo). `/api` is proxied to FastAPI (nginx / vite).

## Commands (Windows PowerShell)
- Stack: `docker compose up -d --build` (`.env` sets `COMPOSE_PROFILES=core`)
- Tests: `./scripts/test.ps1` (runs pytest in a container with the live source mounted; build the image once first
  with `docker compose build backend`)
- New migration: `alembic revision --autogenerate -m "msg"` inside the backend container (see README).

## Conventions / gotchas
- All datetimes are **naive UTC** in the DB; the API serialises with a trailing `Z`.
- Access the session factory as `db.SessionLocal()` (module attr) so tests can rebind it. Tests use SQLite + mongomock
  and capture RabbitMQ publishes (see `tests/conftest.py`).
- Postgres host port is **5433** (5432 is often taken locally).
- Standing needs (`Request.standing`) never deplete; sim NGOs are seeded in `app/seed.py`.
- The Postgres `FOR UPDATE` must use `with_for_update(of=Donation)` because `Donation.donor` is eager-joined.
- Do not git-bash `docker run -v /app` (path mangling): use PowerShell.
