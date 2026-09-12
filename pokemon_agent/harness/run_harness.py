"""`RunHarness`：一个 run 的主 agent 实现——大 LangGraph，episode 是它的子 agent。

拓扑（接口定死，见 `interfaces/harness/harness_port.py`）：

    begin ──→ plan ──→ dispatch ──→ episode ──→ reflect ──┬─(失败且重试未耗尽)─→ dispatch
                  ↑                                       │   （重试 = 再派发一次 episode）
                  │                                       └─(否则：弹出)─→ review
                  │                                                       │
                  └────── continue / retry / push ────────────────────────┤
                    (done / plan 连续失败)                                └─ stop → END
                                                                          → END

- `plan`     **LLM 决策器**：读 trace 历史 + 目标栈 → 渲染 `run_plan` prompt →
             调 LLM → 解析决策（压栈 ≤ `MAX_PLAN_PUSH` / 置 done）。连续
             `PLAN_MAX_ATTEMPTS` 次失败 → 置 `plan_failed` 路由到 review（机器
             没主意了，问人）。每次调用的账写 trace（`MODEL_CALL`，`Source.PLAN`——
             和 episode 内的决策是两条不同的模型链，不挂 `Source.HARNESS`：
             那本该是零成本的记账事件，混进一次真实模型调用会让"harness 花了
             多少 token"这个聚合数字失真）。
- `dispatch` **纯前置**（步 2 起）：生成 `episode_id`、栈顶派发计数 +1
             （`attempts[-1]`）、把父子交界的两个键（`task` / `episode_goals`）
             写进 state、把这一局的 run 级快照刷进 `deps.run_state_snapshot`。
             **它不再"调用子 agent"**——派发由 `episode` 那格做（`§0`：
             "`dispatch` 不再是'调一个对象的方法'，而是父图里的一个子图节点"）。
- `episode`  **派发这一局**：调子 agent（`EpisodeHarnessPort.run/episode.resume`），
             把 `outcome` 交回父 state 给 `reflect`。内置子图之后"单局异常不崩掉
             整个 run"的落点在 `episode_error_handler`（F4 的 `error_handler`，
             `AgentError` 包装成失败结算后 `goto="reflect"`）——不再是这里的
             `try/except`。
- `reflect`  看结算：**成功才弹栈**；失败且重试预算（`MAX_GOAL_RETRIES`）未耗尽
             → 栈顶保留、**直连 dispatch 重试（不经 review）**；预算耗尽 → 强制
             弹出（放弃该目标）、交人工。
- `review`   human-in-the-loop：目标被弹出后（成功或重试耗尽）或 plan 连续失败
             后调 `HumanReviewer`，人类决定继续（→ plan）/ 停止（→ END）/
             重试刚弹出的目标（→ plan）/ 压新目标（→ plan）。

**三条通道**：① 派发（dispatch → episode 节点 → 子 agent）；② Trace（同一个实例，
episode 写、run 读——plan 的思考依据）；③ Memory（共享实例，
run 级不直接查，跨局连续性由子 agent 的蒸馏/检索天然保证）。

**这个文件只放图控制**：六个节点方法该问哪个依赖、该走哪条边、该合并出什么
状态增量。图控制本身用到的纯计算（编辑指令怎么应用到目标栈、重试预算算
没算完、trace 里怎么挑出一局的完整记录）在 `run_utils.py`；"问规划模型"
这一根依赖会用到的重试循环、记账在 `run_plan_utils.py`；**预算换算**在
`run_recursion_limit()`（与 `episode/entry.py::episode_budget` 共用同一条公式，
D6）——跟 `episode_utils.py`/`game_utils.py`/`brain_utils.py`/`memory_query_utils.py`
是同一个原则在两层图上各自的落地。
"""

from __future__ import annotations

from typing import Any

from langgraph.errors import NodeError
from langgraph.types import Command

from pokemon_agent.brain import GoalForBrain, TaskForBrain
from pokemon_agent.errors import AgentError
from pokemon_agent.prompts import run_plan as run_plan_prompt
from pokemon_agent.schemas.frontend import FromFrontendToRunHarnessSubmitEditReq
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToCheckpointToolLoadReq,
    FromHarnessToCheckpointToolLoadResp,
    FromHarnessToReviewerReviewReq,
    FromHarnessToTraceToolAppendReq,
    FromHarnessToTraceToolReadDiskEventsReq,
    FromRunHarnessToEpisodeHarnessRunReq,
    FromRunHarnessToEpisodeHarnessRunResp,
    RunResp,
)
from pokemon_agent.tools.interface import BrainToolPort, CheckpointToolPort, TraceToolPort
from pokemon_agent.trace import Source, TraceKind

