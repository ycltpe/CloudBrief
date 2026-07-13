from typing import Any

import structlog
from pydantic import BaseModel, Field

from app.config import get_settings
from app.models.schemas import SettingGroupOut, SettingItemOut
from app.stores.db import SystemSetting
from app.stores.settings import SettingsStore

logger = structlog.get_logger()


class SettingMeta(BaseModel):
    key: str
    label: str
    description: str
    type: str = Field(..., pattern=r"^(float|int|str|bool|choice)$")
    default: Any
    options: list[str] | None = None
    min: int | float | None = None
    max: int | float | None = None


KNOWN_SETTINGS: dict[str, SettingMeta] = {
    "refusal_threshold": SettingMeta(
        key="refusal_threshold",
        label="拒答阈值",
        description="答案置信度低于该值时触发拒答（0-1）",
        type="float",
        default=0.3,
        min=0.0,
        max=1.0,
    ),
    "stale_threshold_days": SettingMeta(
        key="stale_threshold_days",
        label="知识时效阈值（天）",
        description="超过该天数未更新的文档会被标记为可能过期",
        type="int",
        default=90,
        min=1,
    ),
    "max_history_rounds": SettingMeta(
        key="max_history_rounds",
        label="最大历史轮数",
        description="对话上下文保留的最大轮数",
        type="int",
        default=10,
        min=0,
    ),
    "request_timeout": SettingMeta(
        key="request_timeout",
        label="模型请求超时（秒）",
        description="调用外部模型/向量库的最大等待时间",
        type="int",
        default=30,
        min=1,
    ),
    "retrieval_adapter": SettingMeta(
        key="retrieval_adapter",
        label="检索适配器",
        description="检索阶段使用的实现适配器",
        type="choice",
        default="native",
        options=["native", "langchain"],
    ),
    "parser": SettingMeta(
        key="parser",
        label="文档解析器",
        description="文档解析阶段使用的实现适配器",
        type="choice",
        default="native",
        options=["native", "llamaindex"],
    ),
    "llm_model": SettingMeta(
        key="llm_model",
        label="生成模型",
        description="答案生成使用的模型名称",
        type="str",
        default="qwen3.7-plus",
    ),
    "embedding_model": SettingMeta(
        key="embedding_model",
        label="Embedding 模型",
        description="文本向量化使用的模型名称",
        type="str",
        default="text-embedding-v3",
    ),
    "embedding_dim": SettingMeta(
        key="embedding_dim",
        label="Embedding 维度",
        description="文本向量化输出维度，必须与所选模型一致",
        type="int",
        default=1536,
        min=1,
    ),
    "reranker_model": SettingMeta(
        key="reranker_model",
        label="重排模型",
        description="重排阶段使用的模型名称（DashScope 时生效）",
        type="str",
        default="qwen3-rerank",
    ),
    "reranker_provider": SettingMeta(
        key="reranker_provider",
        label="重排模型 Provider",
        description="选择远程 DashScope 或本地 vLLM 部署的重排模型",
        type="choice",
        default="dashscope",
        options=["dashscope", "local"],
    ),
    "local_reranker_url": SettingMeta(
        key="local_reranker_url",
        label="本地重排服务地址",
        description="本地 vLLM/TEI reranker 的 OpenAI-compatible 端点，如 http://127.0.0.1:8000/v1",
        type="str",
        default="http://127.0.0.1:8000/v1",
    ),
    "local_reranker_model": SettingMeta(
        key="local_reranker_model",
        label="本地重排模型名称",
        description="本地服务上部署的模型名称，如 BAAI/bge-reranker-large",
        type="str",
        default="BAAI/bge-reranker-large",
    ),
    "auto_index_on_upload": SettingMeta(
        key="auto_index_on_upload",
        label="上传后自动构建索引",
        description="文件上传成功后是否自动触发单文件索引",
        type="bool",
        default=True,
    ),
    "graphrag_slow_query_threshold_ms": SettingMeta(
        key="graphrag_slow_query_threshold_ms",
        label="GraphRAG 慢查询阈值（ms）",
        description="Neo4j 查询耗时超过该值时输出 WARN 日志",
        type="int",
        default=500,
        min=1,
    ),
    "graphrag_freshness_threshold_days": SettingMeta(
        key="graphrag_freshness_threshold_days",
        label="GraphRAG 图谱新鲜度阈值（天）",
        description="超过该天数未更新图索引时输出 WARN 日志",
        type="int",
        default=7,
        min=1,
    ),
    "graphrag_min_extraction_entities": SettingMeta(
        key="graphrag_min_extraction_entities",
        label="GraphRAG 最小实体数阈值",
        description="单次抽取实体数低于该值时输出 WARN 日志",
        type="int",
        default=1,
        min=0,
    ),
    "graphrag_timeout_seconds": SettingMeta(
        key="graphrag_timeout_seconds",
        label="GraphRAG 抽取超时（秒）",
        description="图抽取调用 LLM 时的最大等待时间，建议 60-300 秒",
        type="float",
        default=120.0,
        min=1.0,
        max=600.0,
    ),
}


