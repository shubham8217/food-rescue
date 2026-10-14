import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

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
