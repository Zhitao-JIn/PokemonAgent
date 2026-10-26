你在整理一只玩神奇宝贝的 agent 的**单次 task 执行记录**。

一个 task 是一段有预算的按键执行。文末「本次 task 的材料」给出它的 goal、task_id、结果，
以及执行期内逐键记录的情景记忆（"当时看到 → 做了 → 之后变成"）。每条都带标注：`【正样本】` 是推进了
目标的一键，`【负样本】` 是没有效果或偏离目标的一键，标注后面是理由——两类都要用，
负样本是 `failure_points` 的主要来源。

## 你的任务

把**这一次 task 的前后变化**总结成一条 JSON 记忆，供上一层的 episode 总结与以后
的局检索复用。要求：

- `summary`：这一次 task 从什么状态走到什么状态、结果如何。**具体到字段/坐标/对话内容**，
  不写空话。
- `reason`：一两句话的**结论说明**——成了靠的是哪几键；没成卡在哪、为什么（结合「结果」
  里的终止类别：`goal_done` 达成 / `world_ended` 世界结束 / `stalled` 原地打转 /
  `budget_exhausted` 键数用尽 / `interrupted` 半路被意外打断，比如遇敌）。「结果」里的**判定依据**是判定员当时为什么判停的理由，可以参考，
  但要写你自己看记录得出的结论，不要照抄它。上一层会直接读这句话决定下一步怎么拆。
- `reusable_patterns`：以后遇到同类目标可以直接照做的做法。
- `critical_decisions`：哪几步是转折（走对了或走错了）。
- `failure_points`：哪一步浪费了键数、为什么。
- `quality_score`（0.0–1.0）与 `quality_rationale`：这份记录对以后类似 task 的参考价值。
  记录空洞、前后无变化时相应压低，`quality_rationale` 里说明原因。
- `tags`：几个词。

只输出一个 JSON 对象，字段同 episode 蒸馏契约（summary / reason / reusable_patterns /
critical_decisions / failure_points / quality_score / quality_rationale /
applicable_scenes / tags / markdown）。

## 紧凑输出

保留所有约定字段，用最少文字保存可复核的经验。summary 和 reason 各用一至两句；
quality_rationale 用一句。三个经验列表各保留零至三条关键事实，无对应证据时用空数组。
markdown 用三至五个短要点，建议不超过二百个汉字，只补充可复用的证据与做法，
不要逐项重复 JSON 中已经写过的叙述，也不要抄录完整流水、目标或预算说明。
压缩不得丢失关键前后状态、实际终止类别、负样本及推翻结论的证据；
未经验证的解释要标为不确定，不能为凑短文把失败写成成功。

## 本次 task 的材料

goal：$goal；task_id：$task_id
结果：$result
（用了 $steps / $max_steps 键）。

$steps_text

<!-- labels -->
{
  "no_knowledge": "（没有检索到相关领域知识）",
  "none": "（无）",
  "success": "目标达成",
  "failure": "目标未达成",
  "result": "{0}（{1}）；判定依据：{2}",
  "goal": "- {0}｜{1}｜{2}｜note={3}｜overturned={4}",
  "no_goals": "（无目标条目）"
}
