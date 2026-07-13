import re

from pydantic import BaseModel

from app.stages.base import AbstractStage


class QueryRewriteInput(BaseModel):
    current_question: str
    history: list[dict]


class QueryRewriteOutput(BaseModel):
    rewritten_query: str


class QueryRewriteStage(AbstractStage[QueryRewriteInput, QueryRewriteOutput]):
    """多轮查询改写：拼接最近 1-2 轮历史并做简单指代补全。"""

    @property
    def name(self) -> str:
        return "query_rewrite"

    def execute(self, input_data: QueryRewriteInput) -> QueryRewriteOutput:
        current = input_data.current_question.strip()

        if not input_data.history:
            return QueryRewriteOutput(rewritten_query=current)

        # 取最近一轮 assistant + user（如果有）
        recent_turns = input_data.history[-2:]
        context_parts = []
        for turn in recent_turns:
            prefix = "问题" if turn["role"] == "user" else "回答"
            context_parts.append(f"{prefix}：{turn['content']}")

        # 简单指代补全
        rewritten = self._resolve_pronoun(current, input_data.history)
        if rewritten != current:
            return QueryRewriteOutput(rewritten_query=rewritten)

        # 否则拼接上下文
        combined = "\n".join(context_parts) + f"\n当前问题：{current}"
        return QueryRewriteOutput(rewritten_query=combined)

    def _resolve_pronoun(self, current: str, history: list[dict]) -> str:
        pronouns = re.compile(r"^(那|这个|它|他|她|此).*")
        if not pronouns.match(current):
            return current

        # 提取最近一个用户问题的主题（简单取前 10 个字符）
        for turn in reversed(history):
            if turn["role"] == "user":
                topic = turn["content"].strip()
                # 去掉末尾问号，补全当前问题
                return f"{topic}，{current}"
        return current
