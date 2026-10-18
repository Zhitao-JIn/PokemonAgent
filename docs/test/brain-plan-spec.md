# spec —— brain/plan 单元测试（`plan` + `decompose`）

> 状态：**已定稿，待执行**（v1，2026-10-14）
> 上游：`docs/test/brain-test-intent.md` 第 2 节（总意图；不一致以本文件为准）；写法与验证口径沿用已落地的 `docs/test/brain-judge-verify-spec.md`
> 被测：`pokemon_agent/brain/brain.py` 的 `Brain.plan` / `Brain.decompose`（内部 `_parse_plan` / `_parse_decomposition` **只经这两个公开方法测**）
> 复用夹具：`tests/_doubles/llm.py` 的 `ScriptedLLM` / `text_reply`（**不得修改**；纯文本用 ScriptedLLM / text_reply，带图用 ScriptedJudge / vision_reply）
> CHANGELOG 编号：动态取号，规则见第七节

## 一、目标

钉住两条规划链各自的四件事：
1. 模型怎么写，大脑怎么读：解析出 `RunPlan` / `Decomposition`，字段不合法算 `ParseFailure`；
2. 失败都抛该链自己的 `*AttemptFailed`，带账、不吞；
3. 有图且 provider 多模态可用时走 describe，账里 images 记实际发出的图；否则走 complete，images 为空。thinking 仅纯文本请求支持覆盖，带图请求只记账；
4. 成功路径的后置条件：一次尝试恰好一条账、大脑自己不重试、没配 provider 就调会被入口 assert 当场拦下、`plan_llm` 缺省回退 `judge_llm`。

## 二、决定表

| # | 决定 | 理由 / 代价 |
|---|---|---|
| D1 | 假 provider 用 `ScriptedLLM`；不新增 `_doubles` 文件，常量与小工厂函数在测试文件顶部定义 | 输入只有几个字符串，抽公共文件是过度设计 |
| D2 | 解析只经 `plan` / `decompose` 喂文本测，不 import 私有函数 | AGENTS.md「不测私有函数」 |
| D3 | 失败断言看 `excinfo.value.call.error_kind`、`excinfo.value.source` 与 `call.error` 里的关键词；**不**断言整句报错文本，也不断言 pydantic 的原始错误结构 | 措辞与 pydantic 版本会变，类型名与来源是 replay 统计的依据 |
| D4 | 账里的时间字段只断言 `float` 且 `started_at <= ended_at` | AGENTS.md「不依赖时间戳精确值」 |
| D5 | `goal_stack` / `history` / `max_push`（plan）与 `goal` / `context` / `max_tasks`（decompose）是「收下不读」的约定参数：测试里照常传入，只断言 prompt 原样到达 provider，不断言它们影响任何东西 | 源码 docstring 明说素材已渲进 prompt，将来要独立演进 |
| D6 | 实现与 docstring 不符，或下列「已知观察」需要裁决：**停下汇报，不改生产代码，不放宽断言** | 不把缺陷钉成预期 |
| D7 | 每个方法的入口 assert 各测一条，文案各自匹配（`plan provider`） | 两个方法的 assert 文案不同 |
| D8 | 只写 `plan` 目录；`json_utils` / `wiring` 等**不要提前写** | 用户要求一个目录一个目录来 |

### 已知观察（**不写测试**，汇报里原样转述给我）

我已用真实代码探针确认过，它们要么文档没定义、要么是设计上留给调用方的，本轮既不钉成预期也不去改：

- O5：`max_push`（plan）与 `max_tasks`（decompose）在 brain 里**不校验上限**——`decompose(max_tasks=1)` 收到两个 task 的回答照样成功。它们只是「渲进 prompt 的约束」，是否超限由调用方判断。这是 D5 的具体表现，测试不测「超限」。
- O6：`RunPlan` 的 `updates[].index` 越界（如表里只有 3 行却给 9）brain 不丢弃，原样交回，由调用方丢弃（`RunPlan.PlanUpdate` 的 docstring 写明了）。**这条要测**（见 plan 第 4 条），但只测「原样交回」，不测「谁来丢」。

