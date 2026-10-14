"""Idempotent seed: demo accounts + NGOs with standing needs, so manual donations match immediately."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN, ROLE_DONOR, ROLE_NGO
from app.geo import AREAS
from app.models import NGO, Donor, Request, User
from app.security import hash_password
from app.utils import utcnow

DEMO_PASSWORD = "demo123"

# Shared with the simulator: NGOs that exist from the start.
SEED_NGOS = [
    ("Annapurna Food Bank", "Vashi"), ("Seva Community Kitchen", "Nerul"), ("Roti Bank Belapur", "Belapur"),
    ("Hope Foundation Kharghar", "Kharghar"), ("Sanpada Shelter Trust", "Sanpada"),
    ("Airoli Aid Society", "Airoli"), ("Seawoods Care Kitchen", "Seawoods"), ("Navi Mumbai Meals On Wheels", "Nerul"),
]


def _user(db: Session, email: str, name: str, role: str) -> User:
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(email=email, name=name, role=role, password_hash=hash_password(DEMO_PASSWORD))
        db.add(u)
        db.flush()
    return u


def _standing_request(db: Session, ngo: NGO) -> None:
    if db.scalar(select(Request.id).where(Request.ngo_id == ngo.id, Request.standing.is_(True))) is None:
        db.add(Request(ngo_id=ngo.id, category=None, quantity_kg=100.0, needed_by=utcnow() + timedelta(days=3650),
                       standing=True, source="seed"))


def seed(db: Session) -> None:
    _user(db, "admin@foodrescue.demo", "Demo Admin", ROLE_ADMIN)
    donor_user = _user(db, "donor@foodrescue.demo", "Demo Donor", ROLE_DONOR)
    ngo_user = _user(db, "ngo@foodrescue.demo", "Demo NGO", ROLE_NGO)

    if db.scalar(select(Donor).where(Donor.user_id == donor_user.id)) is None:
        lat, lng = AREAS["Vashi"]
        db.add(Donor(user_id=donor_user.id, name="Demo Restaurant (Vashi)", org_type="restaurant", area="Vashi",
                     lat=lat, lng=lng))
    demo_ngo = db.scalar(select(NGO).where(NGO.user_id == ngo_user.id))
    if demo_ngo is None:
        lat, lng = AREAS["Nerul"]
        demo_ngo = NGO(user_id=ngo_user.id, name="Demo Food Bank (Nerul)", area="Nerul", lat=lat, lng=lng,
                       capacity_kg=200)
        db.add(demo_ngo)
        db.flush()
    _standing_request(db, demo_ngo)

    for name, area in SEED_NGOS:
        ngo = db.scalar(select(NGO).where(NGO.name == name))
        if ngo is None:
            lat, lng = AREAS[area]
            ngo = NGO(name=name, area=area, lat=lat, lng=lng, capacity_kg=150)
            db.add(ngo)
            db.flush()
        _standing_request(db, ngo)
    db.commit()
