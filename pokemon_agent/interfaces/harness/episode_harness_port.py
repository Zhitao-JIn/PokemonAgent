"""`EpisodeHarnessPort`：跑一局的子 agent 接口——**接口里就有图**。

一局（one episode）是 run 的子 agent：run 级主 agent（`HarnessPort`）按任务计划
反复调它。本接口除了顶层入口 `run()`，还显式声明**图的十八个节点**与它们的
形状（`(EpisodeRunState) -> 状态增量`），图拓扑写在模块 docstring 里——**每个
节点只改状态里的一处**（或紧密绑在一起的一小组，如 `stall_key`/`stall_count`）：

    look → judge ──(state.done ?)──→ retrieve_verify_step_memory
                       ├─(无 step 记忆)──────────────────────→ END
                       └─(有 step 记忆)→ retrieve_verify_knowledge
                                          → verify_and_summarize → END
      └─(else)→ get_action_space
        → retrieve_step_episode_memory → retrieve_global_episode_memory
          → retrieve_knowledge_semantic_memory → retrieve_object_semantic_memory
        → enrich_observation
        → think_action → act → look_after_action
        → detect_stall → advance_step → store_step_episode_memory → store_object_semantic_memory
        → look

四个 `retrieve_*` 节点各自独立（互不依赖彼此的输出，都只读 `observation`），
写进四个不同的字段；`enrich_observation` 只做合并，把其中三类折进
`observation.facts`，交给 `think_action`。收尾分支的 `retrieve_verify_step_memory`/
`retrieve_verify_knowledge` 是同一个模式在收尾路径的落地——检索单独成节点、
结果单独落一个 state 字段，`verify_and_summarize`（一次调用问完"哪些可信"
和"蒸馏摘要"两件事，见 `docs/ROADMAP.md`"verify_steps 与 summarize 合并"
一条）本身不兼职查库——检索单独成节点，和主循环的 `retrieve_*` 同一模式，
不把查库缝进校验节点。`verify_step_entries` 为空时收尾链直接结束，
没有"不经校验全量蒸馏"的第二条路径。

`EpisodeRunState` 是这一局在图上流转的全部可序列化状态，与接口同文件：
它和节点签名互为契约——节点读它、写它的增量，`run()` 用它的最终形态结算。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from pokemon_agent.schemas.communication import (
    FromHarnessToMemoryToolQueryKnowledgeResp,
    HarnessEpisodeOutcomeResp,
)
from pokemon_agent.schemas.datastore import EpisodeMemory, StepMemory
from pokemon_agent.schemas.domain import (
    ActionFromBrain,
    ActionSpaceForBrain,
    GoalForBrain,
    ObservationFromWorld,
    TaskForHarness,
)


class EpisodeRunState(BaseModel):
    """一局的**全部**可序列化状态。

    分两组，但两组都在这里——分组只是为了读的人知道哪些跨步、哪些不跨：

        身份    episode_id / task / step / goals   跨步，checkpoint 要的就是它
        流转    observation / action_space / action / pending_observation /
                step_episode_memories / global_episode_memories /
                knowledge_semantic_memory / object_semantic_memory
                单步内，从一个节点传到下一个

    **`outcome` 不在这里。** 它是这一局的最终结论，由 `run()` 在图跑完之后
    从 `observation` 直接算出来——放进 state 就得有个节点负责填它，
    而"下结论"不该是任何一个循环节点的副业（详见 `run()` 里的说明）。

    **`goals` 全程只读。** 它是 run 级目标栈的投影——给大脑的全局信息
    （知道自己在全局的哪个位置），本 episode 只判栈顶 `goals[-1]`，
    判成即本局结束；弹栈/压栈是 run 级 `reflect` 的事，这里不碰。

    **活对象一个都不进来**（world / tools / brain / trace）：它们序列化不了，
    进来就把整个状态变成不可存的。它们是 `EpisodeHarness` 的构造参数，由装配处注入。
    """

    episode_id: str = Field(description="这一局的标识，全局唯一。trace 按它分组")
    task: TaskForHarness = Field(description="在跑哪个任务。目标、判据、步数上限都在里面")
    step: int = Field(
        default=0,
        description="跑到第几步。**全项目只有这一个 step**。"
        "细看也算一步——它同样烧一次决策调用，"
        "混进同一个数里意味着 max_steps 是一道『总共允许它折腾多少轮』的闸",
    )
    goals: list[GoalForBrain] = Field(
        default_factory=list,
        description="目标栈（run 级投影）。**判只判栈顶 `goals[-1]`**，"
        "其余层是给大脑的全局信息——知道最终目标是什么、自己在哪一层",
    )

    observation: ObservationFromWorld | None = None
    action_space: ActionSpaceForBrain | None = None
    step_episode_memories: list[StepMemory] = Field(
        default_factory=list,
        description="`retrieve_step_episode_memory` 查出来的、给这一步 `think_action` 用的"
        "本局单步情景记忆。**不折进 observation**——`think_action` 直接拿这份列表"
        "拼 `FromBrainToolToBrainChooseOnceReq.memories`",
    )
    global_episode_memories: list[EpisodeMemory] = Field(
        default_factory=list,
        description="`retrieve_global_episode_memory` 查出来的跨局摘要记忆"
        "（按场景 + 任务目标）。**不折进 `observation.facts`**——`think_action`"
        "直接拿这份列表渲染成文本，拼 `FromBrainToolToBrainChooseOnceReq.episode_memories`（prompt 里"
        "单独一节、单独给可信度说明，不跟这一帧的真实数据混在一起）",
    )
    knowledge_semantic_memory: FromHarnessToMemoryToolQueryKnowledgeResp | None = None
    """`retrieve_knowledge_semantic_memory` 查出来的知识库结果（内容 + 来源）。
    **不折进 `observation.facts`**——`think_action` 直接拿 `.contents` 拼
    `FromBrainToolToBrainChooseOnceReq.knowledge`（prompt 里单独一节）；`enrich_observation` 仍会用它
    算 `knowledge_text` 记一条 `MEMORY_READ`。`None` = 这一步还没查（图上未终止分支
    必经，只在没走到这一格时才是 None，比如刚开局那一帧）。"""
    object_semantic_memory: str = ""
    """`retrieve_object_semantic_memory` 查出来的语义记忆（object：这张地图上
    互动过的东西）。**仍然**由 `enrich_observation` 折进 `observation.facts`——
    它跟 `walk_map`/`landmarks` 一样坐标锚定在这张地图上，可信度同级，
    不像 `knowledge`/`global_episode_memories` 那样是跨场景/跨局的检索结果。"""

    action: ActionFromBrain | None = None
    pending_observation: ObservationFromWorld | None = None
    """**还没盖章的新观测**，等着下一轮 `look` 给它盖 step、判成败。

    两个来源：开局那一帧由 `begin` 从 `reset()` 的返回值里收下，之后每一帧
    由 `act` 从 `execute()` 的返回值里收下。**全项目只有这两处产出观测**——
    harness 自己不主动感知。

    `detect_stall`/`store_step_episode_memory`/`store_object_semantic_memory` 也读它，
    当作动作后的那份快照（`before`/`after` 的 after）。它在
    `act → look_after_action → …→ look` 这一段里活着，被 `look` 消费掉。
    """
    stall_count: int = 0
    """L2 护栏：连续多少步"动作与画面机械状态都没有任何变化"。
    `detect_stall` 里比较本步（动作 + `obs.stall_key()`）与上一步：全同 +1，
    否则清零；达到 `STALL_LIMIT` 时的强制终止判断在 `look`（不是这里）。"""
    stall_key: str | None = None
    """上一步的停摆键（`obs.stall_key()` + 动作描述拼成），供本步比较；
    None = 还没有可比的历史步（开局第一帧）。"""

    done: bool = False
    """这一局该不该结束——`judge` 综合三类机械条件（世界结束/步数用尽/停摆）
    +（不管前三类是否已成立都会问一次的）模型判定后给出的结论。**不在
    `ObservationFromWorld.done` 上**：那个字段是世界层自己的信号
    （窗口关没关），这个才是 harness 的终止裁决，两者语义不同，硬塞进同一个
    字段名会让"是不是被 judge 改过"变得含糊。跟 `stall_key`/`stall_count`
    一样，只有 `judge` 改它。"""
    success: bool = False
    """任务是否达成。**只在 `done` 为 True 时有意义**，否则恒为 False——
    唯一来源是 `judge` 里模型给出 `verdict.done=True` 那一刻，跟世界层、
    机械终止条件都无关。不占 `ObservationFromWorld.success`，
    理由同上：世界本来就不该有"任务算不算完成"这个概念，那是 harness 的
    判断，不是观测的一部分。"""

    verify_step_entries: list[StepMemory] = Field(
        default_factory=list,
        description="`retrieve_verify_step_memory` 查出来的本局全部 step 记忆——"
        "只在判完成的收尾分支上有意义。空列表 = 没有 step 记忆（或查询权限被拒），"
        "路由据此跳过 `retrieve_verify_knowledge`/`verify_and_summarize`，直接结束收尾链",
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


@runtime_checkable
class EpisodeHarnessPort(Protocol):
    """**跑一局的子 agent**：开局、跑图、收尾，一局一个回合。

    接口即图：十九个节点方法就是图的十九个节点（`judge` 出口的 done 分支
    决定是继续循环还是进收尾分支——有 step 记忆时进 `verify_and_summarize`
    一格问完校验+蒸馏，没有则直接结束收尾链）。每个节点只改
    `EpisodeRunState` 里的一处——这是接口对实现方的约束，不只是风格建议：
    一个节点改了几处、改坏了哪处不好定位。实现方把这份契约翻译成自己的
    图引擎（当前是 LangGraph），但图有哪些节点、什么形状，由接口定死。
    """

    # ---- 顶层入口 ----

    def run(
        self,
        episode_id: str,
        task: TaskForHarness,
        stack: list[TaskForHarness],
    ) -> HarnessEpisodeOutcomeResp:
        """跑完一局：解决栈顶这一个目标。

        episode_id：这一局的标识。
        task：栈顶目标（执行单元，含判据/步数上限）。
        stack：**整个目标栈（全局信息）**——投影成 `EpisodeRunState.goals`：
            判只判栈顶（`goals[-1]` = task.goal），其余层给大脑全局视野。
        前置条件：episode_id 非空、task.max_steps > 0、stack 非空且栈顶 == task。
        后置条件：trace 里恰好多一条 EPISODE_START 和一条 EPISODE_END；
            返回的 outcome 与事件流对同一局给出同一份结论。
        """
        ...

    # ---- 图的十九个节点（每个：(state) -> 状态增量，只改一处）----

    def look(self, state: EpisodeRunState) -> dict[str, Any]:
        """接住上一帧，盖步号，不做任何终止判断。**图的入口。**"""
        ...

    def judge(self, state: EpisodeRunState) -> dict[str, Any]:
        """这一局该不该停，在这一格一次性判完——世界结束/步数用尽/停摆/目标
        达成四类来源都在这合并，不分给别的节点。"""
        ...

    def get_action_space(self, state: EpisodeRunState) -> dict[str, Any]:
        """按这一帧观测算这一步能用的动作空间。仅在没终止的分支上跑。"""
        ...

    def retrieve_step_episode_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查本局单步情景记忆（全量），交给 `think_action`。不折进观测。"""
        ...

    def retrieve_global_episode_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查跨局摘要记忆（按场景 + 任务目标），交给 `enrich_observation` 折进观测。"""
        ...

    def retrieve_knowledge_semantic_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查知识库（按 observation 特征 + goal 拼的 query），交给 `enrich_observation`。"""
        ...

    def retrieve_object_semantic_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查语义记忆（object：这张地图上互动过的东西），交给 `enrich_observation`。"""
        ...

    def enrich_observation(self, state: EpisodeRunState) -> dict[str, Any]:
        """把四路检索结果合成这一帧观测：本局单步记忆之外的三类折进 `observation.facts`。"""
        ...

    def think_action(self, state: EpisodeRunState) -> dict[str, Any]:
        """决策：从动作空间里选一个动作（一次 `choose()` = 一轮 Thought → Action）。"""
        ...

    def act(self, state: EpisodeRunState) -> dict[str, Any]:
        """执行动作，推进世界。**唯一推进世界的节点。**"""
        ...

    def look_after_action(self, state: EpisodeRunState) -> dict[str, Any]:
        """感知动作后的新一帧，交给下一轮 `look` 盖章。"""
        ...

    def detect_stall(self, state: EpisodeRunState) -> dict[str, Any]:
        """算这一步的停摆键与连续计数（L2 护栏，只算数不改观测）。"""
        ...

    def advance_step(self, state: EpisodeRunState) -> dict[str, Any]:
        """步号加一。"""
        ...

    def store_step_episode_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """把这一步整理成一条可检索的经验，写进情景记忆。"""
        ...

    def store_object_semantic_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """把这一步涉及的语义记忆（object：那一格本身）写进库。"""
        ...

    def retrieve_verify_step_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查本局全部 step 记忆，交给 `retrieve_verify_knowledge`/`verify_and_summarize`。
        只在判完成的收尾分支上跑一次（不是每步），仅改 `verify_step_entries`。"""
        ...

    def retrieve_verify_knowledge(self, state: EpisodeRunState) -> dict[str, Any]:
        """整局一次检索领域知识（query 由本局 step 记忆的场景/动作特征拼），
        交给 `verify_and_summarize` 判领域合理性。只在 `verify_step_entries`
        非空时才跑，仅改 `verify_knowledge`。"""
        ...

    def verify_and_summarize(self, state: EpisodeRunState) -> dict[str, Any]:
        """拿 `verify_step_entries`/`verify_knowledge` 问独立判定器，一次调用
        问完两件事：只把可信的过滤出来（改 `verified_steps`），并用它们蒸馏出
        一条跨局摘要记忆、落库。**图上单独一格，收尾链的最后一格**（见
        `docs/ROADMAP.md`"verify_steps 与 summarize 合并"一条——只在
        `verify_step_entries` 非空时才会跑到这一格，为空时收尾链直接结束，
        没有"全量蒸馏"的兜底路径）。"""
        ...
