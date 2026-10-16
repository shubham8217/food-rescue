"""Delta Lake history: an append-only, versioned record of every donation and status change.

PostgreSQL holds the *current* state; Delta keeps *how it got there* (time travel via table versions).
All writes are best-effort: a Delta failure must never break ingestion or matching.
"""
import logging
import os
import threading
from datetime import datetime

import polars as pl

from app.config import settings
from app.utils import utcnow

log = logging.getLogger(__name__)
_lock = threading.Lock()
_buffer: list[dict] = []

DONATIONS = "donation_history"
STATUS = "status_events"


def _path(name: str) -> str:
    return os.path.join(settings.delta_dir, name)


def _append(name: str, rows: list[dict]) -> None:
    if not rows:
        return
    os.makedirs(settings.delta_dir, exist_ok=True)
    pl.DataFrame(rows).write_delta(_path(name), mode="append")


def record_donations(donations) -> None:
    """One 'created' snapshot row per donation (call after the DB commit)."""
    if not settings.delta_enabled or not donations:
        return
    try:
        rows = [{
            "donation_id": d.id, "event": "created", "ts": d.created_at or utcnow(),
            "donor": d.donor.name if getattr(d, "donor", None) else None, "food_type": d.food_type,
            "category": d.category, "quantity_kg": float(d.quantity_kg), "expiry_time": d.expiry_time,
            "area": d.area, "status": d.status, "source": d.source, "batch_id": d.batch_id or 0,
        } for d in donations]
        _append(DONATIONS, rows)
    except Exception as exc:  # noqa: BLE001
        log.warning("Delta donation history write failed: %s", exc)


def record_status(donation_id: int, from_status: str | None, to_status: str, ngo_id: int | None = None,
                  note: str = "", flush: bool = True) -> None:
    if not settings.delta_enabled:
        return
    with _lock:
        _buffer.append({"donation_id": donation_id, "from_status": from_status or "", "to_status": to_status,
                        "ts": utcnow(), "ngo_id": ngo_id or 0, "note": note})
    if flush:
        flush_status()


def flush_status() -> None:
    with _lock:
        rows, _buffer[:] = list(_buffer), []
    if not rows:
        return
    try:
        _append(STATUS, rows)
    except Exception as exc:  # noqa: BLE001
        log.warning("Delta status history write failed (%d rows dropped): %s", len(rows), exc)


def _exists(name: str) -> bool:
    return os.path.isdir(os.path.join(_path(name), "_delta_log"))


def table_versions() -> dict:
    from deltalake import DeltaTable
    out = {}
    for name in (DONATIONS, STATUS):
        out[name] = DeltaTable(_path(name)).version() if _exists(name) else None
    return out


def donation_history(donation_id: int, version: int | None = None) -> dict:
    """Timeline of one donation. `version` = time travel: read the status table as of that version."""
    result = {"donation_id": donation_id, "created": None, "timeline": [], "versions": {}}
    if not (settings.delta_enabled and (_exists(DONATIONS) or _exists(STATUS))):
        return result
    result["versions"] = table_versions()
    if _exists(DONATIONS):
        df = pl.read_delta(_path(DONATIONS)).filter(pl.col("donation_id") == donation_id)
        if df.height:
            result["created"] = _jsonable(df.sort("ts").row(0, named=True))
    if _exists(STATUS):
        sdf = pl.read_delta(_path(STATUS), version=version) if version is not None else pl.read_delta(_path(STATUS))
        sdf = sdf.filter(pl.col("donation_id") == donation_id).sort("ts")
        result["timeline"] = [_jsonable(r) for r in sdf.iter_rows(named=True)]
    return result


def _jsonable(row: dict) -> dict:
    return {k: (v.isoformat() + "Z" if isinstance(v, datetime) else v) for k, v in row.items()}


def optimize() -> dict:
    """Compact the many small files appends create, then vacuum old ones (Airflow runs this)."""
    from deltalake import DeltaTable
    out = {}
    for name in (DONATIONS, STATUS):
        if _exists(name):
            dt = DeltaTable(_path(name))
            metrics = dt.optimize.compact()
            dt.vacuum(retention_hours=0, enforce_retention_duration=False, dry_run=False)
            out[name] = {"files_added": metrics.get("numFilesAdded"), "files_removed": metrics.get("numFilesRemoved"),
                         "version": DeltaTable(_path(name)).version()}
    return out


def read_status_events(since: datetime | None = None) -> pl.DataFrame:
    if not _exists(STATUS):
        return pl.DataFrame()
    df = pl.read_delta(_path(STATUS))
    return df.filter(pl.col("ts") >= since) if since else df
