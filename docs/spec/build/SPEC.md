# build —— 装配规格

> 最后更新：2026-10-21（配置系统改造，CHANGELOG 567–573）｜ 活文档：跟随代码更新，与代码冲突时以代码为准
> 覆盖 `pokemon_agent/build.py`、`pokemon_agent/settings/`、`pokemon_agent/errors.py`

## 一、职责与边界

- **`build.py` 是全项目唯一 new 具体实现的地方**（AGENTS.md 三·3"组装只发生在一个地方"）。
  它只做一件事：造 `TaskRuntime` → `EpisodeRuntime` → `RunRuntime`（逐层嵌套），再用它们造 `RunHarness`。
- **对四个独立模块零 import**：本文件顶部只 import `pokemon_agent.harness` / `harness.null_reviewer` /
  `pokemon_agent.tools`——`brain` / `world` / `memory` / `trace` 的实现类一个都不出现，要什么全经工具层工厂拿。
- **只收配置路径**：`build_real(config=None)` 的唯一形参是配置文件路径（一个或多个覆盖层）；型号、地址、`run_id`、目录等一切取值都来自 `AppConfig`，装配点只把配置节里的字段递给 tool 层工厂，不传 provider 实例；
  **不装图、不跑 run**（节点表与边住 `harness/run/run_graph.py` / `harness/episode/episode_graph.py`，
  开局编排住 `harness/run/run_entry.py::new_run`）。
- **`settings/`**：全项目唯一的配置中心（取代旧 `config.py` / `run_config.py` / `run_budget.py`）。`default.json`
  是随包保底值，启动时可叠任意多个覆盖 JSON（深合并：dict 递归、list/标量整体替换），`load_config(overlays)` 返回
  `ResolvedConfig`（冻结的严格 `AppConfig` + 来源列表 + 合并后 JSON + sha256）。每次 run 把合并结果写成
  `paths.config_snapshot` 下的 `<run_id>-<sha8>.json`。判据不变——"改这个数是为了做实验（进 settings）还是为了让代码
  正确（留各模块）"。密钥与 `LANGFUSE_*` 只在 `.env`，不进 JSON。
- **`errors.py`**：跨模块的共同祖先与升级态，只两个类；模块自己的词汇各回各家（见第四节）。

## 二、装配出的对象与来源

`build_real(config)` 返回 `tuple[RunHarness, WorldMcpTool]`。内部先 `load_config` 并落快照，再逐个：

