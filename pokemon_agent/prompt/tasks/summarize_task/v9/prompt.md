你在整理一只玩神奇宝贝的 agent 的单次 task 执行记录。
一个 task 是一段有预算的按键执行；本次输入给出 goal、task_id、结果和执行期逐键情景记忆（“当时看到 → 做了 → 之后变成”）。记录是机器读出的事实，不需要质疑是否发生过；但每一键是正样本还是负样本，由你逐条判断：对比“做了”与“之后变成”的两份快照（位置、朝向、场景、覆盖层、对话框、地图编号），推进目标的是正样本；前后状态完全相同、声称效果与快照对不上或方向与目标无关的是负样本。只是被挡或被拒绝而画面没变，不必然是负样本；没有把握不凭印象下结论。判断只用于组织总结，不单独输出；两类都要用，负样本是 failure_points 的主要来源。
总结本次 task 的前后变化，供上一层 episode 总结与以后的局检索复用。reason 结合最近判定的终止类别：goal_done 达成、world_ended 世界结束、stalled 原地打转、budget_exhausted 键数用尽、interrupted 半路意外打断（如遇敌）。判定依据是判定员当时判停的理由，可参考但不照抄；写你自己看记录得出的结论，说明靠哪几键或卡在哪、为什么，上一层会直接读它决定下一步怎么拆。


只输出单层 JSON，字段为 summary、reason、reusable_patterns、critical_decisions、failure_points、quality_score、quality_rationale、applicable_scenes、tags、markdown、index。index 包含 headline（不写成功、失败等结局词）、keys（仅取自输入原料的原文字词）、evidence（只能从“对话原文”“状态变化”“换图”“失败原因”中选择的数组）。事实由程序记录，不要生成事实块。其余字段写有依据的解读和可复用经验；quality_score 在 0 到 1 之间，列表无内容时用空数组。

<!-- labels -->
{
  "recent": "### 最近判定",
  "termination": "终止类别：{0}",
  "reason": "判定依据：{0}",
  "success": "目标达成",
  "failure": "目标未达成",
  "task_id": "task_id：{0}"
}
