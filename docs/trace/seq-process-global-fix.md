# 修复 —— trace 的 `seq` 改为进程内全局单调

> 性质：缺陷修复（生产代码，trace 模块）。独立于"memory MCP 管理面"与"删除视觉感知档"，单独提交。
> 起草：2026-10-14
> 触发：`tests/test_trace_branch.py::test_a_restored_branch_sees_its_ancestors_up_to_each_fork` 间歇失败（`branch_graph` 两条边顺序为 b2,b1，应为 b1,b2）。2026-10-13 P0 时全绿，2026-10-14 在干净 `b268a68` 之前的实现下也复现过。

## 一、根因

`seq` 的设计意图是"进程内 append 的单调序号，同刻 `ended_at` 的决胜键"（`trace/interface/event.py`、CHANGELOG 0928 325）。但实现里它是**每个后端实例各自一份计数器**：

- `trace/store.py:131` `self._seq = 0`（本地后端，每个 `TraceTool.build(...)` 一个实例）；
- `trace/langfuse_trace.py:107` `self._seq = 0`（Langfuse 后端同理）。

同一进程里存在多个 `TraceTool` 实例时（每条执行线一个：`main`、`b1`、`b2`……，测试与真实恢复流程都是如此），各实例的 `seq` 都从 1 开始。排序键 `(ended_at, seq)` 在**不同实例的两条账**之间，`seq` 没有任何可比性。当它们的 `ended_at` 相同（时钟分辨率有限，Windows 上更粗）时，平局无法裁决，结果取决于读盘顺序，于是间歇失败。

`branch_graph` 的排序（`direct/trace/lineage.py:95`）和 `TraceTool.read_events` 的血缘拼接（`direct/trace/__init__.py:317、320`）都依赖这个键，所以受影响的不只是这一条测试：分叉点"及之前"的判断 `(e.ended_at, e.seq) <= (fork.ended_at, fork.seq)` 也可能在同刻时错判。

## 二、修复

让 `seq` 真正成为**进程内全局**单调序号：

1. 新增一个进程级计数器（模块级 `itertools.count(1)`，取号用 `next()`，在 CPython 下原子；如要显式，包一把 `threading.Lock`），放在两个后端都能 import 的地方（`pokemon_agent/trace/` 下的一个小模块，例如 `seq.py`，只暴露 `next_seq()`）。
2. `store.py`、`langfuse_trace.py` 两处把 `self._seq += 1; … self._seq` 换成 `next_seq()`，删除各自的 `_seq` 字段。
3. 更新 `trace/interface/event.py` 与 `trace_port.py` 里关于 `seq` 的说明：**进程内全局**，不是实例内；跨进程（不同进程写同一 run 目录）不保证，依赖 `ended_at` 区分，仍可能在同刻平局，这是已知的、可接受的边界。
4. 不改排序键 `(ended_at, seq)`，不改落盘格式（封套字段仍是 `seq: int`），不改 `branch_graph` / `lineage_of` / `read_events` 的逻辑。

## 三、测试

1. 现有的 `test_trace_branch.py` 失败项应转为稳定通过：连跑 30 次全过。
2. 新增回归测试（`tests/test_trace_seq.py`，本地）：创建两个 `TraceTool` 实例，**强制两条账 `ended_at` 相等**（传同一个 `ended_at`），交错 append；断言读出顺序等于真实 append 顺序，且 `seq` 严格递增、跨实例不重复。对本地后端与 Langfuse 后端的离线替身各测一遍（Langfuse 用现有测试里的 stub 方式，不联网）。
3. 全量 `python -m pytest`、`ruff check`、`ruff format --check` 全绿。

## 四、不做

- 不改 `tests/test_trace_branch.py`，不加 `sleep`。测试是对的，缺陷在实现。
- 不做跨进程的全局序号（需要共享存储，另案）。
- 不顺手整理 trace 其他代码。

## 五、提交

`修：trace 的 seq 改为进程内全局单调（修复分支图顺序间歇失败）`
同一提交里附 CHANGELOG 一条（写明根因与影响面）。

## 六、停止条件

- 修复后 `test_trace_branch` 连跑 30 次仍出现失败（说明还有别的不确定来源）。
- 任何现有测试因 `seq` 不再从 1 开始而失败，且无法归因为"断言了实例内的绝对值"。
- 需要改动落盘格式或排序键才能做成。
