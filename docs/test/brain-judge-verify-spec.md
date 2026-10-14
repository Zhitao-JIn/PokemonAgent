# spec —— brain/judge_verify 单元测试

> 状态：**已定稿，待执行**（v1，2026-10-14）
> 上游：`docs/test/brain-test-intent.md` 第 3 节（总意图；不一致以本文件为准）；写法沿用已落地的 `docs/test/brain-choose-spec.md`
> 被测：`pokemon_agent/brain/brain.py` 的 `Brain.judge` / `Brain.verify` / `Brain.summarize`（内部 `_ask` / `_parse_verdict` / `_parse_verify` / `_parse_summary` **只经这三个公开方法测**）
> 复用夹具：`tests/_doubles/llm.py`（`ScriptedLLM` / `ScriptedJudge` / `text_reply` / `vision_reply`，**不得修改**）
> CHANGELOG 编号：动态取号，规则见第七节

## 一、目标

钉住三条「独立判定」链各自的四件事：
1. 模型怎么写，大脑怎么读（解析的宽容与边界）；
2. 解析不出就**抛**，抛的是该链自己的 `*AttemptFailed`，带账、不吞、不静默降级；
3. 有图走 `describe()`、没图退化 `complete()`（`judge` / `verify` / `summarize` 的 provider 类型本身就带 `describe`，**不查 `multimodal` 标志**——这点跟 `choose` 不同）；
4. 成功路径的后置条件：一次尝试恰好一条账、大脑自己不重试、没配 provider 就调会被入口 assert 当场拦下、provider 回退规则。

## 二、决定表

| # | 决定 | 理由 / 代价 |
|---|---|---|
| D1 | 假 provider 一律用 `tests/_doubles/llm.py` 的 `ScriptedJudge`；不新增 `_doubles` 文件，常量各测试文件自己在顶部定义 | 这三条链的输入只有几个字符串，抽公共常量文件是过度设计 |
| D2 | 解析分支只经公开方法喂文本测，不 import 私有函数 | AGENTS.md「不测私有函数」 |
| D3 | 失败断言看 `excinfo.value.call.error_kind`（`"ParseFailure"` / `"ToolTimeout"`）与 `excinfo.value.source`，再看 `call.error` 的关键词；**不**断言整句报错文本 | 措辞会改，类型名与来源是 replay 统计的依据 |
| D4 | 账里的时间字段只断言 `float` 且 `started_at <= ended_at` | AGENTS.md「不依赖时间戳精确值」 |
| D5 | `goal` / `history`（judge）、`goal` / `knowledge`（verify）、`goal` / `history` / `success` / `steps` / `max_steps`（summarize）是「收下不读」的约定参数：测试里照常传入，只断言 **prompt 原样到达 provider**，不断言它们影响任何东西 | 源码 docstring 明说它们将来要独立演进，不把「现在不读」钉成契约 |
| D6 | 实现与 docstring 不符，或下列「已知观察」里的行为需要裁决：**停下汇报，不改生产代码，不放宽断言** | 不把缺陷钉成预期 |
| D7 | 每个方法的入口 assert 各测一条（`pytest.raises(AssertionError, match=...)`） | 这三个方法的 assert 文案不同，一条一个，别共用 |
| D8 | 只写 `judge_verify` 目录；`plan` / `json_utils` / `wiring` 等**不要提前写** | 用户要求一个目录一个目录来 |

### 已知观察（**不写测试**，汇报里原样转述给我，由我与用户裁决）

我已用真实代码探针确认过下面这些行为，它们要么是缺陷嫌疑，要么文档没定义，**本轮既不钉成预期也不去改**：

- O1（缺陷嫌疑）：`verify` 里 `{"index": 0, "positive": "false"}`（字符串 `"false"`）被 `bool("false")` 判成 **正样本**。保守方向反了；`json` 里模型写出字符串布尔并不罕见。
- O2：`verify` 收到 `{"verdicts": "xyz"}`（`verdicts` 不是列表）时不抛，全部补成负样本；与「解析不出就抛」不一致。
- O3：`verify` 重复 `index` 时后出现的覆盖先出现的；文档只说「可能重复」，没说谁赢。测试只断言结果等长、`index` 唯一，**不断言谁赢**。
- O4：`summarize` 的 `quality_score` 传字符串 `"0.7"` 会被 pydantic 悄悄转成 `0.7`；不测。

