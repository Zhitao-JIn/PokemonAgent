# Harness 技术规格说明

> **现状（2026-09-11）**：
>
> - **源文件**：`pokemon_agent/harness/episode_harness.py`（`EpisodeHarness` 类），
>   同目录还有 run 级的 `run_harness.py` 与 `brain_utils.py` / `game_utils.py` /
>   `memory_query_utils.py` / `run_plan_utils.py` / `trace_write.py`。
>   **0902 版本文档写的那份 `harness.py` 已经不存在。**
> - **图**：一局 **20** 个节点，状态载体 `EpisodeRunState`，LangGraph `StateGraph`；
>   两条分叉边 + 一条链内小循环。**权威描述在
>   `pokemon_agent/harness/interface/episode_harness_port.py` 的模块 docstring**
>   ——那里与代码同文件、离 `add_node` 最近，并且被 `scripts/check_graph_phases.py`
>   与观测台相位表（`web/src/App.tsx` 的 `CHAIN_PHASES`）机械核对。
> - **状态类**：`EpisodeRunState`，不再是 `LoopState`。
> - **逐节点对照表**（改哪处 state / 写哪条事件 / 一句话）：
>   `docs/spec/harness/PLAN_graph_readability.md` §4。
> - **本文档怎么读**：§2/§3 已按现状重写；§1/§4/§5/§6/§7/§8 保留 0902 原文并在节首
>   标注——那些节里"为什么这样设计"的论证（唯一性规则、`outcome` 为什么不进 state、
>   记账为什么跟着返回值走）与图有 6 个还是 20 个节点无关，重写等于把历史论证丢掉。
>   订正范围与依据见 `docs/spec/harness/PLAN_graph_readability.md` §1.2。

本规格基于源文件的实现与模块内嵌的设计说明整理，目标是让读者不用逐行读代码就能看懂
这一层的结构与事件流。

> **不再标注行号。** 上一版每个小节都挂着 `harness.py:295-334` 这样的坐标，
> 一次重构之后全部失效，而失效的坐标比没有坐标更糟——它会把人带到错误的地方。
> 按方法名索引，方法名改了这份文档也就该改了。

---

## 1. 模块定位与设计哲学

> 本节写于 0902 版（6 节点 / `LoopState` / `harness.py`）。结论多数仍成立，涉及图结构、字段名、方法名的表述以 §2/§3 与 `episode_harness_port.py` 的模块 docstring 为准。

### 1.1 为什么叫 Harness——一次改名的历史

以前叫 `harness` 的那个类，实际上是**工具层**（大脑怎么碰环境）；真正在做控制循环的是图的装配代码。旧名字掩盖了这个事实，导致"一步"这个概念**没有唯一的主人**——`world` 在数 step，旧 harness 在猜边界，图在决定什么时候算一轮，三方各自维护一份，最终需要"按步去重来对账"。

改名 + 重构之后只剩两个角色：

- **`LoopState`** 拥有"这一局跑到哪了"。`step` 在这里盖章，别的角色只读不写。
- **`Harness`** 拥有生死判断与记账职责，**自己不持有任何状态字段**（`__init__` 只挂 `game`/`memory`/`brain`/`trace` 四个端口、`run_id` 和编译好的 `_graph`）。

### 1.2 唯一性规则

1. **`LoopState` 拥有"这一局跑到哪了"**：`step`/`goals`/`succeeded`/`why` 全在 `LoopState` 里流转，不是 `Harness` 的实例字段。
2. **`Harness` 本身无状态**。
3. **只有 Harness 写 trace**。大脑把账（`ModelCall`）连同结果一起交出来，由 Harness 翻译成事件。判定器碰不到自己的账不是特权设计，而是所有大脑调用的共同处境——凡是要花钱调模型的组件，记账权一律收归 Harness。

   **"唯一写"不等于"唯一拼"**：`Harness` 只调 `self._trace.append(*trace_utils.xxx(...))`；把领域对象翻译成 `append()` 的五元组，委托给纯函数模块 `pokemon_agent/trace/utils.py`。调用点（"这一步该不该记、记成哪类事件"）留在 Harness，组装点（"记的话该长什么样"）在 `trace_utils`。

### 1.3 状态为什么全在 LoopState 里——判据是"会不会影响下一个 prompt"

早先按"活多久"分：单步流转的进 `LoopState`，`episode_id`/`task`/`step`/`succeeded` 当实例字段。理由是"图状态会被复制、合并、快照"，但那句话只对**活对象**（world/tools/brain/trace）成立；episode 的身份是**纯数据**，恰恰是 checkpoint 唯一需要的那部分。放在实例字段里，等于把"跑到哪了"存在 checkpointer 看不见的地方。

现行判据统一为**"它会不会影响下一个 prompt"**。据此 `LoopState` 收纳一局的全部可序列化状态，活对象一个都不进来。

### 1.4 光有 LoopState 还复现不了

恢复目标是"恢复 state + 恢复模拟器存档 = 接着往下跑"，还缺一样：

- **记忆库**：进 prompt，但既不在 state 也不在存档里。

**这里原来还有第二个洞：`world._facing`。** 朝向当时是从我们自己的动作历史推的，
不在 pyboy 的 save state 里，而它进 `facts`、进 prompt。现在朝向直接读 RAM
（精灵表 `+9`，见 `ram.read_facing`），存档里有它，洞自然没了——
world 不再持有任何推导出来的状态。

补法留给阶段 2 的 `Checkpoint`：`LoopState` + 记忆库 + 模拟器存档 + manifest。

两个概念要分清：**replay** 是不调模型、从 trace 里取 `raw` 重新解析（只需要 trace）；**resume** 是接着跑（需要完整 checkpoint）。

### 1.5 为什么还是 LangGraph 而不是 while

转移条件是显式的边，将来往中间插节点（状态归并、值回填、成本熔断）不需要改循环体。LangGraph 只承担循环调度与状态传递，记忆和状态表全部自研。

### 1.6 权限：`@initialize` 与横切的装饰器

`run()` 挂着 `agent_permission` 的 `@initialize`：每局开始前重新加载 `config/context.json` 与 `config/permissions.json`。权限检查本身以装饰器形式散在**工具层**（`GameTools`/`MemoryTool` 的每个方法）和**大脑**（`choose`/`judge`/`reflect`）上，不由 Harness 逐个调用——它是横切设施，不是循环的一环。

Harness 这一侧只承担一件事：**权限失败不能让这一局从 trace 里消失**。见 6.3。

### 1.7 还没做的

