import asyncio

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app import db as dbmod
from app.config import settings
from app.constants import ROLE_ADMIN
from app.db import get_db
from app.deps import require_roles
from app.models import User
from app.schemas import DemoStartIn, SpeedIn
from app.security import decode_token
from app.services import stats
from simulator.runner import runner

router = APIRouter(tags=["demo"])
admin_only = require_roles(ROLE_ADMIN)


def _demo_on():
    if not settings.demo_enabled:
        raise HTTPException(404, "The live demo is disabled in this environment (DEMO_ENABLED=false)")


@router.get("/demo/status")
def demo_status(user: User = Depends(admin_only)):
    return runner.status()


@router.post("/demo/start")
async def demo_start(body: DemoStartIn | None = None, user: User = Depends(admin_only)):
    _demo_on()
    body = body or DemoStartIn()
    if body.speed not in (1, 2, 5):
        raise HTTPException(422, "speed must be 1, 2 or 5")
    if runner.running:
        raise HTTPException(409, "Demo is already running")
    if body.duration_minutes <= 0 or body.interval_seconds < 1:
        raise HTTPException(422, "duration_minutes must be > 0 and interval_seconds >= 1")
    await runner.start(body.duration_minutes, body.interval_seconds, body.speed, body.reset, body.start_hour)
    return runner.status()


@router.post("/demo/stop")
async def demo_stop(user: User = Depends(admin_only)):
    await runner.stop()
    return runner.status()


@router.post("/demo/speed")
def demo_speed(body: SpeedIn, user: User = Depends(admin_only)):
    if body.speed not in (1, 2, 5):
        raise HTTPException(422, "speed must be 1, 2 or 5")
    runner.speed = body.speed
    return runner.status()


@router.post("/demo/reset")
def demo_reset(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    _demo_on()
    if runner.running:
        raise HTTPException(409, "Stop the demo before resetting")
    stats.reset_data(db)
    return {"ok": True}


@router.get("/stats/summary")
def stats_summary(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    return stats.summary(db)


@router.get("/admin/live")
def admin_live(after: int = 0, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Polling fallback for the WebSocket: same payload."""
    return stats.live_payload(db, after, first=after == 0)


def _payload(after: int, first: bool) -> dict:
    s = dbmod.SessionLocal()
    try:
        return stats.live_payload(s, after, first)
    finally:
        s.close()


@router.websocket("/ws/live")
async def ws_live(ws: WebSocket, token: str = Query("")):
    try:
        claims = decode_token(token)
        if claims.get("role") != ROLE_ADMIN:
            raise jwt.InvalidTokenError("not admin")
    except jwt.PyJWTError:
        await ws.close(code=4403)
        return
    await ws.accept()
    last_id, first = 0, True
    try:
        while True:
            payload = await run_in_threadpool(_payload, last_id, first)
            last_id, first = payload["last_event_id"], False
            await ws.send_json(payload)
            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, RuntimeError):
        pass
