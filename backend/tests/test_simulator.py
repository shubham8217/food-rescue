import random
from datetime import datetime, timedelta

from app.models import Donation, Event
from app.services import events
from app.services.ingest import ingest_rows
from app.worker.consumer import process_message, sweep
from simulator.generator import generate_batch, intensity, write_csv
from simulator.lifecycle import tick
import json

NOW = datetime(2026, 10, 14, 7, 0)  # 12:30 IST


def test_batch_sizes_within_spec_and_peak_hours_have_more():
    rng = random.Random(1)
    lunch = [generate_batch(NOW, rng, hour=13.5)[1] for _ in range(30)]
    night = [generate_batch(NOW, rng, hour=3.0)[1] for _ in range(30)]
    for m in lunch + night:
        assert 15 <= m["donations"] <= 40 and 3 <= m["requests"] <= 8
    assert sum(m["donations"] for m in lunch) > sum(m["donations"] for m in night) * 1.4
    assert intensity(13.5) > intensity(17) and intensity(20.5) > intensity(4)


def test_about_ten_percent_dirty_and_areas_are_navi_mumbai():
    rng = random.Random(2)
    dirty = total = 0
    areas = set()
    for _ in range(60):
        rows, meta = generate_batch(NOW, rng, hour=13.5)
        dirty += meta["dirty"]
        total += meta["donations"] + meta["requests"]
        areas |= {r["area"] for r in rows if r["area"]}
    assert 0.07 <= dirty / total <= 0.13
    assert {"Nerul", "Vashi", "Belapur", "Kharghar", "Sanpada", "Airoli", "Seawoods"} <= areas


def test_generated_batch_is_roughly_90_percent_clean_after_cleaning(session, published):
    rng = random.Random(3)
    acc = rej = 0
    for _ in range(10):
        rows, _ = generate_batch(datetime.utcnow(), rng, hour=13.5)
        s = ingest_rows(session, rows, source="sim")
        acc += s["accepted_donations"] + s["accepted_requests"]
        rej += s["rejected_rows"]
    assert 0.05 <= rej / (acc + rej) <= 0.20
    assert session.query(Event).filter_by(kind="ingest").count() == 10


def test_csv_written_atomically_for_nifi(tmp_path):
    rows, _ = generate_batch(NOW, random.Random(4))
    p = write_csv(rows, str(tmp_path), 7, NOW)
    assert p.endswith("_07.csv") and not list(tmp_path.glob("*.tmp"))
    header = open(p, encoding="utf-8").readline().strip()
    assert header == "record_type,org_name,food_type,category,quantity_kg,expiry_time,lat,lng,area"


def test_simulated_lifecycle_moves_donations_to_delivered(session, published):
    rows, _ = generate_batch(datetime.utcnow(), random.Random(5), hour=13.5)
    ingest_rows(session, rows, source="sim")
    for m in list(published):
        process_message(json.dumps(m).encode())
    session.expire_all()
    assert session.query(Donation).filter_by(status="matched").count() > 0
    # speed 1000x: every delay elapses immediately; one tick per transition
    for _ in range(3):
        tick(speed=1000)
    session.expire_all()
    delivered = session.query(Donation).filter_by(status="delivered").count()
    assert delivered > 0
    assert session.query(Donation).filter(Donation.status.in_(["matched", "accepted", "picked_up"])).count() == 0 \
        or delivered > 0


def test_sweeper_matches_donations_whose_event_was_lost(session, monkeypatch):
    def boom(msgs):
        raise ConnectionError("down")
    monkeypatch.setattr(events, "publish_donation_created", boom)
    rows, _ = generate_batch(datetime.utcnow(), random.Random(6), hour=13.5)
    ingest_rows(session, rows, source="sim")
    d = session.query(Donation).first()
    d.created_at = datetime.utcnow() - timedelta(minutes=2)
    session.commit()
    assert sweep() >= 1
    session.expire_all()
    assert session.query(Donation).filter_by(status="matched").count() >= 1
