"""episode 图的唯一状态载体：`EpisodeRunState`。

从 `harness/interface/episode_harness_port.py` 搬来（`PLAN_graph_composition.md` §6 步 0）——
**状态不是能力**，`interface/` 只回答"harness 需要外面给什么"，不再回答"harness 自己长什么样"。
那个 Port 文件已在步 4 删除（D5：它是"镜子"不是"港口"），所以旧的
`episode_harness_port` 路径不再存在——唯一的家就是这里。

步 0 的两处内容变更（其余一字未动）：

1. `goals` → `episode_goals`（D2-①）。它是 run 级目标栈在**本层**的投影视图，
   与父侧 `RunState.goals`（"目标栈"这个领域概念）是两个东西，键名必须分开——
   父子图交界按**键名逐字对上**传递（F1），同名不同型会当场 `ValidationError`（F2）。
2. 新增 `outcome`（D2-④）。原先结论由 `run()` 在图跑完之后算，图内没有它的位置；
   加了 `close_episode` 节点之后，**结论必须由子图自己写出**——否则父侧读到的是
   上一轮的陈旧值，而且不报错（F1 的反作用）。
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pokemon_agent.brain import (
    Action,
    ActionSegment,
    Goal,
    Task,
)
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryKnowledgeResp,
    FromRunHarnessToEpisodeHarnessRunResp,
)
from pokemon_agent.schemas.memory import EpisodeMemory, StepMemory, StopReason
from pokemon_agent.world import ActionSpace, Observation


class EpisodeRunState(BaseModel):
    """一局的**全部**可序列化状态。

    分两组，但两组都在这里——分组只是为了读的人知道哪些跨步、哪些不跨：

        身份    episode_id / task / step / episode_goals   跨步，checkpoint 要的就是它
        流转    observation / action_space / action / pending_observation /
                step_episode_memories / global_episode_memories /
                knowledge_semantic_memory / object_semantic_memory
                单步内，从一个节点传到下一个
        决策    plan / pending_presses / pending_stop / plan_step_start   决策内小循环，
                跨 1..N 步（随 checkpoint dump，恢复后接着把剩下的键按完）
        结论    outcome   整局收尾，由 `close_episode` 写

    **`outcome` 在这里**（D2-④）：它是这一局的最终结论（success/steps/reason），
    由 `close_episode` 节点从 `observation` 与 `success` 算出并写进 state——这样
    父子图交界上"episode 还 run 什么"就有一个**逐字对得上的键**（父侧 `RunState.outcome`
    与它同名同型）。放在图外算的话，子图不输出该键，父侧会静默保留上一轮的旧结算。

    **`episode_goals` 全程只读**（键名见模块 docstring 第 1 条）。它是 run 级目标栈的
    投影——给大脑的全局信息（知道自己在全局的哪个位置），本 episode 只判栈顶
    `episode_goals[-1]`，判成即本局结束；弹栈/压栈是 run 级 `reflect` 的事，这里不碰。

    **活对象一个都不进来**（world / tools / brain / trace）：它们序列化不了，
    进来就把整个状态变成不可存的。它们是 `HarnessDeps` 的字段，由装配处注入。
    """

    episode_id: str = Field(description="这一局的标识，全局唯一。trace 按它分组")
    task: Task = Field(description="在跑哪个任务。目标、判据、步数上限都在里面")
    step: int = Field(
        default=0,
        description="跑到第几步。**全项目只有这一个 step，单位是一次小 action（一个键）**"
        "——粒度下沉之后链内每一键各占一步，只有链首那一键烧一次决策调用与一次视觉感知"
        "（链内只读 RAM）。所以 `task.max_steps` 是**一道以『游戏里按了多少键』计价的闸**："
        "它不随链长波动（这正是选它的理由），代价是链长一上去、同一数值下的活动圈数就"
        "变小——这个换算是 2026-09-11 重标定的，算术与实测见 "
        "`experiment/tasks.py` 里 `knowledge_recall_tasks()` 的说明",
    )
    episode_goals: list[Goal] = Field(
        default_factory=list,
        description="目标栈在**本层的投影**（run 级 `RunState.goals` 由 `dispatch` 投影而来）。"
        "**判只判栈顶 `episode_goals[-1]`**，其余层是给大脑的全局信息——知道最终目标是什么、"
        "自己在哪一层",
    )

    observation: Observation | None = None
    """**当前帧**：`close_step`（每步的终点）扶正过来的那一帧——"这一步的 before"。

    带着它自己的步号，且恒等于 `step`（不变式 `observation.step == step`：
    `perceive_after_action` 给新帧盖 `before.step + 1`，`close_step` 同时把 `step` 加一）。
    开局那一帧不走 `close_step`，由 `_begin` 直接产出（`step = 0`）。

    **在本圈里的语义是"这次按键之前的那一帧"**：`perceive_after_action` 拿它当判中止
    的 `before`，两个 store 拿它跟 `pending_observation` 凑成 `before`/`after`
    反思记忆，`act` 拿它当 `execute` 的掩码依据。链边界上的节点（四路 `retrieve_*`/
    `merge_retrieval`/`think_action`/`judge`）读的也是它——那时它就是这一帧。
    """
    action_space: ActionSpace | None = None
    step_episode_memories: list[StepMemory] = Field(
        default_factory=list,
        description="`retrieve_step_episode_memory` 查出来的、给这一步 `think_action` 用的"
        "本局单步情景记忆。**不折进 observation**——`think_action` 直接拿这份列表"
        "拼 `ChooseOnceReq.memories`",
    )
    global_episode_memories: list[EpisodeMemory] = Field(
        default_factory=list,
        description="`retrieve_global_episode_memory` 查出来的跨局摘要记忆"
        "（按场景 + 任务目标）。**不折进 `observation.facts`**——`think_action`"
        "直接拿这份列表渲染成文本，拼 `ChooseOnceReq.episode_memories`（prompt 里"
        "单独一节、单独给可信度说明，不跟这一帧的真实数据混在一起）",
    )
    knowledge_semantic_memory: FromHarnessToMemoryToolQueryKnowledgeResp | None = None
    """`retrieve_knowledge_semantic_memory` 查出来的知识库结果（内容 + 来源）。
    **不折进 `observation.facts`**——`think_action` 直接拿 `.contents` 拼
    `ChooseOnceReq.knowledge`（prompt 里单独一节）；`merge_retrieval` 仍会用它
    算 `knowledge_text` 记一条 `MEMORY_READ`。`None` = 这一步还没查（图上未终止分支
    必经，只在没走到这一格时才是 None，比如刚开局那一帧）。"""
    object_semantic_memory: str = ""
    """`retrieve_object_semantic_memory` 查出来的语义记忆（object：这张地图上
    互动过的东西）。**仍然**由 `merge_retrieval` 折进 `observation.facts`——
    它跟 `walk_map`/`landmarks` 一样坐标锚定在这张地图上，可信度同级，
    不像 `knowledge`/`global_episode_memories` 那样是跨场景/跨局的检索结果。"""

    action: Action | None = None
    """本圈真正交给世界的那一个动作。**恒为单键**（单段、`times=1`）——
    它由 `act` 从 `pending_presses` 队首派生，带的是 `plan` 的 thought 与
    所在段的 rationale。`reflect`/trace/停摆检测都只认它，所以它们全都不用
    知道"决策"这个概念存在。"""

    plan: Action | None = None
    """**这一次决策交出的整条动作序列**（`think_action` 产出）。

    它是**循环状态，不是记忆字段**——`StepMemory` 一律不含决策归属
    （归属规则见 `docs/spec/harness/PLAN_action_step_granularity.md` §4）。留在这里的理由
    只有一个：`act` 每圈要拿它的 `thought` 去派生单键动作。

    **序列原文的权威位置仍是 trace**（`THINK` payload 的 `sequence`），这里存的
    是执行期要用的那一份，不做任何对外承诺；恢复 checkpoint 时它随 dump 回来，
    于是"按到一半被杀"能接着把剩下的键按完。
    """
    pending_presses: list[ActionSegment] = Field(
        default_factory=list,
        description="把 `plan.sequence` 按 `times` **展开成「一键一段」的待按队列**"
        "（每段 `times=1`、带着它所属那一段的 rationale）。`act` 每圈弹队首；"
        "队列空 = 这一次决策的键全按完了，回到链首重新决策。`apply_stop` 判出中止时"
        "按作废范围截断它（`blocked` 丢掉本段剩余同名键/`warp`、`episode_over` 清空）",
    )
    pending_stop: StopReason | None = None
    """**刚按下的这一键的结局**——`perceive_after_action` 判出、`store_step_episode_memory`
    盖进那条记忆。跟 `pending_observation` 一样是"还没被消费的新鲜结果"：
    它活不过 `store_object_semantic_memory`（下一个 `act` 之前就被用掉了）。
    `None` = 没有异常（要么背后还有待按的键，要么它本来就是链尾）"""

    plan_step_start: int | None = None
    """**这一键属于哪一次决策**——那次决策落在第几步（`think_action` 设）。

    这里是它的**权威来源**：决策一次盖一次，`store_step_episode_memory` 从它抄进
    那条记忆的 `plan_step_start`（同一个字段的两半——state 这份给执行期用，记忆那份
    给渲染/取窗用）。归属判据、以及"它为什么不是决策字段"，写在
    `StepMemory.plan_step_start` 上。

    `None` 只在"从旧 checkpoint dump 恢复"时出现（那时还没有这个字段）；记忆侧
    按 `step` 兜底（一次决策一个键），执行不受影响。
    """

    pending_observation: Observation | None = None
    """**刚感知到、还没扶正的那一帧**——本圈的 `after`。等 `close_step` 把当前帧
    推到它身上。

    来源：每一帧都由 `perceive_after_action` 从按键后的那次感知收下（**全项目只有这
    一处产观测**，harness 自己不主动感知；开局那一帧不走这里，它由 `_begin` 直接
    产出成 `observation`）。它在这一圈里当作 `after` 的那份快照被
    `detect_stall`/`store_step_episode_memory`/`store_object_semantic_memory` 读；
    本圈末尾的 `close_step` 把它扶正成 `observation`，当作下一圈的 `before`。
    """
    stall_count: int = 0
    """L2 护栏：连续多少步"动作与画面机械状态都没有任何变化"。
    `detect_stall` 里比较本步（动作 + `obs.stall_key()`）与上一步：全同 +1，
    否则清零；达到 `STALL_LIMIT` 时的强制终止判断在下一轮 `judge`（不是这里）。"""
    stall_key: str | None = None
    """上一步的停摆键（`obs.stall_key()` + 动作描述拼成），供本步比较；
    None = 还没有可比的历史步（开局第一帧）。"""

    done: bool = False
    """这一局该不该结束——`judge` 综合三类机械条件（世界结束/步数用尽/停摆）
    +（不管前三类是否已成立都会问一次的）模型判定后给出的结论。**不在
    `Observation.done` 上**：那个字段是世界层自己的信号
    （窗口关没关），这个才是 harness 的终止裁决，两者语义不同，硬塞进同一个
    字段名会让"是不是被 judge 改过"变得含糊。跟 `stall_key`/`stall_count`
    一样，只有 `judge` 改它。"""
    success: bool = False
    """任务是否达成。**只在 `done` 为 True 时有意义**，否则恒为 False——
    唯一来源是 `judge` 里模型给出 `verdict.done=True` 那一刻，跟世界层、
    机械终止条件都无关。不占 `Observation.success`，
    理由同上：世界本来就不该有"任务算不算完成"这个概念，那是 harness 的
    判断，不是观测的一部分。"""

    outcome: FromRunHarnessToEpisodeHarnessRunResp | None = None
    """**本局结算**（D2-④）：`close_episode` 从 `success`/`observation.step`/`task.max_steps`/
    `stall_count` 算出并写进这里，同时落一条 `EPISODE_END`。

    它是**父子交界上的输出键**——父侧 `RunState.outcome` 与它同名同型，子图的这一份
    合并回父 state 供 `reflect` 弹栈/重试。`None` 只在没跑到 `close_episode` 时出现，
    而收尾链的每条分支都经过它，所以图跑完时恒非 None（`_close` 里对此有断言）。
    """

    verify_step_entries: list[StepMemory] = Field(
        default_factory=list,
        description="`retrieve_verify_step_memory` 查出来的本局全部 step 记忆——"
        "只在判完成的收尾分支上有意义。空列表 = 没有 step 记忆（或查询权限被拒），"
        "路由据此跳过 `retrieve_verify_knowledge`/`verify_and_summarize`，直接进 `close_episode`",
    )
    verify_knowledge: FromHarnessToMemoryToolQueryKnowledgeResp | None = None
    """`retrieve_verify_knowledge` 查出来的领域知识（见
    `docs/ROADMAP.md`"verify_steps 改检索增强验证"）——只在
    `verify_step_entries` 非空时才会跑到这一格；`None` = 还没查（或
    `verify_step_entries` 是空的，路由跳过了这一格）。`verify_and_summarize`
    拿它对照判领域合理性，覆盖不到时校验器自己判"无法确认"，这里不兜底。"""

    verified_steps: list[StepMemory] | None = None
    """`verify_and_summarize` 校验后**已经用来蒸馏并落库**的可信单步记忆——
    蒸馏在同一格内完成，这个字段纯粹是给观测台/事后核对用的"这一局到底
    信了哪些记忆"，不被下游节点读取。

    `None` = 未校验场景（没有 step 记忆、或校验权限被拒）——这种场景直接
    结束收尾链，没有任何全量喂的蒸馏；空列表 `[]` = 校验过但全不可靠——
    蒸馏什么都不喂。两者语义不同，不能互相替代
    （见 `MemoryToolPort.store_episode_summary`）。"""


def safe_dirname(episode_id: str) -> str:
    """`episode_id` 压成文件名安全的一段（与记忆层同一规则）。

    checkpoint 归档（`episode_entry.void_timeline`）也要用它拼目录名，所以是
    模块级公开函数，不是类里的私有件。
    """
    return re.sub(r"[^A-Za-z0-9_-]+", "_", episode_id).strip("_-") or "unknown"


def _atomic_write_text(path: Path, text: str) -> None:
    """临时文件 + rename 的原子写：写完即完整，崩溃最多少一个未 rename 的 tmp。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class EpisodeCheckpoint(BaseModel):
    """**一份存档的全部内容**，也是它自己的读写器（原 `tools/checkpoint_tool.py` 的存/取两半）。

    ## 为什么它不再是"一根 Port"

    D9-v6：存档的读写不是一个**能力**——没有第二种存档后端、也没有"把它换成 mock"
    的需求。它是"harness 自己的状态怎么落盘"这件事，所以跟状态模型住一起（本文件），
    而不是作为外来的 Port 被注入。`HarnessDeps` 里只剩 `checkpoint_root` 一条路径的
    身份；`save`/`load` 变成模型自己的 `write`/`read`。

    ## 落盘布局（与 `checkpoint_tool.py` 时代一致，只有 json 键名变了）

        <checkpoint_root>/step/<safe_dirname>/<step>.state   模拟器世界快照（二进制）
        <checkpoint_root>/step/<safe_dirname>/<step>.json    这份模型（**提交点**）
        <checkpoint_root>/voided-<ts>/                       废弃局的存档归档

    `checkpoint_root` 是**整个 run 的目录**（`checkpoints/<run_id>/`），独立于
    `trace_data/<run_id>/`：后者是"这个 run 的可观测事件流"（一条事件一个文件、
    只写不删），前者是**可变的恢复状态**（会被覆盖、会被整目录搬走归档）。两者
    语义不同，不该是同一棵树下的兄弟目录。

    ## 世界快照为什么不进 json

    `emulator_state` 是 `bytes`，进 json 要走 base64（体积 +33%、且人不可读）；
    它又是**唯一不可从事件重建的东西**，单独一个 `.state` 二进制更直白。它标了
    `exclude=True`——`model_dump_json()` 天然不含它，两个文件各装各的，`read()`
    读回来时再配对。

    **提交点是 `.json`**：先写 `.state`、后原子写 `.json`。中途 crash 留下的是
    上一号有效存档（两个文件都齐的那一份），`read()` 按"成对存在 + 签名匹配"识别。

    ## 为什么 run 级那一半是 dump，不是模型

    判据是**谁解读谁内嵌**：`episode_state` 直接内嵌 `EpisodeRunState`（本层要解读
    它、拿它进图、核对签名）；而 `run_state_dump` 是**纯透传**——episode 层一个字段
    都不读，只是把它跟自己的状态打包进同一份文件，好让 `resume` 读一次就同时重建
    两层状态（`CHANGELOG` 2026-09-09：run 级状态单独存 `run.json` 实测必炸）。
    把它变成 `RunState` 会往本文件引进一条 `episode → run` 的依赖，而它今天
    **一个读者都没有**——episode 包对 run 包现在零引用，不该为它开这个口子。
    """

    run_id: str = Field(description="签名三元组之一；防跨 run 串档的显式字段")
    episode_id: str = Field(description="签名三元组之一")
    step: int = Field(ge=0, description="签名三元组之一：该步开局前")

    episode_state: EpisodeRunState = Field(
        description="这一局的状态（**直接内嵌**，不 dump）：恢复管线拿它进图"
    )
    run_state_dump: dict[str, Any] = Field(
        default_factory=dict,
        description="这一步所属局的 `RunState.model_dump()`（纯透传，episode 层不解读）",
    )
    last_event_id: int = Field(ge=-1, description="trace 游标：主前缀的最后一条 event_id")
    emulator_state: bytes = Field(
        default=b"",
        exclude=True,
        description="模拟器世界快照（唯一不可从事件重建的东西）；不进 json，单独落 `.state`",
    )
    frame_event_ids: dict[int, int] = Field(
        default_factory=dict,
        description="本局帧账之一：步号 → 承载该帧那条事件的 event_id（截图文件名）",
    )
    pending_frames: dict[int, str] = Field(
        default_factory=dict,
        description="本局帧账之二：步号 → 尚未挂上事件的帧的 base64 PNG（通常为空）",
    )
    saved_at: str = Field(default="", description="ISO 保存时间（审计用，恢复逻辑不依赖）")

    def write(self, root: Path) -> None:
        """写一份存档：先把世界快照落盘，再原子写 json（**json 才是提交点**）。

        `root` 是这个 run 的存档根（`HarnessDeps.checkpoint_root`）。
        """
        target_dir = root / "step" / safe_dirname(self.episode_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / f"{self.step}.state").write_bytes(self.emulator_state)
        self.saved_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        _atomic_write_text(target_dir / f"{self.step}.json", self.model_dump_json())

    @classmethod
    def read(cls, root: Path, episode_id: str, step: int) -> EpisodeCheckpoint | None:
        """取一份存档；`.json`/`.state` 不成对、或签名对不上时返回 `None`。

        **坏档（解析不了）不吞**：那是与"没有这份存档"不同的故障，静默返回 `None`
        会让调用方报出误导性的"找不到存档"。这里只对"文件不在"返回 `None`。

        **旧档（`state_dump` 时代的 json）读不了**：键名改成了 `episode_state`，
        pydantic 会因为缺字段直接抛——这正是我们要的（安静降级成"没有存档"更糟）。
        """
        step_dir = root / "step" / safe_dirname(episode_id)
        json_path = step_dir / f"{step}.json"
        state_path = step_dir / f"{step}.state"
        if not json_path.is_file() or not state_path.is_file():
            return None
        checkpoint = cls.model_validate_json(json_path.read_text(encoding="utf-8"))
        if checkpoint.episode_id != episode_id or checkpoint.step != step:
            return None  # 签名不匹配 = 这不是你要的那份（不靠目录位置推断）
        checkpoint.emulator_state = state_path.read_bytes()
        return checkpoint
