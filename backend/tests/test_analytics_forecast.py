"""DuckDB analytics endpoints, history backfill and the forecast."""
import json
from datetime import datetime, timedelta

from app.models import Donation
from app.services import forecast as fc
from app.services import stats
from app.worker.consumer import process_message


def seed_history(session, days=3):
    return fc.backfill_history(session, days=days, seed=1)


def test_backfill_creates_history_and_is_hidden_from_live_stats(client, session, admin):
    out = client.post("/forecast/backfill?days=2", headers=admin).json()
    assert out["days"] == 2 and out["donations"] > 200
    assert session.query(Donation).filter_by(source="history").count() == out["donations"]
    live = stats.summary(session)  # live counters ignore history
    assert live["total_donations"] == 0 and live["kg_rescued"] == 0
    # and a reset keeps the history
    stats.reset_data(session)
    assert session.query(Donation).filter_by(source="history").count() == out["donations"]


def test_backfill_replaces_old_history(client, session, admin):
    a = client.post("/forecast/backfill?days=1", headers=admin).json()["donations"]
    client.post("/forecast/backfill?days=1", headers=admin)
    assert session.query(Donation).filter_by(source="history").count() <= a * 1.5


def test_summary_numbers_are_consistent(client, session, admin):
    seed_history(session)
    s = client.get("/analytics/summary", headers=admin).json()
    n = session.query(Donation).count()
    assert s["total_donations"] == n
    assert 0.7 < s["delivery_rate"] < 0.95 and abs(s["delivery_rate"] + s["expired_rate"] - 1) < 0.01
    assert abs(s["meals"] - s["kg_rescued"] / 0.4) <= 1  # kg is rounded to 0.1, meals are not
    assert s["kg_rescued"] <= s["total_kg"]


def test_by_area_by_category_funnel_top(client, session, admin):
    seed_history(session)
    areas = client.get("/analytics/by-area", headers=admin).json()
    assert {a["area"] for a in areas} >= {"Nerul", "Vashi", "Airoli"}
    assert areas == sorted(areas, key=lambda a: -a["kg"])
    cats = client.get("/analytics/by-category", headers=admin).json()
    assert {c["category"] for c in cats} <= {"cooked_meals", "bakery", "produce", "dairy", "packaged", "beverages"}
    stages = client.get("/analytics/funnel", headers=admin).json()
    counts = [s["count"] for s in stages]
    assert [s["stage"] for s in stages] == ["listed", "matched", "accepted", "picked_up", "delivered"]
    assert counts == sorted(counts, reverse=True) and counts[0] == session.query(Donation).count()
    top = client.get("/analytics/top", headers=admin).json()
    assert len(top["donors"]) == 5


def test_timeline_is_zero_filled_hourly(client, session, admin):
    seed_history(session, days=2)
    t = client.get("/analytics/timeline?hours=24", headers=admin).json()
    assert 24 <= len(t) <= 26
    assert all(a["ts"] < b["ts"] for a, b in zip(t, t[1:]))


def test_rejection_reasons_grouped(client, session, admin, published):
    rows = [{"org_name": "X", "food_type": "Stale bread", "category": "bakery", "quantity_kg": 5,
             "expiry_time": (datetime.utcnow() + timedelta(hours=5)).isoformat(), "area": "Vashi"},
            {"org_name": "X", "food_type": "Stale cake", "category": "bakery", "quantity_kg": 5,
             "expiry_time": (datetime.utcnow() + timedelta(hours=5)).isoformat(), "area": "Vashi"}]
    client.post("/ingest/batch", headers=admin, json=rows)
    rej = client.get("/analytics/rejections", headers=admin).json()
    assert rej[0] == {"reason": "unsafe item", "count": 2}


def test_forecast_learns_lunch_and_dinner_peaks(client, session, admin):
    seed_history(session, days=5)
    f = client.get("/forecast?hours=24", headers=admin).json()
    assert f["history_days"] >= 5 and len(f["points"]) == 24
    by_hour = {p["hour"]: p["predicted_kg"] for p in f["points"]}
    assert by_hour[13] > by_hour[3] * 2 and by_hour[20] > by_hour[4] * 2


def test_forecast_for_one_area_and_empty_history(client, session, admin):
    assert client.get("/forecast", headers=admin).json()["points"] == []
    seed_history(session, days=2)
    one = client.get("/forecast?area=Nerul&hours=6", headers=admin).json()
    full = client.get("/forecast?hours=6", headers=admin).json()
    assert len(one["points"]) == 6
    assert sum(p["predicted_kg"] for p in one["points"]) < sum(p["predicted_kg"] for p in full["points"])


def test_avg_minutes_to_accept_from_delta(client, session, donor, ngo, admin, published):
    client.post("/donations", headers=donor, json={"food_type": "Rice", "category": "cooked_meals", "quantity_kg": 9,
                                                   "expiry_time": (datetime.utcnow() + timedelta(hours=5)).isoformat(),
                                                   "area": "Vashi"})
    for m in list(published):
        process_message(json.dumps(m).encode())
    mid = client.get("/ngo/matches", headers=ngo).json()[0]["id"]
    client.post(f"/matches/{mid}/accept", headers=ngo)
    s = client.get("/analytics/summary", headers=admin).json()
    assert s["avg_minutes_to_accept"] is not None and s["avg_minutes_to_accept"] >= 0


def test_analytics_requires_admin(client, donor, ngo):
    for path in ("/analytics/summary", "/analytics/by-area", "/forecast", "/health/pipeline"):
        assert client.get(path, headers=donor).status_code == 403
        assert client.get(path, headers=ngo).status_code == 403
        assert client.get(path).status_code == 401


def test_forecast_ignores_a_one_hour_demo_burst(client, session, admin):
    """A burst of simulated donations in one hour must not dominate the learned hourly pattern."""
    from datetime import datetime
    seed_history(session, days=5)
    before = client.get("/forecast?area=Nerul&hours=24", headers=admin).json()["points"]
    donor_id = session.query(Donation.donor_id).first()[0]
    now = datetime.utcnow()
    for _ in range(150):
        session.add(Donation(donor_id=donor_id, food_type="burst", category="cooked_meals", quantity_kg=50,
                             expiry_time=now, lat=19.03, lng=73.03, area="Nerul", status="delivered", source="sim",
                             created_at=now, status_changed_at=now))
    session.commit()
    after = client.get("/forecast?area=Nerul&hours=24", headers=admin).json()["points"]
    worst = max(a["predicted_kg"] / max(b["predicted_kg"], 1) for a, b in zip(after, before))
    assert worst < 2.5, f"burst inflated one hour {worst:.1f}x"
