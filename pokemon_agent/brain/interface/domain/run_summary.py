"""RunSummary：一次 run 蒸馏的派生正文，不含来源章。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunSummary(BaseModel):
    """整次 run 的复盘产物；字段与 EpisodeSummary 同形。"""

    summary: str = Field(description="Episode的简明总结")
    reason: str = Field(
        default="", description="结论说明：成了靠什么、没成卡在哪（进 Output.reason）"
    )
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

    markdown: str = Field(default="", description="要原样保存的 Markdown 记忆正文")
