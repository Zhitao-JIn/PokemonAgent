# brain/providers（请求、错误、构造、选型）测试 spec

状态：已确认（2026-10-15）；**v1.2（2026-10-15）修订**：v1.1 曾按旧基线 `320517d` 删掉所有 `timeout_s` 条目；预算线已并入测试分支（合并提交 `84fd4a4`），`complete(req, *, timeout_s=None)` 与单请求总时长闸现在都在被测树里，v1.2 按 `84fd4a4` 的干净导出重新探针并补回这两部分（契约 8 完整版、契约 15）。上位文档：`docs/test/brain-test-intent.md` 第 9 节。
`providers` 目录分两步做：本份是第一步（构造、请求形状、响应映射、HTTP 失败分类、型号选型）；第二步（多模态发图、拼网格图、静默丢图检测）另写 spec，**本步不要提前写**。

## 被测对象

`pokemon_agent/brain/providers.py`：
- 基类 `_OpenAICompatibleBase` 与三个厂商类 `QwenProvider`、`ArkProvider`、`DeepSeekProvider`。测试只通过**公开面**：构造函数、`complete(req)`、`config()`、`multimodal` 属性。不碰带下划线的方法和属性。
- `provider_for(model, *, temperature, max_tokens=None, timeout=45, json_mode=False, thinking=False)`。
- `LlmCompleteReq(prompt, thinking=None)` / `LlmCompleteResp`（`pokemon_agent.brain.schemas`）。

## 怎么观察

- 新建共享替身 `tests/_doubles/http.py`：一个手写的 `urllib.request.urlopen` 替身（不用 `unittest.mock`），用 `monkeypatch.setattr("urllib.request.urlopen", ...)` 装上。它要能做到：
  1. 记录每次调用收到的 `req.full_url`、请求头（键小写）、解析后的 JSON 请求体、`timeout` 实参，并累计调用次数；
  2. 让下一次调用返回一个指定的响应体（JSON dict）；
  3. 让下一次调用抛指定异常（`urllib.error.HTTPError`、`URLError`、`ConnectionResetError`、`TimeoutError`）；
  接口形状由执行方自定，要求简单、有类型注解、一个文件、不超过约 80 行。本步四个新测试文件共用它。
- 已有的 `tests/brain/providers/test_provider_json_mode.py` 自带一份小替身，**不要改它、不要让它改用共享替身**（留到整个 brain 重写完成后统一整理）。
- key 环境变量用 `monkeypatch.setenv` / `monkeypatch.delenv` 控制：`DASHSCOPE_API_KEY`、`ANTHROPIC_AUTH_TOKEN`、`ARK_API_KEY`、`DEEPSEEK_API_KEY`。**每个测试开头先把这四个全部清掉再设需要的**，不能依赖机器上真实的环境变量。

## 探针（真实代码，输入→实际输出；已按 `84fd4a4` 的干净导出重跑，不是主工作区）

### 构造期

| 输入 | 实际 |
|---|---|
| 四个 key 变量全未设，`QwenProvider(temperature=0)` | `RuntimeError`，消息 `DASHSCOPE_API_KEY / ANTHROPIC_AUTH_TOKEN 均未设置`——**构造时就失败，不是调用时** |
| `ArkProvider("m", temperature=0)` 无 key | `RuntimeError`，消息 `ARK_API_KEY 均未设置` |
| 只设 `ANTHROPIC_AUTH_TOKEN`，造 Qwen | 成功，请求头用它（`Bearer <该值>`） |
| `DASHSCOPE_API_KEY=""`（空串）且 `ANTHROPIC_AUTH_TOKEN` 有值 | 空串被跳过，用后者 |
| 两个都设 | `DASHSCOPE_API_KEY` 优先 |
| 不给 `temperature` | `TypeError`（关键字必填） |
| `temperature=-0.1` / `2.1` | `AssertionError`，消息含 `temperature out of range` |
| `temperature=0` / `2.0` | 接受，`config()["temperature"]` 为 `'0'` / `'2.0'` |
| `QwenProvider("", ...)` / `DeepSeekProvider("", ...)` / `ArkProvider("", ...)` | 都是 `AssertionError`（三条消息各不相同） |
| `ArkProvider(temperature=0)`（不给 model） | `TypeError`（Ark 的 model 必填） |
| `QwenProvider(temperature=0)` / `DeepSeekProvider(temperature=0)` 的缺省 | model 分别是 `qwen3.8-max` / `deepseek-flash`；`max_tokens` 缺省 `'25600'`；`multimodal is True` |
| 三家 `config()["base_url"]` | `https://dashscope.aliyuncs.com/compatible-mode/v1`、`https://ark.cn-beijing.volces.com/api/v3`、`https://api.deepseek.com` |
| `config()` 的键 | `provider`、`model`、`temperature`、`max_tokens`、`json_mode`、`thinking`、`base_url`，值全是字符串；不含 key |

