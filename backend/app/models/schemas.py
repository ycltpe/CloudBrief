from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Citation(BaseModel):
    chunk_id: str
    source_title: str
    source_type: str
    updated_at: str
    content_summary: str


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    question: str = Field(..., min_length=1, max_length=2000)
    stream: bool = True
    kb_ids: list[str] | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    is_refusal: bool = False
    is_stale: bool = False
    thinking: str | None = None
    kb_id: str | None = None


class ConversationSummary(BaseModel):
    id: str
    title: str | None = None
    preview: str | None = None
    updated_at: str | None = None


class ConversationUpdateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class ConversationOut(BaseModel):
    id: str
    title: str | None = None
    updated_at: str | None = None


class IndexStep(BaseModel):
    name: str
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    duration_ms: int | None = None
    log: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class IndexRebuildResponse(BaseModel):
    task_id: str


class IndexTaskStatus(BaseModel):
    task_id: str
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    steps: list[IndexStep] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    error: str | None = None


class SSEEvent(BaseModel):
    event: str = "step"
    data: dict[str, Any]


class ErrorResponse(BaseModel):
    error: dict[str, Any]


class EvalResultOut(BaseModel):
    id: int
    question: str
    answer: str | None = None
    ground_truth: str | None = None
    contexts_json: str = "[]"
    ragas_scores_json: str = "{}"
    reasoning_json: str = "{}"
    human_score: int | None = None
    human_note: str | None = None
    is_adopted: bool = False
    is_modified: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class HumanFeedbackIn(BaseModel):
    human_score: int | None = Field(None, ge=1, le=5)
    human_note: str | None = None
    is_adopted: bool = False
    is_modified: bool = False


class TokenPayload(BaseModel):
    user_id: int
    exp: int | None = None


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=6, max_length=128)
    role: Literal["admin", "qa", "user"] = "user"

    @field_validator("username")
    @classmethod
    def username_lower(cls, v: str) -> str:
        return v.lower()


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    created_at: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)

    @field_validator("username")
    @classmethod
    def username_lower(cls, v: str) -> str:
        return v.lower()


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AdminUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=6, max_length=128)
    role: Literal["admin", "qa", "user"] = "user"

    @field_validator("username")
    @classmethod
    def username_lower(cls, v: str) -> str:
        return v.lower()


class UserListResponse(BaseModel):
    total: int
    items: list[UserOut]


class SettingItemOut(BaseModel):
    key: str
    label: str
    description: str
    type: str
    value: Any
    default: Any
    options: list[str] | None = None
    min: int | float | None = None
    max: int | float | None = None


class SettingGroupOut(BaseModel):
    group: str
    items: list[SettingItemOut]


class SettingsResponse(BaseModel):
    groups: list[SettingGroupOut]


class SettingsUpdateRequest(BaseModel):
    values: dict[str, Any]


class SettingsUpdateResponse(BaseModel):
    updated: int
    groups: list[SettingGroupOut]


# 知识库管理
class KbDirectoryOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    parent_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    file_count: int = 0
    graphrag_enabled: bool = False
    children: list["KbDirectoryOut"] = Field(default_factory=list)


KbFileStatus = Literal["uploaded", "indexing", "indexed", "failed"]


class KbFileOut(BaseModel):
    id: int
    directory_id: int
    original_name: str
    stored_name: str
    size: int
    mime_type: str | None = None
    status: KbFileStatus = "uploaded"
    task_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class KbFileUploadResponse(BaseModel):
    file: KbFileOut
    task_id: str | None = None


class KbFileIndexResponse(BaseModel):
    task_id: str


class IndexFileTaskPayload(BaseModel):
    file_id: int


class KbDirectoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[^/\\]+$")
    description: str | None = Field(None, max_length=500)
    parent_id: int | None = None
    graphrag_enabled: bool = False


class KbTreeResponse(BaseModel):
    directories: list[KbDirectoryOut]


class KbFileListResponse(BaseModel):
    files: list[KbFileOut]


class KbDirectoryDeleteResponse(BaseModel):
    message: str
    deleted_files: int
    deleted_directories: int


class KbRebuildResponse(BaseModel):
    task_id: str


# 知识库访问权限
class KbAccessStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class KbAccessRequestIn(BaseModel):
    kb_id: str = Field(..., min_length=1)


class KbAccessReviewIn(BaseModel):
    access_id: int | None = None
    status: Literal["approved", "rejected"]


class KbAccessRequestOut(BaseModel):
    id: int
    kb_id: str
    user_id: int
    username: str | None = None
    status: str
    created_by: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class KbAccessListResponse(BaseModel):
    total: int
    items: list[KbAccessRequestOut]