六件套目前有 trace 和权限确认（后者只到"装饰器 + 控制台审批"这一步）；缺沙箱、成本上限、checkpoint、replay。

> **订正 2026-09-12**：这句里的 **checkpoint 早已落地**（`EpisodeHarness.save_checkpoint()` /
> `resume()` + `tools/checkpoint_tool.py`，真机 `check_restore` 跑通）。当次写的时候确实缺。
> 现在实际缺的是**沙箱 / 成本上限 / replay** 三件（replay 的底座 trace 已在）。

### 1.8 `harness/` 里那些散件：边界是四列，不是文件名

> **本节写于 2026-09-12**，起因是"这些 `*_utils` 到底谁管什么"反复被问。
> 规则本身早就在各文件的模块 docstring 里、并且互不矛盾；散的是**它没有一个
> 统一入口说清楚**。本节就是那个入口。

harness 包 = 两张图（`episode_harness.py` / `run_harness.py`）+ 两张 Port
（`interface/`）+ 一层散件。**散件的归属由四件事决定，跟它叫 `*_utils` 还是别的没关系：**

| 文件 | 类型 | 绑哪张 Port | 属于哪层图 | 谁调它 |
|---|---|---|---|---|
| `brain_utils.py` | 依赖循环 | `BrainToolPort` | episode | `EpisodeHarness.think_action`（唯一） |
| `game_utils.py` | 依赖循环 | `GameToolPort` | episode | `EpisodeHarness` 感知三处（`_begin` 在图外） |
| `run_plan_utils.py` | 依赖循环 | `BrainToolPort` | run | `RunHarness.plan`（唯一） |
| `episode_utils.py` | 图算法 | — | episode | `EpisodeHarness`（终局结论 / 停摆 / 中止范围） |
| `run_utils.py` | 图算法 | — | run | `RunHarness`（目标栈 / trace 挑局） |
| `memory_query_utils.py` | 图算法 | — | episode | `EpisodeHarness`（检索 query 串三处） |
| `trace_write.py` | 写账共用件 | `TraceToolPort` | **跨两层** | 上面三个依赖循环的宿主 |

三条判据（都可机械核对，§1.8.2）：

1. **"依赖循环"与"图算法"的分界是 `import` 里有没有 `*ToolPort`。** 有 = 这个文件在
   替某一根依赖跑重试循环、只交回 `ModelCallLog`，**不写账**（"账写在它的宿主里"，
   `PLAN_graph_readability.md` §3.7.4）；没有 = 纯算状态，谁都不碰。
2. **episode 层与 run 层互不依赖。** run 层不越过 `EpisodeHarnessPort` 去拿 episode 的件，
   episode 层不知道 run 层存在。所以同名后缀的两个文件（`episode_utils`/`run_utils`）
   是**平行**的，不是上下游。
3. **`trace_write.py` 是唯一的第三类**，也几乎是全部困惑的来源：它绑了 `TraceToolPort`
   （所以不是"图算法"），但不属于任何一层图（所以也不是"某根依赖的循环"）——
   它服务的是**三个依赖循环的宿主**。第三类今天只有它一个成员。

**剩下三个文件不在这张表里，因为它们本来就不是 util。** 把它们往上面四列里塞，
塞不进去是正常的：

| 文件 | 正职 |
|---|---|
| `object_interactions.py` | **判定层**：按键 → 物体交互事件（"发生了什么、影响了谁"）。AGENTS.md §四那条分层原则的落地处 |
| `run_data_center.py` | **有状态的中间层**：一个 run 一个实例，前后端槽位。它不是函数集合，是个对象 |
| `auto_reviewer.py` | 默认放行者，装配点注入用 |

#### 1.8.1 已知的命名缺口（不是 bug，是会被误读的地方）

**命名只编码了"属于哪层图"，没有编码"是不是依赖循环"。** `game_utils` 与 `episode_utils`
从名字看不出一个是前者、一个是后者。所以**判断一个件该放哪，问的是"它绑不绑端口、
属于哪层图"，不是"它叫什么"。**

活证据是 `memory_query_utils.py`：名字暗示它绑 `MemoryToolPort`，实际它**一个端口都不
import**（它只从 `Observation`/`StepMemory` 拼检索串，端口调用在宿主那里），结构上跟
`episode_utils` 同类。它的 docstring 自己也这么写（"**不碰 `MemoryToolPort` 本身**"）——
即名字描述的是**它服务哪根依赖**，不是它绑了哪根。

#### 1.8.2 怎么机械核对

```bash
# 1. 六个 util 互不 import：每个的包内 import 里不该出现另一个 util 的名字
for f in brain_utils episode_utils game_utils memory_query_utils run_plan_utils run_utils; do
  grep -n "^from \." pokemon_agent/harness/$f.py
done                       # 期望：只有 .trace_write / .interface，没有平级的 util

# 2. 两层图各 import 自己那组，且 trace_write 是共用件
grep -n "^from \. import" pokemon_agent/harness/episode_harness.py pokemon_agent/harness/run_harness.py

# 3. 判定层只有 episode 层用（run 层不该出现）
grep -rn "object_interactions" pokemon_agent/harness/run_harness.py   # 期望 0 行
```

---

## 2. `EpisodeRunState`

> **本节是现状版（2026-09-11）**：随 `LoopState` → `EpisodeRunState` 一并重写。
> 字段的**权威定义**在同名文件的 `episode_harness_port.py`（状态类与接口同文件）。
> 本节只讲分组、形状与几个关键判据，不抄字段表——抄本会漂移，而字段表恰恰是漂移代价
> 最高的那种文档（0902 版这份抄本把 `succeeded`/`why`/`space`/`memories` 四个早已不存在
> 的字段名写了很久）。

`pydantic.BaseModel`，"一局的**全部**可序列化状态"。

### 2.1 分组

| 分组 | 字段 | 特点 |
|---|---|---|
| 身份 | `episode_id` / `task` / `step` / `goals` | 跨步存活，是 checkpoint 要恢复的那部分 |
| 流转 | `observation` / `action_space` / `action` / `pending_observation` / `step_episode_memories` / `global_episode_memories` / `knowledge_semantic_memory` / `object_semantic_memory` | 单步内，从一个图节点传到下一个 |
| 链 | `plan` / `pending_presses` / `pending_stop` | 链内小循环，跨 1..N 步（随 checkpoint dump，恢复后接着把链按完） |
| 判定 | `done` / `success` / `stall_key` / `stall_count` | 由 `judge` / `detect_stall` 写，其余格子只读 |
| 收尾 | `verify_step_entries` / `verify_knowledge` / `verified_steps` | 只在判完成的收尾链上有意义 |
| 结果（图外） | （不在 state 里）`FromRunHarnessToEpisodeHarnessRunResp` | 由 `run()` 在图跑完之后算出，见 2.3 |

