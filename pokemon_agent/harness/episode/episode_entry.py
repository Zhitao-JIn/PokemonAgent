"""episode 图的**图外侧门**：开局与恢复的装配器（`PLAN_graph_composition.md` §6 步 2）。

## 为什么这两件事必须在图外（不是取舍，是逻辑上的先后）

`resume` 做七步，**前六步的产物就是"进图的完整初始状态"**（§4.0(b) 的表）。
三条理由一条比一条硬：

1. **图的入口状态必须是完整的**（它带着不变式 `observation.step == step`）。要是
   `resume` 变成图的一个节点，"进图的初始状态"就只是一个半初始化的 state，图的
   第一个节点得能处理"我是恢复来的还是新开的"——**图就有了两个入口语义**，
   每个下游节点都得接受两种初值。那是把"装配"塞进了"运行"里。
2. **`void_after` 的前提是"图还没开始跑"**：它要归档 `cursor` 之后的东西，而图一旦
   跑起来，那些东西正是图正在产生的。（`run/run_entry.py` 里那条"restore 标记必须在
   `invoke()` 之后写"的注释就是这条边界的实证。）
3. **`load_state_bytes` 是世界层动作**：做成节点就等于承认"图的一个节点可以基于
   磁盘/模拟器任意改世界"，**replay 的可重放性当场断掉**。

于是 `begin_episode` 与 `prepare_resume` 是**同一族的图入口装配器**，住在这个文件里；
而 `close_episode`（只算账、不推世界）在图内——这个不对称是有意的：现行的
"`act` 是唯一推世界的节点"这条约束比对称性重要。

## 本文件提供四个函数

    begin_episode(deps, …)  -> EpisodeRunState   新跑：EPISODE_START + 世界起点 + 开局视觉感知
    prepare_resume(deps, …) -> EpisodeRunState   恢复：七步里的前六步（装配出一个完整初值）
    run_new(deps, graph, …) -> Outcome           写账 → 进图 → 取结算（异常路径补 EPISODE_ERROR）
    run_resume(deps, graph, …) -> Outcome        同上，但初值由 `prepare_resume` 装配

`graph` 显式传参（不藏在某个对象里）：本步它是 `EpisodeHarness._graph`，步 3 之后
它就是 `episode/episode_graph.py` 的模块级编译产物。**它不是 owner**——两个 `run_*` 才是
"这一次派发"的编排者。

## 与父图的交界

`deps` 是全图唯一的 context（F10/F11）。本文件读它的 `game` / `trace` / `memory` /
`checkpoint_root` / `run_id` / `world_reset_done` / 两张帧表 / `run_state_snapshot`
——**不再有 `self.`**（步 2 把 `_begin` / `resume` 从 `EpisodeHarness` 搬出来时，
依赖从 `self.*` 换成 `deps.*`，函数体一字未改）。

**步 5b 起「存档」由本文件与 `open/save_checkpoint.py` 直接读写模型**（`EpisodeCheckpoint`），
不再经过一根 Port；`prepare_resume` 的第二步（`void_timeline`）就是原
`CheckpointTool.void_after` 那四步的编排。
"""

from __future__ import annotations

import shutil
import time
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.brain import Goal, Task
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolLoadStateBytesReq,
    FromHarnessToGameToolResetReq,
    FromHarnessToGameToolSetTaskReq,
    FromHarnessToMemoryToolVoidMemoryAfterReq,
    FromHarnessToTraceToolAppendReq,
    FromHarnessToTraceToolVoidAfterReq,
    FromRunHarnessToEpisodeHarnessRunResp,
)
from pokemon_agent.trace import TraceKind

from ..deps import HarnessDeps
from .episode_graph import NODES_PER_DECISION, NODES_PER_PRESS, RECURSION_MARGIN
from .episode_state import EpisodeCheckpoint, EpisodeRunState, safe_dirname
from .press.perceive_after_action import perceive_once


def exc_snapshot(exc: Exception) -> str:
    """异常的字符串快照——`episode_error` 的 req 的 `error` 字段只吃文本，
    `Exception` 对象进不了 Pydantic req（`run/run_entry.py` 里有一份同形的）。
    """
    return f"{type(exc).__name__}: {exc}"


# ---- 装配器（图外）：两条入口的"进图初值" ----


