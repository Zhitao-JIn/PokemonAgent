"""用假大脑 / 假世界 / 假记忆把**真的三张图**跑一遍，交回落盘账本——给 `test_node_io.py` 当样本。

图、harness、`TraceTool` 渲染与落盘都是真的；只有模型、PyBoy、记忆库是假的。
这样核对脚本面对的是**真实形状**的账，而不是手写的近似品：harness 改了发账顺序，
这里立刻跟着变。

三个判定按目标文字分层：task 的目标恒为 `SUBTASK`，run 的目标以"依次完成"开头，
其余是 episode 的目标。每层给一个"第 n 次被问时判不判完成"的函数。
"""

from __future__ import annotations

import collections
import time
from collections.abc import Callable, Sequence

from pydantic import BaseModel

from pokemon_agent.brain import Action, ActionSegment, RunPlan
from pokemon_agent.brain.interface import (
    ChooseResult,
    DecomposeResult,
    Decomposition,
    EpisodeSummary,
    JudgeResult,
    ModelCall,
    PlanResult,
    Reflection,
    RunSummary,
    ScriptSignature,
    SummarizeResult,
    SummarizeRunResult,
    VerifyResult,
    VerifyVerdict,
)
from pokemon_agent.errors import AgentError

SUBTASK = "子任务"
"""假拆解给出的每个 task 的目标文字（task 层判定据此认出自己）。"""

_MOCK_DELAY_SECONDS = 0.003
"""每个假件返回前垫的延迟（2026-09-27）。

目的有二：让 rehearsal/测试里的账本带上**非零的真实形状**——模型账的
payload 双时刻（真 `brain.py` 在 provider 前后取时，假件在这里同形盖戳，
练的是 `render._payload_time` 提取路径）与检索 req 的计时字段不再是 0；
也让 UI 时间线上相邻的账拉开一点间隔。
"""

Policy = Callable[[int], bool]
"""第 n 次（从 1 起）被问"完成了没有"时的回答。"""


def _call(prompt: str, result: BaseModel) -> list[ModelCall]:
    """一条成功的调用账（字段齐全，过得了账单契约）。

    `prompt` 是真收到的那句，`raw` 是结果本身的 JSON。双时刻同形盖戳：
    真 `brain.py` 在 provider 前后取时进 payload，假件睡一拍后照抄那个形状。
    """
    started = time.time()
    time.sleep(_MOCK_DELAY_SECONDS)
    return [
        ModelCall(
            payload={
                "ok": "true",
                "prompt": prompt,
                "raw": result.model_dump_json(exclude={"calls"}),
                "input_tokens": "1",
                "output_tokens": "1",
                "cached_tokens": "0",
                "reasoning_tokens": "0",
                "started_at": started,
                "ended_at": time.time(),
            }
        )
    ]


class _Brain:
    """按层分派判定的假大脑。"""

    def __init__(
        self,
        task: Policy,
        episode: Policy,
        run: Policy,
        tasks_per_plan: int,
        fail_on_decompose: int | None = None,
    ) -> None:
        self._policies = {"task": task, "episode": episode, "run": run}
        self._fail_on_decompose = fail_on_decompose
        self._decomposed = 0
        self._asked: collections.Counter[str] = collections.Counter()
        self._tasks_per_plan = tasks_per_plan

    def choose(
        self,
        *,
        prompt: str,
        keys: Sequence[str],
        images: Sequence[str] = (),
        scripts: Sequence[ScriptSignature] = (),
    ) -> ChooseResult:
        result = ChooseResult(action=Action(sequence=[ActionSegment(name=keys[0])]), calls=[])
        return result.model_copy(update={"calls": _call(prompt, result)})

    def reflect(self, *, prompt: str, before: str, after: str, action_text: str) -> Reflection:
        return Reflection(before=before, action_text=action_text, after=after)

    def judge(
        self, *, prompt: str, goal: str, history: Sequence[str], images: Sequence[str] = ()
    ) -> JudgeResult:
        layer = "task" if goal == SUBTASK else "run" if goal.startswith("依次完成") else "episode"
        self._asked[layer] += 1
        result = JudgeResult(done=self._policies[layer](self._asked[layer]), why="w", calls=[])
        return result.model_copy(update={"calls": _call(prompt, result)})

    def plan(
        self,
        *,
        prompt: str,
        goal_stack: Sequence[str],
        history: Sequence[str],
        max_push: int,
        images: Sequence[str] = (),
        thinking: bool | None = None,
    ) -> PlanResult:
        goal = RunPlan.PlanGoal(goal="新目标", success_criteria="c", max_steps=3)
        result = PlanResult(plan=RunPlan(push_goals=[goal]), calls=[])
        return result.model_copy(update={"calls": _call(prompt, result)})

    def decompose(
        self,
        *,
        prompt: str,
        goal: str,
        context: Sequence[str],
        max_tasks: int,
        images: Sequence[str] = (),
        thinking: bool | None = None,
    ) -> DecomposeResult:
        self._decomposed += 1
        if self._decomposed == self._fail_on_decompose:
            raise AgentError("假拆解在这一次上坏了")
        planned = Decomposition.PlannedTask(goal=SUBTASK, success_criteria="c", max_steps=2)
        result = DecomposeResult(
            decomposition=Decomposition(tasks=[planned] * self._tasks_per_plan), calls=[]
        )
        return result.model_copy(update={"calls": _call(prompt, result)})

    def verify(
        self,
        *,
        prompt: str,
        entries: Sequence[str],
        goal: str,
        knowledge: str,
        images: Sequence[str] = (),
    ) -> VerifyResult:
        verdicts = [
            VerifyVerdict(index=i, positive=i % 2 == 0, why="y") for i in range(len(entries))
        ]
        result = VerifyResult(verdicts=verdicts, calls=[])
        return result.model_copy(update={"calls": _call(prompt, result)})

    def summarize(
        self,
        *,
        prompt: str,
        goal: str,
        history: Sequence[str],
        success: bool,
        steps: int,
        max_steps: int,
        images: Sequence[str] = (),
    ) -> SummarizeResult:
        summary = EpisodeSummary(
            summary="s", reason="原因", quality_score=0.5, quality_rationale="q"
        )
        result = SummarizeResult(summary=summary, calls=[])
        return result.model_copy(update={"calls": _call(prompt, result)})

    def summarize_run(
        self,
        *,
        prompt: str,
        goal: str,
        history: Sequence[str],
        success: bool,
        steps: int,
        max_steps: int,
        images: Sequence[str] = (),
    ) -> SummarizeRunResult:
        """假 run 蒸馏与真实 BrainPort 同签名，返回可落库正文及一次调用账。"""
        summary = RunSummary(
            summary="run summary",
            reason="原因",
            quality_score=0.5,
            quality_rationale="q",
            markdown="run summary",
        )
        result = SummarizeRunResult(summary=summary)
        return result.model_copy(update={"calls": _call(prompt, result)})