### 2.2 字段的权威定义在哪

`pokemon_agent/harness/interface/episode_harness_port.py::EpisodeRunState`——每个字段都带
docstring，写清了"谁写它、什么时候写、别的格子怎么读"。**本规格不再抄一份**：
字段表是接口契约，只有一份能是对的。

### 2.3 这里**没有** `outcome`

与 0902 版结论一致：`outcome` 不在 state 里。它是这一局的最终结论，由 `run()` 在图跑完
之后从 `observation` 直接算出来。

放进 state 就得有个节点负责填它，而"下结论"不该是任何一个循环节点的副业——它曾经是
`_look`（一个叫"看一眼"的节点）顺手做的。更硬的理由见 6.4：`EpisodeOutcome` 和
`EPISODE_END` 的 payload 是同一份信息的两个形态，算在两个地方会静默漂移。

（0902 版这一节还讲过 `space` 与 `outcome` 互斥填充那个形状问题。现行版没有这一对：
`action_space` 只在没终止的分支上写，`outcome` 根本不在 state 里。）

### 2.4 `pending_observation` 的生命周期

**每一帧都由 `perceive_after_action` 从按键后的那次感知收下**，写进
`pending_observation`；本圈末尾的 `close_step` 把它扶正成 `observation`，当作下一圈的
`before`（两个 store 与 `detect_stall` 都在扶正之前读它，那是它们能看到 `after` 的唯一
窗口）。

开局那一帧不走这条路径——它由 `_begin` 直接产出成 `observation`（没有"上一步"，
不需要那道接力）。

0902 版的写入者是 `press`、扶正者是 `look`，字段名还叫 `press_result`。接力没变，
两端换了格子。

**观测的写入者是唯一的**：全项目只有 `perceive_after_action`（链内）与 `_begin`（图外，
第 0 步）会产出观测，harness 自己从不主动感知。

### 2.5 这里也**没有**帧账——但它跟着存档走

帧（base64 PNG）进不了 `Observation`，也进不了 state。harness 用两张实例字段记它：
`_frame_event_ids`（步号 → 承载这一帧那条事件的 `event_id`，截图文件名就是它）与
`_pending_frames`（还没挂上任何事件的那一帧的原图，只有第 0 步会非空）。

它们**不是 state**（进 `state_dump` 等于给每份存档都塞一张 PNG），但**必须跟着存档走**
（v6）：两张表都是纯内存态，`resume()` 是在新进程里构造的 harness，拿到的表是空的——
于是恢复后第一条 `OBSERVE`（链首要自带"大脑决策时看到的世界"）与恢复后第一个 store 步的
`before_frame` 会一起丢图。截图本来就在磁盘上（`screenshot/<event_id>.png`），缺的只是
"哪条事件承载这一步这一帧"这张对账。

所以 `save_checkpoint` 把**本局切片**（`_frame_ledger`）打进存档 json 自己的两个键，
`resume()` 原样回载。代价只有第 0 步那一份存档多背一张 PNG——真机实测一张 GBA 截图
2.7 KB、编成 base64 约 3.7 KB，而同目录的 `.state` 是 167 KB。v6 之前写的档没有这两个键，
读回时按空表处理，那正是"这份存档没带帧账"的准确语义。

---

## 3. 图结构

> **本节是现状版（2026-09-11）**：0902 版描述的是 `harness.py` 的 6 节点直线图，
> 那个文件已不存在。现行是 `episode_harness.py` 的 **20** 节点图。
> **拓扑的权威版本在 `episode_harness_port.py` 的模块 docstring**（接口即图：20 个节点
> 方法就是 20 个节点），并被 `scripts/check_graph_phases.py` 与
> `web/src/App.tsx` 的相位表逐条机械核对。

### 3.1 顶层形状

```
save_checkpoint → record_observation → judge ─(done)→ 收尾链(3 节点) → END
                                        └─(否)→ get_action_space
  → 四路 retrieve → merge_retrieval → think_action
  → act → perceive_after_action → apply_stop → detect_stall
  → store_step_episode_memory → store_object_semantic_memory → close_step
       ├─(pending_presses 非空)→ act          ← 链内小循环：一个小 action 一步
       └─(队列空)→ save_checkpoint
（回到 run()）EPISODE_END
```

三条与 0902 版的结构性差别，每条都是"**一次决策摊薄成 N 步**"这条设计的结果：

1. **`step` 是一个小 action。** 一次决策交出的链被展开成 `pending_presses`，链内每按一个
   键走完一圈、各写一条 `StepMemory`、各判一次中止；队列空了才回链首重新决策。
   链内小循环只加一条条件边、**不加节点**——`save_checkpoint` 因此仍只落在链边界上。
2. **账写在它的宿主里。** 每个节点写自己那条账；三个 `*_utils`（`brain_utils` /
   `game_utils` / `run_plan_utils`）只跑重试循环、只交回尝试材料（`ModelCallLog`），
   不碰 trace。规则来自 v7（`PLAN_graph_readability.md` §3.7.4）。
3. **"世界层的信号"与"harness 的终止裁决"拆成两个字段。** 0902 版只有一个
   `obs.done`，`judge` 一跑就用 `model_copy` 把世界信号覆写成自己的结论，事后分不清
   哪个是哪个。现在 `Observation.done` 只读（世界窗口关没关），
   `EpisodeRunState.done` / `success` 由 `judge` 独占写入。

### 3.2 节点表

见 `PLAN_graph_readability.md` §4 的**节点职责对照表**——20 行，"改哪处 state / 写哪条
事件 / 一句话"三列，第 9 行已按现状用 `merge_retrieval`。

（0902 版这里那张六行表写的是 `look` / `retrieve_memory` / `think` / `press` /
`remember` / `summarize`——这六个节点名现在一个都不在图上。）

### 3.3 边

**只有两条分叉边 + 一条收尾链内部的条件边，其余全是固定边。**

- **入口**：`set_entry_point("save_checkpoint")`。
- **`judge` 出口**：`state.done` → `retrieve_verify_step_memory`；否则 →
  `get_action_space`。这是**终止分支**，也是图上唯一决定"这一局还继续不继续"的地方。
- **`close_step` 出口**：`state.pending_presses` 非空 → `act`；否则 →
  `save_checkpoint`。这是**链内小循环**的分叉口。
