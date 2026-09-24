# build —— 装配规格

> 最后更新：2026-09-24 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准
> 覆盖 `pokemon_agent/build.py`、`pokemon_agent/config.py`、`pokemon_agent/errors.py`

## 一、职责与边界

- **`build.py` 是全项目唯一 new 具体实现的地方**（AGENTS.md 三·3"组装只发生在一个地方"）。
  它只做一件事：造 `TaskRuntime` → `EpisodeRuntime` → `RunRuntime`（逐层嵌套），再用它们造 `RunHarness`。
- **对四个独立模块零 import**：本文件顶部只 import `pokemon_agent.harness` / `harness.null_reviewer` /
  `pokemon_agent.tools`——`brain` / `world` / `memory` / `trace` 的实现类一个都不出现，要什么全经工具层工厂拿。
- **只递裸字段**：型号名、ROM / 存档路径、`run_id`——不传 `*Config` 对象、不传 provider 实例；
  **不装图、不跑 run**（节点表与边住 `harness/run/run_graph.py` / `harness/episode/episode_graph.py`，
  开局编排住 `harness/run/run_entry.py::new_run`）。
- **`config.py`**：全项目唯一的**策略常量**集中地，分四组（重试预算 / 动作输出上限 / 循环控制 / 召回与判定）。
  判据——"改这个数是为了做实验（来 config）还是为了让代码正确（留各模块）"；它明确**不读环境变量**。
- **`errors.py`**：跨模块的共同祖先与升级态，只两个类；模块自己的词汇各回各家（见第四节）。

## 二、装配出的对象与来源

`build_real(...)` 返回 `tuple[RunHarness, GameTools]`。内部逐个：

| 对象 | 类型（协议） | 唯一来源 | 装配点递的裸字段 |
|---|---|---|---|
| `game` | `GameTools`（`GameToolPort`） | `GameTools.build(rom, state_path=…, watch=…, vision_model=…, speed=…)` | ROM 路径、存档、两个旋钮、感知型号名 |
| `trace_tool` | `TraceTool`（`TraceToolPort`） | `TraceTool.build(run_id=…, trace_root=…)` | `run_id`、`trace_root` |
| `memory` | `MemoryTool`（`MemoryToolPort`） | `MemoryTool.build(memory_root=…, max_summaries=…)` | 一个记忆根（四族一视同仁地住在它下面各自的 `<kind>/`） |
| `run_brain` / `episode_brain` / `task_brain` | `BrainTool`（容器） | `BrainTool.build(...)` **按需各造一份**：run 只传 `plan=`，episode 传 `text/judge/verify=`，task 只传 `text=` | 各自的型号名 + 输出上限 |
| —— | 八个能力对象（`Planner`/`Decomposer`/`Chooser`/`Judger`/`Reflector`/`Verifier`/`Summarizer`/`TaskSummarizer`） | 由容器组装、按层分发（`run_brain.planner·judger` / `episode_brain.decomposer·judger·verifier·summarizer` / `task_brain.chooser·judger·reflector·verifier·task_summarizer`） | —— |
| `reviewer` | `Reviewer`（Protocol） | 参数；不传 → `NullReviewer()` | 一个策略对象 |
| `task_rt` | `TaskRuntime` | 直接构造（task 层 context） | `game` / `memory` / `trace` + task_brain 的 `chooser`·`judger`·`reflector`·`verifier`·`task_summarizer` |
| `episode_rt` | `EpisodeRuntime` | 直接构造（episode 侧 context，嵌套 `task_rt`） | `game` / `memory` / episode_brain 的 `decomposer`·`judger`·`verifier`·`summarizer` / `trace` / `reviewer` + `task=task_rt` |
| `run_rt` | `RunRuntime` | 直接构造（run 侧 context，嵌套 `episode_rt`） | `trace` / `memory` / `reviewer`（同一实例）/ run_brain 的 `planner`·`judger` |
| `run_harness` | `RunHarness` | `RunHarness(run_rt)` | —— |

- **`reviewer` 缺省 `NullReviewer`（没人插话）**；plan 位置的规划来源就是 brain
  （185 起注入的 `planner` 能力对象），没有独立的 planner 装配。
- **`reviewer` 必须是同一份策略对象**（`plan` 插话与 `review` 审两处读）；**`world` 与事件流都不在返回值里**
  （world 归 `GameTools` 持有，账一律经 `deps.trace` 读写）。

`build_real` 的参数（缺省值即工厂缺省）：`rom`、`state_file=None`、`vision_model="qwen3.8-max"`、
`text_model="qwen-plus"`、`judge_model="qwen3.8-max"`、`verify_model="doubao-seed-2-1-pro-260628"`、
`plan_model="doubao-seed-2-1-pro-260628"`、`max_tokens=25600`、`watch=False`、`speed=0`、
`run_id="local"`、`trace_root=None`、`memory_root=None`（两个落盘根：缺省 = **进程启动目录**
下的 `tracelog/` 与 `memory/`，0916 起——数据跟着启动走，不再锚在仓库根；
memory 只有一个根，四族各占其下 `<kind>/`）、
`reviewer=None`。

**tool 层的接线工厂共五个**：`BrainTool.build` / `GameTools.build` / `MemoryTool.build` /
`TraceTool.build`（四个 classmethod）+ `vision_factory.build_vision_provider(model, temperature=0.0)`
（函数，由 `GameTools.build` 内部调）。另有一个不在 tool 层的
`brain/build_llm_providers.py::build_llm_providers(config)`（由 `BrainTool.build()` 内部调）；`build.py` 一个都不越过。

