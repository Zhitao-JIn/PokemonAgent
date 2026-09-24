"""task 记忆：一条 = 一个 task。**记忆阶梯的中层**（0923 189）。

    ActMemory（每键，task 的 act 机械组装）
      → task_done 读它、LLM 总结 → **TaskMemory**（本类）
        → episode_done 读它、LLM 总结 → EpisodeMemory

## 它是派的，不是记的

**正文**（`summary` 起）由 LLM 从**本 task 通过校验的 ActMemory** 蒸馏而来
（"这一次 task 的前后变化"）；原料一直在 `memory/step_memory/`。来源章
（`run_id` / `episode_id` / `task_id` / `goal` / `success` / `reason` /
`steps_used` / `start_step`）与 ActMemory 无关：它是 harness 从 TaskState 盖的
（装配点 `tools/brain_tool.py::TaskSummarizer.summarize_task()`）。

三条推论与 `EpisodeMemory` 相同：**可重建**（同批原料重蒸得等价的一条）、
**可丢弃**（rm 只损失算力）、**成败只认章不认正文**。

## 代表帧

`first_frame` / `last_frame` 是本 task 首末两键的前后帧里挑出的**代表帧**
（`TaskSummarizer` 从首条 ActMemory 的 `before_frame` 与末条的 `after_frame` 取，
可空）。上层总结（episode_done）拿它当画面锚点，不必回查全部 ActMemory。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaskMemory(BaseModel):
    """一条 task 记忆——**本 task ActMemory 的派生视图**（一 task 一条）。"""

    # —— 来源章（harness 盖的，取自 TaskState）——
    run_id: str = Field(description="所属 run 的标识")
    episode_id: str = Field(description="所属 episode 的标识")
    task_id: str = Field(description="本 task 的标识")
    goal: str = Field(description="本 task 的目标")
    termination: str = Field(
        default="", description="机械终止类别：goal_done / world_ended / stalled / budget_exhausted"
    )
    reason: str = Field(default="", description="task_done 里 LLM 写的结论说明")
    steps_used: int = Field(ge=0, description="本 task 消耗的键数")
    start_step: int = Field(ge=0, description="本 task 的全局键号起点（ActMemory 步号区间下界）")

    # —— 派生正文（本 task 正样本 ActMemory 的蒸馏结果，可重建可丢弃）——
    summary: str = Field(description="本 task 的简明总结：前后变化与结果")
    reusable_patterns: list[str] = Field(
        default_factory=list, description="可重复利用的游戏策略和经验模式"
    )
    critical_decisions: list[str] = Field(default_factory=list, description="关键决策点及其效果")
    failure_points: list[str] = Field(
        default_factory=list, description="可能导致失败的环节及规避方法"
    )
    quality_score: float = Field(ge=0.0, le=1.0, description="记忆质量评分(0.0-1.0)")
    quality_rationale: str = Field(description="质量评分的理由")
    tags: list[str] = Field(default_factory=list, description="记忆标签")

    # —— 代表帧（供上层总结当画面锚点）——
    first_frame: str | None = Field(
        default=None, description="本 task 首键的 before 帧（PNG data URI，可空）"
    )
    last_frame: str | None = Field(
        default=None, description="本 task 末键的 after 帧（PNG data URI，可空）"
    )

    markdown: str = Field(default="", description="LLM 生成的完整记忆正文（.md 主内容）")

    @property
    def success(self) -> bool:
        """成没成——由 `termination` 推出（`goal_done` 即达成），不单独存。"""
        return self.termination == "goal_done"

    def render(self) -> str:
        """渲染成进 prompt 的样子：来源章一行 + 正文。"""
        mark = "成功" if self.success else f"未成功（{self.termination or '未知'}）"
        lines = [
            f"task `{self.task_id}`：{self.goal} —— {mark}"
            f"（键 {self.start_step}–{self.start_step + self.steps_used - 1}，"
            f"共 {self.steps_used} 键）",
        ]
        if self.reason:
            lines.append(f"  结论：{self.reason}")
        lines.append(f"  总结：{self.summary}")
        for label, items in (
            ("可复用", self.reusable_patterns),
            ("关键决策", self.critical_decisions),
            ("失败点", self.failure_points),
        ):
            for item in items:
                lines.append(f"  {label}：{item}")
        if self.quality_rationale:
            lines.append(f"  质量分 {self.quality_score:.2f}（理由：{self.quality_rationale}）")
        return "\n".join(lines)


__all__ = ["TaskMemory"]
