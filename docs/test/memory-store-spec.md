# spec —— `tests/memory/store/`：`LocalMemoryStore` 的单元测试（含 O1–O3 修复）

> 依据：`docs/test/memory-test-intent.md` 第五、六节；源码 `pokemon_agent/memory/store.py`（683 行）。
> 检查点：CP1 修 O1（496）、CP2 修 O2（497）、CP3 修 O3（498）、CP4 注释 O5（499）、CP6 迁移与新建（501）。
> 探针依据（2026-10-17，沙箱实跑）：O1 同实例 touch 新增 0 次 embed、重启后 touch 新增 3 次；O2 第一次 `get` 返回 `({}, {}, '')`、第二次 `None`；O3 `search(limit=0)` 返回 0 条、`limit=-1` 返回 2 条（共 3 条）。

## 一、决定表

| 编号 | 决定 | 理由与代价 |
|---|---|---|
| D1 | 通过 `LocalMemoryStore` 公开方法测，不碰 `_inverted` / `_uuids` / `_vectors` | intent 第四节第 2 条；代价是有些内部行为只能经盘上文件与 embedder 计数间接观察 |
| D2 | 用 `tmp_path` 作根（显式 `root=`），缺省根用例才 `monkeypatch.chdir` | intent 第四节第 1 条 |
| D3 | 替身用 `CountingEmbedder`（计数）与 `OverlapReranker`，见 retrieval spec 第四节 | 同一套共用替身 |
| D4 | **O1 修复**：`_save_index` 写入 `hashes` 键；`_load_or_rebuild` 读取，缺键时视为空 dict | 旧索引无该键时首次 `refresh_changed` 会补算一次（可接受，只发生一次）；不做版本号 |
| D5 | **O2 修复**：`get` 在 `_read_record` 之前检查文件是否存在，缺失时摘索引并返回 `None` | 与接口契约"不存在返回 None"一致；`_read_record` 的缺失分支保留为防御（不被 `get` 之外的调用影响） |
| D6 | **O3 修复**：`search` 入口补 `assert limit > 0`，与 `ports.py` 第 94 行一致 | `recall` 带 query 时 episode 分支已由 `rank` 断言兜住，本修复只改 store 层 |
| D7 | **O4**：只改 `recall.py` 的 `_recall_knowledge` docstring，写明 `score` 恒为 `None`；测试断言 `score is None`（与改后注释一致） | 不改行为；见 capability spec |
| D8 | **O5**：把 `_corpus` 的属性文档字符串移到其赋值之后，删除游离字符串 | 纯注释位置 |
| D9 | 回归测试 CP1–CP3 放在 `tests/memory/test_store_regressions.py`，CP6 并入 `store/` | 避免 CP1 时新建目录 |

## 二、修复检查点（CP1–CP3）

**CP1（496）O1：hash 随索引持久化**
- 实现：`_save_index` 增加 `"hashes": {k: self._hashes[k] for k in sorted(self._hashes) if k in self._uuids}`；`_load_or_rebuild` 对账通过时 `self._hashes = dict(doc.get("hashes", {}))`；全量重建分支清空 `_hashes`，并在重建时对 md 类记录补算 hash。
- 回归用例（放 `test_store_regressions.py`）：
  - `test_refresh_changed_does_not_reembed_after_restart_when_content_unchanged`：写入 3 条 knowledge（md）→ 新实例（模拟重启）→ `os.utime` 改 mtime、内容不变 → `refresh_changed()` → embedder 新增计数 0。修复前应为 3（已探针确认）。
  - `test_refresh_changed_same_instance_touch_does_not_reembed`：同实例 touch → 计数 0（当前即为 0，作为控制组）。
  - `test_refresh_changed_reembeds_when_content_really_changes_after_restart`：重启后真改内容 → 计数 1。
- 破坏验证：还原 `_load_or_rebuild` 的 hashes 读取，第一个回归用例应失败。

**CP2（497）O2：get 缺失返回 None**
- 实现：`get` 先 `if not self._record_path(uuid).is_file(): self._unindex(uuid); return None`，之后才调 `_read_record`。
- 回归用例：`test_get_returns_none_when_record_file_removed_outside_index`：put → 外部删文件 → `get` 返回 `None`（修复前为 `({}, {}, '')`，探针已确认）；随后 `get` 仍为 `None`。

