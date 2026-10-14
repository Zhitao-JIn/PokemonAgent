# spec —— brain/choose 单元测试（含脚本化假 provider）

> 状态：**已定稿，待执行**（v7，2026-10-14：CHANGELOG 编号不写死——并行任务持续占用编号；本任务条目编号 M = 前置任务（tests 入库）条目编号 N + 1，N 的取法见 `tests-tracking-spec.md` 头部；若 N+1 已被并行任务提交占用，则取 HEAD 版 CHANGELOG 最上面已提交编号 + 1。其余同 v6）
> 起草：2026-10-14
> 上游：`docs/test/brain-test-intent.md`（总意图；不一致以本文件为准）
> 被测：`pokemon_agent/brain/brain.py::Brain.choose`（含内部解析 `_parse` / `_collect_args` / `_script_arg`，**只经 `choose` 测**）
> 起点：分支 `codex/unify-script-execution`，HEAD `c2ded1d`

## 一、目标

用一个按脚本回话的假 provider，钉住 `Brain.choose` 的四件事：
1. 模型怎么写，大脑怎么读（解析）；
2. 每一类失败都有名字、带账、不吞；
3. 有图且模型多模态才走 `describe`，否则退化纯文本（转发表在 brain 层）；
4. 成功路径的后置条件：一次尝试恰好一条账、大脑自己不重试、没配 provider 就调会被入口 assert 当场拦下。

## 二、决定表

| # | 决定 | 理由 / 代价 |
|---|---|---|
| D1 | 不用 `MagicMock`，假 provider 是 `tests/_doubles/llm.py` 里手写的小类 | AGENTS.md「不写 mock 套 mock」；手写类还能直接当后续 plan / judge / verify 测试的夹具 |
| D2 | 解析分支一律经 `Brain.choose(...)` 喂文本测，不 import `_parse*` | AGENTS.md「不测私有函数」；`_load_json` 的直接测放 `json_utils/` 目录，不在本轮 |
| D3 | 失败断言看 `exc.value.call.error_kind`（`"ParseFailure"` / `"IllegalAction"` / `"OutputTruncated"` / `"ToolTimeout"`），再看 `exc.value.call.error` 里的关键词；**不**断言整句报错文本 | 报错措辞会改，错误类型名是 replay 统计的依据 |
| D4 | 账的时间字段只断言 `isinstance(float)` 且 `started_at <= ended_at`，不断言具体值 | AGENTS.md「不依赖时间戳精确值」 |
| D5 | 本轮只写 `choose`；`plan` / `judge` / `verify` 等**不要提前写** | 用户要求一个目录一个目录来 |
| D6 | 发现实现与 docstring 不符：**停下汇报，不改生产代码，不放宽断言** | 不把缺陷钉成预期 |
| D7 | 入口 assert 用 `pytest.raises(AssertionError, match="decide provider")` 测一条 | 已确认：每个方法一条，作为契约示范 |

## 三、文件清单

新增（全部在仓库根的 `tests/` 下）：

| 文件 | 内容 |
|---|---|
| `tests/_doubles/llm.py` | 脚本化假 provider（见第四节） |
| `tests/_doubles/brain_choose.py` | `choose` 测试共用常量（见第四节） |
| `tests/brain/choose/test_choose_parse.py` | 9 条解析用例 |
| `tests/brain/choose/test_choose_failures.py` | 失败分类用例 |
| `tests/brain/choose/test_choose_routing.py` | 4 条转发表用例 |
| `tests/brain/choose/test_choose_contract.py` | 5 条后置条件 / 契约用例 |
| `CHANGELOG.md` | 追加（M）条目（见第七节） |

**版本库口径（v6）**：`tests/` 已由前一个任务（`docs/test/tests-tracking-spec.md`，CHANGELOG（450））取消 `.gitignore` 忽略并把现有测试入库。所以本任务的 6 个测试 / 夹具文件**要提交**，用显式路径 `git add`（逐个文件，不用目录通配）。开工前先确认前一个任务的提交已在 `git log` 里、`git check-ignore tests/brain/choose/test_choose_parse.py` 无输出；否则停下汇报。

**不改**任何 `pokemon_agent/` 下的文件；不改已有测试；不新建 `__init__.py`（全仓靠文件名唯一，不靠包）。

## 四、夹具设计

### `tests/_doubles/llm.py`

