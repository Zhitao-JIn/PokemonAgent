# intent —— 模型选型重排：不再考虑豆包，新增 Claude / ChatGPT 两个 provider

> 流程位置：**intent.md（已确认搭配；Q3、Q4 待用户）** → spec → plan → 落码
> 关联：`pokemon_agent/brain/providers.py`、`pokemon_agent/brain/build_llm_providers.py`、
> `pokemon_agent/brain/interface/llm_provider.py`、`pokemon_agent/settings/default.json`（`models` 节）、
> `evals/config.json`、`evals/brain_choose` 等五个脑能力评测
> 本文只写最终意图与候选；字段、函数、数值、阈值与实施顺序归 spec。
> 数据日期：2026-10-23。价格、分数来自公开页面，落 spec 前须逐条回到官方页复核。

---

## 一、一句话意图

新选型不再考虑豆包（Ark）；为 `brain` 补上 Claude、ChatGPT（OpenAI）两家 provider。
**价格最重要：所有模型位置（含评测评分员）都不超过 qwen-plus 价格线，按含缓存的实际单 run 成本比较。**
在价格线内按角色重要程度分级：**plan / decompose、verify、summarize 最重要**，分到线内最强的第一、第二名模型；
choose、judge 调用量大、重要度较低，分到其余。三条厂商约束：①plan 与 judge 不同厂商；
②verify 与 choose、plan 都不同厂商（防止 verify 漏判）；③评测评分员与被测候选不同厂商。
用现有评测加一个新增的 verify 评测，在真实请求上定最终型号。

## 二、为什么这样做（证据）

### 1. 现状

`default.json` 的 `models`：`text`=qwen-plus、`judge`=qwen3.8-max、`verify` 与 `plan`=doubao-seed-2-1-pro。
`verify` 位置同时服务 verify 与 summarize 两个方法，`plan` 位置同时服务 plan 与 decompose。
`_PROVIDER_PREFIXES` 只认 `deepseek` / `doubao` / `qwen`。`evals/config.json` 里评测的四个位置与评分员
（`evaluation_models.result_grader`）现已由评测配置分别指定。`plan` 已按本意图先行打开 thinking
（`thinking: true`、`max_tokens: 25600`、`timeout_s: 90`），型号暂未换。

### 2. 每个位置的画像（`tracelog` 实测与 `default.json` 预算上限）

上限按 10 局 × 6 task × 12 步 ≈ 720 步推算；耗时、token、命中率为实测均值（Qwen / 豆包），样本不大，仅作量级。

| 位置 / 方法 | 做什么 | 每 run 最多调用 | 每次输入 / 输出 token | 缓存命中 | 现状耗时 | 重要程度（用户确认） |
|---|---|---|---|---|---|---|
| `plan` / plan、decompose | 定整局方向、把目标拆成 task，带最多 20 张图 | ≤20、≤12 | 1.8K、2.7K / 160、246（未含 thinking） | 69%、80% | 1.6、2.2 秒 | **最高**：错了整局白走 |
| `verify` / verify | task / 局结束后批量审查记忆，逐条标正负样本；标注连同原记录交给蒸馏 | ≤70（task 结束 ≤60 + 局结束 ≤10） | 1.8K / 78 | 43% | 1.3 秒 | **最高**：漏判会把错误操作蒸馏成经验并跨局传播 |
| `verify` / summarize | 把验证过的记录蒸馏成 task / 局 / run 摘要，即跨局记忆 | ≤61 | 1.4K / 640–1100 | 0% | 4–6 秒 | **最高**：摘要是下一个 run 读到的"经验" |
| `judge` / judge | 每步判断当前目标已达成 / 继续 / 受阻，决定流程走向 | 约 720 | 3.8K / 45 | 64% | 1.3 秒 | 中：每步在环里，但有 verify 事后审查兜底 |
| `text` / choose | 选一个动作，输出约 6 token | 约 720 | 5.2K / 6 | 67% | 1.2 秒 | 中低：单步错可被停滞检测与下一步纠正；但串行 720 次，**每多 1 秒 ≈ 每 run 多 12 分钟** |

