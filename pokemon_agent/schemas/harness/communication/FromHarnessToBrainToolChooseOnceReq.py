"""`FromHarnessToBrainToolChooseOnceReq`：harness → `BrainTool` 的决策请求。

**只装素材**（观测、动作空间、记忆）——harness 依赖 world/memory 是允许的，
而这些正是拼 prompt 需要的素材。`BrainTool` 自己调 `build_prompt(req)` 拼 prompt、
渲染裸字段，再交给 brain。harness 不碰 prompt（0913 定案）。
"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.brain.interface import Goal
from pokemon_agent.schemas.memory import StepMemory
from pokemon_agent.world import ActionSpace, Observation


class FromHarnessToBrainToolChooseOnceReq(BaseModel):
    """harness 侧组装（`harness/episode/decide/think_action.py`，纯参数拼接）、
    交给 `BrainTool` 的决策请求。

    goals：整个目标栈，栈顶（最后一个）是这一轮要完成的。
    obs：当前观测（`facts` 只装这一帧从模拟器内存读出来的东西）。
    space：当前可用动作空间——`BrainTool` 从它提取 `keys` 传给大脑，
        说明文字则渲进 prompt。
    memories：本局内情景记忆（`StepMemory`）。
    knowledge/episode_memories/human_note：分开放，各自在 prompt 里有独立
        占位符与可信度说明（混在一起模型没法区分对待）。

    **`prompt` 不是本模型的字段**（0913 删）：`BrainTool.choose()` 入口处调
    `prompts.decide_action.build_prompt(req)` 拼它，只活在那一次调用的局部
    ——"先拼 prompt 再回填进同一个 req"那个中间态不再外露。
    """

    goals: list[Goal]
    obs: Observation
    space: ActionSpace
    memories: list[StepMemory]
    knowledge: str = ""
    episode_memories: str = ""
    human_note: str = ""
