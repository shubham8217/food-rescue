"""MongoDB access: raw ingest rows and event payloads live here (Postgres holds clean data)."""
import logging

from pymongo import MongoClient

from app.config import settings

log = logging.getLogger(__name__)
_client: MongoClient | None = None


def get_mongo():
    """Returns the Mongo database. Tests monkeypatch this function with a mongomock database."""
    global _client
    if _client is None:
        _client = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=3000)
    return _client[settings.mongo_db]


def reset_collections() -> None:
    mdb = get_mongo()
    for name in ("raw_ingest", "events"):
        mdb[name].delete_many({})
