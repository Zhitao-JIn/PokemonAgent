# PLAN —— harness 图组合重构：run/episode 两级图 + 一节点一文件

> **一句话**：把 harness 从"两个 1749 行/677 行的类各揣一张图"改成
> **"两张编译好的图 + 26 个节点文件 + 一张父子交界契约"**——run 图把 episode 图
> **当真子图挂进去**（不再 `episode.run(req)` 显式调用），节点实现一人一个文件，
> 装配文件只 import。
>
> **状态：v7 方案稿。D1（拼接方式）与 D8-③（`trace_write` 去向）已拍板；D9/D10 为 v3 新增、
> D11（deps 形状 + `world_reset_done` 归位）为 v4 新增；v5 撤掉了 v4 的 deps 分组；
> **v6 又撤掉了 v3 给 checkpoint 的落点**——`harness/checkpoint/` 这个包不存在了；
> **v7 订正了 v6 里一处判断错的理由**（`world_reset_done` 为什么可以不落盘），
> 并补了一节把 `resume` 的两条路径讲全（见下）。
> 余下待拍板项见 §7。按既定做法，拍板前不动代码。**
>
> **v4 的特别说明**：这一轮**不是照意见改**，而是你的一个问题（"其他字段我都不理解，要不删了"）
> 逼出了两条**没验证过的机制**。实测 F10/F11 推翻了 v3"两个 runtime"的结构设想——
> 见下面"v3 → v4 改了什么"。
>
> **本 PLAN 的每一句机制判断都来自 §2 那十一条实测**（langgraph 1.2.11，本机 `.venv`），
> 不是文档印象。十一条里有六条是**否决性**的：不先解决它们，直接照着"内置拼接"改会当场炸
> （或者更糟——**不炸但静默出错**，比如 F10）。

---

## v1 → v2 改了什么（四条，都来自你的四点意见）

| # | v1 怎么写的 | v2 改成 | 为什么 |
|---|---|---|---|
| 1 | D5：两张 Port **收窄**（只留入口方法） | D5：两张 Port **整个删掉** | 你说"不用给图写 port"。我现场核了一遍，**它们零消费者**（§4.5），删掉不破任何契约 |
| 2 | 术语沿用 `chain` | **新增 D7：`chain` → `decision`** | 你说"chain 这个名字不够"。查下来这一个词在本仓指了**四件事**，且函数名与它渲染出的文本互相矛盾（§4.7） |
| 3 | `brain_utils.py` 等 7 个散件"原地不动" | **新增 D8：7 个散件全部解散** | 你说"utils 全部并入图中"。核完发现其中 3 个文件本身就是"装 3 个不相关节点的小函数"的杂物袋，**不是搬家是解散**（§4.8） |
| 4 | `interface/` 装 Port + 状态模型 + 常量 | **`interface/` 瘦身成只装真端口**；状态模型与常量各自归图 | 跟第 1、3 条同一条纪律：**图的东西进图的目录，系统之外的东西才进 interface**（§3.4） |

**另外两处 v1 的自我修正**（查代码时发现的，与你的意见无关）：

- v1 说"`_begin`/`_close` 都变成 episode 图的头尾节点"——**`_begin` 那条站不住**：它要 reset 世界、
>   读起点存档、跑一次视觉感知（推世界 + 调模型），做成图内节点会破掉"`act` 是唯一推世界的节点"
>   这条现行约束。**入口留图外、出口可以进图**，理由见 D1。
- v1 的 D2 说"子侧新增 `outcome` 字段"，但没回答**谁来写它**——`EpisodeRunState` 的现存文档
>   明确写着"`outcome` 不在这里，放进 state 就得有个节点负责填它，而下结论不该是循环节点的副业"。
>   v2 补上落点：**新增 `close_episode` 节点（第 21 个）**，见 D2。

---

## v2 → v3 改了什么（五条，都来自你的五点）

| # | v2 怎么写的 | v3 改成 | 为什么 |
|---|---|---|---|
| 1 | D1 列了三种拼接方式，待拍板 | **D1 定案 ① 纯内置** | 你拍板"内置" |
| 2 | D8-③ 列了甲/乙/丙三个选项 | **乙定案：下沉 tool 层**；并补 §4.8.1 把 trace 那"好几个文件"的职责轴讲清、给出收拢形态 | 你拍板"下沉 tool 层"，同时问"为啥 trace 有两种文件" |
| 3 | §4.0(a) 只给了三层表 | **补 §4.0(a2)：五个可变账字段逐条讲**（谁写、谁读、为什么不进 state、为什么必须落盘 + 一张链的完整走法） | 你说"这几个字段我不理解，需要多解释" |
| 4 | 域① 叫 `boundary/` | **D10：改叫 `open/`**（备选 `head/`） | 你不喜欢 `boundary` |
| 5 | checkpoint 在 tool 层（`tools/checkpoint_tool.py`） | **D9：整包搬进 `harness/checkpoint/`**；`CheckpointToolPort` + 5 个信封 schema 一起作废；顺带修一处越层 | 你说"checkpoint 应该属于 harness 内部"——核下来你的判断站得住（D9 给了判据）。**⚠ 这条落点已被 v6 推翻**（你后来把话收得更紧："不该单独存在，应该和 harness 严格绑定"）——见"v5 → v6 改了什么" |

**另有一处 v2 的事实订正**（写 §4.0(a2) 时查代码发现的，与你的五点无关）：v2 把
`_run_state_dump` 归进"哪都不进的纯宿主态"——**错了**，它是作为一个**自己的键**写进存档 json 的
（`run_state_dump`），与帧账同层。已在 §4.0(a) 就地订正并在那里写明理由。

---

## v3 → v4 改了什么（五条。起因是你问"其他字段我都不理解，要不删了？"）

> **这一轮的性质与前几轮不同**：不是"照你的意见改"，而是**你的疑问逼出了两条没验证的机制**，
> 实测（F10/F11）**推翻了 v3 的一个结构设想**。所以 v4 的重点是"把 deps 的形状定死"，
> 而不是"再加一个字段"。

| # | v3 怎么写的 | v4 改成 | 为什么 |
|---|---|---|---|
| 1 | deps 是 **`RunRuntime` + `EpisodeRuntime` 两个对象**（`run/runtime.py` + `episode/runtime.py`） | **一个 `harness/deps.py`**：一个 `HarnessDeps`（v5 拍平成**不分组的单层**，见下节） | 为回答你的问题去核 deps 形状 → **实测出 F10**：子图的 `context_schema` 声明**不被校验**，穿过去的永远是父那个对象。两个类型 = 静默错误。**v3 的设想从没验证过** |
| 2 | `_run_state_dump` 定位为"episode 层纯透传" | **留，但改名 `run_state_snapshot`，写入点从"入口"搬到 `dispatch` 节点** | 内置子图后**没有"方法入口"了**（`episode.run(req)` 那条路消失）——这是核你的问题时发现的 v3 漏洞：谁写它没安排 |
| 3 | `_world_reset_done` 上移是"可选，不打包票" | **D11：升级为推荐，搬到 `HarnessDeps`** | 你问"这个字段是干什么的"——**答不上来本身就是它放错位置的证据**（它是 run 级的记号） |
| 4 | §4.0 只有三层表，列了 **8 个**字段 | **补 §4.0(a3)：12 个字段逐个裁决**（每个都给"读者是谁 / 删了会怎样 / 裁决"） | 原表**漏了 `_run_id` 与 `_data_center`**，且没回答"没有一个行不行"。12 个里**真能搬的只有 2 个** |
| 5 | D2 只说"子侧改名 `episode_goals`" | **补 D2 补注：还需要一个"投影写入者"** | 键名交集**没有别名机制**——子图要读的每个键，父 state 里必须有**同名**键。改名只是必要条件，还要有 `dispatch` 把 `goals` 投影写成 `episode_goals` |

**两条新实测**（§2 的 F10/F11，探针已沉淀进技能，**29 条断言全绿**）：
**F10** 子图 `context_schema` 声明不生效（静默错）；**F11** context 全程是同一个对象（可变账保得住，
但生命周期得自己管）。这两条一起决定了 `HarnessDeps` 的形状。

---

## v4 → v5 改了什么（一条：撤掉 `HarnessDeps` 里那两个分组）

> 起因是你问"`HarnessDeps` 又是什么东西"。核完发现：**那个 `.run` 是我在 v4 里凭空加的一层**，
> 它的两条依据在代码里**一条都站不住**，所以 v5 把 deps 拍平。

| # | v4 怎么写的 | v5 改成 | 为什么 |
|---|---|---|---|
| 1 | `HarnessDeps` 内含 `RunDeps` / `EpisodeDeps` **两个分组**，`world_reset_done` 落 `HarnessDeps.run` | **一个扁平的 `HarnessDeps`**，只按注释分带（依赖 / run 记号 / 账）；**`HarnessDeps.run` 不存在** | 分组的两条依据在代码里都不成立，而代价是"同一个对象两条合法路径"（见下） |

**为什么撤——两条，都是查代码查出来的**

1. **分组会造出"一个东西两个名字"**：`brain_tool` / `trace` / `data_center` **两个分组里都有**
   （run 图要 brain_tool + trace，episode 图要同一批）。v4 把这写成好话——"同一批 Port 在两侧
   都能读，是设计而不是巧合"——但真相是**没有任何规则**告诉节点该写 `deps.run.trace` 还是
   `deps.episode.trace`：两个名字，同一个实例。这不叫设计，叫**一个东西两个名字**。
   而分组**不产生任何约束**：F10 说 context 的类型声明不被校验，同一次 invoke 也只有一个对象。

2. **"run 侧 / episode 侧"这个轴本身不成立**：v4 说两张帧表是"episode 自己的账"、
   `world_reset_done` 是"run 级的记号"，所以该分居两侧。**查代码：两张帧表的键都是
   `(episode_id, step)`**（`episode_harness.py:229` / `:244`）——它们**跨 episode 累积**，
   只在落盘时切出"本局"那一片（`_frame_ledger()`，`:284-295`），`resume()` 也是把本局切片
   **塞回同一张表**（`:442-447`）。所以帧账活得和 run 一样长，跟 `run_id` / `world_reset_done`
   **完全同级**。而 v4 把 `run_id` 放进 `.episode`、把 `world_reset_done` 放进 `.run`——
   **两样都"整 run 不变"的东西被分到了两边**，这就是那个轴不成立的直接证据。

> **结论**：deps 里**没有一样东西是"每局的"**，它的生命周期只有一个——**一次 run 一份**（F11）。
> 所以不需要嵌套类型来表达分类：**注释分带就够了**（类型不重复，读者照样一眼看懂哪几个是
> 外面递进来的、哪几个是账）。

---

## v5 → v6 改了什么（一条：checkpoint 不再是一个模块）

> 起因是你一句"**checkpoint 不该单独存在，应该和 harness 严格绑定**"。
> v5 的 D9 已经把它搬进 harness 了，但**还给它留了一个自己的包和一套自己的出口**——
> 那还是个"可以单独被谈论的模块"。v6 把它从"搬进 harness 的模块"改成"**harness 自己的一部分**"。

| # | v5 怎么写的 | v6 改成 | 为什么 |
|---|---|---|---|
| 1 | `harness/checkpoint/`（`__init__` + `store.py` + `void.py`，出口 `save` / `load` / `void_archives`） | **没有这个目录**。格式 = `episode/state.py` 的 `EpisodeCheckpoint`（内嵌 `EpisodeRunState`）；写 = `open/save_checkpoint.py` 节点；读 + 废弃编排 = `entry.py`；trace 打标 = `TraceToolPort.void_after` | 你的原话是"不该单独存在"。**只要还给它一个模块 + 一套出口，它就还在单独存在** |
| 2 | `HarnessDeps.checkpoint: CheckpointStore \| None` | **`HarnessDeps.checkpoint_root: Path`** | checkpoint 不再是"外部能力"，只是一条**路径**——依赖清单里少一根 Port（4 根而非 5 根） |
| 3 | `void_after` 的 trace 打标留在 checkpoint 侧 | **`TraceToolPort.void_after(cursor)`** | 原来那个写法**按文件路径读写 trace 目录**，是 `trace/store.py` 边界宣言之外的第三个读者 |

**两条自我更正**（与你的话无关，核代码时发现的）：

- v3 说 `void_after` 的回执是"恢复管线的审计回执"——**查下来没人接它的返回值**
  （`episode_harness.py:417` 那句没有赋值），5 个信封里的 `VoidResp` 是纯装饰。
- v5 的 §5.1 写着"**D9 只搬代码、不改布局**"——**不准确**：json 里 `state_dump` 这个键会改名
  `episode_state`（字段类型从 dict 变成模型）。目录与文件名不变，但**旧存档不可读**。已就地订正。

---

## v6 → v7 改了什么（两处订正 + 一处补漏 + 一节现状。起因是你问"`_world_reset_done` 要删吗""resume 现在做什么"）

> 这两个问题**都不是新需求**，是"把已有机制说清楚"。核的过程中发现 **v6 有一处判断是错的**——
> 它把"`world_reset_done` 不落盘"的理由写成了"重启后 `_begin` 再 reset 一次即可"，
> **漏掉了 resume 这条路径**。

| # | v6 怎么写的 | v7 改成 | 为什么 |
|---|---|---|---|
| 1 | `world_reset_done`"不需要落盘（重启后 `_begin` 再 reset 一次即可）" | **不落盘的结论保留，但补上前提**：`resume` 入口必须**显式**置 `True` | `resume` 路径**不经过 `_begin`**，而本局跑完后**下一局的 `_begin` 会读它**——不置 `True` 就 `reset()`，把刚 `load_state_bytes` 恢复的世界**冲回 ROM 起点**。v6 把它当成"重读一次 ROM 存档"的**代价**，实际是**世界回退**的**错误**（§5.2-8） |
| 2 | §5.1 不变式表写"`resume` **八步**时序" | **七步** | §4.0(b) 的表与 `entry.run_resume()` 的 docstring 都写七步（load / void_after / load_state_bytes / 重建 state / 帧账回载 / RESTORE / invoke）——笔误 |
| 3 | —（没有这一节） | **新增 §4.0(c)：`resume` 今天的两条路径** | 你问"resume 现在做什么"——原来 `resume` 的描述散在四处（§4.0(b) 的七步表、D1 的代价 1、D9 的读写表、§5.1 的时序行），**没有一处把 episode 侧与 run 侧合起来讲** |
| 4 | deps 清单只有**三带 / 11 个字段**，**漏了 run 侧的两个行为开关** | **补一"开关"带**：`auto_push_goals` / `auto_decide_done` | §4.0(a3) 那张表**只数了 `EpisodeHarness.__init__`**；`RunHarness.__init__` 的 8 个参数只被顺带覆盖了 4 个（`trace`/`brain_tool`/`data_center`/`reviewer`）——两个开关整个漏了。而 `plan` 节点的三处读（`:348` / `:388` / `:396`）离不开它们，**4 个真实核对脚本还都传 `False`** 来关掉模型自主规划（`check_harness` / `check_restore` / `resume_only`） |

