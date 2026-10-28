"""RunMemory：整次 run 的派生视图，可重建、可丢弃，成败只认来源章。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .task_memory import MemoryIndex


class RunMemory(BaseModel):
    """本 run 全部 EpisodeMemory 的蒸馏正文与 harness 来源章。"""

    run_id: str = Field(description="所属 run 的标识符")
    run_goal: str = Field(description="本 run 的目标文本")
    episodes: int = Field(ge=0, description="本 run 的局数")
    succeeded: int = Field(ge=0, description="本 run 的成功局数")
    acts_used: int = Field(default=0, ge=0, description="本 run 累计按键数")
    termination: str = Field(default="", description="run 的机械终止类别")
    reason: str = Field(default="", description="run 蒸馏的结论说明；空章为异常摘要")
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

    pointers: list[str]
    index: MemoryIndex

    markdown: str = Field(default="", description="LLM 生成的完整记忆正文（.md 主内容）")

    @property
    def success(self) -> bool:
        """仅 termination 为 goal_done 时成功。"""
        return self.termination == "goal_done"
