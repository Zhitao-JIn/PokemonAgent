"""EpisodeHarness —— **控制一局怎么跑**：一张 LangGraph 状态图，加上它的记账。

    record_observation → judge ──(done?)──→ retrieve_verify_step_memory
                                 ├─(无 step 记忆)──────────→ END
                                 └─(有 step 记忆)→ retrieve_verify_knowledge
                                                    → verify_and_summarize → END
      └─(否)→ get_action_space
        → retrieve_step_episode_memory → retrieve_global_episode_memory
          → retrieve_knowledge_semantic_memory → retrieve_object_semantic_memory
        → merge_retrieval
        → think_action〔产出 plan + pending_presses〕
        → act〔弹队首一键〕 → perceive_after_action〔取帧 + 判读 + 写 AFTER_ACTION〕
        → apply_stop〔按 stop 截队 + 只在真丢键时写 ACTION_TRUNCATED〕
        → detect_stall → store_step_episode_memory → store_object_semantic_memory
        → close_step〔扶正当前帧 + 步号加一〕
             ├─(pending_presses 非空)→ act            ← 链内小循环
             └─(队列空)→ save_checkpoint → record_observation（回到 run() 写 EPISODE_END）

**`step` 是一个小 action。** 一次决策交出的链被展开成 `pending_presses`，链内
每按一个键就走完一圈（`act` 起头、`close_step` 收尾），每圈各写一条
`StepMemory`、各判一次中止；队列空了才回链首重新决策。
链内小循环只加一条条件边，节点集合不变——`save_checkpoint` 因此仍只落在链边界上。
链内按键**只读 RAM**（免费且确定），链尾与中止的那一键才做完整视觉感知，
所以 `MODEL_CALL(PERCEPTION)` 的条数与改动前相等（验收不变量见
`docs/spec/harness/PLAN_action_step_granularity.md` §9）。

四个 retrieve_* 各自独立（互不依赖彼此输出，都只读 observation），写进
四个不同字段；merge_retrieval 只做合并，不查库。收尾分支的
retrieve_verify_step_memory/retrieve_verify_knowledge 是同一个模式在收尾
路径的落地——检索单独成节点、结果单独落一个 state 字段，
`verify_and_summarize` 本身不兼职查库（level 要跟主循环的 retrieve_* 一致）。

- `EpisodeRunState` 持有"这一局跑到哪了"；`EpisodeHarness` 自己没有任何字段，
  只做生死判断与记账；图只管循环调度与状态传递。
- 只有 `EpisodeHarness` 调 `trace.append()`（`trace_write.append_model_calls` 只是把
  同一份 `AppendReq` 样板收成一个函数），payload 由 `tools/trace_render.py` 的
  纯函数组装，这里只决定"该不该记、记成哪个 `EventType`"。
- `act` 是唯一推进世界的节点；收尾（`EPISODE_END`）在 `close_episode` 节点里
  （步 0 起就是图内的一格），`entry.py` 的 `close()` 只把图算好的结算取出来。
- **每个节点只改状态里的一处**（一个字段，或紧密绑在一起的一小组——比如
  `stall_key`/`stall_count` 是同一个判定的两个输出、`close_step` 的
  `observation`/`step` 是"一步关上"的两面）；停摆强制终止的判断归
  `record_observation` 之后的 `judge`（它本来就管"这一局该不该停"）。
- **帧不挂感知调用，挂在"产出它的那次感知所在的事件"上**：开局那一帧归
  `OBSERVE`（`_begin` 感知的，没有前驱按键），之后每一帧归那一键的 `AFTER_ACTION`。
  挂在感知调用上会让链内的键（压根没有视觉调用）那些步永远没有图，而
  `StepMemory.before_frame`/`after_frame` 是逐键都要的（见
  `game_utils.perceive_with_retry` 与 `docs/spec/harness/PLAN_action_step_granularity.md` §3）。
- **账写在它的宿主里（v7）**：账由产出材料的那一格自己落，三个 util 只交回尝试
  材料。于是"帧挂在产出它的那条账上"与"账写在哪一格"变成同一件事，暂存表
  `_pending_frames` 只剩第 0 步一条路径（见 `_pending_frames` 与
  `docs/spec/harness/PLAN_graph_readability.md` §3.7）。
- **帧账跟着存档走（v6）**：`_frame_event_ids`/`_pending_frames` 都是纯内存态，
  `save_checkpoint` 把**本局那份**打包进存档、`resume()` 原样回载。不这样的话，
  恢复后第一条 `OBSERVE` 与第一个 store 步的 `before_frame` 会一起丢图——截图在
  磁盘上，缺的只是"哪条事件承载这一步这一帧"（见 `_frame_ledger`）。
- **链尾那一帧给下一条链的 `OBSERVE`，靠"按 `event_id` 读回"**（v7 取代 v5 的
  "多带一份"）：链尾键的帧只挂在它自己的 `AFTER_ACTION` 上，下一条链的
  `record_observation` 用 `_frame_event_ids` 里登记的 event_id 把同一张图**再读
  一次**（`_frame_b64` + `read_screenshot`），拿到逐字节相同的一份挂上 `OBSERVE`。
  v5 那句"两处都看得到"的承诺不变，变的只是实现——不必为了下一条链把帧提前留在
  暂存表里（取舍见 `docs/spec/harness/PLAN_graph_readability.md` §3.7.3）。
"""

from __future__ import annotations

import base64
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.brain import (
    ActionFromBrain,
    ActionSegmentFromBrain,
    StepVerifyVerdict,
    TaskForBrain,
)
from pokemon_agent.errors import MaxRetriesExceeded, PerceptionFailure
from pokemon_agent.prompts import decide_action as decide_action_prompt
from pokemon_agent.prompts import judge_success as judge_success_prompt
from pokemon_agent.prompts import verify_and_summarize as verify_and_summarize_prompt
from pokemon_agent.prompts.object_render import render_object_events
from pokemon_agent.providers import ModelCall
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToBrainToolReflectReq,
    FromHarnessToBrainToolVerifyAndSummarizeReq,
    FromHarnessToBrainToolVerifyAndSummarizeResp,
    FromHarnessToCheckpointToolSaveReq,
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToMemoryToolAppendObjectEventsReq,
    FromHarnessToMemoryToolQueryEpisodeStepsReq,
    FromHarnessToMemoryToolQueryEpisodeSummariesReq,
    FromHarnessToMemoryToolQueryKnowledgeReq,
    FromHarnessToMemoryToolQueryObjectEventsReq,
    FromHarnessToMemoryToolQueryRecentStepsReq,
    FromHarnessToMemoryToolStoreEpisodeStepReq,
    FromHarnessToMemoryToolStoreEpisodeSummaryReq,
    FromHarnessToTraceToolAppendReq,
    FromRunHarnessToEpisodeHarnessRunReq,
    FromRunHarnessToEpisodeHarnessRunResp,
)
from pokemon_agent.schemas.memory import StopReason, dedup_snapshots, last_decisions
from pokemon_agent.tools.interface import (
    BrainToolPort,
    CheckpointToolPort,
    GameToolPort,
    MemoryToolPort,
    TraceToolPort,
)
from pokemon_agent.trace import Source, TraceKind, read_screenshot
from pokemon_agent.world import Observation

