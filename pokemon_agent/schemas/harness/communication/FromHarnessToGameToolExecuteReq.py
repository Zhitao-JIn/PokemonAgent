"""`FromHarnessToGameToolExecuteReq`：harness → `GameTool` 的动作执行请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import Action
from pokemon_agent.world import Observation


class FromHarnessToGameToolExecuteReq(BaseModel):
    """**要执行的动作 + 它所依据的那一帧观测**。

    observation 一起带上是前置检查要用的：门面会断言这个动作确实来自
    这一帧算出的动作空间。

    **执行粒度是一个键。** 连按在执行层已经展开成一步一步（每一步各写一条记忆、
    各判一次中止），所以这里收到的 `sequence` 恒为单段——多段只可能来自
    `plan`，那是循环状态，不该走到执行层。
    """

    action: Action = Field(description="大脑选出的动作；执行层收到的恒为单键（单段、times=1）")
    observation: Observation = Field(description="这个动作所依据的观测")
    settle: bool = Field(
        default=True,
        description="按完之后要不要给世界一段无输入演化时间再交回控制权。"
        "链的最后一下（含单键动作）是 True；链中间的键是 **False**——"
        "后面还有键要按，等世界把过场走完不但慢，而且那几帧对中间键没用"
        "（中间键只读内存判位移、换图）。**它不改变执行结果**，只决定"
        "调用方什么时候拿到控制权",
    )
