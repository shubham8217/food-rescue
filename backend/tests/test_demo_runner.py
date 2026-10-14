import asyncio

from app.config import settings
from app.models import Donation, IngestBatch
from simulator.runner import DemoRunner


def test_runner_never_stops_when_direct_ingest_is_down(session, published, tmp_path, monkeypatch):
    """HTTP path unreachable -> every batch falls back to in-process ingest; CSVs still land in the inbox."""
    monkeypatch.setattr(settings, "inbox_dir", str(tmp_path))
    monkeypatch.setattr(settings, "api_internal_url", "http://127.0.0.1:9")  # nothing listens here
    r = DemoRunner()

    async def go():
        await r.start(duration_minutes=0.05, interval_seconds=1, speed=5, reset=True, start_hour=13)
        await asyncio.wait_for(r.task, timeout=60)

    asyncio.run(go())
    assert r.state == "finished" and r.total_batches == 3 and r.batch_no == 3
    assert r.fallbacks == 3 and r.direct_ok == 0
    assert len(list(tmp_path.glob("batch_*.csv"))) == 3
    session.expire_all()
    assert session.query(IngestBatch).count() == 3
    assert session.query(Donation).count() > 30


def test_runner_can_be_stopped(session, published, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "inbox_dir", str(tmp_path))
    monkeypatch.setattr(settings, "sim_direct_ingest", False)
    r = DemoRunner()

    async def go():
        await r.start(duration_minutes=10, interval_seconds=30, speed=1, reset=False, start_hour=None)
        await asyncio.sleep(0.5)
        assert r.running
        await r.stop()

    asyncio.run(go())
    assert r.state == "stopped" and not r.running
    assert len(list(tmp_path.glob("batch_*.csv"))) == 1  # first batch is sent immediately


def test_demo_endpoints_validate_and_reset(client, admin, session, published):
    assert client.post("/demo/speed", headers=admin, json={"speed": 3}).status_code == 422
    assert client.post("/demo/start", headers=admin, json={"speed": 4}).status_code == 422
    assert client.post("/demo/start", headers=admin, json={"duration_minutes": 0}).status_code == 422
    assert client.get("/demo/status", headers=admin).json()["state"] in ("idle", "finished", "stopped")
    assert client.post("/demo/reset", headers=admin).json() == {"ok": True}
    live = client.get("/admin/live", headers=admin).json()
    assert set(live) >= {"demo", "stats", "events", "pins", "rejected", "last_event_id"}
