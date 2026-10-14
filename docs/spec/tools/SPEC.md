# tools —— 模块规格（P7 拆分后：`direct/` + `mcpclient/`）

> 最后更新：2026-10-01 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准
>
> **P7 拆分定案**（2026-09-30，CHANGELOG 342/344）：原 `pokemon_agent/tools/`
> 一个包拆成两半——**`direct/`**（brain / trace 半边：BrainTool、TraceTool、
> prompts、四张 Port 协议）与 **`mcpclient/`**（memory / world 半边：进程内
> 实现 + MCP 远程门面 + client）。文件名 `tools/SPEC.md` 沿用，讲的是这整个
> 门面层。历史文档里的 `tools/...` 路径引用一律按映射读：
> `tools/brain_tool`→`direct/brain_tool`、`tools/trace`→`direct/trace`、
> `tools/prompts`→`direct/prompts`、`tools/interface`→`direct/interface`、
> `tools/game_tools`→`mcpclient/game_tools`、`tools/memory_tool`→`mcpclient/memory_local`、
> `tools/vision_factory`→`brain/vision_factory`、`tools/backoff`→`backoff`（顶层）。

## 一、职责与边界

门面层是 Harness 与四个独立第三方模块（`brain` / `world` / `memory` / `trace`）
之间**唯一**的一层。它守两条边界：

- **第一跳（harness → 门面）永远是信封**：入参 `FromHarnessToXxxTool*Req`、
  返回 `*Resp`；两半都放发起方（harness），实体住在
  `pokemon_agent/schemas/harness/communication/`。
- **第二跳（门面 → 模块）走裸参数、返回模块自己的类型**，不造第二个信封
  （`GameToolPort.perceive_with_retry` / `perceive_task` 连 Req 都没有；
  `from pokemon_agent.world import …` 那一跳见各实现文件）。

**跨模块的双向转换只在门面层做**：信封里的领域对象（`Observation` /
`ActionSpace` / `ActMemory`）+ 模块的原生输入（prompt 文本 + 一撮裸字段），
只有 tool 同时认识。四个模块对门面层零 import、`schemas.harness` 对门面层
也没有反向依赖。

**拆分的依赖方向**：`direct/` 认识 brain 与 trace 的形状；`mcpclient/` 认识
world 与 memory 的形状。两半之间**零互相依赖**（唯一的共享件 `backoff.py`
在顶层，只依赖 `config.py`）。装配点 `build.py` 只从两半各 import 工厂。

## 二、目录结构

```
pokemon_agent/direct/                brain / trace 半边（原 tools/ 的上半）
├── brain_tool.py                    BrainTool（容器）＋ 八个能力对象 Planner/Decomposer/Chooser/
│                                    Judger/Reflector/Verifier/Summarizer/TaskSummarizer
├── trace/
│   ├── __init__.py                  TraceTool + _RENDERERS 分派表 + _to_trace_event
│   ├── render.py                    每种账的正文渲染（纯函数）+ _body/_CALL_LINK
│   ├── content.py                   render 的镜像（读侧结构化解析）
│   ├── parse.py / lineage.py / live_feed.py
├── prompts/                         决策 / 判定 / 拆解 / 蒸馏的全部模板与组装函数
│   └── calls/…（.md 模板树）
└── interface/
    ├── __init__.py                  只导出协议
    └── ports.py                     八张单方法大脑口 + GameToolPort / MemoryToolPort / TraceToolPort

pokemon_agent/mcpclient/             memory / world 半边（原 tools/ 的下半）
├── client.py                        McpClient（同步外观 / 异步内核）+ 端点与健康探针
├── game_tools.py                    GameTools（GameToolPort 进程内实现；MCP 模式转交 WorldMcpTool）
├── world_tool.py                    WorldMcpTool（GameToolPort 的 MCP 远程门面）
├── memory_local.py                  MemoryTool（MemoryToolPort 进程内实现）
├── memory_tool.py                   MemoryMcpTool（MemoryToolPort 的 MCP 远程门面）
└── world_server / memory_server     （住 mcp_servers/，不在本包——列在这里对位）

共享件：
├── backoff.py                       backoff_seconds()（两个重试循环共用；P7 起升顶层）
└── brain/vision_factory.py          build_vision_provider()（P7 起归 brain——
                                     它是 brain provider 的接线知识，且 world server
                                     也消费它，放 mcpclient 会造成 server→client 反向依赖）
```

## 三、四张门面与信封清单

四张协议都在 `direct/interface/ports.py`（`@runtime_checkable Protocol`）。

**大脑能力口（实现是 `direct/brain_tool.py` 的 `BrainTool` 八个能力对象）**——
一口一个方法，重试循环下沉到本层：`plan` / `decompose` / `choose` / `judge` /
`reflect` / `verify` / `summarize` / `summarize_task`，每条签名
`(req: FromHarnessToBrainTool<X>Req) -> …<X>Resp`。各层 runtime 只拿自己用得到的那几个口。
`Chooser` 把动作空间里的脚本条目（world 的 `ActionEntry`，脚本条目统一形状）
转成 brain 的 `ScriptSignature` 随 `keys` 交给 `Brain.choose`；脚本调用
不过 `_normalize` 的按键规则，语义校验归 world 执行器。