**CP3（498）O3：search 的 limit 断言**
- 实现：`search` 入口 `assert limit > 0, f"search() needs limit > 0, got {limit}"`。
- 回归用例：`test_search_rejects_non_positive_limit`：`limit=0` 与 `limit=-1` 均触发 `AssertionError`（修复前二者静默返回，探针已确认）；`limit=1` 正常。

## 三、用例清单（CP6 迁移与新建，目标约 25 条；每条一句话命名）

**构造与 kind**
1. `test_store_rejects_unknown_kind`：未知 kind 触发断言。
2. `test_store_creates_kind_directory_under_given_root`：显式 root 下生成 `<kind>/` 目录。
3. `test_store_default_root_is_memory_under_cwd`：缺省根用 `monkeypatch.chdir`，记录落在 `cwd/memory/<kind>`。

**put / get / get_many（json 与 md 两形态）**
4. `test_put_then_get_round_trips_json_record`：json kind 的 metadata、payload、text 原样返回。
5. `test_put_then_get_round_trips_markdown_record`：md kind（knowledge_memory）的 frontmatter 与正文原样返回。
6. `test_get_returns_none_for_unknown_uuid`：从未写入的 uuid → `None`。
7. `test_get_returns_none_when_record_file_removed_outside_index`：CP2 回归，迁入后保留。
8. `test_get_many_skips_unknown_uuids`：未知 uuid 不出现在结果中，已知的保持请求顺序。

**filter / delete / count**
9. `test_filter_with_empty_conditions_returns_every_uuid`。
10. `test_filter_intersects_every_condition`：两个条件的交集。
11. `test_filter_returns_empty_when_one_condition_has_no_bucket`。
12. `test_filter_matches_values_by_equality_only`：`"5"` 不匹配 `"6"`（不支持大小比较）。
13. `test_delete_many_removes_records_and_returns_count`：返回实际删除条数，未知 uuid 不计入。
14. `test_count_tracks_put_and_delete`。

**索引自愈**
15. `test_missing_index_file_is_rebuilt_from_record_files`：删 `index.json` 后新实例仍能 `filter` 到记录。
16. `test_hand_removed_record_is_reconciled_on_startup`：手工删记录文件后新实例 `count` 与 `filter` 反映删除。

**search / rank**
17. `test_search_rejects_non_positive_limit`：CP3 回归，迁入后保留。
18. `test_search_excludes_candidates_with_empty_text`：无 text 的记录搜不到。
19. `test_search_returns_empty_when_no_candidates`：`conditions` 无匹配 → `[]`。
20. `test_search_returns_at_most_limit_results`。
21. `test_rank_rejects_empty_query`；`test_rank_rejects_non_positive_fuse_top_k`。

**refresh_changed**
22. `test_refresh_changed_is_noop_for_json_kind`：json kind 调用不改变 embedder 计数。
23. `test_refresh_changed_reembeds_only_the_edited_markdown_record`：两条 md，只改一条内容 → 计数 +1。
24. `test_refresh_changed_does_not_reembed_after_restart_when_content_unchanged`：CP1 回归，迁入后保留。

**snapshot / restore（store 层）**
25. `test_snapshot_writes_zip_containing_the_kind_records`。
26. `test_restore_brings_back_records_written_before_snapshot`。

27. `test_snapshot_overwrites_a_previous_one_with_the_same_name`：同名 `store.snapshot` 覆盖，返回路径不变（原 159，改直调 store）。
28. `test_snapshot_name_may_not_contain_path_separators`：`store.snapshot("../x")` 触发断言（原 175）。
29. `test_restore_deletes_records_written_after_the_snapshot`：以 zip 为准，快照之后写的记录被删（原 201）。
30. `test_restore_leaves_the_snapshots_directory_alone`：`snapshots/` 不参与还原，拿来还原的 zip 与其他存档都保留（原 223）。
31. `test_search_returns_per_stage_timings`：`store.search` 第二个返回值的键为 bm25 / vector / rrf / rerank 的子集，值为非负浮点（原 275，改直调 store）。
32. `test_refresh_changed_skips_rewrites_with_identical_content`：内容未变、只 touch 时不重写记录文件（原 300）。
33. `test_bm25_corpus_persists_across_instances`：重启后语料仍可用，BM25 结果与重启前一致（原 349）。
34. `test_sidecar_auto_compacts_when_garbage_rows_dominate`：**待探针**（见下），原 418。