执行者如果在写用例时发现了**别的**与 docstring 不符之处，按停止条件 2 处理。

## 三、文件清单

新增（全部在仓库根 `tests/` 下，目录 `tests/brain/judge_verify/` 已按 intent 预留，若不存在则新建，**不加 `__init__.py`**）：

| 文件 | 内容 |
|---|---|
| `tests/brain/judge_verify/test_judge.py` | `Brain.judge` |
| `tests/brain/judge_verify/test_verify.py` | `Brain.verify` |
| `tests/brain/judge_verify/test_summarize.py` | `Brain.summarize` |

不改任何已有文件（含 `_doubles`）。

## 四、写法约定（沿用 choose）

- 每个文件顶层 docstring 写本文件的 intent；`from __future__ import annotations`；全部有类型注解；函数名是一句完整的话；Arrange / Act / Assert 三段用空行隔开；
- import：`from _doubles.llm import ScriptedJudge, text_reply, vision_reply`；被测 `from pokemon_agent.brain import Brain`；错误 `from pokemon_agent.brain.errors import JudgeAttemptFailed, ToolTimeout`（verify / summarize 对应换成 `VerifyAttemptFailed` / `SummarizeAttemptFailed`）；请求信封 `from pokemon_agent.brain.schemas import LlmCompleteReq, VisionDescribeReq`；
- 每个文件顶部定义常量：`PROMPT = "..."`（任意非空串）、`IMAGE = "data:image/png;base64,AAAA"`；`test_judge.py` 另有 `GOAL = "get the first badge"`、`HISTORY = ["walked up", "pressed a"]`；`test_verify.py` 另有 `GOAL`、`KNOWLEDGE = "gym doors open after the trainer is beaten"`、`ENTRIES = ["entered the gym", "talked to the guide", "left the gym"]`（三条）；`test_summarize.py` 另有 `GOAL`、`HISTORY`，并定义一个函数 `summary_json(**overrides) -> str`，返回一份**完整合法**的摘要 JSON（`summary="took the north road"`, `reason="reached the gym"`, `reusable_patterns=["use the north road"]`, `critical_decisions=["skipped the shop"]`, `failure_points=["got lost twice"]`, `quality_score=0.8`, `quality_rationale="clear path"`, `applicable_scenes=["route 2"]`, `tags=["navigation"]`, `markdown="# notes"`），`overrides` 覆盖或新增键；
- 调用形态：
  - `Brain(judge_llm=provider).judge(prompt=PROMPT, goal=GOAL, history=HISTORY)`
  - `Brain(verify_llm=provider).verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)`
  - `Brain(verify_llm=provider).summarize(prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10)`
  - 路由用例另带 `images=`；成功拿结果对象，失败用 `with pytest.raises(...) as excinfo`。

## 五、测试清单

账的键集合（三条链成功时相同）记作 `LEDGER_KEYS = {"input_tokens","output_tokens","cached_tokens","reasoning_tokens","ok","raw","prompt","images","started_at","ended_at"}`；`text_reply` 默认 token 为 11 / 7 / 3 / 2，`vision_reply` 默认为 21 / 9 / 4 / 5。

### 1. `test_judge.py` —— `Brain.judge`