取舍规则：
1. **价格线对所有位置生效**（用户确认：价格最重要）。线内按重要度分配"最强"：plan / verify / summarize 先挑，choose / judge 用其余。
2. **plan / verify / summarize**：调用少 → 在线内用最强的模型、开 thinking、高 effort；时延不敏感。
3. **choose**：延迟是硬约束（先过时延门槛再比质量），不开 thinking。
4. **judge**：调用多、重要度中 → 低 effort、不开重推理。

### 3. 价格线与含缓存的成本

价格线：qwen3.7-plus 输入 ¥2 / 输出 ¥8（百炼官网，中国内地，0–256K，2026-10-22 页面）。比较用含缓存命中的单 run 成本，不比标价。
choose + judge 一个 run 最坏约 649 万输入 token（命中 427 万、未命中 222 万）、输出约 3.6 万：

| 模型 | 命中价 / 未命中价 | choose + judge 单 run（含缓存） | 不含缓存 |
|---|---|---|---|
| DeepSeek V4.1 Flash（闲时 / 忙时） | ¥0.02 / ¥1（忙时 ¥0.04 / ¥2） | 约 ¥2.5 / ¥4.9 | 约 ¥6.6 |
| Qwen3.8-Flash | 隐式命中约未命中价的 20%（待核实）/ ¥0.8 | 约 ¥2.6 | 约 ¥5.3 |
| GPT-6 Luna（token 数按 1.3 倍估） | $0.01 / $0.10 | 约 ¥2.6 | 约 ¥6.1 |
| Claude Haiku 5.5（token 数按 1.5 倍估） | $0.01 / $0.10，需显式设断点 | 约 ¥3.0 | 约 ¥7.1 |
| qwen3.7-plus（价格线基准） | 同上约 20% / ¥2 | 约 ¥6.4 | 约 ¥13.3 |

plan + decompose（约 19 万输入、thinking 输出按 20 万 token 估）单 run 约 ¥0.4 到 ¥1.1；verify + summarize（约 21 万输入、输出按 20 万估）单 run 约 ¥1 到 ¥2；
整套搭配一个 run 约 ¥5 以内。线外的 Sonnet 5.5 / Opus 5.5 / GPT-6.1 Sol / GPT-5.4 / Jev / DeepSeek V4 Pro / Qwen3.8-Max 均超线，不入选。
缓存命中率来自 Qwen / 豆包；Claude 要显式设 `cache_control` 断点才有缓存，OpenAI 要前缀 ≥1024 token 且逐字一致，换家后要在探针里重测。

### 4. 线内模型强度（第三方榜单，口径不一，仅作排序参考）

| 模型 | modelgrep 智能分 | 说明 |
|---|---|---|
| Claude Haiku 5.5 | 43.4 | 线内最强 |
| Qwen3.8-Flash | 40（AA） | 看图待探针 |
| DeepSeek V4.1 Flash | 39.5 | 推理模式测得；原生视觉 |
| GPT-6 Luna | 38.1 | 线内最弱 |

线内只有这四个厂商各一个可选型号，所以"最强的第一、第二名"就是 Haiku 5.5 与 Qwen3.8-Flash / DeepSeek V4.1 Flash（分数相近，待评测分先后）。

### 5. 两家新 provider 的接入事实（公开文档所述，未实测）

- **Claude（`claude-haiku-5-5`）**：必须走原生 Messages API
  （OpenAI 兼容层不适合生产：不支持 prompt caching、不返回 thinking、`reasoning_effort` 被忽略、`temperature<1` 报 400）；
  **必须不传 `temperature` / `top_p` / `top_k`**；文本+图片输入；缓存要显式设 `cache_control`（最小可缓存 512 token，缓存 5 分钟）。
  Haiku 5.5 的自适应 thinking 默认开（choose / judge 要调低 effort 或关闭）。
- **OpenAI（`gpt-6-luna`）**：$0.10 / $0.50，支持 Chat Completions 与图片，`reasoning.effort` 取 none…max，超过 272K 输入加价。
- **Jev、GPT-5.4**：均已评估并放弃（均超价格线）。

### 6. 约束（用户确认）

- **plan 与 judge 不同厂商。** 同厂商的训练来源带来的盲区会相互印证；`brain_scope` 的原则是 judge 复核生成者所依据的证据，
  复核者与被复核者应相互独立。Qwen / DeepSeek / Anthropic / OpenAI 视为四个厂商。
