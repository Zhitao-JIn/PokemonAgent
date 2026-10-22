# spec —— `tests/trace/local/`：`LocalTrace` 与 `new_event_uuid` 的单元测试（含 T1 修复）

> 依据：`docs/test/trace-test-intent.md`；源码 `pokemon_agent/trace/store.py`（228 行）、`datastore/event.py`、`interface/trace_port.py`。
> 检查点：CP1（584）写 A / R / G1–G5 / O / U；CP2（585）写 G6–G8 并修 T1。
> 探针依据（2026-10-21，设计侧沙箱实跑，Python 3.10 + pydantic 2.14，补 `datetime.UTC`）：
> P1 `append(content={1,2})` 抛 `TypeError`，落盘根下无任何残留文件；
> P2 目录 `dir.json`、截断 JSON、非 UTF-8 字节、`.json.tmp` 残留都被跳过，其余事件照常读出；
> P5 `{"step": 3}` 命中 `step=3`，`{"step": "3"}` 不命中；
> P6 `meta` 为 `"[1,2]"` 的文件：不筛选时被列出，任何非空筛选都不命中；
> P7 带多余字段的新格式文件照常读出，缺 `seq` 的旧格式文件被跳过；
> P8 2000 次 `new_event_uuid` 无重复，版本位恒为 7，变体位 ∈ {8,9,a,b}，跨毫秒字典序即时间序；
> P9 `meta=None` 落成 `"{}"`，`content=None` 落成 `"null"`，非 ASCII 不转义；
> P12 两个实例共用一个根互相可见；P13 同 `ended_at` 的四笔账按 append 序读回，`seq` 严格递增；
> P17 根目录被删后 `read_events` 返回 `[]`、`append` 会重建目录；
> **P18 文件被设成不可读（`chmod 0`）时 `read_events` 静默少一条（返回 0 条），不抛错**——与 `TracePort.read_events` 的「失败：底层读取失败原样抛出——本方法不吞这一类错」相悖，即 T1。

## 一、决定表

| 编号 | 决定 | 理由与代价 |
|---|---|---|
| D1 | 只经公开面测：`LocalTrace(root)`、`append`、`read_events`、`flush`、`shutdown`、`new_event_uuid`；可观察通道 = 返回值、`tmp_path` 下的文件、读回的 `Event` | intent 第四节第 2 条；不碰 `_scan_events` / `_dir` / `_Event` |
| D2 | 落盘根一律显式 `LocalTrace(root=tmp_path)`；缺省根用例用 `monkeypatch.chdir(tmp_path)` | 不往仓库写 `tracelog/` |
| D3 | 共用小工具 `tests/_doubles/trace.py` 只放一个函数 `signed_meta(**overrides)`（返回带 `run_id` / `branch` / `source` / `episode_id` / `task_id` / `step` 的 dict）；不放假件，因为 `LocalTrace` 没有需要替身的依赖 | 少六行重复；`_doubles` 是共享夹具的约定位置 |
| D4 | 「同刻」直接给两笔账传相同 `ended_at`；「跨毫秒」monkeypatch `pokemon_agent.trace.store.time.time`；「现在」用调用前后各取一次 `time.time()` 夹住，不比精确值 | intent 第四节第 5 条：不 sleep、不依赖时间戳精确值 |
| D5 | 磁盘上的字段名用字面量断言（`{"uuid","seq","kind","type","started_at","ended_at","meta","content"}`） | 这就是封套契约本身；`Event` 协议与它的对齐由事件协议 spec 守 |
| D6 | **T1 修复**：`_scan_events` 里 `except Exception: continue` 收窄为 `except (ValidationError, UnicodeDecodeError): continue`，并在读文件前跳过非文件（`if not path.is_file(): continue`）。`OSError` 及其他异常原样向上抛 | `TracePort.read_events` 契约写明底层读取失败不吞；残文件 / 旧格式 / 非 UTF-8 是预期内情况（AGENTS.md 第八节：预期内失败走显式处理）。代价：目录里出现无读权限的 `.json` 文件时 `read_events` 会抛 `PermissionError`，而不是悄悄少事件——这正是想要的 |
| D7 | 「无读权限」用 `monkeypatch.setattr(pathlib.Path, "read_text", …)` 对 `.json` 文件抛 `PermissionError` 来模拟，**不用 `chmod`** | 用户机器是 Windows，`chmod 0` 不生效；沙箱里以 root 跑同样不生效 |
| D8 | **T3 不改生产代码**：只写用例钉住「不可序列化 `content` 抛 `TypeError` 且不落文件」，并在 CP3（586）里把这句话补进 `append` 的 docstring | 探针 P1 已证实当前行为符合直觉；补文档不补代码 |
| D9 | **T4 / T5 不钉**：不写「反向区间」「缺 `run_id`」的期望用例；A5 只钉「`LocalTrace` 对 `meta` 透传、不补盖、不要求任何键」 | intent 第六节：嫌疑项不钉成预期；A5 的断言写的是 docstring 已承诺的透传 |

