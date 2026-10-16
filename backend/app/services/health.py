"""Pipeline health: is every stage alive, and is data flowing through it?"""
from datetime import timedelta

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import QUEUE_DONATION_CREATED, S_LISTED
from app.models import Donation, IngestBatch, RejectedRow
from app.services import history, mongo, search
from app.utils import utcnow

TIMEOUT = 2.0


def _svc(ok: bool | None, detail: str = "", **extra) -> dict:
    return {"ok": ok, "detail": detail, **extra}  # ok=None means "not enabled"


def check_postgres(db: Session) -> dict:
    try:
        db.execute(text("select 1"))
        return _svc(True, "connected", donations=db.scalar(select(func.count(Donation.id))) or 0,
                    rejected_rows=db.scalar(select(func.count(RejectedRow.id))) or 0)
    except Exception as exc:  # noqa: BLE001
        return _svc(False, str(exc)[:120])


def check_mongo() -> dict:
    try:
        mdb = mongo.get_mongo()
        return _svc(True, "connected", raw_rows=mdb.raw_ingest.estimated_document_count(),
                    events=mdb.events.estimated_document_count())
    except Exception as exc:  # noqa: BLE001
        return _svc(False, str(exc)[:120])


def check_rabbitmq() -> dict:
    try:
        r = httpx.get(f"{settings.rabbitmq_api_url}/api/queues/%2F/{QUEUE_DONATION_CREATED}",
                      auth=(settings.rabbitmq_api_user, settings.rabbitmq_api_password), timeout=TIMEOUT)
        r.raise_for_status()
        q = r.json()
        stats = q.get("message_stats", {})
        return _svc(True, "connected", queue_depth=q.get("messages", 0), consumers=q.get("consumers", 0),
                    published=stats.get("publish", 0), delivered=stats.get("deliver_get", 0))
    except Exception as exc:  # noqa: BLE001
        return _svc(False, f"management API unreachable: {type(exc).__name__}", queue_depth=None, consumers=0)


def _http_ok(url: str, path: str) -> dict:
    if not url:
        return _svc(None, "not enabled")
    try:
        r = httpx.get(url.rstrip("/") + path, timeout=TIMEOUT)
        return _svc(r.status_code < 500, f"HTTP {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        return _svc(False, f"unreachable: {type(exc).__name__}")


def pipeline_health(db: Session) -> dict:
    now = utcnow()
    rmq = check_rabbitmq()
    oldest = db.scalar(select(func.min(Donation.created_at)).where(Donation.status == S_LISTED,
                                                                   Donation.expiry_time > now,
                                                                   Donation.source != "history"))
    lag = round((now - oldest).total_seconds()) if oldest else 0
    five = now - timedelta(minutes=5)
    rows_5, batches_5 = db.execute(select(func.coalesce(func.sum(IngestBatch.total_rows), 0), func.count(IngestBatch.id))
                                   .where(IngestBatch.created_at >= five)).one()
    last = db.scalar(select(func.max(IngestBatch.created_at)))
    hour = now - timedelta(hours=1)
    tot_h, rej_h = db.execute(select(func.coalesce(func.sum(IngestBatch.total_rows), 0),
                                     func.coalesce(func.sum(IngestBatch.rejected_rows), 0))
                              .where(IngestBatch.created_at >= hour)).one()
    per_min: dict[str, int] = {}
    for ts, n in db.execute(select(IngestBatch.created_at, IngestBatch.total_rows)
                            .where(IngestBatch.created_at >= now - timedelta(minutes=15))).all():
        key = ts.replace(second=0, microsecond=0).isoformat() + "Z"
        per_min[key] = per_min.get(key, 0) + n
    throughput = []
    t = (now - timedelta(minutes=14)).replace(second=0, microsecond=0)
    while t <= now:
        k = t.isoformat() + "Z"
        throughput.append({"ts": k, "rows": per_min.get(k, 0)})
        t += timedelta(minutes=1)

    services = {
        "postgres": check_postgres(db), "mongo": check_mongo(), "rabbitmq": rmq,
        "worker": _svc(rmq.get("consumers", 0) > 0 if rmq["ok"] else None,
                       f"{rmq.get('consumers', 0)} consumer(s) on the queue" if rmq["ok"] else "unknown (no broker info)",
                       lag_seconds=lag),
        "elasticsearch": _svc(search.ping(), "reachable") if search.enabled() else _svc(None, "not enabled"),
        "nifi": _http_ok(settings.nifi_url, "/nifi-api/flow/about"),
        "airflow": _http_ok(settings.airflow_url, "/health"),
    }
    try:
        services["delta"] = _svc(True, "versions", versions=history.table_versions()) if settings.delta_enabled \
            else _svc(None, "disabled")
    except Exception as exc:  # noqa: BLE001
        services["delta"] = _svc(False, str(exc)[:120])

    alerts = []
    if rmq["ok"] and rmq.get("queue_depth", 0) > 200:
        alerts.append(f"RabbitMQ queue is backing up ({rmq['queue_depth']} messages)")
    if lag > 120:
        alerts.append(f"Oldest unmatched donation has waited {lag}s")
    for name, s in services.items():
        if s["ok"] is False:
            alerts.append(f"{name} is down: {s['detail']}")
    return {
        "services": services,
        "pipeline": {
            "rows_last_5min": int(rows_5), "batches_last_5min": int(batches_5),
            "last_batch_age_s": round((now - last).total_seconds()) if last else None,
            "reject_rate_1h": round(rej_h / tot_h, 3) if tot_h else 0.0, "oldest_unmatched_age_s": lag,
        },
        "throughput": throughput, "alerts": alerts, "ts": now.isoformat() + "Z",
    }