**`GameToolPort`（进程内实现 `mcpclient/game_tools.py::GameTools`；
MCP 远程门面 `mcpclient/world_tool.py::WorldMcpTool`）**：

| 方法 | 签名 | 信封文件 |
|---|---|---|
| `get_action_space` | `(req: …GetActionSpaceReq) -> …GetActionSpaceResp` | 开放按键的场合按 overlay 给键 + 按场合给脚本条目，仅开放脚本的场合只给本场合的脚本、不给键 |
| `execute` | `(req: …ExecuteReq) -> FromHarnessToGameToolExecuteResp` | 两形分流：键 → `world/object_events.observe_step`，`event` 带本键裸事件；脚本（统一调用）→ 掩码校验后跑脚本层，`report` 是终态报告（`{ok, code, data, events, calls}`）。MCP 门面调用同名工具并保留报告事件 |
| `reset` | `(req: …ResetReq) -> None` | 只有 Req |
| `perceive_with_retry` | `() -> tuple[…PerceiveOnceResp, ModelCallLog]` | episode 层视觉档；只有 Resp |
| `perceive_task` | `() -> …PerceiveTaskResp` | task 层，不调模型、不失败 |
| `evolve` | `(req: …EvolveReq) -> None` | 只有 Req（MCP 面不提供） |
| `save_state` / `load_state` | Req（+Resp） | 路径由 harness 给，本层原子写文件 |

**`MemoryToolPort`（进程内实现 `mcpclient/memory_local.py::MemoryTool`；
远程委托 `mcpclient/memory_tool.py::MemoryMcpTool`）**——四个方法：
`recall` / `memorize` / `snapshot_memory` / `restore_memory`，Port 信封不变。
服务端默认只注册 recall / memorize，带 `--enable-admin` 才注册 snapshot_memory /
restore_memory；`/health.admin` 报告开关，未开放时门面抛 MemoryAdminDisabled。
管理面传 base64 zip 内容、sha256 与大小，原始 zip 上限 256 MiB；客户端 memory_root
只管本地 snapshots，服务端根由 --memory-root 指定，不依赖共享路径。
服务端 snapshot / restore / memorize 共用一把锁；共用的 MemoryCapability.restore
在删除前拒绝不安全路径，库保持不变，无害杂散条目仍跳过。
详见 `docs/mcp/memory-admin-spec.md` 与 `docs/spec/memory/API.md`。

**`TraceToolPort`（实现 `direct/trace/__init__.py::TraceTool`）**：
`append(req: FromHarnessToTraceToolAppendReq) -> None`（写口唯一）+
`read_events(meta) -> list[TraceEvent]`（分支血缘拼接见 `direct/trace/lineage.py`）。

**信封清单**（`pokemon_agent/schemas/harness/communication/`，一个类一个文件）：

| 门面 | Req 文件 | Resp 文件 |
|---|---|---|
| brain | `FromHarnessToBrainTool{ChooseOnce,Judge,Reflect,Verify,Summarize,SummarizeTask,PlanOnce,Decompose}Req.py` | 同前缀八个 `…Resp.py` |
| game | `FromHarnessToGameTool{GetActionSpace,Execute,Reset,Evolve}Req.py` | `…GetActionSpaceResp.py`、`…PerceiveOnceResp.py`、`…SaveStateResp.py` |
| memory | 14 个 `FromHarnessToMemoryTool*Req.py`（清单见 memory/API.md） | 除三个纯写口外各有 `…Resp.py` |
| trace | `FromHarnessToTraceToolAppendReq.py` | 无（返回 None） |

`ExecuteResp` 带两个可空结果位：`report`（脚本终态报告）/ `event`（本键裸事件，P6）。
`AppendReq` 相应带 `action` / `report` 素材位。

## 四、接线工厂

五个工厂，"这个技能接哪家厂商"的接线知识全收在门面层，装配点
（`pokemon_agent/build.py`）对 `brain`/`world`/`memory`/`trace` 零 import：

| 工厂 | 造什么 | 住哪 |
|---|---|---|
| `BrainTool.build(*, text=…, judge=…, verify=…, plan=…, max_tokens=…)` | `BrainLlmConfig` + providers + `Brain` | `direct/brain_tool.py` |
| `GameTools.build(rom, *, state_path, watch, vision_model, speed, world_server_url=None)` | 配了 `world_server_url`（裸字段，env `MCP_WORLD_SERVER_URL` 只是缺省来源）→ `WorldMcpTool`；否则 `PyBoyWorld` + 感知 provider | `mcpclient/game_tools.py` |
| `MemoryTool.build(*, memory_root, max_summaries, memory_server_url=None)` | 同上双轨（env `MCP_MEMORY_SERVER_URL`） | `mcpclient/memory_local.py` |
| `TraceTool.build(*, run_id, trace_root)` | `LocalTrace` | `direct/trace/__init__.py` |
| `build_vision_provider(model, temperature=0.0)` | world 的 `VisionProvider` | `brain/vision_factory.py` |

