# spec —— Claude / OpenAI 两个 provider 与选型落地（v1.4）

> v1.1 修订原因：CP1 执行方核对官方文档发现 Haiku 5.5 无 thinking 预算，D4 的预算断言不成立，改为 adaptive + effort。
> v1.2 修订原因：CP1 执行方发现 `_post` 把 OpenAI 请求形状写死，原生 Anthropic 请求无法复用；批准基类拆出 `_build_request` 钩子（D13）；同时发现 prompt 是整串文本、无静态/动态分界，缓存断点改为可选参数、默认关（D3）。

> 依据：`docs/model_providers/intent.md`（搭配已定）。本文是执行依据；与 intent 不一致时以本文为准。
> 编号：620（CP1）/ 621（CP2）/ 622（CP3）/ 623（CP4）。
> v1.3 修订原因：探针实测（`.coordination/model-probe/` 三个目录）显示：Luna 单条 user 消息 7/7 次缓存为 0，改成 developer + user 分消息后命中 99%；Luna 在 160×144 小图上分不清左右半边（Claude、Qwen 能分清）。新增 D14、D15 与检查点 626；原 CP4 改为在 626 之后做，并包含把 `cache_marker` / `image_detail` 接进配置（D16）。
> v1.4 修订原因：626 补测显示 GPT-6 Luna 小图左右半边分不清且 detail 参数无效、分消息缓存不稳，judge 改为 Qwen3.8-Flash；D11 更新，D16（配置接线）取消，CP4 只改型号与文档。

## 一、决定表

