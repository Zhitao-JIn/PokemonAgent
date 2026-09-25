# tools —— 模块规格

> 最后更新：2026-09-24 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准

## 一、职责与边界

`pokemon_agent/tools/` 是 Harness 与四个独立第三方模块（`brain` / `world` /
`memory` / `trace`）之间**唯一**的一层。它守两条边界：

- **第一跳（harness → 门面）永远是信封**：入参 `FromHarnessToXxxTool*Req`、
  返回 `*Resp`；两半都放发起方（harness），实体住在
  `pokemon_agent/schemas/harness/communication/`。
- **第二跳（门面 → 模块）走裸参数、返回模块自己的类型**，不造第二个信封
  （`GameToolPort.perceive_with_retry` 连 Req 都没有，入参是裸 keyword
  `ram_only`；`from pokemon_agent.world import …` 那一跳见各实现文件）。

**跨模块的双向转换只在这一层做**：信封里的领域对象（`Observation` /
`ActionSpace` / `ActMemory`）+ 模块的原生输入（prompt 文本 + 一撮裸字段），
只有 tool 同时认识。四个模块对 `tools/` 零 import、`schemas.harness` 对 `tools/`
也没有反向依赖，所以本层不用懒加载规避回环。

出口分家：**协议在 `tools/interface/`（只装抽象、立即导入），实现在
`tools/__init__.py`（只导出实现、`__getattr__` 懒加载）**。消费方写
`from pokemon_agent.tools.interface import GameToolPort`（harness），装配点写
`from pokemon_agent.tools import GameTools`（`build.py`）。

## 二、目录结构

```
pokemon_agent/tools/
├── __init__.py                统一出口：BrainTool/GameTools/MemoryTool/TraceTool + build_vision_provider（懒加载）
├── brain_tool.py              BrainTool（容器）＋ 八个能力对象 Planner/Decomposer/Chooser/Judger/
│                              Reflector/Verifier/Summarizer/TaskSummarizer（各满足一张单方法口）
├── game_tools.py              GameTools（GameToolPort 唯一实现）
├── memory_tool.py             MemoryTool（MemoryToolPort 唯一实现）
├── replay/                    回放的五个磁带件（TapeProvider/TapeGame/TapeMemory/TapeReviewer/TapeTrace）+ Tape + ReplayDiverged
│                              （docs/spec/checkpoint/SPEC.md §五；装配点有磁带时把真件包成它们）
├── vision_factory.py          build_vision_provider()
├── interface/
│   ├── __init__.py            只导出四张协议
│   └── ports.py               八张单方法大脑口（PlanPort/DecomposePort/ChoosePort/JudgePort/ReflectPort/
│                              VerifyPort/SummarizePort/TaskSummarizePort）+ GameToolPort / MemoryToolPort / TraceToolPort
├── prompts/
│   ├── __init__.py            load() / PromptTemplate / load_nested_sections / append_human_note
│   ├── decide_action.py       常量 + build_prompt + retry_prompt
│   ├── judge_success.py       build_prompt
│   ├── object_render.py       render_object_events（无模板）
│   ├── run_plan.py            build_prompt + index_lines/detail_blocks/object_lines/history_blocks/goals_lines
│   ├── decompose.py           build_prompt（episode 目标 → task 链）
│   ├── summarize.py           build_prompt + labeled_blocks（正负两组）
│   ├── summarize_task.py      build_prompt + history_blocks
│   ├── verify.py              build_prompt
│   └── calls/
│       ├── decompose.md  judge_success.md  run_plan.md  summarize.md  summarize_task.md  verify.md
│       └── decide_action/  button_help.md  decide_action.md  map_hint.md  repeat_hint.md  retry_note.md
└── trace/
    ├── __init__.py            TraceTool + _RENDERERS 分派表 + _to_trace_event
    └── render.py              每种账的正文渲染（纯函数）+ _body/_CALL_LINK
```

## 三、四个门面与信封清单

四张协议都在 `tools/interface/ports.py`（`@runtime_checkable Protocol`），
实现在同层的四个文件里。

