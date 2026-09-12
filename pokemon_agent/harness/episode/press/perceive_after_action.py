"""`perceive_after_action`：感知 `act` 刚推进出来的新帧，**判读这一键的结局**，写这一键的
`AFTER_ACTION`。本文件同时是**所有感知调用的宿主**（`perceive_once`）与两个纯函数
（`perceive_with_retry` / `compute_stop`）的家。

改 `pending_observation`/`pending_stop` 两处——"这一键之后看到了什么"与"它为什么没有
继续"是**同一次感知的解读**，两个面。第三面（据此把不该再按的键从队列里拿掉）是**执行
后果**，住在下一格 `press/apply_stop`。

**为什么"判读"必须和"感知"同格**：链中途中止的那一键要补一次完整感知，触发条件就是
`stop is not None`，而 `stop` 是 `compute_stop(before, action, obs)` 的输出——把判读挪到
别的格子，这一格就不知道自己该不该补第二次感知。所以能拆的接缝只有"感知+判读 |
落实+留痕"这一条（论证见 `docs/spec/harness/PLAN_graph_readability.md` §3.6）。

感知分两档（见 `docs/spec/harness/PLAN_action_step_granularity.md` §3）：

- **链中间的键只读内存**：它只需要判"位置动没动、换没换图"，那两件事内存直接答得出；
  为此烧一次视觉调用买的全是用不上的信息（场景、对话），而且会让链的执行结果依赖模型
  返回——"同存档 + 同链 → 同一状态"当场失效。
- **链尾那一键、以及中止的那一键做完整感知**：前者那一帧要交给 `gate/judge` 看，后者是
  这一圈真正的落点。两类加起来，`MODEL_CALL(PERCEPTION)` 的条数与改动前相等（验收
  不变量，§9）。

**中止范围的唯一判据**（§5）：只扩到"再做下去会产生它没打算要的动作"为止。`blocked`
之后再按只是空按（浪费一点 tick），所以只丢掉本段剩余次数；`warp` 之后再按是在**一张
它没规划过的地图**上产生位移，所以整条链作废——**截断本身在下一格**（`apply_stop`），
这里只交出 `stop`。

**账也在这里写**：本格是帧的产出格，所以帧归本格那条 `AFTER_ACTION`（观察摘要：
`status`/`done`，链内每键一条）。`stop` 是**处置**，不进这条观察账——它归
`apply_stop` 只在真丢键时写的那条 `ACTION_TRUNCATED`。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Action
from pokemon_agent.errors import PerceptionAttemptFailed, PerceptionFailure
from pokemon_agent.providers import ModelCall
from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendModelCallsReq,
    FromHarnessToTraceToolAppendReq,
    ModelCallLog,
)
from pokemon_agent.schemas.memory import StopReason
from pokemon_agent.tools.interface import GameToolPort
from pokemon_agent.trace import Source, TraceKind
from pokemon_agent.world import BUTTON_FACING, Observation

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState

PERCEPTION_MAX_RETRIES = 2
"""感知重试预算：一帧最多问几次视觉模型。循环在这里不在 World。"""


def perceive_with_retry(
    game: GameToolPort,
    *,
    ram_only: bool = False,
) -> tuple[Observation | None, str | None, ModelCallLog]:
    """反复问一次感知，直到成功或预算耗尽——**循环与端口调用在这里**，
    `perceive_once()` 只负责单次尝试（见 `docs/ROADMAP.md`）。

    `ram_only=True` 时不问模型：交回的观测只有内存那半，`log` 是空的（没有
    `MODEL_CALL` 要记），因而**不会失败、也不会重试**。

    端口是**参数**、不是 `self` 属性——这样能用假端口独立测试，不用起一张真图。

    步骤 1：问一次感知，失败就把这次的账收进 `log`（`attempt` 由这里定，盖章在渲染层），
    继续下一次尝试。
    步骤 2：成功返回 `(观测, base64 PNG, log)`——一次感知可能有多条 call，逐条收进
    `log`（同一个 `attempt`）。
    步骤 3：预算耗尽返回 `(None, None, log)`——**收场归调用方**（抛 `PerceptionFailure`），
    因为账要由宿主写。

    **截图从这条路径上摘下来了**：帧和"这次模型调用"是两件事——`MODEL_CALL` 记的是喂给
    模型的东西，而链中间的键只读内存、压根没有这次调用，图要是挂在它上面，那些步就永远
    没有图。帧改由调用方挂到产出它的那一步的事件上（`AFTER_ACTION`），**帧的可得性从此
    与"有没有人看过它"无关**。
    """
    log: ModelCallLog = []
    for attempt in range(1, PERCEPTION_MAX_RETRIES + 1):
        # 步骤 1：问一次感知。
        try:
            result = game.perceive_once(ram_only=ram_only)
        except PerceptionAttemptFailed as exc:
            # 步骤 2：失败，把账收进 log，进入下一次尝试。
            raw = exc.call.get("raw", "")
            log.append(
                (
                    attempt,
                    ModelCall(
                        payload=exc.call,
                        error_kind="PerceptionParseFailure",
                        error=raw,
                    ),
                )
            )
            continue

        # 步骤 3：成功——逐条收账，交回观测 + 这一帧的画面。
        log.extend((attempt, ModelCall(payload=call)) for call in result.calls)
        return result.observation, result.frame_png, log

    # 步骤 4：预算耗尽——材料交回调用方，由它决定怎么收场。
    return None, None, log


def perceive_once(
    deps: HarnessDeps,
    episode_id: str,
    step: int,
    *,
    ram_only: bool = False,
) -> tuple[Observation, str | None]:
    """感知一帧，并把这次的尝试账落进 trace——**两个感知调用点的共同宿主**。

    调用点有两个：本文件的节点 `perceive_after_action`（图内）与
    `episode_entry.begin_episode`（图外的局入口）。两者都走 `perceive_with_retry`（循环与
    重试预算都在那里），但**账按"写在它的宿主里"这条规则统一落在这里**——于是
    `MODEL_CALL(PERCEPTION)` 与消费它的那一格在同一个函数里，不再是"util 边重试边写"
    （见 `docs/spec/harness/PLAN_graph_readability.md` §3.7.4）。

    前置条件：`episode_id` 非空。
    后置条件：返回 `(观测, base64 PNG | None)` 成对；预算耗尽时抛 `PerceptionFailure`
    ——**账已经写完**，重试期间烧掉的 token 一条不少。`ram_only=True` 时压根不问模型
    （`log` 为空），因此不会走到失败分支。
    """
    observation, frame_png, log = perceive_with_retry(deps.game, ram_only=ram_only)
    deps.trace.append_model_calls(
        FromHarnessToTraceToolAppendModelCallsReq(
            episode_id=episode_id,
            step=step,
            source=Source.PERCEPTION,
            log=log,
        )
    )
    if observation is None:
        last_reason = log[-1][1].error if log else "ram_only 从不失败"
        raise PerceptionFailure(len(log), last_reason)
    return observation, frame_png


def compute_stop(
    before: Observation,
    action: Action,
    after: Observation,
    *,
    next_step: int,
    max_steps: int,
) -> StopReason | None:
    """**这一键之后为什么没有继续按键**——纯 RAM 判据，不调任何模型。

    调用方是本文件的节点：它拿着按键前后的两帧（链内的键只有 RAM 那一档），纯字段比较
    就能回答这个问题——这也是整条链**确定**的前提（同存档 + 同链 → 同一状态序列），见
    `docs/spec/harness/PLAN_action_step_granularity.md` §3/§5。

    判定顺序（世界没了最优先，其余局部归因优先，`episode_over` 兜底）：世界没了
    （`after.done`）时内存读数不再可信，此时报"本局结束"而不是据那份读数说"撞墙了"；
    剩下的能归因到**这一键**的就归因到它（撞墙 / 换图），归因不到才说"本局到点了"。
    这么排是因为 `stop` 的读者是下一步的大脑：它要的是"我这一下发生了什么"，而"本局结束"
    这件事不用 `stop` 说——最后一帧的 OBSERVE/JUDGE 已经在说它了。

    前置条件：`action` 是单键（`sequence` 一段）——执行层已经展开过。
    后置条件：返回 `None` 表示这一键没有异常（要么背后还有待按的键，要么它本来就是
    链尾）；返回非 None 时调用方按 §5 的作废范围截断队列。
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
    # `step >= max_steps` 而终止，所以这里提前说得出）。放在最后——它是"没法继续"的
    # 兜底说法，而上面两条是这一键自己产生的、更具体的结局。
    if next_step >= max_steps:
        return StopReason.EPISODE_OVER

    return None


