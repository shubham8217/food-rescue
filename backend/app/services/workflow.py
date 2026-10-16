"""Donation lifecycle: accept a match, then pickup / deliver. Used by API routes and the simulator."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import NEXT_STATUS, S_ACCEPTED, S_DELIVERED, S_LISTED, S_MATCHED, S_PICKED_UP
from app.models import NGO, Donation, Match, Request
from app.services import history, search
from app.services.events import log_event
from app.utils import utcnow


class WorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def accept_match(db: Session, match_id: int, ngo_id: int | None = None, actor: str = "NGO",
                 flush: bool = True) -> Donation:
    """ngo_id given -> the match must belong to that NGO (None = admin / simulator)."""
    match = db.get(Match, match_id)
    if match is None or (ngo_id is not None and match.ngo_id != ngo_id):
        raise WorkflowError("Match not found", 404)
    donation = db.scalar(select(Donation).where(Donation.id == match.donation_id).with_for_update(of=Donation))
    if donation.status != S_MATCHED or match.status != "suggested":
        raise WorkflowError(f"Donation is already {donation.status}")
    if donation.expiry_time <= utcnow():
        raise WorkflowError("Donation has expired")
    request = db.get(Request, match.request_id) if match.request_id else None
    if request is not None and request.status != "open":
        raise WorkflowError("That NGO need has already been fulfilled")

    now = utcnow()
    match.status = "accepted"
    for other in db.scalars(select(Match).where(Match.donation_id == donation.id, Match.id != match.id,
                                                Match.status == "suggested")):
        other.status = "declined"
    donation.status, donation.status_changed_at = S_ACCEPTED, now
    donation.accepted_ngo_id = match.ngo_id
    if request is not None and not request.standing:  # standing needs never run out
        request.fulfilled_kg += donation.quantity_kg
        if request.fulfilled_kg >= request.quantity_kg * 0.9:
            request.status = "fulfilled"
    ngo = db.get(NGO, match.ngo_id)
    log_event(db, "accepted", f"{ngo.name} accepted donation #{donation.id} ({donation.quantity_kg:g}kg "
              f"{donation.category.replace('_', ' ')}) [{actor}]", {"donation_id": donation.id, "ngo_id": ngo.id},
              commit=False)
    db.commit()
    history.record_status(donation.id, S_MATCHED, S_ACCEPTED, ngo_id=match.ngo_id, note=actor, flush=flush)
    search.update_status(donation.id, S_ACCEPTED, match.ngo_id)
    return donation


def advance_status(db: Session, donation_id: int, new_status: str, ngo_id: int | None = None,
                   flush: bool = True) -> Donation:
    donation = db.scalar(select(Donation).where(Donation.id == donation_id).with_for_update(of=Donation))
    if donation is None or (ngo_id is not None and donation.accepted_ngo_id != ngo_id):
        raise WorkflowError("Donation not found", 404)
    if new_status not in (S_PICKED_UP, S_DELIVERED):
        raise WorkflowError("Status can only move to picked_up or delivered", 422)
    if NEXT_STATUS.get(donation.status) != new_status:
        raise WorkflowError(f"Cannot move {donation.status} -> {new_status}")
    old_status = donation.status
    donation.status, donation.status_changed_at = new_status, utcnow()
    ngo = db.get(NGO, donation.accepted_ngo_id)
    verb = "picked up" if new_status == S_PICKED_UP else "delivered"
    log_event(db, new_status, f"Donation #{donation.id} {verb} by {ngo.name} ({donation.quantity_kg:g}kg)",
              {"donation_id": donation.id}, commit=False)
    db.commit()
    history.record_status(donation.id, old_status, new_status, ngo_id=donation.accepted_ngo_id, flush=flush)
    search.update_status(donation.id, new_status)
    return donation


def decline_match(db: Session, match_id: int, ngo_id: int) -> Donation:
    """An NGO declines a suggestion. If nobody is left, the donation goes back to 'listed' and is re-matched."""
    match = db.get(Match, match_id)
    if match is None or match.ngo_id != ngo_id:
        raise WorkflowError("Match not found", 404)
    donation = db.get(Donation, match.donation_id)
    if donation.status != S_MATCHED or match.status != "suggested":
        raise WorkflowError(f"Donation is already {donation.status}")
    match.status = "declined"
    ngo = db.get(NGO, ngo_id)
    log_event(db, "declined", f"{ngo.name} declined donation #{donation.id}", {"donation_id": donation.id},
              commit=False)
    db.commit()
    left = db.scalar(select(Match.id).where(Match.donation_id == donation.id, Match.status == "suggested"))
    if left is None:
        reopen_for_matching(db, donation)
    return donation


def reopen_for_matching(db: Session, donation: Donation) -> None:
    if donation.status == S_MATCHED:
        donation.status, donation.status_changed_at = S_LISTED, utcnow()
        db.commit()
