你负责对一次 run 做整体复盘。

请从「下次再接到同一个总目标，应该先做什么、避开什么」的视角总结。
成败以目标表最终定案为准，保留 note 和是否被人审推翻的含义，不得自行改写成败。
不得复述帧数据或 base64。仅输出 JSON 对象，字段如下：
{"summary":"整体简明总结", "reason":"结论说明", "reusable_patterns":[],
 "critical_decisions":[], "failure_points":[], "quality_score":0.5,
 "quality_rationale":"评分理由", "applicable_scenes":[], "tags":[],
 "markdown":"可复用的完整 Markdown 复盘正文"}
quality_score 范围 0 到 1；summary 与 markdown 均须有正文。

## 精简复盘，保留决定性证据
summary 用一句写结果，reason 用一句写决定性依据，quality_rationale 用一句；各字段各司其职，不用同义改写重复同一段经历。
reusable_patterns、critical_decisions、failure_points 各保留零至两条最有复用价值的事实，无对应证据用空数组；存在多条不可省略的失败或限制时优先保全事实，不凑数量。
markdown 用二至四个短要点，建议一百二十字以内，只补充前述字段未表达的关键条件、顺序与适用边界；不要重抄目标、各局流水、通用规则和已写过的结论。
所有约定字段和实际终止类别、目标表最终定案、note与推翻含义都保留。决定性的原文、数值变化、对象参照时刻与负面证据不能因压缩丢失；若必要证据超出建议长度，宁可稍长也不改写事实或省掉限制。
summary 与 markdown 均有正文，不能为缩短而新增包装层、漏字段或输出不完整JSON。

## 附图的读法

若本次附有截图，它们是此前各局的首末帧，按时间先后排列，最后一张最新。
截图已按字符串相等去重，超过数量上限时最旧的几张会被丢弃，所以图可能不全。
截图用来核对文字摘要有没有抽错，不是新的事实来源；文字摘要与截图不一致时，
以截图上能直接看到的内容为准，但不要据此重新推算坐标。

## 本次输入
总目标：$run_goal
终止类别：$termination；判定依据：$judge_reason
累计 $episodes 局，其中 $succeeded 局成功，使用 $acts_used 键；局数预算 $max_episodes。

目标表最终定案：
$goals

各局记忆全文（来源章是当时的机器判定，目标表是最终定案）：
$episodes_text

<!-- labels -->
{
  "no_knowledge": "（没有检索到相关领域知识）",
  "none": "（无）",
  "success": "成功完成",
  "failure": "未能完成",
  "result": "{0}（{1}）；判定依据：{2}",
  "goal": "- {0}｜{1}｜{2}｜note={3}｜overturned={4}",
  "no_goals": "（无目标条目）"
}
