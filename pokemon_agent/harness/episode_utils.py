"""`EpisodeHarness`（局内图）自己的图控制纯函数——跟哪一根依赖都不绑定。

**只放和图控制最相关、不属于任何一根依赖的部分**——一个节点该给出什么
终局结论、该怎么算停摆。跟 `game_utils.py`（对 `GameToolPort`）/
`brain_utils.py`（对 `BrainToolPort`）/`memory_query_utils.py`（对
`MemoryToolPort`）是同一层拆分：那三个文件各自只碰一根依赖会用到的重试
循环与记账，这里放的是不需要碰任何依赖、纯粹算状态的函数。

跨 episode/run 两层图的 `tag_attempt` **已经不在 harness 里**——它随 trace 渲染一起
搬进了 tool 层（`pokemon_agent/tools/trace_render.py` 的 `_tag_attempt`，由 `TraceTool`
在 `req.attempt` 非空时盖章）。所以"放哪一层都会让另一层反向依赖"这个划界问题
在本包内已经不存在了。

run 级图对应的工具函数在 `run_utils.py`/`run_plan_utils.py`，两层图
**互不依赖**——episode 层不知道 run 层的存在。
"""

from __future__ import annotations

from pokemon_agent.brain import ActionFromBrain
from pokemon_agent.schemas.memory import StopReason
from pokemon_agent.world import BUTTON_FACING, Observation


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


def compute_stop(
    before: Observation,
    action: ActionFromBrain,
    after: Observation,
    *,
    next_step: int,
    max_steps: int,
) -> StopReason | None:
    """**这一键之后为什么没有继续按键**——纯 RAM 判据，不调任何模型。

    调用方是 `perceive_after_action`：它拿着按键前后的两帧（链内的键只有 RAM 那一档），
    纯字段比较就能回答这个问题——这也是整条链**确定**的前提（同存档 + 同链 →
    同一状态序列），见 `docs/spec/harness/PLAN_action_step_granularity.md` §3/§5。

    判定顺序（世界没了最优先，其余局部归因优先，`episode_over` 兜底）：
    世界没了（`after.done`）时内存读数不再可信，此时报"本局结束"而不是据那份
    读数说"撞墙了"；剩下的能归因到**这一键**的就归因到它（撞墙 / 换图），
    归因不到才说"本局到点了"。这么排是因为 `stop` 的读者是下一步的大脑：
    它要的是"我这一下发生了什么"，而"本局结束"这件事不用 `stop` 说——
    最后一帧的 OBSERVE/JUDGE 已经在说它了。

    前置条件：`action` 是单键（`sequence` 一段）——执行层已经展开过。
    后置条件：返回 `None` 表示这一键没有异常（要么背后还有待按的键，要么它
        本来就是链尾）；返回非 None 时调用方按 §5 的作废范围截断队列。
    """
    assert len(action.sequence) == 1, "compute_stop() 只判单键动作（连按应在执行层展开）"

    # 世界没了：这份观测读出来的东西不再可信，先报本局结束，不据它归因。
    if after.done:
        return StopReason.EPISODE_OVER

    name = action.sequence[0].name
    facing = BUTTON_FACING.get(name)

    # 方向键：位置与朝向都没变、且朝向本来就等于这个方向 = 撞墙原地空转。
    # **"位置没变但朝向变了"是转身**，不是撞墙（朝向不等就不进这个分支）；
    # **`a` 根本不进这个分支**——`BUTTON_FACING` 里没有它，它不改变位置与朝向，
    # "按了没反应"（对话本来就没弹）是它的合法结局。
    if (
        facing
        and before.place is not None
        and after.place is not None
        and before.place == after.place
        and before.facts.facing == after.facts.facing == facing
    ):
        return StopReason.BLOCKED

    # 换图：后面几段是在一张**没被规划过的地图**上按的（判据只要 map_id）。
    if (
        before.place is not None
        and after.place is not None
        and before.place.map_id != after.place.map_id
    ):
        return StopReason.WARP

    # 本局到点了：这一键用掉了最后一步预算（`close_step` 之后 `judge` 会看到
    # `step >= max_steps` 而终止，所以这里提前说得出）。放在最后——它是"没法
    # 继续"的兜底说法，而上面两条是这一键自己产生的、更具体的结局。
    if next_step >= max_steps:
        return StopReason.EPISODE_OVER

    return None


def compute_stall(
    after: Observation, action: ActionFromBrain, prev_key: str, prev_count: int
) -> tuple[str, int]:
    """算这一步的停摆键（画面机械状态 + 动作描述）与更新后的连续计数。

    跟上一步全同 → 计数 +1，否则清零重计一次。
    """
    key = f"{after.stall_key()}|{action.describe()}"
    count = prev_count + 1 if prev_key == key else 1
    return key, count
