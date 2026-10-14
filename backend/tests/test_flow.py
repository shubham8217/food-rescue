"""ingest -> Mongo raw -> Polars clean -> Postgres -> RabbitMQ event -> worker match -> accept -> deliver"""
from datetime import datetime, timedelta

from app.models import Donation, Match, RejectedRow
from app.worker.consumer import process_message
import json


def iso(hours):
    return (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def good(name="Vashi Bakery", food="Bread loaves", cat="bakery", qty=20, hours=6, area="Vashi"):
    return {"record_type": "donation", "org_name": name, "food_type": food, "category": cat, "quantity_kg": qty,
            "expiry_time": iso(hours), "area": area}


def run_worker(published):
    for m in list(published):
        process_message(json.dumps(m).encode())


def test_ingest_to_match_flow(client, session, admin, published, mongo_db):
    rows = [
        good(), good(food="Pav buns", qty=10, area="Nerul"),
        good(),                                   # duplicate of row 1
        good(food="Old stuff", hours=-3),         # expired
        good(cat="xyz123", food="Mystery"),       # bad category
        good(qty="", food="No qty"),              # missing field
        good(food="Spoiled curry", cat="cooked_meals"),   # unsafe
        {"record_type": "request", "org_name": "Test Shelter", "category": "bakery", "quantity_kg": 25,
         "expiry_time": iso(4), "area": "Vashi"},
    ]
    r = client.post("/ingest/batch", headers=admin, json={"source": "api", "rows": rows})
    assert r.status_code == 200, r.text
    s = r.json()
    assert (s["total_rows"], s["accepted_donations"], s["accepted_requests"], s["rejected_rows"]) == (8, 2, 1, 5)

    # RAW rows reached MongoDB untouched, including the dirty ones
    assert mongo_db.raw_ingest.count_documents({"batch_id": s["batch_id"]}) == 8

    # rejected rows are stored with reasons
    reasons = {x.reason for x in session.query(RejectedRow).all()}
    assert "expired item" in reasons and "duplicate row in batch" in reasons
    assert any(x.startswith("unknown category") for x in reasons)
    assert any(x.startswith("unsafe item") for x in reasons)
    assert "missing required field: quantity_kg" in reasons

    # clean data is in PostgreSQL and one donation.created event per donation was published
    assert session.query(Donation).count() == 2
    assert len(published) == 2 and all(m["event"] == "donation.created" for m in published)
    assert mongo_db.events.count_documents({}) == 2

    # worker consumes the events and saves the top matches
    run_worker(published)
    session.expire_all()
    donations = session.query(Donation).all()
    assert all(d.status == "matched" for d in donations)
    for d in donations:
        ms = session.query(Match).filter_by(donation_id=d.id).order_by(Match.rank).all()
        assert 1 <= len(ms) <= 5
        assert [m.rank for m in ms] == list(range(1, len(ms) + 1))
        assert all(m.distance_km <= 15 for m in ms)
        assert ms == sorted(ms, key=lambda m: -m.score)


def test_second_ingest_of_same_rows_is_deduped_against_db(client, session, admin, published):
    r1 = client.post("/ingest/batch", headers=admin, json=[good()]).json()
    r2 = client.post("/ingest/batch", headers=admin, json=[good()]).json()
    assert r1["accepted_donations"] == 1 and r2["accepted_donations"] == 0
    assert session.query(RejectedRow).filter_by(reason="duplicate of an existing record").count() == 1


def test_csv_upload_and_raw_csv_body(client, admin, published):
    csv_text = ("record_type,org_name,food_type,category,quantity_kg,expiry_time,lat,lng,area\n"
                f"donation,Nerul Cafe,Sandwiches,Bakery,8,{iso(5)},,,Nerul\n"
                f"donation,Nerul Cafe,Mystery,junk,8,{iso(5)},,,Nerul\n")
    r = client.post("/ingest/batch", headers={**admin, "Content-Type": "text/csv"}, content=csv_text)
    assert r.status_code == 200 and r.json()["accepted_donations"] == 1 and r.json()["rejected_rows"] == 1
    r = client.post("/ingest/batch", headers=admin, files={"file": ("x.csv", csv_text.replace("Sandwiches", "Wraps"))})
    assert r.status_code == 200 and r.json()["accepted_donations"] == 1


def test_ingest_validation_errors(client, admin):
    assert client.post("/ingest/batch", headers=admin, json=[]).status_code == 422
    assert client.post("/ingest/batch", headers=admin, json={"nope": 1}).status_code == 422


def test_ingest_survives_broker_outage(client, session, admin, monkeypatch):
    from app.services import events

    def boom(msgs):
        raise ConnectionError("rabbit down")
    monkeypatch.setattr(events, "publish_donation_created", boom)
    r = client.post("/ingest/batch", headers=admin, json=[good()])
    assert r.status_code == 200 and r.json()["accepted_donations"] == 1 and r.json()["publish_failed"]
    assert session.query(Donation).count() == 1  # data is safe; sweeper will match it


def test_donor_creates_ngo_accepts_and_delivers(client, session, donor, ngo, admin, published):
    body = {"food_type": "Veg biryani", "category": "cooked_meals", "quantity_kg": 25, "expiry_time": iso(4) ,
            "area": "Vashi"}
    r = client.post("/donations", headers=donor, json=body)
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    assert r.json()["status"] == "listed" and len(published) == 1
    run_worker(published)

    mine = client.get("/donations/mine", headers=donor).json()
    assert mine[0]["status"] == "matched" and mine[0]["match_count"] >= 1

    matches = client.get("/ngo/matches", headers=ngo).json()
    assert matches and matches[0]["donation"]["id"] == did
    assert matches == sorted(matches, key=lambda m: -m["score"])
    mid = matches[0]["id"]

    # a donor cannot accept; status can't skip ahead
    assert client.post(f"/matches/{mid}/accept", headers=donor).status_code == 403
    assert client.patch(f"/donations/{did}/status", headers=ngo, json={"status": "picked_up"}).status_code == 404  # not yours yet

    acc = client.post(f"/matches/{mid}/accept", headers=ngo)
    assert acc.status_code == 200 and acc.json()["status"] == "accepted"
    assert client.post(f"/matches/{mid}/accept", headers=ngo).status_code == 409   # already taken
    assert client.get("/ngo/matches", headers=ngo).json() == []
    assert client.patch(f"/donations/{did}/status", headers=ngo, json={"status": "delivered"}).status_code == 409  # can't skip

    assert client.patch(f"/donations/{did}/status", headers=ngo, json={"status": "picked_up"}).json()["status"] == "picked_up"
    assert client.patch(f"/donations/{did}/status", headers=ngo, json={"status": "delivered"}).json()["status"] == "delivered"
    pickups = client.get("/ngo/pickups", headers=ngo).json()
    assert pickups[0]["status"] == "delivered"

    st = client.get("/stats/summary", headers=admin).json()
    assert st["kg_rescued"] == 25 and st["meals"] == 62


def test_donor_rejected_with_reason_returns_422(client, donor):
    body = {"food_type": "Stale bread", "category": "bakery", "quantity_kg": 5, "expiry_time": iso(4), "area": "Vashi"}
    r = client.post("/donations", headers=donor, json=body)
    assert r.status_code == 422 and "unsafe item" in r.json()["detail"]
    body.update(food_type="Bread", expiry_time=iso(-2))
    assert "expired" in client.post("/donations", headers=donor, json=body).json()["detail"]


def test_other_ngo_cannot_accept_foreign_match(client, session, donor, ngo, published):
    from app.models import NGO
    client.post("/donations", headers=donor, json={"food_type": "Bread", "category": "bakery", "quantity_kg": 10,
                                                   "expiry_time": iso(5), "area": "Vashi"})
    run_worker(published)
    other = session.query(NGO).filter(NGO.user_id.is_(None)).first()
    m = session.query(Match).filter(Match.ngo_id == other.id).first()
    if m:  # the demo NGO must not be able to accept someone else's match
        assert client.post(f"/matches/{m.id}/accept", headers=ngo).status_code == 404


def test_ngo_creates_request_and_it_is_validated(client, ngo):
    ok = client.post("/ngo/requests", headers=ngo, json={"category": "Bread", "quantity_kg": 30,
                                                         "needed_by": iso(5)})
    assert ok.status_code == 201 and ok.json()["category"] == "bakery"
    assert client.post("/ngo/requests", headers=ngo, json={"category": "junk", "quantity_kg": 30,
                                                           "needed_by": iso(5)}).status_code == 422
    assert client.post("/ngo/requests", headers=ngo, json={"quantity_kg": -1, "needed_by": iso(5)}).status_code == 422
    assert client.post("/ngo/requests", headers=ngo, json={"quantity_kg": 5, "needed_by": iso(-1)}).status_code == 422
