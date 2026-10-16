"""FoodRescue Airflow DAGs.

Every task calls the backend's /ops endpoints with the service key, so the DAGs reuse the exact same
code paths as the API (Delta Lake maintenance, analytics snapshots, expiry, data-quality report, reindex).
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from airflow import DAG
from airflow.exceptions import AirflowSkipException
from airflow.operators.python import PythonOperator

API = os.environ.get("FR_API_URL", "http://backend:8000").rstrip("/")
KEY = os.environ.get("FR_API_KEY", "dev-ingest-key-change-me")
MAX_REJECT_RATE = 0.35  # the simulator injects ~10 % dirty rows; far above that means a broken source

DEFAULT_ARGS = {"owner": "foodrescue", "retries": 2, "retry_delay": timedelta(seconds=30)}


def call(method: str, path: str) -> dict:
    req = urllib.request.Request(API + path, method=method, headers={"X-API-Key": KEY})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {exc.read()[:200]!r}") from exc


def task(name: str, fn, **kw) -> PythonOperator:
    return PythonOperator(task_id=name, python_callable=fn, **kw)


def health_check():
    h = call("GET", "/health/pipeline")
    print("alerts:", h["alerts"])
    if not (h["services"]["postgres"]["ok"] and h["services"]["mongo"]["ok"]):
        raise RuntimeError("PostgreSQL or MongoDB is down")


def expire():
    print(call("POST", "/ops/expire"))


def optimize_delta():
    print(call("POST", "/ops/delta/optimize"))


def snapshot():
    print(call("POST", "/ops/analytics/snapshot"))


def quality_report():
    rep = call("POST", "/ops/quality-report")
    print(rep)
    if rep["rows"] >= 100 and rep["reject_rate"] > MAX_REJECT_RATE:
        raise RuntimeError(f"Reject rate {rep['reject_rate']:.0%} is above {MAX_REJECT_RATE:.0%}: check the source")


def reindex():
    try:
        print(call("POST", "/search/reindex"))
    except RuntimeError as exc:
        if "503" in str(exc):
            raise AirflowSkipException("Search is not enabled") from exc
        raise


COMMON = dict(default_args=DEFAULT_ARGS, start_date=datetime(2026, 1, 1), catchup=False, max_active_runs=1,
              tags=["foodrescue"])

with DAG("foodrescue_expire_stale", schedule="*/10 * * * *",
         description="Mark donations whose food has expired", **COMMON):
    task("expire_stale_donations", expire)

with DAG("foodrescue_analytics_refresh", schedule="*/15 * * * *",
         description="Store a DuckDB analytics snapshot", **COMMON):
    task("health_check", health_check) >> task("analytics_snapshot", snapshot)

with DAG("foodrescue_delta_snapshot", schedule="@hourly",
         description="Compact the Delta Lake history tables", **COMMON):
    task("delta_optimize", optimize_delta)

with DAG("foodrescue_data_quality", schedule="@daily",
         description="Daily reject / duplicate rates; fails when the source looks broken", **COMMON):
    task("health_check", health_check) >> task("quality_report", quality_report) >> task("search_reindex", reindex)
