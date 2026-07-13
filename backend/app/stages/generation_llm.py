from collections.abc import AsyncIterator

from pydantic import BaseModel

from app.clients.model_client import ModelClient
from app.config import get_settings
from app.models.graph_schemas import SubgraphContext
from app.stages.base import AbstractStage, RetrievalResult


class GenerationInput(BaseModel):
    question: str
    chunks: list[RetrievalResult]
    history: list[dict] = []
    graph_context: SubgraphContext | None = None


class GenerationOutput(BaseModel):
    raw_answer: str


class GenerationLLMStage(AbstractStage[GenerationInput, GenerationOutput]):
    """基于证据调用 LLM 生成带引用标注的答案。"""

    def __init__(self, model_client: ModelClient):
        self.model_client = model_client
        self.settings = get_settings()

    @property
    def name(self) -> str:
        return "generation_llm"

    async def execute(self, input_data: GenerationInput) -> GenerationOutput:
        messages = self._build_messages(input_data)
        answer = await self.model_client.chat(messages, stream=False)
        return GenerationOutput(raw_answer=answer)

    async def execute_stream(self, input_data: GenerationInput) -> AsyncIterator[str]:
        """流式生成：按上游模型返回的自然节奏逐段返回。"""
        messages = self._build_messages(input_data)
        stream = await self.model_client.chat(messages, stream=True)
        async for chunk in stream:
            yield chunk

    def _build_messages(self, input_data: GenerationInput) -> list[dict]:
        evidence_text = "\n\n".join(
            f"[{chunk.chunk_id}] {chunk.title}\n{chunk.content}"
            for chunk in input_data.chunks
        )

        system_prompt = (
            "你是一个严谨的内部支持助手。你只能基于下面给出的证据回答问题，每个关键论断后必须标注引用 [^chunk_id]。"
            "如果证据不足以回答问题，请直接回复：根据当前知识库，我找不到足够信息回答这个问题。"
            "不要编造证据中没有的信息。保持简洁、分点说明。"
        )

        graph_block = ""
        if input_data.graph_context and input_data.graph_context.text:
            graph_block = f"\n\n图谱上下文（辅助理解实体关系）：\n\n{input_data.graph_context.text}"

        user_prompt = f"证据：\n\n{evidence_text}{graph_block}\n\n用户问题：{input_data.question}\n\n请用中文回答。"

        messages = [
            {"role": "system", "content": system_prompt},
        ]
        # 加入最近历史（简化为 QA 对）
        for turn in input_data.history[-self.settings.max_history_rounds :]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_prompt})
        return messages
