from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """统一配置入口，所有环境变量均从 .env 加载，代码中禁止硬编码密钥/URL/模型名。"""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 大语言模型（LLM）：provider=dashscope 走云端（保留到本地的失败降级），
    # provider=local 走本地且不回退云端，避免私有化数据外发
    llm_provider: Literal["dashscope", "local"] = "dashscope"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen3.7-plus"
    local_llm_url: str = "http://127.0.0.1:8000/v1"
    local_llm_model: str = "Qwen/Qwen2.5-7B-Instruct"

    # 向量模型（Embedding）：切换 provider/模型/维度后必须重建索引
    embedding_provider: Literal["dashscope", "local"] = "dashscope"
    embedding_api_key: SecretStr | None = None
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1536
    local_embedding_url: str = "http://127.0.0.1:8000/v1"
    local_embedding_model: str = "BAAI/bge-m3"

    # Reranker 模型
    reranker_provider: Literal["dashscope", "local"] = "dashscope"
    reranker_api_key: SecretStr | None = None
    rerank_base_url: str = "https://dashscope.aliyuncs.com/compatible-api/v1"
    reranker_model: str = "qwen3-rerank"
    local_reranker_url: str = "http://127.0.0.1:8000/v1"
    local_reranker_model: str = "Qwen/Qwen3-Reranker-0.6B"

    # 存储配置
    milvus_uri: str = "http://localhost:19531"
    milvus_collection: str = "cloudbrief_chunks"

    redis_url: str = "redis://localhost:6381/0"

    mysql_url: str = "mysql+pymysql://cloudbrief:cloudbrief@localhost:3307/cloudbrief"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "cloudbrief"

    bm25_index_path: Path = Path("./data/bm25_index.pkl")

    # 知识库文件存储
    kb_storage_path: Path = _PROJECT_ROOT / "data" / "kb"
    kb_max_file_size: int = 50 * 1024 * 1024

    # 应用配置
    log_level: str = "INFO"
    backend_port: int = 8001

    # 业务阈值
    refusal_threshold: float = 0.3
    stale_threshold_days: int = 90
    max_history_rounds: int = 10
    request_timeout: int = 30
    graphrag_timeout_seconds: float = 120.0

    # GraphRAG 监控阈值（超过/低于时输出 WARN 日志）
    graphrag_slow_query_threshold_ms: int = 500
    graphrag_freshness_threshold_days: int = 7
    graphrag_min_extraction_entities: int = 1

    # 功能开关
    auto_index_on_upload: bool = True
    self_querying_enabled: bool = False

    # Embedding 批大小（DashScope text-embedding-v3 上限为 10）
    embedding_batch_size: int = 10

    # 大 PDF 页级分批：超过阈值页数时按批推送解析心跳
    pdf_batch_page_threshold: int = 50
    pdf_page_batch_size: int = 25
    # 单份 PDF 页数上限：防止超大页数文件长时间占满索引 worker
    pdf_max_pages: int = 2000

    # 扫描件 OCR：对无文字层 PDF 页调用视觉模型识别（DashScope qwen-vl-ocr）
    ocr_enabled: bool = True
    ocr_api_key: SecretStr | None = None
    ocr_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ocr_model: str = "qwen-vl-ocr-latest"
    ocr_timeout_seconds: float = 120.0
    pdf_ocr_dpi: int = 200

    # JWT 认证配置
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440

    # 适配器开关
    retrieval_adapter: Literal["native", "langchain"] = "native"
    parser: Literal["native", "llamaindex"] = "native"

    # 编排模式
    orchestration_mode: Literal["native", "langchain", "agentic"] = "native"

    # Agentic 编排中断点（触发式）：启用后多跳分解前可暂停等待人工确认
    agentic_interrupt_enabled: bool = False

    # LangGraph 编排状态持久化
    checkpoint_backend: Literal["sqlite", "redis"] = "sqlite"
    checkpoint_sqlite_path: Path = Path("./data/checkpoints.sqlite")
    checkpoint_redis_prefix: str = "cloudbrief:checkpoint"
    checkpoint_redis_ttl: int = 0  # 分钟，0 表示不过期

    @property
    def mysql_database(self) -> str:
        """从 mysql_url 中解析出数据库名，用于 Milvus collection 命名等场景。"""
        return self.mysql_url.rsplit("/", 1)[-1].split("?", 1)[0]


@lru_cache
def get_settings() -> Settings:
    return Settings()
