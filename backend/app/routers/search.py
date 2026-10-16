from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN, ROLE_NGO
from app.db import get_db
from app.deps import admin_or_service, require_roles
from app.models import User
from app.services import search

router = APIRouter(prefix="/search", tags=["search"])


def _need_es():
    if not search.enabled():
        raise HTTPException(503, "Search is not enabled. Start the stack with the 'search' profile "
                                 "(Elasticsearch) and set ELASTICSEARCH_URL.")


def _wrap(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Search backend unavailable: {type(exc).__name__}")


@router.get("/status")
def status(user: User = Depends(require_roles(ROLE_ADMIN, ROLE_NGO))):
    return {"enabled": search.enabled(), "reachable": search.ping()}


@router.get("/donations")
def donations(q: str | None = None, category: str | None = None, area: str | None = None, status: str | None = None,
              min_kg: float | None = Query(None, ge=0), lat: float | None = None, lng: float | None = None,
              radius_km: float = Query(15, gt=0, le=100), size: int = Query(20, ge=1, le=100),
              user: User = Depends(require_roles(ROLE_ADMIN, ROLE_NGO))):
    _need_es()
    near = (lat, lng) if lat is not None and lng is not None else None
    return _wrap(search.search_donations, q, category, area, status, min_kg, near, radius_km, size)


@router.get("/ngos")
def ngos(q: str | None = None, size: int = Query(20, ge=1, le=100),
         user: User = Depends(require_roles(ROLE_ADMIN, ROLE_NGO))):
    _need_es()
    return _wrap(search.search_ngos, q, size)


@router.post("/reindex")
def reindex(user: User = Depends(admin_or_service()), db: Session = Depends(get_db)):
    _need_es()
    return _wrap(search.reindex_all, db)
