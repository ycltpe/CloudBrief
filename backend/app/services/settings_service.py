import threading
import time
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field, SecretStr

from app.config import get_settings
from app.models.schemas import SettingGroupOut, SettingItemOut
from app.stores.db import SystemSetting
from app.stores.settings import SettingsStore

logger = structlog.get_logger()

SECRET_MASK = "********"

# 分组展示顺序
GROUP_ORDER = [
    "业务阈值",
    "功能开关",
    "适配器",
    "大语言模型",
    "向量模型",
    "Reranker 模型",
    "文档解析",
    "GraphRAG 监控",
    "存储连接",
    "认证与安全",
    "系统",
]


class SettingMeta(BaseModel):
    key: str
    label: str
    description: str
    type: str = Field(..., pattern=r"^(float|int|str|bool|choice)$")
    default: Any
    group: str = "系统"
    options: list[str] | None = None
    min: int | float | None = None
    max: int | float | None = None
    # secret 项在 API 出参中脱敏，且提交空值视为不修改
    secret: bool = False
    # 进程启动期读取的连接/端口类配置，DB 覆盖在下次重启后生效
    restart_required: bool = False
    # 修改后需重建索引才能对存量数据生效
    requires_reindex: bool = False


KNOWN_SETTINGS: dict[str, SettingMeta] = {}


def _register(meta: SettingMeta) -> None:
    KNOWN_SETTINGS[meta.key] = meta


# ---- 业务阈值 ----
_register(SettingMeta(
    key="refusal_threshold", label="拒答阈值", group="业务阈值",
    description="答案置信度低于该值时触发拒答（0-1）",
    type="float", default=0.3, min=0.0, max=1.0,
))
_register(SettingMeta(
    key="stale_threshold_days", label="知识时效阈值（天）", group="业务阈值",
    description="超过该天数未更新的文档会被标记为可能过期",
    type="int", default=90, min=1,
))
_register(SettingMeta(
    key="max_history_rounds", label="最大历史轮数", group="业务阈值",
    description="对话上下文保留的最大轮数",
    type="int", default=10, min=0,
))
_register(SettingMeta(
    key="request_timeout", label="模型请求超时（秒）", group="业务阈值",
    description="调用外部模型/向量库的最大等待时间",
    type="int", default=30, min=1,
))

# ---- 功能开关 ----
_register(SettingMeta(
    key="auto_index_on_upload", label="上传后自动构建索引", group="功能开关",
    description="文件上传成功后是否自动触发单文件索引",
    type="bool", default=True,
))
_register(SettingMeta(
    key="self_querying_enabled", label="Self-Querying 元数据过滤", group="功能开关",
    description="启用后，系统会尝试把用户问题中的时间/来源类型约束自动翻译为 Milvus filter",
    type="bool", default=False,
))
_register(SettingMeta(
    key="ocr_enabled", label="扫描件 OCR 识别", group="功能开关",
    description="对无文字层的 PDF 页调用视觉模型识别文字",
    type="bool", default=True,
))

# ---- 适配器 ----
_register(SettingMeta(
    key="retrieval_adapter", label="检索适配器", group="适配器",
    description="检索阶段使用的实现适配器",
    type="choice", default="native", options=["native", "langchain"],
))
_register(SettingMeta(
    key="orchestration_mode", label="编排模式", group="适配器",
    description="问答链路的编排实现；agentic 为 LangGraph 图编排，切换后新会话即时生效",
    type="choice", default="native", options=["native", "langchain", "agentic"],
))
_register(SettingMeta(
    key="agentic_interrupt_enabled", label="Agentic 编排中断点", group="适配器",
    description="启用后，agentic 多跳分解后会暂停执行，等待人工确认再继续（触发式）",
    type="bool", default=False,
))
_register(SettingMeta(
    key="parser", label="文档解析器", group="适配器",
    description="文档解析阶段使用的实现适配器，重建索引后生效",
    type="choice", default="native", options=["native", "llamaindex"],
    requires_reindex=True,
))

