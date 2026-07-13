import json
import uuid
from datetime import date, datetime

from sqlalchemy import func

from app.models.schemas import Citation
from app.stores.db import Conversation, Message, get_session_factory


class ConversationStore:
    """会话状态单一拥有者：直接操作 conversations / messages 表。"""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session_factory()

    def create(
        self,
        user_id: int | None = None,
        title: str | None = None,
    ) -> str:
        conversation_id = str(uuid.uuid4())
        with self._session_factory() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    user_id=user_id,
                    title=title,
                )
            )
            session.commit()
        return conversation_id

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        with self._session_factory() as session:
            return session.query(Conversation).filter_by(id=conversation_id).first()

    def list_by_user(
        self,
        user_id: int,
        limit: int = 100,
    ) -> list[Conversation]:
        with self._session_factory() as session:
            return (
                session.query(Conversation)
                .filter_by(user_id=user_id)
                .order_by(Conversation.updated_at.desc())
                .limit(limit)
                .all()
            )

    def update_title(self, conversation_id: str, title: str) -> bool:
        with self._session_factory() as session:
            conversation = session.query(Conversation).filter_by(id=conversation_id).first()
            if not conversation:
                return False
            conversation.title = title
            session.commit()
            return True

    def update_user_id(self, conversation_id: str, user_id: int) -> bool:
        with self._session_factory() as session:
            conversation = session.query(Conversation).filter_by(id=conversation_id).first()
            if not conversation:
                return False
            conversation.user_id = user_id
            session.commit()
            return True

    def get_messages(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> list[Message]:
        with self._session_factory() as session:
            return (
                session.query(Message)
                .filter_by(conversation_id=conversation_id)
                .order_by(Message.created_at.asc())
                .limit(limit)
                .all()
            )

    def get_last_message(self, conversation_id: str) -> Message | None:
        with self._session_factory() as session:
            return (
                session.query(Message)
                .filter_by(conversation_id=conversation_id)
                .order_by(Message.created_at.desc())
                .first()
            )

    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        citations: list[Citation] | None = None,
        is_refusal: bool = False,
    ) -> None:
        with self._session_factory() as session:
            session.add(
                Message(
                    conversation_id=conversation_id,
                    role=role,
                    content=content,
                    citations_json=json.dumps(
                        [c.model_dump() for c in (citations or [])],
                        ensure_ascii=False,
                    ),
                    is_refusal=is_refusal,
                    created_at=datetime.utcnow(),
                )
            )
            session.commit()

    def update_timestamp(self, conversation_id: str) -> None:
        with self._session_factory() as session:
            conversation = session.query(Conversation).filter_by(id=conversation_id).first()
            if conversation:
                conversation.updated_at = datetime.utcnow()
                session.commit()

    def count_today(self) -> int:
        """统计今日（UTC）创建的会话数。"""
        today_start = datetime.combine(date.today(), datetime.min.time())
        with self._session_factory() as session:
            return (
                session.query(func.count(Conversation.id))
                .filter(Conversation.created_at >= today_start)
                .scalar()
                or 0
            )
