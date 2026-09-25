# plan —— checkpointer 实施计划

> 流程位置：intent.md → spec.md → **plan.md** → PR → production
> 依据：`docs/checkpoint/spec.md`（09-25 定稿）｜ 起草：2026-09-25 ｜ 状态：**已定稿（09-25）**；测试写 P4、P7 两个；P0 核实记录单独成文 `docs/checkpoint/p0-findings.md`

---

## 〇、排序原则

1. **先重构、后加功能**：P1、P2 只挪代码、不改行为，验收标准是"现有核对全过、trace 逐条不变"。功能改动从 P3 开始。
2. **每步独立可验**：每步结束都能跑一遍现有核对（`pytest`、`tests/_fake_run.py` 驱动的 `test_node_io.py`、必要时真机 `check_harness`），不留"做到一半跑不起来"的中间态。
3. **每步 = 一条 CHANGELOG 编号条目 = 一个 commit**（AGENTS.md 三.6）；CHANGELOG 记 why，commit 标题逐字复用条目标题。
4. **测试另行征求同意**（ai-coding-paradigm 规则 8）：每步的"建议测试"只是提议，写不写由你定，见 §十。
5. **有破坏性的动作单独确认**：删除旧 trace 历史（P4）执行前再问一次。

## 一、步骤总览

| 步 | 内容 | 性质 | 依赖 |
|---|---|---|---|
| P0 | 真实代码上核实 spec §八 的三个遗留点 | ✅ 09-25，见 `p0-findings.md` | — |
| P1 | 装配方案 A：三张图在 `build.py` 编译，经 runtime 递给 `act` | ✅ 09-25，CHANGELOG 229 | — |
| P2 | 从两个 `act` 提出共用函数 | ✅ 09-25，CHANGELOG 230 | — |
| P3 | 接入 sqlite saver + `durability="sync"` | ✅ 09-25，CHANGELOG 231（真机一局待 P8 一并跑） | P1 |
| P4 | trace 加 `branch`：封套六件、按血缘读（登记表挪到 P7）；删除旧 trace 历史 | ✅ 09-25，CHANGELOG 232；**删旧历史待你确认** | — |
| P5 | 世界存 / 读模拟器状态 | ✅ 09-25，CHANGELOG 233 | — |
| P6 | `Checkpointer.save` + 清单 + 三个存档点 | ✅ 09-25，CHANGELOG 234 | P3、P4、P5 |
| P7 | `restore_run`：三级由内向外恢复、续跑段跳过存档 | ✅ 09-25，CHANGELOG 235；**命令行入口待定（eval V5）** | P2、P6 |
| P8 | 保真核对脚本 + 活文档同步 | 🟡 09-25，CHANGELOG 236：脚本与文档已写；**真机未跑、AGENTS.md 目录待你看** | P7 |

P1/P2/P4/P5 互不依赖，可按任意顺序做；建议按表序，每步落地后跑一次全量核对再进下一步。

---

## P0 真实代码核实（不改仓库）

在 `.workbuddy/scratch/` 写一次性探针，用 `tests/_fake_run.py` 的假大脑 / 假世界跑真实三张图：

| # | 核实什么 | 通过标准 | 不通过怎么办 |
|---|---|---|---|
| K-a | run 的 `dispatch`、episode 的 `act` 步骤 1，在"进 `act` 前"的同一份状态上重算，结果与当时一致 | 两次结果 JSON 相等 | 找出非确定来源（时间、随机、外部读）移出，或改为存档时把结果写进清单 |
| K-b | 续跑时不调 `begin_*` 就不会多出开局账；三个 `begin_*` 之外没有别的"进图前"副作用 | 续跑段 trace 中无第二条 `episode_start` / `task_start` | 把漏掉的副作用登记进 spec §6.2 |
| K-c | `TaskRuntime` 帧槽在 task begin 时是否会被该 task 读到上一个 task 留下的值 | 新 task 首键前帧槽被写入、从未读旧值 | P3 顺带把帧槽迁进 `TaskState`（spec §八） |
| K-d | 真实状态模型经 sqlite saver 往返无损，`allowed_msgpack_modules` 登记后无告警 | 往返后 `model_dump()` 相等；无 "unregistered type" 告警 | 调整登记范围 |
| K-e | 单局 saver 库增量（不迁帧槽 / 迁帧槽两种情况） | 量出数字，写进 P3 的 CHANGELOG | 超出预期时再讨论压缩或只存帧引用 |

**产出**：一段核实记录（贴进 P1 的 CHANGELOG "为什么"或单独一份 `docs/checkpoint/p0-findings.md`，由你定）。探针脚本不进仓库。

---