# ---- 大语言模型 ----
_register(SettingMeta(
    key="llm_provider", label="生成模型 Provider", group="大语言模型",
    description="云端 DashScope 或本地部署；本地模式为权威路径，不会回退云端，避免私有化数据外发",
    type="choice", default="dashscope", options=["dashscope", "local"],
))
_register(SettingMeta(
    key="llm_api_key", label="LLM API Key", group="大语言模型",
    description="云端生成模型的调用密钥，存储于数据库，出参脱敏",
    type="str", default="", secret=True,
))
_register(SettingMeta(
    key="llm_base_url", label="LLM 云端端点", group="大语言模型",
    description="云端生成模型的 OpenAI-compatible 端点",
    type="str", default="https://dashscope.aliyuncs.com/compatible-mode/v1",
))
_register(SettingMeta(
    key="llm_model", label="生成模型", group="大语言模型",
    description="云端答案生成使用的模型名称",
    type="str", default="qwen3.7-plus",
))
_register(SettingMeta(
    key="local_llm_url", label="本地生成服务地址", group="大语言模型",
    description="本地 vLLM/Ollama 的 OpenAI-compatible 端点，需自建服务",
    type="str", default="http://127.0.0.1:8000/v1",
))
_register(SettingMeta(
    key="local_llm_model", label="本地生成模型名称", group="大语言模型",
    description="本地服务上部署的生成模型名称",
    type="str", default="Qwen/Qwen2.5-7B-Instruct",
))

# ---- 向量模型 ----
_register(SettingMeta(
    key="embedding_provider", label="向量模型 Provider", group="向量模型",
    description="云端 DashScope 或本地部署；切换后向量空间变化，必须重建索引",
    type="choice", default="dashscope", options=["dashscope", "local"],
    requires_reindex=True,
))
_register(SettingMeta(
    key="embedding_api_key", label="Embedding API Key", group="向量模型",
    description="云端 Embedding 模型的调用密钥，存储于数据库，出参脱敏",
    type="str", default="", secret=True,
))
_register(SettingMeta(
    key="embedding_base_url", label="Embedding 云端端点", group="向量模型",
    description="云端 Embedding 模型的 OpenAI-compatible 端点",
    type="str", default="https://dashscope.aliyuncs.com/compatible-mode/v1",
))
_register(SettingMeta(
    key="embedding_model", label="Embedding 模型", group="向量模型",
    description="云端文本向量化使用的模型名称，修改后必须重建索引",
    type="str", default="text-embedding-v3", requires_reindex=True,
))
_register(SettingMeta(
    key="embedding_dim", label="Embedding 维度", group="向量模型",
    description="向量化输出维度，必须与当前模型一致（text-embedding-v3 为 1536，bge-m3 为 1024），修改后必须重建索引",
    type="int", default=1536, min=1, requires_reindex=True,
))
_register(SettingMeta(
    key="embedding_batch_size", label="Embedding 批大小", group="向量模型",
    description="单次 Embedding 请求的文本条数（DashScope text-embedding-v3 上限为 10）",
    type="int", default=10, min=1,
))
_register(SettingMeta(
    key="local_embedding_url", label="本地 Embedding 服务地址", group="向量模型",
    description="本地 Embedding 服务的 OpenAI-compatible 端点，需自建服务",
    type="str", default="http://127.0.0.1:8000/v1",
))
_register(SettingMeta(
    key="local_embedding_model", label="本地 Embedding 模型名称", group="向量模型",
    description="本地服务上部署的 Embedding 模型名称（如 BAAI/bge-m3，维度 1024），修改后必须重建索引",
    type="str", default="BAAI/bge-m3", requires_reindex=True,
))