from . import run_plan_utils, run_utils, trace_write
from .auto_reviewer import AutoContinueReviewer
from .deps import HarnessDeps
from .episode import entry
from .interface import (
    MAX_GOAL_RETRIES,
    MAX_PLAN_PUSH,
    PLAN_MAX_ATTEMPTS,
    EpisodeHarnessPort,
    HumanDecision,
    HumanReviewer,
    ResumeEpisode,
    RunState,
)
from .run import compile_run_graph
from .run_data_center import RunDataCenter

RUN_NODES_PER_ROUND = 6
"""run 图**每一轮派发**烧掉的 superstep 数上界：

    plan → dispatch → episode → reflect

（`review` 不是每轮都跑；`begin` 与 `START` 是一次性的——那几个由
`RUN_RECURSION_MARGIN` 出。）

**它只数 run 自己的节点**：`episode` 那一格内部的步数由
`entry.episode_budget()` 单独算，两笔加起来才是总预算（见 `run_recursion_limit`）。
"子图步数计入父 limit"是 F5 的实测结论，节点里嵌套 invoke 也一样（探针 X1）。
"""

RUN_RECURSION_MARGIN = 60
"""图引擎自身开销 + `begin` / `START` / 收尾那些一次性节点的余量。"""


def run_recursion_limit(state: RunState) -> int:
    """run 图 + 它内部**所有** episode 的 superstep 总预算（D6 / F5 / 探针 X1）。

    三项之和：

      ① run 自己的节点：`RUN_NODES_PER_ROUND × 轮数`，轮数上界 = 栈长 ×(1+重试)；
      ② 每个 episode 的全部步数：`entry.episode_budget(task, 0)`，每个目标最多
         派发 `1 + MAX_GOAL_RETRIES` 次；
      ③ `plan` 压栈带来的新目标：**这一项没有真上界**——每轮最多压
         `MAX_PLAN_PUSH` 个，而新压的目标自己又要跑（几何级数）。所以这里按
         "每个新目标留一整份当前预算"给一次性的宽松余量，真守护交给
         `entry.close()` 的事后断言。这正是 D6 说的那件事：**把"靠 limit 兜底"
         换成"靠断言报警"**——撞 limit 是无声截断，断言会在开发期就地炸。

    **旧公式（`len(goals) * (MAX_GOAL_RETRIES + 1) * 4 + 60`）在 F5 之后是错的**：
    它只管 run 自己那几十个节点，而 episode 一局的内部步数就上万个 superstep
    ——两张图各 invoke 各的时它够用，拼成一张之后会当场撞限。
    """
    episodes = sum(entry.episode_budget(t, 0) for t in state.goals)
    own = len(state.goals) * (MAX_GOAL_RETRIES + 1) * RUN_NODES_PER_ROUND
    push_slack = MAX_PLAN_PUSH * (episodes + own)
    return own + episodes * (MAX_GOAL_RETRIES + 1) + push_slack + RUN_RECURSION_MARGIN


def _project_goals(goals: list[TaskForBrain]) -> list[GoalForBrain]:
    """把目标栈投影成子图要的形状（D2-②）。

    `goals`（`list[TaskForBrain]`）是**"目标栈"这个领域概念**，父侧不动；
    `episode_goals`（`list[GoalForBrain]`）是**同一次派发算出来的投影视图**——
    两者是不同的东西，所以是两个键。这一笔原先只发生在 `dispatch` 传参
    （`stack=state.goals`），现在**同时写进 state**：内置子图之后，子图的初值
    只能从父 state 的**同名键**来（F1/F8），而子侧的名字是 `episode_goals`。

    步 4 拆 `run/dispatch.py` 时本函数跟着 `dispatch` 走。
    """
    return [GoalForBrain(goal=t.goal, criteria=t.success_criteria) for t in goals]


def _exc_snapshot(exc: Exception) -> str:
    """异常的字符串快照——run_error 的 req 的 error 字段只吃文本，
    Exception 对象进不了 Pydantic req。
    """
    return f"{type(exc).__name__}: {exc}"


