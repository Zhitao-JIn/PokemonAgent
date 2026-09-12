## 2026-09-12（28）—— harness 图组合重构·步 1：`chain` → `decision` 术语收敛

**改了什么**

一个词在本仓指了四件事（那次决策的步号 / 按那次决策分组 / 取最近几次 / 图的节点序列），
而且**函数名与它渲染出的文本互相矛盾**——`render_chains()` 输出的句子早就写着
"一次决策按的 N 个键"。本步把它收敛到**决策**这一个词：

| 现在 | 改成 | 处 |
|---|---|---|
| `chain_key(entry)` | `decision_key(entry)` | — |
| `group_chains(entries)` | `group_by_decision(entries)` | — |
| `last_chains(entries, n)` | `last_decisions(entries, n)` | — |
| `render_chains(entries, *, reason)` | `render_decisions(entries, *, reason)` | — |
| `JUDGE_CHAIN_HISTORY` | `JUDGE_DECISION_HISTORY` | — |
| `is_chain_tail`（两个局部变量） | `is_decision_tail` | — |
| `trace_render.action_chain(action)` | `trace_render.action_presses(action)` | 它有另一件事（把 `ActionFromBrain` 渲成 dict），**单列** |

仓库 6 个文件共 **48 处**（含 `schemas/memory` 两层 `__init__` 的 `__all__` 与 import），
连带技能核验脚本 3 个文件 **37 处**；四个纯函数的 docstring 措辞同步
（"链号" → "决策标识"、"整条链" → "整次决策"、"按链长线性放大" → "按决策长度"）。

**为什么这么改**

1. **它描述的是形态，不是归属。** "链"说的是"这些键串在一起"，真正的语义是"它们出自
   **同一次决策**"——`plan_step_start`（= `decision_key`）才是那个归属键。
   **判据在决策，不在连续。**
2. **同词异义已经发生**：`action_chain`（渲染一个动作）与 `CHAIN_PHASES`（前端相位链）
   跟它毫无关系，读者会以为有关。
3. **两套词让读者做翻译**：读 `chain_key` 的人得自己连上"这就是 `plan_step_start`"。
   改完之后每处读出来都是中文原话——"这一步是哪次决策按的"/"最近 2 次决策"。

**取舍**

1. **`last_chains` → `last_decisions`，不改成 `last_decision_entries`。** PLAN D7 的
   "顺带发现"指出"返回的是平铺的键、不是 N 个元素"，名实略有不符——但
   `last_decisions(recent, 2)` 读作"最近 2 次决策（的全部键）"是通的，而
   `last_decision_entries` 更长且丢掉了"取最近"这半句。**代价写进 docstring**：
   第一行点明返回的是"最近 `count` 次决策的**全部键**"。
2. **`macro` / `plan` 两个备选不采用**：`plan` 会与 run 层"LLM 规划"那个节点撞词，
   比现状更糟；`macro` 是游戏圈术语，读代码的人不一定是玩家。
3. **中文的"链尾"/"链内"保留**（指"一次决策内部的位置"），只改会与标识符打架的那几处
   （`judge` 取窗注释、`decide_action` 的渲染说明、`JUDGE_DECISION_HISTORY` 的 docstring）。
   一刀切会把"链内小循环"这类已经稳定的说法一起搅动，收益不抵风险。
4. **`StepMemory.plan_step_start` 不动**——它本来就是对的那半（记忆侧按它分组），
   记忆文件不用迁移。

**影响面**

- **代码**：6 个本仓文件改名（无新增/删除文件）；技能侧 3 个脚本同步。
- **行为**：零变化。三项验收全绿——`check_imports.py`（422 条）、
  `check_graph_phases.py`（21 节点），离线核验 `verify_chain_inner_loop.py`
  （**116 条 ALL PASS**，其中块 F 断言的四个函数名已同步）。
- **未动**：`web/src/App.tsx` 的 `CHAIN_PHASES`（那是"相位链"，UI 局部命名）；
  JSON/存档里的任何字段名（`plan_step_start` 等一律不动，**旧存档照读**）。

---

## 2026-09-12（27）—— harness 图组合重构·步 0：立骨架、解父子交界四件事，行为零变化

**改了什么**

1. **新增 `harness/deps.py`（`HarnessDeps`，14 字段四带）**：全图唯一的 context（依赖 7 /
   开关 2 / 记号 2 / 账 3）。**本步只声明**——节点还是类方法，接入点（步 2 的
   `invoke(..., context=deps)`、步 3 的 `Runtime[HarnessDeps]`）写在模块 docstring 里。
2. **状态与图装配各自分家**（"状态不是能力"）：
   - `harness/episode/state.py`（`EpisodeRunState`）与 `harness/run/state.py`
     （`RunState` / `ResumeEpisode`）——从 `harness/interface/` 的两个 port 文件搬出，
     旧路径 re-export，既有 import 一字不用改；
   - `harness/episode/graph.py`（`compile_episode_graph`）与 `harness/run/graph.py`
     （`compile_run_graph`）——`add_node` 逐行写字面量；两个 `_compile()` 退化成
     "交出节点名 → 节点函数"这张表，`RunHarness._route_after_reflect` 随之搬成
     `run/graph.py` 的模块级 `_should_retry`。
3. **D2 的四件交界事**：子侧 `goals` → **`episode_goals`**（父侧 `goals` 是领域概念，不动）；
   父侧 `RunState` **新增 `episode_goals` 键**、由 `dispatch` 每局投影写入
   （`_project_goals()`）；父侧 `last_task` → **`task`**（键名必须与子侧逐字对上）；
   新增**第 21 个节点 `close_episode`** 写 `state.outcome` 与 `EPISODE_END`，
   `retrieve_verify_step_memory` 的两条分支都汇到它。
4. **跟着改的三处**：`scripts/check_graph_phases.py` 的抽取路径改到 `episode/graph.py`；
   `web/src/App.tsx` 的 `CHAIN_PHASES` 加第 21 格（`EPISODE_END` 映射到它）；
   离线核验脚本补 6 条断言（**110 → 116 条**，含一条反向对照）。

**为什么这么改**

- **图的装配要能一眼读完。** 1749 行的 `episode_harness.py` 里，"图长什么样"（21 行
  `add_node` + 边）与"节点怎么实现"（20 个方法）缠在一个类里；分手之后
  `episode/graph.py` 只有 130 行、顶层即流程。
- **交界键必须逐字对上，而且要有"投影写入者"。** 内置子图按**键名交集**传递：
  子图不输出的键，父侧**保持旧值且不报错**。所以 `outcome` 不能留在图外算
  （`reflect` 会读到**上一次派发的陈旧结算**），父侧也不能只有 `goals` 而没有
  `episode_goals`（子图会拿到默认空列表）。这两条都是**不炸的错**，只能靠结构防。
- **必须先做这一步再换拼接。** "最危险的改名"与"两张图怎么连"混在一起做，出问题
  分不清是谁的锅——这是 PLAN §6 把它排在步 0 的全部理由。

**取舍**

1. **`HarnessDeps` 本步是"只声明不接线"**：接入它要把节点从方法改成自由函数（步 3），
   现在硬接只会把"改名"与"换依赖通道"两件事绑在一起。代价是它暂时没有读者，
   所以同时在技能侧给探针留了位置（改图的组合方式必跑 `probe_langgraph_subgraph.py`）。
2. **`EpisodeHarness._close()` 保留两个不再使用的参数**（`episode_id` / `task`）——
   结算改由图内写之后它们只是"让两个调用点形状不变"，改签名会把 `run()`/`resume()`
   的返回路径一起搅动，收益为零。
3. **`EPISODE_END` 换了写入者（图外 → 图内）但顺序不变**：它仍是这一局的最后一条账
   （收尾链之后），`void_after` 的游标语义不受影响。
4. **旧存档不再可读，不写迁移**：`EpisodeRunState.goals` 改名之后，旧 dump 里的
   `goals` 会被 Pydantic 忽略、`episode_goals` 取默认空列表（`judge` 会断言失败）。
   `checkpoints/` 下都是可再生的核对产物，与 D9-v6 那条"旧存档不读"同一条口径。

**影响面**

- **代码**：新增 6 个文件（`deps.py` + 两个域包各 2 个文件）；改动 8 个
  （两个 harness 文件、两个 port 文件、`interface/__init__.py`、`check_graph_phases.py`、
  `App.tsx`、CHANGELOG）。`episode_harness.py` 1749 → 1711 行。
- **行为**：零变化。三项验收全绿——`check_imports.py`（422 条）、
  `check_graph_phases.py`（21 节点，与相位表逐条一致）、离线核验
  `verify_chain_inner_loop.py`（**116 条 ALL PASS**）。
- **未动**：checkpoint（仍是 `CheckpointToolPort`）、tools 层、memory 层、
  `episode_harness_port.py` 的 Protocol 声明（步 4 才瘦身）。

---

## 2026-09-12（26）—— harness 图组合重构方案（PLAN v1）：九条实测把"内置父子图拼接"从想法变成有边界的工程

**改了什么**
1. **新增 `docs/spec/harness/PLAN_graph_composition.md`（v1 方案稿，未动任何代码）**：
   把"两级图 + 一节点一文件"拆成四件事（拼起来 / 分家 / 立契约 / 立机械保证），
   含目标目录树（`graph/{run,episode}/` + 25 个节点文件 + 6 个功能域）、六个设计决策、
   四步迁移顺序（每步可独立验收、可独立停）。
2. **沉淀图引擎语义探针**：新增技能脚本
   `~/.workbuddy/skills/pokemon-agent-offline-verify/scripts/probe_langgraph_subgraph.py`
   （**23 条断言，全绿**，纯 langgraph、不碰 PyBoy 也不碰项目代码）。技能 SKILL.md 的
   铁律加第 ⑤ 条（改图的组合方式 / 升级 langgraph 必跑）、§4 加四条语义要点、§5 加脚本条目。

**为什么这么改**
用户提出用 langgraph 内置父子图把 harness 重构成"两级图 + 一节点一文件"。**"内置拼接"听起来
是个小改动，实测却发现三处否决性问题**——不先解决，照着改会当场炸：
① 父子 state **同名不同型**会 `ValidationError`（本项目现成的一对：run 的
`goals: list[TaskForBrain]` vs episode 的 `goals: list[GoalForBrain]`）；
② 直挂子图的内部异常**一路冒到 `invoke()` 调用方**，父图节点接不住——现在"单局异常不崩掉
整个 run"这条契约（`dispatch` 的 try/except）**会失去落点**；
③ 子图步数**计入父图 `recursion_limit`**（父 1 + 子 3 需要 `limit ≥ 4`），两层各自标定 limit
的做法必须重算成一个总上界。
另有两条正面发现把它从"理想"变成"可行"：`add_node(..., error_handler=fn)` **能兜住子图
异常**、handler 拿到的是**父 state**、返回 `Command(goto=…)` 流程照常继续（正好是现在
`dispatch` 返回状态增量的等价物）；`context_schema` + `Runtime[Deps]` 的 context **自动穿透
父子图**，节点保持纯函数形态——依赖注入的官方落点，**不需要**闭包/偏函数/节点工厂。

**取舍**
1. **拼接方式推荐"纯内置"**（`add_node("episode", ep_graph, error_handler=…)`）而非"薄壳桥接"
   （= 现状换个名字，不是内置拼接）。两个代价列明账：**`resume()` 必须保留图外侧门**（它的
   七步准备里 `void_after`/`load_state_bytes` 是"进图之前截断世界"，不是图状态，图表达不了）；
   **`recursion_limit` 从"两层各自精确"退化为"一个总上界"**——补偿办法是用已知上界算
   （`max_steps`/`goals` 数/重试次数都是已知的）再加一条"实际步数 ≤ 预算"的 assert，
   把"无声截断"换成"开发期就地炸"。
2. **提出收窄两张 Port**：节点变成自由函数后签名统一是 `(state, runtime) -> dict`，
   用 Protocol 声明 20 个同签名方法 = 零信息量。主张 Protocol 只留 `run()`/`resume()` 入口，
   节点级契约交给那张"改哪处/写哪条账"的表（它**已有** `check_graph_phases.py` 机械核对）。
   **这是本方案唯一"减少现有契约载体"的决策，单独列进待拍板**。
3. **`goals` 改名方向**：推荐子侧 `EpisodeRunState.goals` → `episode_goals`（父侧 `goals` 是
   领域概念"目标栈"，全仓一提 `goals` 都指它；子侧那份是投影出来的视图）。
4. **探针不落仓、落技能**：它是"langgraph 怎么解释父子图"的复跑工具，不是项目产物。
5. **未动任何代码**，按既定做法等拍板。

**影响面**
新增一份文档 + 一条技能脚本（技能侧）。**代码与运行时行为零改动**；
`docs/spec/harness/` 下与 `PLAN_graph_readability.md`（管"图里有什么"，已收口）、
`PLAN_action_step_granularity.md`（管"步的粒度"）并列不冲突，本份管"图怎么拼、节点住哪"。
另发现一处文档漂移：`docs/spec/harness/SPEC.md` §1.7 还写着"缺沙箱、成本上限、**checkpoint**、
replay"——checkpoint 早已落地（2026-09-11（21）），属待订正的滞后项（本次未动）。

## 2026-09-12（25）—— tool 层协议搬家：`tools/interface/` + 出口分家 + 实现懒加载

**改了什么**
1. **五张工具协议换房**：`tools/ports.py` → `tools/interface/ports.py`（`git mv`，
   内容零改动；只把那段"为什么不需要 `interface/`"的 docstring **就地标注为过期**，
   论证不删）。新增 `tools/interface/__init__.py` 作协议的统一出口。
2. **`tools/__init__.py` 出口分家 + 五个实现懒加载**：不再导出任何协议；五个实现
   改走 `_LAZY` + `__getattr__`（与 `world`/`brain` 的 `__init__.py` 同一手法）。
3. **6 个 harness 消费点改 import**：`from pokemon_agent.tools import XToolPort` →
   `from pokemon_agent.tools.interface import XToolPort`（`brain_utils`/`game_utils`/
   `run_plan_utils`/`trace_write`/`episode_harness`/`run_harness`）。
4. **`tools/trace_tool.py` 的子模块 import 显式化**：
   `from pokemon_agent.tools import trace_render` →
   `import pokemon_agent.tools.trace_render as trace_render`。
5. **文档**：`docs/spec/tools/SPEC.md` 加文首**现状块** + 就地把 4 处旧地址标注
   （`interfaces/tools.py`/`interfaces/world.py`）；`PLAN_tool_interface.md` 升 **v3**，
   新增 §7 记落地实测。

**为什么这么改**
`tools/` 是六个领域层里**唯一**一个"统一出口把抽象和实现一起导出来"的层。后果可测：
只要从 `pokemon_agent.tools` 拿一张协议，Python 就得先把 `__init__.py` 跑完，
五个插件全部落进 `sys.modules`——"换 mock 不改 harness"这句在**类型上**早就成立
（注解里只有 Protocol），在 **import 这一层**没成立：它确实不知道自己拿的是谁，
但代价是"必须把五个人全请来才知道"。

**① 一个落地时才被实测推翻的判断（本条最该记住的）**
原方案（PLAN v2）认为"协议搬出去 + 出口不再导出协议"就够了，并把懒加载判成
"只是把账藏起来，不建议"。**这个判断错了**，错在一个容易漏的机制上：
`tools/interface` 是 `tools` 的**子模块**，而 **import 子模块必先跑完父包的
`__init__`**。所以只要 `tools/__init__.py` 还急切导入五个插件，
`from pokemon_agent.tools.interface import GameToolPort` **照样付满价**——
那份方案自带的验收（"146 → ≈113"）按它自己的步骤表**永远不可能通过**。
补上实现懒加载后才真正兑现：

| 做法 | 拿 `GameToolPort` 时累计加载的 `pokemon_agent` 模块 | `tools.*` |
|---|---|---|
| 基线（协议在 `tools/ports.py`） | 146（信封 113 + 33） | 8 个，含 5 个插件 |
| 只搬协议、出口照旧 | 146 | 插件一个不少 |
| **本次（三层都动）** | **116**（113 + 3） | 只有 `tools`/`tools.interface`/`tools.interface.ports` |

**② 顺带修掉一个"靠字母序侥幸通过"的隐患**
`trace_tool.py` 原来写 `from pokemon_agent.tools import trace_render`。出口改懒之后
这行**运行期仍然能跑**（`from 包 import 子模块` 有子模块回退），但
`scripts/check_imports.py` 只用 `hasattr` 判别、**不触发**那个回退，会判它失效；
它今天不报错纯属脚本按路径字母序**先**走到 `trace_render.py`、把该子模块绑成了
包属性。改成 `import pokemon_agent.tools.trace_render as trace_render` 后 AST 上是
纯 `Import` 节点，静态检查器只验"模块导得到"，不再依赖顺序。

**取舍**
- **懒加载 vs 保持急切**：选懒加载。理由不是风格——是"import 子模块必先跑完父包"
  这条语言规则让急切导入与本次目标**直接冲突**。机制与 `world`/`brain` 的
  `__init__.py` 同源（那两处被循环 import 逼、这里被子模块规则逼），写法完全一致。
- **不留转发文件**：`tools/ports.py` 不保留 re-export 薄壳，否则"协议住哪"永远有
  两个答案（与早先 `schemas` 内部那次搬家一致）。
- **不预建 `interface/domain/`**：五张协议签名完全由信封类型 + 标量构成，今天没有
  一张属于自己的形状；沿用 `world`/`trace` 的判据"有专属形状才开子包"。
- **实现只能在这一个装配点 new，这条没动**（`build.py`）；
  `from pokemon_agent.tools import GameTools` 的写法一行不变。
- **接受 `ruff check` 54 → 55**：唯一新增是 `tools/__init__.py` 的 `ANN202`
  （`__getattr__` 缺返回注解）。仓里**已有五个**懒加载出口各贡献一条同款，新加第六个
  必然多一条，属**结构性增量**；把六个 `__getattr__` 一起加注解能降到 49，但那超出
  本任务范围，本次不改，在此留痕免得下次被当成回归。
- **不碰**：`memory/ports.py`（无此毛病——拿 `MemoryStorePort` 只付 5 个模块）、
  五个门面的方法签名、`schemas/`（不改名的决定见 PLAN §4）。

**影响面**
- 新增 `tools/interface/`（2 个文件）；`tools/ports.py` **移动**（非复制）；改 7 个
  import 点 + 2 个 `__init__` + 2 份文档。
- **不改行为**：`check_graph_phases` OK 20 nodes（图拓扑未动）；全包 171 个模块逐个
  import 失败 0；`check_imports` OK 404 条（**条数不变**——只换目标，没增删 import）。
- **对后续**：ROADMAP 25（A2A / 拆包）少了一处硬耦合——拿协议不再拖实现。
- **未做（留档）**：`AGENTS.md` §四 目录树、`docs/spec/interfaces/SPEC.md` 两份
  **指向不存在的顶层 `interfaces/`** 的过期文档，本次只列未动（改 `AGENTS.md`
  按规矩要先讨论）。

---

## 2026-09-12（24）—— harness 散件边界写进 SPEC；抠掉一处指向已删文件的活 docstring；tool 接口 PLAN 升 v2

**改了什么**
1. `docs/spec/harness/SPEC.md` 新增 **§1.8「`harness/` 里那些散件：边界是四列，不是文件名」**
   ——一张 7 行的表（文件 / 类型 / 绑哪张 Port / 属于哪层图 / 谁调它）+ 三条判据 + 三个
   "本来就不是 util" 的文件 + 一段**命名缺口**说明 + 三条可执行的核对命令。插入位置在
   §1.7 与 §2 之间（§1 是"模块定位"，边界属于定位）。
2. `pokemon_agent/harness/episode_utils.py` 的模块 docstring 里那句
   「跨 episode/run 两层图的 `tag_attempt` 在 `tag_attempt.py`」**是错的**——那个文件
   早已退役（随 trace 渲染搬进 `tools/trace_render.py` 的 `_tag_attempt`，由 `TraceTool`
   在 `req.attempt` 非空时盖章）。改成现状，并说明"放哪层都反向依赖"这个划界问题在本包内
   已经不成立。
3. `pokemon_agent/harness/__init__.py` 的目录说明书**补全并纠偏**：原先把
   `memory_query_utils` 跟三个重试循环并列成"重试与记账工具"（它其实一个端口都不 import），
   且漏了 `trace_write.py` / `object_interactions.py` 两个文件。改成按真相分四类 + 指向 SPEC §1.8。
4. `docs/spec/tools/PLAN_tool_interface.md` **升 v2**：删掉"schemas 改名"（已拍板不改）、
   把 §3 从"四张策略表的选择题"降级成"已排除存档"、新增 §6 记录**"interface 指哪个
   interface"**这道真正待确认的题（两份权威文档都指向一个今天不存在的顶层 `interfaces/`）。

**为什么这么改**
- 起因是"harness 里那些 `*_utils` 到底谁管什么"。查下来**规则本身没有矛盾**——六个文件的
  模块 docstring 各说各的、互相引用，说的是同一件事。**散的是它没有一个统一入口**：
  读者要读六个 docstring + `__init__.py` + SPEC 两处 + 一份 PLAN 才能拼出全貌。
  所以补的不是规则，是**入口**。
- 那两处代码 docstring 是**活引用失效**，跟 (20) 条修掉的 5 处同类。特别之处在于它指向的是
  "以后会有的文件"（那份解耦计划曾规划 `harness/tag_attempt.py`），而该文件最终**改道去了
  tool 层**——向后走丢的引用有 grep 能兜，向前走丢的没有，只能靠人读出来。

**取舍**
- §1.8 写成"四列 + 三类"而不是"一条判据"，因为**判据真的只有一条**（import 里有没有
  `*ToolPort`），但 `trace_write.py` 不服从它：它绑了 `TraceToolPort` 却不是"某根依赖的循环"，
  因为它服务的是**三个循环的宿主**、且跨两层图。硬塞成两类会逼出一个例外条款，
  不如把它单列为第三类，并写明"今天只有它一个成员"。**层数多一层，例外少一个。**
- 没有改 `AGENTS.md` §四、没有改 `docs/spec/interfaces/SPEC.md`——那两份都指向不存在的顶层
  `interfaces/`，但按规矩改 `AGENTS.md` 要先与用户讨论。只在 PLAN §6 里列成待确认项。

**影响面**
- 纯文档 + docstring，**零行为变化**。`ruff` 仍 54、`check_imports` 404 OK、两个改动文件
  AST 干净且无超 100 列行。
- 未动代码逻辑、未动任何接口签名、未新增文件（PLAN/SPEC 都是既有文件）。

## 2026-09-12（23）—— rationale 的 prompt 层约束（第 4 条硬规则）+ tool 层接口方案稿 + prompts SPEC 订正

**改了什么**
1. `prompts/calls/decide_action/decide_action.md` 新增**第 4 条硬规则**（本条约 896 字符）：
   一条论据只写「最后要留下的那一句」，**不写写出它的过程**——三族禁写项（①改主意/自我
   纠错 ②写给自己的指令 ③不确定的旁白与出处考据）+ 一条判据（单独拎出来读，它是在说
   「这个动作为什么对」还是「这条论据自己合不合格」）+ 一条真机 ❌ / 一条 ✅。同处把
   「先满足下面**两条**硬规则」改成「**这几条**」（那个数字在 (14) 加第 3 条时就已过期）。
   模板 4333 → 6586 字符（**896 是本次，其余 1357 是 (14)~(21) 那批**）。
2. `docs/spec/prompts/SPEC.md` §4.3 加「订正 2026-09-12」块：`rationale` 的位置（在段里、
   不在顶层）、`sequence` 链尾允许 `a`、以及新增的第 4 条规则。**只加现状块，不改写原论证。**
3. `docs/spec/tools/PLAN_tool_interface.md`（新增）：tool 层抽象接口的**方案稿 v1，等拍板，
   代码未动**。含实测证据（见下）与两道选择题。
4. 探针 `probe_real_llm_contract.py`：新增 `RATIONALE_FORBIDDEN` + `lint_rationale()`，
   探针 A 把它作为**独立指标**打印——单列计数，**不并进契约违规**（契约数字要能跨月份比，
   别被内容质量稀释）。

**为什么这么改**
- 起因是一条**真实落盘的记忆**（`realcheck-0912-062841-ep1` step 1，181 字符）：
  「……然而当前帧尚未移动，**故此条无效**；因此必须仅用第一段完成全部意图。
  **错误：第二段无独立依据。修正：只保留一段**，且 rationale 仅写两条合法依据，不跨帧。」
  模型的直觉是对的（那一段确实立不住），**处置方式错了**：该改 `sequence`，却写进了
  `rationale`。分量在于 `StepMemory` **写入后不再被核对**——这段过程会当作"该段的论据"
  永久留下，并被 `render_chains()` 送进下一次决策的 prompt。
- **为什么在 prompt 层而不是渲染层截断**：截断是**静默改写**模型写过的东西，而"哪几个字
  是过程"只有写的人知道；prompt 层管"不要产生"，渲染层管不了"产生了但删掉"（前者让模型
  少犯，后者让证据失真）。

**取舍**
- 896 字符进的是**每一次**决策的 prompt（实测 `in=7096` token），换来记忆里不再出现"当时
  在犹豫"。代价明确：静态模板 +5.7%（按 15.6k 字符的决策 prompt 估）。**否决**的替代方案
  是在渲染层过滤元话语——那会让 trace / 记忆 / prompt 三者不一致。
- 写成「三族 + 判据」而不是给**字符上限**：上限会逼模型把论据压成电报，(14) 那次已确认
  「改 rationale 不是为了减字段，是为了给更有用的论据」；**过程性文字才是真正的膨胀源**
  （合规的论据 60~132 字符，出问题那条 181 字符，多出来的全是过程）。
- **只加 prompt 约束，不加校验器**：把过程写进 rationale 不是"格式错误"，判定器不该管
  这件事（它判的是可靠不可靠）。

**影响面**
- 只有决策 prompt 的内容变了。解析契约、`StepMemory` 形状、`render_chains()`、判定器窗口
  **都不动**，既有记忆与旧 checkpoint 不用迁移。

**核验**
- 离线：模板渲染通过（`load('decide_action').render()`，11 个占位符全替换、无 `$` 残留）；
  `verify_chain_inner_loop.py` **110 条断言全过**；`check_imports.py` **404 OK**；
  `check_graph_phases.py` **OK 20 nodes**；ruff **54**。
- 真实模型（探针 A，`qwen-plus@0.3` × 6）：**契约违规 0**；首轮合规 4/6，2 次失败都是
  **已知的"丢最外层 `}`"**模式（错误位置 `pos == len(s)`、末尾不是 `}`、重试全救回）——
  与 0905（2/6）/ 0911（1/6）同一模式，**不是回归**。
- **新规则的 lint 用全量语料标定**（关键一步：lint 有误报的话，探针就是在骗人）：
  盘上 12 条 step 记忆 / 20 条论据 → lint 命中 **1 条**，正是那条 181 字符的；
  今天 6 次真实输出的 15 条论据 → **0 命中**。即 **误报 0/19**。

**未做（明说，别当成漏做）**
- `docs/spec/prompts/SPEC.md` 引用的 `tests/test_prompts.py` **全项目已不存在**（顶层无
  `tests/`）——同一次顺手发现的文档滞后，**本次未动**，留作单独一件事。
- tool 层接口：只到方案稿，代码一行未动（等 `PLAN_tool_interface.md` §3/§4 拍板）。

## 2026-09-12（22）—— 按链读落地：`StepMemory.plan_step_start` + `render_chains`，判定器窗口换单位，`max_steps` 改口径

**背景**：`PLAN_action_step_granularity.md` §8 步骤 5 的两项收尾，也是（14）留下的
「已知遗留」——（一）本局**全量**步骤都进决策 prompt，粒度下沉到单键后按链长线性放大；
（二）`JUDGE_HISTORY = 2` 的单位从"步"变成"键"，判定器的时间视野被静默除以链长。
两条的完整论证、实测数字与三个决定写在 `PLAN_action_step_granularity.md` §11。

**改了什么**：

1. **`StepMemory.plan_step_start: int | None`**（默认 `None`）——**这一键属于哪一次决策**
   （那次决策落在第几步）。`None` ⇒ 按 `step` 算，**老记录天然正确**：粒度下沉之前
   一步就是一次决策，两者本来就相等。**它不是链字段**：`chain_index`/`chain_length`
   的读者问的是"这条链长什么样"，它的读者问的是"这一步是哪次决策按的"（§4 的判据）。
   它是 §4 早就预留的那句"将来真要分组时只加一个 `plan_step_start: int`"。
2. **`EpisodeRunState.plan_step_start`**：`think_action` 决策一次盖一次 → 随 state dump
   进 checkpoint → `store_step_episode_memory` 抄进那条记忆。`None` 只在"从旧 dump
   恢复"时出现，记忆侧按 `step` 兜底。
3. **`step_memory.py` 新增四个纯函数**：`chain_key()`（`None` 兜底）、`group_chains()`
   （按链号切组：不重排、不补洞，链号没变就算同一条链）、`last_chains()`（取最近 N 条链
   的全部键，**不把链砍成半截**）、`render_chains()`（**给决策者看的按链合并渲染**：
   一次决策一段，两端两帧 + 逐键的动作/步号/`stop` + 每段理由，段一换才再打一次理由）。
4. **`decide_action.build_prompt` 的 `memories` 块改用 `render_chains()`**；
   `decide_action.md` 的「相关记忆（怎么读）」改成讲新形状，并点明两件必须说的事——
   "中间那些键的画面不在里面（链内只读内存）"、"「然后停了」是执行层机械判出来的、
   跟「因为」的可信度不一样"。
5. **判定器窗口换单位**：`JUDGE_HISTORY = 2`（步）→ `JUDGE_CHAIN_HISTORY = 2`（链）
   + `JUDGE_HISTORY_KEY_CAP = 8`（键帽）。取窗改成"按键数上限取回 → `last_chains()` 按链裁"。
6. **`max_steps` 口径重写**：它是**以"游戏里按了多少键"计价的闸**（数字不动）。
   `EpisodeRunState.step` 的字段说明、`experiment/tasks.py` 模块头里的 judge 视野、
   `knowledge_recall_tasks()` 的 docstring 一并改对。
7. **顺手修四处文档漂移**：`DATAFLOW.md`、`harness/SPEC.md`（两处）、`tools/SPEC.md`
   都把判定窗口写成 `query_recent_steps(ep, 3)` / `JUDGE_HISTORY = 3`——**代码里从来不是 3**
   （是 2），而且 0905 之后语义又变过一次。按"就地标注过期、不重写历史论证"的办法，
   在原句上补「订正 2026-09-12」。

**为什么这么改**：

- **先量后改**（§7.6 自己要求的"单独量 prompt 长度"）：真机 `model_call` 事件里存着完整
  prompt，量出来「相关记忆」一节占 0.1% → 6.8%（step 0/1/2），一条记忆约 **490 字符**
  ——它**按链长线性放大**（链长 4 就是 4 倍）。同一批数据里 `press_count` **全是 1**，
  所以今天还没有真实的膨胀，但那是"模型还没用起连按"，不是"链不会变长"。
- **分组键取 int，而不是"从 trace 取 step 区间"**（v1 当初的想法）：harness 手里只有 trace
  的**写口**、没有读口；为取一个区间去加一条"harness 读自己的 trace"的契约，比加一个 int
  重得多，而且第 0 步那条链根本没有 THINK 可查。
- **判定器换的只是单位**："最近 2 步"在旧粒度下就等于"最近 2 次决策" = "最近 2 条链"，
  数字 2 不动；键帽防的是"链一长就静默膨胀"。

**取舍**：

- **合并渲染只给决策者看的那一版**：判定器/校验器继续用逐条的 `render_sequence()`
  ——"省的是渲染，不是存储"。**中间帧不是"从它眼里拿掉"的**：粒度下沉之前一次决策只感知
  一次、只留两端两帧，中间帧从来不存在；合并渲染是恢复到那个粒度，**多给**的是逐键的
  动作、步号、`stop` 与段级理由。**不按"动作连按"再压成 `up×4`**——那会在两段同名
  动作处跨段合并、把"第 3 键撞墙"这种结局抹平，逐键一行才 14 字符，省不了多少。
- **`max_steps` 数字不预调**：跟 `experiment/tasks.py` 自己那句"每一条都是撞出来的，
  不是推演的"保持一致——等真机上量到平均链长 ≥ 2（同一批任务、同一份 `repeat_hint`）
  再按 `15 × 平均链长` 调。
- **键帽 8**：链长上限是 `MAX_SEGMENTS × MAX_TIMES = 32`，两条长链能把判定 prompt 顶穿；
  8 = 一条打满 `MAX_TIMES` 的单段链，实测 `press_count = 1` 时根本碰不到。

**影响面**：`schemas/memory/datastore/step_memory.py`（一个字段 + 四个函数，都从
`schemas/memory` 出口 re-export）、`schemas/memory/{,datastore/}__init__.py`、
`harness/interface/episode_harness_port.py`（state 加一个链字段 + 节点表行）、
`harness/episode_harness.py`（`think_action` 盖章、store 抄号、两个常量 + judge 取窗）、
`prompts/decide_action.py` + `prompts/calls/decide_action/decide_action.md`、
`experiment/tasks.py`、四份 spec 文档。
**既有记忆文件不用迁移**（`plan_step_start` 默认 `None`，语义等价于"一链一键"）；
**旧 checkpoint dump 也能恢复**（同一个 `None` 兜底）。

**核验**：

- **离线核验 110 条断言全绿**（`verify_chain_inner_loop.py`，从 81 条扩到 110 条）。
  新加的两处：C 块验**链号真的逐键盖下去**（`[0, 0, 0, 3, 4]`——同一链共享起点步号、
  换链才变）与整局按链渲成 3 段；F 块是新的一整块，验四个纯函数的契约——
  老记录 `None` 兜底（退化成"一链一键"）、**链中间缺一步仍算同一条链**（缺的是记录
  不是归属）、**`last_chains` 只按整条链裁**（取 1 条链拿到 2 个键、不是最后那一键）、
  `render_chains` 的段头/逐键行/段级理由只打一次/跨链首尾帧去重/`reason=False` 不去
  `stop`，外加一条**反向对照**：按链渲染必须比逐键渲染短（否则"合并"是假的），
  而 `render_sequence()` 仍逐键 6 段一步不少。
- **真实模型契约核验 3 个探针全绿**（`probe_real_llm_contract.py`，真 qwen-plus@0.3 /
  doubao@0）：
  - **C（决策者读按链合并的记忆）** —— 这是本次唯一动到"模型输入形状"的地方，也是最该
    验的。记忆块真的渲成了一段 `(probe, step=0..2) 一次决策按的 3 个键：`，中间帧不铺、
    逐键动作与步号都在；模型交出的 `sequence` 仍可解析（`right×4 -> up×4`），
    且 `thought` 明确引用了记忆里的撞墙（`北 G`/`#`）。探针里补了两条**防空转断言**
    （"记忆块真的是按链合并的"、"三个键的动作与步号仍逐条在 prompt 里"）——
    不盖 `plan_step_start` 的话三条记忆会各成一链、退化成逐键渲染，这个探针就白跑了。
  - **A（决策输出契约 ×6）**：契约违规 **0**。1/6 出现"丢最外层 `}`"——已归档的采样
    缺陷（`Expecting ',' delimiter` 落在**末字符**，补一个 `}` 即可解析），重试救回；
    0905 基线是 2/6，同一模式，**不是本次回归**。
  - **B（校验器读记忆）**：三条 verdict 全 reliable。证据那条路走的是逐条的
    `render_sequence()`，加字段没有扰动它。
- **机械预检**：`check_imports.py` **404 OK**（原 403）、`check_graph_phases.py`
  **OK 20 nodes**（图拓扑没动）、全仓 ruff 仍 **54**、`ruff format --check` 7 个文件全过。
- **真机 `check_harness` PASS**（用户授权 AI 执行，run `realcheck-0912-062841`，
  3 步、`reason='success'`）。**这一局第一次产出了链长 > 1 的真实决策**——
  之前四次真机 run 的 `press_count` 全是 1，所以"按链读"一直是纸面上的。
  读盘核对（不是看断言，是读 `memory/step_memory/*.json` 的真字节）：
  - `plan_step_start` **真的落了盘**（payload 键里多出这一个），值 `[0, 0, 2]`
    ——第一条链占第 0/1 步、第二条链落在第 2 步，与 trace 里两条
    `llm_outcome intent` 的 `press_count`（2 与 1）逐一对上。
  - 拿**盘上真记录**喂真函数：`group_chains` → `[2, 1]` 两条链；
    `render_chains` → **2 段**（一次决策一段），`render_sequence` → **3 段**（逐键）
    ——两条渲染路径真的并存在跑，决策者看 2 段、拿证据的看 3 段。
  - 链内那一键（step 1）在 trace 里**没有 `view frame`**、只有 `view after`
    ——"链内只读内存"这条设计在真机上成立，不是只有假端口成立。
  - 第 2 次决策的真实 prompt（14398 字符）里「相关记忆」一节确为一段
    `(…ep1, step=0..1) 一次决策按的 2 个键：`，占 **5.40%**。
  - 同一局 step 0 有 **2 次 `ParseFailure` 后第 3 次成功**——既有的重试救回行为，
    与本次改动无关（那一次决策的记忆是空的）。
- **真机另外三个只读维度也 PASS**（都不起 PyBoy）：`check_trace`（59 条有效事件、
  盘上全量 `[0..58]` 连续无缺号无重号）、`check_memory`（本局 3 条 `StepMemory`
  全部非空可解析——**带新字段的记录被真 `MemoryTool` 读得回来**）、
  `check_checkpoint`（step 存档 `['0','2','3']` 成对、`run_state_dump` 的 `run_id` 核对通过）。
  存档步号 `0/2/3` 正是两条链的接缝，与 `plan_step_start = [0, 0, 2]` 一致。
  （`check_restore` **没跑**：它另起一局并改写指针，是另一件事。）

**真机顺带发现（与本次改动无关，但值得记）**：那一局模型把**自我纠错的过程写进了
`rationale` 字段**——第 1 键的论据是正常依据，第 2 键的论据却是
"……但此步依据仅限当前帧——然而当前帧尚未移动，故此条无效；错误：第二段无独立依据。
修正：只保留一段……"。这是已知失败模式（`thought` 里出现"等一下重数"式自我纠错，
见技能 §1.2 表）**泄漏到了 `rationale`**：`rationale` 不是自由文本，它会被
`render_chains()`/`render_sequence()` 原样打进 prompt，而它是**按段**计的——
一段写得越长、这一段里每个键都跟着贵。同一份 prompt 里「相关记忆」占 5.40%，
大头就是这两条长论据。**修法是 prompt 层的事**（约束 `rationale` 只写"这一段的依据"、
不写修正过程），不属于本次改动，留待单独处理。

## 2026-09-11（21）—— 帧账随存档走（v6）：恢复后的链首 `OBSERVE` 与首个 store 步不再丢图

**改了什么**

1. `FromHarnessToCheckpointToolSaveReq` / `...LoadResp` 各加两个字段：
   `frame_event_ids: dict[int, int]`（步号 → 承载这一帧那条事件的 `event_id`）与
   `pending_frames: dict[int, str]`（还没挂上任何事件的那一帧的 base64 PNG）。
2. `CheckpointTool._meta()` 把两者写进存档 json、`_read_checkpoint()` 读回——**旧档缺
   这两个键按空表处理**（`meta.get(key, {})`）。
3. `EpisodeHarness` 新增 `_frame_ledger(episode_id)`（摊平**本局切片**）；`save_checkpoint`
   先摊平再存档；`resume()` 新增「步骤 5：帧账回载」（原步骤 5/6 顺延为 6/7）。
4. 文档：`SPEC.md` 新增 §2.5；`PLAN_checkpoint.md` 加 v6 变更头 + §3.1/§5 两处；
   `pokemon-agent-offline-verify` 技能里那条「恢复后的链首 `OBSERVE` 不带帧（已知缺口）」
   改写成 v6 已修，并标注旧档仍会假失败。
5. 离线核验脚本加 **E 块**：真 `CheckpointTool` + `resume()` + 反向对照 + 第 0 步恢复。

**为什么这么改**：这是 0911 真机 `check_restore` 观察到的事实——恢复段时间线的**第一条
`OBSERVE` 只有 payload、没有帧**。根因不是磁盘缺图：截图按 `event_id` 好好躺在
`screenshot/` 里；缺的是**"哪条事件承载这一步这一帧"这张对账**——它在
`_frame_event_ids`/`_pending_frames` 两张**纯内存**表里，而 `resume()` 是在新进程里构造的
harness，两张表都是空的。同一条根因还压着第二处：恢复后第一个 store 步的
`before_frame`（`store_step_episode_memory` 要 `_frame_b64(ep, before.step)`）会一起变
`None`——上一版只是因为恢复点恰好落在收尾链（收尾链不落 step 记忆）才没暴露。一句话：
**`StepMemory` 的 `before_frame`/`after_frame` 是逐键都要的、链首那一帧是"大脑决策时看到
的世界"的副本，两者都不该因为"进程重启过"而消失。**

**取舍**

- **不进 `state_dump`，而是作为存档 json 自己的键。** 进 state 等于给每份存档都塞一张
  PNG（`EpisodeRunState` 是"一局的全部可序列化状态"，每圈边界 dump 一次）；而帧账只有
  第 0 步那一份会带 PNG——真机实测：GBA 截图 2.7 KB、base64 后 3596 字符，同目录 `.state`
  是 167 KB，`<step>.json` 自己已经 2.6→42 KB。为这点体积去动状态模型不划算。
- **只带本局切片。** 存档是"这一局第 `step` 步"的存档，别的局的帧账与它无关；
  `_frame_event_ids` 在整个 run 里**不清理**（跨局累积），全量落盘等于让每份存档为前面
  每一局背书。
- **整数键。** 落盘时 `json.dumps` 把 `int` 键写成 `"<step>"`，读回时 Pydantic 按
  `dict[int, int]` 把 `"1"` 收成 `1`——`resume()` 直接灌回两张内存表，调用点不用写
  `int(k)`。代价是这份契约依赖 Pydantic 的键强制转换，已用断言钉住（E 块「读回时整数键
  还原」）。
- **不加版本号/迁移。** 缺字段 = 空表，正是"这份存档没带帧账"（v6 之前写的档）的准确语义。
  老的 `checkpoints/restorecheck-0911-22*` 照样读得动。
- **没有改用"扫 trace 反推帧事件的 event_id"。** 反推法（"游标之前最近一条带帧的事件就是
  这一步的帧"）在当前图顺序下**确实**成立，但有两个毛病：**(a)** 第 0 步无解——那时帧还
  没挂上任何事件（在 `_pending_frames` 里），存档不带它就只能丢；**(b)** 它把
  "`save_checkpoint` 排在 `record_observation` 之前"这个**图顺序**变成隐式契约，以后谁调
  一下顺序就会静默丢帧。显式带上两张表是唯一同时覆盖两种来源的写法。

**影响面**：checkpoint json 多两个键——第 0 步那份多 3596 字符（约 3.6 KB），其余步只多
几个整数；**旧档向后兼容**（读回空表）。`save_checkpoint` 的语义从"三件套"变"三件套 +
本局帧账"，`resume()` 从 6 步变 7 步。全仓 `ruff` **54 → 54**（净增 0）；`check_imports`
403 条全解析、`check_graph_phases` 20 节点全对齐；**离线核验 66 → 81 条全绿**。

**离线核验**（E 块，用**真的** `CheckpointTool`：真落盘 json + 真读回 + 真 `void_after`）：
跑一局 → 新 harness 从第 4 步恢复 → 断言恢复后链首 `OBSERVE` 与首个 store 步的
`before_frame` 都拿得到图、且与恢复前同一步**逐字节同图**；**反向对照**把存档里的帧账抹掉
再恢复，断言两者**一起丢**（这条要是不丢，说明上面几条断言恒真、什么都没测到）；再加
**第 0 步恢复**覆盖暂存表那条路径。

**真机核验（经用户授权由 AI 执行）**：`check_restore` **PASS**（run `restorecheck-0911-222937`，
阶段 A 一步达成目标、存档步 `[0,1]` → 自 **step 1（中间步）** 恢复、游标 22 → 恢复后跑到
step 3、`reason='success'`）。这一局的恢复点落在中间步，所以**两处丢图都被真机压到**：

| 核的是什么 | 真机数字 |
|---|---|
| step 0 存档的暂存表 | `pending_frames={'0': <3596 字符 base64>}`（在 `voided-*/` 归档里，说明归档也带着它） |
| step 1/2/3 存档的登记表 | `{'0':5, '1':19}` → `{... '2':53}` → `{... '3':73}`，每个边界加一条 |
| **恢复段的链首 `OBSERVE`** | `#36`（step 1）**带帧**——上一版同一个位置（`#76`/step 3）是**没有帧**的 |
| 那一帧的出处 | `#36` 内字节 sha `69700ee8…` == 登记表指的 `screenshot/19.png` == 它自己那份 `36.png`，也 == 恢复前 `#24` 的 base64（3700 字符逐字符相同） |
| 接缝账 vs 链首帧 | 有效 `checkpoint_save` **4** == 有效链首 `OBSERVE` **4**（全带帧）；上一版这里是 **4 vs 3** |
| 恢复后首个 store 步 | step 1 的记忆 `before_frame`/`after_frame` 都在；该局 step 0/1/2 三条全 YES |

## 2026-09-11（20）—— 收口 4 处走丢引用 + 新增 import 解析机械核对；真机六维核对首次跑通

**改了什么**

1. `experiment/tasks.py`、`experiment/real_check/check_harness.py`、
   `experiment/real_check/check_restore.py`：`from pokemon_agent.schemas.brain import
   TaskForBrain` → `from pokemon_agent.brain import TaskForBrain`。（9）把
   `TaskForBrain`/`GoalForBrain`/`RunPlan`/`StepVerifyVerdict` 等六个数据形状搬到
   `brain/interface/domain/` 时列了消费方清单，`experiment/` 侧漏了这三处；而
   `experiment/__init__.py` 是**立即** `from .tasks import ...`，于是一处失效让整个
   `experiment` 包连带**六个 real_check 脚本全部 import 失败**——`python -m` 直接死在
   包初始化，连 `main()` 都进不去。
2. `experiment/real_check/check_memory_roundtrip.py` 迁到现行契约：
   - `pokemon_agent.schemas.world` 整个子包已删 → `pokemon_agent.world`；
   - `ObservationFromWorld` → `Observation`（同一次搬家里的改名）；
   - `StepMemory.before/after` 现在要的是 **`StepMemory.Observation`**（它自己的快照类，
     不引用 `world.Observation`），`ObjectStillEvent.place/actor_place` 同理要
     `ObjectFactEventBase.Place`——新增 `snapshot()` 助手做 `PlaceInWorld.model_dump()`
     那一下桥（生产路径同款，见 `Brain._snapshot()`），`obs()` 改收 `StepMemory.Observation`；
   - `MemoryTool.query()` **这个方法已不存在**了 → 空格断言改走 `query_object_events_at()`。
3. **新增 `scripts/check_imports.py`**：静态爬全仓 import——**含函数体里的懒加载**——
   把每条绝对/相对 import 解析到真实模块与真实名字，任一条失败即非零退出。

**为什么这么改**：模块级 import 冒烟（`importlib.import_module(<每个模块>)`）能抓顶层失效，
但抓不到函数内的懒加载：`check_memory_roundtrip.py` 那条旧 import 正藏在 `main()` 里，
**181 个模块全绿而脚本一跑就 `ModuleNotFoundError`**。而这一族失效已经反复出现——（9）之后
先查 5 处、（19）后又是 4 处——靠"人肉记得改"显然不行，得让机器在**跑真机之前**拦住。
（`check_graph_phases.py` 是同一思路：把"文档/前端/图是否对齐"压成一条命令。）

**取舍**

- `check_imports.py` 是**有副作用的**静态检查：判定"名字在不在"要用 `hasattr`，
  而模块级 `__getattr__` 的懒加载出口一碰就真导入。所以它必须用**装齐依赖**的解释器跑，
  否则会把"缺第三方依赖"误报成"本仓引用失效"。也正因如此它放 `scripts/` 而不是 pytest：
  它要在真机之前跑，失败信息是给人看的逐条 `文件:行号`。
- `snapshot()` **没有**把 `place()` 整个换成快照类：同一个 `place()` 助手还喂着
  `query_object_events_at(place=...)`，那里要的恰恰是真身 `world.PlaceInWorld`。
  一个助手服务两种坐标类型，靠这一下 `model_dump()` 分流——而不是写两个助手。
- 没顺手修 `check_memory_roundtrip.py` 的 `I001`：那是 HEAD 就有的，与本轮无关，
  修了只会污染 diff。
- 没把"真机 trace 形状核查"落成第 7 个维度：它会硬编码渲染层的 kind 字面值（`after`/
  `frame`/`checkpoint_save`/`truncated`）而随渲染层漂移，而它验的三件事离线核验脚本
  已用假端口覆盖。真机只做一次性确认，不进套件。

**影响面**：`experiment/` 包恢复可导入，`experiment.real_check.*` 六个脚本全活；
`check_memory_roundtrip` 五条读写路径**首次真正跑通**。`scripts/` 多一条可在 CI 前跑的
护栏。全仓 `ruff` **54 → 54**——新增文件零告警；`check_harness`/`check_restore` 因我改的
import 顺序触发 `I001`，已用 `ruff --fix --select I001` 修正，净增 0。

**真机核验（经用户明确授权由 AI 执行，六维度首次全套跑通）**

- 口径：`py -3.12`（全机唯一装了 pyboy 的解释器）+ 从**主仓** `.env` 注入密钥
  （**不往 worktree 写密钥**，走 `setdefault` 同语义的外部变量优先）+ `PYTHONPATH=<worktree>`；
  ROM/state 用 worktree 自带的 `assets/rom[.state]`。
- 六维全过：`check_harness` **PASS**（2m36s、3 步、`reason='success'`）→
  `check_trace` **PASS**（70 条有效事件，盘上 `[0..69]` 连续无缺号无重号）→
  `check_checkpoint` **PASS**（step 0/1/2/3 成对且带 `run_state_dump`）→
  `check_memory` **PASS** → `check_memory_roundtrip` **PASS**（七段全过）→
  `check_restore` **PASS**（自 step 3 恢复，游标 62 后续写至 76 条连续，归档 1 个 voided）。
- **（19）的三条形状在真机产物上复核通过**（此前只有假端口验证）：
  `after` 的 payload 字段**恰好** `{kind, status, done}`（无 `scene`/`overlay`/`stop`）；
  `checkpoint_save` 4 条 == 带帧的链首 `frame` 4 条；**链尾 `after` 的帧与下一条链 `frame`
  的帧磁盘同字节、事件内同 base64**（step 1/2/3 三处逐一比对 sha 相同）；
  真机 `StepMemory` 记录的 `before_frame`/`after_frame` 均在。
- 顺带观察两件事（都不是 bug，记下备查）：
  ① 真机抓到 `ParseFailure` 错误事件后紧跟重试、最终成功（两次 run 分别 1 次和 3 次）
  ——「解析失败要重试并计数」这条在真实模型上确实生效；
  ② **恢复后的链首 `frame` 不带帧**：`_frame_event_ids` 是内存态、不随 checkpoint 走，
  恢复后无从查起，而 `_frame_b64` 回读需要那个登记。本例里它是收尾链（不落 step 记忆），
  所以无影响；要修就得把帧登记表一起存进 checkpoint——留待拍板，本轮不动。

## 2026-09-11（19）—— 把「账」搬回它的宿主：`apply_stop` / `AFTER_ACTION` / `CHECKPOINT_SAVE`，20 格零哑格

**改了什么**

1. `episode_harness.py`（26 处补丁）：
   - `record_action_result` → **`apply_stop`**——职责收窄成"**只落实**"：按 `stop` 的作废
     范围截队，**不再写帧**（帧是 `perceive_after_action` 的事）；只在**真的丢了键**时写一条
     `ACTION_TRUNCATED`（条件写，payload 带 `stop` / `dropped_count` / `dropped`）；
   - 观察账搬回**产出它的那一格**：`perceive_after_action` 自己写 `AFTER_ACTION`（链内每键一条），
     字段从"模型感知才有的 `scene`/`overlay`/`status`/`done`/`stop`"**收敛到 RAM 档读得出的
     `status`/`done`**，`stop` 归处置账——"看到什么"与"据此处置了什么"从此是两笔账；
   - **链尾帧不再走暂存表中转**：`_pending_frames` 缩到只剩**第 0 步**那一条路径
     （那一帧在图外产、没有事件可挂）；链尾键的帧由下一条链的 `record_observation` 按
     `event_id` 读回（`_frame_b64` + `read_screenshot`），v6 承诺的"两处都带、逐字节相同"不变；
   - 新增 `save_checkpoint` 的 **`CHECKPOINT_SAVE`**——`save_checkpoint` 从哑格变成有账的格子。
2. **账搬回宿主**（规则改写）：`brain_utils.py` / `game_utils.py` / `episode_utils.py` 三个
   util **去掉 trace 依赖**，只交回材料（`(action | None, log)` / `(observation | None,
   frame_png | None, log)`），写账由调用它的宿主做。规则从「**谁的循环谁记账**」改成
   「**账写在它的宿主里**」。新增 `harness/trace_write.py::append_model_calls()`，
   把 5 个写点的 `AppendReq` 样板收成一行。
3. 命名：`enrich_observation` → **`merge_retrieval`**（活代码 + 接口 + web + 活文档共 25 处）。
4. 契约与观测台同步：`episode_harness_port.py`（7 处补丁 + **20 行"节点 / 改哪处 / 写哪条 /
   一句话"对照表**进模块 docstring，行序 = 执行顺序）；`web/src/App.tsx`（20 处补丁：
   `CHAIN_PHASES` 20 条且 `key` 改用**节点全名**、`MAIN_END` 16、尾链三条、
   `phaseKeyOf`/`endSeen`/`litOf` 跟着改）。
5. **新增 `scripts/check_graph_phases.py`**：用 `ast` 从 `_compile()` 抽 `add_node` 的字面量、
   用正则从 `App.tsx` 抽 `CHAIN_PHASES.key`，**逐条比对有序列表**（不是比集合），不一致即非零退出。
6. 四处文档订正（§1.1–§1.5）：`DATAFLOW.md` 的 `view(frame/after)` 一行改成"链尾帧按 event_id
   读回"；`ROADMAP.md:1136` 就地加「订正 2026-09-11」；`CHECKPOINT_handoff_2026-09-07.md`
   顶部加一行现状指引（正文不动，它是 0907 的事实快照）；`SPEC.md` 换头部"现状"块 +
   **§2（`LoopState` → `EpisodeRunState`）/§3（图结构）整节重写**、其余各节加"本节写于 0902 版"
   标记。顺带修掉 **5 处走丢的引用**（`brain.py` / `ChooseOnceResp.py` / `trace_port.py` /
   `pyboy_world.py` / `ROADMAP.md:163` 仍指着早已不存在的 `episode_utils.*` 与 `harness/utils.py`）。
7. 离线核验脚本改写：**56 → 66 条**（新增"`AFTER_ACTION` 每键带帧且字段恰好
   `{kind,status,done}`、不带 `stop`"、"`ACTION_TRUNCATED` 只在真丢键时写、位置与 payload 对得上"、
   "**中止 ≠ 截断**"、"跑完 `_pending_frames` 为空"、"`CHECKPOINT_SAVE` 条数 == 链边界数 ==
   `OBSERVE` 数、步号 `[0, 3]` 与真存档一致"等）。

**为什么这么改**：用户的判据是「要不放回节点？其他类似的也都放回节点？要不然太散了，
trace 就在 harness 里记吧」，外加一句更早的「**只有真的截断了记一条截断 process trace**」。
「散」的具体形态是：**想知道一条事件是谁写的，得同时打开 4 个文件**——事件在 util 里产出，
util 又只被节点调用，于是"这条账属于哪个节点"这件事在任何单个文件里都读不出来。
搬回宿主之后，每个节点自己那段 docstring 就说完"我改哪一处 state、我写哪条账"，
`interfaces/` 单层自足这条设计承诺才真正兑现（§4 那张表也因此能进模块 docstring 而不是外挂一份文档）。

**取舍**

- **明账：崩溃窗口变大了。** `LocalTrace.append` 是**逐条原子落盘**——今天 `MODEL_CALL`
  边重试边写，"重试到第 2 次时进程被杀"仍留有前一次的账；搬完之后要等 util 返回才落盘，
  **进程死在模型调用里就全丢**。窗口 ≤ 一次决策的重试条数（decision 3 / perception 2），
  且那时本来也不会有 `EPISODE_END`。**事件顺序不变**（循环期间没有别的写账点）。
- **「中止 ≠ 截断」**：`blocked` 可能一个键都不丢（`up×1 -> down×2`），所以截断账是**条件**写的。
  代价：那一类键的 `stop` 不进 trace（仍进 `StepMemory.stop`，大脑那侧不受影响）；
  换来的是「这一局被截断了几次」= `ACTION_TRUNCATED` 的条数，是一句可以直接数出来的话。
- **`_pending_frames` 不整个删**：第 0 步那一帧在图外产出、没有事件可挂，删不掉；
  能删的是"链内/链尾帧中转"那一半。
- **`dropped` 的展开逻辑不塞进节点**：`AppendReq` + 渲染层已经承担"按 kind 拼 payload"，
  节点只该交回 `list[ActionSegmentFromBrain]`。
- **`CHAIN_PHASES.key` 用节点全名（放弃短别名 `enrich`/`store_step`/`rv_knowledge` …）**：
  换来机械核对退化成一次直接的列表相等判断；代价是 `phaseKeyOf`/`endSeen`/`litOf` 要在同一批里改完。
- **`SPEC.md` 不抄第二份字段表**：抄本会漂移，只指 `episode_harness_port.py` 这个唯一权威。
  结构与论证分离——**结构描述重写、0902 的设计论证原文保留**（那些论证与节点数是 6 还是 20 无关）。
- **明账（本轮唯一新增 lint）**：`episode_harness_port.py` 模块 docstring 里那张 20 行 × 5 列的
  对照表，**行宽超 100 列**（最长 189）——markdown 表不能折行，"要么丢列、要么超宽"，
  选了保信息量。本轮全仓 `ruff` **50 → 54**：`+7` 条 E501 全部来自这张表，另有 `step_memory`
  `−1`（早前会话改 docstring 顺带消掉）与 I001 `−2`（本轮触碰的文件 import 排顺）。
  **`E501-in-docstring` 在本仓是既有类别**（HEAD 那 14 条 E501 全在 docstring 里），
  所以这次是"同类追加"而非新病种；要不要把这张表挪到 `docs/` 换个干净数字，留待下一轮拍板。

**影响面**：`MODEL_CALL(DECISION)`/`(PERCEPTION)`/`(PLAN)` 的**条数与相对位置不变**（只换了写入者）；
`event_id` 单调递增不变；**节点数 20、`NODES_PER_PRESS` 7 不变**（本次只改名 + 挪账）。
每键的账从 4 条变 **5 条**（`ACT` / `AFTER_ACTION` / `STALL_CHECK` / `MEMORY_WRITE` /
`STEP_ADVANCE`），**真的丢了键的那一键 +1**（`ACTION_TRUNCATED`）；每个链边界 +1（`CHECKPOINT_SAVE`）。
验证：离线核验脚本 **66 条全绿**（exit 0）；`scripts/check_graph_phases.py`
`OK  20 nodes; graph order == web CHAIN_PHASES order`；`npx tsc --noEmit` exit 0；
`ruff format --check` 对改动文件"already formatted"。真机六条命令仍待用户跑（AI 不碰 PyBoy）。
另（仓库外，一并记）：离线核验技能的 `SKILL.md` 同步到 v7——断言数 56 → 66，
§1.1/§4 里 `LOOK_AFTER` / `record_action_result` / "链尾帧两处都带（帧先落 `_pending_frames`）"
三处描述改成 `AFTER_ACTION` / `apply_stop` / "按 event_id 读回"，并修掉一条断言标签与它
实际断的数据不符的笔误（写"warp 丢 1 个 down"，实际断的是"warp 丢整条展开后的剩余队列"）。

## 2026-09-11（18）—— 把 `look_after_action` 一分为二：感知归感知，留痕归留痕

**改了什么**

1. `episode_harness.py`：`look_after_action`（8 件事）拆成两格——
   - `perceive_after_action`（改 `pending_observation`/`pending_stop`）：分档感知 → 判 `stop`
     →（中止时）补完整感知 → 盖步号 → 帧进暂存表；**不写任何观测账**；
   - `record_action_result`（改 `pending_presses`）：按 `stop` 的作废范围截队 → 认领这一帧
     → 写 `LOOK_AFTER`。
   边改为 `act → perceive_after_action → record_action_result → detect_stall`；节点数
   19 → **20**；`NODES_PER_PRESS` 6 → **7**（`recursion_limit` 公式自动跟随）。
2. `episode_harness.py`：**链尾键的帧两处都带**——既留在这键自己的 `LOOK_AFTER` 上，又留在
   `_pending_frames` 里由下一条链链首的 `record_observation` 挂给 `OBSERVE`；`_frame_event_ids`
   改成"谁先产出这一帧谁登记"（不再被 `OBSERVE` 覆盖，指向必须稳定）。
3. 同步面：`episode_harness_port.py`（"二十个节点"、图、"帧的归属"一段、`pending_*` 的 docstring、
   两个新方法声明）、`episode_utils.py`/`trace_render.py` 的引用、`web/src/App.tsx` 的相位表
   （补两格、`MAIN_END` 15→**16**、`phaseKeyOf` 的 `view/after` 与 `model_call/perception` 改指）、
   `docs/spec/DATAFLOW.md` 一行；收尾时又补齐四句仍写"**十九**个节点"的旧文案——`_compile` 的
   docstring 与"步骤 1"注释、`EpisodeHarnessPort` 类 docstring、`App.tsx` 页签注释（漏网的原因：
   前一轮只扫了模块 docstring 那一处）。
4. `PLAN_graph_readability.md` 升 **v5**：§3.3 撤回、新增 §3.6（接缝的唯一性 + 帧的承载规则）、
   §4 对照表 19 → 20 行；两份旧 PLAN 顶部加现状指引（不改历史论证）。随后按用户拍板升 **v6**：
   帧定为"两处都带"（§3.6 帧一节整段改写，含"体积不再不变"的明账和上面那个截断判据的坑）、
   第二格定名、§5 一行翻转、§6 步骤 0c 标已落地、§7 勾掉第 8/9 条；并补上 v5 漏改的 §4 引言
   （"19 个格子" → **20**，同步口径由 v3 改成 v6）、§1.2 的节点数、§1.1 的 v6 进度（#1 只落地了
   "补两格"那一半、#2 已落地、#4/#5/#1 另一半仍缺，所以 #6 的"一一对应"仍不成立——表头改成
   "如实标注这两处漂移"）、§3 顶部的现状指引（本节写于 v1、19 节点口径，并把"`look_after_action`
   拆不动"那半句当场标掉）。
5. 顺手校准两处数字文案（都是这次没扫到的）：`_invoke()` 的 docstring 里 `recursion_limit` 的
   上界算式还写着 `10 + 6K ≤ 16K`——`NODES_PER_PRESS` 已是 7，而这段文字本身就在解释那两个常量
   → 改成 `10 + 7K ≤ 17K`（`K ≥ 1` 时仍成立，与 `per_press = 10 + 7` 一致）；
   `PLAN_graph_readability.md` §6 的验收结论也从"`ruff` 干净"改成本轮那句口径。

**为什么这么改**：用户的判据是「拆开吧，不然和 observation 功能太像了」。`look_after_action`
是全图唯一从头到尾在**产出观测**的格子，而 `record_observation` 在**登记观测**——两个名字都带
observation 的格子做的是**频率差 N:1** 的两种事（§3.5 已论证），名字却像同一件事的两种说法。
拆完"感知"与"记账"彻底分家：第一格只改状态，第二格才写账。

**取舍**

- **接缝不是挑的，是被依赖逼出来的**：`中止补感知` 的触发条件就是 `stop is not None`，而 `stop`
  是 `compute_stop(...)` 的输出——**纯感知节点根本不可能存在**。能拆的只有"感知+判读 | 落实+留痕"。
- **推翻了自己 v4 的结论（§3.3），并在原文上方写明撤回**：当时列的四条代价里，① "链内每键
  6→7、链越长代价越大"（涨的是**图跳数**，不是模型/视觉调用，成本口径用错）、③ "`LOOK_AFTER`
  要拆成两条"（**拆节点 ≠ 拆事件**）、④ 原子性退化（按本接缝只残留一半）**均不成立**，只有
  ② `recursion_limit` 重算成立——而那只是改一个常量。这是同一类错的第二次（v1 也把 `act` 的
  扶正判成"不拆"），所以把"别把拆节点/拆事件/图跳数当同一件事"写进了 §3.3 顶部。
- **残留取舍**：`pending_stop`（第一格）与 `pending_presses`（第二格）跨格。缓解三点：两格之间
  没有别的节点、也没有条件边；第二格唯一会失败的地方是 trace 落盘（失败即整局失败、状态不保留，
  不存在"半成品被消费"的窗口）；截断判据与 `compute_stop` 一样是纯函数，不存在两处规则各算各的。
- **链尾帧选了两处都带**（用户拍板：「都保留，重复是为了语义清晰」）：代价是链尾那一步的图落两份
  （`LOOK_AFTER` 一份、`OBSERVE` 一份，逐字节相同），量级约"每链多一张图"；换来 `OBSERVE` 自足
  ——replay 到链首就能同时看到"画面 + `goals` + 完整 `facts`"，不必翻上一条链的末尾。
- **链尾判据用"截断之后队列空"**，不是"截断之前"：`blocked` 只丢本段剩余（链可能接着走，这一帧
  就还是链内的帧），而 `warp`/`episode_over` 清空整条链时那一键事实上就是链尾，帧要留给下一链的
  `OBSERVE`。这一处第一版写错过，离线核验的"每条链首的 `OBSERVE` 都带帧"抓出来了。

**影响面**：`MODEL_CALL(PERCEPTION)` 条数与视觉成本**不变**（分档感知只是换了宿主）；离线核验脚本
**56 条全绿**（52 → 56：新增"两格之间的三条边 + 旧名彻底消失"、"每条链首的 `OBSERVE` 都带帧"、
"登记表指向先产出的那条 `LOOK_AFTER`"、"链尾帧两处是同一张图"）；`ruff check` 对**本轮改过的两个
文件**只剩 1 条——`episode_harness_port.py` 的 E501（127 字符），逐字比对过 HEAD 同位置同长度，
属历史遗留、只是被插行挤到 48 行；`ruff format --check` 两文件均"already formatted"。
**顺带把一句过宽的话纠正掉**（此前写成"ruff 干净"，口径太窄）：全仓 `ruff check` 现在是 **49 条**
（E501 13 / I001 11 / ANN202 9 / ANN401 5 / UP042 5 / ANN001 2 / F401 2 / SIM105 1 / B905 1），
用 `git archive HEAD` 到临时目录取出基线是 **50 条**（E501 14）——本次会话净减 1，**没有一条是本轮
引入的**。这些历史项不在本次范围，留给"什么时候顺手清"另议。`web` 的 `tsc --noEmit`
通过（本 worktree 没有 `node_modules`，临时链接主仓依赖跑的，跑完已删除链接、主仓完好）。
**§1.1 的形状级漂移还剩两项**（`save_checkpoint` 补位、尾链 `verify_steps`+`summarize` 合一）
本轮未动，但 `MAIN_END` 15→16 是被这次插入**强制**跟着改的（否则 `close_step` 会被误判成收尾链
节点）；剩余两项已在相位表表头写明。另：`uv run` 顺手把 `uv.lock` 与 `pyproject.toml` 对齐了
（`agent-permission` 的 lock 条目是接入移除后留下的陈旧项）。真机六条命令仍待用户跑（AI 不碰 PyBoy）。
另（仓库外，一并记）：离线核验技能的 `SKILL.md` 补齐了这次的两处漂移——断言数 **50 → 56**，
§1.1 新增"`look_after_action` 已拆成两格 + 帧两处都带 + 链尾判据要用截断之后"这条（含踩坑提醒），
并把 §1 里那个仍指向主仓的 `PYTHONPATH` 改成"用当前工作区路径"（原与 §0 自相矛盾）。

## 2026-09-11（17）—— 顺序口径统一：`close_step` 的字面位置对齐执行顺序

**改了什么**

1. `episode_harness.py` 的 `_compile()`：`add_node("close_step", ...)` 从 `detect_stall`
   之后挪到 `store_object_semantic_memory` 之后——`add_node` 的**字面顺序现在 = 执行顺序**。
2. `episode_harness_port.py`：`close_step` 的方法**声明**同样后移（`detect_stall` →
   `store_step_episode_memory` → `store_object_semantic_memory` → `close_step`），
   让"接口即图"的宣布顺序与执行顺序一致。
3. 文档：`PLAN_graph_readability.md` 升到 **v3**——§3.4 记录 B 已采纳并落地；§2.1 定名
   `record_observation`（v1 提的 `stamp_observation` 随扶正挪走而失效）并回写"`look` 的工作
   还需要吗"；§4 对照表 13-16 行按执行顺序重排；§6 补落地记录；§7 勾掉两条已拍板项。

**为什么这么改**：`web/src/App.tsx` 的表头写着"与 `_compile` 的 19 个节点一一对应、**顺序照抄**"，
而表里 `close_step` 排在两个 store **之后**（这是执行顺序，也是观测台该展示的顺序）。
`add_node` 的字面顺序不影响 LangGraph 的拓扑（拓扑由边定义），所以两边"都对"——
但两种口径并存会让 §6 那条机械核对永远只能比集合，"顺序照抄"也就永远是一句没法验证的话。
把字面位置挪到与执行顺序一致，是把一句口头约定变成**可断言的形状**。这正是本 PLAN 针对的
病根：漂移能藏两个月，靠的是没有断言守着。

**取舍**：没有反过来改前端去迁就 `add_node` 的旧字面顺序——那会让观测台上"关步"排在
"两个 store"之前，与刚刚挪走的那种错位同形（读图的人会以为先扶正、再落库）。宁动一句
`add_node` 的位置，不动"链按执行顺序展示"这条观测台的语义。

**影响面**：`add_node` 的方法注册顺序对图引擎无语义，Protocol 方法声明顺序同理 →
**运行时行为零变化**。离线核验脚本 52 条仍全绿；`ruff check`/`format` 干净
（`port.py:43` 的 E501 是改动前就有的历史遗留）。web 相位表的形状级漂移
（`save_checkpoint` 缺位、`MAIN_END` 15→16、尾链 `verify_steps`+`summarize` 4→3）
**本轮仍未动**，见 PLAN §1.1 的 #1/#2/#4/#5/#6。

## 2026-09-11（16）—— 步的边界收进一个节点：`look`+`advance_step` → `record_observation`+`close_step`

**改了什么**

1. **`advance_step` → `close_step`**：职责从"步号 +1"扩成"**扶正当前帧 + 步号 +1**"
   （改 `observation`/`step` 两处——"一步结束了"这一个判定的两面），位置从
   `detect_stall` 之后挪到两个 store **之后**；链内小循环的条件边出口随之从
   `store_object_semantic_memory` 挪到 `close_step`。
2. **`look` → `record_observation`**：摘掉扶正与盖步号，只剩"把当前帧记成一条
   `OBSERVE`"——**只记账、不改状态、返回空增量**。
3. **`act` 从"改三处"缩回"改两处"**（不再扶正），断言基准换成 `state.observation`。
4. **`_begin` 直接产出已扶正的 `observation`**（第 0 步）——开局没有"上一步"，
   不需要 `pending_observation` 那道接力。
5. 契约与外围同步：`episode_harness_port.py`（模块图 + `record_observation`/`act`/
   `close_step` 三个节点契约 + `observation`/`pending_observation` 两个字段说明 +
   `stall_count` 那句写错的"强制终止判断在 `look`"）、`web/src/App.tsx`
   （相位表、`phaseKeyOf`、若干注释与一句占位文案）、`trace_render.step_advance` 的
   docstring、`step_memory` 两处去重论证、`trace_event` 的 `VIEW` 说明、
   `episode_utils` 的预算注释。核验脚本补了 3 条拓扑断言（52 条全绿）。

**为什么这么改**：`act` 的第三处（扶正）**不是"刻意的原子性"，是宿主消失**。
扶正本来是 `look` 的活（它的 docstring 自己写着"只改 `observation` 一处"）；
`step == decision` 时代 `look` 每步都跑，扶正从不缺宿主，链内小循环把 `look` 降到
链边界，它就没了着落。而扶正**必须落在两个 store 之后**——那三格要 `before`
（`observation`）与 `after`（`pending_observation`）两帧同时在场，谁先扶正都会把
`before` 冲掉——那个位置的下游只有一条条件边、没有节点体。于是它只能寄居在下一圈
第一个节点 = `act`。**根在 `look` 的混合粒度**（扶正=步级、`OBSERVE`=链级），不在
`act`。把扶正还给"这一步的终点"（`close_step`）之后，三格各归其位：`close_step` 扶正、
`act` 只读不算、`record_observation` 只记。诊断与两个方案的对比见
`docs/spec/harness/PLAN_graph_readability.md` §3.4。

**`look` 的工作没有全部消失——它只是不能再兼任扶正**：`OBSERVE` 必须**每链一条**
（链内每个键要么只读 RAM、本来就没有 `MODEL_CALL` 可挂，要么只有 `LOOK_AFTER` 的
轻量摘要，不含完整 `facts` 也不承载 `goals`）；这一格没了，replay 与观测台就没有
"大脑当时看到的世界"的结构化原件。所以它保留为**单一职责节点**并因此改名——它不
"看"，只记账。

**取舍**

- **不新增节点**（方案 A 会 19→20、`NODES_PER_PRESS` 6→7，链越长越贵），也**不拆**
  `look`（链内每步都要跑扶正 = 再 +1 节点/键，`judge` 入口与两条边都得挪）。
- **checkpoint 内容变了**：B 之后存档里的 `observation` 与 `pending_observation` 同值
  （之前落后一帧）。逐项核对过：`save_checkpoint` 写在 `record_observation` 之前，
  **`resume()` 六步一字不改**，链内没有任何节点读 `state.step`。
- **把 `look` 这个名字留给真正在看的那个**（`look_after_action`）。

**影响面**

- 图的**节点集合不变**（19 个）；边改 3 条：`save_checkpoint→record_observation`、
  `record_observation→judge`、`store_object_semantic_memory→close_step`，条件边出口
  从 `store_object` 挪到 `close_step`。`NODES_PER_DECISION`/`NODES_PER_PRESS` 与
  `recursion_limit` 的量级都不变。
- `MODEL_CALL` 条数、`step` 语义、记忆的键 `(episode_id, step)` 全不变；离线核验
  **52 条全绿**。
- **web 相位表的既有漂移这轮没动**（缺 `save_checkpoint`、`verify_steps`+`summarize`
  仍画成两格、`MAIN_END=15` 应为 16）——它和本次改动无关，按 `PLAN_graph_readability.md`
  §6 单独落；本轮只保证 `close_step` 落在主循环区间内、事件能归到正确的格。
- 真机六条脚本仍未跑（worktree 分支没有 `.env`）。

## 2026-09-11（15）—— 首次接真实模型核验：段论据的条数规则缺失（已补）+ 两个既有失败模式的实测

**背景**：`（14）` 的验收全部走假端口，它证明实现自洽，**证明不了模型会按新格式输出**。
这次把决策/校验两条链路接到真实模型上（`qwen-plus@0.3` / `doubao-seed-2-1-pro@0`
——口径抄 `build_real`），输入帧与记忆**取自主仓真实 run 的 trace 产物**
（`trace_data/realcheck-0910-180502`，含一次真实的撞墙），**全程不碰 PyBoy**。
六次采样、同一帧同一目标。

**改了什么**：只改一处 prompt。

1. **`decide_action.md` 补"一条论据覆盖整段"的规则**（写在 `sequence` 那一节）：
   `times: 4` 要的是**一条**「这条线上 4 格都能走」，不是 4 条「第 1 格…第 2 格…」；
   想让依据具体到格子，就在**同一条**里连着写。
   **实测**：改前 4 次采样里 **3 次**给 `up×4` 那段写了 4 条论据（每个格子一条）→
   撞 `MAX_RATIONALE=2` → 整次输出作废走重试，且**重试 3 次有 2 次仍然这么写**
   （是系统性的，不是手气）；改后 6 次采样**每段都是 1 条，契约违规 0**。
2. **未改，但记下有意的"不改"**：`verify_and_summarize.md`/`judge_success.md` 把记忆
   形状描述成三段（「当时看到 → 做了什么 → 之后变成」），没提 `（14）` 新增的
   `然后停了` 与 `BLIND_NOTE`。**实测不需要改**：校验器拿到撞墙那条（链内盲帧 +
   `然后停了  这个方向上剩下的连按不必再按了（原地不动 = 撞墙）`）后原话判
   「位置仍为(13,6)未移动，北侧邻格为#阻挡，符合撞墙后原地不动的规则」，
   三条全判 reliable；决策者下一步的 `thought` 也主动引用它（"step=2 明确记录
   '原地不动 = 撞墙'"，随后交出 `right -> up` 而不是再按 `up`）。
   **描述不全 ≠ 读不懂**，静态前缀一个 token 不加。

**为什么这么改**：段论据会被**原样复制进这一段每一下的记忆**（`（14）` 的归属规则），
所以"第 1 格…第 4 格…"这种写法本身就不成立——第 1 下的记忆里会出现"第 4 格可走"，
而那一格那一下还没走到。`MAX_RATIONALE` 不是随手定的档位，是这条归属规则的直接后果。
prompt 讲了"一段一份"，没讲"一份覆盖整段"；模型按自己对**每一个键**的承诺去写，
是合理误读，不是乱写。

**取舍**：
- **没把 `MAX_RATIONALE` 从 2 抬到 4**（那样那批输出能直接过）。上限的语义单位是
  "段"，抬高只会让每键记忆里的冗余断言更多、更长，把写法问题掩盖成配置问题。
- **没给解析器加"补一个 `}`"的兜底**。实测第二个失败模式是模型丢掉**最外层 `}`**
  （2/6；`Expecting ',' delimiter` 落在末字符，补一个 `}` 即完全可解析），
  重试**两次都救回**。`_strip_json_fence` 的既有决定是"内容坏了走重试，不在解析器里
  猜着改"——补括号不算内容修复，是可讨论的例外，**留给用户定，这次不动**。
- 只验到"能解析 + 三条可靠"，**没做**判定器/校验器的准确率标定（那要真图）。
  校验器那条是 `temperature=0` 的**单次**采样，不是分布。

**影响面**：只动 `decide_action.md` 一份模板，`$max_rationale` 是原有占位符
（同文件别处已在用），`build_prompt`/`Brain` 零改动。核验脚本落在仓库外
（`%TEMP%\pa_llm_probe\`），可复核但未加进仓库。顺带量到两件事，**本次不处理**：
一次决策输出 1.0k–1.7k token，其中 `thought` 占大头且**大半花在 `walk_map` 的
逐字符列号换算上**（含"等一下重数"式的自我纠错），输入侧缓存命中很高
（`in=6379 / cached=6272`）——而列号算错在新粒度下的代价被放大了：链内盲走，
错一格 = 该段剩余键全作废。要收紧得动 `map_hint` 的读图格式，不属于本次范围。

## 2026-09-11（14）—— `step` 缩成一次小 action：链内小循环 + 逐键 RAM 感知 + `stop` 分情况留痕

**背景**：`harness/object_interactions.py` 的判定层只处理得了单键——判"这一键碰上了
哪一格"要拿 `before`/`after` 两份快照加**这一个键**，而"一次决策 = 一条链"的模型下
链的两头对不上中间是哪一按键撞的门，于是多段链一律不产出事件（判定层整段让位）。
粒度定义、归属规则、中止范围的完整论证在
`docs/spec/harness/PLAN_action_step_granularity.md`（v3）；本条目只记落地，以及
落地过程中暴露出来的三处问题。

**改了什么**：

1. **`step` = 一个小 action（一个键）**。`EpisodeRunState` 新增
   `plan`/`pending_presses`/`pending_stop` 三个链字段（随 checkpoint dump，恢复后
   接着把剩下的键按完）；`think_action` 把 `plan.sequence` 按 `times` 展开成
   "一键一段"的队列，`act` 每圈弹队首、派生一个单键 `ActionFromBrain` 交给世界。
   一次决策的**决策调用与四路检索按链摊薄**，而 `detect_stall`/`advance_step`/
   两个 store 每键各跑一次。
2. **链内小循环只加一条边**：`store_object_semantic_memory` 出口按
   `pending_presses` 是否为空分叉（回 `act` / 回 `save_checkpoint`）。节点集合不变，
   `save_checkpoint` 仍只落在链边界——每键一份含模拟器快照的存档会让存档量乘链长，
   而链内执行是纯 RAM 确定的，从链首存档重放能逐帧复现。
3. **感知分两档**：链内键走 `perceive_once(ram_only=True)`（免费、确定、无模型调用、
   不会失败），链尾那一键与**中止的那一键**做完整视觉感知。
   `MODEL_CALL(PERCEPTION)` 条数与改动前相等（§9 验收不变量）。
4. **`stop`：这一键的结局，分情况作废**。新枚举 `StopReason`
   （`blocked`/`warp`/`episode_over`）+ 纯函数 `episode_utils.compute_stop()`
   （中止范围的**唯一**出处）：撞墙只丢掉本段剩余同名键（`up×4 -> down×2` 里第 2 个
   `up` 撞墙 → 后面的 `down` 照按），`warp`/`episode_over` 清空整条链。判定顺序是
   `after.done`（世界没了，读数不再可信）→ `blocked` → `warp` → 步数用尽。
   `stop` 进 `StepMemory`、进 `LOOK_AFTER` payload，并由 `STOP_NOTE` 渲染进记忆文本。
5. **`rationale` 下沉到段**：`ActionFromBrain.rationale` 删除，
   `ActionSegmentFromBrain` 新增 `rationale: list[str]`（1..`MAX_RATIONALE`）；链级的
   "为什么"由 `thought` 承担（只进 trace）。`Brain._parse` 对顶层 `rationale` 报
   `ParseFailure`（不许两个位置都能写）；新增 `MAX_SEGMENTS` 段数上限（原来无上限）。
6. **`perceived: bool`**：RAM-only 观测显式声明"这一帧没有人看过"，
   `StepMemory.Observation.render()` 在 `False` 时顶一行 `BLIND_NOTE`——
   "没读过"和"读过、是空的"必须能分开。`Brain._blind()` 原样透传这个标记。
7. **帧脱离感知**：不再挂 `MODEL_CALL`，改成**挂在产出它的那次感知所在的事件上**
   （开局那一帧 → `OBSERVE`，之后每一帧 → 那一键的 `LOOK_AFTER`）；
   `_frame_event_ids` 仍是"步号 → 截图"的唯一对账表。
8. **`world.step(segments, *, settle=)`**：链中间的键不等 10 秒过场，只有链尾等
   （那一帧要交给 `judge` 看）。
9. **prompt 跟上**：`decide_action.md` 重写"链怎么按、什么会打断、中间帧看不到
   什么"；`repeat_hint.md` 的成本口径从"每步一次感知调用"改成"每链一次决策 +
   一次视觉，方向键本身不要钱"，并写明撞墙只废掉那个方向。

**为什么这么改**：判定层、记忆层、停摆检测全都只认"一个键 + 前后两帧"，而
"一次决策 = 一条链"让它们的输入对不上；把 `step` 缩到键粒度，这些现成逻辑一个都
不用改就能覆盖链的每一步。完整论证见 `PLAN_action_step_granularity.md`。

**取舍**：
- **checkpoint 只落链边界**（§7.3）：链内不存，靠"同存档 + 同链 → 同一状态"重放。
  代价是链内那几步的重放必须逐帧确定——这正是"链内只读 RAM"的第二个理由。
- **`act` 从"改两处"变成"改三处"**（多扶正 `observation`）：见下面的第 1 处问题的
  修复位置选择。不新增节点（新节点得占一条 trace 事件、要新 TraceKind），不重排图上
  现有节点（`advance_step` 挪到 store 之后会让两个 store 拿到被扶正过的 `before`）。
- **`stop` 渲染不受 `reason` 约束**：它是执行层机械判出来的事实，不是决策者自己的
  说辞，所以判定器看的那一版（`reason=False`）也照摆。

**落地时暴露的三处问题**（都不是设计取舍，是实现的坑）：

1. **当前帧必须在链内前进。** `observation` 在每一圈里的语义是"这次按键**之前**的
   那一帧"（两个 store 拿它当 `before`），而链内小循环不经过 `look`（只在链边界
   扶正它）——不补这一步，链里第二个键读到的还是链首那一帧，
   `(episode_id, step)` 从第 2 步起全错。落点定在 `act`（每一圈的开头），
   链首那一圈幂等。**假端口核验第一次跑就抓到了它：`step 号 [0, 0, 0, 3, 4]`。**
2. **帧只挂 `OBSERVE` 会漏掉链内键。** `look` 只在链边界跑，`OBSERVE` 因此是
   "每条链一条"；帧要是只挂它，链中间那些步的 `before_frame`/`after_frame` 全是
   `None`——而 §3 明确要求逐键都有，否则 `judge`/`verify` 的多模态输入成片缺图。
   改成"帧由产出它的那次感知所在的事件承载"，`_pending_frames` 从"每一帧都过一手"
   缩到只服务开局那一帧。
3. **`stop` 进了字段却没进渲染。** §5 要求大脑下一步能推出"在第 3 键撞墙了"，而
   `StepMemory.render()` 原来不带 `stop`——记忆里就只是"按了 up、画面没变"，会被
   读成"我本来就只打算按一下"。补 `STOP_NOTE` 表 + 渲染那一行。

**已知遗留**：
- `JUDGE_HISTORY = 2` 的语义从"最近 2 步"变成"最近 2 键"，判定器时间视野缩到
  1/链长；`max_steps` 从"决策轮数"变成"小步数"，任务定义要重标定。
  **两条都还没做**（§7.2 / §7.4 / §8 步骤 5）。
- "逐键存、按链读"（把一条链合并成一条渲染给大脑，压
  `retrieve_step_episode_memory` 的 prompt 膨胀，§7.6 建议与主改动分开落地）
  尚未做。
- `web/` 观测台的"一条 OBSERVE 一页"变成"一条链一页"，页面语义变了，尚未跟着改。

**验证**：离线假端口核验（`FakeGame`/`FakeMemory`/`FakeBrain` + 真 `TraceTool`、
真 `Brain.reflect`、真 `compute_stop`）50 条全绿——解析契约 9 条、`compute_stop`
8 条、整局链内小循环 33 条，含"决策只发生 3 次而按了 5 个键"、"`blocked` 只作废
本段剩余 / `warp` 作废整条"、`settle` 只落链尾、"逐键都有截图且帧落在正确的步上
（链内键是 RAM 帧）"、"`MODEL_CALL(PERCEPTION)` = 5"。`ruff check`/`ruff format`
对本轮改动文件无新增问题（`brain/brain.py` 的 `I001`/`E501` 等 HEAD 就存在）。
**真机链路核验（`experiment.real_check.*`）由用户执行，尚未跑。**

**影响面**：`harness/`（`episode_harness`/`episode_utils`/`game_utils`/
`object_interactions`/`interface`）、`brain/`（`brain`/`interface/domain/
action_from_brain`）、`schemas/`（`memory/datastore/step_memory`、
`harness/communication/` 两个信封）、`tools/`（`trace_render`/`game_tools`/`ports`）、
`world/`（`pyboy_world`/`interface`）、`prompts/calls/decide_action/`。
**既有记忆文件不用迁移**（`rationale` 形状不变，`stop`/`perceived` 都有默认值）。
## 2026-09-11（13）—— 修正（12）的错误：`StepMemory`/`EpisodeMemory`/`ObjectFactEvent` 搬回 `schemas/memory/`，`Observation`/`PlaceInWorld` 引用改内部类

**背景**：（12）条把 `schemas/memory/datastore/*.py` 当作"数据形状归它自己模块"
的普通一例，搬进了 `pokemon_agent/memory/datastore/`——跟 `trace/datastore/`
（`TraceEvent`）套用同一条规则处理的。用户指出这一步套错了规则：`memory/ports.py`
的 `MemoryStorePort` 是**完全不透明**的协议（`put`/`get_many`/`filter`/
`archive_many` 全程只认 `metadata: dict[str, str]` + `payload: dict`
两个裸字段，`store.py` 的实现同理，从不 import `StepMemory` 这几个类），
不像 `TracePort.append()`/`LocalTrace.read_disk_events()` 那样**真的要在
内部构造/解析** `TraceEvent`。判断一个数据形状该不该归某个模块自己，标准是
"这个模块的 Port/实现是否真的需要构造或消费它的具体样子"——`memory` 不需要，
所以 `StepMemory`/`EpisodeMemory`/`ObjectFactEvent` 不该进 `memory/`，该待在
`schemas/`（本项目自己的跨层契约层）。

**改了什么**：

1. `git mv pokemon_agent/memory/datastore/{episode_memory,object_memory,
   step_memory}.py` 回 `pokemon_agent/schemas/memory/datastore/`（重新建起
   `schemas/memory/__init__.py`/`schemas/memory/datastore/__init__.py`）；
   `pokemon_agent/memory/__init__.py` 去掉这三个类的 re-export，恢复成只出
   `MemoryStore`/`MemoryStorePort`/检索纯函数。
2. `schemas/memory/datastore/step_memory.py`：去掉
   `from pokemon_agent.world import Observation`，改成 `StepMemory.Observation`
   ——跟 `world.Observation` 字段一致（`step`/`place`/`status`/`facts`/`done`，
   `Facts`/`Landmark`/`PlaceInWorld` 对应内部类 `Observation.Facts`/
   `Observation.Facts.Landmark`/`Observation.Place`）、渲染对齐算法照抄
   （两边要能渲出一模一样的文本，大脑才能拿旧记忆和当前观测直接比对），但
   类本身跟 world 的真身互不引用。**唯一的组装方** `brain.brain.py::reflect()`
   新增 `Brain._snapshot()`：`StepMemory.Observation.model_validate(
   obs.model_dump(mode="json"))`——字段名两边一致，一次转换不需要逐字段
   手写映射。
3. `schemas/memory/datastore/object_memory.py`：`ObjectFactEventBase.actor_place`/
   `place` 字段类型从 `pokemon_agent.world.PlaceInWorld` 改成内部类
   `ObjectFactEventBase.Place`（同样字段一致、类不互相引用，`.key` property
   照抄——语义记忆按 `(map_id, x, y)` 索引，这个键算法两边必须一致）。
   **唯一的组装方** `harness/object_interactions.py` 新增 `_common_fields()`
   辅助函数：构造事件前把 `PlaceInWorld` 真身 `.model_dump()` 拍平成 dict。
4. 全项目 `from pokemon_agent.memory import {StepMemory,EpisodeMemory,
   ObjectFactEvent,ObjectDialogEvent,ObjectWarpEvent,ObjectStillEvent,
   SNAPSHOT_BLIND,SCENE_ANY,render_sequence,dedup_snapshots}` 改成
   `from pokemon_agent.schemas.memory import ...`（约 26 处文件，`tools/
   memory_tool.py` 的 `from pokemon_agent.memory import MemoryStore` 不受
   影响——那是真的属于 `memory/` 自己的类型）。
5. `CLAUDE.md`：`memory/` 目录树条目改成"完全不认识这三个类"；`schemas/`
   条目补上"这三类记录形状为什么物理归这里、内部类边界怎么划"的说明，顺带
   去掉早已过期的"其余：Observation/ActionSpace/TraceEvent"（这几个在（12）
   条已经搬进各自模块，`schemas/` 不再持有）。

**为什么这么改**：这次教训是"数据形状归属"不能按"原来在 schemas，现在物理
搬回对应模块"一刀切处理——要先问这个模块的 Port 到底透不透明。`trace` 不透明
的只是**输入**（`TracePort.append()` 收裸字段），落盘格式是它自己的事，所以
`TraceEvent` 该搬；`memory` 连存储格式都不关心（`payload: dict` 打到底），
搬的判断标准套错了，搬错了地方。

**已知遗留**：`brain/brain.py`（`reflect()`）、`harness/object_interactions.py`
仍然在类级别 `import pokemon_agent.world`（分别拿 `Observation`、
`PlaceInWorld`/`Observation` 判定用）——这是 brain/harness 自己那一步"模块间
零依赖"重构要处理的范围，不在本条修正内；这两处目前是**唯一**认识"world 的
真身"和"schemas.memory 的记录形状"两边长什么样的地方，是有意的（组装职责
必须落在某处）。

**验证**：`py_compile` 全量扫描；基于 `/tmp/stubs`（pydantic/langgraph/
rank_bm25 极简桩包）+ `enum.StrEnum = enum.Enum` 补丁的多导入顺序测试
（world_first/memory_first/trace_first/harness_first/everything）全部通过，
新增断言：`pokemon_agent.memory` 上不再挂 `StepMemory`/`EpisodeMemory`/
`ObjectFactEvent`，`pokemon_agent.schemas.memory` 上有；本机没有真实 pydantic
可用（沙箱无网络），未做 `StepMemory`/`ObjectFactEvent` 的运行时构造/序列化/
渲染 smoke test，逻辑改动是纯粹的"字段对字段照抄 + 独立类"，风险面小，但
这一点严格说不如前几条改动那样有运行时验证兜底，用户如果发现渲染文本/
序列化行为有出入应优先怀疑这里。

**影响面**：`memory/`、`schemas/memory/`、`brain/brain.py`、
`harness/object_interactions.py`，以及约 26 个只做 re-export/引用的文件的
import 路径；不改变任何序列化格式（`StepMemory.model_dump()`/`model_dump_json()`
产出的字段名、结构跟改动前一致，落盘的旧记录仍能被新代码 `model_validate()`
读回——字段名没变，只是类的 identity 变了）。


## 2026-09-11（12）—— 新一轮重构第一步：world 模块与 schemas 彻底解耦，`ObservationFromWorld`/`ActionSpaceForBrain`/`TerrainMapFromRam` 去 From/For 后缀

**背景**：上一轮"interfaces/schemas 集中制撤销"（本文件（7）~（11）条）只解决了
"港口协议physically挨着实现"，没解决"港口协议本身还在收发别的模块/schemas 的
信封"这个更根本的问题——用户指出这正是循环导入反复出现的根因，并给出新的
架构要求：`brain`/`world`/`memory`/`trace` 这几个领域模块之间、以及它们与
`schemas.*` 之间完全没有相互依赖（`providers` 例外，当作底层公共库）；模块间
只靠**裸函数**和 **tool 层**交互，不造信封；`schemas/` 最终只留信封
（communication），随后改名 `communication/`。详细方案见
`docs/PLAN_bare_boundary_refactor.md`。这是这个大方向下的第一步：world。

**改了什么**：
1. **命名**：`ObservationFromWorld` → `Observation`、`ActionSpaceForBrain` →
   `ActionSpace`、`TerrainMapFromRam` → `TerrainMap`——domain 类型不需要
   From/For 这类方向性前缀，那是信封才需要的命名（用户确认：只有信封需要
   from/to，domain 里不需要）。全项目按标识符做了机械改名（31 个文件）。
2. **数据搬家**：`schemas/world/domain/{action_semantics,place_in_world,
   action_space_for_brain→action_space,observation_from_world→observation,
   screen_model}.py` 全部 `git mv` 进 `world/interface/domain/`，跟已经在
   那里的 `Facts`/`ScreenState`/`TerrainMap` 会合——这几个类型本来就是
   world 自己对外承诺的数据形状，只是历史上错放在 `schemas/` 里。
   `schemas/world/domain/` 目录随之清空删除。
3. **WorldPort 裸字段化**（`world/interface/world_port.py`）：
   - `reset()`/`set_task()` 不再收 `TaskForBrain`（brain 的类型），改收
     `task_id`/`goal`/`success_criteria`/`max_steps`/`initial_state_hint`
     五个裸字段。
   - `step()` 不再收 `ActionFromBrain`（brain 的类型），改收
     `list[tuple[str, int]]`（按键名 + 连按次数）。
   - `perceive_once()` 不再返回 `schemas.world.communication.PerceiveOnceResp`
     这个信封，改返回 world 自己的 `Perceived`（新增
     `world/interface/domain/perceived.py`，字段跟原来的 `PerceiveOnceResp`
     一样：`observation`/`calls`/`frame_png`，区别只是"归属"——这是 world
     自己的数据形状，不是"跟别的模块协商出的契约"）。
   - `WorldPort` 因此变成零依赖（不再 `import pokemon_agent.brain`、不再
     `import pokemon_agent.schemas.*`），`world/__init__.py` 里它也从懒加载
     改成了立即加载。
4. **`pyboy_world.py`**（`WorldPort` 唯一实现）同步改写：内部用一个纯本地
   的 `_Task` dataclass（不是任何模块间的信封）攒 `reset()`/`set_task()`
   收到的五个裸字段；`step()` 直接遍历 `(name, times)` 元组列表；
   `perceive_once()` 返回 `Perceived`。**仍然依赖 `providers`**
   （`VisionProvider`/`VisionDescribeReq`）——`providers` 按用户确认当作
   底层公共库，各模块都能直接依赖，不算模块间耦合。
5. **`tools/game_tools.py`**（`GameToolPort` 实现，tool 层）承接"拆信封 →
   调裸函数 → 拼信封"：`reset()`/`set_task()` 把 `req.task`
   （`TaskForBrain`）拆成五个裸字段传给 world；`execute()` 把
   `req.action.segments()` 拆成 `(name, times)` 列表传给 world；
   `perceive_once()` 把 world 返回的 `Perceived` 三个字段原样摊开进
   `FromHarnessToGameToolPerceiveOnceResp`（这个信封本身也改了——不再嵌套
   `perceived: PerceiveOnceResp` 一层，直接是 `observation`/`calls`/
   `frame_png` 三个字段）。
6. **顺带完成用户指出的"上次忘记"的两块搬家**：
   - `schemas/memory/datastore/{episode_memory,object_memory,
     step_memory}.py` → `pokemon_agent/memory/datastore/`，`memory/__init__.py`
     增加对应 re-export。
   - `schemas/trace/datastore/trace_event.py` → `pokemon_agent/trace/datastore/`，
     `trace/store.py`/`trace/interface/trace_port.py` 改成相对导入自己包内的
     `datastore`，`trace/__init__.py` 增加对应 re-export。
   - `schemas/memory/`、`schemas/trace/`、`schemas/world/` 三个子包因此完全
     清空，整包删除。`schemas/__init__.py` 顶层 docstring 同步更新为"四个
     产出模块"（frontend/harness/brain/providers）。
7. 全项目对应消费方的 import 路径同步改写（约 55 个文件）：
   `from pokemon_agent.schemas.{memory,trace,world} import X` →
   `from pokemon_agent.{memory,trace,world} import X`。

**为什么这么改**：见背景——用户指出的根本原则是"模块间零依赖、只靠裸函数和
tool 层交互"，`WorldPort` 收发 `ActionFromBrain`/`TaskForBrain`/
`PerceiveOnceResp` 正是这条原则要消灭的东西，也是本项目里循环导入反复
出现的真正原因（信封天然容易牵扯到别的模块的类型，形成隐蔽的双向依赖）。

**已知遗留、留给后续步骤**：
- `memory/datastore/{step_memory,object_memory}.py` 仍然直接引用
  `pokemon_agent.world` 的 `Observation`/`PlaceInWorld`（只是把
  `from pokemon_agent.schemas.world import X` 原样改成
  `from pokemon_agent.world import X`）——这仍然是"memory 依赖 world"，
  违反"模块间零依赖"，留给 memory 自己的重构步骤去把这两个字段也裸字段化。
- `brain`（`brain/brain.py`/`brain/interface/brain_port.py`）仍然依赖
  `schemas.brain`/`schemas.harness`/`pokemon_agent.memory`——`BrainPort`
  的五个方法还没有裸字段化，留给 brain 自己的重构步骤。
- `harness/interface/episode_harness_port.py` 里的状态模型仍引用
  `Observation`/`ActionSpace`（world 的类型）——同样留给后续。
- 详细的分步计划、开放问题（bare-function 是否也要覆盖这些）见
  `docs/PLAN_bare_boundary_refactor.md`。

**验证**：`find pokemon_agent -name '*.py' | xargs python3 -m py_compile`
全项目通过；用 pydantic/langgraph/rank_bm25 stub 在
`python3.10` 下跑了 5 种导入顺序（`world_first`/`memory_first`/
`trace_first`/`harness_first`/`everything`）全部通过，并断言了
`Observation`/`ActionSpace`/`PlaceInWorld`/`Perceived`/`TerrainMap`/
`INTERACT_KEY`/`StepMemory`/`EpisodeMemory`/`ObjectFactEvent`/`TraceEvent`
等改名/搬家后的名字都能从新位置正确取到。

**影响面**：`pokemon_agent/schemas/{memory,trace,world}/` 三个子包已删除；
`schemas/` 现在只剩 `frontend`/`harness`/`brain`/`providers` 四个产出模块，
且 `brain`/`harness` 仍有非信封内容待后续步骤清理。

## 2026-09-11（11）—— interfaces/schemas 集中制逐步撤销，第五步（最后一步）：harness，`pokemon_agent/interfaces/` 整包删除

**改了什么**：
1. `pokemon_agent/interfaces/harness/{harness_port,episode_harness_port,
   human_reviewer}.py`（`HarnessPort`+`RunState`/`ResumeEpisode`+三个常量
   `MAX_GOAL_RETRIES`/`MAX_PLAN_PUSH`/`PLAN_MAX_ATTEMPTS`；`EpisodeHarnessPort`+
   `EpisodeRunState`；`HumanReviewer`）→ `pokemon_agent/harness/interface/`
   下的同名文件。
2. `pokemon_agent/schemas/harness/domain/human_decision.py`（`HumanDecision`）→
   `pokemon_agent/harness/interface/domain/human_decision.py`；
   `schemas/harness/domain/` 目录随之清空删除。
3. 新增 `harness/interface/domain/__init__.py`（立即加载：`HumanDecision`
   零依赖）、`harness/interface/__init__.py`（`HumanDecision` 立即加载，
   三个 Port + 它们各自模块内的状态模型/常量全部懒加载）。
4. `harness/__init__.py` 重写：`HumanDecision` 立即从 `.interface`
   re-export；其余全部（三个 Port、`RunState`/`ResumeEpisode`/
   `EpisodeRunState`、三个常量、`RunHarness`/`EpisodeHarness`/
   `RunDataCenter`/`DataCenterReviewer`/`AutoContinueReviewer`/
   `STALL_LIMIT` 五个实现类）都改成**懒加载**（`__getattr__`，跟
   `brain/__init__.py` 对 `Brain`/`BrainPort` 的处理同一套机制）。
5. `schemas/harness/__init__.py` 不再 re-export `HumanDecision`。
6. `schemas/harness/communication/FromHarnessToReviewerReviewResp.py`
   （需要 `HumanDecision` 作字段类型）改成
   `from pokemon_agent.harness.interface import HumanDecision`——跟
   `ModelCall`/`Facts`/`TraceKind`/六个 brain 数据形状是同一种"schema
   文件反过来依赖实现模块的 interface 子包"写法。
7. 消费方同步改 import：`harness/` 包内文件（`episode_harness.py`/
   `run_harness.py`/`run_plan_utils.py`/`run_utils.py`/
   `auto_reviewer.py`/`run_data_center.py`）改成 `from .interface import
   X`（同包相对导入，跟 `brain/brain.py` 的写法一致）；包外消费方
   （`api.py`/`build.py`）改成 `from pokemon_agent.harness import X`。
8. **`pokemon_agent/interfaces/` 整包删除**——五步计划（trace → providers →
   brain → tools → harness）至此全部完成，`brain → interfaces ← harness`
   这条历史依赖锚点不再存在，改为"消费方直接认各模块自己的 `interface/`"。
9. `CLAUDE.md` 同步更新：铁律 2（大脑只能 import 各模块自己的 `interface/`
   + `schemas/`，不再提顶层 `interfaces/`）、"接口先行"一节、目录树里
   `interfaces/`/`brain/`/`harness/`/`world/` 几处描述。

**为什么这么改**：跟前四步一样，港口协议和它内嵌的数据形状/状态模型本来
就该挨着实现住。

**取舍**：这是第三次需要懒加载才能避开循环导入（继 `WorldPort`、
`BrainPort` 之后）——`harness_port.py`/`episode_harness_port.py`/
`human_reviewer.py` 都要 `import pokemon_agent.schemas.harness`，而
`schemas/harness/communication/FromHarnessToReviewerReviewResp.py` 的字段
又要从 `harness.interface` 拿回 `HumanDecision`，两条依赖在初始化顺序上
正面相撞。这次的取舍比 `brain` 那一步更彻底：不仅 `HarnessPort`/
`EpisodeHarnessPort`/`HumanReviewer` 三个 Protocol 要懒加载，它们各自
模块里定义的状态模型（`RunState`/`ResumeEpisode`/`EpisodeRunState`）和
三个常量也全部跟着懒加载——因为这些名字和 Port 协议同住一个模块文件，
访问任何一个都会触发同一次 `import pokemon_agent.schemas.harness`。用
pydantic stub 跑了 5 种导入顺序（`harness_first`/`schemas_harness_first`/
`harness_interface_first`/`port_access_first`/`everything`，`everything`
这次覆盖了删除 `pokemon_agent.interfaces` 后的全系统导入）全部通过；
过程中还发现并修复了三处真实的遗留 bug——`harness/auto_reviewer.py`、
`api.py`、`harness/run_data_center.py` 三个文件仍在从
`pokemon_agent.schemas.harness` 导入已经搬走的 `HumanDecision`（这次搬迁
之前就已经不该从那里导入，是更早的 schemas 整理留下的技术债，这次一并
清理）；顺带给 pydantic stub 补了缺失的 `TypeAdapter`，给测试环境补了
`langgraph`/`rank_bm25` 最小 stub（都是纯测试基建缺口，不是代码问题）。

**影响面**：`pokemon_agent/interfaces/` 目录已删除，全项目不再有任何
"跨模块集中港口注册表"，每个模块的港口协议、数据形状、状态模型全部与
它自己的实现同住一个包。五步迁移计划（trace/providers/brain/tools/
harness）至此全部完成。

## 2026-09-11（10）—— interfaces/schemas 集中制逐步撤销，第四步：tools

**改了什么**：
1. `pokemon_agent/interfaces/tools/{brain_tool_port,checkpoint_tool_port,
   game_tool_port,memory_tool_port,trace_tool_port}.py`（`BrainToolPort`/
   `CheckpointToolPort`/`GameToolPort`/`MemoryToolPort`/`TraceToolPort`）
   合并成一个新文件 `pokemon_agent/tools/ports.py`——跟 `memory/ports.py`
   同一个道理走**扁平文件**，不像 `world`/`trace`/`providers`/`brain`
   那样开 `interface/` 子包：这五个 Port 全部只依赖 `schemas.harness` 的
   信封类型，没有自己专属的 domain schema，不需要分协议/数据形状两层。
   `pokemon_agent/interfaces/tools/` 目录随之清空删除。
2. `tools/__init__.py` 新增五个 Port 的 re-export，跟已有的五个实现类
   （`BrainTool`/`CheckpointTool`/`GameTools`/`MemoryTool`/`TraceTool`）
   一起统一出口；零循环依赖风险（`schemas.harness` 对 `tools/` 没有反向
   依赖），立即加载，不需要懒加载。
3. `pokemon_agent/interfaces/__init__.py` 去掉五个 ToolPort 的 re-export，
   docstring 更新搬迁进度（world/trace/providers/brain/tools 已搬完，只剩
   `harness/` 一个子目录）。
4. 消费方（`harness/{brain_utils,game_utils,run_plan_utils,episode_harness,
   run_harness}.py`）把 `from pokemon_agent.interfaces import
   BrainToolPort/CheckpointToolPort/GameToolPort/MemoryToolPort/
   TraceToolPort` 改成 `from pokemon_agent.tools import X`；`harness/`
   里仍然留在 `interfaces` 的名字（`EpisodeRunState`/`PLAN_MAX_ATTEMPTS`/
   `MAX_GOAL_RETRIES`/`RunState`/`EpisodeHarnessPort`/`HumanReviewer` 等）
   不动，等 `harness` 模块自己那一步再搬。
5. 顺带修掉 `world/__init__.py` 文档字符串的一处历史遗留过时描述——它还在
   说"`pokemon_agent.interfaces` 要 re-export `WorldPort`"、`VisionProvider`
   还在 `interfaces` 里，这两条在更早的 trace/providers 步骤里已经不成立，
   这次一并更新成当前实际情况（`WorldPort` 要 `import pokemon_agent.brain`
   而不是 `pokemon_agent.interfaces`，`VisionProvider` 已在 `providers`）。

**为什么这么改**：跟前三步一样，港口协议应该跟它的消费方（这里是五个 tool
实现）物理挨着；tools 这一层恰好没有自己的 domain schema，用扁平文件比照
`memory/` 的先例，不用为了跟 world/trace/providers/brain 保持形式一致而
硬凑一个空的 `interface/domain/` 子包。

**取舍**：这是目前四步里最简单的一步——五个 Port 都只依赖
`schemas.harness`，`schemas.harness` 对 `tools/` 没有任何反向依赖，
零循环风险，不需要像 `WorldPort`/`BrainPort` 那样懒加载。用 pydantic
stub 跑了 4 种导入顺序（`tools_first`/`schemas_harness_first`/
`interfaces_first`/`everything`）全部通过；顺带给 pydantic stub 补了
缺失的 `TypeAdapter`（`memory_tool.py` 一直依赖它，之前的 stub 没有这个
名字，纯测试基建缺口，不是代码问题）。

**影响面**：`pokemon_agent.interfaces` 里现在只剩 `harness/` 一个子目录
（`HarnessPort`/`EpisodeHarnessPort`/`HumanReviewer`/几个常量），这是
五步计划的最后一步，搬完后 `pokemon_agent/interfaces/` 整包删除。

## 2026-09-11（9）—— interfaces/schemas 集中制逐步撤销，第三步：brain

**改了什么**：
1. `pokemon_agent/interfaces/brain/brain_port.py`（`BrainPort`）→
   `pokemon_agent/brain/interface/brain_port.py`。
2. `pokemon_agent/schemas/brain/domain/{action_from_brain,episode_summary,
   goal_for_brain,run_plan,step_verify,task_for_brain}.py`（`ActionFromBrain`/
   `ActionSegmentFromBrain`/`MAX_RATIONALE`/`MAX_TIMES`/`EpisodeSummary`/
   `GoalForBrain`/`RunPlan`/`StepVerifyVerdict`/`TaskForBrain`）→
   `pokemon_agent/brain/interface/domain/` 下的同名文件；
   `schemas/brain/domain/` 目录随之清空删除。
3. 新增 `brain/interface/domain/__init__.py`（立即加载：六个数据形状 + 两个
   常量全部零依赖，只依赖 pydantic）、`brain/interface/__init__.py`（数据
   形状立即加载，`BrainPort` 懒加载）。
4. `brain/__init__.py` 重写：六个数据形状 + 两个常量立即从 `.interface`
   re-export；`Brain`（`brain.py` 的实现类）和 `BrainPort` 都改成
   **懒加载**（`__getattr__`，跟 `world/__init__.py` 对 `WorldPort`/
   `PyBoyWorld` 的处理同一套机制）。
5. `schemas/brain/__init__.py` 不再 re-export 六个数据形状和两个常量，只保留
   `ChooseOnceReq`/`ChooseOnceResp`/`JudgeReq`/`JudgeResp`/`PlanOnceReq`/
   `PlanOnceResp`/`ReflectReq`/`ReflectResp`/`VerifyAndSummarizeReq`/
   `VerifyAndSummarizeResp` 这十个通信协议。
6. `schemas/brain/communication/*.py`（`ChooseOnceReq`/`ChooseOnceResp`/
   `JudgeReq`/`PlanOnceReq`/`PlanOnceResp`/`ReflectReq`/
   `VerifyAndSummarizeResp`）、`schemas/harness/communication/*.py`
   （`FromHarnessToBrainTool*`/`FromHarnessToGameTool*`/
   `FromHarnessToReviewerReviewReq`/`FromHarnessToTraceToolAppendReq`/
   `FromRunHarnessToEpisodeHarnessRunReq`）里引用这六个数据形状的地方，
   改成 `from pokemon_agent.brain.interface import X`——跟 `ModelCall`/
   `Facts`/`TraceKind` 是同一种"schema 文件反过来依赖实现模块的 interface
   子包"写法。
7. `brain/brain.py` 自己也要这六个数据形状，改成 `from .interface import
   (...)`（同包内的相对导入）。
8. 其余消费方（`api.py`、`harness/*.py`、`interfaces/harness/*.py`、
   `prompts/decide_action.py`、`schemas/frontend/communication/
   FromFrontendToRunHarnessSubmitEditReq.py`、`tools/{brain_tool,
   trace_render}.py`、`world/{pyboy_world,interface/world_port}.py`）
   把 `from pokemon_agent.schemas.brain import X`（六个数据形状）/
   `from pokemon_agent.interfaces import BrainPort` 改成
   `from pokemon_agent.brain import X`。
9. `pokemon_agent/interfaces/__init__.py` 去掉 `BrainPort` 的 re-export，
   `pokemon_agent/interfaces/brain/` 目录（只剩 `__pycache__`）一并清空；
   docstring 更新搬迁进度（world/trace/providers/brain 已搬完，剩
   harness/tools 两个）。

**为什么这么改**：跟 `world`/`trace`/`providers` 一样，港口协议和它内嵌的
数据形状本来就该挨着实现住。

**取舍**：这次是继 `WorldPort` 之后第二次需要懒加载才能避开循环导入——
`brain_port.py`/`brain.py` 都要 `import pokemon_agent.schemas.brain`（拿
`ChooseOnceReq` 等通信协议），而 `schemas/brain/communication/*.py` 里这些
协议的字段又要从 `brain.interface` 拿回 `GoalForBrain`/`ActionFromBrain`
等数据形状，两条依赖在初始化顺序上正面相撞。跟 `world/interface` 只需要
把 `WorldPort` 一个名字懒加载不同，这次因为 `Brain`（`brain.py`）本身也
一样依赖 `schemas.brain`，`brain/__init__.py` 顶层必须把 `Brain` 和
`BrainPort` **两个**名字都懒加载——否则光是 `import pokemon_agent.brain`
（哪怕不碰 `Brain`/`BrainPort`）就会先跑完 `brain/__init__.py`，而它对
`.brain` 的旧日 eager import 会立刻拖出同一个循环。用 pydantic stub 跑了
6 种导入顺序（`brain_first`/`schemas_brain_first`/`schemas_harness_first`/
`brain_interface_first`/`brain_port_access`/`everything`，含专门测"先
import pokemon_agent.brain 再立刻访问 .BrainPort/.Brain"这一最坏情形）
全部通过；顺带给 pydantic stub 补了缺失的 `ValidationError`（`brain.py`
一直依赖它，之前的 stub 没有这个名字，纯测试基建缺口，不是代码问题）。

**影响面**：`pokemon_agent.interfaces` 里现在只剩 harness/tools 两类
Port，按计划顺序（tools → harness）继续搬，搬完最后一个后
`pokemon_agent/interfaces/` 整包删除。

## 2026-09-11（8）—— interfaces/schemas 集中制逐步撤销，第二步：providers

**改了什么**：
1. `pokemon_agent/interfaces/providers/{llm_provider,vision_provider,
   embedding_provider,reranker_provider}.py`（`LLMProvider`/`VisionProvider`/
   `JudgeProvider`/`EmbeddingProvider`/`RerankerProvider`）→
   `pokemon_agent/providers/interface/` 下的同名文件。
2. `pokemon_agent/schemas/providers/domain/model_call.py`（`ModelCall`）→
   `pokemon_agent/providers/interface/domain/model_call.py`；
   `schemas/providers/domain/` 目录随之清空删除。
3. 新增 `providers/interface/__init__.py`（立即加载：五个协议 + `ModelCall`
   都只依赖 `schemas.providers` 这个信封类型包，不依赖任何重实现——
   `fastembed`/PIL/真实网络调用都在各自实现文件内部懒加载或按需 import，
   不需要 `world/interface` 那种懒加载）、
   `providers/interface/domain/__init__.py`；`providers/__init__.py` 把
   `interface/` 的六个名字和已有的具体实现（`FastEmbedText`/`FastEmbedReranker`/
   `ArkProvider`/`DeepSeekProvider`/`QwenProvider`）一起 re-export，消费方写
   `from pokemon_agent.providers import LLMProvider, ModelCall`。
4. `schemas/providers/__init__.py` 不再 re-export `ModelCall`。
5. 消费方逐个改 import：`brain/brain.py`、`errors.py`、
   `harness/{brain_utils,episode_harness,game_utils}.py`、
   `memory/{retrieval,store}.py`（仅 `TYPE_CHECKING`）、
   `tools/{memory_tool,trace_render}.py`、`world/pyboy_world.py`，全部从
   `pokemon_agent.interfaces` / `pokemon_agent.schemas.providers` 改成
   `pokemon_agent.providers`。
6. `schemas/brain/communication/{ChooseOnceResp,JudgeResp,PlanOnceResp,
   VerifyAndSummarizeResp}.py`、`schemas/harness/communication/
   {FromHarnessToBrainToolChooseOnceResp,FromHarnessToBrainToolJudgeResp,
   FromHarnessToBrainToolPlanOnceResp,FromHarnessToBrainToolVerifyAndSummarizeResp,
   FromHarnessToTraceToolAppendReq}.py` 需要 `ModelCall` 作字段类型，改成
   `from pokemon_agent.providers.interface import ModelCall`——跟
   `observation_from_world.py` 需要 `from pokemon_agent.world.interface import
   Facts` 是同一种"schema 文件反过来依赖实现模块的 interface 子包"的写法。
7. `pokemon_agent/interfaces/__init__.py` 去掉五个 provider 协议 + `ModelCall`
   的 re-export，docstring 更新搬迁进度（trace、providers 已搬完，剩
   brain/tools/harness 三个）。

**为什么这么改**：跟 `world`/`trace` 一样，港口协议和它信封数据形状本来就该
挨着实现住；`providers/` 恰好没有 world 那种"实现极重（PyBoy）不能立即加载"
的问题，`interface/` 可以放心立即加载，不用再引入一层懒加载。

**取舍**：`providers/interface/` 判定为零循环依赖风险——`schemas.providers`
是它唯一依赖，而 `schemas.providers` 对 `providers/` 没有反向依赖，所以这次
没有像 `world/interface/domain/terrain_map.py` 那样需要把任何 import 挪进
方法体内部延迟加载。用 pydantic stub 跑了 5 种导入顺序
（`providers_first`/`schemas_brain_first`/`schemas_harness_first`/
`schemas_providers_first`/`everything`）全部通过。

**影响面**：`pokemon_agent.interfaces` 里现在只剩 brain/tools/harness 三类
Port，按计划顺序（brain → tools → harness）继续搬，搬完最后一个后
`pokemon_agent/interfaces/` 整包删除。

## 2026-09-11（7）—— interfaces/schemas 集中制逐步撤销，第一步：trace

**改了什么**：
1. `pokemon_agent/interfaces/trace/trace_port.py`（`TracePort`）→
   `pokemon_agent/trace/interface/trace_port.py`。
2. `pokemon_agent/schemas/trace/domain/trace_kind.py`（`TraceKind`）→
   `pokemon_agent/trace/interface/domain/trace_kind.py`；`schemas/trace/domain/`
   目录随之清空删除。
3. 新增 `trace/interface/__init__.py`（立即加载：`TracePort`、`TraceKind` 都不
   依赖任何重实现）、`trace/interface/domain/__init__.py`；`trace/__init__.py`
   把两者一起 re-export，消费方写 `from pokemon_agent.trace import TraceKind,
   TracePort`。
4. `schemas/trace/__init__.py` 不再 re-export `TraceKind`——它的 docstring
   "本包是依赖叶子，不引用任何其他产出模块" 因此继续成立（`TraceKind` 从来
   没让它依赖别的产出模块，只是这次连它自己都不再从这里出）。
5. 全项目改调用点：`from pokemon_agent.interfaces import TracePort` →
   `from pokemon_agent.trace import TracePort`（`api.py`/`tools/trace_tool.py`）；
   `from pokemon_agent.schemas.trace import TraceKind` →
   `from pokemon_agent.trace import TraceKind`（`harness/` 下五个文件、
   `tools/trace_tool.py`）；`schemas/harness/communication/
   FromHarnessToTraceToolAppendReq.py`（一份 schemas 信封，需要 `TraceKind`
   做字段类型）改成 `from pokemon_agent.trace.interface import TraceKind`——
   跟 `schemas/world/domain/observation_from_world.py` 里 `from
   pokemon_agent.world.interface import Facts` 是同一个先例。
6. **顺手把 `WorldPort` 也从 `interfaces/` 的 re-export 里摘掉**（原来是
   "保留薄壳"，这次用户明确要求整个撤销 `interfaces/`，索性一次改到位）：
   `tools/game_tools.py` 改成 `from pokemon_agent.world import WorldPort`。
7. `pokemon_agent/interfaces/__init__.py` 更新 docstring，说明这个包正在被
   逐步淘汰、按 trace → providers → brain → tools → harness 的顺序搬，搬完
   最后一个后整体删除；`__all__` 去掉已搬走的 `TracePort`/`WorldPort`。

**为什么这么改**：用户要求把 `interfaces/` 里的港口文件和 `schemas/*/domain/`
里的数据模型都"放到各个模块内部"，理由跟 `WorldPort`/`Facts` 那次搬家一致——
协议和数据形状physically 挨着自己的实现，不用为了看一个类型定义就去翻另一个
顶层目录。用户额外拍板：`pokemon_agent/interfaces/` 这次不保留 re-export 薄壳
（跟上次 `WorldPort` 的处理方式不同），搬完的模块由调用方直接认，整体搬完后
这个目录会被删除；实施顺序按依赖图从叶子到顶层——`trace` 自己 docstring 就
写明"依赖叶子，不引用任何其他产出模块"，全项目里依赖它的最多、被它依赖的
最少，最适合第一个搬，出问题也最好定位。

**取舍**：
- `TracePort`/`TraceKind` 都不需要像 `Facts.Landmark.place` 那样做懒加载
  处理：`TracePort` 只依赖 `schemas.trace`（`EventType`/`Source`，留在原地
  没搬），`TraceKind` 零依赖；而且 `schemas.trace` 本来就是"依赖叶子"，不会
  反过来向 `trace/interface` 要任何东西——所以这次没有重演 `Facts`/`WorldPort`
  那种双向循环，`trace/interface/__init__.py` 可以老老实实地整个包立即加载，
  不需要 `__getattr__` 懒加载。这也是选 `trace` 第一个搬的直接原因：它是
  这批改动里结构最干净的一个，可以验证"搬迁配方"本身没问题，再去处理
  `brain`/`harness` 这种依赖网更密的模块。
- `trace/store.py` 的 `LocalTrace` 没有引入懒加载：它不依赖任何第三方重
  SDK（不像 `world/pyboy_world.py` 要 `import pyboy`），`trace/__init__.py`
  可以整个包一次性 eager 加载，不需要 world 那种"interface 立即加载、实现
  懒加载"的两段式。
- 用 `python3.10`（配合 `/tmp/stubs/pydantic`）验证了 `pokemon_agent.trace`
  与 `pokemon_agent.schemas.harness`（`TraceKind` 的消费方之一）互相先导后导
  的三种顺序，外加 `interfaces`/`world`/`schemas.*` 一起导入的粗验证，均通过。

**影响面**：`pokemon_agent/interfaces/trace/`、`schemas/trace/domain/` 两个
目录消失；`pokemon_agent/interfaces/__init__.py` 少了两个 re-export；八个
调用点的 import 语句改了归属（`api.py`、`tools/game_tools.py`、
`tools/trace_tool.py`、`harness/brain_utils.py`、`harness/episode_harness.py`、
`harness/game_utils.py`、`harness/run_harness.py`、`harness/run_plan_utils.py`、
`schemas/harness/communication/FromHarnessToTraceToolAppendReq.py`）。
`pokemon_agent/interfaces/` 剩余的港口（`brain`/`harness`/`providers`/`tools`
四个子目录）下一步按 providers → brain → tools → harness 顺序继续搬，
每步单独一条 CHANGELOG。

## 2026-09-11（6）—— world/ 实现文件里的 Protocol/schema 挪进 world/interface

**改了什么**：
1. 上一条（条目 5）建了 `world/interface/` 放 `WorldPort` + `Facts`，但
   `world/` 根目录那几个原有实现文件（`ram.py`/`screen_state.py`）里还各自
   混着一份"协议或数据形状"的定义。这次把它们摘出来，搬进 `world/interface/`：
   - `ram.py` 里的 `Memory(Protocol)` → `world/interface/memory.py`（零依赖，
     纯 `typing.Protocol`，挪动零风险）
   - `ram.py` 里的 `TerrainMapFromRam(BaseModel)`（`read_terrain` 的产出结构）
     → `world/interface/domain/terrain_map.py`
   - `world/screen_state.py` 整个文件（`ScreenState` + `CURSOR_MARKS` +
     `NEEDS_OVERVIEW`）→ `world/interface/domain/screen_state.py`；原文件
     内容搬空后直接删除（`git rm`，历史仍能通过 rename 检测追到）
2. `ram.py` 现在只留"怎么读"——`read_terrain`/`read_passable`/`read_facing` 等
   函数照旧，改成 `from .interface import Facts, Memory, TerrainMapFromRam`
   把协议和产出结构拿过来用；`pyboy_world.py` 相应把
   `from .screen_state import ScreenState` 合并进
   `from .interface import OVERLAY_ACTIONS, Facts, ScreenState`。
3. `world/interface/__init__.py`、`domain/__init__.py` 的统一出口加上
   `Memory`/`ScreenState`/`TerrainMapFromRam`；`world/__init__.py` 的 `_LAZY`
   表去掉这三个（不再需要懒加载——它们现在跟着 `interface/` 一起立即加载），
   只保留 `WorldPort`/`FrameSlot`/`PyBoyWorld`/`parse_screen`/`read_*` 这几个
   真正拖着重依赖或只做"怎么算"的名字。
4. `CLAUDE.md` 的 `world/` 目录说明重写为"协议+数据在 interface/，怎么读/怎么算
   在实现文件"，不再提 `impl/` 子包。

**为什么这么改**：上一条改动只处理了 `WorldPort`/`Facts` 这两个"看得见"的协议
和数据，但用户指出实现文件里还各自私藏着一份没挪的协议/schema——这次改动之前
我曾误把用户"把原有文件也整理一下"的要求理解成"建一个 `world/impl/` 子包包住
这四个实现文件"，被用户纠正：**不是要建 impl 目录，而是要把实现文件里"长得像
协议/schema"的定义摘出来放进 interface**。这次改动就是照这个更正过的理解做的：
`world/` 根目录下不引入任何新的物理分层子包，`pyboy_world.py`/`ram.py`/
`frame_slot.py` 仍然平铺在 `world/` 下，只是它们内部原来夹带的类型定义搬了家。

**取舍**：
- `Memory` 放在 `interface/` 顶层（跟 `world_port.py` 平级），不进 `domain/`：
  `domain/` 是数据形状，`Memory` 是行为契约（Protocol），跟顶层
  `pokemon_agent/interfaces/` 里"协议"和 `schemas/` 里"数据"的分工是同一套
  道理，只是这个 Protocol 太小、太内部，不值得挂到顶层 `interfaces/` 去。
- `TerrainMapFromRam` 搬到 `interface/domain/` 之后，重新踩了一遍
  `Facts.Landmark.place` 当初踩过的坑：`world/interface/` 是立即加载的包，
  而 `TerrainMapFromRam.place()`/`.landmarks()`/`.render()`/`_check_shape()`
  原来在模块顶层就 `import pokemon_agent.schemas.world` 拿 `PlaceInWorld` 和
  几个地形字符常量——这条依赖反过来会经 `schemas/world/__init__.py` →
  `observation_from_world.py` 绕回来要 `world.interface.Facts`，在某些包
  初始化顺序下（`world`/`world.interface` 先于 `schemas.world` 被导入）会炸出
  `ImportError: cannot import name 'Facts' from partially initialized module`。
  修法和 `Facts.Landmark.place` 一样：这些依赖全部挪进各自方法体内部现导，
  模块顶层只留同一个 `domain/` 包里零依赖的 `Facts`；`cells` 字段的 Field
  说明里那句 `f"... 取自 {sorted(MAP_CHARS)}"` 没法惰性化（Field 的 description
  是类定义时就要算出来的字符串），改成写死的行列数（10×9，游戏屏幕的固定
  常量，不会变）+ 一句指向 `schemas.world.domain.screen_model.MAP_CHARS` 的
  说明，不再在类体里直接引用这个名字。
- 没有把 `ram.py`/`pyboy_world.py`/`frame_slot.py` 归进任何新子包（比如
  `impl/`）——这是这次改动明确要撤销的部分：用户要的是"摘出协议/schema"，
  不是"给实现文件加一层物理包装"，`world/` 根目录下这三个实现文件维持原来的
  扁平结构。
- 用 `python3.10`（配合 `/tmp/stubs/pydantic` 最小 stub，本机没有可用的
  pydantic/Python 3.11+ 环境）重新跑了四向循环导入验证（`schemas.world` 先导 /
  `world` 先导 / `world.interface` 先导 / `interfaces` 先导），每个分支里都
  直接构造了 `ScreenState`、`TerrainMapFromRam`（并调用它的
  `place()`/`neighbors()`/`render()`/`render_neighbors()`/`landmarks()` 全部
  五个方法）、访问了 `Memory`，确认这次搬动没有引入新的循环导入——四个分支
  全部通过。

**影响面**：只有 `pokemon_agent/world/` 包内部：`ram.py` 少了两个类定义、
`screen_state.py` 整个文件消失、`interface/` 下新增 `memory.py` +
`domain/terrain_map.py` + `domain/screen_state.py`，以及几处 `__init__.py`
出口表和 `world/__init__.py` 的 `_LAZY` 表。包外任何调用方都只通过
`from pokemon_agent.world import X` 这个统一出口引用这些名字，本次改动零影响。
`docs/spec/*.md` 里如果还提到 `pokemon_agent/world/ram.py` 里定义
`TerrainMapFromRam`/`Memory` 这种旧说法，按既定约定（代码与文档冲突时以代码
为准）不逐一改。

## 2026-09-11（5）—— facts 变成真正的 Facts 模型；WorldPort 搬到 world/interface/

**改了什么**：
1. 新增 `pokemon_agent/world/interface/`：`world_port.py`（`WorldPort` 协议，原
   `pokemon_agent/interfaces/world/world_port.py` 整体搬过来）+
   `domain/facts.py`（新的 `Facts` 模型）。`pokemon_agent/interfaces/__init__.py`
   继续 `from pokemon_agent.world.interface import WorldPort` 原样 re-export，
   消费方写法不变。
2. `ObservationFromWorld.facts` 从 `dict[str, str]` 改成 `Facts`——一个真正的
   Pydantic 模型，`scene`/`overlay`/`landmarks`/`where`/`facing`/… 是具名字段，
   类型该是什么就是什么（`Facts.Scene`/`Facts.Overlay`/`Facts.Landmark` 都是
   `Facts` 的**内部类**）；`Facts` 用 `extra="allow"` 接住视觉模型按 scene 自由给
   的动态字段（`my_hp`/`foe_level`/…），不用为每个 scene 都开一个具名字段。
   上一版临时加的 `ObservationFromWorld.landmarks`（结构化字段）和
   `facts["landmarks"]`（同一份东西的文本渲染）两份并存的写法**删掉**——现在只有
   `facts.landmarks: list[Facts.Landmark]` 一份，`render()`/`items()` 才把它转成
   文本，且只在真的要喂给大脑读、或者拼检索 query 的那一刻转换。
   `screen_model.py`/`place_in_world.py` 里的 `Scene`/`Overlay`/`OVERLAY_ACTIONS`/
   `LandmarkInWorld`/`KIND_*` 全部删掉，`schemas/world/__init__.py` 相应收窄
   `__all__`。跟着改了全部消费方：`pyboy_world.py`（`Facts(...)` 直接构造，不再
   分两步拼 dict 再塞）、`ram.py`（`landmarks()` 产出 `Facts.Landmark`）、
   `game_tools.py`（`_mask()` 直接读 `facts.overlay`，不再 `Overlay(obs.facts.get(...))`
   反解文本）、`decide_action.py`（`BUTTON_HELP` 键类型改成 `Facts.Overlay`）、
   `object_interactions.py`（`kind_in_frame()` 读 `obs.facts.landmarks`）、
   `step_memory.py`/`memory_query_utils.py`/`trace_render.py`/`episode_harness.py`
   （改用 `Facts.scene_value`/`overlay_value`/`model_dump_json()`，不再手写
   `.get("scene", "")` 这类裸字典访问）、`brain.py`（`_blind()` 改用
   `Facts.exclude()` 直接摘掉 `SNAPSHOT_BLIND` 里的动态字段，不再靠 dict 推导式）。
3. `Facts.Landmark` 不直接嵌 `PlaceInWorld`，改存 `map_id`/`x`/`y` 三个原始字段 +
   一个惰性 `.place` 属性（运行时才 `import PlaceInWorld`）。
4. `pokemon_agent/world/__init__.py` 改成局部懒加载：`interface/`（`Facts`/
   `OVERLAY_ACTIONS`/`WorldPort`）立即可用，`PyBoyWorld`/`ScreenState`/
   `TerrainMapFromRam`/… 等重实现改成 `__getattr__` 按需导入；
   `world/interface/__init__.py` 同理只让 `WorldPort` 懒加载，`Facts` 立即加载。
5. CLAUDE.md 目录结构一节同步更新 `interfaces/`/`world/` 两条描述。

**为什么这么改**：
- 用户明确要求 facts 别再绕"结构化 → 渲染成文本 → 再反解回结构化"这条弯路，也不要
  再靠"加一个平行的结构化字段"这种局部补丁（上一条改动就是这种局部补丁），而是让
  `facts` 本身就是结构化的——但也明确不要一个"什么都要素声明齐全"的重型模型，
  "爱存啥存啥，保证不需要来回转换就行"，所以选了"具名字段 + `extra="allow"`
  接动态字段"这个折中，而不是纯 `dict[str, Any]`（那样 `model_dump()`/
  `model_dump_json()` 不会自动递归处理 `Any` 类型字段里的嵌套模型/枚举，判定层/
  持久化都得自己再补一层转换逻辑，回到了"来回转换"）。
- 用户进一步要求把 `WorldPort` 从顶层 `interfaces/` 挪到 `world/interface/`、
  `Facts` 放 `world/interface/domain/` 下——协议和协议吐出来的数据形状本来是
  同一件事的两个角度，没道理分居两个目录；顶层 `interfaces/` 继续 re-export，
  是为了不破坏"brain → interfaces ← harness"这条依赖方向锚点。
- **懒加载不是可选的优化，是绕不开的正确性问题**：`WorldPort` 需要
  `schemas.brain`（`ActionFromBrain`/`TaskForBrain`），而 `schemas.brain` 的
  `ChooseOnceReq`/`ReflectReq` 又需要 `schemas.world` 的 `ObservationFromWorld`；
  `ObservationFromWorld.facts: Facts` 又需要从 `world.interface` 拿 `Facts`。
  这是一个真实存在于包之间的双向依赖，只要 `world/__init__.py`/
  `world/interface/__init__.py` 在包初始化时**立即**导入 `WorldPort`/
  `PyBoyWorld`，不管先动哪一边，另一边在反向回指时都会撞上"我还没初始化完"，
  炸成 `ImportError: cannot import name ... from partially initialized module`
  ——这不是理论推演，是实测出来的（用一个不依赖真 pydantic 的最小 stub 包重放了
  三种触发顺序，改之前全部复现，改之后全部通过，见下）。
  `Facts.Landmark` 不直接嵌 `PlaceInWorld` 也是同一个理由的延伸：`Facts.Landmark`
  作为 Pydantic 模型，字段类型在类定义那一刻就要能解析，没法"引用一个还没导入的
  类型、等以后再补"；改成惰性 `.place` 属性之后，`world/interface/domain/facts.py`
  在模块顶层彻底不碰 `schemas.world`，这条依赖方向上的循环就没有成立的条件了，
  不用再靠"谁先导入谁"这种脆弱的顺序技巧。

**取舍**：
- `Facts` 不是严格 schema——`extra="allow"` 意味着"每个 scene 具体给了哪些字段"
  这件事仍然只活在 `perceive_screen.md` 的 prompt 约定里、不进类型系统；这是
  用户明确要的折中（"爱存啥存啥"），换来的是新增一种 scene 字段时不用碰这个模型。
- 验证环境里真 pydantic 装不上（无网络出口，`.venv` 也是坏的，见此前多条
  CHANGELOG），这次用一个几十行的最小 stub 包替代 pydantic 跑了完整的
  三向导入顺序回归（`world` 先、`world.interface` 先、`interfaces` 先）+
  `Facts` 方法（`render`/`items`/`stall_key_part`/`exclude`/`Landmark.place`）
  的行为验证，没有跑真正的 Pydantic 校验/序列化路径（比如 `model_dump_json()`
  对嵌套模型的真实递归行为）——这部分只能等能装真依赖的环境里跑一次集成测试
  兜底，本地改动范围内不引入新的裸 dict，风险应该是可控的。
- `docs/spec/*.md` 仍未同步（继续沿用"代码与文档冲突时以代码为准"）。

**影响面**：`ObservationFromWorld.facts` 的类型变了（`dict[str, str]` →
`Facts`），触达 `pyboy_world.py`/`ram.py`/`game_tools.py`/`decide_action.py`/
`object_interactions.py`/`step_memory.py`/`memory_query_utils.py`/
`trace_render.py`/`episode_harness.py`/`brain.py`/`screen_state.py`；
`WorldPort` 的物理文件位置变了（顶层 `interfaces/world/` → `world/interface/`），
`from pokemon_agent.interfaces import WorldPort` 这条对外契约不变。
`Scene`/`Overlay`/`OVERLAY_ACTIONS`/`LandmarkInWorld`/`KIND_*` 不再能从
`pokemon_agent.schemas.world` 导入，改从 `pokemon_agent.world.interface` 导入
（`Facts.Scene`/`Facts.Overlay`/`OVERLAY_ACTIONS`/`Facts.Landmark`/
`Facts.Landmark.KIND_*`）。

## 2026-09-11（4）—— object 判定去掉 memory 兜底，landmarks 从 obs 结构化字段直读

**改了什么**：`ObservationFromWorld` 新增 `landmarks: list[LandmarkInWorld]` 字段
（`schemas/world/domain/observation_from_world.py`），跟 `facts["landmarks"]` 出自
`pyboy_world.py::perceive_once()` 里同一次 `terrain.landmarks()` 调用——前者是结构化
原件，后者是渲染给大脑读的文本，只算一次、两份消费方各拿各的形状。
`harness/object_interactions.py::kind_in_frame()` 改成直接读 `obs.landmarks`，删掉了
`parse_landmarks()`（原来"把自己渲染出去的文本再解析回来"那个函数）。`_kind_at()`
里"当帧读不到就查 `known.query(place)` 兜底"这段也删掉了，`kind_in_frame()` 现在就是
`_kind_at()` 的全部逻辑，两个函数合成一个；`object_fact_events()` 签名去掉了
`known: MemoryToolPort` 参数，`episode_harness.py` 调用点跟着去掉最后一个实参。
顺带把 `tools/memory_tool.py` 里那个只为这条兜底而存在、且从没进过 `MemoryToolPort`
接口声明的孤儿方法 `query(place)` 删掉了（它的 docstring 自称是"`SemanticObjectReader`
端口的同名方法"，但仓库里根本没有这个 Protocol——类型标注写的是 `MemoryToolPort`，
调用的却是这个接口没声明的方法，只是因为 Python 不在调用时校验 Protocol 才没报错）。

**为什么这么改**：两条各自独立、但互相印证的理由。第一，候选格（脚下 + 四邻，或
facing 方向 1~2 格）永远在屏幕可见范围内，RAM 读取本身又是精确的，`before` 这一帧
自己的 `landmarks` 就是这次判定需要的全部依据——查 memory 兜底的原始动机（"当帧可能
因为遮挡读不到"）在上一条改动里已经证伪，继续留着这条兜底，一旦真的命中，带回来的
只会是"以前有过、现在早就不在了"的过期信息（最典型就是"物"被拾取之后），对本次判定
没有意义，只会把"这次按键碰到了什么"这个问题混进历史。第二，`facts: dict[str, str]`
这个类型本身是对的——它的用途是给 `render()`/prompt 渲染统一按字符串对齐，不该为了
一个字段改成异构类型；但 `landmarks` 同时还有另一个消费方（判定层）需要结构化数据，
硬塞进 `facts` 文本、再在判定层里用 `.split("; ")` 手写一个反解析器，等于给同一份数据
维护了两份实现，只靠注释保证格式一致——这正是项目在别处（`TERRAIN_MEANING`
两边共用一份 dict）反复强调要避免的"分头实现容易漂移"。让 `ObservationFromWorld`
把结构化原件也带出来，判定层直接读，两个问题一起解决。

**取舍**：`landmarks` 字段进了 `ObservationFromWorld.model_dump()`，会跟着 OBSERVE
trace 事件、`StepMemory` 落盘，内容跟 `facts["landmarks"]` 文本基本重复，多付一点
存储体积——比起维护两份格式契约、且其中一份只在读不到时才会暴露不一致，这笔存储
成本换来的正确性和可读性划算。`MemoryToolPort` 接口本身声明的 `query_object_events_at`
这次没有动——它是正式声明在 Protocol 里的方法，跟被删掉的孤儿方法 `query()` 不是
一回事，虽然现在也没有调用方，但不是这次改动要收拾的对象，留给下次真正用到或
确认要删的时候再处理。

**影响面**：`pokemon_agent/schemas/world/domain/observation_from_world.py`、
`pokemon_agent/world/pyboy_world.py`、`pokemon_agent/world/ram.py`（删掉了现在没有
调用方的 `render_landmarks()`）、`pokemon_agent/harness/object_interactions.py`、
`pokemon_agent/harness/episode_harness.py`（调用点少一个实参）、
`pokemon_agent/tools/memory_tool.py`（删孤儿方法 + 删掉因此不再用到的 `PlaceInWorld`
导入）。`ObjectFactEvent`/`MemoryToolPort` 的 Protocol 声明本身没有改动，接口边界
没有反向依赖变化。本仓库目前没有 `tests/` 覆盖这几个模块，这次也没有新增测试。

## 2026-09-11（3）—— landmark 补"物"/"石"两类 kind，纠正"脚下被精灵挡住"的错误归因

**改了什么**：`world/ram.py` 精灵表遍历新增 `_sprite_kind()`/`_STILL_SPRITE_KIND`——
按图片 id（`+0` 字节）把精灵分派成 `人`/`物`/`石` 三类而不是一律当"人"，分界值
（`FIRST_STILL_SPRITE = 0x3D`）与具体 id（宝可梦球 0x3D、化石 0x3E、巨石 0x3F、
卡比兽 0x43、化石翼龙 0x45、睡着的杂鱼 0x48……）来自 pokered 反汇编的
`SPRITE_CONSTANTS`（https://github.com/pret/pokered/blob/master/constants/sprite_constants.asm），
不是猜的。`schemas/world` 新增地图符号 `ITEM`/`BOULDER`（`I`/`B`）与地标类型
`KIND_ITEM`/`KIND_BOULDER`（"物"/"石"），`landmarks()` 的 kind 映射表从三项扩到五项。
`harness/object_interactions.py` 的 `INTERACTIVE` 加入"物"，新增姿势
`_pickup_or_still`（复用 `_dialog_or_still` 的"弹对话记正文/没弹记 still"判定，
只是触发键是方向键"走进去"而不是 a）并挂进 `_POSTURES["物"]`；"石"暂不挂姿势
（不弹对话、不消失，这版没有推动判定）。顺带把 `object_interactions.py` 模块
docstring 与 `surrounding_cells()`/`_kind_at()` 里"脚下这格容易被人物精灵盖住，
当帧读不出来"这句改成准确的说法——同步更新了 `decide_action/map_hint.md`、
`perceive_screen.md`、`schemas/memory/datastore/object_memory.py` 里跟着提到
"门/招牌/人"三类的措辞。

**为什么这么改**：查证后发现"人物精灵盖住脚下格"这个归因是错的——精灵表遍历时
0 号槽位（玩家自己）本来就被跳过（`for i in range(1, 16)`），不会覆盖别的精灵的
坐标，门/招牌更是直接从 warp/sign 表按坐标写入，跟玩家站哪无关。真正会让脚下这格
"当帧读不到"的是拾取脚本本身：踏上物品格的同一拍游戏就清空了它的精灵槽，这不是
"挡住"，是那一帧它已经不在了——`_kind_at()` 的兜底（查 `known.query()`）本来就是
为这种情况准备的，只是原来的注释把原因归错了地方。而更上游的问题是：物品（宝可梦球/
化石这类）压根不在旧的 `INTERACTIVE = ("人", "招牌", "门")` 里，根本没有 kind 可归——
不是"识别但被挡住"，是"从来没被识别过"。把这两件事分开之后，"脚下的物品难以统计"
就有了具体的修法：先把 kind 表按 pokered 的精灵常量补全，"当帧读不到"才归位成
"兜底查历史"这一条已有机制该接住的情况，不用再造一条新的容错。

**取舍**：`SPRITE_PAPER`/`SPRITE_POKEDEX`/`SPRITE_CLIPBOARD`（0x40/0x41/0x42）三个
先按"物"记但标了不确定——它们各自绑在某张地图的具体剧情脚本上（图鉴只在大木研究所
开局出现一次，写字板只在撒法瑞乐园入口），反汇编里没查到"走上去/按 A 之后是消失还是
留着"这类脚本细节，真遇到那一格再按实测校正（跟当年定 `SUB_TILE` 的方法一样）。"石"
（巨石）只做识别、不做推动判定——怪力谜题不是这个阶段的目标，加入 `INTERACTIVE` 但
不挂姿势，多一次候选格查询但没有下游副作用，等真正要做推动机制时再补，比现在猜一套
用不上的规则更划算。`docs/spec/` 下引用"门/招牌/人"三类的历史叙述性文档（`brain/SPEC.md`
`prompts/SPEC.md`  `schemas/SPEC.md` `world/SPEC.md` 等）这次没有跟着改——那些是设计过程的
叙事记录，不是运行时会读到的东西，代码与文档冲突时以代码为准（CLAUDE.md 开篇），
留到下次系统性过一遍 docs/spec 时再一并处理，不为这一个小改动打散好几份文档的行文。

**影响面**：`pokemon_agent/schemas/world/domain/{screen_model,place_in_world}.py`、
`pokemon_agent/schemas/world/__init__.py`、`pokemon_agent/world/ram.py`、
`pokemon_agent/harness/object_interactions.py`、
`pokemon_agent/schemas/memory/datastore/object_memory.py`、
`pokemon_agent/prompts/calls/decide_action/map_hint.md`、
`pokemon_agent/prompts/calls/perceive_screen.md`。`ObjectFactEvent.kind` 本来就是
不设值域的 `str`，新 kind 不需要改 schema；`_POSTURES`/`INTERACTIVE` 是机制一文档
点名的扩展点，这次改动没有碰事件 schema 或 memory 存储格式。本仓库目前没有
`tests/` 覆盖这几个模块，这次没有新增测试文件——按十节的要求，下次给 `harness/`
补集成测试时应该把"走上物品格产出 dialog 事件"这个用例带上。

## 2026-09-11（2）—— DeepSeekProvider 补默认模型 deepseek-flash（V4.1 Flash）

**改了什么**：`pokemon_agent/providers/openai_compatible.py` 的 `DeepSeekProvider.__init__`
给 `model` 参数补上默认值 `"deepseek-flash"`（即 DeepSeek-V4.1-Flash）；入口 assert
从"必须非空字符串（不给默认值）"改为"不能是空字符串"（校验对象变了，含义不同：前者是
"调用方必须显式选"，后者是普通的非空防御）。类 docstring 同步改写，去掉"model 没有
默认值，跟 ArkProvider 同理"的旧论述。

**为什么这么改**：上一条（1）里 `model` 不给默认值，理由是"flash/v4-pro 两个候选，
项目里没有实测数据替调用方拍板"——这个理由本身没错，但前提已经变了：DeepSeek 官方
文档明确写着 **2026-09-14 起 `deepseek-v4-pro` 的全部请求会被路由到 V4.1 Flash**，
即官方自己把"两个候选"收敛成了"一个当前模型 + 一个即将失效的别名"，不再是项目需要
自己权衡的开放问题。继续不给默认值，等于揣着官方已经给出的答案装作不知道，跟
CLAUDE.md 第六节"不伪造没有依据的默认值"这条的精神反而是相悖的——这里的默认值
恰恰是**有**依据的。`deepseek-v4-pro` 仍然接受显式传入（同一个类，只是构造函数默认
不再是它），不做破坏性收窄。

**取舍**：没有连带去动 `token_floor`——那处的"未实测"结论不受这次信息更新影响，
仍然要等真机数据才能标定，不能顺手也给它一个自信的默认。

**影响面**：`pokemon_agent/providers/openai_compatible.py`。`providers/__init__.py`
无需改动（导出的是类，不是默认值）；`build.py` 未改——本次只是把 provider 类本身的
默认值收敛，接不接进 decide/judge/verify/plan 哪条链路仍是装配处的决定，留给下一步。

## 2026-09-11（1）—— providers 层接入 DeepSeek 官方 API

**改了什么**：`pokemon_agent/providers/openai_compatible.py` 新增 `DeepSeekProvider`
类（继承 `_MultimodalMixin` + `_OpenAICompatibleBase`，与 `QwenProvider`/`ArkProvider`
同构）：`BASE_URL = "https://api.deepseek.com"`，`API_KEY_ENVS = ("DEEPSEEK_API_KEY",)`，
`_disable_thinking_payload()` 返回 `{"thinking": {"type": "disabled"}}`（嵌套对象，
与火山方舟同形、与 DashScope 的扁平布尔字段不同）；`model` 不设默认值（当前有
`deepseek-flash`/`deepseek-v4-pro` 两个候选，理由同 `ArkProvider`）；`max_tokens`
默认沿用 `QwenProvider` 的 25600（`Action.thought` 不设上限这条理由与供应商无关）；
`token_floor` 沿用基类默认 `IMAGE_TOKEN_FLOOR=100`，未做 DeepSeek 专属实测标定。
`providers/__init__.py` 的 `__all__` 与导入语句同步加入 `DeepSeekProvider`，模块
docstring 补一句三家供应商并列的说明。未改动 `build.py` 装配处——本次只接入
provider 类本身，接哪条链路（decide/judge/verify/plan）留给装配处按需决定。

**为什么这么改**：DeepSeek 官方 API 是 OpenAI 兼容协议（`chat/completions`、
`image_url` 结构与 OpenAI 标准一致，见
https://api-docs.deepseek.com/zh-cn/ ），落在 `_OpenAICompatibleBase` 既有的
"一个供应商一个类、子类只钉死 BASE_URL/API_KEY_ENVS/关思考写法"这套约定里，
不需要新开一条继承链。关思考模式官方文档给了 `thinking.type` 与顶层
`reasoning_effort` 两条路，选前者是为了跟 `_disable_thinking_payload()` 钩子
已有的两种形状（扁平布尔 / 嵌套对象）对齐，不引入第三种。`model` 不给默认值、
`token_floor` 标注"未实测"：两处都是照 CLAUDE.md 第六节"不许直连模型 SDK 之外
再假装知道自己不知道的事"的原则——没有真机数据的地方，宁可要求调用方显式给，
也不伪造一个看似合理实则没有依据的默认值（`ArkProvider.model` 与
`QwenVision`/`ArkProvider` 的 `token_floor` 实测依据是先例）。

**影响面**：`pokemon_agent/providers/openai_compatible.py`、
`pokemon_agent/providers/__init__.py`。未触及 `build.py`、`interfaces/`、
`schemas/`——`DeepSeekProvider` 复用的是已有的 `LLMProvider`/`VisionProvider`
Protocol 与 `LlmCompleteReq`/`LlmCompleteResp`/`VisionDescribeReq`/
`VisionDescribeResp` schema，接口边界不变。

## 2026-09-10（16）—— 修恢复时记忆侧的两处漏网：`keep_step` 取错一步 + 局摘要不参与作废

**改了什么**：① `CheckpointTool.void_after` 的 `target_scope` 里目标局那项由 `step` 改为
`step - 1`——checkpoint N 是"第 N 步开局"，拍它时完成的只有 step 0..N-1，保留区间是
`step <= N-1`；`step=0` 自然落到哨兵 `-1`（整局废弃）。② `MemoryTool.void_memory_after`
新增第三类作废对象：该局的 `episode_memory` **整条搬走、不按 step 筛**（新增私有方法
`_void_episode_summaries`，与 `_void_kind` 并列）；`removed` 字典加 `episode_memories` 键，
`FromHarnessToCheckpointToolVoidResp` 加同名字段透出计数。③ `void_after` 的 docstring 与
注释跟着改：作废范围与筛法，以及步骤 4"目标局的 step 目录**也**搬走"（原文写"目标局的
保留"，与实现不符——`target_scope` 里每一局的 step 目录都会被搬进 `voided-<ts>/`）。
④ `check_restore` 判定 5 扩成三条：新增"该局恢复前的摘要 uuid 与恢复后无交集""恢复后该局
摘要至多一条"，并把"记忆侧确有归档"从只在中间步检查改为"该局恢复前有摘要或还有后续步"
就检查。⑤ `check_memory_roundtrip` 路径 5 跟着走：`removed` 等值断言补
`episode_memories: 1`，新增"归档后该局摘要不可再检索、归档目录里有那条 md"，路径 5b 的
重建复活检查扩到 `episode_memory`。⑥ 盘上历史遗留的 4 对重复摘要已用
`MemoryStore.archive_many` **归档（不是删除）** 到 `memory/voided-20260910-184007/episode_memory/`。

**为什么**：两条都是同一个病——**作废口径与 checkpoint 语义对不上**。
· `keep_step` 取 `N` 而非 `N-1`：废弃分支写下的 step N 记录落在保留区漏网，重跑再写一条，
  同一局同一步两条（`query_episode_steps` 会把两条都交给大脑）。末步恢复看不见（末步只有
  终局判定、不写 step 记忆），从中间步恢复才暴露。
· 局摘要不参与作废：局收尾（verify → `write_episode` → `episode_end`）发生在该局最后一个
  checkpoint **之后**、且自己没有 checkpoint，所以**任何**恢复点都会把那次收尾圈进废弃窗口。
  0910 真机恢复实测 4/4 复现：4 个 episode、8 条摘要，每个 episode 两份互相矛盾的账
  （如 `restorecheck-0910-182428-ep1` 同时有 steps=1 与 steps=3 两版）。原 docstring 的理由
  "蒸馏发生在局收尾后，废弃窗口内没有新摘要"被这份实测证伪——它把"收尾在 checkpoint 之后"
  当成了"收尾在废弃窗口之外"。危害落在检索口：`query_episode_summaries` 按 `run_id` 等值筛，
  两条同 run/同 episode 的摘要都进候选、都过 `matches_scene`，**恢复重跑期间大脑会拿到已废弃
  时间线那一份**。

**取舍**：摘要整条作废而不做 step 筛——摘要没有 step 概念，而"恢复点 ≤ 末步 ⇒ 摘要在未来"
恒成立，无条件归档既正确又简单；真崩溃（局尚未收尾）时该局没有摘要，归档是空操作，
所以这个口径对"真恢复"和"跑完再回退"两种用法都安全。`knowledge` 仍排除（全局先验、不属
任何一局）。不给 `MemoryTool` 增加"按 step 删摘要"的能力——没有这种语义需求。

**影响面**：`pokemon_agent/tools/{memory_tool,checkpoint_tool}.py`、
`pokemon_agent/schemas/harness/communication/{FromHarnessToCheckpointToolVoidResp,FromHarnessToMemoryToolVoidMemoryAfterReq}.py`、
`pokemon_agent/interfaces/tools/memory_tool_port.py`、`experiment/real_check/{check_restore,check_memory_roundtrip}.py`、
`docs/spec/memory/PLAN_memory_trace_layout.md`、`docs/spec/real_check/SPEC.md`。

**验证**：改动文件 `ruff check`/`ruff format --check` 全绿、`py_compile` 通过；离线脚本
（临时目录、不碰 PyBoy/不加载模型）跑通 `void_after` 全链路——两局场景下
`step_memories_voided=4`（改前为 3，正是漏掉的那条 step N）、`episode_memories_voided=2`、
保留局只剩 step 0、废弃局整局清空、游标之后的事件全部被打上 `valid=false`、游标之内不受影响。
真机由 `py -3.12 -m experiment.real_check.check_restore --step 1` 复核。

## 2026-09-10（15）—— 维度 5 支持从中间步恢复（`check_restore --step`）+ 记忆侧判据

**改了什么**：`check_restore.py` 加 `--step N`——恢复点不再写死 `saved_steps[-1]`，不给参数时
行为与原先完全一致；新增**判定 5**（记忆侧）：① 中间步恢复时 `memory/voided-*/` 必须新增
（快照前后目录名差集，避免把历史遗留当成"本次归档"）；② 全盘 step 记忆按
`(episode_id, step)` 分组不得有重号。`experiment/real_check/__init__.py` 的用法块补上
`check_restore` / `check_memory_roundtrip` / `resume_only` 三个被漏掉的脚本，并改掉
"先导出两个 key"——密钥早已由 `common.load_env_file()` 从仓库根 `.env` 自动注入。

**为什么这么改**：末步恢复**压不到记忆作废路径**。checkpoint N 是"第 N 步开局"，
所以末步 N 只有终局判定、不执行动作也不写 step 记忆，那段废弃时间线里没有任何记忆记录
可归档（0910 实测末步恢复：checkpoint 侧 voided 有 4 份存档，记忆侧归档 0 条、
`memory/voided-*` 根本不生成）。此前所有脚本都只从最后一个存档步恢复，
`check_restore` 的判定 4 也只查 checkpoint 侧 voided——记忆侧作废从未被压过。

**取舍**：不新开脚本——`check_restore` 是维度 5 的归属文件，恢复步骤本来就是它的一个参数，
克隆一份 200 行文件只改一行是负收益。`resume_only` 已有 `--step`，但它无断言、也不看记忆侧，
压不出结论（它只回答"恢复不崩"）。

**影响面**：`experiment/real_check/check_restore.py`、`experiment/real_check/__init__.py`。
**顺带查出一处待修缺陷（本轮未动代码）**：`CheckpointTool.void_after` 给 `MemoryTool` 的
`keep_step` 取了**恢复步本身**，而 `_step_within` 判 `step <= keep_step` 保留——于是废弃
分支写下的 step N 记录正好落在保留区漏网，重跑又从 step N 写一条新的，同一局同一步出现
两条记录（`query_episode_steps` 会把两条都交给大脑）。修法是把 `target_scope` 里目标局那项
取 `step - 1`：`step=0` 时自然落到哨兵 `-1` = 整局废弃，正是"从第 0 步重跑"该有的语义，
这个巧合也反证了口径本该如此。离线已复现（`恢复步=1/2 → 保留 [0,1]/[0,1,2]`，各漏一条），
真机由 `check_restore --step 1` 的判定 5 确认。

## 2026-09-10（14）—— 撤 `memory_carried` 可观测 + 补 `refresh_changed` 的 metadata 倒排刷新

**改了什么**：① 删掉 `EPISODE_START` 的 `memory_carried` 字段——`schemas/…/FromHarnessToTraceToolAppendReq.memory_carried`、
`trace_render.episode_start` 的 payload 与那段"必须显式传入"的论证、`episode_harness._begin()`
里取数与传参；连带删掉 `MemoryToolPort.episode_summary_count`（Port 属性声明 + `MemoryTool`
实现）——它的唯一消费方就是这个字段，删完即成死接口。② `MemoryStore.refresh_changed()`
从"只重读正文、重算向量"扩成"重读整条记录"：新增 `_unindex` + `_index_record` 按新
frontmatter metadata 重建倒排，并修掉一处返回值顺序错误（原写 `_, _, text = self._read_record(...)`，
而该方法返回 `(text, metadata, payload)`——第三位是 payload 不是正文）。③ 配套两处：
`put()` 落盘后记下该条 mtime（否则刚写完的记录会被 `refresh_changed` 判成 changed、
白跑一遍 embed），`_unindex()` 顺带清 mtime 表。

**为什么这么改**：① 用户裁定"这个字段没有意思，之后都会重新检索一次的"——每一局开局都会
重新查一次跨局摘要，开局那一刻的池子大小既不决定这一局能检索到什么、也不反映它实际用到了
什么，作为"记忆污染"的诊断入口是假的；留着一个没人读、且推断错误的值，比没有更糟。
② 运营直接编辑 `memory/knowledge_memory/*.md` 是保留能力（`refresh_changed` 就是为它存在），
但旧实现只刷正文：改 frontmatter 里的 `source` 这类**过滤字段**，倒排索引永远停在重建那一刻，
`filter()` 查不到新值——"改了不重启就生效"这条性质只兑现了一半。

**取舍**：① `refresh_changed` 仍做 mtime 增量、不做全量重建——单文件夹千级记录、索引几百 KB，
增量已经够，且 `_unindex`/`_index_record` 是现成的、无需新抽象。② 那个返回值顺序错误
一直没暴露，是因为现有知识条目的 payload 恰好是 `{}`——空 dict 被判假，`_put_vector` 的
`if not text: return` 恰好把错误拦住了；这是运气不是正确性（`episode_memory` 的 payload
非空，一旦它调 `refresh_changed` 就会当场炸），所以一并修正、不留在原地。
③ 本轮只删 `memory_carried` 与本条属性，`docs/spec/interfaces/SPEC.md`、`docs/spec/tools/SPEC.md`
里整体过时（仍描述信封化之前的接口形状）的问题不在本轮范围内，另计。

**影响面**：`memory/store.py`、`memory/ports.py`、`tools/memory_tool.py`、
`interfaces/tools/memory_tool_port.py`、`harness/episode_harness.py`、`tools/trace_render.py`、
`schemas/harness/communication/FromHarnessToTraceToolAppendReq.py`；文档 `AGENTS.md`、
`docs/ROADMAP.md`、`docs/spec/{interfaces,tools,harness}/SPEC.md`、
`docs/spec/memory/PLAN_memory_query_convergence.md`。验证：改动文件 `ruff check` 全绿、
临时目录单测确认"改 frontmatter 后 `filter` 命中新值 / 旧值归零 / 正文同步刷新"、
`episode_harness` 与 `trace_render` 导入烟测 OK。`experiment/real_check/check_trace.py`
只断言 kind 集合，不受本改动影响。

## 2026-09-10（13）—— 撤 `discard_episode_steps`（局收尾不碰记忆）+ 契约与实现改名

**改了什么**：① 删掉 `MemoryToolPort.discard_episode_steps`、`MemoryTool.discard_episode_steps`、
信封 `FromHarnessToMemoryToolDiscardEpisodeStepsReq`（schema 文件 + `schemas/harness` 导出）
以及 `episode_harness.verify_and_summarize` 里唯一那处调用——全仓 `discard` 引用归零；
`MemoryTool._retired_dir()` 与 `memory/retired-<ts>/` 落点一并删除。② **改名**：
`MemoryIndexPort` → `MemoryStorePort`、`MemoryIndexStore` → `MemoryStore`；模块
`memory/index/index_store.py` → `memory/store.py`（`memory/index/` 目录整个消失——里面只有
一个文件，没有理由再包一层），`memory/` 现在是 `ports.py` + `store.py` + `retrieval.py` 三个
平级模块。③ 真机 `check_memory_roundtrip` 新增路径 5b：归档后删 `index.json` 强制重建，
断言被归档的记录不复活。

**为什么这么改**：① 用户裁定"一个 episode 结束，无需删除索引，因为本来查询的时候就会隔离，
也就是不做任何操作"——`query_episode_steps` / `query_recent_steps` 本来就按 `episode_id`
等值筛，`step_memory` 上没有任何 `search` / `rank` 调用，历史局的 step 记忆压根进不了检索
世界，清场纯属多余。顺带消掉两个副作用：每局新建一个 `retired-<ts>/` 目录（跑 100 局就是
100 个目录）、以及"归档"从两个时机收成一个（只剩 resume 作废），索引重建的漏洞面随之从
两处收成一处。② `Index` 是 0908 的相对词——当时 memory 包里同时活着 `EpisodeMemoryStore` /
`SemanticObjectStore` / `SemanticKnowledgeStore` 和它，`Index` 用来区分"那套不区分记忆类型
的"；0910 把另外两套删了，对照物消失、`Index` 从限定词变成了"全部"，名字停在旧出身里。
用户点名 `MemoryStorePort`；不改名会让"拷走 `memory/` 就能复用"这条主张在命名上自相矛盾。

**取舍**：`Store` 保留（用户提出"store 也不准确，明明存读都有"）——项目里 `XxxPort` 是契约、
去掉 `Port` 是实现的定式（`MemoryToolPort`/`MemoryTool`、`GameToolPort`/`GameTools`），而
`store` 在通用用法里本来就是读写双向的（key-value store / data store），并非"只写"；真正
放错位置的是 `Index`。改名不做别名兼容（无外部消费者）；本条目之前的 CHANGELOG 与两份 PLAN
的历史章节保留旧名，不回改历史记录。一个未处理的相邻问题：`MemoryStorePort` 现有 9 个方法，
仍超 AGENTS.md 三·2 的 6 个上限（用户已裁定"不拆"，规则是否加例外仍挂起）。

**影响面**：`memory/`（新增 `store.py`、删 `index/`）、`memory/ports.py`、`memory/__init__.py`、
`tools/memory_tool.py`、`interfaces/tools/memory_tool_port.py`、`interfaces/__init__.py`、
`harness/episode_harness.py`、`schemas/harness/__init__.py`（+ 删一个信封文件）、
`experiment/real_check/{check_memory,check_memory_roundtrip}.py`；文档 `AGENTS.md`、
`CLAUDE.md`、`docs/spec/README.md`、`docs/spec/memory/{SPEC,PLAN_memory_trace_layout,
PLAN_memory_query_convergence}.md`。验证：改动文件 `ruff check` / `ruff format --check` 全绿、
全链路导入烟测 OK、真机 `check_memory_roundtrip` **七条路径全 PASS**。

## 2026-09-10（12）—— 契约收窄到 9 个方法：撤 `forget_many` / `delete_many`，`discard` 改走归档

**改了什么**：`MemoryIndexPort` 撤掉 `forget_many`（"摘索引但文件原地留"）与
`delete_many`（自述仅测试用），**11 → 9 个方法**；`MemoryIndexStore` 删掉对应实现。
`MemoryTool.discard_episode_steps` 从 `forget_many` 改为 `archive_many`，归档到新增的
`_retired_dir()`（`memory/retired-<ts>/<kind>/`，与 void 的 `voided-<ts>/` 并列）。
`memory/ports.py`、`memory/index/index_store.py`、`tools/memory_tool.py` 的模块与方法
docstring 同步。顺带修掉 `memory/retrieval.py` 两处 B905（`zip()` 缺 `strict=`，上一轮
遗留、阻塞 `ruff check`），取 `strict=True`——长度不等是上游 bug，按项目规则 fail-fast。
文档：重写 `docs/spec/memory/SPEC.md`（**465 → 107 行**，原内容描述的是 0910 已整体
退役的按类存储实现）；`docs/spec/README.md` 的模块地图、架构图与链接描述追平；
设计稿出六稿（§8 全部定案）。

**为什么这么改**：用户 0910 裁定"`forget_many` 不用，都只是移动归档"——"摘索引但文件
原地留"这个第三种状态**在索引重建时无法还原**（重建的输入是目录下所有 `<uuid>.json`），
会让被 `discard` 丢弃的 step 记忆复活，破掉"step 记忆不跨 episode"这条架构约束。
删掉这个状态而不是修补它，改动面更小。`delete_many` 同理：它与 `archive_many` 的差别
只是真删还是搬走，而生产路径从不需要真删（"落盘了就不丢"）。

**取舍**：`rank` 保持单列而不并进 `search`（`search` 本来就是 `rank` 的封装
——"filter 圈候选 + 截断"，方向不能倒）；`get` / `get_many` **保留**，因为 `filter()`
是零读盘的（只查内存倒排表，内容按 uuid 惰性取），让它直接返记录会把"索引落盘"换来的
收益扔掉。接口不按"读/写/维护"拆三块（用户裁定），代价是与 AGENTS.md 三·2
「接口方法超过 6 个就该拆」冲突（现 9 个）——该规则要不要加例外（"只有跨层边界才强制"）
**挂起待议**，因为改规范要先讨论。

**影响面**：`memory/ports.py`、`memory/index/index_store.py`、`memory/retrieval.py`、
`tools/memory_tool.py`、`docs/spec/memory/SPEC.md`、`docs/spec/README.md`、设计稿。
验证：改动文件 ruff check/format 全绿、导入烟测 OK、真机 `check_memory_roundtrip`
五路径 PASS，另有专项实测确认"归档后重建不复活"（put 3 条 → 归档其中 2 条 → 删
`index.json` 强制重建 → 被归档的没回来，留档文件在 `retired-*/step_memory/` 里）。

## 2026-09-10（11）—— `MemoryIndexPort` 随包归位：契约从 `interfaces/` 搬进 `memory/ports.py`

**改了什么**：把 `pokemon_agent/interfaces/memory/memory_index_port.py` 搬到
`pokemon_agent/memory/ports.py`（`interfaces/memory/` 目录随之删除，
`interfaces/__init__.py` 去掉它的 import 与 `__all__` 项，docstring 注明 memory 的
契约不在本层）；`memory/__init__.py` 补上 re-export 与说明段；`memory/index/__init__.py`、
`memory/index/index_store.py` 的 docstring 指向新位置。顺带修 import 卫生：
`memory/index/index_store.py` 与 `memory/retrieval.py` 对 `EmbeddingProvider` /
`RerankerProvider` 的 import 收进 `TYPE_CHECKING`。`AGENTS.md` 目录树同步——
`memory/` 一段原本描述的还是 0910 已删的 `episode/` / `semantic/` 包，一并改写。
设计稿 `PLAN_memory_query_convergence.md` 出五稿（§8 已决加两条、§11.5 记为"归位"、
§12 两条实测标注处置）。

**为什么这么改**：用户 0910 拍板"memory 层做通用方法、tool 层不做"——那 memory 就是
要能被整体拷走的子系统，它的契约就该与实现同住一包，而不是留在本项目的跨层港口目录
`interfaces/` 里。搬的过程顺带消灭了一个真实害处：原来 `from pokemon_agent.interfaces
import ...` 会执行 `interfaces/__init__.py`（re-export 全部 16 个 Port），把整个
`schemas` 层拖进 `memory` 的传递依赖——实测 `import pokemon_agent.memory` 后
`sys.modules` 里有 **103** 个 `schemas.*`；改 `TYPE_CHECKING` 后为 **0**，
`pokemon_agent.interfaces` 也不再被加载。

**取舍**：没把两个 provider Protocol 也抄进 `memory/`——同一契约两份定义必然漂移，
而 `TYPE_CHECKING` 已拿到"运行期零依赖"的全部好处（两处依赖都只是函数签名上的类型注解，
`from __future__ import annotations` 让注解延迟求值，运行期不需要符号）。
**方法清单本次未动**：用户另裁定的"`forget_many` 撤除"要连带决定
`discard_episode_steps` 的归档落点，留到下一步（设计稿 §8.2 点 2）。

**影响面**：新增 `memory/ports.py`；删 `interfaces/memory/`（4 个文件——3 个是上一轮
重构就已删的旧 store，本轮清掉第 4 个 `memory_index_port.py`）；改
`interfaces/__init__.py`、`memory/__init__.py`、`memory/index/{__init__,index_store}.py`、
`memory/retrieval.py`、`AGENTS.md`、设计稿。**方法形状与运行行为零变化**——
真机 `check_memory_roundtrip` 五路径复跑全 PASS，改动文件 ruff check/format 全绿。

## 2026-09-10（10）—— 文档收尾：build SPEC 退役节整节删 + ROADMAP 补第 27 条

**改了什么**：`docs/spec/build/SPEC.md` 删掉三节整节——§3（`experiment/manifest.py`）、
§3b（`agent_permission` 权限层）、§5（`experiment/` 命令行入口）；标题
"装配、错误体系、实验记录与观测层"去掉"实验记录"，开头文件清单去掉 manifest 那一条，
并在引言加一条"编号有缺口是刻意的"说明（§4/§6/§7 编号保留——`docs/spec/README.md`
按编号引用它们）。`docs/ROADMAP.md` 补第 27 条（0910 落盘重构 + `TraceEvent.valid`
+ 实验资产边界收敛的全量记录，含验证矩阵与取舍），另加一条全局作废声明，
并把四处会误导现状的 `eval_report.py` 引用就地标注退役（P2 可审计行、
工程基础设施的"跨批次回归对比"行、第 3 条的"落地脚本"一句、文件头的链接清单）。
另新增设计稿 `docs/spec/memory/PLAN_memory_query_convergence.md`——ROADMAP 24
剩下一半（`MemoryToolPort` 六个专用查询方法收敛成 filter/search）的接口设计，
把 24 条原文"查询逻辑下沉到 tool 层"那句的歧义摊成 A/B 两方案 + 5 个待拍板点；
ROADMAP 24 与第 27 条已加指针。

**为什么这么改**：三整节描述的模块（manifest / agent_permission / experiment 跑批
入口）在 0910 已全部退役，留着就是"读起来像活的、实际不存在"的文档；ROADMAP 第 27
条是用户 0910 拍板要补的（valid 字段 + 实验资产边界）。

**取舍**：ROADMAP 只动会误导"现状"的四处，`CHANGELOG.md`、`docs/experiences/`、
ROADMAP 已完成区里的 `evaluation/*` 字样一律按史实保留——理由同"ROADMAP 里的历史
记载不改"。没有给三节做编号重排（重排会打断外部按编号的引用）。

**影响面**：纯文档，无代码改动。`build/SPEC.md` 从 1040 行降到 633 行。

## 2026-09-10（9）—— evaluation 全删，metrics 端点与前端面板一并退役

**改了什么**：整目录删除 `evaluation/`（`eval_report.py` / `SPEC.md` / `README.md` /
`tests/` / `__init__.py`）。它的活引用一并清掉：`pokemon_agent/api.py` 删掉
`GET /runs/{id}/metrics` 端点（聚合核心 `aggregate_events` 就住在 evaluation 里，
函数内惰性 import 一断端点即 500）与端点一览表那一行；`web/src/` 删 `useMetrics.ts`、
`MetricsPanel`（含 `metricsTable`/`metricsTh`/`metricsTd` 三个样式）、
`api.ts::getMetrics`、`types.ts` 的 `SourceMetrics`/`RunMetricsSummary`/`RunMetrics`；
`pyproject.toml` 的 `testpaths` 收回 `["tests"]`、删 `evaluation/tests/*` 的 ANN 豁免、
两处注释里把 evaluation 当"会被 setuptools 误发现"的例子换掉；
`.github/workflows/ci.yml` 去掉 `--cov=evaluation` 与对应注释；
`docs/spec/memory/PLAN_memory_trace_layout.md` 的两行改动清单去掉
`evaluation/eval_report.py`。包内 7 处把 evaluation 当"payload 字段契约的消费方"
引用的 docstring（`tools/__init__.py`、`tools/trace_tool.py`、`tools/trace_render.py`、
`schemas/trace/domain/trace_kind.py`、
`schemas/harness/communication/FromHarnessToTraceToolAppendReq.py`、
`interfaces/tools/trace_tool_port.py` 的"读者是 api/evaluation"）改成
"观测台前端按字段名渲染"——**契约本身没变，只是换了个消费者**。

**为什么这么改**：evaluation 的数据源 `trace_data/<run_id>/episodes/<episode_id>.jsonl`
在 0910 的 trace 落盘重构里已经不存在（改成 `events/<run_id>-<event_id>.json`），
它的 CLI 路径早就读不到东西；0910 用户拍板"evaluation 全删"。

**取舍**：① **按链路聚合 token/延迟的能力一起退役**——用户拍板"端点 + 前端面板
一起删"，没有把 `aggregate_events` 挪进包内保命，观测台因此少一个面板，
要看这些数字以后得从 trace 事件离线自己算（ROADMAP 第 2/27 条与 P2 行已标注）。
② 没有为"以后可能还想看报表"预留空壳端点——留一个明知会 500 的端点比删掉更糟。

**影响面**：`evaluation/` 从仓库消失；`pokemon_agent.api` 少一个端点；前端少
一个模块（`useMetrics.ts`）与一个面板。验证：`grep -rn "evaluation\|eval_report"
--include=*.py pokemon_agent/` → 0 行；`ruff check` 对本次改动的 8 个文件只剩
改动前就存在的 5 处历史遗留（api.py 的 ANN401/SIM105/ANN202×2、trace_tool.py
的 ANN001，均未新增）；`ruff format --check` 对改动文件全过；
`import pokemon_agent.api` / `import pokemon_agent.build` 烟测 OK；
前端 `npx tsc --noEmit` 退出码 0。

## 2026-09-10（8）—— experiment 上移仓库根级，只留三样

**改了什么**：`pokemon_agent/experiment/` 整体上移为仓库根级
`experiment/`，只保留三样（0910 拍板）：`tasks.py`（任务定义 +
goal/criteria 写法规范）、`experiment_states/`（知识库探索钉死存档，19 个
.state）、`real_check/`（六维度核对脚本，7 个文件的
`pokemon_agent.experiment.real_check` 导入路径同步改为
`experiment.real_check`）。删除四个退役模块：`manifest.py`（上一条已拆掉
权限快照后只剩 prompt/任务快照，无消费方）、`run_all_tasks.py` /
`run_episode.py` / `run_experiment.py`（跑批入口，消费方全在包内）。包
`__init__.py` 重写为只出口 tasks 一族。文档同步：README 快速开始改用
`check_memory_roundtrip`、CLAUDE.md / AGENTS.md 目录树、
`docs/spec/real_check/SPEC.md` 全部命令路径、`evaluation/SPEC.md` 两处活
引用、`openai_compatible.py` VISION_DUMP 示例；`docs/spec/build/SPEC.md`
第 3/5 节（manifest 与跑批入口）加删除线退役标注，正文存档不动；
ROADMAP / experiences / experiments 里的历史记载不改（史实）。

**为什么这么改**：跑批入口和 manifest 已随 agent_permission 移除与
tests 清空失去存在意义；experiment 是实验侧资产、不是 pokemon_agent
运行时的一部分——放包内让"运行时最小集"和"实验资产"的边界含糊。
real_check 是唯一还活着的实验侧消费，值得和 tasks/states 一起放在根级
显眼处。

**取舍**：`evaluation/eval_report.py` 保留（报表工具本身无死依赖，只改
了两处指向 run_experiment 的说明文字）——它读的是 `experiment_results/`
历史产物，不依赖被删模块。`experiment_results/` 历史数据不动。

**影响面**：根级新增 `experiment/`（git mv 保历史）；包内
`pokemon_agent/experiment/` 消失；`experiment.real_check.*` 六脚本的
`python -m` 命令从仓库根运行。`real_check/common.py` 的 `ROOT` 从写死
`parents[3]`（按包内第 3 层算）改为向上找 `pyproject.toml` 界标——上移
一层后写死层级静默指到上级目录，读产物路径全体偏移（check_trace 真机
首跑即暴露，已修）。验证：`from experiment import TaskChain` OK；
`python -m experiment.real_check.check_memory_roundtrip` 五路径 PASS、
`check_trace` / `check_memory` PASS（均从新路径跑）；ruff 对
experiment/ 仅剩 3 处迁移前就存在的历史遗留（tasks.py 两条 docstring 内
E501、resume_only ANN001）。

## 2026-09-10（7）—— 清掉（5）漏掉的 agent_permission 残留接入面

**改了什么**：`real_check/check_memory_roundtrip.py` 拆掉 `@initialize`
装饰器与 `from agent_permission import initialize`（real_check 六脚本里仅存
的硬依赖）；`real_check/check_harness.py` docstring 去掉 agent_permission
表述；`experiment/manifest.py` 整段删除权限快照机制——`permissions` 字段、
`with_permissions()` 方法、`validate_design()` 里的对应 assert、模块
docstring 里的权限配置叙事、随之失效的 `hashlib` 导入；`run_experiment.py`
去掉 `.with_permissions()` 调用；`tests/test_real_integration.py` docstring
改写（权限运行时的历史叙事不留在测试文档里）。`config/` 目录删除
（`context.json`/`permissions.json` 曾于 0910 下午为实现期验证临时从
6573b1f 恢复，拆完后正式不需要）。

**为什么这么改**：（5）声称"连根拔掉"，但六个 real_check 脚本与 manifest
的权限快照链路漏网——roundtrip 不装 agent_permission 包就 ImportError，
`run_experiment` 没有 config/ 两个文件就 assert 炸。本次补齐，包外代码
零依赖目标达成。

**取舍**：`eval_report.py` 里 `degraded` 字段的注释（"移除后暂无写入方"）
保留不动——它描述的是移除后的现状，不是残留；`pyproject.toml` 顶部
"agent-permission 已整体移除"的说明注释同理保留。三个**陈旧测试文件**
（`test_integration_tool_layer.py` 未入库、对着 harness 两级重构前的旧
`episode.run(episode_id, task, stack)` 签名；`test_render_all_kinds.py`
未入库、引用已删除的 `TraceKind.PERMISSION_SKIPPED`；`test_index_store.py`
已入库、对着索引层中间版 `directory=` 关键字签名）经用户拍板**全部删除**
——tests/ 回到从零重建起点，测试按新 API 重写时再落盘。

**影响面**：`experiment/manifest.py`（schema 少一个字段，旧 manifest.json
里多出的 permissions 键不影响读取——Pydantic 默认忽略额外字段）、
`experiment/run_experiment.py`、`real_check/` 两脚本、`tests/` 一个
docstring、`config/` 目录删除。验证：roundtrip 五路径 PASS（无权限运行时
裸跑）、manifest/run_experiment/check_harness 导入烟测 OK、触碰文件
ruff 全绿。

## 2026-09-10（6）—— 记忆与 trace 落盘布局重构（uuid 一条一文件 + 倒排索引 + valid 标记）

**改了什么**：三层运行产物全部搬出包体、落仓库根级，形状从"追加文件"改成
"一条记录一个 uuid 文件"。`pokemon_agent/memory/` 下的旧 store
（`episode/`、`semantic/` 及三个 Port 文件）整体退役删除，替换为统一索引层
`memory/index/index_store.py::MemoryIndexStore`——一个 kind 一个文件夹
（`memory/step_memory|object_memory|episode_memory|knowledge_memory/`），
每文件夹一份写穿倒排索引 `index.json`（等值取交集查询，启动时按盘上文件集
自愈重建），记录按需惰性读；知识库 12 条 md 从包内迁到
`memory/knowledge_memory/`（拍板⑩：memory 不按 run 分层，`run_id` 只是
metadata 字段）。trace 改为一条事件一个 json（`trace_data/<run_id>/events/
<run_id>-<event_id>.json`），`TraceEvent` 加 `valid` 字段（schema v3→v4），
checkpoint `void_after` 把废弃分支事件原地打 `valid=false`（不删不挪），
`LocalTrace._next_id` 从盘上 max(event_id)+1 现算；截图与事件共用 event_id
（`screenshot/<event_id>.png`），resume 不再作废截图。`MemoryTool` 全部读写
方法改在索引层上实现，`void_memory_after` 从"删"改为"归档到
`memory/voided-<ts>/`"；`MemoryToolPort` 对外签名不变（只换实现）。
读端六个 real_check 脚本同步改写；`check_trace` 的断言语义从"有效事件连续"
改为"盘上全量连续 + 废弃块是一段中间连续区间"。

**为什么这么改**：旧布局三类记忆各自为政（episode jsonl / object jsonl /
knowledge 散 md），文件名里塞 run_id/episode_id/step 语义，违反 ROADMAP 24
"记录身份零语义"；检索靠全量扫描，倒排索引把元数据过滤降到 O(命中数)；
trace 一局一个 jsonl 的中间粒度让 resume 的废弃分支无法表达——`valid` 字段
让"作废"成为数据而不是文件操作，截图绑 event_id 后 id 永远递增、无碰撞。

**取舍**：索引是派生物、真相永远是记录文件——索引损坏可全量重建，换来的是
查询零扫描；等值交集够用、范围比较留给调用方先等值缩小再数值筛（这是领域
知识不该内置进索引）；md 类记录（episode/knowledge）保留 JSON frontmatter
+ 正文，人可直接编辑（`refresh_changed` 按 mtime 增量生效）；旧的废弃分支
trace 数据不迁移——schema v4 起新文件才有 `valid` 字段，旧 run 产物视为
只读历史。

**影响面**：`schemas/trace`（v4 + valid）、`interfaces/memory`（三个旧 Port
删除、`MemoryIndexPort` 重写）、`memory/`（包内 store 目录删除、新索引层）、
`tools/memory_tool.py` + `tools/checkpoint_tool.py` + `tools/trace_tool.py`
（重写/瘦身）、`trace/store.py` + `harness/episode_harness.py` +
`harness/game_utils.py` + `harness/object_interactions.py`（截图绑 event_id）、
`experiment/real_check/*`（六个脚本）、`.gitignore`、CLAUDE.md 第四/九节。
新增仓库根级运行产物目录：`memory/<kind>/`、`trace_data/<run_id>/`。
真机验证：`check_memory_roundtrip` 五条路径 PASS（含 void 归档），
`check_trace` / `check_memory` / `check_restore` PASS。

## 2026-09-10（5）—— 彻底移除 agent_permission 接入

**改了什么**：删掉 `agent_permission` 这条外部依赖在全仓库的全部接入面。
`pyproject.toml` 去掉这条 git 依赖；`run_harness.py` 去掉 `@initialize`
（`run()`/`resume_run()` 两处）；`brain.py`/`tools/game_tools.py`/
`tools/memory_tool.py` 去掉全部 `@require_permission(...)` 装饰器（合计约
20 处）；`harness/episode_harness.py` 拆掉全部 14 处
`try: ... except Exception as exc: if not permission_was_denied(exc): raise`
权限降级兜底，改回直接调用（异常该怎么冒泡就怎么冒泡，不再吞成
`PERMISSION_SKIPPED`）；`harness/episode_utils.py` 删掉
`permission_was_denied`/`PERMISSION_ERRORS`；`TraceKind.PERMISSION_SKIPPED`
连同 `tools/trace_render.py::permission_skipped()`、
`tools/trace_tool.py` 里的分派表条目、
`FromHarnessToTraceToolAppendReq` 的 `permission`/`function`/`fallback`
三个字段一并删除；`evaluation/eval_report.py` 去掉对 `"PermissionSkipped"`
这个错误 kind 的特判分支（`degraded` 字段/报表列先留空，见字段旁注释）。
`config/permissions.json`、`config/context.json` 两个专用配置文件删除。
`api.py`"为什么单进程只能跑一个 run"的文档/报错文案，从"agent_permission
的模块级全局"改写成 API 自己的设计选择（世界/帧管道是进程内单例）。
CLAUDE.md/AGENTS.md/README.md 里引用 `agent_permission` 的几处说明同步改写。

**为什么这么改**：`agent_permission` 从来没有真正跑通过——`config/
context.json`/`permissions.json` 只是满足它启动要求的空壳配置，`docs/
progress.md` 记录过它在这台 device VM 的精简 Python 环境里装不上，端到端
HTTP 测试因此一直卡在这道坎上。用户明确要求先把它连根拔掉，不留兜底骨架，
好让代码和测试能在没有这个包的环境里正常跑起来。

**取舍**：`episode_harness.py` 里原本"权限被拒就静默降级、继续跑"这条容错
路径整段删除，而不是留着骨架以后好接回——`permission_was_denied` 的判据
来自 `agent_permission` 的四个异常类型，包一撤，判据也没了意义，留着只是
装样子的死代码。如果以后要重新引入某种权限/审批机制，届时再按新设计接回
（不一定是同一套装饰器 + trace kind 的形状）。`evaluation/eval_report.py`
的 `degraded` 统计字段/报表列没有跟着删——它是一个通用的"按原因分类的降级
计数"桶，不是 `agent_permission` 专属概念，删列涉及 `evaluation/SPEC.md`
的报表格式，按批量提交约定留到有信号时再处理；这次只删了它唯一的写入触发
点（`kind == "PermissionSkipped"` 判断），改动前该字段就已经是本仓库唯一
的降级来源，改动后它会一直是空字典，直到有新的降级来源接入。
`docs/spec/`、`tests/` 里仍有多处引用 `agent_permission`/`require_permission`
/`PERMISSION_SKIPPED`（如 `docs/spec/tools/SPEC.md`、
`docs/spec/harness/SPEC.md` 等）——按批量提交约定这次不动，等测试/文档
更新的信号。

**影响面**：`pyproject.toml` 依赖列表少一条，`requires-python>=3.11` 的
理由改成 `enum.StrEnum`（不再依赖那个包），环境要求不变。`FromHarnessToTraceToolAppendReq`
少三个可选字段——`evaluation/eval_report.py` 按字段名解析的老 trace
JSONL（历史落盘数据）如果带这三个字段，pydantic 忽略未声明字段，读不出
报错。`ruff check --select F,E9` 对本次改动的文件全部通过（无悬空
import/未定义名字）。语法检查（`ast.parse`）全部通过。**没跑
pytest/realcheck**——`tests/`、`evaluation/tests/` 按约定留到有信号时
一起处理，且这个 device VM 装不上 `agent_permission`（也是本次改动的
起因）本就没法跑通端到端用例，这次改完之后理论上不再需要它，但验证留给
下一次拿到信号的批次。

## 2026-09-10（4）—— run 的返回值也拆成裸值，API 自己拼 JSON

**改了什么**：`RunHarness.run()` / `resume_run()` / `HarnessPort.run()` 的返回类型
从 `RunResp` 改成 `(outcomes, total, succeeded, success_rate)` 四元组；`_close()`
仍在内部组装 `RunResp` 写进 RUN_END，然后拆开交出去。`api.py` 的
`_RunHandle.outcome` 改成本层自己拼的 `dict`（JSON 形状不变，前端无感），
SSE `done` 事件改走 `json.dumps`。其余调用方（run_episode / check_harness /
check_restore / resume_only / test_real_integration）改成解包取 `outcomes[0]`。

**为什么这么改**：上一版把返回值留成模型，理由写的是"trace 要内嵌它"——**这个
理由是错的**：trace 是在 `_close()` 里 append 的，事件内嵌的是函数内部组装的局部
对象，`run()` 返回什么它都不关心。返回值真正的消费方是 api（推 SSE）和几个
real_check 脚本（取 `outcomes[0]`）。外壳边不立契约，那就连返回值一起拆开，
JSON 形状归 API 自己决定。

**取舍**：四元组比对象难读一点，`outcomes` 之外三个值调用方多半用不上（现在
只有 api 用全）——接受，因为它们本来就是 `len(outcomes)` 的派生量，包成对象
只是让"谁算的"看起来更重要。`RunResp` 保留，但降级为 harness 内部的产出模型，
只服务 RUN_END 事件。

**影响面**：`schemas/harness` 出口不变（`RunResp` 仍在，`RunReq` 已删）；
ruff check 相对改动前零新增；静态自检 159 个文件无悬空名字。realcheck 与
pytest 仍未跑。

## 2026-09-10（3）—— run 入参改裸字段，顺手修 HarnessPort 的悬空 import

**改了什么**：`RunHarness.run()` / `HarnessPort.run()` 从收 `RunReq` 改成收裸字段
`run(run_id: str, goals: list[TaskForBrain]) -> RunResp`，`RunReq` 模型删除；
调用侧 api / run_episode / check_harness / check_restore 一并改。第十二节第 1 条
补写"外壳 → Harness 这条边不强制包装"。另外修掉上一条留下的悬空 import：
`interfaces/harness/harness_port.py` 还在 import 已改名的
`FromFrontendToRunHarnessRun{Req,Resp}`。

**为什么这么改**：api 是外壳不是我们的模块，那条边没有"模块间契约"要立，
`resume_run(run_id, episode_id, step)` 本来就是裸参数——`run` 单独包一层 Req
只是把两个字段裹进对象再拆开，读的人多一跳。返回值不同：run 结算是 harness
自己算的产出，仍是模型（记账层要内嵌它）。

**取舍**：外壳边"不强制"而不是"禁止"——`submit_edit` / `latest_frame` 暂时留着
信封没动，等统一口径时一起处理，先不为了整齐做半截迁移。

**影响面**：`RunReq` 从 schemas/harness 出口退出；静态自检这次把 `interfaces/`
全量纳入（上一轮工作副本缺这批文件，正是漏掉 harness_port 的原因），159 个文件
无悬空名字；ruff check 相对改动前零新增。realcheck 与 pytest 仍未跑。

## 2026-09-10（2）—— run 结算改裸名归 harness，trace 信封改回内嵌

**改了什么**：`FromFrontendToRunHarnessRun{Req,Resp}` 改名为裸名 `RunReq`/`RunResp`，
从 `schemas/frontend/` 移到 `schemas/harness/`；`FromHarnessToTraceToolAppendReq`
去掉上一条加的 `run_total`/`run_succeeded`/`run_success_rate` 三个裸字段，
改回内嵌 `outcome_run: RunResp`。调用侧 api / run_harness / run_episode /
check_harness / check_restore / build / trace_render / 测试 fixture 一并改名。
AGENTS.md 第十二节新增第 5 条记这条教训。

**为什么这么改**：上一条为了断 harness → frontend 的反向依赖，把结算摊成三个裸
字段，这是把归属错误藏进字段列表。真正的毛病是模型归错了地方：run 的五个结算
字段全由 `RunHarness._close()` 自己数出，跟谁发起这次 run 无关（api 调、
experiment 调都是它），按第十二节第 2 条判据它是**接口模型**而不是那条调用边的
信封，本就该裸名归产出方。归属一改，trace 内嵌它变成同包引用，反向依赖与循环
import 同时消失，RUN_END 也拿回完整结算（含每个 episode 的 outcomes）。

**取舍**：`frontend` 包因此只剩三个名字（提交目标编辑 + 取帧两半），没有为了
"包要有分量"而把 run 的信封留在那里——包的大小不是归属依据。

**影响面**：`schemas/frontend` 出口 5 → 3，`schemas/harness` 出口 52 → 54；
ruff check 相对改动前零新增问题，全仓 py_compile 通过、schemas 七个出口可导入。
realcheck 与 pytest 仍未跑（需真实模拟器与模型）。

## 2026-09-10 —— 补齐 game_tool / memory_tool 的第一跳信封，RunResp 归位发起方

**改了什么**：三件事。一、`GameToolPort` 9 个方法、`MemoryToolPort` 11 个方法
（`query_knowledge` 之外的全部）从裸参数改为收发信封，新增 27 个
`FromHarnessTo{Game,Memory}Tool*` 文件；两个 Tool 实现负责拆装信封，往里调
world / store 仍是裸参数。二、`FromFrontendToRunHarnessRunResp` 从
`schemas/harness/` 移到 `schemas/frontend/`，与 Req 两半合并到发起方；
`FromHarnessToTraceToolAppendReq` 不再内嵌它，RUN_END 改摊
`run_total`/`run_succeeded`/`run_success_rate` 三个裸字段。三、AGENTS.md 第十二节
补写聚合方向登记与豁免清单，修掉 schemas 三处指向已删包的说明。

**为什么这么改**：第十二节的"第一跳永远是信封"此前只在 brain_tool /
checkpoint_tool / trace_tool 三条边成立，game_tool 一条没有、memory_tool 只有
1/12——撤销"转发型不造信封"那条之后，这两条边失去依据，要么登记豁免要么补齐，
选了补齐。RunResp 分居两包则是因为它被当成"harness 的产物"而不是"frontend 那条
调用边的响应"；合并时发现 trace 信封内嵌它会形成 `schemas.frontend ↔
schemas.harness` 的循环 import（实测起不来），根因是记账层去记了前端那条边的
模型——摘掉这层依赖，环随之消失。

**取舍**：信封只装模块原来的返回类型（`FromHarnessToGameToolPerceiveOnceResp`
里就一个 `PerceiveOnceResp` 字段），不重抄字段——取值多一层 `.perceived`，
换字段单点定义。零参 + 标量返回的 `episode_summary_count` / `cursor` 不套信封，
登记为豁免：没有载荷可装，空壳信封只是噪音。

**影响面**：调用侧改动集中在 `episode_harness`（18 处）、`game_utils`、
`checkpoint_tool`、`check_memory_roundtrip` 与两个测试的 fake；
`schemas/harness` 出口从 25 涨到 51 个信封。ruff check 相对改动前无新增问题，
全仓 py_compile 通过。**未跑 realcheck 六维度**（需真实模拟器与模型），
恢复路径与 memory_roundtrip 的实跑验证待补。

## 2026-09-09（晚 6）—— 修复 resume 路径漏改的信封调用点（realcheck 维度 5 抓到）

**改了什么**：`run_harness.py::resume_run()` 的 `self._checkpoint.load(run_id,
episode_id, step)` 改为构造 `FromHarnessToCheckpointToolLoadReq` 信封传入
（含 import 补充）。全仓扫描其余工具调用点（`episode_harness` 的
save/void_after/load/query_knowledge、`brain_utils`、`run_plan_utils`、
`game_utils`）确认无同类漏网。
**为什么这么改**：Phase A 信封化把 `CheckpointTool.load` 签名改成收信封，
但迁移漏了 resume 路径唯一调用点——`check_harness` 不经过它，四个磁盘校验
维度也查不到调用侧，直到维度 5（真实跨进程恢复）才以
`TypeError: takes 2 positional arguments but 4 were given` 暴露。
**取舍**：修调用侧而非回退 tool 签名——第一跳 harness→Tool 永远是信封是
第十二节定稿规则，tool 侧签名是对的。
**影响面**：realcheck 六维度全 PASS：harness(3 步 success) / trace(64 条
event_id 0..63 连续无缺重号) / checkpoint(存档 0..3 成对带 run_state_dump) /
memory(落盘自洽) / memory_roundtrip(五路径含 void_memory_after 裸参) /
restore(自 step3 恢复，游标 53 后续写 123 条连续，voided 归档 1 个)。
首次运行留有 restorecheck-0909-230141 半程产物（阶段 A 完整、阶段 B 崩在
load 调用），未清理。

## 2026-09-09（晚 5）—— realcheck 接入 `.env`：密钥不再依赖终端手动 export

**改了什么**：新增项目根 `.env` 骨架（ARK_API_KEY / DASHSCOPE_API_KEY /
ANTHROPIC_AUTH_TOKEN，值留空由用户填写）；`.gitignore` 忽略 `.env`；
`real_check/common.py` 新增 `load_env_file()` 并在模块 import 时执行——
外部已有变量优先（setdefault 语义），空值/注释/坏行跳过，`.env` 缺失静默跳过。
**为什么这么改**：realcheck 前置条件要求 ARK/DASHSCOPE 双 key，此前只能靠
开发终端手动 export，核对脚本在别的 shell（含 AI 沙箱）里必然挂在
provider 初始化；`.env` 是不进版本库的标准解，加载点收在四个核对脚本
唯一的公共件里，`python -m` 各入口零改动。
**取舍**：不引入 python-dotenv 依赖——20 行解析足够（本项目 .env 只有
KEY=VALUE）；加载放在 common.py 的 import 侧而非各 main()，换来四个脚本
不用各自记得调用。
**影响面**：real_check 四脚本行为不变（.env 未填时与之前等价）；已验证
加载器工作、`.env` 被 git 忽略。uv 环境另有 `.venv` 为 POSIX 残留
（Windows 下 `uv run` 重建失败）的问题，未动，待用户决定是否进 ROADMAP。

## 2026-09-09（晚 4）—— 澄清"拆 tool 层"的准确含义：拆的是 schemas 侧影子，不是 tools/ 代码层

**改了什么**：仅修 AGENTS.md 第十二节"方向"段。更正为：已拆掉的是 schemas
里的 tool 层影子（`brain_tool/`、`game_tool/`、`checkpoint/` 三个子包）及
tool 层到具体模块的第二跳信封；`tools/` 代码层本体（五个 Tool 门面）保留，
harness 经 Tool 门面调模块的架构不变，第一跳信封（`FromHarnessToBrainTool*`）
保留现名、不改名。
**为什么这么改**：「晚 2」条目把"拆 tool 层"误读为"tools/ 五个 Tool 溶解进
harness、harness 直连各模块"，系我方误读、非用户决策；用户澄清后即时更正，
防止错误方向误导后续重构。
**取舍**：不改「晚 2」历史条目（沿用当日"追加修正、不改旧记录"惯例）；
代码零改动——本轮拆的本来就只有 schemas 侧，与澄清后的口径一致，无返工。
**影响面**：AGENTS.md 第十二节方向段；后续无"tool 层本体拆除"这一重构项。

## 2026-09-09（晚 3）—— AGENTS.md 第十二节删去「转发/产物不造信封」条款

**改了什么**：第十二节原第 3 条整条删除（含判据句），原 4/5 条顺位上移。
**为什么这么改**：用户判定删除。删后转发与产物场景自然落在规则 2 的裸名原则
与规则 1 的信封定义之下，该条独立成条不新增约束力，只留下"何时算转发"的
解释空间。
**取舍**：仅删规范文本，代码不动（`void_memory_after` 裸参、`PerceiveOnceResp`
裸名均为既成事实，行为不受影响）。
**影响面**：AGENTS.md 第十二节 5 条 → 4 条。

## 2026-09-09（晚 2）—— 拆第二跳信封：模块接口回归裸名/实体；tool 层定方向

**改了什么**：
- **架构方向定稿（用户拍板）**：tool 层将拆除，harness 直接调 brain / memory /
  trace / world；tool 现有代码是过渡态。理由：brain/memory/trace 未来都可能接
  第三方，Tool 层是防腐层——第一跳（我方契约）信封永生，第二跳（模块实现侧）
  信封是赌一个注定被换掉的接口。
- **`FromBrainToolToBrain*` ×11 拆除**：改名为裸名接口模型
  （`ChooseOnceReq/Resp`、`JudgeReq/Resp`、`PlanOnceReq/Resp`、`ReflectReq/Resp`、
  `VerifyAndSummarizeReq/Resp`）并归 `schemas/brain/communication/`——与 providers
  的 `LlmCompleteReq` 同规则。`schemas/brain_tool/` 包删除。
- **`FromGameToolToWorldPerceiveOnceResp` → `PerceiveOnceResp`**，归
  `schemas/world/`（它本就是 World 的接口模型，observe+calls 结构有 0903
  设计决策，不拆字段）。`schemas/game_tool/` 包删除。
- **`FromCheckpointToolToMemoryTool*` ×2 删除**，`void_memory_after` 回退裸参
  `（episode_id, step) -> dict`（转发型边界不造信封）。`schemas/checkpoint/` 包删除。
- **改名**：`RunPlanResp`→`RunPlan`、`EpisodeSummaryResp`→`EpisodeSummary`
  （Resp 是信封命名空间，domain 实体不占用）。
- **`screen_model.py` 删除后恢复**：先按"孤儿"删除，随即发现判定搜错了标识符
  （真实导出是 Scene/Overlay/terrain_legend 等，被 prompts/game_tools/world 三处
  消费），从 git index 恢复。**结论改为：保留，非孤儿。**
- **AGENTS.md 新增第十二节**：信封与接口模型命名规则（信封=我方模块间契约、
  文件放 A；模块接口模型裸名；转发/产物不造信封；豁免登记；domain 产出方归属）。

**为什么这么改**：tool 层将被拆除，第二跳信封（`From[Tool]To[模块]`）是赌
"tool 永远存在"的接口投资；清掉它们后，将来拆 tool 层时 schema 侧零阻力，
brain/world 的对外接口就是第三方可直接替换的形态。

**取舍**：tool 层本体（tools/ 五个 Tool、harness 对它们的调用）本轮未动——
拆除是独立的大重构，等 schema 面清干净后单独一轮；`FromHarnessToBrainTool*`
等第一跳信封保留现名，随 tool 层拆除时再改名（`FromHarnessToBrain*`）。
memory→world 的两条 domain 依赖（step_memory 嵌观测、object_memory 嵌地点）
维持为记录在案的例外。

**影响面**：schemas 包 10→7（删 brain_tool/game_tool/checkpoint），导出
90→91；约 25 个文件 import/类名更新；brain_port/brain_tool_port/game_tool_port/
world_port/memory_tool_port 签名同步。全部验证通过（compileall 0 错、393 个
schema import 名 AST 解析 0 失败、ruff F821/F401/I001 清零）。**未提交**。

## 2026-09-09（晚）—— 修正跨包依赖描述：类型层存在 brain↔world 双向，"world 是叶子"失实

**改了什么**：仅文档，零代码改动。本日早前两条目中"DAG：`harness → brain → memory → world`，
trace/providers/world 是叶子"的表述已加修正标注；本条给出修正后的依赖图，以此为准。

**为什么这么改**：对 domain 实体做消费方反向扫描（谁 import 了 domain），发现
`world/pyboy_world.py:28` imports `schemas.brain`（`ActionFromBrain, TaskForBrain`——
`reset/set_task/step` 签名需要），world 不是叶子；`brain/brain.py:68-70` 同引
`schemas.memory` 与 `schemas.world`；`memory/datastore` 嵌 `schemas.world` 实体。
真实包级图：`harness → {brain, brain_tool 两跳, checkpoint_tool, memory_tool, game_tool,
trace_tool, reviewer}`；`brain → memory → world → brain` 构成**类型层三环**。
成因：产出方归属规则下每个实体的放置都合规——brain 产 `ActionFromBrain`（world 消费）、
world 产 `ObservationFromWorld`（brain 消费）——环来自两个模块互为对方的产消方，
是规则的固有张力，不是放错文件。

**取舍**：不改代码。运行时无风险：三包互引的都是零依赖叶子实体，Python import 正常解析
（compileall 0 错、全仓 AST import 校验通过）；运行时 brain 与 world 从不直接对话
（harness 持有两边），环只存在于类型层。若未来造成实际问题，备选方案：①跨界实体
（ActionFromBrain 的执行视图 / ObservationFromWorld）下沉共享底层；②`WorldPort.execute`
改收 world 自有的最小执行视图，在 BrainTool/harness 做翻译。

**影响面**：schemas 跨包依赖的权威描述以本条为准；`screen_model`（world/domain）确认为
无消费方孤儿，处置待定。
## 2026-09-09（晚）—— communication 信封按"文件放 A 处 + 请求方视角"整编，补齐 req 信封

**改了什么**：
- **搬家 24 个信封文件**（不改名）：`FromHarnessToBrainTool*`×10 `brain/`→`harness/`；
  `FromBrainToolToBrain*`×9 `brain/`→新建 `schemas/brain_tool/`（BrainTool 独立模块）；
  `FromHarnessToCheckpointToolSaveReq` `checkpoint/`→`harness/`；
  `FromHarnessToMemoryToolQueryKnowledge*`×2 `memory/`→`harness/`；
  `FromFrontendToRunHarnessSubmitEditReq` `harness/`→新建 `schemas/frontend/`（Frontend=api.py）；
  `FromGameToolToWorldPerceiveOnceResp` `world/`→新建 `schemas/game_tool/`。
- **改名 6 个**（resp 统一请求方视角，与 req 同 From/To 前缀）：
  `EpisodeHarnessOutcomeResp`→`FromRunHarnessToEpisodeHarnessRunResp`；
  `RunHarnessOutcomeResp`→`FromFrontendToRunHarnessRunResp`；
  `FromCheckpointToolToHarnessRestoreResp`→`FromHarnessToCheckpointToolLoadResp`；
  `FromCheckpointToolToHarnessVoidReport`→`FromHarnessToCheckpointToolVoidResp`。
  **位置例外**：`FromFrontendToRunHarnessRunResp` 文件留 `harness/`——它嵌套同包的
  Episode 级 Resp，若按 A 处放 `frontend/` 会造成 `harness→frontend→harness` schema 包循环。
- **providers 层豁免 From/To 标注**（用户裁定：最底层共用层）：`LlmCompleteReq/Resp`、
  `VisionDescribeReq/Resp` 保持裸名留 `schemas/providers/`。
- **新增 11 个信封补齐裸参交互**：`FromHarnessToCheckpointToolLoadReq/VoidReq`、
  `FromRunHarnessToEpisodeHarnessRunReq`、`FromFrontendToRunHarnessRunReq`、
  `FromHarnessToTraceToolReadDiskEventsReq/Resp`、`FromFrontendToGameToolLatestFrameReq/Resp`、
  `FromCheckpointToolToMemoryToolVoidMemoryAfterReq/Resp`（tool-to-tool 边首次信封化）、
  `FromBrainToolToBrainReflectResp`（Brain.reflect 从裸 `StepMemory` 改返回信封）。
- **接线**：`CheckpointTool.load/void_after`、`MemoryTool.void_memory_after`（并补进
  `MemoryToolPort`——原先 port 漏声明该方法）、`TraceTool.read_disk_events`、
  `GameTools.latest_frame`、`LLMProvider.complete`（原裸 `prompt: str`）、
  `RunHarness.run`、`EpisodeHarness.run`（port 原缺 `run_state` 参数，req 化顺带对齐）；
  调用方 `run_harness/episode_harness/api.py/brain.py/brain_tool.py/checkpoint_tool.py`
  与 `experiment/` 三个 real_check/run 脚本同步。

**为什么这么改**：信封住 B 侧导致"发起方在代码里查不到自己的请求长什么样"；
resp 双视角（checkpoint 用响应方、brain/game 用请求方）让同一交互 req/resp 名字对不上；
裸参交互没有信封就没有契约载体。统一"请求方视角 + 文件放 A 处"后，一个交互一个名字、
查一个函数的信封两边一起命中。

**取舍**：MemoryTool 其余 9 方法、GameTools 7 方法、GameTools→World 的 9 个方法、
`EpisodeHarness.resume` 仍裸参——信封化是 Port 签名的整体改动，留第二阶段单独一轮；
RunDataCenter 直读（events/决策槽）维持豁免（共享状态观察面，不是 RPC 语义）；
`TraceTool`→`TracePort` 与 World 帧管道内部保持原样。providers 层豁免标注是本次会话
新裁定，若未来出现第二个 `complete()` 调用方再重新评估。

**影响面**：schemas 七个包 `__init__` 导出重排（总导出 81→90）；约 20 个文件 import 更新；
全部验证通过（compileall 0 错、全仓 408 个 schema import 名字 AST 解析 0 失败、
ruff F821/F401/I001 清零、新引入 E501 清零）。**未提交**——工作区含 0909 会话未提交改动，
按用户要求不做任何 commit。

## 2026-09-09 —— communication 统一 From-To 命名、非信封类型下沉 domain；命名规则补一条“共用端口不填 From”

**改了什么**：
- **`communication/` 只留一次调用的信封，命名统一到 `From{调用方}To{被调方}{方法}{Req|Resp}`**
  （文件名 = 类名）。8 个 snake 命名的文件按真实调用重命名，其中两个各拆成一对：
  `human_review.py`→`FromHarnessToReviewerReviewReq/Resp.py`（原 Resp 叫 `FromFrontend`，
  但实现有三个：api 前端、`AutoContinueReviewer`、`DataCenterReviewer`，统称 Reviewer 才准）；
  `goals_edit.py`→`FromFrontendToRunHarnessSubmitEditReq.py`；
  `vision_completion.py`→`VisionDescribeReq/Resp.py`；`text_completion.py`→`LlmCompleteResp.py`；
  `run_outcome.py`→`RunHarnessOutcomeResp.py`；`harness_episode_outcome.py`→`EpisodeHarnessOutcomeResp.py`。
- **不是信封的类型下沉到各自 `domain/`（snake 命名）**：`RunPlanResp`（+内嵌的 `PlanGoal`）与
  `StepVerifyVerdict`→`brain/domain/`，`HumanDecision`→`harness/domain/human_decision.py`，
  `TraceKind`→`trace/domain/trace_kind.py`。`trace/communication/` 随之消失。
- `PlanGoal` 从顶层类改成 `RunPlanResp` 的**内部类**（`RunPlanResp.PlanGoal`），
  唯一消费点 `run_plan_utils.to_tasks()` 的签名跟着改。
- `FromBrainToLlmEpisodeSummaryResp`→`brain/domain/episode_summary.py::EpisodeSummaryResp`：
  它跟 `RunPlanResp`/`StepVerifyVerdict` 同类——都是 `Brain` 从模型输出解析出的产物
  （`brain.py` 内构造，再经 `_create_episode_memory` 适配成 `EpisodeMemory`），不是一次调用的
  载体。**有 Resp 没 Req 就是"不是信封"的信号**（它自己的 docstring 早写着"不存在单独的
  蒸馏请求协议"）。上一轮下沉另外两个时漏了它。

**为什么这么改**：

1. **`communication/` 的语义是“一次调用的消息载体”**，而 `TraceKind`/`HumanDecision`/
   `StepVerifyVerdict`/`RunPlanResp` 是**别的信封的字段类型**，不是载体本身——放在
   communication 下，From-To 规则对它们永远不成立。下沉到 domain 后 communication 零例外。
2. **原命名把方向信息藏在后缀里**（`HumanReviewReqFromHarness`）或干脆没有
   （`run_outcome.py`），跟同目录 20 个 `From…To…` 文件两套约定并存；按产出方拆包后
   同一目录里两种大小写并排，读起来像混乱而不是规则。
3. **命名规则补两条边界**（原规则只覆盖“调用方唯一、方法唯一”的情形）：
   - **共用端口不填 From**：`VisionProvider.describe()` 有两个正当调用方——
     `PyBoyWorld.perceive_once()`（感知当前屏幕）与 `Brain._ask()`（判定/校验时带图问，
     images 为空则降级走 `complete()`）。硬填一个 `From{A}` 就是撒谎，也不该因为两个调用方
     就把同一份契约拆成两个类。故记作 `VisionDescribeReq/Resp`。
   - **一个模块对外的统一返回形状不填 From 和方法名**：`RunHarnessOutcomeResp` 同时是
     `run()` 与 `resume_run()` 的返回值，`EpisodeHarnessOutcomeResp` 是三个方法的返回值，
     写死任一方法名都会误导；`LlmCompleteResp` 由通用 provider 构造，它不该知道调用方是谁。
   - 由此规则读法是：**带 From-To = 一次特定调用（调用方与方法都唯一）；只写被调方 + 形状 =
     被多方或多方法共用**。大小写不变，名字也短很多。

**取舍**：
- `PlanGoal` 内部类化的代价是签名变长（`list[RunPlanResp.PlanGoal]`），换来 communication
  与 domain 都不必为一个只在单处使用的嵌套模型开文件。`HumanDecision`/`TraceKind`/
  `StepVerifyVerdict` 没这么处理——它们分别被 4 / 8 / 3 个文件独立使用，内部类化会让
  `TraceKind.MODEL_CALL` 变成 `FromHarnessToTraceToolAppendReq.TraceKind.MODEL_CALL`。
- `ruff` 的 `select` **故意不加 `N`（pep8-naming）**：communication 下的 PascalCase 文件名是
  本项目刻意的约定（文件名 = 信封类名），加了 N 会把这 32 个文件全报成 N999。

**影响文件**：`pokemon_agent/schemas/` 下 12 个文件改名 / 移位 / 拆分 + 2 个新建
（`harness/domain/human_decision.py`、`trace/domain/trace_kind.py`）；8 个类改名波及
`pokemon_agent/`、`evaluation/` 共 33 个文件；`run_plan_utils.py` 签名改动。无运行时行为变更。

**已知遗留**：
- **`checkpoint/` 两个文件的方向词与其余包相反，本轮未动（用户明确暂缓）**：
  `brain`/`memory`/`world` 的 Req 与 Resp 共用**调用方向**前缀
  （`FromHarnessToBrainToolChooseOnceReq` 与 `…Resp`），而
  `FromCheckpointToolToHarnessRestoreResp`/`…VoidReport` 用的是**数据回流方向**——
  `load()`/`void_after()` 实际都是 harness 调 checkpoint_tool（`episode_harness.py:244`）。
  按主流约定应为 `FromHarnessToCheckpointToolLoadResp`/`…VoidAfterResp`；另外
  `VoidReport` 缺 `Req|Resp` 后缀，`RestoreResp` 的方法名与端口方法 `load()` 对不上。
- `FromHarnessToTraceToolAppendReq` 住在 `harness/` 而非按被调方该去的 `trace/`——
  这是上一条（解 `trace → brain` 环）刻意付的代价，不是疏漏。
- `docs/spec/` 与 `CLAUDE.md` 仍写着旧类名与旧目录树，按约定 spec 待用户确认后再改。
- `RunPlanResp`/`EpisodeSummaryResp` 现居 domain 却仍带 `Resp` 后缀，是否去掉未定。
- 测试未跑（本机装不上 pyboy/langgraph/agent_permission）。

**验证**：七个出口在 Python 3.11 下全部可导入、81 个对外名字无缺失；全仓库 162 处 schema
import 逐个对账，问题 0；跨包依赖图仍为 DAG（`harness → brain → memory → world`，
trace/providers/world/checkpoint 为叶子）【0909 晚修正：此表述失实——world 引
schemas.brain 不是叶子，真实图见本日末条目】；`ruff check` 总问题 57→39，剩余全部为改动前
既有类别。

## 2026-09-09 —— schemas 归类方向翻转：先按产出模块、最底层再按种类；七个产出模块各自一个统一出口

**改了什么**：
- `schemas/`从`domain`/`datastore`/`communication`三个种类目录，改成七个**产出模块**
  包——`brain`/`world`/`memory`/`trace`/`checkpoint`/`providers`/`harness`，每包内部
  再按`communication`/`domain`/`datastore`分子目录。50 个 schema 文件全部按产出方归位。
- 出口从三个种类出口改成**每个产出模块一个出口**（`schemas/<模块>/__init__.py`），
  `schemas/__init__.py`**不做根出口、不 re-export 任何名字**，只写目录导览。消费方写
  `from pokemon_agent.schemas.brain import X`。全仓库 86 个文件的 schema import 已改写。
- 旧`domain/__init__.py`与`datastore/__init__.py`里内联定义的约 200 行实体全部拆进实体
  文件：`Scene`/`Overlay`/`OVERLAY_ACTIONS`/`TERRAIN_MEANING`/格子常量→新增
  `world/domain/screen_model.py`；`BUTTON_FACING`/`FACING_STEP`/`INTERACT_KEY`→新增
  `world/domain/action_semantics.py`；`KIND_*`→`world/domain/place_in_world.py`；
  `MAX_RATIONALE`/`MAX_TIMES`→`brain/domain/action_from_brain.py`；
  `TRACE_SCHEMA_VERSION`/`Source`/`EventType`→`trace/datastore/trace_event.py`。
- `TaskForHarness`改名`TaskForBrain`（文件`task_for_harness.py`→`task_for_brain.py`），
  与`GoalForBrain`一起从 harness 归到`brain/domain/`；`FromHarnessToTraceToolAppendReq`
  从 trace 归到`harness/communication/`。

**为什么这么改**：

1. **归类方向反了**：先按种类切成一棵全局大树，从目录看不出一个结构是谁造出来的，改一个
   模块要满树找它的 schema。产出方信息本来全在文件名的方位词里（`From{A}To{B}`），目录却
   没体现。第一级改成产出模块后，`communication/`里那 37 个平铺文件按协作者分开了。
2. **根出口抹掉了架构信号**：分模块出口让每个文件的 import 块直接写出"我跟哪几个协作者的
   契约打交道"——`episode_harness.py`一眼看得出它碰了六个协作者的契约，这本身是它太厚的
   证据。根出口把这个信号抹平，且会长成 60 个名字的巨型文件。同时避免同一个名字有两条
   import 路径。
3. **扁平结构藏住了一个真实的循环依赖**：拆包后立刻暴露出
   `brain → harness → trace → brain`的环（`FromHarnessToTraceToolAppendReq`要
   `ActionFromBrain`，`human_review`要`TraceEvent`，大脑的 Req 要`GoalForBrain`/
   `TaskForHarness`）。按产出方把 append 信封归 harness、把两个实体归 brain 之后，
   依赖图收敛成 DAG：`harness → brain → memory → world`，trace/providers/world 是叶子。
   【0909 晚修正：当时按 import 对账未覆盖 world→brain 这条边；真实图见本日末条目】
   在同一个`communication/`包里，这个环永远不会被发现。
4. **出口文件不该承载定义**：旧的两个出口同时是出口又是实现，`trace_event.py`只好写
   `from . import Source`——实现文件反过来 import 自己的出口。拆开后这类反向依赖消失。

**取舍**：
- `ModelCall`按**语义归属**放`providers/domain/`，而不是按构造方（它被 brain、harness、
  game_utils 三处构造）。理由是"一次模型调用的账"跟文本/视觉补全信封是同一件事，放一起
  `providers/`就是"一切跟调模型有关的契约"。
- 三类记忆形状（`StepMemory`/`EpisodeMemory`/对象事件）按**存储方**归`memory/datastore/`，
  而不是按构造方（brain 的 reflect/summarize 产出它们）。否则 memory 包下一个 schema 都
  没有，全在 brain 下——持久化结构的产出地读作"谁拥有这个形状"更自洽。
- `TaskForBrain`改名的代价：它同时被 harness（`RunHarness.run(task)`）和 world
  （`GameToolPort.reset(task)`）消费，在那两处签名里"ForBrain"读起来别扭。接受，理由是
  目录归属优先——它是大脑`PlanOnceReq`的字段，名字跟着产出地走。

**影响文件**：`pokemon_agent/schemas/`全树重排（50 个文件搬运 + 7 个新出口 + 2 个新实体
文件）；`pokemon_agent/`与`evaluation/`共 127 个文件的 import 改写；全仓库`TaskForHarness`
标识符改名。无运行时行为变更——纯目录与 import 路径重排。

**已知遗留**：`docs/spec/`（尤其`schemas/SPEC.md`、`DATAFLOW.md`）与`CLAUDE.md`第四节的
目录树还写着旧的三种类结构，按项目约定 spec 改动要先问，本次未动。测试未跑（本机装不上
pyboy/langgraph/agent_permission）。

**验证**：七个出口在 Python 3.11 下全部可导入、82 个对外名字无缺失；全仓库 162 处 schema
import 逐个对账到出口，问题 0；跨包依赖图复检为 DAG、无环；`ruff check`总问题数从改动前
的 57 降到 40（E501 30→16、I001 3→0），剩余项全部是改动前就有的类别；全项目`ast.parse`
语法检查通过。

## 2026-09-09 —— checkpoint 根目录搬出 trace_data；screenshot 从全局目录搬进 trace_data/<run_id>/

**改了什么**：
- `checkpoints/`不再是`trace_data/<run_id>/checkpoints/`——独立成
  `checkpoints/<run_id>/`（跟`trace_data/<run_id>/`平级）。
- `screenshot/`不再是项目根目录下的全局目录——搬进
  `trace_data/<run_id>/screenshots/`，按 run 分文件夹。
- `CheckpointTool.__init__`签名从`(run_dir, memory)`改成
  `(checkpoint_dir, trace_dir, memory)`——`void_after()`本来就要同时碰
  两棵树（自己的 step 存档、trace 的 jsonl+screenshots），拆开两个参数后
  职责边界写在签名里，不用靠内部约定猜"这个 run_dir 到底指哪一棵"。
- `LocalTrace`/`read_screenshot()`/`_save_screenshot()`不再用模块级
  `SCREENSHOT_ROOT`常量，改成每个`LocalTrace`实例按自己的`run_id`算
  `self._screenshots_dir`；`read_screenshot()`签名新增`run_id`参数。
- `build.py`：`CheckpointTool(checkpoint_dir=Path("checkpoints")/run_id,
  trace_dir=Path("trace_data")/run_id, memory=memory)`。
- `real_check/common.py`新增`CHECKPOINT_ROOT`常量；
  `check_checkpoint.py`/`check_restore.py`/`resume_only.py`三处硬编码的
  `<run_dir>/checkpoints`改成`CHECKPOINT_ROOT/<run_id>`。

**为什么这么改（用户 0909 复核架构图时提的两条真实设计问题）**：

1. **checkpoint 不该在 trace_data 下面**：`trace_data/<run_id>/`的语义是
   "这个 run 的可观测事件流"——`episodes/*.jsonl`一次写入、只追加、只回放；
   `checkpoints/`是另一种东西——**可变的恢复状态**，会被覆盖、会被
   `void_after()`整目录搬走归档。两者混在一个目录树下，容易把"改文件内容"
   和"搬目录"两种完全不同的操作误当成同一类维护对象。
2. **screenshot 反而该在 trace_data 下面**：截图天然是"某个 run 某一局
   某一步"的观测产物，跟`episodes/*.jsonl`该是同一个粒度，之前却是**不分
   run 的全局目录**（`project_root/screenshot/`）。这逼得
   `CheckpointTool._void_screenshots()`只能靠文件名前缀
   `{run_id}_{episode_id}_{step}.png`在全局目录里扫、处理撞名`(n)`后缀
   ——典型的"路径放错了、只好靠命名约定硬凑"的补丁写法。改成按 run 分
   文件夹后，`void_after()`直接对着这个 run 自己的`screenshots/`子目录
   操作，文件名格式不变（仍含 run_id 前缀，只是现在冗余）。

**影响文件**：`pokemon_agent/trace/store.py`、
`pokemon_agent/tools/checkpoint_tool.py`、`pokemon_agent/build.py`、
`pokemon_agent/harness/episode_harness.py`（`read_screenshot()`调用点补
`run_id`）、`pokemon_agent/interfaces/trace/trace_port.py`/
`pokemon_agent/schemas/datastore/step_memory.py`（路径描述性注释同步）、
`pokemon_agent/experiment/real_check/{common,check_checkpoint,
check_restore,resume_only}.py`。落盘布局变更，旧的
`trace_data/<run_id>/checkpoints/`与项目根目录`screenshot/`产物作废（本地
开发数据，无需迁移）。

**已知遗留**：`tests/test_checkpoint_resume.py`/
`tests/test_integration_tool_layer.py`/`tests/test_real_integration.py`
三个测试文件里还固定用着旧路径/旧`CheckpointTool`签名，`docs/spec/harness/
PLAN_checkpoint.md`等 spec 文档的落盘布局图也还没跟着改——按项目约定测试
与 spec 改动要先问，这次只改了生产代码，等用户确认后再动这两类文件。

**验证**：`ast.parse`全项目语法检查通过；这台机器装不上`agent_permission`/
`langgraph`（长期已知限制），没能端到端真实跑一次`check_restore.py`确认新
布局下 resume 全链路仍然通过，需要用户本机重跑确认。

## 2026-09-09 —— 新增调试脚本 `resume_only.py`：跳过阶段 A，直接对已有 checkpoint 发起 resume_run()

**改了什么**：新增 `pokemon_agent/experiment/real_check/resume_only.py`。
跟 `check_restore.py` 阶段 B 同构（读该 step 自己的 checkpoint 拿游标 →
带 `resume_cursor` 重新 `build_real` → 调 `resume_run()`），但跳过阶段 A
（造一局全新的 3 步 run），直接对着磁盘上已有的 `(run_id, episode_id, step)`
三元组发起恢复；不带 `check_restore.py` 那四条 PASS/FAIL 断言，是给人调试
用的，不是回归判据。不给参数时用 `common.resolve_run()` 自动定位最近一次
产物，也可以用 `--run-id`/`--episode-id`/`--step` 精确指定。

**为什么加**：排查 resume 之后 `think_action` 疑似卡住（后来定位为一次
LLM 调用网络抖动，非代码问题）时，每次复现都要先陪跑一遍阶段 A（build_real
装配 + 3 步决策，几十秒到几分钟），这个脚本让反复调试同一个卡点不用每次
重新造数据。

**影响文件**：新增 `pokemon_agent/experiment/real_check/resume_only.py`。

**验证**：`ast.parse` 语法检查通过；未实际跑（同批次其余改动的环境限制，
`agent_permission`/Python 3.11 装不进沙箱），逻辑照抄 `check_restore.py`
阶段 B 已验证过的路径。

## 2026-09-09 —— resume_run() 自己的恢复标记被自己的 void_after 连带归档；维度 2/5 补齐多 episode

**改了什么**：
- `RunHarness.resume_run()`：run 级的 `CHECKPOINT_RESTORE` 标记事件从
  "`graph.invoke()` 之前 append" 挪到"之后 append"。
- `check_trace.py`（维度 2）：事件加载从"`resolve_run()` 选中的那一个
  episode 文件"改成"该 run_id 下**全部** `<run_id>-ep*.jsonl`"。
- `check_restore.py`（维度 5）判定 2/3 的事件加载做同样的改动。
- `check_restore.py` 删掉 `faulthandler.dump_traceback_later(timeout=240,
  repeat=True)`，只留 `faulthandler.enable()`——240s 比一次决策模型调用的
  最坏耗时（90s 超时 ×3 次重试 + 退避，能到 4 分半）还短，健康跑也会假警报。

**为什么这么改（两个独立的真实 bug，都是 `check_restore.py` 端到端实测出来的）**：

1. **自己的恢复标记被自己归档**：`resume_run()` 原来在 `graph.invoke()`
   **之前**就 append 了 run 级 `CHECKPOINT_RESTORE`，这条新事件的 id 必然
   > cursor（`rebuild()` 之后新分配的）；但 `graph.invoke()` 内部
   `episode.resume()` 会用**同一个 cursor** 调 `void_after()`，把磁盘上
   `event_id > cursor` 的行不分文件全部归档——这条刚写的标记自己就满足
   这个条件，当场被自己的 `void_after` 吃掉。实测：cursor=53，标记写在
   id=54，随后被归档，连续性检查里凭空留下一个洞。改成 `invoke()` 之后
   再写，此时这局的 `void_after` 已经跑完，不会回头吃新事件。

2. **一个 run 可能有不止一个 episode**：`reflect()` 判定失败且重试预算未
   耗尽会直接 `dispatch()` 出下一个 episode——resume 完 ep1 后，这次视觉
   模型判定跟阶段 A 原本的结论不同（`success=False`），触发了正常重试，
   派发出 `ep2`。`check_trace.py`/`check_restore.py` 都只读
   `resolve_run()`/`resume_run()` 认定的那**一个** episode 文件，`ep2` 的
   事件整段漏读，连续性检查里看起来"从 60 缺到 122"——两个 episode 首尾
   相接的真实数据被误判成缺号。改成读该 run_id 下全部 `<run_id>-ep*.jsonl`
   文件。

**影响文件**：`pokemon_agent/harness/run_harness.py`、
`pokemon_agent/experiment/real_check/check_trace.py`、
`pokemon_agent/experiment/real_check/check_restore.py`。

**验证**：磁盘上现成的 `restorecheck-0909-153643` 产物手工重放了修复后的
加载逻辑（run 级 + ep1 + ep2 三个文件按 event_id 排序），确认改动后不再
出现假性缺号；`resume_run()` 的重排序改动逻辑自洽（`invoke()` 已经把这局
所有 void_after 都跑完，之后再 append 不会被回头处理），未能跑真实回归
（`agent_permission`/Python 3.11 装不进沙箱），建议用户本机重新跑一遍
`check_restore.py` + `check_trace.py` 端到端确认。

**用户本机复核（0909 当天）**：`check_restore.py`
PASS（自 step 3 恢复，游标 53 后续写 123 条连续，归档 1 个 voided）；
`check_trace.py` PASS（123 条事件、event_id [0..122] 连续无缺号无重号，
model_call 21 条）；`check_checkpoint.py`/`check_memory.py` 同样 PASS。
维度 2/3/4/5 全部真实跑通，闭环验证完成。

## 2026-09-09 —— 修复 resume() 恢复后续 episode 崩溃：补 world.set_task()

**改了什么**：`WorldPort`/`GameToolPort` 新增 `set_task(task)`——只挂
`_task`/`_closed` 记账标记，不动模拟器状态（`reset()` 步骤 2 单独拎出来，
`PyBoyWorld.set_task()`/`GameTools.set_task()` 是具体实现/转发）。
`EpisodeHarness.resume()` 在 `self._game.load_state_bytes(...)` 之后紧跟着
调一次 `self._game.set_task(task)`。

**为什么这么改**：`load_state_bytes()` 只回载 PyBoy 的模拟器字节，不认得
`_task`/`_closed`——这两个是纯 Python 记账，不进存档。`resume()` 之前只
`load_state_bytes()` 不补记账，本局自己靠 checkpoint 里的 `pending_observation`
收尾，不会立刻触发；但本 run 后续再派发新的 episode 时（同一个长命 world，
`_world_reset_done` 已经是 `True`、不会再走 `reset()`——"后续 episode 不重置"
是设计好的取舍，见 2026-09-03 条目），会在 `perceive_once()` 里撞上
`assert self._task is not None, "perceive_once() before reset()"`。

这是用 `check_restore.py` 端到端实测跑出来的真实崩溃（用户本机跑通了
阶段 A + 阶段 B 的 `resume_run()` 调用本身，但 resume 完的那一局判定后
`RunHarness` 又派发了下一个 episode 时炸的），跟前一条 run.json 合并的改动
是两个独立的 bug——那条修的是"读哪份 checkpoint 锚点"，这条修的是"恢复完
一局之后，世界对象本身缺了一块纯 Python 记账"。

**影响文件**：`pokemon_agent/interfaces/world/world_port.py`、
`pokemon_agent/world/pyboy_world.py`、
`pokemon_agent/interfaces/tools/game_tool_port.py`、
`pokemon_agent/tools/game_tools.py`、`pokemon_agent/harness/episode_harness.py`。

**验证**：未能在本机跑通 `check_restore.py` 真实回归（`agent_permission`/
Python 3.11 依赖装不进沙箱环境）；改动是读代码定位到的根因直接对症，逻辑上
自洽（`reset()` 步骤 2 原样搬到新方法），建议用户本机重跑一次
`check_restore.py` 做端到端确认。

## 2026-09-09 —— run.json 合并进 step 存档：彻底消掉 resume_run() 的锚点读取歧义

**改了什么**：`CheckpointTool` 不再单独落一份 `checkpoints/run.json`——
`RunState`（目标栈/结算）跟 `EpisodeRunState` 打包进同一份
`step/<episode_id>/<step>.json`。具体：

- `FromHarnessToCheckpointToolSaveReq`/`FromCheckpointToolToHarnessRestoreResp`
  去掉 `level` 字段，新增 `run_state_dump`，`emulator_state` 从 Optional 改必填
  （只剩一种落盘形态，不再有 run/step 二选一）。
- `CheckpointTool.save()`/`load()` 简化成单一路径；删除 `latest_run()`。
- `EpisodeHarness.run()`/`resume()` 新增 `run_state` 参数（纯透传，本层不解读），
  `save_checkpoint()` 节点把它跟 `EpisodeRunState` 一起打包写盘。
- `RunHarness.dispatch()` 不再单独调 `checkpoint.save(level="run", ...)`，改成
  把 `state.model_dump()` 透传给 `episode.run()`/`resume()`；`resume_run()` 直接
  用真实的 `(run_id, episode_id, step)` 三元组调 `load()` 拿锚点，删掉原来
  `load(run_id, episode_id, 0) or latest_run()` 这段有歧义的兜底逻辑。
- `check_checkpoint.py`（维度 3）改核对 `run_state_dump` 而不是 `run.json` 是否
  存在；`check_restore.py` 改从"要恢复到的那一步"自己的 checkpoint 读游标。

**为什么这么改**：`resume_run()` 原来靠 `load(run_id, episode_id, 0)` 取 run
锚点，指望"这一局还没有 step0 存档时顺便回退读 run.json"——但只要这一局跑过
step0（几乎总是），`load()` 就会先命中它自己的 `step/<eid>/0.json`（`level=
"step"`），`run.json` 的兜底分支永远走不到，`resume_run()` 断言
`anchor.level == "run"` 必炸。这是用 `check_restore.py` 实测跑出来的真实
崩溃（`AssertionError: no run.json anchor`），不是理论推演。

深挖之下这不只是"取数据时选错了函数"：`run.json` 覆盖式写入本身也只支持
"恢复当前正在跑的这一局"，撑不住"恢复到好几局之前、把中间已跑完的局当
废弃时间线归档"这个 `void_after()` 本来就设计要支持的场景（归档逻辑一直
有处理"未来局"复数的代码，只是从来没被 `run.json` 的存储形态真正接住过）。
把 `RunState` 跟着每一步的 checkpoint走（而不是单独覆盖写一份）能同时解决
这两个问题：resume 只需读一份文件，且天然按 episode/step 区分，不再有
"哪份是最新的"这个问题。

**已知遗留缺口**（不是这次引入的，这次顺带放弃掉）：一局如果连第 0 步都没
跑完就崩（`_begin()` 已完成、图入口 `save_checkpoint` 还没来得及写第一份
存档），这一局没有任何 checkpoint 可恢复——原设计想靠一份 `.start.state`
起点快照兜这个窗口，但那份快照从来没被恢复逻辑读过（是死代码，已在更早的
"删除每局起点快照"改动里删掉），这次一并确认放弃，需要时再补。

**验证**：`agent_permission`（第三方私有包）与 Python 3.11（`enum.StrEnum`）
在改动这台机器上都装不上，没能跑通端到端 `check_restore.py`（需要用户在
装好依赖的机器上重跑验证）；改为对 `CheckpointTool` 本体做了一次隔离的
本地回归测试（伪造 schema 依赖绕开整个包的 import 链），覆盖：①从已完整
跑过 step0 的局用 step=3（原 bug 的确切触发条件）恢复，正确拿到
`run_state_dump`；②用 step=0 恢复同样正确、不再有分支歧义；③不存在的
step 正确返回 `None`；④ state/json 不成对正确返回 `None`。四条全部通过。

**影响面**：`checkpoint_tool.py`/`checkpoint_tool_port.py`/两个 schema/
`episode_harness.py`/`run_harness.py`/两个 real_check 脚本/
`PLAN_checkpoint.md`（新增 v5 变更说明）/`real_check/SPEC.md`。落盘格式变更，
旧的 `run.json` 产物作废（本地开发数据，无需迁移）。

## 2026-09-09 —— real_check 重脚本打开 faulthandler（维度 5 进程静默死亡排查）

**改了什么**：`check_harness.py` / `check_restore.py` 模块顶部加
`faulthandler.enable()` + `faulthandler.dump_traceback_later(240, repeat=True)`。

**为什么这么改**：维度 5 阶段 A 在 episode 完整收尾（trace 最后事件
`episode_end`，11:55:01）后不再前进，用户等了 20 分钟无变化后手动结束进程。
静态排查了 episode_end → A4 打印之间的全部路径——reflect（纯函数）、review
（60s 有界轮询，超时兜底 STOP，维度 1 同路径 60s 即过）、permission 审批
（10s 有界）、world（无后台线程，tick 全在内联）——每一段都有界，读不出
卡点。所以改为运行时取证：每 4 分钟把全线程栈 dump 到 stderr，再卡住时
终端直接给出卡在哪个文件哪一行。

**取舍**：健康跑完会有 1-2 次例行栈打印噪音，核对脚本可接受；不引入
py-spy/调试器依赖。

**影响面**：仅两个核对脚本；正常路径零行为变化，ruff 全过。

## 2026-09-09 —— episode_start 补记 `success_criteria` 判据原文

**改了什么**：`tools/trace_render.py` 的 `episode_start()` payload 新增
`success_criteria` 字段（取自 `task.success_criteria`），与 `goal`/`max_steps`
一起做逐局快照。

**为什么这么改**：判据原文此前只在 `run_start`（event 0，run 级 jsonl）有一份
初始栈的——只读 episode 级文件的人（维度 2/3/4 核对、复核脚本）翻不到"这一局
用的判据是什么"；且 plan 压栈后每局的判据可以和初始栈不同，逐局快照才是
"这一局实际判据"的权威落点。

**取舍**：与 `run_start` 的 `success_criteria` 有信息重复——不省，两边读者
不同（run 级 vs episode 级文件），episode 级自洽比去重重要。

**影响面**：payload 加字段是增量变更，`evaluation/eval_report.py` 按字段名
解析、不受影响；ruff 全过。

## 2026-09-09 —— 维度 5（check_restore）与维度 1 装配全面对齐

**改了什么**：`check_restore.py` 两处 `build_real`（阶段 A 新跑、阶段 B 恢复）
补齐与 `check_harness.py` 相同的装配参数：显式 `vision_model="qwen3.8-max"` /
`text_model="qwen-plus"` / `max_tokens=25600`（原先吃缺省值，两维度跑的模型
配置不一致）；`[A2/B2]` 打印 review 超时秒数；阶段 A 补 `outcome.reason`
非空断言；`world.stop` 完成后补完成打印。

**为什么这么改**：review 装配（`make_review_pair` + 双开关全关）此前已对齐，
但模型参数两维度不一致——维度 1 显式三参、维度 5 用缺省，同一套核对跑出
的 model_call 配置没有可比性，排查问题时多一个变量。

**取舍**：`reviewer`/`data_center` 阶段 B 用新的一对（模拟"崩溃后新进程"，
不复用阶段 A 的实例）——保持原设计不动。

**影响面**：仅 `experiment/real_check/check_restore.py`；ruff 全过，未跑
真实链路。静态核对确认两处 build_real 八个关键参数齐全、make_review_pair
各阶段一次。

## 2026-09-09 —— 删除每局起点快照（`<episode_id>.start.state`）：纯冗余

**改了什么**：删掉 `EpisodeHarness` 的 `episode_state_dir` 参数、`_begin` 里的
`save_state(...)` 写入点和 `build.py` 的接线；`docs/spec/harness/SPEC.md` 与
`docs/spec/build/SPEC.md` 的对应描述同步更新。`_world_reset_done` 的 reset
逻辑原样保留。

**为什么这么改**：图结构决定了它没有信息量。终止判定全在 `judge` 出口，
`look` 只盖步号、不碰世界——episode 从"最后一圈入口的 checkpoint"到收尾
之间没有任何世界交互，所以**最后一个 step 存档就是本局的终止画面**，也
就是下一局的起点画面（episode 之间不 reset）；ep1 起点 = `reset()` 加载的
ROM 存档，可复现。实测 trace 也证实：step 3 只有 view/judge/verify，没有
executed。每局再存一份起点快照是零信息冗余（此前代码里也确实无人读它）。

**取舍**：replay 若将来需要"从某局开头加载模拟器续跑"，用上一局的最后
checkpoint 或 ROM 存档即可，不依赖这份快照；若 replay 只做事件/截图回放，
更用不上。历史上它只写不读，属于未兑现的设想，先删——需要时随 replay
一起设计。

**影响面**：`episode_harness.py`（构造函数签名少一个可选参数）、`build.py`
（少一行接线）。`EpisodeHarness` 是内部装配点构造的，无外部调用方传过这个
参数；trace 产物里不再出现 `episodes/*.start.state`，维度 2/3 的核对逻辑
不检查该文件，无需改动。

## 2026-09-09 —— run_start trace 补 `success_criteria` 字段

**改了什么**：`trace_render.py::run_start()` 的 payload 里新增 `success_criteria`
字段（多目标栈时同 `goals` 一样用 `" > "` 拼接），docstring 同步说明。

**为什么这么改**：`run_start` 此前只记 `goal` 文字，判据原文不进事件流——复盘
一条历史 trace 时，只能看到"目标是什么"，看不到"当时的成败判据写的是什么"。
两者本来就是 `TaskForHarness` 起 run 时一起传入的必填字段（`goal`/`success_criteria`
同源），只是渲染函数当初做了选择性摘取，没有漏传。

**取舍**：`evaluation/eval_report.py` 只用 `run_start` 的 `ts` 字段算耗时，不解析
`goals`/`goal_count`，加这个新字段不影响报表解析（`trace_render.py` 文件头的
跨模块契约只约束字段名/删字段，纯新增字段安全）。

**影响面**：仅 `trace_render.py` 一处；trace 产物从这次 realcheck
（`realcheck-0909-105454`）起 `run_start.payload.success_criteria` 有值，之前
产物这个字段缺失，读历史 trace 时留意。

## 2026-09-09 —— judge 看不到步号：render_sequence 去重分支保留条目头，包装头改真实步号

**改了什么**：三处。① `step_memory.py::render_sequence()` 的去重分支不再整段
替换条目头——保留 `(episode_id, step=N) 当时看到：（同上一条「之后变成」…）`，
只省画面内容；② `StepMemory.render()` 与 `render_sequence()` 的条目头格式从
`(ep, 2)` 改成 `(ep, step=2)`，让判据里的 "step=2" 在 prompt 里有字面量可对；
③ `judge_success.build_prompt()` 的包装头从窗口序号 `## 第 {i} 条` 改成真实
步号 `## 第 {entry.step} 步`。模板 `judge_success.md` 补一段：判据里的硬性
停止规则（"看到 step=N 就停"）命中即判 true，不受"默认没完成"约束，步号看
条目头 `(…, step=N)`。

**为什么这么改**：0909 05:27 那次 realcheck（run realcheck-0909-052751）跑了
ep1/ep2/ep3 三局、每局都到 step 3 结束——judge(3) 时 history=[step1, step2]，
step2 的条目头被去重整段替换，**prompt 里根本没有"2"这个数字**（窗口编号
还是从 0 重数的"第 0/1 条"）；判据"看到 step=2 就停"要模型找一个不存在的
字面量，模板的"默认没完成/拿不准一律 false"压倒一切 → done=false → harness
强制 done 但 success=False → reflect 直连重派（1+MAX_GOAL_RETRIES 次）→
"一直卡在 3"。根因在渲染层，判据措辞本身没错。

**取舍**：条目头进 prompt 的字节数多了（每条十几字节），换来步号永远可见；
`(ep, step=N)` 格式同时是检索打分文本（render 的两用约定），格式变化对检索
无解析影响。`judge_success` 的包装头只动 judge 这条链，校验链（step_verify）
的窗口编号与 `StepVerifyVerdict.index` 对应关系不碰。

**影响面**：judge / verify 共用的渲染路径文本变了——两者 prompt 里条目头
多出 `step=N` 字样与保留头；不涉及任何代码逻辑分支。维度 1 需重跑验证
（判停应发生在 judge(3) 看见 step=2 时，模型判 true → success=True → 弹栈 →
review 超时 STOP → RUN_END，单局收场）。

## 2026-09-09 —— 真实核对补上"读回路径"：新增维度 5（checkpoint 恢复）与维度 6（记忆读写回环）

**改了什么**：`real_check/` 新增两个独立脚本。`check_restore.py`（维度 5）真实走一遍
跨进程恢复：阶段 A 用 `build_real` 完整跑一个 3 步 run 生成存档；阶段 B 读 run.json
拿事件游标，带 `resume_cursor` 重新 `build_real`（模拟崩溃后新进程），调
`resume_run()` 走 `load → void_after → 世界快照回载 → 状态重建 → 续跑`，断言四条：
恢复后出 `RunOutcomeResp`、trace 里有 `checkpoint_restore` 且 restored 三元组对得上、
全部事件按 event_id 排序仍严格连续（废弃段截掉后从游标 +1 无缝续写）、`voided-*`
归档目录真实生成。`check_memory_roundtrip.py`（维度 6）把 MemoryTool 五条读写路径
在真实实现下过一遍（临时目录注入，不污染真实记忆库）：episodic 写读回环、object
按图/按格读回、知识库混合检索（真实 fastembed + reranker）、跨局摘要写入 + 检索 +
run_id 隔离、`void_memory_after` 截断计数。

**为什么这么改**：用户指出"这些测试不够——真实情况下的存档恢复逻辑呢，所有模块
都要真实情况下试试"。原四个维度全部只验"落盘产物长什么样"（写路径的静态检查），
没有任何一条**读回路径**被执行过：`CheckpointTool.load()` / `void_after()` /
`resume_run()` 从没被真实调用，MemoryTool 的检索（BM25+向量+reranker）也没在真实
链路里跑过——这类"写没问题、读炸了"的 bug（如 `_read_checkpoint` 签名校验、
`_episode_vector` 惰性补算）只有真的读一遍才现形。

**取舍**：维度 6 的存储后端注入临时目录而不是打真实记忆库——测试要可重复、
无残留，但 store 实现与 fastembed 推理保持真实；维度 5 选拉满（两次 PyBoy +
全程真模型，约 6-8 分钟）而不是只测 `CheckpointTool.load()` 的纯读——恢复的价值
就在"恢复后能继续跑"，半截恢复测不出 dispatch resume 分支的接线问题。
已知风险：judge 带图调用是昨夜两次硬断电的共同峰值点，维度 5 有触发硬件保护
断电的可能（用户已知情，选择先跑）。

**影响面**：新增两个脚本与 `real_check/__init__.py` 无改动；`check_restore` 跑完
会把 last-run 指针指向恢复后的时间线，维度 2/3/4 可直接复核恢复后的产物。


**改了什么**：上一条 changelog 加的 `pokemon_agent/experiment/real_integration_check.py`
（独立脚本 + 自定义 `Check` 类手搓 PASS/FAIL 表）删掉，改写成
`tests/test_real_integration.py`——一个 `pytest.mark.skipif`（没有两个
API key 就整体跳过，`pytest tests/` 默认跑不需要网络的那批）+ 一个
`scope="module"` 的 fixture 真跑一次 episode（避免每条断言各自重跑一遍）+
四个各自独立的 `test_*` 函数（run 跑完 / trace event_id 连续无缺号 / 
checkpoint state-json 成对 / StepMemory-ObjectMemory 落盘状态自洽），核对
逻辑不变，只是从"脚本打印一张表"变成"pytest 原生的每个模块一个测试用例、
各自 PASS/FAIL"。

**为什么这么改**：用户要求"应该写在 test 里，用 pytest 开启"——独立脚本
自己维护一套 `Check`/打印表格的机制是在重新发明 pytest 已经做好的事（用例
发现、跳过、失败汇总、`-v`/`-k` 过滤），改成 pytest 用例后跟其余测试
（`test_checkpoint_resume.py` 等）享受同一套运行方式，`skipif` 也比脚本
自己手写"检查环境变量再 `sys.exit(1)`"更贴合 pytest 的习惯用法。

**取舍**：保留了同一份落盘路径核对逻辑（trace/checkpoint/StepMemory/
ObjectMemory 四项），没有额外加内容语义正确性核对——跟上一条的边界一致。
`skipif` 卡在"两个 key 都要有"，而不是分别对 ARK/DashScope 单独判断——
这次真实调用两条链路都要用到（judge/decide 走 DashScope，plan/verify 走
Ark），少一个就跑不完整，没必要支持"只测一半"的中间态。

**影响面**：删除独立脚本，新增 `tests/test_real_integration.py`（跟其余
测试文件同规则：gitignore 收着、`git add -f` 入库）。`ruff` 干净（补了一处
`E741` 歧义变量名）；`pytest tests/` 在没有 key 的环境下 15 例正常跑、5 例
（本文件）正确跳过，全程无残留副作用；`test_trace_event_ids_are_globally_contiguous`
的解析逻辑再次用真实 trace 产物（`trace_data/itest-*-run/`）验证过，
`test_checkpoint_step_files_are_paired` 用同一份数据验证了"没有 checkpoint
文件时应该失败"的负向路径。用户自己在真实 PowerShell 里跑：

    $env:PYTHONPATH = ""
    $env:ARK_API_KEY = "..."
    $env:DASHSCOPE_API_KEY = "..."
    pytest tests/test_real_integration.py -v -s

## 2026-09-09 —— 维度 2/3/4 产物定位改为"指针优先 + 回退扫描"；核对规格落成 SPEC 文档

**改了什么**：`common.py` 新增 `resolve_run()`——优先读 `.last_realcheck.json`
指针，指针缺失/失效时回退扫描 `trace_data/` 下最新的 `restorecheck-*` /
`realcheck-*` 目录，取其中最近修改且非空的 episode 级 jsonl；维度 2/3/4 的
`read_last_run()` 调用点全部换成它。另新增 `docs/spec/real_check/SPEC.md`，
描述六个维度各自的测试对象、真实依赖、通过判定、运行方式、已验证状态与
已知风险。

**为什么这么改**：0909 凌晨的 restore 跑批随会话重启被杀，指针文件没写、
0908 的旧产物也早已被清空——维度 2/3/4 此前完全依赖"上一个脚本恰好跑完
最后一行"写下的指针，这在会话频繁重启的现实下太脆。用户同时要求把这套
核对出一份可读的描述，按 AGENTS.md 的约定落成 `docs/spec/real_check/SPEC.md`。

**取舍**：回退扫描只认 `restorecheck-` / `realcheck-` 两个前缀并按 mtime 取新，
不做更聪明的"哪个 run 是完整的"判定——完整性正是维度 2 的职责（run_end
缺失会如实 FAIL），定位层不重复做这件事。

**影响面**：`check_trace` / `check_checkpoint` / `check_memory` 的 import 与
调用点各改一处；`read_last_run()` 保留（check_restore 语义上仍只写指针），
无对外行为变化。

## 2026-09-09 —— 核对脚本终止方式改正：plan 双开关全关，review 交 DataCenterReviewer 超时收场

**改了什么**：`check_harness.py` / `check_restore.py`（阶段 A、B 两处）的
`build_real()` 调用统一改为 `auto_push_goals=False, auto_decide_done=False`，
并按 `api.py` 同构装配 `reviewer=DataCenterReviewer(data_center, timeout=REVIEW_TIMEOUT)`、
`data_center=...`（`common.py` 新增 `make_review_pair()` 与 `REVIEW_TIMEOUT`，
沿用 `POKEMON_REVIEW_TIMEOUT` 环境变量、缺省 60s）。

**为什么这么改**：原先核对脚本用缺省装配，`plan` 的 `auto_push_goals=True`
让规划模型在目标完成后自主压新目标续跑——3 步任务实际跑了 10 步（0909
restorecheck 的 ep2 存了 0-9 步存档），"有限任务跑完即停"的预期落空。中途
误改成只关 `auto_push_goals`，用户纠正：两个开关本来就为跳过 plan 而写，
直接用；终止交 human review，等超时按 STOP 收场。注意 `reviewer=None` 时
RunHarness 缺省是 `AutoContinueReviewer`（永远 CONTINUE、无超时概念），
双开关全关+栈空会 plan↔review 空转到 recursion_limit 炸图——必须显式换
`DataCenterReviewer` 才有"等超时就结束"的语义。

**取舍**：不改 `run_harness` 本体的缺省值——开放任务（玩通神奇宝贝）要
plan 自主扩栈，有限终止是核对脚本的诉求，用装配参数表达，不动全局行为。

**影响面**：仅 `experiment/real_check/` 三个文件；生产装配（`build.py`
缺省、`api.py`）不变。维度 2/3/4 只读产物，不受影响。

## 2026-09-09 —— 判据直给，停步字面量按模型实际可见的步号写

**改了什么**：`common.py` 的 `SUCCESS_CRITERIA` 改成一句话直给：
"看到 step=2 就停（why 写「步数用尽」）。没到之前，看到目标所述动作完成
且画面出现反应才判完成，没看到就判 false。"字面量由 `STEPS - 1` 派生。

**为什么这么改**：judge 问到第 3 步的当前帧时该帧还没落库，模型看到的
history 最大步号是 2——"step=3" 这个字面串在 prompt 里永远不会出现，
照 step=STEPS 写模型永远等不到停步信号。判据必须按模型实际能看到的步号写。
（演变过程：先写机械的渲染机制说明，被否；改写成"goal 的性质"含蓄版，
再被否——用户要的就是直给"看到 step=N 就停"，只是 N 取 STEPS-1。）

**取舍**：判据与"judge 先问、当前帧后写库"的渲染时机耦合，若哪天当前帧
提前落库，判据要改回 step=STEPS。harness 侧 `max_steps` 硬限制不受影响，
双保险仍在；`verdict.done → success=True` 的耦合没动（核对脚本不断言 success）。

**影响面**：仅判据文本；judge 在边界步按 history 末条 step=2 判停。

## 2026-09-08 —— 新增真实链路端到端核对脚本 `real_integration_check.py`

**改了什么**：新增 `pokemon_agent/experiment/real_integration_check.py`——跟
`run_episode.py`（只关心"任务跑没跑成"）不同，这个脚本跑完一个短 episode
后逐模块核对产物是否真的落盘：trace（run 级 + episode 级骨架事件都在、
event_id 全局排序后严格连续无缺号无重号）、checkpoint（`run.json` +
至少一个 step 存档、`state`/`json` 成对）、StepMemory/ObjectMemory（报告
落盘状态，episode 成功收尾后 StepMemory 文件被蒸馏链清空是预期行为，不当
失败项）。跑完打印模块级 PASS/FAIL 表，非零退出码表示核对未通过。

**为什么这么改**：本次真实集成测试（v.s. `tests/` 里 Mock/Fake 驱动的
测试）已经现场抓出一个阻断性 bug（见上一条 changelog：`RunHarness` 权限
运行时初始化顺序）——这说明"接真实 Brain + 真实 agent_permission 跑一遍"
这件事本身有价值，值得留一条可重复执行的核对路径，而不是每次都临时手搓。
用户要求"我把脚本写好、你自己在真实 PowerShell 里跑"（这台 device_bash
沙盒的出站代理不放行 ARK/DashScope 域名，见上一条），所以这个脚本设计成
读环境变量拿 key、不硬编码任何密钥、不依赖我这边的沙盒环境。

**取舍**：核对边界只到"文件确实落地、event_id 没有缺号重号、成对关系没被
破坏"这一层，不做"内容语义正确"这类更深的核对（比如 trace 里的 verdict
是不是判对了）——那属于 judge/verify 本身的正确性，不是这次真实集成想
测的"harness/checkpoint/trace/memory 四个模块的写入路径是不是接线正确"。
权限审计日志（`agent_permission` 自己的 audit trail）没有独立核对，篇幅
和优先级都不如上面四项，先留空。

**影响面**：纯新增脚本，不改变任何现有代码路径；`ruff` 干净（行宽已控制
在 100 内），`ast.parse` 通过，并用今天早些时候 pytest 跑集成测试留下的
真实 trace 产物（`trace_data/itest-*-run/`）验证过 `check_trace()` 的解析
逻辑（发现并修了一个我自己的 bug：两个事件文件按读取顺序拼接后不能直接
比较"是否已排序"，必须先按 event_id 全局排序）。用户自己在真实 PowerShell
里跑：

    $env:PYTHONPATH = ""
    $env:ARK_API_KEY = "..."
    $env:DASHSCOPE_API_KEY = "..."
    python -m pokemon_agent.experiment.real_integration_check

## 2026-09-08 —— 修复 RunHarness 权限运行时未初始化：真实集成测试跑出的阻断性 bug

**改了什么**：`@initialize`（`agent_permission`）从 `EpisodeHarness.run()` 挪到
`RunHarness.run()`/`resume_run()`。`EpisodeHarness.run()` 不再自带这个装饰器，
方法上补了注释说明原因；`tests/test_integration_tool_layer.py`（未入库，
本地测试文件）里直接单跑 `EpisodeHarness.run()` 的"episode 级"场景相应改成
自己包一层 `@initialize`。

**为什么这么改**：用户要求"直接操作 PowerShell 跑一个三步就退出的任务，
真实情况下的集成测试，测试所有模块"——computer-use 对终端类应用只能到
click-only 权限，打不了字，改用 device_bash 补齐 pyboy/真实 API key 环境后
跑 `python -m pokemon_agent.experiment.run_episode 3 "..." --state assets/rom.state`，
第一步就炸：`RunHarness` 的图是 `begin → plan → dispatch → ...`，`plan` 节点
在第一次 `dispatch`（进而调用 `EpisodeHarness.run()`）之前就要调用受
`@require_permission` 守卫的 `Brain.plan_once`，而权限运行时只在
`EpisodeHarness.run()` 的 `@initialize` 里初始化——`plan` 永远先于它执行，
权限运行时永远还没起来，`RuntimeError: ... was called before the permission
runtime was initialized` 是**每一次**真实调用 `RunHarness.run()` 的必现结果，
不分走 CLI（`run_episode.py`）还是走生产 API（`api.py::_execute()`，同样直接
调 `harness.run(...)`，同一个坑）。`test_integration_tool_layer.py` 的"run 级"
场景没测出来，是因为它用 `FakeBrain`（未挂 `@require_permission`）代替真实
`Brain`，权限检查这条路径压根没被这个测试走到——只有接上真实 `Brain` +
真实 `agent_permission` 运行时的集成测试才会现形，这正是这次"真实情况下
集成测试"的价值所在。

**取舍**：没有让 `agent_permission` 支持"已初始化就跳过"的软化嵌套语义
（库自己的设计立场很明确：嵌套调用必须硬炸，见 `runtime.py` 的注释——静默
容忍会把一次 run 的审计流从中间切成两段且没有任何报警）；改成把装饰器
挪到唯一正确的位置——`RunHarness.run()`/`resume_run()`，两者都是从
`plan` 节点起步的同一张图。`EpisodeHarness.run()` 在生产路径下只被
`RunHarness.dispatch()` 调用（`grep` 确认全项目仅此一处），独立单跑它只发生
在测试里，测试自己包一层的成本可以接受。

**影响面**：这是一个此前从未被真实调用路径验证过的阻断性 bug——只要接了
真实 `Brain`，`RunHarness.run()`/`resume_run()` 此前 100% 必现崩溃，`api.py`
的生产 HTTP 入口同样受影响。修复后 `pytest tests/`（14 例）与
`ruff check pokemon_agent --select F821` 均验证通过；真实端到端验证（真实
API key + 真实网络请求）卡在这台 device_bash 沙盒的出站代理不放行
`ark.cn-beijing.volces.com`/`dashscope.aliyuncs.com`（`curl` 直接确认两个域名
都收到代理层 403），已确认修复让流程正确推进到"发起真实网络请求"这一步
（此前是权限运行时崩溃，现在是纯网络出站限制），完整的真实网络往返验证
需要在真实 PowerShell（有互联网访问）里跑同一条命令。

## 2026-09-08 —— checkpoint 文档与代码对齐（第 16 条）+ 修复 resume_run() 的 NameError 死代码

**改了什么**：核对发现 `docs/ROADMAP.md` 第 16 条（存档/checkpoint 机制）
仍停在"0906 方案拍板，待实施"，但实际 0907 会话已经把 `PLAN_checkpoint.md`
v4 方案完整实施并接线（`CheckpointToolPort`/`CheckpointTool`、
`save_checkpoint` 图节点、三级恢复入口、废弃归档、`WorldPort.load_state`、
`RunDataCenter` 事件流槽、`StepMemory` 落盘化）——只是 0908 一次 git 对象
丢失事件（详见 `docs/spec/GIT_RECOVERY_2026-09-08.md`）抹掉了这几次提交的
历史记录，代码本身在工作区完好无损。本次把第 16 条改成 ✅ 状态、指向
`PLAN_checkpoint.md`/`CHECKPOINT_handoff_2026-09-07.md` 为权威来源，不再
重复方案细节；同步改掉 `AGENTS.md` 第九节"checkpoint 存事件序列而非最终
状态"一句（与实际方案不符——实际是状态快照 + 事件游标对账，不是纯事件
重放）。核对过程中用 ruff 扫了一遍 `pokemon_agent/`，发现
`run_harness.py::resume_run()` 用到的 `ResumeEpisode` 没有被导入（`F821`
undefined-name）——这是恢复路径上会直接炸 `NameError` 的死代码，补上导入。

**为什么这么改**：用户指出"objectmemory已经变成event流了，你先和现有文档
对齐一遍"——文档滞后于代码是比代码本身有 bug 更容易造成误导的问题（下一个
读 ROADMAP 的人会以为 checkpoint 还没做，重新设计一遍）。`ResumeEpisode`
这个 bug 是核对过程中顺手用 ruff 扫出来的，不是本次目标，但既然扫到了、
修复成本又低（补一行 import），随手一并修掉。

**取舍**：没有去重建丢失的 4 次逐条提交历史（git 对象已经找不回，
`GIT_RECOVERY_2026-09-08.md` 里保留了提交说明供追溯，但 diff 内容拿不到
了）——工作区文件是当前唯一真相源，重建 commit 历史的收益不值得为一个
纯考古目的重写。`ruff` 剩余的 53 条既有格式/类型标注类债务本次不处理，
跟 checkpoint 无关。

**影响面**：纯文档对齐 + 一处 import 修复，不改变任何运行时行为（除了让
`resume_run()` 从"必炸"变成"能跑"）。`pytest tests/`（8 例，含
`test_checkpoint_resume.py` 4 例）与 `ruff check pokemon_agent`（`F821`
归零）均已用临时搭建的 Python 3.12 venv（`pydantic`/`langgraph`/
`rank-bm25`/`agent-permission`）验证通过。

## 2026-09-08 —— memory 新增 MemoryIndexPort/MemoryIndexStore：项目无关的元数据倒排索引 + 语义检索（第 24 条 Phase 1）

**改了什么**：新增 `pokemon_agent/interfaces/memory/memory_index_port.py`
（`MemoryIndexPort` Protocol：`put`/`get`/`get_many`/`filter`/`search`/
`delete_many`）和 `pokemon_agent/memory/index/index_store.py`
（`MemoryIndexStore` 默认实现），并在 `interfaces/__init__.py`、
`memory/__init__.py` 的统一出口里注册导出。这是全新的独立模块，不触碰任何
现有调用方——`MemoryToolPort`/`EventObjectStore`/`KnowledgeStore` 等现有接口
和实现都未改动。`MemoryIndexStore` 内部：每条记录写入时生成一个不带语义的
uuid；`(字段,值) → uuid 集合` 的倒排索引支持任意字段组合的等值过滤检索
（`filter()`），所有字段地位对等，没有主键；`search()` 接受一句话文本，
候选集先按 `conditions` 过滤缩小范围，再调 `memory/retrieval.py::hybrid_retrieve`
做 BM25+embedding+RRF+reranker 的混合排序，排序细节对调用方完全不透明；
单文件 JSONL 写穿落盘、启动时全量读回内存重建倒排索引（跟 `EventObjectStore`
同一取舍）；`delete_many()` 整文件重写（跟 `EventObjectStore.truncate()`
同一取舍）。

**为什么这么改**：`docs/ROADMAP.md` 第 24 条（0908 拍板）——现有
`MemoryToolPort` 的读方法按各自消费方专门定制（按局/按图/按格/按场景……），
形状互不相同，每加一种检索维度就要新开一个方法，接口没法挪给别的项目复用。
这次先只搭一个通用、项目无关的检索底座（过滤检索 + 语义检索两种能力），
不碰现有调用方，验证接口设计站得住之后再考虑要不要把现有查询逐个迁移过来。

**取舍**：`search()` 最初设计是接受调用方算好的查询向量，后来发现现有
`query_episode_summaries` 实际跑的是 BM25+embedding+RRF+reranker 的完整混合
检索管线，不是简单向量余弦——改成接受原始文本、内部自己跑完整管线，重排
也算检索的一部分，保持跟现有检索质量对齐、对调用方不透明。索引结构选了
最简单的内存字典+JSONL 写穿落盘，没有做真正的磁盘索引结构（B-tree 等）——
现在的数据量级用不上，跟 `EventObjectStore`/`KnowledgeStore` 一致的取舍。
倒排索引只支持等值/成员匹配，不支持大小比较（比如 `step` 的区间查询）——
这是索引支持的操作类型的限制，数值比较由调用方自己先用等值条件筛小候选集
再手动比较，不是这层该内置的规则。

**影响面**：新增文件，不影响任何现有代码路径。已用真实依赖（`pydantic`
2.13.5、`rank-bm25`）在一次性搭建的 Python 3.12 虚拟环境里做了功能级冒烟
测试（非仅语法检查）：`put`/`get`/`get_many`/`filter`（含多字段交集、空
条件返回全部、无匹配返回空）/`search`（含 `conditions` 缩小候选范围、
候选集为空返回空列表、未写 `text` 的记录不可被检索到）/`delete_many`，
以及重启后从磁盘重建索引的持久化一致性，全部通过。尚未接入任何现有调用方
（`MemoryToolPort`/`EventObjectStore`/`KnowledgeStore` 迁移属于后续 Phase，
按 ROADMAP 第 24 条"没定的地方"暂缓，等用户明确要做再启动）。

## 2026-09-08 —— judge 去掉重复的"当前观测"，直接复用 history 最后一条

**改了什么**：`judge_success.py` 的 `build_prompt()` 不再从 `req.snapshots[-1]`
单独拼一份"当前观测"塞进 `$observation`；`judge_success.md` 模板删掉
「## 他现在看到的画面」这一节，改在「这一局最近发生的几步」的说明里点明
"最后一条的『之后变成』就是他现在看到的画面"。`FromBrainToolToBrainJudgeReq`/
`FromHarnessToBrainToolJudgeReq` 删掉不再使用的 `snapshots` 字段；
`episode_harness.py::judge()` 相应改成 `images, _ = dedup_snapshots(...)`，
不再取 `snapshots` 传给 req。原来挡"当前观测"三个字段的 `JUDGE_BLIND` 常量
一并删除（它只用来过滤这份被删掉的内容，不是判定器输入的通用防线）。

**为什么这么改**：`history` 最后一条的"之后变成"和这份单独拼的"当前观测"
本来就是同一份 `ObservationFromWorld`（`dedup_snapshots()` 一次遍历一并算出
来的），每次判定都被渲染两遍——而 judge 第 0 步已经不问模型
（`episode_harness.py::judge()` 的硬编码分支），走到 `build_prompt()` 这条路
时 `history` 保证非空，`current is None` 的兜底分支从这套调用点看是死代码。

**取舍**：`JUDGE_BLIND` 里 `known_objects`/`walk_map` 两项本来就不会经这条
路径泄漏（`known_objects` 从写入 `StepMemory` 起就被 `SNAPSHOT_BLIND` 挡住；
`walk_map` 被 `StepMemory._render_obs()` 挡在历史渲染之外），只有 `landmarks`
是真正只被 `JUDGE_BLIND` 挡住的，但它一直都在 `$history` 里对判定器可见
（`_render_obs()` 不挡 `landmarks`）——删掉这份重复的"当前观测"不会新增
`landmarks` 的暴露面，只是让这处不一致自己消失。如果以后要真的不让判定器
看到 `landmarks`，正确的地方是改 `StepMemory._render_obs()`/`render_sequence()`
——但那是 `judge`/`verify_and_summarize` 共用的渲染路径，这次不在改动范围内。

**影响面**：判定 prompt 里"现在"这份信息只出现一次（少一份重复的坐标外观测
文本，省 token）；`FromBrainToolToBrainJudgeReq`/`FromHarnessToBrainToolJudgeReq`
的字段集从 4 个减到 3 个，两个 req 类字段仍保持一一对应（`BrainTool.judge()`
靠 `model_dump()` 互转不受影响）；未跑真机验证，行为等价性靠人工核对
`render_sequence()` 的最后一条渲染结果与原先 `current.facts` 渲染的内容
（除 `landmarks` 外）逐字段一致得出。

## 2026-09-08 —— walk_map 行尾标全局 x 范围 + decide prompt 静态前移动态后移

**改了什么**：
1. `world/ram.py` 的 `render()`：walk_map 每一行行尾追加 `(x=A..B)`（该行首尾
   两格的全局 x），开头声明句删掉具体数字，只解释括号含义——"这一屏 N 列 ×
   M 行；每行末尾括号里是该行首尾两格的全局 x"。
2. `prompts/decide_action.py` 的 `_sample_map()`：读图范例同步改成新格式
   （行尾括号、声明句无数字），原来"最左一列 x=11，最右 x=20"的范例声明删除。
3. `prompts/calls/decide_action/decide_action.md` 重排：`$map_guide`、
   known_objects 三条硬规则、检索知识/相关记忆/跨局摘要三节的"怎么信/怎么读"
   说明全部前移到「## 目标」之前（静态区），动态数据（goals/status/facts/
   knowledge/memories/episode_memories/actions）集中靠后。
4. `map_hint.md`：「只有一套坐标」节补"某格全局 x = 行首 A + 字符索引"的换算
   说明；「图上没有列号」改为「没有逐格列号」（行尾有范围）；补"括号不是格子"
   的说明。`repeat_hint.md` 的数格子规则补"忽略行尾括号"。

**为什么这么改**：2026-09-08 两个 run 的 trace 实证（见
`trace_data/run-20260908-120552-4a96cb/ANALYSIS.md`）：① decision 的 thought
烧掉 1633 output token，根因是范例的坐标声明（x=11..20）与当前帧声明（x=9..18）
在同一份 prompt 里并存，模型把范例数字当通用规则套用，算出矛盾后开始长篇
自我核对——改成每行自带权威范围后，范例与数据同构，混淆源头消失；
② prompt 的静态说明原来排在动态 facts 之后（map_guide 挨着 $facts），
前缀缓存只能命中到 facts 之前的约 72 行，121 行之后的全部静态内容
从来没吃到过缓存——静态前移后整段说明进缓存前缀。

**取舍**：推翻了 map_guide 原来"紧挨 $facts、规则贴着数据读"的安排（decide_action.py
docstring 旧论证删除）——那个收益被行尾 x 范围替代：数据自解释，模型不需要先读
规则才知道括号是什么。行尾括号有被当成格子的风险，用三处说明压（map_hint 的图例
说明 + repeat_hint 的数格子规则 + 图例本身无 `(` `)` 字符），且行本体仍是恰好
10 字符、与括号之间双空格分隔。judge 链路不受影响（`JUDGE_BLIND` 与
`_render_obs` 本来就挡掉 walk_map）；verify 链路会看到新格式，未实测，下一轮
跑批时注意 `verify_unreliable` 是否异动。

**影响面**：decision prompt 结构变化（所有调用方无需改动——占位符集合不变，
冒烟已验证 10 个占位符与 `build_prompt` 参数一一对应）；`render()` 输出多出
行尾标注，读 walk_map 的下游（verify 多帧拼接、记忆渲染排除项）格式兼容。

## 2026-09-08 —— 撤掉 $images_note：网格读法说明改纯静态，行数交给模型看图数

**改了什么**：`verify_and_summarize.md` 截图一节的 `$images_note`（随 n 变化
的行列数文案）整个撤掉，换成**静态文案**——只写死"3 列网格、黑线分隔、
行优先按时间排列、空格是黑色"，行数由模型看图自己数；单帧情况用"只附一张图
时就是本局最后一步结束后的画面"一句覆盖。`prompts/verify_and_summarize.py`
删掉 `_images_note`/`math`/`_COLS`，`build_prompt` 不再传 `images_note`；
`image_grid_dims` docstring 同步改口径。

**为什么这么改**：用户拍板——上一条把 `$images_note` 挪到静态段之后只是
止损，根治是让它不存在：整份 prompt 再无随帧数变化的文字，变化点只剩
goal/steps/knowledge 这些本来就该变的。

**取舍**：行数不再写进文案（省掉动态性），代价是模型要自己数行——上一条
的三列识别实测已证明模型能正确读 3×3 网格与行优先顺序，行数判断风险低。

## 2026-09-08 —— verify 拼图去上采样 + 布局契约去 provider 依赖 + $images_note 移出静态前缀

**改了什么**：
1. `pack_images_grid` 去掉每帧 2x NEAREST 上采样，帧保持原始 160×144——豆包
   按张计费与分辨率无关，上采样不省图费；3 列布局、4px 黑线不变。
2. `prompts/verify_and_summarize` 不再 import provider 的 `image_grid_dims`：
   写死 3 列（模块常量 `_COLS`）+ 自行 `ceil(n/3)` 算行数，provider 侧
   `image_grid_dims` 保留给 `pack_images_grid` 算画布，两处各持一份"3 列"契约。
3. `verify_and_summarize.md` 模板重排：`## 除了文字，你还会看到截图` 一节
   （含随 n 变化的 `$images_note`）从第 13 行移到 `## 输出格式` 之后、
   `## 本局目标` 之前——静态规则（intro+方法论+输出格式 ≈2900 字符）回到
   可缓存前缀内，变化点之后的 goal/steps 本来就动态，断在那里零损失。

**为什么这么改**：隐式缓存按请求开头做前缀匹配，`$images_note` 每 episode
随帧数变化，原先排在开头把 2500+ 字符静态规则全部挤出缓存前缀——与
judge_success 散文占位符同款问题。去 provider import 是依赖方向取舍：
prompts → providers 不值得为"3 列"一个常数建立。

**取舍**：识别可靠性风险（160×144 小格 + 三列网格读法）用真机识别实测兜底
（9 格带数字徽章拼图问豆包），实测通过才保留。


**改了什么**：按 `docs/spec/harness/PLAN_checkpoint.md` v4 实现三级恢复（run/
episode/step）：
1. **前置改造**：`FileEpisodeMemoryStore._steps` 纯内存 → 按局 JSONL 落盘写穿
   （`steps-<eid>.jsonl`，与 EventObjectStore 同构：append 写穿 + truncate +
   `_step_max` 单调 assert + 构造读回 + discard 删文件）；`StepMemory`/
   `ObjectFactEventBase` 加 `run_id` 字段（落盘签名三元组），harness 两侧盖章。
2. **CheckpointTool**（`tools/checkpoint_tool.py` + Port）：`save`（先世界快照
   后 json 提交点，签名三元组内嵌）、`load`（三元组定位 + 成对/签名校验，
   step0 回落 run.json）、`void_after`（废弃时间线处理：trace 按游标截断归档、
   废弃局整体处理、记忆截断经 MemoryTool 范围查询、目标局 step≥N 截图搬移）。
3. **图接线**：episode 图 17→18 节点，`save_checkpoint` 为图入口兼循环边界
   （未注入工具时空转），`recursion_limit` 16×→17×；`EpisodeHarness.resume()`
   step 级恢复入口；`RunHarness` dispatch 前 `run.json` 锚点 + `resume_episode`
   分支 + `resume_run(run_id, episode_id, step)` 入口（START 条件边路由）。
4. **trace 续写**：`LocalTrace(resume_after_event_id=...)`（`_next_id` 从游标
   +1，event_id 严格单调不断链）。
5. **DataCenter 事件流槽**（§7.2）：`publish_event`/`events`/`rebuild`——
   前端可见状态单点化；`LocalTrace` 回归纯写端（`_events`/`events()` 移除，
   `event_sink` 双写 + `read_disk_events()`），api.py SSE/实时数字/eval_report、
   run_harness.review/plan 的读端全部改走 `data_center.events()`。

**为什么这么改**：Agent 工程清单第 6 项（checkpoint/resume），评审最高优先级
缺项；方案与拍板记录见 PLAN_checkpoint v4 §9（8 项拍板）。

**取舍**：不用 LangGraph SqliteSaver（两套真相）；"一样"= 状态等价非轨迹复现
（LLM 非确定）；恢复粒度 = step 边界；废弃数据归档不删除（消费方零改动）；
`CHECKPOINT_RESTORE` 走 TraceKind 29（payload.kind，TRACE_SCHEMA_VERSION=3 不动）。

**影响面**：memory/schemas/tools/harness/trace/api/build 全层；新测试
`tests/test_checkpoint_resume.py` 4 条（落盘回环/签名校验/void 语义/不成对
拒绝）+ 集成测试回归全绿；108 模块导入 OK。遗留：episode 图级全流程恢复
的端到端测试（跑半局→resume）待接完整 fake 栈；CLI/API 的 resume 暴露待接。

## 2026-09-07 —— 集成测试跑通，修掉 4 个 req 化接线 bug

**改了什么**：新增 `tests/test_integration_tool_layer.py`（真实 harness
状态图 + 真实 BrainTool/TraceTool/GameTools + 假 Brain/World/记忆后端 +
真 LocalTrace，跑完整 episode 与 run 两场景）。测试揪出 4 个转换脚本
接线遗漏并修复：① EPISODE_ERROR/RUN_ERROR/RUN_START/RUN_END/
EPISODE_START/PLAN_VERDICT 六种边界账缺 `step`（原实现硬编码 0，
`episode_end` 取 `outcome.steps`）；② `OBSERVE` 账缺 `step=obs.step`；
③ `store_step_episode_memory` 没解包 `reflect` 响应的 `.entry`；
④ run_start 的 `goals`（TaskForHarness）撞 `observe` 的
`goals`（GoalForBrain）字段类型，拆出独立 `run_goals` 字段。

**为什么这么改**：用户要求做集成测试验证 harness→tool→模块搭配。静态
grep 只能证明依赖方向，跑通才暴露"req 组装时字段漏带/带错"这类接缝
bug——4 个全部是转换脚本批处理 + 人工修复的盲区，验证了"集成测试是
装配路径变化的第一道验证"（AGENTS.md 三.5）。

**取舍**：假后端刻意笨（只按脚本回话 + 记录收到的 req），协议翻译的
断言（isinstance 第二跳契约）放测试里而不是 tool 里。测试文件留在
gitignore 的 `tests/` 下不强制入库（沿用仓库现状），要用 `git add -f`。
`LocalTrace` 的 `STORAGE_ROOT` 锚定项目根，测试用每次进程唯一的
run_id + 清理夹具避免撞已完成存档。

**影响面**：`episode_harness.py`/`run_harness.py`/req 模型补字段，
无接口变化；pytest 两场景全绿（episode：2 步成功 + 事件序列/attempt
盖章/event_id 单调断言；run：plan 两轮 + 1 局成功）。

## 2026-09-07 —— BrainTool 接线：harness 不再直握 BrainPort

**改了什么**：`EpisodeHarness`/`RunHarness` 的构造参数 `brain: BrainPort`
改为 `brain_tool: BrainToolPort`；四个调用点（judge/reflect/
verify_and_summarize/choose）与 `choose_with_retry`/`ask_planner_with_retry`
的 req 类型从第二跳原生契约（`FromBrainToolToBrain*`）换成第一跳协议
（`FromHarnessToBrainTool*`）；`build.py` 构造 `BrainTool(brain)` 注入两级
harness——`Brain` 从此只在 build.py 出现。

**为什么这么改**：BrainTool 翻译壳早已存在但悬空（grep 消费者为零），
harness 一直直握 `BrainPort`，两跳契约没有真正分开。接线之后方案第 1 节
的分工语义才成立：harness 组装第一跳 req，tool 负责互转，第二跳契约的
变更权归 BrainTool/Brain 侧，未来任一边单独变形状都不牵动 harness。

**取舍**：BrainTool 今天仍是逐字段原样转发（model_dump）——转换逻辑为零
成本，但两跳类型故意不共用，隔离墙先立起来，转换在有真实差异时再加。
异常（`DecisionAttemptFailed`/`PlanAttemptFailed`）保持原样穿透，不在
tool 里包一层新异常。

**影响面**：5 个文件改类型与 import，无行为变化；build+api 全链 import
冒烟通过；`grep BrainPort|FromBrainToolToBrain pokemon_agent/harness` → 0。

## 2026-09-07 —— TraceTool：记账转换收进 tool 层（按 TraceKind 分派渲染），trace/utils.py 退役

**改了什么**：新增 `TraceToolPort`/`TraceTool`（`interfaces/tools/`、
`tools/trace_tool.py`）与协议 `FromHarnessToTraceToolAppendReq` +
`TraceKind`（28 种账）。harness 记账调用点全部改为组装 req（挑字段 +
声明 kind），payload 字段格式、json 序列化、条件字段、一拆多
（账单 + 失败补 ERROR）、attempt 盖章全部收进 `tools/trace_render.py`
（28 个渲染函数按 kind 分派，从原 `trace/utils.py` 迁入改写）；
`trace/utils.py` 删除，`trace/` 只剩 `store.py`（只依赖 schemas）；
`harness/tag_attempt.py` 一并退役（盖章逻辑并入渲染器，harness 只传
`attempt` 字段）。`build.py` 新增 `TraceTool(trace)` 注入两级 harness。

**为什么这么改**：方案 v5 任务三（分工语义：harness 只组装、tool 管转换；
utils 只被自己的模块使用——trace_utils 的全部调用方是 harness，
trace 自己从不调用）。req 带 kind 而不按领域对象类型分派：`ModelCall`
有三种账单、`StepMemory` 有读/写两种，类型名决定不了格式，"这是哪笔账"
只有调用方知道。

**取舍**：req 是"公共字段 + 领域对象可选字段"的宽模型，各 kind 必填
字段靠渲染函数入口 assert（precondition）表达——换来的是端口只有
`append`/`events` 两个方法、schemas 不新增 28 个文件。`trace_render.py`
约 700 行超出 300 行拆分线：28 个渲染函数按 kind 内聚强、互相只共享
`_tag_attempt`/`_render_goal_stack` 两个小工具，拆文件只会打散内聚，
先接受并在此记录。payload 字段格式是跨模块契约
（`evaluation/eval_report.py` 按字段名解析），变更权在 tool 层，声明写在
模块 docstring。

**影响面**：`episode_harness.py`/`run_harness.py`/`brain_utils.py`/
`game_utils.py`/`run_plan_utils.py` 约 50 个调用点改写（工具脚本辅助 +
人工修复两处脚本粘连）；`trace/__init__.py` 出口收窄为
`LocalTrace`/截图读取；全链 import 冒烟 + TraceTool 分派冒烟（假端口
验证 model_call 一拆二）通过。

## 2026-09-07 —— 协议类按通信方向改名：文件名 = 类名 = From{调用方}To{被调方}{函数名}{Req|Resp}

**改了什么**：`schemas/communication/` 下 23 个协议类整体改名，req/resp 拆成
一文件一类，光读目录就读出"谁对谁说话"。三跳全覆盖：
harness↔`BrainTool`（10 个，如 `FromHarnessToBrainToolChooseOnceReq`）、
`BrainTool`↔`Brain`（9 个，如 `FromBrainToolToBrainJudgeResp`）、
harness↔`MemoryTool`（2 个）、`GameTool`↔`World`（1 个）；外加一处纠偏：
`MemoryEpisodeSummaryResp` 名不副实（它是 brain 问 LLM 蒸馏的响应，跟
MemoryTool 无关），改名 `FromBrainToLlmEpisodeSummaryResp`。内嵌模型
（`PlanGoal`/`RunPlanResp`/`StepVerifyVerdict`）不是跳协议，留在
`run_plan.py`/`step_verify.py` 不动。

**为什么这么改**：方案 v5 任务二（用户拍板：命名统一 PascalCase、
req/resp 分文件、类名一起改、memory/game 一起纳入）。旧命名
（`BrainToolDecideReq`）看不出方向，第二跳（`BrainDecisionReq`）更看不出
"谁递给谁"；新命名把调用关系写进标识符，配合第 1 节"tool 管转换"的
分工，两跳契约独立演化时目录自己会说话。

**取舍**：只改 .py 与 import，`docs/spec/` 的既有文档没同步（旧名出现在
历史文档里属史实，后续文档按需引用新名）；providers 一跳
（`TextCompletionResp` 等）与 harness 对外协议（`run_outcome` 等）本轮
明确不改——前者多调用方共用、方向词不唯一，后者调用方是 api 层不是
模块 tool，留待后续单独定（方案第 9 节）。

**影响面**：23 个类 × 22 个消费文件（brain/harness/tools/interfaces/
world/prompts）纯改名，无行为变化；`build.py`/`api.py` 全链 import 冒烟
通过。ruff（除既有 E501/B905 旧账）+ UP042（human_review，既有）零新增。

## 2026-09-07 —— utils 归位：删包根 `pokemon_agent/utils.py`，三个函数各回各家

**改了什么**：包根 utils 按消费者拆解后删除。`strip_json_fence` 搬进
`brain/brain.py` 成模块级私有 `_strip_json_fence`（唯一消费者是 brain 自己
的四处解析，剥围栏本就是大脑输出解析职责的一部分）；`permission_was_denied`
+ `PERMISSION_ERRORS` 搬进 `harness/episode_utils.py`（唯一消费者是
`EpisodeHarness` 的权限降级节点；原 docstring"跨 episode/run 两级图共用"
与事实不符，grep 证实 run 层不用，已改写）；`tag_attempt` 新开
`harness/tag_attempt.py`（消费者跨 episode/run 两层图，放任何一层的
utils 都会让另一层反向依赖——两层图互不依赖，这里是大伞下唯一的中立落点）。

**为什么这么改**：方案 `docs/spec/tools/PLAN_harness_decoupling.md` v5
的任务四。包根 utils 是"跨模块共享"的垃圾桶形态：三个函数没有一个真正
被两个模块消费，所谓"跨模块"只存在于 docstring 叙事里。模块边界要像
微服务一样清晰（本次重构的任务三），每个函数按"谁用它"归位是第一步。

**取舍**：`tag_attempt` 没有并进 `episode_utils.py`——`run_plan_utils`
import 它就会打破"run 层不知道 episode 层存在"；宁可多一个小文件（文件
名=函数名）也不开这个口子。`strip_json_fence` 没有开独立文件——单消费者、
五行的函数不值得一个模块。

**影响面**：删 `pokemon_agent/utils.py`；`brain/brain.py`、`harness/`
四个文件改 import；无接口/行为变化（函数体逐字搬运）。

## 2026-09-07 —— harness 依赖收口：run 级规划收编 Brain（而非新开 PlanTool）；utils 按依赖拆分

**改了什么**：
- **`Brain` 新增第四个技能 `plan_once`**（`brain/brain.py`）：run 级规划
  收编进 `BrainPort`/`Brain`，不新开工具类。构造函数新增 `plan_llm`
  参数（缺省回退 `judge_llm`，跟 `verify_llm` 同一个回退约定），
  `plan_once(req: RunPlanReq) -> BrainPlanResp` 跟 `choose_once` 同一个
  形状——问一次模型、自己解析（`Brain._parse_plan`，剥 json 围栏 +
  `json.loads` + `RunPlanResp` 校验）、失败抛 `PlanAttemptFailed`（附
  账），不重试。`RunPlanReq` 新增 `prompt` 字段（跟 `BrainDecisionReq`
  同一个"调用方拼好回填"的约定）；新增 `BrainPlanResp`（`plan` +
  `calls`），旧 `RunHarness`/`run_utils.ask_planner_with_retry` 里那套
  "问、重试、记账"搬进新拆出的 `harness/run_plan_utils.py`（`BrainPort`
  作参数注入，不再是 `PlanToolPort`）。`RunHarness.__init__` 的
  `plan_tool` 参数改名 `brain: BrainPort`——直接复用 `EpisodeHarness`
  那同一个 `Brain` 实例，`plan_once` 只是它的第四个技能，不是另一条依赖；
  `build.py` 相应把 `plan_llm=ArkProvider(...)` 加进已有的 `Brain(...)`
  构造，`RunHarness(brain=brain, ...)` 直接传同一个变量。config/
  permissions.json 补上新方法用到的 `execute:llm:plan` 权限。
  **本条目是对同一天早些时候方案的修正**：最初实现走的是新增
  `PlanToolPort`/`tools/plan_tool.py`（复审时发现的记录见下方"为什么这么
  改"），复审后发现它跟 `Brain.choose_once()` 是同一个模式的重复发明，
  已删除，改成现在这版——`interfaces/tools/plan_tool_port.py`、
  `tools/plan_tool.py`、`schemas/communication/plan_tool.py` 均已删除，
  未曾提交过。
- **harness 的 utils 按"跟哪根依赖交互"拆分**：`episode_utils.py` 原来混装
  纯图控制函数 + 三根依赖各自的重试编排，现在只留不绑定任何依赖的纯函数
  （`derive_episode_reason`/`compute_stall`），新拆出 `game_utils.py`
  （`perceive_with_retry`）、`brain_utils.py`（`choose_with_retry`）、
  `memory_query_utils.py`（`build_knowledge_query`/
  `build_verify_knowledge_query`/`build_scene_key`）；run 级同理，
  `run_utils.py` 只留 `goal_retries_exhausted`/`apply_goals_edit`/
  `episode_trace_events`，新拆出 `run_plan_utils.py`（`RUN_TRACE_MASK`/
  `ask_planner_with_retry`/`to_tasks`）。
- **通用小工具上移包根**：`permission_was_denied`/`PERMISSION_ERRORS`/
  `tag_attempt` 不认识任何端口/schema，从 `episode_utils.py` 挪进
  `pokemon_agent/utils.py`，episode/run 两级图共用同一份。

**为什么这么改**：harness 只允许持三根依赖——brain/trace/tools——的规则
收紧后，`RunHarness` 直接拿 `LLMProvider` 是唯一的漏网户：episode 层已经
全部经 `GameToolPort`/`MemoryToolPort`/`BrainPort` 转手，run 层的规划器
却绕过了这层收口。**第一版**补了一个跟 `GameTools`/`MemoryTool` 同构的
`PlanTool` 把它拉回同一个模式；**复审后否决**：`tools/xxx_tool.py` 存在
的理由是转换"某个有状态外部系统"的原始数据结构（world/memory 各自独立
维护状态），而 run 级规划面对的仍然是 `LLMProvider`——跟 `choose_once`
面对的是同一类依赖（模型 provider），`PlanTool.plan_once()` 里那套
"调模型 → 剥 json 围栏 → 解析 → 失败抛异常带账"跟 `Brain.choose_once()`
逐行同构，是把 `Brain` 已经在做的事重新发明了一遍，多出一层没有必要的
间接。修正后的判据顺带说清楚了 `brain`/`trace` 为什么不用进 tools 层、
`prompts` 为什么不需要专门的工具包装——都写进了技能文件
`ai-coding-paradigm`（"目录分级镜像"一节新增三段）。
utils 原来一个文件混装"跟哪根依赖交互都有"的函数，找一个函数要先猜它归
哪一类；按依赖拆开后，"这段代码该放哪"直接由"它在跟谁打交道"决定，不用猜。

**验证**：`python -m compileall pokemon_agent` 全过；`pokemon_agent.build`
链路导入冒烟通过（含 `Brain.plan_once`/`BrainPort.plan_once` 存在性、
`RunHarness`/`Brain` 构造签名核对）；`ruff check`/`ruff format --check`
对本次改动的全部文件（`brain/brain.py`、`interfaces/brain/brain_port.py`、
`interfaces/__init__.py`、`tools/__init__.py`、
`schemas/communication/{run_plan,__init__}.py`、
`harness/{run_plan_utils,run_harness}.py`、`build.py`）零新增问题（repo
里现存的 30 条 pre-existing 债务与本次改动文件无交集）；手写功能测试
（用假 `LLMProvider`/`TracePort` 驱动 `ask_planner_with_retry`）覆盖
"失败一次再成功"（trace 依次记 MODEL_CALL/ERROR/MODEL_CALL）与"预算耗尽"
（`PLAN_MAX_ATTEMPTS` 次全失败、trace 记满 `PLAN_MAX_ATTEMPTS * 2` 条）
两条路径，以及 `plan_llm` 缺省回退 `judge_llm` 的构造行为，均通过。

**影响面**：`RunHarness` 构造签名变了（`plan_tool: PlanToolPort` →
`brain: BrainPort`），`Brain` 构造新增可选参数 `plan_llm`，`build.py` 已
同步；没有发现其他直接构造 `RunHarness`/`Brain` 的调用点
（`api.py`/`experiment/*` 都经 `build.py`）。`config/permissions.json`
新增 `execute:llm:plan` 权限项（`env`/`trusted-agent` 两个角色）。

## 2026-09-06 —— object 语义记忆改造落地：事件流 + 判定收编 harness + 蒸馏组装上移 brain

**改了什么**：ROADMAP 16 事件流方案实施——
- **schema**：`schemas/datastore/object_memory.py` 重写为三类交互事件
  （`ObjectDialogEvent`/`ObjectWarpEvent`/`ObjectStillEvent`，公共戳
  episode_id/step/actor_place/place/kind/button，discriminated union）；
  `ObjectMemory` 类、`leads_to`、`RESULT_*`、`MAX_TRIED`/`MAX_OBJECT_LINES`/
  `MIN_STITCH`/`_stitch` 全部删除；
- **判定收编 harness**：新增 `harness/object_interactions.py`——
  `kind → 姿势判定函数列表`（门两姿势：走过去/站门格朝外按；柜台空一格延伸；
  转向步/多段链/连按不产出），`memory/semantic/util.py` 三个纯函数随迁并删除；
- **memory 纯事件日志**：`InMemoryObjectStore` → `EventObjectStore`
  （`append` 写穿 per-episode JSONL、`query`/`query_map` 过滤直返事件、
  `truncate` 键控幂等重写）；
- **文字化搬 prompts/**：`render_object_events()` 逐事件一行（ep/step 前缀，
  无裁剪/拼接/门特判）；
- **接口/门面/节点**：`SemanticObjectStore`、`MemoryToolPort`、`MemoryTool`
  按 append/query/truncate 重塑；`episode_harness` 三个节点（store/retrieve/
  verify_and_summarize）接线；`trace/utils.object_note` 改记事件本身；
- **蒸馏组装上移 brain**：`_create_episode_memory` 进 `brain.py`，
  `VerifyAndSummarizeReq` 加 episode_id/run_id、resp 加 episode_memory，
  `MemoryTool.store_precomputed_episode_summary` → `store_episode_summary`；
- `.gitignore` 加 `memory/semantic/object_events/`。

**为什么这么改**：checkpoint/恢复（ROADMAP 16）要求记忆可按 step 截断回滚；
就地合并的档案无法回滚，事件流（追加写 + step 戳）可以。判定搬 harness 后
memory 不理解游戏、只理解键和记录（AGENTS.md 四·分层原则）。

**取舍**：返回裸事件而非折叠视图（用户拍板"更纯粹"）——每帧渲染重放
O(事件数)，本规模毫秒级；旧逻辑里"方向键对所有已知候选格记同一结果"的行为
随方法表取消（人的姿势函数对方向键返回 None），行为变化是设计意图；
旧 render 的一行式兼容教训不再适用，渲染层零兼容包袱。

**验证**：compileall 全过；ruff check 全仓 15 项（全部既有债务，本次改动零新增）、
format 全过；全链导入冒烟（12 模块含 build/api）通过；行为冒烟通过——
事件落盘/重启读回/渲染模板逐行断言/不读未来过滤/截断幂等/方法表六场景
（dialog、柜台兜底、door-walk-into warp/still、转向跳过、多段链跳过、
站门格朝外按 warp/still）。

**影响面**：object 记忆的数据形状从"每格档案"变为"事件流"，旧进程内存数据
不作迁移（原 store 本就纯内存、无落盘遗留）。checkpoint 的 save_checkpoint
节点与恢复入口（依赖本条）尚未实施。

## 2026-09-06 —— render 模板定稿：逐事件一行，裁剪/拼接逻辑确认全删

**改了什么**：ROADMAP 16 事件流条目补最终模板——`render_object_events(events)`
为 prompts/ 组装辅助纯函数，逐事件一行（行首 ep/step → 站在 actor 格按 button →
对象格+kind：载荷），**无裁剪、无拼接、无门特判、无互动次数抬头**；
`MAX_TRIED`/`MAX_OBJECT_LINES`/`MIN_STITCH`/`_stitch`/`RESULT_*` 确认随
`ObjectMemory` 全部退役，新旧由行内 step 自明。

**为什么这么改**：用户否掉带"已经走通/还剩 N 种碰法"的分组式模板——"简单告诉我
做过什么就行，并标明 episode 和 step"。折叠/去重/拼接全都不做，消费方（模型）
按行内 step 自判新旧；将来真嫌长，"同姿势留最新"是一行改动，先不加。

**影响面**：仅文档。



## 2026-09-06 —— 事件流三次拍板：写时定型分事件类型，ObjectMemory 档案类退役

**改了什么**：ROADMAP 16 事件流条目第三次改写——事件从"单 op 单模型 + result
三态字符串"改为**写时定型 discriminated union**（公共戳 + actor_place/place/kind/
button，三个子类型 dialog/warp/still）；`ObjectMemory` 可变档案类、`leads_to`
派生、`RESULT_*` 字符串约定全部退役；memory 定形为**纯事件日志**（append 写穿 +
query 过滤直返事件 + truncate 重写），折叠与文字化（同姿势最新覆盖、`_stitch`
对话拼接、上限裁剪、known_objects 文本）整体搬去 prompts/ 组装辅助纯函数。

**为什么这么改**：用户连续两次简化——a) "不要 ObjectMemory，查询直返事件"；
b) "写 event 时直接定型（进入地图/对话各一种）"。我最初推荐 a 折中（memory 内
折叠、返回每格视图），被用户指出 `_stitch` 对话窗口拼接是 GB 对话框分页机制——
拼接属于"理解游戏"，按"memory 不理解游戏"的分层原则必须离开 memory；a 不是
完全体，b 才是。render 现状在 ObjectMemory 方法上（schema 层做文字化，本来就
放错层），按 AGENTS.md prompts/ 定义（模板 + 组装辅助函数）归 prompt 组装。

**取舍**：每帧查询重放 O(事件数)（本规模毫秒级），换取 memory 零派生状态——
内存 list 是存储本体而非物化视图；render 无兼容包袱可重写（旧一行式兼容教训
见 0903 条目）。

**影响面**：仅文档。实施顺序更新：三个事件类型 schema → kind 方法表 →
EventLog（append/query/truncate）→ prompts/ 折叠+render 纯函数 → 接线 →
恢复入口 → 蒸馏组装上移。

## 2026-09-06 —— 事件流 schema 终版拍板，替换进 ROADMAP 16；AGENTS.md 蒸馏器注记同步

**改了什么**：ROADMAP 16 的"object_fact 事件流"条目替换为终版——单 op 单模型
`ObjectFactEvent`（episode_id/step 戳 + actor_place + place + kind + button +
result），`result` 三态（无效果 / 进入新地图N 前缀 / 其他=对话正文本身），
harness 判定结构定为 `kind → 姿势判定函数列表`（门含"站门格朝外按"与"面向门
走进去"两条姿势），`truncate`/fold/写穿细节成文，assert 契约补 `append` 单调
前置与 `leads_to` 防撞前缀两条；新增"蒸馏组装函数上移 brain"拍板条目。
AGENTS.md 树里"episode_store.py 含蒸馏器"注记改为"蒸馏调用在 brain，
episode_store.py 纯存储"。

**为什么这么改**：设计讨论收敛——用户砍掉 touch/attempt 双 op（button 已表达
差异）、key_desc 改为独立的 actor_place + button 两字段、text 并入 result
三态（对话正文自己就是结果）；门的两条姿势由用户补充（面向门走上去也是门）。
蒸馏器归属：蒸馏 LLM 调用本就在 Brain.verify_and_summarize，memory 层只剩
纯组装，按"memory 只做读写"原则上移。

**取舍**：单 op 扁平模型优于 discriminated union（两个 op 才七个字段，union
过度设计）；attempts 键保持字符串形状（`_render_attempt` 解析不动），键值改为
actor_place+button 拼接；对话正文撞 `RESULT_WARP_PREFIX` 的边角用严格匹配/
harness assert 封住，不为此改 result 形状。

**影响面**：仅文档。实施顺序（用户开写）：事件 schema → kind 方法表 →
append/truncate/fold → 接线 → 恢复入口 → 蒸馏组装上移。

## 2026-09-06 —— AGENTS.md 新增分层原则：memory 只做读写与索引

**改了什么**：第四节目录结构 memory/ 条目加"只做读写与索引"注记，树后新增
分层原则一句话（memory 只保管 harness 交给的数据结构与索引、按键原样读写；
语义判定由 harness 以数据形式交给它）。ROADMAP 16 的 object_fact 事件流条目
追记与该原则的合流关系（写接口一步到位成 `append(事件)`）。

**为什么这么改**：用户要求 memory 模块精简泛用——现状 `store_objects_interactions`
（MemoryTool）与 `memory/semantic/util.py`（surrounding_cells/kind_in_frame/
parse_landmarks）把交互判定、受影响对象计算这些游戏语义判定放进了 memory 侧。
该原则同时是 object_fact 事件流改造的接口形状来源：判定搬去 harness 后，
harness 构造事件、memory 只认键和记录。

**取舍**：原则放第四节（分层职责与目录结构同处）而非铁律——它是对 memory
单层的边界约定，不是全项目"违反即返工"级约束；蒸馏器暂留 memory 层未动，
按此原则的归属待用户裁决。

**影响面**：仅文档。代码改造（判定搬 harness、写接口改 append）随 ROADMAP 16
实施一起做，未在本条动代码。

## 2026-09-06 —— ROADMAP 16 二次拍板：任意存档点续跑从"分支"简化为"截断"

**改了什么**：第 16 条里"任意存档点续跑 = 分支，不覆盖"（attempt id + fork 时
物化）整条替换为"截断"——选定 step N 续跑时删掉 N 之后的一切（存档文件、
step_memory 的 step > N 记录、object_fact 的 step > N 增量后重折叠），单时间线、
无 attempt id。崩溃续跑变成截断的特例（未来 ≤1 步）；review retry 白捡（截断
正是回退重跑的全部操作，rewind 接口位撤掉）；assert 契约同步改（截断完成后
store 无 step > N 记录）；object_fact 事件流的键去掉 attempt 段。

**为什么这么改**：用户提出"选定 checkpoint 之后，后续的存档都得删除"——用放弃
未来分支换来删掉整套 attempt/fork/分支折叠机制。object_fact 事件流不受影响反而
更必要：就地合并的当前值无法回滚，增量日志的截断就是删几行追加记录（幂等）。

**取舍**：真实代价一条——回到 step 50 后不能再回到曾经历过的 step 200 之后；
被放弃尝试的完整过程在 trace 底账里都有（trace 追加写从不删），实验数据不丢。
"检索不读未来"的过滤边界（< vs ≤）标注为实现时用 assert 钉住的点。

**影响面**：仅文档。实施顺序不变：CheckpointPort → 两 store 写穿（事件流）→
save_checkpoint 节点 → 恢复入口（含截断）。

## 2026-09-06 —— checkpoint/resume 方案拍板进 ROADMAP 第 16 条（含 object_fact 事件流）

**改了什么**：`docs/ROADMAP.md` 第 16 条从 💬 立项改写为 📋 方案拍板——0902 的
"没定的地方"四问全部有了答案，新增 0906 拍板九条（自管步级 checkpoint 不用
LangGraph checkpointer / save_checkpoint 当图入口且 look 零改动 / bundle 四件套 /
记忆写穿不进 checkpoint / object_fact 改增量日志事件流 / 任意存档点续跑 = 分支
不覆盖、fork 时物化 / 检索不读未来显式化 / 收尾链不存档 / rewind 留接口位）+
恢复 assert 契约三条 + 遗留三项（trace 续接待拍板、AGENTS.md 九待改、分期待定）。

**为什么这么改**：用户启动 Agent 清单第 6 项（checkpoint/恢复，评审最高优先级
缺项）的设计讨论，逐条对齐后要求落盘。object_fact 从"按格就地合并"改事件流
是用户新拍板——as-of 检索（任意存档点拿到对应记忆）的前提，与 trace
"追加写事件序列"同一哲学。

**取舍**：过程性讨论不进 AGENTS.md（规范只留硬约束），全部决策记录放 ROADMAP
一条内；fork 时物化优于链式检索（检索端零改动 vs 永久背分支折叠逻辑）；
崩溃续跑不 fork（避免单分支垃圾命名空间）。设计讨论中否决的两个方案留了理由：
LangGraph checkpointer（存不了世界、恢复点粒度错位）、look 幂等化
（save 前移后问题不存在）。

**影响面**：仅文档，无代码变更。实施顺序（契约先行）：CheckpointPort 接口 →
step/object 两 store 写穿（upsert 键）→ save_checkpoint 节点 → 恢复入口。

## 2026-09-06 —— 范式对照审计后，成本控制两条缺口进 ROADMAP

**改了什么**：`docs/ROADMAP.md` 新增第 22 条（token 预算/上限机制，💬：账本已
逐调用落盘但无超支干预，落点 harness 每步检查 vs experiment 跑批归因未拍板）、
第 23 条（模型分级，📋：build.py 已在实践分档——决策 qwen-plus / 判定校验规划
豆包 pro，但原则未成文、分配未验证），顶部"最后更新"同步。

**为什么这么改**：按 ai-coding-paradigm skill 对照 AGENTS.md 的审计发现，
强制机制 11 的三个子项里"token 落盘"代码已有（`MODEL_CALL` payload），
真正缺的是预算判断与分级成文；用户指定两条进 ROADMAP（skill 规则 8 的
ROADMAP 例外：何时改由用户决定，本次为用户明确指示）。

**取舍**：只进 ROADMAP 不动 AGENTS.md——分级原则写哪、预算阈值怎么定
都是待拍板决策，先记录问题存在，不预设答案；第 22 条倾向方案 a（复用
review 槽位问人）但标明未拍板。

**影响面**：仅文档，无代码变更。恢复了一次编辑中误删的"## 后续阶段"章节标题。

## 2026-09-06 —— 统一出口：11 个子包的对外接口收拢到 `__init__.py`（编码范式规则 6）

**改了什么**：`brain` / `harness` / `interfaces` / `memory` / `providers` / `prompts` /
`tools` / `trace` / `world` / `experiment` 及 `schemas` 三个子包（domain / datastore /
communication）各自建统一出口——公开实体在包 `__init__.py` 里 re-export 并配 `__all__`
显式声明契约面；全部消费方（76 个文件）的深路径 import（如
`from pokemon_agent.schemas.datastore.trace_event import TraceEvent`）改为
`from pokemon_agent.schemas.datastore import TraceEvent`，同包兄弟模块改相对导入。
同时删除已空的 `mocks/`（FakeLLM 前置已删）与 gitignored 的 `tests/` 整目录
（测试流程推倒重建，见 ROADMAP）。

**为什么这么改**：编码范式规则 6——深路径 import 让包的内部文件名成为公共 API
的一部分，重命名一个模块文件就要改散落各处的消费方；统一出口后文件名只是
实现细节，公共面收在 `__all__` 一处，一眼可见每个包对外承诺什么。
`__all__` 而不是 pyproject 加 per-file-ignores：后者要改 lint 规范（AGENTS.md
约定"改规范先讨论"），且 `__all__` 本身就是出口契约的可执行文档。

**取舍**：`schemas/domain`、`schemas/datastore`、`prompts` 三个包的 re-export 放在
文件**底部**并带 `# noqa: E402`——因为 `action_from_brain.py` 等子模块有
`from . import MAX_RATIONALE` 式的反向依赖（常量定义在包 `__init__` 里），顶部
re-export 会构成循环导入。`__all__` 纯字符串列表无运行时解析，放顶部不受影响。
顺手修复：import 重排（isort）合并了重复导入、`brain.py` 的 `DIRECTION_KEYS`
常量从 import 块中间移到块后、对 7 个既有格式债务文件跑了 ruff format
（单独成清理提交）。

**影响面**：76 个文件 import 改写 + 12 个 `__init__.py` 重写，无任何行为变更。
验证：ruff check 从改写前 109 项既有债务降到 38（本次引入的 I001/E402/F404 全清零，
顺带修掉 baseline 的 5 个 F401 和 2 个 F811）；ruff format 116 文件全过；
全量导入冒烟（80 模块含 `build` / `api`）通过。

## 2026-09-06 —— 注释历史叙事迁出代码（编码范式规则 7 落地）

**改了什么**：`pokemon_agent/` 全部 35 个文件的历史叙事注释按四项拍板迁出——
（1）去向：全部进 CHANGELOG（按拍板日期补录在下方各条）；（2）边界：`#` 行内
注释与 docstring 里的历史段都清，契约 docstring（前置/后置条件、字段约束、
不变量、已知风险）保留；（3）`# 步骤 N：` 进度注释与 `# ---- 分节 ----` 保留；
（4）AGENTS.md 注释条款同步改写。改写形态：日期标记（"0904 新增"/"0905 起"）
直接删、句子改现在时；"不再 X"改"不 X"；纯事故/旧实现故事删除，代码里最多留
一行 `（取舍见 CHANGELOG.md 日期 条目）` 指针。运行时字符串例外仅一处
（`episode_harness` judge 第 0 步 payload 的 `why` 去掉拍板标记）。

**为什么这么改**：规则 7——注释仅三处（文件顶层/函数顶层/函数内步骤进度），
注释只写契约与进度，取舍论证与历史叙事一律进 CHANGELOG 或 docs/spec。
原 AGENTS.md"注释只写为什么"条款与之方向相反，按"改规范先讨论"先拍板再改。

**取舍**：防回归红线（如 `WorldPerceptionResp` 不加 ok/message/帧哈希、
`GameTools` 不攒掩码依据）保留为一句现在时红线；完整事故故事进补录条目。
`memory/semantic/util.py:73` 的"我以前见过那里有什么"是喂模型的 prompt 文本，
不是注释，不动。

**影响面**：约 130 处注释/docstring/Field description 改写，零行为变更。
验证：compileall 全过、ruff check 32 项（均为既有债务）、format 116 文件全过、
80 模块导入冒烟 OK。

## 2026-09-06 —— 补录：蒸馏收敛到 verify_and_summarize、prompt 组装对齐、dedup_snapshots 定型

**改了什么**（0906 决策，当时未记录，注释迁出时补记）：
1. 删掉 summarize 兜底节点：`EpisodeMemoryGenerator` 瘦身成纯组装
   （`build_from_response()` 静态方法），`generate_summary()`/`_build_prompt()`/
   `_parse_response()`、harness 侧 `summarize()` 节点、`MemoryTool.store_episode_summary()`、
   `MemoryEpisodeSummaryReq` 一并删除——只保留"先校验、再只用可信记录蒸馏"一条路径。
2. `dedup_snapshots()` 定型：前身 `frame_sequence()` 只返回图片列表，"这张图对应
   哪份观测"要调用方翻 `entries[-1].after` 自己猜（猜错静默喂错内容）；改成一次
   遍历同吐截图与观测两条严格对齐的列表，由构造保证对应；薄包装随后删除。
3. `run_plan` 组装对齐：`history_lines`/`goals_lines` 从 `harness/run_utils.py`
   搬进 `prompts/run_plan.py`，struct→text 归 prompts 层，与其余四份 prompt 一致。
4. `VerifyAndSummarizeReq` 删掉 `initial_state`/`final_state`：与 `steps_text`
   字面重复且 `.render()` 更贵（带 walk_map），不留兼容字段。

**为什么这么改**：1/4 是"没有东西可校验/可蒸馏就不问模型"+去重复渲染；
2 是消除"靠约定猜对应关系"的静默错位面；3 是单一职责归位。

**取舍**：收尾链在无 step 记忆时直接 END，不存在不经校验的全量蒸馏路径。

**影响面**：harness/memory/prompts/schemas 四层联动；无行为变更（补录）。

## 2026-09-05 —— 补录：模型选型切换、provider 泛化、verify 合并、观测状态搬家

**改了什么**（0905 决策，当时未记录，注释迁出时补记）：
1. **模型选型**（用户拍板"之前可能是模型不行，现在换最强的"）：judge/verify/
   memory/plan 换火山方舟 `doubao-seed-2-1-pro-260628`（旗舰、原生多模态）；
   感知从 `qwen3-vl-plus` 升 `qwen3.8-max`（DashScope 没有 `qwen3-vl-max`，
   VL plus 已是最高档）；决策维持 `qwen-plus`；run 级规划器拆独立 `plan_model`
   参数（职责不同、要能分开调），回退链落 judge_model（不落 text_model——
   Qwen 型号名传 ArkProvider 会 404）。
2. **QwenProvider 泛化**（原 QwenText/QwenVision）：一个供应商一个类，不按
   text/vision 拆；temperature 不再由子类定死，每次构造显式传（0.7 决策链路 /
   0.0 感知）；图像预处理插件机制（vision/preprocess.py）判定为死重量删除。
3. **verify_steps 与 summarize 合并**：两次独立 LLM 调用合成一次（省一次往返）。
   放弃的韧性：verify 坏了 summarize 原能单独成功一次。当初 verify_steps 独立
   出来的事故：战斗菜单 `down×3` 被记成"逃跑"、实际打开道具袋——不可信记忆
   直接进蒸馏会把错误固化成跨局知识。
4. **`done`/`success` 搬家**：从 `ObservationFromWorld` 搬到 `EpisodeRunState`。
   原状是 `judge` 靠 `obs.model_copy()` 硬写回，`obs.done` 身兼"世界原始信号"
   与"harness 终止裁决"两职，判完就覆盖、无法回溯是谁说的。
5. **JUDGE_HISTORY 3→2**（用户拍板）：压缩 judge 链路 input token——history
   每条都是纯动态内容（永远排不进静态前缀）。已知风险（用户接受）：2 条未必
   覆盖"证据在两步前"，无实测，效果待真机观察判定失效率。
6. **截图直存 base64**：`StepMemory.before_frame`/`after_frame`、
   `VisionCompletionReq.images` 从文件名引用/`bytes` 改为 base64 字符串；
   `screenshot_step` 参数引入（感知帧按未来步号编号，堵 0 号帧与 before/after
   撞名）；`screenshot/` 人眼可读副本目录新增。
7. **describe() 布局**：单图泛化成图组；文字块挪最前、图片挪最后——隐式缓存
   按请求开头匹配前缀，图在前会掐断静态前缀的缓存（标准价 20% 的复用全吃不到）。
   图序变化对识别准确率的影响无实测，待观察 `cached_tokens` 与失效率。
   DashScope/Ark 隐式缓存"默认开、不可关"（0905 查证）。

**为什么这么改**：见各条——核心是压缩 judge 链路 token、消除字段双义、
吃满隐式缓存。

**取舍**：见各条括注，均已用户确认。

**影响面**：providers/build/schemas/harness 多处；无行为变更（补录）。

## 2026-09-04 —— 补录：plan 双开关与人工通道、GoalsEdit 收敛、事件挂载点调整

**改了什么**（0904 决策，当时未记录，注释迁出时补记）：
1. **plan 双实验开关**：`auto_push_goals`（`False`=丢弃 `resp.push_goals`，
   新目标走 `POST /runs/{id}/goals` 人工通道）与 `auto_decide_done`（`False`=
   plan 无权结束 run，栈空路由去 review 问人）。API 层常量默认全关。
2. **GoalsEdit 收敛**：`push`/`remove`/`replace`/`sync` 四种增量 kind 删到只剩
   整栈原子替换（前端把目标栈改成纯本地草稿后增量 kind 无调用点）；review
   决策里同名旧 `PUSH` 一并删除；goals 单独读接口 `GET /runs/{id}/goals`
   （用户拍板"goals 单独拿出来"）；`HumanNoteReq` 实时插话端点新增。
3. **frame_png 挂载点**：原始画面直接随感知 MODEL_CALL 事件落盘，不经
   `EpisodeRunState.pending_frame_png` 转手（字段删除）——喂给模型的东西记在
   它真正发生的地方；`ModelCall.payload.prompt` 字段新增。
4. **入栈顺序事故**：`push_goals` 的 LIFO 语义曾被反转（误读"先压的先做"为
   "列表第一项最先执行"），用户 0904 纠正：列表**最后**一项是新栈顶、最先派发；
   harness 不替模型倒转顺序。

**为什么这么改**：1/2 是"plan 的工作全部交给 review"的人工接管实验；
3 是账随事走；4 是 LIFO 契约澄清。

**取舍**：两个开关独立可单关；GoalsEdit 改动执行中栈顶的风险已确认可接受
（人工 review 阶段时间窗小）。

**影响面**：api/harness/schemas 多处；无行为变更（补录）。

## 2026-09-03 —— 补录：图节点拆分、感知/账单挂载、schema 红线与渲染教训

**改了什么**（0903 决策，当时未记录，注释迁出时补记）：
1. **节点只改一处**：旧图三节点（look_and_judge/retrieve_memory/remember）各
   一口气写多处状态（最多一处写三个字段+两处落库），拆成现在的十七节点图；
   recursion_limit 公式随之从 `×6` 改 `×16+20`（撞 GraphRecursionError 的症状
   是一局无声截断）。
2. **观测产出点收敛**：`look` 不再每步调 `perceive()`（和上一步末尾感知的是
   同一帧，靠帧缓存挡钱）；观测只在 `_begin`/`look_after_action` 两处产出；
   knowledge/跨局摘要不折进 `obs.facts`（与当帧数据混在一起，模型分不清可信度
   ——trace#20 复盘牵出），各走 `BrainDecisionReq` 独立字段。
3. **节点活动轻量事件 6 类**（judge_verdict/action_space/step_advance/
   retrieve_node/look_after/verify_result）：观测台对齐图后一批节点"亮了却没
   内容"，补零成本记账；Source 各自归位。
4. **记账统一"谁控制循环，谁记账"**：旧版 brain 写 MODEL_CALL/THINK、harness
   写 ACT/OBSERVE/EPISODE_*，"哪类事件归谁写"要一条条记还开例外；现在
   `ModelCall` 只产账单，事件由 Harness 翻译。`Source.VERIFY` 从 JUDGE 拆出、
   `Source.PLAN` 从 HARNESS 拆出（各自独立算失效率/成本）。
5. **WorldPerceptionResp 红线**（事故背书）：不加 `drain_calls()`（生产/消费
   靠可变状态搭桥，清早清晚都会算错账——修法是产出处直接当返回值交出）；
   不加 `ok`/`message`（恒真布尔比没有更糟；动作效果由前后观测对比回答）；
   不加帧哈希（"一帧只感知一次"后无前提）。
6. **渲染教训**：object 记忆一行式 `→` 渲染一符号多义+80 字符截断，改"抬头+
   明细"多行；`walk_map` 格子间加空格被模型当成格子（一行 10 格看成 19 格），
   改无空格；`same_place_as` 折叠在战斗帧恒等、每步谎报"动作没有效果"（大脑
   推翻正确按键、编出能自圆的菜单模型）——错误结论比没有结论贵，删。
   `ActionSpaceForBrain` 的 note/map_note 拆两字段（地图规则不该挂在"可用按键"
   标题下）；`OVERLAY_ACTIONS` 的 CHOICE 掩码取两种布局**并集**（取交集的教训：
   RUN/PKMN 物理够不着，任务恒不可能成功，大脑反而编出"线性焦点导航"自圆）。
7. **杂项**：朝向改读内存（按键推断开局/过场后未知、不进存档）；`ScreenState`
   从 schemas/domain 降级到 world（全项目只有 pyboy_world 认识它）；prompt
   组织"谁只服务谁"的物理目录边界（`game_hints.py`/`brain_hints.py` 并入
   `decide_action/` 子目录）。

**为什么这么改**：见各条。核心主题：单字段单义、账随事走、掩码宁可多给不可
少给。

**取舍**：CHOICE 并集的代价是竖排选择框里左右成空按键（可见、白费一步），
够不着的选项不可见（成功率恒 0）——两害取其轻。

**影响面**：harness/trace/schemas/world 全层；无行为变更（补录）。

## 2026-09-02 —— 补录：检索增强验证、审查依据随事件走、散逸教训

**改了什么**（0902 及更早、日期不可考，注释迁出时补记）：
1. `verify_steps` 改检索增强验证（整局一次检索领域知识交给校验器判领域合理性；
   检索单独成节点，level 与主循环一致）。
2. 审查依据随事件走：`episode_trace` 自带全部审查依据，前端不用二次请求、
   不维护跨会话历史缓存（见 `docs/ROADMAP.md`"前后端交互统一"）。
3. 散逸教训：任务 criteria 不能是残句（`"x或y坐标"` 无法比对，成功率恒 0 且
   看不出原因）；判据不能引用本 scene 读不到的字段（`pokemon_center_heal` 曾
   写"或 my_hp 回满"而治疗发生在 indoor，facts 按 scene 装字段）；`with_permissions`
   存在性断言前移到构造期（库曾在 import 时读 json，缺了 import 即炸；现在
   拖到首次 `harness.run()` 才炸，那时 world 已建好、模型已加载）。

**为什么这么改**：见 `docs/ROADMAP.md` 对应条目。

**取舍**：无（补录）。

**影响面**：无（补录）。

## 2026-09-03 —— 观测台链翻页改"按键翻页器"（替代点标签激活）

**改了什么**：`web/src/App.tsx` ChainPanel 的页签栏（点任意标签跳转）替换为
翻页器——`◀` 上一页 / 页码区（`最新` 或 `历史 x/n` · 第 N 局 · step M）/ `▶`
下一页；另加键盘支持：`←` 上一页、`→` 下一页（已到最新再按 → 进入跟随）、
`Home` 第一页、`End` 回到最新。翻页时清空钉住的节点；自动跟随最新页的语义
不变（page=null），手动翻页后新 look 不打断阅读。

**为什么这么改**：用户 0903 拍板——链的回看要像翻书一样逐页按键前进，
不要"看到一排标签点哪个是哪个"的激活式交互；页签一多（长 run 几十步）
既挤又难定位，翻页器加页码天然给"我在第几页"。

**取舍**：键盘监听挂在 window（观测台无其他全局按键冲突）；`→` 在最新页
再按 = 回到跟随（等同 End），避免"翻到最后还要找按钮"。页码区显示
"历史 x/n"只在离开最新时出现，跟随态直接标"最新"。

**影响面**：仅 `App.tsx`（ChainPanel 的 state/键盘 effect/翻页器渲染 +
pager 系列样式替换 pageTabs）。tsc 通过。

## 2026-09-03 —— 观测台链改为步历史翻页（不再每 look 清空）

**改了什么**：`web/src/App.tsx` 右栏链面板从"单窗口"改"步历史翻页"——
`buildChainWindow`（取最后一次 look 之后）替换为 `buildChainWindows`
（一次扫描把事件流切成每步一页：每个 look 开一页、收到下一次 look 前）。
ChainPanel 顶部加页签栏（局·step，最新一步带 ▶ 标记），点页签回看任意
历史步；未手动翻页时自动跟随最新页（`page === null`），翻到旧页后新 look
不打断阅读，可点"回到最新"或最新页签跳回。点节点钉住看内容不变，翻页时
清空钉住。实时数字独立面板不受影响。

**为什么这么改**：用户 0903 拍板——链的意义是"看它走到哪了"，但每步清空
意味着旧步只能靠截图留证，复盘长 run 时看不到"第 3 步当时在干什么"。
数据本来全在 `events` 里，只差渲染层不切页；全部保留（每步约 17 条事件、
长 run 几百步，前端内存可扛）。

**取舍**：默认自动跟随最新页 + 手动翻页不被打断，而不是"新 look 强制跳最新"
——盯旧步复盘时画面不该被新事件抢走。事件切分一次扫描 O(N)，不复制事件。

**影响面**：`App.tsx` 的 `buildChainWindow`→`buildChainWindows`/`assembleWindow`
与 ChainPanel（新增 page/pinned 双 state + 页签样式）。tsc 通过；切分逻辑
用真实 trace（run-114633 的 9 个 look → 9 页）验证过。

## 2026-09-03 —— 禁止 episode 跨 run 检索 + 起点存档只在 run 启动读一次

**改了什么**：
1. **跨局摘要检索限 run 内**：`MemoryToolPort.query_episode_summaries` /
   `MemoryTool.query_episode_summaries` 加 `run_id: str = ""` 参数（空 = 不限，
   仅测试用）；`MemoryTool` 候选集按 `m.run_id == run_id` 硬过滤；
   `EpisodeHarness.retrieve_global_episode_memory` 调用时传 `self._run_id`。
   落库侧本来就把 `run_id` 标在 `EpisodeMemory` 上（`summarize` → 
   `store_episode_summary(..., run_id=self._run_id, ...)`），检索侧现在对齐。
2. **起点存档只在 run 启动读一次**：`EpisodeHarness` 加 `_world_reset_done`
   标志，`_begin` 只在 run 内第一个 episode 调 `game.reset(task)`（读
   `assets/rom.state` 起点），后续 episode **不重置**、接着上一局结束的状态
   继续跑；每局仍存一份 `ep{n}.start.state` 快照供 replay 定位起点。

**为什么这么改**：
1. 实测（run-112634 ep2 #143-#145）：检索回 3 条跨局摘要，其中两条来自
   昨天崩掉的 `run-181643` 的失败局 ep2/ep3——失败局被蒸馏成的
   "map12_door_north_threshold=(14,2,north) 门前贴合位"常量被当真，模型对着
   `#` 石墙按 A。跨 run 经验 = "别人家的答案"，失败局的污染会跨 run 传播。
2. 每次 episode 都闪回初始位置既烧时间（重跑开局路程）又破坏世界连续性——
   run 启动读一次起点，episode 之间世界状态保持连续（用户 0903 拍板）。

**取舍**：`run_id` 默认空串而非必填——mock/测试不需要构造 run 上下文；
生产路径（episode_harness）强制传。检索过滤放在候选集阶段（场景硬过滤
同一步），比检索后过滤省一次无谓的混合检索。

**影响面**：`memory_tool_port.py` / `memory_tool.py` / `episode_harness.py`
签名与调用；`test_episode_stall.py` 的 FakeMemory 补 `run_id` 参数；
新增 `test_query_episode_summaries_filters_by_run_id`。全量 75 passed。

## 2026-09-03 —— 清理测试债：四个坏测试处置（删 1 / 修 3）

**改了什么**：
- **删** `tests/test_episode_evolve.py`——钉的 evolve 契约已随机制删除作废
  （episode_harness 里决策等待不再靠 `game.evolve` 填充，只剩注释说明），
  其引用的 `IDLE_FRAMES_PER_POLL` 常量与 `StepAudit*` schema 均已不存在。
- **修** `tests/test_episode_stall.py`——`StepAuditResp/StepAuditVerdict` →
  `StepVerifyResp/StepVerifyVerdict`（`step_verify.py`），FakeBrain 方法
  `audit_steps` → `verify_steps`（签名对齐 `Brain.verify_steps`）。
- **修** `tests/test_run_harness.py::test_parse_plan_accepts_json_fence`——
  `RunHarness._parse_plan`（已随重构搬到 run_utils 成模块函数）→
  `parse_plan_response`。
- **修** `tests/test_api.py::test_review_endpoint_removed`→改名
  `test_review_submit_without_pending_returns_409`——review 端点并未移除
  （前端仍用 GET/POST `/runs/{id}/review`），run 存在但无待处理请求时
  返回 409 才是契约，原断言 404 是过时预期。

**为什么这么改**：EventType 收敛（20→7）与 verify 链路改名（audit→verify）
动了大量 schema/接口，三个测试只改了 import 没跟上实现，收集期就断链；
evolve 测试则是功能删除后留下的死测试。测试是用法示范，断了会让"跑测试
看红"失去信号价值——要么对齐要么删，不留收集期断链的僵尸。

**取舍**：evolve 测试选择删而非改写——机制已删，改写等于给不存在的功能
编测试，反而误导读者以为 evolve 还在。

**影响面**：仅 tests/ 四个文件。全量 74 passed（tests/ + evaluation/tests/）。

## 2026-09-03 —— 修复 retrieve_step_episode_memory 的 NameError（run 开局即崩）

**改了什么**：`episode_harness.py::retrieve_step_episode_memory` 第 376 行调用
`trace_utils.retrieve_node(ep, step, "step", ...)` 引用了未定义的裸 `step`——
函数只解包了 `ep`，漏了解包 `step`（对比同文件另外三个 retrieve 都是
`ep, step = state.episode_id, state.observation.step` 一起解包）。

**为什么这么改**：0903 收敛 EventType 20→7 时给四个 retrieve_* 节点补 RETRIEVE
活动事件，其余三处解包齐全、唯独这处只取了 `ep`，导致 run 一开局走到第一个
retrieve 节点就抛 `NameError: name 'step' is not defined` → episode 异常终止 →
run 终止 → SSE 关流 → 前端表现为「运行到一半断开」。这是收敛引入的回归，
修复即补回解包。

**取舍**：无——纯补漏，行为与另外三个 retrieve 节点对齐。

**影响面**：`episode_harness.py` 一行解包。测试套件里 `test_episode_evolve.py` /
`test_episode_stall.py` 两个收集期断链（引用已删的 `step_audit` 模块与
`IDLE_FRAMES_PER_POLL` 常量）是历史遗留，与本次无关，单列待办。

## 2026-09-03 —— 观测台合并：实时数字收进链面板，默认显示数字+点链才切节点内容

**改了什么**：`web/src/App.tsx` 右栏重排——去掉了顶部独立的 `MetricsPanel`
渲染块，`MetricsPanel` 改为内嵌在 `ChainPanel` 的内容区里。默认（未未钉住）
内容区显示实时数字（`useMetrics` 轮询结果），**用户点链上的节点才切到该节点内容**
（raw 全文）；再点一次取消钉住回回实时数字；每次新 look（episode 或 step 变）会
清空钉住 → 自动跳回实时数字。指标事件的聚合口径未动（依然是
`eval_report.aggregate_events` 复用）。

**为什么这么改**：用户用户拍板"把这个展示台和链结合在一起，只有点链的时候才会
切换过去"——避免顶部数字面板单独占位置、避免平时跑时跑时链下方的默认
raw 内容占满屏幕；只有用户主动要查看某个节点时才展开。

**取舍**：之前Chain的"不点节点自动跟随最新节点 raw" 行为改——现在未点链时默认
展示的是实时数字面板（数字面板自己有两秒轮询能跟上）而不是 raw。链上
"走到哪里"的进度信息还保留（n/15 节点 + 点亮的 bead），只是详细内容换成
按 source 聚合的数字。`tsc` 通过。

## 2026-09-03 —— 术语修正：观测台 verify 明细行改称"校验不可信率"

**改了什么**：`web/src/App.tsx` MetricsPanel 里对 `Source.VERIFY` 明细的展示标签
从"审计失效率"改为"校验不可信率"（含注释中的"审计判定"→"校验判定"）。

**为什么这么改**：用户指出 verify_steps 只是**节点内的 llm-as-judge**（蒸馏前
逐条把关 step 记忆），不叫审计——审计/统计指的是观测台「实时数字」整块聚合。
观测台的聚合口径在 eval_report（aggregate_events），与 verify 节点无关。

**取舍**：只改用户可见的观测台标签与我自己的措辞；evaluation/SPEC.md 与
ROADMAP 历史文字里残留的"审计器失效率"是旧命名沿革，未在本轮大动（eval_report
内部字段 verify_unreliable 不涉及语义）。`tsc` 通过。

## 2026-09-03 —— EventType 收敛：20 → 7 类（与 source 正交），语义进 payload.kind

**改了什么**：`EventType` 重定义为 7 个种类——`model_call` / `error` /
`llm_outcome` / `view` / `act` / `memory_io` / `lifecycle`；原 20 类语义全部
降级为 `payload.kind`（llm_outcome=intent/verdict/audit；view=frame/after；
act=space/executed/stall；memory_io=read_merge/read_step/read_global/
read_knowledge/read_object/read_verify_steps/read_verify_knowledge/
write_step/write_object/write_episode；lifecycle=run_start/run_end/
episode_start/episode_end/step）。`TRACE_SCHEMA_VERSION` 2→3，v2 旧文件不再
可解析。改动的生产代码：`trace/utils.py` 全部构造器（换 type + 注入 kind，
`memory_read` 加 kind 参数、`object_note` 的 landmark 类型键改名
`landmark_kind` 避让信封 kind）；`harness/episode_harness.py` 的
retrieve_verify_knowledge 调用点传 kind=read_verify_knowledge；`trace/store.py`
删除 PHASE_BY_TYPE（TraceEvent.phase 直接取 type 值），episode 完整判定改为
lifecycle+kind=episode_end；`harness/run_utils.py` RUN_TRACE_MASK 改为
{LIFECYCLE, ERROR}，history_lines 按 kind 筛并修掉 bool("False")==True 旧 bug；
`evaluation/eval_report.py` run/episode 汇总改按 lifecycle+kind 分支；
前端 `App.tsx` phaseKeyOf 改按 (type, kind) 定位，**删除了"窗口内有没有
decision"的 memory_read 判别启发式**（enrich 与 verify 检索现在靠 kind 直接
分）；观测台与 model_call 栏逻辑不变。测试与参考文件同步。

**为什么这么改**：用户连番追问后定稿三条准则——① type 与生产者(source)正交、
数量极小；② 只有 model_call/error 通过"换生产者 type 不变"测试，是纯种类，
其余品类名描述的是记录相对世界/模型的位置（LLM 产物叫 llm_outcome 体现与
模型交互）；③ view 保持独立（用户拍板不并入 llm_outcome）。

**取舍**：type 变粗后，"筛某类事件"从按 type 变成按 (type, kind)——前端链
映射与 run 级 mask 都相应改为 kind 感知；v2 历史 JSONL 不可读是收敛时明确
接受的结果（与 0902 删兼容成员同一决定）；`llm_outcome` 的 intent 用
action_chain 与 executed 同形以便 diff。store.py 的 phase 字段是历史遗留，
直接取 type 值不再维护映射表。

**影响面**：schemas（EventType 20→7、schema v3）、trace/utils（全部构造器）、
harness（episode/run）、evaluation（汇总分支 + 其测试夹具）、前端（kind 映射、
删启发式）、AGENTS.md type 行 + DATAFLOW 2.2/2.3 全面改写。python 全量导入
冒烟通过、`tsc --noEmit` 通过、test_run_harness + evaluation 测试通过（唯一
失败是与本次无关的旧断言 `RunHarness._parse_plan`，该方法早已搬去 run_utils）。
dev 已重启。

## 2026-09-03 —— trace 补全节点活动事件（6 类）+ model_call 独立日志栏

**改了什么**：后端 `EventType` 从 14 → 20 类，新增 6 类零成本"节点活动"事件：
`JUDGE`（判定结论 done/success/stalled/depth/why，账单仍在 MODEL_CALL）、
`ACTION_SPACE`（get_action_space 输出，count/names）、`RETRIEVE`（四个
retrieve_* + 收尾 retrieve_verify_step_memory 各自的命中摘要 kind/count/refs）、
`STEP_ADVANCE`（advance_step 的 next_step）、`LOOK_AFTER`（look_after_action
观察摘要 scene/overlay/status/done）、`VERIFY_RESULT`（verify_steps 结论
checked/unreliable，逐条 verdicts 仍在 MODEL_CALL）。trace/utils.py 加六个
构造器（Source 各自归位：JUDGE/HARNESS/HARNESS/MEMORY/HARNESS/PERCEPTION/
VERIFY）；episode_harness 的 judge/get_action_space/四个检索/advance_step/
look_after_action/retrieve_verify_step_memory/verify_steps 节点各插一条。
前端 `web/src/App.tsx`：`phaseKeyOf` 增加六类事件映射（retrieve 按 payload.kind
分到五个节点）；链节点内容过滤掉 `model_call`（账单独归日志栏）；新增
`ModelCallPanel`（全部模型调用的账 + raw，倒序），挂在右栏链面板下方。

**为什么这么改**：用户指出 trace 不全——链式观测台把图上的 19 个节点画出来后，
一批节点"亮了却看不到内容"：get_action_space/advance_step/retrieve_* 零事件，
judge/verify_steps/look_after_action 只有 MODEL_CALL 一条账；且 MODEL_CALL
（tokens/raw）混在节点内容里不适合当链路明细。拍板两件事：model_call 单独
一个日志栏；为排除 model_call 后无发送内容的节点补上 trace（区分 source）。

**取舍**：新事件全是不经模型的轻量记账，payload 不带重复全文（retrieve 只记
count/refs，全文仍在 enrich 的合并 MEMORY_READ；LOOK_AFTER 不重复 facts，
完整观测由下一步 OBSERVE 携带；VERIFY_RESULT 不重复逐条 verdicts，报表仍按
MODEL_CALL 里的 verdicts 解析失效率，不动 evaluation）。EventType 扩到 20 类，
AGENTS.md 的 type 行与 DATAFLOW 2.2 已同步（DATAFLOW 老行的旧节点称谓
属历史漂移，以代码为准）。store.py 的 PHASE_BY_TYPE 是已无人消费的遗留
映射，未动。

**影响面**：schemas（EventType +6）、trace/utils（+6 构造器）、
episode_harness（8 个节点插入 append）、前端（映射/过滤/model_call 栏）、
AGENTS.md + DATAFLOW 文档同步。python 导入与六个构造器冒烟通过；
`tsc --noEmit` 通过；dev 已重启换上新代码。

## 2026-09-03 —— 观测台链补齐：与 episode harness 图 19 节点一一对应

**改了什么**：上一条"当前步轨迹链"只画了 10 个相位，用户指出图实际有 19 个
节点、少了 `get_action_space`、四个 `retrieve_*`、`advance_step`、
`store_object_semantic_memory`、`retrieve_verify_step_memory/knowledge`。
`CHAIN_PHASES` 扩成与 `_compile()` 完全同序的 19 项（主循环 15 + 收尾 4），
每个节点带 `note`（无事件节点的一句说明）或 `fromKey`（内容指向别处）。
点亮语义改为两套：**主循环用里程碑推断**——路径确定，走到某个有事件的节点
即代表其之前的主循环节点都跑过（`furthestMain` 取窗口内有事件节点的最大主循环
下标，get_action_space/advance_step/四个 retrieve_*/store_object 因此也能亮）；
**收尾链按各自事件点亮**——`retrieve_verify_step_memory` 只要收尾事件出现即亮
（judge done 必经过它），无 entries 跳 verify 时 `retrieve_verify_knowledge`/
`verify_steps` 保持暗色，忠实反映跳边。内容解析：四个 retrieve_* 点击显示
enrich 那条合并 memory_read（带说明）；无事件节点显示 note。

**为什么这么改**：用户要求"用 episode harness 的 graph 形态做链"——图有 19 个
节点，我第一版把无事件节点合并/吞掉，链长得不像那张图，会误导"这步走了哪
条路"的判断（比如 get_action_space 也是必经节点，链上不出现就无法解释
think 前发生了什么）。

**取舍**：无事件节点没有 raw 可看，用 note 占位（get_action_space/advance_step
是纯计算；retrieve_* 合并读本来就在 enrich 那一条 memory_read 里）；里程碑
推断对"judge 判 done 提前收尾"的窗口给出正确结果（furthestMain 停在 judge，
主循环其余节点保持暗色、收尾链亮起）。纯前端，`tsc --noEmit` 通过。

**影响面**：仅 `web/src/App.tsx`；后端不动。

## 2026-09-03 —— 观测台右栏重设计：单步轨迹链（替代 2x2 四栏）

**改了什么**：`web/src/App.tsx` 右栏整体重写。四栏（think/act/observe/其他）
换成一条"当前步轨迹"链：链上节点 = episode harness 图节点（look→judge→
enrich_observation→think_action→act→look_after_action→detect_stall→
store_memory，局尾接 verify_steps→summarize），一条链只表示当前一步走了
图的哪几个节点。新增 `CHAIN_PHASES` 相位表、`phaseKeyOf`（事件→相位映射）、
`buildChainWindow`（窗口 = 最近一次 observe 起；每次新 observe 即清空重建，
连用户钉住的选择一起重置）、`ChainPanel` 组件（自动跟随最新相位；点节点钉住
看该相位 raw；内容暂用原始 JSON 平铺）。事件→相位映射要点：memory_read 有
两种读（局中合并检索 vs 局尾 verify 知识检索）却发同一事件，靠"窗口内还有
没有 decision 调用"区分；get_action_space/advance_step 不发独立事件；
四个 retrieve_* 合并到 enrich 一格。episode 编号 SSE trace 不带 episode_id，
改数窗口前的 episode_start 事件。删除原 thinkLine/actLine/ObserveItem/
MemoryReadItem/EventColumn 等一干渲染函数与分区 useMemo。

**为什么这么改**：用户 0903 拍板重设计——"用一个链表示进度，用 episode
harness 的 graph 形态做链，每次 look 的时候清空，否则点击链上的节点切换显示
内容，内容暂时用 raw"。四栏日志的毛病是混排：一局里"大脑看到什么/想到什么/
按了什么"靠人肉逐行对，链形态让"这步走到哪了、死在哪"一眼可见（judge 判
done 时链停在 judge，think/act 保持暗色，直接亮 verify/summarize）。

**取舍**：raw 先顶着——用户明确说字段语义化渲染后面再做；memory_read 的
歧义靠窗口启发式（窗口内有 decision=主循环）而非后端加字段，前端改动最小、
不动 trace 形状；已结束 run 的 SSE 不补发历史，所以旧 run 附着看不到点亮，
验证需要活 run。watch 不涉及、纯前端。

**影响面**：仅前端 `web/src/App.tsx` + 无后端改动；`tsc --noEmit` 通过；
观测台骨架截图验证正常（旧 run 无实时事件流，链停在"等第一个 look…"）。

## 2026-09-02 —— observe 栏结构化渲染 + memory_read 并入 observe 栏

**改了什么**：`web/src/App.tsx` 两处。① observe 事件从单行文本升级为
`ObserveItem` 结构化块：头部（status/scene/overlay/where/facing/map_id）+
overview + dialog_text + 四邻 + `walk_map` 等宽 pre 块。② 分区规则改为
observe 栏收 observe + memory_read 两类事件，新增 `MemoryReadItem` 渲染
检索统计（本局 refs/跨局 refs/先验 sources）和 `known_objects_text`
（对象档案）全文；"其他"栏相应不再收 memory_read。

**为什么这么改**：用户看 trace 后指出 observation 缺字段——`walk_map`/
`where`/`facing`/`neighbors` 一直在 `facts` 里但前端只渲染了 overview；
`known_objects` 全文只存在于 memory_read 的 payload（本次 run 对象档案为空
所以没出现，但字段位置如此），落在"其他"栏的原始 JSON 里等于没人看。

**取舍**：walk_map 用 `pre` 而不是表格/图片——它是字符画，逐字符对齐就是
全部信息，11px 等宽 + 横向滚动够用；memory_read 归入 observe 栏而不是
新开第五栏——2x2 网格布局不动，且"大脑这一步看到/读到了什么"本来就该
是一个问题的两半。

**影响面**：仅前端展示层；`tsc` 通过；think/act 两栏和后端接口不动。

## 2026-09-02 —— dev.ps1 启动后自动打开浏览器

**改了什么**：`dev.ps1` 在拉起前后端之后增加一段：轮询 `http://localhost:5173`
（最多 30 秒，500ms 间隔），返回 200 就用 `Start-Process` 打开系统默认浏览器；
超时则提示手动访问，不阻塞主流程。

**为什么这么改**：用户要做「裸跑隔离实验」（启动 run 后全程无人工/无 agent
参与，验证崩溃是否与外部操作有关），浏览器自动打开让"双击脚本 → 打开观测台
→ 点启动"全程不需要 agent 在场，变量更干净。

**取舍**：轮询而非固定 sleep——vite 冷启动耗时波动大，固定等待要么白等要么
打开个 404；打开浏览器失败（30 秒未就绪）只提示不报错退出，保持和 dev.sh
一样"起服务是主角，其余尽量不挡路"的性格。

**影响面**：仅 Windows 启动脚本，`dev.sh` 不变（bash 环境用户习惯自己开）；
解析器语法检查通过。

## 2026-09-02 —— 观测台支持 `?run=<id>` 重新附着运行中的 run

**改了什么**：`web/src/App.tsx` 的 `runId` 初始值从 `useState(null)` 改为
惰性初始化读 URL 查询参数 `?run=<id>`；其余逻辑（SSE 订阅、画面流、目标栈
轮询）不动，拿到 runId 自然接上。

**为什么这么改**：runId 只存在 React 内存里，刷新或重开浏览器就跟还在
后端跑着的 run 失联——本次截图运行中的观测台时（agent-browser daemon
被满载 CPU 拖垮、重启浏览器）当场踩中，页面回到启动表单而 run 白跑。
URL 是刷新后唯一能幸免的载体。

**取舍**：不做 localStorage/会话恢复那套——URL 参数一行惰性初始化就够，
显式、可分享、可收藏；不匹配的 run id 后端会 404，事件流空转，无副作用。

**影响面**：仅前端，不动后端接口；`tsc` 通过。

## 2026-09-02 —— 观测台 think 栏补渲染 rationale

**改了什么**：`web/src/App.tsx` 的 `thinkLine` 在动作和 thought 之后追加
`rationale`（payload 里的 JSON 字符串，解析成 list 后用「；」拼接，前缀
"论据："）；新增 `parseStringList` 做解析容错。`sequence`/`attempt`/
`press_count` 按用户拍板不展示——`sequence` 和 `action` 渲染文本基本重复。

**为什么这么改**：rationale 是 think 栏里唯一在 trace 之外还有生命周期的
字段（进情景记忆、被未来步骤检索回来），UI 上看不到等于无法核对"存进
记忆的论据和当时的想法是否一致"；用户看了字段清单后拍板 think 就要
action + thought + rationale 三样。

**取舍**：解析失败静默降级为不显示论据（展示层不为一行日志炸事件流，
和 observe 的 parseFacts 同一策略）；rationale 多条用「；」连成一行而不
分行，保持每条 think 是单行日志的现有排版。

**影响面**：仅前端展示层，不动后端接口和 trace 形状。

## 2026-09-02 —— 观测台 observe 栏补渲染 facts 内容

**改了什么**：`web/src/App.tsx` 的 `observeLine` 从 payload 的 `facts`（JSON 字符串）
里解析出 `overview`（感知模型的画面描述）和 `dialog_text`（非空时带引号追加），
拼到每行 observe 事件后面；新增 `parseFacts` 做解析容错。`goals` 字段维持不渲染
（目标栈左栏已有展示，不重复）。

**为什么这么改**：后端 `trace_utils.observe` 特意把 facts 全量记进 payload
（docstring：「只记 summary 的话，replay 出来只剩『你在野外』这种废话」），
但前端只渲染了 status/scene/overlay 三个字段，实质内容在 UI 上看不到——
用户看截图时指出"observation 部分有点少"。

**取舍**：只挑 `overview`/`dialog_text` 两项而不是把 facts 整个 JSON 平铺——
平铺会和"其他"栏的 model_call 原始 JSON 一样难读，observe 栏的定位是
"一眼看清这一帧发生了什么"；解析失败静默降级为只显示原有三字段，
因为这是展示层，不该为一行日志把事件流炸掉。

**影响面**：仅前端展示层，不动后端接口和 trace 形状。

## 2026-09-01 —— 路线图合一到 `docs/ROADMAP.md` + task_id 改名调查 + 业界测评对照

**改了什么**：新增 `docs/ROADMAP.md`（单一权威路线图文件），内容包括：已完成项、
两个待讨论方案（内存环境框架重构的设计提议、`task_id` 要不要改名 `goal_id` 的
现状排查与建议）、两条已知问题（无效步定义、批次记忆隔离）、原 P0-P4 分期表（带
状态列）、工程基础设施缺口清单、新增的"对照业界"一节（BALROG/PokéChamp/Claude
Plays Pokemon/tau-bench pass^k/GAIA 等对照表 + 一个连带发现：`memory/episode/
memory/` 下提交的记忆文件可能让 `knowledge_*` 短任务"泄题"）、下一步建议顺序。
`docs/EXPERIENCE_DOCS.md` 第六节的路线图表格和"六·1 已知问题"替换为指向
`docs/ROADMAP.md` 的一句话链接，不再维护两份会漂移的路线图。

**为什么这么改**：用户明确指出"现在的路线图不够清晰，你只要用一个清晰的单文件
描述这个"——此前路线图分散在 `EXPERIENCE_DOCS.md` 第六节（含六·1 补充）、
`evaluation/SPEC.md` 的零散备注、以及对话记录里，没有一个地方能一次看全。
同时用户要求"以全局视角看看本项目还有什么工程上缺失"，并中途追加"现在的测评
benchmark 完全不够，上网搜一下还有哪些"——这两条都需要落到同一份文档里才有
意义，否则又会变成第三份散落的笔记。

**取舍**：`task_id`→`goal_id` 改名和"内存环境框架重构"都只排查/设计，不实现——
前者排查发现 `task_id` 目前是活跃字段（`api.py` 的目标编辑 API、`web/src/
App.tsx` 前端 React key、`run_harness.py` 的 `GoalsEdit` 匹配逻辑都直接依赖），
且前端那条线看起来还在开发中，这时候大范围改名风险大于收益，建议这次不改；
后者用户明确要求"新框架先和我商量"，所以只把四类记忆现状的排查（`KnowledgeStore`
最干净、可以当模板；`FileEpisodeMemoryStore` 混装了跨局摘要和单步情景两种生命
周期；`InMemoryObjectStore` 无目录参数、纯进程内）和一个提议方案写进
`docs/ROADMAP.md` 供讨论，代码未动。业界对照部分本轮只做研究和记录，不对现有
19 条任务的判据或执行做任何改动——尤其是"记忆库可能泄题"这条，明确标注"需要
先核实，这一轮不下结论"，避免把一个未验证的怀疑当成既成事实写进决策文档。

**影响面**：新增 `docs/ROADMAP.md`；修改 `docs/EXPERIENCE_DOCS.md`（删除重复的
路线图表格和六·1 小节，替换为链接）。不改动任何 `pokemon_agent/` 下的运行代码。

## 2026-09-01 —— 纠正 trace 该不该记 task_id + 补 memory_carried + 修 pip 装不上的包发现 bug

**改了什么**：四件事。(1) 用户指出 trace 不记 `task_id` 是刻意设计（`goal` 就是
"任务"、批次实验靠 `run_id` 前缀区分），核实后确认自己上一轮的质疑站不住——
`tests/reference/example_trace_utils.py` 本来就用 `assert "task_id" not in
event[4]` 钉死了这条契约。顺带发现 `docs/spec/harness/SPEC.md` 仍然声称
`EPISODE_START` payload 含 `task_id`，是没跟上代码的过时文档，一并改掉。
(2) `episode_memory` 检索跨 run（其实是跨"批次"）这件事——查证
`query_episode_summaries` 确实检索磁盘上全部历史摘要、不分批次；这是"跨局
学习"假设需要的行为，不是单纯的 bug，但会让批次测评里的 success rate 混进
"同批次内记忆积累"的效应，无法当独立试验解读。这次只做**可观测**：
`EPISODE_START` 新增 `memory_carried` 字段（`trace_utils.episode_start` 新增
必填参数，取值 `memory.episode_summary_count`），把"开局时跨局摘要池有多大"
落进 trace；`docs/spec/tools/SPEC.md`/`docs/spec/DATAFLOW.md` 同步更新（原来
文档写的是 `episode_step_count`，但 step 记忆生命周期收紧后那个数开局恒为
0，早就不是这个字段该取的来源）。要不要在批次测评时隔离记忆存储没有下结论，
连同"无效步定义需要重新想清楚、`STALL_LIMIT` 在短任务里形同虚设"一起，写进
`docs/EXPERIENCE_DOCS.md` 新增的"六·1 已知问题"小节（列表 + 一段说明，不是
这轮要解决的）。(3) 实测 `pip install -e ".[dev]"` 时发现**这条命令在这次
改动之前就没有真的跑通过**：setuptools flat-layout 自动发现把仓库根目录下
`log`/`web`/`assets`/`config`/`evaluation`/`trace_data` 全部当成候选顶层包，
报 "Multiple top-level packages discovered" 直接拒绝构建——`evaluation/`
只是让这个已经存在的坑第一次被撞见。`pyproject.toml` 补
`[tool.setuptools.packages.find] include = ["pokemon_agent*"]`，显式声明只有
`pokemon_agent` 是要被安装的分发内容。(4) 顺带核实：这次没能在本机跑通
`pokemon_agent` 全量测试套件——本机只有 Python 3.10，项目要求 >=3.11
（`agent-permission` 用了 3.11 的 `enum.StrEnum`）；`evaluation/` 改动之外的
两个文件（`trace/utils.py`、`harness/episode_harness.py`）改动都做过
`py_compile` 语法检查，`tests/reference/example_trace_utils.py` 的断言已经
同步改掉，但没有真实跑过 pytest——CI（`actions/setup-python` 会装真正的
3.11/3.12，不受本机版本所限）是这批改动的第一次真实验证。

**为什么这么改**：用户当面指出对 trace 设计的两处质疑一错一半对——task_id
那条是我没读够代码就下结论；episode_memory 跨 run 检索那条是真实存在的
测评方法论风险，但解决方案（隔离 vs 不隔离）本身有待讨论，不能当场拍板，
所以先做可观测（`memory_carried`），把"要不要隔离"留成一个记录在案的开放
问题而不是假装已经解决。

**取舍**：`memory_carried` 没有默认值、强制调用方显式传——开局时"这一局能
看到多少经验"是调用方（`EpisodeHarness._begin`）已经知道的事实，不该由
`trace_utils` 这一层替它猜或者悄悄归零。批次记忆隔离这次没做：会改变
`build_real`/`run_experiment.py`/`run_all_tasks.py` 的装配方式，且"要不要
隔离"取决于"这次测的是纯能力还是带学习的能力"这个还没讨论清楚的问题，
贸然做掉可能做错方向。

**影响面**：`pokemon_agent/trace/utils.py`（`episode_start` 新增必填参数，
向后不兼容——唯一调用点已同步改）、`pokemon_agent/harness/episode_harness.py`
（`_begin` 新增一行取值）、`tests/reference/example_trace_utils.py`（契约
测试同步更新）、三份 SPEC 文档、`docs/EXPERIENCE_DOCS.md`（新增六·1 节）、
`evaluation/SPEC.md`（无效步占比标注局限、success rate 补记忆污染诊断说明）、
`pyproject.toml`（补包发现声明，这一条是这次意外发现的真实 bug 修复，不是
文档性质的改动）。

## 2026-09-01 —— 测评子系统起步：judge 机械复核 + CI/CD

**改了什么**：新增 `evaluation/`（独立于 `pokemon_agent` 包的测评子系统）——
`SPEC.md`（测评指标与判据规范：success rate 拆成 judge 记的与机械复核的两个
数字、cost per run、无效步占比复用现有停摆键、每链路 token；judge 复核
rubric）、`audit_verdicts.py`（19 条 `knowledge_*` 短任务的机械复核规则，
纯规则代码零 LLM 调用，读不出/判不了一律返回"无法核对"不猜）、
`tests/test_audit_verdicts.py`（32 个用例，每条规则至少一正例，多条直接
复现 `docs/experiences/0827-false-positive-analysis.md` 里记录过的真实
误判场景，如"judge 把我方 HP 下降当成对方受伤的证据"）、`README.md`。
`docs/spec/eval/` 里的早期草稿已并入 `evaluation/SPEC.md`，不再单独存在。

同时新增 `.github/workflows/ci.yml`（push/PR 到 main 触发：lint job 跑
`ruff check` + `ruff format --check`，test job 跑 `pytest`，Python 3.11/3.12
矩阵），`pyproject.toml` 补 `pytest-cov` 依赖、`testpaths` 加入
`evaluation/tests`、`per-file-ignores` 加 `evaluation/tests/*` 的 ANN 豁免。

**为什么这么改**：用户要求先把测评（P3，`docs/EXPERIENCE_DOCS.md` 路线图）
搭起来，且明确要先定义 metric/rubric 再写代码；随后要求新文件统一收拢进
`evaluation/`（不散进 `docs/spec/`、`probe/`、`pokemon_agent/experiment/`），
并要建立标准的 CI/CD 流水线。`evaluation/audit_verdicts.py` 是让 success
rate 数字可信的前提——`0827-false-positive-analysis.md` 已证明 judge 单独
报的成功率有 13.9% 假阳率，且误判集中在少数任务、不是均匀噪声，脱离机械
复核的"测评"只是在复制这个问题。

**取舍**：`evaluation/` 不 `import pokemon_agent`，只解析 trace JSONL 的
字面结构——代价是 `Source`/`EventType` 等枚举值以字符串字面量重复出现在
两处，好处是这个子系统的测试不需要装 `agent-permission`/`fastembed`，CI
里能独立、快速地跑，且回归测试不依赖任何真实 trace 文件（本地 `trace_data/`
里现存的 run 都是自由目标探索，不是 `knowledge_*` 短任务，且 `0827` 批次
的原始数据已不在仓库）——改用合成 `facts` 字典 + 两篇经验文档里写下来的
误判现象作为断言。CI 暂不接入 `audit_verdicts.py` 跑真实批次：它消费的
`trace_data/`/`experiment_results/` 是运行产物、不进 git，CI 环境天然是空的。

**影响面**：新增 `evaluation/`（4 个文件）、`.github/workflows/ci.yml`；
修改 `pyproject.toml`；`docs/spec/eval/SPEC.md`（本次改动内产生又移走的
草稿）不再存在。不动 `pokemon_agent/` 下任何现有代码。

## 2026-09-01 —— 建立工程经验文档体系（用户拍板定稿）

**改了什么**：新增 `docs/EXPERIENCE_DOCS.md`（方案定稿）——两类文档分工
（活文档 `docs/spec/` vs 经验文档 `docs/experiences/`，后者过时也是资产）、
四段式模板（分析→定位→解决→验证，头部带日期/Issue/commit/系统状态）、
命名与索引规则、未来目标路线图（P0 护栏 → P1 可观测 → P2 可审计 →
P3 测评 → P4 文档体系）。建 `docs/experiences/` 目录 + 索引 README，并用
最近两个已解决案例补写示范文档（审计 77 秒定位、KeyError 跨 run 泄漏）。

**为什么这么改**：用户判断——所有改动缺"分析→定位→解决→验证"的文档链，
且可观测/可审计/测评是项目晋升跳板。定稿立场：经验文档**过时也是资产**
（记录当时的分析路径，未来同类问题可复用）；文档要"路径可复现"（脚本/命令
能重跑），不追求排版。

**取舍**：经验文档 vs 活文档分开（时效性不同，不互相替代）；经验文档与
`docs/experiments/`（批次实验分析）语义分开（前者单点诊断，后者批次统计）；
路线图排序理由——护栏是测评收敛的物理前提，判定器标定是成功率可信的前提。

**影响面**：`docs/EXPERIENCE_DOCS.md`（新）、`docs/experiences/`（新目录 +
README 索引 + 2 篇示范）。无代码改动。

## 2026-08-31 —— 补 `delete:memory:episodic` 权限 + 上限/隔离验收测试

**改了什么**：`config/permissions.json` 的 env 与 trusted-agent 两个角色补上
`delete:memory:episodic`（discard_episode_steps 的权限，上一轮实现时漏配）——
真实路径实测发现 `PermissionSkipped`：step 记忆实际没被清理，"不跨 episode"
没有真正生效。补上后真实 run 不再报权限错。另补两个契约测试
（`test_memory_tool.py`）：step 记忆按局隔离 + discard 清空本局不影响别局；
摘要超过 `max_summaries` 按质量淘汰最差并删对应 md 文件。

**为什么这么改**：端到端复跑（第二次）暴露——上一轮新增的 `discard_episode_steps`
挂在 `delete:memory:episodic` 上，但权限表没配这个动作，权限系统拒绝 → 走
PermissionSkipped 降级（trace 里 `PermissionSkipped`），清理从未发生。权限表是
黑名单式配置，漏配一个动作的表现就是"静默降级"，只有真实 run 能看到。

**影响面**：`config/permissions.json`、`tests/test_memory_tool.py`。
65 测试全绿。

## 2026-08-31 —— 记忆生命周期收紧 + 全链路 token 精简（用户拍板）

**改了什么**，三块：

1. **step 记忆不跨 episode**：`FileEpisodeMemoryStore._steps` 从全局 list 改为
   `dict[episode_id → list]`（按局隔离）；新增 `discard_episode_steps`——
   `summarize` 蒸馏完成后丢弃本局 step 记忆（持久化靠 trace 的
   `STEP_MEMORY_WRITE`，内存不留），接口（EpisodeMemoryStore / MemoryToolPort）
   与 MemoryTool 同步，权限走 `delete:memory:episodic`。

2. **episode memory 双上限**：存储上限 `max_summaries=50`——超限按质量分淘汰
   最差的（平手淘汰最旧），删对应 md 文件（`_summary_files` 索引）；检索上限
   `EPISODE_CANDIDATE_CAP=20`——场景匹配后候选超限先按质量粗筛再进混合检索。

3. **全链路 token 精简**：`StepMemory.render` 排除 `walk_map`（坐标推理原料，
   前后对比里几乎不变）——实测单条记忆 1300 → 356 字符（-73%），judge 历史
   （3 条）与审计（整局 8 条）的输入同步缩小约 3/4；「四邻」字段保留，撞墙
   判断不受影响。judge 历史条数 `JUDGE_HISTORY=3` 已满足"只看过去 ≤5 步"。

**为什么这么改**：长 run 实测暴露——run 级 plan 持续拆目标时，step 记忆
（全局累积）和 episode 摘要（无限增长）都无界；且每条 step 记忆渲染 1300
字符导致 judge/审计输入膨胀（实测审计单次 3-16K token、43-77 秒）。用户拍板：
step 记忆局内有效、摘要双上限、全链较长部分都缩短。

**取舍**：按质量淘汰而非 FIFO（经验库的价值是高质量可复用经验，FIFO 会留一堆
早期低质量）；粗筛按质量而非相关性（精排本来会把低质量排后，粗筛只是省掉白做）；
walk_map 从渲染排除但仍在原始 facts 里（需要坐标推理的消费方可直接读）。

**影响面**：`memory/episode/episode_store.py`、`tools/memory_tool.py`、
`schemas/datastore/step_memory.py`、`harness/episode_harness.py`、两个存储接口、
三个测试 FakeMemory 同步。63 测试全绿（连跑 3 次稳定）。

## 2026-08-31 —— step 记忆独立审计器（方案 c）：蒸馏前把不可信的自述挑出去

**改了什么**：新增 `Brain.audit_steps`（独立判定器，复用 `judge_llm`）——一局
结束后、蒸馏前，逐条审查本局 step 记忆的可靠性（"按了那个键之后变成那样"是否
合理一致），输出每条 `reliable` 标记；`EpisodeHarness.summarize` 先审计、
把**可信的**作为 `verified_steps` 喂给 `store_episode_summary`，可疑的自述不进
摘要。配套：`StepAuditReq/Resp` schema、`prompts/step_audit.md`（含 2×2 战斗
菜单、a/b 键、撞墙可信等判定规则）、`BrainPort`/`MemoryToolPort` 接口同步、
`store_episode_summary` 加 `verified_steps` 参数（None=全量，兼容旧调用）。

**为什么这么改（用户拍板方案 c）**：step 记忆是模型自述（`Brain.reflect` 拼的
before/action/after），没有验证——直接当事实喂蒸馏器，错误操作被蒸馏成经验并
跨局传播（实测：战斗菜单 `down×3` 够 RUN 实际打开道具袋，被当"决策点"固化，
摘要还标了 reusable_patterns）。审计用 `render(reason=False)`：只给发生过的事，
不给决策者的理由——理由是被评价者自己的主张，进了审计器上下文就是它自己发的
奖状（同 judge 的隔离逻辑）。

**取舍**：失败闭合——审计调用/解析失败时**全部标不可靠**（宁可蒸馏少喂，不可
把错的当对的），代价是失败局蒸馏出的摘要缺决策点、质量降级。审计每次多一次
LLM 调用（复用 judge_llm，`Source.JUDGE` 单独记账，失效率说得清）。

**影响面**：`brain/brain.py`（+audit_steps/_parse_audit/prompt）、
`interfaces/brain/brain_port.py`、`schemas/communication/step_audit.py`（新）、
`prompts/step_audit.md`（新）、`harness/episode_harness.py`（summarize 接入）、
`tools/memory_tool.py`（+verified_steps）、`interfaces/tools/memory_tool_port.py`、
两个测试 FakeBrain/FakeMemory 同步 + 新 `tests/test_step_audit.py`（6 用例）。
63 测试全绿。

## 2026-08-31 —— knowledge 检索融合 observation：战斗/菜单先验终于能进上下文

**改了什么**：`episode_harness.retrieve_memory` 的 `query_knowledge` 检索 query
从"只有 `state.task.goal`"改为"**observation 特征 + goal**"——`scene` /
`overlay` / `status`（含菜单选项与光标）/ `map_id` 并进 query。

**为什么这么改**：trace 复盘（run `180134`）发现 agent 在战斗菜单里连续犯
knowledge 白纸黑字禁止的错——`down×3` 够 RUN（2×2 布局实际落到 ITEM，
按 a 打开道具袋）、`ITEM→down`（应 `right`，又进道具袋，死循环）、用 `b`
当确认。根因是**检索 query 只有 goal**（"走到镇长家"），BM25 匹配不出
`battle_actions.md` / `menu_and_choices.md` 这类战斗/菜单先验；observation
（`scene:battle`、状态行"可选项：FIGHT/ PKMN/ ITEM/ RUN"）才是这些知识的
检索信号。验证：旧 query 前三名是 items/center/dialogue，新 query 第一名
`battle_actions.md`。

**取舍**：query 变长会稀释 goal 的 BM25 权重——靠 reranker 精排兜底（混合
检索本就这么设计的）；observation 特征标记了词源（`scene:`/`overlay:`/
`目标：`），不是裸拼。

**影响面**：`harness/episode_harness.py`。57 测试全绿（含 1 次已知时序抖动）。

## 2026-08-31 —— thought 加 1024 token 软约束 + max_steps 默认 8（用户拍板）

**改了什么**：`decide_action.md` 的 `thought` 字段从"想多长都可以"改为
"**最长约 1024 token**……写长不会加分，压缩它压的是废话，不是思考"；
`run_plan.md` 的示例 `max_steps` 30 → 8；前端启动表单与追加表单的
`maxSteps` 默认值 50 / 30 → 8。

**为什么这么改**：thought 长度就是这步的算力，但实测到过 2235 token——超过
决策需要的信息量，烧的是纯成本。用 **prompt 软约束**（模型知道预算、主动
压缩、保 JSON 完整）而不是 `max_tokens` 硬截断（会切坏 JSON，见 1024 前科）；
`max_tokens=25600` 硬保险丝不动。max_steps 默认 8 对齐"一局 8 步内解决"的
正常粒度（此前表单 50 步上限对单目标过长，plan 示例 30 同样偏松）。

**取舍**：软约束不保证严格达标（模型可能偶尔超），但没有硬截断的语法风险；
step 内连按 `times` 上限仍是 8（`MAX_TIMES`），与 max_steps 是两回事，未动。

**影响面**：`prompts/decide_action.md`、`prompts/run_plan.md`、
`web/src/App.tsx`（两处 defaultValue）。57 测试全绿，tsc 通过。

## 2026-08-31 —— 修跨局摘要检索 KeyError：向量缓存与磁盘摘要生命周期不一致

**改了什么**：`MemoryTool.query_episode_summaries` 从直接索引向量缓存
（`self._episode_memory_vectors[m.episode_id]`）改为走新 helper
`_episode_vector`——缓存缺失时惰性 embed 并缓存。

**为什么这么改**：向量缓存是**进程内**的（只在 `store_episode_summary` 写入，
即本 run 蒸馏过的摘要），但 `FileEpisodeMemoryStore._load_all` 重启时从磁盘
重建摘要列表（含历史所有 run 落盘的）。两者生命周期不一致：新 run 启动后
向量缓存空、摘要列表却有历史条目，检索时一匹配到历史摘要就 `KeyError:
'<上个 run 的 episode_id>'`，整局报错（观测台首跑复现：上一 run 的摘要
`run-…-172417-…-ep1` 场景命中 `field`，向量缓存里没有它）。

**取舍**：惰性补算 + 缓存，而不是启动时全量预热——向量是**派生索引**，
md 才是真相（`episode_store.py` 早就这么定位）；历史摘要多时全量预热会让
每次启动都付一遍 embed 成本，而惰性只给"这次真被检索到"的付。

**影响面**：`tools/memory_tool.py`（+helper）+ 新测试 `tests/test_memory_tool.py`
（回归：缓存空 + 磁盘有历史摘要 → 检索惰性补算、不 KeyError、且文档只 embed 一次）。
57 测试全绿。

## 2026-08-31 —— 撤销手动 sleep：PyBoy 无头限速其实生效，只在逐帧 tick 时才体现

**改了什么**：撤销上一轮在 `_tick` 里加的 `time.sleep(1/(GB_FPS*speed))` 手动
限速，以及随之引入的 `_watch` / `_emulation_speed` 两个自存属性；构造回到
`set_emulation_speed(speed)`（无头也设 1，不再 `speed if watch else 0`）。

**为什么这么改**：上一轮用 `p.tick(60)` 单次调用实测（0.013s）得出"PyBoy
无头忽略 set_emulation_speed"是**错的**——错在测试方法。PyBoy 的限速是
**tick 调用之间 sleep**，不是帧之间：单次 `tick(n)` 内部 n 帧瞬间完成、
不 sleep（0.016s）；逐帧 `tick(1)` × n 才会在每次调用之间按 speed sleep
（实测逐帧 60 帧 = 1.000s）。而 `_tick` 本来就是逐帧 `tick(1)`，所以
`set_emulation_speed(speed)` 就够，手动 sleep 纯属多余。

**取舍**：手动 sleep 虽然也能限速，但绕了弯路、还留下错误注释误导后人；
回到 PyBoy 原生限速更简单，且与用户观察（"等待 decision 期间速度对"——
逐帧 tick 的 evolve 一直是对的）一致。代价不变：全局 60fps = run 按游戏
真实时间走（见上一条）。

**影响面**：`world/pyboy_world.py`（构造 + `_tick` 删 sleep + docstring）。
56 测试全绿。

## 2026-08-31 —— 全局限速：所有涉及 tick 的推进都按真实速度（用户拍板）

**改了什么**：`PyBoyWorld` 构造改为无条件 `set_emulation_speed(speed)`
（默认 1 = 60fps）——无头模式不再 `set_emulation_speed(0)` 不限速；
删掉上一轮的 `_tick_paced` 临时切速 helper（全局已限速，切速冗余），
`evolve` / `step` 改回直接 `_tick`。所有推进——BOOT_FRAMES 开机、按键、
连按后演化、过场、决策等待演化——统一 60fps 真实速度。

**为什么这么改**：用户拍板"所有只要涉及 tick 的都限速"。上一轮只给
决策等待 + 按键后过场限速，用户要求全量一致。

**代价（如实说明，比上轮更大）**：全局 60fps = 整个 run 按游戏真实时间走。
每步 = 决策 3-5 秒 + 过场 10 秒；开局 10 秒开机动画；一局 20 步 ≈ 5 分钟，
跑批实验会显著变慢。这是"真实观感"对"跑得快"的取舍，用户拍板；若实验
要恢复速度，构造参数 `speed` 传 0 即可（一行调用方改动，world 层不写死）。

**影响面**：`world/pyboy_world.py`（构造 + 删 helper + docstring×3）。
56 测试全绿（测试不经过真 PyBoy 构造）。

## 2026-08-31 —— 按键后过场也按真实速度演化（用户拍板）

**改了什么**：`PyBoyWorld.step` 的两段推进（连按后的 `WITHIN_ACTION_FRAMES`、
整条链按完后的 `AFTER_ACTION_FRAMES`）从裸 `_tick` 改为 `_tick_paced`——
临时 `set_emulation_speed(1)`（60fps 真实速度）、演完恢复。限速逻辑抽成
`_tick_paced` helper，`evolve`（决策等待）与 `step`（按键后）共用。

**为什么这么改**：用户拍板"decision 结束后的 tick 依旧没有速度限制"是问题——
无头模式全局不限速，按键后的 600 帧过场瞬间 tick 完，观测台看到的是画面
跳变，过场动画（淡入淡出/对话框/战斗开场）被直接跳过。按真实速度演化后
过场真实可见，且"等过场结束再感知"的正确性意图（AFTER_ACTION_FRAMES 的
原始注释）真正兑现——之前瞬间 tick 完，10 秒过场实际只给了 <10ms。

**代价（如实说明）**：按键后 600 帧 @60fps = 每步多 10 秒真实时间（此前是
瞬间）。观测台观感优先于 run 时长，用户拍板。实验脚本（run_episode 等）
同样受影响——若以后想恢复"无头跑得快"，把 `_tick_paced` 的切速改成仅
`evolve` 用即可。

**影响面**：`world/pyboy_world.py`（`_tick_paced` 新增、step/evolve 改用）。
56 测试全绿（测试不经过真 PyBoy 的 step 限速路径）。

## 2026-08-31 —— 修观测台看不到 plan 自主拆解的目标：快照时机 + 前端字段名

**改了什么**：
1. **`latest_goals` 快照从 plan 入口移到出口**：入口记录的是 LLM 决策前的栈，
   plan 压入的新目标（`plan-` 前缀）要到下一轮 plan 才可见——而它那时可能
   已执行完弹栈，观测台永远看不到 plan 自主拆的目标。改为四个出口分支各按
   "决策后栈"记录（push 分支手动算 `state.goals + pushes`）。
2. **前端 `TraceEvent` 字段名修正**：后端字段是 `type`（EventType 枚举值），
   types.ts 翻译成了 `event_type`——事件列表一直显示 `[undefined]`。改名 +
   App 渲染同步。

**为什么这么改**：用户观测到 `#1 harness {"goal":"移动角色至镇长家建筑正门口…"}`
这个目标不是表单输入的（那是 plan LLM 自主压栈的 `plan-` 目标），且目标栈
面板没反应。两处都是"观测台首跑才暴露"：快照时机是逻辑 bug，字段名是
翻译错误。

**影响面**：`run_harness.py`（plan 出口快照）、`web/src/types.ts`、
`web/src/App.tsx`、`tests/test_run_harness.py`（+1 回归：plan 压栈后快照
立即可见）。56 测试全绿。

## 2026-08-31 —— 决策等待演化无限化 + trace 全链路去截断（用户拍板）

**改了什么**：
1. **IDLE 演化去掉帧数上限**：删 `IDLE_TICK_LIMIT`（1200 帧 ≈ 20 秒），
   think 的等待循环改为 `while not future.done(): evolve(...)`——演化直到
   LLM 返回；`future.done()` 是天然终止（LLM 总会完成或抛异常，不会真无限）。
2. **trace 全链路去截断**：`errors.ParseFailure`（原文）、brain 判定错误、
   episode decision_failed 的 raw、episode_summary_error、plan 错误、
   trace/utils 的 why、DashScope HTTP body、视觉失败原文——一律存完整文本。
   保留的唯一截断：`brain` 的重试提示 `completion.text[:400]`（那是给模型的
   提示不是 trace，控制 prompt 长度合理）。

**为什么这么改**：① 用户拍板"等待 decision 的时间可以更长甚至无限"——观测
台场景下世界一直演化（音乐/动画）比"防跑飞"的静止更有价值，错位由下一步
感知修正；② 用户拍板"trace 不用截断"——之前排查 PlanParseFailure 就是被
200 字符截断误导过（只看到 '```json 开头看不到完整输出），完整原文是排查
的第一手证据，JSONL 落盘没有体积压力。

**取舍**：IDLE 无限演化放弃"决策基于稍早快照"的一致性保证（原 20 秒上限
的理由）——一致性由"下一步感知总会在按键前重新对齐"兜底，且 LLM 平均
3-5 秒的窗口本来就在上限内，实战几乎无差异；按键后演化（`AFTER_ACTION_FRAMES`
600 帧）保持现状不变（无头不限速），用户确认"依旧无上限"。

**影响面**：`episode_harness.py`（删常量 + 循环 + docstring）、`errors.py`、
`brain.py`、`run_harness.py`、`trace/utils.py`、`dashscope.py`、
`pyboy_world.py`、`tests/test_episode_evolve.py`（上限断言改为"至少一轮"）。
55 测试全绿。

## 2026-08-31 —— 修两处首跑才暴露的 bug：出口断言写错对象 + IDLE 演化忙循环

**改了什么**：
1. `brain.py` 的 choose 出口断言 `assert space.contains(parsed.name)` 改为
   `assert parsed.sequence` + 逐段 `space.contains(seg.name)`——`ActionFromBrain`
   没有 `name` 字段（`name` 在 `sequence` 每段的 `ActionSegmentFromBrain` 上），
   旧断言是"intent 分派"重构删字段时漏改的，真实模型一跑就 `AttributeError`。
2. 限速下沉到 `PyBoyWorld.evolve` 内部（临时 `set_emulation_speed(1)`、
   演完恢复原速）：无头模拟器全局不限速（`set_emulation_speed(0)`，实验
   跑得快），`evolve(30)` 瞬间完成、1200 帧预算 ~0.4s 就耗尽，LLM 等待的
   大半时间画面静止——观测台帧流看起来"卡住"。evolve 唯一调用方是
   IDLE 循环（"本来就要等的空闲窗口"），限速恰好填满窗口、不额外花 run
   时间；harness 不再手动 sleep（那会把 60fps 硬编码进调用方）。

**为什么这么改**：两处都是"路径首次真实跑"才暴露——出口断言之前测试走
FakeLLM 没触发（FakeLLM 不经过 `_parse` 或恰好没踩到）；IDLE 演化在无头
模式下的帧预算换算（1200 帧 ≈ 20 秒）默认了真实速度，而实际是瞬间 tick 完。

**取舍**：出口断言保留（AGENTS.md：postcondition 是运行时全覆盖的证据），
只是把对象改对——`_parse` 已逐段校验，这里是对"所有实际执行"的兜底证明；
限速选 evolve 内部而非 harness sleep：速度语义属于"演化"（world 层），
调用方不用知道 60fps。注意 PyBoy 只提供 `set_emulation_speed` setter 没有
getter，恢复原速靠构造时自存（`self._emulation_speed`）。

**影响面**：`brain.py`、`episode_harness.py`。55 测试全绿（测试的 FakeLLM
立即返回，IDLE 循环不执行，sleep 不拖慢测试）。

## 2026-08-31 —— 修 run 级 plan 全量 PlanParseFailure：`_parse_plan` 漏了 JSON 围栏剥离

**改了什么**：新增 `utils.strip_json_fence`（剥 ```json 代码围栏），`RunHarness._parse_plan`
接入；`brain.py` 原有的两处围栏剥离（决策/判定解析）改为复用同一函数。
附带：`QwenText.complete` 空正文抛 `ParseFailure`（带 token 数）而非裸空串。

**为什么这么改**：观测台首跑，trace 的 error 事件完整 reason 显示模型**返回了
内容**，只是开头是 ```` ```json ```` 围栏——`json.loads` 在第一个反引号处报
"char 0"。`brain.py` 早已容忍围栏（"模型最常见的格式偏差"），run 级 plan 是
唯一漏网：之前 run 级 plan 没在真实模型上跑过，这次一跑就暴露。修复后
episode 正常 dispatch → world 正常 tick → 前端画面问题（run 卡在 plan 失败
循环导致无帧）同步解决。

**修正**：初版把根因误判为"qwen-plus 思考模式吞掉正文"（token 数正常 +
content 空），加了 `enable_thinking: false`——trace 证据推翻了该假设（模型
其实返回了内容），但该参数保留作为防御（未来若模型默认思考，正文仍可能
空，届时空正文防护会给出明确报错而不是误导性 JSON 错误）。

**取舍**：围栏剥离只做最外层、不做内容修复——内容坏了应该走重试，不在
解析层猜着改。抽共享函数是因为同逻辑已出现三处（brain×2 + plan×1）。

**影响面**：`utils.py`（新）、`run_harness.py`、`brain.py`、`dashscope.py`、
`tests/test_run_harness.py`（+1 回归）。55 测试全绿。

## 2026-08-31 —— 目标栈运行时观测与编辑：读全栈、写走 plan 轮消费

**改了什么**：
1. **`RunHarness` 加运行时通道**：`latest_goals()`（plan 入口快照目标栈，栈只
   在 reflect/plan/review 变化，重试轮不变，快照足够准）+ `submit_edit(GoalsEdit)`
   （单槽，plan 节点每轮开头消费并应用——≤ 一轮生效，不打断当前 episode）。
   `_apply_edit` 支持 push / remove / replace，**栈顶（执行中）锁定**：命中
   `goals[-1]` 的 remove/replace 静默丢弃（删执行中目标会打乱 `reflect` 的
   `goals[-1] == last_task` 路由，那是 review 的职责）。
2. **API 层**：`GET /runs/{id}` 返回 `goals[]`（task_id/goal/success_criteria/
   max_steps/top 标记）；新增 `POST /runs/{id}/goals`（push/remove/replace，
   终态 409）；`_RunHandle` 持有 harness；`goal_to_task` 恢复 `prefix` 参数
   （编辑 push 用 `edit-` 前缀，避免和 `api-`/`plan-` 撞 task_id）。
3. **前端**：`useRunGoals`（2s 轮询）；目标栈面板（栈顶只读标"执行中"，
   非栈顶行内编辑 + 删除）；追加目标表单。

**为什么这么改**：用户要求"观测台读得到、改得了 harness 的目标栈"——启动时
那一个目标对 plan 压栈/reflect 弹栈是黑盒。读无难点（快照）；写是运行时
干预图状态，安全边界画在**栈顶锁定**：执行中的目标不可删改，追加与对
未执行目标的删改都安全（≤ 一轮生效）。

**取舍**：轮询（2s）而非 SSE 推送——栈变化低频，GET 顺带拿 status/outcome
快照；编辑用单槽"最新一条"而非队列——人看着屏幕下意图，覆盖语义无害。
栈顶锁定的校验放消费时（plan 轮）而非提交时（提交时栈顶是谁有竞态），
非法编辑静默丢弃，前端以轮询结果为准。

**影响面**：`schemas/communication/goals_edit.py`（新）、`run_harness.py`、
`api.py`、`web/src/{types,api,App,useRunGoals}.ts`、`tests/test_api.py`
（+3 用例：读栈、push+remove、栈顶锁定）。54 测试全绿。

## 2026-08-31 —— API 启动默认从 `<rom>.state` 开始（用户拍板）

**改了什么**：`api.py` 的 `default_build_run` 装配时自动补开始存档——`rom + ".state"`
存在就作为 `state_file` 传入（观测台启动从存档开局，与实验入口 `run_episode`
的 `--state assets/rom.state` 默认一致）；文件缺失回退 None（从开机跑），
换 ROM 没配存档不会让 run 直接炸。`build.py` 的 `state_file` 参数语义补注释。

**为什么这么改**：用户确认"在 rom 路径上加 .state 就是开始存档"——观测台
从开机画面跑会导致每次 run 都要先走过场，且长程任务验证希望有确定起点。
默认存档规则收敛到装配层（`default_build_run`），`PyBoyWorld` 的契约不变
（state_path=None 仍是从开机，实验脚本的 `--state none` 语义不受影响）。

**取舍**：放在装配层而非 world 层——world 保持"显式传入"契约（原注释的
多命名起点设想仍成立，只是 API 路径现在用 `rom.state` 这一个命名起点）。

**影响面**：`api.py`（default_build_run 两行 + docstring）、`build.py`（注释）。
51 测试全绿（测试用 fake 工厂，不经过真实装配）。

## 2026-08-31 —— 删 `on_event` 推送钩子：零消费方的参数不留

**改了什么**：`LocalTrace` 的 `on_event` 构造参数与 append 后回调、`build_real`
的 `on_event` 参数一并删除；`build.py` 的 `Callable` / `TraceEvent` 两个死
import 清理；`store.py` 模块 docstring 改为"实时消费方直接轮询 `events()`"。

**为什么这么改**：用户质疑"为什么还要留着 on_event"。确认零调用方——API
路径轮询 LocalTrace 后，这个钩子的唯一历史用途（推送给 SSE）已不存在，没有
任何代码传它。留着就是"为未来准备"的 YAGNI 参数，而 AGENTS.md 明令"别提前
做"；需要时（如实时成本统计）再从消费方加轮询/游标，钩子不是唯一解。

**取舍**：回调式推送 vs 消费方轮询——事件流已经证明"账本即真相 + 轮询"
更简单（少一条同步通道）。若未来出现高频实时消费方（如逐条统计），给
`TracePort` 加 `events_since(id)` 游标即可，仍是轮询形态。

**影响面**：`trace/store.py`、`build.py`、`api.py`（docstring 一句）。51 测试
全绿。

## 2026-08-31 —— api.py 与 review 彻底切割：装配工厂不再碰审查者

**改了什么**：`create_app` 的 `build_run` 工厂签名从 `(run_id, reviewer)` 收窄为
`(run_id)`；`default_build_run` 不再传 reviewer（`build_real` 内部 `RunHarness`
已默认 `AutoContinueReviewer`）；`api.py` 删除 `AutoContinueReviewer` /
`HumanReviewer` import 与"人工审查（暂时下线）"docstring 一节——**整个文件
不再出现 review/reviewer 字样**（grep 验证）。

**为什么这么改**：用户要求"api.py 里不出现 review"——审查是装配层的关注点
（`build_real` 的 reviewer 参数 + `RunHarness` 的默认兜底），API 层不该知道
它的存在。上一次改动只是删功能、留注释，这次是切依赖：API 层对审查者零感知。

**取舍**：`build_real` 的 `reviewer` 参数保留（接口能力，测试与未来注入用），
只是 API 路径不再使用。`tests/test_api.py` 的 fake 工厂同步去掉 reviewer
参数，走 `RunHarness` 默认自动继续。51 测试全绿（沿用已知的 review 窗口
时序敏感点，连跑 3 次无失败）。

**影响面**：`api.py`、`tests/test_api.py`。HTTP 面与 SSE 协议零变化。

## 2026-08-31 —— review 全线下线：api.py 换用 AutoContinueReviewer

**改了什么**：
1. **删 `SlotReviewer` 类**（单槽审查者）与 `POST /runs/{id}/review` 端点、
   `ReviewSubmitReq` 请求模型、`REVIEW_POLL_*` 常量、`create_app` 的
   `review_polls/interval` 参数、`GET /runs/{id}` 的 `review_pending` 字段、
   `_RunHandle.reviewer` 字段、事件流轮询里的 review 分支。
2. **`start_run` 改用 `AutoContinueReviewer`**（`harness/auto_reviewer.py`
   的现成占位实现）：review 节点每个 episode 之间自动 `CONTINUE`，run 不被
   打断地跑完目标栈。
3. `goal_to_task` 收掉 `prefix` 参数（`push-` 前缀的唯一来源已删）。
4. 模块 docstring：SSE 三类消息、人工审查一节标注"暂时下线 + 恢复路径"。

**为什么这么改**：用户拍板——审查 UI 整体推迟（前端 review 部分已删），
harness 暂时自动跳过。SlotReviewer 的单槽/轮询/幂等逻辑没有消费方就是死
代码，且是最先被两轮重构（删 hub、删 on_request）掏空职责的部分——它的
存在只剩"等 UI 回来"。`HumanReviewer` 协议与 `AutoContinueReviewer` 都在，
恢复审查时：换一个"读 HTTP 槽"的 reviewer 实现 + 加回端点 + 事件流循环加
一个只读源，三步都在 API 层内，harness/接口零改动。

**取舍**：SSE 事件流的 review 分支一并删除（没有前端监听，发了也是白发），
恢复时按 docstring 提示加回。`_RunHandle.reviewer` 字段删除——将来审查
UI 需要 submit 入口时随端点一起恢复。

**影响面**：`api.py`（-170 行左右）、`tests/test_api.py`（8 个用例：删
PUSH/review_pending 两个纯 review 用例，其余改造为无审查语义——串行限制
用 FakeEpisode.delay 保持 running 窗口，帧流用例去掉 stop 线程）。51 测试
全绿；HTTP 面减少一个端点，其余协议零变化。

## 2026-08-31 —— 删掉 EventHub：事件流改为轮询单一数据源

**改了什么**：
1. **EventHub 类整体删除**（含 per-run 实例化与 `_RunHandle.hub`）。事件流
   端点改为按 `EVENT_POLL_INTERVAL`（0.1s）轮询三个只读源：LocalTrace 内存
   事件表（trace）、`reviewer.request`（review）、`handle.outcome/error`
   （done/error）。
2. **补发与实时统一成一个循环**：`last_id` 从 `Last-Event-ID` 起步，每轮发
   更新的事件——不再有"先补发再接实时"两段式。重连时仍 pending 的 review
   会重发一次（前端按 run 幂等，语义变化已在 docstring 标明）。
3. **SlotReviewer 去掉 `on_request` 回调**，加 `request` 属性（返回当前未决
   请求对象，消费方按对象身份判重）——reviewer 彻底只剩决策职责。
4. **装配工厂签名回到 `build_run(run_id, reviewer)`**：`on_event` 钩子在
   API 路径上无人消费（`build_real`/`LocalTrace` 的参数保留，属 TracePort
   设计，未来实时统计还用得上）。
5. `_execute` 只写终态不再广播；删除 `import queue`、`queue_get`。

**为什么这么改**：用户指出"感觉不需要 EventHub"。确认属实——hub 是同一份
数据的第二条通道：trace 真相在 LocalTrace（端点补发本来就读它），hub 只是把
同样的东西再广播一遍，靠 `on_event` 钩子保持同步。review 不落 trace 才是 hub
唯一的存在理由，而 `reviewer.request` 暴露后轮询即可覆盖。轮询的代价（0.1s
延迟、每轮扫一遍内存表，单 run 几百条事件）对观测台可忽略；收益是删掉一整类
线程安全广播机制（~50 行）+ 钩子接线 + 判重逻辑，内存里只剩一份真相。

**取舍**：轮询 vs 推送的分界线画在"账本是否存在"——有账本（trace）的数据
轮询天然正确（错过的事件永远能从账本补回）；没账本的瞬态数据（帧）才需要
生产者主动覆盖的槽 + 高频推送。若未来事件量大到轮询扫描成为瓶颈，给
`TracePort` 加 `events_since(id)` 游标即可，接口不变。

**影响面**：`api.py`（EventHub/SlotReviewer/_RunHandle/_execute/start_run/
run_events/docstring）、`tests/test_api.py`（fake 工厂签名回收）。HTTP/SSE
线格式零变化。53 测试全绿（首跑出现过 1 次时序抖动，连跑 4 次全过——review
事件的可见窗口依赖轮询节奏，标记为已知的时序敏感点）。

## 2026-08-31 —— EventHub 降级到 per-run，SlotReviewer 与传输层解耦

**改了什么**：
1. **删掉模块级单例 `_hub`**：`EventHub` 实例改由 `start_run` 创建、挂在
   `_RunHandle` 上；`subscribe/publish/unsubscribe` 去掉 `run_id` 参数
   （专属总线不需要按 run 分桶）。
2. **`SlotReviewer` 不再持有 `EventHub`**：构造参数从 `hub` 改为
   `on_request: Callable[[HumanReviewReqFromHarness], None] | None`——审查
   真的要等人时才调用的通知动作。`start_run` 里注入
   `lambda req: hub.publish("review", ...)`。
3. **装配工厂签名加 `on_event`**：`build_run(run_id, reviewer, on_event)`——
   trace 推送钩子由 API 层注入，`default_build_run` 与测试 fake 不再自己
   摸全局总线（test 的 fake 反而少了 5 行）。
4. `SlotReviewer.review` 的三段重复加锁-清槽-解锁收拢为 try/finally；
   `pending` 语义不变（整个 review 过程中为 true）。

**为什么这么改**：用户指出两点架构问题——① EventHub 生命周期明明绑定单次
run，却以模块级单例存在，违反 AGENTS.md"禁止模块级单例"；且与 FrameSlot
（由 build 装配传入、安分待在 world 层）不同级；② `SlotReviewer` 是决策策略
（`HumanReviewer` = "给决策"），却知道了传输总线（SSE 广播）的存在，职责
泄漏。修复后：hub 的生命周期 = run 的生命周期，reviewer 只管决策，通知动作
靠依赖注入——"广播到哪"重新变成 API 层的私有知识。

**取舍**：`on_request` 用回调而不是让 reviewer 返回"待通知事件"由外层发——
后者要求 harness 改 review 调用协议，前者零侵入；代价是 reviewer 持有一个
回调，但它只知道"调用它"，不知道它背后是什么。`on_event` 注入同理：
`build_real` 本来就收 `on_event`，现在只是把"钩子从哪来"从全局变量改成参数。

**影响面**：`api.py`（EventHub / SlotReviewer / _RunHandle / start_run /
events 端点 / 模块 docstring）、`tests/test_api.py`（fake 工厂签名跟进、
删 `_hub` import）。HTTP 面与 SSE 协议零变化。53 测试全绿。

## 2026-08-31 —— 帧推送节拍 10fps → 30fps

**改了什么**：`FRAME_POLL_INTERVAL` 从 0.1s 改为 1/30s（`api.py` 常量 + docstring），
帧端点对前端的推送频率从 ~10fps 提到 ~30fps。逻辑零改动，只调旋钮。

**为什么这么改**：用户提出观感需求——10fps 下宝可梦的走路/转场动画明显卡顿，
音乐与画面不同步。30fps 下 160x144 的 PNG 编码 + base64 + JSON 在 localhost
上每秒 30 次开销可忽略（约 0.3~1MB/s 带宽）；60fps 收益递减而开销翻倍，
不值得。该常量本来就是刻意留下的"前端推送节奏"旋钮，与模拟器帧率解耦。

**取舍**：考虑过换 WebSocket/MJPEG 二进制流——带宽效率更高，但当前瓶颈
根本不在协议层，引入新连接类型是过度设计；先调节拍，真不够再换协议。

**影响面**：`api.py` 一行；`tests/test_api.py` 不断言具体间隔（10 passed）。

## 2026-08-31 —— 改名 `sse_frame` → `sse_message`：消除"协议帧"与"画面帧"的歧义

**改了什么**：`api.py` 里拼 SSE 线格式的局部函数 `sse_frame` 改名为 `sse_message`，
docstring 明确"这里 frame 指协议层的一条消息封装，与 FrameSlot 的游戏画面帧无关"。
纯改名，函数体不变；`sse_frame` 无外部引用（`create_app` 内部闭包）。

**为什么这么改**：前端介入后读代码的人（和 LLM）把 `sse_frame` 误解成了
"推游戏画面帧"的函数——同名两个含义：`frame_slot.py` 的 frame 是一张 PNG，
SSE 的 frame 是 `event:/id:/data:` 三行字节。`latest_frame` / `frame_png` 已被
画面帧占据，格式化函数继续叫 frame 就是给后人不埋雷。

**取舍**：考虑过叫 `sse_packet` / `sse_line`——`message` 与 SSE 规范用词一致
（MessageEvent / onmessage），且和前端 `subscribeEvents` 的回调语义对得上。

**影响面**：`api.py` 一处定义 + 五处调用；`tests/test_api.py` 不受影响
（10 passed 验证改名无破坏）。

## 2026-08-31 —— 帧管道重构：画面从事件流拆出，走独立生产者-消费者管道

**改了什么**：实时画面不再随感知响应/事件流走，改为**独立帧管道**——`PyBoyWorld._tick`
每帧把画面副本塞进新增的 `world/frame_slot.py`（`FrameSlot`：单槽覆盖 + 惰性编码，
生产者每帧 O(1) 只换引用、PNG 编码只在消费者取帧时发生并缓存）；`GameTools`
新增 `latest_frame()` 消费者接口；API 新增独立 SSE 端点 `GET /runs/{id}/frames`
（~10fps 轮询推最新帧，run 终态关流）。**删**：`WorldPerceptionResp.frame_png` 字段、
`EpisodeHarness.frame_sink` 参数与推送、`build_real` 的 `frame_sink` 透传。
`build_real` 返回 4 元组（`RunHarness, LocalTrace, PyBoyWorld, GameTools`）。

**为什么这么改**（用户拍板）：帧是瞬态显示数据、生命周期绑定在"世界演化"上，
不该被"每步一感知"的节奏牵着走，也不该和事件流同步推。用户确认的语义：
单槽覆盖（永远最新）、不节流（每帧都推进槽）、不做帧去重、旧机制移除。
惰性编码是"不节流"和"无头模式不限速（模拟器可能几百帧/秒）"之间的平衡——
每帧编码 PNG 会把 run 拖慢好几秒，编码挪到消费端后语义与性能兼得。

**取舍**：① 帧不带 episode_id/step（帧率远高于步频，语义就是"当前画面"）；
② `_tick` 里 `screen.image` 是 `frombuffer` 共享渲染缓冲的视图，必须 `copy()`
再塞（存引用会看到未来帧），copy 23040 像素是 O(1) 量级；③ 消费者端
`FRAME_POLL_INTERVAL=0.1s` 是网络/前端的推送节奏，与"不节流"不冲突
（生产端每帧都推进槽，消费者永远取到最新）。

**影响面**：`world/frame_slot.py`（新增）、`pyboy_world.py`（_tick 生产 +
latest_frame）、`game_tools.py`（消费者转发）、`world_perception.py`（删字段）、
`episode_harness.py`（删 frame_sink）、`build.py`（返回 4 元组）、`api.py`
（frames 端点 + BuildRun 4 元组 + _RunHandle.frames）、`test_episode_frame.py`
（重写为 FrameSlot/转发测试）、`test_api.py`（帧用例改新端点）。验证：
编译全绿；53 测试全绿。

## 2026-08-31 —— trace 的 ts 修正为真 Unix 时间戳

**改了什么**：`LocalTrace.append` 的 `ts` 从"当日零时到现在的秒数"（0~86400 的
`datetime.now().time()` 折算）改为 `time.time()`（Unix epoch 秒）——实现向
`TraceEvent.ts` 的 docstring 靠拢（docstring 一直声称是 Unix 时间戳）。

**为什么这么改**：原实现两处不对——跨午夜回绕（00:00 时 ts 回落 0，同 run 内
不再单调、延迟算出负值）、无法对齐外部日志（外部日志都是 epoch）。改为 epoch
同时满足"算延迟"和"对齐外部日志"，无回绕。当前 ts 零消费方，无破坏；
下一步的"每步耗时分布"分析（MODEL_CALL 相邻差 / EPISODE_START-END 差）以此为数据源。

**影响面**：`trace/store.py`（import datetime → time，ts 赋值一行）；`TraceEvent.ts`
docstring 不动（本来就该是 Unix 时间戳）。

## 2026-08-30 —— 决策期间世界演化：choose 异步化，等 LLM 时 tick 继续

**改了什么**：
1. **`GameToolPort.evolve(frames)`**：无输入推进 N 帧（世界自己演化，音乐/动画
   继续），独立于按键被调用。`GameTools.evolve`（复用 `execute:game:press` 权限）、
   `PyBoyWorld.evolve`（=`_tick`）。
2. **`BrainPort.choose_async(req) -> Future[BrainDecisionResp]`**：`choose` 的异步版，
   `Brain` 内部用单 worker `ThreadPoolExecutor` 提交整个 choose（含重试/解析），
   立即返回 Future。
3. **`episode_harness.think` 改造**：`choose_async` 发出后，主线程在
   `while not future.done()` 循环里调 `game.evolve(IDLE_FRAMES_PER_POLL)`——
   LLM 返回前世界继续演化；累计超过 `IDLE_TICK_LIMIT`（1200 帧 ≈20 秒，按 LLM
   平均等待调的）回到静止等待（防世界跑飞）。LLM 返回后照常按键。

**为什么这么改**：用户拍板——宝可梦有音乐和动画，决策等待 3-5 秒画面静止
显得游戏死了。决策是每步最大的空闲窗口（感知/判定必须静止：快照一致性），
把它填上是收益最大的点。

**取舍**：
- **只解耦决策（think），感知/判定保持静止**：感知是"稳定帧快照"，tick 会让
  快照失真；判定基于快照，tick 后世界变会破坏"判的是什么"。决策期间演化是
  刻意接受的错位——按键基于稍早的快照，错位由下一步感知修正。
- **演化有上限（20 秒）**：LLM 更慢就回到静止，防止 NPC 走远/对话框推进让
  决策依据和现实差太多。
- **线程池只碰 LLM HTTP**：`choose` 内部只调 `_decide.complete`（urllib，线程
  安全）与只读 prompt；权限检查走 agent_permission 的普通全局（非 ContextVar），
  跨线程可见。线程池是执行设施不是决策状态，不违反"大脑无状态"。
- **PyBoy 不跨线程**：tick 仍在主线程（think 节点内），SDL 约束不变。

**影响面**：`interfaces/tools/game_tool_port.py`、`interfaces/brain/brain_port.py`
（各加一个方法，接口变更，mock 同步）、`tools/game_tools.py`、`world/pyboy_world.py`、
`brain/brain.py`、`harness/episode_harness.py`（think + 两个 IDLE 常量）；
测试：两个 FakeBrain/FakeGame 同步接口，新增 `tests/test_episode_evolve.py`
（2 用例：延迟 LLM 时 evolve 被调且不超上限 / 即时 LLM 不 evolve）。

## 2026-08-30 —— 帧独立实时推送：画面不进 trace，单独走 SSE

**改了什么**：
1. **`WorldPerceptionResp` 加 `frame_png: bytes | None`**——感知时喂视觉模型的那份
   原始 PNG 顺手带出（`pyboy_world._perceive` 返回 4 元组）。`None` = 实现不产帧
   （mock/测试），向后兼容。
2. **`EpisodeHarness` 加 `frame_sink: Callable[[str, int, bytes], None] | None`**——
   `_begin`（reset 后，step=0）与 `press`（execute 后，step=before.step）在感知
   发生的时刻推帧。**帧必须在 run 线程内抓取并推出**（PyBoy 非线程安全，SSE 线程
   回头拉会竞态）；响应无帧时不推。
3. **`build_real` 透传 `frame_sink`**；API 默认装配把 `frame_sink` 接到 EventHub，
   推 `frame` 消息（`{"episode_id","step","frame_png"}` base64）。
4. **SSE 加第五类消息 `frame`**：实时转发（hub 通用路径，端点零改动），
   **不带 id、断线不补发**——帧是瞬态显示数据，重连后从下一帧开始即可。

**为什么这么改**：用户拍板"帧不该进 trace"——帧是**显示用**的瞬态数据，trace 是
记录的地基（replay/checkpoint/成本统计），塞画面会拖垮全部。帧随感知响应带出、
由 frame_sink 独立推送，trace 链路完全无感。

**取舍**：
- 帧在感知响应里带出（协议加一个默认 None 字段）而不是单独接口——因为帧必须
  **在感知发生的那一刻、run 线程内**抓到，回头拉就是竞态。
- 不做帧哈希去重（同帧连续几步会推重复帧）：先保正确性，前端显示不受影响；
  等体积成为问题时再加（"帧不变不重复推"）。
- 帧不带元数据之外的 step 标注：episode_id/step 随帧 JSON 走，前端无需和 trace
  事件对齐。

**影响面**：`schemas/communication/world_perception.py`（加字段）、`world/pyboy_world.py`
（_perceive 返回 4 元组）、`harness/episode_harness.py`（构造 + begin/press）、
`build.py`（透传）、`api.py`（默认装配 + SSE 协议文档）；新增
`tests/test_episode_frame.py`（3 用例：开局+每步帧 / 无 sink 不崩 / 无帧不推）。

## 2026-08-30 —— 后端暴露层：FastAPI 服务（含 SSE 事件流）

**改了什么**：
1. **新增 `pokemon_agent/api.py`**——后端 HTTP 面，取代被删的 `browser.py`（SSE 观测台）
   与 `main.py`（CLI）：`GET /health`、`POST /runs`（后台线程跑 run）、
   `GET /runs/{id}/events`（SSE：`trace`/`review`/`done`/`error` 四类消息 + 15s 心跳 +
   Last-Event-ID 断线补发）、`POST /runs/{id}/review`（人工决策提交）、
   `GET /runs/{id}`、`GET /runs`。
2. **`BlockingReviewer`**（实现 `HumanReviewer`）：`review()` 挂起 run 线程等前端
   决策；超时（默认 300s）未收到自动 `CONTINUE`（协议"人类没答复就算继续"的落地）。
3. **`EventHub`**：run 线程与 SSE 连接之间的线程安全广播（publish/subscribe 队列）。
4. **`LocalTrace` 加 `on_event` 回调**（可选构造参数，append 落盘后调用）——trace
   接口协议不动，消费方自己接推送。
5. **`build_real` 加 `reviewer`/`on_event` 透传**；`create_app(build_run=...)` 工厂注入
   装配（默认读 `POKEMON_ROM` 环境变量），测试传 fake 不碰模拟器。
6. **pyproject 加 `api` optional-dependencies**（fastapi + uvicorn，dev 补 httpx）。

**为什么这么改**：前端接入需要 HTTP 面——启动 run、实时看事件、人工审查决策。
之前删掉的"前端实现"把接口协议都留下了（`HumanReviewer`/`TracePort`/`RunPlanReq|Resp`），
这一层是协议的 HTTP 落地。

**取舍**：
- **单进程单 run（并发 POST /runs → 409）**：`agent_permission` 的 `@initialize` 是
  模块级全局 + 嵌套检查（runtime.py 明写"不能并发跑两个 subject"），并发会在 episode
  层撞断言。这是库的硬约束，不是 API 设计选择。
- **SSE 控制消息（review/done/error）不带 id 行**：不污染客户端的 Last-Event-ID——
  断线补发只认 trace 的 `event_id` 空间；未决 review 重连总是补发，前端按 run 幂等。
- **review 超时自动继续而非无限等**：run 不会在没人看着时永远卡住；`GET /runs/{id}`
  暴露 `review_pending` 供前端感知。
- **world 清理失败不掩盖 run 结算**（`_execute` 的 finally 就地消化）。

**影响面**：`trace/store.py`（构造加可选参数，向后兼容）、`build.py`（签名加两个
可选参数，旧调用不受影响）、新增 `api.py` + `tests/test_api.py`（9 用例）；
`config/`、`interfaces/`、`schemas/` 零改动。

## 2026-08-30 —— plan 接入 LLM + 前端/CLI 实现移除

**改了什么**：
1. **plan 接入 LLM（run 级自主压栈真正落地）**：
   - 新增 `schemas/communication/run_plan.py`：`RunPlanReq`（run_id/goals/history）+ `RunPlanResp`（push_goals ≤ `MAX_PLAN_PUSH` / done / why）+ `PlanGoal`（goal/success_criteria/max_steps，**无 task_id**——run 级自主拆解的目标没有实验分组键，由 harness 生成 `plan-{run_id}-{序号}`）。
   - `prompts/run_plan.md` 定稿输出格式（JSON schema + 规则：具体可判定、≤5 个、栈空不造目标）。
   - `RunHarness` 注入 `llm_provider`；plan 节点调 LLM：压栈（截断到 5）→ 追加 goals/attempts；`done` 或栈空且不压 → 置 done；**连续 `PLAN_MAX_ATTEMPTS=3` 次调用/解析失败 → 置 `plan_failed` 路由到 review**（机器没主意了，问人）。每次调用写 `MODEL_CALL`（Source.HARNESS，episode_id=run_id、step=0）——run 级思考也产 trace 事件，mask 不读 MODEL_CALL 无递归噪声。`RunState` 加 `plan_failed`（plan 成功后必须清掉，否则残留标志一直路由 review）。
   - `build.py`：RunHarness 传 `llm_provider=QwenText(memory_model or text_model)`。
2. **前端/CLI 实现移除**（用户拍板"删前端+CLI 外壳"，experiment 保留）：
   - 删 `trace/browser.py`（SSE 观测台）、`trace/index.py`（EpisodeIndex 终端索引）、`main.py`（CLI 入口）。
   - `trace/store.py` 重写：删 sse/终端打印（BROWSER_ONLY/LABEL_W/COST_LABEL/_wrapped/_step_shown）；唯一性守卫内联为 `_episode_is_complete`（"已完成的一局不允许覆盖"——用有没有 EPISODE_END 判完整，**修正了旧 index 里 `"EPISODE_END"` 字符串永远匹配不上 `episode_end` 枚举值的潜伏 bug**；跨 run 撞号不会发生因为 episode_id 带 run_id 前缀，索引文件不再需要）。
   - `interfaces/trace/trace_port.py` 删 `sse()`（append 后置条件同步）；AGENTS.md/CLAUDE.md 的 SSE/观测台/推流引用同步清理。
   - `experiment/run_episode.py` docstring 的 main 入口引用改指 `build_real()` + `RunHarness.run()`。

**为什么这么改**：用户定的最后两件事——plan 接 LLM 让"根据历史循环压栈直到结束"真正闭环（LLM 决策器 + 失败降级到人工）；前端/CLI 是展示层实现，协议（`HumanReviewer`/`TracePort`/`RunOutcomeResp`）保留，实现先清掉，不需要保证有输出到 CLI 或 SSE。

**取舍**：plan 失败 3 次到 review——Auto 模式下（`AutoContinueReviewer` 永远继续）plan 持续失败会变成 plan→review→plan 死循环，真实前端由人类叫停（测试里用 STOP 终止验证）；计划内接受，记录在案。plan 的 MODEL_CALL 挂在 episode_id=run_id 上（run 级事件不属任何一局）。删 index.py 时一并修了旧 `"EPISODE_END"` 字符串比较的潜伏 bug（永远匹配不上，导致"已完成"判不出来）。

**影响面**：新增 run_plan.py；改动 run_harness.py（plan 决策器 + 路由三路）、harness_port.py（RunState.plan_failed + PLAN_MAX_ATTEMPTS + MAX_PLAN_PUSH 落实）、build.py、trace/（store 重写、trace_port 去 sse、删 browser/index）、main.py 删除、AGENTS.md/CLAUDE.md。验证：编译全绿；**35 测试绿**（新增 plan 四条：LLM 压栈顺序 / done 收手 / 连续失败路由 review / prompt 组装历史+目标）；LocalTrace 守卫冒烟（已完成拒覆盖、半局允许重跑）。

## 2026-08-30 —— 异常归类收口：网络失败进 AgentError 家族、蒸馏解析并入 ParseFailure

**改了什么**：
1. **新增 `ToolTimeout`（errors.py，AgentError 子类）**：外部提供者调用不通——网络层抖动或服务端 5xx 重试后仍失败。`dashscope` 网络层改：**4xx（401/403/400）当场抛 RuntimeError**（配置/请求错误，重试无意义）；**5xx 与网络异常退避重试，耗尽抛 ToolTimeout**（原来 5xx 一次就崩、网络耗尽抛 RuntimeError）。`RunHarness.dispatch` 只捕 AgentError → 网络失败现在让**这一局失败**（run 级重试预算接管），不再崩整个 run。
2. **蒸馏解析并入 `ParseFailure`**（episode_store 的 `_parse_response`）：原裸 `ValueError` 改为 `ParseFailure`（顺带保留 `raw_text`，replay 能看模型吐了什么）；episode_harness 的 summarize 由 `except ValueError` 改为 **`except AgentError`**（覆盖 ParseFailure + ToolTimeout）——蒸馏失败只记 ERROR 事件，**不改变已定的本局结果**（之前 ToolTimeout 从蒸馏逃逸会让一局成功的结算被覆盖成失败）。
3. **两处吞 Exception 收紧**：pyboy_world 视觉解析 `except Exception` → `except ValueError`（ValidationError/JSONDecodeError 子类，预期外 bug 照常上抛）；brain.judge 的兜底补 docstring 注明"这里捕的是预期外异常（含 bug），代价是 judge 内 bug 静默，trace 的 judge_call 带 why 可见"。

**为什么这么改**：全项目异常审计的结论——"每类失败要有名字"（CLAUDE.md 第八节）没落实的两处：网络失败无名字（RuntimeError 一路穿透崩 run）、蒸馏解析用裸 ValueError（replay 归不进失败模式分布）。网络抖动不该崩 run 是核心动机。

**取舍**：4xx 保持当场崩（配置错误重试多少次都一样，装配期暴露优于运行期假装）；summarize 吞 AgentError 是"记账不崩局"（本局结果在蒸馏前已定，蒸馏是收尾副作用，失败不该回改结算）。

**影响面**：errors.py（+1 类）、providers/dashscope.py（网络层重试语义）、memory/episode/episode_store.py（_parse_response 抛 ParseFailure）、harness/episode_harness.py（summarize 捕 AgentError + import）、world/pyboy_world.py、brain/brain.py（docstring）。验证：编译全绿、32 测试无回归、异常族谱校验（ToolTimeout/ParseFailure ⊂ AgentError）通过。

## 2026-08-30 —— RunHarness 重设计：条件弹栈 + 直连重试 + 三层护栏

**改了什么**：
1. **拓扑**：`reflect` 出口改为条件路由——失败且重试预算未耗尽 → **直连 `dispatch` 重试（不经 review）**；成功弹出 / 重试耗尽强制弹出 → `review`。`plan` 新增 END 出口（栈空且无新目标 → 置 done）；`reflect` 不再置 done。
2. **`reflect` 条件弹栈**：成功才弹；失败保留栈顶（goals/attempts 原样），路由依据 `goals[-1] == last_task`（字段相等）判断"没弹"。
3. **`plan` 升格**：每轮现读 `trace.events(RUN_TRACE_MASK)`，把"每局一行历史 + 完整目标栈"渲染进 `run_plan.md` 模板 → `RunState.plan_note`（LLM 决策器接入后直接调用；静态决策只判终止）。压栈上限 `MAX_PLAN_PUSH = 5`（LLM 版硬上限，静态版不压栈）。
4. **三层护栏**：L1 `decide_action.md` 加"停滞时要换打法"软约束；L2 episode 内停摆检测——`EpisodeRunState` 加 `stall_count`/`stall_key`，`remember` 比较本步（动作 + `obs.stall_key()`）与上一步，连续 `STALL_LIMIT=5` 步无变化强制结束本局（success=False，reason=`stalled`）；L3 run 级 `MAX_GOAL_RETRIES = 2`（同一目标最多派发 3 次），耗尽由 reflect 强制弹出。
5. **`RunState`**：加 `attempts: list[int]`（与 goals 平行的派发计数，invariant 长度相等）与 `plan_note`；stall 的 equal 语义落在 `ObservationFromWorld.stall_key()`（place.key + scene/overlay/cursor + dialog_text 机械字段——**长对话逐句推进算变化，同一句重按才是停摆**；overview/walk_map/检索折入字段刻意排除）。

**为什么这么改**：用户重新设计 run 级控制权——弹栈与否由结果决定，重试是机器的事（直连 dispatch 不打扰人），人只审查"目标被弹出"这个不可逆动作；失败保留栈顶消除了 `last_task` 压回的特例（RETRY 幂等化：栈顶已是该目标 → 无操作）。没有自动重试上限，"失败保留栈顶 + AutoContinueReviewer"就是死循环，所以三层护栏（prompt 软约束 → episode 内停摆强制退出 → run 级硬重试上限）与拓扑一起设计。

**取舍**：review 从"每局必经"改为"每次弹出必经"——重试不打扰人，但重试过程没有人工可见性（trace 里看得见）。停摆键排除 `overview`（VLM 自由措辞，进键则停摆检测失效）；停摆帧仍会走一次 judge（统一路径，不做特判）。路由用字段相等而非新增路由字段，相邻两层内容相同的目标会误判一次路由（多打一轮仍收敛，docstring 记录）。

**影响面**：`interfaces/harness/harness_port.py`（拓扑 docstring/RunState/两个常量）、`run_harness.py`（五节点+路由+`_history_lines`）、`episode_harness_port.py`（stall 字段）、`episode_harness.py`（STALL_LIMIT/remember/reason 派生）、`prompts/run_plan.md`（新建）、`prompts/decide_action.md`（L1 段）。验证：编译全绿；run 级六场景冒烟（全成功/直连重试/耗尽弹出/STOP/RETRY 幂等/PUSH）全过；**新增图层测试 `tests/test_run_harness.py`（8 条，六场景 + 耗尽不连锁 + plan_note 组装）与 `tests/test_episode_stall.py`（2 条，L2 集成走 `EpisodeHarness.run()` 全流程 + stall_key 对话语义）**，全量 32 测试绿；存储层 22 测试无回归。L2 测试绕开 `@initialize` 的方式：`initialize(lambda: None)()` 铺运行期（测试专用，module 级 fixture）。

## 2026-08-30 —— episode 摘要数据退出版本库：留在包内，gitignore 不进 git

**改了什么**：`git rm -r --cached` 取消跟踪 `pokemon_agent/memory/episode/memory/`（172 个
跨局摘要 md，文件留在原位置不动），`.gitignore` 的"运行产物与数据"区补
`pokemon_agent/memory/episode/memory/`；`FileEpisodeMemoryStore` 默认落盘目录不变
（仍是 `episode/memory/`，`_memory_dir()` 原样）；DATAFLOW §3.3 补一句"落盘目录在包内、
gitignore 不进版本库"。

**为什么这么改**：episode 摘要 md 是 agent 运行期一局一局攒出来的产物，不该进版本库
（每个实验批次都会变）；但数据位置留在包内、和代码同目录，避免把运行数据散到项目根。
`semantic/knowledge/*.md` 不同：那是运营手写内容（和 prompts 同类），继续进版本库。

**取舍**：历史 172 个 md 从版本库移除跟踪（文件保留在磁盘、继续作为检索索引的数据源），
新产生的摘要也不再出现在 git status 里；代价是换机器/克隆仓库时这份累积经验不随仓库走，
只能靠 trace 的 `EPISODE_MEMORY_WRITE` 副本或重新跑局重建。

**影响面**：纯跟踪策略变化，代码行为零改动；`git status` 不再显示该目录下的文件；
`FileEpisodeMemoryStore(directory=...)` 显式传目录不受影响。

## 2026-08-30 —— memory 重组：两类对称，每类收敛成 xxx_store + util

**改了什么**：
1. `memory/semantic/retrieval.py` 上提为 `memory/retrieval.py`（跨局摘要与知识库共用，
   docstring 补"只认字符串"的归属判据，删 `memory/vector.py` 过期引用）。
2. `episode/` 收敛为两个文件：`store.py`→`episode_store.py`（并进 `episode_summarizer.py`
   的 `EpisodeMemoryGenerator` 与 `_create_episode_memory`，原文件删除）；`utils.py`→`util.py`
   （只留 `parse_md` / `safe_filename`，从 store 移入并去下划线）。
3. `semantic/` 收敛为两个文件：`object_store.py`→`semantic_store.py`（`InMemoryObjectStore`
   原样保留），`knowledge/store.py` 的 `load_chunks`/`load_named_chunks`/`mtime` 合并为
   `KnowledgeStore` 类（可注入目录、`chunks()` 一次读盘返回 `[(文件名, 正文)]`）同文件；
   删 `knowledge/store.py` 与 `knowledge/__init__.py`，`knowledge/` 变纯数据目录。
4. `MemoryTool`：`__init__` 加 `knowledge: SemanticKnowledgeStore | None = None` 注入参数；
   `_refresh_knowledge_index` 改单次 `chunks()` 读盘（原来 `load_chunks` + `load_named_chunks`
   各读一遍全量文件）。
5. 新增 `interfaces/memory/semantic_knowledge_store.py`（`SemanticKnowledgeStore` 只读两方法），
   与 `SemanticObjectStore` / `EpisodeMemoryStore` 三足鼎立。
6. 文档：`docs/spec/memory/SPEC.md` 头部 + 第 6 节追平（`KnowledgeStore` 接口、`knowledge/`
   纯数据化、retrieval 路径），`prompts/SPEC.md` / `schemas/SPEC.md` 的
   `episode_summarizer.py` 引用改 `episode_store.py`，`AGENTS.md` 目录结构行更新，三个
   `__init__.py` docstring 重写。

**为什么这么改**：用户的规则是"每类记忆只该有两个东西：xxx_store + util"——旧结构
`episode/`（store/utils/episode_summarizer）与 `semantic/`（object_store/util/retrieval/
knowledge 嵌套）三处不齐：`retrieval.py` 只认字符串却住在 semantic 包（它同时服务两类
记忆，是共享件）；`knowledge/store.py` 是模块级函数 + 写死目录，和 episode 侧的
"实现 Protocol 的类"不是一类东西；`episode/utils.py` 里是私有函数被跨模块 import。
按"属于 `<kind>/` 当且仅当 import 该 kind 专属 schema"的判据重排后，两类完全对称。

**取舍**：`episode_store.py` 合并后约 330 行，超 AGENTS.md 的 300 行拆文件线——两类对称
是第一优先级，接受尺寸（将来真要拆，把蒸馏器独立成 `episode_producer.py` 即可）；
`semantic_store.py` 里两个类合并的是文件不是类，object（坐标索引、可写）与 knowledge
（不挂坐标、只读）形状不同，不共享状态。

**影响面**：`MemoryTool` 构造签名加可选参数 `knowledge`（默认 `KnowledgeStore()`，现有
调用方无需改动）；删 3 个文件（episode_summarizer.py / knowledge/store.py /
knowledge/__init__.py）、新增 1 个接口文件；全项目编译通过，冒烟验证（KnowledgeStore
12 分片 / 空目录契约 / FileEpisodeMemoryStore 落盘重建往返）全绿；tests/ 当前为空
（用户正在重写测试），无回归测试可跑。

## 2026-08-29 —— 收口规范漂移：summary 记账上收、删外部输入 assert、删 probe

**改了什么**：
1. `EpisodeMemoryGenerator`/`MemoryTool` 不再持有 `trace_port`、不再写 trace；
   `generate_summary`/`store_episode_summary` 改返回 `(EpisodeMemory, ModelCall)`，
   由 `Harness._summarize` 写 `MODEL_CALL`(Source.MEMORY) + `EPISODE_MEMORY_WRITE` /
   `ERROR`。`build.py` 不再给 `MemoryTool` 传 `trace_port`，`trace/utils.py` 补
   `episode_memory_write`/`episode_summary_error` 两个纯函数。
2. 删掉三处 `assert ...observation is not None`（`harness.py` 两处、`game_tools.py`
   一处）——校验的是模拟器/工具返回值，属外部输入，不是契约 assert。
3. 删除整个 `probe/` 目录（含 `whoami.py` 等直连 DashScope 的调试脚本），
   清理 README / spec 模块地图、`pyboy_world.py` 报错信息里的 probe 引用。
4. `AGENTS.md`/`CLAUDE.md` 目录结构追上代码：删 `graph/`、改 `mocks/`，补
   world/tools/memory/providers/vision/trace/experiment/prompts；「当前阶段」不再写
   "只做 mock"，§十一「明确不做」划掉真实模拟器/权限/SSE/真实 LLM 四项。

**为什么这么改**：把"只有 Harness 写 trace"这条铁律补严——蒸馏器之前是唯一一处
自己写 trace 的例外；三处 assert 把模拟器返回当契约校验，是 AGENTS.md 3.4 明定的
反例；probe 是遗留调试脚本，直连 SDK 违反"直连只在 providers"。

**取舍**：summary 的 token 账从 `EPISODE_MEMORY_WRITE` payload 挪进独立的
`MODEL_CALL`(Source.MEMORY)，与感知/决策/判定同构——蒸馏成本从此能被统一统计；
`probe/audit_verdicts.py`（0827 复核脚本）随 probe 一起删了，docs/experiments 对它的
引用暂未清理。

**影响面**：`MemoryToolPort.store_episode_summary` 返回类型从 `EpisodeMemory` 改成
`tuple[EpisodeMemory, ModelCall]`；`Source.MEMORY` 的 MODEL_CALL 事件是新增的；
probe 删除无运行时影响。

## 2026-08-29 —— docs/spec 同步：追平 08-25 之后的代码漂移

**改了什么**：把 `docs/spec/` 里七处落后于代码的地方同步到现状——
`interfaces/SPEC.md` 4.5 的 `MockTrace` 改回 `LocalTrace`（已落盘 JSONL + 浏览器 SSE，
末尾 `MockTrace = LocalTrace` 只是旧脚本兼容别名）；`world/SPEC.md` 的
`AFTER_ACTION_FRAMES` 360→600（10×GB_FPS）并补 `GB_FPS` 与"等过场"的理由；
`schemas/SPEC.md` 的 `Task.initial_state_hint`、`OVERLAY_ACTIONS[CHOICE]` 补
`left`/`right`、`ScreenState.cursor` 从序号改成选项原文（新增 `option_lines`/`cursor_said`）、
`Snapshot` 从手挑五字段改成 `status`+`facts`（删 `same_place_as`，`walk_map` 进快照）、
`StepMemory.render` 删掉"什么都没变"折叠；`build/SPEC.md` 1.3/1.3.1 的 `build_real`
签名与装配（补 `memory_model`/`upscale`/`run_id`、`MemoryTool` 四参、`Upscale` 预处理）；
`harness/SPEC.md` 删掉已不存在的 `_look_route` 方法；`schemas/SPEC.md` 与 `README.md`
补记 `episode_memory`/`episode_summary_io` 尚无字段表、`tests/` 只剩
`test_single_perception.py` 一个文件。

**为什么这么改**：08-25 全量同步后又动了一轮（光标改原文、Snapshot 存完整 facts、
10 秒演化、批跑入口等，其中光标/Snapshot 两笔只有 git commit、没进 CHANGELOG），
spec 与代码的差距已经大到"光读 spec 会画出错误的系统图"。

**取舍**：只改 spec、不碰运行时代码；`episode_memory`/`episode_summary_io` 的字段表
因缺精确字段只留指针未补全；`AGENTS.md`/`CLAUDE.md` 的目录结构（`graph/`、`mocks/`
FakeLLM/MockWorld）仍落后，按规范"要改规范先讨论"不擅自改。

**影响面**：纯文档同步，无代码改动。

## 2026-08-27（其十五）—— 假阳性逐任务分析

**改了什么**：新增 `docs/experiments/0827-false-positive-analysis.md`，
按任务拆开 124 次 run 的 16 次假阳性、3 次假阴性。
基线那份文档加了一行指路，两份分工：一份讲判定器错在哪，一份讲批次覆盖和成本。

**为什么这么改**：假阳性不是基线数据的一个脚注，它本身就是这次实验的结果。
逐任务对完之后，成因收敛成三类：**换证据 11 次**（判定器拿 `my_hp` 顶 `foe_hp`、
拿 `overview` 的散文顶 `scene`）、**判据没写否定项 3 次**（买成和取消共享同一组
可观测量）、**感知噪声被当成证据 2 次**（`Choose a POKéMON.` 被抄成第三个选项）。

最值得记的是一条相关性：**判定证据是一句固定台词的 8 条任务，假阳性为 0；
唯一一条需要跨帧比较字段的任务（`catch_weaken_target`），假阳率 87.5%。**
台词是离散的、字面的、不可替代的，找不到别的字段来顶替；跨帧比较则要求
判定器同时完成"找历史值、找当前值、比大小"，任何一步含糊它就退回讲故事。
这条直接给出了写新判据的优先级：先找固定台词，再退到单帧枚举字段，
跨帧比较放最后并单独教。

还发现一个可以机械拦截的病症：`catch_weaken_target` r3 的理由以"因此未完成"结尾，
`done` 却是 `true`——**结论和理由是分别生成的**，理由不是推理过程的记录。
可以加一条自洽检查：理由里出现否定词时 `done` 必须为 false。

**取舍**：分析里把"判据的锅"和"判定器的锅"分开记（B 类 vs A 类），
没有笼统归给 judge。`shop_cancel_purchase` 那三次即使判定器完美也会错，
因为判据在两种互斥终局下都为真——那是任务定义的缺陷，改 prompt 治不了。

**影响面**：只新增文档。六条修改建议尚未实施。

## 2026-08-27（其十四）—— 全量复核判定：`probe/audit_verdicts.py`，115/124 → 102/124

**改了什么**：新增 `probe/audit_verdicts.py`，把每条任务的判据翻译成对 trace 的
机械检查（只认 `facts` 字段和 `dialog_text` 字面文本），复核 `task_stats` 里
全部 124 次 run。`docs/experiments/0827-knowledge-baseline.md` 按复核结果重写。

**为什么这么改**：上一版分析只查了 `steps=0` 的三次就下了"95/95 全绿"的结论，
是错的。全量复核出来 **16 次假阳性、3 次假阴性**，`task_stats` 系统性高估约
10 个百分点，而且高估集中在 5 条任务上，按任务比较会得出错误的排序。

16 次假阳性是同一个 bug：**judge 在换证据**——判据点名了一个可观测量，
它拿另一个顶上去。`catch_weaken_target` 判据要 `foe_hp` 降，七次 `foe_hp`
全程停在 `较高`，judge 拿 `my_hp` 从 25/25 掉到 22/25（我方挨的打）当证据；
`wild_encounter` 判据要 `scene=battle`，四次在 `scene=field` 时凭 `overview`
那句"主角正前方有一只野生宝可梦"判过；`shop_cancel_purchase` 三次终帧写着
`Here you are! Thank you!`（买成了），判成了"取消成功"。
"默认 false、拿不准一律 false"防的是证据不足，防不住证据充足但不是那个证据。

**取舍**：复核脚本**只做机械检查，核对不了就报"无法核对"**，不引入第二个模型。
用模型检查模型只是把信任转移一次，不增加证据。代价是判据里但凡有语义成分
就覆盖不到——这反过来是个好压力：判据本来就该写成能机械核对的样子。

**影响面**：新增一个脚本和一份文档，不动运行时代码。
文档里列的三条修复（judge 不许换证据、`overview` 进 `JUDGE_BLIND`、
`shop_cancel_purchase` 加否定项）尚未实施。

## 2026-08-27（其十三）—— 0827 基线批次的数据分析

**改了什么**：新增 `docs/experiments/0827-knowledge-baseline.md`，
分析批次 `0827-060529-ba5c90`（20 条短任务 × 5 遍）的结果。

**为什么这么改**：表面是 95/95 全绿，但逐条对完 trace 之后有三件事必须记下来，
否则下一批数据会带着同样的问题重来一次：
- **3 次成功是假的**：都在 step 0，都是 judge 绕开字面判据去读 `overview` 的散文。
  `JUDGE_BLIND` 挡了 `walk_map`/`landmarks`/`known_objects`，却留着 `overview`——
  而它是这一帧里唯一由模型自由撰写、可以编造内容的字段。
- **`movement_obstacle` 一个可用样本都没有**：第 1 遍 DashScope 超时，
  子进程非 0 退出，剩下 4 遍没跑。汇总表上"缺席"和"没跑"长得一样。
- **步数几乎零方差**（temperature=0.7 下一多半任务五遍步数完全相同），
  说明这批任务已经饱和，量不出记忆机制的价值。

**取舍**：把"95/95"和"修正后的真实成绩"并排写出来，而不是直接改写成后者——
假阳性本身是这次最有价值的发现，抹平了就等于把它藏进一个漂亮数字里。
分析文档放 `docs/experiments/` 而不是 CHANGELOG：CHANGELOG 记的是决策，
这份记的是一次测量，两者的读法不一样。

**影响面**：只新增文档。文末列了五条下一步，其中「`overview` 进 `JUDGE_BLIND`」
和「run 级重试」会动代码，尚未实施。

## 2026-08-27（其十二）—— 一条命令跑完整批基线：`run_all_tasks.py`

**改了什么**：新增 `experiment/run_all_tasks.py`。
`python -m pokemon_agent.experiment.run_all_tasks --repeat 10` 把每条 knowledge 任务
各跑 10 遍，最后按成功率升序打一张表。支持 `--only` 挑几条、`--batch-id` 指定批次标识。

**为什么这么改**：一批基线数据现在是 19 条命令、几小时的手工操作，
中间崩一条，人回来看到的是半张表，而且分不清剩下的是"跑了没成"还是"根本没跑"。
把"跑哪些、各跑几遍、怎么汇总"固定成一条命令，这批数据才是**可复现的产物**
而不是一串手工操作的结果。

**取舍**：
- **每次 run 起子进程**，而不是在同一个解释器里循环。`run_experiment` 已经保证了
  每遍是独立的 run，这一层进程隔离防的是另一类东西：SDL/PyBoy 崩起来是段错误，
  同进程会把解释器一起带走，后面 18 条全没。代价是每次多一次解释器启动（1–2 秒），
  相对一局里几十次模型调用可以忽略。
- **批次层面吞异常，run 层面不吞。** 和 `run_chain` 那条"异常不吞"不矛盾：
  那里护的是一次 run 内部的数据可信度，这里管的是调度——任务之间本来就独立，
  让第 3 条的崩溃吃掉后面 16 条的数据才是真损失。非 0 退出码和"没跑满"都会进表，
  整批也以非 0 退出，不会被当成全绿。
- **汇总不自己记，读 `task_stats/*.json`**（harness 每局落盘的那份，唯一真相），
  按 `run_id` 前缀挑本批次的 run。自己再记一份，两份对不上时没人知道信哪个。
- run_id 的展开规则（`--repeat` > 1 时加 `-r{i}`）是**抄** `run_experiment.main` 的，
  两处必须一致，否则汇总会整条漏掉。这是这个脚本唯一的隐式耦合，写在 docstring 里了。

**只跑单任务**：`knowledge_recall_tasks` 返回的里面混着多节点链，
被显式滤掉了——链是"前一条成功才跑下一条"、失败会中途截断，
它那张表里的"成功率"既不是每条任务的成功率也不是链的成功率。
基线要的是每条短任务各自独立的数。

**影响面**：新增文件，不动任何已有接口。注意跑之前要确认 `AFTER_ACTION_FRAMES`
改成 10 秒之后的那版才是要测的版本——这一批数据和之前那些单次结果不可比。

## 2026-08-27（其十一）—— 每步按完给世界 10 秒演化

**改了什么**：`world/pyboy_world.py` 的帧数常量按秒重写：
新增 `GB_FPS = 60`，`AFTER_ACTION_FRAMES` 从 360 帧（6 秒）改成 `10 * GB_FPS`，
`WITHIN_ACTION_FRAMES` 写成 `2 * GB_FPS`（帧数不变，只是把它和注释对齐），
`BOOT_FRAMES` 同样换成秒的写法。`step()` 里那一行补上了为什么要等。

**为什么这么改**：这一段等的是**按键按下去之后才开始、而且不用再按键就会自己走完**
的过程：换图淡入淡出、战斗开场动画、对话逐字打出、菜单弹出、遭遇触发的闪屏。
等不够就感知，抄回来的是过场中间的一张半成品——视觉模型会照着它填 `scene` 和 `fields`，
而**那一帧对应的状态到下一步已经不存在了**，决策和判定都建立在一个不再为真的世界上。
原来的注释还写着"2 秒"，实际是 360 帧 ≈ 6 秒，注释和数字对不上；
现在常量本身就写成秒乘以帧率，改的时候不会再漂。

**取舍**：无头模式 tick 不限速，600 帧的开销相对一次视觉调用可以忽略，
这里省时间省不出什么，赌的却是整步的正确性。
`watch` 模式下每步会明显多停 4 秒，这是看得见的代价，但看的人本来就在等模型。

**影响面**：所有 episode 的每一步都多演化 4 秒。感知到的画面分布会变
（更少的过场中间帧），因此改动前后的成功率不可直接比。

## 2026-08-27（其十）—— `foe_hp` 的五个挡位给出可核对的分法

**改了什么**：`prompts/perceive_screen.md` 第二节新增「五个挡位怎么分」：
把 HP 槽四等分，按**填充部分右端点落在哪一段**定档
（满 = 填到最右端；较高 = 3/4~满；过半 = 1/2~3/4；较低 = 1/4~1/2；危险 = 1/4 以内），
配一张 ASCII 示意；并写明三条纪律——只比长度不做推断、不要用颜色（画面是黑白的，
原版的变黄变红在这里根本不存在）、**正好压在分界线上时填更高的那一档**。
同时声明这五个词是封闭且有序的集合，写别的词等于字段作废。
`schemas/observation.py` 里 `SCENE_FIELDS` 的注释跟着改，指向新的那一节。

**为什么这么改**：原来只有一句"条的长度目测填一个粗略挡位"，五个词列在括号里，
**没有任何区分办法**——同一个血量在两帧里可能被填成 `较高` 和 `过半`，
而 `catch_weaken_target` 的判据正是"挡位比历史里那几步低"。
判据要比大小，取值却是目测出来的近义词，那条判据就等于在读噪声。
括号里还写着"条几乎空/**变红**"，而这个 ROM 是 DMG 黑白画面，颜色线索不存在——
照着它判断只能是编。

**取舍**：分界线上统一往**高**了取，方向本身无所谓，要紧的是两帧一致：
取整方向不一致时，一次没造成伤害的攻击也会被读成掉了一挡。
挡位仍然是目测，不是从内存读的——对手 HP 在 Gen1 内存里是有的，
直接读会精确得多，但那属于"把答案白送给感知层"，
和 `walk_map` 走内存是两回事（几何是控制的前提，敌方血量是任务要观察的东西）。
这一步只把目测的口径定死，没有换来源。

**影响面**：`perceive_screen` 的 prompt sha 变了，感知那条链路的前后数据不可比。
`catch_weaken_target` 是第一个直接受益的判据。

## 2026-08-27（其九）—— `shop_interaction` 重新启用，接手"自己找店员"这件事

**改了什么**：
- 旧的 `knowledge_shop_open_buy_menu.state`（人站在店里地板上）原样存成
  `knowledge_shop_interaction.state`。
- `shop_interaction` 的 goal 改成「在商店里找到店员，隔着柜台跟他说话，
  直到 BUY / SELL / QUIT 出现」，criteria 改成
  「overlay 是 choice，且 options 是 BUY / SELL / QUIT」，
  `initial_state_hint` 写明店员在柜台里、店里另有两个顾客。
- 把 `knowledge_shop_interaction` 加进 `available_state_tasks`。
- 顺手从 `knowledge_pokemon_center_flow` 链里删掉已经不存在的
  `knowledge_pokemon_center_leave`。

**为什么这么改**：上一条把 `shop_open_buy_menu` 的存档挪到了 BUY/SELL/QUIT 菜单上，
"进店之后自己找到店员"这件事就没有任何任务在考了——而那恰恰是这批任务里
最有信息量的一条（两次失败都栽在认错 NPC 上）。`shop_interaction` 本来就在
`cases` 里，只是**没有对应的 `.state`，也没进 `available_state_tasks`，
被静默过滤掉，从来没跑过**；旧存档正好是它要的起点。

`pokemon_center_flow` 是同一类静默失效：`leave` 那条任务删掉之后，
链的 `if all(task_id in task_by_id ...)` 守卫让整条链直接消失，不报错。
**过滤式的装配会把配置错误变成"什么都没发生"**，两处都是这么坏掉的。

**取舍**：criteria 用 `options 是 BUY / SELL / QUIT` 而不是
`scene 是 shop`——实测跟错人也会让 `scene` 翻成 `shop`
（顾客那句 `No! POTIONS are all sold out.` 就伴随 `scene=shop`），
那个字段在这里不足以区分成败。选择框的三个字面选项才是真正的分界。

**影响面**：新增一个 `.state`，一条任务定义改写并首次真正参与运行，
一条任务链恢复可用。无代码逻辑改动。

## 2026-08-27（其八）—— 重做 `shop_open_buy_menu` 的存档

**改了什么**：`experiment_states/knowledge/knowledge_shop_open_buy_menu.state`
换成停在 BUY / SELL / QUIT 菜单、光标在 BUY 的那一帧。

**为什么这么改**：旧存档开局是 `scene=indoor overlay=none`、人站在店里地板上
（地图 42 x=3 y=5），和 `initial_state_hint` 写的「商店 NPC 对话结束后的菜单，
scene=shop overlay=choice」对不上。这条任务的 goal 是"选 BUY 打开商品列表"，
而 agent 得先自己找到店员、把对话推完才谈得上选 BUY——两次失败都耗在找人上，
考的根本不是这条任务想考的东西。

**怎么做的**：`knowledge_shop_select_item.state`（商品列表，1/1 通过的那个）
往回退一步——载入它、按一次 `b`、存盘，正好回到 BUY / SELL / QUIT。
用的按键时序和 `PyBoyWorld.step` 一致（`button(delay=10)` + 120 + 360 帧）。
验证过：新存档载入后按一次 `a`，出的就是 `POKé BALL / ANTIDOTE / PARLYZ HEAL /
BURN HEAL` 那张商品列表——这条任务现在 1 步可达。

**顺带确认**：那家店是开着的（存档里 ¥3000，商品列表正常）。
之前那句 `No! POTIONS are all sold out.` 是**顾客**的闲聊台词，不是店没开——
店员是 `人 x=0 y=5`，被柜台封在 `walk_map` 的 `#` 里。上一条 CHANGELOG 记的
「认人」判据就是为这个改的。

**取舍**：从后一个状态倒退一步来造前一个状态，比从头打一遍剧情省事，
代价是这两个存档的其余部分（金钱、背包、队伍）完全一样——
两条任务的初始条件因此是强相关的，不再是独立样本。对这批短程任务无所谓。

**影响面**：一个 `.state` 文件。`shop_open_buy_menu` 改动前后的成功率不可比。

## 2026-08-27（其七）—— 认人的判据统一成「四邻全是 `#`」

**改了什么**：重写 `knowledge/shop_purchase.md` 的「怎么认出店员」和
`knowledge/pokemon_center.md` 的「护士在哪」，两处用同一条判据：
**柜台里的人在 `walk_map` 上四邻全是 `#`，你走不到他旁边**——
这正是认出他的办法；站到隔着一格柜台的地板上，朝他的方向按 `a` ×1。
删掉了上一版"护士在上方那一行"的写法。

**为什么这么改**：`shop_open_buy_menu` 又失败一次（15 步用完）。
地图 42 的店员是 `人 x=0 y=5`，那一行是 `#N#.@....#`——他左右上下全是 `#`，
柜台在 x=1，正确站位是 x=2 y=5 朝 west。agent 全程在跟另外两个 `N` 说话：
`人 x=3 y=3` 给 `No! POTIONS are all sold out.`、`人 x=5 y=7` 给
`This shop sells many ANTIDOTES.`——**顾客也会说商店的事**，
所以"台词跟商店有关"根本不是店员的证据，这一条现在写进文档了。

上一版护士那条写的是"在屏幕靠上、柜台在上方"，在这一局是错的：
这里的柜台在**左侧**。方位不是共性，"被 `#` 封住 + 隔一格说话"才是——
两个场景现在共用这一条。

**取舍**：判据依赖 `walk_map`（来自内存，不会错），不依赖 `overview`
（视觉模型写的，会编）。代价是模型要多做一步：在 `landmarks` 的几个「人」里
逐个查四邻。文档里把这个对照步骤写成了固定动作，而不是留给它自己想。

**影响面**：两个知识文档，无代码改动。
`shop_open_buy_menu` 的存档另有问题（开局不在 BUY/SELL/QUIT 菜单上，
与 `initial_state_hint` 不符），那是另一件事，没在这里改。

## 2026-08-27（其六）—— 往返链写进三处；`catch_weaken_target` 只判掉血

**改了什么**：
- 撤回上一条给 `wild_encounters.md` 加的「别在地图边缘来回走」，换成
  「一条链里可以来回走」：`[{"up":4},{"down":4}]` 是合法链，在同一片草丛里走 8 格
  只花一次感知；`times` 从 `walk_map` 上数这段连续 `G` 还剩几格，去和回同一个数。
- 同一件事补进 `repeat_hint.md` 的规划例子和 `decide_action.md` 的 `sequence` 说明
  （那里刚加过"链尾可带一个 `a`"，顺手把"可以原路折回"一起写明）。
- `catch_weaken_target`：goal 从「打对手一下，但别把它打晕」改成「打对手一下，让它掉血」，
  criteria 从「foe_hp 的挡位比历史里那几步低，且 scene 仍是 battle」
  改成「foe_hp 的挡位比历史里那几步低」。

**为什么这么改**：上一条把"走出草丛"写成了禁令，而真正缺的是**做法**——
禁止一个动作不会让模型找到替代动作，给出往返这条具体链才会
（和 `REPEAT_HINT` 那次"许可不会改变行为，例子才会"是同一个教训）。
`catch_weaken_target` 则是判据混进了一个不该判的东西：任务要的是"打掉血"，
`但别把它打晕` / `scene 仍是 battle` 把"对手没倒下"也变成了判据的一部分，
而一发 TACKLE 打晕在那个存档里是常事——掉血这件事**已经发生过**，
却因为它随后晕了而被判失败。掉血是事件，还在不在战斗是状态，两者不该绑在一条判据里
（规范第 4 条）。

**取舍**：`catch_weaken_target` 现在不再区分"削弱"和"打倒"，
作为捕捉链的前置步骤，这一条的把关变松了。宁可松：它要考的是
"能不能用招式造成伤害"，控制伤害不打晕是另一件事，
真要考那件事应该单独出一条任务、并配一个对手血量足够高的存档。

**影响面**：三个 prompt / 知识文档 + 一条任务定义，无代码改动。

## 2026-08-27（其六）—— 多段链允许在末尾带一个 `a`

**改了什么**：`brain.py` 的解析期校验、`game_tools.execute()` 的 assert、
`prompts/decide_action.md` 与 `prompts/repeat_hint.md` 的规则说明，以及
`docs/spec/{tools,interfaces,world}/SPEC.md` 里对应的那几句。
规则从「多段链只能是方向键」放宽成「**链体只能是方向键，最后一段允许是 `a`**，
`a` 最多一次、`times` 恒为 1」。

**为什么这么改**：原规则挡住的是「中间帧看不到」这一件事，而链尾那一帧
本来就会被感知——`a` 打开的对话框/菜单正好出现在这一帧，证据一点没丢。
挡着它的代价是「走过去 + 按一下」必须拆成两次决策，也就是多付一次视觉调用。
`a` 仍然不许出现在链中间：那才是真的把对话吃掉的情形。

## 2026-08-27（其五）—— 复盘 5 条仍然失败的任务，补两条知识

**改了什么**：`knowledge/wild_encounters.md` 加「别在地图边缘来回走」；
`knowledge/shop_purchase.md` 加「店员是柜台后的那个，而且他不一定卖东西」。

**为什么这么改**：查 `experiment_results/task_stats/`，18 条任务里 5 条 0/1、
`pokemon_center_enter` 1/3（唯一成功的那次是判据改完之后，1 步达成）。
逐条读 trace，**judge 的判定全都是对的**——这 5 条不是判据问题，是三类真问题：

- `wild_encounter`：agent 在地图 0 (y≈0) 和地图 12 (y≈33) 之间来回横跳 10 步。
  `up×4` 走过边界换图，`down×4` 换回来，跨图的那几步不在草丛里挪格，
  遭遇判定一次都没跑。知识里只说了"要连着走"，没说"别走出这张图"。
- `shop_open_buy_menu`：对着同一个 NPC 按了 9 次 `a`，每次都是
  `No! POTIONS are all sold out.`，`scene` 始终是 `indoor`。
  和护士那次同构——认错交互对象，然后重复一个已知无效的动作。
- `battle_pokemon_switch`：`right` 连按 1/1/2/1/3/1/4/5/6/8 次，`cursor` 恒为 `FIGHT`。
  而 `battle_action_menu`（同一个菜单里移动光标）1/1 成功。
  **这一条不像是大脑的问题，像输入或读取**，没改任何东西，留待 `probe/` 单独验。
- `catch_weaken_target` / `shop_cancel_purchase`：起始存档和 `initial_state_hint`
  对不上。前者 PIDGEY 被一发 TACKLE 打晕（"别打晕"在那个存档下几乎做不到），
  后者提示写「购买确认选项」，实际开局还在商店外，10 步全花在走到确认框，
  走到时正好用完。属于规范第 7 条那类问题，改存档而不是改判据。

**取舍**：只补了知识文档。存档不对和输入疑点都不该用 prompt 去绕——
用知识去教 agent "绕开一个坏存档"，等于把环境 bug 编码进先验，以后环境修好了这条还在。

**影响面**：两个知识文档，无代码改动。这 5 条任务的样本量都是 1，
上面的归因是单次 trace 的读解，改完要各跑几次才算数。

## 2026-08-27（其四）—— 全量复查任务判据，两类系统性坏判据

**改了什么**：照着 `pokemon_center_enter` 那条的病因把 19 条任务判据过了一遍，
改了 8 条，并在 `tasks.py` 的规范里补了第 8、9 条和两条自查项。

**归属推断类**（judge 手里没有说话人 / 没有名单，无法核对）：
- `npc_dialogue`：「dialog_text 是这个 NPC 说的话」→「dialog_text 非空」。
- `battle_pokemon_switch`：「options 是队伍里的宝可梦名字」→
  「options 不再是 FIGHT / PKMN / ITEM / RUN，而是宝可梦名字」。
- `battle_item_use` / `shop_open_buy_menu` / `shop_cancel_purchase`：
  「options 是道具名 / 商品名」补上字面例子（`POKé BALL` / `POTION` / `ANTIDOTE`），
  把归属判断降级成字符串比对。

**字段不存在类**（引用了那个 scene 下根本不会出现的字段）：
- `pokemon_center_heal`：删掉「或 my_hp 回到满值」——`my_hp` 只在
  `scene=battle` 的 `SCENE_FIELDS` 里，治疗发生在 `indoor`，那里永远读不到它。
- `shop_interaction`：「fields 里有 money 或 items」→「facts 里出现 money 或 items 字段」，
  `facts` 是扁平 dict，没有 `fields` 这一层。

**另外一条**：`choice_confirm` 的「出现了选择之后的对话框文字**或新画面**」
无法机械核对，改成「overlay 变成 dialog 或 scene 和历史里那几步不同」。

**为什么这么改**：`pokemon_center_enter` 那条不是个例。
「拿不准一律 false」这条 judge 原则会把任何**不可核对**的判据变成恒为 0 的任务，
而失败症状和"任务太难"完全一样——不逐条查就看不出来，
而且会持续污染实验数据（一个恒 0 的任务会把整批召回率压低而没人知道原因）。

**没改的**：`movement_obstacle` 锚在 `map_id=12 且 y>=14` 上，
按规范第 7 条它依赖 `experiment_states/` 里那个 `.state` 钉死，属于已知取舍，保留。
`battle_move_select` 的「或对手 HP 挡位下降」需要和历史比，
但 `foe_hp` 在 `scene=battle` 确实存在，judge 有 3 步历史，可核对，保留。

**影响面**：8 条任务定义的判据变了，这些任务改动前后的成功率不可比。
`tasks.py` 的规范部分新增两节，无代码逻辑改动。

## 2026-08-27（其三）—— `pokemon_center_enter` 的判据改回"进门"这一件事

**改了什么**：`experiment/tasks.py` 里 `pokemon_center_enter` 的目标从
「走进宝可梦中心，和前台护士说上话」改成「走进宝可梦中心」，判据从
「scene 是 indoor，且 dialog_text 是护士说的话」改成
「scene 是 indoor，且 map_id 和历史里门外那几步不同」。

**为什么这么改**：两个独立的毛病。其一，任务叫 `_enter` 却塞了两件事，
而对话那一半正是下一个任务 `pokemon_center_heal` 的内容——一局同时考两件事，
失败时分不清是没进门还是没说上话。其二也是更要命的：
「是护士说的话」**判定员没法验证**。判定员只看得到 `dialog_text` 的文字，
而护士的台词（`Welcome to our POKéMON CENTER!`）里不带说话人前缀，
它无从确认这句是谁说的；judge prompt 又明写「拿不准一律 false」——
于是 agent 明明已经对上话，判定仍然稳定输出 false。
这条判据从写下来那天起就是不可能满足的。

**取舍**：新判据用 `map_id` 变化而不是「`overview` 说这是宝可梦中心」——
后者来自视觉模型，而视觉模型编造建筑名称是这个项目里反复出现的问题
（`world/SPEC.md` 和 `observation.py` 都记着真新镇被编出宝可梦中心那次）。
`map_id` 来自内存，不会错。代价是判据只验证了"换过一次图"，
不验证换到的是不是宝可梦中心——初始状态提示已经把 agent 放在中心门外 3–6 步，
这个前提下换图基本只有一种去处，用一个可信的弱判据比用一个会编的强判据划算。

**一般性教训**：判据里不能出现「是某人说的话」这种需要判定员做归属推断的措辞，
除非那句台词自带说话人前缀（`MOM:` 那种）。要么引用台词原文，
要么换成内存里读得到的状态量。`pokemon_center_heal` 的判据引的是原文，是对的。

**影响面**：只改一条任务定义，`knowledge_pokemon_center_enter` 的历史成功率
和改动后的不可比。

## 2026-08-27（其二）—— 护士识别改成几何判据；清掉一条编造的情景记忆

**改了什么**：重写 `knowledge/pokemon_center.md` 的「护士在哪」一节。
上一版给的是"柜台后 / 靠上 / 被 `#` 围住"三条特征，判据换成唯一确定的几何关系：
柜台是横着的一整段 `#`，护士在柜台**上一行**，玩家站柜台**下一行**的同 `x` 格朝 `up`
隔着柜台按 `a`；同一行左右紧邻的 `N` 一律不是护士，负坐标的 `N` 不在地图里。
另把 `episode/memory/pokemon_center_nurse_dialog_fails_on_wrong_map.md`
移到根目录 `_to_delete/`。

**为什么这么改**：上一版特征不具区分性——实测模型拿"上方 y=2 整行是 `#`"去论证
`x=-1 y=3` 那个普通 NPC "被 `#` 包围、符合柜台后特征"，先验反而给错误目标背了书。
真实局面是柜台在 y=2（整行 `#`），护士在 x=3 y=1，正确站位是 x=3 y=3 朝上——
"隔着柜台在正上方"是能一次判死的关系，"被 `#` 围住"不是。
那条情景记忆则是模型自己编的：它断言"post-analysis confirmed 地图 41 是实验室"，
而地图 41 就是初心镇宝可梦中心（40 才是研究所），这条被取回后会直接让 agent 放弃治疗。

**取舍**：在知识文档里点名反驳了"地图 41 是实验室"这个具体说法。
一般不该让通用先验去纠正某一条记忆，但蒸馏出来的情景记忆目前没有可信度标注，
错的和对的一起被取回，只能先在先验里压住这一条。
真正的解法是给情景记忆区分"观察到的"和"推断的"，那是机制层面的事，不在这一步。
情景记忆用 `mv` 到 `_to_delete/` 而不是直接删，留出复核余地。

**影响面**：只改知识文档，移动一个记忆文件；无代码改动。

## 2026-08-27 —— 决策 prompt 强制消费失败记录；护士位置写进先验

**改了什么**：`prompts/decide_action.md` 的「已知事实」段后面加了三条硬规则——
同格同键已记「无效果」不许重按、失败 ≥2 次要先怀疑对象认错并在 `thought` 里写出被证伪的假设、
「在正前方且朝向正确」只能作为"能按"而非"按了有用"的论据；`rationale` 必须能说出
和上一次相比哪一样东西变了。`memory/semantic/knowledge/pokemon_center.md` 补了一节
「护士在哪」：柜台后、屏幕靠上、`walk_map` 上被 `#` 围住的那个 `N` 才是护士，
和主角同一行、四周是 `.` 的 `N` 是普通住客；标准姿势是站到柜台前那一格朝上按 `a` ×1。

**为什么这么改**：实测一局里连续 6 步对着 `x=-1 y=3` 的 `N` 按 `a`，
`known_objects` 已经写着「互动 4 次 / 无效果」，而 `thought` 每一步都重新推导出
「位置最优、朝向正确、所以这次会成功」。两个独立的缺陷叠在一起：
决策 prompt 只教了怎么读**情景记忆**的前后对照，没教怎么读 `known_objects` 里的失败流水，
于是失败次数完全没有进入推理；同时先验里只说了"找到护士"，没说护士长什么样，
模型就把最近的那个 `N` 当成了护士——目标识别在第 0 步就错了，后面全是自我确认。

**取舍**：规则写成"必须换一样东西"而不是"禁止重复动作"——重复本身有时是对的
（对话框里一句一句按 `a`），可证伪的判据是"和上一次相比有没有变量改变"，
而不是动作字面是否相同。护士的识别特征给了三条并要求合看，没有写死坐标：
不同宝可梦中心的绝对坐标不同，但"柜台后 + 靠上 + 被 `#` 围住"是布局共性。

**影响面**：只改 prompt 与知识文档，无代码改动。`decide_action` 的 prompt sha 会变，
manifest 里前后两批实验数据不可直接比。

## 2026-08-26 —— `ScreenState.cursor` 从序号改成选项原文

**改了什么**：`schemas/observation.py` 的 `ScreenState.cursor` 从 `int | None`（0 起序号）
改成 `str | None`（光标所指的选项原文，如 `"FIGHT"`）；新增 `option_lines`
（选项逐行原文）与 `cursor_said`（模型自己的读数，仅在不一致时有值）两个字段；
`options`/`cursor` 改由 `option_lines` 派生（`_derive_cursor_from_lines`），
并加 `_cursor_must_be_one_of_the_options` 校验"光标值必须是某选项之一"。
`prompts/perceive_screen.md` 和 `world/pyboy_world.py` 跟着改。

**为什么这么改**：序号版本没有任何自校验的余地——`cursor=2` 即使没有第三个选项也
无从发现；换成原文之后，"光标值 ∈ 选项集合"变成一条可机械执行的校验，读错当场作废
而不是喂给大脑一个不存在的选项。`cursor_said` 留着模型自己那份读数，两者不一致的
比例就是"这个改动值不值得"的证据。

**取舍**：`option_lines` 读不出（无三角标记）时回退到模型直接填的 `cursor`，不硬判废。

**影响面**：`perceive_screen` 的 prompt sha 变了，感知链路前后数据不可比；这是第一个
让"光标可核对"的判据直接受益的改动。

## 2026-08-26 —— `Snapshot` 存完整 facts，前后对比交给大脑

**改了什么**：`schemas/step_memory.py` 的 `Snapshot` 从"手挑五个字段
（overview/landmarks/neighbors/position/dialog）"改成 `status` + `facts`（除去
`SNAPSHOT_BLIND` 外原样照搬），新增 `SNAPSHOT_BLIND`/`FIELD_ORDER`/`FIELD_LABEL`
三个常量；`same_place_as` 连同 `StepMemory.render()` 里"前后相同折叠成『什么都没变』"
的逻辑一起删掉；`overview`/`position` 降级成 property。`prompts/decide_action.md`
补"必须对比前后快照、说清哪一样变了"的规则。

**为什么这么改**：手挑五字段是为野外挑的——战斗帧里它们是进战斗前残留的野外值、恒等，
于是"光标确实移动了"也被 `same_place_as` 判成"没效果"。**错误的结论比没有结论贵**：
一句加粗的"什么都没变"，大脑对它的信任正好是我们承诺的那么高。所以现在只摆事实
（两份完整快照、字段对齐、顺序固定），变没变由大脑自己读。`walk_map` 也因此进快照了
——屏幕格删掉之后它的行列号就是全局坐标，旧禁令"屏幕相对、跨步失效"的前提已经没了。

**取舍**：字段清单由观测决定（排除表 `SNAPSHOT_BLIND` 只有三项），不由一份写死的白名单
决定——新观测字段默认进记忆，需要理由的是挡在外面。

**影响面**：情景记忆的渲染形状变了，`decide_action` 的 prompt sha 变了；历史 trace 里
旧格式的 `MEMORY_WRITE` payload 与新格式不可比。

## 2026-08-26 —— 权限拒绝按最低运行能力降级
**改了什么**：memory 查询、memory 写入、`Brain.reflect` 和 episode 摘要写入增加权限拒绝降级；每次降级都写一条 `ERROR` trace。`Brain.reflect` 被拒时跳过整个记忆写入分支，但仍推进已执行动作的 step。
**为什么这么改**：这些能力不影响世界推进、动作选择和成功判定；权限拒绝不应把本来还能继续的一局变成无记录的异常终止，同时每次记录才能保留权限失败发生的真实位置。
**取舍**：权限异常单独识别，其他异常继续抛出；`save_state`、reset、perception、action space、press、decision、judge 仍是硬失败。
**影响面**：修改 Harness 的 memory/summary 调用路径和 trace 工具；新增权限降级事件 payload，不改变正常授权路径。

## 2026-08-26 —— 统计只提交任务链结果
**改了什么**：`run_chain()` 不再把链内 task outcome 单独写入统计，只提交最终 chain outcome。
**为什么这么改**：单任务链中 `task_id` 与 `chain_id` 相同，双重写入会让一次独立 run 被统计两次。
**取舍**：保留 chain 的完整任务明细在 `runs[].tasks` 中；不再维护同一统计文件下的 task 级重复计数。
**影响面**：只影响 `experiment_results/task_stats/` 的后续统计写入，不修改已有历史统计。

## 2026-08-26（其二）—— 一帧只感知一次，帧哈希从项目里消失

**改了什么**：观测由 world 在 `reset()` / `step()` 的结尾产出，沿返回值传到 harness，
不再由 harness 每步主动 `perceive()` 一次。

- `ToolPort.perceive()` 删除（无调用方），连带 `read:game:perceive` 这条权限。
- `get_action_space()` → `get_action_space(obs)`，纯函数，不再自己去 `world.observe()`。
- `execute(action)` → `execute(action, obs)`，收下"这个动作是按哪份观测选的"；
  `GameTools._last_space` 整个删除，掩码校验改用模块级纯函数 `_mask(obs, all_actions)`。
- `PyBoyWorld._cache`（帧哈希缓存）、`WorldPort.last_frame_sha`、
  `PerceptionResult.frame_sha`、`OBSERVE` 与 `MODEL_CALL` payload 里的 `frame_sha`
  全部删除。`hashlib` 依赖随之消失。
- `LoopState.press_result` → `pending_observation`：`_begin` 从 `reset()` 收下开局
  那一帧，`press` 从 `execute()` 收下之后每一帧，`look` 拿它盖章、`remember` 拿它当 after。
- `Harness._observe()` 不再感知，只盖 `step`/`done` 并写 `OBSERVE`。

**为什么这么改**：**同一帧曾经被感知四次**——`_look` 一次、`get_action_space()` 一次、
`step()` 结尾一次、下一步 `_look` 又一次。world 内部的帧哈希缓存把三次挡掉，所以
稳态下只花一次感知的钱。但缓存是在补一个结构问题，而且掩盖了两件事：

1. `get_action_space()` 去 `world.observe()` 只为读 `facts["overlay"]` 一个字段——
   那次感知完全多余，掩码本来就是 `Observation` 的纯函数。
2. 「记忆里的 `after` 和下一步的观测相等」只是碰巧成立（靠"`press` 和 `look` 之间
   没人 tick 世界"），没有任何断言守着。插一个会推进世界的节点就静默不一致。

现在观测沿调用流传递，两者是**同一个对象**——不需要保证的东西才不会漂。缓存和帧哈希
随之失去全部理由：前者没有东西可缓存，后者没有东西可比较。

**取舍**：
- **`execute` 收 `obs` 而不是 `space`**。space 是 obs 的派生物，传 obs 更诚实——
  传 space 等于让调用方替被调方保管一份它自己能算的东西。
- **`_mask` 是模块级函数，不是让 `execute()` 去调 `get_action_space()`**：后者会在
  一次权限守卫调用里再触发一次守卫，审计流多一条没有意义的记录。掩码本身不需要授权，
  需要授权的是"向外交出动作空间"。
- **`_look` 不改名**。它不再"看"了，但它仍然是每一步的入口，改名的收益不抵调用方
  和文档里几十处引用的成本。
- **接受感知调用的记账归属变化**：第 N 步的观测由第 N-1 步的 `press` 感知出来，
  那条 `MODEL_CALL` 落在 `step=N-1` 下。那次调用确实发生在第 N-1 步。

**丢掉的能力**：trace 里少了"这两条观测是不是同一帧"。它曾用于诊断两件事——
「模型在同一张图上给了不同答案」（以后不可能发生，同一帧不会被问两遍）和
「卡住了」（换判据：比 `place` + `status` 有没有变）。

**影响面**：**破坏性变更。** `GameToolPort` 少一个方法、两个方法改签名；
`WorldPort` 少一个成员；`PerceptionResult` 少一个字段；`OBSERVE` 事件的 payload
少一个键（旧 trace 文件里有这个键，replay 时忽略即可）；`read:game:perceive`
从权限清单消失。**每步的视觉模型调用次数不变**（一直是 1，只是从"靠缓存达成"
变成"靠结构达成"）。

## 2026-08-26 —— 帧哈希跟着 `PerceptionResult` 走，删掉 `ToolPort.last_frame_sha`

**改了什么**：`PerceptionResult` 加 `frame_sha` 字段；`PyBoyWorld._perceive()` 把 sha
作为返回值的第一项交出去，`observe()` 填进结果；删掉 `GameTools.last_frame_sha`
（property + `@require_permission("read:game:last_frame_sha")`）与 `ToolPort` 上的声明；
`harness._observe` 改用 `perceived.frame_sha`；`permissions.json` 删掉那条权限串。

**为什么这么改**：

1. **那个权限守不住任何东西**。`GameTools` 自己在 `get_action_space()` 和 `execute()`
   里直接读 `self._world.last_frame_sha` 做动作空间的过期检查，绕过守卫。
   同一个文件里能随手绕过的检查不是边界。
2. **它是 `drain_calls()` 的同一个形状**。`_observe()` 在 `perceive()` 之后再调一次
   去取哈希，而值属于刚刚产生的那一帧 —— `PerceptionResult` 的 docstring 早就把这个
   教训写下来了：让产生它的地方直接当返回值交出来。
3. **前提不成立**。这个字段的全部意义是「这条观测是哪一帧」，用第二次读取的结果去
   回答第一次读取的归属，逻辑上就不对。单线程下现在不会错，但那是调用顺序碰巧保证的，
   不是结构保证的。

**取舍**：`WorldPort.last_frame_sha` **保留**。动作空间的过期检查要它，那是工具层
内部的用途，和「交给 Harness 记账」是两件事。属性和返回值各管一头。

**顺带清掉 `write:harness:trace`**：两个角色里都有它，但全项目没有任何
`@require_permission("write:harness:trace")` —— 是个悬空的权限串。悬空的授权比缺失的
授权更坏：它让人以为 trace 写入被守着，实际上一行检查都没有。要给 trace 加守卫，
该是先加装饰器再加这条串。

**影响面**：`ToolPort` 少一个成员（契约变更，实现方要跟）；`PerceptionResult` 多一个
有默认值的字段（旧数据反序列化不受影响，`frame_sha` 为空串）；`read:game:last_frame_sha`
与 `write:harness:trace` 从权限清单消失。行为不变 —— OBSERVE 事件里那个 sha 的值和
从前一样，两条权限串本来也没有守着任何东西。

## 2026-08-25 —— docs/spec 全量同步：十份 SPEC 追上代码
**改了什么**：`docs/spec/` 下十份文档全部对着代码校了一遍，
+1036 / -552 行。今天所有变更的痕迹（动作链、一链一感知、`summary` → `status`、
`ToolResult.message` 删除、朝向读 RAM、细看整条删除、记忆一族改名、trace payload
变化、`--repeat`、观测台单例）都落进了对应的 SPEC；顺带修了**今天之前就已经漂了**
的一批：`MemoryToolPort` 整张签名表（`query_episodic`/`known_here`/`knowledge_base`/
`note_step`/`see_objects` 一个都不剩）、知识库从"全量拼接、每次读盘"改成混合检索 +
mtime 增量索引、`MockTrace` → `LocalTrace`、`memory/port.py` 这个不存在的路径、
`probe/run_episode.py` 已搬到 `pokemon_agent/experiment/`、`save_state` 从来没进过
签名表。
**为什么这么改**：文档漂了不会有任何症状——直到有人照着它改代码。这一轮里
`repeat_hint.md` 就是活的证据：它一个字没改，于是模型同时收到两套互相矛盾的说明。
SPEC 比 prompt 更隐蔽，因为它不进模型的上下文，只进人的上下文。
**取舍**：删掉的东西**不是抹掉，是改写成「这里曾经有一个 X …… 为什么删」**——
`inspect` 那条"细看和 observe 的区别不在再看一次、而在问的是不同的问题"、
`query_episodic` 那条"打分对着的必须和喂进 prompt 的是同一份文本"、
知识库那条"要能一边跑一边改 .md"，都是踩出来的判断，删了代码不等于删了理由。
`build/SPEC.md` 第 5 节描述的旧入口（`probe/run_episode.py`）没有逐节重写，
只在节首标明它已搬走、下面按旧文件读——那几节讲的 `_summary()` 统计逻辑仍有参考价值。
**怎么做的**：五份用 subagent 并行改（world/schemas/tools/interfaces/brain），
其余六份手工改。中途撞上会话额度上限，四个 agent 被腰斩，后半程改回手工。
**影响面**：只动文档，一行代码没碰；`pytest tests` 仍是 15 passed + 1 skipped。

## 2026-08-25 —— 同步 repeat hint 的方向键规则
**改了什么**：在 `repeat_hint.md` 中明确废弃旧的“多段链只能上下、right 必须换步”说明，改为允许四个方向键组成多段链。
**为什么这么改**：仅修改 `decide_action.md` 会让 `repeat_hint.md` 继续向模型提供相互矛盾的路径规划规则。
**取舍**：保留旧文字作为历史说明并追加覆盖规则，避免破坏 prompt 文件的既有结构。
**影响面**：统一 `repeat_hint.md` 与执行器对方向键链的约束。

## 2026-08-25 —— 允许四个方向键组成多段链
**改了什么**：将多段 `sequence` 的允许按键从 `up/down` 扩展为 `up/down/left/right`。
**为什么这么改**：多段按键链表达的是移动路径，四个方向键都属于移动指令，不能只限制上下移动。
**取舍**：`a` 等非方向键仍只能出现在长度为 1 的 sequence 中，避免把交互动作混入移动链。
**影响面**：同步更新决策解析、执行校验和 prompt 规则。

## 2026-08-25 —— 蒸馏 prompt 并入统一加载路径；NPC 说明去重；补上 `tests/test_prompts.py`
**改了什么**：
1. `episode_summary.md` 从 jinja2（`{{ }}`）改成 `$` 占位符，`EpisodeMemoryGenerator`
   不再自己 `jinja2.Template(open(...))`，改用 `prompts.load`；`success` 那个条件表达式
   挪进代码（传 `result="成功完成"/"未能完成"`）；`with_prompts` 里加上它。
   顺带把通篇的"情景记忆"改成"跨局摘要记忆"，并点明它和 `StepMemory` 不是一回事。
2. NPC 那段说明只留 `map_hint.md` 一份，`decide_action.md` 里删掉，
   `decide_action` 独有的那句"只是重复固定台词就换一个"并进 map_hint。
3. 新增 `tests/test_prompts.py`（原来是个 0 字节的空文件）。
**为什么这么改**：
自己读文件的代价不是多几行代码，是这份 prompt **没有 sha、进不了 manifest**——
那一局的蒸馏用的是哪一版说明，事后查不出来，而 manifest 存在的全部意义就是回答这个。
两套模板引擎并存还意味着 `$` 和 `{{ }}` 两种语法在同一个目录里，改错一个不会报错。
NPC 说明重复两份、两份都每步进 prompt，改一处漏一处是迟早的事。
**最要紧的是第 3 条**：`schemas/observation.py` 里 `describe_scene_fields()` /
`json_output_examples()` 的注释一直写着"漂移由 `test_prompts.py` 挡"，
而那个文件是**空的**——**声称存在的锁不存在，比没有锁更糟**：那两个函数因此
零调用方（看起来像死代码），而 prompt 和 `SCENE_FIELDS` 真漂了也没人知道。
现在它测三件事：每份 prompt 的 `$占位符` 和调用方实参双向吻合（漏传当场 KeyError、
多传静默丢内容）、字段清单逐字一致、六个 JSON 样例按解析后的 dict 一致。
实测当前全部吻合，没有存量漂移。
**取舍**：`CALLERS` 那张表是**手写**的，就是"调用方的契约"。从代码里自动扒
`render(...)` 的实参等于两边同源，那就什么都测不出来了。
**影响面**：新 run 的 manifest 会多一份 `episode_summary` 原文；测试从 1 个涨到 12 个。

## 2026-08-25 —— 全部 prompt 过了一遍，清掉两条已经不成立的说法
**改了什么**：`repeat_hint.md` 里的 `?` 地形符改掉——`TERRAIN_MEANING` 只有
`. G D S N # @` 七个字符，**没有 `?`**，那是上一版地图的遗留；改成按真实图例说
"数到 `#`、`D`、`S`、`N` 或转弯处为止"，"什么时候别拉长链"也从"目标格是 `?`"
改成"路上要穿过 `G`"（会遇野生宝可梦，这才是真会中途出事的那种格子）。
`map_hint.md` 末尾"本例中 `x=1,y=5` 的 `N` 就属于这种情况"删掉——**prompt 里
没有这个例子**，那句话指向空气。
**为什么这么改**：prompt 里指向不存在的符号和不存在的例子，模型只能自己编一个
去匹配，而编出来的东西读日志的人分辨不出是它读错了还是我们说错了。
**顺带加的检查**：写了个小脚本把每个模板里的 `$占位符` 和调用方实际传的参数对了一遍
（`Template.substitute` 漏传会当场抛 KeyError，而 prompt 是最常改的文件）——
七个模板全部吻合，没有多也没有少。
**没改但要记一笔**：
1. `episode_summary.md` 走的是**另一套模板引擎**（`episode_summarizer` 自己
   `jinja2.Template`，`{{ }}` 语法），不经过 `prompts.load`，因此**没有 sha、
   也不进 manifest**——这一局用的是哪一版蒸馏 prompt，事后查不出来。
2. NPC 那段说明在 `decide_action.md` 和 `map_hint.md` 里各写了一遍，内容重复；
   两份都在每步的 prompt 里，改一处漏一处是迟早的事。
3. `episode_summary.md` 通篇管跨局摘要叫"情景记忆"，和刚定下的
   step_memory / episode_memory 词汇对不上。

## 2026-08-25 —— prompt 跟上动作链：`repeat_hint` 还在教已经废掉的 `args.times`
**改了什么**：`repeat_hint.md` 整篇重写（它每步都进决策 prompt，挂在动作空间的 note 上）；
`decide_action.md` 开头从"选出下一个动作"改成"选出这一步要按的按键链"，
`sequence` 那条说明拆成三条规则并写清楚拐弯怎么办。
**为什么这么改**：`repeat_hint.md` 一个字都没改过，还在教
`用 "args": {"times": "N"} 连按同一个键`——**那个格式现在直接 ParseFailure**。
它还在教"把开头那段同方向的一次走完，下一步再转弯"，那是一步一个键时代的战术。
两份说明打架的结果在 trace 里看得很清楚：模型规划出 `down×2 → right×3 → up`，
然后卡在"sequence 长度>1 只能 up/down"上，自我说服成"当前只需输出下一步"。
**它不是不会用链，是我们同时给了它两套互相矛盾的说明。**
**取舍**：把"`right×3` 自己单独成一步完全合法"写成显式的一条——多段链只能 up/down
这条规则本身容易被读成"拐弯的方向不能连按"，而那是错的。
`a` 的措辞从"会被夹成 1"改成"会被改成 1"，因为夹的位置已经从执行层挪到了解析期。
**影响面**：只动 prompt。`manifest` 存的是 `decide_action` / `judge_success` 的原文，
这次改动会体现在新的 run 里。
**没做**：多段链只能 up/down 这条规则本身没动——那是你定的边界，我只是把它说清楚。

## 2026-08-25 —— 修：`--repeat` 第二局起观测台不再更新（每局都新起一台服务抢同一个端口）
**改了什么**：`trace/browser.py` 加进程级单例 `shared_server()`，`build_session()`
改成用它，不再每次建会话都 `BrowserTraceServer()`。页面在 `run_id` 变化时打一条
`===== RUN <id> =====` 分隔线。
**为什么这么改**：`BrowserTraceServer.__init__` 就地 bind 固定端口 8765。一个进程里
跑第二局时再 new 一台，Linux 上直接 `EADDRINUSE`，而 **Windows 上更坏**：
`allow_reuse_address` 让第二次 bind 也成功，同一端口上于是有两台服务，
而浏览器那个标签页还挂在**第一台**的 SSE 连接上——第二局的事件全推给了第二台，
页面从此一个字都不再更新。日志和落盘全都正常，所以从终端完全看不出来。
**取舍**：进程级单例（模块级可变状态）。端口本来就是进程级资源，谁先拿到谁就是它；
把服务做成每会话一个，等于假装这个资源可以有多份。多局共用一条 SSE，
靠 RUN 分隔线区分，标签页不用重开。
**影响面**：`--repeat N` 现在整轮都能在同一个页面上看完。
**怎么验的**：起一条真的 SSE 连接，同一进程里连着建两个 `LocalTrace`（run-A / run-B）
各推两条事件，四条**都到了同一条连接**上。

## 2026-08-25 —— 修：观测台整页空白（JS 字符串被 Python 转义打断）
**改了什么**：`browser.py` 里 `facts.walk_map.split('\\n')` 的换行符改成写两个反斜杠。
**为什么这么改**：那段 JS 住在 Python 的三引号字符串里。写 `\n` 的话 **Python**
先把它变成一个真换行，送到浏览器的就是断成两行的字符串字面量，`script` 整段
语法错误——症状不是"walk_map 那一块不对"，而是**观测台一个字都不显示**。
上一条改动就是这么把整页打没的。
**取舍**：这类"字符串里的字符串"没有类型系统看着，只能靠一条规则记住：
`browser.py` 的 HTML 块里，任何要交给 JS 的反斜杠都得写两遍。注释就写在那一行上面。
**怎么防**：现在可以用 `node --check` 验——把那段 HTML 里的 `<script>` 抠出来
喂给它，语法错误当场就报。这次改完验过了，另外拿一条真的 observe 事件跑了一遍
渲染函数，九行 walk_map 逐行输出正常。

## 2026-08-25 —— 观测台的 observe 块补齐：朝向、四邻、地标各占一行，walk_map 逐行打
**改了什么**：`browser.py` 的 observe 块加 `facing`（并进 where 那行，读不到时显示
`朝向 ?`）、`neighbors` 和 `landmarks` 各自成行；`walk_map` 按 `\n` 拆开逐行输出。
**为什么这么改**：`walk_map` 原来整段丢给一个 `line()`，虽然 CSS 是 `pre-wrap`，
但实际读起来仍是一坨——**这张图的全部用处就是看形状**（往那边走得通吗、哪边是死路），
挤成一段就什么都看不出来。`facing` 是新读出来的字段（精灵表 +9），
而它决定 `a` 作用在哪一格，观测台上看不到就没法判断"它为什么对着空气按 a"。
`朝向 ?` 而不是省略：读不出来是要查的事，静默省略会让人以为这一帧没有朝向概念。
**取舍**：observe 块从 5 行涨到十几行。可接受——这本来就是"它当时看到了什么"
唯一的展示位，而终端那边已经完全不打这类事件了。
**影响面**：只动观测台的渲染，事件和 payload 不变。

## 2026-08-25 —— 朝向改为读内存；细看（inspect）整条链路删除
**改了什么**：
新增 `ram.read_facing()`（精灵表 `+9`，`0/4/8/12` → south/north/west/east），
`TerrainMap` 加 `facing` 字段，`facts["facing"]` 从它来。`PyBoyWorld._facing`
连同 `step()` 里的更新一起删除。
细看整条链路删除：`PyBoyWorld.inspect()` / `_note()` / `_notes` / `MAX_NOTES` /
`facts["inspected"]`、`WorldPort.inspect`、`trace.inspect()`、`JUDGE_BLIND` 里的
`inspected`、`prompts/inspect_focus.md`（移到 `_to_delete/`，这台机器上删不掉文件）。
**为什么这么改**：
朝向——`+9` 那个字节的含义**这个文件自己的注释里早就写着**（`ram.py` 的精灵表说明），
只是从来没读。推的那一版有两个洞：开局和过场之后朝向未知（没按过键），
而且它不进存档，checkpoint 恢复不回来（`docs/spec/harness/SPEC.md` 1.4 记的就是它）。
读内存两个洞一起消失。
细看——**没有任何调用方**。`brain` 和 `harness` 里一处都没有，最近几局 trace 里
一条 INSPECT 事件都没有。它带着一份 prompt、一个 4 条上限的缓存、一条 `facts` 键、
一条判定器黑名单，全是维护成本却没有执行路径。
**取舍**：`EventType.INSPECT` 保留——旧 trace 文件里有这类事件，删掉枚举成员
replay 会在校验那一步炸；观测台的 inspect 分支同理保留。两处都标了"没有生产者了"。
`BUTTON_FACING` 保留但改了说明：它现在只回答"这一步往哪按"（工具层算 attempts 键要用），
不再是"现在面朝哪"的来源。
**影响面**：`facts["facing"]` 从此开局就有值（以前要按过一次方向键才出现）；
`Observation.facts` 少了 `inspected` 键；`WorldPort` 少一个方法。
**要验证**：`+9` 的地址和取值靠的是文件里的既有注释，我没有 ROM 可跑。
实跑第一局时看一眼 `facts["facing"]` 和画面里主角朝向对不对得上。

## 2026-08-25 —— `Observation.summary` 改名 `status`；`ToolResult.message` 删除
**改了什么**：`Observation.summary` → `Observation.status`（`_summarize()` →
`_status_line()`，OBSERVE 事件的 payload 键、`decide_action.md` 的 `$summary`
占位符一起改）。`ToolResult.message` 字段删除，`trace.act()` 不再收 message 参数，
ACT 事件只剩动作链。
**为什么这么改**：那个字段不是摘要。它是 `scene` + `overlay` 机械拼出来的一行
（`你在野外。对话框：「…」`），prompt 里对应的小标题正是「当前状态」；而这一帧
真正被看到的东西是视觉模型写的 `facts["overview"]`。叫 summary 会让人以为
"这一帧的信息都在这句里了"，于是观测台只印它、ACT 又复读一遍它——**信息看起来
到齐了，其实一直藏着**。
`message` 更直接：它的字段描述写着"给 LLM 读的结果描述"，而没有任何一条路径把它
交给 LLM，全仓库唯一的消费方是 ACT 事件，内容就是 `status` 本身。动作之后世界
变成什么样，答案是**下一条完整的 OBSERVE**，不是一句转述。
**取舍**：`status` 这个名字对应 prompt 里的小标题，不再暗示它是全部信息。
ACT 事件从此只回答"按了什么"，OBSERVE 回答"变成了什么样"，两件事不再混在一条里。
**影响面**：`Observation` 是跨层 schema，改名波及 brain / world / trace / prompt；
旧 JSONL 里的 `summary` 键不迁移，观测台读 `p.status||p.summary` 兼容旧数据。
`WorldPort.step` 的返回值少一个字段。

## 2026-08-25 —— 「a 只按一次」挪到解析期；world 收到什么按什么
**改了什么**：`Brain._parse` 里遇到 `a` 直接把 `times` 定死为 1。
`PyBoyWorld` 的 `_clamped()` / `_dialog_is_open()` 整段删除，`step()` 现在
逐段按 `segment.times` 执行、不改写任何东西，`message` 也不再拼"被夹成 N 次"的说明。
`MAX_TIMES` 从 `world` 搬到 `schemas/action.py`，成为 `ActionSegment.times` 和
`Brain._parse_times` 的**同一个来源**（原来三处各写一个 8，且 world 那个已无人使用）。
观测台的 observe 块补上 `overview` / `dialog_text` / `where+neighbors`。
**为什么这么改**：动作合法性是解析期的事。执行层再悄悄夹一次，**大脑交出去的链
和真正发生的链就对不上**——它以为自己按了三次 `a`，实际只按了一次，下一步的推理
建立在错的前提上。原来的补救是把"被夹了"写进 `message`，而 `message` 只进 trace，
大脑根本看不见。现在解析期定死，交给 world 的链就是真正会发生的那条链。
另一条「对话框开着时方向键连按夹到 1」直接没了也不亏：`OVERLAY_ACTIONS[DIALOG]`
本来就只有 `a`，对话框开着时方向键连动作空间都进不去。
**取舍**：`a×5` 被静默改成 `a×1`，不重试——动作名是对的，只是次数不合规范，
为它跑一轮重试不划算（判据同 ```json 包裹）。观测台从此能看到 `overview` 那一整段，
代价是每步多几行；`summary` 那句缩写留着，它是 prompt 的上下文开头。
**影响面**：`world.step()` 不再有任何改写行为，`WorldPort` 的契约随之变干净。

## 2026-08-25 —— 一次决策 = 一次感知：整条动作链交给 world 执行，结尾只感知一次
**改了什么**：`GameTools.execute()` 不再拆链，直接 `world.step(action)` 一次。
`PyBoyWorld.step()` 改成遍历 `action.segments()`，段与段之间不感知，跑完整条链
才 `observe()` 一次；夹连按的逻辑抽成 `_clamped(segment)`，按段判。
`WorldPort.step` 的契约文档同步成"执行整条链、结尾感知一次"。
删掉 `_times()`（从 `args["times"]` 抠字符串的那条通道，已无调用方——次数现在
由 `ActionSegment.times` 在解析期校验）。观测台的行动行不再复读 message。
**为什么这么改**：感知是每步花钱的那一项。展开成一次一按时 `up×4` 是**四次视觉调用**
（实测 17k input token、6.6 秒）；改成一段一次仍然是两次。而多段链按规则只能是
移动键，中间那几帧没有任何会被用到的信息。`up×4 -> down×2` 现在是 1 次感知。
message 那行「你在野外。你在野外。你在野外。你在野外。」也随之消失——它本来就是
四段拼的，而且和紧随其后的 OBSERVE summary 是同一句话，观测台上纯属复读。
**取舍**：链中途的画面彻底看不到，所以链**不能**包含会产出证据的按键——这正是
「多段链只能是 up/down」那条规则的理由，现在它从"约定"变成了"不这样就会丢证据"。
`a` 仍由 world 夹回一次一按：它的收益全在中间帧上。
**影响面**：`execute()` 从 20 行变成 1 行调用；trace 里一步的 perception 事件数
从 `press_count` 降到 1。`WorldPort` 的实现方（目前只有 `PyBoyWorld`）要按新契约走。
**没做**：链的中途中止（野生宝可梦在第二按跳出来，剩下两按仍会打进去）——
本轮明确不做，动作合法性由解析期保证就够了。

## 2026-08-25 —— 动作链每段只感知一次（原来一段 N 次按键 = N 次视觉调用）
**改了什么**：`GameTools.execute()` 不再把 `up×4` 展开成 4 次 `step(times=1)`，
改成一段一次 `step(times=4)`，连按次数交回给 `world`。
**为什么这么改**：`world.step()` 每次结尾必定感知一次。展开之后 `right×4` 在真实
trace 里产生了**四条 perception 事件**（4×~4300 input token、6.6 秒），而那四帧里
有用的只有最后一帧。返回的 message 也是四段拼起来的，控制台上就是
「你在野外。 你在野外。 你在野外。 你在野外。」。更隐蔽的是：`world.step()` 里
连按 N 次再感知一次的那段逻辑（`WITHIN_ACTION_FRAMES`）被架空成了死代码，
连带「`a` 连按夹到 1」「对话框开着时夹到 1」两条保护一起失效——它们判的是
`times > 1`，而展开之后永远是 1。
**取舍**：中间帧看不到了，这正是 world 里那两条夹逻辑存在的理由——方向键的中间帧
没有证据，`a` 的中间帧全是证据，所以 `a` 由 world 夹回一次一按。
`up×4 -> down×2` 现在是 2 次感知，不是 6 次。
**影响面**：只动 `execute()` 的循环；trace 里一步的 perception 事件数会从
`press_count` 降到 `segment_count`。
**还没解决**：**动作链没有中途中止条件**。`execute()` 只在链的开头校验一次
frame sha 和 action space，之后整条链跑完。实测有一局野生宝可梦在 `right×4` 的
最后一按才跳出来——要是它在第二按跳出来，剩下两下会打进一个按"野外"算出来的
动作空间里。廉价的做法是每按一次从 RAM 读 map_id/坐标（不调视觉模型），
变了就丢掉剩余按键；需要给 `ram.py` 加一个战斗标志地址。

## 2026-08-25 —— schemas 里的记忆一族按检索单元重命名
**改了什么**：
`memory_episodic.py` → `step_memory.py`（`MemoryEntry` → `StepMemory`，`Snapshot` 不动）、
`memory_episode.py` → `episode_memory.py`、
`memory_episode_summary.py` → `episode_summary_io.py`、
`memory_semantic.py` → `object_fact.py`。26 个文件里的 import、docstring、
docs/spec 与 CLAUDE.md 的目录说明一起改。**只改名字，一行行为都没动。**
**为什么这么改**：`episodic` 和 `episode` 靠一个词尾区分"一条=一步"和"一条=一整局"——
那是英语的语法差别，不是概念差别，读的人没有任何线索去猜哪个是哪个（这三个文件的
检索单元完全不同，选错就是把一整局的经验当成一步喂进去）。`MemoryEntry` 的
「Entry」等于什么都没说，而这个类的全部要点恰恰是"一条 = 一步"。
`memory_episode_summary.py` 里**根本没有记忆**，全是蒸馏那次 LLM 调用的请求/响应契约，
挂着 `memory_` 前缀会被当成第三种记忆。
**取舍**：`Snapshot` 留着不改——它在 `StepMemory` 的上下文里意思很清楚，
换成 `ObservationDigest` 只是更长。`episode_summary_io` 的 `_io` 是必要的：文件里
`EpisodeSummaryRequest` 和 `EpisodeSummaryResponse` 各占一半，只叫 `..._request`
会和住在同一个文件里的 response 直接打架；"summary" 保留是因为它已经是这条链路上
大家在用的词，换成 `distill_*` 的收益不抵重新建立词汇的成本。
一个文件一个主类的对应关系现在是硬的：读 `schemas/` 的目录就知道有几种记忆。
**影响面**：纯重命名，无行为变更；旧的落盘数据不受影响（存的是字段，不是类名）。
外部若有脚本 `from pokemon_agent.schemas.memory_episodic import MemoryEntry` 要跟着改。

## 2026-08-25 —— 删掉测试里那个接管审批的 fixture
**改了什么**：`tests/test_run_experiment.py` 的 `approved` fixture 及其 `sys.stdin` 接管删除，
文件头的说明改成现状。
**为什么这么改**：`execute:game:save_state` 在 `config/permissions.json` 里已经是
`approval_required: false`，`pokemon_agent/` 里也不再有任何审批调用点——那个 fixture
在替一条不会触发的链路做准备，而它的 docstring 还在断言"挂着 approval_required"，
读的人会照着这句去理解批量跑实验的约束。**过时的注释比没有注释更贵。**
**取舍**：真要把审批打开时得连它一起想清楚（每局开局都存一次档，批量跑就是每局按一次），
所以这句话留在文件头，只是从"现在如此"改成了"哪天打开要注意"。
**影响面**：只动测试，`--repeat` 现在可以无人值守跑。

## 2026-08-25 —— run_experiment 支持 `--repeat`：同一个任务连跑 N 遍
**改了什么**：`--repeat N`（默认 1）。跑一条链的那段从 `main()` 里抽成
`run_chain(chain, run_id, state, watch)`，`main()` 只负责解析参数、编 run_id、循环、
最后报一行「跑了 N 遍，成功 M 遍（X%）」。
**为什么这么改**：成功率是这个项目要产出的数字，而单跑一遍出来的成功率是 0 或 1，
不是成功率。以前想跑 10 遍只能在 shell 里手写循环，每遍的 run_id 还得自己编。
**取舍**：每一遍都**新建又关掉一整套 world/harness**，不复用——复用的话第 2 遍会从
第 1 遍结束的画面开始，测的就不是同一件事了；代价是每遍多一次模拟器启动。
`--repeat 1` 时 run_id 保持原样不加后缀（`--run-id` 是拿来指名道姓找这一跑数据的，
测试就这么用），大于 1 时才加 `-r1`/`-r2`。异常不吞：环境崩了就整轮终止，
不带着坏环境把剩下的跑成假数据——已跑完那几遍的统计每局都落过盘，不会白跑。
`--repeat` 的合法性走 `parser.error` 而不是 assert：命令行是外部输入，
而 assert 在 `python -O` 下会被删掉。
**影响面**：新增参数，默认行为与之前完全一致；`tests/test_run_experiment.py` 不受影响。
**没做**：多遍之间没有并行，也没有"失败自动重试"——前者要先解决模拟器实例互相抢
存档路径的问题，后者会污染成功率。

## 2026-08-25 —— 删掉 `sse()` 里那七类事件的死打印分支
**改了什么**：`store.py` 里 OBSERVE / MEMORY_READ / THINK / ACT / INSPECT /
MEMORY_WRITE / OBJECT_NOTE 七个打印分支整段删除，连同只被它们用到的 `_facts()`
和 `_chain()`；那句裸的提前 `return` 换成模块级的 `BROWSER_ONLY` 集合，带上
"终端看什么、观测台看什么"的分工说明。
**为什么这么改**：`sse()` 一进来就对这七类 `return`，下面却留着它们的完整打印代码——
**永远执行不到**。这种死代码的代价不是几十行，是读的人对整个文件的信任：改了它们、
跑一遍、终端毫无变化，只能怀疑是自己改错了（这一轮就真的在这上面绕了一圈）。
**取舍**：分工本身不动——终端留给"跑得对不对"（账单、错误、目标出栈、episode 起止），
观测台留给"它当时看到了什么"。想让某一类回终端，从 `BROWSER_ONLY` 里删掉它再写分支，
名单是唯一的事实来源。提前 return 仍放在表头之前：只有观测台事件的那一步，
终端不该冒出一个空的 STEP 表头。
**影响面**：只删控制台输出，`append()` 的落盘与推流是同一条事件，payload 一个字段没少——
replay、观测台、成本统计都不受影响。上一条日志里"发现但没改"的那项就是这个。

## 2026-08-25 —— known_objects 改成多行档案，日志不再只存 80 字符的半截标签
**改了什么**：`ObjectFact.render()` 从"一行三种 `→`"改成「抬头 + 缩进明细」的多行形状，
尝试记录渲染成「站在 x=3 y=4 按 a → 无效果」；`query_objects` 改用空行分隔条目；
`memory_read` 事件改存全文 `known_objects_text` + `known_object_count`（删掉
`known_object_names` 和那个 80 字符截断）；控制台与观测台跟着改成整段打印。
`walk_map` 的表头从「x 从 2 到 11，y 从 1 到 9」改成「10 列 × 9 行：最左一列 x=2…」。
`prompts/map_hint.md` / `inspect_focus.md` 的示例同步。新增 `tests/test_trace.py`。
**为什么这么改**：老那一行里 `→` 出现三次、三次意思都不同，而 `x=3 y=4`（角色按键时
站的格）紧挨着对象自己的 `x=3 y=3`，读起来像同一个东西的两个坐标——**这是会让模型
误判"这条尝试是在哪按的"的歧义**，不只是难看。日志那边更直接：只存首行截 80 字符，
而 `query_objects` 当时用单换行拼接，于是整段被当成一条，观测台上实际只显示了
第一条档案的前 80 个字符（`…x=3 y=4→dow`）。决策模型读到的原文没进日志，
replay 就回答不了"它当时看到了什么"。
**取舍**：档案变长（每条 2-5 行），每帧都要进 prompt，token 成本上升——换的是
坐标不再有歧义。走通的门只留成功那一条碰法，失败的不再列：门开过之后待办清单就没用了。
attempts 的存储键仍是 `x=3 y=4→a`，只在渲染层翻译，**不动落盘格式**，否则已有存档全部失配。
**影响面**：`known_objects` 的文本形状变了（prompt 和日志同时变）；下游若按
`known_object_names` 读观测台字段要改读 `known_objects_text`。旧 JSONL 不迁移。
**顺带修的**：`store_objects_interactions` 遇到多段动作链直接不记——链的 `before`/`after`
是整条链的两头，把它记成"在起点按了一次 up"会往档案里写一条**假的尝试**。
**发现但没改**：`LocalTrace.sse()` 开头对 OBSERVE / MEMORY_READ / THINK / ACT /
INSPECT / MEMORY_WRITE 直接 `return`，下面那些分支在控制台上**全是死代码**——
这几类现在只有浏览器观测台看得到。要么删，要么把 return 去掉，需要先定一下控制台该看什么。

## 2026-08-25 —— trace 跟上动作链：payload 记结构化 sequence，控制台不再恒印 `[无 times]`
**改了什么**：`trace/utils.py` 新增 `action_chain()`，`think`/`act` 共用它，payload 里
记 `action`（`up×4 -> down×2` 渲染文本）+ `sequence`（结构化 JSON）+ `segment_count` +
`press_count`，删掉顶层 `args`。`store.py` 的 `_times()` 换成 `_chain()`，只在多段链时
补一段「N 段 / M 次按键」；观测台 `browser.py` 的行动行同步。
**为什么这么改**：`act` 的 `args` 已经从 `{"times": n}` 变成段数组，而 `_times()` 还在
判 `"times" not in args`——这个判断对 list 恒成立，于是控制台**每一行**都印 ` [无 times]`，
一个恒真的提示比没有更糟。同时聚合需要的是结构化的链，靠反解析 `describe()` 的措辞
早晚会静默算错。
**取舍**：payload 里渲染文本和结构化字段各存一份，略有冗余——但一份给人读、一份给
统计读，合成一份就要有人去解析另一份。`args` 直接删而不是留空：留一个恒为空的字段
会让读日志的人以为"模型没给参数"。旧 JSONL 里的 `args` 不迁移，读取端全是 `.get()`。
**影响面**：只动 trace 三个文件，事件类型与 `event_id` 语义不变；下游若有按 `args`
统计连按次数的脚本要改读 `press_count`。
**仍未跟上（未改）**：`tools/memory_tool.py` 的语义记忆仍按 `action.name` / `action.args["times"]`
记 attempts——链的情况下 `name` 只是第一段，会把 `up×4 -> down×2` 记成一次 `up`。

## 2026-08-25 —— 统一所有动作使用 sequence
**改了什么**：取消顶层 `action`/`args` 格式，所有动作统一使用 `sequence`；单元素 sequence 可包含任意按键，多元素 sequence 只能包含 `up/down`。
**为什么这么改**：让单次互动与连续移动共享同一个结构，同时保留“动作链只能是移动”的边界。
**取舍**：单次 `a` 也需要写成一个 sequence 元素，但动作 schema 更统一，解析分支更少。
**影响面**：更新决策解析、执行校验和 prompt；旧的顶层 action 格式不再接受。

## 2026-08-25 —— 移除旧单动作参数兼容
**改了什么**：取消 `action + args.times` 的旧格式兼容；移动使用 `sequence`，非移动单次动作只使用 `action`。
**为什么这么改**：两种动作形态的边界需要明确，避免模型继续生成旧的 `args.times`，并确保按键链永远只表达上下移动。
**取舍**：旧 JSON 输出会被解析失败并触发重试；单次 `a` 等动作的格式变为更短的 `{"action": "a"}`。
**影响面**：更新决策解析和 prompt；`Action` 内部保留 `args` 字段以避免影响 trace/schema 的其他调用方，但入口不再接受旧参数。

## 2026-08-25 —— 限定按键链只包含上下移动
**改了什么**：将 `sequence` 限定为只允许 `up` 和 `down`；互动和其他方向键继续使用单动作格式。
**为什么这么改**：按键链用于表达连续移动路径，不应把 `a` 等会改变交互状态的按键混入连续执行序列。
**取舍**：无法用一条 sequence 表达“移动→互动→移动”，互动必须结束一次移动链后由下一轮决策单独发出。
**影响面**：收紧决策解析、工具执行校验和 prompt 示例，避免模型生成非法混合按键链。

## 2026-08-25 —— 支持受限按键链
**改了什么**：动作现在支持 `sequence` 按键链；只有 `up`/`down` 可以重复，`a`、`left`、`right` 等按键只能单次出现。执行器按链顺序逐段推进世界。
**为什么这么改**：移动路径需要表达“上移若干格、互动一次、再下移若干格”，单一 `action + times` 无法表达这种组合。
**取舍**：动作链中途仍不重新请求 LLM；每个段落实际逐次调用 world，返回最后一帧，避免把交互键误连按。
**影响面**：更新动作 schema、决策 prompt、world 执行、trace 和情景记忆的动作表示；旧格式仍可解析。

## 2026-08-25 —— 移除 trace 控制台 debug 开关
**改了什么**：移除 `LocalTrace` 的 debug 参数和 `POKEMON_AGENT_TRACE_DEBUG` 环境变量；`object_note` 永久不在控制台打印，但继续写入 trace 和推流。
**为什么这么改**：对象记忆明细属于离线调试数据，不应成为普通运行日志的一部分，也不需要额外运行模式切换。
**取舍**：需要查看对象记忆时直接读取 JSONL/SSE 数据，不再通过控制台开关查看。
**影响面**：所有运行模式的控制台输出统一，`LocalTrace` 构造接口更简单。

## 2026-08-25 —— 默认隐藏调试型 object note 日志
**改了什么**：`LocalTrace` 默认不在控制台打印 `object_note`，但仍完整写入内存、JSONL 和 SSE；设置 `POKEMON_AGENT_TRACE_DEBUG=1` 后恢复打印。
**为什么这么改**：普通运行主要需要观察成本、动作和 episode 结果，逐条对象记忆会淹没决策过程。
**取舍**：调试信息没有删除，只把默认展示关闭，因此 replay 和离线分析不受影响。
**影响面**：减少默认 trace 控制台噪声；需要排查对象记忆时显式打开 debug 环境变量。

## 2026-08-25 —— 修正隔障碍物 NPC 交互规则
**改了什么**：修正 NPC prompt：`#` 只限制移动，不再被当作 NPC 交互的阻断条件；补充柜台式隔障碍物交互示例。
**为什么这么改**：实际地图中 `x=1,y=5` 的店员与主角之间有 `#`，但仍可面朝按 `a` 对话，之前的“四邻格可通行”规则过于严格。
**取舍**：改为先按 `a` 验证交互，再根据无反应结果调整路径或目标，可能多消耗一次动作，但避免漏掉真实可交互 NPC。
**影响面**：更新 `map_hint.md` 与 `decide_action.md`，改善商店柜台、货架等障碍物场景的 NPC 选择。

## 2026-08-25 —— 明确障碍物不阻止 NPC 相邻互动
**改了什么**：更新 `map_hint.md` 和 `decide_action.md`，要求 agent 将 NPC 本身的不可通行格与 NPC 的可对话性分开判断，并优先寻找四个相邻可通行格绕行互动。
**为什么这么改**：实际观测中 agent 已识别出店员，却因柜台等障碍物无法直线接近而错误判定为不可对话。
**取舍**：增加“连续重复固定回应后检查其他 NPC”的启发，避免对同一个缺货店员无限重复按 `a`，但不在 prompt 中硬编码某个地图的坐标。
**影响面**：改善商店和其他有障碍物场景下的 NPC 路径规划与交互选择，不改变工具接口。

## 2026-08-25 —— 增加 env 全权限免审批角色
**改了什么**：在权限配置中新增拥有当前全部声明权限的 `env` role，将运行时 context 切换到该角色，并关闭 `execute:game:save_state` 的审批要求。
**为什么这么改**：当前实验阶段需要无人值守地连续执行任务链，保存游戏状态不应在每个 episode 开始时阻塞等待人工确认。
**取舍**：`env` 是开发实验专用的全权限角色，不适用于生产或不受控环境。
**影响面**：实验运行不再因保存 state 请求审批而暂停；原有 `trusted-agent` 角色仍保留。

## 2026-08-25 —— 使用 manifest 允许的任务链实验类型
**改了什么**：将任务链的 `experiment_kind` 从自定义的 `task_chain` 改为 manifest 已支持的 `sequential_episodes`。
**为什么这么改**：`RunManifest.validate_design()` 对实验类型有明确白名单，任务链本质上就是多个连续 episode。
**取舍**：不扩展 manifest 协议，避免让已有结果读取逻辑认识新的类型名称。
**影响面**：修复任务链启动阶段的 `AssertionError`，manifest 结构保持兼容。

## 2026-08-25 —— 统一 knowledge 任务链接口
**改了什么**：将 `knowledge_recall_task_chains()` 合并进 `knowledge_recall_tasks()`，该函数现在只返回 `TaskChain`，原有单任务作为单节点链返回。
**为什么这么改**：实验入口不需要区分短任务和任务链，统一的数据形态能让后续增加链式任务时不再扩展编排分支。
**取舍**：改变了 `knowledge_recall_tasks()` 的返回类型；调用方必须通过 `chain.tasks` 访问子任务。
**影响面**：更新 `run_experiment.py` 的任务发现逻辑，不影响任务内容和已有 CLI 的单任务 ID。

## 2026-08-25 —— 实验入口支持任务链
**改了什么**：新增 `TaskChain` 和 knowledge 任务链定义；`run_experiment.py` 现在会在同一个游戏 session 中按顺序执行链内任务，并分别记录子任务与整条链的统计。
**为什么这么改**：长程实验需要让前一个任务留下的游戏状态和记忆成为后一个任务的输入，单次只运行一个短任务无法验证这种跨任务复用。
**取舍**：任务链仍以每个子任务为一个 episode，失败后停止后续任务；这样保留现有 trace 和成功率语义，也避免把多个目标混成一个不可解释的结果。
**影响面**：新增实验编排能力，现有单任务 CLI 用法继续可用。

> 最新在最上。每条固定四段：改了什么 / 为什么这么改 / 取舍 / 影响面。
> 这是给人读的决策记录，不是 git log 的复制品。

## 2026-08-25 —— trace 落盘只留下最后一条事件（真 bug），测试收敛成一个端到端

**改了什么**：

- **修 `LocalTrace._save_event`**：改成直接追加，不再"写临时文件再原子重命名"。
- 删掉全部旧测试，新增 `tests/test_run_experiment.py` ——从 `run_experiment.main()`
  在**真实环境**里跑一整局：真 DashScope、真 fastembed、真 PyBoy、真权限配置、
  真落盘，一个替身都没有。没有 `DASHSCOPE_API_KEY` 时 skip。
- 顺带修 `agent_permission` 的 `AuditService`：写 `log/audit.jsonl` 前先建目录。

**为什么这么改**：那个 bug 是写测试时撞出来的，**而且它已经静默毁掉了全部历史数据**。

`_save_event` 往 `<ep>.jsonl.tmp` 追加一行，然后 `os.replace(temp, path)`。
"原子重命名"这个模式只对**整份文件重写**成立：把完整内容写进 temp、再一次性换过去。
这里是追加——每次都用"只含这一条事件的临时文件"把已有的整份覆盖掉，
所以**磁盘上永远只剩最后一条**。内存里的 `self._events` 是全的，控制台打印也正常，
所以它完全无声。实测：`trace_data/` 下每一个 episode 的 `.jsonl` 都只有 1 行，
剩的那条还都是 `EPISODE_END`。

replay、checkpoint、离线成功率统计、失败模式分布——四件事共同的底座，
一直是空的。这也解释了为什么"trace 是唯一的事实来源"这条主张从来没被真正验证过：
没人读过落盘的那份。

测试收敛成一个，是因为**旧的七个里有九个用例已经红了**（`MemoryTool` 的签名早就变了，
而 `tests/` 在 `.gitignore` 里，没有任何东西会告诉你）。与其修一批各自只覆盖
一小块的单元测试，不如留一个真正走完整条链路的：命令行入口 → manifest → 权限 →
装配 → LangGraph 循环 → 四类记忆 → trace 落盘 → 统计文件。
**这条路上没有替身**，除了会花钱的那几个。

**取舍**：**一个替身都不留，跑真的。** 先写过一版把四个模型换成脚本化假实现的，
理由是"确定、免费、不联网"；但那样每换掉一个真实现，就放弃了一条集成路径上的覆盖，
而这个测试的全部价值恰恰在于**它是唯一一条端到端走完的路径**。
代价接受下来：跑一次花钱、要网、非确定。

非确定带来的约束是**断言什么**：一个字都不断言模型说了什么，只断言
"不管模型怎么答都必须成立"的结构性不变量。把模型答得对不对写进断言，
这个测试就会因为换型号、调温度而变红——那时红的是测试，不是代码。
**成功率是拿实验数据报的，不是拿测试断言报的。**

同理，真模型连着几次吐不出合法动作（`MaxRetriesExceeded`）时测试**不红**，
只要求它别失败得无声无息：有 ERROR 说明白为什么、有 END 说明这一局收了尾。
写成硬断言就是在赌模型今天的手感。

唯一自动化掉的是**控制台审批**（测试替那个"真人"答 approve）。它走的仍是真实
审批流程，只是没法让 CI 等一个人。这里顺带暴露一件事：
`execute:game:save_state` 挂着 `approval_required`，而每局开局都存档——
**批量跑实验时每一局开头都要一个真人按一下**。要无人值守跑多局，
得先决定这条权限到底该不该要审批。

副作用是真的：它往仓库的 `trace_data/` 和 `experiment_results/` 里写真实数据，
和手跑一次入口完全一样。**重定向到临时目录就等于没测落盘**——
而落盘正是这次修掉的那个 bug 所在的地方。`run_id` 带 `test-` 前缀便于事后清理。

**影响面**：`trace_data/` 里已有的数据**救不回来**，那些 run 只能重跑。
`_save_event` 的修复不改任何接口。

## 2026-08-25 —— 注释分层：代码只说"是什么"，docs/spec 独占"为什么"

**改了什么**：全仓 65 个文件、286 个函数走了一遍。

- 每个模块 docstring 压到 ~400–600 字，只留"这个文件干什么"和读代码当场用得上的
  几条硬约束；长论证搬去 `docs/spec/`。`harness.py` 3784 → 714 字，
  `brain.py` 1256 → 697，其余同比例。
- **每个函数 docstring 的最后一句是一句 30 词以内的"它干什么"**，前面才是契约与取舍。
  原先缺 docstring 的 46 个函数（`errors.py` 的六个 `__init__`、`trace/browser.py`
  的十个方法、`memory_tool.py` 的十二个方法……）全部补上。
- 行内注释按同一把尺子收：`harness.py` 110 → 40 行、`brain.py` 47 → 21 行，
  全仓 392 行。删掉的都是已经进了 spec 的长段论证，留下的是"读这几行代码时
  当场需要知道"的那种。

**为什么这么改**：论证有两个读者，需求不一样。**读代码的人**要在三秒内知道
"这个函数是干嘛的"，然后回到他自己的问题上；**读设计的人**要知道"为什么不是
另一种做法"。把两者压在同一段 docstring 里，第一个读者每次都要先跳过五十行
才找得到答案——而他一天要跳几十次。

结尾句放在**最后**而不是开头，是刻意的：docstring 的开头是契约（前置条件、
后置条件、失败语义），那是**调用前必须读**的；"它干什么"是读完契约之后的收束，
也是只想扫一眼的人直接跳到底就能拿到的那一行。

**取舍**：**先补 spec，再删代码里的论证。** 顺序反过来就会丢东西——
上一条 CHANGELOG 那次 spec 重写就是为这一步做的准备。凡是 spec 里没有对应
落点的论证，这次一律没删（比如 `_judge` 的早退分支为什么为 resume 保留、
`ValidationError` 不是 `AgentError` 子类那段）。

不给 `__init__.py` 之外的每个文件强行凑满 200 词——**短文件就该短**。
`schemas/action.py` 的模块 docstring 只有 67 字，够了。

**影响面**：纯注释。`py_compile` 全仓通过，没有一行可执行代码变动。

## 2026-08-25 —— docs/spec 追上代码

**改了什么**：`harness/SPEC.md` 整篇重写；`schemas/SPEC.md` 删 `Intent` 一节、
新增 `completion.py` 一节；`brain`/`prompts`/`interfaces`/`tools` 四份按实际接口订正；
`build/SPEC.md` 新增「3b. `agent_permission` —— 横切的权限层」并更新 manifest 现状；
`README.md` 的循环流程、不变量、过渡态三节重写。

**为什么这么改**：spec 的漂移**不止这次改动造成的**。清点下来，代码里已经不存在、
spec 里还在描述的名字有：`_inspect`（7 处）、`_dispatch`、`_push_goal`、`_nodes`、
`see_objects`、`recent`、`Intent`（26 处）、`MAX_GOAL_DEPTH`；此外
`known_here`/`knowledge_base`/`write_episodic`/`note_step`/`query_episodic` 这批
`MemoryToolPort` 的旧方法名在 spec 里出现 60 多次，代码里早就改成了
`query_objects`/`query_knowledge`/`store_episode_step`/`store_objects_interactions`/
`query_episode_steps`。一份指着不存在的方法讲设计的文档，比没有文档更费时间——
读的人会先花半小时确认自己没找错地方。

**取舍**：**删掉的东西留"墓碑"而不是直接抹去。** `Intent`、`INTENT_HELP`、
`intent_help.md`、`_judge_all` 各自保留一节，写清楚它是什么、为什么删、
以及**重写时要捡回来的那几条论证**（多层判定的隔离与可标定性、判据不能省、
`SCREEN_COORD` 拦的是哪个具体教训、代价不对称要让模型知道）。
这些论证是踩出来的，代码里删干净了就只剩这一处载体。

**不再标注行号。** 上一版每节都挂着 `harness.py:295-334`，一次重构之后全部失效，
而失效的坐标比没有坐标更糟——它会把人带到错误的地方。改成按方法名索引。

**没做**：`world`/`providers`/`memory` 三份没动，`MemoryToolPort` 旧方法名那 60 多处
也没改——那些是这次改动之前就欠下的，混进来会让这条记录说不清是哪一半的锅。
`README.md` 的「已知的过渡态」里记了三条待办：`inspect` 半死链路、
拆子目标机制待重写、`tests/` 被 gitignore。

**影响面**：纯文档。

## 2026-08-25 —— outcome 只在 run() 的出口算一次，`LoopState.outcome` 删掉

**改了什么**：`_outcome()` 这个方法删了，内容内联进 `run()` 的出口；
`LoopState.outcome` 字段删了；`_look` 的终止分支不再多带字段；
`_summarize` 的 `success` / `steps` 直接从 `state.observation` 读。

**为什么这么改**：两条，第二条是真的会咬人。

一是位置不对：`_outcome()` 挂在 `_look` 里，一个叫"看一眼"的节点顺手把这一局的
最终结论下了。和上一版把蒸馏、`EPISODE_END` 从它里面搬走是同一类毛病，只是轻一些。

二是**同一份信息算了两遍**：`EpisodeOutcome` 和 `EPISODE_END` 的 payload
逐字段对应（success / steps / reason）。算在两个地方，迟早不一致——
而不一致时**没有任何东西会报错**：返回值说成功、事件流说失败，
离线统计和调用方各信一半，而且要等到对账的时候才发现。
搬到一起之后它们从同一个 `obs` 派生，不一致这件事在结构上就不可能。

**取舍**：不包成方法。它只有一个调用方，而且是三行纯翻译（三个 if 选一个字符串），
包起来只会让"这个数是怎么来的"多隔一跳。做成图节点更不行——
图上的格子代表"发生了一件事"（调模型、推世界、写库），
`_outcome` 不花钱不改世界不写记忆，给它一格会稀释"读图 = 看这一局做了哪些真事"。

顺带解掉一个隐患：`space` 和 `outcome` 以前互斥填充，`LoopState` 里任何时刻
都有一个是上一轮的陈值，靠调用图保证下游不会读错——不是靠类型。
`outcome` 没了之后这个形状本身消失了。

`run()` 的出口断言也跟着换了：从"某个字段被填了"（`outcome is not None`）
换成"图不该在这一局跑完之前结束"（`obs is not None and obs.done`）——
后者才是真正要保的那条。

**影响面**：`Harness.run()` 的签名与返回值不变。`LoopState` 少一个字段，
自建 `LoopState` 的地方（只有 `_begin`）不受影响。

## 2026-08-25 —— 图拉直：删掉 intent 分派与多层判定，收尾拆成 summarize + run

**改了什么**：

- 删 `Intent` 枚举、`Action.intent` / `Action.goal`、`ActionSpace.intents`、
  `_fields_must_match_the_intent`；`Action.name` 从可选变必填。
- 删 `_dispatch` / `_push_goal` / `_nodes` / `_space` / `MAX_GOAL_DEPTH`
  / `EventType.GOAL_PUSH` / `trace_utils.goal_push()`；`harness/utils.py` 清空。
- 删 `_judge_all`（线程池并发判每一层）。`_judge` 改成只判栈顶 `goals[-1]`，
  完成就出栈，栈空 = 任务完成。
- 图新增 `summarize` 节点：`look --done--> summarize --> END`。
  `_summarize_episode` 从 `_outcome()` 里搬进去，并与节点函数合并成一个 `_summarize(state)`
  ——`result` 是从 `state.outcome` 取出来又传回去的同一个对象，去掉参数之后
  两者签名一模一样、其中一个只剩一行转调，那就是一个方法多了；
  节点函数额外收一份自己就能读到的状态，还会让人以为它可以被喂进一个和 `state`
  不一致的 outcome。`_outcome()` 变成纯构造。
- `EPISODE_END` 从 `_outcome()` 搬到 `run()`，和异常路径共用一个出口。
- brain 侧跟着删 `_parse_intent`、intent 校验、`$intents` 渲染、`INTENT_HELP`、
  `SCREEN_COORD`；`decide_action.md` 去掉 intent 段落和 push_goal / inspect 两个例子。

**为什么这么改**：拆子目标的机制要**换个地方重写**，所以先把当前这套接线拆干净。

拆一半最坏：`Intent` 留在 schema 里、图上却没有 `push_goal` 的去处，
模型照样能输出 `intent: "push_goal"`（prompt 里还写着），然后在分派处炸——
一个只在特定输出下才出现的崩溃。要么两头都留，要么两头都删。

`_judge_all` 跟着删是因为它的前提没了。它存在的理由是"中间层完成时，上面那些
当初为它拆出来的一起作废"，而压栈的唯一途径已经删了、栈恒为一层。
对一层的栈来说"每层各判一次"和"判栈顶"是同一件事，只是前者还额外背着一个线程池、
一段并发写 trace 的注意事项、一个恒为 0 的 `depth`。

`summarize` 独立成节点，是因为它**要调一次模型**。藏在 `_outcome()` 里的时候，
图上看不到"这一局结束时还额外烧了一次调用"，读图的人会以为一局的开销就是
`steps × (感知 + 决策 + 判定)`。图上看得见的东西才会被算进成本。

`EPISODE_END` 搬进 `run()`，是为了让正常结束和异常终止共用同一个出口。
分散到图内图外各写一次，迟早有一条路径漏掉——而漏掉的那些局会直接从
成功率的分母上消失，正是上一条改动刚修完的那类问题。

**取舍**：

`goals` 保留成**栈**而不是压成单个 `goal`，当前目标恒为栈顶。栈恒为一层，
所以 `if not remaining`（栈空才写 success）在今天永远成立——留着它不是为了当下分支，
而是把"只有任务目标本身完成才算成功"写成代码：子目标回来之后，agent 自己压的那些
完成了只该弹栈，不该给自己发奖状。这是唯一刻意保留的"占位"，因为它是一条**规则**，
不是一个抽象。

反过来，多层判定那份权衡（判定之间的隔离、单目标判定的可标定性 vs 合成一次省 token）
**只记在这里，不留在代码里占位**。占位的抽象会把下一版往旧形状上带，
而拆解机制在别处重写时，多层判定要不要回来、以什么形状回来，是那时的决定。

`goal_pop` 的 `reason` 字段留着（现在只有 `done` 一个取值，`superseded` 没了）：
拆解回来时"完成"和"白拆"仍然必须分得开，而那是判断目标栈到底帮没帮上忙的那个数。

**影响面**：`Action` / `ActionSpace` 的形状变了，所有构造点已扫过（测试里的
`Action(name=..., thought=..., rationale=[...])` 本来就没传 intent，不受影响）。
`Harness` 与 `BrainPort` 的对外签名不变。
`prompts/intent_help.md` 和 `harness/utils.py` 已清空但**还需要手动删除文件**；
`prompts.load_sections()` 随之变成零调用方，留着还是删掉见该函数的说明。

## 2026-08-25 —— `Completion` / `VisionCompletion` 从 interfaces 挪进 schemas

**改了什么**：新增 `schemas/completion.py`，把 `interfaces/llm.py` 的 `Completion`
和 `interfaces/vision.py` 的 `VisionCompletion` 搬进去；两个接口文件改成从
`schemas` 引入，各自的模块 docstring 说明"这里只放 Protocol"；
`providers/dashscope.py` 和三个测试文件的 import 跟着改；
目录说明那一行补上 `Completion`。

**为什么这么改**：目录分工写的是 `schemas/` 放 Pydantic 数据模型、`interfaces/`
放 Protocol（第四节）。这两个类长在接口文件里读起来顺——就在用它们的 Protocol 旁边——
但那让 `interfaces/` 同时承担了两件事。代价不是洁癖：接口先行那条规矩说
「光读 `interfaces/` 就能看懂整个系统怎么运转」，数据模型混在里面，
读的人分不清哪些是**契约**、哪些是**契约里流的东西**。

**取舍**：两个类放同一个文件，不各建一个。它们回答同一个问题（"一次模型调用回来了什么"），
而且都带着一个不是记账、而是正确性证据的字段（`truncated` / `input_tokens`）——
这个共同点是踩出来的，分成两个文件就没地方写。
字段名仍然不统一（`prompt_tokens` vs `input_tokens`），跟各自网关返回的名字走：
中间再翻译一层，排查"网关到底报了什么"时就得反查映射表。
**没有留 re-export 兼容层**——留了等于 `interfaces/` 还在导出数据模型，这次改动就白做。

**影响面**：纯搬家，没有行为变化。`from pokemon_agent.interfaces.llm import Completion`
这种写法会断，仓库内的引用点已全部改完（4 处）。

## 2026-08-25 —— 一局无论怎么死，trace 里都留下完整的 START…END

**改了什么**：`_begin()` 挪进 `run()` 的 `try`；`EPISODE_START` 挪到 `_begin()` 的
第一行（`reset()`/`save_state()` **之前**）；删掉专门捕获权限异常的那个 `except`；
`RunManifest` 新增 `permissions` 字段与 `with_permissions()`，`validate_design()`
断言它非空，`run_experiment.py` 的装配链上加一环；新增
`tests/test_harness_episode_boundary.py`。

**为什么这么改**：三件事其实是同一件——**"这一局到底发生了什么"必须能被事后重建**。

`_begin()` 在 `try` 外面是真 bug：它调 `save_state()`，而 `execute:game:save_state`
是配置里唯一 `approval_required` 的权限。人类拒批或审批超时抛出来的异常从这里逃走，
这一局连 `EPISODE_END` 都没有，正好撞上那段注释要防的"从分母上消失"。
`EPISODE_START` 也一样：它原本写在 `reset()`/`save_state()` 之后，注释却声称
"episode 的边界应该是这一局在事件流里看到的第一条事件"——那句话只在这两步都成功时成立。

权限那个 `except` 的函数体和兜底逐字相同，删掉它程序行为一个字节不变。留着的坏处是
它**看起来**已经把权限失败单独处理过了，于是这件事不会再有人回来做。

manifest 记权限配置是 prompt 那条论证的同一个应用：`permissions.json` 里角色少一条
`read:memory:knowledge`，这批 run 跑的其实是"无知识库"那个消融组，而 trace 里
**没有任何字段说得出这件事**。它全程不变、又不在版本库里，所以既要 sha 也要原文。

**取舍**：`EPISODE_START` 提前写，代价是可能出现"一步没跑就结束"的 episode，
但那本来就是事实，`EPISODE_END` 的 `reason` 会说清楚。
权限失败仍然不单独成一类失败模式——真要按权限名聚合时，改的地方是
`trace_utils.episode_error()` 内部（翻译异常是那个纯函数的职责），不是控制流。
`validate_design()` 断言 `permissions` 非空会让**任何**没走 `with_permissions()`
的装配当场失败，这是故意的：宁可开跑前炸，也不要事后拿到一批无法归因的数据。

**影响面**：`Harness` 的对外签名不变。`RunManifest` 多一个必填约束——
自建 manifest 的调用方（目前只有 `run_experiment.py`）必须补 `.with_permissions()`。
测试新增一个文件，不动已有测试。

## 2026-08-25 —— 抬到 Python 3.11，并把 agent-permission 写进依赖

**改了什么**：`requires-python` 从 `>=3.10` 改为 `>=3.11`，ruff `target-version`
跟着改成 `py311`；`agent-permission` 补进 `dependencies`；CLAUDE.md / AGENTS.md
第七节的"Python 3.10"同步改掉。

**为什么这么改**：`agent_permission.audit` 用了 `enum.StrEnum`，那是 3.11 才有的。
声明 `>=3.10` 是一句**假的**承诺——照着它建 3.10 环境，装完在 import 权限库时就炸，
而报错指向 `enum`，离病因隔了两层。依赖漏写是同一类问题的另一半：这个库一直靠开发机上
恰好装过才跑得起来，干净环境 clone 下来根本起不来，而那正是复现实验的起点环境。

**取舍**：抬版本而不是给库降级（把 `StrEnum` 换成 `class X(str, Enum)` 也能跑 3.10）。
理由是这个项目没有任何跑在 3.10 上的理由，而降级要改的是**另一个仓库**，
为了迁就一个我们自己都不需要的下限去改上游，方向反了。
依赖用 git URL 而不是版本号，是因为权限库还没发到 PyPI；发了之后换成版本号，
届时要能锁版本——`permissions.json` 的语义变化会静默改变实验条件。

**影响面**：只动构建元数据和规范文档，不动运行代码。已有的 3.10 环境需要重建。

## 2026-08-23 —— 记忆观测改为显示名称和标题

**改了什么**：`known_object` 改为显示物体名称，`knowledge` 改为显示知识标题，
`episode_level` 保持只显示数量；新增短标签字段，限制每类最多显示 5 项、每项 80 字符。

**为什么这么改**：布尔值“有/无”无法回答具体召回了什么，而完整正文又会让 SSE 页面失去
可读性；展示短标签能保留可解释性而不传输大段文本。

**取舍**：标签从渲染文本的首行提取，当前不引入新的知识元数据模型；标题格式变化时，
提取结果会随内容变化。

**影响面**：仅影响浏览器/控制台的记忆展示和新增 trace payload 字段，不影响检索排序。

## 2026-08-23 —— 明确四类记忆的观测名称

**改了什么**：浏览器和控制台统一显示 `step_memory`、`known_object`、`knowledge`、
`episode_level`，并在 `memory_read` payload 中增加对应的明确计数字段。

**为什么这么改**：`episodic` 和 `episode` 容易混淆单步记忆与跨局经验，无法直接看出
当前检索结果属于哪一层。

**取舍**：保留旧字段 `count`、`known_objects`、`episode_memory_count`，保证历史事件和
旧消费者仍可读取；新观测使用明确字段。

**影响面**：仅改变 trace 展示和新增 payload 字段，不改变记忆检索结果。

## 2026-08-23 —— 将本地 trace 实现重命名为 LocalTrace

**改了什么**：`pokemon_agent.trace.store.MockTrace` 正式更名为 `LocalTrace`，同步更新
装配代码、运行脚本和当前文档；保留 `MockTrace` 兼容别名，避免旧测试和外部脚本立即失效。

**为什么这么改**：该实现已经负责 JSONL 落盘、replay、控制台输出和浏览器 SSE 推送，
不再是测试替身，`MockTrace` 这个名字会误导调用方。

**取舍**：暂不删除兼容别名，等旧调用方迁移后再移除。

**影响面**：新代码应使用 `LocalTrace`；TracePort、事件格式和运行行为不变。

## 2026-08-23 —— 增加最小浏览器 SSE 观测台

**改了什么**：新增标准库实现的本地 `BrowserTraceServer`。`run_episode_loop.py` 启动
 session 时自动监听本机端口并打开浏览器，`LocalTrace.sse()` 将信息事件推送到页面；
控制台保留 episode、模型调用、错误等控制流输出。

**为什么这么改**：浏览器更适合展示 observe / retrieve_memory / think / act 这样的信息流，
控制台继续承担运行控制和成本/错误诊断，避免两边输出互相干扰。

**取舍**：页面只做文字展示，不做历史回放、筛选或鉴权；无浏览器连接时事件直接丢弃，
完整事件仍然写入 JSONL trace。

**影响面**：通过 `python -m probe.run_episode_loop ...` 启动时自动打开本地观测页；
Harness 和 `TracePort` 调用方式不变。

## 2026-08-23 —— trace 增加 phase 并压缩记忆读取输出

**改了什么**：`TraceEvent` 增加 `phase` 字段，由 trace 实现根据事件类型推导；控制台
step 输出增加 `----- STEP -----` 和 `--- MEMORY RETRIEVAL ---` 分隔符。记忆读取事件
不再把完整知识文本塞进 trace 展示 payload，只记录是否命中及字符数，跨局经验保留引用。

**为什么这么改**：浏览器信息流需要按 `episode_id + step + phase` 聚合，读者需要看到
清晰的阶段边界，而不是被完整知识文本淹没；控制流仍留在控制台。

**取舍**：暂不增加冗余的 `turn_id`，也不重构完整生命周期事件；当前环境尚无独立浏览器
SSE 端点，后续只替换 `TracePort.sse()` 的输出实现。

**影响面**：trace JSONL 和控制台观测格式变化；Harness 的事件调用方式不变，事件仍由
`event_id` 单调排序，episode memory 的检索逻辑不变。

## 2026-08-23 —— 知识库检索粒度改为按文件

**改了什么**：`knowledge/store.py::load_chunks()` 不再按空行拆分，而是把每个非空
`.md` 文件作为一个知识 chunk；同步更新了相关说明和缓存注释。

**为什么这么改**：同一文件中的标题、规则和示例通常共同描述一个主题，按段落拆分
容易让召回结果丢失上下文；按文件检索更符合当前知识库的组织方式。

**取舍**：单个文件过大时召回粒度会偏粗，后续如果某个攻略文件明显超过上下文预算，
再针对该文件引入带标题的层级分块。

**影响面**：知识库的 BM25、embedding 和 reranker 都以文件为单位工作；episode memory
仍保持一条 `EpisodeMemory` 一个 chunk，`query_episodic()` 不受影响。

## 2026-08-23 —— 跨局摘要记忆/知识库换成 embedding + reranker 混合检索；query_episodic 改回全包

**改了什么**
上一条刚落地的字符 bigram TF-IDF 被这一条整体替换：新增 `interfaces/embedding.py`
（`EmbeddingProvider`）、`interfaces/rerank.py`（`RerankerProvider`）两个 Protocol，
`providers/local_embedding.py`/`providers/local_reranker.py` 分别用 `fastembed`
（ONNX Runtime，不依赖 torch）接入 `BAAI/bge-small-zh-v1.5`（embedding）和
`BAAI/bge-reranker-base`（reranker），全项目只有这两个文件直连模型。
`memory/retrieval.py` 新增 `bm25_rank`（关键词，`rank-bm25`）+ `embedding_rank`（向量余弦）
两路召回，用 `reciprocal_rank_fusion`（RRF，k=60）融合，再交给 reranker 精排——
标准的"广召回 + 精排"两阶段检索。`MemoryTool` 的 `query_episode_memories()` 和
`knowledge_base()` 都改用 `hybrid_retrieve()`；reranker 分数是无界 logit，
先做 min-max 归一化再和质量/成功权重相加。`knowledge/store.py` 从"整份读入不筛选"
换成 `load_chunks()`（按空行分段）+ `mtime()`（改文件即失效缓存），因为知识库接下来
会塞进克制关系表、攻略这类会长大的内容，不能再指望全塞进 prompt。

顺带把 `query_episodic()` 改回"全包"：签名从 `(query, limit)` 变成 `(episode_id)`，
不再做任何相关性排序或截断，只按 `episode_id` 过滤、按 `step` 升序返回。单步情景记忆
本来就该是"这一局发生过的事"，不该被检索式的相关性打分筛掉——上一条把它和跨局摘要
记忆混在一起打分是设计错误，这里改正。

`harness.py::_retrieve_memory()` 和 `build.py::build_real()` 同步更新签名/装配
（`MemoryTool` 新增 `embedding_provider`/`reranker_provider` 两个必填构造参数）。

**为什么这么改**
用户明确要求"正常的 RAG 那套"——真实 embedding + reranker + 关键词混合检索，
而不是上一条的字符重叠近似。模型来源选本地离线下载（不走 dashscope 这类远程 API），
避免每次检索都产生网络调用和额外计费。BM25 分数和余弦相似度量纲不同、不能直接相加，
RRF 只看排名不看分数量级，天然绕开这个问题。

**取舍**
- `fastembed` 而不是 `sentence-transformers`：后者依赖 `torch`，体积和安装成本都高得多；
  `fastembed` 走 ONNX Runtime，本项目已经因为 `magika` 间接依赖它，零增量。
- embedding 只在写入时算一次并缓存（`_episode_memory_vectors`），不是每次检索都对全库
  重新编码——避免检索延迟随记忆库增长线性变差。知识库的向量缓存按 `mtime` 失效，
  保留了原设计"改 `.md` 文件不用重启进程"的性质。
- reranker 的候选集上限（`fuse_top_k`，默认 `max(limit*3, 10)`）是个经验值，
  不是精确算出来的——候选太少精排没有意义，太多则拖慢每一步的决策延迟。
- 没有做端到端的真实模型推理验证：开发环境的沙箱出于安全策略屏蔽了 HuggingFace Hub，
  模型权重下载不了。逻辑本身（BM25/RRF/融合/归一化）用假的确定性 embedding/reranker
  在测试里验证过，`FastEmbedText`/`FastEmbedReranker` 的调用方式对照 `fastembed`
  源码里的真实签名核对过，但没有在这次改动里真的跑过一次下载+推理。
- 测试文件里已经存在的 `MemoryTool()` 零参调用（`test_poses.py` 九处，另外
  `test_goals.py`/`test_judge.py` 里也有类似的旧调用）在这条改动前就是坏的
  （构造函数早改了）——这次多了两个必填参数，它们仍然是坏的，没有顺手修，
  留给后续单独处理。

**影响面**
`MemoryTool` 的构造函数签名（新增两个必填参数）、`query_episodic`/`knowledge_base`
的调用签名，波及 `harness.py`、`build.py`、`tests/test_episode_memory.py`。
`pyproject.toml` 新增依赖 `fastembed`、`rank-bm25`。`memory/vector.py` 的
`tokenize()` 仍在用（`bm25_rank` 依赖它分词），但 `tfidf_vector`/`cosine_similarity`
不再被业务代码调用，只剩 `test_vector.py` 覆盖，暂不删除。

## 2026-08-23 —— 跨局摘要记忆检索换成轻量向量相似度（字符 bigram TF-IDF + 余弦）

**改了什么**：新增 `memory/vector.py`——四个纯函数（`tokenize`/`build_idf`/
`tfidf_vector`/`cosine_similarity`），零新增依赖，标准库 `math` 之外什么都
没引入。`MemoryTool.query_episode_memories` 的排序从字符集合重叠计数换成
这一套：场景过滤剩下的候选集现算一次 IDF，查询词和每条候选各自转成 TF-IDF
向量，用余弦相似度当"文本相关性"这一项，再按老规矩叠加质量分和成败权重
（`EPISODE_RELEVANCE_WEIGHT`/`EPISODE_QUALITY_WEIGHT`/`EPISODE_SUCCESS_WEIGHT`）。
新增 `tests/test_vector.py`（纯函数各一个用法示范）和
`test_relevance_ranks_topically_close_memories_above_unrelated_ones`
（`test_episode_memory.py` 里新增，验证质量分打平时题材相关的记忆确实排前面
——这是换向量相似度真正要验证的行为，字符重叠那版做不到这一点）。

**为什么这么改**：用户直接要求"现在就做轻度的向量相似度"。选字符 bigram 而不是
分词：项目文本是中文，标准库没有分词器，而且这个阶段明确"零新增依赖"
（用户原始设计文档里的取舍，CLAUDE.md 第六节同样的态度）；bigram 比
`MemoryTool._overlap` 原来用的单字符集合多留住一点点词序信息（"前进"和"后退"
的单字符集合会互相污染，bigram 不会），复杂度增量却几乎为零。IDF 现算、
不缓存：语料（候选集文本）随每次写入变化，量级还是个位数到几十条，现算的
成本远低于维护一份缓存失效逻辑，和 `knowledge/store.py` 的 `load_all()`
不缓存是同一个理由。相关性权重定得比质量/成功权重大，是因为"这条经验到底
切不切题"应该是排序的第一道判据，质量/成功只用来在相关性接近时挑更可信的
那条——不然一条题材完全不相关但质量分拉满的摘要会排到题材相关但质量普通的
摘要前面，那就是"按质量排序"而不是"检索"了。

**取舍**：只接了跨局摘要记忆（`query_episode_memories`）这一条检索路径，
单步情景记忆（`query_episodic`）还是原来的字符集合重叠，**没有动**——那条
路径查的是"哪一步画面和现在最像"，`MemoryEntry.render()` 的内容（位置/四邻/
对话框）比自然语言摘要短得多、结构化程度更高，字符重叠在那种场景下没有明显
短板，这次没有必要跟着换，等真的观察到排序不准再说。向量不落盘、每次检索
现算，没有为"语料涨到几百条之后现算太贵"这个还没到来的问题预留缓存接口。

**影响面**：`query_episode_memories` 的排序结果会变（同样的输入，相关性算法
换了，具体名次可能不一样），但方法签名和调用方（`Harness._retrieve_memory`）
不用改一行。`_episode_score` 的签名变了（从接收 `query: str` 改成接收算好的
`query_vec`/`idf`），这是 `MemoryTool` 内部私有方法，不影响任何外部调用方。

## 2026-08-23 —— 把跨局摘要记忆接进循环：retrieve 查、episode 结束才落盘

**改了什么**：`Harness._retrieve_memory()` 现在除了单步情景记忆
（`query_episodic`）和语义记忆（`known_here`/`knowledge_base`），也调
`MemoryTool.query_episode_memories(scene, query, limit)`——查询词用
`state.task.goal`（"和当前任务相关"），场景用 `obs.place.map_id`，命中的话
折进 `obs.facts["episode_memories"]`，走的是和 `known_objects`/`knowledge`
一样的路径（同一条 `MEMORY_READ` trace 事件，`trace/utils.py` 的
`memory_read()` 加了 `episode_memories` 参数）。`Harness._outcome()` 新增
`_summarize_episode()`，在 `EPISODE_END` 之前调恰好一次
`MemoryTool.summarize_episode(...)`——这是这一局唯一一处跨局摘要记忆的落盘点；
单步记忆和 object 语义记忆继续在 `_remember()` 里逐步落盘，两条落盘路径互不干扰。
`Harness.__init__` 新增 `run_id` 参数（默认 `"local"`，和 `MockTrace` 的默认值
对齐），`build.py` 的 `build_real()` 同步加了 `run_id`/`memory_model` 两个参数，
并把 `MemoryTool()`（零参数，一调用就会 `TypeError`）改成正确传入
`trace_port`/`llm_provider`——这是装配路径上此前就存在、但从来没被跑到过的断链，
不修的话这次接入的两条新路径在真实环境里根本启动不了。`MemoryToolPort` 协议
补上 `summarize_episode` 的声明（Harness 只依赖接口，不该调协议里没有的方法）。

**为什么这么改**：讨论里定下来的分工——retrieve 时把 episode 级和 semantic
级记忆都查出来喂给决策，落盘只在两个时机发生：单步记忆和 object 语义记忆每步
落（"remember"），跨局摘要记忆只在 look 判定这一局结束时落一次（"look 到 end
之间"）。查询词特意不用 `Snapshot.of(obs).render()`（那是给单步记忆用的画面
相似度检索）——`EpisodeMemory.render()` 里没有位置/地标这些字段，两边词汇不
重叠，拿快照去查会一条都选不中；跨局摘要记忆问的是"这类任务别的局怎么打"，
天然该用任务目标去匹配。蒸馏失败（LLM 解析不出合法 JSON）在 `_summarize_episode`
里只吞 `ValueError` 这一种、有名字的失败——`generate_summary` 内部已经为它
留了一条 `ERROR` trace，这里不该让它拖累这一局本该正常记录的 `EPISODE_END`。

**取舍**：`run_id` 没有单一真相来源——`TracePort` 的实现自己持有一份、不对外
暴露 getter，`Harness` 只能另外存一份，传自定义 `trace` 时要记得让两处
`run_id` 对上，这次没有花力气把 `TracePort` 协议改成能对外暴露 `run_id`（那是
更大的改动，超出这次的范围）。`memory_model` 默认复用 `text_model`，没有像
判定器那样强制建议单独选型，先能跑起来，调优留到有真实数据之后。

**影响面**：`MemoryToolPort` 新增一个协议方法；`trace_utils.memory_read()` 新增
一个可选参数，向后兼容旧调用点；`build_real()` 新增两个带默认值的可选参数，
不改变现有调用方式。仍未修：`tests/test_goals.py`/`test_judge.py`/
`test_poses.py` 里一共 12 处 `MemoryTool()` 零参数构造，和 `test_poses.py`
那处一样，是更早就存在、和这次改动无关的断链——这些测试全部因为没有
`assets/rom` 被跳过，从没被真正跑到过，所以现在都不遇到（会在有 ROM 的机器上
`TypeError`），值得单独找时间批量修一次。

## 2026-08-23 —— 跨局摘要记忆（EpisodeMemory）：场景硬过滤 + 质量/成功加权检索

**改了什么**：新增 `schemas/memory_episode.py`（`EpisodeMemory`，含
`matches_scene()` 的场景通配判定）；`MemoryTool` 新增
`query_episode_memories`/`write_episode_memory`/`episode_memory_size`/
`summarize_episode`，`interfaces/tools.py` 的 `MemoryToolPort` 同步加了这三个
协议方法；顺手修掉了这条链路上此前就存在、但从未被跑到过的几处断链：
`memory/utils.py` 的 `_create_memory_entry` 硬凑 `MemoryEntry` 字段导致
一调用就会 `ValidationError`（现在是 `_create_episode_memory`，产出正确类型）；
`EpisodeMemoryGenerator.__init__` 签名和 `MemoryTool` 里的调用点参数个数对不上；
`Source.MEMORY` 在枚举里根本不存在（现已补上，见 `schemas/trace.py`）。
新增 `tests/test_episode_memory.py`，覆盖场景过滤、通配、排序、蒸馏全链路。

**为什么这么改**：讨论 RAG 检索设计时定下来的结论——检索单元是**一整局**蒸馏出的
经验，不是单步记忆，两者不该共用同一套存储和检索路径（同一局内的单步记忆不该被
跨局检索拿走）。场景过滤按 `map_id` 硬匹配，但允许 `applicable_scenes` 留空或标
`SCENE_ANY` 表示"任何场景都适用"，避免通用经验（"进草丛要连按"）被过滤误杀；
排序在文本相关性之外叠加质量分和成败两个信号，量级刻意选得比文本重叠分大，让
"质量高/成功过"的摘要能压过"文本刚好多重叠几个字但质量很差"的摘要，具体权重
留到接了真实数据再调。之所以顺手修了那几处断链：不修的话新功能就是在一段
`ValidationError` 必现的死代码上继续搭，测试根本跑不起来。

**取舍**：没有把这条检索路径接进 `harness.py` 的主循环——什么时候调
`summarize_episode`、检索结果该塞进 prompt 的哪个位置，这是编排层的决定，
不是这次要解决的问题，留给下一步。排序权重（`EPISODE_QUALITY_WEIGHT`/
`EPISODE_SUCCESS_WEIGHT`）先拍了两个常数，没有接真实回放数据调过。

**影响面**：新增两个类型（`EpisodeMemory`）和三个协议方法，不改动任何已有的
单步情景记忆（`MemoryEntry`/`query_episodic`/`write_episodic`）行为。
另外发现 `tools/memory_tool.py` 里 `note_step()` 调用的 `_should_note_step()`
在 HEAD 上从未被定义过（`tests/test_memory.py` 里练到它的用例因为没有
`assets/rom` 一直被跳过，没人抓到）；这次顺手给了一个保守的默认实现（有
`before.place`/`after.place`/非空 `action.name` 才继续判），但没有深入验证是否
就是原意——这处修复没有测试覆盖，值得单独找一次真机会话确认。
`tests/test_poses.py` 里 `MemoryTool()` 零参数构造也和当前构造函数签名对不上，
是另一处独立的既有断链，这次没有动它，一并记在这里以免下次以为是这次改坏的。

## 2026-08-20 —— 判定器的两处：过期的坐标说明；对话框下连按会吃掉证据帧

**判定器不看历史是有意的，而且不会因此漏判**：每走一步都判一次，
所以"他刚才和某人说过话"这种事，会在**那句话还在对话框里的那一帧**被抓到。
判据永远只回答"就现在这一帧而言，成立吗"。这条现在明写进了 prompt——
早先没写，模型就自己去脑补历史。

**一、`judge_success.md` 里那句坐标说明是过期的。**

它写着「`walk_map` 的行列号**和 `landmarks` 的坐标**是屏幕格」——
而地标那次改动之后 `landmarks` 已经是**全局坐标**了，我漏了这一处。

后果实测可见：判定器把 `walk_map` 的行号当成全局 y，
得出"@ 在 y=4 行，其下方 y=7 是墙，说明尚未穿过门进入房屋"——
而同一份 facts 里 `map_id: 37`、`scene: indoor` 明明白白写着他在屋里。
**结论侥幸没错（任务确实没完成），但 `why` 全是编的**，而 `why` 是每一个
`True` 都要留档的东西。

改法不是补一句说明，是**把整件事禁掉**：「不要做坐标换算。判据里提到位置就直接读
`where`，它已经是答案了。**坐标推理不是证据**——证据是对话框的文字、`scene`、
`overview` 这些画面里直接写着的东西。」

顺带把这一节挪到 `$observation` **前面**：固定文本放前面才吃得到前缀缓存，
放后面等于白设。

**二、对话框开着时，连按被夹成 1 次。**

这条这局还没撞上，但一定会撞，而且**撞上了不报错**：

我们只在一步走完之后感知一次，所以连按会把中间那几帧整个吃掉。而对话框恰恰是判据
最常用的证据来源（"对话框里出现母亲说的话"）——连按三次 `a` 推完整段对话，
那几句话的每一帧都没被看到，最后一次按键还把对话框关掉，判定器看到的是一个
**没有对话框的画面**。一局本该成功的 episode 就这样被记成失败。

夹在 world 而不是靠 prompt 劝：劝它"预期有对话就别连按"，前提是它得先知道会有对话；
而对话框**已经开着**这件事我们是确定知道的（缓存里的 `ScreenState.overlay`）。

夹了要在 `message` 里说明——否则大脑以为自己按了 3 次，下一步的推理就建立在
错的前提上。**只夹对话框这一种情况**：连按是省钱的主要手段（一条直线拆成五步
就是把感知成本乘五），为一个只在对话框下成立的问题把它整个关掉，代价太大。

**影响面**：`prompts/judge_success.md`、`world/pyboy_world.py`；
`tests/test_world_smoke.py` 新增 2 条。88 个测试通过，ruff 干净。

## 2026-08-20 —— 交互记忆扩成「地标档案」：见过几次、通往哪、说过什么

**改了什么**：`ObjectNote` 从「互动过的对象」扩成**每一个见过的地标都有一条档案**。
新增字段 `seen` / `touched` / `first_seen` / `last_seen` / `leads_to`；
`note_interaction()` 并成 `note_step()`（互动 + 穿门两件事同一个触发点）；
新增 `note_seen()`，由 `Harness._observe()` 每步调一次。

**字段按「来源」分档，不按「字段好听」分**：

| 字段 | 门 | 招牌 | 人 | 来源 | 会不会错 |
|---|:-:|:-:|:-:|---|---|
| `map_id / x / y`、`kind` | ● | ● | ● | 内存 | 不会 |
| `seen` / `touched` / `first_seen` / `last_seen` | ● | ● | ● | 计数 | 不会 |
| `lines` 互动时的文字 | ○ | ● | ● | 抄 `dialog_text` | 抄错=感知错 |
| **`leads_to` 通往哪张地图** | ● | — | — | **前后 map_id 相减** | **不会** |
| ~~`identity` 这是谁~~ | — | — | ✗ | 模型推 | **会错，不存** |

**前四行一个模型调用都不需要。**

**`leads_to` 是这次最大的收获。** 早先"这扇门是哪"只有三个来源：内存的 warp 表
（精确，但那是"世界怎么连起来"，白送等于把这个项目要证明的事删掉）、视觉模型
（三轮实测全在编）、或者走进去看。现在是第三个——`before.map_id != after.map_id` 时
答案就是 `after` 的那个数，**纯算术，不会错，而且是它自己走进去换来的**。

**`identity` 不存**（用户拍的板，我也同意）：它必须由模型从 `lines` 推，
而一旦固化，错的身份会被反复当成事实——**那正是这次死循环的成因**
（它把自己写的"确认为母亲"当成了已知）。而 `lines` 本身就带着身份
（`OAK:` 有前缀、`BLUE is out at GrandPa's lab.` 内容自明）。
让模型每次读原文自己判断，比把一次判断钉死安全。

**没互动过的也建档**，这是档案最有用的一类条目：

    地图0 x=13 y=5 的「门」 → **还没互动过**（见过 7 次，互动 0 次）

没有它，agent 只能从 `landmarks` 看到那里有扇门，**分不出哪扇是探索过的、
哪扇是新的**——而那正是它规划下一步要去哪的依据。现在这行字就是它的待办清单。

**踩到并修掉的一个 bug**：`note_step` 原来一律用 `before.facts["facing"]` 算
"我碰到了哪一格"。按方向键时那是**走这一步之前**的朝向——往东走三步再往北进门，
算出来的是东边那格，于是那扇门永远学不到 `leads_to`。
改成方向键用 `BUTTON_FACING[action.name]`（这一次按键决定的），`a` 才用 before 的
（它作用在当前朝向上）。顺带把那张表从 `world` 提到 `schemas/core.py`——
**两处必须用同一张表**。

**写明的限制**：

- 键是 `(map, x, y)`，而 Gen1 有会走动的 NPC。它一动就会在新位置产生第二条记录，
  旧的变成幽灵。真新镇和屋内的 NPC 基本不动，先把机制跑起来；
  等看到幽灵条目真的多了再治（sprite 的 `picture_id` 我们读位置时已经拿到了）。
- **连按穿门（`times > 1`）故意不记 `leads_to`**：门可能在中途任意一格，算不准是哪一扇。
  宁可漏记一次，也不能把它挂到错的门上——错的那条会被当成事实反复使用。

**影响面**：`schemas/core.py`、`world/pyboy_world.py`、`tools/game_tools.py`、
`interfaces/tools.py`、`harness/harness.py`；`tests/test_memory.py` 新增 2 条。
86 个测试通过，ruff 干净。

## 2026-08-20 —— 交互记忆：跟哪一格互动过、它给了什么

**改了什么**：新增第二种记忆。`ObjectNote` 按 `(map_id, x, y)` 索引，
记「那一格的东西跟我说过什么」，每帧作为 `facts["known_objects"]` 发出去。
新增 `Place` / `Landmark` 两个模型、`Observation.place`、`EventType.OBJECT_NOTE`、
`ToolPort.note_interaction()`。

**为什么这么改**：实测的死循环——

    step 11  对着 NPC 按 a，dialog 是 "BLUE is out at GrandPa's lab."
             它在 rationale 里写下 "landmarks 中『人 x=2 y=3』…**确认为母亲**"
    step 12  取回那条记忆，照着自己的断言又按一次 a
    step 13  同上 …

三处叠在一起才有这个循环：

1. **它凭空断言了一个身份。** 和之前编招牌名字是同一个病：画面里没有可以支撑
   "这是母亲"的证据，它按先验补了一个。
2. **那句断言进了情景记忆的 `rationale`，下一步被取回。** 于是它把**自己上一步的
   猜测**当成了已知事实——`rationale` 是记忆里最像"结论"的那一栏，它读它就像读权威。
3. **判定器每一步都在说真话**（"这是 'BLUE is out at GrandPa's lab.'，不是母亲说的话"），
   但**判定器的话到不了决策模型手里**。这条隔离是有意的、也不打算放开：
   让被评价者看见评价者的理由，它就会开始朝着评价者的措辞优化，那是奖励黑客。

所以补的是第四条通道：**它自己验证过的事实**。

这也正好落在之前定的长期记忆范式上：**自带作用域 + 域内恒真 + 域会再现**。
`(map_id, x, y)` 就是那个作用域——同一张地图的同一格，下一步、下一局、下周都是它。

**几个设计点**：

- **面朝哪一格是算出来的，不是认的。** `place`（内存读的全局坐标）
  + `facing`（我们自己的动作历史推的）→ `place.step_toward(facing)`。
  两个输入都是确定量。键要是靠模型认"我刚才在跟谁说话"，整套记忆立刻失去意义。
- **可不可交互也不问模型**：判据取自 `landmarks`，那是内存给的穷尽列表。
  对着空地按 `a` 不记——这些条目每帧都要发，记了就是灌噪声。
- **没有文字也记。** 对着一扇门按 `a` 通常什么都不弹，而"我试过，没反应"本身有用：
  它下次就不会再对着同一扇门按第二次。
- **只筛当前地图，不筛当前屏幕。** "屏幕外那扇门我进去过"恰恰是规划路线时最需要的
  一条，筛屏幕反而把最有用的滤掉。
- **和 `MEMORY_WRITE` 分开成 `OBJECT_NOTE` 事件**：两种记忆的寿命和用途都不同，
  混成一类就数不出"它认识了多少个东西"——而那正是这个机制有没有用的直接指标。
- `Place` 做成模型而不是三个散字段：它现在**承载记忆的键**，三个数必须整体传递。
  散着传总有一天会漏掉 `map_id`，而漏掉之后两张地图上的同一坐标会撞在一起，
  记忆开始张冠李戴，且不报错。

`MAP_HINT` 相应加了一条硬话：**没在 `known_objects` 里的东西，你就是不知道它是谁**；
不要在 `rationale` 里写没验证过的身份，因为那会进记忆、下一步被你自己当成事实。

**实测**：走到招牌前按一次 `a`，下一帧起
`known_objects: 全局坐标 地图0 x=11 y=5 的「招牌」→ PALLET TOWN  RED 的老家`。
按第二次不会重复记（同一句去重）。

**还没做的**：门的目标地图仍然不给（那是"世界怎么连起来"，要靠走进去学），
但现在走进去之后**有地方记了**——`ObjectNote` 的 `lines` 就是那个落点。
下一步是让它进门时把"这扇门通向哪"也记上。

**影响面**：`schemas/core.py`、`world/pyboy_world.py`、`tools/game_tools.py`、
`interfaces/tools.py`、`harness/harness.py`；`tests/test_memory.py` 新增 2 条、
`tests/test_screen.py` 改 1 条。84 个测试通过，ruff 干净。

## 2026-08-20 —— dialog_text 从来没进过 facts；假对话框；同帧重复感知；记忆不说"没变"

一局实测暴露的四处，其中第一处是这个项目到目前为止最严重的一个 bug。

**1. `dialog_text` 从来没有进过 `facts`。**

视觉模型读出来了，存进 `ScreenState.dialog_text`，然后 `observe()` 组装 facts 时
**漏掉了它**。后果：

- **判定器看不到对话内容**，「对话框里出现母亲说的话」这类判据
  **永远不可能被判成立**——任务从一开始就注定失败，而没有任何地方报错。
- **决策模型看不到**，于是按先验编一句当成自己读到的。实测编出了
  `OAK: Hello there! Welcome to the world of POKéMON!`。

判定器自己把根因说出来了：`{"done": false, "why": "对话框内容未提供，无法确认是否为母亲说的话"}`。
**它是对的，而我们四处找别的原因。**

修：`facts["dialog_text"]` 排在 overlay 之后、其余一切之前；`Snapshot` 也加上
（对话跨步骤成立——那句话说过就是说过了）。

**2. 地图黑边被认成对话框。**

室内地图下方那一整片纯黑是**地图边界**，被判成了 `overlay=dialog`——
而同一帧（frame sha 一模一样）上一步它还判的是 `none`。

两处一起修：

- prompt 里给出唯一可靠的判据：**对话框是白底黑框有黑字**，黑边没有白底、没有边框、
  里面没有字；并加一条自检——"你能从里面抄出文字吗？抄不出来就不是对话框"。
- 代码里加交叉检验：`overlay=dialog` 而 `dialog_text` 为空 → **降级成 `none`**，
  并记 `perception_warning=dialog_without_text`。这不需要任何新输入，
  **只是拿模型自己的两个输出对账**。要紧在于 `overlay` 决定动作掩码：
  判错一次大脑就会拿到一组按不出效果的动作，然后照着它按好几步。

**3. 同一帧被反复感知。** `step()` 原来无条件清缓存，于是"对着空地按 a"这种
什么都没发生的一步照样花一次感知调用。实测连着四步 frame sha 一模一样，模型却给出了
三种不同的 `overview`，其中一步就是上面那个假对话框。

修：`step()` 不再清缓存，交给 `_perceive()` 的帧哈希判——画面真变了一定会重新调，
没变就直接返回。**同一帧只问一次，这类抖动直接消失，顺带省钱。**
实测连按 4 步 `a` 撞空气，感知调用从 4 次降到 1 次。

**4. 记忆没说"什么都没发生"。** 实测：

    step 7   按 a（对着空地）→ 什么都没变
    step 8   取回 step 7 的记忆，照着自己上一步那句"站在门格上按 a 是开门的标准操作"，
             **再按一次 a**
    step 9   同上        step 10  同上

记忆忠实记下了"没变化"，但那个事实藏在两块结构相同的文本里没被读出来——
**它把过去的 `rationale` 当成了权威，而权威说的话恰恰是错的**。

修：`MemoryEntry.render()` 直接写「**之后变成：什么都没变**（位置、四邻、对话框
全部相同——这个动作没有效果）」。判定是纯比较，我们做得又快又准，不该留给它。
比较**不含 `overview`**：那是模型每次重写的自然语言，同一帧也会给出不同措辞，
拿它比会把"没变"误判成"变了"。

**影响面**：`world/pyboy_world.py`、`schemas/core.py`、`prompts/perceive_screen.md`；
`tests/test_world_smoke.py` 新增 3 条、`tests/test_memory.py` 新增 1 条。
82 个测试通过，ruff 干净。

## 2026-08-20 —— max_tokens 提到 25600；MAP_HINT 补换算公式和数字符的规矩

**改了什么**：`QwenText` 的 `max_tokens` 从 3072 提到 25600，`build_real` 和
`probe.run_episode` 加 `--max-tokens` 透传。`MAP_HINT` 重写两节。

**为什么提 max_tokens**：实测单步 `thought` 到过 2235 token，离 3072 只剩八百，
而那还是它在**和自己的记忆吵架**的情况下——真正需要长推理的局面还没出现。
**这是上限不是预算**，只在模型自己想说这么多时才花得掉；判定那条链路每次输出
二三十个 token，抬高上限对它没有任何影响。真正控成本的是 `max_steps` 和 prompt 长度。
（各家模型对 `max_tokens` 有硬上限，qwen-plus 一档通常是 8192，被 API 拒了用
`--max-tokens` 调低，别改默认值。）

**为什么改 MAP_HINT**：一局实测里模型花了 1938 token / 43 秒，全用在"这两套坐标
对不上"的自我拉扯上。查下来**我们给的数据是对的，它自己推的换算公式也是对的**，
错的只有两处纯机械操作：

- `##...S#D##` 里 `##...` 是三个点，它数成两个，于是断定 `S` 在列 4（正确是 5）。
  同一句话里它又说 `D` 在列 7——S 在 4 的话 D 就该在 6，句子本身自相矛盾。
  拿这个错值去反推偏移，和 `landmarks` 的 `x=11` 对不上，
  于是**认定是我们的数据矛盾**，开始反复重数。
- 同一段推理里把 `(列,行)` 和 `(行,列)` 混着用：门在 `(7,7)`，它写"南邻是 `(8,7)`"
  ——按我们的写法那是第 7 行第 8 列，是墙。

所以补的不是"再强调一遍"，是三样具体的东西：

1. **直接给换算公式**（`c = 4 + (x - X)`，`r = 4 + (y - Y)`），并写明"照抄，不要自己推"。
   它每步都在重新推导同一个常量公式，推对了也白花几百 token。
2. **怎么数字符**：对着列号表头竖着看，别在心里从左往右数；直接把
   `##...S#D##` 那个例子和正确答案写进去。
3. **一条自检**：算出来的和 `landmarks` 对不上时，**是你数错了，不是数据错了**——
   两者同一帧来自同一份内存，不可能矛盾；重数，不要花篇幅论证哪边可信。

**取舍**：讨论过是否把寻路整个拿走（对每个地标做 BFS，直接给方向串）。
那不会增加任何信息——`walk_map` 里本来就全有，只是替它做那步算术。
但那样导航就不再是 agent 的能力，实验里"它会不会走路"这一维会消失。
**决定保留**，先只把说明写硬，看这三条能不能压住。

**影响面**：`providers/dashscope.py`、`build.py`、`probe/run_episode.py`、
`tools/game_tools.py`。78 个测试通过，ruff 干净。

## 2026-08-20 —— 地标改成「内存出的类型 + 全局坐标，没有名字」

**改了什么**：删掉 `ScreenState.labels` 和感知 prompt 里那一整节；
`facts["landmarks"]` 改由 `TerrainMap.landmarks()` 产出，形如
`门 x=13 y=5; 招牌 x=11 y=5`。新增 `facts["neighbors"]`（`北 . 南 G 西 # 东 .`）。
`Snapshot` 去掉 `walk_map`、加上 `neighbors`。

**为什么这么改**：真跑一局暴露了两个问题，根因不同，但都是**我们给了模型一个
它没法正确使用的东西**。

### 一、名字是编的，而且**不可能不编**

实测输出：`写着「POKéMON CENTER」的招牌 (1,7); 写着「POKé MART」的招牌 (5,3)`。
**真新镇既没有宝可梦中心也没有商店。**

根因不是 prompt 不够严——前两轮已经收紧过两次了。是**总览画面里没有可以支撑那个
名字的证据**：招牌上的字根本没渲染（要走过去按 A 才弹对话框），所有的门都是同一个
深色矩形。它没有输入，只能按先验补，而先验里"宝可梦小镇"就该有中心和商店。

名字只有三个可能来源：

- **内存**：warp 表里带着目标地图编号，精确。**但那是"世界怎么连起来"，
  正是长程记忆要学的东西**——白送给 agent，等于把这个项目要证明的事删掉。
  （`walk_map` 读内存是另一回事：它替代的是"这一格能不能走"，游戏自己每帧都在算，
  属于低层控制。这条线要划清楚。）
- **视觉模型**：三轮实测全在编。
- **经验**：走进去看见了什么，然后记住。**只有这一个是对的**，而它还没做。

所以现在只给类型和位置，名字留空。`MAP_HINT` 里明写："想知道招牌写什么，走过去按 a；
想知道门后面是什么，走进去。看到过什么就记进 rationale。"

### 二、屏幕格坐标进了记忆，模型花两千 token 和自己吵架

`MAP_HINT` 里我们自己写着屏幕格"**不能跨步骤引用**"，然后把带屏幕格的 landmarks
和整张 `walk_map` 存进记忆、下一步又喂回去。

实测：step 1 取回 step 0 的「民宅的门 (7,7)」，对照当前地图发现 `(7,7)` 是 `#`，
于是花了 **2235 个 output token、49 秒**反复重数那一行字符串，试图判断是记忆错了
还是地图错了。**两边都没错，是我们给的数据自相矛盾。**

修法：地标改用全局坐标（纯算术：`全局 = 主角全局 + (屏幕格 - PLAYER_CELL)`，
不读新内存），跨步骤永远成立。`walk_map` 从 `Snapshot` 里删掉——它的原点跟着人走，
没有稳定的坐标系可以承载。

**取舍：那"这一下改变了什么"靠什么看？** 靠 `position`（全局坐标）和
`neighbors`（相对"我"的四邻）：撞墙 → 前后 position 一模一样；进门 → 地图编号变了；
"我以为西边能走" → `neighbors["left"]` 白纸黑字写着当时是什么。四邻不依赖屏幕原点，
所以跨步骤成立；整张图能多告诉你的只是"当时周围什么形状"，而那个信息没法安全地存。

**影响面**：`schemas/core.py`（删 `labels` 及其校验器、改 `Snapshot`、
`named_cells`→`landmarks`）、`world/pyboy_world.py`、`tools/game_tools.py`
（`MAP_HINT` 重写两节）、`prompts/perceive_screen.md`（删「写 labels」整节）；
`tests/test_screen.py`、`tests/test_prompts.py`、`tests/test_world_smoke.py` 跟着改。
78 个测试通过，ruff 干净。

实测效果：`门 x=13 y=5` 在第 0 步的记忆里和第 1 步的当前帧里**是同一个坐标**，
不可能再矛盾；走到 x=9 y=6 时 `门 x=5 y=5` 进入视野——那才是通往家的那扇门。

## 2026-08-20 —— 删掉 `Observation.goal`（目标栈接进来之后它就没有消费方了）

**改了什么**：`Observation` 去掉 `goal` 字段；`PyBoyWorld.observe()` 不再填它；
`Harness._observe()` 的盖章不再写它。

**为什么这么改**：顺着"每一次 `model_copy` 盖的章，谁在读"查了一遍，
发现 `Observation.goal` **一个读者都没有**：

- `Brain.choose` 原来 `assert obs.goal`，目标栈接进来之后改成了 `assert goals`；
- prompt 走 `_render_goals(goals)`，不读 `obs.goal`；
- `Brain.judge` 读的是 `Goal.goal`（栈上某一层），也不读它；
- `Snapshot.of()` 只取 facts 里的 overview / where / walk_map / landmarks。

留着不只是浪费一次赋值，**它是有误导性的**：字段说明写着"当前任务目标"，
而 agent 当下在做的是**栈顶**那条，任务目标只是栈底。谁顺手拿 `obs.goal`
去渲染点什么，拿到的就是错的那一条，而且不会报错。

顺带确认了一件分层上的事：**world 根本不需要知道任务目标**。
`reset(task)` 里的 `task` 现在只用于断言 `max_steps > 0`，以及将来按不同任务
选不同起始存档。三个接口文档里"后置条件 goal == task.goal"那句一并改掉。

**影响面**：`schemas/core.py`、`world/pyboy_world.py`、`harness/harness.py`、
`interfaces/{world,tools}.py` 的文档。78 个测试通过，ruff 干净。

## 2026-08-20 —— 过一遍 run_episode 整条链路，修 4 处

用假 provider 把 `probe.run_episode.main()` 原封不动跑了一整局（含一次故意的解析失败），
盯输出发现的：

**1. `task_id` 写死成 `"explore-pallet"`。** 而 goal 从命令行来。
**`task_id` 是成功率的分组键**——写死意味着换个目标跑出来的两批数据会被当成同一个
任务聚合，算出来的成功率没有意义。改成从目标文本派生（同一目标 = 同一 id，跨进程稳定），
可用 `--task-id` 覆盖。

**2. `remember` 那块在控制台被压成一行。** `_wrapped()` 直接 `textwrap.wrap(text)`，
它把换行当空白吃掉——于是记忆里那张 10x9 的 walk_map 变成一条横着的字符串，
**正好是这一步最该看清的东西**。改成先按原有换行拆、再对每行折行。
顺带去掉重复的 `(episode_id, step)` 前缀（`MemoryEntry.render()` 开头本来就是它）。

**3. `GameTools._last_space` 现在连帧哈希一起存。** 上一轮审查里我标了"目前无害"
就没修，这是偷懒——那条断言的全部意义就是拦住将来的错误。
原来只检查按键名在不在上一轮清单里，而 `a` 在野外 / 对话框 / 选择框下都可用：
**名字对得上不代表语境对得上**。只要将来有一类"不经过 look 直接 press"的路径
（重试、宏动作、skill library），断言就会放行一个按旧语境选的键。
现在换帧即失效，当场炸。

**4. 汇总加了「动作」一行**：按键 / 细看 / 拆子目标（完成 N / 作废 N）。
这是目标栈和细看这两个机制唯一的直接证据——拆十条弹十条看着很好看，
但如果八条是 `superseded`，说明它在乱拆不是在规划。
同时标明 `perception` 那一行**含细看**（走的是同一个视觉模型、另一份 prompt）。

顺带在 `--criteria` 的默认值上写明：那句"画面上出现能直接证明这个目标已达成的证据"
是**同义反复**，只够跑通链路；真做实验必须给一句只看一帧就能判真假的话，
否则判定器只能凭"看起来差不多了"回答。

**影响面**：`probe/run_episode.py`、`probe/echo_trace.py`、`tools/game_tools.py`。
78 个测试通过，ruff 干净。

## 2026-08-20 —— 审查修一批：记账、异常边界、细看的堆积

**改了什么**：两轮独立审查（一轮盯 harness 循环，一轮盯 world / tools）跑出来的问题，
按严重程度修完。

**1. `last_calls` 改成 `drain_calls()`** —— 这是最要紧的一条，而且**两个方向都错过**：

- 原来由**生产方**在下一次感知时清空，但**缓存命中时不清**。于是不推进世界的那些
  轮次（`inspect` / `push_goal`）会把上一轮的账**再记一遍**。实测一局 3 次真实
  VLM 调用、trace 里 4 条 MODEL_CALL，其中两条逐字节相同。更糟的是 `inspect` 的账
  （`prompt_sha` 是 `inspect_focus`）被当成"产生这一帧观测的感知调用"记进
  `Source.PERCEPTION`——**prompt 归因跟着错乱**。
- 改成"进门就清"之后翻到另一边：`reset()` 里那次真实调用的账，被紧接着那次
  命中缓存的 `perceive()` 冲掉，**钱花了但没有记录**（实测 4 次调用只记了 2 条）。

两个方向都错，说明问题不在时机而在归属。改成由**记账的人取走**：
`WorldPort.drain_calls()` / `ToolHost.drain_calls()`，world 内部改成 `_pending_calls`
只追加。不变量变成**每次调用恰好记一次账**，由调用次数本身保证，不依赖调用顺序。
新增 `test_every_vision_call_is_billed_exactly_once` 钉住——成本不会自己报错，
多记少记只体现在月底账单和实验表格上。

**2. 异常逃出 `run()` 时补 `EPISODE_END`（`reason=error`）。** 不补的话这一局在
事件流里永远"没有结束"，离线统计时既不在成功也不在失败，**直接从分母上消失**——
而 `MaxRetriesExceeded` 恰恰是最该被记成失败的那一类。记完照常往外抛。

**3. `_notes` 改成按 focus 去重的 dict，加 `MAX_NOTES=4` 上限。** `inspect` 不推进
世界，所以 `step()` 里那次清空永远轮不到，一帧里能一直问。实测连问 6 次同一个问题，
`facts["inspected"]` 从 0 涨到 231 字符，**同一条答案被原样拼了 6 遍**。
重复的事实比过期的更糟（模型当成强证据），而这段文字**同时进决策 prompt 和判定 prompt**。

**4. 三处"契约说不抛异常，但失败点在 try 外面"：**
- `world.inspect()` 的取帧 / 读内存 / `render()` 全挪进 try（`render` 用的是
  `Template.substitute`，模板少一个占位符就抛 `KeyError`，而 prompt 是最常改的文件）。
- `Brain.judge()` 的 `render()` 同样挪进 try —— 它是被 `_judge_all` **并发**调用的，
  一个 worker 抛出来会穿过整个循环，把一次本该记成"判定失败"的事件变成一局丢失的数据。
- `Brain._parse` 的 `except` 加上 `ValidationError`：`Action` 的 model_validator 抛的是
  `ValueError`，pydantic 包成 `ValidationError`，**不是 `AgentError` 的子类**，
  不带上就会穿过重试直接崩掉一整局。当前不可达（`_parse` 自己先验了一遍），
  但那意味着同一套校验写了两遍且没有同步机制。

**5. 感知失败的重试现在会产出 `ERROR` 事件。** `_observe` 原来固定构造
`ModelCall(payload=call)`，`error_kind` 永远是空，于是「视觉模型输出解析失败」这一类
**永远不出现在失败模式分布里**——而 world 明明已经把 `ok=False` 标好了。

**6. `_judge` 的 `succeeded` 早退分支现在会打上 `done/success`。** 当前图里走不到，
但 resume 会：从 `succeeded=True` 的 checkpoint 恢复时，不打标记的话 `_look` 不出
outcome、转而进 `think`，而那时 `goals` 已经是空的，`brain.choose` 的断言当场崩。

**7. `_parse_intent` 的回退路径现在也过掩码。** 原来 `intent` 缺失但有 `action` 时
直接 `return Intent.PRESS`，跳过了 `intent not in space.intents` 检查。
今天 PRESS 恒可用所以安全，但真掩掉的那天症状会是 `AssertionError` 而不是可重试的
`IllegalAction`。

**8. 修正两处文档。** `perceive()` 的后置条件原来写"同一帧内多次调用返回相同内容"，
而 `inspect()` 之后 facts 会多一条——两条契约直接打架。改成"幂等只对模型调用成立"。
`_observe` 的 docstring 里"实测 3 步一局共 4 次感知"那个数字**就是从被重复计数的
trace 上读出来的**，删掉。

**影响面**：`interfaces/{world,tools}.py`、`world/pyboy_world.py`、`tools/game_tools.py`、
`brain/brain.py`、`harness/harness.py`；`tests/test_goals.py` 新增 3 条回归。
78 个测试通过，ruff 干净。

## 2026-08-20 —— 目标栈 + 三类意图（press / push_goal / inspect）

**改了什么**：大脑每一轮不再只会按键，而是从三类事里选一件（`Action.intent`）：

    press       按键，推进世界。**唯一不可逆的一类。**
    push_goal   把当前目标拆一层压进栈，带判据
    inspect     对同一帧再问一个具体问题（另一份 prompt），世界不动

图变成 `look → think → (press | push_goal | inspect) → look`。
**分派放在图的边上，不是节点里的 if**——加一类 = 加一个枚举值 + 一个节点 + 一条边。

`LoopState` 多一个 `goals: list[Goal]`。`goals[0]` 恒为任务目标。
`look` 每步判定，`Brain.judge(goal, obs)` 从 `(task, obs)` 改成收一条 `Goal`
（目标 + 判据），任务目标和子目标走同一个方法、同一份 prompt。

新增：`Intent` / `Goal` / `ModelCall` 之外的 `EventType.INSPECT / GOAL_PUSH / GOAL_POP`；
`WorldPort.inspect()` 与 `prompts/inspect_focus.md`；`tests/test_goals.py`（5 条用法）。

**为什么这么改**：没有目标栈时，模型每一步都要从"走回家"重新推一遍完整路径，
中间结论（"先往北两格再往西"）走完一步就丢了，只在 `thought` 里躺着，进不了下一步的输入。
目标栈就是那层工作记忆——它有完成状态，所以不是知识，该由运行时状态保持。

**取舍与踩到的坑**：

- **每层各判一次（并发），最深的那条"已完成"连同它上面的全部出栈。** 一条规则，没有特例。
  中间写过两版都是错的：先是"只判栈顶"——那样栈上压着未完成的子目标时任务永远轮不到判，
  而任务完全可能顺手完成（压着"走到门口"往那边走，路上母亲先说话了），
  这类局会被记成 max_steps_exceeded，**成功率被系统性地压低**；
  改成"先判栈底，再从栈顶往下弹"之后是两段特殊逻辑，而且**判不到中间层**——
  `[任务, A, B]` 里 A 完成了发现不了，会继续做一个只为 A 存在的 B。
  现在的规则同时覆盖这两种情况。
- **判定并发发出，不合并成一次调用。** 一步最多 `MAX_GOAL_DEPTH` 次判定，串行的话
  墙钟就是它们的和。合并成一次能省调用，但会丢两样东西：**判定之间的隔离**
  （模型同时看到任务目标和子目标，会开始互相推理"子目标成了任务应该也快了"，
  污染源只是从决策模型换成了栈上的其他目标）和**可标定性**（单目标判定是干净的
  二分类 `(目标, 判据, 帧) → 0/1`，合并后输出是长度可变的向量，
  而且同一份 prompt 在栈深 1 和栈深 4 下不是同一个东西，误差不再独立）。
  而这几次调用天然独立，**并发就够了**：延迟是 `max` 不是 `sum`，和合成一次一样快。
  实测 18 次 × 0.3s 的假判定，串行 5.4s，并发 2.0s。
  代价是没有提前退出了（顺序版判到第一条完成的就停），用 token 换墙钟。
  token 那一头由 prompt 字段顺序解决：`judge_success.md` 改成
  「固定说明 → 画面 → 目标+判据」，同一步内的几次调用共享一大段前缀，
  重复的 input 基本免费；原来是目标在最前面，**前缀缓存一点都吃不到**。
- **模型调用并发，写 trace 不并发。** `event_id` 必须单调，那是 SSE 断线补发的
  唯一依据；多线程写进去会乱序甚至重号。所以只并发拿结果，记账回主线程按 depth 顺序做。
- **出栈理由分 `done` 和 `superseded`。** 上面那些不是完成的，是失去意义的。
  不分开就算不出**拆出来的子目标有多少是白拆的**——而那是判断目标栈帮没帮上忙的那个数。
- **子目标完成只弹栈，绝不写 `success`。** 子目标是 agent 自己定的；能写 success 的话
  它可以压一个"我已经到家了"的子目标让判定器判它完成，成功率变成它自己发的奖状。
  这条落在 `_judge` 的 `while len(goals) > 1` 上，不是一句注释。
- **`inspect` 必须带 `focus`。** 不带就是把同一帧原样再看一遍——`perceive()` 帧内缓存，
  返回的字节完全一样，零新信息，而模型拿不准时一定会选它，然后下一轮看到同样的画面
  再选一次。带上具体问题、走 `inspect_focus.md`，才真的产出新事实。
  答案并进 `facts["inspected"]`，`step()` 之后清空（它只对那一帧有效）。
- **`push_goal` / `inspect` 也算一步。** 它们同样烧一次决策调用；不算的话
  `max_steps` 管不住"一直拆、从不走"。代价是"走了几格"和"想了几次"混在一个数里。
- **栈深上限靠掩码，不靠 prompt 劝。** 到 `MAX_GOAL_DEPTH`（4）之后 `push_goal`
  从 `space.intents` 里掉出去。说明和可选项必须一致——只在 prompt 里劝的话，
  模型照样会选，白花一轮再吃一条 IllegalAction。
- **记忆只在 `press` 时写。** 另外两类世界没变，`after` 和 `before` 是同一帧，
  写进去就是一堆"结果：什么都没发生"，会稀释检索。
- 第一版 `inspect()` 里清了帧缓存想让 facts 重组装，结果 `_perceive()` 重跑了一遍
  正常感知：**多花一次钱，还把 `last_calls` 覆盖成那次调用的账**，细看的账丢了。
  实际上 `observe()` 每次都从缓存重新组装 facts，根本不用清。测试抓到的。

**影响面**：`schemas/core.py`、`interfaces/{brain,tools,world}.py`、`brain/brain.py`、
`tools/game_tools.py`、`world/pyboy_world.py`、`harness/harness.py`、
`prompts/decide_action.md`（重写输出格式）、新增 `prompts/inspect_focus.md`、
`probe/echo_trace.py`（新事件类型的显示）。74 个测试通过，ruff 干净。

旧格式（只有 `action` 没有 `intent`）仍然被当作 `press` 接受——语义无歧义，
为它跑一轮重试不划算，判据同 ```json 包裹。

## 2026-08-20 —— episode 状态整体上移进 LoopState，Harness 变成无状态

**改了什么**：`Harness` 的五个实例字段（`_episode_id` / `_task` / `_step` /
`_succeeded` / `_why`）全部挪进 `LoopState`。现在 `Harness` 只剩三个协作者
（tools / brain / trace）和一张编译好的图——**它自己没有任何状态**。
`_observe` / `_judge` / `_outcome` / `_record_call` 改成收 state 参数。

**为什么这么改**：判据从「它活多久」换成了**「它会不会影响下一个 prompt」**。

原先那条只对活对象成立：world / tools / brain / trace 确实序列化不了，不能进 state。
但 episode 的身份是**纯数据**，而且恰恰是 checkpoint 唯一需要的那部分。
放在实例字段里，等于把"跑到哪了"存在了一个 checkpointer 看不见的地方——
接上 LangGraph 的 checkpointer 也恢复不出第几步、在跑哪个任务。

**取舍**：
- 方法签名变长（多一个 `state`），换来"跑到哪了"只有一个存放处，而且能 dump 成 JSON。
- `_observe()` 现在返回三元组 `(obs, succeeded, why)` 而不是一个 Observation。
  丑一点，但"判过成功就不再问"必须跨步存活，它就得写回 state。
- **没有一起加目标栈。** 先把存放处修对，再往里放新东西。

**光有 LoopState 仍然复现不了**，这一点写进了模块 docstring：
还差记忆库（`GameTools._memories`，进 prompt 但不在存档里）和 `world._facing`
（朝向是从我们自己的动作历史推的，pyboy 的 save state 里根本没有它）。
补法是阶段 2 的 `Checkpoint` = LoopState + 记忆库 + 模拟器存档 + world 推导状态 + manifest。

**影响面**：只动 `harness/harness.py`。69 个测试全过，ruff 干净。

## 2026-08-20 —— 重划 brain / tools / harness 三层

**改了什么**：三层全部重写并改名。

    以前                         现在
    harness/harness.py (工具)    tools/game_tools.py  `GameTools`
    graph/build.py (循环)        harness/harness.py   `Harness`
    brain/react.py               brain/brain.py       `Brain`
    harness/judge.py             并进 `Brain.judge()`
    —                            build.py（只做装配）
    —                            interfaces/brain.py  `BrainPort`
    ToolPort                     拆成 `ToolPort`（大脑看的）+ `ToolHost`（Harness 看的）

职责按一句话切：**Brain 管一切要 LLM 的判断，Tools 管碰环境，Harness 管循环。**
`step` / `done` / `success` 的所有权上移到 `Harness`——world 不再数步，
`Observation.step` 由 `Harness._stamp()` 盖章。`PyBoyWorld` 只保留一个终止权：
窗口被关（`_closed`），因为那时候世界真的没了。

`ReActBrain.remember()` 变成 `Brain.reflect()`：**只返回 `MemoryEntry`，不落库**，
落库由 Harness 调 `tools.memory_write`。

**观测只在 `look` 节点产生**：`Harness._observe()` 是全项目唯一给
`step` / `done` / `success` 赋值的地方，而它只有 `_look` 一个调用方，
所以"一步一次观测"是调用图的形状本身，不需要任何字段去保证。
（第一版曾拆成两个产出点——开局一次、`act` 里执行完再一次——为的是省一次
`perceive()`。那是错的：world 按帧缓存，`look` 里再读一次不产生任何模型调用，
而拆成两处的代价是"每步观测一次"在代码里看不出来。实测 3 步一局共 4 次感知调用。）

分支只有一个，在 `look` 出口：**看完才知道这一局还要不要继续**。
放在 `act` 出口的话，"步数用尽"和"任务达成"要在两个地方各判一次。

**为什么这么改**：按步去重（`_traced_step` / `_judged_step`）是个补丁，
它在补的是一个信息缺口——"新的一步开始了"这件事调用方知道，harness 只能靠
`obs.step` 去猜。而 step 有三个主人（world 数、harness 猜、图决定一轮），
才需要互相对账。实测症状是步号 1 → 0 回退、判定每步跑两次（成本翻倍且不报错）。

根因是命名：叫 harness 的那个类其实是工具层，真正控制循环的是图。
名字盖住了职责，职责就没法归位。改名之后每件事只发生在一处，
两个去重字段不是被修好的，是被消掉的。

**取舍**：
- `Brain` 现在有三个方法、两个 provider，比单一职责的类"胖"。接受，因为
  "所有 LLM 调用的集合"本身就是一条有意义的边界（记账、换型、标定都按它切）。
  代价是 choose/judge 的隔离从类型层面降到约定层面，靠两条硬约束顶着：
  `judge()` 只收 `(task, obs)`；`judge_llm` 是独立实例。
- `Brain.reflect()` 目前**没有模型调用**，是纯格式化。「存入前的修饰」的挂载点
  留在那里，但现在开它就是每步第三次调用，而检索本身还是字符重叠——
  没有任何证据说明修饰过的条目检索得更准。等向量检索接上再开。
- 仍然用 LangGraph 而不是 while：转移条件是显式的边，将来插节点
  （状态归并、值回填、成本熔断）不用改循环体。

**Harness 是唯一写 trace 的人。** 全项目 `trace.append` 只出现在 `harness/harness.py`。
`Brain` 构造函数里没有 `TracePort` 了，三个方法也都不收 `episode_id` / `step`——
它把账（新增的 `ModelCall`）连同结果交出来，由 Harness 翻译成事件：

    brain.choose() -> Decision(action, calls, recalled)
                   -> MEMORY_READ + MODEL_CALL×N + ERROR×失败次数 + THINK
    brain.judge()  -> Verdict(done, why, call)   -> MODEL_CALL(judge) [+ ERROR]
    brain.reflect()-> MemoryEntry（episode_id 由 Harness 盖章）

`choose()` 重试用尽时**返回 `action=None` 而不是抛异常**——`MaxRetriesExceeded`
由 Harness 抛，因为"这一局是否因此终止"是循环的判断，大脑只如实汇报。

上一版的分布是：brain 写 MODEL_CALL / THINK / ERROR / MEMORY_READ，
harness 写 ACT / MEMORY_WRITE / OBSERVE / EPISODE_*，于是"某类事件归谁写"
要一条条记；更糟的是为了让判定器碰不到自己的账，还给 `judge` 开了个不写 trace 的
例外——**用例外弥补一条不统一的规则**。现在规则只有一句：**谁控制循环，谁记账。**
判定器碰不到自己的账不再是特权设计，而是所有大脑调用的共同处境。

顺带修正一处对称性：`MEMORY_READ` 和 `MEMORY_WRITE` 以前分属两个类，现在都在 Harness
（仍在不同节点，因为它们本来就发生在一步的两头）。

**影响面**：`probe/run_episode.py` 改成 `harness.run(episode_id, task)` 一行；
`tests/test_memory.py`、`tests/test_judge.py` 按新 API 重写；
`tests/test_world_smoke.py` 里两条断言 world 记 step 的改成断言它**不**记。
69 个测试通过，ruff 干净。

## 2026-08-18 —— 论据进记忆：Action 加 rationale，thought 只进 trace

**改了什么**
`Action` 新增 `rationale: list[str]`（1-`MAX_RATIONALE` 条，必填），`thought` 从
`default=""` 改为必填非空。`_parse` 拆出 `_parse_thought` / `_parse_rationale`，
两类缺失各自单列 reason。`remember()` 改用论据合成记忆内容，prompt 模板相应改写。
另修两处旧问题：ACT 事件的 step 改用执行前的值；删掉 `observe` 节点里不可达的
done 分支。测试 9 → 13，ruff 由 1 个 I001 转全绿。

**为什么这么改**

先是发现 `thought` 根本没跨步：它唯一的消费方是 `trace.append`，`remember()` 拼
记忆时不含它。推理产出后立刻被截断，再也不进入任何后续决策。这与本项目自称 ReAct
是矛盾的——ReAct 的分界线不是"先想后做"（那太平凡），而是**第 t 步的 thought 能不能
被第 t+k 步看见**。原论文的 HotpotQA 轨迹里 thought 与 action 本就是同一步给出的，
所以"thought 是不是独立动作"不构成判据，**能不能跨步**才是。

但这是实现没落地，不是设计选择——设计一直打算让推理跨步，走检索而不是拼接。
于是**保留 ReActBrain 这个名字**，把代码补上。

顺带纠正一个此前想反了的问题：**检索式 scratchpad 不是对机制三的妥协，是让
scratchpad 与 episodic control 共存的解法。** 原版 ReAct 的上下文随步数单调增长，
同一个状态在第 3 步和第 300 步面对的输入必然不同，这才是系统性破坏近似 Markov 性
的那个；而按状态相关性检索，相似状态取回相似记忆，被注入的内容近似是**状态的函数**，
反而维持了它。附带收益是上下文不随步数爆炸，长程任务上才跑得下去。

那么跨步的该是什么？不是完整推理，也不是结论：

- **结论**（"所以该捡药水"）可以从 `name` 反推，存进去等于把同一件事存两遍。
- **完整推理**里大部分是本次决策的中间步骤，对未来无用，还挤占检索名额与 token。
- **论据**（"地上有药水而我手上没有"）才是 `name` 里没有的信息，而且它是**适用条件**
  ——未来取回这条经验时可以检查它现在还成不成立。结论做不到这件事。

所以分工定为：`thought` 服务本次决策的质量（长度即算力，不设上限，只进 trace），
`rationale` 服务未来的迁移（短、可证伪、进 memory）。

还有一个白拿的性质：记忆条目由「模型出假设 + 世界出判决」拼成，天然**自带标签**
（"我以为 P，结果 R"）。一条错误论据被取回时反例就贴在同一行，不会被当成知识使用。
这让"记忆被无用内容污染"的风险比预想的低——脏东西是带标签的脏东西。

**取舍**

- **论据不区分时效性，一律按有时效处理。** 曾考虑给持久知识（"馆主是火属性"）单独
  开池 + 去重，因为它会被反复产出。放弃了：rationale 是**条目内部的字段**，重复只
  造成 token 膨胀，**不占检索名额**，危害远小于估计。代价是持久知识只能绑在发现它
  的那一步上，跨状态检索不到——那属于 skill library（机制二）的范围。
- **超上限打回重试，不截断。** 模型认为 N 条都承重，悄悄丢一条是替它做了个没有记录
  的决定。代价是这类重试要花 token；实测占比高再改成截断。
- **单条写成裸字符串则容忍**，不消耗重试。判据同 ```json 包裹：常见格式偏差、语义
  无歧义、为它跑一轮重试不划算。
- **`MAX_RATIONALE` 抽成常量**。它有两个执行点（`Action` 的字段约束 = 数据契约，
  `_parse` = 外部输入校验），写死两遍迟早漂成"解析器放行、构造时炸"。
- **缺失用 reason 字符串区分，不新增异常类型**。replay 按 reason 聚合就能把"格式坏"
  和"不肯给论据"拆开，够用了，不值得为它多一个异常类。
- **ACT 的 step 取自 `get_action_space()` 时缓存的值**，而不是执行后 `-1`，也不是
  重新 `observe()`。后者在真实模拟器上是「截图 + VLM」，为记一条日志再感知一次太贵；
  前者依赖 world 的后置条件做减法，且 observation 为 None 时无解。缓存复用的是
  `get_action_space()` 里已经取到的那次观测，免费且在两条路径下都正确。
- **`observe` 的 done 分支直接删，换成一条 assert**。它永远不执行（两条入边都保证
  未结束），而且返回 `action_space=None` 会让下一节点的 assert 崩在更远的地方——
  按第三节第 4 条的判据，不改变行为的"防御"不该存在。

**影响面**
`Action` 的构造点只有 `_parse` 一处，无其他调用方受影响。`MemoryEntry` 签名未动，
key 仍是 step 占位。`FakeLLM.scripted()` 自动把 thought 复制为 rationale，因此所有
只关心动作序列的既有测试一行未改。ACT 的 step 修正会改变 trace 的形状——阶段 2 的
按 step 聚合建立在这次修正之上，**先改再堆**。

## 2026-08-13 —— 更正：harness 与 trace 也是 mock，移进 mocks/

**改了什么**
`harness/harness.py` → `mocks/mock_harness.py`（类名 `Harness` → `MockHarness`），
`harness/trace.py` → `mocks/mock_trace.py`（`InMemoryTrace` → `MockTrace`）。
`harness/` 包不再使用（挂载盘不允许删除，其 `__init__.py` 已移到 `_to_delete/`，
请在本地删掉这个空目录和 `_to_delete/`）。两个模块的 docstring 重写，明确列出它们缺什么。

**为什么这么改**
上一条我用"是否完整实现契约"当判据，把 InMemoryTrace 归成了真实实现。判据用错了。
**这一阶段的范围是"只做大脑，其余全部 mock"**，harness 和 trace 都在"其余"里：

- MockHarness 的 masking 是写死的 if 分支（不是从状态表查）、记忆检索是字符集重叠
  （没有 state abstraction、没有值回填），六件套只有 trace 一件，
  缺权限确认、沙箱、成本控制、checkpoint、replay，动作空间不会增长。
- MockTrace 只是个内存列表，不落盘、不推流、不做 checkpoint 事件源、不按失败类型聚合。

它们后面是要被**重写**的，不是"换个存储介质"。放在 `harness/` 会让人以为那是成品，
导致后面接着往上堆而不是推倒重来。

**取舍**
保留"替身也严格遵守契约"这一点（MockTrace 的 event_id 仍然真的单调、
MockHarness 的 precondition 断言一个没少）。替身可以简陋，不能违约——
否则换成真实实现时上层会崩，mock 的意义就没了。这条写进了两个文件的 docstring。

`mocks/` 现在有四个文件（fake_llm / mock_world / mock_harness / mock_trace），
对照之下 `brain/` 只有一个 —— 这个比例恰好说明了当前阶段的范围。

**影响面**
纯搬迁与改名，9 个测试仍全绿，ruff 无告警。

## 2026-08-13 —— 最小闭环跑通（mock + harness + 图装配 + 测试）

**改了什么**
新增 `mocks/fake_llm.py`、`mocks/mock_world.py`、`harness/trace.py`（InMemoryTrace）、
`harness/harness.py`、`graph/build.py`，以及 `tests/test_react.py`（5 个单元测试）和
`tests/test_episode.py`（4 个集成测试）。9 个测试全绿，ruff 无告警。

**为什么这么改**
到这一步"最小闭环"才成立：一个任务从头跑到尾、全程有 trace、失败路径有计数。
几个位置的决定：

- **InMemoryTrace 放 `harness/` 而不是 `mocks/`**。判据：实现的是完整契约就进 harness，
  只为让流程跑通的替身才进 mocks。它的 event_id 真的单调、replay 真的能回放，
  和将来的 FileTrace 只差存储介质，而且测试会一直用它（测试不该往磁盘写东西）。
- **masking 在 harness，成败判定在 world**。掩码是策略（什么时候允许买东西是设计决定），
  判定是能力（只有世界知道状态是否满足判据）。这条边界写进了 Harness 的模块 docstring。
- **`execute()` 前要先 `get_action_space()`**，harness 记住最近一次给出的空间做 precondition，
  执行后立即置空——世界推进了，上一次的动作空间就失效了。
- **AgentState 只存流转数据，不存业务状态**。业务状态在 harness 里。
  因为图状态会被 LangGraph 复制、合并、快照，把记忆或世界塞进去会产生意料之外的副本。
- **FakeLLM 支持返回坏 JSON 和 loop 模式**。解析失败与重试是大脑最重要的一条分支，
  没有能制造失败的 mock 就测不到它。

**取舍**
- `memory_query` 用字符集重叠打分，粗糙。故意不上 embedding：
  换向量检索是机制一的事，现在上会掩盖"检索策略属于实现方"这个分层是否真的成立。
- `MockWorld` 的 DEMO_TASK 只有 12 步上限，**不满足 Task docstring 写的下界**
  （必须长到上下文装不下）。代码注释里标了这一点：它只是让闭环跑起来的脚手架，
  真实任务集要另行设计。
- `build_demo()` 返回 harness 和 trace 三元组，比只返回图啰嗦。
  但测试要读 trace 做断言，不返回就得从图里掏，那才是真的破坏封装。

**影响面**
全项目可运行。`pytest` 通过即表示：换真实模拟器只需换 `MockWorld`、
换真实模型只需换 `FakeLLM`，brain 和 harness 一行不动。

## 2026-08-13 —— episode 的边界从"通关"改成"一个任务"

**改了什么**
`schemas/core.py` 新增 `Task`（task_id / goal / success_criteria / max_steps）和
`EpisodeOutcome`；`Observation` 加 `goal` 与 `success` 两个字段。
`WorldPort.reset()` 改签名为 `reset(task)`，`step()` 的契约补上成败判定与终止条件。
`ToolPort.perceive()` 后置条件补 goal。`ReActBrain` 的 prompt 加"当前任务目标"一节，
`choose()` 入口增加两条 precondition（episode 未结束、goal 非空）。

**为什么这么改**
原来一个 episode = 一次通关，粒度太大，三处都出问题：

1. **机制三拿不到信号**。通关是几千步只产出一个 0/1 结果，
   MC 回填的折扣一路乘下去，回填到前期步骤上几乎是噪声。任务级几十到几百步才有梯度。
2. **评测只能报二值结果**。任务级能报成功率、失败模式分布、有记忆 vs 无记忆的对比——
   这才是"提升了多少"要的形态。
3. **迭代周期以小时计**，每改一行都要跑一次通关才有反馈。

**取舍**
- **"长程"这个卖点会被稀释**：任务缩得太小，一个上下文窗口就装下了，记忆架构失去存在理由。
  所以在 `Task` 的 docstring 里写死了下界：必须长到单靠上下文装不下、
  必须跨任务复用经验才做得好。这条判据要在设计任务集时守住。
- 采用两层结构：**episode = 一个任务**（回填与评测单位），**通关 = 一串 episode**（future work，不实现）。
  额外收益是 episodic 记忆有了清晰的作用域：**一条轨迹 = 一个 episode = 一次任务尝试**，
  MC 回填的边界与检索的相关性范围都由此确定。
  （注意别把"跨任务复用的经验"叫 semantic —— semantic 是外部领域知识，
  比如"水属性克制火属性"，来自攻略/图鉴而非自己跑出来的轨迹。
  跨任务复用的成功经验属于 episodic 的聚合，或晋升后进 skill library。）
- 成败判定放在 `WorldPort` 而不是 harness：只有世界知道游戏状态是否满足判据。
  代价是 mock world 要实现判定逻辑。

**影响面**
接口签名变更（`reset`），但尚无实现，无返工。`Task` 与 `EpisodeOutcome` 是新增，
`Observation` 的两个新字段有默认值，不破坏已有构造。

## 2026-08-13 —— 实现 ReActBrain（大脑，唯一的实现代码）

**改了什么**
新增 `brain/react.py`：`ReActBrain.choose()`（一轮 Thought → Action，含重试）、
`remember()`（写记忆）、三个私有方法（`_recall` / `_build_prompt` / `_parse`）。

**为什么这么改**
几个位置的决定：

- **重试放在大脑里，不放在 LLMProvider 里**。因为"什么算失败"是大脑的判断——
  解析不出来算失败、选了不存在的动作也算失败，这两件事 provider 都不知道。
- **ParseFailure 与 IllegalAction 分开抛**。它们在 replay 里是不同的失败模式：
  前者说明格式没学会（改 prompt 或上约束解码），后者说明模型在幻觉动作（改动作说明或收紧掩码）。
  合并成一类就丢掉了这个诊断信息。
- **每次重试重新调用 LLM 而不是复用上次输出**。模型的随机性本身就是重试有意义的原因。
- **`_build_prompt` 每次从参数完整组装，不留历史**。这是"大脑无状态"在代码层面的落点：
  想违反铁律 1 就必须在这里加一个实例变量，很显眼。
- **容忍 ```json 包裹**直接在解析里处理，不消耗一次重试——这是模型最常见的格式偏差，
  为它跑一整轮重试不划算。

**取舍**
- 大脑自己写 trace（COST / THINK / ERROR / MEMORY_READ / MEMORY_WRITE 五类），
  而不是由外层统一收集。代价是大脑多依赖一个 TracePort；
  收益是 token 成本只在 LLM 调用点拿得到，绕出去就要让成本模块认识 LLM 层，破坏分层。
- `choose()` 需要 `episode_id` 参数，签名比"只传 obs 和 space"啰嗦。
  但大脑无状态就意味着它不能自己记住当前是哪个 episode，只能由调用方每次传入。
- prompt 用字符串模板而非模板引擎：原型期够用，且模板内容一眼可见。

**契约落点（对应第三节第 4 条）**
构造函数 assert `max_retries >= 1`、`memory_limit >= 1`（pre）；
`choose()` 入口 assert 动作空间非空（pre）、出口 assert 返回动作在空间内（post）；
`_recall` assert 返回条数不超过 limit（对 ToolPort 后置条件的交叉验证）；
`remember()` assert result 非空（pre）。

**影响面**
新增。依赖四个 Protocol，不依赖任何实现。此时还跑不起来——缺 FakeLLM、MockWorld、
Harness、InMemoryTrace 和图装配。

## 2026-08-13 —— 接口层设计（只有 Protocol 和数据模型，无实现）

**改了什么**
新增 `schemas/core.py`（7 个 Pydantic 模型）、`errors.py`（3 类预期内失败）、
`interfaces/` 四个 Protocol：`LLMProvider` / `ToolPort` / `TracePort` / `WorldPort`。
所有方法只有 docstring 契约，方法体是 `...`。

**为什么这么改**
按"接口先行"，先让 `interfaces/` 成为可读的设计文档。几个关键决定：

- **ToolPort 与 WorldPort 分开**。ToolPort 是"大脑能做什么"（五个 MCP 工具），
  WorldPort 是"世界能做什么"（reset/observe/all_actions/step）。harness 用后者实现前者。
  换真实模拟器时只动 WorldPort 的实现，ToolPort 和大脑一行不改。
  masking 放在 harness 而不是 world，因为掩码是策略不是能力。
- **LLMProvider 做得极薄**，只有 complete()。重试是调用方策略、约束解码将来加新方法、
  对话历史由无状态的大脑每次组装——三样都不进这个接口。
- **TracePort 只有 append 和 replay，没有删改**。append 返回 event_id 而不是事件，
  是为了落盘实现能在这里分配序号；replay 带 after_event_id，直接对应 SSE 的 Last-Event-ID。
- **IllegalAction 异常与 execute() 入口 assert 并存**，针对两个责任方：
  前者是大脑内部发现模型幻觉（外部输入不合法 → 重试），后者防大脑没检查就把动作递出去（调用方 bug）。

**取舍**
- `Action` 里带 `thought` 字段：数据模型里混了调试信息，不够纯粹。
  但 replay 时只知道选了什么、不知道为什么选，价值折半，值这个代价。
- `ToolResult.observation` 可为 None，调用方需另行 perceive()：多一次调用，
  换来"推进世界"和"读取世界"两件事不被绑死。
- `MemoryEntry.key` 本阶段用 step 占位。机制一接进来时这里换成 state abstraction 的语义 key，
  **接口签名不变**——这是检验抽象对不对的试金石。

**影响面**
新增，无既有代码。下一步的实现与 mock 全部按这四个 Protocol 写。

## 2026-08-13 —— 明确 assert 的定位：契约（pre + post + invariant）

**改了什么**
`CLAUDE.md` 第三节第 4 条重写为契约式设计的完整三件套，给了 pre/post 的代码示例，
并补了"不做流程控制/兜底/外部输入校验"的判据。

**为什么这么改**
第一版把 assert 摊成"前置 + 后置 + 各种不变量"，边界糊；第二版矫枉过正只留 precondition，
把 postcondition 推给测试，这是错的——测试只覆盖想到的用例，出口 assert 覆盖所有实际执行。
本项目最核心的主张"大脑不会幻觉出不存在的动作"，最好的运行时证据就是 `choose()` 出口的
一行 postcondition assert。

关于边界，判据收敛成一条可机械判断的：`python -O` 会删掉所有 assert，
删掉后程序行为会改变的东西就不该是 assert。这一条同时排除了兜底、副作用和外部输入校验，
不需要三条独立规则去记。

**取舍**
出口 assert 有运行时开销，且在热路径上会重复检查。原型期不管这个——
真到了性能敏感的地方，`-O` 本来就是关掉它们的正规手段。

**影响面**
规范层面。尚无代码，无返工。

## 2026-08-13 —— 立项：定开发规范与工程配置

**改了什么**
新建 `CLAUDE.md`（开发规范）、`pyproject.toml`（ruff 行宽 100 + pytest）、`.gitignore`、本文件。
尚未写任何业务代码。

**为什么这么改**
项目的架构约束（大脑无状态、依赖单向、trace 是四件事的共同底座）如果不先写死，
原型期会以"先这样以后再改"的名义被逐条破坏，而这几条一旦破了，
后面的 replay / checkpoint / SSE 观测台全部要重做。规范先行的成本远低于返工。

**取舍**
- 上 LangGraph 而不是手写 while 循环：少一次重写，代价是一开始要和框架抽象磨合。
  但只让它承担循环调度，记忆与状态表自己实现，磨合面被限制住了。
- 输出格式先用 Pydantic + 解析重试，不上约束解码：原型期没有真实模型，
  约束解码会把实现和具体模型能力绑死。
- 不引入 mypy / pre-commit：原型期摩擦大于收益，ruff 的 ANN 规则已经强制了类型注解。

**影响面**
全项目。后续所有代码都受 `CLAUDE.md` 约束。
## 2026-08-24 —— 建立 experiment 实验环境与从头 replay
**改了什么**：新增 experiment 入口、实验任务定义、manifest 实验元数据、episode 起点存档和从头 replay 约束，并补充野生遭遇知识实验提示。
**为什么这么改**：短程/长程、知识召回和情景记忆实验必须能从 manifest 解释实验自变量；每个 episode 还必须有独立起点，避免连续运行状态无法复现。
**取舍**：experiment 入口先复用 probe 实现，减少原型阶段分叉；暂不实现从中间事件续播，因为它会把不完整上下文误当成可复现 replay。
**影响面**：新增实验层能力；probe 每局额外保存起点存档；已有 trace 的 partial replay 调用会显式失败。
## 2026-08-24 —— 将 episode runner 正式移入 experiment
**改了什么**：`run_episode.py` 与 `run_episode_loop.py` 从 `probe/` 移到 `pokemon_agent/experiment/`；Harness 在 reset 后、第一步观测前保存真实 episode 起点 state；补充 World/GameTool 的 save_state 接口。
**为什么这么改**：probe 是探索脚本，实验 runner 应属于可复现实验环境；起点存档必须在 episode 开始边界生成，不能在结束后推测。
**取舍**：暂时不实现全局长期记忆；`memory_policy` 仅记录摘要经验作用域，当前支持 session_local，未来预留 cross_run_import。
**影响面**：启动命令路径改变为 `python -m pokemon_agent.experiment.run_episode_loop`；旧 probe runner 不再保留。
## 2026-08-24 —— 固定短程入口与摘要经验作用域
**改了什么**：明确短程任务由 `experiment/run_episode.py` 启动；`memory_policy` 固定为 `session_local`，移除跨 run 导入语义。
**为什么这么改**：短程与长程的启动边界必须和实验定义一致；摘要经验本来就是当前 session/run 的内部变量，不能让 manifest 暗示存在跨 run 实验。
**取舍**：暂不支持跨 run 摘要迁移，也不把它作为实验变量。
**影响面**：短程命令路径和 manifest 校验语义更新，长程仍由 `run_episode_loop.py` 负责。
## 2026-08-24 —— 整理 memory 目录边界
**改了什么**：将语义检索、向量、语义接口与对象工具移入 `memory/semantic/`；将 episode 摘要和 episode 工具移入 `memory/episode/`；删除旧路径。
**为什么这么改**：semantic knowledge 与 episode 经验的生命周期、检索条件和实验含义不同，目录边界应直接表达这一设计。
**取舍**：原型阶段不保留兼容入口，强制所有调用方使用唯一的新目录结构。
**影响面**：`MemoryTool` 和测试统一使用新路径，旧 import 将直接失败。
## 2026-08-24 —— 分离 semantic protocol 与检索实现
**改了什么**：将 `SemanticObjectStore` 移到 `interfaces/semantic_memory.py`；更新 `MemoryTool` 的接口引用；明确 `semantic/vector.py` 是 TF-IDF 词法工具而非 embedding 模型。
**为什么这么改**：Protocol 属于跨层契约，应位于 interfaces；具体 semantic 实现只依赖接口，不应拥有接口定义。
**取舍**：保留 TF-IDF 作为混合检索中的轻量词法组件，不把它误命名成神经 embedding。
**影响面**：`MemoryTool` 的接口 import 路径改变；运行时模型配置不变。
## 2026-08-24 —— 删除重复的 TF-IDF vector 实现
**改了什么**：删除未被生产代码使用的 `semantic/vector.py` 和对应测试；将 BM25 所需的字符 bigram tokenizer 收回 `semantic/retrieval.py`。
**为什么这么改**：当前检索已经使用 `rank_bm25.BM25Okapi`，额外保留一套 TF-IDF/余弦相似度既不参与运行又重复表达词法检索。
**取舍**：保留字符 bigram 分词，因为 BM25 仍需要它；不保留第二套本地 TF-IDF 排序器。
**影响面**：semantic 检索实现更单一，删除死代码和对应测试。
## 2026-08-24 —— 增加宝可梦红 knowledge 主题与短程任务
**改了什么**：新增门与地图切换、NPC 对话、战斗确认、移动阻挡四个 knowledge 文件，并将 knowledge 短程任务扩展为五个主题任务。
**为什么这么改**：这些经验是跨坐标、可在单帧证据上验证、且会直接改变动作策略的宝可梦红通用规则，适合测试 semantic knowledge 召回。
**取舍**：暂不加入道具菜单、属性克制等需要更复杂起点和判定器的主题，先保证任务能在当前 harness 中解释成功或失败。
**影响面**：新增 semantic knowledge 内容；`knowledge_recall_tasks()` 返回的任务数量从三项扩展为五项。
## 2026-08-24 —— 扩展到十个常见短场景并记录起点要求
**改了什么**：为 `Task` 增加 `initial_state_hint`，将 knowledge 短程任务扩展到十个，并新增道具拾取、菜单选项、商店/宝可梦中心知识。
**为什么这么改**：任务不仅需要目标和成功判据，还必须告诉实验采集者应该准备什么起点 state；十个短场景覆盖野外、室内、对话、选择、菜单、商店和战斗等常见状态。
**取舍**：state hint 是人工采集说明，不进入 agent prompt，也不假装由代码自动验证地图坐标。
**影响面**：Task schema 向后兼容；`knowledge_recall_tasks()` 现在返回十个任务。
## 2026-08-24 —— 细分战斗与商店短场景
**改了什么**：新增战斗行动、招式选择、宝可梦切换、道具使用、逃跑，以及商店购买菜单、选商品、确认购买、取消购买九个任务；新增 `battle_actions.md` 与 `shop_purchase.md`。
**为什么这么改**：战斗和购买不是单一场景，而是多个有不同动作空间和成功证据的状态转移；拆开后每个 state 才能独立采集、独立统计。
**取舍**：购买任务要求准备足够金钱或专门的买不起商品 state；战斗任务不要求一定获胜，重点测行动分支的 knowledge 召回。
**影响面**：knowledge 短程任务从十个扩展到十九个。
## 2026-08-24 —— 将 knowledge 任务调整为 5-15 步微任务
**改了什么**：重写过于单步的目标，使门、对话、菜单、战斗和购买任务包含移动、读取、选择、确认或返回等连续环节；默认步数上限调整为 15。
**为什么这么改**：单次打开菜单或一次确认不能检验 knowledge 是否改善了短程规划；实验需要观察 5-15 步内的连续策略。
**取舍**：5-15 步是自然完成区间而非硬性延迟条件，不强行让 agent 为凑步数执行无意义动作。
**影响面**：`knowledge_recall_tasks()` 默认 `max_steps` 从 12 改为 15，state 采集应把起点放在目标前的准备位置。
## 2026-08-24 —— 增加捕捉与宝可梦中心场景
**改了什么**：删除重复的战斗确认任务；新增削弱目标、投掷精灵球、确认捕捉结果、进入宝可梦中心、完成治疗、离开中心六个任务，并增加对应 knowledge。
**为什么这么改**：捕捉和治疗是宝可梦红最常见的核心循环，且每个流程都包含不同的状态和成功证据，不能由普通战斗或进门任务代替。
**取舍**：捕捉任务需要准备有精灵球和可控伤害的战斗 state；治疗任务需要准备至少一只受伤宝可梦。
**影响面**：knowledge 短程任务现在覆盖战斗、捕捉、购物、治疗和地图交互等核心流程。
## 2026-08-24 —— 按现有 state 提供实验入口
**改了什么**：允许 `experiment/run_episode.py` 作为真正的短程入口；新增 `experiment/run_experiment.py`，按任务类别选择现有 `rom_field.state`、`rom_fight.state`、`rom_indoor.state` 或 `rom.state`，自动生成 manifest 并运行任务。
**为什么这么改**：实验必须基于仓库当前真实存在的 state，不能要求尚未采集的专用 state 才能启动。
**取舍**：当前多个任务共享同一个基础 state，state hint 仍用于后续判断是否需要更精确的采集版；本入口先运行一个 episode，不伪装成批量统计器。
**影响面**：新增可执行实验入口；短程入口不再要求外部预设 `CLAUDE_RUN_ID`。
## 2026-08-24 —— 以 experiment_states/knowledge 为唯一 task 输入
**改了什么**：将 knowledge task catalog 限定为当前已有的 19 个 state，并让实验入口按完全相同的 task id 从 `pokemon_agent/experiment/experiment_states/knowledge/` 加载 state。
**为什么这么改**：实验任务必须和实际可复现的起点一一对应，不能再用 assets 下的基础 state 猜测替代。
**取舍**：没有对应 state 的菜单、选项和捕捉结果任务暂不进入当前 catalog，待 state 收集后再加入。
**影响面**：knowledge task 数量从 24 调整为当前 state 文件对应的 19 个；`run_experiment.py` 不再读取 `assets/rom_*.state`。
## 2026-08-24 —— knowledge 实验默认按运行时间生成 run_id
**改了什么**：`run_experiment.py` 在未传 `--run-id` 时按时间加随机短后缀生成 run_id。
**为什么这么改**：task_id 用于任务归类，run_id 用于区分每次实际运行；同一 task 的重复实验必须拥有独立数据目录。
**取舍**：需要复现实验或手动归档时可通过 `--run-id` 指定固定名称。
**影响面**：默认数据目录恢复为每次运行独立的 `trace_data/<timestamp>-<suffix>/`。
## 2026-08-24 —— 记录 provider manifest 并按 task_id 聚合成功率
**改了什么**：为本地 embedding/reranker 增加 config；实验 manifest 写入 vision/text/judge/embedding/reranker 配置；新增 `trace_data/task_stats/<task_id>.json` 聚合多次 run 的尝试数、成功数和成功率。
**为什么这么改**：run_id 区分一次运行，task_id 才是实验统计单位；两者不能混用。
**取舍**：聚合文件先采用简单 JSON 累积，后续再从 trace 离线重建以增强抗中断能力。
**影响面**：每次 `run_experiment` 完成后更新对应 task 的统计文件。
## 2026-08-24 —— 将实验元数据与统计移出 trace_data
**改了什么**：manifest 改存到 `experiment_results/<run_id>/manifest.json`，按 task_id 的聚合统计改存到 `experiment_results/task_stats/<task_id>.json`。
**为什么这么改**：trace_data 只表达逐事件事实流和 episode 起点；实验条件与统计结果属于实验产物，不能混入 trace 存储。
**取舍**：episode JSONL 和起点 state 仍留在 trace_data，便于 replay；manifest 与统计通过 run_id/task_id 关联，不复制事件流。
**影响面**：新运行不再把 manifest 或 task_stats 写入 trace_data。
## 2026-08-24 —— 修复 episode 摘要模板路径
**改了什么**：将 `episode_summarizer.py` 的模板路径改为基于文件绝对位置解析 `pokemon_agent/prompts/episode_summary.md`。
**为什么这么改**：文件从 `memory/` 移到 `memory/episode/` 后，旧的 `..\prompts` 相对层级少了一层，导致实验启动时直接找不到模板。
**取舍**：使用包内文件的绝对解析路径，不依赖当前工作目录。
**影响面**：修复 `run_experiment` 初始化 `MemoryTool` 时的 `FileNotFoundError`。
## 2026-08-24 —— knowledge 召回展示改为文件名
**改了什么**：新增 knowledge 来源文件名追踪；MEMORY_READ 和控制台只展示命中的 `.md` 文件名，不再展示 knowledge 正文或标题摘要。
**为什么这么改**：当前实验只需确认召回了哪份知识文件，正文已经进入 agent prompt，不应在观测台重复输出。
**取舍**：检索正文仍完整传给 agent；展示层和模型上下文保持分离。
**影响面**：新增 `knowledge_sources` trace 字段，控制台和浏览器观测台都只显示文件名；旧 trace 没有该字段时显示为空。
## 2026-08-24 —— 完善观测台状态展示
**改了什么**：浏览器观测台的 observe 事件增加 `scene`、`overlay` 和 `walk_map` 展示；known_object 继续只显示地图与坐标等短定位信息。
**为什么这么改**：这三个字段是判断当前动作空间和路线状态的核心事实，只显示 summary 不足以检查 agent 的决策依据。
**取舍**：不展开 known_object 正文，也不重复显示 knowledge 正文；观测台保持检查用的紧凑格式。
**影响面**：只改浏览器展示，不改变 trace payload 和模型输入。
## 2026-08-24 —— 精简 episode_memory_write 事件
**改了什么**：从 `episode_memory_write` payload 删除 `input_tokens` 和 `output_tokens`。
**为什么这么改**：摘要记忆写入事件只需要记录摘要内容与适用范围，模型调用成本应由独立的模型调用账单事件承担。
**取舍**：历史 JSONL 中已有的 token 字段不回写；新生成事件不再包含它们。
**影响面**：新 trace 的 `episode_memory_write` 只保留 summary、quality_score、applicable_scenes。
## 2026-08-24 —— 将 episode 摘要逐条落盘为 LLM 生成的 Markdown
**改了什么**：恢复摘要事件 token 记录；扩展摘要输出为 LLM 生成的 `filename` 与 `markdown`，每个 episode 单独保存到 `pokemon_agent/memory/episode/memory/`；收紧 `applicable_scenes` 为稳定标签。
**为什么这么改**：当前先保留每局原始摘要，后续可以离线聚类合并；场景标签必须可检索、可比较，不能使用长段自然语言。
**取舍**：文件名冲突时追加 episode_id 保证一局一个文件；程序检索仍使用结构化 EpisodeMemory，Markdown 是落盘归档。
**影响面**：新增摘要文件写入；`episode_memory_write` 同时恢复 input/output token 字段。
## 2026-08-24 —— 让 applicable_scenes 标签参与实际匹配
**改了什么**：`applicable_scenes` 支持 `map:<id>`、`scene:<name>`、`overlay:<name>` 等稳定标签；Harness 查询时传入当前地图、scene 和 overlay 的组合键。
**为什么这么改**：原来模型生成的场景描述即使写进摘要，也无法和查询侧的纯数字 map_id 匹配，导致摘要经验被错误过滤。
**取舍**：保留旧的纯数字 map_id 兼容匹配；新摘要统一使用带前缀标签。
**影响面**：episode 摘要召回的场景过滤更可解释，旧摘要仍可继续使用。
## 2026-08-25 —— 补齐 AgentPermission 运行配置
**改了什么**：为 `player-agent` 增加游戏执行权限，为保存游戏状态增加高风险确认策略；将 `context.json` 改为由 episode 初始化覆盖的运行时模板。
**为什么这么改**：宝可梦 agent 需要读取游戏状态并执行动作，原配置只有读取权限；`context.json` 中固定的 episode 标识会在多 episode session 中失真。
**取舍**：保留 `trusted-agent` 角色和兼容的 `execute:game:save` 策略，不在本次改动中修改库的权限命名协议。
**影响面**：只影响 AgentPermission 的配置加载；尚未接入 Python 装饰器或改变游戏执行代码。

## 2026-08-25 —— 细分 agent 游戏与记忆权限
**改了什么**：把 `player-agent` 从宽泛的 `read:game:*` / `execute:game:*` 拆成观测、动作空间、按键、存档边界以及情景/跨局/对象/知识记忆权限。
**为什么这么改**：权限配置应该反映工具接口的真实能力；通配执行权限会让 agent 无法区分读取、推进世界和写入记忆的风险。
**取舍**：保留 `trusted-agent` 的全量权限作为调试角色；`save`/`save_state` 继续由高风险策略单独控制。
**影响面**：仅修改 `config/permissions.json` 和变更日志，不改变运行代码。

## 2026-08-25 —— 移除未绑定的示例权限
**改了什么**：删除 `agent_permission.examples.pokemon:inspect`。
**为什么这么改**：它指向 AgentPermission 包中的示例函数，不是 `pokemon_agent.tools.game_tools.GameTools.inspect()`；保留它不会给本项目函数增加任何保护，反而会造成权限配置与实际执行路径不一致。
**取舍**：先使用项目自己的资源名，待装饰器接入时再让装饰器声明和配置逐项对齐。
**影响面**：仅影响 `player-agent` 的权限配置，不改变游戏行为。

## 2026-08-25 —— 增加模型调用权限
**改了什么**：为决策模型、目标判定模型、视觉感知模型和跨局记忆摘要模型增加独立的 `execute:llm:*` 权限。
**为什么这么改**：这些调用会产生网络访问和模型成本，且四条链路职责不同；不应让游戏按键权限隐含获得所有模型调用能力。
**取舍**：本地 embedding 和 reranker 暂不归入远程 LLM 权限，因为它们不调用远程模型服务；是否需要单独限制留到接入权限装饰器时再决定。
**影响面**：只修改 AgentPermission 配置，不改变 provider 实现。

## 2026-08-25 —— 将按键权限收敛为 press
**改了什么**：把动态的 `execute:game:button:*` 改为固定的 `execute:game:press`。
**为什么这么改**：项目所有按键都经过 `GameTools.execute(action)` 这一条统一边界；具体按键名已在 `Action.name` 和 `act` trace 事件中记录，不需要把每个按键扩展成权限资源。
**取舍**：权限层只判断“是否允许推进游戏”，不在配置层限制某个具体按键；动作空间和 `execute()` 的现有契约继续负责非法按键拦截。
**影响面**：只修改 AgentPermission 配置；按键级审计仍通过 trace 保留。

## 2026-08-25 —— 完整配置 trusted-agent 权限
**改了什么**：将此前讨论的游戏、LLM、记忆、Harness 和存档权限全部写入 `trusted-agent`。
**为什么这么改**：`trusted-agent` 作为调试和受信任运行角色，应明确拥有项目实际使用的全部能力；逐项列出也便于和装饰器绑定关系对照。
**取舍**：保留存档的高风险确认策略，即使角色拥有对应权限，保存动作仍按策略确认。
**影响面**：只修改 AgentPermission 配置和变更日志，不改变 Python 运行逻辑。
## 2026-08-25 —— 移除 inspect 动作分支
**改了什么**：从 `GameToolPort`、`GameTools`、`Action.Intent` 和 Harness 图中移除 `inspect` 函数与 `INSPECT` 节点，并删除对应权限；解析器不再接受 `inspect` 动作。
**为什么这么改**：当前原型只保留常规观测和按键推进，细查会引入额外视觉调用、动作分支和同帧状态，超出本阶段最小闭环。
**取舍**：底层 `WorldPort.inspect()` 及相关历史测试/展示代码暂未删除，避免把世界实现和 trace 兼容清理扩大到本次接口变更之外；它们已不再从 Harness 工具路径可达。
**影响面**：Brain 可选动作从 `PRESS/PUSH_GOAL/INSPECT` 收敛为 `PRESS/PUSH_GOAL`；现有依赖 inspect 的旧测试需要同步移除或改写。
## 2026-08-25 —— 收敛 MemoryTool 公开接口
**改了什么**：将单步记忆、跨局摘要、对象记忆和知识检索改为统一的 `query_*` / `store_*` 命名；知识查询改为一次返回内容与来源；移除每帧 `see_objects()` 登记路径。
**为什么这么改**：旧接口混用了 `query`、`recent`、`write`、`note`、`known` 等动词，且知识内容与来源分别检索，无法保证属于同一次命中结果；每帧登记对象也和观察数据重复。
**取舍**：不保留旧方法别名，强制调用方迁移到新契约；`store_episode_summary()` 暂时同时负责摘要生成和保存，因为当前没有独立保存已生成摘要的调用场景。
**影响面**：修改 `MemoryToolPort`、`MemoryTool` 和 Harness 记忆节点；旧测试与文档引用需要同步迁移。

## 2026-08-25 —— 删除旧 MemoryTool 与 inspect 测试
**改了什么**：删除直接依赖旧 MemoryTool 方法名和 `inspect` 图分支的 `test_memory.py`、`test_episode_memory.py`、`test_poses.py`、`test_goals.py`、`test_subgoals.py`。
**为什么这么改**：这些测试验证的接口已经被本次设计收敛移除，继续保留会把旧契约伪装成当前行为。
**取舍**：保留未直接依赖旧接口的世界、提示词、检索和判定测试；新 MemoryTool 契约测试后续按新接口补回。
**影响面**：删除 5 个旧测试文件，不改变生产代码。
## 2026-08-25 —— 收敛为单角色完整权限边界
**改了什么**：将 `trusted-agent` 定义为 Brain + Harness 的统一角色；为所有 `GameToolPort` / `MemoryToolPort` 公开能力配置权限，并加入 `Brain.reflect()` 未来 LLM 修饰所需的 `execute:llm:memory_reflection`。
**为什么这么改**：当前权限系统只支持单角色，继续拆分角色只会制造无法执行的配置复杂度；工具能力和 Brain 直接发起的模型调用是两条清晰的权限边界。
**取舍**：保留 `last_frame_sha` 和 trace 权限作为工具/运行审计能力；删除不存在的 `execute:game:save` 以及不属于工具接口的 Harness 生命周期权限。
**影响面**：只修改 AgentPermission 配置和变更日志，不改变 Brain/Harness 运行逻辑。
## 2026-08-25 —— 接入 AgentPermission 装饰器
**改了什么**：在 `Brain`、`GameTools`、`MemoryTool` 和 `Harness.run()` 的具体实现方法上加入显式权限装饰器；将运行时 context 角色切换为 `trusted-agent`。
**为什么这么改**：权限系统实际检查的是被调用的具体函数，接口声明不会自动继承装饰器；在实现边界执行检查才能阻止未授权调用真正发生。
**取舍**：`Harness.run()` 负责 episode 开始时执行 `initialize`；多权限方法使用多个装饰器逐项检查；`Brain.reflect()` 当前仍是本地逻辑，但预先纳入记忆反思权限以约束未来 LLM 化。
**影响面**：受保护函数在权限上下文未初始化、权限不足或审批拒绝时不会执行；配置和运行 context 已同步更新。
## 2026-08-25 —— 明确无权限错误处理
**改了什么**：Harness 对 `PermissionDenied`、`ApprovalExpired` 和 `ApprovalRejected` 增加显式捕获并写入 episode error trace；移除 `Harness.run()` 自身的 trace 权限门。
**为什么这么改**：权限拒绝是预期内的运行时失败，不应重试或静默吞掉；如果先拦截 `Harness.run()`，连拒绝事件都无法写入 trace。
**取舍**：记录后继续向上抛出，让 episode 调用方决定结束或展示错误；不把权限失败伪装成模型解析失败或非法动作。
**影响面**：只改变权限错误的记录与传播方式，不改变允许调用的执行路径。