def begin_episode(
    deps: HarnessDeps,
    episode_id: str,
    task: Task,
    stack: list[Task],
) -> EpisodeRunState:
    """开一局：写 EPISODE_START、reset 世界、感知第一帧，返回初始状态。

    `stack` 是整个目标栈（run 级投影）：`episode_goals` = 全栈投影，**判只判栈顶**
    （`episode_goals[-1]` = task.goal），其余层是给大脑的全局信息。
    """
    # 步骤 1：开局账——EPISODE_START。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.EPISODE_START,
            step=0,
            episode_id=episode_id,
            task=task,
        )
    )

    # 步骤 2：世界起点只在 run 的第一个 episode 读一次；后续 episode
    # **不重置**，接着上一局结束的状态继续跑（取舍见 `CHANGELOG.md`
    # 2026-09-03 条目）。局起点不再另存快照——终止判定全在 `judge`
    # 出口，退出前最后一圈入口的 checkpoint（`save_checkpoint`）就是
    # 本局的终止画面，也是下一局的起点画面；ep1 起点 = `reset()`
    # 加载的 ROM 存档，同样可复现。
    #
    # 这个记号从 `EpisodeHarness._world_reset_done` 搬到 deps（D11）：它的语义
    # 本来就是 run 级的（"这个 run 的世界起点读过了没有"），跟"哪一局"无关。
    if not deps.world_reset_done:
        deps.game.reset(FromHarnessToGameToolResetReq(task=task))
        deps.world_reset_done = True

    # 步骤 3：感知第一帧（重试循环与记账都在 `press/perceive_after_action.py` 的
    # `perceive_once`——图内那一格用的是**同一个宿主**，所以"这一帧的账"只有一处实现，
    # 步 3 之前这里与 `EpisodeHarness._perceive` 各有一份**同样 8 行**的重复）；
    # 原始画面不随感知调用落盘，而是先暂存进 `deps.pending_frames`——这一帧是第 0 步的
    # 开局画面，等链首的 `record_observation` 记 `OBSERVE` 时，由它把图挂上去并登记登记表。
    obs, frame_png = perceive_once(deps, episode_id, 0)
    if frame_png is not None:
        deps.pending_frames[(episode_id, 0)] = frame_png
    assert not obs.done, "reset() must return a fresh observation"

    # 步骤 4：组装初始状态。**开局这一帧直接就是 `observation`**（第 0 步）：
    # 开局没有"上一步"，不需要 `pending_observation` 那道接力——扶正它是
    # 本函数的活（之后每一步的扶正归 `close_step`）。
    return EpisodeRunState(
        episode_id=episode_id,
        task=task,
        episode_goals=[Goal(goal=t.goal, criteria=t.success_criteria) for t in stack],
        observation=obs,
    )


