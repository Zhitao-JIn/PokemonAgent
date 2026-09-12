# Checkpoint / Resume 交接文档（2026-09-07，供实现会话使用）

> **本文档描述 0907 当天的事实快照**（当时是十七节点图、`look`/`look_after_action`/
> `advance_step` 等名字、图里还没有链内小循环）。文件名带日期戳，是历史记录，**就地
> 不改写**。当前图见 `pokemon_agent/harness/interface/episode_harness_port.py` 的模块
> docstring（那里是现下唯一的权威图，且与 `web/src/App.tsx` 的相位表由
> `scripts/check_graph_phases.py` 机械核对）。

> 目标：为两级 harness 补上 checkpoint/resume（Agent 工程清单第 6 项，当前
> 最高优先级缺项）。本文档是实现的唯一输入——架构事实、设计决策、契约草案、
> 改动触点、验收标准全部在内，不需要考古旧会话。
> 基线：commit `c8b9ab7`，分支 `feat/model-call-observability-and-providers`。
> 本文档只给方向、契约与判断点，**不给实现代码**（用户自己写）。

## 0. 一句话目标

run 或 episode 中断（进程退出 / 崩溃 / 主动暂停）后，能从上一次一致性点恢复，
继续跑完剩余目标——trace 不重不漏、event_id 不断链、模拟器世界与记忆对得上。

## 1. 架构速览（两图两编译点，就是全部边界）

```
RunHarness（run 级，五节点环）   run_harness.py:505 _compile()，graph.compile() :544
  begin → plan → dispatch → reflect → review → dispatch …
    └─ EpisodeHarness（episode 级，十七节点图）  episode_harness.py:270 _compile()，graph.compile() :336
         look → judge ─(done)→ 收尾链(3 节点) → END
               └(否)→ get_action_space → 四路 retrieve → enrich_observation
                       → think_action → act → look_after_action
                       → detect_stall → advance_step → store_step/store_object → look
```

**两处 `graph.compile()` 都没传 checkpointer——这就是要补的洞。**

## 2. 现状盘点

### 2.1 已有、直接依赖的资产

| 资产 | 位置 | 意义 |
|---|---|---|
| `RunState`（Pydantic，全部可序列化） | `interfaces/harness/harness_port.py:59` | 身份组 run_id/goals/attempts/outcomes——字段 docstring 明写"跨轮，checkpoint 要的就是它"；流转组 episode_id/outcome/last_task/plan_note/plan_failed/done/why |
| `EpisodeRunState`（Pydantic） | `interfaces/harness/episode_harness_port.py:54` | 身份组 episode_id/task/step/goals；流转组单步内传递。`outcome` 不在 state（`run()` 结尾从 observation 算）；`goals` 是 run 级投影、全程只读 |
| `LocalTrace` | `trace/store.py` | 事件 5 元组 + `frame_png`；`event_id` 严格单调（:38 `_next_id=0` 起，:118 有单调 assert）；`events()` 支持过滤读取；`TRACE_SCHEMA_VERSION=3` **不要动** |
| TraceTool 层 | `tools/trace_tool.py` + `trace_render.py`，`TraceKind`(28) + 宽模型 `FromHarnessToTraceToolAppendReq` | harness 只组装 req，渲染在 tool 层 |
| episode 起点模拟器存档 | `episode_harness.py:252-253`：`<episode_state_dir>/<episode_id>.start.state` | PyBoy save-state，档位 A 的物理基础 |
| WorldPort.save_state | `interfaces/world/world_port.py:15` | **只有 save 没有 load**——载入目前藏在 `reset(task)` 内部（走构造时的 `state_path`），步级续跑需要先补 load 能力 |
| 情景记忆持久化 | `memory/episode/episode_store.py`（md + frontmatter） | 跨局摘要已落盘，恢复后天然可读 |
| StepMemory 的持久化路径 | trace `MEMORY_WRITE` 事件（content 全文） | 单步记忆只活在内存，但**可从 trace 重建** |
| 集成测试基建 | `tests/test_integration_tool_layer.py`（真实图 + 假 Brain/World/记忆） | checkpoint 测试照此模式写 |

### 2.2 缺口（= 交付物清单）

1. 两级 `graph.compile()` 无 checkpointer / 无恢复入口。
2. `LocalTrace` 无法在已有 JSONL 上续写（`_next_id` 恒从 0 起，恢复即断单调链）。
3. `WorldPort` 无 `load_state`；episode 中途（非起点）无模拟器存档点。
4. `RunDataCenter` 三槽（goals/review/human_note）纯内存，进程死即丢。
5. 无任何"恢复 RunState 并续跑"的入口（`run()` 签名只支持从零开始）。

## 3. 设计决策（已按项目规范定死，不要另起炉灶）

### 3.1 粒度与档位

