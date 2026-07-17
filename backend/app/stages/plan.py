"""查询规划 Stage：将复杂问题拆分为可执行的查询计划。"""

from pydantic import BaseModel

from app.clients.model_client import ModelClient
from app.services.settings_service import SettingsService
from app.stages.base import AbstractStage


class PlanInput(BaseModel):
    question: str
    history: list[dict] = []


class PlanOutput(BaseModel):
    steps: list[str]


class PlanStage(AbstractStage[PlanInput, PlanOutput]):
    """根据问题生成执行计划。

    当前实现为最小可用版本：将原问题作为单一步骤返回。
    后续可接入 LLM 进行意图识别、工具选择或多步计划生成。
    """

    def __init__(self, model_client: ModelClient, graph_schema_store=None):
        self.model_client = model_client
        self.graph_schema_store = graph_schema_store
        self.settings_service = SettingsService()

    @property
    def name(self) -> str:
        return "plan"

    def execute(self, input_data: PlanInput) -> PlanOutput:
        return PlanOutput(steps=[input_data.question])