- **`retrieve_verify_step_memory` 出口**：`verify_step_entries` 非空 →
  `retrieve_verify_knowledge`；为空 → **直接 `END`**。没有 step 记忆就没有可校验、
  可蒸馏的东西，不问模型——**不存在"不经校验的全量蒸馏"那条兜底路径**
  （见 §5 的两条"明确不做"与 `ROADMAP.md:1136` 的就地订正）。
- 其余相邻节点之间全是固定边。

### 3.4 ASCII 图

以 `episode_harness_port.py` 模块 docstring 里的那张图为权威版本——它与代码同文件、
离 `add_node` 最近，改图的人先看到它。0902 版这里那张六节点 ASCII 图不再保留。

### 3.5 为什么 `merge_retrieval` / 两个 store / `verify_and_summarize` 是独立节点

**图结构本身要能一眼看出三条规则**，不用读代码（0902 版那三条的现状版）：

| 规则 | 图上的体现 |
|---|---|
| 每一步先查记忆再决策 | 四个 `retrieve_*` 固定挂在 `judge` 与 `think_action` 之间；`merge_retrieval` 只做汇聚 |
| 只有推进世界的那一步才写记忆 | 两个 store 只跟在 `apply_stop` 后面 |
| 一局只在结束时蒸馏一次经验 | `verify_and_summarize` 只在 `judge` 的终止分支上 |

四个 `retrieve_*` **不各自记账**：四路的结果要齐了才能写那一条合并读
（`merge_retrieval` 的 `MEMORY_READ`），拆成四条会让人以为它们发生在循环的不同位置。

`verify_and_summarize` 独立成节点还有一条单独的理由：**它要调一次模型**。藏在收尾逻辑里
的时候，图上看不到"这一局结束时还额外烧了一次调用"，读图的人会以为一局的开销就是
`steps × (感知 + 决策 + 判定)`。**图上看得见的东西才会被算进成本。**

（0902 版这一节讲的是 `retrieve_memory` / `remember` / `summarize` 三个节点、
以及"`summarize` 独立成节点"。`summarize` 在 0906 已被合并进 `verify_and_summarize`，
"一进一出、净数不变"那句也随之作废。）

### 3.6 收尾为什么不在图里

与 0902 版结论一致，理由不变：`EPISODE_END` 写在 `run()` 里，正常结束与异常终止**都**得
写这条事件——写在 `run()` 里两条路径才共用同一个出口；分散到图内图外各写一次，迟早有
一条路径漏掉，而那些局会直接从成功率的分母上消失。

现状多了两个"图外的记账点"，同一条理由：

- `resume()` 写 `CHECKPOINT_RESTORE`（恢复接缝）。
- `run()`/`resume()` 的异常路径写 `EPISODE_ERROR`。
- 与 `CHECKPOINT_RESTORE` 对称的存档端接缝是 **`save_checkpoint` 节点**里的
  `CHECKPOINT_SAVE`（v7 新增）——存档点在事件流里也要可见，否则 replay 只能反推存档
  文件的 step 来切段。

---

## 4. 逐节点方法详解

> 本节写于 0902 版（6 节点 / `LoopState` / `harness.py`）。结论多数仍成立，涉及图结构、字段名、方法名的表述以 §2/§3 与 `episode_harness_port.py` 的模块 docstring 为准。

### 4.1 `_begin(episode_id, task) -> LoopState`

**职责**：开一局：写下边界，重置世界，造出初始状态。**这里不观测**——观测是 `look` 的事，而 `look` 是图的入口。记忆**不清空**——跨任务复用经验正是要验证的东西。

**流程（顺序是刻意的）**：

1. **先写 `EPISODE_START`**（`Source.HARNESS`），payload 含 `goal`/`success_criteria`/`max_steps`。**`task_id` 不进 payload**——批次实验的分组键靠 `run_id` 前缀区分（`experiment/run_all_tasks.py`），run 级自主拆解目标的 `task_id` 是 harness 生成的序号（`plan-{run_id}-{i}`），本身不携带跨局可比的语义（`schemas/communication/run_plan.py`），两种情况都不该进 trace。

   **在做任何事之前就写。** 以前它排在 `reset()`/`save_state()` 之后，注释却声称"episode 的边界应该是这一局在事件流里看到的第一条事件"——那句话只在这两步都成功时才成立。`reset()` 要调模拟器和视觉模型，`save_state()` 挂着唯一那条 `approval_required` 的权限，两者都可能抛；抛在这一行之前的话，`run()` 的兜底只会补一条 `EPISODE_END`，事件流里出现一个没有开头的结尾，比彻底没有记录更难读。

   代价是"这一局可能一步没跑就结束了"，但那本来就是事实，`EPISODE_END` 的 `reason` 会说清楚。

2. `reset = self._game.reset(task)` 真实重置世界（通常含一次真实的开局感知）。
3. 对 `reset.calls` 逐条当场记账（`Source.PERCEPTION`），**不留到下一次 `_observe()` 才补记**。
4. 构造 `LoopState`，`goals=[Goal(goal=task.goal, criteria=task.success_criteria)]`——栈底是任务目标本身，"它永远在，也永远是成败的唯一依据"。

**trace 事件**：`EPISODE_START` ×1（先）→ `MODEL_CALL`（+ 可能的 `ERROR`）×若干，均 `step=0`。

### 4.2 `_look(state) -> dict`

**职责**："每一步都从这里开始。"调 `_observe(state)` 拿到 `(obs, goals, succeeded, why)`，写回 state。

开局那一帧也走这里（它是图入口），所以"起点存档就已经满足判据"的 episode 会在第 0 步就被判出来，一步都不用走——不这样的话这类局会白跑满步数，而成功率里少掉的正是最容易达成的那些。

**返回值是状态增量，不是"结果"**：LangGraph 的节点约定（CLAUDE.md 第五节）——返回的 dict 只放**这一步改了哪些字段**，由 LangGraph 合并进 `LoopState`，没写进去的字段保持原样。

```python
update = {"observation": obs, "goals": goals, "succeeded": succeeded, "why": why}
if not obs.done:
    update["space"] = self._game.get_action_space()
return update
```

只有"接着跑"那条分支多带一个 `space`（`think` 要用）；终止那条什么都不多给——**这一局的结论由 `run()` 算**。

`space` 直接来自工具层：`intents` 那一层没有了（`ActionSpace` 里连这个字段都删了），Harness 不再覆写它。

**trace 事件**：不直接写，全部委托给 `_observe`（及它调用的 `_judge`）。

### 4.3 `look` 出口的路由