**一条不该在文档里犯的错**：第 1 条的性质是"**结论对、理由错**"——`不落盘` 是对的，
但它给出的理由只在"全新 run"这条路径上成立。**这类错误比结论错更危险**：读者照理由去验证，
会发现"确实不用落盘"（因为 `_begin` 真的会兜底），从而**确认了一个在 resume 路径上不成立的推论**。
所以 v7 把它写成 §5.2 的一条风险，并给了一句可复用的判据：

> **凡是不经过 `_begin` 就进了恢复路径的场合，都必须自己把这个记号补上。**
> （`_begin` 是唯一读点——这条是从代码里数出来的，不是推出来的。）

## v7 → v8 改了什么（零方案变更：§7 的 10 项待拍板全部定稿）

> 你的原话是"**全按你的决定来**"。所以 v8 不动任何设计，只做一件事：
> 把 §7「仍待拍板」的 10 行**逐行落成定论**（每一项取的就是原文里那一列的推荐），
> 并把"节奏"这一问答掉。**没有第 11 项、没有备选被翻案**——v1–v7 讨论过的机制一字不改。

| # | 定论 | 一句话依据 |
|---|---|---|
| 1 | 子侧改 `episode_goals`；父侧 `goals` 不动，**新增** `episode_goals` 键由 `dispatch` 投影写入 | 两者是不同的东西（领域概念 vs 投影视图），本就该两个键（D2 补注） |
| 2 | `chain` → **`decision`**；`action_chain` → `action_presses` | 每处读出来即中文原话，不需要翻译（D7） |
| 3 | `append_model_calls` **进端口**（`TraceToolPort`） | 让 harness 直接 import 具体模块，会把上次 `tools/interface/` 拆分的成果还回去（D8-③） |
| 4 | 域① 叫 **`open/`** | `entry/` 与 `entry.py` 撞词；`head/` 语义弱于"一条决策的开场"（D10） |
| 5 | D9-v6 三条附带**全接受**：删 `CheckpointToolPort` + 5 信封 / `void_after` 打标还给 trace 端口 / json 键 `state_dump` → `episode_state` | 三条是同一次拆除的三个面，拆开做等于拆三次（D9） |
| 6 | `RunHarness` **留薄类**；`EpisodeHarness` **删** | 前者有外部调用面（`api.py` 持 `handle.harness`），后者没有（D1 落地形态） |
| 7 | `run/` + `episode/`；七域 `open gate retrieve decide press store close`；固定名 `graph.py`/`entry.py`/`state.py`；**`deps.py` 放 `harness/` 根下** | context 全图只有一个类型、且不属于任何一张图（§5.3-3 的例外清单因此变三个顶层文件） |
| 8 | `world_reset_done` **搬到 deps**，且 **`resume` 入口必须显式置 `True`** | `_begin` 是唯一读点，恢复路径不经过它（§5.2-8） |
| 9 | `run_state_dump` **留**，改名 **`run_state_snapshot`**，写入点从"入口"搬到 **`dispatch` 节点** | 内置子图后没有"方法入口"了（D11-(3)、§4.0(a3) 丙被实测否决） |
| 10 | **节奏：步 0 + 步 1 做完停下看一眼** | 步 0 动的是"最危险的改名 + 新增键"，步 1 是纯改名——**两步都为"后面换拼接"清障，且各自可独立回滚**；此时还没碰"两张图怎么连"，停下来复核成本最低 |

**唯一被这次拍板"顺带定死"的形（原先只是推荐）**：`EpisodeCheckpoint` 的类型内嵌
（`episode/state.py` 里持有 `EpisodeRunState` 而不是 `dump: dict`）——它是第 5 条"json 键改名"
的另一半，两处必须同一版落地。

---

## 0. 你的三条，拆成可执行的四件事

| 你的原话 | 落成什么 |
|---|---|
| 严格执行上层到下层多 graph 迭代，用 langgraph 内置的父子图拼接 | run 图 `add_node("episode", ep_graph, error_handler=…)`；`dispatch` 不再是"调一个对象的方法"，而是"父图里的一个子图节点" |
| 第一层：宏观两级图，一级 run，一级 episode | `harness/run/` + `harness/episode/` |
| 第二层：子图分别表示 run 和 episode 的一级展开；run 完全展开，episode 按功能区分 | run 的 5 个节点平铺（`run/` 根下）；episode 的 21 个节点按 **7 个功能域**分文件夹（§3.3） |
| 第三层：完全展开的节点，一个节点的功能用一个文件，graph 只 import | 26 个节点文件 + 2 个 `graph.py`（只有装配与边） |
| 善用文件夹做层级隔离 | §3 目录树；`run/` 与 `episode/` 两棵不相交的树，只有 `dispatch` 一处相交 |

**四件事**：① 拼起来（换拼接方式 + 异常兜底 + limit 重标定）；② 分家（节点一人一文件、散件解散）；
③ 立契约（父子交界必须是显式模型，不能靠"碰巧同名"）；④ 立机械保证（防它半年后又长回单体）。

---

## 1. 现状（可测）

| 量 | 值 |
|---|---|
| `episode_harness.py` | **1749 行** = 1 个类 + 20 个节点方法 + 3 个图外方法（`_begin`/`_close`/`_invoke`）+ 3 个帧账辅助 |
| `run_harness.py` | **677 行** = 1 个类 + 5 个节点方法 + 2 个路由/组装方法 + `resume_run` |
| 两张图怎么连 | `RunHarness.dispatch()` 里 `self._episode.run(req)` —— **显式方法调用**，LangGraph 完全不知道 episode 是个图 |
| 图装配在哪 | 各自 `_compile()`，节点实现与边交织在同一文件 |
| 节点数 | episode **20**、run **5** |
| 接口层的两张 Port | `HarnessPort`（182 行）/ `EpisodeHarnessPort`（471 行）——**零消费者**（§4.5） |
| 散件 | 7 个文件 545 行：`brain_utils` 81 / `game_utils` 77 / `run_plan_utils` 85 / `episode_utils` 115 / `run_utils` 56 / `memory_query_utils` 73 / `trace_write` 58 |
| checkpoint | `tools/checkpoint_tool.py` **264 行** = 1 个类 + 5 个信封的组装/解包 + 一段**按文件路径读写 trace** 的越层代码。唯一消费者是 harness（图内 `save_checkpoint` + 两个 `resume`）；`_meta()` 的 8 个键里 **6 个是 harness 的 state**——**形状由 harness 的 state 决定**，这就是 D9 的现场证据 |
| 碰 trace 的文件 | **6 个、跨 3 层**（`trace/` 包 3 + `tools/` 2 + `harness/trace_write.py` 1）——职责轴见 §4.8.1 |
| `recursion_limit` | episode 级：`(max_steps - step) * 17 + 20`；run 级：`len(goals) * (MAX_GOAL_RETRIES + 1) * 4 + 60`——**两层各自算，因为两张图各 invoke 各的** |

**这不是"架构坏了"，是"两张图的外壳粘在一起"**：现在 `dispatch` 的 try/except `AgentError`
（"单局异常不崩掉整个 run"）之所以成立，正因为 episode 那次 invoke 发生在 `dispatch` 的
函数体里。改成内置子图之后，**这条契约会失去落点**——见 §2 F3/F4。

---

## 2. 实测：langgraph 1.2.11 的父子图语义

> **十一条**全部在本机 `.venv`（langgraph 1.2.11）跑过。结论与参数在这里，
> **这一节是本 PLAN 的地基：§4 的每个决策都指着这里的编号。**
> （F10/F11 是 v4 新增——起因是你问"`_run_state_dump` 要不要显式"时，我发现
> "run 与 episode 各一个 runtime"这个 v3 设想从没被验证过。）

| # | 测什么 | 实测结论 | 对本次的意义 |
|---|---|---|---|
| **F1** | 父 state 与子图 schema **不同**时，能不能直接 `add_node(compiled_subgraph)` | **能。** 传递模型是**键名交集**：父 state 的同名键喂给子图当年初值；子图输出的同名键合并回父 state；父图没有的键**丢弃** | 拼接可行，但"交界"是**键名**，不是显式调用——所以 D2 那张表是必需的；F1 还有一条**反作用**：子图不输出的键，父侧保持旧值（陈旧陷阱，D2-④） |
| **F2** | 父子**同名但不同型** | **`ValidationError` 当场炸**（`list[TaskForBrain]` 喂给 `list[GoalForBrain]`） | 现成的雷：两张 state 都有 `goals`，类型不同。**不先解掉，直挂就崩**（D2-①） |
| **F3** | 直挂的子图内部抛异常 | **一路冒到 `graph.invoke()` 调用方**，父图任何节点都接不住 | 现在"单局异常不崩 run"的落点消失——**必须另找兜底**（D1/F4） |
| **F4** | `add_node(..., error_handler=fn)` 挂子图节点 | **能兜住子图内部异常。** handler 签名 `(state, error: NodeError) -> Command \| dict`，**拿到的 state 是父 state**（不是子图的）；返回 `Command(goto="reflect", update={...})` 时**流程正常继续**；只返回 dict 时**图停在该节点**（后续不跑） | 这是"纯内置拼接"能不能成立的**决定性一条**：异常兜底有官方落点，且写在 run 图一侧 |
| **F5** | 子图步数算不算进父图 `recursion_limit` | **算。** 父 1 步 + 子 3 步 = 需要 `limit ≥ 4`（`limit=3` 抛 `GraphRecursionError`） | **run 级公式必须重标定**：从"只管 run 自己那 5×N 个节点"变成"要覆盖全部 episode 内部步数"（D6） |
| **F6** | `context_schema` + `Runtime[Deps]` | 官方依赖注入通道；**父图 `invoke(state, context=deps)` 的 context 自动穿透进子图**；节点保持 `(state, runtime) -> dict` 的纯函数形态；只写 `(state)` 也兼容 | 依赖注入的落点定了，**不需要**闭包/偏函数/节点工厂三件套（D3） |
| **F7** | 子图 `compile(input_schema=..., output_schema=...)` | 生效：输入按 `input_schema` 裁剪、输出按 `output_schema` 限制回传键 | 可以把"run ↔ episode 传什么"写成**两个显式模型**，而不是散在代码里的约定（D2） |
| **F8** | 同一个编译好的子图，在父图**环里被调多次** | 每次进子图，state **按父 state 的同名键重建**（不是复用上次的终态）。两次调用互不残留 | 跨 episode 的可变账（帧登记表等）**不能指望子图自己记住** → 归 deps（D4） |
| **F9** | 观测台的数据源 | `api.py` 的 SSE 是**轮询 `LocalTrace`**，不吃 LangGraph stream（`stream_mode="updates"` 且不传 `subgraphs=True` 时，只看得见父图节点名） | **观测台零影响**——它吃的是 trace 事件，事件照旧由节点写。不必动 `web/` |
| **F10** | **父子 `context_schema` 声明不同类型**时会怎样 | **穿过去的永远是父的那个对象**，子图自己那句 `StateGraph(..., context_schema=EpDeps)` **不被校验**。子图节点声明 `Runtime[EpDeps]` 却拿到 `RunDeps` 实例——读 `episode_id` **不报错**，静默得到"属性不存在"（属性名恰好撞上时更糟：拿到**语义不同**的值）。与 F2 相反，这是**不炸的错** | **否决"run 一个 context / episode 一个 context"**：`context_schema` 只能有一个类型。落地 = **一个 `HarnessDeps`**（v5：单层不分组，见 D3 修订） |
| **F11** | 父图**循环多圈**时，context 是不是同一个对象 | **是同一个**（实测 id 全同，外部传入的 deps 被**原地修改**，循环结束后外部引用看得见累积结果）。与 F8 恰好相反：**state 每进子图重造，context 全程不重建** | 可变账（帧表）放 context **保得住**，跨 episode 也活着（D4 修订）。**代价**：它是外部传入的对象 → **生命周期必须显式约定为"一次 run 新建一个"**，否则第二次 run 会带着上一次的残留帧账 |

---

## 3. 目标结构

### 3.1 目录树

```
pokemon_agent/harness/
├── __init__.py                    统一出口（懒加载表跟着更新）
│
├── deps.py                        ← **全图唯一的 context**（F10：context_schema 只能有一个类型）。
│                                    `HarnessDeps` **一个扁平对象**（v5：v4 那两个分组已撤），
│                                    字段只按注释分四带：注入的依赖 / 行为开关 / 整 run 的记号 / 整 run 的账。
│                                    住根下的理由：**它不属于任何一张图**（两图共用的唯一对象）。
│                                    生命周期由 `run/harness.py` 规定：**一次 run 新建一个**（F11 的代价）。
│
├── run/                           ← run 级图：5 个节点，完全展开（节点直接平铺在根下）
│   ├── __init__.py                域出口
│   ├── graph.py                   装配：5 个 add_node + 挂 episode 子图 + 3 条条件边（只 import，不写实现）
│   ├── state.py                   RunState + ResumeEpisode
│   ├── entry.py                   图外侧门：run_new() / resume_run()
│   ├── begin.py                   begin 节点
│   ├── plan.py                    plan 节点 + PLAN_MAX_PUSH / PLAN_MAX_ATTEMPTS / RUN_TRACE_MASK
│   │                              + to_tasks() / apply_goals_edit()
│   ├── dispatch.py                dispatch 节点（只做前置：episode_id + attempts+1 + 备好 EpisodeInput）
│   │                              + episode_error_handler()（F4 的兜底，挂子图节点）
│   ├── reflect.py                 reflect 节点 + MAX_GOAL_RETRIES + goal_retries_exhausted()
│   ├── review.py                  review 节点 + episode_trace_events()
│   └── harness.py                 RunHarness 薄类（外部调用面，见 D1-落地形态）
│
├── episode/                       ← episode 级图：21 个节点，按 7 个功能域分文件夹
│   ├── __init__.py                域出口
│   ├── graph.py                   装配 + EpisodeInput/EpisodeOutput + 那张 21 行职责表
│   ├── state.py                   EpisodeRunState + **EpisodeCheckpoint**（D9-v6：checkpoint 的格式就是它）
│   ├── entry.py                   图外侧门：run_new(_begin) / run_resume(resume 七步)
│   ├── open/                      ① 一条决策的开场：存上一环 → 记这一环的输入
│   │   │                             （`open` 是**每决策一次**的段落；`close/` 是整局收尾，两者不同层级）
│   │   ├── save_checkpoint.py
│   │   └── record_observation.py
│   ├── gate/                      ② 判停与空间
│   │   ├── judge.py
│   │   └── get_action_space.py
│   ├── retrieve/                  ③ 四路检索 + 汇聚
│   │   ├── step_episode_memory.py
│   │   ├── global_episode_memory.py        + build_scene_key()
│   │   ├── knowledge_semantic_memory.py    + build_knowledge_query()
│   │   ├── object_semantic_memory.py
│   │   └── merge_retrieval.py
│   ├── decide/                    ④ 决策
│   │   └── think_action.py                 + DECISION_MAX_RETRIES + choose_with_retry()
│   ├── press/                     ⑤ 链内一圈（每键走一次）
│   │   ├── act.py
│   │   ├── perceive_after_action.py        + PERCEPTION_MAX_RETRIES
│   │   │                                   + perceive_with_retry() + compute_stop()
│   │   ├── apply_stop.py
│   │   ├── detect_stall.py                 + STALL_LIMIT + compute_stall()
│   │   └── close_step.py
│   ├── store/                     ⑥ 落库
│   │   ├── step_episode_memory.py
│   │   └── object_semantic_memory/          ← 270 行判定层会被搬进来，所以拆成包
│   │       ├── __init__.py                 节点本体
│   │       └── rules.py                    ← 现 object_interactions.py 的判定规则
│   └── close/                     ⑦ 收尾
│       ├── close_episode.py                ← 新增第 21 个节点：算 outcome + 写 EPISODE_END
│       ├── retrieve_verify_step_memory.py
│       ├── retrieve_verify_knowledge.py    + build_verify_knowledge_query()
│       └── verify_and_summarize.py
│
├── interface/                     ← 只装"实现方在系统之外"的真端口（§3.4）
│   ├── __init__.py
│   ├── human_reviewer.py          HumanReviewer
│   └── domain/human_decision.py   HumanDecision
│
├── run_data_center.py             前后端交互中间层（不是图，保留原地）
└── auto_reviewer.py               AutoContinueReviewer（HumanReviewer 的一个实现，保留原地）
```

