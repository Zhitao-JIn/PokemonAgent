"""帧账的读：本局哪些步号的画面挂在哪条事件上、以及按事件把那一帧读回来。

**为什么单独一个模块**：帧账（`HarnessDeps.frame_event_ids` / `pending_frames`）是
纯内存态，而**读点跨域**——`open/record_observation`（链首要把上一条链链尾那一帧
读回来）与 `store/step_episode_memory`（逐键的 `before_frame`/`after_frame`）都要读，
`open/save_checkpoint` 还要把它切片打包进存档。放进任何一个域都会让别的域反过来
import 它。所以按"共用件"单独立一个模块：`PLAN_graph_composition.md` §3.1 的树只列
节点文件，没有为它安排位置——这段注释就是它的位置说明。

**判据**：这里没有"哪一步"的语义，只有"这张表怎么读"，所以它不属于任何节点。
写侧（登记一帧）落在产出它的那一格：第 0 步在 `open/record_observation`，其余每键在
`press/perceive_after_action`。
"""

from __future__ import annotations

import base64

from pokemon_agent.trace import read_screenshot

from ..deps import HarnessDeps


def frame_ledger(
    deps: HarnessDeps, episode_id: str
) -> tuple[dict[int, int], dict[int, str]]:
    """把本局的帧账摊成两张"步号说话"的表，供存档打包（`open/save_checkpoint`）。

    **帧账是纯内存态，不随存档走就等于恢复后丢图**：`resume` 是在新进程里回载的，
    两张表若为空，恢复后第一条 `OBSERVE`（链首要自带"大脑决策时看到的世界"）与
    恢复后第一个 store 步的 `before_frame`（`StepMemory` 逐键都要那两帧）都会是
    `None`——而截图本来就在磁盘上（`screenshot/<event_id>.png`），缺的只是
    "哪条事件承载这一步这一帧"。

    只带**本局切片**：存档是"这一局第 `step` 步"的存档，别的局的帧账与它无关。

    前置条件：`episode_id` 非空。
    后置条件：返回 `(登记表, 暂存表)`，键是**整数步号**——落盘时由 `json.dumps`
    写成 `"<step>"`，读回时由 Pydantic 还原成整数键（`entry.prepare_resume()` 直接
    塞回两张表）。
    """
    assert episode_id, "frame_ledger() got an empty episode_id"
    registry = {
        step: event_id
        for (ep, step), event_id in deps.frame_event_ids.items()
        if ep == episode_id
    }
    pending = {
        step: png for (ep, step), png in deps.pending_frames.items() if ep == episode_id
    }
    return registry, pending


def frame_b64(deps: HarnessDeps, episode_id: str, step: int) -> str | None:
    """读第 `step` 步开局画面对应的便利截图、编成 base64；读不到就是 `None`。

    截图与 trace 事件共享 event_id（拍板⑦）：这里用 `deps.frame_event_ids` 里登记的
    帧事件 event_id 定位文件（`screenshot/<event_id>.png`），不再有按 step 号拼文件名
    的公式。`StepMemory.before_frame`/`after_frame` 已直接存 base64，只有
    `store/step_episode_memory` 反思成一条记忆的这一刻才需要现读现编；`judge` 的图
    完全来自 history 里已经存好的截图，不走这里。

    查不到登记就返回 `None`——那是"这一帧本来就没落图"的正常情形（感知失败的那
    一步）；`entry.prepare_resume()` 已把本局登记表从存档回载，恢复后不再存在
    "表是空的"这种缺口（见 `frame_ledger`）。
    """
    event_id = deps.frame_event_ids.get((episode_id, step))
    if event_id is None:
        return None
    raw = read_screenshot(deps.run_id, event_id)
    return base64.b64encode(raw).decode() if raw is not None else None