返回值直接进三个 runtime，大脑按层各造一份（`run_brain` / `episode_brain` /
`task_brain`）。**server 侧（`mcp_servers/world_server.py`）也消费
`build_vision_provider`**——这是 `vision_factory` 归 brain 而不归 mcpclient 的原因
（否则 server→client 反向依赖）。

## 五、跨模块转换规则

- **账的方言搬运**：`direct/brain_tool.py::_adopt()` 把 `brain.interface` 的
  `ModelCall` 转成 `schemas.harness` 的 `ModelCall`；反方向
  `direct/trace/__init__.py::_to_trace_event()`。
- **世界语义 + 存储形状**：`_normalize()`（键链规则，脚本原样放行）、
  `reflect()` 组装 `ActMemory`（`result` 字段 P5 起带脚本结局码）、
  `summarize_task()` / `summarize()` / `decompose()`。
- **记忆过滤**：`_blind()` / `_render_observation()`（SNAPSHOT_BLIND）。
- **动作空间**：`mcpclient/game_tools.py::_action_space()` 调 world 的 `compute_action_space`
  取 `names` / `mask` / `entries`（掩码只由 world 给出，本层不改），再给开放按键的场合挂
  `BUTTON_HELP`/`REPEAT_HINT`/`MAP_HINT`。
  **已知耦合**：`mcpclient.game_tools` import `direct.prompts` 的三份文案——
  337 定案的方向是"desc 由 server 产出自带于 entries"，届时这份文案该迁去
  world 侧，耦合随之消失。
- **trace 正文**：`direct/trace/render.py` 每渲染函数收 `AppendReq` 吐 `Rendered`；
  `act_call` 按 key / script 两形分支（P5）。
- **文字化**：`direct/prompts/object_render.py` / `run_plan.py`。
- **object 事件（P6）**：判定唯一裁判是 `world/object_events.py::judge_press`；
  逐键路径事件随 `step` 响应（`observe_step`）回 harness，脚本路径随终态报告
  `events[]` 批量——两路在 `store_object_semantic_memory` 汇合，
  `rules.stamp_events` 只补章，不再判定。

## 六、prompts（`direct/prompts/`）

每个需要拼装逻辑的模板配一个同名 `.py`，对外只给 `build_prompt()`；模板按
**文件名**加载（`prompts/__init__.py::load()` 整树 `rglob`，重名当场 assert）。
P5 起 `decide_action.md` 的"可用动作"一节并列键与脚本条目（签名 + 说明 +
`{"action": "walk_to", "args": {…}}` 输出格式），组装见 `decide_action.py`。
世界侧的感知模板住 `world/prompts/perceive_screen.md`（不在本层）。
其余对照表不变（judge_success / verify / summarize / summarize_task /
decompose / run_plan / object_render）。

## 七、当前状态与已知缺口

- **四张门面**：`CheckpointToolPort` 已解散；`TraceToolPort` 只剩通用读口
  `read_events`；MCP 面上 world server 共 45 个 tool（原子 7 + release_lease
  + 脚本 37），脚本一次调用占 harness 账一步。
- **重试循环全在门面层**：`direct/brain_tool.py::_attempt_loop()` 七条链，
  `mcpclient/game_tools.py::perceive_with_retry()` 与
  `mcpclient/world_tool.py::perceive_with_retry()`（远程同构）。
- **`render.py` 里的墓碑**：`plan_failed()` / `human_note_injected()`
  `raise AssertionError`，不在 `_RENDERERS` 表。
- **`mcpclient.game_tools` → `direct.prompts` 的文案耦合**（见五）——等
  desc 迁 server 侧后消除。

## 八、发现的不一致

1. **`meta` 由谁拼**。`TraceTool.append` 不拼：`direct/trace/__init__.py`
   assert `"run_id" not in req.meta`，`source`/`episode_id`/`task_id`/`step`
   由 harness 一次交齐（`run_id` 由落盘层盖）。
2. **接线工厂的数量与住址**。五个工厂分布在 direct / mcpclient / brain 三处
   （见四）；`docs/spec/memory/PORTS.md` 若仍写"三个"以本文件为准。
3. **prompt 不只在 `direct/prompts/`**：世界侧感知模板在
   `world/prompts/perceive_screen.md`。
4. **历史文档冻结**：`docs/checkpoint` / `docs/eval` / `docs/experiences` /
   `docs/perceive` / `docs/web_reviewer` / `docs/HANDOFF_*` / `docs/roadmap/*_archive.md`
   里的 `tools/` 路径引用是过去时的记录，不改——按本文件头部的映射表读。
