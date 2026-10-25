from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.database import get_db
from models.manager import Manager
from schema.manager import (
    ManagerCreate,
    ManagerUpdate,
    ManagerResponse,
    PasswordUpdate,
)
from utils.auth_guard import get_current_manager
from utils.password import hash_password

router = APIRouter(
    prefix="/managers",
    tags=["managers"]
)


@router.get("/me", response_model=ManagerResponse)
def get_me(
    current_manager: dict = Depends(get_current_manager),
    db: Session = Depends(get_db)
):
    manager_id = current_manager.get("manager_id") or current_manager.get("user_id")
    manager = (
        db.query(Manager)
        .filter(Manager.id == UUID(str(manager_id)))
        .first()
    )

    if not manager:
        raise HTTPException(
            status_code=404,
            detail="Manager not found"
        )

    return manager


@router.post("/", response_model=ManagerResponse, status_code=201)
def create_manager(
    details: ManagerCreate,
    db: Session = Depends(get_db)
):
    if db.query(Manager).filter(Manager.email == details.email).first():
        raise HTTPException(
            status_code=400,
            detail="Email is already registered"
        )

    hashed_password = hash_password(details.password)

    new_manager = Manager(
        name=details.name,
        email=details.email,
        password_hash=hashed_password,
    )

    db.add(new_manager)
    db.commit()
    db.refresh(new_manager)

    return new_manager


@router.put("/me/password")
@router.put("/password")
def update_password(
    details: PasswordUpdate,
    current_manager: dict = Depends(get_current_manager),
    db: Session = Depends(get_db),
):
    manager_id = current_manager.get("manager_id") or current_manager.get("user_id")
    manager = (
        db.query(Manager)
        .filter(Manager.id == UUID(str(manager_id)))
        .first()
    )

    if not manager:
        raise HTTPException(
            status_code=404,
            detail="Manager not found"
        )

    manager.password_hash = hash_password(details.password)
    db.commit()

    return {
        "success": True,
        "message": "Password updated successfully",
        "data": {}
    }


@router.put("/me", response_model=ManagerResponse)
@router.put("/", response_model=ManagerResponse)
def update_manager(
    details: ManagerUpdate,
    current_manager: dict = Depends(get_current_manager),
    db: Session = Depends(get_db),
):
    manager_id = UUID(str(current_manager.get("manager_id") or current_manager.get("user_id")))
    manager = (
        db.query(Manager)
        .filter(Manager.id == manager_id)
        .first()
    )

    if not manager:
        raise HTTPException(
            status_code=404,
            detail="Manager not found"
        )

    if details.name is not None:
        manager.name = details.name

    if details.email is not None and details.email != manager.email:
        existing_email = (
            db.query(Manager)
            .filter(
                Manager.email == details.email,
                Manager.id != manager_id
            )
            .first()
        )
        if existing_email:
            raise HTTPException(
                status_code=400,
                detail="Email is already in use"
            )
        manager.email = details.email

    db.commit()
    db.refresh(manager)

    return manager


@router.delete("/me")
@router.delete("/{manager_id}")
def delete_manager(
    manager_id: str = "me",
    current_manager: dict = Depends(get_current_manager),
    db: Session = Depends(get_db),
):
    target_id = current_manager.get("manager_id") or current_manager.get("user_id")
    if manager_id != "me" and manager_id != str(target_id):
        raise HTTPException(
            status_code=403,
            detail="You can only delete your own account"
        )

    manager = (
        db.query(Manager)
        .filter(Manager.id == UUID(str(target_id)))
        .first()
    )

    if not manager:
        raise HTTPException(
            status_code=404,
            detail="Manager not found"
        )

    db.delete(manager)
    db.commit()

    return {
        "success": True,
        "message": "Manager deleted successfully",
        "data": {}
    }
