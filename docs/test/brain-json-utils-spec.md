# spec —— brain/json_utils 单元测试（`_load_json` 的容忍边界）

> 状态：**已定稿，待执行**（v1，2026-10-14）
> 上游：`docs/test/brain-test-intent.md` 第 5 节；写法与验证口径沿用 `docs/test/brain-plan-spec.md`
> 被测：`pokemon_agent/brain/brain.py::_load_json`（内部调 `_strip_json_fence`，**只经 `_load_json` 测**）
> 这是本模块**唯一直接测私有函数**的目录（intent 硬边界 2 的已确认破例）：`_load_json` 是 choose / judge / verify / summarize / plan / decompose 六条解析共用的地基，它的容忍边界本身就是契约。
> CHANGELOG 编号：动态取号（取分支 HEAD 的 CHANGELOG 最上面已提交编号 +1，动手前再取一次）

## 一、契约（来自 `_load_json` 的 docstring，已用探针核实）

「剥围栏后，从第一个 `{` 或 `[` 起读出**一个完整的 JSON 值**，它之后的内容一律忽略。值**之外**的多余内容容忍；值**内部**的语法错误与截断照样抛 `json.JSONDecodeError`，交给调用方重试，不在这里猜着修。」

## 二、决定表

| # | 决定 | 理由 / 代价 |
|---|---|---|
| D1 | 只 import `_load_json`：`from pokemon_agent.brain.brain import _load_json`；`_strip_json_fence` 不单独测，`_override` 也不在此测（已被 plan / decompose 目录的 `thinking_override` 用例覆盖，重复无益） | 破例只开到必要处 |
| D2 | 失败断言用 `pytest.raises(json.JSONDecodeError)`；只对「没有 JSON 值」这一类额外断言 `excinfo.value.msg` 含 `no JSON value`；**不**断言其余错误的具体措辞（那是标准库的文案） | 措辞会随 Python 版本变 |
| D3 | 成功断言比较解析出的 Python 值（`==`），不比较字符串 | 契约是「读出值」 |
| D4 | 实现与 docstring 不符：**停下汇报，不改生产代码，不放宽断言** | 不把缺陷钉成预期 |
| D5 | 一个函数一句话；同类输入用 `pytest.mark.parametrize`，参数给 `id` | 失败时一眼看出是哪种输入 |

### 已知观察（**不写测试**，汇报里转述）

