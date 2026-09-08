"""`BrainTool` → `Brain` 这一跳的决策请求协议：`FromBrainToolToBrainChooseOnceReq`。"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.schemas.datastore import StepMemory
from pokemon_agent.schemas.domain import ActionSpaceForBrain, GoalForBrain, ObservationFromWorld


class FromBrainToolToBrainChooseOnceReq(BaseModel):
    """**递给大脑的决策请求**：目标栈、当前观测、可用动作、三类不同可信度的检索结果，
    加上这次问模型用的 prompt。**模块间调用只认一个输入参数**——这一份 req 同时是
    `pokemon_agent.prompts.decide_action.build_prompt()` 的输入（读 `prompt` 之外的
    字段拼出 prompt）和 `Brain.choose_once()` 的输入（只读 `prompt`），两边共享同一个
    对象，不用两套参数各传一遍。

    goals：整个目标栈，栈顶（最后一个）是这一轮要完成的。
    obs：当前观测（`facts` 只装这一帧从模拟器内存读出来的东西——
        `walk_map`/`neighbors`/`known_objects` 这类，不掺检索结果）。
    space：当前可用动作空间。
    memories：Harness 检索好的**本局内**情景记忆（`StepMemory`，"当时看到→做了什么→
        之后变成"，来自这一局自己走过的步骤）。
    knowledge：检索到的**领域知识**（`semantic/knowledge/*.md`，按 scene/goal 检索出的
        片段）——运营维护、长期为真，但检索覆盖不到当前场景是常态，不是错误。
    episode_memories：**跨局摘要**——之前几次尝试蒸馏出的经验，可能带着那一局自己的
        偏差，可信度低于 `memories`，仅供参考。
    prompt：这次问模型用的完整 prompt。**构造时留空**——先拿其余字段调
        `build_prompt(req)` 拼出字符串，再 `req.model_copy(update={"prompt": ...})`
        回填，才交给 `Brain.choose_once(req)`；重试时同一个 req 只換这个字段
        （`retry_prompt()` 在原 `prompt` 后追加纠正说明），其余字段不变。

    三者故意分开传：可信度不一样，prompt 里
    要分开介绍、分开提醒"这条能信到什么程度"，混在一起模型没法区分对待。
    """

    goals: list[GoalForBrain]
    obs: ObservationFromWorld
    space: ActionSpaceForBrain
    memories: list[StepMemory]
    knowledge: str = ""
    episode_memories: str = ""
    human_note: str = ""
    """人类实时插话（来自 `RunDataCenter` 的 human_note 槽），一次性、
    只对这一次决策生效。空串 = 这一步没人插话，按正常规则走；非空时
    `decide_action.md` 会把它当成压过其余所有规则的最高优先级指令渲染出来
    （见 `pokemon_agent.prompts.decide_action.build_prompt` 的说明）。"""
    prompt: str = ""
