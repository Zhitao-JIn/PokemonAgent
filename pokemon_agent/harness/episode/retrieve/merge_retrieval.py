"""`merge_retrieval`：把四路检索的结果**汇到一处**——只有 object 那一路会改状态。

**只有 `known_objects` 折进 `obs.facts`**：它虽然也是跨步骤攒出来的，但坐标锚定在
这张地图上，跟 `walk_map`/`landmarks` 同一个可信度级别。`knowledge`（知识库）与
`global_episode_memories`（跨局摘要）各走各的 `FromHarnessToBrainToolChooseOnceReq`
字段，在 `decide_action.md` 里各有独立占位符和可信度说明，**不混进"已知事实"**。
本局单步（`step_episode_memories`）本来就没折进观测，仍是独立列表。

**本格不写账**（0914 对齐审计）：它原来另记一条 `MEMORY_READ` 当"四路合并"的账，
但四路各自的 `read_*` 已经把 `count`/`refs` 记全了，那条合并账**每一项都与某条
`read_*` 逐字重复**——合并这件事本身没有产出任何新信息。四路读的账归四个
`retrieve_*` 节点，本格只负责"把它们折成同一帧观测"。

折进去的东西去哪了：`obs.facts.known_objects` 随这一帧进 `think_action` 的
prompt（`decide_action.md` 的「已知事实」一节），**原文就存在 `MODEL_CALL(decide)`
的 `prompt` 里**——所以本格的产品照样能在账上查到，只是不再另立一条账。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def merge_retrieval(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """把语义 object 折进这一帧观测。**只改 `observation` 一处，不查库、不记
    trace。**

    前置条件：四路 retrieve 都已跑过（`state` 里四个字段齐备）、`state.observation` 非空。
    后置条件：返回 `{"observation": …}`；`knowledge`/`episode_memories` 原样留在 state 里
    给 `decide/think_action` 自己取。
    """
    assert state.observation is not None, "merge_retrieval before judge"
    obs = state.observation

    # 折进语义记忆（object）——坐标锚定，跟 walk_map/landmarks 同一可信度级别。
    # 知识库/跨局摘要**不**折进 obs.facts：真正喂给 think_action 的路径是 state
    # 里那两个字段原样传下去，由 think_action 自己拼
    # FromHarnessToBrainToolChooseOnceReq。
    #
    # `known_objects` 走 `Facts` 的**动态字段**（`model_config` 是 `extra="allow"`，
    # `facts.py:69`），不是具名字段——`Facts.exclude()` 就是为剥掉它而写的。
    # 所以这里**不能用 `{**obs.facts, ...}`**：`Facts` 是 Pydantic 模型不是 mapping，
    # 那个写法是 `facts` 还是 `dict[str, str]` 的年代留下的，一旦 `object_semantic_memory`
    # 非空就会炸 `TypeError: 'Facts' object is not a mapping`（0915 143903 实测，
    # 那一局正是因为目标涉及 NPC，object 记忆第一次非空）。
    # `model_copy(update=…)` 对 `extra="allow"` 的模型会把不认识的键放进
    # `__pydantic_extra__`，与 `Facts.exclude()` 的读法同一处。
    if state.object_semantic_memory:
        obs = obs.model_copy(
            update={
                "facts": obs.facts.model_copy(
                    update={"known_objects": state.object_semantic_memory}
                )
            }
        )
    return {"observation": obs}
