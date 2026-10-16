"""Production mode: no demo accounts, simulator disabled, strong secrets enforced."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base
from app.models import NGO, Donor, User
from app.seed import seed


@pytest.fixture()
def empty_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


def test_production_seed_creates_only_the_configured_admin(empty_db, monkeypatch):
    monkeypatch.setattr(settings, "seed_demo_users", False)
    monkeypatch.setattr(settings, "admin_email", "Boss@Example.org")
    monkeypatch.setattr(settings, "admin_password", "a-long-real-password")
    seed(empty_db)
    seed(empty_db)  # idempotent
    users = empty_db.query(User).all()
    assert [(u.email, u.role) for u in users] == [("boss@example.org", "admin")]
    assert empty_db.query(Donor).count() == 0 and empty_db.query(NGO).count() == 0


def test_production_seed_refuses_a_weak_admin_password(empty_db, monkeypatch):
    monkeypatch.setattr(settings, "seed_demo_users", False)
    monkeypatch.setattr(settings, "admin_password", "short")
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        seed(empty_db)


def test_demo_seed_still_creates_the_three_demo_accounts(empty_db):
    seed(empty_db)
    assert {u.email for u in empty_db.query(User)} == {"admin@foodrescue.demo", "donor@foodrescue.demo",
                                                       "ngo@foodrescue.demo"}


def test_live_demo_endpoints_are_404_when_disabled(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "demo_enabled", False)
    r = client.post("/demo/start", headers=admin, json={})
    assert r.status_code == 404 and "disabled" in r.json()["detail"]
    assert client.post("/demo/reset", headers=admin).status_code == 404
    assert client.get("/demo/status", headers=admin).status_code == 200  # read-only status stays available