**消失的东西**：`episode_harness.py`（1749 行）、两张 Port 文件（653 行）、
7 个散件里的 **7 个**（`trace_write` 也已随 D8-③ 下沉 tool 层）、
`object_interactions.py`（搬进 `store/object_semantic_memory/rules.py`）、
**`tools/checkpoint_tool.py`（264 行，D9-v6：**解散**进 harness，不建 `harness/checkpoint/` 包）**、
**`CheckpointToolPort` + 5 个 `FromHarnessToCheckpointTool*` 信封 schema**。

**checkpoint 在目录树上没有自己的位置——这是 D9-v6 的要点**：它的**格式**住 `episode/state.py`
（`EpisodeCheckpoint`），**写**住 `episode/open/save_checkpoint.py`，**读与废弃编排**住
`episode/entry.py`。三处都是本来就存在的地方。

**留下的两个顶层文件**：`run_data_center.py`（前后端交互层，本来就不是图的一部分）、
`auto_reviewer.py`（`HumanReviewer` 的一个默认实现）。

### 3.2 行数逐层递减（编码范式的硬要求）

| 层 | 文件 | 量级 |
|---|---|---|
| 顶层：装配 | `run/graph.py`、`episode/graph.py` | **各 ~45–70 行**（只有 `add_node`/`add_edge`/两个 schema） |
| 次层：域出口 | `episode/<域>/__init__.py` × 7 | **~8 行**（re-export 本域节点） |
| 末层：节点实现 | 26 个文件 | **~15–90 行**（一个节点的全部：契约、记账、状态增量） |
| 图外上下水 | `run/entry.py` / `episode/entry.py` | 各 **~120–200 行**（`resume` 的七步准备占大头） |
| 外部调用面 | `run/harness.py` | **~100 行**（`__init__` 装 runtime + 四个委托） |
| 图的持久化 | `episode/state.py` 的 `EpisodeCheckpoint` + `open/save_checkpoint.py` | **~15 + ~35 行**（原 264 行减去五个信封、再减去越层的 trace 打标与 memory 委托——那两件各归其主） |

现状是"1749 行单体"，改造后顶层 70 行 + 26 个末层文件——**顶层即流程，细节按需下钻**。

### 3.3 七个功能域怎么切出来的（不是拍脑袋）

切法是**照着图本身的自然断点**，不是照概念分类：

| 域 | 节点 | 断点依据 |
|---|---|---|
| `open/`（原 `boundary/`，v3 改名见 D10） | save_checkpoint / record_observation | 图上是**一条决策的开场两连**（存上一环 → 记本环输入），每决策一次；它们既不判也不改 state |
| `gate/` | judge / get_action_space | 一个判"该不该停"、一个算"能按什么"——**出循环与进循环的两个闸口** |
| `retrieve/` | 4×`retrieve_*` + merge_retrieval | 这五个在图上是一条直线且**彼此无数据依赖**（都只读 `observation`）；`merge_retrieval` 是它们的汇聚点 |
| `decide/` | think_action | 一次决策一格，自带重试循环 |
| `press/` | act / perceive_after_action / apply_stop / detect_stall / close_step | **链内小循环的完整一圈**（含 `close_step` 的分叉出口）——它循环的正是这五个 |
| `store/` | store_step_episode_memory / store_object_semantic_memory | 两个 store 的输入契约相同（`before`/`action`/`after` 三件套），且都只落库不改 state |
| `close/` | close_episode / 2×`retrieve_verify_*` / verify_and_summarize | **收尾链**：主循环结束后的四格，与主循环完全不相交（只在 `judge` 判 done 后进） |

**为什么 `close_episode` 要新加**：v1 想让它留在图外（`run()` 里的 `_close`），但 F1 的
"子图输出按键名合并回父 state"要求 `outcome` **必须由子图写出**，否则父侧 `reflect` 读到的是
上一轮的陈旧值（D2-④）。而"下结论"确实不该是循环节点的副业——所以给它一个自己的格子，放在
`close/` 域。**21 个节点**。

### 3.4 `interface/` 只装真端口

**判据**：**"港口"的定义是"实现方在系统之外"。**

| 名字 | 实现方 | 是港口吗 | 处置 |
|---|---|---|---|
| `HumanReviewer` | 前端（`DataCenterReviewer`）/ 兜底放行者 / 测试假件 | **是**（系统之外） | **留**，原地 |
| `HumanDecision` | 同上（数据形状） | **是** | **留**，原地 |
| `HarnessPort` | 隔壁文件的 `RunHarness` | **不是**（镜子） | **删**（D5） |
| `EpisodeHarnessPort` | 隔壁文件的 `EpisodeHarness` | **不是** | **删**（D5） |
| `CheckpointToolPort` | 隔壁文件的 `CheckpointTool`——而它描述的是 **harness 自己的 state** | **不是**（错放的抽屉） | **连实现一起解散进 harness，端口随之消失**（D9-v6） |
| `RunState` / `ResumeEpisode` | ——（是状态，不是能力） | **不是** | 搬 `run/state.py` |
| `EpisodeRunState` | —— | **不是** | 搬 `episode/state.py` |
| 三个常量 | —— | **不是** | 归各自服务的节点文件（D8-②） |

**一句话**：`interface/` 从此只回答"harness 需要外面给什么"，不再回答"harness 自己长什么样"。

### 3.5 散件解散映射表（每个函数归它唯一的服务者）

| 现在 | 函数 / 常量 | 归到 |
|---|---|---|
| `brain_utils.py` | `choose_with_retry` + `DECISION_MAX_RETRIES` | `episode/decide/think_action.py` |
| `game_utils.py` | `perceive_with_retry` + `PERCEPTION_MAX_RETRIES` | `episode/press/perceive_after_action.py` |
| `memory_query_utils.py` | `build_knowledge_query` | `episode/retrieve/knowledge_semantic_memory.py` |
| | `build_scene_key` | `episode/retrieve/global_episode_memory.py` |
| | `build_verify_knowledge_query` | `episode/close/retrieve_verify_knowledge.py` |
| `episode_utils.py` | `compute_stop` | `episode/press/perceive_after_action.py` |
| | `compute_stall` | `episode/press/detect_stall.py` |
| | `derive_episode_reason` | `episode/close/close_episode.py` |
| `run_plan_utils.py` | `ask_planner_with_retry` / `to_tasks` / `RUN_TRACE_MASK` | `run/plan.py` |
| `run_utils.py` | `goal_retries_exhausted` | `run/reflect.py` |
| | `episode_trace_events` | `run/review.py` |
| | `apply_goals_edit` | `run/plan.py`（与 `plan` 同族：都是"改目标栈"） |
| `episode_harness.py` 里的常量 | `STALL_LIMIT` | `episode/press/detect_stall.py` |
| | `JUDGE_CHAIN_HISTORY` / `JUDGE_HISTORY_KEY_CAP` | `episode/gate/judge.py` |
| | `NODES_PER_DECISION` / `NODES_PER_PRESS` | `episode/graph.py`（它算的是 limit，属装配） |

**归位判据**：**"这个函数/常量，删掉它唯一的调用者之后还有没有人要？"** 答案是否 → 跟着调用者走。
7 个文件里只有 `trace_write.py` 的答案是"是"（4 个宿主），单独处置（D8-③）。

---

## 4. 设计决策

### 4.0 先把两条机制讲清楚（你点名要的）

#### (a)"可变账归 `HarnessDeps`，不进 state"——**这不是我的新主张，是现状的显式化**

先纠正一个容易误解的地方：**"不进 state" ≠ "不落盘"**。现在这套东西是**三层**，不是两层：

| 住哪 | 具体东西 | 进 `EpisodeRunState`？ | 进存档 json？ | 谁读它 |
|---|---|---|---|---|
| **图状态** | `observation` / `step` / `plan` / `pending_presses` / `stall_count` … | ✅ | ✅（`state_dump` 键） | 每一个节点 |
| **不进 state、但进存档的旁路键** | `_frame_event_ids` / `_pending_frames` / `_run_state_dump` | ❌ | ✅（**存档 json 自己的键**） | `save_checkpoint` / `record_observation` / `_frame_b64` |
| **纯宿主态** | `_graph` / `_world_reset_done` | ❌ | ❌ | 图外上下水 |

> **v3 订正一处**：v2 把 `_run_state_dump` 误归进第三层（"哪都不进"）。核对代码后它其实跟帧账**同层**
> ——`save_checkpoint` 把它作为一个**自己的键**（`run_state_dump`）写进同一份存档 json
> （`checkpoint_tool.py` 的 `_meta()` 第 5 行），恢复时 `resume_run()` 正是从那个键取回 run 级状态。
> 区别在**用途**：帧账是"图上要对账的表"，`_run_state_dump` 是"run 级搭 episode 级存档的车"；
> 相同点在**归属**：都不是 state，都要落盘。

第二层是关键：**它要落盘**（不然 `resume()` 之后第一条 `OBSERVE` 和第一个 store 步的
`before_frame` 会一起丢图——真机 `check_restore` 就是在这个缺口上丢过帧），
**但不能混进 `state_dump`**。两条理由，都在现场：

1. **语义**：`EpisodeRunState` 的每个字段都是**某个节点的读/写对象**。状态里没有哪个节点
   需要"一张 PNG 字符串"——`record_observation` 要的是"这一帧的 `event_id`"，拿去
   `_frame_b64()` 读盘（截图本来就在 `screenshot/<event_id>.png`）。把一个**没人读的大字符串**
   放进每个节点都能看见的 state，是给 21 个节点加噪音。
2. **量级与冗余**：一张 GBA 截图 base64 约 3.7 KB，而 `save_checkpoint` **每步（链边界）写一份**
   ——混进 `state_dump` 就是每份存档都背一张 PNG，而 PNG 在磁盘上**已经有一份**。
   （这条代价在 `PLAN_checkpoint` 里已经算过并否决过一次，当时的结论就是"当存档 json 自己的
   一个键"。）

**那重构后为什么需要 `HarnessDeps`？** 因为节点从"方法"变成"自由函数"之后，
`self` 这条通道没了。**它不是新概念，是 `self` 减去 state 之后剩下的那一半**
（v4 修订：不是"两侧各一个 runtime"，而是**一个 `HarnessDeps`**；v5 再进一步**去掉分组**，
理由见"v4 → v5 改了什么"与 D3 修订）：

```
现在的 EpisodeHarness.__init__ 里那 12 个字段            重构后（v6）
├── _game/_memory/_brain_tool/_trace             → HarnessDeps（4 根 Port）
├── _checkpoint                                  → 不再是依赖（D9-v6：解散进 harness），
│                                                  只余 checkpoint_root 一条路径
├── _run_id / _data_center                       → HarnessDeps（2 个不可变量）
├── _frame_event_ids / _pending_frames           → HarnessDeps（两张账，整 run 累积）
├── _run_state_dump                              → HarnessDeps（run 侧递进来的原料）
├── _world_reset_done                            → HarnessDeps（★D11：语义本是 run 级）
├── _graph                                       → episode/graph.py 模块级（编译一次）
└── 20 个节点方法                                 → 21 个自由函数 (state, runtime) -> dict
```

**判据（一句话）**：**节点需要它、但它跨不过 checkpoint 的 JSON 边界** → 进 deps；
**能 JSON 化且图上要读** → 进 state。

> **v7 补注——这张表数的是谁**：它只列了 `EpisodeHarness.__init__` 的字段。`RunHarness.__init__` 的 8 个参数里，`trace` / `brain_tool` / `data_center` / `reviewer` 已经在这张表里（两侧共用同一个对象），但 **`auto_push_goals` / `auto_decide_done` 两个行为开关原先两处都没数到**——它们同样进 deps（D3 的"开关"带）。教训：**数字段时要说清"数的是哪个类的"**，否则两个类各数一半，漏的那个谁都不认领。

**为什么放 deps 而不是别处**——F11 给了机制依据：context **整个 invoke 期间是同一个对象、
不被子图重建**，所以"跨 episode 要活着的账"（帧表、`world_reset_done`）放它里面才保得住；
而 F8 说子图 **state 每次重建**，所以 state 里放不住这些。

> **顺带发现（v3 记作"可选"，v4 升级为推荐 → D11）**：`_world_reset_done` 的语义其实是 **run 级**的
> ——"世界起点存档只读一次"跨 episode 成立，而 deps **一次 run 只建一份**（F11）。它现在混在
> episode 那一堆字段里、却跟"哪一局"无关，所以归到 run 那一带去；这样 deps 里
> **一样"每局的东西"都没有**，"子图每次重建"（F8）与它再无关系。
> 升级理由：你问"这个字段是干什么的"**本身就是它放错位置的证据**（见 §4.0(a3) A 组的判据）。