from . import brain_utils, episode_utils, game_utils, memory_query_utils, trace_write
from .auto_reviewer import AutoContinueReviewer
from .deps import HarnessDeps
from .episode import compile_episode_graph, entry
from .interface import EpisodeRunState
from .object_interactions import object_fact_events
from .run_data_center import RunDataCenter

# ---- 节点数常量已搬进 `episode/graph.py`（步 2）----
# 它们算的是 `recursion_limit`，而 limit 是"这张图长什么样"的函数——跟 `add_node`
# 的字面量住在一起，改节点集时改一处就够。本模块不再需要它们（`_invoke` 已搬进
# `episode/entry.py`，那里用 `entry.episode_budget()`）。


def _exc_snapshot(exc: Exception) -> str:
    """异常的字符串快照——`episode_error`/`run_error` 的 req 的 error 字段
    只吃文本，Exception 对象进不了 Pydantic req。

    步 2 起 `entry.py` 自带一份同形的 `exc_snapshot()`（那条路径的异常在那里补账），
    本模块这一份只服务于图内节点。== 步 3 统一。
    """
    return f"{type(exc).__name__}: {exc}"


MEMORY_RECALL_LIMIT = 5
"""每次决策检索几条情景记忆。"""

EPISODE_MEMORY_RECALL_LIMIT = 3
"""每次决策检索几条跨局摘要记忆。"""

JUDGE_DECISION_HISTORY = 2
"""判定器能看到本局最近几条**链**（`render(reason=False)`，不含决策者的主张）。

**单位是决策，不是步**：一次决策 = 一串键，所以"最近 2 次决策"就是换粒度之前的
"最近 2 步"（那时一步一步都是一次决策）。2026-09-11 粒度下沉到单键之后若还按步取，
判定器的时间视野会被**静默除以决策长度**（一次决策能按 8 键），而它判的"事件"类判据
前提就是"证据可能在前几次决策的快照里"——所以这里换的是**单位**，数字 2 没动
（详见 `docs/spec/harness/PLAN_action_step_granularity.md` §7.4）。

窗口大小的取舍（含已知风险）记录在 `CHANGELOG.md` 2026-09-05 条目。"""