- **verify 与 choose、plan 都不同厂商。** verify 审查的是 choose 选出的动作和 plan 拆出的 task，审查者与被审查者同源时，
  同样的盲区会让问题"看不出来"。
- **评测评分员**：与被测候选不同厂商；价格同样不超线。

## 三、做什么

1. **补两个 provider**（实现随契约住在 `brain/`，遵守铁律 2：brain 对 `pokemon_agent.*` 外部依赖为零）：
   Claude（原生 Messages API，不传采样参数，支持 effort / 图，显式设 `cache_control` 断点）、
   OpenAI（Chat Completions，支持 effort / 图）。HTTP 沿用现有 `urllib` 做法，不新增 SDK 依赖。
2. **不再考虑豆包（已确认：只不考虑，不删除）。** 豆包相关代码、配置、测试与文档保持原样；
   `default.json` 里 `plan` / `verify` 现用的豆包型号随选型结果被替换。
3. **先测时延、可用性、缓存，再比质量。** 评测前先做探针：每个候选在真实请求上测 p50 / p95 时延、缓存命中率、
   图片输入（尤其 Qwen3.8-Flash）、thinking / effort、JSON 输出；choose 位置设时延门槛。
4. **防止 verify 漏判**（见第四节"verify 防漏判"）：厂商独立 + 最强模型 + 新增 `brain_verify` 评测 + 可选双审。
5. **换评测评分员**：由 deepseek-flash 改为按被测候选厂商选择的评分员；评测配置要能表达"两个评分员 + 选用规则"。
6. **定型顺序**：verify → plan → judge → choose（重要度高的先挑线内最强）；每步满足第二节第 6 条的厂商约束。
7. **配置**：`models.*` 的 `thinking` / `max_tokens` / `timeout_s` 与 effort 随新型号调整。密钥只进 `.env`。

## 四、候选（均在 qwen-plus 价格线内；定型顺序 verify → plan → judge → choose）

### verify / summarize（最重要；`verify` 位置同时服务两个方法）

| 候选 1 | 候选 2 | 候选 3 | 配置要点 |
|---|---|---|---|
| Claude Haiku 5.5 | DeepSeek V4.1 Flash | Qwen3.8-Flash（看图待探针） | 高 effort / thinking 开；summarize 输出长，看输出价；候选须与 choose、plan 不同厂商，GPT-6 Luna 为兜底 |

### plan / decompose（最重要；先定 verify，再定 plan，须 ≠ verify 厂商）

| 候选 1 | 候选 2 | 候选 3 | 配置要点 |
|---|---|---|---|
| DeepSeek V4.1 Flash（thinking 开） | Claude Haiku 5.5 | GPT-6 Luna | thinking 开、effort 中高；带最多 20 张图；`timeout_s` 90；与 verify、judge 不同厂商 |

### judge（重要度中；须 ≠ plan 厂商）

| 候选 1 | 候选 2 | 候选 3 | 配置要点 |
|---|---|---|---|
| GPT-6 Luna | DeepSeek V4.1 Flash | Claude Haiku 5.5 | 低 effort / 不开重推理；Claude 不能传 temperature，可复现性要重评 |

### choose（重要度中低；须 ≠ verify 厂商；先过时延门槛）

| 候选 1 | 候选 2 | 候选 3 | 配置要点 |
|---|---|---|---|
| Qwen3.8-Flash | Claude Haiku 5.5 | GPT-6 Luna | 全部不开 thinking（Haiku 关自适应 thinking，Luna effort=none）；DeepSeek V4.1 Flash（thinking 关）作后备 |

### 已定搭配（用户 2026-10-23 裁决；经三轮真实探针修订）

| 位置 | 型号 | 说明 |
|---|---|---|
| verify / summarize | Claude Haiku 5.5（thinking 开，effort high） | 图片与缓存（显式断点）已验证；生产暂不设缓存标记，成本只有几分钱 |
| plan / decompose | DeepSeek V4.1 Flash（thinking 开） | 图片全部通过，自动缓存约 80% |
| judge | Qwen3.8-Flash（thinking 关） | 图片通过，自动缓存约 91%；**原定 GPT-6 Luna 因看不清小图左右半边（detail 参数无效）且分消息缓存不稳定而放弃** |
| choose | Qwen3.8-Flash（thinking 关） | 时延中位数约 1.7 秒、最慢约 4.9 秒，低于 10 秒超时；与 judge 同厂商，约束未禁止 |