**大脑能力口（实现是 `BrainTool` 的八个能力对象，`brain_tool.py`）**——一口一个方法，重试循环
下沉到本层，所以方法名不带 `once`：`plan`（信封 `…PlanOnce…`）、`decompose`、`choose`（信封 `…ChooseOnce…`）、
`judge`、`reflect`、`verify`、`summarize`、`summarize_task`。
每条签名 `(req: FromHarnessToBrainTool<X>Req) -> …<X>Resp`。各层 runtime 只拿自己用得到的那几个口。

**`GameToolPort`（实现 `GameTools`，`game_tools.py`）**：

| 方法 | 签名 | 信封文件 |
|---|---|---|
| `get_action_space` | `(req: FromHarnessToGameToolGetActionSpaceReq) -> …GetActionSpaceResp` | Req + Resp |
| `execute` | `(req: FromHarnessToGameToolExecuteReq) -> None` | 只有 Req |
| `reset` | `(req: FromHarnessToGameToolResetReq) -> None` | 只有 Req |
| `perceive_with_retry` | `(*, ram_only: bool = False) -> tuple[FromHarnessToGameToolPerceiveOnceResp, ModelCallLog]` | 只有 Resp，**无 Req** |
| `evolve` | `(req: FromHarnessToGameToolEvolveReq) -> None` | 只有 Req |
| `save_state` | `(req: FromHarnessToGameToolSaveStateReq) -> FromHarnessToGameToolSaveStateResp` | Req + Resp；路径由 harness 给，本层原子写文件 |
| `load_state` | `(req: FromHarnessToGameToolLoadStateReq) -> None` | 只有 Req；读档后不推进世界 |

**`MemoryToolPort`（实现 `MemoryTool`，`memory_tool.py`）**——各方法一对一信封：
`query_act_memories` / `query_recent_act_memories`（Req+Resp）、`store_act_memory`（只有 Req）、
`query_task_memories`（Req+Resp）/ `store_task_memory`（只有 Req）、`query_episode_summaries` /
`store_episode_summary`（Req+Resp）、`query_object_events` /
`query_object_events_at`（Req+Resp）、`append_object_events`（只有 Req）、
`query_knowledge` / `store_knowledge`（Req+Resp）、
`fetch`（Req+Resp：按自然键直接取回记录，回放按账上的 `refs` 取用）、
`snapshot_memory` / `restore_memory`（Req+Resp，0916——快照打整个记忆根成 zip /
还原时**以 zip 为准**，库里多出来的记录删掉；`snapshot` 的 Req 只带 `name`、Resp 带 `archive` 路径；
`restore` 的 Req 带 `archive`、Resp 带 `unpacked` 条数）。

**`TraceToolPort`（实现 `TraceTool`，`trace/__init__.py`）**：`append(req:
FromHarnessToTraceToolAppendReq) -> None`（写口只有这一个，0916 统一——
调用账的 `calls` 交整条重试链，渲染时逐条落成 `*_call` 账）、
`read_events(meta: dict[str, Any] | None = None) -> list[TraceEvent]`（读口无信封，
按 `meta` 做交集筛选——`None`/`{}` = 整个落盘根；给了 `meta`（且不带 `branch`）时按本执行线的
分支血缘拼接：祖先各取分叉点及之前、本分支全取（`TraceTool.build(branch=…, lineage=…)`）；返回契约层类型 `TraceEvent`，
不是 trace 自己的 `Event`）。

**信封清单**（`pokemon_agent/schemas/harness/communication/`，一个类一个文件）：

