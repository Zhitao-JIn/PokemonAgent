# plan —— trace 模块单元测试：检查点、编号与验收

> 依据：`docs/test/trace-test-intent.md`、`trace-local-spec.md`、`trace-contract-spec.md`、`trace-facade-spec.md`。
> 分支：`tests/trace-unit`，基线 `main`（2c95ab9，建分支时以 `git rev-parse main` 为准并写进交接）。
> 范围：不含 Langfuse（留到 trace 线最后阶段，另起 intent / spec / plan）。

## 一、角色

- 设计侧：写文档、派发、验收、提交（用户 2026-10-20 授权设计侧运行 git 写操作）。
- 执行方：只改允许文件、跑检查、写 CHANGELOG（用给定编号）、停下汇报。**不提交**。

## 二、检查点

| 序 | 编号 | 内容 | 依赖 |
|---|---|---|---|
| CP1 | 584 | 新建 `tests/trace/`（契约 14 + 序号 4 + 事件协议 3 + 包边界 3 + `local/` 29）与 `tests/_doubles/trace.py`；搬门面 7 条 + 新增对齐 1 条；删 `test_trace_store.py` | 无 |
| CP2 | 585 | T1：先补 G6–G8 三条（G8 必须先红），再改 `store.py::_scan_events` | CP1 |
| CP3 | 586 | T2/T3 文档：`store.py` 与 `datastore/event.py` 的 docstring、`append` docstring 补「不可序列化 content 抛 TypeError 且不落盘」、AGENTS.md 与 CLAUDE.md 第九节（字段数、排序键）两份逐字一致 | CP2 |

CHANGELOG 标题（实现提交逐字复用）：
- 584：`2026-10-21（584）—— trace 单元测试：LocalTrace、TracePort 契约、序号与包边界（CP1）`
- 585：`2026-10-21（585）—— trace 读盘只跳过预期内的残文件，不再吞掉 IO 错误（CP2）`
- 586：`2026-10-21（586）—— trace 文档对齐：八字段封套与 (ended_at, seq) 排序（CP3）`

## 三、允许改动的文件

**CP1**
- 新增：`tests/_doubles/trace.py`；`tests/trace/test_trace_port_contract.py`、`test_trace_append_sequence.py`、`test_trace_event_protocol.py`、`test_trace_package_boundary.py`；`tests/trace/local/test_local_trace_append.py`、`test_local_trace_read.py`、`test_local_trace_tolerance.py`（CP1 只写 G1–G5）、`test_local_trace_root.py`、`test_new_event_uuid.py`；`tests/direct/trace/test_trace_tool_contract.py`、`test_trace_event_alignment.py`
- 删除：`tests/trace/test_trace_store.py`
- 修改：`CHANGELOG.md`（顶部一条）
- 不得改动：`pokemon_agent/` 下任何文件（破坏验证还原后除外）、`tests/trace/langfuse/`、`tests/_fake_langfuse.py`、`tests/direct/trace/` 下已有文件、`scripts/`

**CP2**
- 修改：`tests/trace/local/test_local_trace_tolerance.py`（追加 G6–G8）、`pokemon_agent/trace/store.py`（仅 `_scan_events` 与 import）、`CHANGELOG.md`
- 其余同 CP1 的禁区

**CP3**
- 修改：`pokemon_agent/trace/store.py`、`pokemon_agent/trace/datastore/event.py` 的 docstring / 注释；`AGENTS.md`、`CLAUDE.md`（第九节，逐字一致）；`CHANGELOG.md`；`tests/trace/local/test_local_trace_append.py`（若 docstring 里还写着旧字段数）
- 只允许改注释与文档，**不允许改任何可执行语句**

## 四、验收

