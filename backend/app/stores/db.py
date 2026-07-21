from datetime import datetime

import structlog
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from app.config import get_settings

logger = structlog.get_logger()

Base = declarative_base()

_engine = None
_SessionLocal = None


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(32), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default="user")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


def _resolve_mysql_url() -> str:
    """mysql_url 的三级链自举：DB 覆盖存在时优先，但读取覆盖本身需要先连库。

    因此先用 .env/默认值建临时连接读出覆盖值，再以生效值创建正式引擎。
    仅一级自举，不递归；覆盖库不可达或表不存在（首次部署）时回退 .env。
    """
    env_url = get_settings().mysql_url
    try:
        bootstrap = create_engine(env_url, pool_pre_ping=True)
        with bootstrap.connect() as conn:
            row = conn.execute(
                text("SELECT value FROM system_settings WHERE `key` = 'mysql_url' LIMIT 1")
            ).first()
        bootstrap.dispose()
        if row and row[0]:
            logger.info("mysql_url_db_override_applied")
            return row[0]
    except Exception as exc:
        logger.warning("mysql_url_db_override_read_failed", error=str(exc))
    return env_url


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            _resolve_mysql_url(),
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal


def init_db():
    Base.metadata.create_all(bind=get_engine())


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    title = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user = relationship("User", backref="conversations")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(36), index=True, nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    citations_json = Column(Text, default="[]")
    is_refusal = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class IndexMetadata(Base):
    __tablename__ = "index_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kb_id = Column(String(64), nullable=False, default="default", index=True)
    collection_name = Column(String(255), nullable=False)
    bm25_index_path = Column(String(512), nullable=False)
    is_active = Column(Boolean, default=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    parent_id = Column(Integer, ForeignKey("index_metadata.id"), nullable=True)
    reason = Column(String(32), nullable=True)
    source_changes_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)


class EvalResult(Base):
    __tablename__ = "eval_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    contexts_json = Column(Text, default="[]")
    answer = Column(Text)
    ground_truth = Column(Text)
    ragas_scores_json = Column(Text, default="{}")
    reasoning_json = Column(Text, default="{}")
    human_score = Column(Integer)
    human_note = Column(Text)
    is_adopted = Column(Boolean, default=False)
    is_modified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(Text)
    updated_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class KbDirectory(Base):
    __tablename__ = "kb_directories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_id = Column(Integer, ForeignKey("kb_directories.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    parent = relationship(
        "KbDirectory",
        remote_side=[id],
        back_populates="children",
    )
    children = relationship(
        "KbDirectory",
        remote_side=[parent_id],
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    files = relationship(
        "KbFile",
        back_populates="directory",
        cascade="all, delete-orphan",
    )
    graph_schema = relationship(
        "KbGraphSchema",
        back_populates="directory",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uix_kb_directory_parent_name"),
    )


class KbGraphSchema(Base):
    __tablename__ = "kb_graph_schemas"

    directory_id = Column(Integer, ForeignKey("kb_directories.id"), primary_key=True)
    enabled = Column(Boolean, default=False, nullable=False)
    enabled_by_user = Column(Boolean, default=False, nullable=False)
    enabled_at = Column(DateTime, nullable=True)
    shadow_mode = Column(Boolean, default=False, nullable=False)
    entity_types_json = Column(Text, default="[]")
    relation_types_json = Column(Text, default="[]")
    version = Column(Integer, default=1)
    # 图谱构建监控字段
    last_build_at = Column(DateTime, nullable=True)
    last_build_task_id = Column(String(64), nullable=True)
    last_build_entities = Column(Integer, nullable=True)
    last_build_relations = Column(Integer, nullable=True)
    last_build_error = Column(Text, nullable=True)
    last_build_diagnostics_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    directory = relationship("KbDirectory", back_populates="graph_schema")


class GraphShadowRecord(Base):
    __tablename__ = "graph_shadow_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kb_id = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    question = Column(Text, nullable=False)
    vector_answer = Column(Text, nullable=False)
    graph_answer = Column(Text, nullable=True)
    subgraph_context_json = Column(Text, default="{}")
    diff_metrics_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class KbFile(Base):
    __tablename__ = "kb_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    directory_id = Column(Integer, ForeignKey("kb_directories.id"), nullable=False, index=True)
    original_name = Column(String(255), nullable=False)
    stored_name = Column(String(255), nullable=False)
    relative_path = Column(String(512), nullable=False)
    size = Column(Integer, default=0)
    mime_type = Column(String(128))
    status = Column(String(16), default="uploaded")
    last_indexed_at = Column(DateTime, nullable=True)
    last_task_id = Column(String(36), nullable=True)
    content_hash = Column(String(64), nullable=True)
    index_error = Column(Text, nullable=True)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    directory = relationship("KbDirectory", back_populates="files")


class KbUserAccess(Base):
    __tablename__ = "kb_user_access"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kb_id = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(16), default="approved", nullable=False)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint("kb_id", "user_id", name="uix_kb_user_access_kb_user"),
    )


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    log_hash = Column(String(64), unique=True, nullable=False, index=True)
    user_hash = Column(String(64), nullable=True, index=True)
    received_at = Column(DateTime, nullable=False, index=True)
    original_question = Column(Text, nullable=False)
    rewritten_question = Column(Text, nullable=True)
    kb_id = Column(String(64), nullable=True, index=True)
    question_type = Column(String(32), nullable=True)
    config_snapshot = Column(Text, default="{}")
    retrieval_adapter = Column(String(32), nullable=True)
    is_fallback = Column(Boolean, default=False)
    max_score = Column(Float, nullable=True)
    retrieved_chunks = Column(Text, default="[]")
    answer = Column(Text, nullable=True)
    citations_json = Column(Text, default="[]")
    is_refusal = Column(Boolean, default=False)
    is_stale = Column(Boolean, default=False)
    graphrag_enabled = Column(Boolean, default=False)
    graphrag_used = Column(Boolean, default=False)
    latency_ms_rewrite = Column(Integer, nullable=True)
    latency_ms_retrieve = Column(Integer, nullable=True)
    latency_ms_generate = Column(Integer, nullable=True)
    latency_ms_total = Column(Integer, nullable=True)
    tool_trace = Column(JSON, default=list)
    self_querying_dropped_fields = Column(JSON, default=list)
    user_feedback = Column(String(16), nullable=True)
    user_feedback_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class IndexTaskStep(Base):
    __tablename__ = "index_task_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), nullable=False, index=True)
    step_name = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False)
    duration_ms = Column(Integer, nullable=True)
    log = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        index=True,
    )
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint("task_id", "step_name", name="uix_index_task_steps_task_step"),
    )
