from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import settings
from app.deps import admin_or_service
from app.models import User
from app.services import history

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/versions")
def versions(user: User = Depends(admin_or_service())):
    return history.table_versions() if settings.delta_enabled else {}


@router.get("/donations/{donation_id}")
def donation_history(donation_id: int, version: int | None = Query(None, ge=0, description="time travel"),
                     user: User = Depends(admin_or_service())):
    """Full status timeline of one donation from the Delta Lake history (optionally as of a table version)."""
    try:
        return history.donation_history(donation_id, version)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"Cannot read history: {type(exc).__name__}: {exc}")