# ---- Reranker 模型 ----
_register(SettingMeta(
    key="reranker_provider", label="重排模型 Provider", group="Reranker 模型",
    description="云端 DashScope 或本地 vLLM/TEI 部署的重排模型",
    type="choice", default="dashscope", options=["dashscope", "local"],
))
_register(SettingMeta(
    key="reranker_api_key", label="Reranker API Key", group="Reranker 模型",
    description="云端重排模型的调用密钥，存储于数据库，出参脱敏",
    type="str", default="", secret=True,
))
_register(SettingMeta(
    key="rerank_base_url", label="重排云端端点", group="Reranker 模型",
    description="云端重排模型的 OpenAI-compatible 端点",
    type="str", default="https://dashscope.aliyuncs.com/compatible-api/v1",
))
_register(SettingMeta(
    key="reranker_model", label="重排模型", group="Reranker 模型",
    description="云端重排阶段使用的模型名称",
    type="str", default="qwen3-rerank",
))
_register(SettingMeta(
    key="local_reranker_url", label="本地重排服务地址", group="Reranker 模型",
    description="本地 vLLM/TEI reranker 的 OpenAI-compatible 端点，如 http://127.0.0.1:8000/v1",
    type="str", default="http://127.0.0.1:8000/v1",
))
_register(SettingMeta(
    key="local_reranker_model", label="本地重排模型名称", group="Reranker 模型",
    description="本地服务上部署的模型名称，如 BAAI/bge-reranker-large",
    type="str", default="BAAI/bge-reranker-large",
))

# ---- 文档解析 ----
_register(SettingMeta(
    key="pdf_batch_page_threshold", label="PDF 分批解析阈值（页）", group="文档解析",
    description="超过该页数的 PDF 按批解析并推送进度心跳",
    type="int", default=50, min=1,
))
_register(SettingMeta(
    key="pdf_page_batch_size", label="PDF 每批页数", group="文档解析",
    description="大 PDF 分批解析时每批处理的页数",
    type="int", default=25, min=1,
))
_register(SettingMeta(
    key="pdf_max_pages", label="PDF 页数上限", group="文档解析",
    description="单份 PDF 超过该页数拒绝解析，防止占满索引 worker",
    type="int", default=2000, min=1,
))
_register(SettingMeta(
    key="ocr_api_key", label="OCR API Key", group="文档解析",
    description="扫描件 OCR 视觉模型的调用密钥（DashScope），存储于数据库，出参脱敏",
    type="str", default="", secret=True,
))
_register(SettingMeta(
    key="ocr_base_url", label="OCR 云端端点", group="文档解析",
    description="OCR 视觉模型的 OpenAI-compatible 端点",
    type="str", default="https://dashscope.aliyuncs.com/compatible-mode/v1",
))
_register(SettingMeta(
    key="ocr_model", label="OCR 模型", group="文档解析",
    description="扫描件 OCR 使用的视觉模型名称",
    type="str", default="qwen-vl-ocr-latest",
))
_register(SettingMeta(
    key="ocr_timeout_seconds", label="OCR 超时（秒）", group="文档解析",
    description="单页 OCR 调用的最大等待时间",
    type="float", default=120.0, min=1.0,
))
_register(SettingMeta(
    key="pdf_ocr_dpi", label="OCR 渲染 DPI", group="文档解析",
    description="PDF 页转图片时的渲染精度，越高越清晰但越慢",
    type="int", default=200, min=72, max=600,
))

# ---- GraphRAG 监控 ----
_register(SettingMeta(
    key="graphrag_slow_query_threshold_ms", label="GraphRAG 慢查询阈值（ms）", group="GraphRAG 监控",
    description="Neo4j 查询耗时超过该值时输出 WARN 日志",
    type="int", default=500, min=1,
))
_register(SettingMeta(
    key="graphrag_freshness_threshold_days", label="GraphRAG 图谱新鲜度阈值（天）", group="GraphRAG 监控",
    description="超过该天数未更新图索引时输出 WARN 日志",
    type="int", default=7, min=1,
))
_register(SettingMeta(
    key="graphrag_min_extraction_entities", label="GraphRAG 最小实体数阈值", group="GraphRAG 监控",
    description="单次抽取实体数低于该值时输出 WARN 日志",
    type="int", default=1, min=0,
))
_register(SettingMeta(
    key="graphrag_timeout_seconds", label="GraphRAG 抽取超时（秒）", group="GraphRAG 监控",
    description="图抽取调用 LLM 时的最大等待时间，建议 60-300 秒",
    type="float", default=120.0, min=1.0, max=600.0,
))