判据是 `"summarize" if state.observation.done else "retrieve_memory"`，写在 `_compile()` 里
`add_conditional_edges` 的内联 lambda 上，是图上唯一的终止分支。**不直接连 `END`**——
终止要先经过蒸馏。不写 trace。

### 4.4 `_retrieve_memory(state) -> dict`

**职责**：这一步**全部的记忆读**都在这里发生。图上单独一格，是"查记忆"唯一的入口。

**流程**：

1. `memories = self._memory.query_episode_steps(episode_id)`——**这一局**全部的单步情景记忆，按 `step` 升序，**不做相关性排序、不截断**。
2. `known = self._memory.query_objects(obs)`（语义记忆·object，按坐标筛）；非空则折进 `obs.facts["known_objects"]`。
3. `knowledge_result = self._memory.query_knowledge(query=task.goal, limit=MEMORY_RECALL_LIMIT)`（语义记忆·knowledge，和坐标无关的通用先验，走混合检索）；非空则折进 `obs.facts["knowledge"]`。
4. 若 `obs.place` 非 None，用 `map:.. | scene:.. | overlay:..` 拼出 `scene_key`，`self._memory.query_episode_summaries(scene=scene_key, query=task.goal, limit=EPISODE_MEMORY_RECALL_LIMIT)` 取跨局摘要记忆；非空则折进 `obs.facts["episode_memories"]`。
   - 查询词用 `task.goal` **而不是当前快照**：`EpisodeMemory.render()` 里压根没有位置/地标这些字段，拿快照去比只会一条都选不中。
5. 写一条 `MEMORY_READ`。

**为什么四种读都折进 `obs.facts` 而不是各开一个字段**：对 `think()` 而言它们和 `walk_map`/`landmarks` 一样，都是"当前状态的一部分"，这样不用动 `decide_action.md` 的 `$facts` 渲染逻辑。

**为什么不放在 `_observe()`（`look` 节点）里**：它们是记忆的读，不属于"看一眼"。这不只是分类洁癖——早先塞在 `_observe()` 里时，`knowledge` 会在 `_judge()` 跑之前就出现在 `obs.facts` 里被判定模型看到，白白花 token（判定本不该看这类字段，见 `brain/SPEC.md` 的 `JUDGE_BLIND`）。现在 `_judge()` 在 `_observe()` 内部先跑完，`retrieve_memory` 是后一个节点，判定模型天然看不到。

**常量**：`MEMORY_RECALL_LIMIT = 5`（知识库检索条数）、`EPISODE_MEMORY_RECALL_LIMIT = 3`（跨局摘要条数，比前者小：那是"别的局蒸馏出的经验"，本来就该比"这一局刚发生的事"占更少 prompt 篇幅）。

**trace 事件**：`MEMORY_READ` ×1（`Source.DECISION`）。检索发生在决策调用之前，事件顺序照实写——**因果顺序，不是排版偏好**。

### 4.5 `_think(state) -> dict`

**职责**：调大脑决策，把大脑交回的账翻译成事件。一次 `choose()` 可能因解析失败重试多次，所以这里产出的是一组事件。

三类事件分开写，因为它们回答不同的问题：

| 事件 | 回答 |
|---|---|
| `MODEL_CALL` | 每次尝试花了多少——失败的那几次同样烧了钱 |
| `ERROR` | 每次为什么失败——按 `kind` 聚合就是失败模式分布 |
| `THINK` | 最终选了什么 |

**流程**：`decision = self._brain.choose(goals, observation, space, memories)`（**不重新查记忆**，直接用 `state.memories`）→ 断言 `decision.calls` 非空 → 逐条记账 → 若 `decision.action is None` 写一条 `ERROR`（`kind="MaxRetriesExceeded"`）并 `raise MaxRetriesExceeded` → 否则写 `THINK`。

**抛异常的是这里，不是大脑**：大脑只汇报"一次都没解析出合法动作"，而"这一局是否因此终止"是循环的判断。

### 4.6 `_press(state) -> dict`

**职责**：按键，推进世界。**只管执行和账，不写记忆**；**`step` 也不在这里加**——`press → remember` 是一个整体，加一次的地方在链路末尾。

**流程**：`result = self._game.execute(action, before)` → 断言 `result.observation` 非空 → 对 `result.calls` 逐条记账（`Source.PERCEPTION`）→ 写 `ACT`（`Source.WORLD`，step 用 `before.step`）→ 返回 `{"pending_observation": result.observation}`。

**`before` 要交给 `execute()`**：它是这个动作据以选出的那份观测，工具层照它重算掩码
做校验。依据随参数传入，"用过期的掩码"在结构上不可能发生（见 `tools/SPEC.md` 2.6）。

**返回的观测就是下一步 `look` 要用的那一帧**，不是"顺便带回来的东西"。
`look` 不再自己感知，见 4.x `_observe`。

**一步交出去的是一整条动作链。** `Action.sequence`（`list[ActionSegment]`，每段是
"按哪个键 × 连按几次"）由**一次** `execute()` 整条交给 world，world 只在**链尾**感知一次。
所以一步之内的感知事件数**恰好是 1**，不再随按键次数增长——
走 5 格从 5 次视觉调用变成 1 次，成本和延迟一起砍到五分之一。
代价是链的中间状态 agent 看不见：撞墙了也会把剩下几次按完。这是时序抽象的经典取舍，
`MAX_TIMES` 是给它的闸。

**`ACT` 记的是结构化的链本身**（`trace_utils.action_chain()`，`think` 和 `act` 共用它，
所以"想按的"和"按下去的"能逐字段比对）：`sequence`(json) / `segment_count` /
`press_count`，外加给人读的一行 `action`（`up×4 -> down×2`）。

**这里曾经还记一个 `message`：** `ToolResult.message`，world 返回的一句"结果描述"。
它的字段说明写着"给 LLM 读的"，而全仓库唯一的消费方就是这条 `ACT` 事件；内容又只是
`observation.status`，紧接着还会作为下一条 `OBSERVE` 的 `status` 再出现一遍，
观测台上纯属复读。字段和 `trace_utils.act()` 的那个参数一起删了——现在签名是
`act(episode_id, step, action)`。**按完之后世界变成什么样，答案是下一条完整的 `OBSERVE`，不是一句转述。**

新观测**没盖过章**（`step` 恒 0），但 `remember` 只取它的 `Snapshot`——里面全是 facts，和步号无关。

### 4.7 `_remember(state) -> dict`

**职责**：把 `press` 刚推进的这一步写进记忆。

**流程**：

