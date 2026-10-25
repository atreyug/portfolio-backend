from fastapi import APIRouter, Depends

from schema.portfolio import StatelessMonitoringRequest
from utils.auth_guard import get_current_manager

router = APIRouter(prefix="/api/monitoring", tags=["Monitoring"])


@router.post("/check")
async def check_monitoring_holding(
    request: StatelessMonitoringRequest,
    current_manager: dict = Depends(get_current_manager),
):
    """Evaluate request-supplied monitoring rules without database writes."""
    from services.monitor import MonitoringService

    result = await MonitoringService().check_stateless(request)
    return {"success": True, "data": result}


@router.post("/run")
async def run_monitoring(current_manager: dict = Depends(get_current_manager)):
    """Compatibility endpoint; clients should submit rules to /check on each poll."""
    return {
        "success": True,
        "data": {
            "checked_assets": 0,
            "triggered_rules": 0,
            "persisted": False,
            "message": "Monitoring is stateless. Submit holdings and rules to POST /api/monitoring/check.",
        },
    }