> **v3 补充**：这五个字段的**逐条讲解**（谁写、谁读、为什么不进 state、为什么必须落盘）
> 与"一条链从头走一遍"的用法演示见 **§4.0(a2)**——本节只给分类，那一节给故事。

#### (a2) 那五个字段逐个讲（v3 新增，因为"表"讲不清"为什么"）

**它们共同的性质**：都是"**图外的那一刻**"与"**图内的节点**"之间**没有别的地方可以放**的东西。
`state` 是给节点读写的，这五样都不满足"某个节点在图上读它"这个条件——所以它们既不该进 state，
又不能没有归宿。

| 字段 | 是什么（一句话） | 谁写 | 谁读 | 为什么不进 state | 要不要落盘 |
|---|---|---|---|---|---|
| `_graph` | 编译好的图对象 | `__init__` | 图的 `invoke` | 它是**装配产物**，不是数据 | 不要（启动时重编译） |
| `_world_reset_done` | "世界起点存档已经读过了"这个记号 | `_begin` | `_begin` | 它是**做过的动作**的记号，不是这一局的数据；而 episode state 每局新造一份 | **不要落盘**，但**两处都要显式写**——`_begin`（首局 reset 后）与 `resume()`（恢复后）；**后者不能省**，理由见 §5.2-8 |
| `_run_state_dump` | 这一局对应的 `RunState.model_dump()` | `run()` / `resume()` 入口 | `save_checkpoint`（**纯转发**） | episode 图**没有节点读它**——它是 run 级的东西搭 episode 级存档的车 | **要**——写进同一份存档 json 自己的键（`run_state_dump`） |
| `_frame_event_ids` | `(局, 步号) → 承载这一帧的事件的 event_id` | `record_observation`（第 0 步）/ `perceive_after_action`（链内与链尾） | `_frame_b64`（store 步要帧时） | 3.7 KB 的反面：它是**小整数表**，但**没有节点要它**；它是"对账"，不是"状态" | **要**——不落盘，`resume` 后链首 `OBSERVE` 与第一个 store 步的 `before_frame` 一起丢图 |
| `_pending_frames` | `(局, 步号) → 那一步开局画面的 base64 PNG` | `_begin`（**只在第 0 步**） | `record_observation`（**取走即删**） | 3.7 KB × 每步一份存档；而且**没有节点要 PNG 字符串**（要图的是 store 步，它按"帧的字节"要） | **要**，但它只活到链首那一格 |

**两条机制是这节的真正难点**（只说"不进 state"是讲不明白的）：

1. **为什么需要"登记表"。** 截图与 trace 事件**共享 event_id**（文件名 = `<event_id>.png`），
   所以"某一步的开局画面在哪个文件"**不能由步号算出来**——而"这一帧挂在哪条事件上"是**不固定的**：
   开局那一帧挂 `OBSERVE`，之后每一帧挂那一键自己的 `AFTER_ACTION`（链内键根本不过 `record_observation`）。
   所以必须有一张 `(局, 步号) → event_id` 的对账表。
2. **为什么还需要"暂存表"。** PNG 进不了领域模型 `Observation`，所以帧要从"产出它的那一格"
   传一手到"把它挂上事件的那一格"。多数时候这两格**是同一格**（`perceive_after_action` 产出帧、
   当场挂到自己的 `AFTER_ACTION` 上），压根不用暂存；**唯一的例外是第 0 步**——那一帧由 `_begin`
   产出，而 `_begin` 在**图外**，没有"自己那条账"可挂。于是先把字节放进暂存表，等链首
   `record_observation` 记 `OBSERVE` 时取走（`pop`），挂完即删。**这解释了为什么它"只在第 0 步非空"。**

**一条链从头走一遍**（把两张表的用法走完，比任何定义都清楚）：

| 时刻 | 谁 | 做什么 | 两张表的变化 |
|---|---|---|---|
| 开局 | `_begin`（**图外**） | 感知一帧 | `_pending_frames[(ep,0)] = PNG`（还没有账可挂，只能先存字节） |
| 链首 | `record_observation` | 记 `OBSERVE` | 表①：`pop` 出 PNG → 挂到这条 OBSERVE 上；表②：`_frame_event_ids[(ep,0)] = 这条的 event_id` |
| 链内/链尾 | `perceive_after_action`（每键） | 感知一帧 | 帧**当场**挂到自己那条 `AFTER_ACTION`；`_frame_event_ids[(ep, 步号+1)] = 那条的 event_id`（**+1**：这一帧是"下一键的开局画面"） |
| 下一链链首 | `record_observation` | 记 `OBSERVE` | 不问暂存表（它是空的）——改按 `_frame_b64(ep, obs.step)` 从 `screenshot/` **读回**上一链链尾那一帧 |
| 每链边界 | `save_checkpoint` | 写存档 | 把**本局切片**摊成两张"步号说话"的表，写进 json 的 `frame_event_ids` / `pending_frames` 两个键 |
| 恢复 | `resume()`（**图外**） | 重建 state | 从存档回载两张表 → 于是恢复后第一条 `OBSERVE` 与第一个 store 步的 `before_frame` 都还拿得到图 |

> 一句话收束：**登记表记"哪条事件承载这一帧"（小、长期、跟存档走）；暂存表搬"这一帧的字节"
> （大、一次性、只在第 0 步非空）。** 前者是"对账"，后者是"接力棒"。

#### (a3) 十二个字段逐个裁决：谁能删、谁不能、删了会怎样（v4 新增）

**(a)/(a2) 只讲了"它们住哪"，没讲"没有一个行不行"**——这是你问"要不删了"时暴露的真缺口。
下面按**裁决**分三组，每行都给"**读者是谁 / 删了会怎样**"。先给总数：

> `EpisodeHarness.__init__` 今天有 **12 个**实例字段（不是 v2/v3 图上列的 8 个——表漏了
> `_run_id` 与 `_data_center`，v4 补齐）。**真正能消掉的只有 2 个**；其余 10 个要么是
> "外部递进来的依赖"（7 个，本来就在 `__init__` 里，重构只是换载体），要么是"必须有归宿的数据"（3 个）。

**A 组：能搬走的（2 个）——你说"不知道它是干什么的"，恰好证明它放错了地方**

| 字段 | 是什么 | 谁读它 | 搬走后 | 裁决 |
|---|---|---|---|---|
| `_graph` | 编译好的图对象 | 图外的 `invoke` | 编译一次的东西，本来就该是**模块级常量** | **搬** → `episode/graph.py` 模块级（D3 已定） |
| `_world_reset_done` | "世界起点存档已经读过了"这个记号 | `_begin`（读）/ `_begin`+`resume()`（写，2 处） | **语义本来就是 run 级**：`reset()` 只在 run 的第一个 episode 跑，之后每局**接着上一局的世界继续**（本局起点 = 上一局终点，见 `episode_harness.py:581-587`） | **搬** → `HarnessDeps`（**D11，v4 从"可选"升级为"推荐"**） |

**B 组：不能删、但也不是"账"的（7 个）——它们是外部递进来的依赖**

| 字段 | 是什么 | 谁读它 | 删了会怎样 | 裁决 |
|---|---|---|---|---|
| `_game` / `_memory` / `_brain_tool` / `_trace` | 4 根 Port | 几乎每个节点 | **什么都做不了**（铁律 2：大脑与 harness 只通过 Port 与外界交互） | **留**（依赖注入本体） |
| `_checkpoint` | 第 5 根 Port | `save_checkpoint` 节点 / 两个 `resume` | —— | **删**（D9-v6：它描述的正是 harness 自己的 state，**不该以"外部能力"的形态存在**；整根换成 `deps.checkpoint_root: Path`） |
| `_run_id` | 这次 run 的标识 | 6 处：`read_screenshot(run_id, event_id)` 拼截图路径、标 `EpisodeMemory.run_id`、给事件盖 `run_id` | 截图路径拼不出来、记忆与事件标不上 run → trace 分组全乱 | **留**（构造时注入的**不可变量**，不是状态） |
| `_data_center` | 前端中间层（前端 ↔ 后端插话槽） | 1 处：`think_action` 取 `human_note`（`episode_harness.py:1122`，只读那一个槽） | 真人实时插话失效 | **留**（同上，注入的不可变量） |

**C 组：不能删、且真的要有归宿的（3 个）——但只有前两个是 episode 自己的账**

| 字段 | 是什么 | 谁读它 | 删了会怎样 | 裁决 |
|---|---|---|---|---|
| `_frame_event_ids` | `(局, 步号) → 承载这一帧的事件 id` | `_frame_b64()`（store 步要帧时）/ `save_checkpoint`（打包） | `resume` 后链首 `OBSERVE` 与第一个 store 步的 `before_frame` **一起丢图**（真机 `check_restore` 踩过） | **留**（你已理解的那个） |
| `_pending_frames` | `(局, 步号) → 第 0 步开局帧的 PNG` | `record_observation`（链首取走即删） | 第 0 步链首 `before_frame` 丢图 | **留**（你已理解的那个） |
| `_run_state_dump` | 这一局对应的 `RunState.model_dump()` | `save_checkpoint`（**写**）/ `RunHarness.resume_run()`（**读**，`run_harness.py:218`） | **跨进程恢复拿不到 run 级状态**（目标栈 / 派发计数 / 已完成结算全丢）→ `resume_run()` 无从重建 `RunState` | **留**——理由见下，**这不是"感觉"，是一条踩过坑的决定** |

**`_run_state_dump` 为什么删不掉（你说"感觉不用显式了"——方向对了一半）**

它看着像"纯透传、本层不解读"，很容易被当成冗余。但它是一次**实测崩溃的修复产物**
（`CHANGELOG.md` 2026-09-09「run.json 合并进 step 存档：彻底消掉 resume_run() 的锚点读取歧义」）：

- **改之前的形态**：run 级状态单独存一份 `checkpoints/run.json`。`resume_run()` 靠
  `load(run_id, episode_id, 0) or latest_run()` 猜该读哪份——**实测必炸**
  （`AssertionError: no run.json anchor`：这一局只要跑过 step0，`load()` 就先命中
  `step/<eid>/0.json`，`run.json` 的兜底分支永远走不到）。
- **改之后**：`RunState` 与 `EpisodeRunState` **打包进同一份存档**，恢复时读那一步的
  checkpoint 就同时拿回两层状态，"**不用再猜该读 run 锚点还是 episode 锚点**"。
- **它的必要性由"跨进程"决定**：`experiment/real_check/resume_only.py` 写得明白
  ——"带 `resume_cursor` 重新 `build_real`（**新进程语义**）→ `resume_run()`"。
  新进程里根本没有内存中的 `RunState`，它**只能从磁盘拿**。
- **而 `resume_run(run_id, episode_id, step)` 的签名里没有 run state 参数**
  （`run_harness.py:195`），所以它除了存档**没有第二个来源**。

**那能不能"不显式"**——三个方案，逐个判：

| | 做法 | 判 |
|---|---|---|
| **甲（现状保留，推荐）** | runtime 上一个字段，`save_checkpoint` 读它 | ✅ 一个 dict、每步一份，不是 PNG 那种量级问题；**代价只是命名**（"episode 层纯透传"听着含糊） |
| 乙（进交界契约） | `EpisodeInput.run_state` 声明它，子图从 state 读 | ❌ 需要**父 `RunState` 加一个"自我快照"键**（自己 dump 自己），且 F2 的同名不同型风险又要重查一遍——**比现状更绕** |
| 丙（run 单独存档） | 回到 `run.json` | ❌ **已被实测否决**（就是上面那条 CHANGELOG） |

**结论：留（选甲）。** 但它该**重新归类**——它不是你"不知道的账"，它是 **run 侧递进来的原料**：
episode 不解读它、只是把它跟自己的状态一起打包，因为**存档格式决定了"两层状态必须在一份文件里"**。
所以它的正确定位是"**run 借 episode 存档的车**"，不是"episode 的第三个账"。

> **一句话收束整节**：12 个字段里**只有 `_frame_event_ids` / `_pending_frames` 两个是 episode 自己的账**
> ——你"只理解这两个"这件事本身是对的，不是知识缺口。其余 10 个是**外面递进来的**
> （7 个依赖 + `_run_state_dump`）或**放错地方的**（`_graph` / `_world_reset_done`，搬完就消失）。
> 搬完之后 `HarnessDeps` 里剩下的，没有一个是你需要"理解它从哪来"的。

#### (b)`resume()` 为什么必须留图外——**这不是取舍，是逻辑上的先后**

`resume()` 现在做七步，其中**前六步的产物就是"图的初始状态"**：

| 步 | 做什么 | 是谁的事 |
|---|---|---|
| 1 | `checkpoint.load()` | 磁盘 |
| 2 | `void_after(cursor)` —— 按游标**截断磁盘上的 trace / 记忆 / 截图** | **磁盘**（不是图状态） |
| 3 | `load_state_bytes()` —— 把**模拟器**摆到正确帧 | **模拟器** |
| 4 | `state = EpisodeRunState.model_validate(dump)` | **产出图的输入** |
| 5 | 帧账回载（两张表） | 运行期旁路账 |
| 6 | 写 `CHECKPOINT_RESTORE` | 接缝账 |
| 7 | `graph.invoke(state)` | 图 |

三条理由，一条比一条硬：

1. **图的入口状态必须是完整的。** 它带着不变式 `observation.step == step`。如果 `resume`
   变成图的一个节点，那"进图的初始状态"是什么——一个半初始化的 state？那么图的第一个节点
   就要能处理"我是恢复来的还是新开的"，**图会有两个入口语义**，而且每个下游节点都得能接受
   两种初始状态。这是把"装配"塞进了"运行"里。
2. **`void_after` 是磁盘操作，它的作用前提是"图还没开始跑"。** 它要删掉"`cursor` 之后"的东西
   ——而图一旦跑起来，那些东西就正是图正在产生的。`run_harness.py` 里那段注释记着一条实测
   踩出来的坑：`resume_run` 必须在 `graph.invoke()` **之后**才写盘，否则本局的 `void_after`
   会把它刚写的事件吃掉。**这条坑就是"图外"这个边界的实证。**
3. **`load_state_bytes` 是世界层动作。** 做成节点就等于承认"图的一个节点可以基于磁盘/模拟器
   任意改世界"——那 **replay 的可重放性就断了**（replay 靠"同 state + 同输入 → 同输出"）。

**所以 `resume` 与 `_begin` 是同一族的"图入口装配器"**，重构后住一起（`episode/entry.py`）：

```python
def run_new(runtime, episode_id, task, stack, run_state) -> Outcome:   # 新跑
    """写 EPISODE_START → _begin（世界起点存档 + 开局视觉感知）→ invoke → 取 outcome"""

def run_resume(runtime, episode_id, task, stack, step, run_state) -> Outcome:
    """七步准备（load → void_after → load_state_bytes → 重建 state → 帧账回载 → RESTORE）→ invoke"""
```

