"""`RunHarness`：一个 run 的主 agent 实现——大 LangGraph，episode 是它的子 agent。

拓扑（接口定死，见 `interfaces/harness/harness_port.py`）：

    begin ──→ plan ──→ dispatch ──→ reflect ──┬─(失败且重试未耗尽)─→ dispatch（直接重试）
                  ↑                           │
                  │                           └─(否则：弹出)─→ review
                  │                                            │
                  └────── continue / retry / push ─────────────┤
                    (done / plan 连续失败)                     └─ stop → END
                                                               → END

- `plan`     **LLM 决策器**：读 trace 历史 + 目标栈 → 渲染 `run_plan` prompt →
             调 LLM → 解析决策（压栈 ≤ `MAX_PLAN_PUSH` / 置 done）。连续
             `PLAN_MAX_ATTEMPTS` 次失败 → 置 `plan_failed` 路由到 review（机器
             没主意了，问人）。每次调用的账写 trace（`MODEL_CALL`，`Source.PLAN`——
             和 episode 内的决策是两条不同的模型链，不挂 `Source.HARNESS`：
             那本该是零成本的记账事件，混进一次真实模型调用会让"harness 花了
             多少 token"这个聚合数字失真）。
- `dispatch` 栈顶交给子 agent（`EpisodeHarnessPort.run(episode_id, 栈顶, 全栈)`），
             `AgentError` 捕获包装成失败结算——单局异常不崩掉整个 run；
             栈顶派发计数 +1（`attempts[-1]`）。
- `reflect`  看结算：**成功才弹栈**；失败且重试预算（`MAX_GOAL_RETRIES`）未耗尽
             → 栈顶保留、**直连 dispatch 重试（不经 review）**；预算耗尽 → 强制
             弹出（放弃该目标）、交人工。
- `review`   human-in-the-loop：目标被弹出后（成功或重试耗尽）或 plan 连续失败
             后调 `HumanReviewer`，人类决定继续（→ plan）/ 停止（→ END）/
             重试刚弹出的目标（→ plan）/ 压新目标（→ plan）。

**三条通道**：① 调用（dispatch → episode.run）；② Trace（同一个实例，
episode 写、run 读——plan 的思考依据）；③ Memory（共享实例，
run 级不直接查，跨局连续性由子 agent 的蒸馏/检索天然保证）。

**这个文件只放图控制**：五个节点方法该问哪个依赖、该走哪条边、该合并出什么
状态增量。图控制本身用到的纯计算（编辑指令怎么应用到目标栈、重试预算算
没算完、trace 里怎么挑出一局的完整记录）在 `run_utils.py`；"问规划模型"
这一根依赖会用到的重试循环、记账在 `run_plan_utils.py`——跟
`episode_utils.py`/`game_utils.py`/`brain_utils.py`/`memory_query_utils.py`
是同一个原则在两层图上各自的落地。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from pokemon_agent.brain import TaskForBrain
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
from pokemon_agent.tools import BrainToolPort, CheckpointToolPort, TraceToolPort
from pokemon_agent.trace import TraceKind

from . import run_plan_utils, run_utils
from .auto_reviewer import AutoContinueReviewer
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
from .run_data_center import RunDataCenter


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
        limit = len(goals) * (MAX_GOAL_RETRIES + 1) * 4 + 60
        try:
            final = self._graph.invoke(state, {"recursion_limit": limit})
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
        limit = len(state.goals) * (MAX_GOAL_RETRIES + 1) * 4 + 60
        try:
            final = self._graph.invoke(state, {"recursion_limit": limit})
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

        每次调用的账（`MODEL_CALL`，`Source.PLAN`）写 trace——"每一步都产出
        trace 事件"，run 级思考也不例外；mask 不读 MODEL_CALL，不会产生递归噪声。
        **不用 `Source.HARNESS`**：那是零成本记账事件的桶，`plan` 是一次真实
        模型调用，跟 episode 内的 `DECISION` 平级，该有自己的链路。三条非
        `plan_failed` 的出口都额外补一条 `PLAN_VERDICT` 账（tool 按 kind 渲染）
        ——账单只答"花了多少钱"，这条答"这一格给了什么结论"，复盘
        "planner 这次为什么压了这个目标"靠它。

        重试循环、记账、prompt 拼装、解析、编辑应用都在 `run_utils`——这里只
        决定"问完之后走哪条路"。

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

        resp, ok = run_plan_utils.ask_planner_with_retry(
            self._brain_tool, self._trace, state.run_id, req
        )
        if not ok:
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
        # 交给 `_compile()` 的路由（`not s.goals` → `review`）去问人。
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
        """栈顶交给子 agent，异常包装成失败结算，栈顶派发计数 +1。

        生成 `episode_id`（`{run_id}-ep{序号}`，run 内唯一）；把**整个目标栈**
        传给子 agent（它的 `goals` 投影 = 全栈，判只判栈顶）。`AgentError`
        捕获后包装成 `success=False` 的结算——单局异常不崩掉整个 run。
        """
        assert state.goals, "dispatch() called with an empty goal stack"
        assert len(state.attempts) == len(state.goals), "attempts must parallel goals"
        top = state.goals[-1]
        episode_id = f"{state.run_id}-ep{len(state.outcomes) + 1}"

        # run 级状态不再单独落盘：`state.model_dump()` 直接透传给 episode 层，
        # 由它在每一步的 checkpoint 里原样打包（PLAN_checkpoint §3/§4 v5 改法，
        # 见 `checkpoint_tool.py` 落盘布局说明）——进程死在本局任何时刻，
        # 恢复时读那一步的 checkpoint 就能同时拿回两层状态，不用再猜"该读
        # run 锚点还是 episode 锚点"。
        if state.resume_episode is not None:
            assert state.resume_episode.episode_id == episode_id, (
                f"resume target mismatch: {state.resume_episode.episode_id} != {episode_id}"
            )
            step = state.resume_episode.step
            try:
                outcome = self._episode.resume(
                    episode_id, top, state.goals, step, run_state=state.model_dump()
                )
            except AgentError as exc:
                outcome = FromRunHarnessToEpisodeHarnessRunResp(
                    episode_id=episode_id,
                    success=False,
                    steps=0,
                    reason=f"error: {type(exc).__name__}",
                )
            return {
                "episode_id": episode_id,
                "outcome": outcome,
                "last_task": top,
                "attempts": state.attempts[:-1] + [state.attempts[-1] + 1],
                "resume_episode": None,
            }

        try:
            outcome = self._episode.run(
                FromRunHarnessToEpisodeHarnessRunReq(
                    episode_id=episode_id,
                    task=top,
                    stack=state.goals,
                    run_state=state.model_dump(),
                )
            )
        except AgentError as exc:
            outcome = FromRunHarnessToEpisodeHarnessRunResp(
                episode_id=episode_id,
                success=False,
                steps=0,
                reason=f"error: {type(exc).__name__}",
            )

        return {
            "episode_id": episode_id,
            "outcome": outcome,
            "last_task": top,
            "attempts": state.attempts[:-1] + [state.attempts[-1] + 1],
        }

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
            last_task=state.last_task,
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
            assert state.last_task is not None, "RETRY without a last task"
            if state.goals and state.goals[-1] == state.last_task:
                return {}
            return {
                "goals": state.goals + [state.last_task],
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

    def _route_after_reflect(self, state: RunState) -> str:
        """reflect 的出口路由：失败且栈顶还是刚失败的那个目标 → 直连 dispatch
        重试（不经 review）；否则（成功弹出 / 重试耗尽弹出）→ review。

        用 `goals[-1] == last_task`（字段相等）判断"没弹"：相邻两层内容完全
        相同的目标会把"耗尽弹出"误判成"可重试"，多打一轮后仍会走到 review，
        代价可接受，不值得为它引入额外的路由字段。
        """
        if (
            state.outcome is not None
            and not state.outcome.success
            and state.goals
            and state.goals[-1] == state.last_task
        ):
            return "dispatch"
        return "review"

    # ---- 图组装 ----

    def _compile(self) -> Any:
        """把五个节点编译成 LangGraph：`begin → plan → dispatch ⇄ reflect`，
        `plan` 出口三路（dispatch / done→END / plan 连续失败→review），
        `reflect` 弹出后接 `review`（human-in-the-loop）。"""
        graph = StateGraph(RunState)
        graph.add_node("begin", self.begin)
        graph.add_node("plan", self.plan)
        graph.add_node("dispatch", self.dispatch)
        graph.add_node("reflect", self.reflect)
        graph.add_node("review", self.review)
        graph.add_conditional_edges(
            START,
            lambda state: "dispatch" if state.resume_episode is not None else "begin",
            {"begin": "begin", "dispatch": "dispatch"},
        )
        graph.add_edge("begin", "plan")
        graph.add_conditional_edges(
            "plan",
            lambda s: (
                "review"
                if s.plan_failed
                else END
                if s.done
                # 栈空到这里还没被判 done，只会是 `auto_decide_done=False`——
                # `dispatch` 断言非空栈，这种情形改路由去 `review` 问人（要不要
                # `PUSH` 新目标、还是 `STOP`），不会撞断言。
                else "review"
                if not s.goals
                else "dispatch"
            ),
            {"dispatch": "dispatch", "review": "review", END: END},
        )
        graph.add_edge("dispatch", "reflect")
        graph.add_conditional_edges(
            "reflect",
            self._route_after_reflect,
            {"dispatch": "dispatch", "review": "review"},
        )
        graph.add_conditional_edges(
            "review",
            lambda s: END if s.done else "plan",
            {"plan": "plan", END: END},
        )
        return graph.compile()
