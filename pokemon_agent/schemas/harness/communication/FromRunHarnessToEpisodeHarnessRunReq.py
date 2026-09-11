"""RunHarness → EpisodeHarness 的 run 交互：一局的派发请求。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import TaskForBrain


class FromRunHarnessToEpisodeHarnessRunReq(BaseModel):
    """主 agent 把目标栈顶派发给子 agent：解决栈顶这一个目标。

    `stack` 是完整栈（子 agent 要看栈顶之下的目标做上下文）；`run_state`
    是 RunState 的 model_dump（透传给图状态，恢复路径由此重建）。
    """

    episode_id: str = Field(description="这一局的标识")
    task: TaskForBrain = Field(description="栈顶目标（本局要解决的）")
    stack: list[TaskForBrain] = Field(description="完整目标栈，栈顶 == task")
    run_state: dict[str, Any] = Field(description="RunState.model_dump()，图状态重建用")
