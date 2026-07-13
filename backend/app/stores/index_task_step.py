from datetime import datetime

from sqlalchemy import case

from app.stores.db import IndexTaskStep, get_session_factory


class IndexTaskStepStore:
    """索引构建任务步骤持久化仓库。

    每个 (task_id, step_name) 只保留最新状态，与 Redis 原 setex 覆盖语义一致。
    """

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session_factory()

    def upsert_step(
        self,
        task_id: str,
        step_name: str,
        status: str,
        duration_ms: int | None = None,
        log: str | None = None,
    ) -> IndexTaskStep:
        """插入或更新任务步骤，返回最新行。"""
        with self._session_factory() as session:
            row = (
                session.query(IndexTaskStep)
                .filter_by(task_id=task_id, step_name=step_name)
                .first()
            )
            if row:
                row.status = status
                row.duration_ms = duration_ms
                row.log = log
                row.updated_at = datetime.utcnow()
            else:
                row = IndexTaskStep(
                    task_id=task_id,
                    step_name=step_name,
                    status=status,
                    duration_ms=duration_ms,
                    log=log,
                )
                session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def list_steps(
        self,
        task_id: str,
        after_updated_at: datetime | None = None,
    ) -> list[IndexTaskStep]:
        """按更新时间升序列出任务步骤；支持按 updated_at 过滤。"""
        with self._session_factory() as session:
            query = session.query(IndexTaskStep).filter_by(task_id=task_id)
            if after_updated_at is not None:
                query = query.filter(IndexTaskStep.updated_at > after_updated_at)
            return query.order_by(
                IndexTaskStep.updated_at.asc(),
                case((IndexTaskStep.step_name == "task", 1), else_=0).asc(),
                IndexTaskStep.id.asc(),
            ).all()