class SettingsService:
    def __init__(self, store: SettingsStore | None = None):
        self.store = store or SettingsStore()

    def get_known_setting_keys(self) -> list[str]:
        return list(KNOWN_SETTINGS.keys())

    def get_default(self, key: str) -> Any:
        cfg = get_settings()
        mapping = {
            "refusal_threshold": cfg.refusal_threshold,
            "stale_threshold_days": cfg.stale_threshold_days,
            "max_history_rounds": cfg.max_history_rounds,
            "request_timeout": cfg.request_timeout,
            "retrieval_adapter": cfg.retrieval_adapter,
            "parser": cfg.parser,
            "llm_model": cfg.llm_model,
            "embedding_model": cfg.embedding_model,
            "embedding_dim": cfg.embedding_dim,
            "reranker_model": cfg.reranker_model,
            "reranker_provider": cfg.reranker_provider,
            "local_reranker_url": cfg.local_reranker_url,
            "local_reranker_model": cfg.local_reranker_model,
            "auto_index_on_upload": True,
            "graphrag_slow_query_threshold_ms": 500,
            "graphrag_freshness_threshold_days": 7,
            "graphrag_min_extraction_entities": 1,
            "graphrag_timeout_seconds": cfg.graphrag_timeout_seconds,
        }
        return mapping.get(key, KNOWN_SETTINGS[key].default)

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

        # str / bool stored as-is for now
        return raw.strip()

    def validate_and_coerce(self, key: str, raw_value: Any) -> str:
        meta = KNOWN_SETTINGS.get(key)
        if not meta:
            raise ValueError(f"未知配置项: {key}")
        return self._coerce_value(meta, str(raw_value))

    def get_runtime_value(self, key: str) -> Any:
        """供业务代码读取运行期配置：DB 优先，其次 .env 默认值。"""
        meta = KNOWN_SETTINGS.get(key)
        default = self.get_default(key)
        row = self.store.get(key)
        if not row:
            return default
        raw = row.value
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
        rows = self.store.get_all()
        db_values = {row.key: row.value for row in rows}

        thresholds = []
        adapters = []
        models = []
        switches = []
        graphrag = []
        for key, meta in KNOWN_SETTINGS.items():
            raw = db_values.get(key)
            default = self.get_default(key)
            value = raw if raw is not None else default
            item = SettingItemOut(
                key=key,
                label=meta.label,
                description=meta.description,
                type=meta.type,
                value=value,
                default=default,
                options=meta.options,
                min=meta.min,
                max=meta.max,
            )
            if key in ("refusal_threshold", "stale_threshold_days", "max_history_rounds", "request_timeout"):
                thresholds.append(item)
            elif key in ("retrieval_adapter", "parser"):
                adapters.append(item)
            elif key == "auto_index_on_upload":
                switches.append(item)
            elif key in (
                "llm_model",
                "embedding_model",
                "embedding_dim",
                "reranker_model",
                "reranker_provider",
                "local_reranker_url",
                "local_reranker_model",
            ):
                models.append(item)
            elif key.startswith("graphrag_"):
                graphrag.append(item)
            else:
                thresholds.append(item)

        groups = [
            SettingGroupOut(group="业务阈值", items=thresholds),
            SettingGroupOut(group="适配器", items=adapters),
        ]
        if switches:
            groups.append(SettingGroupOut(group="功能开关", items=switches))
        groups.append(SettingGroupOut(group="模型", items=models))
        if graphrag:
            groups.append(SettingGroupOut(group="GraphRAG 监控", items=graphrag))
        return groups

    def update(self, updates: dict[str, Any], updated_by: int | None = None) -> list[SystemSetting]:
        coerced: dict[str, str] = {}
        for key, raw in updates.items():
            coerced[key] = self.validate_and_coerce(key, raw)
        return self.store.set_many(coerced, updated_by=updated_by)


def get_settings_service() -> SettingsService:
    return SettingsService()
