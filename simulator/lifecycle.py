"""Simulated NGOs: auto-accept the best match, then move picked_up -> delivered over time.
Only touches donations with source='sim'. Also expires stale listed/matched donations."""
import asyncio
import logging
from datetime import datetime

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, update
from sqlalchemy.orm.exc import ObjectDeletedError

from app import db as dbmod
from app.constants import S_ACCEPTED, S_DELIVERED, S_LISTED, S_MATCHED, S_PICKED_UP
from app.models import Donation, Match
from app.services import history, search, workflow
from app.services.matching import match_donation
from app.utils import utcnow

log = logging.getLogger("simulator.lifecycle")


def delays(donation_id: int) -> dict[str, float]:
    """Deterministic per-donation delays (seconds at 1x) so runs look organic but stay testable."""
    return {S_MATCHED: 6 + (donation_id * 37) % 15,      # NGO accepts
            S_ACCEPTED: 10 + (donation_id * 53) % 21,    # pickup
            S_PICKED_UP: 15 + (donation_id * 29) % 31}   # delivery


def tick(speed: float = 1.0, now: datetime | None = None) -> int:
    now = now or utcnow()
    moved = 0
    with dbmod.SessionLocal() as db:
        stale = db.execute(select(Donation.id, Donation.status).where(
            Donation.status.in_([S_LISTED, S_MATCHED]), Donation.expiry_time <= now)).all()
        if stale:
            db.execute(update(Donation).where(Donation.id.in_([i for i, _ in stale]))
                       .values(status="expired", status_changed_at=now))
            db.commit()
            for did, old in stale:
                history.record_status(did, old, "expired", note="expiry sweep", flush=False)
                search.update_status(did, "expired")
        rows = db.scalars(select(Donation).where(
            Donation.source == "sim", Donation.status.in_([S_MATCHED, S_ACCEPTED, S_PICKED_UP])).limit(600)).all()
        for d in rows:
            try:
                elapsed = (now - d.status_changed_at).total_seconds() * speed
                if elapsed < delays(d.id)[d.status]:
                    continue
                if d.status == S_MATCHED:
                    ms = db.scalars(select(Match).where(Match.donation_id == d.id, Match.status == "suggested")
                                    .order_by(Match.rank)).all()
                    for m in ms:
                        try:
                            workflow.accept_match(db, m.id, None, actor="simulated NGO", flush=False)
                            moved += 1
                            break
                        except workflow.WorkflowError:
                            db.rollback()
                    else:  # every suggested need got taken meanwhile: re-match
                        workflow.reopen_for_matching(db, d)
                        match_donation(db, d.id, log=False)
                elif d.status == S_ACCEPTED:
                    workflow.advance_status(db, d.id, S_PICKED_UP, flush=False)
                    moved += 1
                elif d.status == S_PICKED_UP:
                    workflow.advance_status(db, d.id, S_DELIVERED, flush=False)
                    moved += 1
            except workflow.WorkflowError:
                db.rollback()
            except ObjectDeletedError:  # the admin reset the data while we were iterating: nothing to do
                db.rollback()
            except Exception:
                db.rollback()
                log.exception("lifecycle step failed for donation %s", d.id)
    history.flush_status()
    return moved


async def lifecycle_loop():
    from simulator.runner import runner
    while True:
        try:
            await run_in_threadpool(tick, runner.speed)
        except Exception:
            log.exception("lifecycle tick failed")
        await asyncio.sleep(1.0)
