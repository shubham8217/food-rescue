import hmac

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import NGO, Donor, User
from app.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    err = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token",
                        headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise err
    user = db.scalar(select(User).where(User.email == payload.get("sub")))
    if user is None:
        raise err
    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role: {', '.join(roles)}")
        return user

    return checker


def donor_profile(db: Session, user: User) -> Donor | None:
    return db.scalar(select(Donor).where(Donor.user_id == user.id))


def ngo_profile(db: Session, user: User) -> NGO | None:
    return db.scalar(select(NGO).where(NGO.user_id == user.id))


_optional_scheme = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


def _service_user() -> User:
    return User(id=0, email="service@foodrescue.internal", name="Service account", role="admin")


def admin_or_service(*extra_roles: str):
    """Admin JWT (or `extra_roles`) **or** a valid X-API-Key (NiFi / Airflow service account)."""
    allowed = ("admin", *extra_roles)

    def checker(x_api_key: str | None = Header(default=None), token: str | None = Depends(_optional_scheme),
                db: Session = Depends(get_db)) -> User:
        if x_api_key:
            if settings.ingest_api_key and hmac.compare_digest(x_api_key, settings.ingest_api_key):
                return _service_user()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                                headers={"WWW-Authenticate": "Bearer"})
        user = get_current_user(token, db)
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role: {', '.join(allowed)}")
        return user

    return checker
