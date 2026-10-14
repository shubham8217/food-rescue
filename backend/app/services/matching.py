"""Matching engine.

score = 0.4 * distance_score + 0.35 * urgency_score + 0.25 * fit_score

* distance_score = 1 - d / radius                      (closer is better)
* urgency_score  = mean(donation pressure, need pressure); pressure = 1 - hours_left / 12 (clamped 0..1)
                   -> food about to expire and NGOs needing it soon rank higher
* fit_score      = min(q, need) / max(q, need)         (right-sized needs rank higher)

Hard filters: within radius, category compatible, enough shelf life to travel there (25 km/h).
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import S_EXPIRED, S_LISTED, S_MATCHED
from app.geo import haversine_km
from app.models import NGO, Donation, Match, Request
from app.services.events import log_event
from app.utils import utcnow

W_DISTANCE, W_URGENCY, W_FIT = 0.40, 0.35, 0.25
URGENCY_HORIZON_H = 12.0
TRAVEL_KMH = 25.0
TOP_N = 5


@dataclass
class Candidate:
    ngo_id: int
    request_id: int | None
    lat: float
    lng: float
    need_kg: float
    needed_by: datetime
    category: str | None


@dataclass
class Scored:
    ngo_id: int
    request_id: int | None
    score: float
    distance_km: float
    distance_score: float
    urgency_score: float
    fit_score: float


def _pressure(hours_left: float) -> float:
    return 1.0 - min(max(hours_left, 0.0), URGENCY_HORIZON_H) / URGENCY_HORIZON_H


def score_match(distance_km: float, donation_hours_left: float, need_hours_left: float,
                donation_kg: float, need_kg: float, radius_km: float | None = None) -> dict:
    radius = radius_km or settings.match_radius_km
    distance_score = max(0.0, 1.0 - distance_km / radius)
    urgency_score = (_pressure(donation_hours_left) + _pressure(need_hours_left)) / 2
    fit_score = min(donation_kg, need_kg) / max(donation_kg, need_kg) if donation_kg > 0 and need_kg > 0 else 0.0
    score = W_DISTANCE * distance_score + W_URGENCY * urgency_score + W_FIT * fit_score
    return {"score": round(score, 4), "distance_score": round(distance_score, 4),
            "urgency_score": round(urgency_score, 4), "fit_score": round(fit_score, 4)}


def rank_candidates(donation: dict, candidates: list[Candidate], now: datetime,
                    radius_km: float | None = None, top_n: int = TOP_N) -> list[Scored]:
    """Pure function: filter by expiry/category/radius, score, keep best request per NGO, return top N."""
    radius = radius_km or settings.match_radius_km
    donation_hours = (donation["expiry_time"] - now).total_seconds() / 3600
    if donation_hours <= 0:
        return []
    best: dict[int, Scored] = {}
    for c in candidates:
        if c.category is not None and c.category != donation["category"]:
            continue
        if (c.needed_by - now).total_seconds() <= 0 or c.need_kg <= 0:
            continue
        d = haversine_km(donation["lat"], donation["lng"], c.lat, c.lng)
        if d > radius:
            continue
        if d / TRAVEL_KMH > donation_hours:  # would expire before pickup is possible
            continue
        parts = score_match(d, donation_hours, (c.needed_by - now).total_seconds() / 3600,
                            donation["quantity_kg"], c.need_kg, radius)
        s = Scored(c.ngo_id, c.request_id, parts["score"], round(d, 2), parts["distance_score"],
                   parts["urgency_score"], parts["fit_score"])
        if c.ngo_id not in best or s.score > best[c.ngo_id].score:
            best[c.ngo_id] = s
    return sorted(best.values(), key=lambda s: (-s.score, s.distance_km))[:top_n]


def _open_candidates(db: Session, now: datetime) -> list[Candidate]:
    rows = db.execute(
        select(Request, NGO).join(NGO, NGO.id == Request.ngo_id)
        .where(Request.status == "open", Request.needed_by > now, NGO.lat.is_not(None))
    ).all()
    out = []
    for req, ngo in rows:
        out.append(Candidate(ngo.id, req.id, ngo.lat, ngo.lng, req.quantity_kg - req.fulfilled_kg,
                             req.needed_by, req.category))
    return out


def match_donation(db: Session, donation_id: int, now: datetime | None = None, log: bool = True) -> list[Match]:
    """Compute and persist the top-5 matches for a donation (idempotent: replaces old suggestions)."""
    now = now or utcnow()
    donation = db.get(Donation, donation_id)
    if donation is None or donation.status not in (S_LISTED, S_MATCHED):
        return []
    donation.match_attempts += 1
    if donation.expiry_time <= now:
        donation.status, donation.status_changed_at = S_EXPIRED, now
        db.commit()
        return []

    ranked = rank_candidates(
        {"expiry_time": donation.expiry_time, "category": donation.category, "lat": donation.lat,
         "lng": donation.lng, "quantity_kg": donation.quantity_kg},
        _open_candidates(db, now), now)

    for old in db.scalars(select(Match).where(Match.donation_id == donation_id, Match.status == "suggested")):
        db.delete(old)
    matches = []
    for i, s in enumerate(ranked, start=1):
        m = Match(donation_id=donation_id, ngo_id=s.ngo_id, request_id=s.request_id, rank=i, score=s.score,
                  distance_km=s.distance_km, distance_score=s.distance_score, urgency_score=s.urgency_score,
                  fit_score=s.fit_score, status="suggested")
        db.add(m)
        matches.append(m)
    if matches and donation.status == S_LISTED:
        donation.status, donation.status_changed_at = S_MATCHED, now
    db.commit()
    if log:
        if matches:
            top = db.get(NGO, matches[0].ngo_id)
            log_event(db, "match",
                      f"Donation #{donation.id} ({donation.category.replace('_', ' ')} {donation.quantity_kg:g}kg, "
                      f"{donation.area}) -> {top.name} score {matches[0].score:.2f} (+{len(matches) - 1} more)",
                      {"donation_id": donation.id, "matches": len(matches)})
        else:
            log_event(db, "no_match", f"Donation #{donation.id} ({donation.area}) has no eligible NGO yet",
                      {"donation_id": donation.id})
    return matches