**向量 sidecar**
- **待探针确认后再定用例**（惰性加载、压实阈值）。执行方第一步对 `_load_vectors` / `_maybe_compact_vectors` 做一次探针，结果写回本节再写用例。不预先钉。

## 四、迁移清单（`tests/memory/test_memory_store.py`，实际 18 个）

逐条映射（旧函数行号按当前文件）。执行方逐条读原文核对；映射与原文不符 → 停，汇报。

| 旧用例（行号） | 去向 |
|---|---|
| `test_store_default_root_is_the_startup_directory`（86） | 用例 3 |
| `test_tool_defaults_put_each_family_under_the_shared_root`（104） | **CP7** capability 用例 26 |
| `test_explicit_memory_root_wins_over_the_default`（119） | **CP7** capability 用例 27；若执行方读原文后确认只经 LocalMemoryStore，则并入用例 2 |
| `test_store_explicit_root_wins_over_the_default`（127） | 用例 2 |
| `test_snapshot_zips_the_whole_root_and_excludes_itself`（139） | 用例 25（改为直调 `store.snapshot`，不经 MCP 信封） |
| `test_snapshot_overwrites_a_previous_one_with_the_same_name`（159） | 用例 27 |
| `test_snapshot_name_may_not_contain_path_separators`（175） | 用例 28 |
| `test_restore_makes_deleted_records_come_back`（185） | 用例 26 |
| `test_restore_deletes_records_written_after_the_snapshot`（201） | 用例 29 |
| `test_restore_leaves_the_snapshots_directory_alone`（223） | 用例 30 |
| `test_restore_refreshes_every_family_not_just_step_memory`（238） | **CP7** capability 用例 28 |
| `test_restore_rejects_unsafe_entries_before_touching_the_library`（258） | **CP7** capability 用例 23（已在 capability spec 中） |
| `test_knowledge_store_search_returns_per_stage_timings`（275） | 用例 31 |
| `test_refresh_changed_skips_rewrites_with_identical_content`（300） | 用例 32 |
| `test_refresh_changed_recomputes_when_content_actually_changes`（327） | 用例 23 |
| `test_bm25_corpus_persists_across_instances`（349） | 用例 33 |
| `test_embedding_rank_scores_with_numpy_matrix_include_zero_vectors`（393） | **删除**：纯函数零向量用例已由 CP5（504）`test_embedding_rank_scores_zero_vector_document_as_zero` 覆盖；删前执行方须确认函数体只调 `embedding_rank` |
| `test_sidecar_auto_compacts_when_garbage_rows_dominate`（418） | 用例 34，**待探针**：执行方先对 `_load_vectors` / `_maybe_compact_vectors` 做探针，结果写回本节，再定断言 |

落盘根的 `MemoryTool` 级用例（104、119）与快照恢复的能力层用例（238、258）随 CP7 迁出，CP6 不做。

CP6 完成后：`test_memory_store.py` 中剩余的 MCP 信封相关断言一律不迁、随 CP7 处理原文件的删除（见 capability spec 四节）。迁移前后用例名集合必须能对上：每个旧名字都有去向，新增名字都在第三节。

## 五、验证

- 默认 pytest：`tests/memory/store/` 与 `test_store_regressions.py` 全部通过，耗时计入 memory 目录 3 秒预算。
- 破坏验证：CP1、CP2、CP3 各做一次（见第二节），还原后生产目录 `git diff` 为空。
- 不调真实模型，不联网，不 sleep（`os.utime` 改 mtime）。

## 六、停止条件

- CP1 修复后，同实例 touch 的控制组用例（计数 0）失败 → 停，汇报（说明 mtime 基线逻辑有变化）。
- O1 修复后旧索引（无 `hashes` 键）加载失败 → 停，汇报。
- 任一回归用例在修复前不失败（即未复现）→ 停，汇报，不改用例迎合。
- 迁移时发现原用例断言了私有成员 → 停，汇报。

## 七、非目标

- 不测 `MemoryCapability`（capability spec）；不测检索排序（retrieval spec）；不测 MCP 传输；不修 `refresh_changed` 之外的 hash 逻辑。
