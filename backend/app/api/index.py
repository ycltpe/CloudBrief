from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.dependencies import require_role
from app.models.schemas import IndexRebuildResponse, IndexTaskStatus, UserOut
from app.services.index_service import IndexService

router = APIRouter(tags=["index"])
index_service = IndexService()


@router.post("/index/rebuild", response_model=IndexRebuildResponse)
async def rebuild_index(
    _current_user: UserOut = Depends(require_role("admin")),
):
    try:
        task_id = index_service.trigger_rebuild()
        return IndexRebuildResponse(task_id=task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/index/tasks/{task_id}", response_model=IndexTaskStatus)
async def get_index_task(
    task_id: str,
    _current_user: UserOut = Depends(require_role("admin")),
):
    try:
        return index_service.get_task_status(task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/index/tasks/{task_id}/events")
async def index_task_events(
    task_id: str,
    request: Request,
    last_event_id: str | None = None,
    _current_user: UserOut = Depends(require_role("admin")),
):
    return EventSourceResponse(
        index_service.event_stream(task_id, request=request, last_event_id=last_event_id)
    )
