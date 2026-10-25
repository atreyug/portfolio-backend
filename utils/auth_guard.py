from uuid import UUID
import jwt
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from core.database import get_db
from models.manager import Manager
from utils.jwt import decode_access_token

_bearer = HTTPBearer()


def get_current_manager(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> dict:
    token = credentials.credentials

    try:
        manager_data = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Your token has expired. Please login again.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token. Please login again.",
        )

    if manager_data.get("type") != "access":
        raise HTTPException(
            status_code=401,
            detail="Invalid access token.",
        )

    manager_id = manager_data.get("manager_id") or manager_data.get("user_id")

    if not manager_id:
        raise HTTPException(
            status_code=401,
            detail="Invalid token payload.",
        )

    try:
        uuid_id = UUID(str(manager_id))
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid manager ID format in token.",
        )

    manager = db.query(Manager).filter(Manager.id == uuid_id).first()

    if not manager:
        raise HTTPException(
            status_code=401,
            detail="Manager account not found.",
        )

    return manager_data


# Alias for backward compatibility if needed
get_current_user = get_current_manager
