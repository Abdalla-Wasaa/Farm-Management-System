from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User, now

passwords = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)
DUMMY_HASH = passwords.hash("dummy-password-for-timing")


def token(user: User):
    return jwt.encode(
        {"sub": str(user.id), "exp": now() + timedelta(hours=8), "iat": now()},
        settings.jwt_secret,
        algorithm="HS256",
    )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db, scope="function"),
):
    try:
        if credentials is None:
            raise ValueError()
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["sub", "exp", "iat"]},
        )
        user = db.get(User, int(payload["sub"]))
        if not user:
            raise ValueError()
        return user
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise HTTPException(
            401,
            "Invalid or expired authentication",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require(user, *roles):
    if user.role not in roles:
        raise HTTPException(403, "Insufficient permission")


def create_user(db, phone, password, role="buyer"):
    if db.scalar(select(User).where(User.phone == phone)):
        raise HTTPException(409, "Phone already registered")
    user = User(phone=phone, password_hash=passwords.hash(password), role=role)
    db.add(user)
    db.flush()
    return user
