# experiment —— 模块规格

> 最后更新：2026-09-25 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准
> 仓库根级包，**不在 `pokemon_agent/` 内**：它驱动 harness，不是被 harness 依赖的一层

## 一、职责与边界

- **只做两件事**：定义可重复的实验任务（`tasks.py`）、在**真实** PyBoy + 真实模型上核对链路
  （`real_check/`）。另有 `experiment_states/` 提供钉死的初始存档。
- **外壳不包装信封**：`harness.run(run_id=…, goals=[…])` 收裸字段、返回裸四元组
  `(outcomes, total, succeeded, rate)`——experiment 不是我们的模块，这条边不造 `*Req`。
- **不 import 被核对象的实现细节**：核对脚本读**产物**（tracelog / memory 目录）而不是
  去调内部函数；唯一例外是 `node_io` 的两条静态对照（节点清单、链路名），那是刻意的
  "对照真源"而非各抄一份。
- **不写进生产路径**：`real_check/` 的看门狗、faulthandler、临时目录都只在本包生效。

## 二、目录结构

```
experiment/
├── __init__.py          统一出口：__all__ = ["TaskChain", "knowledge_recall_tasks"]
├── tasks.py             任务定义 + goal/criteria 写法规范（docstring 九条推论 + 自查清单）
├── experiment_states/   钉死存档：knowledge/ 下 20 个 knowledge_*.state（一名一档）
└── real_check/          真实链路核对（独立进程，不用 pytest）
    ├── __init__.py      维度分工与用法说明
    ├── common.py        路径常量、产物读法、last-run 指针、load_env_file
    ├── node_io.py       逐节点输入输出核对（节点指纹 / 正文契约 / 步骤模板）
    ├── check_harness.py 维度 1：真驱动 PyBoy + 真实模型、逐节点核账
    ├── check_checkpoint.py 维度 3：三级存档与图内恢复的保真（也真驱动 PyBoy + 模型）
    ├── check_trace.py   维度 2：盘上事件封套与骨架
    ├── check_memory.py  维度 4：四族记忆落盘自洽
    └── check_memory_roundtrip.py  维度 6：MemoryTool 五条读写路径回环
```

## 三、五个核对维度

| 维度 | 脚本 | 核什么 | 前置 |
|---|---|---|---|
| 1 harness | `check_harness.py` | 静态形状 → 跑得完 → 逐节点账 → 每局一条 `episode_memory` | `.env` 里有 `DEEPSEEK_API_KEY` |
| 2 trace | `check_trace.py` | 每条事件**恰好**六个封套字段、盘上无残文件、骨架 kind 齐、有 `model_call` | 先跑维度 1 |
| 3 checkpoint | `check_checkpoint.py` | 自跑短 run（记每次 task 级存档的记忆 zip 大小与耗时）→ 三级存档各回档不开跑（世界字节 / 记忆 zip 哈希 / 图状态读回将派的正是清单上那一局、那个 task）→ 从某局第 2 个 task 的存档恢复跑到底（新线前三条账是恢复 → 存档 → 该 task 开局；原有 trace 不变）→ 仅凭 trace 画出的分支图与实际恢复一致、按血缘拼接 `node_io` 全过 → 改坏 `state_schema_hash`、删掉存档账各被拒且不写账 | `.env` 里有 `DEEPSEEK_API_KEY`；写独立工作目录 `checkpoint_check/<run_id>/`（`--work-root` 可改），启动目录的 `memory/` 先拷进去，**不动你的记忆库**；`--finish-all` 时 run 级、episode 级存档也各恢复跑到底 |
| 4 memory | `check_memory.py` | `step_memory` / `object_memory` / `episode_memory` / `knowledge_memory` 各族落盘 | 先跑维度 1 |
| 6 memory roundtrip | `check_memory_roundtrip.py` | `MemoryTool` 五条读写路径（episodic / object / 知识读 / 摘要写读 / 知识写+判重） | 无（自带临时目录） |

