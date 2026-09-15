"""`PlannerContext`：递给 `Planner` 的规划素材。

**为什么是 harness 的领域模型而不是参数列表**：`Planner` 是将来要换成模型实现的
接口，它的输入面注定会变（0914 就把"事件流"换成了"记忆索引 + 详情"）。
装成一个模型后，加字段不破所有实现的签名；参数列表则会。

**0914 S2：`events` 退役，换成记忆三段**。原先这个字段装的是
`deps.trace.read_events()` 的全量事件流——控制台实现拿它给人看历史。但
"存下来的东西只有 memory 里的东西"，trace 是过程账不是经历，而且大半是
prompt/raw 噪声。现在换成：

- `index`：本 run 每一局一行（`episode_memory` 的**来源章**）；
- `details`：其中几局的**正文**（一期按确定性规则预取，二期交给工具环）；
- `objects`：本 run 涉及的地图交互事实（`object_memory`）。

消费方各取所需：控制台实现打索引给人看（人写目标时要知道前面几局成没成），
模型实现把三段都渲进 prompt。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain import GoalEntry
from pokemon_agent.schemas.memory import EpisodeMemory, ObjectFactEvent


class PlannerContext(BaseModel):
    """`Planner.plan()` 的入参：目标表现状 + 本 run 的局索引（含少量详情）+ 地图事实。"""

    run_id: str = Field(description="这次 run 的标识")
    plan: list[GoalEntry] = Field(
        description="当前目标表（含已完成/已弃的条目——它们是层次上下文与教训）"
    )
    index: list[EpisodeMemory] = Field(
        default_factory=list,
        description="本 run 每一局的摘要记忆（**按执行顺序**）。每一份自带来源章，"
        "取章就是索引行；正文在 `details` 里给选中的那几份",
    )
    details: list[EpisodeMemory] = Field(
        default_factory=list,
        description="**这一版预取的正文**——`index` 的子集。二期上工具环后可以为空，"
        "模型自己请求要哪几局（信封不用改）",
    )
    objects: list[ObjectFactEvent] = Field(
        default_factory=list,
        description="本 run 涉及的地图交互事实（跨局共池，锚在 (map_id,x,y) 上）",
    )


__all__ = ["PlannerContext"]