| 门面 | Req 文件 | Resp 文件 |
|---|---|---|
| brain | `FromHarnessToBrainTool{ChooseOnce,Judge,Reflect,Verify,Summarize,SummarizeTask,PlanOnce,Decompose}Req.py` | 同前缀的八个 `…Resp.py` |
| game | `FromHarnessToGameTool{GetActionSpace,Execute,Reset,Evolve}Req.py` | 只有 `…GetActionSpaceResp.py`、`…PerceiveOnceResp.py` |
| memory | `FromHarnessToMemoryTool{QueryActMemories,QueryRecentActMemories,StoreActMemory,QueryTaskMemories,StoreTaskMemory,QueryEpisodeSummaries,StoreEpisodeSummary,QueryObjectEvents,QueryObjectEventsAt,AppendObjectEvents,QueryKnowledge,StoreKnowledge,SnapshotMemory,RestoreMemory}Req.py` | 除 `…StoreActMemory`、`…StoreTaskMemory`、`…AppendObjectEvents` 外各有一个 `…Resp.py` |
| trace | `FromHarnessToTraceToolAppendReq.py` | 无（返回 None） |

两件住在这个目录、但不属于上面四张门面：`ModelCall.py`（一次模型调用的账，
`payload`/`error_kind`/`error`，同文件还定义 `ModelCallLog = list[ModelCall]`；
brain 侧另有一份方言，由 `_adopt()` 转过来——批量记账信封
`FromHarnessToTraceToolAppendModelCallsReq.py` 0916 已随写口统一删除）。同样不由
tools 层消费的还有
`FromHarnessToReviewerAuditReq.py`（内含 `…AuditReq`/`…AuditResp`/`AuditVerdict`）、
`FromHarnessToReviewerInjectReq.py`、`RunResp.py`。层间交接（`EpisodeInput/Output`、`TaskInput/Output`）
在 `schemas/harness/domain/`，不是信封。

## 四、接线工厂

五个工厂，"这个技能接哪家厂商"的接线知识全收在 tool 层，装配点
（`pokemon_agent/build.py`）一个都不越过、对 `brain`/`world`/`memory`/`trace`
零 import：

| 工厂（真实签名） | 造什么 | 住哪 |
|---|---|---|
| `BrainTool.build(*, text="qwen-plus", judge="qwen3.8-max", verify="doubao-seed-2-1-pro-260628", plan="doubao-seed-2-1-pro-260628", max_tokens=25600)` | `BrainLlmConfig` + `build_llm_providers()` + `Brain` | `brain_tool.py` |
| `GameTools.build(rom: str, *, state_path=None, watch=False, vision_model="qwen3.8-max", speed=0)` | `PyBoyWorld` + 感知 provider | `game_tools.py` |
| `MemoryTool.build(*, memory_root=None, max_summaries=50)` | `LocalEmbeddingProvider` + `LocalRerankerProvider` + 四个 `LocalMemoryStore` | `memory_tool.py` |
| `TraceTool.build(*, run_id="local", trace_root=None)` | `LocalTrace` | `trace/__init__.py` |
| `build_vision_provider(model="qwen3.8-max", temperature=0.0)` | world 的 `VisionProvider`（`provider_for(model, temperature=…, timeout=20)`） | `vision_factory.py` |

装配点的用法（`build.py:119-168`）：`GameTools.build(rom, state_path=…, watch=…,
vision_model=…, speed=…)`、`TraceTool.build(run_id=run_id, trace_root=trace_root)`、
`MemoryTool.build(memory_root=…, max_summaries=…)`、
`BrainTool.build(text=…, judge=…, verify=…, plan=…, max_tokens=…)`，返回值直接进
三个 runtime（`RunRuntime` / `EpisodeRuntime` / `TaskRuntime`），大脑按层各造一份（`run_brain` / `episode_brain` / `task_brain`）。四个工厂都是 `__init__` 的糖（内部只构造 + `cls(...)`）。

## 五、跨模块转换规则

tool 层是唯一同时认识两边形状的地方，实际存在的转换点：

- **账的方言搬运**：`brain_tool.py:562 _adopt()` 把 `brain.interface` 的
  `ModelCall` 转成 `schemas.harness` 的 `ModelCall`（字段此刻恰好同名，语义边界
  是真的）；反方向在 `trace/__init__.py:99 _to_trace_event()`——读回来的一条
  trace 事件 → `TraceEvent`。