**不对称但要紧的一点**：`_begin`（推世界 + 调模型）留**图外**，`close_episode`（只算账）进**图内**。
理由是现行的"`act` 是唯一推世界的节点"这条约束比对称性重要。

#### (c)`resume` 今天的两条路径（v7 新增——因为"它到底在做什么"原先没有一处讲全）

它是**两个入口接力**，不是一个函数：

| | `RunHarness.resume_run(run_id, episode_id, step)`（run 侧，**图外**） | `EpisodeHarness.resume(episode_id, task, stack, step, run_state)`（episode 侧，**图外**） |
|---|---|---|
| 1 | `assert` 注入了 checkpoint | `checkpoint.load()`——签名与成对校验在 tool 内 |
| 2 | `load(run_id, episode_id, step)` 取**锚点**：就是那一步的存档 | `void_after(cursor=checkpoint.last_event_id)` 归档截断"该步之后"的时间线 |
| 3 | **`RunState.model_validate(anchor.run_state_dump)`** ← run 级状态**只能从存档拿**（§4.0(a3) C 组） | **`load_state_bytes()`** ← 唯一**不可从事件重建**的东西（模拟器字节） |
| 4 | `data_center.rebuild(read_disk_events(), state.goals)` 重建交互层 | `set_task()` ← `check_restore.py` 跑出来的真故障修复；**`world_reset_done = True`**（§5.2-8） |
| 5 | 塞 `ResumeEpisode(episode_id, step)` 进 state | `EpisodeRunState.model_validate(checkpoint.state_dump)` + assert |
| 6 | `graph.invoke(state)` ← **`START` 条件边直接跳 `dispatch`**（跳过 `begin` 与 `plan`） | 帧账回载（两张表） |
| 7 | invoke **之后**才写 `CHECKPOINT_RESTORE`（顺序是契约，见下） | 写 `CHECKPOINT_RESTORE`（episode 侧） |
| 8 | `_close()` → `RUN_END` | `_invoke(state)` 进图（`save_checkpoint` 幂等重写本号存档 → `record_observation`） |

**接力那一下在 `dispatch`**：run 图从 `START` 直接进 `dispatch`（条件边看
`state.resume_episode is not None`），`dispatch` 走 resume 分支 → 调上表右列七步 →
清空 `resume_episode` 后继续 `reflect`。所以 **`begin` 与 `plan` 在 resume 时都不跑**——
前者只是校验；后者的 LLM 规划结果**早已在存档的 `outcomes`/`goals` 里**，重问一遍只会
多花一次调用、且可能与存档里的栈不一致。

**三条"为什么"，都不是随手写的**：

1. **世界快照必须回载**：它是唯一**不可从事件重建**的东西（记忆落盘、trace 落盘、
   state 从存档反序列化，只有模拟器字节不在事件流里）。
2. **记忆不用重建**：各 store 在构造时就已从磁盘读回，所以 `resume()` 只重建 state 与帧账。
3. **两条 `CHECKPOINT_RESTORE` 的时机不同，且 run 侧那条是硬约束**：episode 侧那条在
   **进图之前**写；run 侧那条**必须等 `graph.invoke()` 跑完**——否则本局的 `void_after`
   会把它当场归档（`run_harness.py` 里记着 0909 实测那条坑：标记事件 id 恰好在游标 +1）。

**一条隐含约束（重构时要保住）**：resume 只能恢复到"**下一局**"——`dispatch` 断言
`resume_episode.episode_id == f"{run_id}-ep{len(outcomes) + 1}"`。也就是说存档那一刻
`outcomes` 有 n 条，就只能恢复到第 n+1 局，**不能跳回中间某一局**。这不是缺陷（run 语义
本来就是线性推进），但**别在重构时把它误当成"随便挑一局的恢复"**。

**重构后（D1 内置子图）这套时序一个字不改**，只是换住处：左列 → `run/entry.py` 的
`resume_run()`；右列 → `episode/entry.py` 的 `run_resume()`；`resume_episode` 的消费点仍是
`dispatch`；`run_state` 透传从方法参数变成 `deps.run_state_snapshot`（写入点搬 `dispatch`，
D11-(3)）；第 5 步的 `model_validate(state_dump)` 变成直接读 `checkpoint.episode_state`
（D9-v6 的类型内嵌）。

### D1 —— 拼接方式：episode 图挂在 run 图里，还是留显式调用？

> **已拍板：① 纯内置**（2026-09-12）。下表保留，作为"为什么是它"的记录，不再是选择题。

**现状**：`dispatch` 调用 `episode.run(req)`；`run()` 里做三件图外的事（写 `EPISODE_START`、
`_begin` 建初始 state、`_close` 组结算写 `EPISODE_END`），异常时还要补 `EPISODE_ERROR` 再抛。

| | ① 纯内置（推荐） | ② 薄壳桥接（= 现状换个名字） | ③ 混合 |
|---|---|---|---|
| run 图怎么写 | `add_node("episode", ep_graph, error_handler=…)` | `add_node("dispatch", bridge)`，bridge 里 `episode.run(req)` | 循环体直挂，上下水在桥接节点里 |
| episode 图边界 | `[20 节点] → close_episode → END`，`_begin` 在 `entry.py` | 无独立边界（就是那 20 个节点） | 无独立边界 |
| 是不是"内置父子图" | **是** | **不是**（只是两张图各自 invoke） | 一半 |
| 异常兜底 | F4 的 `error_handler`，写在**父图一侧** | 现状的 try/except，原样 | 同 ② |
| `recursion_limit` | **必须重标定**（F5：子图步数计入父图） | 不变（两层各算各的） | 必须重标定 |
| 观测台 | 零影响（F9） | 零影响 | 零影响 |
| 改动面 | 大 | 小 | 中 |

**推荐 ①**，理由不是"更符合你原话"（虽然确实更符合），而是三条实测把它从"理想"变成了"可行"：

- F4 证明异常兜底有官方落点，而且 handler 拿到的是**父 state**——"包装成失败结算交给
  `reflect`"这段逻辑可以**一字不改地**搬进 `episode_error_handler`，`Command(goto="reflect")`
  正好是现在 `dispatch` 返回状态增量的等价物；
- F7 证明父子交界能写成**两个显式模型**，这正好接上项目"契约先行"那条；
- F8 证明"子图每次重建 state"是确定的语义，不是巧合。

**① 的两个真实代价（明账，不藏）**：

1. **`resume()` 进不了图**（§4.0(b) 三条理由）。所以 episode 侧保留 `entry.py` 的两个入口函数；
   run 侧对称地保留 `resume_run()`（它同样有 `DataCenter.rebuild` 与 `void_after` 的时序契约）。
2. **`recursion_limit` 从"两层各自精确"退化成"一个总上限"**。对策见 D6。

**落地形态（v2 补充）**——改完之后"类"还剩多少：

| 现在的类 | 改完 |
|---|---|
| `EpisodeHarness`（1749 行） | **消失**。它没有外部调用面（只被 `RunHarness` 用），五个依赖进 `HarnessDeps`、节点进文件、`run()`/`resume()` 变 `entry.py` 的两个函数 |
| `RunHarness`（677 行） | **留一个 ~100 行的薄类**（`run/harness.py`）。理由是**它有外部调用面**：`api.py` 持有 `handle.harness` 并调 `submit_edit()`/`review()`/`run()`，这些是"长命对象 + 前后端交互"的职责，不是图节点的职责。它内部只剩"装 runtime + 四个委托" |

### D2 —— 父子交界：一张必须存在的键表

F1 说"传递模型是键名交集"，F2 说"同名不同型当场炸"。所以**交界必须显式列出来**，
不能靠"碰巧同名"。

**必须解决的四件事**：

| # | 键 | 父 `RunState` | 子 `EpisodeRunState` | 处置 |
|---|---|---|---|---|
| ① | `goals` | `list[TaskForBrain]` | `list[GoalForBrain]` | **子侧改名 `episode_goals`**（推荐）：父侧的 `goals` 是"目标栈"这个领域概念（全仓一提 `goals` 都指它，`api.py`/`run_harness.py` 共 20 处）；子侧那份是**投影**出来给大脑看的视图。改子侧只动 3 处（`episode_harness.py:750/791/1134`），改父侧要动 20 处 |
| ② | `episode_id` | `str \| None` | `str` | 同名同型（`None` 只在 run 未派发时出现）→ **直接传**，子图入口 assert 非空 |
| ③ | 任务 | `last_task: TaskForBrain \| None` | `task: TaskForBrain` | 对齐：父侧 **`last_task` → `task`**（"刚派发的那一层目标"就是它，名字更短且与子侧一致）。父侧那 20 处 `goals` 引用不受影响 |
| ④ | 结算（**v2 新增，v1 漏了**） | `outcome: …RunResp \| None`（已有） | 无 | **子侧新增 `outcome` 字段 + 新增 `close_episode` 节点写它**。注意 F1 的反作用：**子图不输出的键，父侧保持旧值**——如果子图不写 `outcome`，`reflect` 会读到**上一次派发的陈旧结算**（而且不报错）。所以这一条不是"锦上添花"，是**防静默错误的必需项** |

**交界契约的形式**（F7）：episode 图 `compile(input_schema=EpisodeInput, output_schema=EpisodeOutput)`，
两个模型放 `episode/graph.py`（**产出地归档**）。好处是"run 给 episode 什么、episode 还 run 什么"
从散在代码里的约定变成两个**读得出来的模型**。

#### D2 补注（v4）——**"改名"只是必要条件，还需要一个"投影写入者"**

v2/v3 只说了"子侧改名 `episode_goals`"，漏掉了下一问：**改完名，那个键的值谁来写？**

F1/F8 说清楚子图初值的来路：**父 state 的同名键**。所以 `EpisodeInput` 声明的**每一个**键，
父 `RunState` 里都必须**有同名键**——否则子图拿默认值（= 静默不传）。逐条核：

| `EpisodeInput` 的键 | 父 `RunState` 里谁提供 | 怎么提供 |
|---|---|---|
| `episode_id` | 已有 | `dispatch` 生成 |
| `task` | 父侧 `last_task` **改名**（D2-③） | `dispatch` 写 |
| `episode_goals: list[GoalForBrain]` | **父侧新增这个键**（`goals` 保留不动） | **`dispatch` 做投影写入**：把目标栈 `goals: list[TaskForBrain]` 映射成 `list[GoalForBrain]` 写进这个**新键** |
| `outcome` | 已有（子图**输出**合并回来） | `close_episode`（第 21 个节点） |
| （run 级状态） | **不进交界** | 走 `deps.run_state_snapshot`（D11-(3)） |

**为什么是"新增键"而不是"改父侧的 `goals` 名"**：父侧的 `goals` 是"目标栈"这个领域概念
（全仓 20 处引用），改它等于改一处领域术语；而 `episode_goals` 是**同一次派发算出来的投影视图**
——两者是**不同的东西**，本来就该是两个键。`dispatch` 做投影这一笔，现在就发生在
`run_harness.py:472`（`top` 与 `state.goals` 两个参数），只是改成**写 state 而非传参**。

> **这条补注顺带解释了一件容易看漏的事**：为什么 D2-③ 必须把父侧 `last_task` 也改名成 `task`
> ——不是"为了短"，是因为**键名必须逐字对上**才能传过去。F1 的"键名交集"没有别名机制。

> **F8 的一个陷阱要顺手防住**：子图的初值来自父 state 的同名键，所以"父 state 里有一个别人
> 用不上的键"会**静默流进**子图。§5.3 的机械核对要加一条：交界模型声明的键，必须真的存在于
> 父 state（防"改了名两边都不报错、只是值不传了"）。

### D3 —— 依赖注入用 `context_schema` + `Runtime`，不用闭包

**现状**：节点是类方法，依赖从 `self._game` 等 5 个实例字段取。

| | 形态 | 评价 |
|---|---|---|
| 闭包/工厂 | `def build_act(deps): def node(state): …` | 可行，但**节点的依赖变成隐形的**（读签名看不出它要什么），且每个节点多一层缩进 |
| 偏函数 | `partial(act, deps=deps)` | 同上；且 `partial` 对象在 traceback 里名字很难看 |
| **`context_schema` + `Runtime`（推荐）** | `def act(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:` | **F6 实测**：官方通道、父 context 自动穿透子图、签名自述依赖、节点是真纯函数（测试里传一个假 `Runtime` 即可） |

**推荐第三种**。它顺带解决一个现在的隐性问题：`EpisodeHarness` 的 5 个构造函数参数
（game/memory/brain_tool/trace/checkpoint）就是"这一层需要什么"的清单，但它藏在 `__init__` 里；
写进 `HarnessDeps` 之后，**"episode 图依赖四根 Port + 一条 checkpoint 根路径"变成一行可读的声明**
（D9-v6 之后 `checkpoint` 这根 Port 消掉了）。

**代价**：每个节点函数多一个参数；`build.py` 要多做一步"把 Port 装进 deps"
（装配点本来就在干这个，不算新增负担）。

#### D3 修订（v4 定"只能有一个 context"，v5 又撤了它的分组）——**context_schema 只能有一个，所以不能"两侧各一个 runtime"**

v1–v3 一直写的是"`RunRuntime` + `EpisodeRuntime` 两个对象"。**F10 实测把这条路堵死了**：

```python
# 实测（F10）：父 RunDeps + 子 StateGraph(..., context_schema=EpDeps)
父图节点: type=RunDeps  value=RunDeps(run_id='r1', ...)
子图节点: type=RunDeps  value=RunDeps(run_id='r1', ...)      ← 声明 EpDeps，拿到 RunDeps
          子图节点读到 episode_id = '<属性不存在>'              ← 不报错，静默错
```

**子图的 `context_schema` 声明不生效**——穿过去的永远是父那个对象。所以：
要么**声明同一个类型**（诚实），要么**声明不同类型**（= 给未来的读者埋一个静默地雷）。

**落地形态（v5 定，v4 的两个分组已撤）**：**一个扁平的 `HarnessDeps`**：

