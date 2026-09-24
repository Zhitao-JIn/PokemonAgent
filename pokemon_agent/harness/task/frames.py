"""帧槽的写与读：task 层 ActMemory 的前后两张图从哪来。

**写侧只有一处**：task 的 perceive 格里的 `sense`（每圈取一帧就写一次）。
**读侧只有一处**：同一格里的 `store_step_episode_memory`（ActMemory 的 `before_frame` /
`after_frame`）。episode 层自己取的帧（完整档）不进槽——它的 `sense_frame` 账直接带图。

单立一个模块是因为槽住在 `TaskRuntime` 上、写读两个单元都要用，这里只有"怎么写、怎么读"，
没有任何一格的业务语义。

**槽只有两个具名位**：`before` = 这一键按下前的画面，`after` = 按下后的画面。写新帧就是一次
挪动——旧的 `after` 挪进 `before`，新帧落 `after`。按步号查，所以某个 task 的首帧与上一个
task 的末帧步号相同时，查到哪张都是同一个世界状态。

跨进程时槽是空的，那时就是没有图（不再有回盘兜底）。
"""

from __future__ import annotations

from .task_runtime import TaskRuntime


def remember_frame(deps: TaskRuntime, episode_id: str, step: int, frame_png: str | None) -> None:
    """把一帧记进帧槽——**帧槽的唯一写入口**。

    槽是两个具名位，写新帧就是**一次挪动**（三元组是 `(episode_id, step, base64 PNG)`）：

    | 写之前 | 写之后 |
    |---|---|
    | `before` 空（本局第一帧） | `before` ← 新帧 |
    | `before` 有、`after` 空（本局第 2 帧） | `after` ← 新帧 |
    | 两位都有 | `before` ← 旧的 `after`，`after` ← 新帧 |

    后置条件：`before` 是**当前这一步**的开局画面、`after` 是**刚产出的下一步**
    那张——正好是 `ActMemory` 的 `before_frame`/`after_frame` 两个字段要的东西。

    换局时两位**整对清空**（槽里任何一帧的 `episode_id` 不是本局就作废）：上一局的
    帧不该跟着新局活着，留着会让新局第 0 步的 `before` 变成上一局最后一帧。

    后置条件（缺帧这一支）：`frame_png is None` 时**不写、也不挪**——缺帧是预期内的
    正常情形（感知那一档没产出图），不占槽位。读者在槽里查不到就是 `None`
    （0914 封套改造后不再有回盘那级）。

    前置条件：`episode_id` 非空、`step >= 0`。
    """
    assert episode_id, "remember_frame() got an empty episode_id"
    assert step >= 0, f"remember_frame() got a negative step: {step}"
    if frame_png is None:
        return

    before, after = deps.frame_before, deps.frame_after
    # 跨局整对清空：两位里只要有一张不是本局的，两张一起作废。
    if (before is not None and before[0] != episode_id) or (
        after is not None and after[0] != episode_id
    ):
        before = after = None

    if before is None:
        before = (episode_id, step, frame_png)
    elif after is None:
        after = (episode_id, step, frame_png)
    else:
        before, after = after, (episode_id, step, frame_png)
    deps.frame_before, deps.frame_after = before, after


def frame_b64(deps: TaskRuntime, episode_id: str, step: int) -> str | None:
    """第 `step` 步开局画面的 base64 PNG；槽里没有就是 `None`。

    **只有一个取法**：查帧槽（`deps.frame_before` / `deps.frame_after`）。产出方（task 的
    `sense`）刚把它挪进槽，唯一的读者（`store_step_episode_memory`）紧跟其后：`before` 给
    `before_frame`，`after` 给 `after_frame`。正常跑必然命中，**零盘 IO**。

    0914 封套改造删掉了原先的第二级（回盘按 `deps.frame_event_ids` 找承载这一帧的
    事件、读它自带的 `frame_png`）——事件不再自带图，那级连同登记表一起下线。
    跨进程（将来若恢复重放）时槽必然是空的，那时就是没有图。

    查不到槽、或那一帧本来就没产出（感知那一档没给图），都返回 `None`——
    两者都是预期内的正常情形。

    前置条件：`episode_id` 非空。
    """
    assert episode_id, "frame_b64() got an empty episode_id"

    for frame in (deps.frame_before, deps.frame_after):
        if frame is not None and frame[0] == episode_id and frame[1] == step:
            return frame[2]
    return None