def prepare_resume(
    deps: HarnessDeps,
    episode_id: str,
    task: Task,
    step: int,
) -> EpisodeRunState:
    """恢复：七步准备里的**前六步**——跑完就得到一个可以直接进图的完整初值。

    前置条件：`deps.checkpoint_root` 非空（装配时注入了存档根目录）；
    `(episode_id, step)` 的存档成对存在。恢复语义：废弃处理（`void_timeline`）+
    世界快照回载 + 状态回载（它在存档里，记忆由各 store 落盘读回）+ **帧账回载**（v6），
    **不重调视觉模型、不重跑已完成节点**。

    第七步（`graph.invoke`）在 `run_resume` 里——那是"运行"，不是"装配"。
    """
    root = deps.checkpoint_root
    assert root is not None, "prepare_resume() needs a checkpoint_root"
    # 步骤 1：取存档（成对/签名校验在 `EpisodeCheckpoint.read()` 内），状态直接在里面。
    checkpoint = EpisodeCheckpoint.read(root, episode_id, step)
    assert checkpoint is not None, f"no checkpoint for ({episode_id}, {step})"
    state = checkpoint.episode_state
    assert state.episode_id == episode_id and state.task == task
    # 步骤 2：废弃处理（对账游标 = 存档的 last_event_id；trace 打标 + 记忆/存档归档）。
    void_timeline(deps, episode_id, step, checkpoint.last_event_id)
    # 步骤 3：世界快照回载——唯一不可从事件重建的东西。`load_state_bytes()`
    # 只回载模拟器字节，不认得 `_task`/`_closed`（纯 Python 记账，不进存档）；
    # 不补 `set_task()` 的话，本局自己靠 `pending_observation` 收尾没事，
    # 但本 run 后续再派发新 episode 时（同一个长命 world、`world_reset_done`
    # 已是 True、不会走 `reset()`）会在 `perceive_once()`/`step()` 撞上
    # "before reset()" 断言——这是 check_restore.py 端到端跑出来的真故障。
    deps.game.load_state_bytes(
        FromHarnessToGameToolLoadStateBytesReq(emulator_state=checkpoint.emulator_state)
    )
    deps.game.set_task(FromHarnessToGameToolSetTaskReq(task=task))
    # 这一步**不是记账，是"别再 reset"的强制令**（D11 / §5.2-8）：恢复路径不走
    # `begin_episode`，而本局跑完后**下一局**会走——那时若为 False 就会 `reset()`，
    # 把刚 `load_state_bytes` 恢复的世界冲回 ROM 起点（不是"重读一次"，是世界回退）。
    deps.world_reset_done = True
    # 步骤 4：帧账回载（v6）——两张表都是纯内存态：截图按 event_id 躺在磁盘上，
    # 但"哪条事件承载这一步这一帧"只有内存里那两张表知道。不回载的话，恢复后
    # 第一条 `OBSERVE` 与第一个 store 步的 `before_frame` 会一起丢图（真机
    # `check_restore` 就是在这个缺口上丢的帧）。
    for frame_step, event_id in checkpoint.frame_event_ids.items():
        deps.frame_event_ids[(episode_id, frame_step)] = event_id
    for frame_step, png in checkpoint.pending_frames.items():
        deps.pending_frames[(episode_id, frame_step)] = png

    # 步骤 5：落恢复事件（replay/统计的接缝标记）。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHECKPOINT_RESTORE,
            episode_id=episode_id,
            step=state.step,
            restored_episode_id=checkpoint.episode_id,
            restored_step=checkpoint.step,
            cursor=checkpoint.last_event_id,
        )
    )
    return state


def void_timeline(
    deps: HarnessDeps,
    episode_id: str,
    step: int,
    cursor: int,
) -> None:
    """废弃恢复点之后的时间线（原 `CheckpointTool.void_after` 的那四步）。

    1. **trace 打标 + 圈定**：走 `TraceToolPort.void_after`——`event_id > cursor`
       的事件原地打 `valid=false`，返回的名单是"只活在游标之后的局"（整局废弃）。
    2. **圈定作废范围**：目标局 `step > N-1`（N 是恢复步——存档 N 是"第 N 步开局"，
       拍它时完成的只有 step 0..N-1，废弃分支写的 step N..M 全要作废），外加每一个
       future episode **整局**（`keep_step = -1`）。这一步**只能在这里算**：它是恢复
       语义，不是存储知识。
    3. **memory 归档**：`MemoryToolPort.void_memory_after` 把作废记录搬进
       `memory/voided-<ts>/<kind>/` 并摘出索引（不 unlink——落盘了就不丢）。
       knowledge 不进作废范围（全局先验、不属任何一局）。
    4. **checkpoint 归档**：`target_scope` 里每一局的 step 目录整体搬进
       `<checkpoint_root>/voided-<ts>/`——目标局也搬（旧时间线的存档一律离场，
       重跑会写出新的那批）。

    **截图不参与**（拍板⑨）：event_id 永远递增，resume 重跑零撞名，废弃事件的截图
    原地保留。
    """
    # 步骤 1：trace 打标 + 圈定整局废弃的局。
    future_episodes = deps.trace.void_after(
        FromHarnessToTraceToolVoidAfterReq(cursor=cursor)
    )
    # 步骤 2：作废范围。目标局的 keep_step 取 `step - 1`（见 docstring）——取 N 会让
    # 废弃分支写下的 step N 漏网，重跑又从 step N 写一条，同一局同一步两条记录。
    # `step=0` 自然落到哨兵 -1（=整局废弃），正是"从第 0 步重跑"该有的语义。
    target_scope: list[tuple[str, int]] = [(episode_id, step - 1)]
    target_scope += [(eid, -1) for eid in future_episodes]
    # 步骤 3：memory 层归档（MemoryTool 自己知道 uuid → 路径）。
    for eid, keep_step in target_scope:
        deps.memory.void_memory_after(
            FromHarnessToMemoryToolVoidMemoryAfterReq(episode_id=eid, step=keep_step)
        )
    # 步骤 4：checkpoint 归档（目标局也搬——旧时间线的存档一律离场）。
    root = deps.checkpoint_root
    assert root is not None, "void_timeline() needs a checkpoint_root"
    voided_dir = root / f"voided-{time.strftime('%Y%m%d-%H%M%S')}"
    voided_dir.mkdir(parents=True, exist_ok=True)
    for eid, _keep_step in target_scope:
        eid_dir = root / "step" / safe_dirname(eid)
        if eid_dir.is_dir():
            shutil.move(str(eid_dir), str(voided_dir / f"step-{safe_dirname(eid)}"))


