import mongomock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import db as dbmod
from app.db import Base
from app.seed import seed
from app.services import events, mongo


@pytest.fixture()
def published(monkeypatch):
    """Capture RabbitMQ publishes instead of needing a broker."""
    sent: list[dict] = []
    monkeypatch.setattr(events, "publish_donation_created", lambda msgs: sent.extend(msgs))
    return sent


@pytest.fixture()
def mongo_db(monkeypatch):
    mdb = mongomock.MongoClient()["test"]
    monkeypatch.setattr(mongo, "get_mongo", lambda: mdb)
    return mdb


@pytest.fixture()
def session(monkeypatch, mongo_db, published):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    dbmod.SessionLocal.configure(bind=engine)
    with dbmod.SessionLocal() as s:
        seed(s)
    s = dbmod.SessionLocal()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def client(session):
    from app.main import app
    return TestClient(app)  # no lifespan: tests seed the DB themselves


def login(client, email: str, password: str = "demo123") -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin(client):
    return login(client, "admin@foodrescue.demo")


@pytest.fixture()
def donor(client):
    return login(client, "donor@foodrescue.demo")


@pytest.fixture()
def ngo(client):
    return login(client, "ngo@foodrescue.demo")
