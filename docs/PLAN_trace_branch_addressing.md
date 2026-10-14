# PLAN_trace_branch_addressing —— trace 按 (run_id, branch) 寻址：一次执行尝试一个账本

> 状态：**S1+S2 已落实现（337：seed 纯函数 + 装配 + 6 条钉子测试，全量绿）——S3 实弹验收
> 待用户本机跑**（Langfuse UI 已清空，直接跑 door 即可）。核心改动 = `TraceTool.build`
> langfuse 分支的 seed 一行。本文是实施契约，S3 按 §八表格逐条过。

## 一、背景与问题

现状：langfuse 后端 `trace_id = create_trace_id(seed=run_id)`——**一个 run 的所有执行线**
（main + 每次 restore 新发的 b-xxx）全部追加进同一个 trace。335 首跑实锤三类问题：

1. **跨尝试污染**：同 run_id 重跑/续跑/调试，事件全部混流——同 checkpoint_id 的
   `checkpoint_save` 堆积（wild 实锤 4-5 条），lineage 的"恰好一条"不变量被打破。
2. **读账语义复杂且脆弱**：`TraceTool.read_events`（meta 无 branch 时）做血缘可见性拼接
   （本线 + 祖先分叉点前）；`RunStream.load` 建工具时 branch 缺省 main → 恢复线整个不可见
   → unjudgeable（door 首跑事故）。
3. **观测语义混乱**：UI 里一条 trace 混多次尝试，钻取与对账困难（用户被迫手工筛）。

## 二、定案（用户 0929）

- **trace_id = f(run_id, branch)**：一次执行尝试 = 一个 trace，互不混流。
- restore 时 branch 拿全新随机 uuid（现状不变，`b-xxxxxx` 每次 restore 新发）。
- **Langfuse 侧不再有"血缘"概念**：每条执行线账本独立，血缘拼接在该后端退化为直读。
- **local 后端不变**：trace_root 目录 = 账本（run-one 目录级隔离已有）；同账本内的真跑
  中途恢复仍走血缘（335 已宽容化：save 不在本账本 → warning + 按世界起点处理）。
- 用户自述：Langfuse 侧的筛选由用户自己在 UI 做，系统不提供跨 trace 聚合。

## 三、寻址规则

| 后端 | 账本寻址 | 隔离粒度 |
|---|---|---|
| local | `trace_root` 目录（run-one 级：`runs/<样本[#eN]>/trace/`） | 目录 = 账本；同账本血缘保留 |
| langfuse | `trace_id = create_trace_id(seed=f"{run_id}::{branch}")` | **trace = 一次执行尝试** |

- 同 `(run_id, branch)` 重入：事件追加进同一 trace（预期内；branch 是随机 uuid，实际不重入）。
- 不同 branch / 不同 epoch（run_id 带 `#eN`）/ 不同样本：各自独立 trace。

## 四、改动点

1. `direct/trace/__init__.py::TraceTool.build`（langfuse 分支）：
   `create_trace_id(seed=run_id)` → `create_trace_id(seed=f"{run_id}::{branch}")`。
   `branch` 已是 build 形参——**核心就这一行**。
2. `trace/langfuse_trace.py`：docstring 写明寻址规则与重入语义。
3. `build.py`：零改动（`branch` 已递给 `TraceTool.build`）。
4. evals 侧：零改动——`RunStream.load` 已是"空 meta 全量读 + 自筛 branch"，trace 隔离后
   全量读即该线全部；`run_one` 无种子（335 已撤）。
5. 血缘宽容（335 已落）：save 不在本账本 → warning + 世界起点——langfuse 拆分后该分支
   在 langfuse 读侧不再触发；local 同账本中途恢复仍走血缘。
6. 测试：`test_build` 增断言（seed 为 run_id 与 branch 的组合、非裸 run_id）；lineage 宽容
   已有覆盖；不新增 langfuse 集成测试（读侧由实弹验收，§六）。

## 五、语义变化与代价

- **恢复线在 langfuse 侧看不到父线分叉前历史**。兜底三层：
  ① 结构化记忆通道不受影响（`read_task_memory`/`read_episode_memory` 读的是**随存档恢复的
  记忆快照**，与 trace 血缘无关）；② local 同账本血缘仍在（真跑中途恢复主场景）；③ eval
  场景零影响（打包起点即世界起点）。
