## 蒸馏输出

只输出一个单层 JSON 对象，不加外层 summary 包装或其他文字；以下十个字段全部必填，不新增字段：
```json
{"summary":"实际起止状态与结果","reason":"结论及决定性证据","reusable_patterns":[],"critical_decisions":[],"failure_points":[],"quality_score":0.5,"quality_rationale":"参考价值与局限","applicable_scenes":[],"tags":[],"markdown":"可独立理解的完整 Markdown 记忆正文"}
```

- summary、reason、quality_rationale、markdown 是字符串；summary 和 markdown 均须有正文。
- summary 写实际起止与结果，具体到字段、坐标或对话，不写空话；reason 说明成了靠什么、没成卡在哪及原因，保留决定性原文或数值证据及参照时刻。
- reusable_patterns 写可照做的策略与经验；critical_decisions 写关键转折；failure_points 写浪费、偏离目标与潜在失败环节。三个字段及 applicable_scenes、tags 都是字符串数组；tags 用有意义的词。
- quality_score 是 0.0–1.0 的浮点数；quality_rationale 说明参考价值与适用局限。记录少、空洞、前后无变化或质量参差时相应压低评分并解释。
- applicable_scenes 只填写实际适用的稳定标签：`*`、`map:<数字>`、`scene:field`、`scene:indoor`、`scene:battle`、`scene:menu`、`scene:shop`、`overlay:dialog`、`overlay:choice`、`terrain:grass`、`interaction:npc`、`interaction:door`、`interaction:shop`、`interaction:pokemon_center`；通用经验用 `*`，不写自然语言长句。
- markdown 是可直接保存的完整 Markdown 正文，不包含 JSON 代码围栏。

## 紧凑且完整的结构

summary 与 reason 各一至两句，quality_rationale 一句；经验、转折、失败列表各零至三条有记录支持的内容，无证据用空数组，不编造失败或把假设写成发生过，未经验证的解释标为不确定。
字段分工而非反复改写：经验列表写方法，markdown 只补独有条件、限制与可复用证据，不重抄 JSON 各字段、完整流水、目标或预算；不复述帧数据或 base64。
压缩不得丢失关键前后状态、数值、位置归属、对象身份、证据类型、时间归属、验收边界、否定条件、真实终止类别、负样本或推翻成功结论的证据；多个必要事实宁可稍长也要完整。不从后续状态补造缺失原文，不把失败写成成功；来源章与记录不一致时保留差异，不补造完成。
输出前核对引号、方括号与大括号闭合；JSON 字符串里的换行使用转义，不增加文件名或协议外字段。
$compact_note

<!-- labels -->
{
  "task": "markdown 用三至五个短要点，建议不超过二百个汉字，保留可独立理解的关键条件。",
  "episode": "markdown 用二至四个短要点，建议不超过二百个汉字，不重复转述每个 task 的全文。",
  "run": "markdown 用短要点保存可复用的完整复盘正文与关键条件，不逐条复述各局全文。"
}
