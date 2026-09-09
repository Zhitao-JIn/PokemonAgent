"""EpisodeHarness —— **控制一局怎么跑**：一张 LangGraph 状态图，加上它的记账。

    look → judge ──(done?)──→ retrieve_verify_step_memory
                                 ├─(无 step 记忆)──────────→ END
                                 └─(有 step 记忆)→ retrieve_verify_knowledge
                                                    → verify_and_summarize → END
      └─(否)→ get_action_space
        → retrieve_step_episode_memory → retrieve_global_episode_memory
          → retrieve_knowledge_semantic_memory → retrieve_object_semantic_memory
        → enrich_observation
        → think_action → act → look_after_action
        → detect_stall → advance_step → store_step_episode_memory → store_object_semantic_memory
        → look                              （回到 run() 写 EPISODE_END）

    四个 retrieve_* 各自独立（互不依赖彼此输出，都只读 observation），写进
    四个不同字段；enrich_observation 只做合并，不查库。收尾分支的
    retrieve_verify_step_memory/retrieve_verify_knowledge 是同一个模式在收尾
    路径的落地——检索单独成节点、结果单独落一个 state 字段，
    `verify_and_summarize` 本身不兼职查库（level 要跟主循环的 retrieve_* 一致）。

- `EpisodeRunState` 持有"这一局跑到哪了"；`EpisodeHarness` 自己没有任何字段，
  只做生死判断与记账；图只管循环调度与状态传递。
- 只有 `EpisodeHarness` 调 `trace.append()`，payload 由 `tools/trace_render.py` 的
  纯函数组装，这里只决定"该不该记、记成哪个 `EventType`"。
- `act` 是唯一推进世界的节点；收尾（`EPISODE_END`）在 `run()`，不在图里。
- **每个节点只改状态里的一处**（一个字段，或紧密绑在一起的一小组——比如
  `stall_key`/`stall_count` 是同一个判定的两个输出）；停摆强制终止的判断
  归 `look` 之后的 `judge`（它本来就管"这一局该不该停"）。
"""

from __future__ import annotations

import base64
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.harness.episode_utils import permission_was_denied
from pokemon_agent.interfaces import (
    BrainToolPort,
    CheckpointToolPort,
    EpisodeRunState,
    GameToolPort,
    MemoryToolPort,
    TraceToolPort,
)
from pokemon_agent.prompts import decide_action as decide_action_prompt
from pokemon_agent.prompts import judge_success as judge_success_prompt
from pokemon_agent.prompts import verify_and_summarize as verify_and_summarize_prompt
from pokemon_agent.prompts.object_render import render_object_events
from pokemon_agent.schemas.communication import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToBrainToolReflectReq,
    FromHarnessToBrainToolVerifyAndSummarizeReq,
    FromHarnessToBrainToolVerifyAndSummarizeResp,
    FromHarnessToCheckpointToolSaveReq,
    FromHarnessToMemoryToolQueryKnowledgeReq,
    FromHarnessToMemoryToolQueryKnowledgeResp,
    FromHarnessToTraceToolAppendReq,
    HarnessEpisodeOutcomeResp,
    StepVerifyVerdict,
    TraceKind,
)
from pokemon_agent.schemas.datastore import Source, dedup_snapshots
from pokemon_agent.schemas.domain import GoalForBrain, ModelCall, TaskForHarness
from pokemon_agent.trace import read_screenshot, screenshot_filename

from . import brain_utils, episode_utils, game_utils, memory_query_utils
from .object_interactions import object_fact_events
from .run_data_center import RunDataCenter


def _exc_snapshot(exc: Exception) -> str:
    """异常的字符串快照——`episode_error`/`run_error` 的 req 的 error 字段
    只吃文本，Exception 对象进不了 Pydantic req。
    """
    return f"{type(exc).__name__}: {exc}"


MEMORY_RECALL_LIMIT = 5
"""每次决策检索几条情景记忆。"""

EPISODE_MEMORY_RECALL_LIMIT = 3
"""每次决策检索几条跨局摘要记忆。"""

JUDGE_HISTORY = 2
"""判定器能看到本局最近几步（`render(reason=False)`，不含决策者的主张）。

窗口大小的取舍（含已知风险）记录在 `CHANGELOG.md` 2026-09-05 条目。"""

STALL_LIMIT = 5
"""L2 护栏：连续多少步"动作与画面机械状态都没有变化"就强制结束本局。

阈值取 5（与 run 级 `MAX_PLAN_PUSH` 同为 5）：一两次重复可能是模型没看清，
连续五次原地打转才断定它陷入循环。它上面还有更硬的一层——run 级
`MAX_GOAL_RETRIES`，本局结束不是终点。"""


