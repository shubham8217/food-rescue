from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _iso_z(d: datetime) -> str:
    return d.isoformat() + "Z" if d.tzinfo is None else d.isoformat()


UTCDateTime = Annotated[datetime, PlainSerializer(_iso_z, return_type=str)]


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str
    email: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    role: str


class DonationIn(BaseModel):
    food_type: str = Field(min_length=2, max_length=160)
    category: str
    quantity_kg: float = Field(gt=0, le=5000)
    expiry_time: datetime
    area: str
    lat: float | None = None
    lng: float | None = None
    org_name: str | None = None  # admins only; donors always use their own profile


class DonationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    donor_name: str | None = None
    food_type: str
    category: str
    quantity_kg: float
    expiry_time: UTCDateTime
    lat: float
    lng: float
    area: str | None
    status: str
    source: str
    created_at: UTCDateTime
    status_changed_at: UTCDateTime
    accepted_ngo_id: int | None = None
    accepted_ngo_name: str | None = None
    match_count: int = 0


class MatchOut(BaseModel):
    id: int
    rank: int
    score: float
    distance_km: float
    distance_score: float
    urgency_score: float
    fit_score: float
    status: str
    ngo_id: int
    ngo_name: str
    donation: DonationOut


class RequestIn(BaseModel):
    category: str | None = None
    quantity_kg: float
    needed_by: datetime


class RequestOut(BaseModel):
    id: int
    ngo_name: str
    category: str | None
    quantity_kg: float
    fulfilled_kg: float
    needed_by: UTCDateTime
    status: str
    standing: bool


class StatusIn(BaseModel):
    status: str


class DemoStartIn(BaseModel):
    duration_minutes: float = 10
    interval_seconds: float = 30
    speed: int = 1
    reset: bool = True
    start_hour: int | None = Field(default=None, ge=0, le=23)  # force lunch/dinner intensity for demos


class SpeedIn(BaseModel):
    speed: int
