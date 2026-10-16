"""用假大脑 / 假世界 / 假记忆把**真的三张图**跑一遍，交回落盘账本——给 `test_node_io.py` 当样本。

图、harness、`TraceTool` 渲染与落盘都是真的；只有模型、PyBoy、记忆库是假的。
这样核对脚本面对的是**真实形状**的账，而不是手写的近似品：harness 改了发账顺序，
这里立刻跟着变。

三个判定按目标文字分层：task 的目标恒为 `SUBTASK`，run 的目标以"依次完成"开头，
其余是 episode 的目标。每层给一个"第 n 次被问时判不判完成"的函数。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from pokemon_agent.errors import AgentError
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolEvolveReq,
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolExecuteResp,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolGetActionSpaceResp,
    FromHarnessToGameToolLoadStateReq,
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToGameToolResetReq,
    FromHarnessToGameToolSaveStateReq,
    FromHarnessToGameToolSaveStateResp,
)
from pokemon_agent.world import ActionSpace, TaskObservation, TaskScene

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


class _Game:
    """每次感知给一张新帧；`fail_on_press` 指定第几次按键时抛 `AgentError`。"""

    def __init__(self, fail_on_press: int | None) -> None:
        self._frames = 0
        self._presses = 0
        self._fail_on_press = fail_on_press

    def perceive_task(self) -> FromHarnessToGameToolPerceiveTaskResp:
        time.sleep(_MOCK_DELAY_SECONDS)
        self._frames += 1
        observation = TaskObservation(step=0, status=f"s{self._frames}", scene=TaskScene.WALK)
        return FromHarnessToGameToolPerceiveTaskResp(
            observation=observation, frame_png=f"F{self._frames}"
        )

    def execute(self, req: FromHarnessToGameToolExecuteReq) -> FromHarnessToGameToolExecuteResp:
        time.sleep(_MOCK_DELAY_SECONDS)
        self._presses += 1
        if self._presses == self._fail_on_press:
            raise AgentError("假世界在这一键上坏了")
        return FromHarnessToGameToolExecuteResp()

    def reset(self, req: FromHarnessToGameToolResetReq) -> None:
        pass

    def evolve(self, req: FromHarnessToGameToolEvolveReq) -> None:
        """确定性假世界不自行演化；观测随 perceive 推进。"""

    def save_state(
        self, req: FromHarnessToGameToolSaveStateReq
    ) -> FromHarnessToGameToolSaveStateResp:
        """假世界的"完整状态"就是两个计数器；写成 json，读回后恢复点与存档点相同。"""
        path = Path(req.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps({"frames": self._frames, "presses": self._presses}).encode()
        path.write_bytes(data)
        return FromHarnessToGameToolSaveStateResp(path=str(path), size=len(data))

    def load_state(self, req: FromHarnessToGameToolLoadStateReq) -> None:
        state = json.loads(Path(req.path).read_bytes())
        self._frames, self._presses = state["frames"], state["presses"]

    def get_action_space(
        self, req: FromHarnessToGameToolGetActionSpaceReq
    ) -> FromHarnessToGameToolGetActionSpaceResp:
        return FromHarnessToGameToolGetActionSpaceResp(action_space=ActionSpace(names=["a", "up"]))
