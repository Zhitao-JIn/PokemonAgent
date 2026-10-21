# spec —— `tests/trace/`：`TracePort` 契约、进程内序号、事件协议与词表、包边界

> 依据：`docs/test/trace-test-intent.md`；源码 `trace/interface/trace_port.py`、`interface/event.py`、`seq.py`、`datastore/{event,trace_event}.py`、`trace/__init__.py`。
> 检查点：全部属 CP1（573）。
> 探针依据：见 `trace-local-spec.md` 开头（P8、P10、P13、P14）。另：`next_seq` 8 线程 × 500 次共 4000 个值全部唯一且为正；`from pokemon_agent.trace import …` 当前会连带导入 `langfuse_trace` / `langfuse_support`，但 `langfuse` SDK 本体只在调用时才导入（沙箱未装 SDK 也能导入包）。

## 一、决定表

| 编号 | 决定 | 理由与代价 |
|---|---|---|
| D1 | 契约文件用一个名为 `trace` 的 pytest 夹具提供实现，`params=["local"]`；夹具只造 `LocalTrace(root=tmp_path)`，不 import `LangfuseTrace` | Langfuse 放到 trace 线最后阶段（用户 2026-10-21）；届时只往 `params` 里加一项和一个构造分支，用例不改 |
| D2 | 契约用例只用 `TracePort` 的四个方法 + 返回的 `Event` 属性，**不**读磁盘、不碰 `tmp_path` 里的文件 | 这样同一批用例才能原样套到第二个实现上；磁盘断言留给 `local/` |
| D3 | `next_seq` 不断言绝对值（进程内计数器会被别的测试推进），只断言相对关系：严格递增、唯一、为正 | 全局状态；intent 第四节第 5 条 |
| D4 | 事件协议对齐用「`Event` 协议声明的属性名集合 == 盘上记录的键集合」来守，`Event.__annotations__` 取属性名 | 这是 `store.py` / `event.py` 文档里写的「没有编译器保护」那一条的机械版 |
| D5 | 包边界用 `ast` 扫描 `pokemon_agent/trace/**.py`，相对 import 按 PEP 328 解析（逻辑与 `scripts/check_trace_self_contained.py` 的 A 项一致，测试里自带一份约 25 行的实现，不 import `scripts/`） | `scripts/` 不是包；脚本保持不动（用户已定） |
| D6 | 第三方依赖白名单 `{pydantic, httpx, langfuse}`（目前 `trace/` 顶层与函数内的非标准库 import 恰为这三个） | 守「trace 是独立模块、依赖面小」；以后加新依赖必须有意识地改白名单 |
| D7 | 标准库判定用 `sys.stdlib_module_names`（3.10+） | 不手写标准库名单 |
| D8 | `EventType` 的值与 `EventTypeName` 的 `Literal` 成员互相对照 | 两处是人工同步的（`trace_event.py` 文档里写了「类型级表达只有这一处」） |

## 二、用例清单

### C. `test_trace_port_contract.py`（14 条；夹具 `trace` 见 D1）

1. `test_the_implementation_satisfies_the_trace_port_protocol`：`isinstance(trace, TracePort)`。
2. `test_append_returns_the_uuid_of_the_event_it_stored`：返回值等于读回事件的 `uuid`，是非空 `str`。
3. `test_two_appends_get_two_distinct_uuids`。
4. `test_an_empty_trace_reads_as_an_empty_list`。
5. `test_reading_without_a_filter_returns_every_event`：`None` 与 `{}` 都返回全部。
6. `test_filter_requires_every_given_key_to_match`：两个键各自单独命中不同的事件、合起来只命中一个。
7. `test_filter_is_and_not_or`：两个条件各命中一条、交集为空 → `[]`。
8. `test_an_event_missing_a_filtered_key_never_matches`：筛不存在的键 → `[]`；筛 `{"episode_id": ""}` 也不命中缺该键的事件（缺键 ≠ 空值）。
9. `test_filter_compares_values_by_equality_including_type`：`step` 存的是整数 `3`：`{"step": 3}` 命中，`{"step": "3"}` 不命中。
10. `test_a_filter_that_matches_nothing_returns_an_empty_list_without_raising`。
11. `test_events_are_returned_ordered_by_ended_at`：以乱序的 `ended_at` 写入，读回升序。
12. `test_equal_ended_at_is_broken_by_append_order`：四笔同刻账，读回顺序 == 写入顺序。
13. `test_meta_and_content_decode_back_to_the_original_objects`：中文、嵌套 list / dict、`None` 往返无损（`json.loads(event.meta)` / `event.content`）。
14. `test_flush_and_shutdown_can_be_called_repeatedly_and_events_stay_readable`：各调两次，均返回 `None`，之后 `read_events` 仍返回之前的事件。

