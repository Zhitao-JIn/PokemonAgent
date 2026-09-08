# Harness 与模块解耦方案（tool 层接线 + TraceTool + utils 归位 + 协议改名）

> 状态：**v5，方案定稿**。v2 吸收 2026-09-07 评审意见：命名统一 PascalCase、
> req/resp 分文件、类名一起改、memory/game 协议一起纳入、明确"tool 管数据处理"
> 的分工语义。v5 定案 `trace/utils.py` 的 28 个转换函数进 TraceTool
> （tool 按 req.kind 分派渲染，判据见 5.2）。
> 定稿后按第八节顺序实施，每步一个 commit + 一条 CHANGELOG。

## 0. 现状结论（摸底结果）

1. **BrainTool 这一层已经建好，但悬空没人用。** `tools/brain_tool.py`（翻译壳）、
   `interfaces/tools/brain_tool_port.py`（`BrainToolPort`）、
   `schemas/communication/brain_tool_*.py`（5 对 req/resp）都在；
   但 `episode_harness.py` / `run_harness.py` / `brain_utils.py` / `run_plan_utils.py`
   全部直接持有 `BrainPort`，`build.py` 也是把 `brain` 直接注入两个 harness。
   **所以任务主体是接线，不是新建。**
2. `TracePort` 只有两个方法：`append`（七参数）+ `events`（类型 mask 读）。
   写者只有 harness；读者是 `api.py`（SSE 轮询）和 `evaluation/`（离线报表）。
3. `run_harness.py` 里没有任何权限降级逻辑——`permission_was_denied` 的唯一
   消费者是 `episode_harness.py`（其 docstring"跨两级图共用"与事实不符）。
4. `pokemon_agent/utils.py` 三个函数的消费者全部查清，见第 6 节表格。
5. memory/game 两根 tool 的通信协议面（grep 证实）：
   - memory：只有一对 req/resp——`MemoryKnowledgeQueryReq/Resp`；
     其余方法直接传领域对象（`StepMemory`/`EpisodeMemory`/`PlaceInWorld`），
     那些是存储层形状，**不属于通信协议，不参与改名**。
   - game：只有 `WorldPerceptionResp` 一个（world 产出，经 GameTool 原样
     传给 harness——今天两跳共用一个类，见第 4 节说明）。
   - 另发现 `memory_episode_summary.py` 名不副实：它是 **brain 问 LLM 蒸馏**
     的响应协议（`brain/brain.py` 解析 LLM 输出用），跟 MemoryTool 无关。

## 1. 分工语义（本轮确立，写给所有协议的 docstring）

```
harness：只负责组装——找到需要的字段，拼成 req（一个 Pydantic 模型）
tool   ：对 req 做处理——转换成模块原生输入（不用改就原样转发）
模块   ：只返回自己该返回的（裸领域对象 / 原生 resp）
tool   ：把模块返回处理成新的 resp——harness 拿到的 resp 形状由 tool 负责
```

推论：
- req/resp 类的**变更权在 tool 层**：harness 的字段需求变了改 req 的组装方；
  模块的返回形状变了，只有 tool 需要跟着改，harness 拿到的 resp 可以不动。
- 两跳协议（harness↔tool、tool↔模块）**类型故意不共用**——今天的翻译是
  逐字段原样对应，但类是两套，以后任一边单独变形状都不牵动另一边。
- 跨层传递一律 Pydantic 模型（铁律 4）——这是第 5 节 trace/utils 讨论的
  判据之一。

## 2. 命名规范（v2 修订）

**文件名 = 类名，全部 PascalCase，一文件一类。** 函数名里的下划线转成
驼峰（`choose_once` → `ChooseOnce`），req 与 resp 各自一个文件：

```
From{调用方}To{被调方}{函数名PascalCase}{Req|Resp}.py
```

调用方/被调方取**这一跳的双方**：harness→BrainTool 的决策协议是
`FromHarnessToBrainToolChooseOnceReq`；BrainTool→Brain 的同一决策是
`FromBrainToolToBrainChooseOnceReq`。光读 `schemas/communication/` 目录
就能读出"谁对谁说话、说的哪个函数"。

## 3. 任务一：BrainTool 接线（harness 从 BrainPort 切到 BrainToolPort）

BrainTool 现有实现**不动**（今天"处理"就是逐字段原样转发，符合第 1 节语义）。