JUDGE_HISTORY_KEY_CAP = 8
"""上面那个窗口一次**最多取几个键**（查询上限，也是渲染上限）。

**为什么要有帽**：链长没有上限（`MAX_SEGMENTS × MAX_TIMES` = 32 键），两条长链能把
判定器的 prompt 顶到十几条记忆。8 = 一条打满 `MAX_TIMES` 的单段链：实测一条记忆
渲成文本约 490 字符、判定 prompt 本体约 4 千字符，8 条就是它的量级上限。真机实测
（2026-09-11 四次 run）`press_count` 全是 1，这个帽现在根本碰不到——它防的是链一长
就静默膨胀。"""

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
        deps: HarnessDeps | None = None,
    ) -> None:
        """接好依赖，编译好状态图，此后不再变。

        `checkpoint`：checkpoint 手（PLAN_checkpoint §2）。`None` = 不做
        checkpoint（测试、单局直跑），`save_checkpoint` 节点空转。

        `deps`（**步 2 新增**）：全图唯一的 context（`HarnessDeps`）。不传就现建
        一份。**传进来的那份必须与 `RunHarness` 用的是同一个对象**——`dispatch`
        写 `deps.run_state_snapshot`、`save_checkpoint` 读它，两处必须是同一份，
        否则各看各的而且不报错。装配点 `build.py` 显式建一份、两边共用。

        **本类不再自己存依赖**（步 2）：`self.deps` 是唯一真源，下面的几个
        `_xxx` 都是**读 `deps` 的 property / 别名**——一份真源、两个句柄。
        步 3 把节点搬成自由函数（签名 `(state, runtime: Runtime[HarnessDeps])`）时，
        这些别名会逐个消失。
        """
        self.deps = deps or HarnessDeps(
            game=game,
            memory=memory,
            brain_tool=brain_tool,
            trace=trace,
            # episode 侧从不读 `reviewer`（那是 `review` 节点的事）；这一份只是
            # 兜底 deps 要凑齐"依赖"带，填个默认实现。
            reviewer=AutoContinueReviewer(),
            data_center=data_center,
            checkpoint=checkpoint,
            run_id=run_id,
        )
        """全图唯一的 context（`HarnessDeps`）：依赖 + 开关 + 整 run 的记号与账。
        帧登记表、帧暂存表、`run_state_snapshot`、`world_reset_done` 的真源都在
        它里面——见 `deps.py` 与 `PLAN_graph_composition.md` §4（D3/D4/D11）。"""
        # 两张帧表是**可变的 dict**，要让"图外的 `entry.py`"与"图内的节点"看见
        # 同一份：只能拿同一个对象（复制会分叉）。所以这里是别名，不是拷贝。
        self._frame_event_ids: dict[tuple[str, int], int] = self.deps.frame_event_ids
        self._pending_frames: dict[tuple[str, int], str] = self.deps.pending_frames
        self._graph = self._compile()

    # ---- 依赖：全部读 `deps`（步 2；步 3 撤掉这一节，节点改成收 `Runtime`）----

    @property
    def _game(self) -> GameToolPort:
        """世界那一根（`PyBoy` + 视觉模型的粘合层）。"""
        return self.deps.game

    @property
    def _memory(self) -> MemoryToolPort:
        """情景记忆 + 语义记忆（object）都走这一个端口。"""
        return self.deps.memory

    @property
    def _brain_tool(self) -> BrainToolPort:
        """大脑（决策 / 判定 / 蒸馏 / 规划四问）。"""
        return self.deps.brain_tool

    @property
    def _trace(self) -> TraceToolPort:
        """记账 req 由这里组装，payload 渲染与落盘都在 `TraceTool`。"""
        return self.deps.trace

    @property
    def _run_id(self) -> str:
        """本 run 的标识（真源 `deps.run_id`）。

        `RunHarness.run(run_id)` 会把它刷成传入的那一个——两边必须是同一个串，
        否则截图路径（`_frame_b64` → `read_screenshot`）与 trace 事件会指向
        不同的 run。
        """
        return self.deps.run_id

    @property
    def _data_center(self) -> RunDataCenter | None:
        """人类实时插话的来源（`RunDataCenter` 的 human_note 槽）。
        `None` = 没接前端（测试、CLI），`think_action` 每步照常跑，只是永远
        取不到插话——跟 `reviewer`/`data_center` 在 `RunHarness` 里"不传就是
        没有真人"的兜底是同一个约定。**只读它的 human_note 槽**，不碰
        goals/review 两个槽——那两个是 run 级的事，不归 episode 管。"""
        return self.deps.data_center

    @property
    def _checkpoint(self) -> CheckpointToolPort | None:
        """checkpoint 手；`None` = 不做 checkpoint，`save_checkpoint` 节点空转。
        **步 5 这根 Port 会消失**（D9-v6：checkpoint 解散进 harness，只剩
        `deps.checkpoint_root` 一条路径）。"""
        return self.deps.checkpoint

    @property
    def _run_state_dump(self) -> dict[str, Any] | None:
        """当前正在跑的这一局对应的 `RunState.model_dump()`——真源是
        `deps.run_state_snapshot`：**写入点在 `dispatch` 节点**（D11-(3)——
        内置子图之后没有"方法入口"这个位置了），`save_checkpoint()` 原样打包进
        每一步的存档，本层不解读（纯透传，见 `checkpoint_tool.py` 落盘布局说明）。"""
        return self.deps.run_state_snapshot

    def _frame_ledger(self, episode_id: str) -> tuple[dict[int, int], dict[int, str]]:
        """把本局的帧账摊成两张"步号说话"的表，供 `save_checkpoint()` 打包进存档。

        **帧账是纯内存态，不随存档走就等于恢复后丢图**：`resume()` 是在新进程里
        构造的 `EpisodeHarness`，两张表都是空的，于是恢复后第一条 `OBSERVE`（链首
        要自带"大脑决策时看到的世界"）与恢复后第一个 store 步的 `before_frame`
        （`StepMemory` 逐键都要那两帧）都会是 `None`——而截图本来就在磁盘上
        （`screenshot/<event_id>.png`），缺的只是"哪条事件承载这一步这一帧"。

        只带**本局切片**：存档是"这一局第 `step` 步"的存档，别的局的帧账与它无关。

        前置条件：`episode_id` 非空。
        后置条件：返回 `(登记表, 暂存表)`，键是**整数步号**——落盘时由 `json.dumps`
        写成 `"<step>"`，读回时由 Pydantic 还原成整数键（`resume()` 直接塞回两张表）。
        """
        assert episode_id, "_frame_ledger() got an empty episode_id"
        registry = {
            step: event_id
            for (ep, step), event_id in self._frame_event_ids.items()
            if ep == episode_id
        }
        pending = {
            step: png for (ep, step), png in self._pending_frames.items() if ep == episode_id
        }
        return registry, pending

    def _frame_b64(self, episode_id: str, step: int) -> str | None:
        """读第 `step` 步开局画面对应的便利截图、编成 base64，读不到就是 `None`。

        截图与 trace 事件共享 event_id（拍板⑦）：这里用 `_frame_event_ids`
        里登记的帧事件 event_id 定位文件（`screenshot/<event_id>.png`），不再有
        按 step 号拼文件名的公式。`StepMemory.before_frame`/`after_frame` 已直接
        存 base64（见该字段文档），只有 `store_step_episode_memory()` 反思成一条
        记忆的这一刻才需要现读现编；`judge()` 的图完全来自 history 里已经存好的
        截图，不走这里。查不到登记就返回 `None`——那是"这一帧本来就没落图"的正常
        情形（感知失败的那一步）；`resume()` 已把本局登记表从存档回载，恢复后不再
        存在"表是空的"这种缺口（见 `_frame_ledger`）。
        """
        event_id = self._frame_event_ids.get((episode_id, step))
        if event_id is None:
            return None
        raw = read_screenshot(self._run_id, event_id)
        return base64.b64encode(raw).decode() if raw is not None else None

    def _perceive(
        self, episode_id: str, step: int, *, ram_only: bool = False
    ) -> tuple[Observation, str | None]:
        """感知一帧，并把这次的尝试账落进 trace——**两个感知调用点的共同宿主**。

        调用点有两个：`perceive_after_action`（图内节点）与 `_begin`（图外的局
        入口）。两者都走 `game_utils.perceive_with_retry`（循环与重试预算都在那里），
        但**账按"写在它的宿主里"这条规则统一落在这里**——于是
        `MODEL_CALL(PERCEPTION)` 与消费它的那一格在同一个方法里，不再是
        "util 边重试边写"（见 `docs/spec/harness/PLAN_graph_readability.md` §3.7.4）。

        前置条件：`episode_id` 非空。
        后置条件：返回 `(观测, base64 PNG | None)` 成对；预算耗尽时抛
        `PerceptionFailure`——**账已经写完**，重试期间烧掉的 token 一条不少。
        `ram_only=True` 时压根不问模型（`log` 为空），因此不会走到失败分支。
        """
        observation, frame_png, log = game_utils.perceive_with_retry(self._game, ram_only=ram_only)
        trace_write.append_model_calls(
            self._trace,
            episode_id=episode_id,
            step=step,
            source=Source.PERCEPTION,
            log=log,
        )
        if observation is None:
            last_reason = log[-1][1].error if log else "ram_only 从不失败"
            raise PerceptionFailure(len(log), last_reason)
        return observation, frame_png

    # ---- 对外只有这两个入口（步 2 起它们只是"薄委托"）----
    #
    # 开局/恢复的**装配**（写 EPISODE_START、reset 世界、感知首帧；恢复的七步准备）
    # 与**进图 + 取结算**都搬进了 `episode/entry.py`——那是"图外侧门"，它收的是
    # `HarnessDeps`，所以图外与图内看到的是同一份依赖。这两个方法留着是因为
    # `EpisodeHarnessPort`（`api.py`/测试/脚本在用）的形状不变；步 3/4 会把
    # 这一层也去掉（节点搬成自由函数、外部调用面收进 `RunHarness` 薄类）。

    def run(
        self, req: FromRunHarnessToEpisodeHarnessRunReq
    ) -> FromRunHarnessToEpisodeHarnessRunResp:
        """跑完一局：解决栈顶这一个目标。

        前置条件：episode_id 非空、task.max_steps > 0、stack 非空且栈顶 == task。
        后置条件：trace 里恰好多一条 EPISODE_START 和一条 EPISODE_END。
        """
        return entry.run_new(
            self.deps,
            self._graph,
            episode_id=req.episode_id,
            task=req.task,
            stack=req.stack,
            run_state=req.run_state,
        )

    def resume(
        self,
        episode_id: str,
        task: TaskForBrain,
        stack: list[TaskForBrain],
        step: int,
        run_state: dict[str, Any],
    ) -> FromRunHarnessToEpisodeHarnessRunResp:
        """从本局第 `step` 步开局的 checkpoint 恢复并跑完（PLAN_checkpoint §5，step 级入口）。

        前置条件：构造时注入了 checkpoint 工具；`(episode_id, step)` 的存档成对存在。
        恢复语义（七步）见 `episode/entry.py::prepare_resume`。

        `stack` 参数保留是为了端口形状不变（恢复路径的 `episode_goals` 早已在存档的
        state 里，不需要重投影）——`run()` 那边它是必需的。
        """
        assert stack, "resume() got an empty goal stack"
        return entry.run_resume(
            self.deps,
            self._graph,
            episode_id=episode_id,
            task=task,
            step=step,
            run_state=run_state,
        )

    def save_checkpoint(self, state: EpisodeRunState) -> dict[str, Any]:
        """图边界节点：每圈边界（含 step0）写一份 checkpoint（PLAN_checkpoint §2）。

        **只写存档与接缝账，不改状态**——返回空增量。三件套：模拟器世界快照 +
        `EpisodeRunState` dump + trace 游标；v6 起再带上**本局帧账**（见
        `_frame_ledger`——纯内存态，不带就等于恢复后丢图）。存档成功后补一条
        `CHECKPOINT_SAVE`（`LIFECYCLE`），与 `resume()` 的 `CHECKPOINT_RESTORE` 对称
        ——存档端也要在事件流里可见，否则 replay 只能反推存档文件的 step 来切段。
        checkpoint 工具未注入（测试/单局直跑）时空转（那时**不写账**：没有存档就没有
        接缝可标）。
        """
        if self._checkpoint is None:
            return {}
        # 步骤 1：摊平本局帧账——它必须在存档里，且只有本局那一段有意义。
        frame_event_ids, pending_frames = self._frame_ledger(state.episode_id)
        # 步骤 2：写存档：世界快照 + 两层状态 dump + trace 游标 + 本局帧账。
        self._checkpoint.save(
            FromHarnessToCheckpointToolSaveReq(
                run_id=self._run_id,
                episode_id=state.episode_id,
                step=state.step,
                state_dump=state.model_dump(),
                run_state_dump=self._run_state_dump,
                last_event_id=self._trace.cursor(),
                emulator_state=self._game.save_state_bytes().emulator_state,
                frame_event_ids=frame_event_ids,
                pending_frames=pending_frames,
            )
        )
        # 步骤 3：存档端留一个接缝标记（量级是**链边界一条**，不是每键一条）。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.CHECKPOINT_SAVE,
                episode_id=state.episode_id,
                step=state.step,
                saved_step=state.step,
            )
        )
        return {}

    # ---- 图 ----

    def _compile(self) -> CompiledStateGraph:
        """把 21 个节点交给 `episode/graph.py` 接起来。

        **步 0 起"图长什么样"与"节点怎么实现"分居两个文件**：这里交出
        "节点名 → 节点函数"这张表，节点顺序、条件边、决策内小循环与收尾链的
        分叉全在 `episode/graph.py`（读它就够）。`add_node` 的字面量与观测台
        相位表的一致性由 `scripts/check_graph_phases.py` 机械核对。
        """
        return compile_episode_graph(
            {
                "save_checkpoint": self.save_checkpoint,
                "record_observation": self.record_observation,
                "judge": self.judge,
                "get_action_space": self.get_action_space,
                "retrieve_step_episode_memory": self.retrieve_step_episode_memory,
                "retrieve_global_episode_memory": self.retrieve_global_episode_memory,
                "retrieve_knowledge_semantic_memory": self.retrieve_knowledge_semantic_memory,
                "retrieve_object_semantic_memory": self.retrieve_object_semantic_memory,
                "merge_retrieval": self.merge_retrieval,
                "think_action": self.think_action,
                "act": self.act,
                "perceive_after_action": self.perceive_after_action,
                "apply_stop": self.apply_stop,
                "detect_stall": self.detect_stall,
                "store_step_episode_memory": self.store_step_episode_memory,
                "store_object_semantic_memory": self.store_object_semantic_memory,
                "close_step": self.close_step,
                "retrieve_verify_step_memory": self.retrieve_verify_step_memory,
                "retrieve_verify_knowledge": self.retrieve_verify_knowledge,
                "verify_and_summarize": self.verify_and_summarize,
                "close_episode": self.close_episode,
            }
        )

    # ---- 记 + 判 ----

    def record_observation(self, state: EpisodeRunState) -> dict[str, Any]:
        """把当前帧记成一条 `OBSERVE`——**这一链的决策输入**。只记账，不改状态。

        图上它在链首、`judge` 之前，是这一格唯一的记账点：`OBSERVE` 必须落在
        **每条链**上（决策输入一次一条），链内每个键都没有它——链内那些键只读 RAM
        （`_perceive(ram_only=True)`，本来就没有 `MODEL_CALL` 可挂），痕迹留在那一键
        自己的 `AFTER_ACTION` 上（轻量摘要，不含完整 `facts`，也不承载 `goals`）。
        这一格没了，replay 与观测台就没有"大脑当时看到的世界"的结构化原件了。

        **它不扶正、不盖步号**：`observation` 在每步的终点（`close_step`）就前进
        到位了，开局那一帧由 `_begin` 直接产出。扶正曾经住在这里——那时它是
        "步级 + 链级"的混合节点（扶正每步一次、`OBSERVE` 每链一次）；链内小循环
        让链内每步都不再经过它，扶正遂失去宿主，挪去了 `close_step`
        （见 `docs/spec/harness/PLAN_graph_readability.md` §3.4）。

        **它带的那一帧有两个来源**（帧的承载规则见模块文档最后两条）：

        - **开局那一帧**（`_begin` 感知的，没有前驱按键）：从 `_pending_frames` 取，
          取走即删；
        - **上一条链链尾那一帧**：链尾键自己那份挂在它的 `AFTER_ACTION` 上，这一份
          由 `_frame_b64(episode_id, obs.step)` **按 event_id 读回**（v7 取代 v5 的
          "多带一份"）——好让链首这一页自带"大脑决策时看到的世界"。恢复后的链首同理
          （v6：登记表由 `resume()` 从存档回载，不再有"表是空的"这个缺口）。

        PNG 进不了领域模型 `Observation`，所以两者都要在挂账这一刻现取现用。
        """
        obs = state.observation
        assert obs is not None, "record_observation before an observation exists"

        # 步骤 1：取这一帧——开局那一帧进暂存表取；否则按 event_id 读回上一条链
        # 链尾那一帧（`_frame_b64` 只认登记表，未登记即 None，缺图跳过）。两条路径
        # 都可能给 None（这一帧本来就没落图，或链首恰好没有前驱按键产出的那一份）。
        frame_png = self._pending_frames.pop((state.episode_id, obs.step), None)
        if frame_png is None:
            frame_png = self._frame_b64(state.episode_id, obs.step)

        # 步骤 2：记 OBSERVE，把这一帧的原始画面挂上。
        event_id = self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.OBSERVE,
                episode_id=state.episode_id,
                step=obs.step,
                obs=obs,
                goals=state.episode_goals,
                frame_png=frame_png,
            )
        )
        # 有帧才登记（没帧的 OBSERVE 不产生截图文件，登记它会让 `_frame_b64`
        # 去读一个不存在的文件）；**已有登记的不覆盖**——登记表的规则是"谁先产出
        # 这一帧谁登记"：每一键的帧都由 `perceive_after_action` 那条 `AFTER_ACTION`
        # 先登记（读哪次都一样，但指向必须**稳定**，不能同一时刻问两次答两个事件），
        # 只有第 0 步这一帧没有前驱按键，才由本格登记。
        if frame_png is not None and (state.episode_id, obs.step) not in self._frame_event_ids:
            self._frame_event_ids[(state.episode_id, obs.step)] = event_id
        return {}

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
        assert state.observation is not None, "judge before record_observation"
        obs = state.observation
        goals = state.episode_goals
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

        # 步骤 2：取最近几条**链**当证据（换算见上面两个常量），Harness 自己经
        # pokemon_agent.prompts.judge_success
        # 拼 prompt、回填进同一个 req 再交给 Brain（同 decide_action 的模式）——
        # 但 judge() 扛着"永远不抛异常"的契约，渲染搬出来之后这条契约不能丢：
        # 拼装本身可能抛的 KeyError（模板占位符对不上）在这里就近吞掉，不能让
        # 它一路冒穿 Harness。
        # 检索面只认步号（`limit` 是"几条记忆"），所以要分两步取窗：先按键数上限
        # 取回尾部，再按决策裁到最近 `JUDGE_DECISION_HISTORY` 次。`last_decisions` 不把
        # 一次决策砍成半截——半截里"这一键之后为什么停"读不出来。
        recent = self._memory.query_recent_steps(
            FromHarnessToMemoryToolQueryRecentStepsReq(
                episode_id=state.episode_id, limit=JUDGE_HISTORY_KEY_CAP
            )
        ).steps
        history = last_decisions(recent, JUDGE_DECISION_HISTORY)

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
        space = self._game.get_action_space(
            FromHarnessToGameToolGetActionSpaceReq(observation=state.observation)
        ).action_space
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.ACTION_SPACE,
                episode_id=state.episode_id,
                step=state.observation.step,
                names=space.names,
            )
        )
        return {"action_space": space}

    # ---- 记忆检索：四个各自独立，最后由 merge_retrieval 合并 ----

    def retrieve_step_episode_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查本局单步情景记忆（全量），交给 `think_action`。**只改 `step_episode_memories` 一处。**

        单独查、不折进观测：跟另外三类（跨局摘要/知识库/语义 object）折进
        `observation.facts` 不一样，它是给 `think_action` 的一份独立列表。
        """
        assert state.observation is not None, "retrieve_step_episode_memory before judge"
        ep, step = state.episode_id, state.observation.step
        memories = self._memory.query_episode_steps(
            FromHarnessToMemoryToolQueryEpisodeStepsReq(episode_id=ep)
        ).steps
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
        episode_memories = self._memory.query_episode_summaries(
            FromHarnessToMemoryToolQueryEpisodeSummariesReq(
                scene=scene_key,
                query=state.task.goal,
                limit=EPISODE_MEMORY_RECALL_LIMIT,
                # 只检索本 run 沉淀的摘要（取舍见 `CHANGELOG.md` 2026-09-03 条目）。
                run_id=self._run_id,
            )
        ).summaries
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
        result = self._memory.query_knowledge(
            FromHarnessToMemoryToolQueryKnowledgeReq(
                query=memory_query_utils.build_knowledge_query(obs, state.task.goal),
                limit=MEMORY_RECALL_LIMIT,
            )
        )
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
        if state.observation.place is None:
            events: list = []
        else:
            events = self._memory.query_object_events(
                FromHarnessToMemoryToolQueryObjectEventsReq(
                    map_id=state.observation.place.map_id, before_step=step
                )
            ).events
        known = render_object_events(events)
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

    def merge_retrieval(self, state: EpisodeRunState) -> dict[str, Any]:
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
        assert state.observation is not None, "merge_retrieval before judge"
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

        重试循环（解析失败要重试）在 `brain_utils.choose_with_retry` 里（同步调用
        ——无头模式下世界不限速，见 `pokemon_agent/world/pyboy_world.py`）；**账不写
        在那里**——它交回 `(动作 | None, ModelCallLog)`，由本格
        （`trace_write.append_model_calls`）落到 `MODEL_CALL(DECISION)` 上。重试用尽
        （`action is None`）时本格补一条 `DECISION_FAILED` 再抛 `MaxRetriesExceeded`
        （见 `docs/spec/harness/PLAN_graph_readability.md` §3.7.4）。
        """
        assert state.observation is not None, "think_action before record_observation"
        assert state.action_space is not None, "think_action without an action space"
        ep, step = state.episode_id, state.observation.step

        # 步骤 1：拼这一步的基础 prompt。knowledge/episode_memories 单独传，
        # 不折进 obs.facts（见 `merge_retrieval` 的说明）——各自在
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
            goals=state.episode_goals,
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

        # 步骤 2：问一次决策（重试循环在 brain_utils.choose_with_retry；账由本格落
        # ——`log` 里失败与成功两种尝试都在，逐条进 MODEL_CALL）。
        action, log = brain_utils.choose_with_retry(self._brain_tool, req)
        trace_write.append_model_calls(
            self._trace, episode_id=ep, step=step, source=Source.DECISION, log=log
        )

        # 步骤 2.5：预算耗尽——补一条 DECISION_FAILED（把最后一次失败的账带出来，
        # 报表按它统计失效率），再抛 `MaxRetriesExceeded`。本步到此为止。
        if action is None:
            last = log[-1][1]
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.DECISION_FAILED,
                    episode_id=ep,
                    step=step,
                    call=last,
                )
            )
            raise MaxRetriesExceeded(
                brain_utils.DECISION_MAX_RETRIES, f"{last.error_kind}: {last.error}"
            )

        # 步骤 3：写 THINK（记的是**整条链**），把链交回 state。`attempt` = 这条链是
        # 第几次尝试问出来的（就是 `log` 最后一条的序号）。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.THINK,
                episode_id=ep,
                step=step,
                action=action,
                attempt=log[-1][0],
            )
        )

        # 步骤 4：把链展开成「一键一段」的待按队列——一次决策交出的东西在这一格
        # 定型，`act` 只负责弹队首（把展开塞进 `act` 会让"这一次决策打算按什么"
        # 散在 N 圈里，链原文也就没有一处权威拷贝了）。
        #
        # 每段带着**它所属那一段**的 rationale：`times=4` 声明这 4 下同质，
        # 所以理由共享；展开后每一份都仍是"这一步为什么按"（见 §4b）。
        # `times` 只是书写压缩，展开成 N 个 `times=1` 不改变任何语义。
        presses = [
            ActionSegmentFromBrain(name=segment.name, times=1, rationale=list(segment.rationale))
            for segment in action.sequence
            for _ in range(segment.times)
        ]
        # 顺带记下**这条链从第几步开始**（`plan_step_start`）：链内的键要能被认领回
        # 这一次决策（记忆侧按它分组——决策者回看时按链读，见
        # `schemas/memory/datastore/step_memory.py::render_decisions()`）。它是执行期的
        # 记账，`StepMemory` 那一份由 `store_step_episode_memory` 从这里抄。
        return {"plan": action, "pending_presses": presses, "plan_step_start": step}

    # ---- 唯一的动作节点。**只有 act 推进世界。** ----

    def act(self, state: EpisodeRunState) -> dict[str, Any]:
        """弹出队首那**一个键**，推进世界。**只管执行和账，不写记忆、不感知。**

        改 `action`/`pending_presses` 两处——"弹队首"这一个动作的两面：派生出的
        单键动作交出去、剩下的队列留给链内小循环。

        **当前帧不由这一格扶正**（那是 `close_step` 的活）：`observation` 在本圈
        里的语义是"这次按键**之前**的那一帧"——`perceive_after_action` 拿它当 `before`
        判中止，两个 store 拿它跟 `pending_observation` 凑成 `before`/`after` 反思
        记忆。它在**上一步的终点**就已经就位，本格只读不算。

        **派生而不是新建类型**：`reflect`/trace/停摆检测/记忆全都只认
        `ActionFromBrain`，派生出来的那个照样是"这一步要做的动作"（单段、
        `times=1`），所以它们一个都不用知道"链"这个概念存在。`thought` 沿用
        `plan` 的（链级的，只进 trace），`rationale` 取自队首所在的那一段。

        **`settle` 由"这是不是队列里的最后一个键"决定**：链中间的键后面还有键
        要按，等世界把 10 秒过场走完不但慢，而且那几帧对它没用（它只读内存
        判位移、换图）；链尾那一帧要交给 `judge` 看，必须等。

        `step` 不在这里加（在 `close_step` 里加，`ACT` 和 `MEMORY_WRITE`
        落在同一步上）。感知挪到下一格 `perceive_after_action`——一帧只在产出处
        感知一次，这里不盖。
        """
        assert state.observation is not None, "act before close_step"
        assert state.plan is not None, "act without a plan"
        assert state.pending_presses, "act with an empty pending queue"
        # 一切"按键之前"的判断都照着当前帧——它已由上一步的终点扶正好。
        ep, before = state.episode_id, state.observation

        # 步骤 1：派生这一圈的单键动作。
        head = state.pending_presses[0]
        is_decision_tail = len(state.pending_presses) == 1
        action = ActionFromBrain(thought=state.plan.thought, sequence=[head])

        # 步骤 2：按 `before` 这份观测执行（工具层照它验掩码），只推进世界，不感知。
        self._game.execute(
            FromHarnessToGameToolExecuteReq(
                action=action, observation=before, settle=is_decision_tail
            )
        )

        # 步骤 3：写 ACT，交给下一格 perceive_after_action 去感知。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.ACT,
                episode_id=ep,
                step=before.step,
                action=action,
            )
        )
        # 两处一起交：派生的单键动作、剩下的队列（当前帧的扶正在 `close_step`）。
        return {
            "action": action,
            "pending_presses": state.pending_presses[1:],
        }

    def perceive_after_action(self, state: EpisodeRunState) -> dict[str, Any]:
        """感知 `act` 刚推进出来的新帧，**判读这一键的结局**，写这一键的 `AFTER_ACTION`。

        改 `pending_observation`/`pending_stop` 两处——"这一键之后看到了什么"与
        "它为什么没有继续"是**同一次感知的解读**，两个面。第三面（据此把不该再按
        的键从队列里拿掉）是**执行后果**，住在下一格 `apply_stop`。

        **为什么"判读"必须和"感知"同格**：步骤 3 的中止补感知触发条件就是
        `stop is not None`，而 `stop` 是 `compute_stop(before, action, obs)` 的输出
        ——把判读挪到别的格子，这一格就不知道自己该不该补第二次感知。所以能拆的
        接缝只有"感知+判读 | 落实+留痕"这一条（论证见
        `docs/spec/harness/PLAN_graph_readability.md` §3.6）。

        感知分两档（见 `docs/spec/harness/PLAN_action_step_granularity.md` §3）：

        - **链中间的键只读内存**：它只需要判"位置动没动、换没换图"，那两件事
          内存直接答得出；为此烧一次视觉调用买的全是用不上的信息（场景、对话），
          而且会让链的执行结果依赖模型返回——"同存档 + 同链 → 同一状态"当场失效。
        - **链尾那一键、以及中止的那一键做完整感知**：前者那一帧要交给 `judge`
          看，后者是这一圈真正的落点。两类加起来，`MODEL_CALL(PERCEPTION)` 的
          条数与改动前相等（验收不变量，§9）。

        **中止范围的唯一判据**（§5）：只扩到"再做下去会产生它没打算要的动作"
        为止。`blocked` 之后再按只是空按（浪费一点 tick），所以只丢掉本段剩余
        次数；`warp` 之后再按是在**一张它没规划过的地图**上产生位移，所以整条
        链作废——**截断本身在下一格**（`apply_stop`），这里只交出 `stop`。

        **账也在这里写（v7）**：本格是帧的产出格，所以帧归本格那条 `AFTER_ACTION`
        （观察摘要：`status`/`done`，链内每键一条）。`stop` 是**处置**，不进这条观察
        账——它归 `apply_stop` 只在真丢键时写的那条 `ACTION_TRUNCATED`。
        """
        assert state.observation is not None, "perceive_after_action before act"
        assert state.action is not None, "perceive_after_action without an action"
        ep, before, action = state.episode_id, state.observation, state.action
        # `act` 已经弹掉队首，所以"队列空"就是"刚按的这一个是链尾"。
        is_decision_tail = not state.pending_presses

        # 步骤 1：感知（重试循环与记账都在 `self._perceive`）。链尾直接走完整档，
        # 链中间的键先只读内存。账的步号取 `before.step`——与 `ACT` 落在同一步上。
        obs, frame_png = self._perceive(ep, before.step, ram_only=not is_decision_tail)

        # 步骤 2：判这一键的结局。纯字段比较，不调模型——判据见
        # `episode_utils.compute_stop`（它同时是中止范围的唯一出处）。
        stop = episode_utils.compute_stop(
            before,
            action,
            obs,
            next_step=before.step + 1,
            max_steps=state.task.max_steps,
        )

        # 步骤 3：链中途就中止的那一键补一次完整感知——它是这一圈真正的落点，
        # 跟链尾同一个待遇（判定层要看的字段里，只有对话文字 RAM 读不出）。
        #
        # 已知代价（真机要验，§7.10）：这一键按下去时 `settle=False`（当时以为
        # 后面还有键），所以这份观测可能落在过场中间——换图尤其明显。链内窗口
        # 现在是 `WITHIN_ACTION_FRAMES`（2 秒），够不够读出换图后的画面没有验证过。
        if stop is not None and not is_decision_tail:
            obs, frame_png = self._perceive(ep, before.step)

        # 步骤 4：**给这一帧盖上它自己的步号**——它是"第 `before.step + 1` 步的
        # 开局画面"。`close_step` 拿它当新 `observation` 时步号只加一，两处必须
        # 同值（不变式 `observation.step == step`）；不同值的话 `(episode_id, step)`
        # 这个记忆键会从第二步起就错位，`before_frame`/`after_frame` 也跟着查错。
        obs = obs.model_copy(update={"step": before.step + 1})

        # 步骤 5：写这一键的观察账（`AFTER_ACTION`）——**账写在它的宿主里**：帧在
        # 本格产出，就挂在本格这条账上，不再转手给 `apply_stop`（那一格与感知无关，
        # 只为处置写账）。登记 `_frame_event_ids` 供 `StepMemory` 的 before/after 与
        # "链尾帧读回"用（登记的步号 = 这一帧是第 `before.step + 1` 步的开局画面）。
        event_id = self._trace.append(
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
            self._frame_event_ids[(ep, before.step + 1)] = event_id

        return {"pending_observation": obs, "pending_stop": stop}

    def apply_stop(self, state: EpisodeRunState) -> dict[str, Any]:
        """按 `stop` 的作废范围截队；**只在真的丢了键时**留一条 `ACTION_TRUNCATED`。

        改 `pending_presses` 一处；写一条账（可选的）——"截断了没有、丢了哪些键"是
        执行层处置自己的动作，与"这一键看到了什么"（上一格 `perceive_after_action`
        的 `AFTER_ACTION`）是两笔账：后者链内每键一条，前者**只在真丢键时**一条。

        **为什么"截断"要单独成账、而且是条件账**：`stop` 有三种（`blocked`/`warp`/
        `episode_over`），但**中止不等于截断**——`up×1 -> down×2` 里第一下撞墙时本段
        剩余为零，一个键都不用丢，链照常往下走。把 `stop` 挂在恒有值的字段上，读的
        人得自己判断"这条 stop 有没有兑现成动作"，"这一局被截断了几次"也只能靠重算。
        于是 `stop` 只进 `ACTION_TRUNCATED`（处置账），`AFTER_ACTION`（观察账）不带它
        ——"看到什么"与"据此处置了什么"分开（见
        `docs/spec/harness/PLAN_graph_readability.md` §3.7.2/§3.7.3）。

        **`stop` 为什么挂在这里、不挂 `ACT`**：`ACT` 写在按键那一刻，那时世界还没动，
        结果根本不存在（`PLAN_action_step_granularity.md` §5 的 v4 修订）。

        **帧不归这一格**（v7）：帧由 `perceive_after_action` 挂在自己的
        `AFTER_ACTION` 上，这一格只处置队列。

        **执行层不悄悄改写大脑交出来的链**：截断这件事由 `ACTION_TRUNCATED` 留痕
        （`stop` 另经 `StepMemory` 传给大脑），大脑下一步读得到，自己就能推出
        "在第 3 键撞墙了"。
        """
        assert state.observation is not None, "apply_stop before act"
        assert state.action is not None, "apply_stop without an action"
        assert state.pending_observation is not None, "apply_stop before perceive"
        action = state.action
        stop = state.pending_stop

        # 步骤 1：按作废范围截断队列。（`act` 已经弹掉队首，所以"队列空"就是
        # "刚按的这一个是链尾"。）
        presses = list(state.pending_presses)
        dropped: list[ActionSegmentFromBrain] = []
        if stop is StopReason.BLOCKED:
            # 本段剩余次数。展开之后同一段的键在队列里是连续的，而"这一下撞墙"
            # 意味着后面同方向的每一下撞的都是同一面墙（朝向已经就是那个方向，
            # 再按也不会动）——所以丢掉从队首起的整段同名键。丢得刚好够：
            # `up×4 -> down×2` 里第 2 个 up 撞墙 → 丢掉后面两个 up，`down` 照按。
            name = action.sequence[0].name
            while presses and presses[0].name == name:
                dropped.append(presses.pop(0))
        elif stop is not None:
            # `warp`（新地图上没规划过）与 `episode_over`（本局到点了）：整条链作废。
            dropped, presses = presses, []

        # 步骤 2：**只有真的丢了键才写这条处置账**——一个键都没丢时不写，"被截断了
        # 几次"于是可以直接数事件条数（数 `ACTION_TRUNCATED` 的条数）。
        if dropped:
            assert stop is not None, "dropped keys imply a stop reason"
            self._trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.ACTION_TRUNCATED,
                    episode_id=state.episode_id,
                    step=state.observation.step,
                    stop=stop.value,
                    dropped=dropped,
                )
            )
        return {"pending_presses": presses}

    # ---- 停摆检测、落库、关步——都读同一份 before/action/after，互不影响谁先跑 ----

    def detect_stall(self, state: EpisodeRunState) -> dict[str, Any]:
        """算这一步的停摆键与连续计数（L2 护栏），记一条 STALL_CHECK 快照。
        **改 `stall_key`/`stall_count` 两处状态字段 + 写一条账，不碰观测。**

        本步（动作 + `obs.stall_key()`）跟上一步全同 → 计数 +1，否则清零重计。
        达到 `STALL_LIMIT` 时的强制终止判断在下一轮 `judge`（它是图上唯一的
        终止判定节点），这里只算数、记快照。

        STALL_CHECK 快照的动机（每一步的构成过程可回看，不用重放整局）见
        `CHANGELOG.md` 2026-09-03 条目。
        """
        assert state.observation is not None, "detect_stall before record_observation"
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

    def store_step_episode_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """把 `act` 刚推进的这一步反思成一条情景记忆，落库。**不改状态字段，只落库记账。**

        情景记忆记"我在那种画面里选了什么"（一次经过）；`before`/`action`/
        `after` 都从 state 直接读，跟 `detect_stall`/`close_step`/
        `store_object_semantic_memory` 读的是同一份、互不影响谁先跑。
        """
        assert state.observation is not None, "store_step_episode_memory before record_observation"
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
        # 第 `before.step + 1` 步的开局画面（= 这一步做完动作后的画面，两次
        # 感知的 event_id 都登记在 `_frame_event_ids`，见该表与
        # `perceive_after_action` 的说明）。直接存 base64 的取舍见 `CHANGELOG.md`
        # 2026-09-05 条目。
        entry = self._brain_tool.reflect(
            FromHarnessToBrainToolReflectReq(before=before, action=action, after=after)
        ).entry.model_copy(
            update={
                "episode_id": ep,
                "run_id": self._run_id,
                # `stop` 由这里盖章，不在大脑里——"这一键之后为什么没有继续按键"
                # 是这一圈的结局，而 `reflect` 只看得见前后两帧（它算得出"撞墙了"
                # 却算不出"链被作废了"，那件事在 `perceive_after_action` 判完才成立）。
                "stop": state.pending_stop,
                # 同 `stop`：`reflect` 只看得见前后两帧，它不知道"这一键属于哪次决策"。
                # 归属是执行期的事（`think_action` 盖的 `plan_step_start`）。
                "plan_step_start": state.plan_step_start,
                "before_frame": self._frame_b64(ep, before.step),
                "after_frame": self._frame_b64(ep, before.step + 1),
            }
        )

        # 步骤 2：落库。
        self._memory.store_episode_step(FromHarnessToMemoryToolStoreEpisodeStepReq(entry=entry))
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
        assert state.observation is not None, (
            "store_object_semantic_memory before record_observation"
        )
        assert state.action is not None, "store_object_semantic_memory without an action"
        assert state.pending_observation is not None, "store_object_semantic_memory before act"
        ep, before, action, after = (
            state.episode_id,
            state.observation,
            state.action,
            state.pending_observation,
        )

        # 步骤 1：判定（kind 方法表）+ 落库，逐事件记 OBJECT_NOTE。
        events = object_fact_events(before, action, after, ep, before.step)
        if events:
            # 盖 run_id 章（落盘签名三元组之一），同 store_step 的 episode_id 盖章。
            self._memory.append_object_events(
                FromHarnessToMemoryToolAppendObjectEventsReq(
                    events=[e.model_copy(update={"run_id": self._run_id}) for e in events]
                )
            )
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

    def close_step(self, state: EpisodeRunState) -> dict[str, Any]:
        """把这一步**关上**：当前帧前进到刚感知的那一帧、步号加一。
        **改 `observation`/`step` 两处——"一步结束了"这一个判定的两面。**

        **扶正为什么并进这一格、又为什么排在这里**：`observation :=
        pending_observation` 是"这一步"的终点，不是"下一步"的起点；而它必须发生在
        两个 store **之后**——那两格要 `before`（`observation`）与 `after`
        （`pending_observation`）两帧同时在场，谁先扶正都会把 `before` 冲掉。而
        stores 之后紧接着的就是"这一步结束了"这个分叉（回 `act` 按下一键，还是回
        链首重新决策）——扶正与它是同一时刻的两面，所以并在这里，条件边也挂在
        这里（`PLAN_graph_readability.md` §3.4）。

        链内小循环每一步都经过它（`act → … → store_object → close_step → act`）；
        链尾那一次扶正之后回 `save_checkpoint`，下一个拿到 `observation` 的就是
        链首的 `record_observation`。

        不变式：`observation.step == step`——`perceive_after_action` 已经把
        `pending_observation.step` 盖成 `before.step + 1`（与本格算出的步号同值）。
        """
        assert state.pending_observation is not None, "close_step before any observation exists"
        # 步数推进也要留痕——"这一步关上"本身要有痕迹。
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.STEP_ADVANCE,
                episode_id=state.episode_id,
                step=state.step,
                next_step=state.step + 1,
            )
        )
        return {"observation": state.pending_observation, "step": state.step + 1}

    # ---- 收尾 ----

    def retrieve_verify_step_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查本局全部 step 记忆，交给 `retrieve_verify_knowledge`/`verify_and_summarize`。
        **图上单独一格，只改 `verify_step_entries` 一处**——跟主循环的
        `retrieve_step_episode_memory` 是同一个 level：查库单独成节点，不跟
        判定逻辑缝在一起。

        只在判完成的收尾分支上跑一次（不是每步）。没有 step 记忆时留空列表——
        下游路由据此直接结束这一局的收尾链。
        """
        assert state.observation is not None and state.done, (
            "retrieve_verify_step_memory before the episode finished"
        )
        ep, step = state.episode_id, state.observation.step
        entries = self._memory.query_episode_steps(
            FromHarnessToMemoryToolQueryEpisodeStepsReq(episode_id=ep)
        ).steps
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
        检索账单独记一条 `MEMORY_READ`（收尾路径没有 `merge_retrieval`
        可以顺路记账，这里自己记，否则 trace 看不出"校验器看到了什么知识"）。
        """
        assert state.observation is not None, "retrieve_verify_knowledge before judge"
        ep, step = state.episode_id, state.observation.step
        knowledge_result = self._memory.query_knowledge(
            FromHarnessToMemoryToolQueryKnowledgeReq(
                query=memory_query_utils.build_verify_knowledge_query(
                    state.verify_step_entries, state.task.goal
                ),
                limit=MEMORY_RECALL_LIMIT,
            )
        )
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
        # （`self._brain_tool.verify_and_summarize`）异常原样上抛，两层各管各的
        # 失败原因，不要混在一起。全量历史对应的截图（`StepMemory`
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
            result = self._brain_tool.verify_and_summarize(req)

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

        episode_memory = self._memory.store_episode_summary(
            FromHarnessToMemoryToolStoreEpisodeSummaryReq(memory=result.episode_memory)
        ).memory

        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.EPISODE_MEMORY_WRITE,
                episode_id=ep,
                step=step,
                memory=episode_memory,
            )
        )

        return {"verified_steps": verified}

    def close_episode(self, state: EpisodeRunState) -> dict[str, Any]:
        """**本局收尾**：算结算写进 `state.outcome`，并落一条 `EPISODE_END`。

        收尾链的每一条分支都汇到这一格（见 `episode/graph.py`）——没有 step
        记忆时从 `retrieve_verify_step_memory` 直接跳过来，有记忆时跟在
        `verify_and_summarize` 后面。

        **为什么它必须是图内的一个节点**（D2-④）：`outcome` 是父子图交界上的
        **输出键**——父侧 `RunState.outcome` 与它同名同型。而父子图按**键名交集**
        传递（F1）：子图不输出的键，父侧**保持旧值且不报错**。所以"下结论"若留在
        图外（早先的 `_close` 就在图外），`reflect` 读到的是**上一次派发的陈旧
        结算**——一个不炸的错。

        它只算账：`done`/`success` 是 `judge` 的产物，`obs.step` 是画面维度的
        坐标，`stall_count` 是停摆护栏——本格一个都不改。
        """
        obs = state.observation
        assert obs is not None, "close_episode before an observation exists"
        outcome = FromRunHarnessToEpisodeHarnessRunResp(
            episode_id=state.episode_id,
            success=state.success,
            steps=obs.step,
            reason=episode_utils.derive_episode_reason(
                state.success,
                obs.step,
                state.task.max_steps,
                stalled=state.stall_count >= STALL_LIMIT,
            ),
        )
        self._trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.EPISODE_END,
                step=outcome.steps,
                episode_id=state.episode_id,
                outcome_episode=outcome,
            )
        )
        return {"outcome": outcome}