class EpisodeHarness:
    """一局的控制器。**它自己没有状态**——状态全在 `EpisodeRunState` 里流。"""

    def __init__(
        self,
        game: GameToolPort,
        memory: MemoryToolPort,
        brain_tool: BrainToolPort,
        trace: TraceToolPort,
        run_id: str = "local",
        data_center: RunDataCenter | None = None,
        checkpoint: CheckpointToolPort | None = None,
    ) -> None:
        """接好四个端口，编译好状态图，此后不再变。

        `checkpoint`：checkpoint 手（PLAN_checkpoint §2）。`None` = 不做
        checkpoint（测试、单局直跑），`save_checkpoint` 节点空转。
        """
        self._game = game
        self._memory = memory
        """情景记忆 + 语义记忆（object）都走这一个端口。"""
        self._brain_tool = brain_tool
        self._trace = trace
        """记账 req 由这里组装，payload 渲染与落盘都在 `TraceTool`。"""
        self._run_id = run_id
        self._data_center = data_center
        """人类实时插话的来源（`RunDataCenter` 的 human_note 槽）。
        `None` = 没接前端（测试、CLI），`think_action` 每步照常跑，只是永远
        取不到插话——跟 `reviewer`/`data_center` 在 `RunHarness` 里"不传就是
        没有真人"的兜底是同一个约定。**只读它的 human_note 槽**，不碰
        goals/review 两个槽——那两个是 run 级的事，不归 episode 管。"""
        """蒸馏摘要时标在 `EpisodeMemory.run_id` 上的 run_id。"""
        self._world_reset_done = False
        """世界起点存档只读一次——run 启动后第一个 episode 的 `_begin` 读，
        之后的 episode **接着上一局结束的状态继续跑**，episode 之间保持
        世界连续性（取舍见 `CHANGELOG.md` 2026-09-03 条目）。"""
        self._checkpoint = checkpoint
        """checkpoint 手；`None` = 不做 checkpoint，`save_checkpoint` 节点空转。"""
        self._run_state_dump: dict[str, Any] | None = None
        """当前正在跑的这一局对应的 `RunState.model_dump()`——`run()`/`resume()`
        入口处赋值，`save_checkpoint()` 节点原样打包进每一步的存档，本层不解读
        （纯透传，见 `checkpoint_tool.py` 落盘布局说明）。"""
        self._graph = self._compile()

    def _frame_b64(self, episode_id: str, step: int) -> str | None:
        """读第 `step` 步对应的便利截图、编成 base64，读不到就是 `None`。

        `StepMemory.before_frame`/`after_frame` 已直接存 base64（见该字段文档），
        只有 `store_step_episode_memory()` 反思成一条记忆的这一刻才需要现读现编
        （把 `before`/`after` 两帧编进去）；`judge()` 的图完全来自 history 里
        已经存好的截图，不走这里。
        """
        raw = read_screenshot(self._run_id, screenshot_filename(self._run_id, episode_id, step))
        return base64.b64encode(raw).decode() if raw is not None else None

    # ---- 对外只有这一个入口 ----

    # 注意：这里**不带** `@initialize`。生产路径下这个方法只会被
    # `RunHarness.dispatch()` 调用（见 `run_harness.py`），`@initialize` 挂在
    # 那一层的 `RunHarness.run()`/`resume_run()` 上——它们的图入口 `plan` 节点
    # 在第一次 `dispatch` 之前就要调用受权限守卫的 `Brain.plan_once`，权限运行时
    # 必须在那时已经初始化，等不到这里。这里若也挂 `@initialize` 会在
    # `dispatch → episode.run()` 处形成嵌套调用，被 `agent_permission` 的
    # 嵌套检查直接断言失败（`runtime.py` 明写不允许静默容忍）。独立于
    # `RunHarness` 单跑这个方法（如集成测试的"episode 级"场景）时，调用方
    # 自己在调用点包一层 `@initialize`。
    def run(
        self,
        episode_id: str,
        task: TaskForHarness,
        stack: list[TaskForHarness],
        run_state: dict[str, Any],
    ) -> HarnessEpisodeOutcomeResp:
        """跑完一局：解决栈顶这一个目标。

        前置条件：episode_id 非空、task.max_steps > 0、stack 非空且栈顶 == task。
        后置条件：trace 里恰好多一条 EPISODE_START 和一条 EPISODE_END。

        `stack` 是整个目标栈（全局信息）——投影成 `goals`（判只判栈顶，
        `goals[-1]` = task.goal），其余层是给大脑的全局视野。`run_state` 是
        `RunHarness.dispatch()` 派发这一局时的 `RunState.model_dump()`——本层
        不解读，只存起来供 `save_checkpoint()` 原样打包进每一步的存档（run
        级状态跟 episode 级状态从此共存一份文件，见 `checkpoint_tool.py`）。

        开局、跑图、收尾三段，异常路径也补齐 EPISODE_END 后原样抛出。
        """
        assert episode_id, "run() got an empty episode_id"
        assert task.max_steps > 0, f"max_steps must be > 0, got {task.max_steps}"
        assert stack and stack[-1].task_id == task.task_id, (
            "run() needs a non-empty stack whose top is the task being run"
        )
        self._run_state_dump = run_state

        # 步骤 1：开局，跑图直到终止。
        # `recursion_limit` = 17 × max_steps + 20：continue 分支一步要走 16 个
        # 节点（save_checkpoint 加入后，余量 1），`+20` 盖掉收尾分支（最多
        # 4 个节点）与图引擎开销。
        # **这个数字必须跟着 `_compile()` 的节点数一起改**，否则会在步数没走完
        # 时被 LangGraph 的 `GraphRecursionError` 无声打断（论证见 `CHANGELOG.md`
        # 2026-09-05 条目）。
        try:
            state = self._begin(episode_id, task, stack)
            final = self._invoke(state, task)
        except Exception as exc:
            # 步骤 2：异常路径——补 EPISODE_END（error 变体）再原样抛出。
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.EPISODE_ERROR,
                    episode_id=episode_id,
                    step=0,
                    error=_exc_snapshot(exc),
                )
            )
            raise

        return self._close(final, episode_id, task)

    def resume(
        self,
        episode_id: str,
        task: TaskForHarness,
        stack: list[TaskForHarness],
        step: int,
        run_state: dict[str, Any],
    ) -> HarnessEpisodeOutcomeResp:
        """从本局第 `step` 步开局的 checkpoint 恢复并跑完（PLAN_checkpoint §5，step 级入口）。

        前置条件：构造时注入了 checkpoint 工具；`(episode_id, step)` 的存档成对存在。
        恢复语义：世界快照回载 + 状态快照重建（记忆由各 store 落盘读回），
        **不重调视觉模型、不重跑已完成节点**；废弃时间线（step 之后的事件/记忆/
        截图）在进图前由 `void_after` 归档截断。`run_state` 同 `run()`——纯透传，
        供后续每一步的 `save_checkpoint()` 使用。
        """
        assert self._checkpoint is not None, "resume() needs a checkpoint tool"
        self._run_state_dump = run_state
        # 步骤 1：取存档（签名/成对校验在 tool 内）。
        checkpoint = self._checkpoint.load(self._run_id, episode_id, step)
        assert checkpoint is not None, f"no checkpoint for ({episode_id}, {step})"
        # 步骤 2：废弃处理（对账游标 = checkpoint 的 last_event_id）。
        self._checkpoint.void_after(self._run_id, episode_id, step, checkpoint.last_event_id)
        # 步骤 3：世界快照回载——唯一不可从事件重建的东西。`load_state_bytes()`
        # 只回载模拟器字节，不认得 `_task`/`_closed`（纯 Python 记账，不进存档）；
        # 不补 `set_task()` 的话，本局自己靠 `pending_observation` 收尾没事，
        # 但本 run 后续再派发新 episode 时（同一个长命 world，`_world_reset_done`
        # 已是 True、不会走 `reset()`）会在 `perceive_once()`/`step()` 撞上
        # "before reset()" 断言——这是 check_restore.py 端到端跑出来的真故障。
        self._game.load_state_bytes(checkpoint.emulator_state)
        self._game.set_task(task)
        self._world_reset_done = True
        # 步骤 4：状态重建（记忆层由各 store 构造时从落盘读回，无需重建）。
        state = EpisodeRunState.model_validate(checkpoint.state_dump)
        assert state.episode_id == episode_id and state.task == task
        # 步骤 5：落恢复事件（replay/统计的接缝标记）。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.CHECKPOINT_RESTORE,
                episode_id=episode_id,
                step=state.step,
                restored_episode_id=checkpoint.episode_id,
                restored_step=checkpoint.step,
                cursor=checkpoint.last_event_id,
            )
        )
        # 步骤 6：进图（save_checkpoint 幂等重写本号存档后进 look）。
        try:
            final = self._invoke(state, task)
        except Exception as exc:
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.EPISODE_ERROR,
                    episode_id=episode_id,
                    step=0,
                    error=_exc_snapshot(exc),
                )
            )
            raise
        return self._close(final, episode_id, task)

    def _invoke(self, state: EpisodeRunState, task: TaskForHarness) -> dict[str, Any]:
        """跑图直到终止。`recursion_limit` 按剩余步数换算（新跑/恢复同一条公式）。"""
        return self._graph.invoke(
            state, {"recursion_limit": (task.max_steps - state.step) * 17 + 20}
        )

    def _close(
        self, final: dict[str, Any], episode_id: str, task: TaskForHarness
    ) -> HarnessEpisodeOutcomeResp:
        """收尾：outcome 与 EPISODE_END 从同一份 final_state 派生（run/resume 共用）。

        `done`/`success` 是 `EpisodeRunState` 自己的字段（`judge` 产出）；
        `obs.step` 仍读观测（`step` 是画面维度的坐标）。
        """
        final_state = EpisodeRunState.model_validate(final)
        obs = final_state.observation
        reason = episode_utils.derive_episode_reason(
            final_state.success,
            obs.step,
            task.max_steps,
            stalled=final_state.stall_count >= STALL_LIMIT,
        )
        outcome = HarnessEpisodeOutcomeResp(
            episode_id=episode_id,
            success=final_state.success,
            steps=obs.step,
            reason=reason,
        )
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.EPISODE_END,
                step=outcome.steps,
                episode_id=episode_id,
                outcome_episode=outcome,
            )
        )
        return outcome

    def save_checkpoint(self, state: EpisodeRunState) -> dict[str, Any]:
        """图边界节点：每圈边界（含 step0）写一份 checkpoint（PLAN_checkpoint §2）。

        **只写存档，不改状态**——返回空增量。三件套：模拟器世界快照 +
        `EpisodeRunState` dump + trace 游标。checkpoint 工具未注入（测试/单局
        直跑）时空转；存档失败若因权限被拒，记 PERMISSION_SKIPPED 后继续跑
        （跟 store 系节点同一兜底），其余异常原样上抛。
        """
        if self._checkpoint is None:
            return {}
        try:
            self._checkpoint.save(
                FromHarnessToCheckpointToolSaveReq(
                    run_id=self._run_id,
                    episode_id=state.episode_id,
                    step=state.step,
                    state_dump=state.model_dump(),
                    run_state_dump=self._run_state_dump,
                    last_event_id=self._trace.cursor(),
                    emulator_state=self._game.save_state_bytes(),
                )
            )
        except Exception as exc:
            if not permission_was_denied(exc):
                raise
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PERMISSION_SKIPPED,
                    episode_id=state.episode_id,
                    step=state.step,
                    permission="execute:game:save_state",
                    function="CheckpointTool.save",
                    fallback="skip save_checkpoint",
                    source=Source.HARNESS,
                )
            )
        return {}

    def _begin(
        self, episode_id: str, task: TaskForHarness, stack: list[TaskForHarness]
    ) -> EpisodeRunState:
        """开一局：写 EPISODE_START、reset 世界、存起点存档、感知第一帧，返回初始状态。

        `stack` 是整个目标栈（run 级投影）：`goals` = 全栈投影，**判只判栈顶**
        （`goals[-1]` = task.goal），其余层是给大脑的全局信息。

        `memory_carried`（跨局摘要池大小）必须在 `reset()` 之前取——契约上它
        描述的是「开局那一刻」，晚取容易被悄悄改成「reset 之后」。
        """
        # 步骤 1：开局账——EPISODE_START。
        memory_carried = self._memory.episode_summary_count
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.EPISODE_START,
                step=0,
                episode_id=episode_id,
                task=task,
                memory_carried=memory_carried,
            )
        )

        # 步骤 2：世界起点只在 run 的第一个 episode 读一次；后续 episode
        # **不重置**，接着上一局结束的状态继续跑（取舍见 `CHANGELOG.md`
        # 2026-09-03 条目）。局起点不再另存快照——终止判定全在 `judge`
        # 出口，退出前最后一圈入口的 checkpoint（`save_checkpoint`）就是
        # 本局的终止画面，也是下一局的起点画面；ep1 起点 = `reset()`
        # 加载的 ROM 存档，同样可复现。
        if not self._world_reset_done:
            self._game.reset(task)
            self._world_reset_done = True

        # 步骤 3：感知第一帧（重试循环在 `game_utils.perceive_with_retry`；
        # 原始画面随该函数内部的感知 MODEL_CALL 事件落盘）。
        obs = game_utils.perceive_with_retry(self._game, self._trace, episode_id, step=0)
        assert not obs.done, "reset() must return a fresh observation"

        # 步骤 4：组装初始状态。
        return EpisodeRunState(
            episode_id=episode_id,
            task=task,
            goals=[GoalForBrain(goal=t.goal, criteria=t.success_criteria) for t in stack],
            pending_observation=obs,
        )

    # ---- 图 ----

    def _compile(self) -> CompiledStateGraph:
        """装配状态图：注册十八个节点与它们之间的边，返回编译好的图。

        `save_checkpoint` 是图入口、也是循环边界（store_object 之后回它）——
        每一圈边界（含 step0）都在同一节点写 checkpoint（PLAN_checkpoint §2）。

        终止分支在 `judge` 出口——四类终止来源（世界结束/步数用尽/停摆/目标
        达成）全在 `judge` 一格里判完，`look` 只盖步号，不掺和"该不该停"。

        四个 `retrieve_*` 节点按边排成一条直线（图引擎要求边有先后），但彼此
        没有数据依赖——都只读 `observation`，各写各的字段，顺序是图形状要求
        的，不是因果依赖。
        """
        # 步骤 1：注册十八个节点。
        graph = StateGraph(EpisodeRunState)
        graph.add_node("save_checkpoint", self.save_checkpoint)
        graph.add_node("look", self.look)
        graph.add_node("judge", self.judge)
        graph.add_node("get_action_space", self.get_action_space)
        graph.add_node("retrieve_step_episode_memory", self.retrieve_step_episode_memory)
        graph.add_node("retrieve_global_episode_memory", self.retrieve_global_episode_memory)
        graph.add_node(
            "retrieve_knowledge_semantic_memory", self.retrieve_knowledge_semantic_memory
        )
        graph.add_node("retrieve_object_semantic_memory", self.retrieve_object_semantic_memory)
        graph.add_node("enrich_observation", self.enrich_observation)
        graph.add_node("think_action", self.think_action)
        graph.add_node("act", self.act)
        graph.add_node("look_after_action", self.look_after_action)
        graph.add_node("detect_stall", self.detect_stall)
        graph.add_node("advance_step", self.advance_step)
        graph.add_node("store_step_episode_memory", self.store_step_episode_memory)
        graph.add_node("store_object_semantic_memory", self.store_object_semantic_memory)
        graph.add_node("retrieve_verify_step_memory", self.retrieve_verify_step_memory)
        graph.add_node("retrieve_verify_knowledge", self.retrieve_verify_knowledge)
        graph.add_node("verify_and_summarize", self.verify_and_summarize)

        # 步骤 2：接边——judge 出口按 done 分叉，其余是直线。
        graph.set_entry_point("save_checkpoint")
        graph.add_edge("save_checkpoint", "look")
        graph.add_edge("look", "judge")
        graph.add_conditional_edges(
            "judge",
            lambda state: "retrieve_verify_step_memory" if state.done else "get_action_space",
            {
                "get_action_space": "get_action_space",
                "retrieve_verify_step_memory": "retrieve_verify_step_memory",
            },
        )
        graph.add_edge("get_action_space", "retrieve_step_episode_memory")
        graph.add_edge("retrieve_step_episode_memory", "retrieve_global_episode_memory")
        graph.add_edge("retrieve_global_episode_memory", "retrieve_knowledge_semantic_memory")
        graph.add_edge("retrieve_knowledge_semantic_memory", "retrieve_object_semantic_memory")
        graph.add_edge("retrieve_object_semantic_memory", "enrich_observation")
        graph.add_edge("enrich_observation", "think_action")
        graph.add_edge("think_action", "act")
        graph.add_edge("act", "look_after_action")
        graph.add_edge("look_after_action", "detect_stall")
        graph.add_edge("detect_stall", "advance_step")
        graph.add_edge("advance_step", "store_step_episode_memory")
        graph.add_edge("store_step_episode_memory", "store_object_semantic_memory")
        graph.add_edge("store_object_semantic_memory", "save_checkpoint")
        # 收尾分支：没有 step 记忆（entries 为空）时直接 END——没有东西可
        # 校验/可蒸馏，不问模型（取舍见 `CHANGELOG.md` 2026-09-06 条目）。
        graph.add_conditional_edges(
            "retrieve_verify_step_memory",
            lambda s: "retrieve_verify_knowledge" if s.verify_step_entries else END,
            {"retrieve_verify_knowledge": "retrieve_verify_knowledge", END: END},
        )
        graph.add_edge("retrieve_verify_knowledge", "verify_and_summarize")
        graph.add_edge("verify_and_summarize", END)
        return graph.compile()

    # ---- 看 + 判 ----

    def look(self, state: EpisodeRunState) -> dict[str, Any]:
        """接住上一步交下来的那一帧，盖步号。**图的入口，只改 `observation` 一处——
        只盖步号，不做任何终止判断。**

        不感知：观测沿 `pending_observation` 传下来（一帧只在产出处感知一次——
        `_begin`/`look_after_action`），这里只把它正式编上第几步。开局那一帧
        也走这里（它是图的入口）。

        "这一局该不该停"整个交给下一格 `judge`——它才是这张图上关于终止唯一
        的决策者：不管终止的理由要不要问模型（步数用尽/世界结束/停摆不用问，
        目标达成要问），判定都归它管，不该有两个节点各管一部分。
        """
        # 步骤 1：盖步号。
        raw = state.pending_observation
        assert raw is not None, "look before an observation exists"
        obs = raw.model_copy(update={"step": state.step})

        # 步骤 2：记 OBSERVE（只管步号与目标栈；原始画面已在感知时随
        # MODEL_CALL 落盘，见 `game_utils.perceive_with_retry`）。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.OBSERVE,
                episode_id=state.episode_id,
                step=obs.step,
                obs=obs,
                goals=state.goals,
            )
        )
        return {"observation": obs}

    def judge(self, state: EpisodeRunState) -> dict[str, Any]:
        """这一局该不该停，在这一格一次性判完。**图上唯一的终止判定节点，
        只改 `done`/`success` 两处（紧密绑在一起的一小组，同 `stall_key`/
        `stall_count`）——`observation` 本身不再被这一格改动。**

        四类终止来源都在这合并，不分给别的节点：世界自己置 `done`（读
        `obs.done`，世界层自己的信号，只读不改）、步数用尽、连续
        `STALL_LIMIT` 步动作与画面机械状态都没变化（L2 护栏——`stall_count`
        由上一轮 `detect_stall` 算出，这里只读不改）——这三类不用问模型；
        第四类要问大脑（目标达成没有）。

        不管前三类是否已经成立，都照常问一次模型——**最后一帧仍然可能真的
        达成了目标**，这种情况要按成功记，不是按停摆/超时记，问的这次账
        （JUDGE）不能因为已经知道要终止就省略。本 episode 只解决栈顶
        （`goals[-1]`）；判成直接把 `done`/`success` 打上，不弹栈——弹栈/压栈
        是 run 级 `reflect` 的职责。

        **例外：第 0 步不问模型**。失败重试是"栈顶保留、世界不重置、直接开
        新 episode 重派"（见 `run_harness.py::reflect()`），重试 episode 第 0 步
        的这一帧和上一个失败 episode 最后一步已经判过的那一帧相同——再问一次
        模型是纯重复。**已知风险（用户已接受）**：这个判断对"全新目标第一次
        派发"的 episode 不成立——它的第 0 步从没被判过，理论上可能第一步就
        巧合达成，这里会漏判一次，要等第 1 步才会被发现（不会永久漏判，
        只是晚一步）。`episode_harness.run()` 目前收不到"这是第几次派发"的
        信息，没法只在真正的重试时才跳过，所以是全局跳过。
        """
        assert state.observation is not None, "judge before look"
        obs = state.observation
        goals = state.goals
        assert goals, "the goal stack must never be empty"

        # 步骤 1：三类不用问模型的终止——世界结束/步数用尽/停摆。
        stalled = state.stall_count >= STALL_LIMIT
        if stalled or obs.done or state.step >= state.task.max_steps:
            done, success = True, False
        else:
            done, success = False, False

        # 步骤 1.5：第 0 步不问模型（原因见上面的方法文档），非模型结论
        # （stall/世界结束/步数用尽——第 0 步这三样必然都是 False）直接就是
        # 最终结论，不用拼 history/images/prompt，也不留 MODEL_CALL 账单
        # （没问模型就没有账要记）。
        depth = len(goals) - 1
        if obs.step == 0:
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.JUDGE_VERDICT,
                    episode_id=state.episode_id,
                    step=obs.step,
                    done=done,
                    success=success,
                    stalled=stalled,
                    depth=depth,
                    why="第 0 步不问模型",
                )
            )
            return {"done": done, "success": success}

        # 步骤 2：取最近几步当证据，Harness 自己经 pokemon_agent.prompts.judge_success
        # 拼 prompt、回填进同一个 req 再交给 Brain（同 decide_action 的模式）——
        # 但 judge() 扛着"永远不抛异常"的契约，渲染搬出来之后这条契约不能丢：
        # 拼装本身可能抛的 KeyError（模板占位符对不上）在这里就近吞掉，不能让
        # 它一路冒穿 Harness。
        history = self._memory.query_recent_steps(state.episode_id, JUDGE_HISTORY)

        # 步骤 2.5：这次问模型要带的截图，去重后一并拿到（不再单独取
        # `snapshots`——"当前观测"改由 `judge_success.build_prompt()` 直接复用
        # `history` 最后一条的"之后变成"，见 0909 CHANGELOG 条目）。
        images, _ = dedup_snapshots(list(history))

        verdict_req = FromHarnessToBrainToolJudgeReq(
            goal=goals[-1],
            history=history,
            images=images,
        )
        try:
            verdict_req = verdict_req.model_copy(
                update={"prompt": judge_success_prompt.build_prompt(verdict_req)}
            )
        except Exception as exc:  # noqa: BLE001  同 Brain.judge() 原有的取舍
            verdict = FromHarnessToBrainToolJudgeResp(
                done=False,
                why=f"判定调用失败：{type(exc).__name__}",
                call=ModelCall(
                    payload={"ok": "False", "attempt": "1"},
                    error_kind=type(exc).__name__,
                    error=f"{exc}",
                ),
            )
        else:
            verdict = self._brain_tool.judge(verdict_req)

        # 步骤 2.5：判定账单（MODEL_CALL，JUDGE）——账单与失败补 ERROR 由 tool 处理。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.JUDGE_CALL,
                episode_id=state.episode_id,
                step=obs.step,
                depth=depth,
                call=verdict.call,
                why=verdict.why,
            )
        )

        # 步骤 3：判成才改——覆盖停摆/超时的结论，最后一帧仍可能真的达成。
        if verdict.done:
            done, success = True, True

        # 步骤 4：判定结论留一条轻量事件（`EventType.JUDGE`）——账单（MODEL_CALL）
        # 归 model_call 列后，观测台上 judge 节点的内容靠这条。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.JUDGE_VERDICT,
                episode_id=state.episode_id,
                step=obs.step,
                done=done,
                success=success,
                stalled=stalled,
                depth=depth,
                why=verdict.why,
            )
        )
        return {"done": done, "success": success}

    def get_action_space(self, state: EpisodeRunState) -> dict[str, Any]:
        """按这一帧观测算这一步能用的动作空间。

        **只在没终止的分支上跑，只改 `action_space` 一处。**
        """
        assert state.observation is not None, "get_action_space before judge"
        # "这一步允许了哪些动作"留痕——它是大脑决策的合法边界。
        space = self._game.get_action_space(state.observation)
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.ACTION_SPACE,
                episode_id=state.episode_id,
                step=state.observation.step,
                names=space.names,
            )
        )
        return {"action_space": space}

    # ---- 记忆检索：四个各自独立，最后由 enrich_observation 合并 ----

    def retrieve_step_episode_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查本局单步情景记忆（全量），交给 `think_action`。**只改 `step_episode_memories` 一处。**

        单独查、不折进观测：跟另外三类（跨局摘要/知识库/语义 object）折进
        `observation.facts` 不一样，它是给 `think_action` 的一份独立列表。
        """
        assert state.observation is not None, "retrieve_step_episode_memory before judge"
        ep, step = state.episode_id, state.observation.step
        try:
            memories = self._memory.query_episode_steps(ep)
        except Exception as exc:
            if not permission_was_denied(exc):
                raise
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PERMISSION_SKIPPED,
                    episode_id=ep,
                    step=state.observation.step,
                    permission="read:memory:episodic",
                    function="query_episode_steps",
                    fallback="[]",
                    source=Source.MEMORY,
                )
            )
            memories = []
        refs = " ".join(f"({m.episode_id}, {m.step})" for m in memories)
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.RETRIEVE_NODE,
                episode_id=ep,
                step=step,
                read_kind="step",
                count=len(memories),
                refs=refs,
            )
        )
        return {"step_episode_memories": memories}

    def retrieve_global_episode_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查跨局摘要记忆（按场景 + 任务目标）。**只改 `global_episode_memories` 一处。**

        `obs.place` 为 None 时没有场景可过滤，直接返回空列表——不是异常。
        """
        assert state.observation is not None, "retrieve_global_episode_memory before judge"
        obs, ep, step = state.observation, state.episode_id, state.observation.step
        scene_key = memory_query_utils.build_scene_key(obs)
        if scene_key is None:
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.RETRIEVE_NODE,
                    episode_id=ep,
                    step=step,
                    read_kind="global",
                    count=0,
                    refs="",
                )
            )
            return {"global_episode_memories": []}
        try:
            episode_memories = self._memory.query_episode_summaries(
                scene=scene_key,
                query=state.task.goal,
                limit=EPISODE_MEMORY_RECALL_LIMIT,
                # 只检索本 run 沉淀的摘要（取舍见 `CHANGELOG.md` 2026-09-03 条目）。
                run_id=self._run_id,
            )
        except Exception as exc:
            if not permission_was_denied(exc):
                raise
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PERMISSION_SKIPPED,
                    episode_id=ep,
                    step=step,
                    permission="read:memory:episode",
                    function="query_episode_summaries",
                    fallback="[]",
                    source=Source.MEMORY,
                )
            )
            episode_memories = []
        refs = " ".join(m.episode_id for m in episode_memories)
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.RETRIEVE_NODE,
                episode_id=ep,
                step=step,
                read_kind="global",
                count=len(episode_memories),
                refs=refs,
            )
        )
        return {"global_episode_memories": episode_memories}

    def retrieve_knowledge_semantic_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查知识库（query 由 observation 特征 + goal 拼成，
        见 `memory_query_utils.build_knowledge_query`）。
        **只改 `knowledge_semantic_memory` 一处。**
        """
        assert state.observation is not None, "retrieve_knowledge_semantic_memory before judge"
        obs, ep, step = state.observation, state.episode_id, state.observation.step
        try:
            result = self._memory.query_knowledge(
                FromHarnessToMemoryToolQueryKnowledgeReq(
                    query=memory_query_utils.build_knowledge_query(obs, state.task.goal),
                    limit=MEMORY_RECALL_LIMIT,
                )
            )
        except Exception as exc:
            if not permission_was_denied(exc):
                raise
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PERMISSION_SKIPPED,
                    episode_id=ep,
                    step=step,
                    permission="read:memory:knowledge",
                    function="query_knowledge",
                    fallback="empty FromHarnessToMemoryToolQueryKnowledgeResp",
                    source=Source.MEMORY,
                )
            )
            result = FromHarnessToMemoryToolQueryKnowledgeResp(contents=[], sources=[])
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.RETRIEVE_NODE,
                episode_id=ep,
                step=step,
                read_kind="knowledge",
                count=len(result.contents),
                refs=" ".join(result.sources),
            )
        )
        return {"knowledge_semantic_memory": result}

    def retrieve_object_semantic_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查语义记忆（object：这张地图上互动过的事件），文字化后交给 think。
        **只改 `object_semantic_memory` 一处。**"""
        assert state.observation is not None, "retrieve_object_semantic_memory before judge"
        ep, step = state.episode_id, state.observation.step
        try:
            if state.observation.place is None:
                events: list = []
            else:
                events = self._memory.query_object_events(
                    state.observation.place.map_id, before_step=step
                )
            known = render_object_events(events)
        except Exception as exc:
            if not permission_was_denied(exc):
                raise
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PERMISSION_SKIPPED,
                    episode_id=ep,
                    step=step,
                    permission="read:memory:objects",
                    function="query_object_events",
                    fallback="",
                    source=Source.MEMORY,
                )
            )
            events, known = [], ""
        # 统计口径 = 事件条数（渲染文本一行一条事件，两者恒相等）
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.RETRIEVE_NODE,
                episode_id=ep,
                step=step,
                read_kind="object",
                count=len(events),
                refs="",
            )
        )
        return {"object_semantic_memory": known}

    def enrich_observation(self, state: EpisodeRunState) -> dict[str, Any]:
        """把语义 object 折进这一帧观测，交给 `think_action`。**只改 `observation` 一处，不查库。**

        只有 `known_objects` 折进 `obs.facts`——它虽然也是跨步骤攒出来的，
        但坐标锚定在这张地图上，跟 `walk_map`/`landmarks` 同一个可信度级别；
        `knowledge`/`episode_memories` 各走各的 `FromHarnessToBrainToolChooseOnceReq` 字段
        （`think_action` 里单独取），prompt 里各有各的占位符和可信度说明，
        不混进 `已知事实`。

        本局单步（`state.step_episode_memories`）本来就没折进观测，仍是给
        `think_action` 的独立列表。

        四路检索各自在自己的节点里完成，这里只做 object 合并 + 记一条
        MEMORY_READ——四类读拆到四个节点查，但事件还是共用一条：拆成多条事件
        会让人以为它们发生在循环的不同位置（见 `tools/trace_render.py::memory_read`）。
        """
        assert state.observation is not None, "enrich_observation before judge"
        obs, ep, step = state.observation, state.episode_id, state.observation.step

        # 步骤 1：折进语义记忆（object）——坐标锚定，跟 walk_map/landmarks 同一
        # 可信度级别，继续留在 obs.facts 里。
        if state.object_semantic_memory:
            obs = obs.model_copy(
                update={"facts": {**obs.facts, "known_objects": state.object_semantic_memory}}
            )

        # 步骤 2：知识库/跨局摘要不再折进 obs.facts——只在这里算出文本，
        # 供本步 MEMORY_READ 记账用；真正喂给 think_action 的路径是
        # `state.knowledge_semantic_memory`/`state.global_episode_memories`
        # 原样传下去，由 think_action 自己拼 FromHarnessToBrainToolChooseOnceReq。
        knowledge_text = (
            "\n\n".join(state.knowledge_semantic_memory.contents)
            if state.knowledge_semantic_memory
            else ""
        )

        # 步骤 3：连同 step_episode_memories，写一条 MEMORY_READ。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.MEMORY_READ,
                episode_id=ep,
                step=step,
                memories=state.step_episode_memories,
                known_objects=state.object_semantic_memory,
                knowledge=knowledge_text,
                episode_memories=state.global_episode_memories,
                knowledge_sources=(
                    state.knowledge_semantic_memory.sources
                    if state.knowledge_semantic_memory
                    else []
                ),
            )
        )
        return {"observation": obs}

    def think_action(self, state: EpisodeRunState) -> dict[str, Any]:
        """大脑推理，然后**把它交回来的账翻译成事件**。

        重试循环（解析失败要重试）、每次尝试的记账，都在
        `brain_utils.choose_with_retry` 里（同步调用——无头模式下世界不限速，
        见 `pokemon_agent/world/pyboy_world.py`）；
        重试用尽时它直接抛 `MaxRetriesExceeded`——这里只管拼 prompt、调用、
        写最终的 `THINK`。
        """
        assert state.observation is not None, "think_action before look"
        assert state.action_space is not None, "think_action without an action space"
        ep, step = state.episode_id, state.observation.step

        # 步骤 1：拼这一步的基础 prompt。knowledge/episode_memories 单独传，
        # 不折进 obs.facts（见 `enrich_observation` 的说明）——各自在
        # `decide_action.md` 里有独立占位符和可信度说明。
        knowledge_text = (
            "\n\n".join(state.knowledge_semantic_memory.contents)
            if state.knowledge_semantic_memory
            else ""
        )
        episode_memories_text = (
            "\n\n".join(m.render() for m in state.global_episode_memories)
            if state.global_episode_memories
            else ""
        )
        # 步骤 1.5：取一次人类实时插话（`RunDataCenter` 的 human_note 槽，
        # 取到即清空，只对这一次决策生效）。没接前端（`self._data_center`
        # 为 `None`）时恒为空串。取到非空才留痕——
        # 没人插话是常态，不该每步都记一条空事件。
        human_note = self._data_center.take_human_note() if self._data_center else ""
        if human_note:
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.HUMAN_NOTE_INJECTED,
                    episode_id=ep,
                    step=step,
                    text=human_note,
                )
            )

        req = FromHarnessToBrainToolChooseOnceReq(
            goals=state.goals,
            obs=state.observation,
            space=state.action_space,
            memories=state.step_episode_memories,
            knowledge=knowledge_text,
            episode_memories=episode_memories_text,
            human_note=human_note,
        )
        # `Harness` 自己经 `pokemon_agent.prompts.decide_action` 拼 prompt，
        # 再把 prompt 回填进同一个 req——`req` 是 `build_prompt()` 和
        # `choose_once()` 共享的唯一输入，不必两套参数各传一遍。
        req = req.model_copy(update={"prompt": decide_action_prompt.build_prompt(req)})

        # 步骤 2：问一次决策（重试循环在 brain_utils.choose_with_retry）。
        action, attempt = brain_utils.choose_with_retry(
            self._brain_tool, self._trace, ep, step, req
        )

        # 步骤 3：成功——写 THINK，动作交回 state。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.THINK,
                episode_id=ep,
                step=step,
                action=action,
                attempt=attempt,
            )
        )
        return {"action": action}

    # ---- 唯一的动作节点。**只有 act 推进世界。** ----

    def act(self, state: EpisodeRunState) -> dict[str, Any]:
        """按键，推进世界。**只管执行和账，不写记忆、不感知。**

        `step` 不在这里加（在 `advance_step` 里加，`ACT` 和 `MEMORY_WRITE`
        落在同一步上）。感知挪到下一格 `look_after_action`——一帧只在产出处
        感知一次，这里不盖。
        """
        assert state.observation is not None, "act before look"
        assert state.action is not None, "act without an action"
        ep, before, action = state.episode_id, state.observation, state.action

        # 步骤 1：按 `before` 这份观测执行（工具层照它验掩码），只推进世界，不感知。
        self._game.execute(action, before)

        # 步骤 2：写 ACT，交给下一格 look_after_action 去感知。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.ACT,
                episode_id=ep,
                step=before.step,
                action=action,
            )
        )
        return {}

    def look_after_action(self, state: EpisodeRunState) -> dict[str, Any]:
        """感知 `act` 刚推进出来的新帧。**图上单独一格，只感知，不判定。**

        判定（该不该终止、目标是否达成）留给下一轮 `look`/`judge`——这里
        只把新的一帧收回来，重试循环在 `game_utils.perceive_with_retry`。
        """
        assert state.observation is not None, "look_after_action before act"
        ep, before = state.episode_id, state.observation

        # 步骤 1：感知这一步之后的新帧，交给停摆检测和落库那几格。原始画面
        # 随感知 MODEL_CALL 直接落盘。
        #
        # `screenshot_step=before.step + 1`：这一帧感知到的是"下一步的开局画面"
        # （它马上会变成 pending_observation，下一轮 `look()` 才会正式把它标成
        # `before.step + 1` 步），截图要按它未来的身份编号，不能沿用
        # `before.step`——否则跟 `_begin()` 存的开局第一帧（固定编号 0）撞名，
        # `StepMemory` 按 step 号回头找文件时会找错。MODEL_CALL 事件本身仍然
        # 按 `before.step` 记账（这次感知发生在第 `before.step` 步的回合里），
        # 两者解耦见 `LocalTrace.append()`。
        obs = game_utils.perceive_with_retry(
            self._game,
            self._trace,
            ep,
            before.step,
            screenshot_step=before.step + 1,
        )
        # 步骤 2：留一条轻量观察摘要（`EventType.LOOK_AFTER`）——该节点的
        # 痕迹只有感知 MODEL_CALL（要归 model_call 列）；完整 facts 由下一步
        # look 的 OBSERVE 携带，这里不重复。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.LOOK_AFTER,
                episode_id=ep,
                step=before.step,
                scene=obs.facts.get("scene", ""),
                overlay=obs.facts.get("overlay", ""),
                status=obs.status,
                done=obs.done,
            )
        )
        return {"pending_observation": obs}

    # ---- 停摆检测、步号、落库——都读同一份 before/action/after，互不影响谁先跑 ----

    def detect_stall(self, state: EpisodeRunState) -> dict[str, Any]:
        """算这一步的停摆键与连续计数（L2 护栏），记一条 STALL_CHECK 快照。
        **改 `stall_key`/`stall_count` 两处状态字段 + 写一条账，不碰观测。**

        本步（动作 + `obs.stall_key()`）跟上一步全同 → 计数 +1，否则清零重计。
        达到 `STALL_LIMIT` 时的强制终止判断在下一轮 `judge`（它是图上唯一的
        终止判定节点），这里只算数、记快照。

        STALL_CHECK 快照的动机（每一步的构成过程可回看，不用重放整局）见
        `CHANGELOG.md` 2026-09-03 条目。
        """
        assert state.observation is not None, "detect_stall before look"
        assert state.action is not None, "detect_stall without an action"
        assert state.pending_observation is not None, "detect_stall before act"
        key, count = episode_utils.compute_stall(
            state.pending_observation, state.action, state.stall_key, state.stall_count
        )
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.STALL_CHECK,
                episode_id=state.episode_id,
                step=state.observation.step,
                stall_key=key,
                stall_count=count,
            )
        )
        return {"stall_key": key, "stall_count": count}

    def advance_step(self, state: EpisodeRunState) -> dict[str, Any]:
        """步号加一。**只改 `step` 一处。**"""
        # 步数推进也要留痕——"advance 这个节点跑过了"本身要有痕迹。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.STEP_ADVANCE,
                episode_id=state.episode_id,
                step=state.observation.step,
                next_step=state.step + 1,
            )
        )
        return {"step": state.step + 1}

    def store_step_episode_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """把 `act` 刚推进的这一步反思成一条情景记忆，落库。**不改状态字段，只落库记账。**

        情景记忆记"我在那种画面里选了什么"（一次经过）；`before`/`action`/
        `after` 都从 state 直接读，跟 `detect_stall`/`advance_step`/
        `store_object_semantic_memory` 读的是同一份、互不影响谁先跑。
        """
        assert state.observation is not None, "store_step_episode_memory before look"
        assert state.action is not None, "store_step_episode_memory without an action"
        assert state.pending_observation is not None, "store_step_episode_memory before act"
        ep, before, action, after = (
            state.episode_id,
            state.observation,
            state.action,
            state.pending_observation,
        )

        # 步骤 1：反思成一条情景记忆（盖 episode_id——大脑不知道自己在哪一局；
        # 顺便盖两张截图的 base64——大脑不知道 run_id，也不该知道磁盘上的存储
        # 约定，这两样都是 harness 自己的事，跟盖 episode_id 同一个道理）。
        # `before_frame` 是第 `before.step` 步的开局画面，`after_frame` 是
        # 第 `before.step + 1` 步的开局画面（= 这一步做完动作后的画面，两者
        # 是同一份东西，见 `screenshot_filename()`/`LocalTrace.append()` 的
        # `screenshot_step` 说明）。直接存 base64 的取舍见 `CHANGELOG.md`
        # 2026-09-05 条目。
        try:
            entry = self._brain_tool.reflect(
                FromHarnessToBrainToolReflectReq(before=before, action=action, after=after)
            ).entry.model_copy(
                update={
                    "episode_id": ep,
                    "run_id": self._run_id,
                    "before_frame": self._frame_b64(ep, before.step),
                    "after_frame": self._frame_b64(ep, before.step + 1),
                }
            )
        except Exception as exc:
            if not permission_was_denied(exc):
                raise
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PERMISSION_SKIPPED,
                    episode_id=ep,
                    step=before.step,
                    permission="execute:llm:memory_reflection",
                    function="Brain.reflect",
                    fallback="skip store_step_episode_memory",
                    source=Source.MEMORY,
                )
            )
            return {}

        # 步骤 2：落库。
        try:
            self._memory.store_episode_step(entry)
        except Exception as exc:
            if not permission_was_denied(exc):
                raise
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PERMISSION_SKIPPED,
                    episode_id=ep,
                    step=before.step,
                    permission="write:memory:episodic",
                    function="store_episode_step",
                    fallback="skip",
                    source=Source.MEMORY,
                )
            )
        else:
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.MEMORY_WRITE,
                    episode_id=ep,
                    step=before.step,
                    entry=entry,
                )
            )
        return {}

    def store_object_semantic_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """把这一步涉及的语义记忆（object 交互事件）判定并落库。
        **不改状态字段，只落库记账。**"""
        assert state.observation is not None, "store_object_semantic_memory before look"
        assert state.action is not None, "store_object_semantic_memory without an action"
        assert state.pending_observation is not None, "store_object_semantic_memory before act"
        ep, before, action, after = (
            state.episode_id,
            state.observation,
            state.action,
            state.pending_observation,
        )

        # 步骤 1：判定（kind 方法表）+ 落库，逐事件记 OBJECT_NOTE。
        try:
            events = object_fact_events(before, action, after, ep, before.step, self._memory)
            if events:
                # 盖 run_id 章（落盘签名三元组之一），同 store_step 的 episode_id 盖章。
                self._memory.append_object_events(
                    [e.model_copy(update={"run_id": self._run_id}) for e in events]
                )
        except Exception as exc:
            if not permission_was_denied(exc):
                raise
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PERMISSION_SKIPPED,
                    episode_id=ep,
                    step=before.step,
                    permission="write:memory:objects",
                    function="append_object_events",
                    fallback="skip",
                    source=Source.MEMORY,
                )
            )
            events = []
        for event in events:
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.OBJECT_NOTE,
                    episode_id=ep,
                    step=before.step,
                    event=event,
                )
            )
        return {}

    # ---- 收尾 ----

    def retrieve_verify_step_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查本局全部 step 记忆，交给 `retrieve_verify_knowledge`/`verify_and_summarize`。
        **图上单独一格，只改 `verify_step_entries` 一处**——跟主循环的
        `retrieve_step_episode_memory` 是同一个 level：查库单独成节点，不跟
        判定逻辑缝在一起。

        只在判完成的收尾分支上跑一次（不是每步）。没有 step 记忆（或查询
        权限被拒）时留空列表——下游路由据此直接结束这一局的收尾链。
        """
        assert state.observation is not None and state.done, (
            "retrieve_verify_step_memory before the episode finished"
        )
        ep, step = state.episode_id, state.observation.step
        try:
            entries = self._memory.query_episode_steps(ep)
        except Exception as exc:
            if not permission_was_denied(exc):
                raise
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PERMISSION_SKIPPED,
                    episode_id=ep,
                    step=step,
                    permission="read:memory:episodic",
                    function="query_episode_steps",
                    fallback="[]",
                )
            )
            return {"verify_step_entries": []}
        # 这个节点只在收尾链跑一次，但也要留自己的痕迹——entries 为空（下游
        # 跳 verify 直接蒸馏）时这条正好说明"查了，没有可校验的 step 记忆"。
        refs = " ".join(f"({m.episode_id}, {m.step})" for m in entries)
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.RETRIEVE_NODE,
                episode_id=ep,
                step=step,
                read_kind="verify_step",
                count=len(entries),
                refs=refs,
            )
        )
        return {"verify_step_entries": entries}

    def retrieve_verify_knowledge(self, state: EpisodeRunState) -> dict[str, Any]:
        """整局一次检索领域知识，交给 `verify_and_summarize` 判领域合理性。
        **图上单独一格，只改 `verify_knowledge` 一处。**

        只在 `verify_step_entries` 非空时才会走到这一格（路由见 `_compile`）。
        检索权限被拒就当没有知识——校验器仍能靠方法论层自洽判一部分，召回
        覆盖不到的领域判断由校验器自己判"无法确认"，这一层不兜底。检索账
        单独记一条 `MEMORY_READ`（收尾路径没有 `enrich_observation` 可以顺路
        记账，这里自己记，否则 trace 看不出"校验器看到了什么知识"）。
        """
        assert state.observation is not None, "retrieve_verify_knowledge before judge"
        ep, step = state.episode_id, state.observation.step
        try:
            knowledge_result = self._memory.query_knowledge(
                FromHarnessToMemoryToolQueryKnowledgeReq(
                    query=memory_query_utils.build_verify_knowledge_query(
                        state.verify_step_entries, state.task.goal
                    ),
                    limit=MEMORY_RECALL_LIMIT,
                )
            )
        except Exception as exc:
            if not permission_was_denied(exc):
                raise
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PERMISSION_SKIPPED,
                    episode_id=ep,
                    step=step,
                    permission="read:memory:knowledge",
                    function="query_knowledge",
                    fallback="empty FromHarnessToMemoryToolQueryKnowledgeResp",
                    source=Source.MEMORY,
                )
            )
            knowledge_result = FromHarnessToMemoryToolQueryKnowledgeResp(contents=[], sources=[])
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.MEMORY_READ,
                episode_id=ep,
                step=step,
                memories=[],
                knowledge="\n\n".join(knowledge_result.contents),
                knowledge_sources=knowledge_result.sources,
                read_kind="read_verify_knowledge",
            )
        )
        return {"verify_knowledge": knowledge_result}

    def verify_and_summarize(self, state: EpisodeRunState) -> dict[str, Any]:
        """拿 `verify_step_entries`/`verify_knowledge` 问独立判定器，**一次调用**
        问完两件事：哪些 step 记忆可信、只用可信的那些蒸馏出跨局摘要并落库。
        **图上单独一格，收尾链的最后一格。**

        step 记忆是模型自述（`Brain.reflect()` 打包 before/action/after），没有
        验证——直接喂蒸馏会把错误操作蒸馏成经验并跨局传播。独立判定器
        （`Brain.verify_and_summarize`，`verify_llm`——可以配成跟 judge 不同的
        模型）在同一次输出里先逐条把关、再只用可信的写摘要；这次合并调用的
        账仍记在 `Source.VERIFY` 下（校验器自己的失效率要说得出，代价是这条
        账单现在也混进了写摘要那部分的 token，不再是纯校验成本）。

        只在 `verify_step_entries` 非空时才会走到这一格（路由见 `_compile`）
        ——为空时这一局的收尾链在上一格就结束了，不存在不经校验的全量蒸馏
        路径。
        """
        assert state.observation is not None and state.done, (
            "verify_and_summarize before the episode finished"
        )
        assert state.verify_step_entries, "verify_and_summarize 不该在没有 entries 时被路由到"
        ep, step = state.episode_id, state.observation.step
        obs = state.observation
        entries = state.verify_step_entries
        knowledge_text = (
            "\n\n".join(state.verify_knowledge.contents) if state.verify_knowledge else ""
        )
        outcome: dict[str, Any] = {
            "success": state.success,
            "steps": obs.step,
            "max_steps": state.task.max_steps,
        }

        # Harness 自己经 pokemon_agent.prompts.verify_and_summarize 拼 prompt、
        # 回填进同一个 req（同 judge 的模式）：拼装本身可能抛的 KeyError 在这
        # 就近吞成"全部标不可靠 + 不写摘要"，不冒穿；真正问模型那步
        # （`self._brain_tool.verify_and_summarize`）单独一层 try，只处理权限被拒——
        # 两层各管各的失败原因，不要混在一起。全量历史对应的截图（`StepMemory`
        # 自带 base64，不用读盘），去重后一起交给校验器——跟 judge 同一套
        # `dedup_snapshots()`，区别只是这里没有"当前帧"要额外拼进来（校验的是
        # 已经结束的一局，没有正在进行的"当前"这一说），第二个返回值（对应的
        # 观测列表）这里也用不上——`build_prompt()` 转文字只靠 `entries` 本身
        # （`render_sequence()`），不需要另一份从截图反推的观测，直接丢弃。
        images, _ = dedup_snapshots(entries)
        # 多帧拼接不在调用方做——`ArkProvider._prepare_images` 在发送前自动
        # 把多帧打包成一张网格图（豆包按张计费且与分辨率无关，拼接是
        # provider 层的结构保证，见 `providers/openai_compatible.py`）。

        req = FromHarnessToBrainToolVerifyAndSummarizeReq(
            goal=state.task.goal,
            entries=entries,
            knowledge=knowledge_text,
            images=images,
            episode_id=ep,
            run_id=self._run_id,
            success=outcome["success"],
            steps=outcome["steps"],
            max_steps=outcome["max_steps"],
        )
        try:
            req = req.model_copy(update={"prompt": verify_and_summarize_prompt.build_prompt(req)})
        except Exception as exc:  # noqa: BLE001  同 Brain.verify_and_summarize() 原有的取舍
            result = FromHarnessToBrainToolVerifyAndSummarizeResp(
                verdicts=[
                    StepVerifyVerdict(
                        index=i, reliable=False, why=f"合并调用失败：{type(exc).__name__}"
                    )
                    for i in range(len(entries))
                ],
                summary=None,
                call=ModelCall(
                    payload={"ok": "False", "attempt": "1"},
                    error_kind=type(exc).__name__,
                    error=f"{exc}",
                ),
                why=f"合并调用失败：{type(exc).__name__}",
            )
        else:
            try:
                result = self._brain_tool.verify_and_summarize(req)
            except Exception as exc:
                if not permission_was_denied(exc):
                    raise
                self._trace.append(
                    FromHarnessToTraceToolAppendReq(
                        kind=TraceKind.PERMISSION_SKIPPED,
                        episode_id=ep,
                        step=step,
                        permission="execute:llm:verify",
                        function="Brain.verify_and_summarize",
                        fallback="skip verify",
                    )
                )
                return {"verified_steps": None}

        # 步骤 2：合并调用的账单（MODEL_CALL，VERIFY）——逐条 verdicts 由 tool
        # 结构化进 payload（报表按它解析失效率）。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.VERIFY_CALL,
                episode_id=ep,
                step=step,
                call=result.call,
                verdicts=result.verdicts,
            )
        )
        # 逐条 verdicts 在 MODEL_CALL 里（报表按它解析失效率）；这里补轻量汇总
        # 给观测台链上这一格当内容。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.VERIFY_RESULT,
                episode_id=ep,
                step=step,
                checked=len(result.verdicts),
                unreliable=sum(1 for v in result.verdicts if not v.reliable),
            )
        )
        reliable = {v.index for v in result.verdicts if v.reliable}
        verified = [e for i, e in enumerate(entries) if i in reliable]

        # 摘要那一半解析/调用失败：只记一条错误，这一局不落跨局摘要，
        # 不影响本局结果。
        if result.summary is None or result.episode_memory is None:
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.EPISODE_SUMMARY_ERROR,
                    episode_id=ep,
                    step=step,
                    reason=result.why or "合并调用没能拿到 summary",
                )
            )
            return {"verified_steps": verified}

        try:
            episode_memory = self._memory.store_episode_summary(result.episode_memory)
        except Exception as exc:
            if not permission_was_denied(exc):
                raise
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PERMISSION_SKIPPED,
                    episode_id=ep,
                    step=step,
                    permission="write:memory:episode",
                    function="store_episode_summary",
                    fallback="skip",
                    source=Source.MEMORY,
                )
            )
            return {"verified_steps": verified}

        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.EPISODE_MEMORY_WRITE,
                episode_id=ep,
                step=step,
                memory=episode_memory,
            )
        )

        # 丢弃本局 step 记忆（不跨局累积；权限拒绝静默，下局照样跑）。
        try:
            self._memory.discard_episode_steps(ep)
        except Exception as exc:
            if not permission_was_denied(exc):
                raise
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.PERMISSION_SKIPPED,
                    episode_id=ep,
                    step=step,
                    permission="delete:memory:episodic",
                    function="discard_episode_steps",
                    fallback="skip",
                    source=Source.MEMORY,
                )
            )
        return {"verified_steps": verified}