| # | 决定 | 取舍 |
|---|---|---|
| D1 | 新增 `ClaudeProvider`（前缀 `claude-`），**原生 Messages API**：`POST https://api.anthropic.com/v1/messages`，头 `x-api-key`、`anthropic-version: 2023-06-01`；key 从 `ANTHROPIC_API_KEY` 读（只读这一个名字，不读 `ANTHROPIC_AUTH_TOKEN`） | 不用 Anthropic 的 OpenAI 兼容层（无缓存、无 thinking 输出、`temperature<1` 报错）；不引入官方 SDK，沿用 urllib |
| D2 | Claude 请求体**不带** `temperature` / `top_p` / `top_k`；构造函数仍收 `temperature`（接口不变），`config()` 里如实记 `temperature_sent=false` | `judge` 现配 0.0，Claude 上该值被忽略；可复现性靠评测重测 |
| D3 | Claude 缓存（v1.2 修订）：构造参数 `cache_marker: str \| None = None`。为 `None` 时**不发任何 `cache_control`**；给定字符串时，把 prompt 在该字符串**首次出现处之前**切成静态前缀块，在这一块末尾放一个 `cache_control: {"type":"ephemeral"}` 断点，余下文字为动态尾部块（图片仍在最后）；找不到标记时退回不发断点。**默认关**，是否启用与用哪个标记，留待 CP3 探针和 CP4 视各位置 prompt 决定 | 现有 prompt 是一整个字符串，静态规则与动态素材之间没有标记；整块放断点只会白付 1.25 倍写入价而永远不命中。verify 位置每 run ≤70 次、约 1.8K token，不缓存的成本也只有几分钱 |
| D4 | Claude thinking（v1.1 按官方文档修订）：`thinking=false` 发 `thinking: {"type":"disabled"}`，不发 effort；`thinking=true` 发 `thinking: {"type":"adaptive"}` 并带 `output_config: {"effort": <effort>}`（构造参数 `effort`，默认 `"high"`，取值 low / medium / high / xhigh / max）。官方已取消手动 thinking 预算（`budget_tokens` 会 400），所以**不做 max_tokens 与预算的比较断言**；thinking 的 token 计入 `max_tokens`，不够时由 `stop_reason == "max_tokens"` 报截断，调用方按现有截断流程处理 | Haiku 5.5 默认开自适应 thinking，必须显式关；字段名来自官方 Haiku 5.5 提示指南与迁移指南 |
| D5 | Claude 响应解包：`content` 里取所有 `type=="text"` 块拼接；`usage.input_tokens + cache_read_input_tokens + cache_creation_input_tokens` 之和作为 `prompt_tokens`，`cache_read_input_tokens` 作为 `cached_tokens`；`stop_reason == "max_tokens"` 为截断；`reasoning_tokens` 取不到记 0；正文为空照旧抛 `EmptyCompletion` | 与现有 `_unpack` 返回的六元组同形，上层不改 |
| D6 | Claude 图片：`{"type":"image","source":{"type":"base64","media_type":"image/png","data":<去掉 data URI 头的 base64>}}`；多图逐张发（不拼网格）；`describe()` 保持「文字在前、图在后」 | 与现有帧格式（完整 data URI）互转只在 provider 内部 |
| D7 | 新增 `OpenAIProvider`（前缀 `gpt-`），Chat Completions：`POST https://api.openai.com/v1/chat/completions`，`Authorization: Bearer`，key 读 `OPENAI_API_KEY`；沿用 `_OpenAICompatibleBase` 的 `_post` / `_unpack`；token 上限字段用 `max_completion_tokens`（不是 `max_tokens`）；缓存是自动前缀缓存，不需任何请求参数 | 复用最多 |
| D8 | OpenAI thinking：`thinking=false` → `reasoning_effort: "none"`；`thinking=true` → `reasoning_effort` 取构造参数 `effort`（默认 `"medium"`）；**以官方文档与探针为准**，若模型不接受 `none`，在汇报里写出实际报错与可用取值 | judge 用 Luna，不开重推理 |
| D9 | 不改 `Action` 契约、不改 prompt 模板；`LLMProvider` / `JudgeProvider` 协议、`BrainLlmConfig` / `LinkSpec` 字段不变，**`effort` 暂不进配置**：provider 内部用默认值，配置化留到 CP4 视探针结果决定 | 控制检查点大小 |
| D10 | `_PROVIDER_PREFIXES` 增加 `("claude-", ClaudeProvider)` 与 `("gpt-", OpenAIProvider)`，`provider_for` 的报错信息自动带上新前缀；豆包条目与类**原样保留** | 豆包不删 |
| D11 | 最终搭配（CP4 才生效；v1.4 据探针修订）：`text = qwen3.8-flash`（thinking 关，temperature 0.3，max_tokens 25600，timeout 10 s）；`judge = qwen3.8-flash`（thinking 关，temperature 0.0，max_tokens 25600，timeout 45 s）；`verify = claude-haiku-5-5`（thinking 开，temperature 0.0（Claude 不发送），max_tokens 16000，timeout 60 s；effort 取 provider 默认 high；不配缓存标记）；`plan = deepseek-flash`（thinking 开，temperature 0.0，max_tokens 25600，timeout 90 s）。GPT-6 Luna 不进生产（见 intent） | 见 intent 第四节 |
| D12 | 探针脚本放 `scripts/probe_models.py`，真实调用只在 CP3 且需用户授权；默认不跑；结果落 `.coordination/model-probe/<时间戳>/`（不入 git） | |
| D13 | 基类拆出一个请求构造钩子（v1.2 新增）：把 `_OpenAICompatibleBase._post` 里「拼 URL、请求头、请求体」抽成 `_build_request(self, content, think) -> tuple[str, dict[str, str], dict]`，默认实现**逐字保持**现有行为（`{base}/chat/completions`、Bearer 鉴权、`temperature` / `max_tokens`、thinking 载荷、`response_format`）；`_post` 其余部分（线程池总时长闸、错误分类）原样共用。`ClaudeProvider` 覆盖 `_build_request` 与 `_unpack`、并用 `_image_part` 钩子产生图片块；`OpenAIProvider`（CP2）覆盖 `_build_request` 改用 `max_completion_tokens` | 复用传输与错误分类，只在「请求怎么拼、响应怎么读」上分叉；Qwen / DeepSeek / Ark 行为不变由既有测试保证 |
| D14 | `OpenAIProvider` 增加构造参数 `cache_marker: str \| None = None`（v1.3）：为 `None` 或标记找不到（或位置为 0）时行为不变（单条 user 消息）；找到时请求体 `messages` 改为两条：`{"role":"developer","content": <标记之前的文字>}` 与 `{"role":"user","content": <标记起的文字，带图时为 [文字块, 图片块…]>}`。`config()` 如实报告 `cache_marker`。依据：实测分消息布局第 2–6 次命中约 99%，单消息 0% | 与 Claude 的 `cache_marker` 同名同语义，生产配置里同一个字段 |
| D15 | `OpenAIProvider` 增加构造参数 `image_detail: str \| None = None`（v1.3）：不为 `None` 时在每个 `image_url` 里加 `"detail": <值>`（取值以官方文档为准，预期 low / high / auto），覆盖 `_image_part`；默认不变。依据：Luna 小图只算约 30 token，左右半边答错 | 先验证 `high` 是否能分清左右，再决定生产是否启用 |
| D16 | **取消**（v1.4）：不把 `cache_marker`、`image_detail`、`effort`、`token_floor` 接进配置；Claude 与 OpenAI 的这些参数保留为 provider 构造参数，生产使用默认值 | judge 不再用 OpenAI，verify 的缓存收益只有几分钱 |