- **世界语义 + 存储形状**：`brain_tool.py:253 _normalize()` 施加这个世界的动作
  规则（`INTERACT_KEY` 只按一次、链体只许 `DIRECTION_KEYS`、链尾至多一个交互键，
  上限 `MAX_SEGMENTS`/`MAX_TIMES`/`MAX_RATIONALE`）；`reflect()` 组装
  `ActMemory`（`step`/`episode_id`/`task_id` 在这里盖章），`summarize_task()` 组装 `TaskMemory`，
  `summarize()` 组装 `EpisodeMemory`（正负两组都进 prompt），`decompose()` 把 `Decomposition` 交回
  （`task_id` 由 harness 编）。
- **记忆过滤**：`brain_tool.py:622 _blind()` 用 `SNAPSHOT_BLIND` 造记忆用的那份
  观测，`:630 _render_observation()` 把观测渲成 brain 要的文本。
- **动作空间**：`game_tools.py:51 _mask()` 按 `Facts.Overlay` 把 `OVERLAY_ACTIONS` 与
  `world.all_actions()` 取交，并挂上 `BUTTON_HELP`/`REPEAT_HINT`/`MAP_HINT` 三份文案。
- **trace 正文**：`trace/render.py` 每个渲染函数收 `FromHarnessToTraceToolAppendReq`、
  吐 `Rendered`（`type`/`kind`/`content`）；写账正文走 `render.py:520 _body()` + 三份
  drop 名单（`_STEP_BODY_DROP`/`_OBJECT_BODY_DROP`/`_EPISODE_BODY_DROP`），链路名由
  `render.py:248 _CALL_LINK` 给，账名 → 渲染函数的表是 `_RENDERERS`
  （`trace/__init__.py:52`）。一次交互的 N 次尝试由调用账的 `calls`
  （整条重试链）在 `render.model_call` 里一拆多：每条尝试一条
  `*_call` 账、失败的那次再补一条 `call_failed`（0916 统一写口后
  批量入口 `append_model_calls` 已删）。
- **文字化**：`prompts/object_render.py:27 render_object_events()`（事件 → 行）、
  `prompts/run_plan.py:75 history_blocks()` 与 `:91 goals_lines()`（记忆/目标表 →
  行列表）——`build_prompt()` 与 `BrainTool` 的入参共用同一份实现，分两份会漂移。

## 六、prompts

每个需要拼装逻辑的模板配一个同名 `.py`，对外只给 `build_prompt()`；模板按
**文件名**加载（`prompts/__init__.py:113 load()` 在整棵 `prompts/` 树里 `rglob`
`<name>.md`，重名当场 assert）：调用方不关心它在哪层子目录。

| 组装模块 | 模板文件 | 装配函数 / 常量 |
|---|---|---|
| `decide_action.py` | `calls/decide_action/decide_action.md`（本体）、`button_help.md`（`load_nested_sections`）、`map_hint.md`、`repeat_hint.md`、`retry_note.md` | `build_prompt()`、`retry_prompt()`、`BUTTON_HELP`/`MAP_HINT`/`REPEAT_HINT`、`RetryPromptReq` |
| `judge_success.py` | `calls/judge_success.md` | `build_prompt()` |
| `verify.py` | `calls/verify.md` | `build_prompt()` |
| `summarize.py` | `calls/summarize.md` | `build_prompt()`、`labeled_blocks()`（正 / 负两组） |
| `summarize_task.py` | `calls/summarize_task.md` | `build_prompt()`、`history_blocks()` |
| `decompose.py` | `calls/decompose.md` | `build_prompt()` |
| `run_plan.py` | `calls/run_plan.md` | `build_prompt()`、`index_lines()`、`detail_blocks()`、`object_lines()`、`history_blocks()`、`goals_lines()` |
| `object_render.py` | 无模板（纯函数） | `render_object_events()` |

**分工原则**（AGENTS.md 六）：prompt 是规则、入参是素材——"怎么判、怎么想"写进
prompt，"判什么、想什么"才当参数传，同一件东西绝不两处给。模板用
`string.Template` 的 `$var`（`PromptTemplate.render()` 用 `substitute`，漏传就炸），
人类的插话由 `prompts/__init__.py:152 append_human_note()` 统一追加在最末尾。
`decide_action.py` 是唯一同时提供"首次组装"与"重试追加"的模块（`retry_note.md`
只服务 `decide_action.md`，其余链路原样重问）。

