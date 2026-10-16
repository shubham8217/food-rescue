"""Ingestion pipeline: raw -> MongoDB, clean (Polars) -> PostgreSQL, rejected -> RejectedRow,
then publish 'donation.created' to RabbitMQ."""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NGO, Donation, Donor, IngestBatch, RejectedRow, Request
from app.services import events, history, mongo, search
from app.services.cleaning import clean_records
from app.utils import utcnow

log = logging.getLogger(__name__)

REQUEST_TYPES = {"request", "need", "ngo_request"}
DONATION_TYPES = {"donation", "surplus", ""}


def _split_rows(rows: list[dict]):
    donations, requests, rejected = [], [], []
    for i, row in enumerate(rows, start=1):
        rtype = str(row.get("record_type") or "donation").strip().lower()
        if rtype in DONATION_TYPES:
            donations.append((i, row))
        elif rtype in REQUEST_TYPES:
            requests.append((i, row))
        else:
            rejected.append({"row_number": i, "raw": row, "reason": f"unknown record_type: '{rtype}'",
                             "record_type": "unknown"})
    return donations, requests, rejected


def _get_or_create_donor(db: Session, cache: dict, name: str, area, lat, lng) -> Donor:
    if name not in cache:
        donor = db.scalar(select(Donor).where(Donor.name == name))
        if donor is None:
            donor = Donor(name=name, area=area, lat=lat, lng=lng)
            db.add(donor)
            db.flush()
        cache[name] = donor
    return cache[name]


def _get_or_create_ngo(db: Session, cache: dict, name: str, area, lat, lng) -> NGO:
    if name not in cache:
        ngo = db.scalar(select(NGO).where(NGO.name == name))
        if ngo is None:
            ngo = NGO(name=name, area=area, lat=lat, lng=lng)
            db.add(ngo)
            db.flush()
        cache[name] = ngo
    return cache[name]


def ingest_rows(db: Session, rows: list[dict], *, source: str, filename: str | None = None,
                donor_override: Donor | None = None, allow_requests: bool = True,
                now: datetime | None = None) -> dict:
    now = now or utcnow()
    batch = IngestBatch(source=source, filename=filename, total_rows=len(rows))
    db.add(batch)
    db.flush()

    # 1) RAW first: every incoming row is stored untouched in MongoDB.
    try:
        mdb = mongo.get_mongo()
        if rows:
            res = mdb.raw_ingest.insert_many([
                {"batch_id": batch.id, "row_number": i, "source": source, "filename": filename,
                 "received_at": now, "raw": r} for i, r in enumerate(rows, start=1)])
            batch.mongo_ref = f"raw_ingest:{batch.id}:{len(res.inserted_ids)}"
    except Exception as exc:  # Mongo down must not stop the demo
        log.warning("MongoDB raw write failed: %s", exc)
        events.log_event(db, "warning", f"MongoDB raw write failed for batch {batch.id}: {exc}", commit=False)

    # 2) CLEAN with Polars
    don_in, req_in, rejected = _split_rows(rows)
    if not allow_requests and req_in:
        rejected += [{"row_number": i, "raw": r, "reason": "request rows not allowed for this account",
                      "record_type": "request"} for i, r in req_in]
        req_in = []

    don_res = clean_records([r for _, r in don_in], "donation", now, [i for i, _ in don_in])
    # cross-batch dedupe: drop rows whose key already exists in PostgreSQL
    keys = [r["dedupe_key"] for r in don_res.clean]
    seen = set(db.scalars(select(Donation.dedupe_key).where(Donation.dedupe_key.in_(keys)))) if keys else set()
    if seen:
        raw_by_row = dict(don_in)
        kept = []
        for r in don_res.clean:
            if r["dedupe_key"] in seen:
                don_res.rejected.append({"row_number": r["row_number"], "raw": raw_by_row[r["row_number"]],
                                         "reason": "duplicate of an existing record"})
            else:
                kept.append(r)
        don_res.clean = kept
    req_res = clean_records([r for _, r in req_in], "request", now, [i for i, _ in req_in])
    rejected += [{**x, "record_type": "donation"} for x in don_res.rejected]
    rejected += [{**x, "record_type": "request"} for x in req_res.rejected]

    # 3) CLEAN -> PostgreSQL (requests first so matching sees this batch's needs)
    ngo_cache: dict = {}
    for r in req_res.clean:
        ngo = _get_or_create_ngo(db, ngo_cache, r["org_name"], r["area"], r["lat"], r["lng"])
        db.add(Request(ngo_id=ngo.id, category=r["category"], quantity_kg=r["quantity_kg"], needed_by=r["expiry_time"],
                       source=source, batch_id=batch.id, dedupe_key=r["dedupe_key"]))
    donor_cache: dict = {}
    donations: list[Donation] = []
    for r in don_res.clean:
        donor = donor_override or _get_or_create_donor(db, donor_cache, r["org_name"], r["area"], r["lat"], r["lng"])
        d = Donation(donor_id=donor.id, food_type=r["food_type"], category=r["category"], quantity_kg=r["quantity_kg"],
                     expiry_time=r["expiry_time"], lat=r["lat"], lng=r["lng"], area=r["area"], source=source,
                     batch_id=batch.id, dedupe_key=r["dedupe_key"], created_at=now, status_changed_at=now)
        db.add(d)
        donations.append(d)
    for rej in sorted(rejected, key=lambda x: x["row_number"]):
        db.add(RejectedRow(batch_id=batch.id, row_number=rej["row_number"], record_type=rej["record_type"],
                           raw=rej["raw"], reason=rej["reason"]))
    batch.accepted_donations = len(don_res.clean)
    batch.accepted_requests = len(req_res.clean)
    batch.rejected_rows = len(rejected)
    db.flush()
    summary = {
        "batch_id": batch.id, "source": source, "total_rows": len(rows),
        "accepted_donations": batch.accepted_donations, "accepted_requests": batch.accepted_requests,
        "rejected_rows": batch.rejected_rows, "donation_ids": [d.id for d in donations],
        "rejected": [{"row_number": x["row_number"], "reason": x["reason"]} for x in rejected][:20],
    }
    events.log_event(
        db, "ingest",
        f"Batch #{batch.id} [{source}]: {len(rows)} rows -> {batch.accepted_donations} donations, "
        f"{batch.accepted_requests} requests accepted, {batch.rejected_rows} rejected", summary, commit=False)
    db.commit()

    # 4) EVENT: donation.created -> RabbitMQ (+ payload copy in MongoDB)
    msgs = [{"event": "donation.created", "donation_id": d.id, "category": d.category, "quantity_kg": d.quantity_kg,
             "area": d.area, "batch_id": batch.id, "ts": now.isoformat()} for d in donations]
    try:
        events.publish_donation_created(msgs)
    except Exception as exc:
        log.warning("RabbitMQ publish failed: %s", exc)
        events.log_event(db, "warning", f"RabbitMQ publish failed ({exc}); worker sweeper will pick these up")
        summary["publish_failed"] = True
    history.record_donations(donations)  # Delta Lake (best effort)
    search.index_donations(donations)  # Elasticsearch (best effort)
    try:
        if msgs:
            mongo.get_mongo().events.insert_many([dict(m) for m in msgs])
    except Exception as exc:
        log.warning("MongoDB event payload write failed: %s", exc)
    return summary
