import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db as dbmod
from app.config import settings
from app.routers import auth, demo, donations, ingest, ngo
from app.seed import seed
from simulator.lifecycle import lifecycle_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    with dbmod.SessionLocal() as s:
        seed(s)
    task = asyncio.create_task(lifecycle_loop())
    yield
    task.cancel()


app = FastAPI(title="FoodRescue API", version="0.5.0", lifespan=lifespan,
              description="Surplus food -> NGOs matching for Navi Mumbai.")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

for r in (auth.router, donations.router, ngo.router, ingest.router, demo.router):
    app.include_router(r)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