## 七、当前状态与已知缺口

- **四张门面**：`CheckpointToolPort` 已解散；`GameToolPort` 的存读档只有 `save_state` / `load_state` 两个方法
  （09-25 为 checkpointer 加回）；`TraceToolPort` 只剩一个通用读口
  `read_events`（无游标、无掩码、无 `read_event(id)`），没有本层自己的测试目录。
- **重试循环全在 tool 层**：`brain_tool.py:168 _attempt_loop()` 服务
  choose/plan/decompose/judge/verify/summarize/summarize_task 七条链路（`reflect` 不调模型），
  `game_tools.py:169 perceive_with_retry()` 是 world 那条链的同构兄弟；两者都把
  `AttemptFailed`/`PerceptionAttemptFailed` 翻译成 `MaxRetriesExceeded(source=…)`，
  账随结果或异常走。
- **`render.py` 里有会炸的墓碑**：`plan_failed()` 与 `human_note_injected()` 都
  `raise AssertionError`，且不在 `_RENDERERS` 表里——按老名字发账会就地爆炸。
- **`ports.py:30`、`tools/__init__.py:38`、`interface/__init__.py:26` 曾引
  `docs/spec/tools/PLAN_tool_interface.md`**（该文件连同 `docs/spec/tools/`
  整个目录已不在仓库里）。2026-09-15 已全部改指本文件。

## 八、发现的不一致

1. **`meta` 由谁拼**。AGENTS.md 九写"`run_id` 由落盘层盖，其余由
   `TraceTool.append` 按信封公共字段拼"。代码里 `TraceTool.append` **不拼**：
   `trace/__init__.py:142` 反过来 assert `"run_id" not in req.meta`，并要求
   `source`/`episode_id`/`step` 由 harness 一次交齐（`run_id` 仍由落盘层盖）。
2. **接线工厂的数量**。AGENTS.md 二.2 与第四节已改口径为**五个**（`BrainTool.build`
   / `GameTools.build` / `MemoryTool.build` / `TraceTool.build` /
   `build_vision_provider`）；曾有一段时间 AGENTS.md 只说两个、六说三个。
   代码里就是五个（`game_tools.py:107`、`trace/__init__.py:120`），
   `build.py:119/134` 都在用。`docs/spec/memory/PORTS.md` 的附表仍按旧数写"三个"。
3. **brain 实现依赖的分布**。AGENTS.md 十二.4 的枚举是"`brain_tool.py` 4 处 +
   `vision_factory.py` 1 处"。代码里 `tools/` 指向 brain 实现面的 import 语句共
   5 条，但构成不同：`brain_tool.py:47`/`:55`/`:148`（3 条）、
   `game_tools.py:23`（`from pokemon_agent.brain.errors import ProviderRejected`）、
   `vision_factory.py:64`。**`game_tools.py` 那一条在 AGENTS 的枚举里没有出现**，
   `brain_tool.py` 是 3 条而不是 4 条。
4. **prompt 不只在 `tools/prompts/`**。AGENTS.md 六说"prompt 模板与组装函数
   住在 `tools/prompts/`"；世界侧的感知模板住在
   `pokemon_agent/world/prompts/perceive_screen.md`（**不是** `tools/` 下），
   读取器是 `pokemon_agent/world/prompts/__init__.py`——`tools/prompts/__init__.py:39`
   记录了 0913 的这次移出。
5. **代码内部的陈旧表述**（不影响对外契约，逐条给真值、标处置）：
   `brain_tool.py:166` 的分节注释曾写"五条链路共用"，而 `_attempt_loop` 的调用点是
   **六个**（choose/plan/judge/verify/summarize/extract）——**2026-09-15 已改**；
   `game_tools.py:47` 注释曾把 `decide_action.py` 的路径写成
   `pokemon_agent/prompts/decide_action.py`，真值是
   `pokemon_agent/tools/prompts/decide_action.py`——**2026-09-15 已改**。
