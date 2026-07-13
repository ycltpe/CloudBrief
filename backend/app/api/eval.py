
from fastapi import APIRouter, HTTPException

from app.models.schemas import EvalResultOut, HumanFeedbackIn
from app.stores.eval_results import EvalResultStore

router = APIRouter(tags=["eval"])
eval_store = EvalResultStore()


def _to_out(result) -> EvalResultOut:
    return EvalResultOut(
        id=result.id,
        question=result.question,
        answer=result.answer,
        ground_truth=result.ground_truth,
        contexts_json=result.contexts_json,
        ragas_scores_json=result.ragas_scores_json,
        reasoning_json=result.reasoning_json,
        human_score=result.human_score,
        human_note=result.human_note,
        is_adopted=result.is_adopted,
        is_modified=result.is_modified,
        created_at=result.created_at.isoformat() if result.created_at else None,
        updated_at=result.updated_at.isoformat() if result.updated_at else None,
    )


@router.get("/eval/results", response_model=list[EvalResultOut])
async def list_eval_results(limit: int = 100, offset: int = 0):
    try:
        results = eval_store.list_all(limit=limit, offset=offset)
        return [_to_out(r) for r in results]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/eval/results/{result_id}", response_model=EvalResultOut)
async def get_eval_result(result_id: int):
    try:
        result = eval_store.get(result_id)
        if not result:
            raise HTTPException(status_code=404, detail="Eval result not found")
        return _to_out(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/eval/results/{result_id}/feedback", response_model=EvalResultOut)
async def feedback_eval_result(result_id: int, feedback: HumanFeedbackIn):
    try:
        result = eval_store.update_feedback(result_id, feedback)
        if not result:
            raise HTTPException(status_code=404, detail="Eval result not found")
        return _to_out(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