### S. `test_trace_append_sequence.py`（4 条）

15. `test_next_seq_is_positive_and_strictly_increasing`。
16. `test_next_seq_hands_out_unique_values_across_threads`：8 线程 × 500。
17. `test_seq_is_process_wide_not_per_instance`：两个 `LocalTrace` 交替 append，读回事件的 `seq` 严格递增且互不相同。
18. `test_two_instances_break_equal_end_times_by_process_append_order`：两个实例共用一个根、交替写四笔同刻账 → 读回按 0,1,2,3（由 `tests/direct/trace/test_trace_seq.py` 的 local 半边改写，不经 `TraceTool`）。

> 文件名为什么不是 `test_trace_seq.py`：`tests/direct/trace/` 下已有同名文件，而本仓库测试文件名全仓唯一（多数目录无 `__init__.py`）。

### E. `test_trace_event_protocol.py`（3 条）

19. `test_the_event_protocol_declares_exactly_the_fields_stored_on_disk`：`set(Event.__annotations__)` == 一条落盘记录的键集合（D4）。
20. `test_event_type_constants_are_the_seven_documented_strings`：`EventType` 的公开常量值 == `{"model_call","error","llm_outcome","view","act","memory_io","lifecycle"}`。
21. `test_event_type_name_literal_covers_exactly_the_event_type_constants`：`typing.get_args(EventTypeName)` 与上一条同集合（D8）。

### B. `test_trace_package_boundary.py`（3 条）

22. `test_the_trace_package_imports_nothing_else_from_pokemon_agent`：D5；失败信息列出 `文件:行号 import 模块`。
23. `test_the_trace_package_only_uses_standard_library_and_allowed_third_party_modules`：D6、D7。
24. `test_the_package_root_exports_exactly_the_documented_names`：`pokemon_agent.trace.__all__` == `{"Event","EventType","LangfuseTrace","LocalTrace","TracePort","new_event_uuid"}`（只对照名字，不构造 `LangfuseTrace`）。

**合计 24 条。**

## 三、迁移与删除

| 现有用例 | 处理 |
|---|---|
| `test_trace_store.py::test_reading_a_slice_goes_through_meta_not_the_envelope` | 改写为契约 C6 / C10 |
| `…::test_meta_filter_is_and_of_equalities` | 改写为契约 C5 / C7 |
| `…::test_a_missing_key_never_matches` | 改写为契约 C8 |
| `…::test_uuid_is_the_file_name_and_lives_on_the_envelope` | 契约 C2（uuid 与返回值一致）；「uuid 即文件名」一半已在 `local/` A1 |
| `tests/direct/trace/test_trace_seq.py` | **不动**（同时参数化 local 与 langfuse，随 Langfuse 阶段再处理）；S4 是它 local 半边的直接版本 |
| `scripts/check_trace_self_contained.py` | **不动**（B1 对应它的 A 项）。已知：它的 B 项仍写「入口只在 `tools/`」，而 `tools/` 已拆成 `direct/` 与 `mcpclient/`，脚本现在大概率会误报——记入台账，由用户另案决定修还是删 |

## 四、停止条件

1. 契约用例要读磁盘才能写出来（说明契约里有遗漏，停下问）；
2. B2 在当前代码上就红（出现白名单之外的第三方 import）——汇报具体文件与模块，不自行改白名单；
3. E1 在当前代码上就红（`Event` 协议与盘上字段已经不一致）——这是一个真缺陷，汇报，不自行改任何一边；
4. 耗时超限（`tests/trace/` 非 langfuse 部分 > 3 秒）。

## 五、非目标

不构造 `LangfuseTrace`；不测 `TraceKind`（在 `schemas/`，属于声明方）；不测 `TraceTool`。
