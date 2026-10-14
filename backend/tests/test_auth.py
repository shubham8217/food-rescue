import pytest

from app.security import create_access_token, hash_password, verify_password
from tests.conftest import login


def test_bcrypt_roundtrip():
    h = hash_password("demo123")
    assert h != "demo123" and h.startswith("$2")
    assert verify_password("demo123", h) and not verify_password("wrong", h)


@pytest.mark.parametrize("email,role", [("donor@foodrescue.demo", "donor"), ("ngo@foodrescue.demo", "ngo"),
                                        ("admin@foodrescue.demo", "admin")])
def test_seed_accounts_can_login(client, email, role):
    r = client.post("/auth/login", json={"email": email, "password": "demo123"})
    assert r.status_code == 200 and r.json()["role"] == role
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.json()["email"] == email


def test_wrong_password_and_unknown_user(client):
    assert client.post("/auth/login", json={"email": "donor@foodrescue.demo", "password": "nope"}).status_code == 401
    assert client.post("/auth/login", json={"email": "ghost@x.com", "password": "demo123"}).status_code == 401


def test_oauth_form_login_for_swagger(client):
    r = client.post("/auth/token", data={"username": "admin@foodrescue.demo", "password": "demo123"})
    assert r.status_code == 200 and r.json()["access_token"]


def test_missing_and_garbage_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_expired_token_rejected(client):
    tok = create_access_token("admin@foodrescue.demo", "admin", minutes=-5)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_role_guards(client, admin, donor, ngo):
    # admin-only
    assert client.post("/demo/start", headers=donor).status_code == 403
    assert client.post("/demo/start", headers=ngo).status_code == 403
    assert client.get("/stats/summary", headers=donor).status_code == 403
    assert client.get("/stats/summary", headers=admin).status_code == 200
    assert client.get("/donations", headers=donor).status_code == 403
    # donor-only
    assert client.get("/donations/mine", headers=ngo).status_code == 403
    assert client.post("/donations", headers=ngo, json={}).status_code in (403, 422)
    # ngo-only
    assert client.get("/ngo/matches", headers=donor).status_code == 403
    assert client.get("/ngo/matches", headers=ngo).status_code == 200
    # ingest: ngo not allowed
    assert client.post("/ingest/batch", headers=ngo, json=[{}]).status_code == 403
    # unauthenticated
    assert client.get("/ngo/matches").status_code == 401


def test_websocket_requires_admin_token(client, donor, admin):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/live?token=bad"):
            pass
    donor_token = donor["Authorization"].split()[1]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/live?token={donor_token}"):
            pass
    admin_token = admin["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/live?token={admin_token}") as ws:
        data = ws.receive_json()
        assert "stats" in data and "demo" in data