厂商约束仍满足：plan（DeepSeek）≠ judge（Qwen）；verify（Anthropic）≠ choose、plan。生产不再使用 OpenAI；`OpenAIProvider` 保留，供评测评分员等用途。
超出价格线的模型（MiMo-V2.6-Pro、GLM-5.2、Kimi K3、Qwen3.8-Max 等）不纳入；价格线不放宽。
落地顺序：先写 provider 与探针（已完成），再切换 `default.json` 的 `models`；评测用于事后验证，不作为切换前提。
choose 若评测显示 Qwen3.8-Flash 质量或时延不足，后备是 DeepSeek V4.1 Flash（关 thinking，探针时延中位数约 1.0 秒）。

### 选型理由

| 位置 | 入选理由 | 落选 / 排序理由 |
|---|---|---|
| verify / summarize | **Haiku 5.5**：线内分数最高，漏判后果最重的位置先给最强；**DeepSeek V4.1 Flash**：原生视觉、命中价最低，可做第二审；**Qwen3.8-Flash**：便宜 | GPT-6 Luna 分数最低，只作兜底 |
| plan / decompose | **DeepSeek V4.1 Flash**：原生推理、已在复核席使用视觉；与 verify 首选 Haiku 不同厂商；**Haiku 5.5**：分数最高，若 verify 未选它则可上；**Luna**：effort 可调 | 调用 ≤32 次，thinking 成本仅几毛到一块钱，不受价格困扰 |
| judge | **Luna**：支持图、effort 可调，且与 plan（DeepSeek）、verify（Haiku）都不同厂商；**DeepSeek V4.1 Flash**；**Haiku 5.5** | 每步判成败有 verify 事后兜底，重要度低于 verify / plan |
| choose | **Qwen3.8-Flash**：¥0.8 / ¥2.7，零新代码，时延最可能接近现状；**Haiku 5.5**；**Luna** | DeepSeek V4.1 Flash 的榜单分是推理模式测的，choose 不开 thinking，且有时延风险 |

**证据强度**：分数来自第三方榜单，口径不一；价格来自官方页；各家时延、缓存、图片能力未实测。
以上排序是**待探针与评测验证的假设**，最终以 `evals/` 里的评测结果为准。

### verify 防漏判

1. **厂商独立（硬）**：verify 与 choose、plan 不同厂商。
2. **线内最强模型 + 开 thinking + 高 effort**：verify 一个 run ≤70 次，成本约 ¥1，在线内。
3. **新增 `brain_verify` 评测**：现有五个脑能力评测（choose、plan、decompose、judge、summary）里没有 verify。
   用"故障注入"量化漏判：取冻结记录中已知有问题的步（原地不动、方向相反、声称效果与前后快照矛盾），
   再人工构造矛盾（改写"之后变成"使其与声称不符），指标是**负样本召回率**和**误杀率**；通过门槛在 spec 定。
4. **双审（建议启用）**：第二个不同厂商的 verifier（如 DeepSeek V4.1 Flash）对第一个判"正"的记录复审，任一判负即按负处理（OR），
   提高召回；因为 verify 调用少且模型在线内，费用翻倍也只多约 ¥1 / run。
5. 现有 prompt 已要求"前后快照对不上就判负、截图用来核对文字有没有抽错"，本任务不改 prompt。

### 评测评分员（取代 deepseek-flash；同样在价格线内）

| 被测候选厂商 | 评分员 | 说明 |
|---|---|---|
| Anthropic（Haiku） | DeepSeek V4.1 Flash（thinking 开） | 不同厂商；分数略低于被评对象，是线内的最佳独立选择 |
| 其他（OpenAI / Qwen / DeepSeek） | Claude Haiku 5.5 | 线内最强，且不同厂商 |

