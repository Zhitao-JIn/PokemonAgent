# brain/domain 测试 spec

状态：已确认（2026-10-14）。上位文档：`docs/test/brain-test-intent.md` 第 7 节（本 spec 在其用例清单上按探针结果细化）。

## 被测对象

`pokemon_agent/brain/interface/domain/` 下对外暴露的数据形状（pydantic 模型）：
`Action`/`ActionSegment`、`ScriptCall`/`ScriptSignature`/`ScriptArg`、`Decomposition`（含 `PlannedTask`）、`RunPlan`（含 `PlanGoal`、`PlanUpdate`）、`Goal`、`VerifyVerdict`、`EpisodeSummary`、`ModelCall`，以及六个结果袋 `ChooseResult`/`JudgeResult`/`PlanResult`/`DecomposeResult`/`VerifyResult`/`SummarizeResult`。
导入路径统一用 `from pokemon_agent.brain.interface.domain import ...`（包出口已导出以上全部名字；`Reflection` 已在 reflect 目录覆盖，`Task` 只有字段默认值，不单独测）。
这些模型是 harness 与 schemas 内嵌的"数据形状"，字段约束变动会静默改变"模型输出解析得过不过"，所以只测**项目自己声明的约束与默认值**，不测 pydantic 框架本身（类型转换等）。

## 探针（真实代码，输入→实际输出；校验失败一律是 `pydantic.ValidationError`）

| 输入 | 实际 |
|---|---|
| `Action()` | ValidationError |
| `Action(sequence=[seg], script=ScriptCall(..))` | ValidationError |
| `Action(sequence=[ActionSegment(name="up")])` | 成功，`script is None` |
| `Action(script=ScriptCall(name="walk_to", args={"x":5,"y":2}))` | 成功，`sequence == []` |
| `Action(sequence=[up×1, a×3]).describe()` | `"up -> a×3"` |
| 脚本动作 `.describe()`（带参 / 不带参） | `"script:walk_to(x=5, y=2)"` / `"script:wait()"` |
| 脚本动作 `.segments()` | `[]` |
| 对 `.segments()` 的返回值追加元素后，动作自身 `sequence` | 长度不变（返回的是副本） |
| `ActionSegment(name="")` / `times=0` | ValidationError；缺省 `times==1` |
| `ScriptCall(args={"x":1.5})` | ValidationError；`{"x":"5"}` 保持字符串 `"5"` |
| `ScriptArg(type="float")` | ValidationError；缺省 `required is True` |
| `ScriptSignature(name="w").params` | `[]` |
| `Decomposition(tasks=[])` | ValidationError；`tasks[i].max_steps==0` 也 ValidationError；缺省 `why==""` |
| `RunPlan()` | 合法，三个字段全是缺省（空、空、`""`） |
| `PlanUpdate.status` 取 `"completed"` | ValidationError（只允许 `pending`/`abandoned`）；`index=-1` ValidationError；缺省 `note==""` |
| `PlanGoal.max_steps==0` | ValidationError |
| `Goal(goal="", criteria="c")` | ValidationError |
| `VerifyVerdict(index=-1, ...)` | ValidationError |
| `EpisodeSummary.quality_score` 为 1.5 / -0.1 | 均 ValidationError |
| `EpisodeSummary` 只给必填项 | 其余列表字段缺省空列表，`reason`/`markdown` 缺省 `""` |
| `ModelCall()` | `payload=={}`，`error_kind==""`，`error==""` |
| 六个结果袋只给必填项 | `calls==[]`，`extra=={}`；两个实例的 `calls`/`extra` 互不共享 |
| `JudgeResult(done=False, why="w").interrupted` | `False`；缺 `why` → ValidationError |
| `Action(sequence=[..], thought="x")` | 成功，`thought` 被丢弃（不在 `model_dump()` 里） |

## 要钉的契约（测试清单）

文件 `tests/brain/domain/test_action.py`
1. 一个 `Action` 恰好是按键链或脚本调用之一：按键链可、脚本可、两者都空拒、两者都填拒。
2. `describe()`：单键段无 `×1` 后缀；多段用 ` -> ` 连接，`times>1` 的段写成 `名×次数`；脚本写成 `script:名(k=v, ...)`；无参脚本写成 `script:名()`。
3. 脚本动作的 `segments()` 是空列表；按键动作的 `segments()` 返回副本，改它不影响动作本身。
4. `ActionSegment` 的 `name` 非空；`times` 缺省 1，小于 1（0、-1）被拒。