# ---- 两个入口：装配 → 进图 → 取结算 ----


def run_new(
    deps: HarnessDeps,
    graph: CompiledStateGraph,
    *,
    episode_id: str,
    task: Task,
    stack: list[Task],
    run_state: dict[str, Any] | None,
) -> FromRunHarnessToEpisodeHarnessRunResp:
    """跑完一局：解决栈顶这一个目标。

    前置条件：episode_id 非空、task.max_steps > 0、stack 非空且栈顶 == task。
    后置条件：trace 里恰好多一条 EPISODE_START 和一条 EPISODE_END。

    `stack` 是整个目标栈（全局信息）——投影成 `episode_goals`（判只判栈顶，
    `episode_goals[-1]` = task.goal），其余层是给大脑的全局视野。`run_state` 是
    `RunHarness.dispatch()` 派发这一局时的 `RunState.model_dump()`——本层
    不解读，只存起来供 `save_checkpoint()` 原样打包进每一步的存档（run
    级状态跟 episode 级状态从此共存一份文件，见 `episode_state.EpisodeCheckpoint`）。
    """
    assert episode_id, "run_new() got an empty episode_id"
    assert task.max_steps > 0, f"max_steps must be > 0, got {task.max_steps}"
    assert stack and stack[-1].task_id == task.task_id, (
        "run_new() needs a non-empty stack whose top is the task being run"
    )
    deps.run_state_snapshot = run_state

    # 步骤 1：开局，跑图直到终止。
    # `recursion_limit` 的换算在 `_invoke()` 里（`episode/episode_graph.py` 的
    # `NODES_PER_DECISION` + `NODES_PER_PRESS` 两个常量）——**那两个数字必须跟着
    # `episode/episode_graph.py` 的节点集合一起改**，否则会在步数没走完时被 LangGraph 的
    # `GraphRecursionError` 无声打断（论证见 `CHANGELOG.md` 2026-09-05 条目）。
    try:
        state = begin_episode(deps, episode_id, task, stack)
        final = _invoke(deps, graph, state, task)
    except Exception as exc:
        # 步骤 2：异常路径——补 EPISODE_END（error 变体）再原样抛出。
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.EPISODE_ERROR,
                episode_id=episode_id,
                step=0,
                error=exc_snapshot(exc),
            )
        )
        raise

    return close(final, task)


def run_resume(
    deps: HarnessDeps,
    graph: CompiledStateGraph,
    *,
    episode_id: str,
    task: Task,
    step: int,
    run_state: dict[str, Any] | None,
) -> FromRunHarnessToEpisodeHarnessRunResp:
    """从本局第 `step` 步开局的 checkpoint 恢复并跑完（PLAN_checkpoint §5）。

    前置条件与恢复语义见 `prepare_resume`。本函数只负责三段编排：
    **准备（`prepare_resume`）→ 进图 → 取结算**，异常路径补 `EPISODE_ERROR` 再抛。
    """
    deps.run_state_snapshot = run_state
    try:
        state = prepare_resume(deps, episode_id, task, step)
        final = _invoke(deps, graph, state, task)
    except Exception as exc:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.EPISODE_ERROR,
                episode_id=episode_id,
                step=0,
                error=exc_snapshot(exc),
            )
        )
        raise

    return close(final, task)


# ---- 进图与取结算 ----


