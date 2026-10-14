from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN, ROLE_DONOR, ROLE_NGO
from app.db import get_db
from app.deps import donor_profile, get_current_user, ngo_profile, require_roles
from app.models import NGO, Donation, Match, User
from app.schemas import DonationIn, DonationOut, MatchOut
from app.services import ingest
from app.services.matching import match_donation

router = APIRouter(prefix="/donations", tags=["donations"])


def serialize(db: Session, donations: list[Donation]) -> list[DonationOut]:
    ids = [d.id for d in donations]
    counts = dict(db.execute(select(Match.donation_id, func.count(Match.id)).where(Match.donation_id.in_(ids))
                             .group_by(Match.donation_id)).all()) if ids else {}
    ngo_ids = {d.accepted_ngo_id for d in donations if d.accepted_ngo_id}
    ngos = {n.id: n.name for n in db.scalars(select(NGO).where(NGO.id.in_(ngo_ids)))} if ngo_ids else {}
    out = []
    for d in donations:
        o = DonationOut.model_validate(d)
        o.donor_name = d.donor.name if d.donor else None
        o.accepted_ngo_name = ngos.get(d.accepted_ngo_id)
        o.match_count = counts.get(d.id, 0)
        out.append(o)
    return out


def match_out(m: Match, donation: DonationOut) -> MatchOut:
    return MatchOut(id=m.id, rank=m.rank, score=m.score, distance_km=m.distance_km, distance_score=m.distance_score,
                    urgency_score=m.urgency_score, fit_score=m.fit_score, status=m.status, ngo_id=m.ngo_id,
                    ngo_name=m.ngo.name, donation=donation)


@router.post("", response_model=DonationOut, status_code=201)
def create_donation(body: DonationIn, user: User = Depends(require_roles(ROLE_DONOR, ROLE_ADMIN)),
                    db: Session = Depends(get_db)):
    """Manual donation: goes through the same Polars cleaning as bulk ingest."""
    donor = donor_profile(db, user) if user.role == ROLE_DONOR else None
    if user.role == ROLE_DONOR and donor is None:
        raise HTTPException(403, "No donor profile for this account")
    row = {"org_name": donor.name if donor else (body.org_name or "Admin Donor"), "food_type": body.food_type,
           "category": body.category, "quantity_kg": body.quantity_kg, "expiry_time": body.expiry_time.isoformat(),
           "area": body.area, "lat": body.lat if body.lat is not None else (donor.lat if donor and body.area == donor.area else None),
           "lng": body.lng if body.lng is not None else (donor.lng if donor and body.area == donor.area else None)}
    summary = ingest.ingest_rows(db, [row], source="manual", donor_override=donor, allow_requests=False)
    if not summary["donation_ids"]:
        reason = summary["rejected"][0]["reason"] if summary["rejected"] else "rejected"
        raise HTTPException(422, f"Donation rejected: {reason}")
    d = db.get(Donation, summary["donation_ids"][0])
    if summary.get("publish_failed"):
        match_donation(db, d.id)  # broker down: match inline so the user still sees results
        db.refresh(d)
    return serialize(db, [d])[0]


@router.get("/mine", response_model=list[DonationOut])
def my_donations(user: User = Depends(require_roles(ROLE_DONOR)), db: Session = Depends(get_db)):
    donor = donor_profile(db, user)
    if donor is None:
        return []
    rows = db.scalars(select(Donation).where(Donation.donor_id == donor.id).order_by(Donation.id.desc()).limit(200)).all()
    return serialize(db, list(rows))


@router.get("", response_model=list[DonationOut])
def list_donations(status: str | None = None, limit: int = 100, user: User = Depends(require_roles(ROLE_ADMIN)),
                   db: Session = Depends(get_db)):
    q = select(Donation).order_by(Donation.id.desc()).limit(min(limit, 500))
    if status:
        q = q.where(Donation.status == status)
    return serialize(db, list(db.scalars(q).all()))


@router.get("/{donation_id}/matches", response_model=list[MatchOut])
def donation_matches(donation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = db.get(Donation, donation_id)
    if d is None:
        raise HTTPException(404, "Donation not found")
    if user.role == ROLE_DONOR:
        donor = donor_profile(db, user)
        if donor is None or d.donor_id != donor.id:
            raise HTTPException(403, "Not your donation")
    elif user.role == ROLE_NGO:
        raise HTTPException(403, "NGOs use /ngo/matches")
    ser = serialize(db, [d])[0]
    ms = db.scalars(select(Match).where(Match.donation_id == donation_id).order_by(Match.rank)).all()
    return [match_out(m, ser) for m in ms]
