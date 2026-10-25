import uuid
from datetime import datetime, timedelta, timezone

import jwt

from config.config import settings


def _jwt_secret() -> str:
    secret = settings.JWT_SECRET_KEY
    if not secret or not secret.strip():
        raise RuntimeError("JWT_SECRET_KEY must be configured before using authentication.")
    return secret


def create_access_token(data: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = data.copy()
    payload.update({
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRES_IN),
        "jti": str(uuid.uuid4()),
    })
    return jwt.encode(payload, _jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, _jwt_secret(), algorithms=[settings.JWT_ALGORITHM])


def create_refresh_token(data: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "manager_id": data["manager_id"],
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRES_IN),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def decode_refresh_token(token: str) -> dict:
    payload = jwt.decode(token, _jwt_secret(), algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("Invalid refresh token type")
    return payload