```python
def text_reply(text, *, truncated=False, prompt_tokens=11, completion_tokens=7,
               cached_tokens=3, reasoning_tokens=2) -> LlmCompleteResp
def vision_reply(text, *, input_tokens=21, output_tokens=9,
                 cached_tokens=4, reasoning_tokens=5) -> VisionDescribeResp

class ScriptedLLM:            # 满足 LLMProvider
    multimodal: bool          # 构造参数，默认 False
    requests: list[LlmCompleteReq]
    def __init__(self, *replies, multimodal: bool = False) -> None
    def complete(self, req) -> LlmCompleteResp

class ScriptedJudge(ScriptedLLM):   # 满足 JudgeProvider
    described: list[VisionDescribeReq]
    def describe(self, req) -> VisionDescribeResp
```

- `replies` 按调用顺序消费；某一项是 `BaseException` 实例就**抛出**它，否则原样返回。
- `complete` / `describe` 先把收到的请求 append 到 `requests` / `described`，再取下一条回复。
- 回复用尽后再被调用：`raise AssertionError("ScriptedLLM ran out of replies")`。
- 类与函数带完整类型注解和一句 docstring；文件顶层 docstring 说明"谁用、为什么手写不用 MagicMock"。
- 为什么 `ScriptedJudge` 继承 `ScriptedLLM`：`Brain.choose` 的决策 provider 类型是 `LLMProvider`，但带图时会调 `describe`（brain 查 `multimodal` 标志后分派），所以决策位置也要能放 `ScriptedJudge`。

### `tests/_doubles/brain_choose.py`

```python
PROMPT = "..."                     # 任意非空字符串
KEYS = ["up", "down", "a"]
WALK_TO = ScriptSignature(name="walk_to", params=[ScriptArg(name="x", type="int"), ScriptArg(name="y", type="int")])
USE_ITEM = ScriptSignature(name="use_item", params=[ScriptArg(name="item", type="str"), ScriptArg(name="quantity", type="int", required=False)])
SCRIPTS = [WALK_TO, USE_ITEM]
IMAGE = "data:image/png;base64,AAAA"   # brain 不校验图内容，短串即可
```

## 五、测试清单

**通用写法**：每个文件顶层 docstring 写本文件的 intent；`from __future__ import annotations`；全部有类型注解；函数名是一句完整的话；Arrange / Act / Assert 三段用空行分开；公共 import 用 `from _doubles.llm import ...` 与 `from _doubles.brain_choose import ...`；被测对象用 `from pokemon_agent.brain import Brain, Action, ActionSegment, ScriptCall`，错误用 `from pokemon_agent.brain.errors import ...`，信封用 `from pokemon_agent.brain.schemas import ...`。

调用形态统一为：
`Brain(decide_llm=provider).choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)`（路由用例另带 `images=`）。成功时拿 `ChooseResult`，失败用 `with pytest.raises(DecisionAttemptFailed) as excinfo`。

### 1. `test_choose_parse.py` —— 成功解析（9 条）

| 函数名 | 模型回复 | 断言 |
|---|---|---|
| `test_a_key_name_becomes_a_single_segment_with_times_one` | `{"action": "up"}` | `action == Action(sequence=[ActionSegment(name="up", times=1)])`；`action.script is None` |
| `test_a_json_fence_around_the_answer_is_tolerated` | ` ```json\n{"action": "up"}\n``` ` | 同上 |
| `test_text_around_the_json_object_is_ignored` | `Sure, here is my move:\n{"action": "a"}\nHope that helps}` | 动作为单段 `a` |
| `test_a_script_call_reads_args_from_the_nested_object` | `{"action": "walk_to", "args": {"x": 5, "y": 2}}` | `action.script == ScriptCall(name="walk_to", args={"x": 5, "y": 2})`；`action.sequence == []` |
| `test_a_script_call_also_reads_args_flattened_at_the_top_level` | `{"action": "walk_to", "x": 5, "y": 2}` | 同上 |
| `test_integer_arguments_accept_digit_strings` | `{"action": "walk_to", "args": {"x": "5", "y": " 2 "}}` | `args == {"x": 5, "y": 2}`，值类型是 `int` |
| `test_fields_outside_the_signature_are_ignored` | `{"action": "walk_to", "x": 1, "y": 2, "thought": "hi"}` | `args == {"x": 1, "y": 2}` |
| `test_optional_script_arguments_may_be_missing_and_string_arguments_are_stripped` | `{"action": "use_item", "item": " potion "}` | `args == {"item": "potion"}`（无 `quantity` 键） |
| `test_surrounding_whitespace_in_the_action_name_is_stripped` | `{"action": "  up  "}` | 单段 `up` |

### 2. `test_choose_failures.py` —— 失败分类（用例名 9 个，参数化展开）

均先排好一条回复，调 `choose`，捕获 `DecisionAttemptFailed`，断言 `excinfo.value.call.error_kind` 与 `excinfo.value.call.error` 含关键词，另断言 `excinfo.value.call.payload["ok"] == "false"`。

