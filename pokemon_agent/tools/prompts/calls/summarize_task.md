你在整理一只玩神奇宝贝的 agent 的**单次 task 执行记录**。

一个 task 是一段有预算的按键执行（goal：$goal；task_id：$task_id）。下面是执行期内
逐键记录的情景记忆（"当时看到 → 做了 → 之后变成"）。每条都带标注：`【正样本】` 是推进了
目标的一键，`【负样本】` 是没有效果或偏离目标的一键，标注后面是理由——两类都要用，
负样本是 `failure_points` 的主要来源。结果：$result
（用了 $steps / $max_steps 键）。

$steps_text

## 你的任务

把**这一次 task 的前后变化**总结成一条 JSON 记忆，供上一层的 episode 总结与以后
的局检索复用。要求：

- `summary`：这一次 task 从什么状态走到什么状态、结果如何。**具体到字段/坐标/对话内容**，
  不写空话。
- `reason`：一两句话的**结论说明**——成了靠的是哪几键；没成卡在哪、为什么（结合「结果」
  里的终止类别：`goal_done` 达成 / `world_ended` 世界结束 / `stalled` 原地打转 /
  `budget_exhausted` 键数用尽）。「结果」里的**判定依据**是判定员当时为什么判停的理由，可以参考，
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