执行者在写用例时发现了**别的**与 docstring 不符之处，按停止条件 2 处理。

## 三、文件清单

新增（`tests/brain/plan/` 若不存在则新建，**不加 `__init__.py`**）：

| 文件 | 内容 |
|---|---|
| `tests/brain/plan/test_plan.py` | `Brain.plan` |
| `tests/brain/plan/test_decompose.py` | `Brain.decompose` |

不改任何已有文件（含 `_doubles`）。

## 四、写法约定

沿用 judge_verify：每个文件顶层 docstring 写 intent；`from __future__ import annotations`；全部类型注解；函数名是一句完整的话；Arrange / Act / Assert 用空行隔开。

- import：`from _doubles.llm import ScriptedLLM, text_reply`；`from pokemon_agent.brain import Brain`；`from pokemon_agent.brain.errors import PlanAttemptFailed, ToolTimeout`（decompose 文件换 `DecomposeAttemptFailed`）；`from pokemon_agent.brain.schemas import LlmCompleteReq`。
- 顶部常量（两个文件各自定义）：`PROMPT = "..."`（任意非空串）；`LEDGER_KEYS = {"input_tokens","output_tokens","cached_tokens","reasoning_tokens","thinking_override","ok","raw","prompt","images","started_at","ended_at"}`。`test_plan.py` 另有 `GOAL_STACK = ["beat the first gym"]`、`HISTORY = ["walked to the gym"]`、`MAX_PUSH = 2`，以及 `plan_json(**overrides) -> str`：返回一份**完整合法**的计划 JSON，默认为
  `push_goals=[{"goal":"reach the gym","success_criteria":"standing in the gym","max_steps":6},{"goal":"beat the leader","success_criteria":"badge obtained","max_steps":8}]`、`updates=[{"index":0,"status":"abandoned","note":"dead end"}]`、`why="gym first"`，`overrides` 覆盖或新增顶层键。`test_decompose.py` 另有 `GOAL = "get the first badge"`、`CONTEXT = ["badge case is empty"]`、`MAX_TASKS = 3`，以及 `chain_json(**overrides) -> str`，默认为 `tasks=[{"goal":"reach the gym","success_criteria":"standing in the gym","max_steps":6},{"goal":"beat the leader","success_criteria":"badge obtained","max_steps":8}]`、`why="gym first"`。
- 调用形态：
  - `Brain(plan_llm=provider).plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)`（需要时加 `thinking=`）
  - `Brain(plan_llm=provider).decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)`（需要时加 `thinking=`）

## 五、测试清单

`text_reply` 默认 token 为 11 / 7 / 3 / 2。

### 1. `test_plan.py` —— `Brain.plan`