**通用**
1. `git diff --stat` 与未跟踪文件清单只涉及第三节允许的文件；`--ignore-cr-at-eol` 核对行尾未被整体改写（仓库以 LF 提交）。
2. 起点只做收集，不跑全量：记录 HEAD、`git status --short`、`python -m pytest --collect-only -q` 的总收集数 N0（含 deselected），以及 `python -m pytest tests/trace tests/direct/trace -q` 的结果（应全绿，有红则停下汇报）。全量默认 pytest 只在收尾跑一次：耗时 90 秒以上，必须放后台、写 JUnit，不前台等待；失败逐条列出，并到主目录（已检出 main，不含本分支改动；只复跑、不得修改其中任何跟踪文件）复跑同一文件，证明是已有失败。
3. `ruff check .` 与 `ruff format --check .` 全绿。
4. CHANGELOG 数字来自实测（用例数、junit 计数），不写估算值；四段固定格式。
5. 默认 pytest 下 `tests/trace/` 非 langfuse 部分耗时 ≤ 3 秒（`--durations=10` 前十行进汇报）。

**CP1 专项**
6. 收集数：`N1 == N0 + 45`（删 16、搬 7、增 1、`tests/trace` 新增 53）；全量的 `failures / errors` 与主目录复跑的结果一致，`skipped` 不增加。
7. 搬走的 7 条函数体与原文件逐行一致（给出 diff 证据）。
8. 破坏验证（临时改 `pokemon_agent/trace/` 内文件，逐处还原，最终 `git diff pokemon_agent/` 为空）：

| # | 临时破坏 | 应变红的用例 |
|---|---|---|
| X1 | `store.py` 排序键 `(ended_at, seq)` 改成 `(ended_at, uuid)` | 契约 #12、序号 #18 |
| X2 | `_matches` 里的 `all` 改成 `any` | 契约 #6、#7 |
| X3 | `append` 里 `json.dumps(..., ensure_ascii=False)` 去掉 `ensure_ascii=False`（content 那处） | `local/` #8 |
| X4 | `new_event_uuid` 版本位 `0x7` 改成 `0x4` | `local/` #2、#29 |
| X5 | `next_seq` 改成每次返回 `1` | 序号 #15、#17、#18 |
| X6 | 在 `trace/store.py` 里加一行 `from pokemon_agent.schemas import harness`（临时） | 包边界 #22 |
| X7 | `datastore/event.py::_Event` 里给 `_Event` 临时加一个字段 `extra_field: str = ""` | 事件协议 #19 |

**CP2 专项**
9. 动手前先只加 G6–G8，跑一次，汇报 G8 为红（其余 G6、G7 在旧代码上应为绿）；再改 `store.py`，全绿。
10. 收集数 `N2 == N1 + 3`；再做一次破坏验证：把 `except (ValidationError, UnicodeDecodeError)` 临时改回 `except Exception`，G8 应变红，还原。
11. 全量 pytest 与 N1 同口径：除 G8 之外没有任何用例因收窄而变红。

**CP3 专项**
12. `git diff` 中 `pokemon_agent/` 下的变更**只含注释与 docstring**（执行方给出 `ast` 前后对比：去掉 docstring 后两份 AST dump 相同）。
13. AGENTS.md 与 CLAUDE.md 第九节的差异为 0（除各自文件开头的镜像声明）。

## 五、派发前清单（设计侧）

1. `python .coordination/overlap.py`，确认 584–586 仍是预留且无新占用；
2. 台账「活跃任务」新增一行 `tests/trace-unit`，并把 584–586 的状态改为「已派发」；
3. 在本机建 worktree：`git worktree add .worktrees\trace-test -b tests/trace-unit main`；
4. 设计文档（intent / 三份 spec / plan）作为分支第一个提交，之后才发 CP1 交接；
5. 交接消息自包含，放在一个 ```text 代码块里，位于最后一条回复。

## 六、风险

- 契约夹具以后要加 Langfuse：`params` 增加一项即可，但 `LangfuseTrace` 的 `read_events` 是最终一致，契约 #14 之外的「写后立刻读」类用例到时候要加一个 `flush` 步骤——这一点留在 Langfuse 阶段的 intent 里讨论，本轮不预设。
- `tests/direct/trace/test_trace_seq.py` 与新文件 `test_trace_append_sequence.py` 在 local 半边有概念重叠，Langfuse 阶段合并时再决定留哪个。
- `scripts/check_trace_self_contained.py` 的 B 项已过时（见契约 spec 第三节），不在本轮处理。