| # | 文件 | 改什么 |
|---|---|---|
| 1 | `harness/episode_harness.py` | `__init__` 参数 `brain: BrainPort` → `brain_tool: BrainToolPort`；三个调用点换类型：`judge` → `FromHarnessToBrainToolJudgeReq`；`reflect` → `FromHarnessToBrainToolReflectReq`；`verify_and_summarize` → `FromHarnessToBrainToolVerifyAndSummarizeReq`（字段逐一对应，组装处只换类名）；import 行同步 |
| 2 | `harness/brain_utils.py` | `choose_with_retry` 签名改 `brain_tool: BrainToolPort`；`req` 类型改 `FromHarnessToBrainToolChooseOnceReq`；docstring 同步 |
| 3 | `harness/run_plan_utils.py` | `ask_planner_with_retry` 同上：`FromHarnessToBrainToolPort` + `FromHarnessToBrainToolPlanOnceReq` |
| 4 | `harness/run_harness.py` | `__init__` 的 `brain: BrainPort` → `brain_tool: BrainToolPort` |
| 5 | `build.py` | `new BrainTool(brain)`；两个 harness 改注 `brain_tool`；`Brain` 从此只在 build.py 出现 |

**验收**：`grep -rn "BrainPort" pokemon_agent/harness` → 0 行。

## 4. 任务二：协议类按方向改名（brain / memory / game 一起，含类名）

改名映射（`git mv` + 类名一起改；文件里若混有非协议类则拆出）：

| 旧文件 / 旧类 | 新文件 / 新类（= 文件名） |
|---|---|
| `brain_tool_decide.py` `BrainToolDecideReq/Resp` | `FromHarnessToBrainToolChooseOnceReq.py` / `...ChooseOnceResp.py` |
| `brain_tool_judge.py` `BrainToolJudgeReq/Resp` | `FromHarnessToBrainToolJudgeReq.py` / `...JudgeResp.py` |
| `brain_tool_reflect.py` `BrainToolReflectReq/Resp` | `FromHarnessToBrainToolReflectReq.py` / `...ReflectResp.py` |
| `brain_tool_verify.py` `BrainToolVerifyReq/Resp` | `FromHarnessToBrainToolVerifyAndSummarizeReq.py` / `...VerifyAndSummarizeResp.py` |
| `brain_tool_plan.py` `BrainToolPlanReq/Resp` | `FromHarnessToBrainToolPlanOnceReq.py` / `...PlanOnceResp.py` |
| `brain_decision.py` `BrainDecisionReq/Resp` | `FromBrainToolToBrainChooseOnceReq.py` / `...ChooseOnceResp.py` |
| `brain_verdict.py` `BrainVerdictReq/Resp` | `FromBrainToolToBrainJudgeReq.py` / `...JudgeResp.py` |
| `reflect.py` `ReflectReq` | `FromBrainToolToBrainReflectReq.py` |
| `verify_and_summarize.py` `VerifyAndSummarizeReq/Resp` | `FromBrainToolToBrainVerifyAndSummarizeReq.py` / `...VerifyAndSummarizeResp.py` |
| `run_plan.py` `RunPlanReq`/`BrainPlanResp` | `FromBrainToolToBrainPlanOnceReq.py` / `...PlanOnceResp.py` |
| `memory_knowledge_query.py` `MemoryKnowledgeQueryReq/Resp` | `FromHarnessToMemoryToolQueryKnowledgeReq.py` / `...QueryKnowledgeResp.py` |
| `world_perception.py` `WorldPerceptionResp` | `FromGameToolToWorldPerceiveOnceResp.py` |
| `memory_episode_summary.py` `MemoryEpisodeSummaryResp` | `FromBrainToLlmEpisodeSummaryResp.py`（**纠偏**：这是 brain 问 LLM 蒸馏的响应，旧名带 memory 是误导） |

三点说明：

1. **`WorldPerceptionResp` 的方向取 GameTool→World**：它是 world 的产出、
   `GameTools.perceive_once()` 原样转发给 harness——今天两跳共用一个类，
   是"tool 不用改就转发"的现状。哪天 harness 需要裁剪视图，就新增
   `FromHarnessToGameTool*Resp` 并在 tool 里做处理，harness 从此不认识
   world 的形状（这正是第 1 节语义的用武之地，现在不提前做）。
2. **嵌套模型不跟着改**：`StepVerifyVerdict`、`TraceEvent`、`StepMemory` 等
   是领域/存储形状或 resp 内嵌结构，不是某一跳的协议本体。
3. **本轮明确不做**（后续另议，见第 9 节）：providers 一跳的协议
   （`text_completion.py`/`vision_completion.py`——多调用方共用，方向命名
   需要先想清楚）与 harness 对外接口协议（`run_outcome`/`human_review`/
   `goals_edit` 等——调用方是 api 层，不是模块 tool）。