```python
# harness/deps.py
@dataclass
class HarnessDeps:
    """**全图唯一的 context**（F10）。节点签名一律 `Runtime[HarnessDeps]`。

    生命周期：**一次 run 新建一份**（F11——框架不重建它，跨 run 复用会带着上次的账）。
    """

    # ---- 依赖：外面递进来的，整 run 不变 ----
    game: GameToolPort
    memory: MemoryToolPort
    brain_tool: BrainToolPort
    trace: TraceToolPort
    reviewer: HumanReviewer
    data_center: RunDataCenter | None
    checkpoint_root: Path                   # D9-v6：checkpoint 不再是一根 Port，只是一条路径

    # ---- 开关：构造时定，整 run 不变；plan 节点读它决定"模型能不能自主改栈" ----
    # （v7 补：这两个原本是 RunHarness.__init__ 的参数，原 deps 清单漏了它们）
    auto_push_goals: bool = True
    auto_decide_done: bool = True

    # ---- 记号：整 run 的 ----
    run_id: str = "local"
    world_reset_done: bool = False           # D11：世界起点存档读过了没有

    # ---- 账：键里带 episode_id，整 run 累积（没有"每局要清"的东西） ----
    frame_event_ids: dict[tuple[str, int], int] = field(default_factory=dict)
    pending_frames: dict[tuple[str, int], str] = field(default_factory=dict)
    run_state_snapshot: dict[str, Any] | None = None    # D11-(3)：dispatch 每局刷新
```

节点读 `runtime.context.trace` / `runtime.context.world_reset_done`——**只有一条路径**。

**为什么不再分组**（v4 曾分成 `RunDeps` / `EpisodeDeps`，v5 撤）：

1. **分组会造出"一个东西两个名字"**：`brain_tool` / `trace` / `data_center` 两个分组里都有，
   于是 `deps.run.trace` 与 `deps.episode.trace` **都是合法写法**，而没有任何规则说该用哪个
   （完整论证见"v4 → v5 改了什么"）。**删掉分组，这个岔路就不存在了。**
2. **分组不产生约束**：F10 说 context 的类型声明压根不被校验，同一次 invoke 也只有一个对象
   ——所以分组只是一层**看得见、管不着**的壳。
3. **分类用注释就够**：四带（依赖 / 开关 / 记号 / 账）在 dataclass 里一眼可读，**类型不重复**。

**顺手解决一个真问题**：`data_center` 在 run 与 episode 两侧是**同一个对象**（episode 只读
`human_note` 槽、run 持全槽），`brain_tool` / `trace` 两侧共用——拍平之后**一个字段就是这个对象**，
不再有"两个字段碰巧指向同一个东西"的疑云。

**`world_reset_done` 有了正确的家**：它是 run 级的长命记号，**不需要落盘**，
也不用操心"每局重建时它会不会丢"。**但"不落盘"有一个前提，v7 才查清**：`resume` 入口必须
**显式**把它置 `True`——恢复路径不经过 `_begin`，而本局跑完后下一局的 `_begin` 会读它；
少写这一处的症状是"**能恢复、能跑完本局，但下一局世界回退到 ROM 起点**"（详见 §5.2-8）。
v6 这里原写"重启后 `_begin` 再 reset 一次即可"，**只覆盖了全新 run 那条路径，是错的**。

**生命周期（F11 的代价，必须写死在 `run/harness.py`）**：`HarnessDeps` 是 `invoke(state, context=deps)`
传进去的**外部对象**，框架不重建它（F11）。所以 **一次 run 新建一个 deps**——
若跨 run 复用同一个实例，第二次 run 会带着上一次的帧账残留（`pending_frames` 里塞着已经
不存在的 episode 的 PNG）。放在 `RunHarness.run()` 的开头构造，与"这次 run 的 `run_id`"同生同死。

### D4 —— 可变账归 `HarnessDeps`，不进 state

见 §4.0(a)：**这是现状的显式化，不是新策略**。落点：**不是 `run/runtime.py` +
`episode/runtime.py` 两个对象，而是 `harness/deps.py` 里一个 `HarnessDeps`**（F10 堵死了两侧
各一个 context 的路；v5 又把 v4 的分组也撤了，见 D3 修订）。

**收益**：`HarnessDeps` 是一个**名字直说它是外部递进来的东西**的对象——现在这些字段散在
`__init__` 的六段长 docstring 里，读的人要自己拼出"哪些是纯内存态、哪些跟存档走"。

**字段清单照 §4.0(a3) 的裁决表搬**（这是 v4 与 v3 的差别：v3 只说"照那张表搬"，那张表
却把 12 个字段漏成 8 个、且没给"删了会怎样"的依据）：

| 字段 | 带 | 依据 |
|---|---|---|
| `game` / `memory` / `brain_tool` / `trace` | 依赖 | 4 根 Port（D9-v6 把 `checkpoint` 从这份清单里去掉了） |
| `checkpoint_root` | 依赖 | 一条路径、不是端口——checkpoint 已是 harness 自己的事（D9-v6） |
| `reviewer` / `data_center` | 依赖 | 两个策略对象（真人 / 自动），`None` = 没接 |
| `run_id` | run 记号 | 整 run 不变（拼截图路径、标记忆） |
| `world_reset_done` | run 记号 | **D11：从 episode 那堆字段里搬来**（"世界起点存档读过了没有"，不落盘） |
| `frame_event_ids` / `pending_frames` | 账 | 键是 `(episode_id, step)`——**整 run 累积，按局天然分居**，没有"每局要清"的东西 |
| `run_state_snapshot` | 账 | run 侧递进来的原料（搭 episode 存档的车，§4.0(a3) C 组）；`dispatch` 每局刷新 |
| 不住 deps | — | `_graph` → `*/graph.py` 模块级常量；20 个节点方法 → 21 个自由函数 `(state, runtime) -> dict` |

### D5 —— 删掉两张 Port（你已拍板；下面是现场核出来的证据）

**现场核实（两个独立证据）**：

1. **两个类都不实现它们**：`class RunHarness:`（`run_harness.py:87`）、
   `class EpisodeHarness:`（`episode_harness.py:191`）——**都没有继承任何 Protocol**。
2. **零消费者**：全仓没有一处 `import HarnessPort` 用于类型标注；`run_harness.py` 里那个
   `HarnessPort` 的 import 是**未使用的老债**（`docs/ROADMAP.md:1104` 自己记过这件事）。
   两张 Port 唯一"用户"是文档（`CLAUDE.md` / `docs/spec/*`）。

**它们是"镜子"，不是"港口"**：实现方就在隔壁文件，而"港口"的定义是"实现方在系统之外"。

**那图的自述交给谁？**——图自己，而且更强：

| Port 想说的 | 谁在说（更强） |
|---|---|
| 图有哪些节点 | `graph.py` 的 `add_node` 列表——**可执行**，且 `check_graph_phases.py` 机械核对 |
| 每个节点改哪一处 state / 写哪条账 | 那张 21 行职责表（挪进 `episode/graph.py` 的模块 docstring，**图的全貌挨着图的装配**） |
| 父子交界给什么、还什么 | `EpisodeInput` / `EpisodeOutput` 两个 Pydantic 模型（**可校验、可序列化、能进 checkpoint**） |
| 节点的输入输出形状 | `(state, runtime) -> dict` 这个**统一签名本身** |

**代价与收益**：删掉 653 行零信息量的抄本（20 个方法全是 `...`，且改图时要多维护一处抄本
——`ROADMAP` 里已经记过一次漏改：删 `summarize()` 时漏删 Protocol 声明）。
**没有任何代码需要改**，因为没人用。

### D6 —— `recursion_limit` 重标定：精确预算 → 上界 + 事后断言

**现状**（两层各算各的）：

```
episode: (task.max_steps - state.step) * (NODES_PER_DECISION + NODES_PER_PRESS) + RECURSION_MARGIN
run:     len(goals) * (MAX_GOAL_RETRIES + 1) * 4 + 60
```

F5 之后，run 图的 limit 必须**覆盖全部 episode 内部步数**：

```
run_total = run 图自身节点数（5 × 轮数，轮数由 goals/重试次数可算）
          + Σ_ep [ 每步开销 × 该局可用步数 ]      ← 这一项是新增的，量级是主导项
          + 余量
```

**保护性下降的补偿**：公式里的每一项**都是已知上界**（`max_steps`、`goals` 数、
`MAX_GOAL_RETRIES`、链长上限 `MAX_SEGMENTS × MAX_TIMES`），所以能算出真上界；
再在 `entry.py` 里加一条 assert：**实际消耗步数 ≤ 预算**——把"靠 limit 兜底"
换成"靠断言报警"。这比现在更诚实：现在撞限是**无声截断**（CHANGELOG 里那次事故），
断言至少会在开发期就地炸。

### D7 —— 术语：`chain` → `decision`（v2 新增）

**为什么"不够"——现场证据**：这一个词在本仓指了**四件事**，而且**函数名与它渲染出的文本
互相矛盾**：

| 位置 | 名字 | 说的其实是什么 |
|---|---|---|
| `StepMemory.plan_step_start` | plan | ✅ 已经对了："这一步是哪次**决策**按的" |
| `chain_key(entry)` | chain | 那次决策的步号 |
| `group_chains()` / `last_chains()` / `render_chains()` | chain | 按"那次决策"分组 / 取窗 / 渲染 |
| `JUDGE_CHAIN_HISTORY` | chain | 判定器看最近几次决策 |
| `is_chain_tail`（局部变量 ×2） | chain | 这是这次决策的最后一个键吗 |
| `trace_render.action_chain()` | chain | **另一件事**（把 `ActionFromBrain` 渲成 dict） |
| `web/src/App.tsx` 的 `CHAIN_PHASES` | chain | **又一件**（图的节点序列） |
| `render_chains()` 输出的文本 | —— | **"一次决策按的 N 个键"** ← 它已经在说"决策"了 |

三条理由：
1. **它描述的是形态，不是归属。** "链"说的是"这些键串在一起"，但真正的语义是"它们出自
   **同一次决策**"——`plan_step_start` 才是那个归属键。**判据在决策，不在连续。**
2. **同词异义已经发生**：`action_chain` / `CHAIN_PHASES` 与它无关，读者会以为有关。
3. **两套词让读者做翻译**：读 `chain_key` 的人得自己连上"这就是 `plan_step_start`"。

**推荐：统一到 `decision`**（与 `plan_step_start`、`ActionFromBrain.thought`、
以及那段渲染文本同根）：

| 现在 | 改成 |
|---|---|
| `chain_key(entry)` | `decision_key(entry)` |
| `group_chains(entries)` | `group_by_decision(entries)` |
| `last_chains(entries, n)` | `last_decisions(entries, n)` |
| `render_chains(entries, *, reason)` | `render_decisions(entries, *, reason)` |
| `JUDGE_CHAIN_HISTORY` | `JUDGE_DECISION_HISTORY` |
| `is_chain_tail` | `is_decision_tail` |
| `trace_render.action_chain(action)` | `action_presses(action)` ← 它有另一件事，要跟上面分开 |
| `StepMemory.plan_step_start` | **不动**（它本来就是对的那半） |
| `web/` 的 `CHAIN_PHASES` | **不动**（那是相位链，UI 局部命名） |

**备选两个，说明取舍**：
- **`plan`**：与 `EpisodeRunState.plan` 同根，最短。**不推荐**——run 层的 `plan` 节点是 LLM
  规划（另一件事），跨层同词会让 `plan` 指两个东西，比现在更糟。
- **`macro`**：游戏圈术语（一次输入展开多键），很贴。**备选**——读代码的人不一定是玩家；
  且 `macro_key` 这种名字在 Python 里也怪。

**`decision` 的判据**：改完之后每处读出来都是中文原话——"这一步是哪次**决策**按的" /
"最近 2 次**决策**" / "这是这次**决策**的最后一个键"。**读起来即语义，不需要翻译。**

> **顺带发现（单独定，因为它有调用方）**：`last_chains()` 现在返回 `list[StepMemory]`
> （平铺的**键**），**不是"几条链"**——名字和返回形状不符。两个选法：
> ① 改名 `last_decision_entries()`（保持返回平铺，改动最小）；② 改成返回
> `list[list[StepMemory]]`（`judge` 的取窗要跟着改）。**推荐 ①**，本 PLAN 只记这一笔。

### D8 —— 散件解散（v2 新增）

**你说"utils 全部并入图中"，我核完发现要分三种情况**——因为它们的性质不一样：

| 情况 | 文件 | 性质 | 处置 |
|---|---|---|---|
| ① **一根依赖的重试循环** | `brain_utils` / `game_utils` / `run_plan_utils` | 每个文件服务**一个**节点（`think_action` / `perceive_after_action` / `plan`） | **直接并入那个节点文件**（映射表见 §3.5） |
| ② **杂物袋** | `episode_utils` / `run_utils` / `memory_query_utils` | 每个文件里装着**2–3 个互不相关的节点**的小函数（名字 `episode_utils` 就没说清是谁的 util） | **解散**，函数各归各自的节点（这不是搬家，是把一个错放的抽屉拆掉） |
| ③ **真共用件** | `trace_write` | `append_model_calls` 有 **4 个宿主**（`think_action` / `perceive_after_action` / `_perceive` / `run.plan`），跨两张图 | **定案乙：下沉 tool 层**（形态见 §4.8.1） |

**情况 ③ 为什么不能跟着走**：它是 §`PLAN_graph_readability` §3.7.4 那条规则的另一半——
"**账写在它的宿主里**"（换掉了"谁的循环谁记账"）。如果把它复制进 4 个文件，
那就回到了"谁的循环谁记账"，而那条规则**就是因为崩溃窗口被否决的**（重试期间崩了 → 账没写）。

**已拍板：乙（下沉 tool 层）**（2026-09-12）。理由不只是"让 harness 变干净"：**它的本质是
"账 → 事件"的翻译**（`ModelCallLog` 拼成 `FromHarnessToTraceToolAppendReq` 逐条 append），
而**同一个族**的活（`_tag_attempt`、事件渲染）今天已经在 tool 层——`tools/trace_render.py`。
按"schema 按产出地归类"的同一精神，"把账翻译成事件"的能力属于 trace tool。
（另两个选项：甲=留在 harness 并写明"唯一例外"；丙=每个宿主自带一份，**已否决**——违反
§3.7.4 的"账写在宿主里"，回到崩溃窗口。）

#### 4.8.1 落地形态：`append_model_calls` 放哪、以及"为啥 trace 有好几个文件"

你在拍板时问的第二问（"为啥 trace 有两种文件"）要按**"这些文件各自回答什么问题"**来分，
不能按"都叫 trace"来分。今天碰 trace 的其实是 **6 个文件、3 层**：

| 文件 | 回答的问题 | 变更触发条件 |
|---|---|---|
| `trace/interface/domain/trace_kind.py` | **有哪几种账** | 加一种事件 |
| `trace/datastore/trace_event.py` | **落盘的一条事件长什么样** | 改存储格式（`schema_version`） |
| `trace/store.py`（`LocalTrace`） | **事件怎么落到磁盘**（一条一 json + 截图副本 + 原子写 + 游标） | 改磁盘布局 |
| `tools/trace_tool.py`（108 行） | **哪一种账由哪个函数渲染**（`_RENDERERS` 分派表） | 加/删一种 kind |
| `tools/trace_render.py`（790 行） | **每一种账的 payload 长什么样**（30 个纯函数） | **改前端契约**（字段名是跨模块契约） |
| `harness/trace_write.py`（58 行） | ——（它不是领域件，是一个**调用点的样板**） | 记账点增减 |

