"""Delta Lake history: created snapshot + status timeline, time travel, compaction."""
import json
from datetime import datetime, timedelta

import polars as pl

from app.config import settings
from app.services import history
from app.worker.consumer import process_message


def iso(h):
    return (datetime.utcnow() + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_donation(client, donor, published):
    r = client.post("/donations", headers=donor, json={"food_type": "Veg biryani", "category": "cooked_meals",
                                                       "quantity_kg": 20, "expiry_time": iso(5), "area": "Vashi"})
    assert r.status_code == 201, r.text
    for m in list(published):
        process_message(json.dumps(m).encode())
    published.clear()
    return r.json()["id"]


def test_full_timeline_in_delta(client, session, donor, ngo, admin, published):
    did = make_donation(client, donor, published)
    mid = client.get("/ngo/matches", headers=ngo).json()[0]["id"]
    client.post(f"/matches/{mid}/accept", headers=ngo)
    client.patch(f"/donations/{did}/status", headers=ngo, json={"status": "picked_up"})
    client.patch(f"/donations/{did}/status", headers=ngo, json={"status": "delivered"})

    created = pl.read_delta(f"{settings.delta_dir}/donation_history")
    assert created.filter(pl.col("donation_id") == did).height == 1

    h = client.get(f"/history/donations/{did}", headers=admin).json()
    assert h["created"]["food_type"] == "Veg biryani" and h["created"]["status"] == "listed"
    steps = [(t["from_status"], t["to_status"]) for t in h["timeline"]]
    assert steps == [("listed", "matched"), ("matched", "accepted"), ("accepted", "picked_up"),
                     ("picked_up", "delivered")]
    assert h["versions"]["status_events"] >= 3


def test_time_travel_returns_older_state(client, donor, ngo, admin, published):
    did = make_donation(client, donor, published)          # status_events v0 = listed->matched
    v0 = client.get("/history/versions", headers=admin).json()["status_events"]
    mid = client.get("/ngo/matches", headers=ngo).json()[0]["id"]
    client.post(f"/matches/{mid}/accept", headers=ngo)
    now = client.get(f"/history/donations/{did}", headers=admin).json()
    then = client.get(f"/history/donations/{did}?version={v0}", headers=admin).json()
    assert len(now["timeline"]) == len(then["timeline"]) + 1


def test_history_requires_admin(client, donor, ngo):
    assert client.get("/history/versions", headers=donor).status_code == 403
    assert client.get("/history/donations/1", headers=ngo).status_code == 403
    assert client.get("/history/donations/1").status_code == 401


def test_unknown_donation_has_empty_history(client, admin):
    h = client.get("/history/donations/999999", headers=admin).json()
    assert h["created"] is None and h["timeline"] == []


def test_optimize_compacts_small_files(client, donor, ngo, admin, published):
    make_donation(client, donor, published)
    for _ in range(3):
        history.record_status(1, "a", "b")
    out = client.post("/ops/delta/optimize", headers=admin).json()
    assert out["status_events"]["files_removed"] >= 2
    assert out["status_events"]["version"] >= 3


def test_delta_failure_never_breaks_the_pipeline(client, donor, monkeypatch, published):
    monkeypatch.setattr(settings, "delta_dir", "/proc/not-writable/delta")
    r = client.post("/donations", headers=donor, json={"food_type": "Bread", "category": "bakery", "quantity_kg": 5,
                                                       "expiry_time": iso(5), "area": "Vashi"})
    assert r.status_code == 201


def test_delta_can_be_disabled(client, donor, monkeypatch, published, tmp_path):
    monkeypatch.setattr(settings, "delta_enabled", False)
    client.post("/donations", headers=donor, json={"food_type": "Bread", "category": "bakery", "quantity_kg": 5,
                                                   "expiry_time": iso(5), "area": "Vashi"})
    assert not (tmp_path / "delta").exists()


def _writer(delta_dir, start, n):
    from app.config import settings as s
    s.delta_dir = delta_dir
    for i in range(start, start + n):
        history.record_status(i, "a", "b", note="mp")


def test_concurrent_processes_do_not_corrupt_the_delta_log(tmp_path):
    """Backend and worker are separate processes writing the same volume: the write lock must serialise them."""
    import multiprocessing as mp
    ctx = mp.get_context("spawn")  # clean interpreters, like the real backend and worker containers
    d = str(tmp_path / "shared")
    procs = [ctx.Process(target=_writer, args=(d, k * 1000, 15)) for k in range(4)]
    [p.start() for p in procs]
    [p.join(120) for p in procs]
    assert all(p.exitcode == 0 for p in procs)
    df = pl.read_delta(f"{d}/status_events")
    assert df.height == 60 and df["donation_id"].n_unique() == 60
    from deltalake import DeltaTable
    assert DeltaTable(f"{d}/status_events").version() == 59  # 60 commits, no gaps
