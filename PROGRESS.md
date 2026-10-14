# FoodRescue: Progress

## ✅ Done

| Feature | Details |
|---|---|
| Docker setup | `core` profile: postgres, mongo, rabbitmq, backend, worker, frontend (`docker-compose.yml`) |
| Auth | JWT login, bcrypt, roles donor / ngo / admin, role guards on backend and frontend. Seed users: `donor@`, `ngo@`, `admin@foodrescue.demo` (password `demo123`) |
| Data models | User, Donor, NGO, Donation, Request, Match, IngestBatch, RejectedRow (Alembic migration) |
| Donation status flow | listed → matched → accepted → picked_up → delivered |
| Ingestion | `POST /ingest/batch` (CSV / JSON / file upload); raw rows saved to MongoDB first |
| Polars cleaning | required-field check, dedupe, category standardisation, expired / unsafe rejection; rejected rows stored with reason |
| Events | clean data saved to PostgreSQL, then `donation.created` published to RabbitMQ |
| Matching worker | 15 km haversine radius, expiry and food-type filters, score = 0.4 distance + 0.35 urgency + 0.25 quantity fit, top 5 saved |
| Live demo simulator | admin start / stop, 1x / 2x / 5x; 20 batches (one per 30 s); 15–40 donations and 3–8 NGO needs per batch; ~10% dirty data; CSVs written to `data/inbox/` and sent to `/ingest/batch` (with fallback); simulated NGOs accept and deliver |
| Frontend | Login; Donor (create donation, my donations); NGO (ranked matches, accept, pickup tracking, post need); Admin (live demo controls, counters, event log, rejected rows, Leaflet map); live updates via WebSocket with polling fallback |
| Tests | 74 pytest tests: cleaning, matching, auth, ingest → match flow, simulator |

## ⏳ Remaining

| Item | How to build |
|---|---|
| Apache NiFi | Watch `data/inbox/`, POST each CSV to `/ingest/batch`; set `SIM_DIRECT_INGEST=false` |
| Delta Lake | Append donation / status history after each commit in `services/ingest.py` and `services/workflow.py` |
| Airflow | DAGs for snapshots, analytics refresh, stale-donation expiry |
| DuckDB + Polars analytics | Query Delta / Postgres; add `/analytics/*` endpoints and charts page |
| Elasticsearch | Index donations / NGOs from the worker; add `/search` endpoint |
| Pipeline-health page | Queue depth, batch throughput, reject rate, worker lag |
| Map polish | Match lines, marker clustering |
| Forecasting | Surplus forecast per area from history |
| Deployment, final docs, diagram, demo script | Production compose, HTTPS, architecture diagram |

## 🐞 Known limitations
- Simulator runs inside one backend process (single uvicorn worker).
- The demo NGO account takes part in the simulation; for a manual accept, create the donation while the demo is stopped.
- Start Live Demo clears previous data unless the checkbox is unticked.
- Map tiles need internet access.

## 🎤 Demo steps
1. Donor: list a donation, see it become *Matched* and open the 5 ranked NGOs.
2. NGO: accept it, mark picked up, mark delivered.
3. Admin: pick **Lunch rush**, press **▶ Start Live Demo**; show counters, map, event log, rejected rows, and `data/inbox/*.csv`.
4. Open RabbitMQ UI (http://localhost:15672) to show the `donation.created` queue.