- **厂商由型号名前缀决定**：`brain/providers.py::provider_for()` 查 `_PROVIDER_PREFIXES`
  （顺序即优先级）：`deepseek` → `DeepSeekProvider`、`doubao` → `ArkProvider`、`qwen` → `QwenProvider`。
  前缀不认识 → **装配期** `ValueError`，不拖到第一次调用才 404。
- **温度分层**（`brain/build_llm_providers.py` 的常量，不是旋钮）：`DECIDE_TEMPERATURE = 0.3`
  （决策链）、`DETERMINISTIC_TEMPERATURE = 0.0`（judge / verify / plan）；感知链温度恒 0。
- **两个旋钮互相独立**：`watch` 管开不开 SDL 窗口，`speed` 管倍率（`0` 不限速、`1` 真实速度）。

## 三、环境变量

密钥由 provider 的类属性 `API_KEY_ENVS` 声明，`provider_for()` 造实例时从 `os.environ` 现读
（**首个有值的生效**；一个都没有 → `RuntimeError`，炸在装配期）：

| 环境变量名 | 声明处 | 用途 |
|---|---|---|
| `DASHSCOPE_API_KEY` | `QwenProvider.API_KEY_ENVS` | DashScope（语言 + 视觉两用那家） |
| `ANTHROPIC_AUTH_TOKEN` | `QwenProvider.API_KEY_ENVS` | 同上，第 2 顺位备选 |
| `ARK_API_KEY` | `ArkProvider.API_KEY_ENVS` | 火山方舟（`doubao*` 型号名） |
| `DEEPSEEK_API_KEY` | `DeepSeekProvider.API_KEY_ENVS` | DeepSeek 官方 API |
| `VISION_DUMP_DIR` | `brain/providers.py::_DUMP_DIR` | 多模态请求图的 dump 目录（调试用），空 = 关 |

**`.env` 的注入只发生在核对脚本侧**：`experiment/real_check/common.py::load_env_file()` 在模块
**import 时**执行一次，`setdefault` 语义（外部环境已有的同名变量优先；空值行 / 注释行 /
`export ` 前缀 / 解析不了的行一律跳过；`.env` 不存在则静默返回）。`build.py` **自己不读 `.env`**
——它要求调用方的环境里已经有密钥，缺了在装配期就炸。

## 四、异常族

`errors.py` 一共两个类，`__all__ = ["AgentError", "MaxRetriesExceeded"]`：

| 类 | 语义 | 谁抛 / 谁接 |
|---|---|---|
| `AgentError(Exception)` | 本项目**预期内失败**的基类；捕获它 = "我知道这里会出问题" | —— |
| `MaxRetriesExceeded(AgentError)` | 连续重试仍拿不到可用结果的**升级态** | 抛：`BrainTool._attempt_loop` / `GameTools.perceive_with_retry`；接：harness 的调用点（run / episode 的 `act` 只兜 `AgentError`） |

`MaxRetriesExceeded.__init__(attempts, last_reason, calls=(), source="")` 四个字段：`attempts`（试了几次）、
`last_reason`（最后一次为什么失败）、`calls: list[ModelCall]`（整条失败账，tool 层那份 `ModelCall`，可空）、
`source`（哪条链路耗尽：`"choose"` / `"plan"` / `"decompose"` / `"judge"` / `"verify"` / `"summarize_episode"` / `"summarize_task"` / `"sense"`）。

**模块自己的词汇不住这里**：`brain/errors.py` 自成一根 `BrainError`、`world/errors.py` 自成一根
`WorldError`——它们的异常在 tool 层的桥上就被翻译成 `MaxRetriesExceeded`，
跨不过两层 `act` 的捕获点。

## 五、当前状态与已知缺口

- `config.py` 的全部常量：重试预算 `BRAIN_MAX_ATTEMPTS=3`、`PERCEPTION_MAX_RETRIES=3`、
  `MODEL_RETRY_BACKOFF_SECONDS=0.5`、`CONSOLE_REVIEW_TIMEOUT=30.0`；输出上限 `MAX_SEGMENTS=4`、`MAX_TIMES=8`；
  三层停判 `STALL_LIMIT=5`（task）、`EPISODE_STALL_LIMIT=3`、`RUN_STALL_LIMIT=3`、`RUN_MAX_EPISODES=50`；
  规划 `EPISODE_MAX_TASKS_PER_PLAN=5`、`PLAN_MAX_NEW_GOALS=3`；图闸门 `NODES_PER_DECISION=3`、`NODES_PER_PRESS=1`、
  `RECURSION_MARGIN=20`、`EPISODE_RECURSION_LIMIT=20_000`、`RUN_RECURSION_LIMIT=200_000`；召回与判定
  `MEMORY_RECALL_LIMIT=5`、`JUDGE_HISTORY_STEPS=3`。
- 存档链已删：图上没有存档格，`build_real` 也**没有**存档 / 恢复参数。模块私有物理量故意不在 config：`pyboy_world.PRESS_FRAMES`、
  `providers.IMAGE_TOKEN_FLOOR = 100`、`memory/store.py` 的 `_KINDS` / `_MD_KINDS`。

### 发现的不一致

- **AGENTS.md 六写"这三个工厂同形，都在 tool 层"**：代码里 tool 层实际有**五个** `build*`
  （四个 classmethod + `build_vision_provider`），而 `build_llm_providers` 在 `brain/` 不在 tool 层。
