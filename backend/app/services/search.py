"""Elasticsearch search over donations and NGOs. Disabled (no-op) when ELASTICSEARCH_URL is empty.

Indexing is best-effort and idempotent (stable document ids), so a search outage never breaks the pipeline
and `reindex_all` can rebuild the index at any time.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings

log = logging.getLogger(__name__)
DONATIONS = "fr-donations"
NGOS = "fr-ngos"
_es = None

MAPPINGS = {
    DONATIONS: {"properties": {
        "food_type": {"type": "text"}, "donor": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
        "category": {"type": "keyword"}, "area": {"type": "keyword"}, "status": {"type": "keyword"},
        "quantity_kg": {"type": "float"}, "expiry_time": {"type": "date"}, "created_at": {"type": "date"},
        "location": {"type": "geo_point"}, "accepted_ngo_id": {"type": "integer"}}},
    NGOS: {"properties": {"name": {"type": "text"}, "area": {"type": "keyword"}, "location": {"type": "geo_point"}}},
}


def enabled() -> bool:
    return bool(settings.elasticsearch_url)


def _client():
    """Tests monkeypatch this function with a fake client."""
    global _es
    if _es is None:
        from elasticsearch import Elasticsearch
        _es = Elasticsearch(settings.elasticsearch_url, request_timeout=5)
    return _es


def ensure_indices() -> None:
    es = _client()
    for name, mapping in MAPPINGS.items():
        if not es.indices.exists(index=name):
            es.indices.create(index=name, mappings=mapping)


def donation_doc(d) -> dict:
    return {"food_type": d.food_type, "donor": d.donor.name if getattr(d, "donor", None) else None,
            "category": d.category, "area": d.area, "status": d.status, "quantity_kg": float(d.quantity_kg),
            "expiry_time": d.expiry_time.isoformat(), "created_at": d.created_at.isoformat(),
            "location": {"lat": d.lat, "lon": d.lng}, "accepted_ngo_id": d.accepted_ngo_id}


def _bulk(actions: list[dict]) -> None:
    from elasticsearch import helpers
    helpers.bulk(_client(), actions, refresh=False)


def index_donations(donations) -> None:
    if not enabled() or not donations:
        return
    try:
        ensure_indices()
        _bulk([{"_op_type": "index", "_index": DONATIONS, "_id": d.id, "_source": donation_doc(d)} for d in donations])
    except Exception as exc:  # noqa: BLE001
        log.warning("Elasticsearch indexing failed: %s", exc)


def update_status(donation_id: int, status: str, ngo_id: int | None = None) -> None:
    if not enabled():
        return
    try:
        doc = {"status": status}
        if ngo_id:
            doc["accepted_ngo_id"] = ngo_id
        _client().update(index=DONATIONS, id=donation_id, doc=doc)
    except Exception as exc:  # noqa: BLE001  (missing doc / ES down: reindex fixes it)
        log.debug("Elasticsearch status update skipped: %s", exc)


def reindex_all(db: Session) -> dict:
    from app.models import NGO, Donation
    ensure_indices()
    donations = db.scalars(select(Donation)).all()
    ngos = db.scalars(select(NGO)).all()
    _bulk([{"_op_type": "index", "_index": DONATIONS, "_id": d.id, "_source": donation_doc(d)} for d in donations])
    _bulk([{"_op_type": "index", "_index": NGOS, "_id": n.id,
            "_source": {"name": n.name, "area": n.area,
                        "location": {"lat": n.lat, "lon": n.lng} if n.lat is not None else None}} for n in ngos])
    _client().indices.refresh(index=f"{DONATIONS},{NGOS}")
    return {"donations": len(donations), "ngos": len(ngos)}


def build_query(q: str | None, category: str | None, area: str | None, status: str | None,
                min_kg: float | None, near: tuple[float, float] | None, radius_km: float) -> dict:
    must = [{"multi_match": {"query": q, "fields": ["food_type^3", "donor^2", "area", "category"],
                             "fuzziness": "AUTO"}}] if q else [{"match_all": {}}]
    flt = []
    if category:
        flt.append({"term": {"category": category}})
    if area:
        flt.append({"term": {"area": area}})
    if status:
        flt.append({"term": {"status": status}})
    if min_kg is not None:
        flt.append({"range": {"quantity_kg": {"gte": min_kg}}})
    if near:
        flt.append({"geo_distance": {"distance": f"{radius_km}km", "location": {"lat": near[0], "lon": near[1]}}})
    return {"bool": {"must": must, "filter": flt}}


def search_donations(q=None, category=None, area=None, status=None, min_kg=None, near=None, radius_km=15.0,
                     size=20) -> dict:
    query = build_query(q, category, area, status, min_kg, near, radius_km)
    res = _client().search(index=DONATIONS, query=query, size=size,
                           sort=["_score", {"expiry_time": "asc"}])
    hits = [{"id": int(h["_id"]), "score": h.get("_score"), **h["_source"]} for h in res["hits"]["hits"]]
    total = res["hits"]["total"]["value"] if isinstance(res["hits"]["total"], dict) else res["hits"]["total"]
    return {"total": total, "hits": hits}


def search_ngos(q: str | None = None, size: int = 20) -> dict:
    query = {"multi_match": {"query": q, "fields": ["name^2", "area"], "fuzziness": "AUTO"}} if q else {"match_all": {}}
    res = _client().search(index=NGOS, query=query, size=size)
    return {"total": len(res["hits"]["hits"]),
            "hits": [{"id": int(h["_id"]), **h["_source"]} for h in res["hits"]["hits"]]}


def ping() -> bool:
    try:
        return bool(enabled() and _client().ping())
    except Exception:  # noqa: BLE001
        return False
