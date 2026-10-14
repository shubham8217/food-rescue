"""Realistic Navi Mumbai surplus-food batch generator (pure; seedable for tests).

Volume follows the day: peaks around lunch (~13:30) and dinner (~20:30) IST. About 10% of rows
are deliberately dirty (duplicates, expired, bad category, missing fields, unsafe items).
"""
import csv
import math
import os
import random
from datetime import datetime, timedelta

from app.geo import AREAS
from app.seed import SEED_NGOS

IST_OFFSET = timedelta(hours=5, minutes=30)
CSV_COLUMNS = ["record_type", "org_name", "food_type", "category", "quantity_kg", "expiry_time", "lat", "lng", "area"]
DIRTY_RATE = 0.10

DONORS = [
    ("Vashi Sweets & Bakers", "Vashi", "bakery"), ("Hotel Sagar Vashi", "Vashi", "restaurant"),
    ("Inorbit Food Court Vashi", "Vashi", "restaurant"), ("Nerul Dosa Corner", "Nerul", "restaurant"),
    ("Sagar Ratna Nerul", "Nerul", "restaurant"), ("Nerul Fresh Mart", "Nerul", "supermarket"),
    ("Belapur Bakery House", "Belapur", "bakery"), ("CBD Corporate Canteen", "Belapur", "cafe"),
    ("Kharghar Spice Kitchen", "Kharghar", "restaurant"), ("Central Park Cafe Kharghar", "Kharghar", "cafe"),
    ("Kharghar Super Bazaar", "Kharghar", "supermarket"), ("Sanpada Chaat Centre", "Sanpada", "restaurant"),
    ("Sanpada Daily Fresh", "Sanpada", "supermarket"), ("Airoli Biryani House", "Airoli", "restaurant"),
    ("Airoli IT Park Cafeteria", "Airoli", "cafe"), ("Mindspace Foods Airoli", "Airoli", "cafe"),
    ("Seawoods Grand Central Mall", "Seawoods", "supermarket"), ("Seawoods Bake Studio", "Seawoods", "bakery"),
    ("Palm Beach Dhaba", "Nerul", "restaurant"), ("Raghuleela Foods Vashi", "Vashi", "supermarket"),
]

# category -> [(food, min_kg, max_kg, min_shelf_h, max_shelf_h)]
FOODS = {
    "cooked_meals": [("Veg biryani", 8, 40, 2, 5), ("Dal rice", 10, 45, 2, 6), ("Paneer curry & roti", 6, 30, 2, 5),
                     ("Vegetable pulao", 8, 35, 2, 5), ("Chole bhature", 6, 25, 2, 4), ("Idli sambar", 5, 20, 2, 4)],
    "bakery": [("Assorted bread loaves", 5, 30, 6, 24), ("Pav buns", 4, 25, 5, 20), ("Pastries & cakes", 3, 15, 6, 20),
               ("Sandwich bread", 5, 25, 6, 24)],
    "produce": [("Mixed vegetables", 10, 80, 10, 48), ("Seasonal fruits", 8, 60, 10, 48), ("Leafy greens", 5, 30, 8, 30),
                ("Tomatoes & onions", 10, 70, 24, 72)],
    "dairy": [("Milk packets", 10, 60, 8, 36), ("Curd tubs", 5, 30, 8, 30), ("Paneer blocks", 3, 15, 10, 40)],
    "packaged": [("Biscuit cartons", 5, 40, 48, 240), ("Ready-to-eat packs", 5, 35, 48, 240),
                 ("Packaged snacks", 4, 30, 48, 240), ("Rice & dal sacks", 10, 80, 72, 300)],
    "beverages": [("Fruit juice cartons", 6, 40, 24, 120), ("Bottled lassi", 5, 25, 10, 48)],
}
# which categories each donor type tends to have
BY_ORG_TYPE = {
    "restaurant": ["cooked_meals"] * 6 + ["bakery"], "cafe": ["cooked_meals", "bakery", "beverages", "bakery"],
    "bakery": ["bakery"], "supermarket": ["produce", "dairy", "packaged", "beverages", "produce", "bakery"],
}
CATEGORY_VARIANTS = {
    "cooked_meals": ["cooked_meals", "Cooked Meals", "Veg Meals", "meals", "Prepared Food"],
    "bakery": ["bakery", "Bakery", "BREAD", "Baked Goods", "pastries"],
    "produce": ["produce", "Vegetables", "Fresh Produce", "FRUITS", "veggies"],
    "dairy": ["dairy", "Dairy", "Milk", "curd"],
    "packaged": ["packaged", "Packaged Food", "snacks", "Dry Goods"],
    "beverages": ["beverages", "Drinks", "Juice"],
}
DIRTY_KINDS = ["duplicate", "expired", "bad_category", "missing_field", "unsafe"]
BAD_CATEGORIES = ["xyz123", "misc stuff", "???", "unknown", "electronics", "n/a"]


