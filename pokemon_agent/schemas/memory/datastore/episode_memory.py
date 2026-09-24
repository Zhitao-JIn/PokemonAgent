"""跨局摘要记忆：**一整局各 task 记忆（TaskMemory）的总结**（一局一条）。

记忆阶梯：ActMemory（一键一条）→ TaskMemory（一 task 一条）→ EpisodeMemory（一局一条）。
名字里的"跨局"说的是**它会被别的局读到**（检索回来当参考），**不是"它总结了
多个局"**——一条 `EpisodeMemory` 只对应一局。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EpisodeMemory(BaseModel):
    """一条跨局摘要记忆——**本局 TaskMemory 的派生视图**，不是第二份事实。

    ## 它是派的，不是记的

    **正文**（`reason` 与 `summary` 起）由 LLM 从本局全部 TaskMemory 蒸馏而来；
    每条 TaskMemory 都带 verify 的正/负标注一起送进去（负样本是 `failure_points`
    的主要来源）。蒸馏点在 `harness/episode/episode_done/summarize_episode.py`。

    **来源章**（`episode_id` / `run_id` / `goal` / `success` / `steps` / `acts_used` /
    `termination`）是 harness 从 episode state 盖的，与正文无关。装配点
    `tools/brain_tool.py::Summarizer.summarize()` 把 `EpisodeSummary` 与这些字段拼在一起。

    ## 三条推论（改这里之前先读）

    1. **可重建**——同一批 TaskMemory + 同样的章，重跑蒸馏得**等价**的一条
       （LLM 非确定，不逐字节相同）。所以"换 prompt / 换模型重蒸"是合法操作，
       不是危险操作。
    2. **可丢弃**——`rm memory/episode_memory/*.md` 只损失算力，不损失事实。
       这是它作为派生物的定义性质，也是"什么时候可以放心重来"的判据。
    3. **成败只认章，不认正文**——`success` 是 harness 的机械判定；LLM 被**告知**了
       本局结果，所以它可能把"成功"写进叙述里。**读的人必须以字段为准**，不许从
       `summary` 正文反推成败（`render()` 把章摆在第一行，就是这个意思）。

    ## "一局一条"是硬约束

    每一局跑完都恰好留一条本类记录——**包括正文产不出来的那些**（整局异常、
    收尾时没有 TaskMemory 可蒸）：那时落一条**只有来源章、正文全空**的记录，
    写入点是 `harness/episode/episode_done/leave_chapter.py::store_empty_chapter()`
    （episode 收尾没有 TaskMemory 时由 `leave_chapter` 单元调、整局异常时由接住它的
    run `act` 调）。所以"这局我试过没有"永远能从记忆里读出来，`plan` 不会对同一个
    目标反复做同一件蠢事。

    **空不空看正文自己**（0914 99）：早先另设过一枚 `chapter_only` 标记，
    已连字段一起删掉——"这条记录有没有正文"从 `markdown` / `summary` 为空
    就读得出来，多一枚标记就是同一件事的第二个真相来源。
    """

    # —— 来源章（harness 盖的，取自 run state；与 step memory 无关）——
    episode_id: str = Field(description="蒸馏自哪一局")
    run_id: str = Field(description="所属 run 的标识符")
    goal: str = Field(description="那一局的任务目标")
    steps: int = Field(ge=0, description="那一局派了几个 task（本层计数单位）")
    acts_used: int = Field(default=0, ge=0, description="那一局累计按了几个键（统计用）")
    termination: str = Field(
        default="",
        description="机械终止类别：goal_done / world_ended / stalled / budget_exhausted / error",
    )
    reason: str = Field(
        default="", description="episode_done 里 LLM 写的结论说明；空章版为异常摘要"
    )

    # —— 派生正文（本局可信 step memory 的蒸馏结果，可重建可丢弃）——
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
    #
    # 这里**没有 `filename`**（0914 98 全退）：早期落盘真拿 LLM 给的可读名命名，
    # 改用 uuid 之后它就成了"只被写、从没被读"的一格——`store_episode_summary`
    # 自己的 docstring 写着「uuid 文件名天然不撞」。删的是字段本身，
    # 不是账上少抄一份。
    markdown: str = Field(default="", description="LLM 生成的完整记忆正文（.md 主内容）")

    @property
    def success(self) -> bool:
        """成没成——由 `termination` 推出（`goal_done` 即达成），不单独存。"""
        return self.termination == "goal_done"

    def render(self) -> str:
        """渲染成进 prompt 的样子，**检索打分也用它**——理由同
        `ActMemory.render`（`schemas/memory/datastore/act_memory.py`）：两处用同一份文本，
        避免"按 A 的内容选中，却把 B 的内容喂进去"这种不报错的错位。

        **第一行是来源章，往下才是派生正文，顺序不能反**——章是 harness 的机械判定，
        正文是 LLM 的叙述。读者要判断"这局成没成"只看第一行；正文里出现的"成功"
        只是叙述，不是判据（见类 docstring 的第 3 条推论）。

        渲染成进 prompt、也用于检索打分的那段文本。
        """
        lines = [
            f"({self.episode_id}) 目标：{self.goal}"
            f"（{'成功' if self.success else '未成功'}"
            f"{'，' + self.termination if self.termination else ''}，"
            f"{self.steps} 个 task / {self.acts_used} 键）"
        ]
        if self.reason:
            lines.append(f"  结论  {self.reason}")
        if not self.summary.strip():
            # 正文不存在（整局异常，或收尾时一条可信的 step 记忆都没有）：
            # **不要**往 prompt 里塞一排空字段冒充正文，说明为什么没有就够了。
            lines.append(f"  （本局无正文：{self.quality_rationale}）")
            return "\n".join(lines)
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