## P1 装配方案 A（重构，行为不变）

**改动**
- `build.py`：编译三张图（`compile_task_graph()` / `compile_episode_graph()` / `compile_run_graph()`）；
  `EpisodeRuntime` 加 `task_graph`，`RunRuntime` 加 `episode_graph`；`RunHarness` 改收编译好的 run 图。
- `harness/run/act/__init__.py`：删 `_episode_graph` / `episode_graph()`，改读 `runtime.context.episode_graph`。
- `harness/episode/act/__init__.py`：删 `_task_graph` / `task_graph()`，改读 `runtime.context.task_graph`；`__all__` 去掉 `task_graph`。
- `harness/run/harness.py`：`_compile()` 删除，图由构造函数传入。
- `tests/_fake_run.py`：造 runtime 的三处（247 / 257 / 268 行附近）同步加字段。

**验收**：`pytest` 全过；`test_node_io.py` 的正反例全过；fake run 前后两次的 trace 逐条相同（除 uuid / 时间戳）。

**CHANGELOG 要点**：模块级图缓存违反"禁止模块级单例、组装只在唯一装配点"，且 checkpointer 需要与运行时同一批图对象。

---

## P2 提取共用函数（重构，行为不变）

**改动**
- `harness/run/act/`：`_episode_error` → 公开 `settle_episode_error(deps, run_id, episode_input, exc, *, source)`，从出口导出；`act` 传 `source="run.act"`。
- `harness/episode/act/`：步骤 1 提成 `dispatch_task(state) -> {"tasks", "task_input"}`；`_task_error` → 公开 `settle_task_error(deps, task_input, exc, *, source)`；`act` 改调它们，`source="episode.act"`。
- `run.act.dispatch` 已是纯函数，不动。

**验收**：同 P1（trace 中 `source` 值与之前完全一致）。

---

## P3 接入 sqlite saver

**改动**
- `pyproject.toml` 加 `langgraph-checkpoint-sqlite`，更新 `uv.lock`。
- `build.py` 造 `SqliteSaver(checkpoints/langgraph.sqlite)`，登记 `allowed_msgpack_modules`，编译 run 图时传 `checkpointer=`。
- `run_entry._invoke` / `episode_entry.run_episode` / `task_entry.run_task` 三处 `invoke` 加 `durability="sync"`；run 的 config 加 `thread_id = f"{run_id}@main"`。
- ~~视 K-c 迁帧槽~~：P0 结论为不需要（`p0-findings.md` K-c）。
- 从三种状态模型递归生成 `allowed_msgpack_modules` 的 `(模块, 类名)` 列表（K-d）。
- 真机跑一局量 sqlite 增量，据此定 saver 文件位置与清理方式（K-e）。

**验收**：fake run 跑完后，sqlite 里同一 thread 下有三层命名空间的 checkpoint；run 的 `next == ("act",)` 那条可被查到；`pytest` 全过；真机 `check_harness` 跑一局通过。

---

## P4 trace 加 `branch`（trace 结构变更，S2 / S6 已确认）

**改动**
- trace 封套 `meta` 加 `branch`，由落盘层盖章：`TraceTool.build(run_id=…, branch=…)`；`build.py` 缺省 `branch="main"`。
- 分支登记表 `checkpoints/<run_id>/branches.json` 的读写（本步只实现读与 `main` 的隐式存在；写在 P7）。
- `read_events` 按登记表逐级上溯拼接（本步只有 `main`，行为等同于加一个 `branch` 过滤）。
- `experiment/real_check/node_io.py`：`META_KEYS` 加 `branch`；切流前按血缘拼接。
- `docs/spec/trace/` 与 `docs/spec/DATAFLOW.md` 的封套描述同步。
- **删除旧 trace 历史**（S6）：`tracelog/` 现有事件全部删除，不做缺省兼容。**执行前再与你确认一次。**

**验收**：新跑的每条事件恰好六个 `meta` 字段；`check_trace` 与 `node_io` 全过；读取遇到缺 `branch` 的事件抛错（而不是补缺省）。

---

## P5 世界存 / 读模拟器状态

**改动**
- `WorldPort` 加 `save_state() -> bytes` / `load_state(data: bytes) -> None`；`PyBoyWorld` 实现。
- `GameToolPort` 加 `save_state` / `load_state`；信封 `FromHarnessToGameToolSaveStateReq/Resp`、`FromHarnessToGameToolLoadStateReq`。
- 订正 `GameToolPort` docstring 中"world 层仍保留存档能力"的过时说法。
- `scripts/check_world_self_contained.py` 若登记了 Port 方法清单，同步。

