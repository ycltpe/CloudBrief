"""多跳分解 Stage：将复杂问题分解为多个子问题。"""

from pydantic import BaseModel

from app.clients.model_client import ModelClient
from app.stages.base import AbstractStage


class MultiHopDecomposeInput(BaseModel):
    question: str
    history: list[dict] = []


class MultiHopDecomposeOutput(BaseModel):
    sub_questions: list[str]


class MultiHopDecomposeStage(AbstractStage[MultiHopDecomposeInput, MultiHopDecomposeOutput]):
    """多跳问题分解：把复杂问题拆成多个可独立检索的子问题。

    当前实现为最小可用版本：直接返回原问题作为单个子问题。
    后续可接入 LLM 进行多跳推理分解。
    """

    def __init__(self, model_client: ModelClient):
        self.model_client = model_client

    @property
    def name(self) -> str:
        return "multi_hop_decompose"

    def execute(self, input_data: MultiHopDecomposeInput) -> MultiHopDecomposeOutput:
        return MultiHopDecomposeOutput(sub_questions=[input_data.question])