| 函数名 | 装配 / 回复 | 断言 |
|---|---|---|
| `test_done_true_is_a_success_verdict` | `{"done": true, "why": "badge on screen"}` | `done is True`；`interrupted is False`；`why == "badge on screen"` |
| `test_done_false_is_a_not_yet_verdict` | `{"done": false, "why": "still in town"}` | `done is False`；`interrupted is False`；`why` 原文 |
| `test_interrupted_is_only_honoured_when_done_is_false`（参数化 4 组） | `(done=false, interrupted=true)` → 真；`(done=true, interrupted=true)` → 假；`(done=false, interrupted="yes")` → 假；`(done=false, 无 interrupted)` → 假 | `result.interrupted` 等于各组期望；`result.done` 等于输入的 `done` |
| `test_a_missing_or_empty_why_becomes_the_placeholder_text`（参数化 3 组） | `{"done": true}`、`{"done": true, "why": ""}`、`{"done": true, "why": null}` | `result.why == "（未说明）"` |
| `test_a_json_fence_around_the_verdict_is_tolerated` | ` ```json\n{"done": false, "why": "no"}\n``` ` | `done is False`、`why == "no"` |
| `test_a_missing_or_non_boolean_done_fails_as_parse_failure`（参数化 4 组） | `{"done": "yes"}`、`{"done": 1}`、`{"why": "x"}`、`[{"done": true}]` | 抛 `JudgeAttemptFailed`；`call.error_kind == "ParseFailure"`；`call.error` 含 `done`；`call.payload["ok"] == "false"` |
| `test_non_json_output_fails_as_parse_failure_and_keeps_the_raw_text` | `text_reply("nope")` | 抛 `JudgeAttemptFailed`；`error_kind == "ParseFailure"`；`excinfo.value.source == "judge"`；`payload["raw"] == "nope"`；`payload["ok"] == "false"`；`payload["input_tokens"] == "11"`、`output_tokens == "7"` |
| `test_images_go_through_describe` | `ScriptedJudge(vision_reply('{"done": true}'))`，`images=[IMAGE, IMAGE]` | `described == [VisionDescribeReq(images=[IMAGE, IMAGE], prompt=PROMPT)]`；`requests == []`；账 `payload["images"] == [IMAGE, IMAGE]` |
| `test_no_images_fall_back_to_plain_completion` | `ScriptedJudge(text_reply('{"done": true}'))`，不传 `images` | `requests == [LlmCompleteReq(prompt=PROMPT)]`；`described == []`；`payload["images"] == []` |
| `test_the_two_response_shapes_land_in_the_same_ledger_keys` | 各跑一次：`vision_reply`（带图）与 `text_reply`（不带图） | 两次账的四个 token 字段分别等于对应响应的数（`str`），`payload` 键集合都等于 `LEDGER_KEYS` |
| `test_a_successful_attempt_returns_exactly_one_ledger_entry` | `{"done": true, "why": "ok"}` | `len(result.calls) == 1`；`payload` 键集合恰为 `LEDGER_KEYS`；`ok == "true"`；`raw` 为回复原文；`prompt == PROMPT`；`started_at` / `ended_at` 是 `float` 且 `started_at <= ended_at`；`error_kind == ""`、`error == ""` |
| `test_the_prompt_reaches_the_provider_verbatim_whatever_goal_and_history_say` | 成功一次 | `provider.requests == [LlmCompleteReq(prompt=PROMPT)]`（即 `GOAL` / `HISTORY` 不会被偷偷拼进请求，D5） |
| `test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry` | `ScriptedJudge(ToolTimeout("gateway down"))` | 抛 `JudgeAttemptFailed`；`error_kind == "ToolTimeout"`；`call.error` 含 `gateway down`；`excinfo.value.__cause__` 是同一个 `ToolTimeout` 实例；`payload` 键集合恰为 `{"ok","prompt","images","started_at","ended_at"}`；`payload["ok"] == "false"` |
| `test_judge_never_retries_by_itself` | 只排一条无法解析的回复 | 抛后 `len(provider.requests) == 1` |
| `test_calling_judge_without_a_judge_provider_trips_the_entry_assert` | `Brain()` | `pytest.raises(AssertionError, match="judge provider")` |

### 2. `test_verify.py` —— `Brain.verify`

下面「完整合法回答」指三条都在、`index` 0 / 1 / 2、`positive` 依次 `true` / `false` / `true`、`why` 依次 `"a"` / `"b"` / `"c"`。

