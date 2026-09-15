"""记忆链蒸馏的解析产物：`EpisodeSummary`。

只有响应协议：蒸馏是**单独一次调用**（`Brain.summarize()`，prompt 由
`tools/prompts/summarize.py` 加载的 `calls/summarize.md` 拼出）。它此前和校验
合并成 `Brain.verify_and_summarize()` 的一次调用，拆开之后（CHANGELOG 第 39 条）
就没有 `VerifyAndSummarizeReq/Resp` 这类合并信封了，这里只剩蒸馏侧的响应产物。

`EpisodeSummary` 是蒸馏结果的直接产物，由 `BrainTool.summarize()` 配上 harness
给的五个来源字段（`episode_id`/`run_id`/`goal`/`success`/`steps`）搬进存储形状
`EpisodeMemory`——两段的分界见 `EpisodeMemory` 的类 docstring。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EpisodeSummary(BaseModel):
    """**蒸馏出的响应**：情景记忆内容协议。

    字段是一次蒸馏的直接产物：经验本体（`summary` 到 `tags`）+ 落盘所需的
    `markdown`。经验本体与 `EpisodeMemory` 同构，
    是通信层（本类）向存储层（`EpisodeMemory`）的显式映射来源，
    而不是共享同一个嵌套类型。

    **没有 `filename`**（0914 98 全退）：早期落盘拿 LLM 给的可读名命名，
    改用 uuid 之后它没有任何读方——删的是字段本身，不是"账上少抄一份"。
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

    markdown: str = Field(default="", description="要原样保存的 Markdown 记忆正文")
