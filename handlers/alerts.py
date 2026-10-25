"""
Alerts handler — stateless design.

Per the privacy-first architecture alerts are not persisted in the
backend database.  The monitoring endpoint evaluates rules on every
request and returns any triggered conditions directly in its response.

These routes exist so the frontend can call them without breaking.
GET  /api/alerts       – returns an empty list with an explanatory note.
PATCH /api/alerts/{id}/read – accepted and ignored (nothing to mark).
"""

from fastapi import APIRouter, Depends

from utils.auth_guard import get_current_manager


router = APIRouter(
    prefix="/api/alerts",
    tags=["Alerts"],
)

_STATELESS_NOTE = (
    "Alerts are not persisted in this backend. "
    "Rule evaluations are returned directly by POST /api/monitoring/check. "
    "Use frontend state to track triggered conditions across polling cycles."
)


@router.get("")
def get_alerts(
    unread_only: bool = False,
    _: dict = Depends(get_current_manager),
):
    return {
        "success": True,
        "data": [],
        "note": _STATELESS_NOTE,
    }


@router.patch("/{alert_id}/read")
def mark_alert_read(
    alert_id: str,
    _: dict = Depends(get_current_manager),
):
    # No-op — no persistence; accepted for API compatibility.
    return {
        "success": True,
        "message": "Acknowledged. Alerts are not persisted in this backend.",
        "note": _STATELESS_NOTE,
    }