### 请求形状（对 `complete(LlmCompleteReq(prompt="hi"))` 观察）

| 项 | 实际 |
|---|---|
| URL | 在 base_url 后加 `/chat/completions`（三家各一条） |
| 请求头 | `authorization: Bearer <key>`，`content-type: application/json` |
| 请求体 | `{"model": ..., "temperature": 0.3, "max_tokens": 77, "messages": [{"role":"user","content":"hi"}], ...思考字段}`；`temperature`、`max_tokens` 是数字（不是字符串） |
| 思考字段（默认关） | Qwen 为 `enable_thinking: false`；Ark 与 DeepSeek 为 `thinking: {"type":"disabled"}` |
| 思考字段（开） | Qwen 为 `enable_thinking: true`；Ark 与 DeepSeek 为 `thinking: {"type":"enabled"}` |
| 单次覆盖 | 构造时 `thinking=True`：`req.thinking=None` 开、`False` 关、`True` 开；构造时缺省（关）：`req.thinking=True` 开、`None` 关 |
| `json_mode=True` | 请求体多一个 `response_format: {"type":"json_object"}`（已有测试覆盖，本步不重复） |
| 传给 `urlopen` 的 `timeout` | 缺省 45；构造时 `timeout=9` 则为 9；`complete(req, timeout_s=7.5)` 则这一次为 7.5（只影响这一次，下一次不带 `timeout_s` 又回到构造时的值） |
| `complete(req, timeout_s=0)` / `-1` | `ValueError`，消息 `timeout_s must be positive`；**在发出请求之前**抛，替身调用次数不增加 |
| `complete(LlmCompleteReq(prompt=""))` | `AssertionError`，消息含 `empty prompt` |

### 响应映射

| 响应体 | 实际 |
|---|---|
| 完整 usage（`prompt_tokens=11`、`completion_tokens=5`、`prompt_tokens_details.cached_tokens=3`、`completion_tokens_details.reasoning_tokens=2`） | `text`、`prompt_tokens=11`、`completion_tokens=5`、`cached_tokens=3`、`reasoning_tokens=2`、`truncated=False` |
| 没有 `usage` | 四个数字全是 0，`truncated=False` |
| `finish_reason="length"` | `truncated=True` |
| `finish_reason="stop"` 且 `completion_tokens=25600`（恰好写满） | `truncated=False`（判据是服务端的 `finish_reason`，不是 token 数） |
| `content` 为空串、`None` 或纯空白 | 抛 `EmptyCompletion`，带 `completion_tokens`、`reasoning_tokens`、`finish_reason`（`finish_reason` 缺失时为 `""`） |

### HTTP 失败分类

| 服务端行为 | 实际 |
|---|---|
| HTTP 400 / 401 / 403 / 404 | `ProviderRejected`，消息形如 `QwenProvider HTTP 401: <响应体>` |
| HTTP 500 / 502 / 503 | `ToolTimeout`，消息形如 `QwenProvider HTTP 503: <响应体>` |
| `URLError` / `ConnectionResetError` / `TimeoutError` | `ToolTimeout`，消息形如 `QwenProvider 调用不通：<异常类名>: ...` |
| 401 且响应体不含 key | 消息里没有 key，也没有 `Bearer` |
| HTTP 429 | **`ProviderRejected`**（见 O14，不钉） |

一次调用一个 HTTP 请求（已在基线上确认）：对 503 与 401 各调一次 `complete`，替身记录的调用次数都是 1（provider 层不重试）。

### `provider_for`

