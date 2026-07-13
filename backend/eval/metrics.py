import asyncio
import json
import re
from typing import Any

from app.clients.model_client import ModelClient


class LLMJudgeMetrics:
    """基于 LLM-as-judge 的 RAGAS-like 指标（不依赖 RAGAS 库，便于自定义和调试）。"""

    def __init__(self, model_client: ModelClient):
        self.model_client = model_client

    async def _ask(self, prompt: str, temperature: float = 0.0) -> str:
        return await self.model_client.chat(
            [
                {
                    "role": "system",
                    "content": "你是一个严谨的评测助手，只按指定格式输出 JSON，不要任何解释。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
        )

    def _extract_json(self, text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        return {}

    async def context_relevance(self, question: str, contexts: list[str]) -> float:
        if not contexts:
            return 0.0
        prompt = (
            f"问题：{question}\n\n"
            f"证据片段：\n" + "\n---\n".join(f"[{i}] {c}" for i, c in enumerate(contexts)) + "\n\n"
            "请判断每个证据片段与问题的相关性，输出 JSON："
            '{"scores": [0.0~1.0, ...]}，数组顺序与片段顺序一致。'
        )
        result = self._extract_json(await self._ask(prompt))
        scores = result.get("scores", [])
        if not scores or len(scores) != len(contexts):
            return 0.0
        return sum(float(s) for s in scores) / len(scores)

    async def context_precision(self, question: str, contexts: list[str], expected_ids: list[str]) -> float:
        if not contexts:
            return 0.0
        tasks = []
        for ctx in contexts:
            prompt = (
                f"问题：{question}\n\n"
                f"证据片段：{ctx}\n\n"
                "该片段是否包含能回答问题的信息？只输出 true 或 false。"
            )
            tasks.append(self._ask(prompt))
        answers = await asyncio.gather(*tasks)
        relevant_count = sum(1 for ans in answers if ans.strip().lower().startswith("true"))
        return relevant_count / len(contexts)

    def context_recall(self, question: str, contexts: list[str], expected_ids: list[str]) -> float:
        if not expected_ids:
            return 1.0
        return len(set(expected_ids)) / len(expected_ids)

    async def faithfulness(self, answer: str, contexts: list[str]) -> float:
        if not answer.strip():
            return 0.0
        prompt = (
            "证据：\n" + "\n---\n".join(contexts) + "\n\n"
            f"答案：{answer}\n\n"
            "请将答案拆分为若干条独立论断，并判断每条论断是否都能从证据中直接推导出来。"
            '输出 JSON：{"supported": N, "total": M}'
        )
        result = self._extract_json(await self._ask(prompt))
        supported = result.get("supported", 0)
        total = result.get("total", 1)
        if total == 0:
            return 0.0
        return supported / total

    async def answer_relevance(self, question: str, answer: str) -> float:
        if not answer.strip():
            return 0.0
        prompt = (
            f"问题：{question}\n\n"
            f"答案：{answer}\n\n"
            "请判断答案对问题的相关程度，输出 0.0~1.0 之间的小数，只输出数字。"
        )
        text = (await self._ask(prompt)).strip()
        try:
            return float(re.search(r"[\d.]+", text).group(0))  # type: ignore
        except Exception:
            return 0.0


def hit_rate(retrieved_ids: list[str], expected_ids: list[str]) -> float:
    if not expected_ids:
        return 1.0 if not retrieved_ids else 0.0
    hits = len(set(retrieved_ids) & set(expected_ids))
    return hits / len(expected_ids)


def citation_accuracy(answer: str, citations: list[dict[str, Any]], expected_ids: list[str]) -> float:
    if not expected_ids:
        return 1.0
    cited_ids = {c["chunk_id"] for c in citations}
    if not cited_ids:
        return 0.0
    hits = len(cited_ids & set(expected_ids))
    return hits / len(expected_ids)


def refusal_accuracy(should_refuse: bool, is_refusal: bool) -> bool:
    return should_refuse == is_refusal


def stale_accuracy(should_stale: bool, is_stale: bool) -> bool:
    return should_stale == is_stale
