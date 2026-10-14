# Extension points (not built yet)

| Future component | Where it plugs in |
|---|---|
| **Apache NiFi** | The simulator already writes atomic CSVs to `data/inbox/`. NiFi `ListFile -> FetchFile -> InvokeHTTP` posts them to `POST /ingest/batch` (multipart `file`). Set `SIM_DIRECT_INGEST=false` so NiFi becomes the only path. |
| **Delta Lake** | After the DB commit in `services/ingest.py::ingest_rows` and on status changes in `services/workflow.py`, call a `history.record(...)` hook that appends to a Delta table (`deltalake` package). |
| **Airflow** | DAGs in `pipeline/dags/` call the same service functions (`services.stats`, Delta snapshot, analytics refresh). Compose profile `pipeline`. |
| **DuckDB + Polars analytics** | Read the Delta tables / Postgres via DuckDB; expose `/analytics/*` routers next to `routers/demo.py`. |
| **Elasticsearch** | Index donations from the `donation.created` consumer (`worker/consumer.py`) and add `/search` router. Compose profile `search`. |
