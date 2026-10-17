# spec —— `tests/memory/capability/`：`MemoryCapability`（recall / memorize / snapshot / restore）的单元测试

> 依据：intent 第五、六节；源码 `pokemon_agent/memory/recall.py`（442 行）。
> 检查点：CP7（编号 502，派发时登记）。替身：`tests/_doubles/memory.py`。
> 探针依据（2026-10-17，沙箱实跑）：knowledge 判重 first=1、second=0；`recall` 的 knowledge 条目 score 为 `None`；`recall(query, {"episode_id": …}, limit=0)` 触发 `AssertionError: rank() needs fuse_top_k > 0`；`recall(query, {}, limit=0)` 同样触发 `AssertionError`（经 episode 分支的 rank，不是 knowledge 分支）；`memorize` 未知 kind 触发断言；episode 空 `episode_id` 触发 pydantic `ValidationError`（不是断言）。

## 一、决定表

| 编号 | 决定 | 理由与代价 |
|---|---|---|
| D1 | 只经 `MemoryCapability` 的公开方法测；五族 store 不直接访问 | 能力层是对外契约（`recall.py` docstring 写明） |
| D2 | `MemoryCapability(embedder, reranker, memory_root=tmp_path)` 作为唯一装配 | 与 `build.py` 同形，不 new 其他依赖 |
| D3 | 前置条件与 kind 校验用 `pytest.raises(AssertionError)`；schema 校验用 `pytest.raises(ValidationError)` | 区分"调用方违约（断言）"与"输入不合格（pydantic 异常）"，与 AGENTS.md 第四节一致 |
| D4 | O4 按行为改注释后，测试断言 knowledge 条目 `score is None` | 修的是文档，行为不变 |
| D5 | `recall(limit=0)` 的两个用例都钉成 `AssertionError`，并注明 knowledge 用例是经 episode 分支触发 | 这是**当前行为**，但它正是契约要求的断言行为（`rank` 的前置条件），不是缺陷，可以钉 |
| D6 | 不测 MCP 管理面（`--enable-admin`、归档大小、sha256、并发互斥） | intent 第三节 |

## 二、已知观察（不改，记遗留）

- **K1**：`recall(query, limit=0)` 对 knowledge 的 `limit` 检查来自 episode 分支的 `rank`，而不是 knowledge 分支自己。store 层修复（store spec CP3）后，knowledge 分支自身也会断言，两层都会 `AssertionError`。无需额外改动。

## 三、用例清单（每条一句话命名）

**memorize：各族落族与断言**
1. `test_memorize_act_stores_run_episode_step_and_map_metadata`：act 的 metadata 含 `run_id`、`episode_id`、`step`、`map_id`（用 `recall` 取回校验，不读盘）。
2. `test_memorize_act_accepts_equal_step_and_rejects_lower_step`：同 step 通过；更小 step 触发断言。
3. `test_memorize_task_stores_summary_as_searchable_text`：task 的 text = summary，可经 `recall(episode_id=…)` 取回 `content == summary`。
4. `test_memorize_episode_rejects_markdown_without_summary`：markdown 非空、summary 为空 → 断言。
5. `test_memorize_episode_rejects_summary_without_markdown`：反向 → 断言。
6. `test_memorize_episode_accepts_both_empty`：两者皆空（空章）→ 通过，`stored` 含该条。
7. `test_memorize_object_stores_place_key_and_map_metadata`：object 的 `place` 与 `map_id` 可经 `recall(place=…)` 命中。
8. `test_memorize_object_rejects_lower_step_within_same_episode`：object 的 step 单调。
9. `test_memorize_knowledge_skips_identical_topic_and_text`：第二次同 topic+text → `stored` 为空（探针已确认）。
10. `test_memorize_knowledge_keeps_same_topic_with_different_text`：同 topic 不同正文 → 两条都入库。
11. `test_memorize_rejects_unknown_kind`：`kind="bogus"` → 断言（探针已确认）。
12. `test_memorize_returns_stored_entries_with_kind_and_uuid`：`stored` 每条含 `kind` 与 `uuid`。

**recall：分族路由**
13. `test_recall_by_episode_id_returns_acts_in_step_order_then_tasks`：先 act（step 升序），后 task（total_acts 升序）。
14. `test_recall_by_episode_id_skips_payloads_that_fail_validation`：写入非法 act payload 不出现在结果中（需经 `memorize` 之外的途径写入时，改用合法 payload 的边界用例；否则本条移入 store 层）。
15. `test_recall_by_place_or_map_id_routes_to_object_family`。
16. `test_recall_by_run_id_returns_episode_summaries_in_natural_order`：`r1-ep2` 排在 `r1-ep10` 之前。
17. `test_recall_with_query_returns_knowledge_with_score_none`：D4，knowledge 条目 `score is None`。
18. `test_recall_with_no_hints_and_no_query_returns_empty`。
19. `test_recall_truncates_to_limit`：多族合并后截断到 `limit`。
20. `test_recall_with_episode_query_and_zero_limit_raises_assertion`：D5，探针已确认。
21. `test_recall_with_knowledge_query_and_zero_limit_raises_assertion`：D5，探针已确认，注释写明经 episode 分支。

**snapshot / restore**
22. `test_snapshot_then_restore_brings_back_memorized_records`：快照后删除（以覆盖式 restore 前的新写入为对照）→ restore → 可 recall。
23. `test_restore_rejects_archive_with_unsafe_entry_and_leaves_library_unchanged`：构造含 `..` 条目的 zip → `AssertionError`；之后 recall 结果与之前相同。
24. `test_restore_resets_step_monotonic_cache`：memorize step=5 → restore 到只含 step=0 的快照 → memorize step=1 通过（不被旧缓存拦住）。

**缺省根**
25. `test_root_property_reports_memory_under_cwd_by_default`：`monkeypatch.chdir` 后 `root == cwd/memory`。

## 四、迁移清单

- `tests/mcpclient/memory_tool/test_episode_summary_order.py` → 用例 16（改直调 `recall`），原文件删除。
- `tests/mcpclient/memory_tool/test_object_recall_content.py` → 拆：object 内容往返的 memory 侧断言迁入用例 7、15；"条目满足 MCP 端口模型"的断言**原地保留**，文件保留并删去已迁部分。
- `tests/memory/test_memory_store.py` 中能力层的用例（不安全条目整包拒绝、kind 分发、step 单调、knowledge 判重）→ 用例 9、11、23、24；随 CP6–CP7 删除原文件。
- `tests/mcp_servers/test_mcp_memory_e2e.py`：保留，不迁。

CP7 必须逐条写出迁移映射（旧用例名 → 新用例号 / 保留位置），写进 CHANGELOG 条目。

## 五、验证

- 默认 pytest：`tests/memory/capability/` 通过，耗时计入 memory 目录预算。
- 破坏验证：临时把 `_memorize_knowledge` 的判重去掉，用例 9 应失败；还原后 `git diff` 生产目录为空。
- 不调真实模型，不联网。

## 六、停止条件

- 用例 14 无法用公开接口构造非法 payload → 停，改为移入 store 层并汇报（不自行加私有访问）。
- 迁移时发现原用例断言了 MCP 信封 → 停，汇报。
- restore 相关用例在 Windows 路径下的 zip 条目行为与 Linux 不同 → 停，汇报。

## 七、非目标

- 不测 MCP 工具注册与 kind 过滤（`mcp_servers/`）；不测 harness 如何调用 recall/memorize；不测排序质量。
