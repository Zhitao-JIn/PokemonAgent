# spec —— Claude / OpenAI 两个 provider 与选型落地（v1.0）

> 依据：`docs/model_providers/intent.md`（搭配已定）。本文是执行依据；与 intent 不一致时以本文为准。
> 编号：620（CP1）/ 621（CP2）/ 622（CP3）/ 623（CP4）。

## 一、决定表

| # | 决定 | 取舍 |
|---|---|---|
| D1 | 新增 `ClaudeProvider`（前缀 `claude-`），**原生 Messages API**：`POST https://api.anthropic.com/v1/messages`，头 `x-api-key`、`anthropic-version: 2023-06-01`；key 从 `ANTHROPIC_API_KEY` 读（只读这一个名字，不读 `ANTHROPIC_AUTH_TOKEN`） | 不用 Anthropic 的 OpenAI 兼容层（无缓存、无 thinking 输出、`temperature<1` 报错）；不引入官方 SDK，沿用 urllib |
| D2 | Claude 请求体**不带** `temperature` / `top_p` / `top_k`；构造函数仍收 `temperature`（接口不变），`config()` 里如实记 `temperature_sent=false` | `judge` 现配 0.0，Claude 上该值被忽略；可复现性靠评测重测 |
| D3 | Claude 缓存：请求内容按「静态前缀 + 动态尾部」组块，在**静态前缀末尾**放一个 `cache_control: {"type":"ephemeral"}` 断点；静态前缀 = 现有 `prompt` 文本里图片之前的全部文字 | 实现只做一个断点，不做多断点；最小可缓存长度 512 token，不足时服务端不缓存也不报错 |
| D4 | Claude thinking：`thinking=false` 发 `thinking: {"type":"disabled"}`；`thinking=true` 发自适应 thinking 并带 `effort`（默认 `high`，构造参数 `effort` 可覆盖）；`max_tokens` 必须大于 thinking 预算，由 provider 在 `thinking=true` 时断言 | Haiku 5.5 默认开自适应 thinking，必须显式关；字段名与取值以官方文档为准，CP1 开工前先核对官方页，核对结果写进汇报 |
| D5 | Claude 响应解包：`content` 里取所有 `type=="text"` 块拼接；`usage.input_tokens + cache_read_input_tokens + cache_creation_input_tokens` 之和作为 `prompt_tokens`，`cache_read_input_tokens` 作为 `cached_tokens`；`stop_reason == "max_tokens"` 为截断；`reasoning_tokens` 取不到记 0；正文为空照旧抛 `EmptyCompletion` | 与现有 `_unpack` 返回的六元组同形，上层不改 |
| D6 | Claude 图片：`{"type":"image","source":{"type":"base64","media_type":"image/png","data":<去掉 data URI 头的 base64>}}`；多图逐张发（不拼网格）；`describe()` 保持「文字在前、图在后」 | 与现有帧格式（完整 data URI）互转只在 provider 内部 |
| D7 | 新增 `OpenAIProvider`（前缀 `gpt-`），Chat Completions：`POST https://api.openai.com/v1/chat/completions`，`Authorization: Bearer`，key 读 `OPENAI_API_KEY`；沿用 `_OpenAICompatibleBase` 的 `_post` / `_unpack`；token 上限字段用 `max_completion_tokens`（不是 `max_tokens`）；缓存是自动前缀缓存，不需任何请求参数 | 复用最多 |
| D8 | OpenAI thinking：`thinking=false` → `reasoning_effort: "none"`；`thinking=true` → `reasoning_effort` 取构造参数 `effort`（默认 `"medium"`）；**以官方文档与探针为准**，若模型不接受 `none`，在汇报里写出实际报错与可用取值 | judge 用 Luna，不开重推理 |
| D9 | 不改 `Action` 契约、不改 prompt 模板；`LLMProvider` / `JudgeProvider` 协议、`BrainLlmConfig` / `LinkSpec` 字段不变，**`effort` 暂不进配置**：provider 内部用默认值，配置化留到 CP4 视探针结果决定 | 控制检查点大小 |
| D10 | `_PROVIDER_PREFIXES` 增加 `("claude-", ClaudeProvider)` 与 `("gpt-", OpenAIProvider)`，`provider_for` 的报错信息自动带上新前缀；豆包条目与类**原样保留** | 豆包不删 |
| D11 | 最终搭配（CP4 才生效）：`text = qwen3.8-flash`（thinking 关，10 s）、`judge = gpt-6-luna`（thinking 关，45 s）、`verify = claude-haiku-5-5`（thinking 开，60 s）、`plan = deepseek-flash`（thinking 开，90 s，max_tokens 25600）；Qwen3.8-Flash 与 DeepSeek 型号字符串以官方文档与探针为准 | 见 intent 第四节 |
| D12 | 探针脚本放 `scripts/probe_models.py`，真实调用只在 CP3 且需用户授权；默认不跑；结果落 `.coordination/model-probe/<时间戳>/`（不入 git） | |

## 二、检查点

| 检查点 | 编号 | 内容 | 允许改动的文件 | 验收核对点 |
|---|---|---|---|---|
| CP1 | 620 | `ClaudeProvider`（D1–D6、D10 前半）+ 单元测试（mock HTTP，不联网） | `pokemon_agent/brain/providers.py`、`tests/brain/providers/` 下新增文件、`CHANGELOG.md` | 请求体不含采样参数；缓存断点位置；thinking 开关两种形状；`usage` 求和；截断与空正文；图片块；`provider_for("claude-haiku-5-5")` 能构造；豆包相关测试不动 |
| CP2 | 621 | `OpenAIProvider`（D7、D8、D10 后半）+ 单元测试（mock HTTP） | 同上 | `max_completion_tokens`；`reasoning_effort` 两种取值；`cached_tokens` 读取；`provider_for("gpt-6-luna")` |
| CP3 | 622 | `scripts/probe_models.py` + 其单元测试；**真实探针一次**（授权见交接消息） | `scripts/probe_models.py`、`tests/scripts/` 下新增文件、`CHANGELOG.md` | 汇报每个位置候选的：可用性、p50/p95 时延、缓存命中率、图片是否送达、thinking/effort 是否生效、JSON 输出是否合法；Qwen3.8-Flash 是否看图 |
| CP4 | 623 | 按 D11 改 `default.json` 的 `models`；文档补两家 provider；若探针显示需要 `effort` 配置化则一并做（schema + `LinkSpec`） | `pokemon_agent/settings/default.json`、`pokemon_agent/settings/` 内必要的 schema、`docs/spec/brain/SPEC.md`、`docs/spec/build/SPEC.md`、`AGENTS.md`、`CLAUDE.md`、`CHANGELOG.md` | 只改选型，不含评测结论；全量 pytest 绿；默认配置能装配四个 provider |

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
- 发现现有 `_post` 无法在不改变 Qwen / DeepSeek / Ark 行为的前提下复用（需要重构基类）。

## 六、非目标

不接入 Jev、GPT-5.4、任何超价格线模型；不删豆包；不改 prompt；不改 `Action`；不引入官方 SDK；不做评测与评分员配置（见上）。
