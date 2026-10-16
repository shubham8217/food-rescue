from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN, ROLE_NGO, S_ACCEPTED, S_DELIVERED, S_MATCHED, S_PICKED_UP
from app.db import get_db
from app.deps import ngo_profile, require_roles
from app.models import NGO, Donation, Match, Request, User
from app.routers.donations import match_out, serialize
from app.schemas import DonationOut, MatchOut, RequestIn, RequestOut, StatusIn
from app.services import workflow
from app.services.cleaning import canonical_category
from app.services.matching import match_donation
from app.utils import parse_dt, utcnow

router = APIRouter(tags=["ngo"])


def _my_ngo(db: Session, user: User) -> NGO:
    ngo = ngo_profile(db, user)
    if ngo is None:
        raise HTTPException(403, "No NGO profile for this account")
    return ngo


def _wf(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except workflow.WorkflowError as e:
        raise HTTPException(e.status_code, str(e))


@router.get("/ngo/matches", response_model=list[MatchOut])
def my_matches(user: User = Depends(require_roles(ROLE_NGO)), db: Session = Depends(get_db)):
    """Open suggestions for this NGO, best score first."""
    ngo = _my_ngo(db, user)
    rows = db.execute(
        select(Match, Donation).join(Donation, Donation.id == Match.donation_id)
        .where(Match.ngo_id == ngo.id, Match.status == "suggested", Donation.status == S_MATCHED,
               Donation.expiry_time > utcnow())
        .order_by(Match.score.desc()).limit(100)).all()
    sers = {s.id: s for s in serialize(db, [d for _, d in rows])}
    return [match_out(m, sers[d.id]) for m, d in rows]


@router.get("/ngo/pickups", response_model=list[DonationOut])
def my_pickups(user: User = Depends(require_roles(ROLE_NGO)), db: Session = Depends(get_db)):
    ngo = _my_ngo(db, user)
    rows = db.scalars(select(Donation).where(Donation.accepted_ngo_id == ngo.id,
                                             Donation.status.in_([S_ACCEPTED, S_PICKED_UP, S_DELIVERED]))
                      .order_by(Donation.status_changed_at.desc()).limit(100)).all()
    return serialize(db, list(rows))


@router.post("/matches/{match_id}/accept", response_model=DonationOut)
def accept(match_id: int, user: User = Depends(require_roles(ROLE_NGO, ROLE_ADMIN)), db: Session = Depends(get_db)):
    ngo_id = _my_ngo(db, user).id if user.role == ROLE_NGO else None
    d = _wf(workflow.accept_match, db, match_id, ngo_id, actor=user.role)
    return serialize(db, [d])[0]


@router.post("/matches/{match_id}/decline", response_model=DonationOut)
def decline(match_id: int, user: User = Depends(require_roles(ROLE_NGO)), db: Session = Depends(get_db)):
    d = _wf(workflow.decline_match, db, match_id, _my_ngo(db, user).id)
    return serialize(db, [d])[0]


@router.patch("/donations/{donation_id}/status", response_model=DonationOut)
def update_status(donation_id: int, body: StatusIn, user: User = Depends(require_roles(ROLE_NGO, ROLE_ADMIN)),
                  db: Session = Depends(get_db)):
    ngo_id = _my_ngo(db, user).id if user.role == ROLE_NGO else None
    d = _wf(workflow.advance_status, db, donation_id, body.status, ngo_id)
    return serialize(db, [d])[0]


def _req_out(r: Request) -> RequestOut:
    return RequestOut(id=r.id, ngo_name=r.ngo.name, category=r.category, quantity_kg=r.quantity_kg,
                      fulfilled_kg=r.fulfilled_kg, needed_by=r.needed_by, status=r.status, standing=r.standing)


@router.get("/ngo/requests", response_model=list[RequestOut])
def my_requests(user: User = Depends(require_roles(ROLE_NGO)), db: Session = Depends(get_db)):
    ngo = _my_ngo(db, user)
    rows = db.scalars(select(Request).where(Request.ngo_id == ngo.id).order_by(Request.id.desc()).limit(50)).all()
    return [_req_out(r) for r in rows]


@router.post("/ngo/requests", response_model=RequestOut, status_code=201)
def create_request(body: RequestIn, user: User = Depends(require_roles(ROLE_NGO)), db: Session = Depends(get_db)):
    ngo = _my_ngo(db, user)
    category = None
    if body.category:
        category = canonical_category(body.category)
        if category is None:
            raise HTTPException(422, f"unknown category: '{body.category}'")
    if body.quantity_kg <= 0 or body.quantity_kg > 5000:
        raise HTTPException(422, "quantity_kg out of range (0-5000)")
    needed_by = parse_dt(body.needed_by)
    if needed_by <= utcnow():
        raise HTTPException(422, "needed_by is in the past")
    r = Request(ngo_id=ngo.id, category=category, quantity_kg=body.quantity_kg, needed_by=needed_by, source="manual")
    db.add(r)
    db.commit()
    # a new need may unlock donations that had no match so far
    for did in db.scalars(select(Donation.id).where(Donation.status == "listed", Donation.expiry_time > utcnow())
                          .limit(100)).all():
        match_donation(db, did, log=False)
    db.refresh(r)
    return _req_out(r)