| 函数名 | 装配 / 回复 | 断言 |
|---|---|---|
| `test_a_valid_plan_object_parses_into_a_run_plan` | `plan_json()` | `result.plan.push_goals` 两条，`goal` 依次为 `["reach the gym","beat the leader"]`（顺序即派发顺序）、第一条 `max_steps == 6`；`updates` 一条，`index == 0`、`status == "abandoned"`、`note == "dead end"`；`why == "gym first"` |
| `test_a_json_fence_around_the_plan_is_tolerated` | 围栏包 `plan_json()` | `result.plan.why == "gym first"` |
| `test_an_empty_object_is_a_plan_that_pushes_and_updates_nothing` | `{}` | `push_goals == []`、`updates == []`、`why == ""` |
| `test_an_update_index_beyond_the_table_is_passed_through_for_the_caller_to_drop` | `plan_json(updates=[{"index": 9, "status": "pending"}])` | 不抛；`result.plan.updates[0].index == 9`；`note == ""`（O6） |
| `test_an_invalid_plan_field_fails_as_parse_failure_naming_the_field`（参数化 5 组） | (a) `push_goals` 里 `goal=""`，关键词 `goal`；(b) `max_steps=0`，关键词 `max_steps`；(c) `updates[0].index=-1`，关键词 `index`；(d) `updates[0].status="completed"`，关键词 `status`；(e) `push_goals="x"`（不是列表），关键词 `push_goals`。每组都基于 `plan_json(...)` 覆盖相应键 | 抛 `PlanAttemptFailed`；`call.error_kind == "ParseFailure"`；`excinfo.value.source == "plan"`；`call.error` 含 `RunPlan` 与该组关键词；`payload["ok"] == "false"` |
| `test_non_json_or_non_object_output_fails_as_parse_failure_and_keeps_the_raw_text`（参数化 2 组） | `nope`、`[1]` | 抛 `PlanAttemptFailed`；`error_kind == "ParseFailure"`；`payload["raw"]` 为回复原文；`payload["input_tokens"] == "11"`、`output_tokens == "7"` |
| `test_plan_without_images_uses_text_and_records_an_empty_image_list`（参数化：成功 / 解析失败各一组） | 成功用 `plan_json()`，失败用 `nope` | 未提供 images 时，两种情形的 `payload["images"] == []`；`provider.requests` 里每条都是 `LlmCompleteReq`（纯文本请求） |
| `test_the_thinking_override_reaches_the_request_and_the_ledger`（参数化 3 组） | `thinking` 取 `True` / `False` / `None` | `provider.requests == [LlmCompleteReq(prompt=PROMPT, thinking=<该值>)]`；`payload["thinking_override"]` 分别为 `"true"` / `"false"` / `"none"` |
| `test_a_successful_attempt_returns_exactly_one_ledger_entry` | `plan_json()` | `len(result.calls) == 1`；`payload` 键集合恰为 `LEDGER_KEYS`；`ok == "true"`；四个 token 值为 `"11"` `"7"` `"3"` `"2"`；`raw` 为回复原文；`prompt == PROMPT`；`images == []`；`thinking_override == "none"`；`started_at` / `ended_at` 是 `float` 且 `started_at <= ended_at`；`error_kind == ""`、`error == ""` |
| `test_the_prompt_reaches_the_provider_verbatim_whatever_the_materials_say` | 成功一次 | `provider.requests == [LlmCompleteReq(prompt=PROMPT)]`（`GOAL_STACK` / `HISTORY` / `MAX_PUSH` 不会被拼进请求，D5） |
| `test_plan_falls_back_to_the_judge_provider_when_no_plan_provider_is_given` | `Brain(judge_llm=j)`，`j = ScriptedLLM(text_reply(plan_json()))` | 成功；`len(j.requests) == 1` |
| `test_an_explicit_plan_provider_is_used_instead_of_the_judge_provider` | `Brain(judge_llm=j, plan_llm=p)`，`j` 不排回复，`p` 排 `plan_json()` | 成功；`len(p.requests) == 1`；`j.requests == []` |
| `test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry` | `ScriptedLLM(ToolTimeout("gateway down"))`，`thinking=True` | 抛 `PlanAttemptFailed`；`error_kind == "ToolTimeout"`；`call.error` 含 `gateway down`；`__cause__` 是同一个异常实例；`payload` 键集合恰为 `{"ok","prompt","images","thinking_override","started_at","ended_at"}`；`payload["thinking_override"] == "true"` |
| `test_plan_never_retries_by_itself` | 只排一条无法解析的回复 | 抛后 `len(provider.requests) == 1` |
| `test_calling_plan_without_any_provider_trips_the_entry_assert` | `Brain()` | `pytest.raises(AssertionError, match="plan provider")` |

### 2. `test_decompose.py` —— `Brain.decompose`

