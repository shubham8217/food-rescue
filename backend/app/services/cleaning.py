"""Polars cleaning: validate required fields, dedupe, standardise categories, reject expired/unsafe.

Pure functions (no DB / network) so they are trivially unit-testable. Input is a list of raw
dict rows; output is clean rows plus rejected rows with a human-readable reason.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import polars as pl

from app.geo import AREAS, BBOX, area_centroid, canonical_area
from app.utils import parse_dt

COLUMNS = ["org_name", "food_type", "category", "quantity_kg", "expiry_time", "lat", "lng", "area"]
MAX_QTY_KG = 5000.0
MIN_SHELF_MINUTES = 60

_CATEGORY_ALIASES = {
    "cooked_meals": ["cooked meals", "cooked meal", "meals", "meal", "veg meals", "non veg meals", "nonveg meals",
                     "biryani", "rice", "dal", "curry", "thali", "cooked food", "prepared food", "food", "lunch",
                     "dinner", "roti", "sabzi"],
    "bakery": ["bakery", "bread", "breads", "pastry", "pastries", "cake", "cakes", "buns", "bun", "baked goods",
               "baked", "pav", "biscuits", "fresh bread"],
    "produce": ["produce", "vegetables", "vegetable", "veggies", "fruits", "fruit", "fresh produce", "veg", "greens"],
    "dairy": ["dairy", "milk", "curd", "yogurt", "yoghurt", "paneer", "cheese", "butter", "lassi"],
    "packaged": ["packaged", "packed", "packaged food", "snacks", "canned", "dry goods", "grains", "staples",
                 "ready to eat"],
    "beverages": ["beverages", "beverage", "drinks", "drink", "juice", "juices", "soft drinks"],
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


CATEGORY_LOOKUP: dict[str, str] = {}
for _canon, _aliases in _CATEGORY_ALIASES.items():
    CATEGORY_LOOKUP[_norm(_canon)] = _canon
    for _a in _aliases:
        CATEGORY_LOOKUP[_norm(_a)] = _canon


def canonical_category(value: str | None) -> str | None:
    if value is None:
        return None
    return CATEGORY_LOOKUP.get(_norm(value))


UNSAFE_PATTERN = r"(?i)spoil|rotten|rot\b|mou?ld|stale|rancid|contaminat|half[- ]eaten|leftover from plate|expired|fungus|smelly"


@dataclass
class CleanResult:
    clean: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)  # {row_number, raw, reason}


def _to_frame(rows: list[dict], row_numbers: list[int]) -> pl.DataFrame:
    data = {"row_number": row_numbers}
    for col in COLUMNS:
        vals = []
        for r in rows:
            v = r.get(col)
            v = None if v is None else str(v).strip()
            vals.append(v or None)
        data[col] = vals
    schema = {"row_number": pl.Int64, **{c: pl.Utf8 for c in COLUMNS}}
    return pl.DataFrame(data, schema=schema)


def _imputed(col: str, idx: int):
    def f(area):
        c = area_centroid(area)
        return c[idx] if c else None
    return f


def clean_records(rows: list[dict], kind: str = "donation", now: datetime | None = None,
                  row_numbers: list[int] | None = None,
                  existing_keys: set[str] | frozenset = frozenset()) -> CleanResult:
    """kind='donation' enforces category + shelf-life/unsafe rules; kind='request' is an NGO need
    (category optional, expiry_time means 'needed by')."""
    if not rows:
        return CleanResult()
    now = now or datetime.utcnow()
    row_numbers = row_numbers or list(range(1, len(rows) + 1))
    is_donation = kind == "donation"

    df = _to_frame(rows, row_numbers)
    df = df.with_columns(
        pl.col("quantity_kg").cast(pl.Float64, strict=False).alias("qty"),
        pl.col("lat").cast(pl.Float64, strict=False).alias("lat_f"),
        pl.col("lng").cast(pl.Float64, strict=False).alias("lng_f"),
        pl.col("expiry_time").map_elements(parse_dt, return_dtype=pl.Datetime("us")).alias("expiry_dt"),
        pl.col("category").map_elements(canonical_category, return_dtype=pl.Utf8).alias("category_std"),
        pl.col("area").map_elements(canonical_area, return_dtype=pl.Utf8).alias("area_std"),
        pl.col("area").map_elements(_imputed("lat", 0), return_dtype=pl.Float64).alias("area_lat"),
        pl.col("area").map_elements(_imputed("lng", 1), return_dtype=pl.Float64).alias("area_lng"),
    ).with_columns(
        # impute missing coordinates from the area centroid
        pl.coalesce("lat_f", "area_lat").alias("lat_f"),
        pl.coalesce("lng_f", "area_lng").alias("lng_f"),
    )

    required = ["org_name", "food_type", "category", "quantity_kg", "expiry_time", "area"] if is_donation \
        else ["org_name", "quantity_kg", "expiry_time", "area"]

    checks: list[tuple[pl.Expr, pl.Expr]] = []
    for col in required:
        checks.append((pl.col(col).is_null(), pl.lit(f"missing required field: {col}")))
    checks += [
        (pl.col("qty").is_null(), pl.lit("invalid quantity_kg (not a number)")),
        ((pl.col("qty") <= 0) | (pl.col("qty") > MAX_QTY_KG), pl.lit(f"quantity_kg out of range (0-{int(MAX_QTY_KG)})")),
        (pl.col("expiry_dt").is_null(), pl.lit("invalid expiry_time (unparseable date)")),
    ]
    if is_donation:
        checks += [
            (pl.col("category_std").is_null(), pl.format("unknown category: '{}'", pl.col("category"))),
            (pl.col("food_type").str.contains(UNSAFE_PATTERN), pl.format("unsafe item: '{}'", pl.col("food_type"))),
            (pl.col("expiry_dt") <= now, pl.lit("expired item")),
            (pl.col("expiry_dt") < now + timedelta(minutes=MIN_SHELF_MINUTES),
             pl.lit(f"unsafe: under {MIN_SHELF_MINUTES} min of shelf life left")),
        ]
    else:
        checks += [
            (pl.col("category").is_not_null() & pl.col("category_std").is_null(),
             pl.format("unknown category: '{}'", pl.col("category"))),
            (pl.col("expiry_dt") <= now, pl.lit("needed_by is in the past")),
        ]
    checks += [
        (pl.col("lat_f").is_null() | pl.col("lng_f").is_null(), pl.lit("missing location (no lat/lng and unknown area)")),
        ((pl.col("lat_f") < BBOX["lat"][0]) | (pl.col("lat_f") > BBOX["lat"][1])
         | (pl.col("lng_f") < BBOX["lng"][0]) | (pl.col("lng_f") > BBOX["lng"][1]),
         pl.lit("location outside Navi Mumbai service area")),
    ]
    reason_expr = pl.coalesce([pl.when(cond).then(msg) for cond, msg in checks]).alias("reason")

    df = df.with_columns(reason_expr).with_columns(
        pl.concat_str(
            [pl.col("org_name").str.to_lowercase(), pl.col("food_type").fill_null("").str.to_lowercase(),
             pl.col("category_std").fill_null("any"), pl.col("qty").round(2).cast(pl.Utf8),
             pl.col("expiry_dt").dt.strftime("%Y%m%d%H%M")],
            separator="|", ignore_nulls=True,
        ).alias("dedupe_key")
    )

    # Dedupe only among otherwise-valid rows: keep the first occurrence of each key.
    valid_mask = pl.col("reason").is_null()
    df = df.with_columns(
        (valid_mask & (pl.int_range(pl.len()).over(pl.when(valid_mask).then(pl.col("dedupe_key"))) > 0))
        .alias("dup_in_batch")
    ).with_columns(
        pl.when(pl.col("reason").is_null() & pl.col("dup_in_batch"))
        .then(pl.lit("duplicate row in batch"))
        .when(pl.col("reason").is_null() & pl.col("dedupe_key").is_in(list(existing_keys)))
        .then(pl.lit("duplicate of an existing record"))
        .otherwise(pl.col("reason"))
        .alias("reason")
    )

    raw_by_row = dict(zip(row_numbers, rows))
    result = CleanResult()
    for rec in df.iter_rows(named=True):
        if rec["reason"] is not None:
            result.rejected.append({"row_number": rec["row_number"], "raw": raw_by_row[rec["row_number"]],
                                    "reason": rec["reason"]})
        else:
            result.clean.append({
                "row_number": rec["row_number"],
                "org_name": rec["org_name"],
                "food_type": rec["food_type"],
                "category": rec["category_std"],
                "quantity_kg": float(rec["qty"]),
                "expiry_time": rec["expiry_dt"],
                "lat": float(rec["lat_f"]),
                "lng": float(rec["lng_f"]),
                "area": rec["area_std"],
                "dedupe_key": rec["dedupe_key"],
            })
    return result


__all__ = ["clean_records", "canonical_category", "CleanResult", "AREAS"]