- **run 级恢复 = episode 粒度**。`RunState` 快照恢复后从 `dispatch` 重入重派栈顶；
  已完成 episode 靠 `outcomes` + trace 的 `EPISODE_END` 对账，不重跑。
- **episode 级两档**：
  - **档位 A（必做）：整局重跑**。从 `<episode_id>.start.state` 载入模拟器 +
    从 trace 重建该局已有 StepMemory → episode 从 step 0 重跑但**带着恢复的
    记忆**。这是"记忆有用"的直接验证场景，也是唯一不依赖新存档点的方案。
  - **档位 B（选做，只留接口不做实现）**：步级续跑。LangGraph `SqliteSaver`，
    thread_id=`episode_id`，配合每步一次 `game.save_state()`。成本全在模拟器
    存档频率与 WorldPort.load_state 补口。
- **不做**：跨 run 恢复（恢复出的 run 沿用原 run_id 续写 trace，不新开）；恢复时改目标栈（那是 `apply_goals_edit` 的事）。

### 3.2 机制：状态快照 + 事件游标对账

AGENTS.md 第 233 行"checkpoint 存事件序列而非最终状态"的落地含义：

**checkpoint 记录 = 可序列化状态快照 + 事件游标 + 模拟器存档路径**。事件序列
本体不复制（JSONL 里已经在），游标即指针。为什么不是纯事件重放：模拟器世界
状态与 LLM 已花的钱不可从事件重建；为什么仍要快照带对账而不裸快照：状态可以
随时用 trace 校验，防止"快照说是 N 步、事件流只到 N-2"这类静默错位。

**对账规则（恢复时必须 assert，对应 AGENTS.md :132 的 postcondition）**：
- 快照 `step` == 该 episode 事件流中的最大 step；
- `len(RunState.outcomes)` == trace 中该 run 的 `EPISODE_END`（含 ERROR 变体）数；
- 游标 `event_id` == 恢复时 trace 文件的最大 event_id（续写从此 +1）；
- `len(attempts) == len(goals)`（RunState 既有 invariant）。

### 3.3 event_id 续链（硬性）

`trace/store.py:38` `_next_id = 0` 是改点：`LocalTrace` 增加"从既有 run 目录
恢复"的入口（读该 run 全部 JSONL 的最大 event_id 作为起点），或提供显式
`resume_from(event_id)` 方法——二选一，倾向前者（构造期定，调用方少一个坑）。
**恢复后 `_episode_is_complete()` 的语义要同步核对**（:101 在 append 时用到）。

### 3.4 DataCenter 槽

不做持久化（人工重发的成本低于一套槽持久化的复杂度）。恢复入口负责用
`RunState.goals` 重新 `publish_goals(...)`，让前端面板与恢复后的栈对齐；
human_note/review 槽留空即可（本来就该人重新发）。

## 4. 新增契约草案（命名照 617c6eb 规则：From{调用方}To{被调方}{函数}{Req|Resp}）

接口先行：先在 `interfaces/` 写 Protocol（带"承诺什么/何时失败/调用方保证什么"
三段 docstring），再写实现。建议形态（签名可微调，语义不要动）：

- `interfaces/tools/checkpoint_tool_port.py`
  - `CheckpointToolPort.save(req: FromHarnessToCheckpointToolSaveReq) -> None`
  - `CheckpointToolPort.load(run_id: str) -> FromCheckpointToolToHarnessRestoreResp | None`
- `schemas/communication/FromHarnessToCheckpointToolSaveReq.py`：
  `run_id / level("run"|"episode") / episode_id|None / state_dump(dict，Pydantic model_dump)/ last_event_id / emulator_state_path|None`
- `schemas/communication/FromCheckpointToolToHarnessRestoreResp.py`：
  同构 + `saved_at` 之类元信息
- 落盘格式：一个 run 一个 JSON 文件（`trace_data/<run_id>/checkpoint.json`，
  单文件覆盖写——只恢复"最近一次一致性点"，不存历史链）
- 实现 `tools/checkpoint_tool.py`：纯读写 + 对账 assert；对账需要读 trace，
  通过注入的 `TraceTool`/trace 目录路径完成，**不反向 import harness**
- 装配只发生在 `build.py`（项目唯一 new 实现处），harness 构造函数注入
  `CheckpointToolPort`——harness 不 import 实现，符合铁律 2/3

## 5. 改动触点清单

