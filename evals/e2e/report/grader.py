"""装配侧的 model grader：把 brain 的 `DeepSeekProvider` 包成统一 `ModelGrader`（V3/D6）。

evals 对 provider 的依赖**只在这里**（装配面）；判分 JSON 解析失败重试一次，再失败抛
`ValueError`。默认关（D6）：CLI 不给 `--model-grade` 就不装配本类——机械判定第一真源。
"""

from __future__ import annotations

import json

from evals.scorers.model_graded import ModelGrade
from pokemon_agent.brain.providers import DeepSeekProvider
from pokemon_agent.brain.schemas.completion import LlmCompleteReq


class LLMGrader:
    """`ModelGrader` 的 provider 实现：一次调用 + 一次重试，JSON 解析归本类。

    前置条件：`DEEPSEEK_API_KEY` 在环境里（`.env` 或 shell）。
    失败：两次产出都不是合法判分 JSON → `ValueError`（调用方决定计 unjudgeable 还是中止）。
    """

    def __init__(self, model: str, *, timeout: int = 60) -> None:
        self._provider = DeepSeekProvider(
            model, temperature=0.0, json_mode=True, timeout=timeout, multimodal=False
        )

    def grade(self, prompt: str) -> ModelGrade:
        last_error = ""
        for _ in range(2):
            resp = self._provider.complete(LlmCompleteReq(prompt=prompt))
            try:
                payload = json.loads(resp.text)
                return ModelGrade(
                    score=int(payload["score"]), reason=str(payload.get("reason", ""))
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
        raise ValueError(f"model grader 两次解析失败：{last_error}")


__all__ = ["LLMGrader"]
