from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
import jwt
from sqlalchemy.orm import Session

from core.database import get_db
from models.manager import Manager
from schema.auth import Login, Signup, RefreshTokenRequest
from utils.auth_helpers import build_token_data
from utils.jwt import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from utils.password import hash_password, verify_password

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


@router.post("/login")
@router.post("")
def login(
    details: Login,
    db: Session = Depends(get_db),
):
    manager = (
        db.query(Manager)
        .filter(Manager.email == details.email)
        .first()
    )

    if not manager:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "message": "No manager found with this email",
                "data": {},
            },
        )

    if not verify_password(details.password, manager.password_hash):
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "Wrong Password",
                "data": {},
            },
        )

    token_data = build_token_data(manager)

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": "Login Successful",
            "data": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "manager": {
                    "id": str(manager.id),
                    "name": manager.name,
                    "email": manager.email,
                },
            },
        },
    )


@router.post("/signup")
def signup(
    details: Signup,
    db: Session = Depends(get_db),
):
    existing_manager = (
        db.query(Manager)
        .filter(Manager.email == details.email)
        .first()
    )

    if existing_manager:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Manager with this email already exists",
                "data": {},
            },
        )

    new_manager = Manager(
        name=details.name,
        email=details.email,
        password_hash=hash_password(details.password),
    )

    db.add(new_manager)
    db.commit()
    db.refresh(new_manager)

    token_data = build_token_data(new_manager)
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return JSONResponse(
        status_code=201,
        content={
            "success": True,
            "message": "Signup successful",
            "data": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "manager": {
                    "id": str(new_manager.id),
                    "name": new_manager.name,
                    "email": new_manager.email,
                },
            },
        },
    )


@router.post("/refresh")
def refresh_access_token(
    details: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    refresh_token = details.refresh_token

    try:
        payload = decode_refresh_token(refresh_token)
    except jwt.ExpiredSignatureError:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "Refresh token has expired. Please login again.",
                "data": {},
            },
        )
    except jwt.InvalidTokenError:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "Invalid refresh token. Please login again.",
                "data": {},
            },
        )

    if payload.get("type") != "refresh":
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "Invalid refresh token.",
                "data": {},
            },
        )

    manager_id = payload.get("manager_id") or payload.get("user_id")

    if not manager_id:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "Invalid refresh token payload.",
                "data": {},
            },
        )

    try:
        uuid_id = UUID(str(manager_id))
    except ValueError:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "Invalid manager ID format.",
                "data": {},
            },
        )

    manager = (
        db.query(Manager)
        .filter(Manager.id == uuid_id)
        .first()
    )

    if not manager:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "Manager account not found.",
                "data": {},
            },
        )

    token_data = build_token_data(manager)
    access_token = create_access_token(token_data)

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": "Token refreshed successfully",
            "data": {
                "access_token": access_token,
                "refresh_token": refresh_token,
            },
        },
    )