| 函数名 | 装配 / 回复 | 断言 |
|---|---|---|
| `test_a_valid_decomposition_parses_into_an_ordered_task_chain` | `chain_json()` | `result.decomposition.tasks` 两条，`goal` 依次为 `["reach the gym","beat the leader"]`，`max_steps` 依次 `6`、`8`；`why == "gym first"` |
| `test_a_json_fence_around_the_chain_is_tolerated` | 围栏包 `chain_json()` | `len(tasks) == 2` |
| `test_the_explanation_is_optional` | `chain_json()` 去掉 `why` 键 | 不抛；`result.decomposition.why == ""` |
| `test_an_invalid_chain_fails_as_parse_failure_naming_the_field`（参数化 4 组） | (a) `{}`，关键词 `tasks`；(b) `tasks=[]`，关键词 `tasks`；(c) 某 task `max_steps=0`，关键词 `max_steps`；(d) 某 task `goal=""`，关键词 `goal`（后两组基于 `chain_json(...)` 覆盖） | 抛 `DecomposeAttemptFailed`；`error_kind == "ParseFailure"`；`excinfo.value.source == "decompose"`；`call.error` 含 `Decomposition` 与该组关键词；`payload["ok"] == "false"` |
| `test_non_json_or_non_object_output_fails_as_parse_failure_and_keeps_the_raw_text`（参数化 2 组） | `nope`、`[1]` | 抛 `DecomposeAttemptFailed`；`error_kind == "ParseFailure"`；`payload["raw"]` 为回复原文；`payload["input_tokens"] == "11"` |
| `test_a_non_positive_max_tasks_trips_the_entry_assert_before_any_model_call`（参数化 `0`、`-1`） | `ScriptedLLM(text_reply(chain_json()))` | `pytest.raises(AssertionError, match="max_tasks")`；`provider.requests == []` |
| `test_decompose_uses_the_plan_provider_and_falls_back_to_the_judge_provider`（拆成两个函数更清晰：`test_decompose_uses_the_plan_provider` 与 `test_decompose_falls_back_to_the_judge_provider_when_no_plan_provider_is_given`） | 前者 `Brain(judge_llm=j, plan_llm=p)`，`p` 排回复、`j` 不排；后者 `Brain(judge_llm=j)` | 前者 `len(p.requests) == 1` 且 `j.requests == []`；后者 `len(j.requests) == 1` |
| `test_the_thinking_override_reaches_the_request_and_the_ledger`（参数化 3 组） | `thinking` 取 `True` / `False` / `None` | 同 plan |
| `test_a_successful_attempt_returns_exactly_one_ledger_entry` | `chain_json()` | `len(result.calls) == 1`；`payload` 键集合恰为 `LEDGER_KEYS`；`ok == "true"`；`images == []`；`prompt == PROMPT`；`raw` 为回复原文 |
| `test_the_prompt_reaches_the_provider_verbatim_whatever_the_materials_say` | 成功一次 | `provider.requests == [LlmCompleteReq(prompt=PROMPT)]` |
| `test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry` | `ScriptedLLM(ToolTimeout("gateway down"))` | 抛 `DecomposeAttemptFailed`；`error_kind == "ToolTimeout"`；`__cause__` 是同一个实例；`payload` 键集合恰为 `{"ok","prompt","images","thinking_override","started_at","ended_at"}` |
| `test_decompose_never_retries_by_itself` | 只排一条无法解析的回复 | 抛后 `len(provider.requests) == 1` |
| `test_calling_decompose_without_any_provider_trips_the_entry_assert` | `Brain()` | `pytest.raises(AssertionError, match="plan provider")` |

## 六、验证

