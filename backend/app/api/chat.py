import asyncio
import json
import time

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.dependencies import get_current_user_optional
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationOut,
    ConversationSummary,
    ConversationUpdateIn,
    UserOut,
)
from app.pipelines.generation import StreamEvent
from app.services.chat_service import ChatService
from app.stores.graph_store import GraphStore

logger = structlog.get_logger()
router = APIRouter(tags=["chat"])


def get_chat_service(request: Request) -> ChatService:
    graph_store = request.app.state.graph_store
    return ChatService(graph_store=graph_store if isinstance(graph_store, GraphStore) else None)


def _format_sse(event: StreamEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: UserOut | None = Depends(get_current_user_optional),
    chat_service: ChatService = Depends(get_chat_service),
):
    try:
        logger.info(
            "chat_request",
            user_id=current_user.id if current_user else None,
            has_conversation_id=bool(request.conversation_id),
            stream=request.stream,
        )
        if request.stream:
            async def event_generator():
                stream_start = time.perf_counter()
                event_count = 0
                async for event in chat_service.ask_stream(request, current_user=current_user):
                    event_count += 1
                    yield _format_sse(event)
                logger.info(
                    "chat_stream_response_closed",
                    user_id=current_user.id if current_user else None,
                    event_count=event_count,
                    latency_ms=int((time.perf_counter() - stream_start) * 1000),
                )

            logger.info(
                "chat_stream_response_start",
                user_id=current_user.id if current_user else None,
            )
            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        return await chat_service.ask(request, current_user=current_user)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.error("chat_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/chat/{conversation_id}")
async def get_conversation_history(
    conversation_id: str,
    current_user: UserOut | None = Depends(get_current_user_optional),
    chat_service: ChatService = Depends(get_chat_service),
):
    try:
        logger.info(
            "chat_history_request",
            conversation_id=conversation_id,
            user_id=current_user.id if current_user else None,
        )
        return {
            "conversation_id": conversation_id,
            "messages": await asyncio.to_thread(chat_service.get_history, conversation_id),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("chat_history_failed", conversation_id=conversation_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    current_user: UserOut | None = Depends(get_current_user_optional),
    chat_service: ChatService = Depends(get_chat_service),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="需要登录才能查看会话列表")
    try:
        logger.info("list_conversations", user_id=current_user.id)
        return await asyncio.to_thread(chat_service.list_conversations, current_user.id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("list_conversations_failed", user_id=current_user.id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def update_conversation_title(
    conversation_id: str,
    body: ConversationUpdateIn,
    current_user: UserOut | None = Depends(get_current_user_optional),
    chat_service: ChatService = Depends(get_chat_service),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="需要登录才能编辑标题")
    try:
        logger.info(
            "update_conversation_title",
            conversation_id=conversation_id,
            user_id=current_user.id,
        )
        ok = await asyncio.to_thread(
            chat_service.update_conversation_title,
            conversation_id=conversation_id,
            user_id=current_user.id,
            title=body.title,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="会话不存在或无权限")
        conversation = await asyncio.to_thread(
            chat_service.conversation_store.get_conversation, conversation_id
        )
        return ConversationOut(
            id=conversation.id,
            title=conversation.title,
            updated_at=conversation.updated_at.isoformat() if conversation.updated_at else None,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "update_conversation_title_failed",
            conversation_id=conversation_id,
            user_id=current_user.id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/chat/{conversation_id}/agentic-state")
async def get_agentic_state(
    conversation_id: str,
    current_user: UserOut | None = Depends(get_current_user_optional),
    chat_service: ChatService = Depends(get_chat_service),
):
    """获取指定会话的 agentic 编排状态快照（含中断等待状态）。"""
    try:
        state = await chat_service.get_agentic_state(conversation_id)
        return {
            "conversation_id": conversation_id,
            "state": state,
            "interrupted": bool(state.get("resume_payload") is None and state.get("sub_questions")),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "agentic_state_failed",
            conversation_id=conversation_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/chat/{conversation_id}/agentic-resume")
async def resume_agentic_stream(
    conversation_id: str,
    resume_payload: dict = Body(default={}),
    current_user: UserOut | None = Depends(get_current_user_optional),
    chat_service: ChatService = Depends(get_chat_service),
):
    """恢复被中断的 agentic 编排流，以 SSE 形式继续输出后续事件。"""
    try:
        async def event_generator():
            stream_start = time.perf_counter()
            event_count = 0
            async for event in chat_service.resume_agentic_stream(
                conversation_id=conversation_id,
                resume_payload=resume_payload,
            ):
                event_count += 1
                yield _format_sse(event)
            logger.info(
                "agentic_resume_stream_response_closed",
                conversation_id=conversation_id,
                user_id=current_user.id if current_user else None,
                event_count=event_count,
                latency_ms=int((time.perf_counter() - stream_start) * 1000),
            )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "agentic_resume_failed",
            conversation_id=conversation_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))
