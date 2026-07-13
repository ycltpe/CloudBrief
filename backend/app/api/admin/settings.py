
import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import require_role
from app.models.schemas import (
    SettingsResponse,
    SettingsUpdateRequest,
    SettingsUpdateResponse,
    UserOut,
)
from app.services.settings_service import SettingsService, get_settings_service

logger = structlog.get_logger()
router = APIRouter(prefix="/settings", tags=["admin-settings"])


@router.get("", response_model=SettingsResponse)
async def list_settings(
    service: SettingsService = Depends(get_settings_service),
    _current_user: UserOut = Depends(require_role("admin")),
):
    groups = service.list_groups()
    logger.info("admin_list_settings")
    return SettingsResponse(groups=groups)


@router.put("", response_model=SettingsUpdateResponse)
async def update_settings(
    request: SettingsUpdateRequest,
    service: SettingsService = Depends(get_settings_service),
    current_user: UserOut = Depends(require_role("admin")),
):
    if not request.values:
        raise HTTPException(status_code=400, detail="NO_SETTINGS_PROVIDED")

    try:
        service.update(request.values, updated_by=current_user.id)
    except ValueError as exc:
        logger.warning("admin_update_settings_validation_failed", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))

    logger.info("admin_update_settings", operator_id=current_user.id, keys=list(request.values.keys()))
    return SettingsUpdateResponse(updated=len(request.values), groups=service.list_groups())


@router.get("/runtime/{key}")
async def get_runtime_setting(
    key: str,
    service: SettingsService = Depends(get_settings_service),
    _current_user: UserOut = Depends(require_role("admin", "qa", "user")),
):
    """供内部调试使用：读取任意运行期配置值。"""
    if key not in service.get_known_setting_keys():
        raise HTTPException(status_code=404, detail="UNKNOWN_SETTING")
    return {"key": key, "value": service.get_runtime_value(key)}