## 二、用例清单

### A. `test_local_trace_append.py`（12 条）

1. `test_append_writes_one_json_file_named_by_the_returned_uuid`：返回 `u` → 根下恰好一个 `u.json`。
2. `test_file_name_is_a_time_ordered_uuid_v7`：文件名匹配 v7 正则。
3. `test_stored_record_has_exactly_the_eight_contract_fields`：`json.loads` 文件，键集合正好是 D5 那八个。
4. `test_meta_and_content_are_stored_as_json_strings`：盘上 `meta` / `content` 是 `str`，`json.loads` 回原对象。
5. `test_meta_is_stored_verbatim_without_stamping_or_requiring_any_key`：传 `{"source": "s"}`，读回 `meta` 解码后恰好等于它（没有补 `run_id` / `branch`，也没有因缺键报错）。
6. `test_none_meta_is_stored_as_an_empty_object`：`"{}"`。
7. `test_none_content_is_stored_as_json_null`：`"null"`。
8. `test_non_ascii_content_is_written_unescaped`：原始文件文本里能直接找到中文字符，且解码后相等；嵌套 list / dict 往返无损。
9. `test_missing_times_default_to_the_same_append_moment`：`started_at == ended_at`，且落在调用前后两次 `time.time()` 之间。
10. `test_given_start_and_end_pass_through_exactly`：两个都传，读回逐值相等。
11. `test_only_a_given_start_leaves_the_end_at_the_append_moment`：传 `started_at`，`ended_at` 落在调用前后之间且 `started_at` 原样。
12. `test_unserializable_content_raises_type_error_and_writes_nothing`：`content={1, 2}` → `TypeError`；根下无任何文件。

### R. `test_local_trace_read.py`（4 条）

13. `test_two_instances_on_one_root_see_each_others_events`。
14. `test_events_of_different_runs_share_the_root_and_are_sliced_by_run_id`：同根下两个 `run_id`，筛选各得各的，不筛得全部。
15. `test_reading_does_not_modify_the_root`：读前后文件名集合与每个文件的字节相等。
16. `test_read_events_return_typed_event_objects`：`isinstance(e, Event)`；`started_at` / `ended_at` 是 `float`、`seq` 是 `int`、`meta` / `content` 是 `str`、`uuid` 等于文件 stem。

### G. `test_local_trace_tolerance.py`（8 条；G1–G5 属 CP1，G6–G8 属 CP2）

每条的 Arrange 都是：先 `append` 一条好事件，再往根里手写一个坏文件；Assert 两件事——好事件仍读得出、坏文件没有混进结果（G8 除外）。