1. `entry = self._brain.reflect(before, action, after).model_copy(update={"episode_id": ep})`——`episode_id` 在这里盖章，因为大脑不知道自己在哪一局。
2. `self._memory.store_episode_step(entry)` + 写 `MEMORY_WRITE`。
3. `for note in self._memory.store_objects_interactions(before, action, after)` 逐条写 `OBJECT_NOTE`（可能一条都没有，见下）。
4. 返回 `{"step": state.step + 1}`。

**两类记忆分开写**：情景记忆记"我在那种画面里选了什么"（作用域是一次经过）；`OBJECT_NOTE` 记"地图39 x=2 y=3 那个人会说什么"（作用域是那一格，域内恒真、域会再现）。后者不需要模型判断——面朝哪一格由 `place + facing` 算出，两个输入都确定。

**动作链让这一类记忆多了一条"宁可不记"的规则**（在 `MemoryTool` 那侧，Harness 只是照单转记）：
多段链、以及单段但连按（`times != 1`）的移动，**一律不记**。这份档案的键是
「在哪一格按了哪个键」，而一条链的 `before`/`after` 是**整条链的两头**——中间路过了哪些格子、
哪一次按键才是撞在门上的那一次，这里都看不到。把 `up×4 -> down×2` 记成"在起点按了一次 up"，
写进去的是一条**假的尝试记录**。少记一条只是慢一点；记错一条会让它以后永远不再试那个正确的碰法。

所以链一长，这一步的 `OBJECT_NOTE` 数就是 0——**这不是漏记，是这一步确实没有可信的证据。**

**顺序不能换**：`ACT`（在 `press`）和 `MEMORY_WRITE`（这里）都属于第 n 步，`step + 1` 放在链路末尾，下一轮 `look` 写的 `OBSERVE` 才落在第 n+1 步。提前加一的话事件流的步号会往回跳。

### 4.8 `_observe(state) -> tuple[Observation, list[Goal], bool, str]`

**职责**：全项目**唯一**产出 `Observation` 的地方；读一帧，盖上步号与终止判断，判一次成败，记进 trace。

只有 `_look` 调它，所以"一步恰好一次"——这正是这一版不需要 `_traced_step`/`_judged_step` 那两个去重字段的原因：一步一次是**调用图的形状本身**保证的。

**终止的三个来源，这里全判了**：

- **步数用尽**——只有这一层知道走了几步。
- **世界不可用**（窗口被关）——world 自己置 `done`，这里保留。
- **目标达成**——问大脑，见 `_judge`。

**流程**：从 `state.pending_observation` 取出上一步交下来的那一帧 → 盖 `step` 和 `done` → 写 `OBSERVE` → `return self._judge(state, obs)`。

**这里不感知，也不记感知的账。** 曾经它调 `self._game.perceive()`，而那和上一步
`step()` 结尾感知的是同一帧——靠 world 内部的帧缓存挡住才没花两份钱。现在观测由
world 在 `reset()` / `step()` 的结尾产出、沿 `pending_observation` 传下来，一帧只
感知一次（完整论证见 `tools/SPEC.md` 2.7）。

副作用是**感知调用的账记在产生它的那一步**：第 N 步的观测由第 N-1 步的 `press`
感知出来，那条 `MODEL_CALL` 落在 `step=N-1` 下。这是对的——那次调用确实发生在
第 N-1 步。开局那一帧同理，由 `_begin` 记在 `step=0` 下。

`OBSERVE` 的 payload 含 `status`/`scene`/`overlay`/`facts`(json)/`goals`
（曾经还有 `frame_sha`，随帧哈希一起删了）。**`goals` 记的是判定弹栈之前的栈**——`OBSERVE` 必须先于本步的判定事件（因果顺序），判完之后的栈会在随后的 `GOAL_POP` 里体现。

字段名是 `status` 不是 `summary`：`Observation.summary` 改叫 `Observation.status` 了——
那一行是 scene + overlay 机械拼出来的**状态行**（`你在野外。对话框：「…」`），
不是画面描述。画面描述是视觉模型写的 `facts["overview"]`，叫 summary 会让人以为
"读这一个字段就等于看过这一帧"，而实质内容一直在 `facts` 里。

**`known_objects`/`knowledge` 不在这里拼**：见 4.4。

**事件顺序是因果顺序**：先记产生这一帧观测的那几次感知调用，再记观测本身，最后才是基于它的判定。反过来记的话，拿事件流做 replay 的人会先看到结果、再看到产生它的原因。控制台上排版不好看是**显示层的问题**，在显示层解决——不能为了排版去改事件流。

### 4.9 `_judge(state, obs) -> tuple[...]`

**职责**：**判栈顶那一条。完成就出栈。**

**算法**：

1. **早退分支**：若 `state.succeeded` 已为真，直接返回 `(obs.model_copy(done=True, success=True), state.goals, True, state.why)`。当前图内走不到（判成成功的那一步同时置了 `obs.done`），但 resume 会：从一个 `succeeded=True` 的 checkpoint 恢复时，不打标记的话 `look` 的条件边不去 summarize、转而进 `think`，而那时 `goals` 已是空的，`brain.choose` 的 `assert goals` 会当场崩掉。
2. `history = self._memory.query_recent_steps(episode_id, JUDGE_HISTORY)`。**订正 2026-09-12**：粒度下沉到单键后这里改成「按键数上限取回 → `last_chains(recent, JUDGE_CHAIN_HISTORY)` 按链裁到最近 2 条」，常量也从 `JUDGE_HISTORY`（步）改名成分 `JUDGE_CHAIN_HISTORY` / `JUDGE_HISTORY_KEY_CAP`。
3. `verdict = self._brain.judge(goals[-1], obs, history)`。
4. 写判定的账（`Source.JUDGE`），`depth = len(goals) - 1` 塞进 payload。
5. 未完成 → `return obs, goals, False, ""`。
6. 完成 → 写 `GOAL_POP`（`reason="done"`）→ `remaining = goals[:-1]` → 若 `remaining` 为空（栈空 = 任务完成）返回 `(obs.model_copy(done=True, success=True), remaining, True, verdict.why)`；否则返回 `(obs, remaining, False, "")`。

**两个补充规则**：`obs.done` 不是跳过判定的理由（那里的 `done` 是"步数用尽"，而任务完全可能恰好在最后一步达成）；判过成功之后不再问（结论不会反悔）。

**判定的账单单独记**（`Source.JUDGE`）：它和决策各自烧 token，混在一起就说不清"成功率这个数字本身花了多少钱"，也算不出判定器自己的失效率。判定失败会顺带补一条 `ERROR`——"判了没完成"和"根本没判出来"必须分得开，否则判定器坏掉时表现就是成功率悄悄变成 0，而没人知道为什么。