class RunHarness:
    """`HarnessPort` 的实现：完整一局游戏（run_id），目标栈驱动，episode 为子 agent。"""

    def __init__(
        self,
        episode: EpisodeHarnessPort,
        trace: TraceToolPort,
        brain_tool: BrainToolPort,
        reviewer: HumanReviewer | None = None,
        data_center: RunDataCenter | None = None,
        auto_push_goals: bool = True,
        auto_decide_done: bool = True,
        checkpoint: CheckpointToolPort | None = None,
        deps: HarnessDeps | None = None,
    ) -> None:
        """前置条件：`episode`/`trace`/`brain` 非空——缺了说明装配出 bug。

        注入子 agent、事件流（**同一个 trace 实例**：episode 写、这里读）、
        大脑（`plan_once` 问 run 级规划，通常跟 `episode` 内部持的是**同一个**
        `Brain` 实例——规划只是它的第四个技能，多一个 `plan_llm` provider，
        不是另一条依赖）与人类审查者（默认 `AutoContinueReviewer`）。

        `data_center`：前后端交互的统一中间层（goals 槽 + review 槽），缺省
        新建一个私有实例（没有前端接入时 goals 槽没人写、review 槽没人答，
        `AutoContinueReviewer` 照常自动放行）；
        API 层装配时传同一个实例给 `reviewer`（`DataCenterReviewer`）和这里，
        两边才是在读写同一份状态。

        `auto_push_goals`（缺省 `True`）：`False` 时 `plan()` 仍然照常问模型，
        但**丢弃 `resp.push_goals`**，不自动往栈里加目标——想要新目标进栈，
        走人工通道 `POST /runs/{id}/goals`（`apply_goals_edit`，这是唯一的人工
        加目标通道），不受这个开关影响，因为压栈逻辑本身在
        `run_utils.apply_goals_edit` 里独立于 `plan()`。

        `auto_decide_done`（缺省 `True`）：`False` 时 `plan()` 没有任何权力让
        整个 run 结束——`resp.done` 被忽略，**目标栈自然清空**（没有待办目标、
        这一轮也没压新的）也不由 `plan()` 直接判 `done` 收尾，而是路由去
        `review()`，把"要不要停"交给人（`STOP` 才真的结束；`CONTINUE` 时栈
        还是空的话会再绕回来问一次，不会平白卡死。没人应答超时按 `STOP` 处理
        ——沉默不等于"继续"，见 `run_data_center.py::DataCenterReviewer.
        review()`）。两个开关各自独立，可以只关一个；引入与演进的决策记录见
        `CHANGELOG.md` 2026-09-04/09-05 条目。
        """
        assert episode is not None, "RunHarness needs an episode harness"
        assert trace is not None, "RunHarness needs a trace"
        assert brain_tool is not None, "RunHarness needs a brain tool"
        self._episode = episode
        self._trace = trace
        self._brain_tool = brain_tool
        self._reviewer = reviewer or AutoContinueReviewer()
        self.data_center = data_center or RunDataCenter()
        self._auto_push_goals = auto_push_goals
        self._auto_decide_done = auto_decide_done
        self.deps = deps if deps is not None else episode.deps
        """**全图唯一的 context**（步 2 新增，D3/F10）——两侧必须共用**同一个对象**：
        `dispatch` 往 `deps.run_state_snapshot` 写、子图的 `save_checkpoint` 从同一份读；
        `run()` 还把它当 `invoke(context=…)` 的入参递给图。不传就取子 agent 那一份
        （它一定有一份），别在这里另建——那会造出两个各看各的真源，而且不报错。"""
        self._checkpoint = checkpoint
        """checkpoint 手（PLAN_checkpoint）；None = 不做 checkpoint，run 级锚点
        与 resume 不可用。"""
        """前后端交互的统一中间层——`api.py` 直接读写它（不经这个类的方法），
        这个类自己也只经它读写 goals/review 槽，双方不互相直接调对方的方法。"""
        self._graph = self._compile()

    # ---- 入口 ----

    def run(
        self, run_id: str, goals: list[TaskForBrain]
    ) -> tuple[list[FromRunHarnessToEpisodeHarnessRunResp], int, int, float]:
        """跑完一个 run：目标栈逐个解决（每层一个 episode），返回 run 级结算。

        返回 `(outcomes, total, succeeded, success_rate)` 四个裸值，不打包成对象——
        trace 里那条 RUN_END 内嵌的 `RunResp` 由 `_close()` 自己组装，跟返回值无关。

        `goals` 是初始目标栈，栈顶（最后一个）先解决；`plan` 每轮读历史决定
        压不压新目标；失败的目标由 reflect 在重试预算内自动重试，预算耗尽交
        人工。结算由 `reflect` 累积在 `outcomes`，这里组装汇总。

        后置条件：trace 里恰好多一条 RUN_START 和一条 RUN_END——异常路径也
        补齐 RUN_END（error 变体）后原样抛出，不吞（跟 `EpisodeHarness.run()`
        对 EPISODE_START/EPISODE_END 的处理是同一个模式）。
        """
        assert run_id, "run() got an empty run_id"
        assert goals, "run() got an empty goal stack"

        # 步骤 1：开局账——RUN_START（跟 EpisodeHarness.run() 的 episode_start
        # 是同一个理由：没有它，replay/统计分不出一个 run 从哪开始）。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.RUN_START,
                step=0,
                episode_id=run_id,
                run_goals=goals,
            )
        )

        state = RunState(run_id=run_id, goals=list(goals), attempts=[0] * len(goals))
        # `deps.run_id` 与这一局的 trace/截图路径同生同死：子侧的 `_run_id` 读的就是它。
        self.deps.run_id = run_id
        limit = run_recursion_limit(state)
        try:
            final = self._graph.invoke(state, {"recursion_limit": limit}, context=self.deps)
        except Exception as exc:
            # 步骤 2：异常路径——补 RUN_END（error 变体）再原样抛出，不吞。
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.RUN_ERROR,
                    episode_id=run_id,
                    step=0,
                    error=_exc_snapshot(exc),
                )
            )
            raise
        return self._close(final, run_id)

    def resume_run(
        self, run_id: str, episode_id: str, step: int
    ) -> tuple[list[FromRunHarnessToEpisodeHarnessRunResp], int, int, float]:
        """恢复入口：三元组 `(run_id, episode_id, step)` 定位（PLAN_checkpoint §4）。

        - step > 0：恢复到该局第 step 步开局，跑完本局后 run 图从 reflect 继续
          （START 条件边按 `resume_episode` 路由，dispatch 走 resume 分支）；
        - step = 0：本局从头重跑（等价于 episode 级恢复的 run 级包装）；
        - 废弃时间线（该步之后的事件/记忆/截图/未来局）由 episode 级
          `resume()` 内的 `void_after` 归档截断。

        前置条件：构造时注入了 checkpoint 工具；`(run_id, episode_id, step)` 三元组
        指定的那份 checkpoint 存在——它同时带 run 级与 episode 级两份状态
        （见 `checkpoint_tool.py` 落盘布局说明），这里只取 run 级的那份。

        run 级的 `checkpoint_restore` 标记事件在 `graph.invoke()` **之后**才
        append（顺序本身是契约的一部分，别挪到前面）——原因见方法体里那段注释。
        """
        assert self._checkpoint is not None, "resume_run() needs a checkpoint tool"
        anchor: FromHarnessToCheckpointToolLoadResp | None = self._checkpoint.load(
            FromHarnessToCheckpointToolLoadReq(run_id=run_id, episode_id=episode_id, step=step)
        )
        assert anchor is not None, f"no checkpoint for episode={episode_id!r} step={step}"
        state = RunState.model_validate(anchor.run_state_dump)
        assert state.run_id == run_id

        # DataCenter 单点重建：事件主前缀 + goals 槽对齐。
        self.data_center.rebuild(
            self._trace.read_disk_events(FromHarnessToTraceToolReadDiskEventsReq()).events,
            state.goals,
        )
        state = state.model_copy(
            update={"resume_episode": ResumeEpisode(episode_id=episode_id, step=step)}
        )
        self.deps.run_id = run_id
        limit = run_recursion_limit(state)
        try:
            final = self._graph.invoke(state, {"recursion_limit": limit}, context=self.deps)
        except Exception as exc:
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.RUN_ERROR,
                    episode_id=run_id,
                    step=0,
                    error=_exc_snapshot(exc),
                )
            )
            raise

        # run 级恢复标记**必须在 graph.invoke() 之后才 append**——这一局的
        # `episode.resume()` 内部会用同一个 cursor 调 `void_after()`，把磁盘上
        # 所有 `event_id > cursor` 的行（不分文件）都归档；这个标记事件本身
        # 的 id 必然 > cursor（它是 rebuild() 之后新分配的），如果在
        # `graph.invoke()` **之前**就写盘，会被这一局自己的 `void_after` 当场
        # 连带归档掉，在连续性判定里凭空留下一个洞（0909 实测踩到：
        # `restore_step` 的游标是 53，先写的这条标记恰好落在 id 54，
        # 结果自己被自己的 void_after 判定"> 53"而归档）。放到 `invoke()`
        # 之后写，此时该局的 void_after 已经跑完，不会再回头吃掉新事件。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.CHECKPOINT_RESTORE,
                step=0,
                episode_id=run_id,
                restored_episode_id=episode_id,
                restored_step=step,
                cursor=anchor.last_event_id,
            )
        )
        return self._close(final, run_id)

    def _close(
        self, final: dict[str, Any], run_id: str
    ) -> tuple[list[FromRunHarnessToEpisodeHarnessRunResp], int, int, float]:
        """收尾：组装结算并写 RUN_END（run/resume_run 共用）。

        结算对象只活在这个函数里：写进 RUN_END 事件，然后拆成四个裸值交出去。
        """
        final_state = RunState.model_validate(final)
        outcomes = final_state.outcomes
        succeeded = sum(1 for o in outcomes if o.success)
        result = RunResp(
            run_id=run_id,
            outcomes=outcomes,
            total=len(outcomes),
            succeeded=succeeded,
            success_rate=(succeeded / len(outcomes)) if outcomes else 0.0,
        )
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.RUN_END,
                step=0,
                episode_id=run_id,
                outcome_run=result,
            )
        )
        return result.outcomes, result.total, result.succeeded, result.success_rate

    # ---- 大图的五个节点（每个：(RunState) -> 状态增量）----

    def begin(self, state: RunState) -> dict[str, Any]:
        """初始栈已由 `run()` 构造进 state——这里只做校验。**图的入口。**"""
        assert state.goals, "begin() got an empty goal stack"
        assert len(state.attempts) == len(state.goals), "attempts must parallel goals"
        return {}

    def plan(self, state: RunState) -> dict[str, Any]:
        """**LLM 决策器**：读历史 + 目标栈 → 问规划模型 → 应用决策。

        决策三条路：
        - 压栈（`push_goals`，截断到 `MAX_PLAN_PUSH`）→ 追加 goals/attempts，继续
        - `done`（或栈空且不压）→ 置 done，run 结束
        - 连续 `PLAN_MAX_ATTEMPTS` 次调用/解析失败 → 置 `plan_failed`，路由 review

        每次调用的账（`MODEL_CALL`，`Source.PLAN`）**由本节点写**——重试循环在
        `run_plan_utils.ask_planner_with_retry`，它只交回每次尝试的原始材料
        （"账写在它的宿主里"，见 `PLAN_graph_readability.md` §3.7.4）。
        "每一步都产出 trace 事件"，run 级思考也不例外；mask 不读 MODEL_CALL，
        不会产生递归噪声。**不用 `Source.HARNESS`**：那是零成本记账事件的桶，
        `plan` 是一次真实模型调用，跟 episode 内的 `DECISION` 平级，该有自己的
        链路。三条非 `plan_failed` 的出口都额外补一条 `PLAN_VERDICT` 账
        （tool 按 kind 渲染）——账单只答"花了多少钱"，这条答"这一格给了什么结论"，
        复盘"planner 这次为什么压了这个目标"靠它。

        重试循环、prompt 拼装、解析、编辑应用都在 `run_plan_utils`/`run_utils`
        ——这里只决定"问完之后走哪条路"。

        **入栈顺序：`state.goals + pushes` 原序 append，栈顶 = `goals[-1]`**
        ——这是纯 LIFO：`push_goals` 列表里**最后**一项会变成新栈顶、最先被
        派发。不是"列表第一项优先级最高、最先执行"，而是"后压的先做"——
        列表本身就该按"先出现的先入栈（压得更深），后出现的后入栈（压在
        最上面、最先执行）"这个顺序给，模型自己要清楚这一点，harness 不该
        替它倒转顺序（顺序曾被反转过一次又纠正，事故记录见 `CHANGELOG.md`
        2026-09-04 条目）。这里只负责按 LIFO 老实 append。`review()` 的
        `PUSH` 分支是同一个约定，都按原序 append。`run_utils.apply_goals_edit`
        （`POST /runs/{id}/goals`）是整栈同步，不走按 `push` 分支单独 append。
        """
        # 先消费观测台的编辑指令（单槽，最新一条），再问 LLM——编辑后的
        # 目标栈要进本次决策的 prompt。栈顶锁定在 `run_utils.apply_goals_edit`
        # 内校验。快照**不在入口记录**：LLM 压栈发生在出口（state 合并前），
        # 入口快照会漏掉本轮的 push_goals——观测台将看不到 plan 自主拆的目标。
        # 这一步无论下面跳不跳模型调用都要做——人工编辑通道
        # （`POST /runs/{id}/goals`）不受这两个开关影响。
        edit = self.data_center.take_goals_edit()
        if edit is not None:
            run_utils.apply_goals_edit(state, edit)

        # 两个开关都关掉时**真的跳过这次调用**：`resp.push_goals` 会被强制
        # 清空、`resp.done` 不会被采信——不管
        # 模型这次说了什么，落到 state 里的效果都跟"没问"完全一样（对照下面
        # 走完整条链路时最后的兜底分支：`pushed=[]`、`done=False`）。既然
        # 结果注定被扔，这次真实调用（一整笔 token）就是纯浪费，直接跳过，
        # 图路由不变（走跟"问完但没压栈/没判 done"完全一样的返回形状，
        # `_compile()` 的条件边照旧看 `plan_failed`/`done`/`goals` 判走
        # dispatch 还是 review）。
        if not self._auto_push_goals and not self._auto_decide_done:
            self.data_center.publish_goals(state.goals)
            why = "auto_push_goals / auto_decide_done 均关闭，plan 跳过模型调用"
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PLAN_VERDICT,
                    step=0,
                    episode_id=state.run_id,
                    done=False,
                    pushed=[],
                    why=why,
                )
            )
            return {"plan_note": f"（{why}）", "plan_failed": False}

        events = self.data_center.events(run_plan_utils.RUN_TRACE_MASK)
        req = FromHarnessToBrainToolPlanOnceReq(
            run_id=state.run_id,
            goals=state.goals,
            events=events,
            max_push=MAX_PLAN_PUSH,
        )
        prompt = run_plan_prompt.build_prompt(req)
        req = req.model_copy(update={"prompt": prompt})

        resp, log = run_plan_utils.ask_planner_with_retry(self._brain_tool, req)
        # 步骤：把这次规划的每一次尝试落成账（失败的那几次也要——它们同样烧了
        # token）。run 级事件不挂在任何一局上，`episode_id` 位放 run_id、step 用 0。
        trace_write.append_model_calls(
            self._trace, episode_id=state.run_id, step=0, source=Source.PLAN, log=log
        )
        if resp is None:
            self.data_center.publish_goals(state.goals)
            note = f"plan 连续 {PLAN_MAX_ATTEMPTS} 次失败，交人工审查\n\n{prompt}"
            return {"plan_note": note, "plan_failed": True}

        # `auto_push_goals=False` 时强制清空——模型的 `push_goals` 照常问、
        # 照常解析（省事，`run_plan.md` 不用跟着改），只是这里不采纳。
        pushes = (
            run_plan_utils.to_tasks(resp.push_goals[:MAX_PLAN_PUSH], state.run_id)
            if self._auto_push_goals
            else []
        )
        # `auto_decide_done=False` 时同理：`resp.done` 不算数，栈空也不算数——
        # 两种情形都不在这里判 `done`，直接落到最后的"什么都不做"分支，
        # 交给 `run/graph.py` 的路由（`not s.goals` → `review`）去问人。
        # `auto_decide_done=True`（缺省）时：这两种情形都直接判
        # `done`，不经 `review()`。
        if self._auto_decide_done and (resp.done or (not state.goals and not pushes)):
            self.data_center.publish_goals(state.goals)
            why = resp.why or (
                "全部目标解决" if all(o.success for o in state.outcomes) else "存在重试耗尽的目标"
            )
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PLAN_VERDICT,
                    step=0,
                    episode_id=state.run_id,
                    done=True,
                    pushed=[],
                    why=why,
                )
            )
            return {"plan_note": prompt, "plan_failed": False, "done": True, "why": why}
        if pushes:
            new_goals = state.goals + pushes
            self.data_center.publish_goals(new_goals)
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PLAN_VERDICT,
                    step=0,
                    episode_id=state.run_id,
                    done=False,
                    pushed=[p.goal for p in pushes],
                    why=resp.why,
                )
            )
            return {
                "plan_note": prompt,
                "plan_failed": False,
                "goals": new_goals,
                "attempts": state.attempts + [0] * len(pushes),
            }
        self.data_center.publish_goals(state.goals)
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.PLAN_VERDICT,
                step=0,
                episode_id=state.run_id,
                done=False,
                pushed=[],
                why=resp.why,
            )
        )
        return {"plan_note": prompt, "plan_failed": False}

    def dispatch(self, state: RunState) -> dict[str, Any]:
        """**纯前置**（步 2）：备好这一局的标识与初值，派发本身归 `episode` 节点。

        它准备四样：

        - `episode_id`（`{run_id}-ep{序号}`，run 内唯一）；
        - 父子交界的两个键（D2-③ + v4 补注）：`task` = 栈顶那一层，
          `episode_goals` = **整个目标栈的投影**（子图判只判栈顶
          `episode_goals[-1]`，其余层是给大脑的全局视野）。父侧的 `goals`
          是"目标栈"这个领域概念，不动——两者是不同的东西，所以是两个键；
        - `attempts[-1] + 1`：栈顶派发计数；
        - `deps.run_state_snapshot`：这一局存档要搭车带的 run 级状态（D11-(3)）。
          写入点从"episode 方法入口"搬到这里——**每局都刷新**，多局时每一局的
          存档携带的都是**那一局派发时**的 run state，不会串。

        `resume_episode` **不在这里清**：它是"这一局从哪一步恢复"的记号，
        由 `episode` 节点读完才清（它得知道该走哪条路）。

        不在这里捕获 `AgentError`——那件事归 `episode_error_handler`（F4）。
        """
        assert state.goals, "dispatch() called with an empty goal stack"
        assert len(state.attempts) == len(state.goals), "attempts must parallel goals"
        top = state.goals[-1]
        episode_id = f"{state.run_id}-ep{len(state.outcomes) + 1}"
        if state.resume_episode is not None:
            assert state.resume_episode.episode_id == episode_id, (
                f"resume target mismatch: {state.resume_episode.episode_id} != {episode_id}"
            )

        # 存档里的 run 级状态**必须跟这一局一起落盘**（PLAN_checkpoint §3/§4 v5）：
        # 进程死在本局任何时刻，恢复时读那一步的 checkpoint 就能同时拿回两层状态。
        self.deps.run_state_snapshot = state.model_dump()
        return {
            "episode_id": episode_id,
            "task": top,
            "episode_goals": _project_goals(state.goals),
            "attempts": state.attempts[:-1] + [state.attempts[-1] + 1],
        }

    def episode(self, state: RunState) -> dict[str, Any]:
        """**派发这一局**：run 图里那格"接上 episode 子图"的地方（步 2 / D1-①）。

        两条路，都由 `episode/entry.py` 的图外入口编排（开局的 reset + 首帧感知、
        恢复的七步准备，都在图外）：

        - 普通派发 → `EpisodeHarnessPort.run`（`entry.run_new`：EPISODE_START →
          `begin_episode` → 进图 → 取结算）；
        - 恢复（`resume_episode` 非空）→ `EpisodeHarnessPort.resume`
          （`entry.run_resume`：`prepare_resume` 七步 → 进图 → 取结算）。

        返回的状态增量就是**父子交界那张键表**（D2）：`outcome` 交给 `reflect`；
        `resume_episode` 清空——这一局的恢复记号用掉了（重试时下一轮派发走普通路径）。
        `task`/`episode_goals` 已在 `dispatch` 里写过，这里不重复写（F1 的反作用：
        子图不输出的键，父侧保持旧值——所以也不需要"清空"它们）。

        **异常不在这里兜**：直挂的子图异常会一路冒穿到 `invoke()` 的调用方（F3），
        兜底是挂在同一格上的 `episode_error_handler`（F4）。
        """
        assert state.episode_id, "episode() without an episode_id"
        assert state.task is not None, "episode() without a task"

        if state.resume_episode is not None:
            outcome = self._episode.resume(
                state.episode_id,
                state.task,
                state.goals,
                state.resume_episode.step,
                run_state=self.deps.run_state_snapshot,
            )
            return {"outcome": outcome, "resume_episode": None}

        outcome = self._episode.run(
            FromRunHarnessToEpisodeHarnessRunReq(
                episode_id=state.episode_id,
                task=state.task,
                stack=state.goals,
                run_state=self.deps.run_state_snapshot,
            )
        )
        return {"outcome": outcome}

    def episode_error_handler(self, state: RunState, error: NodeError) -> Command:
        """**单局异常不崩掉整个 run** 的落点（F4 的 `error_handler`）。

        原先这段逻辑是 `dispatch` 里的 `except AgentError`；内置子图之后"父图调用
        那一格"没了，异常由 LangGraph 交给 handler。实测（F4）：handler 拿到的是
        **父 state**，返回 `Command(goto="reflect", update=…)` 时流程正常继续；
        只返回 dict 的话图会停在这一格（所以必须用 `Command`）。

        **只吞 `AgentError`**：那才是"单局失败"这一类预期内的失败（有名字、后面
        replay 要按失败类型归类统计）；别的异常仍然是 bug，原样抛出去——这条守的是
        `except AgentError` 时代的语义，不许趁机扩大吞错范围。
        """
        exc = error.error
        if not isinstance(exc, AgentError):
            raise exc
        assert state.episode_id, "episode_error_handler() without an episode_id"
        return Command(
            goto="reflect",
            update={
                "outcome": FromRunHarnessToEpisodeHarnessRunResp(
                    episode_id=state.episode_id,
                    success=False,
                    steps=0,
                    reason=f"error: {type(exc).__name__}",
                )
            },
        )

    def reflect(self, state: RunState) -> dict[str, Any]:
        """看结算：**成功才弹栈**；失败按重试预算分流（路由见 `_route_after_reflect`）。

        预算内失败 → 栈顶保留（goals/attempts 原样），直连 dispatch 重试；
        预算耗尽（已派发 `1 + MAX_GOAL_RETRIES` 次）→ 强制弹出、放弃该目标，
        交人工 review 处置。无论哪种，结算都累积进 `outcomes`。
        """
        assert state.outcome is not None, "reflect() without a fresh outcome"
        assert len(state.attempts) == len(state.goals), "attempts must parallel goals"
        outcomes = state.outcomes + [state.outcome]

        if state.outcome.success:
            return {
                "outcomes": outcomes,
                "goals": state.goals[:-1],
                "attempts": state.attempts[:-1],
            }

        if run_utils.goal_retries_exhausted(state.attempts[-1]):
            return {
                "outcomes": outcomes,
                "goals": state.goals[:-1],
                "attempts": state.attempts[:-1],
            }
        return {"outcomes": outcomes}

    def review(self, state: RunState) -> dict[str, Any]:
        """**human-in-the-loop**：目标被弹出后（成功或重试耗尽）或 plan 连续失败后，
        把结果交给人类。

        调 `HumanReviewer`，按决策路由：
        - `CONTINUE` → 回 plan（plan 连续失败时，这里是一次人工放行）
        - `STOP`     → 置 done，结束 run（→ END）
        - `RETRY`    → 刚弹出的目标压回栈顶（幂等：失败保留栈顶的情形它没被
                       弹出，重试 = 直连重派，这里无需动作）

        `PUSH` 决策已删——加/改/删目标统一走
        `POST /runs/{id}/goals`（`FromFrontendToRunHarnessSubmitEditReq`，整栈原子替换），跟"这一轮
        episode 怎么办"分开，用户确认"只保留 goal 的 push（整栈同步）和
        goals 的 read（独立的 `GET /runs/{id}/goals`），去掉 review 的 push"。
        """
        episode_trace = (
            run_utils.episode_trace_events(self.data_center.events(), state.episode_id)
            if state.episode_id
            else []
        )
        req = FromHarnessToReviewerReviewReq(
            run_id=state.run_id,
            outcomes=state.outcomes,
            goals=state.goals,
            last_task=state.task,
            episode_trace=episode_trace,
        )
        self.data_center.publish_review_request(req)
        resp = self._reviewer.review(req)
        self.data_center.clear_review()

        if resp.decision is HumanDecision.CONTINUE:
            return {}
        if resp.decision is HumanDecision.STOP:
            return {"done": True, "why": "human stopped"}
        if resp.decision is HumanDecision.RETRY:
            assert state.task is not None, "RETRY without a last task"
            if state.goals and state.goals[-1] == state.task:
                return {}
            return {
                "goals": state.goals + [state.task],
                "attempts": state.attempts + [0],
            }
        raise AssertionError(f"unknown human decision: {resp.decision!r}")

    # ---- 运行时观测/编辑（观测台用）----

    def latest_goals(self) -> list[TaskForBrain]:
        """最近一次 plan 的目标栈快照（栈顶 = 最后一个）；run 未开始过为空。

        快照在 plan 入口记录：栈只在 reflect（弹）/ plan（压）/ review（压）
        变化，重试轮（reflect→dispatch）栈不变，所以 plan 入口快照在重试期间
        依然准确；最多滞后一个"刚弹栈还没到下一轮 plan"的窗口。

        **薄委托**：goals 槽已经搬进 `self.data_center`（见构造函数），这两个
        方法留着只是不破坏调用方（`api.py`）现有的调用形状——真正的状态在
        `data_center` 那一侧，新代码应该直接读写 `self.data_center`。
        """
        return self.data_center.latest_goals()

    def submit_human_note(self, text: str) -> None:
        """薄委托：把人类实时插话转给 `self.data_center`（同一份实例也传给了
        `EpisodeHarness`，那边的 `think_action` 每步取一次）。API 层可以调
        这个方法，也可以直接写 `handle.data_center.submit_human_note(...)`——
        两者等价，跟 `submit_edit`/`self.data_center.submit_goals_edit` 是
        同一个薄委托模式。
        """
        self.data_center.submit_human_note(text)

    def submit_edit(self, edit: FromFrontendToRunHarnessSubmitEditReq) -> None:
        """收一条目标栈编辑指令进单槽（最新覆盖），plan 轮消费生效。

        `FromFrontendToRunHarnessSubmitEditReq`（只剩一种：整栈原子替换，不锁栈顶）
        在消费时才真正应用（`run_utils.apply_goals_edit`）。同上，薄委托
        给 `self.data_center`。
        """
        self.data_center.submit_goals_edit(edit)

    # ---- 路由与组装 ----

    # ---- 图组装 ----

    def _compile(self) -> Any:
        """把 6 个节点交给 `run/graph.py` 接起来（第 6 个是"只在出错时跑"的 handler）。

        **步 0 起"图长什么样"与"节点怎么实现"分居两个文件**：本方法只交出
        "节点名 → 节点函数"这张表；拓扑（`dispatch → episode → reflect`，
        含 `reflect` 出口的重试判据 `_should_retry`、`plan` 出口三路、
        `START` 的恢复分流，以及挂在 `episode` 那格上的 `error_handler`）
        全在 `run/graph.py`。
        """
        return compile_run_graph(
            {
                "begin": self.begin,
                "plan": self.plan,
                "dispatch": self.dispatch,
                "episode": self.episode,
                "episode_error_handler": self.episode_error_handler,
                "reflect": self.reflect,
                "review": self.review,
            }
        )
