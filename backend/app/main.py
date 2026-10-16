import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db as dbmod
from app.config import settings
from app.routers import analytics, auth, demo, donations, health, history, ingest, ngo, ops, search
from app.seed import seed
from simulator.lifecycle import lifecycle_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("pika").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.app_env == "production" and (len(settings.jwt_secret) < 32 or "change-me" in settings.jwt_secret):
        raise RuntimeError("Refusing to start in production with a weak/default JWT_SECRET")
    with dbmod.SessionLocal() as s:
        seed(s)
    task = asyncio.create_task(lifecycle_loop())
    yield
    task.cancel()


app = FastAPI(title="FoodRescue API", version="1.0.0", lifespan=lifespan,
              description="Surplus food -> NGOs matching for Navi Mumbai.")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

for r in (auth.router, donations.router, ngo.router, ingest.router, demo.router, analytics.router, search.router,
          history.router, health.router, ops.router):
    app.include_router(r)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
