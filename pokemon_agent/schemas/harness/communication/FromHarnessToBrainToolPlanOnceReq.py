"""`FromHarnessToBrainToolPlanOnceReq`：harness → `BrainTool` 的 run 级规划请求。

**只装素材**——目标表、本 run 的局索引与预取详情、地图交互事实。`BrainTool`
自己拼 prompt（`prompts.run_plan.build_prompt()`，与 `plan()` 里渲染
`goal_table`/`history` 共用同一份渲染函数），再交给大脑。harness 不碰 prompt
（0913 定案）。

**0914 S2：素材从"全量事件流"换成"记忆"**。原先这里装的是
`deps.trace.read_events()` 的全量事件流，`build_prompt()` 再从里面折出"每局一行"
的历史。那条路有两个毛病：① 与"存下来的东西只有 memory"相矛盾——trace 是过程账，
不是被留下来的经历；② trace 里大半是 prompt/raw 这类噪声，而 memory 已经是对它
的蒸馏。现在装的是 `episode_memory`（本 run 全部局：章 + 详情）与
`object_memory`（地图交互事实）——**trace 与 plan 之间不再有数据通路**。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain import GoalEntry
from pokemon_agent.schemas.memory import EpisodeMemory, ObjectFactEvent


class FromHarnessToBrainToolPlanOnceReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的规划请求。

    run_id：这次 run 的标识（trace 记账用，大脑不需要）。
    plan：当前**目标表**，表序 = 先后顺序（第一条待做的最先被派发）。
        每一行带自己的 `status`/`attempts`/`note`/`parent_id`——模型据此看见
        "哪些做过了、成没成、为什么没成"。
    index：本 run 沉淀的 `episode_memory` 全量，**按执行顺序**（不是字典序——
        `episode_id` 是 `{run_id}-ep{n}`，字典序在 n≥10 时会乱）。一份
        `EpisodeMemory` = 来源章（`episode_id`/`goal`/`success`/`steps`）+
        派生正文；**索引行只取章**，正文是详情那一份的事。
    details：**这一版预取的正文**——`index` 的子集（一期规则见
        `run/nodes/plan.py::_pick_details`）。二期上工具环后这个字段可以为空，
        模型自己请求要哪几局的正文，**信封不用改**（这就是留的那条缝）。
    objects：本 run 涉及的地图交互事实（`object_memory`，锚在 `(map_id,x,y)` 上，
        跨局共池）。plan 是 run 级、没有当前观测也就没有"这一张图"，所以按
        **可选条件**取（`query_object_events(map_id=None)`）。
    max_push：这一次最多新增几个目标。**提示模型的建议上限，不是截断**——
        `plan` 节点不再替模型裁剪（裁掉就是静默丢目标）。
    """

    run_id: str
    plan: list[GoalEntry]
    index: list[EpisodeMemory] = Field(default_factory=list)
    details: list[EpisodeMemory] = Field(default_factory=list)
    objects: list[ObjectFactEvent] = Field(default_factory=list)
    max_push: int