**维度 1 内部四件事，顺序是"从静态到动态、从大到小"**：① `_check_static_shape()`——跑之前
零成本核"格清单 ↔ 三张图"、"链路名 ↔ `tools/trace/render._CALL_LINK`"、"终止类别 ↔ `Termination`"；
② 整图跑到底并拿到 run 级四元组；③ `node_io` 的 `check_run_markers` + 五条判据（`check_vocabulary` /
`check_payloads` / `check_layer_flow` / `check_node_coverage` / `check_content_invariants`）+
`check_run_invariants`；④ `_check_one_record_per_episode`——每局**恰好**一条 `episode_memory`。

**`node_io.py` 的读法：按层切流**。三层的账交错落盘，按 `meta` 切成三种流——run 流
（`episode_id == run_id`）、episode 流（`task_id == episode_id`）、task 流（每个 task 一条）；
下层在上层流里缩成一个记号（`EPISODE` / `TASK`）。每条流用一张**后继表**核：每个活动后面只许跟
表里那几个，表就是那张图的拓扑。`model_call` / `error` 不进流（条数随重试浮动）。

**真实常量**（改图或改账必须同步这里，否则维度 1 当场炸）：

- `RUN_NODES` / `EPISODE_NODES` / `TASK_NODES`（三张图的格）；
  `CELL_SOURCES`（`层.格` → 格内发账单元）、`KNOWN_SOURCES`（三层单元 + 图外入口，即 `meta.source` 值域）。
- `META_KEYS = ("run_id", "branch", "source", "episode_id", "task_id", "step")`——封套 `meta` **恰好**这六件。
- `BOOLEAN_FIELDS` + `BOOLEAN_LOWER`——一份扁平名单，一套小写字面量；`TERMINATIONS`——五个终止类别。
- `MODEL_CALL_LINKS`（八条：`sense` / `choose` / `plan` / `decompose` / `judge` / `verify` /
  `summarize_episode` / `summarize_task`）与派生的 `MODEL_CALL_KINDS`（`<链路>_call`）。
- `CONTRACTS`（每种 `(type, kind)` 的正文必填键）、`_WRITE_BODY_KEYS`（四本写账）、
  `_WRITE_FORBIDDEN_KEYS`（封套六件 + `meta` 六件 + 四张帧 + 来源章）。
- 后继表：`RUN_NEXT` / `EPISODE_NEXT` / `TASK_NEXT` 与各自的结尾集合。
- 零痕迹豁免：`SILENT_NODES`（不写账的格，现为空）、`CONDITIONAL_NODES`（条件未触发，含只在下层抛错时
  发账的两层 `act`；按过键的 run 里
  `KEY_CHAIN_SOURCES` 必须齐）、异常收尾的局再豁免 `CLOSING_SOURCES` 与 task 层。
- 衔接：task 内键号逐键 +1、`choose_verdict` 首键 = 紧跟的按键；`task_end.steps_used` = 键数；
  `episode_end.tasks_used` / `acts_used` = 派出的 task 数 / 键数；派出的 task 必出自先前的拆解；
  `settle_goal` / `settle_task` 盖的是刚结束的那一局 / 那个 task，被放弃的只能是还没派的条目，正常收尾的局里
  每个派出的 task 恰好盖一次章；`run_end.total` = 派出局数；结算账不另记 `success` / `done`。
- **能证 / 不能证**：能证"格跑过、账的格式对、执行序与拓扑一致、层间计数一致"；**不能证格读到的
  state 值**。

**样本**：`tests/_fake_run.py` 用假大脑 / 假世界跑真的三张图，`tests/test_node_io.py` 拿它做正例
（正常 / task 失败后重拆 / task 抛错后这一局继续 / 整局抛错由 run.act 收尾）与逐处改动的反例。

## 四、命令行与开关

各脚本都从项目根用 `python -m` 跑：`experiment.real_check.check_harness` / `check_trace` /
`check_memory` / `check_memory_roundtrip` / `check_checkpoint`。**只有 `check_harness.py` 写供别的维度读的产物**
（`check_checkpoint` 的产物只在它自己的工作目录里）：