| 输入 | 实际 |
|---|---|
| `"qwen3.8-max"` / `"doubao-seed"` / `"deepseek-flash"` | `QwenProvider` / `ArkProvider` / `DeepSeekProvider` |
| `"Qwen-x"`（大写开头） | `QwenProvider`（大小写不敏感） |
| `"qwen"`（恰好是前缀） | `QwenProvider` |
| `"doubao-qwen"` | `ArkProvider`（只看开头） |
| `"xqwen"`、`"gpt-4"` | `ValueError`，消息含该型号名与 `deepseek* / doubao* / qwen*` |
| `""` | `AssertionError`，消息含 `empty model name` |
| 不给 `temperature` | `TypeError` |
| 不给 `max_tokens` | 各家缺省 `'25600'`；给 `max_tokens=5` 则 `'5'` |
| 连调两次同样参数 | 两个不同的实例 |

## 要钉的契约（测试清单）

文件 `tests/brain/providers/test_provider_construction.py`
1. 温度必须显式给出，且在 `[0, 2]` 闭区间内（0 与 2.0 接受，-0.1 与 2.1 拒绝，三家参数化）。
2. 型号名不能为空（三家各一条，参数化）；Ark 的型号名必填；Qwen 与 DeepSeek 有各自的缺省型号。
3. key 只在环境变量里找：Qwen 的 `DASHSCOPE_API_KEY` 优先，空串被跳过后落到 `ANTHROPIC_AUTH_TOKEN`；Ark、DeepSeek 只认各自一个变量；没有 key 时**构造即失败**（`RuntimeError`，消息点名所有候选变量名）。
4. 缺省值：`max_tokens` 为 `'25600'`、`multimodal` 为真；三家的 `base_url` 各自配套。
5. `config()` 自报七个键，值是字符串，且**不含 key**（把 key 设成一个独特的值，断言它不在 `str(config())` 里）。

文件 `tests/brain/providers/test_provider_request.py`
6. 请求落在 `base_url + /chat/completions`，带 Bearer 与 JSON 头；请求体含型号、温度、`max_tokens`（数字）与单条 user 消息（三家参数化）。
7. 思考开关：默认关、构造时开；各家字段形状不同（Qwen 扁平布尔、Ark 与 DeepSeek 嵌套对象）；`req.thinking` 对单次请求覆盖构造时的设置，`None` 沿用构造时的设置。
8. 超时的传递：缺省 45、构造时给的值原样传给 `urlopen`（参数化）；`complete(req, timeout_s=x)` 只覆盖这一次（`urlopen` 收到 x，下一次不带 `timeout_s` 回到构造时的值）；`timeout_s` 为 0 或负数 → `ValueError`，且替身调用次数为 0。
9. 空 prompt 在发出请求之前就被拒（`AssertionError`），且替身记录的调用次数为 0。

文件 `tests/brain/providers/test_provider_responses.py`
10. 响应字段映射：文本与四个 token 数都落到 `LlmCompleteResp`；缺 `usage` 时数字为 0。
11. `truncated` 只看 `finish_reason == "length"`（"stop" 且恰好写满不算截断）。
12. 空正文（空串、`None`、纯空白，参数化）抛 `EmptyCompletion`，并带出 token 数与 `finish_reason`。**这是对已有 `test_empty_completion.py` 的公开面版本**；已有文件调用了私有的 `_unpack`，本步不改、不删，留到整个 brain 重写完成后统一裁决。

文件 `tests/brain/providers/test_provider_errors.py`
13. 4xx（400、401、403、404，参数化）→ `ProviderRejected`；5xx（500、502、503，参数化）→ `ToolTimeout`；网络层异常（三种，参数化）→ `ToolTimeout`；消息里有 provider 类名，4xx/5xx 的消息里有状态码与响应体片段。
14. 一次调用一个请求：503 与 401 各调一次，替身记录的调用次数都是 1。
15. 单请求总时长硬闸：用一个会阻塞的 `urlopen` 替身（阻塞在 `threading.Event.wait()` 上，不真睡）；`complete(req, timeout_s=0.2)` 必须在约 2 秒内抛 `ToolTimeout`（消息含 provider 类名与 `调用不通`）而不是卡死；**替身必须在 `finally` 里 `set()` 事件**，让被丢弃的工作线程退出。只测 `timeout_s` 路径（此时总闸 = `timeout_s`）；缺省的 `timeout+15` 不测（要等 16 秒以上）。**此条依赖 Python ≥ 3.11**（`concurrent.futures.TimeoutError` 在 3.11 起才是内建 `TimeoutError` 的别名，3.10 上会漏过 `except`）：执行方必须用项目解释器先探针确认再写，探针结果与本条不符就停下报告。
16. key 不进错误消息：401 与 503 各一条，断言消息里既没有 key 的值也没有 `Bearer`。

