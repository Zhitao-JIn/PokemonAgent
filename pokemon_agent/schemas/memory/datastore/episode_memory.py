"""跨局摘要记忆：一整局蒸馏出来的一条经验。"""

from __future__ import annotations

from pydantic import BaseModel, Field

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

    前半段字段是这条摘要的**来源信息**——它是从哪一局、为了什么目标、打得成不成功
    蒸馏出来的，检索排序（场景匹配 + 质量/成功加权）要用到它们；后半段（`summary`
    到 `tags`）是 LLM 蒸馏出的**经验本体**，它们本身才是"经验"。
    """

    # —— 来源信息（harness 盖章，不是 LLM 生成）——
    episode_id: str = Field(description="蒸馏自哪一局")
    run_id: str = Field(description="所属 run 的标识符")
    goal: str = Field(description="那一局的任务目标")
    success: bool = Field(description="那一局是否成功完成")
    steps: int = Field(ge=0, description="那一局实际用了多少步")

    # —— 经验本体（LLM 蒸馏出的内容）——
    summary: str = Field(description="Episode的简明总结")
    reusable_patterns: list[str] = Field(
        default_factory=list, description="可重复利用的游戏策略和经验模式"
    )
    critical_decisions: list[str] = Field(default_factory=list, description="关键决策点及其效果")
    failure_points: list[str] = Field(
        default_factory=list, description="可能导致失败的环节及规避方法"
    )
    quality_score: float = Field(ge=0.0, le=1.0, description="记忆质量评分(0.0-1.0)")
    quality_rationale: str = Field(description="质量评分的理由")
    applicable_scenes: list[str] = Field(default_factory=list, description="此记忆适用的游戏场景")
    tags: list[str] = Field(default_factory=list, description="记忆标签（导航/战斗/物品收集等）")

    # —— 落盘（md 是主内容，以上字段是它的元数据）——
    filename: str = Field(
        default="episode_memory", description="落盘用的文件名（不含 .md，LLM 给的可读名）"
    )
    markdown: str = Field(default="", description="LLM 生成的完整记忆正文（.md 主内容）")

    def matches_scene(self, scene: str) -> bool:
        """这条摘要在给定场景下是否适用。

        前置条件：`scene` 非空——空场景没有"匹配"这个概念，调用方（`MemoryTool`）
            要保证传进来的是一个具体场景标识（当前实现下是 `map_id` 的字符串形式）。
        后置条件：`applicable_scenes` 为空、或显式含 `SCENE_ANY`，
            视为"任何场景都命中"（见 `SCENE_ANY` 的说明）；否则要求精确命中列表中的一项。

        看这条摘要在给定场景下适不适用。
        """
        assert scene, "matches_scene() got an empty scene"
        if not self.applicable_scenes or SCENE_ANY in self.applicable_scenes:
            return True
        current = set(scene.split("|"))
        return any(label in current or label == f"map:{scene}" for label in self.applicable_scenes)

    def render(self) -> str:
        """渲染成进 prompt 的样子，**检索打分也用它**——理由同
        `StepMemory.render`（`schemas/memory/step_memory.py`）：两处用同一份文本，
        避免"按 A 的内容选中，却把 B 的内容喂进去"这种不报错的错位。

        渲染成进 prompt、也用于检索打分的那段文本。
        """
        lines = [
            f"({self.episode_id}) 目标：{self.goal}（{'成功' if self.success else '未成功'}，{self.steps} 步）"
        ]
        lines.append(f"  总结  {self.summary}")
        if self.reusable_patterns:
            lines.append("  可复用经验  " + "；".join(self.reusable_patterns))
        if self.critical_decisions:
            lines.append("  关键决策  " + "；".join(self.critical_decisions))
        if self.failure_points:
            lines.append("  失败点  " + "；".join(self.failure_points))
        lines.append(f"  质量分 {self.quality_score:.2f}（理由：{self.quality_rationale}）")
        if self.tags:
            lines.append("  标签  " + "、".join(self.tags))
        return "\n".join(lines)
