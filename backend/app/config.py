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

    # 模型配置
    dashscope_api_key: SecretStr
    model_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    rerank_base_url: str = "https://dashscope.aliyuncs.com/compatible-api/v1"

    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1536
    reranker_model: str = "qwen3-rerank"
    reranker_provider: Literal["dashscope", "local"] = "dashscope"
    local_reranker_url: str = "http://127.0.0.1:8000/v1"
    local_reranker_model: str = "Qwen/Qwen3-Reranker-0.6B"
    llm_model: str = "qwen3.7-plus"
    llm_provider: Literal["dashscope", "local"] = "dashscope"
    local_llm_url: str = "http://127.0.0.1:8000/v1"
    local_llm_model: str = "Qwen/Qwen2.5-7B-Instruct"
    local_embedding_url: str = "http://127.0.0.1:8000/v1"
    local_embedding_model: str = "BAAI/bge-m3"

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

    # Embedding 批大小（DashScope text-embedding-v3 上限为 10）
    embedding_batch_size: int = 10

    # 大 PDF 页级分批：超过阈值页数时按批推送解析心跳
    pdf_batch_page_threshold: int = 50
    pdf_page_batch_size: int = 25

    # 扫描件 OCR：对无文字层 PDF 页调用视觉模型识别（DashScope qwen-vl-ocr）
    ocr_enabled: bool = True
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

    @property
    def mysql_database(self) -> str:
        """从 mysql_url 中解析出数据库名，用于 Milvus collection 命名等场景。"""
        return self.mysql_url.rsplit("/", 1)[-1].split("?", 1)[0]


@lru_cache
def get_settings() -> Settings:
    return Settings()
