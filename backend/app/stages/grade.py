"""相关性评分 Stage：对检索结果与问题的相关性进行快速评分。"""

from pydantic import BaseModel, Field

from app.clients.model_client import ModelClient
from app.stages.base import AbstractStage, RetrievalResult


class GradeInput(BaseModel):
    question: str
    chunk: RetrievalResult


class GradeOutput(BaseModel):
    is_relevant: bool = True
    score: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""


class GradeStage(AbstractStage[GradeInput, GradeOutput]):
    """对单个 chunk 与问题的相关性进行打分。

    当前实现为最小可用版本：直接返回相关，避免阻塞主流程。
    后续可接入轻量级 LLM 判断或 cross-encoder 评分。
    """

    def __init__(self, model_client: ModelClient):
        self.model_client = model_client

    @property
    def name(self) -> str:
        return "grade"

    def execute(self, input_data: GradeInput) -> GradeOutput:
        return GradeOutput(is_relevant=True, score=input_data.chunk.score, reason="默认通过")