# ---- 存储连接 ----
_register(SettingMeta(
    key="mysql_url", label="MySQL 连接串", group="存储连接",
    description="业务数据库连接串（含凭据，出参脱敏）。自举读取：先用 .env 连接读出覆盖值，下次重启生效",
    type="str", default="", secret=True, restart_required=True,
))
_register(SettingMeta(
    key="redis_url", label="Redis 连接串", group="存储连接",
    description="缓存/队列/Pub-Sub 连接串（含凭据时出参脱敏）。Celery broker 在进程启动时读取，重启后生效",
    type="str", default="", secret=True, restart_required=True,
))
_register(SettingMeta(
    key="milvus_uri", label="Milvus 地址", group="存储连接",
    description="向量数据库连接地址",
    type="str", default="http://localhost:19531",
))
_register(SettingMeta(
    key="milvus_collection", label="Milvus Collection 前缀", group="存储连接",
    description="新建索引 collection 的命名前缀，仅影响后续重建",
    type="str", default="cloudbrief_chunks",
))
_register(SettingMeta(
    key="neo4j_uri", label="Neo4j 地址", group="存储连接",
    description="图数据库 Bolt 连接地址，主进程启动时建立连接，重启后生效",
    type="str", default="bolt://localhost:7687", restart_required=True,
))
_register(SettingMeta(
    key="neo4j_user", label="Neo4j 用户名", group="存储连接",
    description="图数据库用户名，重启后生效",
    type="str", default="neo4j", restart_required=True,
))
_register(SettingMeta(
    key="neo4j_password", label="Neo4j 密码", group="存储连接",
    description="图数据库密码，存储于数据库，出参脱敏，重启后生效",
    type="str", default="", secret=True, restart_required=True,
))
_register(SettingMeta(
    key="bm25_index_path", label="BM25 索引路径", group="存储连接",
    description="BM25 索引文件的存放路径（新索引写到其同级目录）",
    type="str", default="./data/bm25_index.pkl",
))
_register(SettingMeta(
    key="checkpoint_backend", label="LangGraph 编排状态持久化后端", group="存储连接",
    description="agentic 模式下 LangGraph 编排状态的持久化后端：sqlite（单进程本地）或 redis（多进程共享，复用 REDIS_URL）",
    type="choice", default="sqlite", options=["sqlite", "redis"], restart_required=True,
))
_register(SettingMeta(
    key="checkpoint_sqlite_path", label="LangGraph 编排状态 SQLite 路径", group="存储连接",
    description="agentic 模式下 LangGraph 编排状态持久化的 SQLite 文件路径",
    type="str", default="./data/checkpoints.sqlite",
    restart_required=True,
))
_register(SettingMeta(
    key="checkpoint_redis_prefix", label="LangGraph checkpoint Redis key 前缀", group="存储连接",
    description="Redis checkpointer 的 key 前缀，避免与现有缓存/锁/Pub-Sub key 冲突",
    type="str", default="cloudbrief:checkpoint", restart_required=True,
))
_register(SettingMeta(
    key="checkpoint_redis_ttl", label="LangGraph checkpoint Redis 过期时间（分钟）", group="存储连接",
    description="Redis checkpoint key 的过期时间，0 表示不过期；过期后状态不可恢复",
    type="int", default=0, min=0, restart_required=True,
))
_register(SettingMeta(
    key="kb_storage_path", label="知识库文件存储路径", group="存储连接",
    description="上传文件在服务器上的存放目录",
    type="str", default="",
))
_register(SettingMeta(
    key="kb_max_file_size", label="上传文件大小上限（字节）", group="存储连接",
    description="单个上传文件的最大字节数，默认 50MB",
    type="int", default=50 * 1024 * 1024, min=1,
))