## 二、检查点

| 检查点 | 编号 | 内容 | 允许改动的文件 | 验收核对点 |
|---|---|---|---|---|
| CP1 | 620 | `ClaudeProvider`（D1–D6、D10 前半）+ 单元测试（mock HTTP，不联网） | `pokemon_agent/brain/providers.py`、`tests/brain/providers/` 下新增文件、`CHANGELOG.md` | 请求体不含采样参数；缓存断点位置；thinking 开关两种形状；`usage` 求和；截断与空正文；图片块；`provider_for("claude-haiku-5-5")` 能构造；豆包相关测试不动 |
| CP2 | 621 | `OpenAIProvider`（D7、D8、D10 后半）+ 单元测试（mock HTTP） | 同上 | `max_completion_tokens`；`reasoning_effort` 两种取值；`cached_tokens` 读取；`provider_for("gpt-6-luna")` |
| CP3 | 622 | `scripts/probe_models.py` + 其单元测试；**真实探针一次**（授权见交接消息） | `scripts/probe_models.py`、`tests/scripts/` 下新增文件、`CHANGELOG.md` | 汇报每个位置候选的：可用性、p50/p95 时延、缓存命中率、图片是否送达、thinking/effort 是否生效、JSON 输出是否合法；Qwen3.8-Flash 是否看图 |
| CP3b | 626 | `OpenAIProvider` 加 `cache_marker`（D14）与 `image_detail`（D15）+ 单元测试；探针补测一次（Luna：detail="high" 的图片真实性；分消息 + 图片的组合）；不改配置 | `pokemon_agent/brain/providers.py`、`tests/brain/providers/test_openai_provider.py`、`scripts/probe_models.py`、`tests/scripts/`、`CHANGELOG.md` | 默认行为不变；真实结果原样汇报 |
| CP4 | 623 | 按 D11 改 `default.json` 的 `models`（只改型号与超参，不接新配置字段，D16 取消）；同步依赖默认模型名的既有测试、`AGENTS.md` / `CLAUDE.md` / `docs/spec/brain/SPEC.md` / `docs/spec/build/SPEC.md` 中对 provider 与默认型号的描述（只补事实，不重写）；全量 pytest 跑一次 | `pokemon_agent/settings/default.json`、依赖该文件型号名的测试、上述四份文档、`CHANGELOG.md` | 只改选型，不含评测结论；全量 pytest 与 ruff 全绿；默认配置能装配四个 provider（不联网） |

评分员配置（评测里的两个评分员 + 选用规则）与 `brain_verify` 评测**不在本 spec**：前者待探针通过后另立检查点；后者等用户回答 intent Q3 后另立。

## 三、测试清单

- `tests/brain/providers/test_claude_provider.py`：用本地假 HTTP 服务或 monkeypatch `urllib.request.urlopen`，不联网。覆盖 D2–D6、4xx→`ProviderRejected`、429/5xx→`ToolTimeout`、总时长闸。
- `tests/brain/providers/test_openai_provider.py`：同理，覆盖 D7、D8。
- `tests/brain/providers/test_provider_for.py`（若已存在则追加）：新前缀、未知前缀的报错信息。
- 探针脚本的单元测试只测参数解析与汇总计算，不发请求。

## 四、验证方式与费用

- CP1、CP2、CP4：不得调用真实模型。
- CP3：真实调用，每个位置的候选各打少量真实请求（文字 + 带图），预计总额低于 1 美元；**用户在交接消息里授权这一次**。

## 五、停止条件

- 官方文档与 D4 / D8 的字段名不符，或型号字符串不存在；
- 改动超出该检查点的允许文件范围；
- 起点 pytest / ruff 不全绿；
- 需要执行被禁止的 git 命令才能继续；
- 需要任何未授权的真实模型调用；
- 按 D13 拆出 `_build_request` 钩子后，Qwen / DeepSeek / Ark 的既有测试出现任何行为差异，或除 D13 规定之外还需要改基类。

## 六、非目标

不接入 Jev、GPT-5.4、任何超价格线模型；不删豆包；不改 prompt；不改 `Action`；不引入官方 SDK；不做评测与评分员配置（见上）。
