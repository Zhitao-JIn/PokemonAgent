"""帧槽的写与读：一步的开局画面从哪来、怎么按步号取回来。

**为什么单独一个模块**：帧槽（`HarnessDeps.frame_before` / `HarnessDeps.frame_after`）
是**跨域共用**的——写侧分散在**图外**（`episode_entry.begin_episode`）与
**图内**（`press/perceive_after_action`），读侧在步尾
`store/store_step_episode_memory`（每个键的步尾要这一步与下一步两张）。放进任何
一个域都会让别的域反过来 import 它。所以按"共用件"单立一个模块：七个域包那张
节点表没有为它安排位置——这段注释就是它的位置说明。

**判据**：这里没有"哪一步"的业务语义，只有"帧槽怎么写、怎么读"，所以它不属于
任何节点。写侧两个产出格：第 0 步那一帧在**图外**的 `begin_episode`（那时还没有
任何事件可挂），其余每一步的开局画面在**图内每键**的 `perceive_after_action`。

**槽只有两个具名位**（0913 晚第二版，取代原先按步号索引的 dict）：`before` =
**这一步**的开局画面，`after` = **下一步**的开局画面。写新帧就是**一次挪动**——
旧的 `after` 挪进 `before`，新帧落 `after`。"挪"正是它只有两个位的原因。

为什么恰好两步：一步之内有多个读者——步尾 `store_step_episode_memory` 要 `before`
与 `after` 两张（对应 `StepMemory` 的 `before_frame`/`after_frame`）；链首
`record_observation` 按 `obs.step` 取**本步开局画面**挂 `OBSERVE`。只留一帧仍不够：
步尾刚产出的那帧会当场把要的另一张挤掉。留三帧以上纯属浪费。

**帧只经这一个槽取**（0914 封套改造）：原先还有"回盘读事件的 `frame_png`"这条
兜底路（`deps.frame_event_ids` 登记表 + `TracePort.read_event`），而封套改造把
事件自带的图整条拆了——登记表、`read_event`、`frame_png` 互为唯一消费者，一起下线。
（同日跟进：观察账 `observe`/`after_action` 的**正文**重新带图，但取法不变——
`after_action` 直接带刚产出的那一帧、`observe` 查本槽；槽成了画面唯一的取用通道，
跨进程时槽是空的，那时观察账就没有 `frame` 键。）
"""

from __future__ import annotations

from ..deps import HarnessDeps


def remember_frame(deps: HarnessDeps, episode_id: str, step: int, frame_png: str | None) -> None:
    """把一帧记进帧槽——**帧槽的唯一写入口**。

    槽是两个具名位，写新帧就是**一次挪动**（三元组是 `(episode_id, step, base64 PNG)`）：

    | 写之前 | 写之后 |
    |---|---|
    | `before` 空（本局第一帧，图外的 `begin_episode` 产出） | `before` ← 新帧 |
    | `before` 有、`after` 空（本局第 2 帧） | `after` ← 新帧 |
    | 两位都有 | `before` ← 旧的 `after`，`after` ← 新帧 |

    后置条件：`before` 是**当前这一步**的开局画面、`after` 是**刚产出的下一步**
    那张——正好是 `StepMemory` 的 `before_frame`/`after_frame` 两个字段要的东西。

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


def frame_b64(deps: HarnessDeps, episode_id: str, step: int) -> str | None:
    """第 `step` 步开局画面的 base64 PNG；槽里没有就是 `None`。

    **只有一个取法**：查帧槽（`deps.frame_before` / `deps.frame_after`）。产出方
    （图外的 `begin_episode` / 图内每键的 `perceive_after_action`）刚把它挪进槽，
    而唯一的读者（步尾 `store_step_episode_memory`）贴在这两步之内：`before` 给
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