### 4.10 `_summarize(state) -> dict`

**职责**：图上的最后一格，把这一局蒸馏成一条跨局摘要记忆。

`success`/`steps` **直接从 `state.observation` 读**，不经过 `EpisodeOutcome`。

**为什么是这里、而不是每一步**：单步情景记忆和语义记忆（object）才是每步在 `_remember()` 里落盘的那两类；跨局摘要记忆的**检索单元是一整局**，自然也只在一整局跑完之后蒸馏一次。

**只吞 `ValueError` 这一种失败**：蒸馏解析不出合法结构时 `EpisodeMemoryGenerator.generate_summary` 抛 `ValueError`，且已在内部留了一条 `ERROR` trace 事件。**单据齐全才吞**——那条 ERROR 是它出现在失败模式统计里的凭证，没有凭证的静默吞掉就是在丢数据。吞掉是因为蒸馏失败不该拖累这一局本该正常记的 `EPISODE_END`：这一局确实跑完了，只是没能力提炼经验，这是两件事。别的异常照常往上抛。

**`EPISODE_END` 不在这里写**——它在 `run()`。

---

## 5. 目标栈

> 本节写于 0902 版（6 节点 / `LoopState` / `harness.py`）。结论多数仍成立，涉及图结构、字段名、方法名的表述以 §2/§3 与 `episode_harness_port.py` 的模块 docstring 为准。

`goals` 这个栈的形状留着，但**这一版它恒为一层**：栈底是任务目标，而压栈的唯一途径 `push_goal` 已经删了。**当前目标永远是栈顶**（`goals[-1]`），判定只判它，完成就出栈；栈空 = 任务完成，只有这一条路径写 `success`。

`if not remaining` 在只有一层时永远成立。留着它不是为了当下分支，而是把"只有任务目标本身完成才算成功"写成代码——子目标回来之后，agent 自己压的那些完成了只该弹栈，不该给自己发奖状。

### 5.1 这里曾经有一套多层并发判定

`_judge_all` + `reason="superseded"`：每层各判一次（`ThreadPoolExecutor` 并发发出），最深的那条"已完成"连同它上面的全部出栈。前提是**栈会长起来**，现在不会。

对一层的栈来说，"每层各判一次"和"判栈顶"是同一件事，只是前者还额外背着一个线程池、一段"模型调用并发但写 trace 不并发"的注意事项（`event_id` 必须单调，那是 SSE 断线补发的唯一依据），以及一个恒等于 0 的 `depth`。

当时那份权衡记在这里，**不留在代码里占位**——占位的抽象会把下一版往旧形状上带：

- **并发而不是把整栈塞进一次调用**：合成一次会丢掉**判定之间的隔离**（模型同时看到任务目标和子目标就会互相推理，"子目标完成了，那任务应该也快了"）和**可标定性**（单目标判定是干净的二分类 `(目标, 判据, 帧) → 0/1`，可以人工标注算准确率；合成一次后输出是长度可变的向量，而且同一份 prompt 在栈深 1 和栈深 4 下不是同一个东西，误差不再独立）。合并省的是 token，不是时间——token 那头由 prompt 的字段顺序解决（固定说明和画面在前、目标在最后，同一步内几次调用共享一大段前缀）。
- **不再有提前退出**：顺序版判到第一条完成的就停能省几次调用，并发版全判。用 token 换墙钟。

拆解机制在别处重写时，多层判定要不要回来、以什么形状回来，是**那时**的决定。

`goal_pop` 的 `reason` 字段留着（现在只有 `done` 一个取值）：拆解回来时"完成"和"白拆"仍然必须分得开，而那是判断目标栈到底帮没帮上忙的那个数。

### 5.2 常量

- `JUDGE_HISTORY = 3` —— 判定器能看到本局最近几步。**订正 2026-09-12**：代码里从来不是 3（是 2），且 0905 之后语义再次变过——现在叫 `JUDGE_CHAIN_HISTORY = 2`，单位是**链**（一次决策），另有键数帽 `JUDGE_HISTORY_KEY_CAP = 8`。不是 0：证据可能在三步以前那一帧的对话框里。也不是"全部"：判定是每步一次，条数一多成本就跟着步数增长。历史里**不含 `rationale`**（`StepMemory.render(reason=False)`）——发生过的事给判定器看，决策者对那件事的主张不给。

---

## 6. `run()` 整体流程

> 本节写于 0902 版（6 节点 / `LoopState` / `harness.py`）。结论多数仍成立，涉及图结构、字段名、方法名的表述以 §2/§3 与 `episode_harness_port.py` 的模块 docstring 为准。

`run(self, episode_id: str, task: Task) -> EpisodeOutcome`，`Harness` **对外唯一的入口**，挂着 `@initialize`（每局重载权限配置）。

**前置条件**：`episode_id` 非空；`task.max_steps > 0`（均用 `assert` 表达）。

**后置条件**：trace 里恰好多一条 `EPISODE_START` 和一条 `EPISODE_END`。

### 6.1 正常路径

```python
try:
    state = self._begin(episode_id, task)
    final = self._graph.invoke(state, {"recursion_limit": task.max_steps * 6 + 20})
except Exception as exc:
    self._trace.append(*trace_utils.episode_error(episode_id, task.task_id, exc))
    raise

final_state = LoopState.model_validate(final)
obs = final_state.observation
assert obs is not None and obs.done, "the graph must not end before the episode does"

reason = ("success" if obs.success
          else "max_steps_exceeded" if obs.step >= task.max_steps
          else "world_ended")
outcome = EpisodeOutcome(episode_id=episode_id, task_id=task.task_id,
                         success=obs.success, steps=obs.step, reason=reason)
self._trace.append(*trace_utils.episode_end(episode_id, outcome, final_state.why))
return outcome
```

**`recursion_limit` 怎么算**：一步走五个节点（look / retrieve_memory / think / press / remember），外加收尾的 `summarize`。`× 6` 留了一倍余量——递归上限撞上去的症状是一局无声截断，宁可给宽。这只是安全阀，真正的步数上限由 `_observe` 里 `state.step >= task.max_steps` 判定并触发 `done`。

### 6.2 `_begin()` 为什么在 `try` 里面

它调 `save_state()`，而 `execute:game:save_state` 是配置里唯一 `approval_required` 的权限。人类拒批或审批超时抛出来的异常要是从这里逃走，这一局**连 `EPISODE_END` 都没有**——正是 6.3 要防的"从分母上消失"。

### 6.3 异常路径：为什么必须补 `EPISODE_END`