- O7：起点是文本里**第一个** `{` 或 `[`。前缀里若出现不属于答案的括号（如 `see [note]: {"a": 1}`、`use {x} then {"a": 1}`）会从那里开始读并抛错，不会跳到后面真正的对象。docstring 已写明「第一个」，这是设计取舍，不是缺陷；但模型写出这类前缀并不罕见，建议留意重试率，本轮不测、不改。
- O8：围栏标签只认「恰好剥掉 `json` 这四个字符」，`` ```jsonl `` 会剩下 `l` 开头的内容。无实际调用场景，不测。

## 三、文件清单

新增（目录不存在则新建，不加 `__init__.py`）：`tests/brain/json_utils/test_load_json.py`。不改任何已有文件。

## 四、测试清单

写法：顶层 docstring 写 intent；`from __future__ import annotations`；全部类型注解；Arrange / Act / Assert 空行分段。

| 函数名 | 输入（参数化时每项给 id） | 断言 |
|---|---|---|
| `test_a_fence_with_or_without_the_json_tag_is_stripped`（参数化 5 组） | `` ```json\n{"a": 1}\n``` ``；`` ```\n{"a": 1}\n``` ``；`` ```JSON\n{"a": 1}\n``` ``；`` ```json{"a": 1}``` ``（标签后无换行）；`` "  ```json\n{\"a\": 1}\n```  " ``（围栏两侧有空白） | 都得 `{"a": 1}` |
| `test_only_the_outermost_fence_is_handled` | `` ```json\n{"a": 1}\n``` and ```json\n{"b": 2}\n``` `` | 得 `{"a": 1}`（第一个值，之后忽略） |
| `test_text_before_the_first_brace_is_skipped`（参数化 3 组） | `Sure, here it is:\n{"a": 1}`；`say "hi" then {"a": 1}`；`` text ```json\n{"a": 1}\n``` ``（围栏前有散文） | 都得 `{"a": 1}` |
| `test_content_after_the_value_is_ignored`（参数化 4 组） | `{"a": 1} trailing words`；`{"a": 1}}`（多一个右括号）；`{"a": 1} // note`；`` {"a": 1}\n{"b": 2} ``（第二个对象） | 都得 `{"a": 1}` |
| `test_a_top_level_array_is_a_valid_start` | `prefix [1, 2] suffix` | 得 `[1, 2]` |
| `test_the_earlier_of_an_object_and_an_array_wins` | `[{"a": 1}] {"b": 2}` | 得 `[{"a": 1}]`（起点取更靠前的那个） |
| `test_a_nested_value_is_read_whole` | `x {"a": {"b": [1, {"c": 2}]}} y` | 得 `{"a": {"b": [1, {"c": 2}]}}` |
| `test_a_closing_brace_inside_a_string_does_not_end_the_value` | `{"a": "x}"} tail` | 得 `{"a": "x}"}` |
| `test_a_syntax_error_inside_the_value_still_raises`（参数化 4 组） | `{"a": 1,}`（尾逗号）；`{"a": 1 "b": 2}`（漏逗号）；`{"a": 1, // c\n "b": 2}`（值内注释）；`{a: 1}`（键没引号） | 抛 `json.JSONDecodeError` |
| `test_single_quotes_still_raise` | `{'a': 1}` | 抛 `json.JSONDecodeError` |
| `test_a_truncated_value_still_raises`（参数化 3 组） | `{"a": 1`；`{"a": [1, 2`；`[ {"a": 1} ` | 抛 `json.JSONDecodeError` |
| `test_text_without_any_json_value_raises`（参数化 6 组） | `""`；`"   "`；`just words`；`` ```json\n``` ``；`"just a string"`；`123` | 抛 `json.JSONDecodeError`，且 `excinfo.value.msg` 含 `no JSON value` |

## 五、验证

1. `python -m pytest tests/brain/json_utils -p no:cacheprovider`：全绿、远小于 1 秒；
2. `python -m ruff check .`、`python -m ruff format --check .` 全绿；
3. 全量 `python -m pytest`：在**独立 worktree** 里跑（见交接消息），起点与终点同一配置，终点 passed = 起点 passed + 新增数；已知的 `test_evals_script_timeout.py` 2 条沙箱删除守卫失败可存在，须逐条一致；
4. 破坏验证，两处各做一次再还原：
   - (a) 把 `_load_json` 里 `value, _end = json.JSONDecoder().raw_decode(stripped, start)` 临时改成 `value = json.loads(stripped[start:])`：`test_content_after_the_value_is_ignored` 必须有失败；
   - (b) 把 `start = min(starts)` 临时改成 `start = max(starts)`：`test_the_earlier_of_an_object_and_an_array_wins` 必须失败；
   还原后 `git diff pokemon_agent/` 必须为空。

## 六、CHANGELOG

标题：`## <日期，同最近条目>（N）—— brain/json_utils 单元测试`
- **改了什么**：新增 `tests/brain/json_utils/test_load_json.py`，直接钉 `_load_json` 的容忍边界。
- **为什么这么改**：六条解析共用这块地基，此前它的边界只被各条链的用例间接碰到；改一处会静默影响全部。
- **取舍**：这是 brain 测试里唯一直接测私有函数的地方（破例已确认）；围栏标签细节与括号前缀的限制只记入观察，不钉成预期。
- **影响面**：只增测试，不动 `pokemon_agent/`；新增用例数与 pytest 尾行只写亲眼见到的实数。

提交信息标题复用 CHANGELOG 标题原文，前缀 `test(brain): `。

## 七、停止条件

1. 起点 `ruff` 不全绿，或起点全量 pytest 的失败不属于上述已知 2 条；终点失败集合与起点不同；
2. 任一用例失败且原因是 `_load_json` 的行为与上表不符（贴出输入、期望、实际）；
3. 需要改 `pokemon_agent/` 或已有测试文件才能继续；
4. `git diff --cached --stat` 里出现预期之外的文件，或 CHANGELOG 的暂存 diff 远大于条目大小（行尾被整体改写）；
5. 任何真实模型调用、联网、ROM 读取。

## 八、非目标

`wiring` / `domain` / `errors` / `providers` / `factory` / `schemas` / `reflect` 目录；`_override` 的单测；O7、O8 的任何改动；任何生产代码改动。