配套：`schemas/communication/__init__.py` 重写导出；全项目 import 方
（`tools/brain_tool.py`、`harness/*`、`brain/brain.py`）批量替换。

**验收**：`grep -rn -E "BrainToolDecideReq|BrainDecisionReq|RunPlanReq|MemoryKnowledgeQueryReq|WorldPerceptionResp|MemoryEpisodeSummaryResp" pokemon_agent --include="*.py" | grep -v __pycache__` → 0 行。

## 5. 任务三：TraceTool（新增，转换进 tool）+ trace/utils.py 退役（已定，见 5.2）

### 5.1 TraceTool 本体

| # | 文件 | 改什么 |
|---|---|---|
| 1 | `interfaces/tools/trace_tool_port.py`（新增） | `TraceToolPort(Protocol)`：`append(req: FromHarnessToTraceToolAppendReq) -> int` + `events(event_types) -> list[TraceEvent]`。docstring 写三件套 + 边界不对称性：**写者只有 harness（走本端口）；读者是 api/evaluation（运维侧，直读 TracePort，不进 tool 层）** |
| 2 | `schemas/communication/from_harness_to_trace_tool_append_req.py`（新增，文件名按第 2 节规范转 PascalCase） | 一个 req 模型：公共字段 `episode_id`/`step`/`kind: TraceKind`（新枚举，28 种事件各一个值）+ 领域对象可选字段（`obs`/`call`/`action`/`goals`/`memories`/`entry`/`outcome`/`why`/`depth`/`attempt`/`frame_png`/`screenshot_step`……按 kind 取用）。顺带把 trace 这条链补齐铁律 4（现在是裸五元组 tuple 穿层） |
| 3 | `tools/trace_tool.py`（新增） | `TraceTool(trace: TracePort)`：**内部按 `req.kind` 分派**到对应的私有渲染函数（原 trace/utils 的 28 个函数搬进来做转换：json 序列化、计数、条件字段、一拆多全在 tool）；每个渲染函数入口用 assert 表达该 kind 的必填字段（precondition）；渲染完 `self._trace.append(...)`，多事件 kind（model_call 补 ERROR）循环 append |
| 4 | `harness/` 全部 TracePort 消费者 | 类型换 `TraceToolPort`；原 `trace_utils.xxx(...)` 调用点改组装 req（挑字段 + 给 kind）后 `trace_tool.append(req)` |
| 5 | `build.py` | `new TraceTool(trace)` 注入两个 harness；`LocalTrace` 照旧返回给 api 侧读 |

### 5.2 trace/utils.py 去向——**已定：28 个转换函数进 TraceTool（tool 做转换）**

定案依据（用户分工语义 + 使用判据）：

1. **它是转换器不是组装器**：函数体内有 json 序列化（facts/segments/verdicts）、
   计数（press_count/chars）、条件字段（非空才记）、一次调用一拆多
   （账单 + 失败补 ERROR）——这些是"数据处理"，按"harness 只组装、
   tool 管转换"的分工归 tool。
2. **使用判据**：全部调用方是 harness，trace 自己（`store.py`）从不调用
   ——按"utils 只被自己的模块使用"，它也不该留在 trace/。
   两条判据同向：**进 tool。**

**为什么按 `kind` 分派、不按领域对象类型名（isinstance）分派**：同一个
类型产出不同事件——`ModelCall` 可以是决策账单（attempt）/判定账单
（depth/why）/校验账单（verdicts）；`StepMemory` 既出现在"读"（一批 +
知识库内容）也出现在"写"（单条）。类型名决定不了格式，"这笔账是什么账"
只有调用方知道——kind 由 harness 组装时给出，tool 拿 kind 分派渲染。
每个 kind 必填什么字段，在渲染函数入口用 assert 表达（precondition，
docstring 一一对应）。

**契约声明**：payload 字段是跨模块契约——`evaluation/eval_report.py` 按
字段名解析（`cached_tokens`/`verdicts`/`attempt`……），改字段名/增删字段
必须同步 evaluation。这条写进 `tools/trace_tool.py` 的模块 docstring。

- 代价：TraceTool 单文件约 +700 行（28 个渲染函数），超出 300 行拆分线时
  拆成 `tools/trace_tool_render.py`（渲染）+ `trace_tool.py`（分派 + append）；
  req 模型的可选字段较多，靠入口 assert 兜契约。
- 收益：harness 记账调用点变一行组装；trace/ 只剩 store.py，只依赖 schemas；
  转换规则有了唯一归宿（tool），铁律 4 合规，接口极小。