不补的话这一局在事件流里永远"没有结束"：离线统计成功率时它既不在成功里也不在失败里，**直接从分母上消失**——而 `MaxRetriesExceeded` 恰恰是最该被记成失败的那一类。

记完照常 `raise`（不带参数，保留原始异常和堆栈）：这一局确实跑不下去了，吞掉只会让调用方拿到一个语义不明的空结果。

**权限失败不单开一个 `except` 分支。** 曾经有一个（catch `PermissionDenied` / `ApprovalExpired` / `ApprovalRejected`），函数体和兜底逐字相同——删掉它程序行为一个字节不变，它只是让人误以为权限失败已经被单独处理过了，于是这件事不会再有人回来做。将来真要按权限名聚合（"哪一项权限最常拦住 agent"），改的地方是 `trace_utils.episode_error()` 内部：那是"把异常翻译成事件"的纯函数的职责，不是控制流的。

> 补充：`agent_permission` 的四个异常类**各自直接继承 `Exception`，没有共同基类**，所以任何"列举权限异常"的写法都会在库新增异常类型时静默漏掉。这也是不列举、只用兜底的实际理由之一。

### 6.4 `outcome` 为什么在这里算

`EpisodeOutcome` 和 `EPISODE_END` 的 payload 是**同一份信息的两个形态**（`success`/`steps`/`reason` 逐字段对应）。算在两个地方，迟早不一致——而不一致时**没有任何东西会报错**：返回值说成功、事件流说失败，离线统计和调用方各信一半，要等到对账才发现。写在一起、从同一个 `obs` 派生之后，不一致在结构上就不可能。

不包成方法是因为它只有这一个调用方，而且是三行纯翻译；包起来只会让"这个数是怎么来的"多隔一跳。

出口断言是 `obs is not None and obs.done`（"图不该在这一局跑完之前结束"），不是"某个字段被填了"——后者才是真正要保的那条。

---

## 7. 模型调用记账机制

> 本节写于 0902 版（6 节点 / `LoopState` / `harness.py`）。结论多数仍成立，涉及图结构、字段名、方法名的表述以 §2/§3 与 `episode_harness_port.py` 的模块 docstring 为准。

账跟着 `PerceptionResult`/`ToolResult` 的返回值走，**不再靠 `drain_calls()`**：

| 来源 | 在哪记 | Source |
|---|---|---|
| `reset()` | `_begin` | `PERCEPTION` |
| `execute()` | `_press` | `PERCEPTION` |
| `choose()` | `_think` | `DECISION` |
| `judge()` | `_judge` | `JUDGE` |
| `reflect()` | 由 `MemoryTool` 内部产出，不经 Harness 记账 | — |
| 蒸馏 | 由 `EpisodeMemoryGenerator` 内部产出 | — |

旧机制的问题：`drain_calls()` 是"下次谁来取谁就顺手把上一步的账也记了"的隐式时机，账目会跨步错位。新机制要求每个产生调用的接口把 `calls` 随返回值交出来，调用方在**当场**完成记账。

`_observe` 不再出现在这张表里：它不感知，所以不产生任何模型调用记录。一步之内
产生感知调用的地方只有 `press`（开局那一步是 `_begin` 的 `reset()`）。

`execute()` 那一行的账**至多一条**：整条动作链交出去，world 只在链尾感知一次（见 4.6）。
"一步烧几次感知"因此和按键次数脱钩了——按成本读事件流时，`press` 那一格的
`MODEL_CALL` 数不再是"这一步按了几下"的代理指标。

**`trace_utils.model_call()` 是纯函数**：输入一个 `ModelCall`，输出 `list[AppendArgs]`（长度 1 或 2——失败时多一条 `ERROR`），调用方自己逐条 `append`。它不认识 `TracePort`、不做 I/O，可以脱离 Harness 单测。账单和失败模式是两件事：前者回答"花了多少钱"，后者回答"为什么没拿到东西"；混进一条里，按失败类型聚合时就得去解析 payload 里的字符串。

---

## 8. 一轮循环的事件时间线

> 本节写于 0902 版（6 节点 / `LoopState` / `harness.py`）。结论多数仍成立，涉及图结构、字段名、方法名的表述以 §2/§3 与 `episode_harness_port.py` 的模块 docstring 为准。

以"某一步、模型一次决策成功、执行后记忆库检测到语义记忆条目"为例（`n` 为本轮开始时的 `state.step`）：

| 顺序 | 事件 | 节点 | Source | step |
|---|---|---|---|---|
| 1 | `MODEL_CALL`（感知） | `look` → `_observe` | `PERCEPTION` | n |
| 2 | （可能）`ERROR` | 同上 | `PERCEPTION` | n |
| 3 | `OBSERVE` | `look` → `_observe` | `PERCEPTION` | n |
| 4 | `MODEL_CALL`（判定）×1 | `look` → `_judge` | `JUDGE` | n |
| 5 | （可能）`ERROR` | 同上 | `JUDGE` | n |
| 6 | `GOAL_POP`（仅目标完成时） | `look` → `_judge` | `JUDGE` | n |
| 7 | `MEMORY_READ` | `retrieve_memory` | `DECISION` | n |
| 8 | `MODEL_CALL`（决策）×N | `think` | `DECISION` | n |
| 9 | （可能）`ERROR`×失败次数 | 同上 | `DECISION` | n |
| 10 | `THINK` | `think` | `DECISION` | n |
| 11 | `MODEL_CALL`（感知，链尾一次）×0 或 1 | `press` | `PERCEPTION` | n |
| 12 | `ACT` | `press` | `WORLD` | n |
| 13 | `MEMORY_WRITE` | `remember` | `HARNESS` | n |
| 14 | `OBJECT_NOTE`×M（多段链或连按时 M 恒为 0，见 4.7） | `remember` | `HARNESS` | n |

之后 `step` 自增为 `n+1`，回到 `look`。

**终止那一轮**：事件 1–6 之后不进 `retrieve_memory`，改走 `summarize` —— `MODEL_CALL`（蒸馏）+ `EPISODE_MEMORY_WRITE`（蒸馏失败时是 `ERROR`），然后图结束，`run()` 写下最后一条 `EPISODE_END`。

**关键顺序约束**：

- `_observe` 内部：感知调用记账 → `OBSERVE` → 判定调用记账 → `GOAL_POP`（若有）。
- `retrieve_memory` 先于 `think` 的决策调用。
- `ACT`（`press`）与 `MEMORY_WRITE`（`remember`）标注同一个 `step`（`before.step`）；`step` 自增在 `remember` 末尾。
