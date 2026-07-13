import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies import require_role
from app.models.schemas import AdminDashboardResponse, UserOut
from app.services.dashboard_service import DashboardService

logger = structlog.get_logger()
router = APIRouter(prefix="/dashboard", tags=["admin-dashboard"])
dashboard_service = DashboardService()


@router.get("", response_model=AdminDashboardResponse)
async def get_dashboard(
    request: Request,
    current_user: UserOut = Depends(require_role("admin", "qa", "user")),
):
    try:
        logger.info("admin_dashboard", user_id=current_user.id, role=current_user.role)
        graph_store = request.app.state.graph_store
        return dashboard_service.get_dashboard(graph_store=graph_store)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin_dashboard_failed", user_id=current_user.id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