文件 `tests/brain/providers/test_provider_for.py`
17. 前缀选厂商（三家参数化），大小写不敏感，只看开头（`xqwen` 不认、`doubao-qwen` 是 Ark）。
18. 不认识的前缀抛 `ValueError`，消息含该型号名；空型号名抛 `AssertionError`；温度必填。
19. `max_tokens` 不给时用各家缺省，给了就原样落到 `config()`；超时与 `json_mode`、`thinking` 原样转发（`json_mode`、`thinking` 的细节已有测试，这里各用一条确认转发即可）；每次调用造新实例。

## 不测

- 缺省总时长闸 `timeout+15`（太慢）；`describe(req, timeout_s=...)`：第二步。
- 多模态发图、`describe()`、静默丢图（`IMAGE_TOKEN_FLOOR`）、`image_grid_dims` / `pack_images_grid`、`_png_bytes`、落盘调试：第二步。
- `json_mode` 的请求体细节、"思考两种写法都发"：已有 `test_provider_json_mode.py` 覆盖，不重复。
- HTTP 429 的分类（O14）、`ArkProvider` 的缺省型号问题。
- 私有方法与属性：`_unpack`、`_post`、`_key`、`_timeout` 等一律不碰。

## 已知观察（不写测试，由我与用户裁决）

- O13（已撤回）：此前以为温度范围没有校验，其实基类构造里有 `assert 0.0 <= temperature <= 2.0`。契约 1 钉它。
- O14：HTTP 429（限流）被归为 `ProviderRejected`。按代码注释的口径，这一类"重试注定无用、让循环立即耗尽"；但 429 通常是瞬时限流，等一等往往能成功，与 5xx 同属"值得再试"。是不是应该和 5xx 一样归 `ToolTimeout`，待定。
- O15：模块把"型号名为空""温度越界"用 `assert` 校验，而它们的来源是装配点的配置；与 `provider_for` 的 docstring 里"配置写错是预期内的运行时情况、不用 assert"的说法不一致（`provider_for` 对未知前缀用了 `ValueError`，但对空型号名用的是 assert）。待定。

## 测试风格与规模

用法示范：Arrange / Act / Assert 以空行分段，句子式测试名；不用 `unittest.mock` / `MagicMock`；唯一的替身是共享的 `tests/_doubles/http.py`。
预期约 70–90 条（参数化展开后计）。

## 破坏验证（必做，各一次，做完立即还原）

- (a) 基类 `__init__` 里把 `assert 0.0 <= temperature <= 2.0` 的上界改成 `<= 3.0`：契约 1 的"2.1 拒绝"用例必须失败。
- (b) `QwenProvider.API_KEY_ENVS` 的两个名字顺序对调：契约 3 的"主变量优先"用例必须失败。
- (c) `_post` 里 4xx 的判断 `400 <= e.code < 500` 临时改成 `400 <= e.code < 404`：契约 13 里 404 的 `ProviderRejected` 用例必须失败（所以参数化里必须含 404）。
- (d) `_unpack` 里 `truncated = choices[0].get("finish_reason") == "length"` 改成 `usage.get("completion_tokens", 0) >= self._max_tokens`：契约 11 的"恰好写满"用例必须失败。
- (e) `ArkProvider._disable_thinking_payload` 返回 `{"thinking": {"type": "enabled"}}`：契约 7 的 Ark 默认关用例必须失败。
- 每次做完立即还原，并确认 `git diff pokemon_agent/` 为空。

## 停止条件

- 实际行为与上面探针表不符；
- 需要改 `pokemon_agent/` 才能让测试通过；
- 需要引入 `unittest.mock` / `MagicMock`，或需要访问带下划线的私有属性才能观察；
- 站位不是 `tests/brain-unit` 的 `84fd4a4` 或其后代（`QwenProvider.complete` 的签名里没有 `timeout_s`）；
- 契约 15 在项目解释器上的探针与上述描述不符。