1. `python -m pytest tests/brain/plan -p no:cacheprovider`：全绿、远小于 5 秒、不联网；
2. 全量 `python -m pytest`，起点与终点同一配置，每次用全新 `--basetemp=.pytest_tmp/run_<序号>`。
   首选口径：起点全绿、终点全绿，终点 passed = 起点 passed + 本任务新增用例数（参数化展开后的实数）。
   **兜底口径**（栈里仍出现 `sitecustomize` / `SAFE_DELETE` 守卫报错时）：失败集合不变——目前已知起点是 `2 failed, 755 passed, 2 skipped`，那 2 条 failed 是 `test_evals_script_timeout.py` 的守卫失败；终点集合必须逐条相同，passed = 起点 passed + 新增数；用户会在本机 PowerShell 再复验，那次才是最终全绿依据；
3. `python -m ruff check .`、`python -m ruff format --check .` 全绿；
4. 破坏验证，**两处各做一次再还原**：
   - (a) `Brain.plan` 里构造请求处把 `LlmCompleteReq(prompt=prompt, thinking=thinking)` 临时改成 `LlmCompleteReq(prompt=prompt)`：`test_the_thinking_override_reaches_the_request_and_the_ledger`（plan 的）里 `True` / `False` 两组必须失败；
   - (b) `Brain.decompose` 里把 `assert max_tasks > 0, ...` 那一行临时注释掉：`test_a_non_positive_max_tasks_trips_the_entry_assert_before_any_model_call` 必须失败；
   每处做完立即还原，**全部还原后确认 `git diff pokemon_agent/` 为空**。汇报里写明做了、结果如何。

不需要真实模型、不需要 ROM、不需要网络。

## 七、CHANGELOG

编号**不写死**：取 `git show HEAD:CHANGELOG.md` 最上面已提交条目的编号 +1，记作 M；动手写之前再取一次，HEAD 动了就重取。若工作区 `CHANGELOG.md` 已有**不属于本任务**的未提交改动，停下汇报（停止条件 5）。

按仓库四段格式追加到最上，标题：`## <今天日期，与最近条目同格式>（M）—— brain/plan 单元测试`
- **改了什么**：新增 `tests/brain/plan/` 下 `test_plan.py` / `test_decompose.py`，复用 `tests/_doubles/llm.py` 的 `ScriptedLLM`。
- **为什么这么改**：`plan` / `decompose` 此前没有直接测试；字段不合法算解析失败、思考开关进请求与账、plan 缺省回退 judge 都靠集成路径碰运气。
- **取舍**：解析只经公开方法测；`max_push` / `max_tasks` 的上限不在 brain 校验，不测；`updates[].index` 越界只测原样交回。
- **影响面**：只增测试，不动 `pokemon_agent/` 下任何文件；写明新增用例数与全量 pytest 实数。

提交信息标题复用 CHANGELOG 标题原文，前缀 `test(brain): `。

## 八、停止条件

遇到下列任一情形**停下汇报，不要自己决定、不要重试、不要绕过**：
1. 起点 `ruff check` / `ruff format --check` 不是全绿；起点 pytest 的失败集合不等于已知那 2 条，或出现不能用删除守卫解释的失败；终点失败集合与起点不一致；
2. 任一用例失败，且原因是 `plan` / `decompose` 的行为与本 spec 的断言不符（贴出输入、期望、实际）——不要改生产代码，不要改弱断言；
3. 需要改 `pokemon_agent/` 下任何文件才能让测试通过；
4. 需要改已有测试文件或已有 `_doubles` 文件才能继续；
5. `git status` 里出现本任务之外的**你将要提交的**文件被他人改动，或 `CHANGELOG.md` 有他人的未提交改动（并行任务改了无关的受跟踪文件，如 `docs/perceive/` 下的，不算，不碰即可）；
6. 任何真实模型调用、联网请求、ROM 读取。

## 九、非目标

`choose` / `judge` / `verify` / `summarize` / `reflect` / `json_utils` / `wiring` / `domain` / `errors` / `providers` / `factory` / `schemas` 目录的测试；`BrainTool`（`direct/`）的重试循环；prompt 内容；`max_push` / `max_tasks` 上限的校验；任何生产代码改动。