**验收**：`grep -rn "TracePort\|LocalTrace" pokemon_agent/harness` → 0 行；
`grep -rn "from pokemon_agent" pokemon_agent/trace | grep -v schemas` → 0 行
（trace/ 只剩 store.py，只依赖 schemas）；
`test ! -f pokemon_agent/trace/utils.py && echo dead` → 期望 dead。

## 6. 任务四：utils 归位（删除 `pokemon_agent/utils.py`）

判据一句话：**看"谁用它"决定它住哪——只服务一个模块的，搬进那个模块。**

| 函数 | 现消费者 | 去向 | 理由 |
|---|---|---|---|
| `strip_json_fence` | 仅 `brain/brain.py` | 挪为 `brain.py` 模块级私有 `_strip_json_fence` | 剥围栏是大脑输出解析职责的一部分；单消费者不值得独立文件 |
| `PERMISSION_ERRORS` + `permission_was_denied` | 仅 `harness/episode_harness.py` | `harness/episode_utils.py` | episode 层专用（grep 证实 run 层不用）；docstring 改为符合事实的表述 |
| `tag_attempt` | `harness/brain_utils.py` / `game_utils.py` / `run_plan_utils.py` | 新文件 `harness/tag_attempt.py`（文件名=函数名） | 跨 episode/run 两个消费者；**不能放 episode_utils**——run 层 import episode 层会破坏"两层图互不依赖"；也不能放 run_utils——同理反向 |
| `pokemon_agent/utils.py` | — | **删除** | 搬空后即死文件 |

- `memory/episode/util.py`：只服务 `episode_store.py`，符合原则，不动。
- `harness/*_utils.py` 现状已是"每根依赖一个文件"，符合原则，不动。
- `trace/utils.py`：按 5.2 定案退役，28 个转换函数进 `tools/trace_tool.py`（tool 做转换），随本任务一起改。

## 7. 任务五：边界验收清单（可执行，改完跑一遍）

```bash
# 1. brain 不碰任何实现层
grep -rn -E "from pokemon_agent\.(harness|tools|world|memory|trace|providers)" pokemon_agent/brain   # 期望 0 行

# 2. harness 只握 tool 端口，不认识 brain/trace 实现
grep -rn -E "\b(BrainPort|TracePort)\b" pokemon_agent/harness                                        # 期望 0 行
grep -rn -E "from pokemon_agent\.(brain|world|memory|providers)|LocalTrace" pokemon_agent/harness    # 期望 0 行

# 3. BrainTool/TraceTool 只在装配点 new
grep -rn -E "BrainTool\(|TraceTool\(" pokemon_agent --include="*.py" | grep -v __pycache__           # 只允许 build.py 与 tools/ 自身

# 4. 旧协议名已死（见第 4 节验收 grep）

# 5. 包根 utils 已死
test ! -f pokemon_agent/utils.py && echo dead                                                        # 期望 dead
```

另外两处文字工作：
- `tools/__init__.py` 的 docstring 重写——现状写着"没有 plan_tool、brain/trace
  不进这一层"，与本次改动直接矛盾。
- `CHANGELOG.md` 追加条目（tool 层接线 / 协议改名 / utils 归位），按四段格式。

## 8. 实施顺序（每步一个 commit）

| 步 | 内容 | 为什么排这里 |
|---|---|---|
| 1 | 任务四：utils 归位 | 独立、无依赖、改动面最小 |
| 2 | 任务二：协议改名（brain/memory/game + 类名） | 纯改名，趁 import 替换还没开始先做，后面接线直接用新名 |
| 3 | 任务三：TraceTool（转换进 tool） | trace/utils 28 个函数进 tool 按 kind 分派；依赖任务二的命名定稿 |
| 4 | 任务一：BrainTool 接线 | 主体改动 |
| 5 | 任务七：验收 grep + tools/__init__ docstring + CHANGELOG 收尾 | 兜底确认 |

每步之后：`ruff check . && ruff format .` + 跑 `tests/` 现有测试套
（端到端集成测试是装配路径变化的第一道验证）。
注：v1 把协议改名排在最后，v2 改为先改名后接线——接线本来就要动
import，一次改到位比改名、接线各改一遍 import 省一轮冲突。

## 9. 本轮不做、后续另议

1. ~~providers 一跳的协议改名~~ **已定（2026-09-07 用户拍板）：不改，
   保持 `text_completion.py`/`vision_completion.py` 这两个**——provider
   协议按能力命名（不按调用方），现状即终态。
2. harness 对外协议（`run_outcome`/`harness_episode_outcome`/`human_review`/
   `goals_edit`）：调用方是 api 层不是模块 tool，等 api 边界讨论时一起定。
