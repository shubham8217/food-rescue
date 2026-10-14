"""Matching worker: consumes 'donation.created' from RabbitMQ and saves the top-5 matches.

Also sweeps (every 30 s) for donations that never got matched, e.g. when the broker was down at
ingest time or a new NGO need appeared, so the pipeline self-heals.
"""
import json
import logging
import time

import pika
from sqlalchemy import select

from app import db as dbmod
from app.config import settings
from app.constants import QUEUE_DONATION_CREATED, S_LISTED
from app.models import Donation
from app.services.matching import match_donation
from app.utils import utcnow
from datetime import timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s worker: %(message)s")
logging.getLogger("pika").setLevel(logging.WARNING)
log = logging.getLogger("worker")

SWEEP_EVERY_S = 30
MAX_ATTEMPTS = 4


def process_message(body: bytes) -> int:
    """Handle one donation.created payload. Returns number of matches saved."""
    msg = json.loads(body)
    with dbmod.SessionLocal() as db:
        return len(match_donation(db, int(msg["donation_id"])))


def sweep() -> int:
    now = utcnow()
    with dbmod.SessionLocal() as db:
        ids = db.scalars(select(Donation.id).where(
            Donation.status == S_LISTED, Donation.match_attempts < MAX_ATTEMPTS, Donation.expiry_time > now,
            Donation.created_at < now - timedelta(seconds=20)).limit(200)).all()
        for i in ids:
            match_donation(db, i, log=False)
    return len(ids)


def run() -> None:
    while True:
        try:
            conn = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
            ch = conn.channel()
            ch.queue_declare(queue=QUEUE_DONATION_CREATED, durable=True)
            ch.basic_qos(prefetch_count=20)
            log.info("connected; waiting for %s", QUEUE_DONATION_CREATED)
            last_sweep = time.time()
            for method, _props, body in ch.consume(QUEUE_DONATION_CREATED, inactivity_timeout=5):
                if method is not None:
                    try:
                        n = process_message(body)
                        log.info("matched donation -> %d matches", n)
                    except Exception:
                        log.exception("failed to process message; sweeper will retry")
                    ch.basic_ack(method.delivery_tag)
                if time.time() - last_sweep > SWEEP_EVERY_S:
                    last_sweep = time.time()
                    try:
                        swept = sweep()
                        if swept:
                            log.info("sweeper re-checked %d donations", swept)
                    except Exception:
                        log.exception("sweep failed")
        except (pika.exceptions.AMQPError, OSError) as exc:
            log.warning("broker unavailable (%s); retrying in 3s", exc)
            time.sleep(3)


if __name__ == "__main__":
    run()
