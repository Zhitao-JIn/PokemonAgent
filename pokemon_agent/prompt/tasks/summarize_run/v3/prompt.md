你负责对一次 run 做整体复盘。

请从「下次再接到同一个总目标，应该先做什么、避开什么」的视角总结。
成败以目标表最终定案为准，保留 note 和是否被人审推翻的含义，不得自行改写成败。
不得复述帧数据或 base64。仅输出 JSON 对象，字段如下：
{"summary":"整体简明总结", "reason":"结论说明", "reusable_patterns":[],
 "critical_decisions":[], "failure_points":[], "quality_score":0.5,
 "quality_rationale":"评分理由", "applicable_scenes":[], "tags":[],
 "markdown":"可复用的完整 Markdown 复盘正文"}
quality_score 范围 0 到 1；summary 与 markdown 均须有正文。

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
