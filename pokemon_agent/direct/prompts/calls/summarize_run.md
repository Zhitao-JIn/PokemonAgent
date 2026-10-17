你负责对一次 run 做整体复盘。总目标：$run_goal
终止类别：$termination；判定依据：$judge_reason
累计 $episodes 局，其中 $succeeded 局成功，使用 $acts_used 键；局数预算 $max_episodes。

目标表最终定案：
$goals

各局记忆全文（来源章是当时的机器判定，目标表是最终定案）：
$episodes_text

请从「下次再接到同一个总目标，应该先做什么、避开什么」的视角总结。
成败以目标表最终定案为准，保留 note 和是否被人审推翻的含义，不得自行改写成败。
不得复述帧数据或 base64。仅输出 JSON 对象，字段如下：
{"summary":"整体简明总结", "reason":"结论说明", "reusable_patterns":[],
 "critical_decisions":[], "failure_points":[], "quality_score":0.5,
 "quality_rationale":"评分理由", "applicable_scenes":[], "tags":[],
 "markdown":"可复用的完整 Markdown 复盘正文"}
quality_score 范围 0 到 1；summary 与 markdown 均须有正文。
