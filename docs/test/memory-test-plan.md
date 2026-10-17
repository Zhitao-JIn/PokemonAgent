# plan —— memory 模块单元测试：检查点、编号与验收

> 依据：`docs/test/memory-test-intent.md`（已确认）。各目录 spec：`memory-retrieval-spec.md` / `memory-store-spec.md` / `memory-capability-spec.md` / `memory-providers-spec.md`。
> 分支：`tests/memory-unit`，基线 `5964222`（= main）。worktree：`.worktrees/memory-test`。

## 一、角色

- 设计侧：写文档、派发、验收、提交（分支上所有提交由设计侧做）。
- 执行方：只改允许文件、跑三项检查、写 CHANGELOG（用给定编号）、停下汇报。不提交。

## 二、检查点顺序（一个检查点 = 一次验收 = 一个提交）

| 序 | 编号 | 内容 | 依赖 |
|---|---|---|---|
| CP1 | 496 | O1 修复：`_hashes` 随 `index.json` 持久化 + 回归测试 | 无 |
| CP2 | 497 | O2 修复：`get` 文件缺失时返回 `None` + 回归测试 | 无（与 CP1 同文件 `store.py`，串行） |
| CP3 | 498 | O3 修复：`search` 入口 `assert limit > 0` + 回归测试 | CP2 之后（同文件） |
| CP4 | 499 | O4 + O5：只改注释（`recall.py` 的 knowledge score 说明、`store.py` 属性文档位置） | CP1–CP3 之后（`store.py` 串行） |
| CP5 | 500 | 共用替身 `tests/_doubles/memory.py` + `tests/memory/retrieval/`（按 retrieval spec） | CP4 |
| CP6 | 501 | `tests/memory/store/`（按 store spec）；从 `test_memory_store.py` 迁出 store 相关用例 | CP5 |
| CP7 | 502 | `tests/memory/capability/`（按 capability spec）；迁入 `mcpclient/memory_tool` 两个用例；删除 `tests/memory/test_memory_store.py` 与 `test_episode_summary_order.py` / `test_object_recall_content.py` 中已迁走部分 | CP6 |
| CP8 | 503 | `tests/memory/providers/`（按 providers spec） | CP5 |

编号说明：496–499 已在台账预留；500 起在派发时逐个登记（CP5 派发时登记为 500，依此类推）。

## 三、每个检查点的验收核对点（设计侧）

1. `git diff --stat` 只涉及允许文件清单；`--ignore-cr-at-eol` 核对行尾未被整体改写。
2. 生产代码改动（CP1–CP3）：读 diff；确认回归测试在**修复前**会失败（破坏验证：临时还原修复行，回归测试应失败，再还原，`git diff` 生产目录为空）。
3. CHANGELOG 条目与实际改动相符；数字（用例数、pytest 尾行）是实测值。
4. 全量 pytest、`ruff check .`、`ruff format --check .` 全绿。
5. memory 目录默认 pytest 耗时 ≤ 3 秒（CP5 起检查）。
6. 迁移检查点（CP6、CP7）：迁移前后用例名集合对得上（迁走的用例在新位置出现；新增是新覆盖）。

## 四、允许改动的文件（派发前用于核对交集）

- CP1：`pokemon_agent/memory/store.py`，新增 `tests/memory/test_store_regressions.py`（CP1–CP3 共用的回归文件，CP6 时并入 `tests/memory/store/`）、`CHANGELOG.md`。
- CP2：`pokemon_agent/memory/store.py`，`tests/memory/test_store_regressions.py`（追加用例）、`CHANGELOG.md`。
- CP3：`pokemon_agent/memory/store.py`，`tests/memory/test_store_regressions.py`（追加用例）、`CHANGELOG.md`。
- CP4：`pokemon_agent/memory/recall.py`（注释）、`pokemon_agent/memory/store.py`（注释位置）、`CHANGELOG.md`。
- CP5：`tests/_doubles/memory.py`（新）、`tests/memory/retrieval/*.py`（新）、`CHANGELOG.md`。
- CP6：`tests/memory/store/*.py`（新）、`tests/memory/test_memory_store.py`（删减）、`CHANGELOG.md`。
- CP7：`tests/memory/capability/*.py`（新）、`tests/memory/test_memory_store.py`（删除剩余）、`tests/mcpclient/memory_tool/test_episode_summary_order.py`（迁走后删除）、`tests/mcpclient/memory_tool/test_object_recall_content.py`（拆分）、`CHANGELOG.md`。
- CP8：`tests/memory/providers/*.py`（新）、`CHANGELOG.md`。

> 注：CP1–CP3 的回归测试都放在 `tests/memory/test_store_regressions.py` 一个文件里（CP6 时并入 `tests/memory/store/`）。文件名全仓唯一，执行方需先 `ls` 确认无重名。

## 五、回退

一个检查点一个提交。回退用 `git revert <提交>`，不 reset、不 rebase。CP1–CP3 的修复若被回退，对应回归测试同时回退。

## 六、耗时估计

CP1–CP4 约各 1 轮（修复 + 回归）；CP5–CP8 约各 1–2 轮。整体约 8–10 轮验收。真实模型：无（memory 测试零模型）。

## 七、PR 组织

整条分支一个 PR，按检查点顺序的提交保留历史。合入前核对基线之后主线是否动了同一批文件（`overlap.py`）。brain-scope CP1 的两个 memory 测试在它合入后单独成一条迁移检查点（不在本分支内）。

## 八、遗留（另案）

- brain-scope 的两个 memory 测试迁移与 run 族补全：等 brain-scope 合入。
- `hybrid_retrieve(fuse_top_k=0)` 的失败位置在 reranker 而非 `hybrid` 自身：文档缺口，记入遗留，不在本分支修。
- `recall(query, limit=0)` 经 episode 分支由 `rank` 断言兜住，而直接 `store.search` 静默：只修 store 层（CP3），不改 capability。
- `harness` 与 `evals` 里读写记忆的用例：另案，本分支不碰。
