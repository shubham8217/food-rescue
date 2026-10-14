"""Event log (Postgres, shared across processes) and the RabbitMQ publisher."""
import json
import logging

import pika
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import QUEUE_DONATION_CREATED
from app.models import Event
from app.utils import utcnow

log = logging.getLogger(__name__)


def log_event(db: Session, kind: str, message: str, data: dict | None = None, commit: bool = True) -> Event:
    ev = Event(kind=kind, message=message, data=data, ts=utcnow())
    db.add(ev)
    if commit:
        db.commit()
    else:
        db.flush()
    return ev


def publish_donation_created(messages: list[dict]) -> None:
    """Publish one 'donation.created' message per donation. Raises on connection failure;
    callers treat that as non-fatal because the worker sweeper re-matches unmatched donations."""
    if not messages:
        return
    conn = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
    try:
        ch = conn.channel()
        ch.queue_declare(queue=QUEUE_DONATION_CREATED, durable=True)
        for m in messages:
            ch.basic_publish(
                exchange="", routing_key=QUEUE_DONATION_CREATED, body=json.dumps(m, default=str),
                properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
            )
    finally:
        conn.close()
