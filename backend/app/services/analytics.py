"""Analytics: DuckDB SQL over Polars frames (loaded from PostgreSQL and the Delta Lake status history).

Polars shapes the data, DuckDB answers the analytical questions in SQL. The history donations seeded by the
backfill (source='history') are included here on purpose: they give the charts and the forecast something to show.
"""
from datetime import datetime, timedelta

import duckdb
import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import MEAL_KG
from app.models import NGO, Donation, Donor, RejectedRow
from app.services import history
from app.utils import utcnow

DONATION_SCHEMA = {"id": pl.Int64, "donor_id": pl.Int64, "category": pl.Utf8, "area": pl.Utf8, "status": pl.Utf8,
                   "quantity_kg": pl.Float64, "created_at": pl.Datetime("us"), "changed_at": pl.Datetime("us"),
                   "source": pl.Utf8, "ngo_id": pl.Int64}


def donations_frame(db: Session) -> pl.DataFrame:
    rows = db.execute(select(Donation.id, Donation.donor_id, Donation.category, Donation.area, Donation.status,
                             Donation.quantity_kg, Donation.created_at, Donation.status_changed_at, Donation.source,
                             Donation.accepted_ngo_id)).all()
    return pl.DataFrame([tuple(r) for r in rows], schema=DONATION_SCHEMA, orient="row")


def _con(**frames: pl.DataFrame) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    for name, df in frames.items():
        con.register(name, df.to_arrow())
    return con


def _rows(con, sql: str, *params) -> list[dict]:
    cur = con.execute(sql, list(params))
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _iso(v):
    return v.isoformat() + "Z" if isinstance(v, datetime) else v


def summary(db: Session) -> dict:
    con = _con(d=donations_frame(db))
    row = _rows(con, """
        select count(*) total, coalesce(sum(quantity_kg),0) total_kg,
               coalesce(sum(quantity_kg) filter (where status='delivered'),0) rescued_kg,
               count(*) filter (where status in ('accepted','picked_up','delivered')) accepted_n,
               count(*) filter (where status='delivered') delivered_n,
               count(*) filter (where status='expired') expired_n
        from d""")[0]
    total = row["total"] or 0
    out = {
        "total_donations": total, "total_kg": round(row["total_kg"], 1), "kg_rescued": round(row["rescued_kg"], 1),
        "meals": int(row["rescued_kg"] / MEAL_KG),
        "acceptance_rate": round(row["accepted_n"] / total, 3) if total else 0.0,
        "delivery_rate": round(row["delivered_n"] / total, 3) if total else 0.0,
        "expired_rate": round(row["expired_n"] / total, 3) if total else 0.0,
        "avg_minutes_to_accept": None, "avg_minutes_accept_to_delivery": None,
    }
    out.update(_timings(db))
    return out


def _timings(db: Session) -> dict:
    """Average minutes listed -> accepted and accepted -> delivered, from the Delta Lake status history."""
    try:
        ev = history.read_status_events()
        if ev.is_empty():
            return {}
        con = _con(e=ev.select("donation_id", "to_status", "ts"))
        r = _rows(con, """
            with a as (select donation_id, min(ts) t from e where to_status='accepted' group by 1),
                 m as (select donation_id, min(ts) t from e where to_status='matched' group by 1),
                 v as (select donation_id, min(ts) t from e where to_status='delivered' group by 1)
            select avg(date_diff('second', m.t, a.t))/60.0 to_accept,
                   (select avg(date_diff('second', a2.t, v.t))/60.0 from a a2 join v using (donation_id)) to_deliver
            from a join m using (donation_id)""")[0]
        return {"avg_minutes_to_accept": _r(r["to_accept"]), "avg_minutes_accept_to_delivery": _r(r["to_deliver"])}
    except Exception:  # noqa: BLE001  (Delta unavailable: the other metrics still work)
        return {}


def _r(v):
    return round(v, 1) if v is not None else None


def by_area(db: Session) -> list[dict]:
    con = _con(d=donations_frame(db))
    return _rows(con, """
        select coalesce(area,'unknown') area, count(*) donations, round(sum(quantity_kg),1) kg,
               round(coalesce(sum(quantity_kg) filter (where status='delivered'),0),1) rescued_kg,
               round(count(*) filter (where status='delivered') * 1.0 / count(*), 3) delivery_rate
        from d group by 1 order by kg desc""")


def by_category(db: Session) -> list[dict]:
    con = _con(d=donations_frame(db))
    return _rows(con, """
        select category, count(*) donations, round(sum(quantity_kg),1) kg,
               round(coalesce(sum(quantity_kg) filter (where status='delivered'),0),1) rescued_kg
        from d group by 1 order by kg desc""")


def timeline(db: Session, hours: int = 24, now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    since = now - timedelta(hours=hours)
    con = _con(d=donations_frame(db))
    got = {r["ts"]: r for r in _rows(con, """
        select date_trunc('hour', created_at) ts, count(*) donations, round(sum(quantity_kg),1) kg,
               round(coalesce(sum(quantity_kg) filter (where status='delivered'),0),1) delivered_kg
        from d where created_at >= ? group by 1""", since)}
    out, t = [], since.replace(minute=0, second=0, microsecond=0)
    while t <= now:
        r = got.get(t, {})
        out.append({"ts": _iso(t), "donations": r.get("donations", 0), "kg": r.get("kg", 0.0),
                    "delivered_kg": r.get("delivered_kg", 0.0)})
        t += timedelta(hours=1)
    return out


def rejections(db: Session) -> list[dict]:
    rows = db.execute(select(RejectedRow.reason)).all()
    df = pl.DataFrame({"reason": [r[0] for r in rows]}, schema={"reason": pl.Utf8})
    con = _con(r=df)
    return _rows(con, """
        select trim(regexp_replace(reason, ':.*$', '')) reason, count(*) count
        from r group by 1 order by count desc""")


def funnel(db: Session) -> list[dict]:
    con = _con(d=donations_frame(db))
    r = _rows(con, """
        select count(*) "listed",
               count(*) filter (where status in ('matched','accepted','picked_up','delivered')) "matched",
               count(*) filter (where status in ('accepted','picked_up','delivered')) "accepted",
               count(*) filter (where status in ('picked_up','delivered')) "picked_up",
               count(*) filter (where status = 'delivered') "delivered"
        from d""")[0]
    return [{"stage": k, "count": r[k]} for k in ("listed", "matched", "accepted", "picked_up", "delivered")]


def top(db: Session, limit: int = 5) -> dict:
    con = _con(d=donations_frame(db))
    donor_names = pl.DataFrame([(i, n) for i, n in db.execute(select(Donor.id, Donor.name)).all()],
                               schema={"donor_id": pl.Int64, "name": pl.Utf8}, orient="row")
    ngo_names = pl.DataFrame([(i, n) for i, n in db.execute(select(NGO.id, NGO.name)).all()],
                             schema={"ngo_id": pl.Int64, "name": pl.Utf8}, orient="row")
    con.register("dn", donor_names.to_arrow())
    con.register("nn", ngo_names.to_arrow())
    donors = _rows(con, f"""
        select dn.name, round(sum(d.quantity_kg),1) kg, count(*) donations from d join dn using (donor_id)
        group by 1 order by kg desc limit {int(limit)}""")
    ngos = _rows(con, f"""
        select nn.name, round(sum(d.quantity_kg),1) kg, count(*) donations from d join nn using (ngo_id)
        where d.status = 'delivered' group by 1 order by kg desc limit {int(limit)}""")
    return {"donors": donors, "ngos": ngos}