| 函数名 | 回复 / 参数 | `error_kind` | `error` 含 |
|---|---|---|---|
| `test_an_action_outside_the_space_fails_as_illegal_action` | `{"action": "start"}` | `IllegalAction` | `start`、`up`、`walk_to` |
| `test_non_json_output_fails_as_parse_failure` | `I think we should go up` | `ParseFailure` | `not valid json` |
| `test_a_top_level_array_fails_as_parse_failure` | `["up"]` | `ParseFailure` | `top level is not an object` |
| `test_a_missing_or_empty_action_name_fails_as_parse_failure` | 参数化：`{"action": ""}`、`{"action": "  "}`、`{}`、`{"action": 3}` | `ParseFailure` | `non-empty string` |
| `test_a_script_missing_a_required_argument_fails_as_parse_failure` | `{"action": "walk_to", "x": 1}` | `ParseFailure` | `missing argument 'y'` |
| `test_a_wrongly_typed_int_argument_fails_as_parse_failure` | 参数化 `x` 取：`"five"`、`1.5`、`true`、`[]`（`y` 固定 `2`） | `ParseFailure` | `must be an integer` |
| `test_a_truncated_completion_fails_as_truncated_even_if_it_would_not_parse` | 参数化 `truncated=True`，文本 `{"action": "up"}`（本可解析）与 `{"action": "u`（不可解析） | `OutputTruncated` | `7`（`text_reply` 默认 `completion_tokens`） |
| `test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry` | `ScriptedLLM(ToolTimeout("gateway down"))` | `ToolTimeout` | `gateway down` |
| `test_a_failed_attempt_still_records_tokens_and_raw_text` | 回复 `text_reply("nonsense")` | `ParseFailure` | — |

附加断言：
- 第 8 条（provider 异常）：`excinfo.value.__cause__` 是同一个 `ToolTimeout` 实例；`excinfo.value.source == "choose"`；`call.payload` 的键集合恰为 `{"ok", "prompt", "images", "started_at", "ended_at"}`（没拿到响应，所以没有 token 与 `raw`），`payload["prompt"] == PROMPT`，`payload["images"] == []`。
- 第 9 条（失败仍留账）：`payload["raw"] == "nonsense"`；`payload["input_tokens"] == "11"`、`output_tokens == "7"`、`cached_tokens == "3"`、`reasoning_tokens == "2"`；`payload["prompt"] == PROMPT`。

### 3. `test_choose_routing.py` —— 转发表（4 条）

| 函数名 | 装配 | 断言 |
|---|---|---|
| `test_images_go_through_describe_when_the_model_is_multimodal` | `ScriptedJudge(vision_reply('{"action": "up"}'), multimodal=True)`，`images=[IMAGE, IMAGE]` | `described == [VisionDescribeReq(images=[IMAGE, IMAGE], prompt=PROMPT)]`；`requests == []`；账 `payload["images"] == [IMAGE, IMAGE]` |
| `test_images_are_dropped_to_plain_text_when_the_model_is_not_multimodal` | `ScriptedJudge(text_reply('{"action": "up"}'), multimodal=False)`，`images=[IMAGE]` | `requests == [LlmCompleteReq(prompt=PROMPT)]`；`described == []`；账 `payload["images"] == []`（带了图但没发出去，在账上看得见） |
| `test_no_images_means_plain_completion_even_for_a_multimodal_model` | `ScriptedJudge(text_reply('{"action": "up"}'), multimodal=True)`，不传 `images` | `requests` 长度 1、`described == []` |
| `test_the_two_response_shapes_land_in_the_same_ledger_keys` | 各跑一次：`vision_reply(...)`（多模态+图）与 `text_reply(...)`（纯文本） | 两次账的 `input_tokens` / `output_tokens` / `cached_tokens` / `reasoning_tokens` 分别等于对应响应里的数（`str`），键集合相同 |

### 4. `test_choose_contract.py` —— 后置条件与契约（5 条）

| 函数名 | 断言 |
|---|---|
| `test_a_successful_attempt_returns_exactly_one_ledger_entry` | `len(result.calls) == 1` |
| `test_the_ledger_carries_prompt_raw_and_token_counts_as_strings` | `payload` 键集合恰为 `{"input_tokens","output_tokens","cached_tokens","reasoning_tokens","ok","raw","prompt","images","started_at","ended_at"}`；四个 token 值是 `"11"` `"7"` `"3"` `"2"`；`ok == "true"`（小写）；`raw` 为回复原文；`prompt == PROMPT`；`images == []`；`started_at` / `ended_at` 是 `float` 且 `started_at <= ended_at`；`call.error_kind == ""` 且 `call.error == ""` |
| `test_the_prompt_reaches_the_provider_verbatim` | `provider.requests == [LlmCompleteReq(prompt=PROMPT)]`（`thinking` 为 `None`） |
| `test_choose_never_retries_by_itself` | provider 只排一条无法解析的回复；`choose` 抛 `DecisionAttemptFailed` 后 `len(provider.requests) == 1` |
| `test_calling_choose_without_a_decide_provider_trips_the_entry_assert` | `Brain()`（不给任何 provider）；`pytest.raises(AssertionError, match="decide provider")` |