17. `test_a_truncated_json_file_is_skipped`（G1）。
18. `test_a_file_in_the_pre_seq_format_is_skipped`（G2）：合法 JSON 但缺 `seq`。
19. `test_a_leftover_tmp_file_is_ignored`（G3）：`x.json.tmp`。
20. `test_a_file_with_unknown_extra_fields_is_still_read`（G4）。
21. `test_a_file_whose_meta_is_not_an_object_matches_no_condition`（G5）：`meta` 为 `"[1,2]"`：`read_events()` 与 `read_events({})` 列出，`read_events({"run_id": …})` 不含它。
22. `test_a_file_with_invalid_utf8_is_skipped`（G6，CP2）。
23. `test_a_directory_named_like_an_event_file_is_skipped`（G7，CP2）：`dir.json/`。
24. `test_an_unreadable_event_file_makes_read_events_raise_instead_of_hiding_it`（G8，CP2）：按 D7 模拟，`pytest.raises(PermissionError)`。**实现前必须先红**（当前返回少一条、不抛），执行方汇报红灯输出后再改生产代码。

### O. `test_local_trace_root.py`（4 条）

25. `test_default_root_is_tracelog_under_the_startup_directory`（由 `test_default_root_is_the_startup_directory` 迁来，改为只用 `LocalTrace`）。
26. `test_a_str_root_is_accepted`：传 `str(tmp_path / "x")`。
27. `test_missing_root_directories_are_created_recursively`：`tmp_path/a/b/c`。
28. `test_events_written_earlier_are_visible_to_a_new_instance`：先写后新建实例再读。

### U. `test_new_event_uuid.py`（4 条）

29. `test_uuid_has_the_v7_layout`：版本位 `7`、变体位 ∈ {8,9,a,b}、`uuid.UUID` 可解析。
30. `test_two_thousand_uuids_are_all_distinct`。
31. `test_a_later_millisecond_sorts_after_an_earlier_one`：monkeypatch `time.time`（D4）。
32. `test_the_first_48_bits_carry_the_millisecond_timestamp`：固定 `time.time` 为 `1_000_000.123` → 前 12 个十六进制位 == `int(…*1000)`。

**合计 32 条**（CP1 = 29 条，CP2 = 3 条）。

## 三、迁移与删除

| 现有用例（`tests/trace/test_trace_store.py`） | 处理 |
|---|---|
| `test_trace_writes_one_json_per_event_named_by_its_uuid` | 改写为 A1 + A2 + 契约 C13 |
| `test_event_has_exactly_the_seven_contract_fields` | 改写为 A3（名称与注释同时修正为「八个」） |
| `test_meta_and_content_are_json_strings_with_the_run_id_stamped_in` | JSON 字符串一半改写为 A4；「run_id 被盖章」一半留给门面文件（见 facade spec） |
| `test_default_root_is_the_startup_directory` | 迁为 O1（#25） |
| 其余 | 见契约 spec 与门面 spec |

`test_trace_store.py` 在 CP1 末尾**整文件删除**（其 16 个用例的去向合计：改写 8、迁移 1、搬门面 7）。

## 四、T1 的生产代码改动（CP2 唯一改动点）

文件：`pokemon_agent/trace/store.py`，函数 `LocalTrace._scan_events`。
- 循环里先 `if not path.is_file(): continue`；
- `except Exception:` 改为 `except (ValidationError, UnicodeDecodeError):`，在文件顶部 `from pydantic import ValidationError`（trace 包已依赖 pydantic，不增加依赖）；
- docstring 里「残文件/旧格式文件解析失败是预期内的运行期情况，跳过不报错」补一句「读取失败（权限、IO）不属于此类，原样抛出」。

不改 `append`、不改 `_matches`、不改 `_meta_of`（它对 `meta` 的容错是另一回事，P6 已覆盖）。

## 五、停止条件

停下汇报、不自行决定：
1. 任何用例红了而原因不明显；
2. G8 在改动前**没有**变红（说明探针与实际不符）；
3. 收窄后全量里有别的测试因 `PermissionError` / `IsADirectoryError` 之类变红；
4. `tests/trace/local/` 默认 pytest 耗时 > 3 秒；
5. 需要改 `store.py` 之外的生产文件。

## 六、非目标

不测 Langfuse；不测 `TraceTool`；不测 T4（反向区间）；不测多进程并发写；不测磁盘满 / 原子写崩溃（`os.replace` 的行为属标准库）。
