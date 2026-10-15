# brain/schemas（补全信封）测试 spec

状态：已确认（2026-10-15）。上位文档：`docs/test/brain-test-intent.md` 第 11 节。探针基线：`ae03dff` 的干净导出。

## 被测对象

`pokemon_agent/brain/schemas/`：四个 pydantic 模型 `LlmCompleteReq`、`LlmCompleteResp`、`VisionDescribeReq`、`VisionDescribeResp`，以及包出口 `pokemon_agent.brain.schemas`（`__all__` 恰为这四个名字）。
已有 `tests/brain/schemas/test_llm_complete_req_roundtrip.py`（0915 事故回归钉：`prompt` 字段被误删、pydantic 静默忽略未知字段）——**不改、不删、不搬**。本步新增 `tests/brain/schemas/test_envelopes.py`，补它没覆盖的：默认值、必填、类型拒绝、序列化往返、出口。

## 怎么观察

只构造模型、读字段、`model_dump()`、`model_validate()`、`model_dump_json()`。不读 `model_fields` 之类的内省（用 `model_dump().keys()` 看字段集合）。不需要任何替身，不需要环境变量。

## 探针（真实代码，输入→实际输出）

| 输入 | 实际 |
|---|---|
| `from pokemon_agent.brain.schemas import *` 的 `__all__` | `['LlmCompleteReq','LlmCompleteResp','VisionDescribeReq','VisionDescribeResp']` |
| `LlmCompleteReq()` | `ValidationError`，位置 `prompt`，类型 `missing` |
| `LlmCompleteReq(prompt="p")` | `thinking is None` |
| `LlmCompleteReq(prompt="p", thinking=True/False)` | 原样保留 |
| `LlmCompleteReq(prompt=None)` / `prompt=5` | `ValidationError`（`string_type`） |
| `LlmCompleteReq(prompt="p").model_dump()` 的键 | `{prompt, thinking}` |
| `LlmCompleteResp()` | `ValidationError`，位置 `text` |
| `LlmCompleteResp(text="x")` | `prompt_tokens`、`completion_tokens`、`cached_tokens`、`reasoning_tokens` 都是 0，`truncated is False` |
| `LlmCompleteResp(...).model_dump()` 的键 | `{text, prompt_tokens, completion_tokens, cached_tokens, reasoning_tokens, truncated}` |
| `VisionDescribeReq(images=[], prompt="q")` | `ValidationError`，位置 `images`，类型 `too_short` |
| `VisionDescribeReq(prompt="q")` / `(images=["a"])` | `ValidationError`，位置分别是 `images` / `prompt`，类型 `missing` |
| `VisionDescribeReq(images="abc", prompt="q")` / `images=[1]` | `ValidationError`（`list_type` / `string_type`） |
| `VisionDescribeReq(images=["a","b"], prompt="")` | 接受（空 prompt 在信封层不拦；`describe()` 才拒，那是 providers 的事） |
| `VisionDescribeReq(...).model_dump()` 的键 | `{images, prompt}` |
| `VisionDescribeResp()` | `ValidationError`，位置 `text` |
| `VisionDescribeResp(text="x")` | `input_tokens`、`output_tokens`、`cached_tokens`、`reasoning_tokens` 都是 0 |
| `VisionDescribeResp(...).model_dump()` 的键 | `{text, input_tokens, output_tokens, cached_tokens, reasoning_tokens}` |
| 四个模型各自 `X.model_validate(x.model_dump()) == x`；`model_dump_json` → `model_validate_json` 同样相等 | 成立 |

## 要钉的契约（测试清单）

文件 `tests/brain/schemas/test_envelopes.py`
1. 包出口只导出这四个名字，且都能从 `pokemon_agent.brain.schemas` 取到。
2. 必填字段：缺 `prompt`（`LlmCompleteReq`、`VisionDescribeReq`）、缺 `text`（两个 Resp）、缺 `images` 都被拒（参数化）。
3. 默认值：`LlmCompleteReq.thinking is None`；`LlmCompleteResp` 四个 token 数为 0 且 `truncated is False`；`VisionDescribeResp` 四个 token 数为 0（两个 Resp 参数化）。
4. `thinking` 三态（`None`/`True`/`False`）原样保留。
5. 类型拒绝：`prompt` 为 `None` 或数字被拒；`images` 为裸字符串或含非字符串元素被拒。
6. `images` 至少一张：空列表被拒；一张、多张接受且顺序保持。
7. 空 prompt 在信封层被接受（`VisionDescribeReq(images=["a"], prompt="")`）——钉的是「信封不替 provider 做内容校验」这层分工。
8. 字段集合：四个模型各自 `model_dump()` 的键恰好等于探针表里的集合（这是对「字段被静默删除」的守卫，0915 事故的泛化版；不与已有 roundtrip 测试重复——那条只守 `prompt`）。
9. 往返：四个模型各自经 `model_dump()` / `model_validate()` 与 `model_dump_json()` / `model_validate_json()` 往返后相等（参数化）。

预期约 25–35 条（参数化展开后计）。

## 不测

- pydantic 对未知字段的默认忽略行为：那是库的行为，不是本模块的契约；字段被删的风险已由契约 8 守住。
- 数字字符串到整数的宽松转换（`"3"` → `3`）：同上，库的行为。
- brain 与 world 两份 `VisionDescribe*` 副本字段是否同构：两个模块互不依赖，这条跨模块守卫归 world 目录或集成阶段，不在 brain 内做。
- 私有成员、`model_fields` 内省一律不碰。

## 测试风格

用法示范：Arrange / Act / Assert 以空行分段，句子式测试名；不用 `unittest.mock`；无 `__init__.py`；不新增替身。

## 破坏验证（必做，各一次，做完立即还原，每次确认 `git diff pokemon_agent/` 为空）

- (a) `VisionDescribeReq.images` 的 `Field(min_length=1)` 去掉（变成 `images: list[str]`）：契约 6 必须失败。
- (b) `LlmCompleteResp.truncated` 的默认值 `False` 改成 `True`：契约 3 必须失败。
- (c) `LlmCompleteReq.thinking` 的默认值 `None` 改成 `False`：契约 3 必须失败。
- (d) 在 `LlmCompleteResp` 里删掉 `reasoning_tokens` 字段：契约 8 必须失败（已有 roundtrip 测试守不到它）。
- (e) `VisionDescribeResp.cached_tokens` 的默认值 `0` 改成 `1`：契约 3 必须失败。
- 若某个破坏的字面写法套不上，用等效的最小破坏代替并在汇报里写明。

## 停止条件

- 实际行为与上面探针表不符；
- 需要改 `pokemon_agent/` 才能让测试通过；
- 需要 `unittest.mock`，或需要访问带下划线的私有属性；
- 站位不是 `tests/brain-unit` 的 `ae03dff` 或其后代。
