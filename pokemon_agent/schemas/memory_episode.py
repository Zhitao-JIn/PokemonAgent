"""跨局摘要记忆契约：**这一局打完了，值得留给下一局的是什么。**

和 `schemas/memory_episodic.py` 的 `MemoryEntry` 不是同一种东西，虽然中文名字都带"情景"：

    MemoryEntry    单步记忆。"我在那个画面里选了什么、结果如何"，检索单元是**一步**，
                   同一局内随时可能被下一步取回，服务的是"这一局别再撞同一次墙"。
    EpisodeMemory  跨局摘要记忆（本文件）。"这一整局打下来，值得复用的经验是什么"，
                   检索单元是**一整局**，被检索方是未来某一局的开局/规划阶段，
                   服务的是"这一类任务下次要不要重复上次的策略"。

两者的检索时机、检索粒度、生命周期全部不同：`MemoryEntry` 一局之内产生、
也可能一局之内被取回；`EpisodeMemory` 要等一局**结束**、由
`memory/episode_summarizer.py` 从这一局的 `MemoryEntry` 序列蒸馏出来，之后跨局存在。
**一局里的单步记忆不该被跨局检索拿走**——它们太琐碎，拿到别的局里只会是噪音，
这正是拆成两个类型、两条检索路径的理由（`MemoryTool.query_episodic` 只管前者，
`MemoryTool.query_episode_memories` 只管后者，互不混用）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .memory_episode_summary import EpisodeMemoryContent

SCENE_ANY = "*"
""""不限场景"的通配值。

场景过滤答的是"这条经验在当前地图有没有用"，但很多经验天生和站在哪张地图无关
（"进草丛要连按而不是试探一次"）。这类经验如果被要求精确匹配当前 `map_id`
才能命中，会被场景过滤误杀——它们不属于任何一张具体地图，但属于所有地图。
`applicable_scenes` 留空，或者显式含这个通配值，都当作"任何场景都命中"处理，
而不是强迫每条通用经验去列举它适用的每一张地图。
"""


class EpisodeMemory(BaseModel):
    """一条跨局摘要记忆：**这一局（`episode_id`）打完之后，蒸馏出的可复用经验。**

    `content` 是 LLM 蒸馏出的实质内容（见 `EpisodeMemoryContent`），
    其余字段是这条摘要的**来源信息**——它是从哪一局、为了什么目标、
    打得成不成功蒸馏出来的，检索排序（场景匹配 + 质量/成功加权）要用到它们，
    但它们本身不是"经验"的一部分。
    """

    episode_id: str = Field(description="蒸馏自哪一局")
    run_id: str = Field(description="所属 run 的标识符")
    goal: str = Field(description="那一局的任务目标")
    success: bool = Field(description="那一局是否成功完成")
    steps: int = Field(ge=0, description="那一局实际用了多少步")
    content: EpisodeMemoryContent = Field(description="蒸馏出的经验本体")
    rationale: str = Field(description="为什么这条摘要值得留（LLM 给出的理由）")
    stamp: str = Field(default="", description="生成时刻的标识，跨步骤稳定，不用于排序")

    def matches_scene(self, scene: str) -> bool:
        """这条摘要在给定场景下是否适用。

        前置条件：`scene` 非空——空场景没有"匹配"这个概念，调用方（`MemoryTool`）
            要保证传进来的是一个具体场景标识（当前实现下是 `map_id` 的字符串形式）。
        后置条件：`content.applicable_scenes` 为空、或显式含 `SCENE_ANY`，
            视为"任何场景都命中"（见 `SCENE_ANY` 的说明）；否则要求精确命中列表中的一项。
        """
        assert scene, "matches_scene() got an empty scene"
        scenes = self.content.applicable_scenes
        if not scenes or SCENE_ANY in scenes:
            return True
        return scene in scenes

    def render(self) -> str:
        """渲染成进 prompt 的样子，**检索打分也用它**——理由同
        `MemoryEntry.render`（`schemas/memory_episodic.py`）：两处用同一份文本，
        避免"按 A 的内容选中，却把 B 的内容喂进去"这种不报错的错位。
        """
        c = self.content
        lines = [f"({self.episode_id}) 目标：{self.goal}（{'成功' if self.success else '未成功'}，{self.steps} 步）"]
        lines.append(f"  总结  {c.summary}")
        if c.reusable_patterns:
            lines.append("  可复用经验  " + "；".join(c.reusable_patterns))
        if c.critical_decisions:
            lines.append("  关键决策  " + "；".join(c.critical_decisions))
        if c.failure_points:
            lines.append("  失败点  " + "；".join(c.failure_points))
        if c.tags:
            lines.append("  标签  " + "、".join(c.tags))
        return "\n".join(lines)