| 对象 | 类型（协议） | 唯一来源 | 装配点递的裸字段 |
|---|---|---|---|
| `game` | `WorldMcpTool`（`GameToolPort`） | `WorldMcpTool.build(world_server_url=…)` | `services.world_server_url`；缺地址在 memory 检查前抛 McpTransportError，有地址先检查 /health |
| `trace_tool` | `TraceTool`（`TraceToolPort`） | `TraceTool.build(run_id=…, trace_root=…)` | `run_id`、`trace_root` |
| `memory` | `MemoryTool`（`MemoryToolPort`） | `MemoryTool.build(memory_server_url=…, memory_root=…)` | 只经 MCP；缺地址在装配期抛 `McpTransportError`；`memory_root` 仅作客户端快照根 |
| `run_brain` / `episode_brain` / `task_brain` | `BrainTool`（容器） | `BrainTool.build(...)` **按需各造一份**：run 只传 `plan=`，episode 传 `text/judge/verify=`，task 只传 `text=` | 各自的型号名 + 输出上限 |
| —— | 八个能力对象（`Planner`/`Decomposer`/`Chooser`/`Judger`/`Reflector`/`Verifier`/`Summarizer`/`TaskSummarizer`） | 由容器组装、按层分发（`run_brain.planner·judger` / `episode_brain.decomposer·judger·verifier·summarizer` / `task_brain.chooser·judger·reflector·verifier·task_summarizer`） | —— |
| `reviewer` | `Reviewer`（Protocol） | `ReviewerTool.build(review, flush=…)`；`review.mode=off` → `NullReviewer()` | `review` 配置节 + trace 的 `flush` |
| `saver` | `SqliteSaver`（LangGraph） | `harness.checkpoint.build_saver(checkpoint_root)`：库文件 `<checkpoint_root>/langgraph.sqlite`，反序列化白名单由三种状态模型递归生成 | `paths.checkpoint`（相对 `paths.runs_root`） |
| `checkpointer` | `Checkpointer` | `harness.checkpoint.Checkpointer(root, run_graph, game, memory, trace, branch, models)`；`checkpoint.enabled` 关时为 None；三层 runtime 的 `checkpointer` 字段是**同一实例** | `run.branch`（默认 `main`） |
| 三张图 | `CompiledStateGraph` | `compile_task_graph()` / `compile_episode_graph()` / `compile_run_graph(checkpointer=saver)`，**只在这里编译**；只有 run 图挂 saver，内层两张图的状态经嵌套命名空间写进同一个库 | —— |
| `task_rt` | `TaskRuntime` | 直接构造（task 层 context） | `game` / `memory` / `trace` + task_brain 的 `chooser`·`judger`·`reflector`·`verifier`·`task_summarizer` |
| `episode_rt` | `EpisodeRuntime` | 直接构造（episode 侧 context，嵌套 `task_rt`） | `game` / `memory` / episode_brain 的 `decomposer`·`judger`·`verifier`·`summarizer` / `trace` / `reviewer` + `task_graph`（task 图）+ `task=task_rt` |
| `run_rt` | `RunRuntime` | 直接构造（run 侧 context，嵌套 `episode_rt`） | `trace` / `memory` / `reviewer`（同一实例）/ run_brain 的 `planner`·`judger` + `episode_graph`（episode 图）+ `episode=episode_rt` |
| `run_harness` | `RunHarness` | `RunHarness(run_rt, run_graph)` | —— |

- **`review.mode` 缺省 `off` → `NullReviewer`（没人插话）**；plan 位置的规划来源就是 brain
  （185 起注入的 `planner` 能力对象），没有独立的 planner 装配。
- **`reviewer` 必须是同一份策略对象**（`plan` 插话与 `review` 审两处读）；**`world` 与事件流都不在返回值里**
  （world 归 server 持有，调用方持有 `WorldMcpTool`，账一律经 `deps.trace` 读写）。

`build_real` 的取值全部来自配置，默认值见 `pokemon_agent/settings/default.json`：`models.{text,judge,verify,plan}`
各带型号、温度、输出上限、单请求超时（plan 另有 `thinking`），`models.json_mode` 四条链路共用；`run.{run_id,branch}`；
`paths.{runs_root,trace,memory,checkpoint,config_snapshot}`（相对路径以仓库根为基准，`runs_root` 默认 `"."`）；
`services.{memory_server_url,world_server_url}`；`review.mode`（`off`/`human`/`ai`/`both`）；`checkpoint.enabled`；
`debug.vision_dump_dir`。评测与实验写覆盖文件传入，例如 `build_real(config=["a.json", "b.json"])`。

**tool 层的接线工厂**：`BrainTool.build(links=…, …)` / `ReviewerTool.build(review, *, flush)`（住 `direct/reviewer_tool.py`，
按 `review.mode` 造复核席，`off` 时是 `NullReviewer`）/ `WorldMcpTool.build` / `MemoryTool.build` / `TraceTool.build`。
另有一个不在 tool 层的 `brain/build_llm_providers.py::build_llm_providers(config)`（由 `BrainTool.build()` 内部调，
`config` 是 brain 自己的纯数据 `BrainLlmConfig`）；`build.py` 一个都不越过。

