"""Harness 伸向环境和记忆的两只手：`GameToolPort` 和 `MemoryToolPort`。

**它们是两个不相关的协议，不是一个协议的两半。** `Harness.__init__` 收两个独立
参数：`GameToolPort` 只碰 world，`MemoryToolPort` 只碰记忆，两者互不相识，
把它们组合起来是 Harness 一个人的事。上一版是一个大 `ToolHost` 把感知世界和
读写记忆混在同一个实现类里，换记忆后端就得动世界那一侧的代码。

记忆分四类暴露，因为读写语义不同：**单步情景记忆**全量返回（一局的轨迹本来就该
完整交给决策）；**语义记忆 object** 按坐标查；**知识库**和**跨局摘要**走同一套
混合检索（关键词 + 向量 + reranker）。程序记忆还没做，先不占位。

每个方法的 docstring 说明三件事——承诺什么、什么情况下失败、调用方要保证什么。
**这些方法上挂着权限装饰器**（`@require_permission`），所以除了各自写明的失败之外，
它们都可能抛权限异常；Harness 的兜底不按类型分支，见 `harness/harness.py` 的 `run()`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.action import Action, ActionSpace, ToolResult
from pokemon_agent.schemas.episode_memory import EpisodeMemory
from pokemon_agent.schemas.step_memory import StepMemory
from pokemon_agent.schemas.object_fact import ObjectFact
from pokemon_agent.schemas.observation import PerceptionResult, Observation
from pokemon_agent.schemas.knowledge import KnowledgeQueryResult
from pokemon_agent.schemas.task import Task


@runtime_checkable
class GameToolPort(Protocol):
    def save_state(self, path: str) -> None:
        """保存当前世界状态，供 episode replay 使用。

        把当前世界状态存成一个文件。
        """
        ...
    """Harness 用它操作世界：感知、执行、开局、溯源。**不碰任何记忆。**"""

    def perceive(self) -> PerceptionResult:
        """取当前观测。**幂等只读**：不推进世界、不写 trace、不触发判定。

        后置条件：同一帧内多次调用**不产生额外的模型调用**（实现方要在帧内缓存——
            感知是每步都要付钱的那一项）；`result.calls` 是这次调用产生的模型调用
            记录，命中缓存时为空列表（**不是 None**）。

        返回的 `observation` 在同一帧内**完全稳定**：同一帧问几次，拿到的字节一样。

        读当前这一帧，连同这次产生的模型调用记录一起交出来。
        """
        ...

    def get_action_space(self) -> ActionSpace:
        """取当前状态下可用的按键（含 masking）。

        后置条件：`names` 非空。走投无路的状态也必须至少给一个动作——
            空动作空间是工具层的 bug，不能让大脑去处理这种情况。

        工具层只管按键。这里曾经有一句"`intents` 不由这一层填"——
        `ActionSpace.intents` 这个字段已经删了（只剩按键一类动作），
        所以现在工具层给出的就是完整的动作空间，Harness 不再覆写它。

        给出此刻允许按的键。
        """
        ...

    def execute(self, action: Action) -> ToolResult:
        """执行一个动作，推进世界。

        前置条件：`action.name` 属于**调用前最近一次** `get_action_space()` 的结果。
            实现方必须 assert 这一点——大脑幻觉出不存在的动作要在这里就地爆炸，
            而不是变成一个语义不明的模拟器错误。
        后置条件：`result.observation` 非空，是执行后的新观测。
            它的 `step` **还没有盖章**——盖章是 Harness 的事。
            `result.calls` 是推进这一步期间产生的模型调用记录（通常来自
            推进后重新感知那一次），命中缓存时为空列表。

        执行一个动作，推进世界，返回结果与新观测。
        """
        ...

    def reset(self, task: Task) -> PerceptionResult:
        """按任务重置到初始状态并返回首个观测。

        前置条件：`task.max_steps > 0`。
        后置条件：`result.observation.done` 为 False；`step` 未盖章（由 Harness 填 0）；
            `result.calls` 是这次重置期间产生的模型调用记录。

        按任务重置世界，返回第一帧观测。
        """
        ...


@runtime_checkable
class MemoryToolPort(Protocol):
    """Harness 用它读写记忆：情景记忆 + 语义记忆（object + knowledge）+ 跨局摘要记忆。
    **不碰世界。**

    几类记忆分开暴露，因为它们的读写语义不同：单步情景记忆**全量返回**（一局的
    单步记忆本来就该完整保留、完整交给决策，见 `query_episode_steps` 的说明）；
    语义记忆（object）按坐标查；跨局摘要记忆和知识库都走同一套混合检索
    （关键词 + 向量 + reranker，见 `memory/retrieval.py`）。程序记忆
    （procedural）还没做，先不占位。
    """

    # ---- 情景记忆：episodic ----

    def query_episode_steps(self, episode_id: str) -> list[StepMemory]:
        """**这一局**全部的单步情景记忆，按发生顺序（`step` 升序）。

        **不做相关性排序、不截断**——单步记忆本来就该完整保留：它记的是
        "这一步做过什么、结果如何"，是这一局自己的完整轨迹，不是从一个大库里
        挑几条相关的出来，见 `schemas/episode_memory.py` 顶部对
        `StepMemory`（单步、全量、限定这一局）和 `EpisodeMemory`（跨局、
        检索、限定相关）的区分。

        前置条件：`episode_id` 非空。
        后置条件：返回的每一条 `entry.episode_id == episode_id`；按 `step` 升序。

        取这一局全部的单步情景记忆，按发生顺序。
        """
        ...

    def query_recent_steps(self, episode_id: str, limit: int) -> list[StepMemory]:
        """**这一局**最近几条情景记忆，按时间顺序。

        前置条件：limit > 0。
        后置条件：返回条数 <= limit；全部来自 `episode_id` 这一局；最新的在最后。

        取这一局最近几条情景记忆。
        """
        ...

    def store_episode_step(self, entry: StepMemory) -> None:
        """写入一条情景记忆。

        前置条件：`entry.rationale` 非空。没有理由的经验取回来也没用——
            它说不出当时为什么这么判断，也就无法检查那个判断现在还成不成立。

        写入一条情景记忆。
        """
        ...

    @property
    def episode_step_count(self) -> int:
        """库里有多少条情景记忆。**A/B 实验的自变量之一**，要能被记进事件流。"""
        ...

    # ---- 跨局摘要记忆：episode memory ----
    #
    # 和上面的"情景记忆"是两条不同的检索路径（见 `schemas/episode_memory.py` 顶部
    # 对 `StepMemory` vs `EpisodeMemory` 的区分）：这里检索/写入的单元是**一整局**，
    # 不是一步，一局内的单步记忆不会、也不该经这两个方法被跨局取走。

    def query_episode_summaries(self, scene: str, query: str, limit: int = 3) -> list[EpisodeMemory]:
        """检索和当前场景相关的跨局摘要记忆。

        前置条件：`scene` 非空；`limit > 0`。
        后置条件：返回条数 <= limit；按"场景匹配 + 相关性 + 质量/成功"降序——
            **检索策略属于实现方**，调用方不知道也不该知道具体怎么排的。
            场景过滤允许"通用经验"（`applicable_scenes` 为空或含通配值）参与任何场景的检索，
            见 `EpisodeMemory.matches_scene`；实现方在"精确匹配场景"命中为空时，
            必须退回到"只看通用经验"而不是直接返回空列表——一次标注失误
            （LLM 蒸馏时场景标错）不该让这条摘要在所有场景下都检索不到。

        检索几条和当前场景、当前任务相关的跨局经验。
        """
        ...

    @property
    def episode_summary_count(self) -> int:
        """库里有多少条跨局摘要记忆，是要能被记进事件流的可观测量。"""
        ...

    def store_episode_summary(
        self, episode_id: str, run_id: str, goal: str, outcome: dict[str, str | int | bool]
    ) -> EpisodeMemory:
        """一局结束时调用：把这一局的单步记忆蒸馏成一条跨局摘要记忆，写入并返回。

        前置条件：`episode_id` 对应的单步记忆已经全部写完——调用方（Harness）
            保证在真正结束这一局之后才调它，不是提前调。`outcome` 至少含
            `success`（bool）与 `steps`（int）。
        失败：蒸馏用的 LLM 输出解析不出合法结构时抛 `ValueError`，不吞——
            解析失败是预期内的运行时情况，调用方决定要不要吞掉这次失败
            （Harness 的选择是吞：见 `harness/harness.py` 的 `_summarize`）。

        把这一局蒸馏成一条跨局摘要记忆，写入并返回。
        """
        ...

    # ---- 语义记忆：object ----

    def query_objects(self, obs: Observation) -> str:
        """`obs.place` 所在地图上，已知的语义记忆（object）渲染成的一段文字。

        后置条件：`obs.place` 为 None 时返回空串；没有任何已知条目时也返回空串——
            调用方（Harness）据此决定要不要往 `facts["known_objects"]` 里塞东西。

        把这张地图上已知的 object 渲染成一段文字。
        """
        ...

    def store_objects_interactions(
        self, before: Observation, action: Action, after: Observation
    ) -> list[ObjectFact]:
        """这一步碰到了什么语义记忆（object），记下来。返回被更新的条目（可能为空）。

        前置条件：`before`/`after` 都有 `place`。算不出确定的一格时（连按、
            原地转身、两个候选同时存在）**不记**，宁可漏记也不能记错格子。

        把这一步碰到的 object 记下来，返回被更新的条目。
        """
        ...

    # ---- 语义记忆：知识库（和坐标无关的通用先验） ----
    def query_knowledge(self, query: str, limit: int = 5) -> KnowledgeQueryResult:
        """项目自带的通用游戏先验（草丛怎么走、属性克制表、道馆打法……）里，
        和 `query` 相关的那几条，拼成一段文字。

        和 `query_objects()` 不同：那个按 `obs.place` 筛，这个不按坐标筛，
        按内容相关性筛——知识库条目量级会随内容增长（不再是"个位数、全喂"
        那个阶段，见 `memory/semantic/knowledge/store.py` 顶部说明），
        混合检索（关键词 + 向量 + reranker）负责从里面挑出这一步真正用得上的。

        前置条件：`query` 非空；`limit > 0`。
        后置条件：返回内容和来源来自同一次检索；没有命中时两者都是空列表。

        从通用游戏先验里检索出这一步用得上的那几条。
        """
        ...
