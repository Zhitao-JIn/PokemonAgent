# brain/errors 测试 spec

状态：已确认（2026-10-14）。上位文档：`docs/test/brain-test-intent.md` 第 8 节。

## 被测对象

`pokemon_agent/brain/errors.py`：brain 自持的异常词汇。
- 根 `BrainError(Exception)`；直接子类：`ParseFailure`、`IllegalAction`、`EmptyCompletion`、`OutputTruncated`、`ToolTimeout`、`ProviderRejected`、`ImageNotDelivered`、`AttemptFailed`。
- `AttemptFailed` 的六个子类：`DecisionAttemptFailed`、`PlanAttemptFailed`、`DecomposeAttemptFailed`、`JudgeAttemptFailed`、`VerifyAttemptFailed`、`SummarizeAttemptFailed`。
- 这些类按失败类型归类统计（replay 用类名），外部 `except BrainError` / `except AttemptFailed` 依赖这套继承关系。

## 探针（真实代码，输入→实际输出）

`ModelCall(error_kind="ParseFailure", error="bad json")` 记作 `mc`。

| 输入 | 实际 |
|---|---|
| `DecisionAttemptFailed(mc)` | `.source=='choose'`，`str=="[choose] attempt failed: ParseFailure: bad json"`，`.call is mc` |
| `PlanAttemptFailed(mc)` | `.source=='plan'` |
| `DecomposeAttemptFailed(mc)` | `.source=='decompose'` |
| `JudgeAttemptFailed(mc)` | `.source=='judge'` |
| `VerifyAttemptFailed(mc)` | `.source=='verify'` |
| `SummarizeAttemptFailed(mc)` | `.source=='summarize_episode'`（不是 `summarize`） |
| `DecisionAttemptFailed(mc, "x")` | `.source=='x'`，`str=="[x] attempt failed: ..."` |
| `AttemptFailed(mc)` | `.source==''`，`str` 以 `[AttemptFailed]` 开头（`source` 为空时用类名） |
| `ParseFailure('{"a"', "not valid json")` | `.raw_text=='{"a"'`，`.reason=='not valid json'`，`str=="not valid json: '{\"a\"'"` |
| `IllegalAction("fly", ["up","down"])` | `.name=='fly'`，`.allowed==['up','down']`，`str=="action 'fly' not in action space ['up', 'down']"` |
| `EmptyCompletion(10, 8, "stop")` | 三个属性同名保存，`str` 含 `completion_tokens=10`、`reasoning_tokens=8`、`finish_reason='stop'` |
| `OutputTruncated(512)` | `.tokens==512`，`str` 含 `512 tokens` |
| `ImageNotDelivered(30, 200)` | `.input_tokens==30`，`.floor==200`，`str` 含 `input_tokens=30 < floor=200` |
| `ToolTimeout("gateway down")` / `ProviderRejected("401")` | 普通异常，`str` 即原消息 |
| `ToolTimeout` 与 `ProviderRejected` 互为子类吗 | 否（互相不是子类） |
| `ParseFailure` 是 `AttemptFailed` 子类吗 | 否 |
| 15 个类中任何一个是否 `pokemon_agent.errors.AgentError` 的子类 | 否，全部不是 |
| `errors.__all__` 的名字集合 | 与模块里所有 `BrainError` 子类（含自身）完全相同 |
| 上述 15 个名字是否能从 `pokemon_agent.brain`（包根）取到 | 取不到（`hasattr` 全为 False），只能从 `pokemon_agent.brain.errors` 导入 |

## 要钉的契约（测试清单）

1. 每个 brain 异常都继承 `BrainError`（15 个名字参数化，包括 `BrainError` 自身）。
2. `BrainError` 及其全部子类都不是 `AgentError` 的子类（"自成一根"）。这里 `AgentError` 从 `pokemon_agent.errors` 导入，仅用来断言否定关系。
3. 六个 `*AttemptFailed` 都继承 `AttemptFailed`；`ParseFailure`、`IllegalAction`、`EmptyCompletion`、`OutputTruncated`、`ToolTimeout`、`ProviderRejected`、`ImageNotDelivered` 都**不是** `AttemptFailed`。
4. 六个子类各自的默认 `source`（`choose`/`plan`/`decompose`/`judge`/`verify`/`summarize_episode`）与 `call` 原样保存（`is` 同一对象）；参数化。
5. 显式传 `source` 时覆盖默认值，且消息里用它。
6. 基类 `AttemptFailed` 的 `source` 默认空串，消息用类名兜底。
7. `AttemptFailed` 的消息含 `call.error_kind` 与 `call.error`（用不同于探针的值再验一次）。
8. `ParseFailure` 记住 `raw_text` 与 `reason`，消息里含两者。
9. `IllegalAction` 记住 `name` 与 `allowed`，消息里含名字和允许集合。
10. `EmptyCompletion` 记住三个字段并体现在消息里。
11. `OutputTruncated` 记住 token 数。
12. `ImageNotDelivered` 记住 `input_tokens` 与 `floor`，消息说明图被丢弃。
13. `ToolTimeout` 与 `ProviderRejected` 是两个互不相干的类（互不为子类），都能被 `except BrainError` 捕到；这一条钉"重试 vs 当场崩"的可分辨性。
14. `errors.__all__` 恰好等于模块内全部 `BrainError` 子类名（含 `BrainError`）：新增异常忘记导出时会失败。

## 不测

- 现有 `tests/brain/providers/test_empty_completion.py` 测的是 provider 产出 `EmptyCompletion`，留在 `providers/`，不搬。
- 包根不导出这些异常（探针第 17 行）是现状，不钉。
- 各异常的完整消息字面量里不影响调用方判断的措辞（如 `ImageNotDelivered` 后半句 "hallucination"）：只断言关键片段。

## 测试文件

`tests/brain/errors/test_brain_errors.py`（单文件）。
`ModelCall` 从 `pokemon_agent.brain.interface` 导入，直接构造，不用任何替身、不用 mock。
命名为句子式，Arrange / Act / Assert 以空行分段。预期约 40–60 条（参数化展开后计）。

## 已知观察

- O8：包根 `pokemon_agent.brain` 不导出这些异常，外部要写 `from pokemon_agent.brain.errors import ...`。这是否是有意，不在本任务裁决。

## 破坏验证（必做，各一次，做完立即还原）

- (a) 把 `class ParseFailure(BrainError)` 改成 `class ParseFailure(Exception)`：契约 1 的 `ParseFailure` 用例必须失败。
- (b) 把 `DecomposeAttemptFailed.__init__` 的默认 `source="decompose"` 改成 `"plan"`：契约 4 的 decompose 用例必须失败。

## 停止条件

- 实际行为与上面探针表不符；
- 需要改 `pokemon_agent/` 才能让测试通过；
- 需要引入 mock。
