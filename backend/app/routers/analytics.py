from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import admin_or_service
from app.models import User
from app.services import analytics, forecast as forecast_svc

router = APIRouter(tags=["analytics"])
guard = admin_or_service()


@router.get("/analytics/summary")
def summary(user: User = Depends(guard), db: Session = Depends(get_db)):
    return analytics.summary(db)


@router.get("/analytics/by-area")
def by_area(user: User = Depends(guard), db: Session = Depends(get_db)):
    return analytics.by_area(db)


@router.get("/analytics/by-category")
def by_category(user: User = Depends(guard), db: Session = Depends(get_db)):
    return analytics.by_category(db)


@router.get("/analytics/timeline")
def timeline(hours: int = Query(24, ge=1, le=24 * 14), user: User = Depends(guard), db: Session = Depends(get_db)):
    return analytics.timeline(db, hours)


@router.get("/analytics/rejections")
def rejections(user: User = Depends(guard), db: Session = Depends(get_db)):
    return analytics.rejections(db)


@router.get("/analytics/funnel")
def funnel(user: User = Depends(guard), db: Session = Depends(get_db)):
    return analytics.funnel(db)


@router.get("/analytics/top")
def top(user: User = Depends(guard), db: Session = Depends(get_db)):
    return analytics.top(db)


@router.get("/forecast")
def forecast(area: str | None = None, hours: int = Query(24, ge=1, le=72), user: User = Depends(guard),
             db: Session = Depends(get_db)):
    return forecast_svc.forecast(db, area, hours)


@router.post("/forecast/backfill")
def backfill(days: int = Query(7, ge=1, le=30), user: User = Depends(guard), db: Session = Depends(get_db)):
    """Seed synthetic history (peaks at lunch and dinner) so analytics and forecast have data to show."""
    return forecast_svc.backfill_history(db, days)
