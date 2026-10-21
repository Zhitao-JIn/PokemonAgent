# spec —— `tests/direct/trace/`：从 `test_trace_store.py` 搬出的 `TraceTool` 门面用例

> 依据：`docs/test/trace-test-intent.md` 第七节决定 2；`tests/trace/test_trace_store.py`（385 行、16 例）。
> 检查点：CP1（573）。
> 本文只管**搬家**，不重写门面测试——`direct` 层整体留给 direct 那一轮。

## 一、决定表

| 编号 | 决定 | 理由与代价 |
|---|---|---|
| D1 | 7 个依赖 `TraceTool` / `FromHarnessToTraceToolAppendReq` 才能 Arrange 的用例，**逐字**搬到 `tests/direct/trace/test_trace_tool_contract.py`，断言、docstring、用例名都不改 | 搬家不引入行为差异，验收可以用 diff 核对 |
| D2 | 搬过去的文件自带 `_tool` / `_step_advance` 两个辅助函数（从原文件原样复制）和 `pathlib` / `json` / `pytest` 所需 import | 测试文件之间不互相 import；共用替身才放 `_doubles/` |
| D3 | 原文件顶部的 module docstring **不搬**，新文件写一段新的（说明「这些用例钉的是 `TraceTool` 的契约，不是 `trace` 模块的」） | 旧 docstring 描述的是已过时的七字段与 `(ended_at, uuid)` |
| D4 | 另加 1 条新用例 `test_trace_event_shape_matches_the_trace_event_protocol`，放新文件 `tests/direct/trace/test_trace_event_alignment.py` | 它守的是「`schemas.harness.domain.TraceEvent` 的字段 == `trace.Event` 协议的属性」，需要 import 项目侧形状，因此不能放进 `tests/trace/`（那边要保持对 `pokemon_agent` 其余部分零依赖的观感） |
| D5 | `test_meta_and_content_are_json_strings_with_the_run_id_stamped_in` **不搬**（它的 JSON 字符串一半已改写进 `local/` A4）；「run_id 被盖章」一半已被 `tests/direct/trace/test_trace_tool.py::test_the_tool_stamps_run_id_and_branch_into_meta` 覆盖 | 避免两处重复；该用例随旧文件一起删除 |
| D6 | 搬家不去重：`test_meta_is_the_harness_signature_and_is_forwarded_verbatim` 与 `test_the_tool_stamps_run_id_and_branch_into_meta` 有重叠，也照搬 | 去重属于 direct 那一轮的判断 |

## 二、搬家清单（7 条，逐字）

| # | 原用例名（`test_trace_store.py`） | 新位置 |
|---|---|---|
| 1 | `test_call_kind_is_the_account_name_and_a_failed_attempt_is_its_own_event` | `test_trace_tool_contract.py` |
| 2 | `test_meta_is_the_harness_signature_and_is_forwarded_verbatim` | 同上 |
| 3 | `test_a_signature_missing_a_key_is_refused` | 同上 |
| 4 | `test_an_empty_source_in_the_signature_is_refused` | 同上 |
| 5 | `test_a_caller_supplied_run_id_is_refused` | 同上 |
| 6 | `test_a_caller_supplied_count_is_refused` | 同上 |
| 7 | `test_build_factory_forwards_the_trace_root` | 同上 |

> intent 第七节决定 2 写的是「6 个」，实际核对后是 **7 个**（多出的是 #2）；以本表为准（intent 里的数字已同步改为 7）。

新用例（#8）：

8. `test_trace_event_shape_matches_the_trace_event_protocol`（`test_trace_event_alignment.py`）：`set(TraceEvent.model_fields)` == `set(Event.__annotations__)`（`Event` 取自 `pokemon_agent.trace`）。

## 三、验收口径（门面部分）

- 搬走的 7 条在新文件中的函数体与原文件逐行一致（执行方用 `diff` 或 AST 比较给出证据）；
- `tests/direct/trace/` 下已有文件一个字节都不改；
- 旧文件 `tests/trace/test_trace_store.py` 在 CP1 末尾删除后，`tests/trace/` 根目录下只剩新文件与 `langfuse/`；
- 全仓收集数核对：`N1 == N0 − 16 + 7 + 1 + (tests/trace 新增 CP1 部分)`，其中 `tests/trace` 新增 CP1 部分 = 契约 14 + 序号 4 + 事件协议 3 + 包边界 3 + `local/` 29 = **53**，所以 `N1 == N0 + 45`。

## 四、停止条件

1. 搬走的用例在新位置不是逐字相同；
2. D4 的对齐用例在当前代码上就红（`TraceEvent` 与 `Event` 已经不一致）——汇报，不自行改任何一边；
3. `tests/direct/trace/` 现有测试因搬家变红。

## 五、非目标

不重写 `test_trace_tool.py`、`test_trace_render.py` 等 direct 层测试；不为门面补新用例。