| 函数名 | 装配 / 回复 | 断言 |
|---|---|---|
| `test_verdicts_come_back_the_same_length_as_the_entries_and_in_index_order` | `{"verdicts": [完整合法回答]}` | `len(result.verdicts) == len(ENTRIES)`；`[v.index for v in verdicts] == [0, 1, 2]`；`[v.positive ...] == [True, False, True]`；`[v.why ...] == ["a", "b", "c"]` |
| `test_a_missing_index_is_marked_negative_not_a_parse_failure` | 只答 `index` 0（正）和 2（正） | 不抛；`verdicts[1].positive is False`；`verdicts[1].why` 非空；0 和 2 保持 `positive is True` 与原 `why` |
| `test_out_of_order_answers_are_returned_in_index_order` | 裸数组，顺序 2、0、1 | `[v.index ...] == [0, 1, 2]`，且每条 `why` 跟着自己的 `index` 走 |
| `test_duplicate_indexes_still_yield_one_verdict_per_entry` | 裸数组，`index` 0 出现两次 + 1 + 2 | `len == 3`；`index` 为 `[0, 1, 2]`（**不断言重复项谁赢**，O3） |
| `test_indexes_outside_the_entries_are_dropped` | 答 0、1、2 之外再加 `index` 9 与 `index` -1 | `len == 3`；`index` 为 `[0, 1, 2]` |
| `test_a_verdict_without_a_positive_field_counts_as_negative` | `[{"index": 0, "why": "x"}]`（其余补齐） | `verdicts[0].positive is False`；`verdicts[0].why == "x"` |
| `test_the_answer_may_be_a_bare_array_or_wrapped_in_verdicts_or_fenced`（参数化 3 组） | 同一份完整合法回答的三种包装：裸数组、`{"verdicts": [...]}`、` ```json ` 围栏 | 三种得到的 `verdicts` 相等 |
| `test_unparseable_output_raises_instead_of_marking_everything_unreliable`（参数化 3 组） | `nope`、`{"foo": 1}`、`[{"index": "abc"}]` | 抛 `VerifyAttemptFailed`；`error_kind == "ParseFailure"`；`excinfo.value.source == "verify"`；`payload["ok"] == "false"`；`payload["raw"]` 为回复原文 |
| `test_verify_does_no_filtering_of_its_own` | 完整合法回答（正、负、正混在一起） | 返回的 `verdicts` 恰好三条，负样本也在里面 |
| `test_no_entries_yield_no_verdicts` | `entries=[]`，回复 `[]` | `result.verdicts == []`；`len(result.calls) == 1` |
| `test_verify_falls_back_to_the_judge_provider_when_no_verify_provider_is_given` | `Brain(judge_llm=ScriptedJudge(完整合法回答))` | 不抛；`judge` 的 `requests` 长度 1 |
| `test_an_explicit_verify_provider_is_used_instead_of_the_judge_provider` | `Brain(judge_llm=j, verify_llm=v)`，`j` 不排回复，`v` 排完整合法回答 | 成功；`v.requests` 长度 1；`j.requests == []` |
| `test_images_go_through_describe_and_no_images_fall_back_to_complete` | 两次：带 `images=[IMAGE]`（`vision_reply`）与不带（`text_reply`） | 带图：`described == [VisionDescribeReq(images=[IMAGE], prompt=PROMPT)]` 且 `requests == []`；不带：`requests == [LlmCompleteReq(prompt=PROMPT)]` 且 `described == []` |
| `test_a_successful_attempt_returns_exactly_one_ledger_entry` | 完整合法回答 | `len(result.calls) == 1`；`payload` 键集合恰为 `LEDGER_KEYS`；`ok == "true"`；token 四个值为 `"11"` `"7"` `"3"` `"2"`；`prompt == PROMPT`；`images == []` |
| `test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry` | `ScriptedJudge(ToolTimeout("gateway down"))` | 抛 `VerifyAttemptFailed`；`error_kind == "ToolTimeout"`；`__cause__` 是同一个异常实例；`payload` 键集合恰为 `{"ok","prompt","images","started_at","ended_at"}` |
| `test_verify_never_retries_by_itself` | 只排一条无法解析的回复 | 抛后 `len(provider.requests) == 1` |
| `test_calling_verify_without_any_provider_trips_the_entry_assert` | `Brain()` | `pytest.raises(AssertionError, match="verify provider")` |

### 3. `test_summarize.py` —— `Brain.summarize`

| 函数名 | 装配 / 回复 | 断言 |
|---|---|---|
| `test_a_bare_summary_object_parses` | `summary_json()` | `result.summary` 的每个字段等于 `summary_json` 里写的值（`summary` / `reason` / `reusable_patterns` / `critical_decisions` / `failure_points` / `quality_score` / `quality_rationale` / `applicable_scenes` / `tags` / `markdown`） |
| `test_a_summary_wrapped_in_an_outer_object_parses_too` | `json.dumps({"summary": json.loads(summary_json())})` | 结果与上一条逐字段相同 |
| `test_the_markdown_field_is_kept_on_the_summary` | `summary_json(markdown="# a\n\nbody")` | `result.summary.markdown == "# a\n\nbody"` |
| `test_a_filename_in_the_output_is_discarded` | `summary_json(filename="x.md")` | 不抛；`"filename" not in result.summary.model_dump()` |
| `test_optional_fields_default_when_the_model_leaves_them_out` | 只给 `summary` / `quality_score` / `quality_rationale` 三个必填字段 | `reason == ""`；四个列表字段都 `== []`；`markdown == ""` |
| `test_a_json_fence_around_the_summary_is_tolerated` | 围栏包 `summary_json()` | 解析出的 `summary.summary == "took the north road"` |
| `test_missing_required_fields_fail_as_parse_failure`（参数化 3 组） | `summary_json()` 里分别去掉 `summary` / `quality_score` / `quality_rationale` 这一个键（用 `json.loads` 删键再 `dumps`） | 抛 `SummarizeAttemptFailed`；`error_kind == "ParseFailure"`；`payload["ok"] == "false"` |
| `test_a_quality_score_outside_zero_to_one_fails_as_parse_failure`（参数化 2 组） | `quality_score` 取 `1.5`、`-0.1` | 同上 |
| `test_non_json_or_non_object_output_fails_as_parse_failure_and_keeps_the_raw_text`（参数化 2 组） | `nope`、`[1]` | 抛 `SummarizeAttemptFailed`；`error_kind == "ParseFailure"`；`excinfo.value.source == "summarize_episode"`；`payload["raw"]` 为回复原文；`payload["input_tokens"] == "11"` |
| `test_summarize_uses_the_verify_provider` | `Brain(verify_llm=v)`，`v` 排 `summary_json()` | 成功；`v.requests == [LlmCompleteReq(prompt=PROMPT)]` |
| `test_summarize_falls_back_to_the_judge_provider_when_no_verify_provider_is_given` | `Brain(judge_llm=j)` | 成功；`j.requests` 长度 1 |
| `test_images_go_through_describe_and_no_images_fall_back_to_complete` | 同 verify 的写法 | 同 verify |
| `test_a_successful_attempt_returns_exactly_one_ledger_entry` | `summary_json()` | `len(result.calls) == 1`；`payload` 键集合恰为 `LEDGER_KEYS`；`ok == "true"`；`raw` 为回复原文；`prompt == PROMPT` |
| `test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry` | `ScriptedJudge(ToolTimeout("gateway down"))` | 抛 `SummarizeAttemptFailed`；`error_kind == "ToolTimeout"`；`__cause__` 是同一个实例；`payload` 键集合恰为 `{"ok","prompt","images","started_at","ended_at"}` |
| `test_summarize_never_retries_by_itself` | 只排一条无法解析的回复 | 抛后 `len(provider.requests) == 1` |
| `test_calling_summarize_without_any_provider_trips_the_entry_assert` | `Brain()` | `pytest.raises(AssertionError, match="verify provider")` |

## 六、验证

1. `python -m pytest tests/brain/judge_verify -p no:cacheprovider`：全绿、远小于 5 秒、不联网；
2. 全量 `python -m pytest`，起点与终点同一配置，每次用全新 `--basetemp=.pytest_tmp/run_<序号>`。
   首选口径：起点全绿、终点全绿，终点 passed = 起点 passed + 本任务新增用例数（参数化展开后的实数，汇报给实数）。
   **兜底口径**（仅当栈里仍出现 `sitecustomize` / `SAFE_DELETE` 守卫报错时）：失败集合不变——起点记下所有 failed / error 的测试 id（目前已知是 `tests/evals/.../test_evals_script_timeout.py` 的 2 条），终点集合必须逐条相同，passed = 起点 passed + 新增数；
   用户会在本机 PowerShell 再复验一遍，那次才是最终全绿依据；
3. `python -m ruff check .`、`python -m ruff format --check .` 全绿；
4. 破坏验证，**两处各做一次再还原**，用来证明测试有牙：
   - (a) `Brain._parse_verdict` 里把 `interrupted = raw.get("interrupted") is True and not done` 临时改成不带 `and not done`：`test_interrupted_is_only_honoured_when_done_is_false` 的「done=true, interrupted=true」那一组必须失败；
   - (b) `Brain._parse_verify` 里漏条补齐处把 `positive=False` 临时改成 `positive=True`：`test_a_missing_index_is_marked_negative_not_a_parse_failure` 必须失败；
   每处做完立即还原，**全部还原后确认 `git diff pokemon_agent/` 为空**。汇报里写明做了、结果如何。

不需要真实模型、不需要 ROM、不需要网络。

## 七、CHANGELOG

编号**不写死**（并行任务持续占用编号）：取 `git show HEAD:CHANGELOG.md` 最上面已提交条目的编号 +1，记作 M；动手写之前再取一次，若 HEAD 动了就重取。若工作区 `CHANGELOG.md` 已有**不属于本任务**的未提交改动，停下汇报（停止条件 5）。

按仓库四段格式追加到 `CHANGELOG.md` 最上，标题：
`## <今天日期，与最近条目同格式>（M）—— brain/judge_verify 单元测试`
- **改了什么**：新增 `tests/brain/judge_verify/` 下 `test_judge.py` / `test_verify.py` / `test_summarize.py`，复用 `tests/_doubles/llm.py`。
- **为什么这么改**：`judge` / `verify` / `summarize` 此前没有直接测试；「解析不出就抛、不静默降级」「漏条补负样本」「两种外层写法」「带图走 describe」都靠集成路径碰运气。
- **取舍**：解析只经公开方法测；`goal` / `history` 等「收下不读」的参数不钉成契约；`verify` 的字符串布尔、非列表 `verdicts`、重复 `index` 谁赢等未定义行为这轮不钉（见汇报里的观察项）。
- **影响面**：只增测试，不动 `pokemon_agent/` 下任何文件；写明新增用例数与全量 pytest 实数。