**你看到的"两种文件"就是 tool 层那两：分派器 vs 翻译表。** 分开不是历史包袱，两条理由都在现场：

1. **量级**：790 行纯函数 + 108 行的类，合并就是 900 行，破"一个模块 300 行"的红线；
2. **变更触发条件不同**：`trace_render.py` 动一次就是**跨模块契约变更**（观测台按字段名渲染，
   改字段必须同步前端），`trace_tool.py` 动一次只是"多一种 kind"。合在一个文件会让
   "我这次改的是不是契约"变模糊——而这件事恰恰是本仓吃过亏的地方。

**但 v3 收拢一次**：`trace_write.py` 下沉之后，tools 里会有**三个** trace 相关文件
（`trace_tool.py` / `trace_render.py` / 新的 `model_calls.py`），与"一个 tool 一个文件"的
视觉格局不符 → **收进一个包**（与 `harness/episode/` 同款手法）：

```
tools/trace/
├── __init__.py        TraceTool（端口实现 + `_RENDERERS` 分派表）
├── render.py          ← trace_render.py 改名搬入（30 个纯函数）
└── model_calls.py     ← harness/trace_write.py 搬入：append_model_calls + ModelCallLog
```

**`append_model_calls` 进端口，不做自由函数。** 即 `TraceToolPort` 新增一个方法：

```python
def append_model_calls(self, *, episode_id: str, step: int, source: Source, log: ModelCallLog) -> None: ...
```

理由是你上一轮定下的那条：**"harness 依赖 toolport，tool 只需要实现 port"**。若让 harness
直接 `from pokemon_agent.tools.trace.model_calls import append_model_calls`，harness 就多了一条
"认识具体模块"的 import——而它今天只认 `tools.interface`（这正是上次 `tools/interface/` 拆分的
成果，不该在这里还回去）。

**代价**：端口多一个方法；签名里出现 `ModelCallLog`（`providers.ModelCall` 本来就已经在
`FromHarnessToTraceToolAppendReq` 里，不算新增依赖）。**备选**：保持自由函数、让 harness
import 那个模块——可行，但破你自己定的那条边界，所以列为次选。

### D9 —— checkpoint 不单独存在：它是 harness 自己的持久化形态（v3 新增，**v6 重写落点**）

**先核你的判断。** §3.4 已经用过一次判据"港口 = 实现方在系统之外"，但对 checkpoint 更锋利的问法是：

> **这个模块的"形状"由谁决定？**

| 模块 | 形状由谁决定 | **换掉 harness 的 state 模型，它要不要改** |
|---|---|---|
| `GameTool` | **模拟器**（PyBoy 的 API 与存档字节） | 不用 |
| `MemoryTool` | **记忆领域**（step / object / knowledge 三种检索单元） | 不用 |
| `TraceTool` | **事件流领域 + 前端契约**（30 种 payload 字段名） | 不用 |
| **`CheckpointTool`** | **harness 自己的 state**（`_meta()` 的 8 个键里 6 个是 harness 的东西） | **要改**（加帧账那次就是实例：harness 加一张表 → checkpoint 必须跟着加一个键） |

**方向盘在 harness 手里、模块在 tool 层 = 错放的抽屉。** 你的判断站得住。另有两条旁证：
① **唯一消费者是 harness**（`save_checkpoint` 节点 + 两个 `resume`；`tools/` 内部一个用的人都没有）；
② **它从来没有 mock 实现**——"不做 checkpoint"是靠 `None` 表达，不是靠另一个实现，
**这正好说明它从没被当作"可替换的外部能力"**。

#### 为什么 v3 的落点（`harness/checkpoint/` 包）又被推翻

你的原话是"**不该单独存在，应该和 harness 严格绑定**"。v3 那版已经把它搬进 harness 了，
但**仍然给它一个自己的包、一套自己的出口**（`save` / `load` / `void_archives`）——
换汤不换药：它还是一个**可以单独被谈论的模块**。

> **v6 改成：它根本不是一个模块。** 它拆成**一个模型 + 两个本来就在的时刻**。

| 现在的 264 行 | v6 去哪 | 形态 |
|---|---|---|
| **格式**（json 的键、目录布局、原子写、配对与签名校验） | **`episode/state.py` 的 `EpisodeCheckpoint` 模型** | 字段直接内嵌 `EpisodeRunState`（**不是 dump**）；自带 `write()` / `read()` 两个方法 |
| **写** | **`episode/open/save_checkpoint.py`**（本来就有的那个节点） | 节点里三行：建模型 → `write(root, bytes)` |
| **读** | **`episode/entry.py` 的 `run_resume()`**、**`run/entry.py` 的 `resume_run()`** | `EpisodeCheckpoint.read(...)` |
| **废弃 ①：trace 打标** | **`TraceToolPort.void_after(cursor)`**（新端口方法） | 谁的盘谁自己截 |
| **废弃 ②：memory 归档** | 调用点从 tool 内部挪到 `entry.py`（能力早已在 `MemoryTool.void_memory_after`） | 换调用者 |
| **废弃 ③：存档目录归档** | **`entry.py` 里约 8 行**（`shutil.move` 进 `voided-<ts>/`） | 编排属于恢复管线，不属于"存储" |

```python
# episode/state.py —— 与 EpisodeRunState 同住一个文件，这就是「严格绑定」
class EpisodeCheckpoint(BaseModel):
    """本局第 step 步开局的完整快照：磁盘上就是这一份 json（+ 同名 .state）。

    写者：open/save_checkpoint.py（图边界节点，每圈一份）
    读者：entry.py 的 run_resume()；run/entry.py 的 resume_run()（只取 run 级那份）
    """
    run_id: str
    episode_id: str
    step: int
    episode_state: EpisodeRunState            # ← 严绑：直接是本图的状态模型，不再 dump/validate 往返
    run_state_dump: dict[str, Any]            # ← run 借道（D11-(3)）。episode 是子图，不反向 import run
    last_event_id: int
    frame_event_ids: dict[int, int]
    pending_frames: dict[int, str]
    saved_at: str
    emulator_state: bytes = Field(exclude=True)   # 世界快照 → 落同名 .state 兄弟文件，不进 json
```

**删掉的东西（一张清单）**：

- `tools/checkpoint_tool.py`（264 行）；
- `CheckpointToolPort`（`ports.py:130–170`，41 行）；
- 5 个信封 schema（`FromHarnessToCheckpointTool{SaveReq, LoadReq, LoadResp, VoidReq, VoidResp}`
  ——**它们是 harness 发给自己的一封信**）；
- `tools/__init__.py` 懒加载表里的一项、`tools/interface/__init__.py` 的一项导出；
- `build.py` 的 `CheckpointTool(...)` → 改成往 `HarnessDeps` 里塞一条 `checkpoint_root: Path`。

**顺带修掉两处**：

1. **越层**：`void_after()` 今天**直接 glob `trace_data/<run>/events/*.json`、原地改写 `valid=false`**
   （`checkpoint_tool.py:137–156`）——它是 `trace/store.py` 那条边界宣言（"写者只有 harness 走端口、
   读者是 api"）之外的**第三个读者**，还是按文件路径读的。修法：`TraceToolPort.void_after(cursor)`
   返回"哪些局被废弃"，编排留在 `entry.py`。
2. **一个没人接的回执**：`resume()` 里那句 `void_after(...)` **没有接返回值**
   （`episode_harness.py:417`）——5 个信封里的 `VoidResp` 是纯装饰，删掉正好。

**代价（明账，两条）**：

- **json 里 `state_dump` 这个键改名 `episode_state`**（字段类型从 dict 变成模型）。
  **目录与文件名布局一字不变**，但**旧存档不再可读**——不写迁移代码，`checkpoints/` 下的
  都是可再生的核对产物。`experiment/real_check/check_checkpoint.py` 认的是 `run_state_dump`
  这个键（名字没变），它只需订正 docstring 里那句 `CheckpointTool.load()`。
- **磁盘布局知识从"一个 store 模块"挪进了 `episode/state.py` 的模型方法**。
  为什么仍然这么放：因为你要的是"**不单独存在**"——给它一个 `store.py` 就是**又造一个模块**；
  而"格式"的性质本来就是**数据自身的形状**，`state.py` 正是放这个的地方。两个方法一共约 15 行
  （`json.dumps` + tmp + `os.replace`；`model_validate_json` + 配对校验）。

**顺带一提**：`_frame_ledger()`（摊平本局帧账）**唯一的调用者就是 `save_checkpoint`**，
所以它跟着写者走、进 `open/save_checkpoint.py`；`_frame_b64()` 服务的是 store 步，另归。

> **备选（不推荐）**：保持 tool 层不动，只把那五个 schema 就地标注为"harness 内部件"。
> 那正是这次要推翻的东西。

### D10 —— 域① `boundary/` 改名（v3 新增）

那两个节点是 `save_checkpoint` + `record_observation`，图上它们是**一条决策的开场两格**：
**存上一环的成果**（世界快照 + 两层 state + 游标 + 帧账）、**记这一环的输入**（`OBSERVE`）。

`boundary` 说的是**位置**（"接缝"），不说是**干什么**——与其它六个域（都是动作/角色：
闸口、检索、决策、按键、落库、收尾）不同轴，所以读起来别扭。试试替换法：
"我在改 `retrieve/` 的一个节点" ↔ "我在改 `boundary/` 的一个节点"，后者听完不知道在说哪一段。

| 候选 | 读出来 | 评价 |
|---|---|---|
| **`open/`（推荐）** | "这次决策**开场**的两格" | 与六域同为段落名；`open` / `close` 是英语里最不需要翻译的一对 |
| `head/` | "**链首**两格" | 位置语言，与 `press/`（链内一圈）成"首 vs 内"对照；**备选** |
| `seal/` | "把上一环**封存**" | 只盖一半（`record_observation` 不是封存） |
| `entry/` | —— | **不可用**：同层已有 `episode/entry.py`（图外入口），同词会误读 |

**一处要同时说清的**：`close/` 是**整局收尾**，而 `open/` 是**一条决策的开场**，两者不同层级。
为避免误读，`episode/open/__init__.py` 的模块 docstring 第一句要写：
"本域是**每条决策**的开场，与 `close/`（整局收尾）不同层级。"

> **另一个更彻底的改法（备选）**：让"接缝域"这个概念**消失**——`record_observation.py` 并进 `gate/`
> （那一域成为"决策前置三格：记输入 → 判停 → 算空间"），`save_checkpoint.py` 归 `press/`
> （它和 `close_step` 一样是"一圈的收口"）。域数 7 → 6，`boundary` 这个名字连带不存在。
> **不推荐为默认**：它会把"每决策一次的三格"与"两个闸口"混在一个域里，域内聚性反而下降。
> （**v6 注**：这段原文写的是"`save_checkpoint.py` 跟着 D9 的 checkpoint 包走"——**那个包在 v6 已不存在**。）

### D11 —— context 全图唯一 + `world_reset_done` 归位（v4 新增；v5 定为**单层 deps**）

**起因**：你问"12 个字段里我只理解那两个，别的都不知道，要不删了"。核完的账是
**只能真搬 2 个**（§4.0(a3)：`_graph` 与 `_world_reset_done`），但核的过程把 v3 的两处设想顶翻了，
所以这一条不是"再搬一个字段"，而是**把 deps 的形状定死**。

#### (1) 必须补的技术约束：`context_schema` 全图只能有一个类型

v3 写的是"`RunRuntime` + `EpisodeRuntime`"。**F10 实测证明这条路走不通**：子图自己的
`context_schema` 声明**不被校验**，穿过去的永远是父那个对象 → 子图节点声明 `EpisodeDeps`
却拿到 `RunDeps`，读 `episode_id` **静默得到"属性不存在"**（不报错！）。

**处置**：`harness/deps.py` 里一个 `HarnessDeps`（**v5：单层不分组**，形态见 D3 修订）。
**节点签名一律 `Runtime[HarnessDeps]`**，读 `runtime.context.xxx`——**只有一条路径**。

**顺带的好处**：`brain_tool` / `trace` / `data_center` 两侧共用——拍平之后它们**就是同一个字段**，
不再有"两个字段碰巧指向同一个对象"的疑云。

#### (2) `world_reset_done` 归位：deps 里从此**没有一样"每局的"东西**

你问"这个字段是干什么的"这件事**本身就是判据**：它是"**这个 run 的世界起点存档读过了没有**"
——`reset()` 只在 run 的第一个 episode 跑，之后每局接着上一局的世界继续
（本局起点 = 上一局终点，`episode_harness.py:581-587` 记着这个取舍）。它跟"哪一局"无关。

**搬法**：`HarnessDeps.world_reset_done`（它那一带里唯一**会被写**的记号）。
读它的是 `_begin`（图外，`episode/entry.py`），而 entry 的签名本来就收 `deps`，**不用多传参数**。

**不落盘**（与 `run_id` 一致）——但**"不落盘"不等于"没人写它"**（v7 订正）：
① 全新 run：第一局的 `_begin` 在 `reset()` 之后置 `True`；
② **resume：`run_resume()` 里必须显式置 `True`**。第 ② 条不是记账，是**防止后续 episode
误 `reset()`**——恢复路径不经过 `_begin`，而本局跑完后下一局的 `_begin` 会读它；若为 `False`
就会 `reset()`，把刚 `load_state_bytes` 恢复的世界**冲回 ROM 起点**（不是"重读一次"，是世界回退）。
v6 原写"重启后 `_begin` 再 reset 一次即可"只覆盖了情形 ①，**漏了 ②**（详见 §5.2-8）。

**收益比"少一个字段"大**：搬完之后，deps 里**没有一样"每局的"东西**——
F8（子图 state 每次重建）与它再无关系，episode 图真正变成"每局独立"。

#### (3) 内置子图带来的**必须补**的一笔：`run_state_dump` 的写入点要搬家

这是核这个问题时才发现的 v3 漏洞。**现状**：`EpisodeHarness.run()` / `resume()` 是**方法调用**，
run state 由 `dispatch` 当**参数**递进来（`run_harness.py:472` 的 `run_state=state.model_dump()`），
方法入口顺手 `self._run_state_dump = run_state`（`episode_harness.py:367/408`）。

**改内置子图后，这个"方法入口"不存在了**——子图被 `add_node` 挂着，父图没法"调用它并传参"。
所以：