# ---- 认证与安全 ----
_register(SettingMeta(
    key="jwt_secret_key", label="JWT 签名密钥", group="认证与安全",
    description="访问令牌签名密钥，存储于数据库，出参脱敏。修改后所有已签发 token 立即失效",
    type="str", default="", secret=True,
))
_register(SettingMeta(
    key="jwt_algorithm", label="JWT 签名算法", group="认证与安全",
    description="访问令牌签名算法",
    type="str", default="HS256",
))
_register(SettingMeta(
    key="jwt_access_token_expire_minutes", label="令牌有效期（分钟）", group="认证与安全",
    description="访问令牌的有效时长",
    type="int", default=1440, min=1,
))

# ---- 系统 ----
_register(SettingMeta(
    key="log_level", label="日志级别", group="系统",
    description="应用日志输出级别，进程启动时读取，重启后生效",
    type="choice", default="INFO", options=["DEBUG", "INFO", "WARNING", "ERROR"],
    restart_required=True,
))
_register(SettingMeta(
    key="backend_port", label="后端端口", group="系统",
    description="API 服务监听端口，进程启动时读取，重启后生效",
    type="int", default=8001, min=1, max=65535, restart_required=True,
))


class SettingsService:
    """运行期配置统一入口：DB 覆盖 → .env 配置 → 代码默认值，三级回退。

    DB 读取带进程级缓存（全量快照 + TTL），update/reset 时同步失效；
    DB 不可用时负缓存空快照并回退到 .env/默认值，不影响业务链路。
    """

    _CACHE_TTL_SECONDS = 60.0
    _cache_lock = threading.Lock()
    _cache_snapshot: tuple[float, dict[str, str]] | None = None

    def __init__(self, store: SettingsStore | None = None):
        self.store = store or SettingsStore()

    @classmethod
    def invalidate_cache(cls) -> None:
        with cls._cache_lock:
            cls._cache_snapshot = None

    def get_known_setting_keys(self) -> list[str]:
        return list(KNOWN_SETTINGS.keys())

    def get_meta(self, key: str) -> SettingMeta | None:
        return KNOWN_SETTINGS.get(key)

    def get_default(self, key: str) -> Any:
        """第二、三级回退：.env 显式配置优先，否则代码默认值。"""
        cfg = get_settings()
        meta = KNOWN_SETTINGS.get(key)
        if hasattr(cfg, key):
            value = getattr(cfg, key)
            if isinstance(value, SecretStr):
                return value.get_secret_value()
            if isinstance(value, Path):
                return str(value)
            return value
        if meta is None:
            raise ValueError(f"未知配置项: {key}")
        return meta.default

    def _load_db_snapshot(self) -> dict[str, str]:
        # 缓存读写必须走类属性：实例属性会遮蔽类属性，导致 invalidate_cache 清不掉
        cls = type(self)
        now = time.monotonic()
        with cls._cache_lock:
            if cls._cache_snapshot is not None:
                cached_at, snapshot = cls._cache_snapshot
                if now - cached_at < cls._CACHE_TTL_SECONDS:
                    return snapshot
        try:
            rows = self.store.get_all()
            snapshot = {row.key: row.value for row in rows}
        except Exception as exc:
            logger.warning("runtime_settings_db_read_failed", error=str(exc))
            snapshot = {}
        with cls._cache_lock:
            cls._cache_snapshot = (now, snapshot)
        return snapshot

    def get_source(self, key: str) -> str:
        """当前生效值来源：db / env / default。"""
        if key in self._load_db_snapshot():
            return "db"
        if key in get_settings().model_fields_set:
            return "env"
        return "default"

    def _coerce_value(self, meta: SettingMeta, raw: str) -> str:
        if meta.type == "float":
            try:
                v = float(raw)
            except ValueError:
                raise ValueError(f"{meta.label} 必须是数字")
            if meta.min is not None and v < meta.min:
                raise ValueError(f"{meta.label} 不能小于 {meta.min}")
            if meta.max is not None and v > meta.max:
                raise ValueError(f"{meta.label} 不能大于 {meta.max}")
            return str(v)

        if meta.type == "int":
            try:
                v = int(raw)
            except ValueError:
                raise ValueError(f"{meta.label} 必须是整数")
            if meta.min is not None and v < meta.min:
                raise ValueError(f"{meta.label} 不能小于 {meta.min}")
            if meta.max is not None and v > meta.max:
                raise ValueError(f"{meta.label} 不能大于 {meta.max}")
            return str(v)

        if meta.type == "choice":
            if raw not in (meta.options or []):
                raise ValueError(f"{meta.label} 必须是 {meta.options} 之一")
            return raw

        if meta.type == "bool":
            lowered = raw.lower()
            if lowered not in ("true", "false", "1", "0"):
                raise ValueError(f"{meta.label} 必须是布尔值")
            return "true" if lowered in ("true", "1") else "false"

        # str 原样存储（去除首尾空白）
        return raw.strip()

    def validate_and_coerce(self, key: str, raw_value: Any) -> str:
        meta = KNOWN_SETTINGS.get(key)
        if not meta:
            raise ValueError(f"未知配置项: {key}")
        return self._coerce_value(meta, str(raw_value))

    def get_runtime_value(self, key: str) -> Any:
        """供业务代码读取运行期配置：DB 优先，其次 .env 配置，最后代码默认值。"""
        meta = KNOWN_SETTINGS.get(key)
        default = self.get_default(key)
        raw = self._load_db_snapshot().get(key)
        if raw is None:
            return default
        if meta is None:
            return raw
        try:
            coerced = self._coerce_value(meta, raw)
        except ValueError:
            logger.warning("invalid_runtime_setting", key=key, raw=raw, default=default)
            return default
        if meta.type == "float":
            return float(coerced)
        if meta.type == "int":
            return int(coerced)
        if meta.type == "bool":
            return coerced == "true"
        return coerced

    def list_groups(self) -> list[SettingGroupOut]:
        db_values = self._load_db_snapshot()
        env_keys = get_settings().model_fields_set

        grouped: dict[str, list[SettingItemOut]] = {}
        for key, meta in KNOWN_SETTINGS.items():
            raw = db_values.get(key)
            default = self.get_default(key)
            if raw is not None:
                source = "db"
            elif key in env_keys:
                source = "env"
            else:
                source = "default"
            if meta.secret:
                value: Any = SECRET_MASK
                display_default: Any = SECRET_MASK
            else:
                value = raw if raw is not None else default
                display_default = default
            item = SettingItemOut(
                key=key,
                label=meta.label,
                description=meta.description,
                type=meta.type,
                value=value,
                default=display_default,
                source=source,
                secret=meta.secret,
                restart_required=meta.restart_required,
                requires_reindex=meta.requires_reindex,
                options=meta.options,
                min=meta.min,
                max=meta.max,
            )
            grouped.setdefault(meta.group, []).append(item)

        groups = [
            SettingGroupOut(group=name, items=grouped[name])
            for name in GROUP_ORDER
            if name in grouped
        ]
        for name, items in grouped.items():
            if name not in GROUP_ORDER:
                groups.append(SettingGroupOut(group=name, items=items))
        return groups

    def update(self, updates: dict[str, Any], updated_by: int | None = None) -> list[SystemSetting]:
        coerced: dict[str, str] = {}
        for key, raw in updates.items():
            meta = KNOWN_SETTINGS.get(key)
            if meta and meta.secret and (raw is None or str(raw).strip() in ("", SECRET_MASK)):
                # secret 项提交空值/掩码值视为不修改，防止脱敏值写回覆盖真实密钥
                continue
            coerced[key] = self.validate_and_coerce(key, raw)
        results = self.store.set_many(coerced, updated_by=updated_by)
        self.invalidate_cache()
        return results

    def reset_to_default(self, key: str) -> None:
        """删除 DB 覆盖，让该配置回退到 .env/代码默认值。"""
        if key not in KNOWN_SETTINGS:
            raise ValueError(f"未知配置项: {key}")
        self.store.delete(key)
        self.invalidate_cache()


def get_settings_service() -> SettingsService:
    return SettingsService()
