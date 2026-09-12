"""`HarnessPort`：**一个 run 的主 agent**——完整的一局 Pokemon 游戏，episode 是它的子 agent。

    HarnessPort（主，一 run = 完整一局游戏）      → 管目标栈、调度、汇总
        └── 反复调 EpisodeHarnessPort（子，一 episode）→ 解决栈顶一个目标

**目标栈模型**：run 维护游戏级目标栈，`episode` 只解决栈顶；弹栈/压栈是
主 agent 的职责（`reflect`/`plan`），不是子 agent 的。

**接口即图**：五个节点方法就是大图的节点，拓扑写在模块 docstring 里——

    begin ──→ plan ──→ dispatch ──→ reflect ──┬─(失败且重试未耗尽)─→ dispatch（直接重试）
                  ↑                           │
                  │                           └─(否则：弹出)─→ review
                  │                                            │
                  └────── continue / retry / push ─────────────┤
                    (栈空且无新目标 → done)                     └─ stop → END
                                                               → END

- `begin`    初始目标栈入 state（纯校验）
- `plan`     **LLM 决策器**：读 trace 历史 + 目标栈 → 组装 `run_plan` prompt →
             调 LLM → 解析决策（压栈 ≤ `MAX_PLAN_PUSH` 个 / 置 `done` 结束）；
             连续 `PLAN_MAX_ATTEMPTS` 次失败 → 置 `plan_failed` 路由到 review
- `dispatch` 栈顶交给子 agent（`EpisodeHarnessPort.run`），异常包装成失败结算；
             栈顶派发计数 +1（`attempts[-1]`）
- `reflect`  看结算：**成功才弹栈**；失败且重试预算（`MAX_GOAL_RETRIES`）未耗尽
             → 栈顶保留、直连 `dispatch` 重试（**不经 review**）；预算耗尽 → 强制
             弹出（放弃该目标）、交人工。弹栈与不弹都累积 `outcomes`
- `review`   **human-in-the-loop**：目标被弹出后（成功或重试耗尽）或 plan 连续
             失败后，人类审查并决定继续（`plan`）/ 停止（`END`）/ 重试刚弹出的
             目标（`plan`）/ 压新目标（`plan`）

**三条通道**：① 显式调用（dispatch → episode.run）；② Trace（episode 写事件、
run 按类型 mask 读——plan 的思考依据）；③ Memory（共享实例，跨 episode 连续性）。

原来放在顶层 `pokemon_agent/interfaces/harness/`；跟着"协议物理挨着它自己的实现"这条原则搬到了这里，`pokemon_agent/interfaces/`
这个集中注册表这次整个撤销，消费方直接
`from pokemon_agent.harness import HarnessPort, RunState`。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pokemon_agent.brain import TaskForBrain

# `ResumeEpisode` 只在这里 re-export（旧 import 路径不破），RunState 被 Protocol 签名用。
from pokemon_agent.harness.run.state import ResumeEpisode, RunState  # noqa: F401
from pokemon_agent.schemas.harness import FromRunHarnessToEpisodeHarnessRunResp

MAX_GOAL_RETRIES = 2
"""同一个目标最多自动重试几次（不含首次派发）——即最多被派发
`1 + MAX_GOAL_RETRIES` 次。耗尽后 `reflect` 强制弹出该目标、交人工处置；
没有这条硬上限，"失败保留栈顶 + 自动继续的 reviewer"就是一个死循环。"""

MAX_PLAN_PUSH = 5
"""`plan` 一次最多压几个新目标——LLM 决策器的硬上限，解析后截断。
没有它，一次读歪了的历史能让栈瞬间膨胀。"""

PLAN_MAX_ATTEMPTS = 3
"""`plan` 的 LLM 调用/解析最多试几次。连续失败说明规划器当前不可用——
机器没主意了，置 `plan_failed` 路由到 review 交人工，而不是崩掉整个 run。"""


@runtime_checkable
class HarnessPort(Protocol):
    """**一个 run 的主 agent**：完整一局游戏，episode 是它的子 agent。

    接口即图：五个节点方法（`begin`/`plan`/`dispatch`/`reflect`/`review`）就是
    大图的五个节点，拓扑见模块 docstring。实现方把这份契约翻译成自己的图引擎
    （LangGraph），但图有哪些节点、什么形状，由接口定死。
    """

    # ---- 顶层入口 ----

    def run(
        self, run_id: str, goals: list[TaskForBrain]
    ) -> tuple[list[FromRunHarnessToEpisodeHarnessRunResp], int, int, float]:
        """跑完一个 run：按目标栈逐个解决（每层一个 episode），返回 run 级结算。

        run_id：这次 run 的标识（完整一局游戏会话）。
        goals：初始目标栈，栈顶（最后一个）先解决；之后由主 agent 自主压栈。
        返回：`(outcomes, total, succeeded, success_rate)` 四个裸值——每个 episode
            的结算（按执行顺序）、跑了几局、成了几局、成功率。**不打包成对象**：
            外壳边不立契约，要 JSON 的调用方自己拼。
        前置条件：run_id 非空、goals 非空。
        后置条件：`outcomes` 与 trace 里各局的 EPISODE_START/END 对同一 run
            给出同一份结论。
        """
        ...

    # ---- 大图的五个节点（每个：(RunState) -> 状态增量）----

    def begin(self, state: RunState) -> dict[str, Any]:
        """初始目标栈入 state。**图的入口。**"""
        ...

    def plan(self, state: RunState) -> dict[str, Any]:
        """读 trace 历史 + 目标栈 → 组装 `plan_note`；栈空且无新目标 → 置 done。
        每次压栈不得超过 `MAX_PLAN_PUSH` 个（静态版不压栈）。"""
        ...

    def dispatch(self, state: RunState) -> dict[str, Any]:
        """栈顶交给子 agent（`EpisodeHarnessPort.run(episode_id, 栈顶, 全栈)`），
        异常包装成失败结算，栈顶派发计数 +1。**唯一推进世界（调子 agent）的节点。**"""
        ...

    def reflect(self, state: RunState) -> dict[str, Any]:
        """看结算：成功弹栈；失败且重试预算未耗尽 → 栈顶保留（路由回 dispatch
        直接重试）；预算耗尽 → 强制弹出交人工。无论哪种都累积 `outcomes`。"""
        ...

    def review(self, state: RunState) -> dict[str, Any]:
        """**human-in-the-loop**：目标被弹出后，把结果交给人类（`HumanReviewer`），
        按决策继续 / 停止 / 重试刚弹出的目标 / 压新目标。"""
        ...
