"""`EpisodeHarness`（局内图）自己的图控制纯函数——跟哪一根依赖都不绑定。

**只放和图控制最相关、不属于任何一根依赖的部分**——一个节点该给出什么
终局结论、该怎么算停摆。跟 `game_utils.py`（对 `GameToolPort`）/
`brain_utils.py`（对 `BrainToolPort`）/`memory_query_utils.py`（对
`MemoryToolPort`）是同一层拆分：那三个文件各自只碰一根依赖会用到的重试
循环与记账，这里放的是不需要碰任何依赖、纯粹算状态的函数。

跨 episode/run 两层图的 `tag_attempt` 在 `tag_attempt.py`（消费者跨两层，
放任何一层都会让另一层反向依赖）。

run 级图对应的工具函数在 `run_utils.py`/`run_plan_utils.py`，两层图
**互不依赖**——episode 层不知道 run 层的存在。
"""

from __future__ import annotations

from pokemon_agent.brain import ActionFromBrain
from pokemon_agent.world import Observation


def derive_episode_reason(success: bool, step: int, max_steps: int, *, stalled: bool) -> str:
    """从终局状态推出 EPISODE_END 的 `reason`：成功 > 停摆 > 步数用尽 > 世界自己结束。

    `success`/`stalled` 都由调用方直接传值，不收 `obs` 进来拆字段——
    `stalled` 来自 `state.stall_count >= STALL_LIMIT`，`success` 是 `judge`
    的裁决（`EpisodeRunState.success`，跟观测本身脱钩），这个函数只吃裸值，
    不假装自己需要一份完整观测。
    """
    if success:
        return "success"
    if stalled:
        return "stalled"
    if step >= max_steps:
        return "max_steps_exceeded"
    return "world_ended"


def compute_stall(
    after: Observation, action: ActionFromBrain, prev_key: str, prev_count: int
) -> tuple[str, int]:
    """算这一步的停摆键（画面机械状态 + 动作描述）与更新后的连续计数。

    跟上一步全同 → 计数 +1，否则清零重计一次。
    """
    key = f"{after.stall_key()}|{action.describe()}"
    count = prev_count + 1 if prev_key == key else 1
    return key, count
