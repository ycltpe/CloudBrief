import csv
import json
from datetime import datetime
from io import StringIO
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.dependencies import require_role
from app.models.schemas import (
    AdminEvalFeedbackIn,
    AdminEvalListResponse,
    AdminEvalResultOut,
    UserOut,
)
from app.stores.eval_results import EvalResultStore

logger = structlog.get_logger()
router = APIRouter(prefix="/eval", tags=["admin-eval"])
eval_store = EvalResultStore()


def _safe_json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _to_admin_out(result) -> AdminEvalResultOut:
    return AdminEvalResultOut(
        id=result.id,
        question=result.question,
        answer=result.answer,
        ground_truth=result.ground_truth,
        contexts=_safe_json_loads(result.contexts_json, []),
        ragas_scores=_safe_json_loads(result.ragas_scores_json, {}),
        reasoning=_safe_json_loads(result.reasoning_json, {}),
        human_score=result.human_score,
        human_note=result.human_note,
        is_adopted=result.is_adopted,
        is_modified=result.is_modified,
        created_at=result.created_at.isoformat() if result.created_at else None,
        updated_at=result.updated_at.isoformat() if result.updated_at else None,
    )


def _format_datetime(value: datetime | None) -> str:
    return value.isoformat() if value else ""


@router.get("/results", response_model=AdminEvalListResponse)
async def list_eval_results(
    min_score: float | None = Query(None, ge=0.0, le=1.0),
    has_feedback: bool | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _current_user: UserOut = Depends(require_role("admin", "qa")),
):
    try:
        items, total = eval_store.list_with_filters(
            limit=limit,
            offset=offset,
            min_score=min_score,
            has_feedback=has_feedback,
        )
        logger.info(
            "admin_list_eval_results",
            min_score=min_score,
            has_feedback=has_feedback,
            limit=limit,
            offset=offset,
            total=total,
        )
        return AdminEvalListResponse(total=total, items=[_to_admin_out(r) for r in items])
    except Exception as exc:
        logger.error("admin_list_eval_results_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/results/{result_id}", response_model=AdminEvalResultOut)
async def get_eval_result(
    result_id: int,
    _current_user: UserOut = Depends(require_role("admin", "qa")),
):
    try:
        result = eval_store.get(result_id)
        if not result:
            raise HTTPException(status_code=404, detail="EVAL_RESULT_NOT_FOUND")
        return _to_admin_out(result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin_get_eval_result_failed", result_id=result_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/results/{result_id}/feedback", response_model=AdminEvalResultOut)
async def feedback_eval_result(
    result_id: int,
    feedback: AdminEvalFeedbackIn,
    current_user: UserOut = Depends(require_role("admin", "qa")),
):
    try:
        result = eval_store.update_feedback(result_id, feedback)
        if not result:
            raise HTTPException(status_code=404, detail="EVAL_RESULT_NOT_FOUND")
        logger.info(
            "admin_update_eval_feedback",
            result_id=result_id,
            operator_id=current_user.id,
            human_score=feedback.human_score,
            is_adopted=feedback.is_adopted,
            is_modified=feedback.is_modified,
        )
        return _to_admin_out(result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "admin_update_eval_feedback_failed",
            result_id=result_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/export")
async def export_eval_results(
    format: str = Query(..., pattern="^(csv|json)$"),
    min_score: float | None = Query(None, ge=0.0, le=1.0),
    has_feedback: bool | None = Query(None),
    _current_user: UserOut = Depends(require_role("admin", "qa")),
):
    """导出全部满足筛选条件的人工标注评测记录。"""
    try:
        items, _ = eval_store.list_with_filters(
            limit=10000,
            offset=0,
            min_score=min_score,
            has_feedback=has_feedback,
        )
        logger.info(
            "admin_export_eval_results",
            format=format,
            min_score=min_score,
            has_feedback=has_feedback,
            count=len(items),
        )

        if format == "csv":
            return _export_csv(items)
        return _export_json(items)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin_export_eval_results_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


def _export_csv(items: list) -> StreamingResponse:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "question",
            "answer",
            "ground_truth",
            "contexts_json",
            "ragas_scores_json",
            "reasoning_json",
            "human_score",
            "human_note",
            "is_adopted",
            "is_modified",
            "created_at",
            "updated_at",
        ]
    )
    for r in items:
        writer.writerow(
            [
                r.id,
                r.question,
                r.answer or "",
                r.ground_truth or "",
                r.contexts_json or "[]",
                r.ragas_scores_json or "{}",
                r.reasoning_json or "{}",
                r.human_score if r.human_score is not None else "",
                r.human_note or "",
                "1" if r.is_adopted else "0",
                "1" if r.is_modified else "0",
                _format_datetime(r.created_at),
                _format_datetime(r.updated_at),
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=eval_results.csv"},
    )


def _export_json(items: list) -> StreamingResponse:
    data = [_to_admin_out(r).model_dump() for r in items]
    output = StringIO(json.dumps(data, ensure_ascii=False, indent=2))
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=eval_results.json"},
    )
