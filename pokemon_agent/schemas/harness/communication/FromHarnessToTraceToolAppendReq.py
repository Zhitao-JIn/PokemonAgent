"""harness → `TraceTool` 的记账请求协议：`FromHarnessToTraceToolAppendReq`。

harness 只负责组装——从这一步手头的领域对象里挑出本笔账需要的字段、声明
`kind` 与 **`meta`**（签名信息）；tool 对 req 做处理（按 kind 渲染 `content`、
必要时一拆多），模块（`TracePort` 的实现）只收**三个裸参数**：
`type` / `kind` / `meta` + `content`。

**`kind` 与落盘 `kind` 逐字同值**（0914 去翻译表）：渲染层不再改它的名字，
`req.kind` 一路落到封套上。所以本枚举就是账名词表，见
`schemas/harness/domain/trace_kind.py`。

**`meta` 是一个语义成分，不是三个公共字段的拼装结果**（0914 跟进）：封套上那个
`meta`（`{run_id, source, episode_id, step}`）是 harness 的**签名信息**，内容由
harness 在 `req.meta` 里一次交齐，tool 原样转发（`run_id` 由落盘层盖）——
它不该由 tool 从三个散着的公共字段现拼：那样 `meta` 的内容就归了 tool，
harness 想多签一样东西都没有地方放。

**按 `kind` 分派、不按领域对象类型分派**：同一个类型产出不同事件——
`ModelCall` 可以是决策账单（attempt）/判定账单（why）/校验账单（verdicts），
`ActMemory` 写成一条（`entry`）或按坐标列个清单（`refs`）；
类型名决定不了格式，"这是哪笔账"只有调用方知道。

各 kind 必填的字段见 `tools/trace/render.py` 每个渲染函数入口的 assert；
`content` 的字段名是跨模块契约（观测台前端按字段名渲染），变更权在 tool 层。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from pokemon_agent.brain.interface import (
    Action,
    Goal,
    Task,
    VerifyVerdict,
)
from pokemon_agent.schemas.harness.domain import TraceKind
from pokemon_agent.schemas.harness.domain.episode_io import EpisodeOutput
from pokemon_agent.schemas.harness.domain.goal_entry import GoalEntry
from pokemon_agent.schemas.harness.domain.task_entry import TaskEntry
from pokemon_agent.schemas.harness.domain.task_io import TaskOutput
from pokemon_agent.schemas.harness.domain.termination import Termination
from pokemon_agent.schemas.memory import (
    ActMemory,
    EpisodeMemory,
    ObjectFactEvent,
    TaskMemory,
)
from pokemon_agent.world import Observation

from .ModelCall import ModelCall
from .RunResp import RunResp


class FromHarnessToTraceToolAppendReq(BaseModel):
    """一笔 trace 账的组装结果：签名信息（`meta`）+ 按 kind 取用的领域对象。

    **必填的两件**：`kind`（哪本账）与 `meta`（签名信息，见下）；
    其余字段全部可选，按 kind 取用，多余字段留着无妨（渲染函数只读自己那几个）。

    **落盘形状**（0914 封套改造）：

    ```
    {uuid, kind, type, ts, meta, content}          ← 封套四件 + 标签 + 正文
    meta    = {run_id, source, episode_id, task_id, step}  ← JSON 字符串；run_id 由 store 盖
    content = 该账的正文                            ← JSON 字符串
    ```

    `meta` / `content` 一律是 **JSON 字符串**（需要一层转义），读端
    `json.loads` 回来——判据是"存在反函数"：能从这串字符无损还原出源记录的字段。

    `error`：异常的字符串快照（`f"{type(exc).__name__}: {exc}"`），由调用方
    组装——Exception 对象进不了 Pydantic 模型，也没必要进。
    """

    kind: TraceKind

    meta: dict[str, Any]
    """**这条账的签名信息**——封套 `meta` 的本体，由 harness 一次交齐。

    恰好四件（run 级账沿用项目约定——`episode_id` 位放 `run_id`、step 恒 0）：

    ```
    {"source": "发这条账的位置", "episode_id": "…", "step": 3}
    ```

    - **`source`**：图上单元名（`store_step_episode_memory`、`summarize_episode`、
      `run.act`…）或**图外入口名**（`run_entry.new_run` / `episode_entry.begin_episode` /
      `task_entry.begin_task`）。`kind` 只回答"哪本账"，回答不了"谁写的"——
      `write_episode_memory` 有**三个**生产者，账上不分这几笔就只能靠猜。**别和
      `KnowledgeRecord.source` 混**：那个是"这条知识出自哪一局"，是记录自己的
      元数据；这个说的是"这条 trace 由谁写出"，两处同名不同层。
    - **`episode_id` / `step`**：这条账发在哪一局、哪一步。判据侧
      （`node_io._check_meta`）核"恰好四件"——多签的东西要先进判据，不是自由槽。

    **`run_id` 不在这里**：它是落盘实例的标识（构造 `LocalTrace` 时给的），只有
    落盘那一层知道（`store._stamp_run_id` 盖，调用方带了就当场炸）。

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
    input: str | None = None
    """结论账（`choose_verdict` / `judge_verdict` / `verify_verdict` / `plan_verdict`）附带的
    **发给模型的请求原文**——取自那次成功调用的 `payload.prompt`。结论与它是同一次
    调用的两个面，放在一起才不必跳到调用账对读。`plan` 无模型路径交 `None`，
    正文里就不出现这两个键。"""
    output: str | None = None
    """同 `input`，是模型吐回的**原文**（`payload.raw`）。"""
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
    start_step: int | None = None
    """task 的全局键号基数（`task_start` 带）。"""

    # ---- 决策 / 观测 ----
    obs: Observation | None = None
    goals: list[Goal] | None = None
    action: Action | None = None
    names: list[str] | None = None

    # ---- 记忆 ----
    count: int | None = None
    """**已废（0914 跟进）——留成墓碑，理由同 `meta`。**

    它做过"检索器承诺命中几条"的第二个来源，与 `refs` 组成"承诺 vs 清单"的
    交叉校验。但六条读口**交上来的永远是 `len(<同一个集合>)`**——`read_step` 数
    `memories`、`read_episode_memory` 数 `episode_memories`、两条 knowledge 数 `contents`
    （与 `sources` 成对产出、恒等长）、`read_object_memory` 数 `events`、
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
    refs: list[str] | None = None
    """命中的**是谁**——每一条一个字符串（`render.retrieve_node` 原样转发）。

    六条读口共用这一个形状，**每一路各拼各的"标识长什么样"**（0914 跟进）：

    | 读口 | 一条 `refs` 是什么 |
    |---|---|
    | `read_step` / `read_verify_step` | `"(episode_id, step)"` 坐标 |
    | `read_episode_memory` | 跨局摘要的 `episode_id` |
    | `read_knowledge` / `read_verify_knowledge` | 命中记录的 `source` 文件名 |
    | `read_object_memory` | 物体格键 `12:13:8`（`PlaceInWorld.key`） |

    **它是数组，不是拼成一行的字符串**（0914 跟进）：`content` 已经是 JSON，
    把清单压成 `"a b c"` 只会把分词规则转嫁给每个读它的人——判据侧曾为此维护一张
    "哪条读口按什么数条数"的表，而 `read_knowledge` 的 5 个文件名一个括号都没有，
    把"一律数括号"那条判据当场打成假警。命中为空就是空数组（`[]`），不是特例。"""
    entry: ActMemory | None = None
    memory: EpisodeMemory | TaskMemory | None = None
    event: ObjectFactEvent | None = None
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
    tasks: list[Task] | None = None
    """拆解出的任务链（`decompose_verdict` 带），`task_id` 已由 harness 编好。"""
    goal: GoalEntry | None = None
    task_entry: TaskEntry | None = None
    abandoned: list[str] | None = None
    """刚盖完章的目标表行（`settle_goal` 带）。"""
    audit: str | None = None
    """人审表态：`accept` / `overturn`（`settle_goal` 带）。"""

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

    human_note: str = ""
    """这条链是在哪一句**人类插话**之下产出的（空串 = 没被插话）。

    0914 控制台改造后它挂在 `THINK` 上——插话的唯一落点是决策那一格
    （`press_key` 自己没有 LLM 调用），所以"人说了什么"天然属于那条链的账。"""
