from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import S_LISTED
from app.db import Base
from app.utils import utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Donor(Base):
    __tablename__ = "donors"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    org_type: Mapped[str] = mapped_column(String(40), default="restaurant")
    area: Mapped[str | None] = mapped_column(String(60), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)


class NGO(Base):
    __tablename__ = "ngos"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    area: Mapped[str | None] = mapped_column(String(60), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    capacity_kg: Mapped[float] = mapped_column(Float, default=100.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IngestBatch(Base):
    __tablename__ = "ingest_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), index=True)  # sim | api | upload | manual
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    accepted_donations: Mapped[int] = mapped_column(Integer, default=0)
    accepted_requests: Mapped[int] = mapped_column(Integer, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0)
    mongo_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Donation(Base):
    __tablename__ = "donations"
    id: Mapped[int] = mapped_column(primary_key=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("donors.id"), index=True)
    food_type: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(40), index=True)
    quantity_kg: Mapped[float] = mapped_column(Float)
    expiry_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    area: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=S_LISTED, index=True)
    source: Mapped[str] = mapped_column(String(20), default="manual", index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("ingest_batches.id"), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(400), index=True, nullable=True)
    accepted_ngo_id: Mapped[int | None] = mapped_column(ForeignKey("ngos.id"), nullable=True)
    match_attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    donor: Mapped[Donor] = relationship(lazy="joined")


class Request(Base):
    """An NGO need. category=None means 'any category'. standing=True is an always-open need."""
    __tablename__ = "requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    ngo_id: Mapped[int] = mapped_column(ForeignKey("ngos.id"), index=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quantity_kg: Mapped[float] = mapped_column(Float)
    fulfilled_kg: Mapped[float] = mapped_column(Float, default=0.0)
    needed_by: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open | fulfilled
    standing: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("ingest_batches.id"), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    ngo: Mapped[NGO] = relationship(lazy="joined")


class Match(Base):
    __tablename__ = "matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    donation_id: Mapped[int] = mapped_column(ForeignKey("donations.id"), index=True)
    ngo_id: Mapped[int] = mapped_column(ForeignKey("ngos.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"), nullable=True)
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    distance_km: Mapped[float] = mapped_column(Float)
    distance_score: Mapped[float] = mapped_column(Float)
    urgency_score: Mapped[float] = mapped_column(Float)
    fit_score: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="suggested", index=True)  # suggested|accepted|declined
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    ngo: Mapped[NGO] = relationship(lazy="joined")


class RejectedRow(Base):
    __tablename__ = "rejected_rows"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("ingest_batches.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    record_type: Mapped[str] = mapped_column(String(20), default="donation")
    raw: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    """Live event log shared by backend, worker and simulator (separate processes)."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AnalyticsSnapshot(Base):
    """Periodic copy of the analytics summary (written by the Airflow analytics DAG)."""
    __tablename__ = "analytics_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(40), default="summary")
    data: Mapped[dict] = mapped_column(JSON)


class QualityReport(Base):
    """Data-quality report (daily Airflow DAG): reject rates, duplicates, reasons."""
    __tablename__ = "quality_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    data: Mapped[dict] = mapped_column(JSON)