class KbInfoOut(BaseModel):
    kb_id: str
    name: str
    description: str | None = None


class UserAccessibleKbListResponse(BaseModel):
    items: list[KbInfoOut]


# GraphRAG 管理
class EntityTypeOut(BaseModel):
    name: str
    description: str | None = None
    examples: list[str] = Field(default_factory=list)


class RelationTypeOut(BaseModel):
    name: str
    description: str | None = None
    source_types: list[str] = Field(default_factory=list)
    target_types: list[str] = Field(default_factory=list)


class KbGraphSchemaOut(BaseModel):
    directory_id: int
    enabled: bool
    enabled_by_user: bool
    shadow_mode: bool
    entity_types: list[EntityTypeOut] = Field(default_factory=list)
    relation_types: list[RelationTypeOut] = Field(default_factory=list)
    version: int = 1
    updated_at: str | None = None


class KbGraphSchemaUpdate(BaseModel):
    enabled: bool | None = None
    enabled_by_user: bool | None = None
    shadow_mode: bool | None = None
    entity_types: list[EntityTypeOut] | None = None
    relation_types: list[RelationTypeOut] | None = None


class KbGraphSchemaRecommendResponse(BaseModel):
    directory_id: int
    entity_types: list[EntityTypeOut] = Field(default_factory=list)
    relation_types: list[RelationTypeOut] = Field(default_factory=list)


class KbRebuildGraphResponse(BaseModel):
    task_id: str


class GraphShadowReportOut(BaseModel):
    id: int
    kb_id: str
    user_id: int | None = None
    question: str
    vector_answer: str
    graph_answer: str | None = None
    diff_ratio: float | None = None
    created_at: str | None = None


class GraphShadowReportListResponse(BaseModel):
    total: int
    items: list[GraphShadowReportOut]
    avg_diff_ratio: float | None = None


# RAGAS 评测审计（admin/qa）
class AdminEvalContext(BaseModel):
    chunk_id: str
    source_title: str
    source_type: str
    content: str
    updated_at: str | None = None


class AdminEvalResultOut(BaseModel):
    id: int
    question: str
    answer: str | None = None
    ground_truth: str | None = None
    contexts: list[dict[str, Any]] = Field(default_factory=list)
    ragas_scores: dict[str, Any] = Field(default_factory=dict)
    reasoning: dict[str, Any] = Field(default_factory=dict)
    human_score: int | None = None
    human_note: str | None = None
    is_adopted: bool = False
    is_modified: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class AdminEvalListResponse(BaseModel):
    total: int
    items: list[AdminEvalResultOut]


class AdminEvalFeedbackIn(BaseModel):
    human_score: int | None = Field(None, ge=1, le=5)
    human_note: str | None = None
    is_adopted: bool = False
    is_modified: bool = False


# Dashboard 数据聚合
class DashboardIndexStatus(BaseModel):
    is_ready: bool = False
    active_collection: str | None = None
    bm25_index_path: str | None = None
    last_task_status: str = "unknown"
    last_task_updated_at: str | None = None


class DashboardEvalScores(BaseModel):
    context_precision: float | None = None
    context_recall: float | None = None
    faithfulness: float | None = None
    answer_relevancy: float | None = None


class DashboardGraphRagStatus(BaseModel):
    enabled_kb_count: int = 0
    total_kb_count: int = 0
    last_build_at: str | None = None
    last_build_entities: int | None = None
    last_build_relations: int | None = None
    last_build_error: str | None = None
    avg_query_duration_ms: float | None = None


class DashboardRecentTask(BaseModel):
    task_id: str
    status: str = "pending"
    created_at: str | None = None


class DashboardDependencyStatus(BaseModel):
    name: str
    status: Literal["healthy", "degraded", "unhealthy", "unknown"] = "unknown"
    latency_ms: int | None = None
    message: str | None = None


class DashboardSystemHealth(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy", "unknown"] = "unknown"
    dependencies: list[DashboardDependencyStatus] = Field(default_factory=list)
    checked_at: str | None = None


class AdminDashboardResponse(BaseModel):
    user_count: int = 0
    conversation_count_today: int = 0
    index_status: DashboardIndexStatus = Field(default_factory=DashboardIndexStatus)
    latest_eval_scores: DashboardEvalScores = Field(default_factory=DashboardEvalScores)
    recent_tasks: list[DashboardRecentTask] = Field(default_factory=list)
    graph_rag_status: DashboardGraphRagStatus = Field(default_factory=DashboardGraphRagStatus)
    system_health: DashboardSystemHealth = Field(default_factory=DashboardSystemHealth)
