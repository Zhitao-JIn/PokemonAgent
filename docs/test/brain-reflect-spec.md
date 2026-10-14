# brain/reflect 测试 spec

状态：已确认（2026-10-14）。上位文档：`docs/test/brain-test-intent.md`。

## 被测对象

`Brain.reflect(*, prompt, before, after, action_text) -> Reflection`（`pokemon_agent/brain/brain.py`）。
本版不调模型、不写库、不盖章坐标；只把 `before` / `action_text` / `after` 原样装进 `Reflection`。
`Reflection` 定义在 `pokemon_agent/brain/interface/domain/reflection.py`，三个 str 字段：`before`、`action_text`、`after`。

## 探针（真实代码，输入→实际输出）

| 输入 | 实际 |
|---|---|
| `Brain()`（四个 provider 全不给）`.reflect(prompt="p", before="B", after="A", action_text="up")` | `Reflection(before='B', action_text='up', after='A')` |
| `before=""` | `AssertionError: reflect() got an empty before-snapshot text` |
| `after=""` | `AssertionError: reflect() got an empty after-snapshot text` |
| 两者都空 | 先报 before 的那条 |
| `action_text=""` | 正常返回，`action_text==''` |
| `prompt` 为空或不同值 | 结果相等（`prompt` 不被消费） |
| `before=" "`、`after="\n"`（纯空白） | 正常返回，原样保留 |
| 缺 `prompt` 关键字 | `TypeError` |
| 全部按位置传参 | `TypeError`（关键字专用） |
| 返回对象赋值 `r.before = "x"` | 成功（模型可变） |

## 要钉的契约（测试清单）

1. 不给任何 provider 也能用：`Brain()` 上调用成功。
2. 三段原样透传：返回 `Reflection`，三个字段与入参逐字相等；多行、含引号、含中文的文本不被改写、不被截断。
3. 纯空白的 before/after 被接受并原样保留（断言只判空串）。
4. `action_text` 可以为空串，原样保留。
5. `before` 为空 → `AssertionError`，消息含 `before`；`after` 为空 → `AssertionError`，消息含 `after`；两者都空时报 before。
6. `prompt` 不影响结果：两次调用只有 `prompt` 不同，返回值相等。
7. 参数是关键字专用：位置传参 `TypeError`。
8. 无副作用：连续调用同一 `Brain`，互不影响（第二次的结果只取决于第二次的入参）。
9. 返回类型是 `Reflection`，且字段恰为 `before`、`action_text`、`after` 三个（不含 `episode_id` / `step`）。

## 不测

- 模型可变（`r.before = "x"` 能成功）是现状，不是契约，不钉。
- `Reflection` 的 pydantic 校验细节（框架行为）。
- 日后 `reflect` 改成接 LLM 的行为：到时另写 spec。

## 测试文件

`tests/brain/reflect/test_reflect.py`。夹具：不需要任何 LLM 替身（本方法不调模型）；用 `Brain()`。
命名为句子式，Arrange / Act / Assert 以空行分段，不用 mock。
预期约 9–14 条（参数化展开后计）。

## 已知观察

- O7：`reflect` 的断言用的是真值判断，所以 `""` 被拒、`" "` 被收下；这与 docstring"渲染好的文本"一致，不当缺陷。

## 破坏验证（必做，各一次，做完立即还原）

- (a) 去掉 `assert before, ...`：测试 5 的 before 用例必须失败。
- (b) 把返回里的 `after=after` 改成 `after=before`：测试 2 必须失败。

## 停止条件

- 实际行为与上面探针表不符；
- 需要改 `pokemon_agent/` 才能让测试通过；
- 需要引入 mock。
