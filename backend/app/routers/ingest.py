import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN, ROLE_DONOR
from app.db import get_db
from app.deps import admin_or_service, donor_profile
from app.models import IngestBatch, RejectedRow, User
from app.services import ingest

router = APIRouter(prefix="/ingest", tags=["ingest"])
MAX_ROWS = 5000


async def _read_rows(request: Request) -> tuple[list[dict], str, str | None]:
    """Accepts multipart CSV/JSON file upload, a raw CSV body, or a JSON body (list or {rows, source})."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        f = form.get("file")
        if f is None or not hasattr(f, "read"):
            raise HTTPException(422, "multipart upload needs a 'file' field")
        text = (await f.read()).decode("utf-8-sig")
        name = f.filename or "upload"
        if name.lower().endswith(".json"):
            return _json_rows(json.loads(text)), "upload", name
        return list(csv.DictReader(io.StringIO(text))), "upload", name
    body = (await request.body()).decode("utf-8-sig")
    if "csv" in ctype:
        return list(csv.DictReader(io.StringIO(body))), "api", None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(422, "Body must be JSON, CSV (text/csv) or a multipart file upload")
    source = payload.get("source", "api") if isinstance(payload, dict) else "api"
    return _json_rows(payload), source, None


def _json_rows(payload) -> list[dict]:
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise HTTPException(422, "JSON must be a list of objects or {\"rows\": [...]}")
    return rows


@router.post("/batch")
async def ingest_batch(request: Request, user: User = Depends(admin_or_service(ROLE_DONOR)),
                       db: Session = Depends(get_db)):
    rows, source, filename = await _read_rows(request)
    if not rows:
        raise HTTPException(422, "No rows supplied")
    if len(rows) > MAX_ROWS:
        raise HTTPException(413, f"Too many rows (max {MAX_ROWS})")
    if source not in ("sim", "api", "upload"):
        source = "api"
    if user.role == ROLE_DONOR:
        donor = donor_profile(db, user)
        if donor is None:
            raise HTTPException(403, "No donor profile for this account")
        source = "upload" if source != "api" else source
        return ingest.ingest_rows(db, rows, source=source, filename=filename, donor_override=donor,
                                  allow_requests=False)
    return ingest.ingest_rows(db, rows, source=source, filename=filename)


@router.get("/batches")
def batches(limit: int = 50, user: User = Depends(admin_or_service()), db: Session = Depends(get_db)):
    rows = db.scalars(select(IngestBatch).order_by(IngestBatch.id.desc()).limit(min(limit, 200))).all()
    return [{"id": b.id, "source": b.source, "filename": b.filename, "total_rows": b.total_rows,
             "accepted_donations": b.accepted_donations, "accepted_requests": b.accepted_requests,
             "rejected_rows": b.rejected_rows, "created_at": b.created_at.isoformat() + "Z"} for b in rows]


@router.get("/rejected")
def rejected(batch_id: int | None = None, limit: int = 100, user: User = Depends(admin_or_service()),
             db: Session = Depends(get_db)):
    q = select(RejectedRow).order_by(RejectedRow.id.desc()).limit(min(limit, 500))
    if batch_id:
        q = q.where(RejectedRow.batch_id == batch_id)
    return [{"id": r.id, "batch_id": r.batch_id, "row_number": r.row_number, "type": r.record_type,
             "reason": r.reason, "raw": r.raw} for r in db.scalars(q).all()]
