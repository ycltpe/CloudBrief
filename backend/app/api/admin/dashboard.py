import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies import require_role
from app.models.schemas import (
    AdminDashboardResponse,
    DashboardEvalScoresResponse,
    DashboardGraphRagResponse,
    DashboardRecentTasksResponse,
    DashboardStatsResponse,
    DashboardSystemHealthResponse,
    UserOut,
)
from app.services.dashboard_service import DashboardService

logger = structlog.get_logger()
router = APIRouter(prefix="/dashboard", tags=["admin-dashboard"])
dashboard_service = DashboardService()


@router.get("", response_model=AdminDashboardResponse)
def get_dashboard(
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


@router.get("/stats", response_model=DashboardStatsResponse)
def get_dashboard_stats(
    request: Request,
    current_user: UserOut = Depends(require_role("admin", "qa", "user")),
):
    try:
        logger.info(
            "admin_dashboard_stats",
            user_id=current_user.id,
            role=current_user.role,
        )
        return dashboard_service.get_stats()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "admin_dashboard_stats_failed",
            user_id=current_user.id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/eval-scores", response_model=DashboardEvalScoresResponse)
def get_dashboard_eval_scores(
    request: Request,
    current_user: UserOut = Depends(require_role("admin", "qa", "user")),
):
    try:
        logger.info(
            "admin_dashboard_eval_scores",
            user_id=current_user.id,
            role=current_user.role,
        )
        return dashboard_service.get_eval_scores()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "admin_dashboard_eval_scores_failed",
            user_id=current_user.id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/recent-tasks", response_model=DashboardRecentTasksResponse)
def get_dashboard_recent_tasks(
    request: Request,
    current_user: UserOut = Depends(require_role("admin", "qa", "user")),
):
    try:
        logger.info(
            "admin_dashboard_recent_tasks",
            user_id=current_user.id,
            role=current_user.role,
        )
        return dashboard_service.get_recent_tasks()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "admin_dashboard_recent_tasks_failed",
            user_id=current_user.id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/graph-rag", response_model=DashboardGraphRagResponse)
def get_dashboard_graph_rag(
    request: Request,
    current_user: UserOut = Depends(require_role("admin", "qa", "user")),
):
    try:
        logger.info(
            "admin_dashboard_graph_rag",
            user_id=current_user.id,
            role=current_user.role,
        )
        return dashboard_service.get_graph_rag_status()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "admin_dashboard_graph_rag_failed",
            user_id=current_user.id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/system-health", response_model=DashboardSystemHealthResponse)
def get_dashboard_system_health(
    request: Request,
    current_user: UserOut = Depends(require_role("admin", "qa", "user")),
):
    try:
        logger.info(
            "admin_dashboard_system_health",
            user_id=current_user.id,
            role=current_user.role,
        )
        graph_store = request.app.state.graph_store
        return dashboard_service.get_system_health(graph_store=graph_store)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "admin_dashboard_system_health_failed",
            user_id=current_user.id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))
