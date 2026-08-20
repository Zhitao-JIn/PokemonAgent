"""成败判定 —— **独立的一次模型调用，不是决策模型顺带说一句**。

## 为什么单独一个类、单独一个 prompt

成功率是这个项目唯一要报的硬数字。让做决策的那个模型顺便判断"我成功了吗"，
就是**误差同源**：它读错画面 → 以为达成了 → 判成功，而且错得越离谱数字越好看。

拆开之后至少做到三件事：

- **各自记账。** 判定的 token 和延迟走 `Source.JUDGE`，和决策分得开。
  判定花了多少钱、失败多少次，都是可统计的。
- **各自换型。** 判定可以用更强或更便宜的模型，和决策无关。
- **各自标定。** 将来拿人工标注的真值来对，能算出**判定器本身的准确率**——
  没有这一步，成功率就只是一个无法证伪的数字。

**这仍然不是真正独立的真值。** 判定看到的画面来自同一条感知链路，
感知错了两边一起错。真正的独立真值要么读游戏的事件旗标，要么人工标注。
这一版先把结构立起来，标定留到评测阶段。

## fail closed

任何异常情况——解析失败、模型不回话、网络抖——一律判**没完成**。

理由不对称：判成"完成"会立刻终止这一局，后面所有步骤都不会发生，
而且这个结论直接进实验数据；判成"没完成"只是多跑几步，下一步还有机会纠正。
所以所有不确定都往"没完成"倒。
"""

from __future__ import annotations

import json
import time

from pokemon_agent.interfaces.llm import LLMProvider
from pokemon_agent.prompts import load as load_prompt
from pokemon_agent.schemas.core import Observation, Task


class Verdict:
    """一次判定的结果，连同它花了什么。

    不用 Pydantic：它不跨层（只有 harness 自己读），做成模型反而多一份要维护的契约。
    """

    def __init__(
        self, done: bool, why: str, call: dict[str, str]
    ) -> None:
        self.done = done
        self.why = why
        self.call = call
        """这次调用的账：token、延迟、原始输出。由 harness 写进 trace。"""


class LLMSuccessJudge:
    """问一个模型：这个任务完成了没有。

    有意做得很薄——它不看历史、不看记忆、不看动作，只看**当前这一帧的观测**和任务目标。

    为什么不给它历史：给了它就会开始推理"他走了这么多步应该快到了"，
    而那正是我们要防的。判定只该基于**眼前的证据**。
    """

    def __init__(self, llm: LLMProvider, *, prompt_name: str = "judge_success") -> None:
        self._llm = llm
        self._prompt = load_prompt(prompt_name)

    @property
    def prompt_sha(self) -> str:
        """哪一版判定 prompt。改了 prompt 不记版本，前后两批成功率就没法比。"""
        return self._prompt.sha

    def judge(self, task: Task, obs: Observation) -> Verdict:
        """判定一次。**永远返回 Verdict，不抛异常。**

        判定器自己出错不该让一整局崩掉——那会把一次可以标记为"判定失败"的事件，
        变成一局丢失的数据。
        """
        rendered = "\n".join(f"- {k}: {v}" for k, v in obs.facts.items()) or obs.summary
        prompt = self._prompt.render(
            goal=task.goal, criteria=task.success_criteria, observation=rendered
        )

        t0 = time.perf_counter()
        try:
            completion = self._llm.complete(prompt)
        except Exception as exc:  # noqa: BLE001  判定器不该让整局崩掉
            return Verdict(False, f"判定调用失败：{type(exc).__name__}", {
                "prompt_sha": self._prompt.sha, "ok": "False",
                "latency_ms": str(int((time.perf_counter() - t0) * 1000)),
                "error": f"{type(exc).__name__}: {exc}"[:200],
            })

        latency = int((time.perf_counter() - t0) * 1000)
        call = {
            "prompt_sha": self._prompt.sha,
            "input_tokens": str(completion.prompt_tokens),
            "output_tokens": str(completion.completion_tokens),
            "latency_ms": str(latency),
            "raw": completion.text,
        }

        done, why, ok = self._parse(completion.text)
        call["ok"] = str(ok)
        return Verdict(done, why, call)

    @staticmethod
    def _parse(text: str) -> tuple[bool, str, bool]:
        """解析成 `(done, why, 解析成功没有)`。

        解析不出来时 `done` 一律为 False —— 见模块 docstring 的 fail closed。
        第三个返回值让调用方能把"判了没完成"和"根本没判出来"分开统计：
        前者是结论，后者是故障，混在一起会让判定器的失效变得不可见。
        """
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("```")[1].removeprefix("json").strip()
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            return False, f"判定输出不是合法 JSON：{text[:80]!r}", False

        if not isinstance(raw, dict) or not isinstance(raw.get("done"), bool):
            return False, f"判定输出缺少布尔 done：{text[:80]!r}", False

        why = raw.get("why")
        return bool(raw["done"]), str(why) if why else "（未说明）", True