Inspect AI 有原生 `anthropic/` 与 DeepSeek（openai-api）接入，用现有 `.env` 的 key，不依赖我们要新写的 brain provider。
评分调用量：以 choose 评测为例，冻结 189 条请求，每个候选一个评测约 100 万输入 token，Haiku 5.5 约 $0.3（含输出，粗估）；
五个评测 × 多个候选总额预计几美元量级。两个评分员的打分尺度不一定一致，跨候选比较前要做标定。
若之后需要更强的评分员做抽检校准，须另行授权（超线）。

## 五、不做什么

- 不接入 Jev，不使用 GPT-5.4，不使用任何超价格线的模型（含 Sonnet / Opus / GPT-6.1 Sol）。
- 不删除任何豆包相关代码、配置、测试与文档。
- 不改 `Action` 契约、不改 prompt 模板内容。
- 不动 memory 的 embedding / reranker、world 的感知、trace 的结构。
- 不在本任务里改 `default.json` 的生产型号：先出评测结果，由用户拍板后另开检查点改默认值（`plan` 的 thinking 开关除外，已先行打开）。
- 不用 Anthropic 的 OpenAI 兼容层，不引入 Anthropic / OpenAI 官方 SDK。
- 不把 verify 与 summarize 拆成两个模型位置（需要改配置结构；如需要另案）。

## 六、需要用户确认的问题

1. **Q1 豆包（已确认）。** 不删代码，只在选型里不再考虑。
2. **Q2 价格线（已确认）。** 所有位置（含评分员）都不超 qwen-plus 线，价格最重要。
3. **Q3 verify 防漏判。** ①是否新增 `brain_verify` 评测（会增加一个评测任务和一份冻结数据）？②是否启用双审（verify 费用约多 ¥1 / run）？
4. **Q4 真实运行授权。** 探针与评测会产生真实调用费用（预计几美元量级），每一次真实运行需要用户单独授权。

## 七、影响面

- `brain/`：新增两个 provider（Haiku 5.5、GPT-6 Luna）；`_PROVIDER_PREFIXES` 与 `build_llm_providers` 变化；Ark 相关代码不动。
- `settings/`：`models` 节的型号与超参；`schema` 若需要新增字段（如 effort）。
- `evals/`：评分员按被测厂商选择，评测配置表达"两个评分员 + 选用规则"；新增 `brain_verify` 评测（若 Q3 确认）。
- `tests/brain/**`：新增两个 provider 的单元测试；Ark 相关测试不动。
- `docs/`：`docs/spec/brain/SPEC.md`、`docs/spec/build/SPEC.md`、`docs/test/brain-*` 与 AGENTS.md / CLAUDE.md 需补充两家新 provider；豆包的描述不动。
- `.env`：已有 `ANTHROPIC_API_KEY`、`OPENAI_API_KEY`。

## 八、风险

1. 线内只有四个型号、能力差距不大；"最强第一第二"的分数只差几分，榜单排序不可靠，最终靠评测。
2. Qwen3.8-Flash 能否看图未核实；不支持时 verify / plan 的第三候选消失，三条厂商约束的可行搭配减少。
3. Claude 的原生 API 不能传 `temperature`，而 `judge` 现在配置的是 `temperature: 0.0`；provider 需按型号忽略该参数，judge 的可复现性要重评。
4. 缓存命中率是按 Qwen / 豆包实测的，Claude 若漏设 `cache_control`、OpenAI 前缀不足 1024 token 或步间变化，成本回到"不含缓存"，仍应在线内但需复核。
5. thinking 输出量由 effort 与 `max_tokens` 控制；plan 位置带最多 20 张图，输入 token 随张数增长。
6. verify 漏判是跨局污染的源头，`brain_verify` 评测若不做，只能靠厂商独立与线内最强模型兜底，无法量化。
7. 价格与分数来自第三方榜单，可能有出入；spec 前必须逐条回官方页核对。

## 九、成功的样子

- 两个新 provider 通过单元测试与一次真实探针（可用性、时延、缓存命中、图、thinking / effort、JSON 输出、错误分类）。
- 每个位置的候选在对应评测上有同口径的结果、时延分布与含缓存的单 run 成本估算；verify 有负样本召回率与误杀率。
- 用户据此拍板各位置型号；最终搭配满足全部厂商约束；新选型里不含豆包。