**验收**：真机上 `load_state(save_state())` 后 `perceive_once(ram_only=True)` 与存之前逐字段相同；fake world 同样实现两个方法（铁律 4：mock 与真实实现同一 Protocol）。

---

## P6 存档

**改动**
- 新包 `harness/checkpoint/`：`checkpointer.py`（`Checkpointer.save`）、`manifest_io.py`、`errors.py`、出口 `__init__.py`。
- 清单模型 `schemas/harness/domain/checkpoint_manifest.py`（`CheckpointManifest`、`GraphRef`、`Lineage`、`CodeStamp`）。
- 三个 runtime 加 `checkpointer` 字段（同一实例）；三个存档点：`run_entry.new_run`（reset 之后）、`begin_episode` 末尾、`begin_task` 末尾。
- `TraceKind` 加 `checkpoint_save` / `checkpoint_error`；`node_io` 的 `CONTRACTS` / 后继表 / `KNOWN_SOURCES` 登记。
- `config.py` 加 `CHECKPOINT_ENABLED`（默认开）。

**验收**：fake run 与真机各跑一次，产出 1 个 run 级、每局 1 个 episode 级、每 task 1 个 task 级存档；每份清单满足 spec §5.1 不变式；每次存档一条 `checkpoint_save`；人为让世界存档失败时记 `checkpoint_error` 且 run 跑完。

---

## P7 恢复

**改动**
- `harness/checkpoint/restore.py`：`restore_run`（spec §6.2）——公共前置、三级续跑、替 episode / run 的 `act` 交差、一致性 assert。
- 分支登记表的写入；新分支 `b<n>`、新 thread `<run_id>@b<n>`。
- `Checkpointer` 的"正在续跑"标志；续跑段 `save()` 记 `checkpoint_skipped`。
- `TraceKind` 加 `checkpoint_restore` / `checkpoint_skipped`；`node_io` 登记新 source `checkpoint.restore`。
- 入口：`experiment/` 下一个命令行入口（如 `python -m experiment.restore <checkpoint_id>`），具体位置按你对测评模块的定位（eval V5）再定。

**验收**：fake run 上三级各恢复一次并跑完：新分支第一条事件是 `checkpoint_restore`；续跑段内的存档点只产生 `checkpoint_skipped`；拼接血缘后 `node_io` 全过；原分支 trace 文件一字节未变。

---

## P8 保真核对与文档

**改动**
- `experiment/real_check/check_checkpoint.py`：spec §九 五项。
- 活文档同步：`docs/spec/harness/SPEC.md`（runtime 字段、三个存档点、图在 build 编译）、`docs/spec/build/SPEC.md`、`docs/spec/world/SPEC.md`、
  `docs/spec/trace/SPEC.md` + `API.md`、`docs/spec/DATAFLOW.md`（事件总表）、`docs/spec/experiment/SPEC.md`、新增 `docs/spec/checkpoint/SPEC.md`；`docs/spec/README.md` 索引加一行。
- `AGENTS.md` 第四节目录结构加 `harness/checkpoint/`（改规范文字前先给你看）。

**验收**：真机跑 `check_checkpoint` 五项全过。

---

## 九、不在本 plan、需要你另行决定的

| 事项 | 说明 |
|---|---|
| ROADMAP H9 | 现写"E1 之后以 subagent 边界重做"，本计划已提前到三级 begin。ROADMAP 何时改由你定 |
| 测评数据集如何引用 checkpoint | 归 `docs/eval/`，等 eval 的 spec |

## 十、建议测试（写不写由你定）

按"测试是用法示范"：走公开出口、依赖经构造函数注入假实现、读者只看测试就会用。

| 步 | 建议的测试 | 示范什么 |
|---|---|---|
| P2 | `test_act_shared_helpers.py`：`dispatch_task` 纯函数性；`settle_*_error` 对 `AgentError` 兜底、对其他异常原样抛 | 两个共用函数怎么调、失败时抛什么 |
| P4 | `test_trace_branch.py`：两级分支的 `read_events` 拼接结果；缺 `branch` 的事件被拒 | 按分支读账的用法 |
| P6 | `test_checkpoint_save.py`：fake run 跑完，三级清单齐全且满足不变式 | `Checkpointer` 怎么装配、存下来长什么样 |
| P7 | `test_checkpoint_restore.py`：fake run 上三级各恢复一次，断言新分支首事件与原分支不变 | `restore_run` 怎么调、恢复后能看到什么 |

**代价**：每个约一两百行；P6 / P7 两个依赖 `tests/_fake_run.py` 的假世界实现 P5 的两个新方法。**价值**：P4、P7 的血缘拼接与交差逻辑最容易出隐蔽错，真机核对跑一次要几分钟，fake 测试秒级。