- **run 全貌不再 = 单 trace**：跨尝试聚合靠 `.eval` metadata（`run_id`/`branch`/`epoch`
  串联）；Langfuse UI 按 trace 名/id 前缀筛（用户自管）。
- 同 `(run_id, branch)` 重入事件追加（预期内）。
- 旧数据：用户已在 UI 全删，无迁移负担。

## 六、验收

1. door 样本 langfuse 重跑：trace_id 含 branch 段（≠ 旧值）；trace 内事件 branch 全 =
   新 b-xxx；scorer = C。
2. 同样本再跑一次：第三个独立 trace，互不混流；两次分数独立。
3. local 中途恢复（`check_checkpoint`）血缘测试仍绿。
4. 全量 + ruff。

## 七、不做

- langfuse 侧跨 trace 血缘拼接（eval 无需；真跑中途恢复由记忆通道兜底）。
- run 维度聚合视图（`.eval` metadata 串联足够；UI 筛选用户自理）。
- local 账本语义改动（同账本血缘保留，宽容化已够）。

## 八、实施计划（含测试验收）

### S1 核心改动（两文件）

| 文件 | 改动 | 验证 |
|---|---|---|
| `trace/langfuse_support.py` 或 `langfuse_trace.py` | 新增纯函数 `langfuse_trace_seed(run_id, branch) -> str`，返回 `f"{run_id}::{branch}"`——seed 公式收在单一处，可单测 | 纯函数单测 |
| `direct/trace/__init__.py::TraceTool.build`（langfuse 分支） | `create_trace_id(seed=run_id)` → `create_trace_id(seed=langfuse_trace_seed(run_id, branch))` | 步骤 2 单测 + 步骤 3 实弹 |
| `trace/langfuse_trace.py` | docstring 写明寻址规则与重入语义 | 阅读验收 |

验证命令：`ruff check pokemon_agent/` + 定向单测（S2）。

### S2 测试清单

新增 `tests/trace/langfuse/test_langfuse_seed.py`（纯函数，不联网）：

1. `test_seed_combines_run_id_and_branch`——`langfuse_trace_seed("r1", "b-aa") == "r1::b-aa"`
2. `test_seed_differs_across_branches`——同 run_id 不同 branch → seed 不同
3. `test_seed_stable_for_same_attempt`——同 (run_id, branch) → seed 相同（幂等）

修改 `tests/assembly/test_build.py`：

4. AST 断言扩展——langfuse 分支的 `create_trace_id` 调用必须 `seed=langfuse_trace_seed(run_id, branch)` 形状（防回退成裸 run_id）

回归：全量（`--basetemp` 全新）+ ruff；既有 lineage 宽容 / branch / checkpoint 测试必须全绿。

### S3 实弹验收（用户本机，Langfuse UI 已清空）

| # | 操作 | 通过判据 |
|---|---|---|
| 1 | `inspect eval evals\tasks\e2e.py -T samples='["knowledge_door_transition"]' --log-dir eval_results\inspect` | accuracy = 1.0；Langfuse UI 出现**新 trace**（id ≠ 旧），trace 内 branch 全 = 新 b-xxx，含 press_key×8 |
| 2 | 同命令**再跑一次** | 出现第二个独立 trace（id 不同）；两次分数独立，互不混流 |
| 3 | `inspect view --log-dir eval_results\inspect` | 钻取正常，metadata 的 run_id/branch 可对上 UI 的 trace |
| 4 | `-T trace_backend=local` 跑一次 | 仍 = C（local 路径零回归） |

### S4 回滚

单行 revert（seed 改回 `run_id`）即可；Langfuse 旧 trace 已清空，无兼容包袱。

### S5 风险

- 同 `(run_id, branch)` 重入混流：branch 为随机 uuid，实际不发生；若发生属 spec §五预期内语义。
- Langfuse UI 无 trace 名时按 id 搜：seed 可从 `.eval` metadata 的 `run_id` + `branch` 推出，可查可复现。
