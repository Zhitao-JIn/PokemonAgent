"""记忆链蒸馏的响应协议：`FromBrainToLlmEpisodeSummaryResp`。

只有响应协议：校验和蒸馏合并为 `Brain.verify_and_summarize()` 的一次
调用（见 `docs/ROADMAP.md`“verify_steps 与 summarize 合并”一条），蒸馏在
那次调用里问完模型，不存在单独的蒸馏请求协议。

`FromBrainToLlmEpisodeSummaryResp` 是蒸馏结果的直接产物，经
`memory/episode/episode_store.py` 的显式适配点（`_create_episode_memory`）
搬进存储形状 `EpisodeMemory`。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromBrainToLlmEpisodeSummaryResp(BaseModel):
    """**蒸馏出的响应**：情景记忆内容协议。

    字段是一次蒸馏的直接产物：经验本体（`summary` 到 `tags`）+
    落盘所需（`filename`/`markdown`）。经验本体与 `EpisodeMemory` 同构，
    是通信层（本类）向存储层（`EpisodeMemory`）的显式映射来源，
    而不是共享同一个嵌套类型。
    """

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

    filename: str = Field(default="episode_memory", description="用于保存 Markdown 记忆的文件名")
    markdown: str = Field(default="", description="要原样保存的 Markdown 记忆正文")
