
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.config import get_settings
from app.stages.base import AbstractStage, RetrievalResult


class LCGenerationInput(BaseModel):
    question: str
    chunks: list[RetrievalResult]
    history: list[dict] = []


class LCGenerationOutput(BaseModel):
    raw_answer: str


class LCGenerationStage(AbstractStage[LCGenerationInput, LCGenerationOutput]):
    """LangChain 生成适配器：使用 LangChain ChatOpenAI 生成带引用答案。"""

    def __init__(self):
        settings = get_settings()
        self.settings = settings
        self.llm = ChatOpenAI(
            model=settings.llm_model,
            base_url=str(settings.model_base_url),
            api_key=settings.dashscope_api_key.get_secret_value(),
            temperature=0.3,
            timeout=settings.request_timeout,
        )

    @property
    def name(self) -> str:
        return "lc_generation"

    def execute(self, input_data: LCGenerationInput) -> LCGenerationOutput:
        evidence_text = "\n\n".join(
            f"[{chunk.chunk_id}] {chunk.title}\n{chunk.content}"
            for chunk in input_data.chunks
        )

        system_prompt = (
            "你是一个严谨的内部支持助手。你只能基于下面给出的证据回答问题，每个关键论断后必须标注引用 [^chunk_id]。"
            "如果证据不足以回答问题，请直接回复：根据当前知识库，我找不到足够信息回答这个问题。"
            "不要编造证据中没有的信息。保持简洁、分点说明。"
        )

        user_prompt = f"证据：\n\n{evidence_text}\n\n用户问题：{input_data.question}\n\n请用中文回答。"

        messages = [("system", system_prompt)]
        for turn in input_data.history[-self.settings.max_history_rounds :]:
            messages.append((turn["role"], turn["content"]))
        messages.append(("user", user_prompt))

        response = self.llm.invoke(messages)
        return LCGenerationOutput(raw_answer=response.content)
