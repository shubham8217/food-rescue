"""Service key (NiFi/Airflow), ops endpoints, pipeline health, decline flow, production guard."""
import asyncio
import json
from datetime import datetime, timedelta

import pytest

from app.models import AnalyticsSnapshot, Donation, QualityReport
from app.services import health
from app.worker.consumer import process_message

KEY = {"X-API-Key": "test-service-key"}


def iso(h):
    return (datetime.utcnow() + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def row(**kw):
    base = {"record_type": "donation", "org_name": "NiFi Bakery", "food_type": "Bread", "category": "bakery",
            "quantity_kg": 10, "expiry_time": iso(6), "area": "Vashi"}
    base.update(kw)
    return base


def test_service_key_can_ingest_csv_like_nifi(client, published):
    csv_text = ("record_type,org_name,food_type,category,quantity_kg,expiry_time,lat,lng,area\n"
                f"donation,NiFi Cafe,Sandwiches,bakery,8,{iso(5)},,,Nerul\n")
    r = client.post("/ingest/batch", headers={**KEY, "Content-Type": "text/csv"}, content=csv_text)
    assert r.status_code == 200 and r.json()["accepted_donations"] == 1


def test_bad_or_missing_service_key_rejected(client):
    assert client.post("/ingest/batch", headers={"X-API-Key": "wrong"}, json=[row()]).status_code == 401
    assert client.post("/ops/expire", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/ops/expire").status_code == 401


def test_service_key_disabled_when_not_configured(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ingest_api_key", "")
    assert client.post("/ops/expire", headers={"X-API-Key": ""}).status_code == 401
    assert client.post("/ops/expire", headers={"X-API-Key": "anything"}).status_code == 401


def test_ops_endpoints_reject_non_admin_users(client, donor, ngo):
    for h in (donor, ngo):
        assert client.post("/ops/expire", headers=h).status_code == 403
        assert client.post("/ops/delta/optimize", headers=h).status_code == 403


def test_expire_stale_marks_old_donations(client, session, published):
    client.post("/ingest/batch", headers=KEY, json=[row()])
    d = session.query(Donation).first()
    d.expiry_time = datetime.utcnow() - timedelta(minutes=1)
    session.commit()
    assert client.post("/ops/expire", headers=KEY).json() == {"expired": 1}
    session.expire_all()
    assert session.query(Donation).first().status == "expired"
    assert client.post("/ops/expire", headers=KEY).json() == {"expired": 0}


def test_analytics_snapshot_and_quality_report_are_stored(client, session, published):
    client.post("/ingest/batch", headers=KEY, json=[row(), row(), row(food_type="Stale cake")])
    snap = client.post("/ops/analytics/snapshot", headers=KEY).json()
    assert snap["data"]["total_donations"] == 1
    rep = client.post("/ops/quality-report", headers=KEY).json()
    assert rep["rows"] == 3 and rep["rejected"] == 2 and rep["duplicate_rows"] == 1
    assert rep["reject_rate"] == pytest.approx(0.667, abs=0.001)
    session.expire_all()
    assert session.query(AnalyticsSnapshot).count() == 1 and session.query(QualityReport).count() == 1


@pytest.fixture()
def rabbit_ok(monkeypatch):
    monkeypatch.setattr(health, "check_rabbitmq", lambda: {"ok": True, "detail": "connected", "queue_depth": 3,
                                                           "consumers": 1, "published": 10, "delivered": 7})


def test_pipeline_health_shape_and_numbers(client, session, admin, published, rabbit_ok):
    client.post("/ingest/batch", headers=admin, json=[row(), row(food_type="Stale cake")])
    h = client.get("/health/pipeline", headers=admin).json()
    assert h["services"]["postgres"]["ok"] and h["services"]["mongo"]["ok"]
    assert h["services"]["rabbitmq"]["queue_depth"] == 3 and h["services"]["worker"]["ok"] is True
    assert h["services"]["elasticsearch"]["ok"] is None and h["services"]["nifi"]["ok"] is None
    p = h["pipeline"]
    assert p["rows_last_5min"] == 2 and p["batches_last_5min"] == 1 and p["reject_rate_1h"] == 0.5
    assert len(h["throughput"]) >= 15 and sum(t["rows"] for t in h["throughput"]) == 2
    assert h["alerts"] == []


def test_health_alerts_when_broker_down_and_lag(client, session, admin, published, monkeypatch):
    monkeypatch.setattr(health, "check_rabbitmq", lambda: {"ok": False, "detail": "unreachable", "queue_depth": None,
                                                           "consumers": 0})
    client.post("/ingest/batch", headers=admin, json=[row()])
    d = session.query(Donation).first()
    d.created_at = datetime.utcnow() - timedelta(minutes=10)
    session.commit()
    h = client.get("/health/pipeline", headers=admin).json()
    assert any("rabbitmq is down" in a for a in h["alerts"])
    assert any("unmatched donation" in a for a in h["alerts"])
    assert h["pipeline"]["oldest_unmatched_age_s"] >= 600


def test_optional_services_report_disabled_or_down(monkeypatch):
    from app.config import settings
    assert health._http_ok("", "/x")["ok"] is None
    monkeypatch.setattr(settings, "nifi_url", "http://127.0.0.1:9")
    assert health._http_ok(settings.nifi_url, "/nifi-api/flow/about")["ok"] is False


def test_ngo_can_decline_and_donation_returns_to_pool(client, session, donor, ngo, published):
    client.post("/donations", headers=donor, json={"food_type": "Rice", "category": "cooked_meals", "quantity_kg": 9,
                                                   "expiry_time": iso(5), "area": "Nerul"})
    for m in list(published):
        process_message(json.dumps(m).encode())
    mine = client.get("/ngo/matches", headers=ngo).json()
    assert mine
    r = client.post(f"/matches/{mine[0]['id']}/decline", headers=ngo)
    assert r.status_code == 200
    assert all(m["id"] != mine[0]["id"] for m in client.get("/ngo/matches", headers=ngo).json())
    # declined match can neither be accepted nor declined again
    assert client.post(f"/matches/{mine[0]['id']}/accept", headers=ngo).status_code == 409
    assert client.post(f"/matches/{mine[0]['id']}/decline", headers=ngo).status_code == 409
    assert client.post("/matches/99999/decline", headers=ngo).status_code == 404
    # the other NGOs still see it
    session.expire_all()
    assert session.query(Donation).first().status == "matched"


def test_decline_roles(client, donor, admin):
    assert client.post("/matches/1/decline", headers=donor).status_code == 403
    assert client.post("/matches/1/decline", headers=admin).status_code == 403


def test_production_refuses_weak_secret(monkeypatch):
    from app.config import settings
    from app.main import app, lifespan
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "dev-secret-change-me-please-32-bytes-min")

    async def go():
        async with lifespan(app):
            pass
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        asyncio.run(go())
