# 🍲 FoodRescue

**A platform that matches surplus food from restaurants, cafes, supermarkets and bakeries with NGOs, food banks and community kitchens in Navi Mumbai.**

Donors list surplus food, the system finds the best nearby NGOs for it, and the donation is tracked until it is delivered. It is also a data-engineering project: files are ingested, cleaned, streamed as events, matched, versioned, analysed and searched, and everything is visible on a live dashboard.

![Architecture](docs/architecture.png)

Screenshots are in [docs/screenshots](docs/screenshots). Deeper docs: [architecture](docs/architecture.md) · [database model](docs/er-diagram.md) · [demo script](docs/DEMO_SCRIPT.md) · [progress](PROGRESS.md).

## What it does

- **Donors** list surplus food (or upload a CSV) and follow its status: listed → matched → accepted → picked up → delivered.
- **NGOs** see ranked matches with a score breakdown, accept or decline them, track pickup and delivery, post needs, and search donations.
- **Admins** run a live demo, and have an analytics page (charts, funnel, forecast, search) and a pipeline-health page.

### How matching works
For each new donation, the worker keeps NGO needs within **15 km** that accept that food type and can be reached before the food expires, then scores them:

`score = 0.4 × distance + 0.35 × urgency + 0.25 × quantity fit`

The top 5 matches are saved. Bad data (duplicates, expired or unsafe food, unknown categories, missing fields) is rejected with a clear reason instead of being silently dropped.

## Tools and why they are used

| Tool | Used for |
|---|---|
| **Apache NiFi** | Watches `data/inbox/`, POSTs each CSV to the API, archives it, routes failures to `data/nifi-failed/` |
| **Python + Polars** | Cleaning: required fields, dedupe, category standardisation, expired / unsafe rejection |
| **MongoDB** | Every raw row is stored untouched before cleaning, plus event payloads |
| **PostgreSQL** | Current state: donations, requests, matches, rejected rows (Alembic migrations) |
| **RabbitMQ** | `donation.created` events; the matching worker consumes them, with a sweeper that self-heals |
| **Delta Lake** | Versioned history of every donation and status change, with time travel |
| **Apache Airflow** | DAGs: expire stale donations, Delta compaction, analytics snapshots, data-quality report |
| **DuckDB + Polars** | SQL analytics (summary, by area / category, timeline, funnel, rejections, top donors / NGOs) and the surplus forecast |
| **Elasticsearch** | Full-text, filter and distance search over donations and NGOs |
| **FastAPI** | REST + WebSocket API, JWT auth with donor / NGO / admin roles |
| **React + Vite + Leaflet** | Role-based UI, live dashboard, clustered map with match lines |
| **Docker Compose** | One command; profiles `core`, `pipeline`, `search`, `all` |

## Setup and run

### 1. Install
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (WSL2 on Windows) and [Git](https://git-scm.com/).
- Free ports: **5173, 8000, 5433, 27017, 5672, 15672** (core) and **8080, 8081, 9200** (full stack).
- Memory: give Docker at least **6 GB** for the core stack and **8 GB** for everything, and keep about **10 GB** of free disk (the NiFi, Airflow and Elasticsearch images are large).

### 2. Get the code
```powershell
git clone https://github.com/shubham8217/food-rescue.git
cd food-rescue
```

### 3. Configure
```powershell
Copy-Item .env.example .env
```

### 4. Start the core stack
```powershell
docker compose up -d --build
docker compose ps
```
Tables are migrated and demo accounts are created automatically.

### 5. Start everything (NiFi, Airflow, Elasticsearch)
```powershell
./scripts/up-all.ps1
```
This sets the service URLs, switches the simulator to NiFi-only ingestion and starts all profiles.
You can also start one group: `docker compose --profile pipeline up -d` (NiFi + Airflow) or `docker compose --profile search up -d` (Elasticsearch; set `ELASTICSEARCH_URL=http://elasticsearch:9200` in `.env`).

### 6. Open the app

| What | URL | Login |
|---|---|---|
| App | http://localhost:5173 | demo accounts below |
| API docs (Swagger) | http://localhost:8000/docs | use *Authorize* with a demo account |
| RabbitMQ | http://localhost:15672 | guest / guest |
| NiFi (full stack) | http://localhost:8080/nifi | none (local demo) |
| Airflow (full stack) | http://localhost:8081 | admin / foodrescue123 |
| Elasticsearch (full stack) | http://localhost:9200 | none |
| PostgreSQL | localhost:5433 | foodrescue / foodrescue |
| MongoDB | localhost:27017 | none |

Demo logins (password `demo123`): `donor@foodrescue.demo`, `ngo@foodrescue.demo`, `admin@foodrescue.demo`.

### 7. Try it
1. **Donor:** list a donation (or upload a CSV) and watch it become *Matched*.
2. **NGO:** accept (or decline) it, mark picked up, then delivered. Try the search box (needs Elasticsearch).
3. **Admin → Live demo:** press **▶ Start Live Demo** (10 minutes, one batch every 30 s). Use 1x / 2x / 5x, filters and the clustered map.
4. **Admin → Analytics:** press **Seed 7 days of history** to fill the charts and the forecast.
5. **Admin → Pipeline health:** every stage, queue depth, throughput and alerts.

### 8. Run the tests
```powershell
docker compose build backend      # once
./scripts/test.ps1                # backend tests (about 120)
```
The frontend is checked by `npm run build` (also run in CI), see `.github/workflows/ci.yml`.

### Stop / reset
```powershell
docker compose --profile all down        # stop
docker compose --profile all down -v     # stop and delete all data
```

## Production-style deployment
```powershell
Copy-Item .env.prod.example .env.prod     # fill in every value
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```
HTTPS through Caddy, no database ports on the host, mandatory secrets, resource limits, no demo accounts and the simulator disabled (`APP_ENV=production` refuses weak JWT secrets). Backups: `./scripts/backup.ps1` (or `backup.sh`).

## Useful commands
```powershell
docker compose logs -f worker             # watch the matching worker
docker compose exec postgres psql -U foodrescue
docker compose exec backend ls /data/delta        # Delta Lake tables
```

## Project layout
```
backend/    API, cleaning, matching, history, analytics, search, worker, migrations, tests
simulator/  data generator, live-demo runner, simulated-NGO lifecycle
frontend/   React dashboard
nifi/       script that builds the NiFi flow through its REST API
airflow/    DAGs
deploy/     Caddyfile for the production stack
docs/       architecture, ER diagram, demo script, screenshots
data/inbox/ CSV drop folder
```