def local_hour(now_utc: datetime) -> float:
    t = now_utc + IST_OFFSET
    return t.hour + t.minute / 60


def intensity(hour: float) -> float:
    """0..1 surplus intensity: peaks at lunch (13:30) and dinner (20:30)."""
    def bump(c, w):
        return math.exp(-(((hour - c) / w) ** 2))
    return max(bump(13.5, 1.8), bump(20.5, 2.0), 0.12)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _jitter(area: str, rng: random.Random) -> tuple[float, float]:
    lat, lng = AREAS[area]
    return round(lat + rng.uniform(-0.007, 0.007), 5), round(lng + rng.uniform(-0.007, 0.007), 5)


def generate_batch(now_utc: datetime, rng: random.Random, hour: float | None = None) -> tuple[list[dict], dict]:
    """Returns (rows, meta). Rows are CSV-ready dicts mixing record_type donation/request."""
    h = local_hour(now_utc) if hour is None else hour
    k = intensity(h)
    n_don = max(15, min(40, round(15 + k * 25 + rng.uniform(-3, 3))))
    n_req = max(3, min(8, round(3 + k * 5 + rng.uniform(-1, 1))))

    rows: list[dict] = []
    for _ in range(n_don):
        name, area, org_type = rng.choice(DONORS)
        cat = rng.choice(BY_ORG_TYPE[org_type])
        food, kmin, kmax, smin, smax = rng.choice(FOODS[cat])
        lat, lng = _jitter(area, rng)
        rows.append({
            "record_type": "donation", "org_name": name, "food_type": food,
            "category": rng.choice(CATEGORY_VARIANTS[cat]) if rng.random() < 0.35 else cat,
            "quantity_kg": round(rng.uniform(kmin, kmax), 1),
            "expiry_time": _iso(now_utc + timedelta(hours=rng.uniform(max(smin, 1.5), smax))),
            "lat": lat, "lng": lng, "area": area,
        })
    for _ in range(n_req):
        name, area = rng.choice(SEED_NGOS)
        lat, lng = _jitter(area, rng)
        cat = rng.choice([None, None, "cooked_meals", "bakery", "produce", "dairy", "packaged"])
        rows.append({
            "record_type": "request", "org_name": name, "food_type": "", "category": cat or "",
            "quantity_kg": round(rng.uniform(15, 90), 1),
            "expiry_time": _iso(now_utc + timedelta(hours=rng.uniform(2, 8))),
            "lat": lat, "lng": lng, "area": area,
        })

    # a few clean rows lack coordinates: the cleaner imputes them from the area
    for r in rows:
        if rng.random() < 0.03:
            r["lat"] = r["lng"] = ""

    dirty = 0
    out: list[dict] = []
    for r in rows:
        out.append(r)
        if rng.random() >= DIRTY_RATE:
            continue
        kind = rng.choice(DIRTY_KINDS if r["record_type"] == "donation" else ["missing_field", "bad_category"])
        dirty += 1
        if kind == "duplicate":
            out.append(dict(r))
        elif kind == "expired":
            r["expiry_time"] = _iso(now_utc - timedelta(hours=rng.uniform(1, 6)))
        elif kind == "bad_category":
            r["category"] = rng.choice(BAD_CATEGORIES)
        elif kind == "missing_field":
            r[rng.choice(["quantity_kg", "expiry_time", "area"] + (["food_type"] if r["record_type"] == "donation" else []))] = ""
        elif kind == "unsafe":
            r["food_type"] = rng.choice(["Spoiled ", "Stale ", "Rotten ", "Mouldy "]) + r["food_type"].lower()
    rng.shuffle(out)
    return out, {"donations": n_don, "requests": n_req, "dirty": dirty, "total_rows": len(out), "intensity": round(k, 2),
                 "hour": round(h, 1)}


def write_csv(rows: list[dict], inbox_dir: str, batch_no: int, now_utc: datetime) -> str:
    """Atomic write (tmp -> rename) so a file watcher such as NiFi never reads a half-written CSV."""
    os.makedirs(inbox_dir, exist_ok=True)
    name = f"batch_{now_utc.strftime('%Y%m%dT%H%M%S')}_{batch_no:02d}.csv"
    path = os.path.join(inbox_dir, name)
    with open(path + ".tmp", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    os.replace(path + ".tmp", path)
    return path
