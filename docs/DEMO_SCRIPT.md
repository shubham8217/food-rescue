# Demo script (about 10 minutes)

Start the full stack first (`./scripts/up-all.ps1`) and wait until `docker compose ps` shows everything healthy.
Open these tabs: the app (http://localhost:5173), NiFi (:8080/nifi), Airflow (:8081), RabbitMQ (:15672).

## 1. The idea (1 min)
Show `docs/architecture.png`. Say: *surplus food is wasted while NGOs nearby need it; the hard part is getting messy
data in, cleaning it and matching the right food to the right NGO before it expires.*

## 2. Donor (1 min)
Sign in as **donor@foodrescue.demo** / `demo123`. List "Veg biryani · 24 kg · Vashi". It becomes **Matched** within
a few seconds. Click the row to show the 5 ranked NGOs. Try an invalid one ("Stale bread") to show the rejection reason.

## 3. NGO (1.5 min)
Sign in as **ngo@foodrescue.demo**. Open the match: distance / urgency / fit scores. **Accept**, then *Mark picked up*
and *Mark delivered*. Show **Decline** on another match, and the **Search** box ("biryani", filter by area / kg).

## 4. Live demo (3 min)
Sign in as **admin@foodrescue.demo**, open **Live demo**, pick **Lunch rush**, speed **2x**, press **Start Live Demo**.
Point out:
* the **counters** (batches, accepted / rejected rows, matches, kg rescued, meals = kg ÷ 0.4)
* the **map**: clusters, match lines from accepted donations to NGOs, NGO squares, status filters and a 15 km radius
  when a pin is clicked
* the **event log** (ingest → match → accepted → picked_up → delivered)
* the **rejected rows** table with reasons (duplicate, expired, unknown category, unsafe, missing field)
* `data/inbox/*.csv` filling up, then **NiFi** moving each file to `data/archive/` (open the NiFi canvas)
* **RabbitMQ**: queue `donation.created` with a consumer; change speed to 5x live

## 5. Analytics, history and search (2 min)
**Analytics** → *Seed 7 days of history*: timeline, funnel, kg by area / category, rejection reasons, top donors / NGOs,
and the **24 h surplus forecast** with the lunch and dinner peaks. In Swagger (`/docs`) call
`GET /history/donations/{id}` to show the Delta Lake timeline and `?version=N` for time travel.

## 6. Orchestration and health (1.5 min)
**Airflow**: show the four DAGs (expire stale, analytics refresh, Delta compaction, data quality) and trigger one.
**Pipeline health**: every stage green, queue depth, throughput, reject rate.
Optional resilience: `docker compose stop rabbitmq` during the demo (the page turns red and ingestion keeps going),
then `docker compose start rabbitmq`: the worker sweeper catches up.

## Closing line
*Every tool has one job: NiFi ingests files, Polars cleans, MongoDB keeps the raw rows, PostgreSQL holds the current
state, RabbitMQ decouples matching, Delta Lake keeps history, Airflow schedules maintenance, DuckDB answers analytical
questions, Elasticsearch searches, and FastAPI + React present it.*