> **`run_state_dump` 的写入点从"入口"移到 `dispatch` 节点**：`dispatch` 每局派发时把
> `state.model_dump()` 刷进 `deps.run_state_snapshot`，子图里的 `save_checkpoint` 读它写盘。

**这比现状更好**：现状在 `run()`/`resume()` 入口写**一次**，而 `dispatch` 是**每局都写**
→ 多局时每一局的存档携带的都是**那一局派发时**的 run state，不会串。

**命名建议**：顺手改成 `run_state_snapshot`——"snapshot" 比 "dump" 更直说它是"**某一刻**的快照"
（`dump` 是序列化动作的名字，不是数据本身的名字）。

> **为什么不学 `episode_goals` 那样"把它放进父子交界键表"**：那需要父 `RunState` 加一个
> **装着 `RunState` 自己 dump 的键**（自己装自己），且要重走一遍 F2 的同名不同型核查——
> 比"deps 上一个字段"更绕。三条方案的对比见 §4.0(a3)。

---

## 5. 风险与不变式

### 5.1 必须零变化的东西（验收据此）

| 项 | 为什么 | 怎么证 |
|---|---|---|
| trace 事件序列与条数 | replay / 观测台 / 成本统计的共同底座 | 离线核验脚本（现 **110 条断言**）全绿；真机六维 |
| `event_id` 单调递增、相对次序 | 同上 | `check_trace.py` |
| 步号语义（`step` = 一次小 action）与 `observation.step == step` | 记忆键 `(episode_id, step)` 靠它 | 离线核验 + 真机 |
| checkpoint **目录与文件名**布局 + `resume` 七步时序 | 恢复链路 | `check_restore.py`；**布局逐字节不变**。**一处例外（D9-v6）**：json 里 `state_dump` 键改名 `episode_state`（字段类型 dict → 模型）→ **旧存档不再可读**，不写迁移代码（`checkpoints/` 下的都是可再生的核对产物） |
| `MODEL_CALL` 三类条数（决策/感知/规划） | 成本不变量 | 离线核验 |
| 观测台 | F9：它吃 trace，不吃 graph stream | `check_graph_phases.py` + `tsc --noEmit` |

### 5.2 八个容易破的地方

1. **`goals` 改名（D2-①）只动子侧**，但**子侧的 `state.goals` 有 3 处、docstring 有 2 处**；
   **父侧还要"新增"一个 `episode_goals` 键 + `dispatch` 里的投影写入**（D2 补注）——
   漏了这一步的表现是**子图拿默认空列表、不报错**；另有一处**不在 harness 里的悬空引用**：
   `brain/interface/domain/goal_for_brain.py:15` 的 docstring 还在指向
   `interfaces/harness/episode_harness_port.py`（**这个路径今天已经不存在**）——搬完顺手订正。
2. **D7 的改名要连出口一起**：`schemas/memory/datastore/__init__.py` 与
   `schemas/memory/__init__.py` 的 `__all__` + import 各 4 处。
3. **`NODES_PER_DECISION` / `NODES_PER_PRESS` 的 docstring** 里逐字列了节点名，节点搬家之后
   立刻过期——按惯例**搬完就改**，别等。
4. **`scripts/check_graph_phases.py` 的抽取路径**写死 `episode_harness.py` 的 `_compile()`。
   节点搬进 `episode/` 之后它必须改（改成抽 `episode/graph.py` 的装配函数）。
   **顺手扩到 run 图**——现在 run 图的 5 个节点**没有任何核对**，`web/src/App.tsx` 也只画 episode 链。
5. **D9-v6 的拆除面比 v5 更大**：删 5 个信封 schema 会牵动 `schemas/harness/communication/`
   的出口（`__init__` + `__all__`），还要改 `build.py` 的两处注入、`tools/__init__.py`
   的懒加载表、`tools/interface/__init__.py` 的导出。另有三处**引用要顺手订正**：
   `experiment/real_check/check_checkpoint.py` 的 docstring（`CheckpointTool.load()`）、
   `resume()` 里那句 `void_after` 的调用形态、`trace/store.py` 的一条注释。
   **`check_imports.py` 必须复跑**。
6. **D8-③ 给 `TraceToolPort` 加方法**：这是本 PLAN 第二处动端口（第一处是 D9 的删）。
   `trace_write.py` 的 4 个调用点（`think_action` / `perceive_after_action` /
   `EpisodeHarness._perceive` / `RunHarness.plan`）一起改，**离线核验的 `MODEL_CALL` 计数
   是这一改的唯一验收**（它必须一条不差）。
7. **`HarnessDeps` 的生命周期**（v4 新增，F11 的代价）：它是 `invoke(context=…)` 的入参，
   **框架不重建它**。所以必须**一次 run 新建一个**（放在 `RunHarness.run()` 开头，与本次
   `run_id` 同生同死）。跨 run 复用同一个实例 → 第二次 run 带着上一次的帧账残留，
   而**表现是"图能跑、只是帧对不上"**——又一个不炸的错。

8. **`world_reset_done` 的两处写，性质不同**（v7 新增，订正 v6 的一处错判）：
   `_begin` 里那次是"**我刚 reset 过**"的记账；`resume()` 里那次是"**别再 reset**"的**强制令**
   ——恢复路径不经过 `_begin`，而本局跑完后**下一局**会走 `_begin`。少写这一处，症状是
   "**能恢复、能跑完本局，但下一局世界回退到 ROM 起点**"（**新进程 resume 独有**；同进程内因为
   实例复用、标志早已为 `True`，反而看不出来，所以这是个**只在真实恢复链路上才会现形**的错）。
   **判据**：`_begin` 是**唯一读点**（代码里数出来的）→ **凡是不经过 `_begin` 就进了恢复路径的
   场合，都必须自己把这个记号补上**。

### 5.3 新增四条机械保证（防它长回去）

1. **"一节点一文件"**：从 `*/graph.py` 抽 `add_node` 的名字，每个名字必须存在
   `<域>/<name>.py`（同名文件即节点）。挂在 `check_graph_phases.py` 里一并跑，
   或新开 `check_node_files.py`。
2. **"交界键表是真的"**：`EpisodeInput`/`EpisodeOutput` 声明的每个键，必须真的存在于
   `RunState`（防 F1/F8 的静默不传——D2 补注把这条从"改名"升级成"要有投影写入者"）。
3. **"散件已清零"**（v3 新增，v4/v6 各补一次例外）：`harness/` 根下只允许
   `__init__.py`、**`deps.py`**（D3 修订：全图唯一 context，不属于任何一张图）、
   两个顶层文件（`run_data_center.py` / `auto_reviewer.py`）与**两个目录**
   （`run/` `episode/`——D9-v6 之后**没有 `checkpoint/`**），此外不应再出现任何 `.py`。挂进
   `check_graph_phases.py` 一起跑——这条防的是"半年后又长出一个 `xxx_utils.py`"。
4. **"context 只有一个类型"**（v4 新增，防 F10 那个静默错）：`*.py` 里
   `Runtime[...]` 的类型参数只能是 `HarnessDeps`。在 `check_graph_phases.py` 里
   `grep` 一次即可——**这条防的是"哪天有人给子图单独声明一个 context_schema"**，
   而那不会报错，只会让子图节点静默读到不存在的属性。

**这四条是把"结构"变成可执行断言**——和 §1.1 那次"web 表与图漂移两个月没人发现"是同一个病。

---

## 6. 迁移顺序（六步，每步可独立验收、可独立停）

> 原则：**先立骨架不改行为 → 再改术语 → 再换拼接 → 再拆文件 → 最后收口**。
> 每一步结束后，**离线核验 + 三个 check 脚本必须全绿**；真机命令由你跑。

| 步 | 做什么 | 为什么排这里 | 验收 |
|---|---|---|---|
| **步 0** | 建 `run/` `episode/` 骨架 + **`harness/deps.py`**（一个 `HarnessDeps`，v5 单层）：各自 `state.py` + 两个 `graph.py`（节点**以方法引用**接进去）；解 D2 的四件事（`goals`→`episode_goals`、父侧新增该键 + `dispatch` 投影写入、`last_task`→`task`、加 `close_episode`+`outcome`）；**调用关系仍是 `episode.run(req)` 不动** | 把"最危险的改名"与"拼接方式切换"**分开做**——混在一起出问题分不清是谁的锅 | 全绿；**行为零变化**（这一步行数几乎不变） |
| **步 1** | **D7 术语改名**（`chain` → `decision`，含两个出口文件的 `__all__`）+ D8 的**情况①②**解散（并入节点前先原地改自由函数，不动文件位置） | 纯改名，不碰结构；此时散件还在原位，改了也容易复核 | 全绿 + `grep -rn "chain" pokemon_agent/` 只剩 `action_presses` 与无关项 |
| **步 2** | 换拼接：`dispatch` → `add_node("episode", ep_graph, error_handler=…)`；`_begin`/`resume` 进 `entry.py`；`close_episode` 进图；**D6 的 limit 重标定** | 这一步唯一改变的是"两张图怎么连"，节点实现一字未动——回滚成本最低 | 全绿 + 新增"两图 limit 不撞限"的离线用例；真机 |
| **步 3** | 拆 episode 的 21 个节点，**按功能域一批一批搬**（`open` → `gate` → `retrieve` → `decide` → `press` → `store` → `close`，D10 的域名从这一批起用），每搬一批跑一次核验 | 分批让"搬错了一个节点"能定位到那一批；七个域之间本来就低耦合 | 每批全绿；搬完 `episode_harness.py` 删除 |
| **步 4** | 拆 run 的 5 个节点（含 `resume_run` 进 `entry.py`、`RunHarness` 收成薄类）；**D5 删两张 Port**；`interface/` 瘦身；`check_graph_phases.py` 扩到两张图 + §5.3 三条核对；`harness/__init__.py` 懒加载表；SPEC / CHANGELOG | 收口 | 全绿；`check_graph_phases.py` 输出两行 OK（run 5 + episode 21） |
| **步 5** | **跨层件归位**（v3 新增，v6 改范围）：D9-v6 **解散** `tools/checkpoint_tool.py`（格式→`episode/state.py`、写→`open/save_checkpoint.py`、读→`entry.py`、trace 打标→`TraceToolPort.void_after`）、删端口与 5 个信封；D8-③ 把 `harness/trace_write.py` → `tools/trace/model_calls.py`、`TraceToolPort` 加 `append_model_calls`、4 个调用点改掉 | 放在最后，因为它是**唯一同时动两个层**的一步——前面都绿了再动它，出问题一眼能定位到"搬错了" | 全绿（**`MODEL_CALL` 三类条数必须一条不差**）；`check_imports.py` 复跑；跑一次 `check_restore.py`（**新存档**） |

**每步一个 commit + 一条 CHANGELOG**（四段式），与既有做法一致。

---

## 7. 待你拍板

**已拍板（2026-09-12，留档不再改）**

| # | 事项 | 定论 |
|---|---|---|
| A | **D1 拼接方式** | **① 纯内置**（依据 §2 F4/F7/F8；两个代价见 D1） |
| B | **D5 两张 `HarnessPort`** | **删**（零消费者，见 §4.5） |
| C | **D8-③ `trace_write.py`** | **乙：下沉 tool 层**（形态见下面第 3 条，仍需点头） |
| D | **D9 checkpoint 归属** | **不单独存在，解散进 harness**（v6 依你"不该单独存在、严格绑定"的原话改；判据见 D9）。~~v3 的"搬进 `harness/checkpoint/`"已被 v6 推翻~~ |

**已拍板（2026-09-12，v8——"全按你的决定来"）**

下表每一行的"定论"就是 v7 那一版"我的推荐"列的原文；依据逐条见上面的 v7→v8 段。
**本 PLAN 至此无待决项**，下一步是执行 §6 的迁移顺序。

| # | 事项 | 定论 |
|---|---|---|
| 1 | **D2-① `goals` 改名方向 + D2 补注的"投影写入者"** | **子侧**改 `episode_goals`；**父侧 `goals` 不动**，另**新增** `episode_goals` 键由 `dispatch` 投影写入（§D2 补注） |
| 2 | **D7 术语** | **`chain` → `decision`**；`action_chain` → `action_presses`（`macro`/`plan` 两个备选均不采用） |
| 3 | **D8-③ 的形态** | **进端口**：`TraceToolPort.append_model_calls`（自由函数方案不采用） |
| 4 | **D10 域① 的名字** | **`open/`** |
| 5 | **D9-v6 附带的三条** | ① 删 `CheckpointToolPort` + 5 个信封 ② `void_after` 的 trace 打标还给 trace 端口（三存储各截各的，编排在 `entry.py`）③ **json 键 `state_dump` → `episode_state`**（旧存档不可读，不写迁移） |
| 6 | **`RunHarness` 薄类** | **留**（`api.py` 的 `handle.harness` 是外部调用面）；`EpisodeHarness` **删** |
| 7 | **目录名 + deps 落点** | `run/` `episode/`（**没有 `checkpoint/`**，D9-v6）+ 七域 `open gate retrieve decide press store close`；固定名 `graph.py`/`entry.py`/`state.py`；**`deps.py` 放 `harness/` 根下** |
| 8 | **D11-(2) `world_reset_done` 上移** | **搬**到 `HarnessDeps`；**`resume` 入口要显式置 `True`**（§5.2-8） |
| 9 | **D11-(3) `run_state_dump` 的处置** | **留，改名 `run_state_snapshot` + 写入点搬到 `dispatch` 节点** |
| 10 | **节奏** | **步 0 + 步 1 做完停下**，交你复核后再进步 2 |

---

## 8. 附：探针脚本

§2 的十一条来自 9 个一次性探针（纯 langgraph，不碰 PyBoy、不碰项目代码），
覆盖：不同 schema 直挂 / 同名不同型 / 子图异常冒穿 / `error_handler` 兜底与 `goto` /
`recursion_limit` 累加 / `context_schema` 穿透 / `input_schema` 裁剪 / 环内多次调子图 / stream 可见性 /
**子图 context 声明被忽略（F10）** / **context 对象同一性（F11）**。

**已沉淀进技能** `pokemon-agent-offline-verify`（`scripts/probe_langgraph_subgraph.py`，
断言版，**29 条全绿**）：它不属仓库文件（探针是 AI 的复跑工具，不是项目产物），与那份技能里
已有的 110 条断言互补——**那 110 条管"这个仓的图长什么样"，这十一条管"langgraph 怎么解释父子图"**。
本 PLAN 只引机制结论，脚本在技能侧维护。

> **F10/F11 是 v4 现加的探针**（起因是你问"`_run_state_dump` 要不要显式"）。它们推翻了 v3
> "run 与 episode 各一个 runtime"的设想——**这正是"先跑探针再写方案"这条做法本身的收益**：
> 两条都是"不跑就一定会踩、跑了才发现"的机制。
