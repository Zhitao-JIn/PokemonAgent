你负责对一次 run 做整体复盘，从“下次再接到同一个总目标，应该先做什么、避开什么”的视角总结。
成败以目标表最终定案为准，保留 note 与是否被人审推翻的含义，不自行改写成败。各局记忆全文的来源章是当时的机器判定，目标表是最终定案。


只输出单层 JSON，字段为 summary、reason、reusable_patterns、critical_decisions、failure_points、quality_score、quality_rationale、applicable_scenes、tags、markdown、index。index 包含 headline（不写成功、失败等结局词）、keys（仅取自输入原料的原文字词）、evidence（只能从“对话原文”“状态变化”“换图”“失败原因”中选择的数组）。事实由程序记录，不要生成事实块。其余字段写有依据的解读和可复用经验；quality_score 在 0 到 1 之间，列表无内容时用空数组。

<!-- labels -->
{
  "recent": "### 最近判定",
  "termination": "终止类别：{0}",
  "reason": "判定依据：{0}",
  "goals": "### 目标表最终定案",
  "counts": "成功局数：{0}\n累计键数：{1}"
}