| 开关 | 语义 |
|---|---|
| `--goal TEXT` | 就地覆盖 `common.GOAL`（这一局的目标文字） |
| `--criteria TEXT` | 就地覆盖 `common.SUCCESS_CRITERIA` |
| `--max-tasks N` | 就地覆盖 `common.MAX_TASKS`（一局最多派几个 **task**，episode 层单位；0924 由 `--steps` 改名）；非整数 → `SystemExit`；`assert max_tasks > 0`（`Task` 的硬约束） |
| `--review` | 接 `WebReviewer`：问人走常驻后端 + 网页（先 `python -m pokemon_agent.review_backend`，再开 http://127.0.0.1:8765），并把看门狗放宽到 30 分钟；`--review-url ws://host:port` 换后端地址 |
| `--trace-root PATH` | trace 落盘根（缺省 = **启动目录**下的 `tracelog/`）；写方（`build_real(trace_root=…)`）与核对读法同源 |
| `--memory-root PATH` | 记忆库落盘根（缺省 = **启动目录**下的 `memory/`）。**四族共用一个根**——四族一视同仁，各自住它下面的 `<kind>/` |
| `--state PATH` | 覆盖钉死的初始存档 |

解析器是 `common.flag_value(flag)`（0916 从 check_harness 的 `_arg` 上收，一份实现
三家共用——check_trace / check_memory 也认 `--trace-root` / `--memory-root`，
读产物跟着写方走）：**只认"空格分隔"**这一种写法
（不引 `argparse`）；`--flag` 后面紧跟另一个以 `--` 开头的值 → 按"没给值"处理并打印
`[warn]`，**不静默吞掉**。都不传时行为与"从启动目录起跑"的缺省逐字一致。任务在
`[4/6]` 打印（目标 / 判据 / 预算各一行）。

产物根的缺省（0916 起）是 `Path.cwd()`——`common.TRACE_ROOT` / `common.MEMORY_ROOT`
在 import 时取启动目录，`load_events` / `read_memory_files` / `memory_dir` /
`write_last_run` / `read_last_run` / `resolve_run` 都收可选 root 参数，给了开关就
覆盖。**两个根各管一件事、各一个开关**：`--trace-root` 管 trace（含 run 指针），
`--memory-root` 管四族记忆（`memory_dir(kind, root)` / `read_memory_files(kind)` 内部
取它）。从仓库根起跑时与旧行为逐字一致。

`check_harness.py` 的三个模块常量：`MODEL = "deepseek-flash"`（**一个常量管全部五个位置**，
厂商类由前缀表选）、`WATCH = False`、`SPEED = 10`。装配调用是
`build_real(ROM, STATE, vision_model=MODEL, …, run_id=run_id,
reviewer=FileReviewer() if _REVIEW_MODE else None,
watch=WATCH, speed=SPEED)`。

- **184 起 plan 每次真调 brain**（`planner` 族撤销，`build_real` 不再有 `planner` 参数）：
  run **不再确定性地在第一局收尾**——模型加不加目标、喊不喊停，按它的回话走。
- **"开读口、关决策"的跑法暂缺**（原 `NullPlanner` 独力承担，已随之撤销）：
  要恢复，给 tool 层的 PlanPort 加一个空实现（能力对象化的下一步）。
- 判据写法守 `common.py` 那条口径：**只写"画面出现什么"，不许出现 step / 步数用尽**——
  预算用尽是机械事实，由 `judge` 自己判，写进判据会让它经 `verdict.done` 记成 `success`。

`check_memory_roundtrip.py` 不依赖任何产物：它在 `.memcheck/<eid>/`（点开头的
临时目录，跑完删）下造临时 `memory/` 根（`MemoryTool.build(memory_root=mem_root)`，
四族各占其下 `<kind>/`），从仓库知识库拷**前 3 份**手工先验进 `knowledge_memory/`，
跑完 `shutil.rmtree`。共七条路径（含快照 zip 往返：`snapshot_memory` → 覆盖
`restore_memory`）。

## 五、超时与看门狗

三套机制叠在一起，数值都在代码里：