提交信息的标题复用 CHANGELOG 标题原文，前缀 `test(brain): `（与 `b593903` 同格式）。

## 八、停止条件

遇到下列任一情形**停下汇报，不要自己决定、不要重试、不要绕过**：
1. 起点 `ruff check` / `ruff format --check` 不是全绿；起点 pytest 的失败集合不等于已知那 2 条，或出现不能用删除守卫解释的失败；终点失败集合与起点不一致；
2. 任一用例失败，且原因是 `judge` / `verify` / `summarize` 的行为与本 spec 的断言不符（贴出输入、期望、实际）——不要改生产代码，不要改弱断言；
3. 需要改 `pokemon_agent/` 下任何文件才能让测试通过；
4. 需要改已有测试文件或已有 `_doubles` 文件才能继续；
5. `git status` 里出现本任务之外的受跟踪文件改动，或 `CHANGELOG.md` 有他人的未提交改动；
6. 任何真实模型调用、联网请求、ROM 读取。

## 九、非目标

`choose` / `plan` / `decompose` / `reflect` / `json_utils` / `wiring` / `domain` / `errors` / `providers` / `factory` / `schemas` 目录的测试；`BrainTool`（`direct/`）的重试循环；prompt 内容；O1–O4 的任何修复；任何生产代码改动。