def _invoke(
    deps: HarnessDeps,
    graph: CompiledStateGraph,
    state: EpisodeRunState,
    task: Task,
) -> dict[str, Any]:
    """跑图直到终止。`recursion_limit` 按剩余步数换算（新跑/恢复同一条公式）。

    **`max_steps` 是"小 action 数"**（每按一个键一步），而一圈的节点数取决于
    这一圈的链长：`NODES_PER_DECISION + NODES_PER_PRESS` 是"链长 = 1"时的
    开销，也正是每步开销的上界（链长 K ≥ 1 时 `10 + 7K ≤ 17K`）。按上界算，
    链再长也不会被 LangGraph 的 `GraphRecursionError` 无声打断。
    **这两个常量必须跟着 `episode/episode_graph.py` 的节点集合一起改**（论证见
    `CHANGELOG.md` 2026-09-05 条目）。

    这一局自己的 limit 是**贴身的那一道**：管"这一局别跑飞"。run 级另有**一个
    闸门常量**（`run_entry.RUN_RECURSION_LIMIT`，一个大数、不按公式算）——它
    **不覆盖**本局的步数（本仓是形态 B：父子各算各的计数器，实测见探针 X5），
    只负责"整个 run 别无限跑"。

    **`context=deps`（步 3 起是必需项，不是可选项）**：节点从方法搬成自由函数后
    签名是 `(state, runtime: Runtime[HarnessDeps])`，而 `runtime.context` 正是
    这里递进去的那个对象（F6 实测：官方依赖注入通道；F11：框架**不重建**它）。
    此前节点是 `self.xxx` 方法、依赖走 `self.deps`，所以这一步加不加都跑得动；
    搬完第一个节点起，不给就会让节点读到一份空的 context——**炸在第一个节点上**，
    定位成本很低，但别拖到那时才发现。
    """
    return graph.invoke(
        state,
        {"recursion_limit": episode_budget(task, state.step)},
        context=deps,
    )


def episode_budget(task: Task, step: int) -> int:
    """一局从第 `step` 步起还能烧掉多少个 superstep——**这是贴身的那个限**。

    它是"这一局能不能跑完"的守护，逐局按剩余步数算（`judge` 就是按
    `state.step >= task.max_steps` 判停的）。**run 级不再引用它**：那边只留一个可调的
    闸门常量 `run_entry.RUN_RECURSION_LIMIT`（X5 拍板——形态 B 下父子计数独立，
    run 级没有可算的预算；见 `run/run_entry.py` 那个常量的 docstring）。

    上界推导：每按一个键一圈 `NODES_PER_DECISION + NODES_PER_PRESS` 个节点，
    是"链长 = 1"的开销、也是每步开销的上界（链长 K ≥ 1 时 `10 + 7K ≤ 17K`）。
    """
    per_press = NODES_PER_DECISION + NODES_PER_PRESS
    return (task.max_steps - step) * per_press + RECURSION_MARGIN


def close(
    final: dict[str, Any], task: Task
) -> FromRunHarnessToEpisodeHarnessRunResp:
    """收尾：取出图内 `close_episode` 已经写好并落账的结算（run_new/run_resume 共用）。

    **图跑完之后这里不再算任何东西**（D2-④）：结算由 `close_episode` 节点
    从同一份 final_state 派生、写进 `state.outcome` 并落 `EPISODE_END`，
    本函数只把它取出来交给调用方。

    顺带在这里落**D6 的事后断言**：一局的步数不可能超过 `task.max_steps`
    （`judge` 就是按 `state.step >= task.max_steps` 判停的）。把"靠 limit 兜底"
    换成"靠断言报警"——真撞上 recursion_limit 是**无声截断**，而这条会在开发期
    就地炸（`PLAN_graph_composition.md` §4 D6）。
    """
    final_state = EpisodeRunState.model_validate(final)
    assert final_state.outcome is not None, "close_episode must have written the outcome"
    assert final_state.outcome.steps <= task.max_steps, (
        f"episode ran {final_state.outcome.steps} steps > max_steps={task.max_steps}"
        " —— 递归上限或终止判定有一个失灵了"
    )
    return final_state.outcome


__all__ = [
    "begin_episode",
    "close",
    "episode_budget",
    "exc_snapshot",
    "prepare_resume",
    "run_new",
    "run_resume",
    "void_timeline",
]
