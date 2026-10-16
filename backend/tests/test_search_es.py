"""Elasticsearch integration against a fake client (no ES needed for the unit tests)."""
import json
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.services import search
from app.worker.consumer import process_message


class FakeIndices:
    def __init__(self):
        self.created = []

    def exists(self, index):
        return index in self.created

    def create(self, index, mappings):
        self.created.append(index)

    def refresh(self, index):
        pass


class FakeES:
    def __init__(self):
        self.indices = FakeIndices()
        self.docs = {}
        self.updates = []
        self.last_query = None

    def update(self, index, id, doc):
        self.updates.append((int(id), doc))

    def search(self, index, query, size=20, sort=None):
        self.last_query = (index, query, size, sort)
        hits = [{"_id": str(i), "_score": 1.2, "_source": d} for i, d in self.docs.items()][:size]
        return {"hits": {"total": {"value": len(hits)}, "hits": hits}}

    def ping(self):
        return True


@pytest.fixture()
def es(monkeypatch):
    fake = FakeES()
    monkeypatch.setattr(settings, "elasticsearch_url", "http://fake:9200")
    monkeypatch.setattr(search, "_client", lambda: fake)

    def fake_bulk(actions):
        for a in actions:
            fake.docs[int(a["_id"])] = a["_source"]
    monkeypatch.setattr(search, "_bulk", fake_bulk)
    return fake


def iso(h):
    return (datetime.utcnow() + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_donations_are_indexed_on_ingest_and_status_updates_follow(client, session, es, donor, ngo, published):
    r = client.post("/donations", headers=donor, json={"food_type": "Veg biryani", "category": "cooked_meals",
                                                       "quantity_kg": 12, "expiry_time": iso(5), "area": "Vashi"})
    did = r.json()["id"]
    assert es.docs[did]["food_type"] == "Veg biryani" and es.docs[did]["location"]["lat"] > 19
    assert es.docs[did]["donor"] == "Demo Restaurant (Vashi)" and "fr-donations" in es.indices.created
    for m in list(published):
        process_message(json.dumps(m).encode())
    assert (did, {"status": "matched"}) in es.updates
    mid = client.get("/ngo/matches", headers=ngo).json()[0]["id"]
    client.post(f"/matches/{mid}/accept", headers=ngo)
    assert any(u[0] == did and u[1]["status"] == "accepted" and u[1]["accepted_ngo_id"] for u in es.updates)


def test_search_endpoint_builds_filters_and_returns_hits(client, es, ngo, donor, published):
    client.post("/donations", headers=donor, json={"food_type": "Veg biryani", "category": "cooked_meals",
                                                   "quantity_kg": 12, "expiry_time": iso(5), "area": "Vashi"})
    r = client.get("/search/donations?q=biryani&category=cooked_meals&area=Vashi&min_kg=5&lat=19.07&lng=72.99&radius_km=10",
                   headers=ngo)
    assert r.status_code == 200 and r.json()["total"] == 1 and r.json()["hits"][0]["food_type"] == "Veg biryani"
    q = es.last_query[1]["bool"]
    assert q["must"][0]["multi_match"]["query"] == "biryani"
    flt = q["filter"]
    assert {"term": {"category": "cooked_meals"}} in flt and {"term": {"area": "Vashi"}} in flt
    assert {"range": {"quantity_kg": {"gte": 5.0}}} in flt
    assert any("geo_distance" in f and f["geo_distance"]["distance"] == "10.0km" for f in flt)


def test_build_query_without_filters_is_match_all():
    q = search.build_query(None, None, None, None, None, None, 15)
    assert q == {"bool": {"must": [{"match_all": {}}], "filter": []}}


def test_reindex_indexes_donations_and_ngos(client, session, es, admin, donor, published):
    client.post("/donations", headers=donor, json={"food_type": "Bread", "category": "bakery", "quantity_kg": 5,
                                                   "expiry_time": iso(5), "area": "Vashi"})
    es.docs.clear()
    out = client.post("/search/reindex", headers=admin).json()
    assert out["donations"] == 1 and out["ngos"] >= 8 and len(es.docs) >= 9


def test_ngo_search(client, es, ngo, admin):
    client.post("/search/reindex", headers=admin)
    r = client.get("/search/ngos?q=food", headers=ngo)
    assert r.status_code == 200 and r.json()["total"] >= 1


def test_search_disabled_returns_clear_503(client, ngo):
    r = client.get("/search/donations?q=x", headers=ngo)
    assert r.status_code == 503 and "search" in r.json()["detail"].lower()
    assert client.get("/search/status", headers=ngo).json() == {"enabled": False, "reachable": False}


def test_search_backend_error_is_503_not_500(client, ngo, monkeypatch):
    monkeypatch.setattr(settings, "elasticsearch_url", "http://down:9200")

    def boom():
        raise ConnectionError("nope")
    monkeypatch.setattr(search, "_client", boom)
    assert client.get("/search/donations?q=x", headers=ngo).status_code == 503


def test_indexing_failure_never_breaks_donation_creation(client, donor, monkeypatch, published):
    monkeypatch.setattr(settings, "elasticsearch_url", "http://down:9200")

    def boom():
        raise ConnectionError("nope")
    monkeypatch.setattr(search, "_client", boom)
    r = client.post("/donations", headers=donor, json={"food_type": "Bread", "category": "bakery", "quantity_kg": 5,
                                                       "expiry_time": iso(5), "area": "Vashi"})
    assert r.status_code == 201


def test_search_roles(client, donor):
    assert client.get("/search/donations", headers=donor).status_code == 403
    assert client.get("/search/donations").status_code == 401
