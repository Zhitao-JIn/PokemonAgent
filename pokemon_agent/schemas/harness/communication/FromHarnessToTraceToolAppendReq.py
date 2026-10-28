"""harness → `TraceTool` 的记账请求协议：`FromHarnessToTraceToolAppendReq`。

harness 只负责组装——从这一步手头的领域对象里挑出本笔账需要的字段、声明
`kind` 与 **`meta`**（签名信息）；tool 对 req 做处理（按 kind 渲染 `content`、
必要时一拆多），模块（`TracePort` 的实现）只收**裸参数**：
`type` / `kind` / `meta` / `content`（加可选的 `started_at` / `ended_at`）。

**`kind` 与落盘 `kind` 逐字同值**（0914 去翻译表）：渲染层不再改它的名字，
`req.kind` 一路落到封套上。所以本枚举就是账名词表，见
`schemas/harness/domain/trace_kind.py`。

**`meta` 是一个语义成分，不是三个公共字段的拼装结果**（0914 跟进）：封套上那个
`meta`（`{run_id, branch, source, episode_id, task_id, step}`）是 harness 的
**签名信息**——harness 在 `req.meta` 里一次交齐 `source` / `episode_id` /
`task_id` / `step` 四件，`run_id` / `branch`（执行线标识）由 tool 层在 append
时盖（`TraceTool.append` → `_stamp_meta`）——它不该由 tool 从三个散着的公共
字段现拼：那样 `meta` 的内容就归了 tool，harness 想多签一样东西都没有地方放。

**按 `kind` 分派、不按领域对象类型分派**：同一个类型产出不同事件——
`ModelCall` 可以是决策账单（attempt）/判定账单（why）/校验账单（verdicts），
`ActMemory` 写成一条（`entry`）或按坐标列个清单（`refs`）；
类型名决定不了格式，"这是哪笔账"只有调用方知道。

各 kind 必填的字段见 `direct/trace/render.py` 每个渲染函数入口的 assert；
`content` 的字段名是跨模块契约（观测台前端按字段名渲染），变更权在 tool 层。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from pokemon_agent.brain.interface import (
    Action,
    Decomposition,
    Goal,
    RunPlan,
    Task,
    VerifyVerdict,
)
from pokemon_agent.schemas.harness.domain import TraceKind
from pokemon_agent.schemas.harness.domain.checkpoint_mark import CheckpointMark
from pokemon_agent.schemas.harness.domain.episode_io import EpisodeOutput
from pokemon_agent.schemas.harness.domain.goal_entry import GoalEntry
from pokemon_agent.schemas.harness.domain.review_mark import ReviewMark
from pokemon_agent.schemas.harness.domain.task_entry import TaskEntry
from pokemon_agent.schemas.harness.domain.task_io import TaskOutput
from pokemon_agent.schemas.harness.domain.termination import Termination
from pokemon_agent.schemas.memory import (
    ActMemory,
    EpisodeMemory,
    RunMemory,
    TaskMemory,
)
from pokemon_agent.world import Observation, RamReadout, TaskObservation

from .ModelCall import ModelCall
from .RunResp import RunResp


class FromHarnessToTraceToolAppendReq(BaseModel):
    """一笔 trace 账的组装结果：签名信息（`meta`）+ 按 kind 取用的领域对象。

    **必填的两件**：`kind`（哪本账）与 `meta`（签名信息，见下）；
    其余字段全部可选，按 kind 取用，多余字段留着无妨（渲染函数只读自己那几个）。

    **落盘形状**（0914 封套改造，2026-09-27 双时刻、0928 325 加 `seq`）：

    ```
    {uuid, seq, kind, type, started_at, ended_at, meta, content}  ← 封套八件
    meta    = {run_id, branch, source, episode_id, task_id, step}  ← JSON 字符串
              （run_id / branch 由 tool 层盖，其余四件由 harness 交齐）
    content = 该账的正文                            ← JSON 字符串
    ```

    `meta` / `content` 一律是 **JSON 字符串**（需要一层转义），读端
    `json.loads` 回来——判据是"存在反函数"：能从这串字符无损还原出源记录的字段。

    `error`：异常的字符串快照（`f"{type(exc).__name__}: {exc}"`），由调用方
    组装——Exception 对象进不了 Pydantic 模型，也没必要进。
    """

    kind: TraceKind

    meta: dict[str, Any]
    """**这条账的签名信息**——封套 `meta` 的本体：harness 一次交齐四件，tool 层
    再盖两件执行线标识，合起来六件。

    harness 交的四件（run 级账沿用项目约定——`episode_id` 位放 `run_id`、step 恒 0）：

    ```
    {"source": "发这条账的位置", "episode_id": "…", "task_id": "…", "step": 3}
    ```

    - **`source`**：图上单元名（`store_step_episode_memory`、`summarize_episode`、
      `run.act`…）或**图外入口名**（`run_entry.new_run` / `episode_entry.begin_episode` /
      `task_entry.begin_task`）。`kind` 只回答"哪本账"，回答不了"谁写的"——
      `write_episode_memory` 有**三个**生产者，账上不分这几笔就只能靠猜。**别和
      `KnowledgeRecord.source` 混**：那个是"这条知识出自哪一局"，是记录自己的
      元数据；这个说的是"这条 trace 由谁写出"，两处同名不同层。
    - **`episode_id` / `step`**：这条账发在哪一局、哪一步。判据侧
      （`node_io._check_meta`）核"恰好六件"（存档 / 恢复账另加 `checkpoint_id`）——
      多签的东西要先进判据，不是自由槽。

    **`run_id` / `branch` 不在这里**：它们是执行线标识，由 tool 层在 append 时盖
    （`TraceTool.append` → `_stamp_meta`，排在头两个）；trace 后端对这两个键
    零持有、只透传。调用方带了就当场炸（`TraceTool.append` 入口 assert——
    同一件事说两遍）。

    **为什么由 harness 交齐、而不是 tool 拿三个公共字段拼**（0914 跟进）：`meta`
    是封套的语义成分，内容归 harness；拆成三个公共字段再由 tool 现拼，等于把
    "签名里有什么"的决定权交给了 tool，harness 想多签一样东西都没有地方放。"""

    # ---- 通用账目字段 ----
    calls: list[ModelCall] | None = None
    """这条账涉及的**全部模型调用**，按发生顺序（重试链就是每次尝试一条）。

    **为什么是列表而不是单条**：写账的节点拿到的是"整条重试链"（`resp.calls` /
    `exc.calls`），tool 渲染时逐条落成 `*_call` 账——账在语义上从来不是一条，
    只是此前恰好只有一条值得记。列表化之后"重试了 3 次"这件事由**账的条数
    与顺序**直接回答（0914 跟进删 `attempt` 戳）。"""
    why: str | None = None
    judge_reason: str | None = None
    error: str | None = None
    link: str | None = None
    """**这条错误账属于哪条链**（`sense` / `choose` / `plan` / `decompose` /
    `judge` / `verify` / `summarize` / `summarize_task`）——`CALL_FAILED` / `CALL_EXHAUSTED`
    两条错误账靠它分开"是哪条链出的错"。

    **为什么不并进 `kind`**：一个 kind 只答"这是什么账"。三条错误账
    （`call_failed` / `call_exhausted` / `summary_parse_error`）是**三种失败
    模式**，链路是另一个维度——合成 15 个 kind（`decide_failed`…）会让词表
    膨胀三倍，而"按失败模式聚合"这个更值钱的切法会被埋掉。"""

    # ---- 边界 / 结算 ----
    task: Task | None = None
    run_goals: list[Task] | None = None
    """run 级边界的初始目标栈（`sense_frame` 的 goals 是 Goal，
    两处词表不同，各用各的字段）。"""
    outcome_run: RunResp | None = None
    outcome_episode: EpisodeOutput | None = None
    outcome_task: TaskOutput | None = None
    run_goal: Goal | None = None
    """run 级总目标（`run_start` 带）。"""
    total_acts: int | None = None
    """task 的局内累计键数快照（`task_start` 带）。"""

    # ---- 决策 / 观测 ----
    obs: TaskObservation | Observation | None = None
    goals: list[Goal] | None = None
    action: Action | None = None
    names: list[str] | None = None

    # ---- 记忆 ----
    count: int | None = None
    """**已废（0914 跟进）——留成墓碑，理由同 `meta`。**

    它做过"检索器承诺命中几条"的第二个来源，与 `refs` 组成"承诺 vs 清单"的
    交叉校验。但六条读口**交上来的永远是 `len(<同一个集合>)`**——`read_step` 数
    `memories`、`read_episode_memory` 数 `episode_memories`、两条 knowledge 数 `contents`
    （与 `sources` 成对产出、恒等长）、
    `read_verify_step` 数 `entries`。两份来源其实是同一份，于是它成了纯粹派生。
    `refs` 改成数组之后，长度直接数得出来——`retrieve_node` 不再读本字段，
    判据侧（`node_io`）也不再核它。**留着槽**是为了让还按老路传 `count=` 的调用方
    当场炸，而不是被 Pydantic 静默丢掉。"""
    query: str | None = None
    """这一次检索**问的是什么**——调用方原样交出它交给记忆读口的检索条件。

    两种形状，取决于这一路怎么查（见 `render.retrieve_node` 的表）：
    **等值过滤**写成 `k=v k=v`（`episode_id=…` / `run_id=…` / `map_id=… before_step=…`），
    **BM25 检索词**原样记那一串文本（`scene:… overlay:… 目标：…`，它本来就带空格）。

    为什么非记不可：命中为空时，只有它能把"**检索条件写错了**"和"**库里真没有**"
    分开——一个空清单本身只是后者的候选证据，不是结论。模型调用记了完整 prompt，
    检索这边对应的就是它。"""
    started_at: float | None = None
    """（2026-09-27 双时刻定案）这次**操作真实开始**的 wall clock（`time.time()`）。

    只有两类账有真实操作时长、也只由它们的调用点记：模型调用（`brain.py` 在
    provider `complete()` 前后取时，进每条 `ModelCall.payload`）与六条读口的
    检索（检索节点在 MemoryTool 查询前后取时，进本字段）。其余账不记——
    落盘层补 `start = end =` 记账时刻，封套里没有独立于操作时间的记账时刻。"""
    ended_at: float | None = None
    """操作结束时刻；**排序键的一半**（`(ended_at, seq)` 升序）。见 `started_at`。"""
    timings: dict[str, float] | None = None
    """检索的**分段耗时**（秒，`prepare`/`bm25`/`vector`/`rrf`/`rerank`）——只有
    `read_knowledge` 带（0928 324，随检索返回值从 memory 模块带出），其余读口
    不计时、省略这个键（等值过滤没有分段可言）。渲染进 content 的 `timings` 键；
    **不参与排序**——排序唯一依据是 `(ended_at, seq)`，分段耗时只是观测数据。"""
    refs: list[str] | None = None
    """命中的**是谁**——每一条一个字符串（`render.retrieve_node` 原样转发）。

    六条读口共用这一个形状，**每一路各拼各的"标识长什么样"**（0914 跟进）：

    | 读口 | 一条 `refs` 是什么 |
    |---|---|
    | `read_step` / `read_verify_step` | `"(episode_id, step)"` 坐标 |
    | `read_episode_memory` | 跨局摘要的 `episode_id` |
    | `read_knowledge` / `read_verify_knowledge` | 命中记录的 `source` 文件名 |

    **它是数组，不是拼成一行的字符串**（0914 跟进）：`content` 已经是 JSON，
    把清单压成 `"a b c"` 只会把分词规则转嫁给每个读它的人——判据侧曾为此维护一张
    "哪条读口按什么数条数"的表，而 `read_knowledge` 的 5 个文件名一个括号都没有，
    把"一律数括号"那条判据当场打成假警。命中为空就是空数组（`[]`），不是特例。"""
    entry: ActMemory | None = None
    memory: EpisodeMemory | TaskMemory | RunMemory | None = None
    """RunMemory 为 run 收尾蒸馏的存储形状，供 write_run_memory 写账。"""
    reason: str | None = None

    # ---- 判定 / 校验 / 规划结论 ----
    verdicts: list[VerifyVerdict] | None = None
    checked: int | None = None
    negative: int | None = None
    pushed: list[str] | None = None
    termination: Termination | None = None
    """本层机械终止类别（`judge_verdict` 带；未判停为 None）。"""
    fail_streak: int | None = None
    """连续失败计数（episode / run 的 `judge_verdict` 与 `settle_goal` 带）。"""
    updates: list[dict[str, str]] | None = None
    """规划对已有目标的表态（`plan_verdict` 带）：`{task_id, status, note}`。"""
    planning: RunPlan | Decomposition | None = None
    planning_round: int | None = None
    decision: str | None = None
    judge_trigger: str | None = None
    execution_order: list[str] | None = None
    entry_id: str | None = None
    tasks: list[Task] | None = None
    """拆解出的任务链（`decompose_verdict` 带），`task_id` 已由 harness 编好。"""
    goal: GoalEntry | None = None
    task_entry: TaskEntry | None = None
    abandoned: list[str] | None = None
    """刚盖完章的目标表行（`settle_goal` 带）。"""
    audit: str | None = None
    """人审表态：`accept` / `overturn`（`settle_goal` / `settle_task` / `judge_verdict` 带）。"""

    # ---- 图控制记账 ----
    stall_key: str | None = None
    stall_count: int | None = None
    text: str | None = None
    next_step: int | None = None
    frame: str | None = None
    """这一帧的**原始画面**（base64 PNG），由观察账（`sense_frame`）
    随正文一起带——调用方用刚取到的那一帧，**没有就是省略这个键**
    （不写 `null`：漏交写 `null` 会让判据侧把"没读"当成一个空词静默放过）。

    0914 曾把事件自带的图整条删掉、改由 `memory/step_memory/` 当真源；同日跟进又
    请回来——**replay 只看 trace 就该看得到画面**，而 RAM 档感知本来就照截帧，
    每个键都有图可带。写口（`write_step`）的正文里仍然**不收**帧（那四本账
    一个 `frame` 都不该有，见 `node_io._WRITE_FORBIDDEN_KEYS`）。"""
    ram: RamReadout | None = None
    """这一帧的**内存读数**，由观察账（`sense_frame`）随正文一起带；没有就省略这个键。
    只给测评读真值用，不进 agent 的任何输入（`docs/eval/spec.md` W2）。"""

    human_note: str = ""
    """这条链是在哪一句**人类插话**之下产出的（空串 = 没被插话）。

    0914 控制台改造后它挂在 `THINK` 上——插话的唯一落点是决策那一格
    （`press_key` 自己没有 LLM 调用），所以"人说了什么"天然属于那条链的账。"""
    checkpoint: CheckpointMark | None = None
    """存档三本账（`checkpoint_*`）的素材。"""
    report: dict[str, Any] | None = None
    """脚本执行账（`act_call` script 形）的素材：脚本终态报告
    （`{ok, code, data, events, calls}` 的 JSON 形状）原样。"""
    review: ReviewMark | None = None
    """问人两本账（`review_inject` / `review_audit`）的素材。"""