def perceive_after_action(
    state: EpisodeRunState, runtime: Runtime[HarnessDeps]
) -> dict[str, Any]:
    """感知新帧、判读结局、写 `AFTER_ACTION`。**只改 `pending_observation`/`pending_stop` 两处。**

    前置条件：`state.observation`/`state.action` 非空（前两格 `act` 已跑过）。
    后置条件：返回 `{"pending_observation": …, "pending_stop": …}`；有帧时把这一帧登记进
    `deps.frame_event_ids`（供 `StepMemory` 的 before/after 与"链尾帧读回"用）。
    """
    deps = runtime.context
    assert state.observation is not None, "perceive_after_action before act"
    assert state.action is not None, "perceive_after_action without an action"
    ep, before, action = state.episode_id, state.observation, state.action
    # `act` 已经弹掉队首，所以"队列空"就是"刚按的这一个是链尾"。
    is_decision_tail = not state.pending_presses

    # 步骤 1：感知（重试循环与记账都在 `perceive_once`）。链尾直接走完整档，
    # 链中间的键先只读内存。账的步号取 `before.step`——与 `ACT` 落在同一步上。
    obs, frame_png = perceive_once(deps, ep, before.step, ram_only=not is_decision_tail)

    # 步骤 2：判这一键的结局。纯字段比较，不调模型——判据见 `compute_stop`。
    stop = compute_stop(
        before,
        action,
        obs,
        next_step=before.step + 1,
        max_steps=state.task.max_steps,
    )

    # 步骤 3：链中途就中止的那一键补一次完整感知——它是这一圈真正的落点，跟链尾同一个
    # 待遇（判定层要看的字段里，只有对话文字 RAM 读不出）。
    #
    # 已知代价（真机要验，PLAN §7.10）：这一键按下去时 `settle=False`（当时以为后面还有
    # 键），所以这份观测可能落在过场中间——换图尤其明显。链内窗口现在是
    # `WITHIN_ACTION_FRAMES`（2 秒），够不够读出换图后的画面没有验证过。
    if stop is not None and not is_decision_tail:
        obs, frame_png = perceive_once(deps, ep, before.step)

    # 步骤 4：**给这一帧盖上它自己的步号**——它是"第 `before.step + 1` 步的开局画面"。
    # `close_step` 拿它当新 `observation` 时步号只加一，两处必须同值（不变式
    # `observation.step == step`）；不同值的话 `(episode_id, step)` 这个记忆键会从第二步
    # 起就错位，`before_frame`/`after_frame` 也跟着查错。
    obs = obs.model_copy(update={"step": before.step + 1})

    # 步骤 5：写这一键的观察账（`AFTER_ACTION`）——**账写在它的宿主里**：帧在本格产出，
    # 就挂在本格这条账上。登记 `deps.frame_event_ids` 供 `StepMemory` 的 before/after 与
    # "链尾帧读回"用（登记的步号 = 这一帧是第 `before.step + 1` 步的开局画面）。
    event_id = deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.AFTER_ACTION,
            episode_id=ep,
            step=before.step,
            status=obs.status,
            done=obs.done,
            frame_png=frame_png,
        )
    )
    if frame_png is not None:
        deps.frame_event_ids[(ep, before.step + 1)] = event_id

    return {"pending_observation": obs, "pending_stop": stop}
