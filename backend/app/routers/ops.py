"""Operational endpoints called by Airflow DAGs (admin JWT or X-API-Key)."""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.constants import S_LISTED, S_MATCHED
from app.db import get_db
from app.deps import admin_or_service
from app.models import AnalyticsSnapshot, Donation, IngestBatch, QualityReport, User
from app.services import analytics, history, search
from app.utils import utcnow

router = APIRouter(prefix="/ops", tags=["ops"])
guard = admin_or_service()


@router.post("/delta/optimize")
def delta_optimize(user: User = Depends(guard)):
    """Compact the small Delta files that appends create; vacuum old versions."""
    return history.optimize()


@router.post("/expire")
def expire_stale(user: User = Depends(guard), db: Session = Depends(get_db)):
    now = utcnow()
    stale = db.execute(select(Donation.id, Donation.status).where(
        Donation.status.in_([S_LISTED, S_MATCHED]), Donation.expiry_time <= now)).all()
    if stale:
        db.execute(update(Donation).where(Donation.id.in_([i for i, _ in stale]))
                   .values(status="expired", status_changed_at=now))
        db.commit()
        for did, old in stale:
            history.record_status(did, old, "expired", note="airflow expiry", flush=False)
            search.update_status(did, "expired")
        history.flush_status()
    return {"expired": len(stale)}


@router.post("/analytics/snapshot")
def analytics_snapshot(user: User = Depends(guard), db: Session = Depends(get_db)):
    data = analytics.summary(db)
    snap = AnalyticsSnapshot(kind="summary", data=data)
    db.add(snap)
    db.commit()
    return {"snapshot_id": snap.id, "data": data}


@router.post("/quality-report")
def quality_report(user: User = Depends(guard), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=1)
    tot, acc_d, acc_r, rej = db.execute(select(
        func.coalesce(func.sum(IngestBatch.total_rows), 0), func.coalesce(func.sum(IngestBatch.accepted_donations), 0),
        func.coalesce(func.sum(IngestBatch.accepted_requests), 0), func.coalesce(func.sum(IngestBatch.rejected_rows), 0)
    ).where(IngestBatch.created_at >= since)).one()
    reasons = analytics.rejections(db)
    dup = sum(r["count"] for r in reasons if r["reason"].startswith("duplicate"))
    report = {"window_hours": 24, "rows": int(tot), "accepted": int(acc_d + acc_r), "rejected": int(rej),
              "reject_rate": round(rej / tot, 3) if tot else 0.0, "duplicate_rows": dup,
              "duplicate_rate": round(dup / tot, 3) if tot else 0.0, "top_reasons": reasons[:5]}
    row = QualityReport(data=report)
    db.add(row)
    db.commit()
    return {"report_id": row.id, **report}