| 机制 | 数值 | 位置 |
|---|---|---|
| faulthandler 卡死栈打印 | `timeout=240`、`repeat=True`（每 4 分钟例行打印，健康跑完有 1–2 次噪音） | `check_harness.py` 模块级 |
| 强退看门狗 `_arm_kill_switch` | `12` 分钟；`--review` 模式 `30` 分钟；触发即 `os._exit(70)` 并打印标记 | `check_harness.py`，`threading.Thread(daemon=True)` |
| 文件信箱每次提问的等待 | `file_reviewer.DEFAULT_TIMEOUT = 300.0` 秒 | `harness/file_reviewer.py` |

看门狗的理由（写在它的 docstring 里）：providers 层封住了**单次请求**的总时长，但多层重试相乘的
最坏时长仍可能超过现场的耐心——它保证"任何情况下进程都会终结"，且日志里留明确标记。
`--review` 放宽到 30 分钟，是因为人答得慢时一局的墙钟会被拉长（每问最多等 `WEB_REVIEW_TIMEOUT`）。

## 六、存档与状态

- `experiment/experiment_states/` 下**只有一个 `knowledge/` 子目录**，里面是 **20 个**
  `knowledge_*.state` 文件（`ls` 实测 20 个，无其它文件）。
- 这 20 个档正是 `tasks.py::knowledge_recall_tasks()` 里 `available_state_tasks` 的那 20 个 id——
  每个 `Task` 的 `task_id` 是 `f"knowledge_{name}"`，只有名字在 `available_state_tasks` 里的
  `cases` 才会成任务。`cases` 有 23 条，被筛掉的 3 条是 `choice_confirm` / `menu_open` /
  `catch_confirm_success`（没有对应存档）。
- `TaskChain`（`pydantic.BaseModel`）：`chain_id` / `tasks: list[Task]`（`min_length=1`）/
  `initial_state_hint=""`，属性 `initial_task`。`knowledge_recall_tasks(max_steps=15)` 先建 3 条多任务链
  （`knowledge_encounter_and_battle` / `knowledge_shop_purchase_flow` / `knowledge_pokemon_center_flow`），
  再把每个单任务补成一条单节点链，一起返回。
- `max_steps` 现在数的是**键**（一次小 action）：同一个 15 现在意味着"最多按 15 个键"。

## 七、当前状态与已知缺口

- **`experiment_states/knowledge/` 是唯一的存档族**：仓库里没有别的钉死存档目录。
  测评数据集 `evals/e2e/dataset/v1/` 从这 20 条任务冻结而来（`.state` 拷进 `states/` 并记 sha256，目标 / 判据抄进
  `samples.jsonl`）：此后改 `tasks.py` 或这里的存档**不影响**测评样本，要同步须出新版本数据集（见 `docs/spec/evals/SPEC.md`）。
- **`catch_weaken_target` 的判据已改为读 `foe_hp` 当前值**（0925，CHANGELOG 255）：战斗双方 HP 由 RAM 给，
  `foe_hp` 写成 `"当前/上限"`。
- **判据里锚绝对坐标的前提是"该`.state` 钉死"**（`tasks.py` 第 7 条推论，以 `movement_obstacle` 为例）。
- **核对脚本数崩溃靠"一个文件一个进程"**：拆成独立进程是为了隔离"接真实依赖才现形的硬崩溃"，
  pytest 单进程跑会把崩溃点糊在一起。
- **`real_check/__init__.py` 与 `common.py` 都提到 console 装配**（`CONTROL_SETUP_HINT` 里那段
  `ConsoleReviewer` 的写法），类真实存在于 `harness/`，照抄可用。

### 发现的不一致

- **维度编号缺 5**（1 / 2 / 3 / 4 / 6）：5 是早年的 restore 维度，随旧存档链删除（CHANGELOG 57），
  现在的恢复核对并在维度 3 里。
- **`experiment/__init__.py` 说 `real_check/` 是"六个维度的真实链路核对脚本"**：
  现存脚本只有四个（见上表），第六个（`check_memory_roundtrip`）之外的两格已删。
