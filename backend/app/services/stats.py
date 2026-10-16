"""Aggregates for the admin dashboard (counters, live payload, reset)."""
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.constants import MEAL_KG, S_ACCEPTED, S_DELIVERED, S_PICKED_UP
from app.models import NGO, Donation, Event, IngestBatch, Match, RejectedRow, Request
from app.services import mongo


def summary(db: Session) -> dict:
    batches, acc_d, acc_r, rej = db.execute(select(
        func.count(IngestBatch.id), func.coalesce(func.sum(IngestBatch.accepted_donations), 0),
        func.coalesce(func.sum(IngestBatch.accepted_requests), 0),
        func.coalesce(func.sum(IngestBatch.rejected_rows), 0))).one()
    real = Donation.source != "history"  # backfilled history only feeds analytics / forecast
    by_status = dict(db.execute(select(Donation.status, func.count(Donation.id)).where(real)
                                .group_by(Donation.status)).all())
    kg_delivered = db.scalar(select(func.coalesce(func.sum(Donation.quantity_kg), 0.0))
                             .where(Donation.status == S_DELIVERED, real)) or 0.0
    kg_in_flight = db.scalar(select(func.coalesce(func.sum(Donation.quantity_kg), 0.0))
                             .where(Donation.status.in_([S_ACCEPTED, S_PICKED_UP]), real)) or 0.0
    return {
        "batches": batches,
        "accepted_rows": int(acc_d + acc_r), "accepted_donations": int(acc_d), "accepted_requests": int(acc_r),
        "rejected_rows": int(rej),
        "matches": db.scalar(select(func.count(Match.id))) or 0,
        "donations_by_status": by_status,
        "total_donations": sum(by_status.values()),
        "kg_rescued": round(kg_delivered, 1), "kg_in_flight": round(kg_in_flight, 1),
        "meals": int(kg_delivered / MEAL_KG),
    }


def live_payload(db: Session, after_event_id: int = 0, first: bool = False) -> dict:
    from simulator.runner import runner  # local import: simulator depends on app

    q = select(Event).where(Event.id > after_event_id).order_by(Event.id.desc()).limit(100 if first else 200)
    evs = list(reversed(db.scalars(q).all()))
    pins = db.execute(select(Donation.id, Donation.lat, Donation.lng, Donation.status, Donation.category,
                             Donation.quantity_kg, Donation.area, Donation.food_type, Donation.accepted_ngo_id)
                      .where(Donation.source != "history").order_by(Donation.id.desc()).limit(400)).all()
    ngos = db.scalars(select(NGO).where(NGO.lat.is_not(None))).all()
    ngo_xy = {n.id: (n.lat, n.lng) for n in ngos}
    rej = db.scalars(select(RejectedRow).order_by(RejectedRow.id.desc()).limit(40)).all()
    return {
        "demo": runner.status(),
        "stats": summary(db),
        "events": [{"id": e.id, "ts": e.ts.isoformat() + "Z", "kind": e.kind, "message": e.message} for e in evs],
        "last_event_id": evs[-1].id if evs else after_event_id,
        "pins": [{"id": p.id, "lat": p.lat, "lng": p.lng, "status": p.status, "category": p.category,
                  "kg": p.quantity_kg, "area": p.area, "food": p.food_type,
                  "ngo": ngo_xy.get(p.accepted_ngo_id)} for p in pins],
        "ngos": [{"id": n.id, "name": n.name, "lat": n.lat, "lng": n.lng, "area": n.area} for n in ngos],
        "rejected": [{"id": r.id, "batch_id": r.batch_id, "row_number": r.row_number, "type": r.record_type,
                      "reason": r.reason, "raw": r.raw, "ts": r.created_at.isoformat() + "Z"} for r in rej],
    }


def reset_data(db: Session) -> None:
    """Wipe transactional data (keeps users, donors, NGOs and standing needs)."""
    db.execute(delete(Match).where(Match.donation_id.in_(select(Donation.id).where(Donation.source != "history"))))
    db.execute(delete(Donation).where(Donation.source != "history"))
    for model in (RejectedRow, Event):
        db.execute(delete(model))
    db.execute(delete(Request).where(Request.standing.is_(False)))
    db.execute(update(Request).values(fulfilled_kg=0.0))
    db.execute(delete(IngestBatch))
    db.commit()
    try:
        mongo.reset_collections()
    except Exception:
        pass