## 六、验证

1. `python -m pytest tests/brain/choose -p no:cacheprovider`：全绿，耗时远小于 5 秒，不联网；
2. 全量 `python -m pytest`，**起点与终点必须同一配置**。删除上限已调到 5000，**首选口径是起点全绿、终点全绿**（终点 passed = 起点 passed + 新增用例数，汇报给实数）。
   **兜底口径**（仅当 pytest 栈里仍出现 `sitecustomize` / `SAFE_DELETE` 的守卫报错时才用）是“失败集合不变”：
   - 起点先跑一次全量，把所有 failed / error 的测试 id 完整记下来（执行沙箱里有一层删除守卫：同一轮累计删除满 50 次后，后续所有删文件操作被拦，会级联出一批 `tests/trace/` 的 ERROR，外加 `test_evals_script_timeout.py` 的 2 条 failed；这些是环境假失败，不是代码问题）；
   - 终点再跑一次全量，failed / error 的测试 id 集合必须与起点**逐条相同**，passed 数 = 起点 passed 数 + 本任务新增用例数（参数化展开后的实数）；
   - 起点那批失败项里，凡是单独跑能通过的（如 `tests/trace/test_trace_store.py` 单独跑），在汇报里列出“单独跑通过”的证据；
   - 每次 pytest 都用全新的 `--basetemp=.pytest_tmp/run_<序号>`（该目录已在 .gitignore 里），不要再起别的名字的临时目录；
   - 用户会在本机 PowerShell（无此守卫）再复验一遍全量，那一次才是最终全绿的依据；
3. `python -m ruff check .`、`python -m ruff format --check .` 全绿；
4. 手动破坏一次再还原（只做一次，用来证明测试有牙）：把 `Brain.choose` 里 `if truncated:` 那一段临时注释掉，`test_a_truncated_completion_fails_as_truncated_even_if_it_would_not_parse` 必须失败；**还原后确认 `git diff pokemon_agent/` 为空**。汇报里写明做了、结果如何。

不需要真实模型、不需要 ROM、不需要网络。

## 七、CHANGELOG（M）

按仓库四段格式追加到 `CHANGELOG.md` 最上，标题：
`## 2026-10-14（M）—— brain/choose 单元测试与脚本化假 provider`
- **改了什么**：新增 `tests/_doubles/llm.py`（`ScriptedLLM` / `ScriptedJudge` 与两个回复构造函数）、`tests/_doubles/brain_choose.py` 与 `tests/brain/choose/` 下四个测试文件。
- **为什么这么改**：`Brain.choose` 此前没有任何直接测试；解析的各个分支、失败分类与账、有图时的转发表都靠集成路径碰运气。
- **取舍**：解析器只经 `choose` 测、不 import 私有函数；假 provider 手写不用 MagicMock，后面 plan / judge / verify 目录复用它；入口 assert 只测一条作为契约示范。
- **影响面**：只增测试与测试夹具，不动 `pokemon_agent/` 下任何文件；写明新增用例数与全量 pytest 实数。

## 八、停止条件

遇到下列任一情形**停下汇报，不要自己决定、不要重试、不要绕过**：
1. 起点 `ruff check` / `ruff format --check` 不是全绿；或起点 pytest 不绿且失败里出现**不能用删除守卫解释**的项（判据：该测试单独跑也失败，且栈里没有 `sitecustomize` / `SAFE_DELETE`）；终点失败集合与起点不一致；
2. 任一用例失败，且原因是 `Brain.choose` 的行为与本 spec 的断言不符（贴出输入、期望、实际）——不要改生产代码，不要改弱断言；
3. 需要改 `pokemon_agent/` 下任何文件才能让测试通过；
4. 需要改已有测试文件或已有 `_doubles` 文件才能继续；
5. `git status` 里出现本任务之外的受跟踪文件改动；
6. 任何真实模型调用、联网请求、ROM 读取。

## 九、非目标

`plan` / `decompose` / `judge` / `verify` / `summarize` / `reflect` / `json_utils` / `wiring` / `domain` / `errors` / `providers` / `factory` / `schemas` 目录的测试；`BrainTool`（`direct/`）的重试循环；prompt 内容；任何生产代码改动。