| 文件 | 改什么 |
|---|---|
| `interfaces/tools/checkpoint_tool_port.py`（新） | Protocol + 两张 schema |
| `tools/checkpoint_tool.py`（新） | 实现与对账 |
| `trace/store.py:32-45` | 恢复续写入口（_next_id / _episode_is_complete 语义） |
| `harness/run_harness.py:544`、`harness/episode_harness.py:336` | 档位 B 时 compile(checkpointer=...)；档位 A 不动这两处 |
| `harness/run_harness.py:141 run()` / `episode_harness.py:152 run()` | 增加恢复分支（或新增 `resume()` 入口——判断点 §9.3） |
| `harness/episode_harness.py:252` 附近 | 档位 B：每步 save_state（选做不实现） |
| `interfaces/world/world_port.py` | 档位 B：补 `load_state`（选做不实现） |
| `build.py` | 装配 CheckpointTool、注入两端 |
| `api.py` / `experiment/run_episode.py` | 恢复入口暴露（至少 CLI 一条） |
| `CHANGELOG.md` | 四段式条目 |

## 6. 硬约束（违反即返工，详见 AGENTS.md）

1. brain 无状态、不碰实现层——checkpoint 与 brain 无关，别给 Brain 加任何东西。
2. 跨层传递一律 Pydantic；活对象（world/tools/brain/trace）永不进 state。
3. 装配只在 `build.py`；mock 与实现同一 Protocol。
4. 每步都有 trace；恢复本身也要留痕——建议新增 `TraceKind.CHECKPOINT_RESTORE`
   （28+1 个 kind，render 函数照 `trace_render.py` 现有模式补）。
5. 恢复成功的前后各一条 assert（AGENTS.md :132 的 postcondition 要求）。
6. 测试规则照 AGENTS.md 第十节；测试文件在 .gitignore，入库要 `git add -f`。

## 7. 验收标准（可执行）

```bash
# A. 恢复入口存在且走装配点（人工看 build.py）
# B. 集成测试：跑半局 → 保存 checkpoint → 全新实例恢复 → 续跑到 END
PYTHONPATH= C:/Users/GummiGu/.workbuddy/venvs/pokemon/Scripts/python.exe \
  -m pytest tests/test_checkpoint_resume.py -q
# C. event_id 跨恢复单调（新测试里断言恢复后续写 event_id > 恢复前最大值）
# D. 对账 assert 生效：手工把快照 step 改小，恢复必须炸
# E. ruff check pokemon_agent 不新增债务（既有 32 项旧账除外）
```

档位 A 的等价性判据：同一任务，"一口气跑完"与"跑 3 步→断→恢复→跑完"两条
trace 对比——决策输入（StepMemory 列表、goals、step 号）逐字段一致；
模型账（MODEL_CALL）条数恢复路径可多出 0 次（第 0 步不问模型的规则不受影响）。

## 8. 边界：明确不做

- 不做 checkpoint 历史（只存最近一次一致性点）；不做分布式/并发；
- 不做前端断线重连的 SSE 补发（event_id 单调是为它**铺路**，但补发本身另立项）；
- 不动 `TRACE_SCHEMA_VERSION`（3 不变；CHECKPOINT_RESTORE 走 payload.kind，不新增 type）；
- 不给 brain/`prompts/` 添加任何恢复相关逻辑。

## 9. 留给实现方拍板的判断点（拿不准就问用户）

1. 恢复入口形态：`run(resume=True)` 参数 vs 独立 `resume()` 方法——影响 API 层
   暴露方式；
2. 档位 B 的 checkpointer 选型：LangGraph `SqliteSaver` 够用（单进程、单文件），
   不要引入 Redis/Postgres 这类重依赖；
3. checkpoint 保存时机：每步存（档位 A 下 step 0 之外每步都会覆盖写一次
   checkpoint.json，文件小、可接受）vs 只在 episode 边界存（更省，但进程死在
   episode 中段时只能回退到上局末尾）——推荐前者，成本可忽略；
4. `_episode_is_complete()`（store.py:101）恢复场景下的语义是否要变；
5. run 级事件"episode_id 位放 run_id、step=0"的旧约定下，CHECKPOINT_RESTORE
   事件的 episode_id 位放什么（建议：run 级 checkpoint 放 run_id，episode 级
   放真实 episode_id）。

## 10. 本机环境坑（直接照做，详见 `docs/spec/tools/VERIFY_handoff_2026-09-07.md` §5）

1. **git 分支 ref 会被静默删除**：任何 commit 后检查
   `.git/refs/heads/feat/model-call-observability-and-providers` 是否还在；
   丢了就 `mkdir -p .git/refs/heads/feat && printf '<sha>\n' > <ref 文件>`（手工写文件，别用 `git update-ref`，同样会被回滚）。
2. 项目专用 venv：`C:/Users/GummiGu/.workbuddy/venvs/pokemon`（含 pyboy）；
   运行前 `export PYTHONPATH=""`。
3. heredoc 里 `\n` 可能被传输层写坏——改文件用 python `chr(10)`/splitlines。
4. ruff 用 `C:/Users/GummiGu/AppData/Local/Programs/Python/Python312/python.exe -m ruff`。