- **厂商由型号名前缀决定**：`brain/providers.py::provider_for()` 查 `_PROVIDER_PREFIXES`
  （顺序即优先级）：`deepseek` → `DeepSeekProvider`、`doubao` → `ArkProvider`、`qwen` → `QwenProvider`。
  前缀不认识 → **装配期** `ValueError`，不拖到第一次调用才 404。
- **温度、输出上限、超时按链路配置**：每条链路的 `LinkSpec`（型号、`temperature`、`max_tokens`、`timeout_s`、`thinking`）
  取自 `models.*`，brain 里不再写死数字；默认值决策链温度 0.3，judge / verify / plan 为 0.0。
- **server 命令行旋钮**：`--watch` 管 server 所在机器的 SDL 窗口，`--speed` 管倍率（`0` 不限速、`1` 真实速度）；这两项不再是 build_real 参数。

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

**`.env` 的解析只有一处**：`pokemon_agent/env.py::load_env_file`（`setdefault` 语义：外部环境已有的同名变量优先；
空行 / 注释行 / 解析不了的行跳过，`export ` 前缀剥掉，成对引号剥一层；找不到文件返回 `None`）。调用方是
reviewer 与 memory server 的命令行入口、评测入口、核对与手动脚本。`build.py` **自己不读 `.env`**
——它要求调用方的环境里已经有密钥，缺了在装配期就炸。

## 四、异常族

`errors.py` 一共两个类，`__all__ = ["AgentError", "MaxRetriesExceeded"]`：

| 类 | 语义 | 谁抛 / 谁接 |
|---|---|---|
| `AgentError(Exception)` | 本项目**预期内失败**的基类；捕获它 = "我知道这里会出问题" | —— |
| `MaxRetriesExceeded(AgentError)` | 连续重试仍拿不到可用结果的**升级态** | 抛：`BrainTool._attempt_loop`；接：harness 的调用点（run / episode 的 `act` 只兜 `AgentError`） |

`MaxRetriesExceeded.__init__(attempts, last_reason, calls=(), source="")` 四个字段：`attempts`（试了几次）、
`last_reason`（最后一次为什么失败）、`calls: list[ModelCall]`（整条失败账，tool 层那份 `ModelCall`，可空）、
`source`（哪条链路耗尽：`"choose"` / `"plan"` / `"decompose"` / `"judge"` / `"verify"` / `"summarize_episode"` / `"summarize_task"`）。

**模块自己的词汇不住这里**：`brain/errors.py` 自成一根 `BrainError`、`world/errors.py` 自成一根
`WorldError`——它们的异常在 tool 层的桥上就被翻译成 `MaxRetriesExceeded`，
跨不过两层 `act` 的捕获点。

## 五、当前状态与已知缺口

- 可配置的策略值全在 `AppConfig` 里：`retry`（重试预算、退避）、`action_limits`（`MAX_SEGMENTS` / `MAX_TIMES` 一族）、
  `loop`（三层停判、图闸门、递归上限）、`budget`（分层运行预算）、`memory`（召回条数、RRF k、融合倍数与下限）、
  `request_timeouts_s`、`review`、`trace`、`checkpoint`；`eval` 段对被测系统不透明，由评测线自己解释。
- 图上没有存档格：存档由图外入口与 run 的 `act` 显式调用存档器（`docs/spec/checkpoint/SPEC.md`）；`build_real` 的 `branch` 只给恢复出来的执行线用（血缘由 trace 从账本推，不经装配点）。模块私有物理量故意不在 settings：`pyboy_world.PRESS_FRAMES`、
  `providers.IMAGE_TOKEN_FLOOR = 100`、`memory/store.py` 的 `_KINDS` / `_MD_KINDS`。

### 发现的不一致

- **AGENTS.md 六写"这三个工厂同形，都在 tool 层"**：代码里 tool 层有**四个** `build*`
  （四个 classmethod），而 `build_llm_providers` 在 `brain/` 不在 tool 层。
