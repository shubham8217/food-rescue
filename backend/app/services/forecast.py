"""Surplus forecast per area and hour, plus a history backfill so there is something to learn from.

Model: for each (area, hour-of-day, IST) take a recency-weighted mean of kg donated over the history days
(weight 0.85 ** age_in_days, zero-filled for hours with no donations, outliers capped at 3x the median for that hour).
It is deliberately simple and explainable: lunch and dinner peaks come straight from the data.
"""
import random
from datetime import datetime, timedelta

import polars as pl
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.geo import AREAS
from app.models import Donation, Donor
from app.services.analytics import donations_frame
from app.services.cleaning import clean_records
from app.utils import utcnow

IST = timedelta(hours=5, minutes=30)
DECAY = 0.85


def forecast(db: Session, area: str | None = None, hours: int = 24, now: datetime | None = None) -> dict:
    now = now or utcnow()
    df = donations_frame(db)
    if area:
        df = df.filter(pl.col("area") == area)
    areas = [area] if area else sorted(AREAS)
    if df.is_empty():
        return {"area": area, "history_days": 0, "points": [], "note": "No history yet. Run a backfill or the live demo."}

    df = df.with_columns((pl.col("created_at") + IST).alias("local")).with_columns(
        pl.col("local").dt.date().alias("day"), pl.col("local").dt.hour().alias("hour"))
    days = sorted(df["day"].unique().to_list())
    today = (now + IST).date()
    # zero-filled grid (area x day x hour) so quiet hours count as zero, not "missing"
    grid = pl.DataFrame({"area": areas}).join(pl.DataFrame({"day": days}), how="cross") \
        .join(pl.DataFrame({"hour": list(range(24))}), how="cross")
    kg = df.group_by(["area", "day", "hour"]).agg(pl.col("quantity_kg").sum().alias("kg"),
                                                  pl.len().alias("n"))
    full = grid.join(kg, on=["area", "day", "hour"], how="left").with_columns(
        pl.col("kg").fill_null(0.0), pl.col("n").fill_null(0)).with_columns(
        (pl.lit(DECAY) ** (pl.lit(today) - pl.col("day")).dt.total_days().cast(pl.Float64)).alias("w"))
    # Robustness: one demo burst (dozens of donations in a single hour) must not distort the learned pattern.
    # Each (area, day, hour) cell is capped at 3x the median of the same (area, hour) across days, plus a small floor.
    full = full.with_columns(pl.col("n").cast(pl.Float64)).with_columns(
        pl.min_horizontal(pl.col("kg"), pl.col("kg").median().over(["area", "hour"]) * 3 + 5).alias("kg"),
        pl.min_horizontal(pl.col("n"), pl.col("n").median().over(["area", "hour"]) * 3 + 1).alias("n"))
    prof = full.group_by(["area", "hour"]).agg(
        ((pl.col("kg") * pl.col("w")).sum() / pl.col("w").sum()).alias("kg"),
        ((pl.col("n") * pl.col("w")).sum() / pl.col("w").sum()).alias("n"))
    lookup = {(r["area"], r["hour"]): (r["kg"], r["n"]) for r in prof.iter_rows(named=True)}

    points = []
    start = (now + IST).replace(minute=0, second=0, microsecond=0)
    for i in range(1, hours + 1):
        t = start + timedelta(hours=i)
        kgs = sum(lookup.get((a, t.hour), (0, 0))[0] for a in areas)
        ns = sum(lookup.get((a, t.hour), (0, 0))[1] for a in areas)
        points.append({"ts": (t - IST).isoformat() + "Z", "hour": t.hour, "predicted_kg": round(kgs, 1),
                       "predicted_donations": round(ns, 1)})
    return {"area": area, "history_days": len(days), "points": points, "note": None}


def backfill_history(db: Session, days: int = 7, seed: int | None = 42, now: datetime | None = None) -> dict:
    """Insert `days` of synthetic past donations (source='history'): peaks at lunch and dinner."""
    from simulator.generator import generate_batch, intensity

    now = (now or utcnow()).replace(minute=0, second=0, microsecond=0)
    rng = random.Random(seed)
    db.execute(delete(Donation).where(Donation.source == "history"))
    db.commit()
    donors: dict[str, Donor] = {}
    count = 0
    for back in range(days * 24, 0, -1):
        t = now - timedelta(hours=back)
        local_hour = (t + IST).hour
        rows, _ = generate_batch(t + timedelta(minutes=rng.randint(0, 59)), rng, hour=float(local_hour))
        res = clean_records([r for r in rows if r["record_type"] == "donation"], "donation", t)
        keep = max(1, round(len(res.clean) * intensity(float(local_hour))))  # quiet at night, busy at meals
        for r in res.clean[:keep]:
            donor = donors.get(r["org_name"]) or db.scalar(select(Donor).where(Donor.name == r["org_name"]))
            if donor is None:
                donor = Donor(name=r["org_name"], area=r["area"], lat=r["lat"], lng=r["lng"])
                db.add(donor)
                db.flush()
            donors[r["org_name"]] = donor
            created = t + timedelta(minutes=rng.randint(0, 59))
            status = "delivered" if rng.random() > 0.15 else "expired"
            db.add(Donation(donor_id=donor.id, food_type=r["food_type"], category=r["category"],
                            quantity_kg=r["quantity_kg"], expiry_time=r["expiry_time"], lat=r["lat"], lng=r["lng"],
                            area=r["area"], status=status, source="history", dedupe_key=None, created_at=created,
                            status_changed_at=created + timedelta(minutes=rng.randint(40, 180))))
            count += 1
        if back % 24 == 0:
            db.flush()
    db.commit()
    return {"days": days, "donations": count}