文件 `tests/brain/domain/test_script_call.py`
5. `ScriptSignature` 声明必填与可选参数：`ScriptArg.required` 缺省为必填，可显式设为可选；`type` 只允许 `str`/`int`；无参脚本的 `params` 为空列表。
6. `ScriptCall.args` 的值只能是 `str` 或 `int`（`1.5` 被拒）；脚本名、参数名非空。

文件 `tests/brain/domain/test_planning_models.py`
7. `Decomposition` 至少一个 task；task 的 `goal`/`success_criteria` 非空，`max_steps` 为正（0、-1 被拒）；`why` 缺省空串。
8. `RunPlan` 可以什么都不给（三个字段全缺省）；`PlanGoal` 的 `goal`/`success_criteria` 非空、`max_steps` 为正；`PlanUpdate.status` 只允许 `pending`/`abandoned`（`completed`、`failed` 被拒），`index` 不能为负，`note` 缺省空串。
9. `Goal` 的 `goal` 与 `criteria` 都必须非空。
10. `VerifyVerdict.index` 不能为负。
11. `EpisodeSummary.quality_score` 取值闭区间 `[0, 1]`：0.0、1.0 接受，1.5、-0.1 拒绝；只给必填项时列表字段缺省空列表、`reason`/`markdown` 缺省空串。

文件 `tests/brain/domain/test_results.py`
12. 六个结果袋（参数化）：只给必填项时 `calls` 为空列表、`extra` 为空字典；两个实例各自拥有自己的 `calls`/`extra`（往一个里追加不影响另一个）。
13. `JudgeResult`：`interrupted` 缺省 `False`；`why` 必填。
14. `ModelCall()` 缺省 `error_kind==""`、`error==""`、`payload=={}`（空串表示成功）。

## 不测

- `Task.max_steps` 的"> 0"：文档说 > 0，但代码没有约束，见 O9。
- `ModelCall` 是否不可变、`ScriptCall.args` 对布尔值的处理、模型对多余字段的忽略：见 O10、O11，不钉。
- pydantic 自身的类型转换、`model_dump` 格式。
- `Reflection`（已在 `tests/brain/reflect/`）。

## 已知观察（不写测试，由我与用户裁决）

- O9：`Task.max_steps` 的 Field 描述写"> 0"，实际 `max_steps=0` 和 `-5` 都被接受（没有 `gt=0` 约束）。是文档过期还是漏了约束，待定。
- O10：`ModelCall` 的 docstring 写"不可变值语义"，但对其字段赋值（`mc.error = "x"`）成功，模型并非 frozen。另：`ScriptCall(args={"x": True})` 被存成整数 `1`。
- O11：`Action` 的"恰好一种形状"校验用的是 `assert`（在 `model_validator` 里）。常规运行下它变成 `ValidationError`，但在 `python -O` 下断言被剥掉、空 `Action()` 会被放行。这个输入来自模型输出（外部输入），按仓库"外部世界不配合用异常"的口径应是显式异常；是否改，待定。本 spec 的测试按常规模式跑。

## 测试风格与规模

用法示范：Arrange / Act / Assert 以空行分段，句子式测试名，不用 mock，不需要任何替身（直接构造模型）。
校验失败统一断言 `pydantic.ValidationError`。参数化用于"多个非法值"与"六个结果袋"。预期约 55–75 条（参数化展开后计）。

## 破坏验证（必做，各一次，做完立即还原）

- (a) `Action._one_shape` 里 `assert filled == 1` 改成 `assert filled >= 1`：契约 1 的"两者都填拒"用例必须失败。
- (b) `Action.describe` 里把 `f"{seg.name}×{seg.times}" if seg.times > 1 else seg.name` 改成总是带 `×`：契约 2 的单键用例必须失败。
- (c) `RunPlan.PlanUpdate.status` 的 `Literal["pending", "abandoned"]` 加入 `"completed"`：契约 8 的 `completed` 用例必须失败。

## 停止条件

- 实际行为与上面探针表不符；
- 需要改 `pokemon_agent/` 才能让测试通过；
- 需要引入 mock；
- 发现测试只能靠 `python -O` 之外的方式才过（见 O11，常规模式下不应出现）。
