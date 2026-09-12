# PLAN —— 图的可读性：漂移订正、命名对齐、职责裁定（v7，2026-09-11）

> **一句话**：**图本身没坏**——节点各有单一职责、每个只改状态里的一处、全图只有两条
> 分叉边。"乱"来自图**外面**的三件事：① 文档与观测台跟代码漂移（**这是错，不是取舍**）；
> ② 两个节点的名字不指职责；③ 缺一页"节点 ↔ 职责 ↔ 字段 ↔ 事件"对照表——读图的人现在
> 只能从 20 段 docstring 里自己拼出全貌。
>
> **本 PLAN 不动图拓扑、不并行化四路检索、不合并节点**（理由见 §5）。
> 拆掉两处职责：`act` 的扶正用**并进已有节点**的方式做（节点数不变，§3.4）；
> `look_after_action` 按"感知 / 落实+留痕"**一分为二**（19 → 20，§3.6）——v1–v4 曾判它
> "拆不动"，**v5 撤回那个判断**（§3.3）。

## 版本记录

| 版本 | 内容 |
|---|---|
| v1 | 漂移订正清单、两个改名提案、19 节点逐个体检、对照表提案 |
| v2 | 补 §3.4：`act` 的扶正该不该挪走、两案 A/B |
| **v3** | **§3.4 定为 B 并已落地**（`advance_step` → `close_step`，19 节点不变）；§2.1 的改名从 `stamp_observation` 改为 **`record_observation`**，并回答"`look` 的工作还需要吗"；§4 表第 2/11/14 行同步代码 |
| **v4** | 补 §3.5：**为什么 `record_observation` 不并进 `look_after_action`**（用户第二次问起同一个直觉，说明这条得留痕）；§0/§5 各加一行 |
| **v5** | **§3.3 撤回**（"拆不动"的四条代价逐条重算，三条不成立）；新增 **§3.6：`look_after_action` 一分为二**（`perceive_after_action` + `record_action_result`，19 → 20 节点）；**帧的承载者换了**——链尾键的帧交给下一条链的 `OBSERVE`（`OBSERVE` 从此每条链都带图）；§4 对照表扩到 20 行 |
| **v6** | 两处拍板并落地：帧选 **两处都带**（用户："都保留，重复是为了语义清晰"）；第二格定名 **`record_action_result`**。§3.6 的帧一节改写为记录这个选择（含"体积不再不变"的明账）；§5 一行翻转；§6 步骤 0c 标已落地（离线核验 **56 条全绿**、`tsc --noEmit` 通过，账见 `CHANGELOG.md` 2026-09-11（18）） |
| **v7** | **§3.7 三项落地**：① 处置格 `record_action_result` → **`apply_stop`**，只在真的丢键时写 `ACTION_TRUNCATED`；② 观察账挪回产出格（`perceive_after_action` 写 `AFTER_ACTION`），字段收到 RAM 档的 `status`/`done`，`stop` 归处置账；③ **账搬回宿主**——三个 util 去掉 trace 依赖只交回材料，规则从「谁的循环谁记账」改成「账写在它的宿主里」；另加 `CHECKPOINT_SAVE`，20 格零哑格；**§3.7 与 §1/§2.2/§4/§6 的落地同日完成**（2026-09-11）：离线核验 **66 条全绿**、`scripts/check_graph_phases.py` **OK 20 节点**（有序逐条比对）、`tsc --noEmit` 通过；账见 `CHANGELOG.md` 2026-09-11（19） |

---

## 0. 结论速览

| 议题 | 裁定 | 理由 |
|---|---|---|
| 漂移订正 | **做**（web 6 处 + SPEC 两节 + ROADMAP 一条） | 描述的对象已经不存在，不是风格问题 |
| 命名对齐 | **做 1 个、待定 1 个**：`look` → `record_observation`；`enrich_observation` → **`merge_retrieval`**（**两条都已落地**） | 名不副实。`look` 改完刚好把"看"与"入账"分开 |
| 拆解节点职责 | **两处要做**：`act` 的扶正（§3.4，节点数不变）；**`look_after_action` 一分为二**（§3.6，19 → 20） | `act` 的第三处不属于它（v1 判错）；`look_after_action` 的"感知"与"落实+留痕"是两件事——v1–v4 判成"收益为负"，**v5 撤回**（§3.3） |
| 扶正（帧升格）的归属 | **走 B：并进步进节点**，`advance_step` → `close_step`，位置移到两个 store **之后**，节点数 19 不变 | 它是**步级**的事，与"弹队首交给世界"无关；落在这里原本只是因为 `look` 在链内不跑、而两个 store 之后只隔着一条条件边 |
| 职责下放（把记账并进 `look_after_action`） | **不做** | 链尾那一帧有**两个身份**，两条账各记一种；且它已是最胖节点（§3.5） |
| 帧的承载者（§3.6） | **两处都带**（v6 用户拍板）：链内键的帧归**这一键自己的观察账 `AFTER_ACTION`**（v7 改名并收窄字段）；链尾键的帧**既留在自己的 `AFTER_ACTION` 上、又给下一条链链首的 `OBSERVE`**（v7 起靠 event_id 读回，不再走 `_pending_frames` 中转） | "`OBSERVE` = 这一链的决策输入"这条承诺带上原件，链尾那格也照样看得见图。代价：链尾那一步的图落两份，约"每链多一张图" |
| 职责对照表 | **新增，已落地**（20 行表进接口模块 docstring，行序 = 执行顺序） | 这是"读图"缺的那一页，替代不了也不需要拆节点 |
| 历史快照文档 | **不动**（只加一行指引） | `CHECKPOINT_handoff_2026-09-07.md` 是 0907 的事实记录 |

---

## 1. 漂移订正（五处，全是"描述与代码不符"）

### 1.1 `web/src/App.tsx` —— 链的相位表与真图差 2 格

这是用户在看观测台时最直接感受到"乱"的地方：**链上画的格子和图上跑的节点不是一套**。

| # | 位置 | 现在写的 | 应该是 |
|---|---|---|---|
| 1 | `CHAIN_PHASES`（L34-54） | 19 条（v3 之后首位已是 `record_observation`） | 首位补 `save_checkpoint`；`verify_steps`+`summarize` **两条合一**为 `verify_and_summarize`；**v5 再补 `perceive_after_action`**（§3.6）→ 共 **20 条**，与 `_compile` 的 20 个 `add_node` **逐条对齐** |
| 2 | `MAIN_END`（L26） | `15` | `16`（补上 `save_checkpoint` 后，主循环占 index 0..15） |
| 3 | `close_step` 的 `note`（L47） | 原写 `advance_step`："纯步数自增，**无 trace 事件**" | 删掉"无事件"这句——它写 `TraceKind.STEP_ADVANCE`（`phaseKeyOf` 的 `lifecycle/step` 也映射它）。**v3 已随改名落地**：位置与 label 改为 `close_step`（index 14，仍 `< MAIN_END`） |
| 4 | `phaseKeyOf`（L78、L123-126） | `llm_outcome/audit → "verify_steps"`；`model_call/verify → "verify_steps"`、`model_call/memory → "summarize"` | 三处都改指 `verify_and_summarize`（合并调用只有一次，账也只有一笔） |
| 5 | `endSeen`（L145 类型 / L169-174 构造 / L703-710 `litOf`） | 两个布尔 `verify` / `summarize` | 合一为 `verify`（`litOf` 里删掉 `summarize` 分支） |
| 6 | 表头注释（L29-32） | "与 `episode_harness._compile` 的 19 个节点一一对应、顺序照抄" | 修完 #1（补 `save_checkpoint`）与 #4（尾链 4 条并成 3 条）之后这句话**才**成立；顺带在注释里写明"相位表由 `scripts/check_graph_phases.py` 机械核对"（见 §6）。**v3 已先把两侧的口径统一**：`add_node` 的字面顺序改成执行顺序，`close_step` 在表里与图里是同一个位置 |

> 根因：`docs/ROADMAP.md:1136` 记载"`verify_and_summarize` 取代 `verify_steps`+`summarize`"那次改动
> **只改了代码，没改前端**；而 0906 又"删掉 `summarize()` 兜底节点，收尾链只留 `verify_and_summarize` 一条路径"。
> 两次改动叠加，前端停在更早的形状上，且因为没有断言守着，没有人发现。

> **v3 进度**：#3 已随 `look`/`advance_step` 改名一起落地（`record_observation` 进首位、
> `close_step` 顶替 `advance_step` 的槽位）。**#1 #2 #4 #5 #6 当时刻意未动**——它们是"形状级"的
> 漂移，动它们要连带改 `endSeen`/`litOf` 的渲染逻辑，和当时的"职责裁定"混在一起会让 review 失焦。
>
> **v5 追加**：§3.6 又给这张表加了一条（补 `perceive_after_action`，19 → 20 条）。
> 于是 **#1 从"待做"变成"必须与 §3.6 同时做"**——否则观测台上的链会比真图少一格，
> 而这一格恰好是"感知"那一半。`MAIN_END` 的应然值也随之作废重算（#2）。
>
> **v6 进度（2026-09-11 落地）**：#1 里"补两格"这一半**已落地**（`CHAIN_PHASES` 19 → 20 条，
> `phaseKeyOf` 的 `view/after` 与 `model_call/perception` 分别改指 `record_action_result` /
> `perceive_after_action`）；#2 **已落地**（`MAIN_END` 15 → **16**，是被插入**强制**跟着改的
> ——不改就会把 `close_step` 误判成收尾链节点）。
> **未落地的还有**：#1 的另一半（补 `save_checkpoint` 那一格、尾链 `verify_steps` + `summarize`
> 合成 `verify_and_summarize`）、#4、#5。所以 #6 这句"一一对应"**仍然不成立**——现状是"条数相同、
> 顺序按图排列，但有两处节点**身份**对不上"，表头注释已按这个口径改写，并把这两处漂移写在明面上
> （**如实标注漂移 ≠ 宣布已对齐**）。
>
> **v7 进度（2026-09-11 全部落地，本节收口）**：上一条留下的三项全部做完——
> #1 的另一半（`CHAIN_PHASES` 补 `save_checkpoint` 那一格）、#4（`phaseKeyOf` 的
> `lifecycle/checkpoint_save` → `save_checkpoint`、`view/after` → `perceive_after_action`、
> `llm_outcome/audit` 与 `model_call/verify|memory` → `verify_and_summarize`、`act/truncated` →
> `apply_stop`）、#5（`endSeen` 的 `verify`/`summarize` 两布尔合一、`litOf` 删掉 `summarize`
> 分支）。**#6 那句"一一对应、顺序照抄"从此成立**，并且不再靠人守——`scripts/check_graph_phases.py`
> 抽 `add_node` 的字面量有序列表与 `CHAIN_PHASES.key` 逐条比对（不是比集合）。
> `CHAIN_PHASES.key` 也**从短别名改成节点全名**（`enrich`/`store_step`/`rv_knowledge` …），
> 让这条核对退化成一次直接的列表相等判断；代价是 `phaseKeyOf`/`endSeen`/`litOf` 要同步改。
> 另外补上 #1 里 v6 漏掉的半格：尾链那 4 条并成 3 条是**旧形状**，v7 的尾链是
> `retrieve_verify_step_memory → retrieve_verify_knowledge → verify_and_summarize`。

### 1.2 `docs/spec/harness/SPEC.md` —— 整篇描述的对象已不存在

它的开篇写着"**仅凭本文档即可复现出与源码一致的图结构**"，而它写的源文件是
`pokemon_agent/harness/harness.py`（**该文件已不存在**）、图是
`look → retrieve_memory → think → press → remember`（6 节点，`LoopState`），
现实是 `episode_harness.py` 的 **20** 节点 `EpisodeRunState`（v6 时点）。**它不是"有几处过期"，是整篇写的是另一个系统。**

**订正方式（不重写历史论证）**：

1. 顶部加一块 `> **现状（2026-09-11）**：` 指引——源文件、节点数、图拓扑、状态类各一句，
   并指向 `episode_harness_port.py` 的模块 docstring（那是现在唯一的权威图）。
2. **替换 §2（`LoopState`）与 §3（图结构）两节**为现状版：`EpisodeRunState` 字段分组表 +
   **20 节点图**（含链内小循环与两条分叉）。这两节是"结构描述"，过期了就是错的。
   **✅ v7 已落地**（2026-09-11）：头部换成"现状（2026-09-11）"块（源文件 / 图 / 状态类 /
   权威表指针 / 怎么看这篇），§2/§3 整节重写；**不再抄一份字段表**（抄本会漂移），改成指
   `episode_harness_port.py` 模块 docstring 这个唯一权威。
3. 其余章节（§1 设计哲学、§5 目标栈、§6 `run()`、§7 记账、§8 事件时间线）**保留原文**，
   但每节标题下加一行 `> 本节写于 0902 版（6 节点 / LoopState）；结论多数仍成立，
> 涉及图结构的表述以 §3 为准。` **✅ v7 已落地**（§1/§4/§5/§6/§7/§8 各加一块这样的标记）。

> 取舍：**不重写整篇**。§1、§5、§7 里有大量"为什么这样设计"的论证（如"唯一性规则"、
> "`outcome` 为什么不进 state"、"记账为什么跟着返回值走"），它们与图有 6 个还是 19 个节点无关，
> 重写等于把有价值的历史论证丢掉。**结构描述重写、设计论证保留**是这里的分界。

### 1.3 `docs/ROADMAP.md:1136`

该条末尾写"没有 step 记忆的边缘分支**仍走原 `summarize` 节点**"——这个节点已在 0906 被删，
收尾链现在只有 `verify_and_summarize` 一条路径（`retrieve_verify_step_memory` 出口直接连 `END`）。
**就地加一句订正**，不改该条其余内容（它是当时决策的记录）。

### 1.4 `docs/spec/harness/CHECKPOINT_handoff_2026-09-07.md` —— **不动**

它写"episode 级，**十七节点图**"、图里没有链内小循环，两处代码坐标也已失效。
但它文件名带日期戳，是 **0907 当天的事实快照**，改写它等于篡改历史记录。
只在顶部加一行：`> 本文档描述 0907 版；当前图见 episode_harness_port.py 模块 docstring。`

### 1.5 `docs/spec/DATAFLOW.md`

L199 那张表还写着 `view(frame)` = "每步 look 的全量观测"。在"一次链一条 OBSERVE"之后，
`frame` 是**每条链**一条（链内键的帧挂在 `LOOK_AFTER` 上）。**一行订正**。

---

## 2. 命名对齐职责

判据：**名字描述的动作，是不是这个格子真的在做的事。**

### 2.1 `look` → `record_observation`（**v3 定名，已落地**）

| | |
|---|---|
| 现名暗示 | "看一眼" |
| 实际在做 | 读 `state.observation`（上一圈 `close_step` 扶正上来的那一帧）→ 写 `OBSERVE` → 挂开局帧 → 登记 `_frame_event_ids`。**它不感知**（一帧只在 `_begin`/`look_after_action` 感知一次），也**不再扶正**（扶正已挪给 `close_step`） |
| 定名 | **`record_observation`** |
| 为什么是这个名而不是 v1 提的 `stamp_observation` | v1 给它起名 `stamp_observation` 的依据是"盖章（`model_copy` 补步号）是它唯一不可替代的动作"。**v3 把扶正挪走之后，盖章这件事就没了**——扶正列进 §3.4 的 B 之后，"补步号"发生在 `close_step`，这一格退化成"把本步的观测登记成一条 `OBSERVE`"。"入账"才是它剩下的全部工作，`record_*` 也正好与链内的 `store_*` 一族同构（一侧记键、一侧记帧） |
| 连带面 | 6 处：`_compile` 三处（`add_node`/两条 `add_edge`）、方法定义、接口声明、`web/App.tsx` 的 key |

#### 附：回答"`look` 这个点的工作还需要吗？"

**需要，而且不能删。** 理由不是"少改一处省事"，是这个格子承载的东西在别处**没有落点**：

- `OBSERVE` 事件必须是**每链一条**，不能退化成每步一条。链内键走的是 RAM-only 感知档
  （没有 `MODEL_CALL(PERCEPTION)`），它们既不产生 `facts` 也不产生 `goals`——把全量观测
  挂在它们身上，等于凭空多出 N 条视觉调用，直接破坏"感知成本不随链长增长"这条不变量。
- 但"大脑当时看到的世界"这个**结构化原件**必须有且只有一份：replay 要按它重放，
  观测台的"每条链一页帧"要按它取图。链内键只有轻量的 `LOOK_AFTER` 摘要（那一键后看到的变化），
  它替代不了"开局那一刻的完整观测"。
- 所以删掉这一格 = 把"本链开局的真值"降级成"从 N 条 `LOOK_AFTER` 摘要里拼"。
  这不是可读性问题，是**数据可溯源性**问题。

**结论**：`look` 的工作没有全部消失——它只是**不能再兼任扶正**。它保留为一个
**单一职责节点**，并因此改名：它不"看"，只记账。

### 2.2 `enrich_observation` → `merge_retrieval`（**v7 已落地**）

| | |
|---|---|
| 现名暗示 | "丰富观测"（像是在给观测补充信息） |
| 实际在做 | ① 只把 **object** 一路折进 `obs.facts`；② 把四路检索的**合并账**写成一条 `MEMORY_READ`。它是四路检索的**汇聚点**，不是"观测的加工厂" |
| 候选 | `merge_retrieval`（推荐）/ `record_retrieval` |
| 为什么推荐 | 与 `retrieve_*` 四兄弟呼应，把"这是检索子系统的汇聚"说出来；也解释了它为什么**必须**存在——`MEMORY_READ` 要等四路齐了才能记（这正是"四路检索为什么不各自记账"的答案） |
| 连带面 | 9 个文件（代码 5 + docs 3 + web 1） |

### 2.3 不改的两个（说清楚为什么）

- **`look_after_action` 保留**。它名字里的"look after action"是准的，只是不含"判 stop / 截断"
  这两件后续动作——但那是**同一件事的后半段**（§3.3 详述），补进名字只会更长。
- **`get_action_space` 保留**。它与工具层的 `GameTools.get_action_space` **撞名**（`grep` 命中的
  17 个文件里大半是工具层自己的方法），在 trace/读代码时确实会混。但改一个名字要动 17 处引用，
  而混淆只发生在"同时读 harness 和 tools 两层代码"时——**收益不抵改动面**，记为已知问题。
  真要改，正确名字是 `compute_action_space`（"算" vs 工具层的"取"）。

---

## 3. 「拆解节点职责」的裁定

> **现状指引（2026-09-11）**：本节写于 **v1**，当时的图是 **19** 个节点。此后 `look` →
> `record_observation`、`advance_step` → `close_step`（§2.1、§3.4），`look_after_action` →
> `perceive_after_action` + `record_action_result`（**v5 裁定拆，见 §3.6**）。所以本节里凡出现
> 19 / `look` / `advance_step` 的地方都是**当时的现场记录**，不是现状；**当前节点集合与顺序看 §4
> 与 `pokemon_agent/harness/interface/episode_harness_port.py` 的模块 docstring**。
> 本节里唯一的**结论性错误**是 §3.3（"拆不动"），已在原文上方标撤回。

用户的直觉是"有些格子把好几件事塞在一起"。我把 19 个节点逐个过了一遍，结论是：

真正称得上**多职责**的只有三处：`act`、`look_after_action`、`judge`。
其中 **`act` 的那一处已按 §3.4 挪走**；~~`look_after_action` 与 `judge` 拆不动~~——`judge`
那半仍成立（§3.2），`look_after_action` 那半**已被 v5 推翻**（裁定**拆**，§3.3 有撤回说明、§3.6 是方案）。
剩下的（`think_action` / `detect_stall` / `enrich_observation`）确实各改 ≥2 处，
但那是**一件事的多个面**，属于"太碎"而不是"杂"。

### 3.1 判据

拆不拆，看**拆开之后那个中间态是不是一个可用、有意义的系统状态**：

- 中间态可用 → 是两件事，**可以拆**
- 中间态无意义 / 危险（半成品比不拆更糟）→ 是**一件事的多个面**，不拆

### 3.2 逐节点裁定（只列改 ≥2 处的）

| 节点 | 改的 state 字段 | 中间态可用吗 | 裁定 |
|---|---|---|---|
| `judge` | `done`、`success` | 判了机械终止但没问模型 → **错**（最后一帧仍可能真的达成目标） | **不拆**；接口 docstring 已明说"终止判定不该有两个节点各管一部分" |
| `think_action` | `plan`、`pending_presses` | 同一决策的两个表示（原文 / 执行队列），只写一个 → 下一圈带着上一条链的残留 | **不拆** |
| `think_action`（另一层）| 内含 `human_note` 取用与留痕 | 取了 note 但决策抛异常 → note 已被 `take()` 消费，**丢了** | **不拆**（横切输入必须与消费同格） |
| `act` | ~~`observation`、`action`、`pending_presses`~~ → **`action`、`pending_presses`（v3 已为 2 处）** | 扶正了观测但没执行 → 观测前进一格而世界没动，两个 store 会拿它当 `before`，**错位** | **扶正挪走**（§3.4 走 B）：这三件事里"扶正"是步级的，"弹键交世界"是链级的，混在一格才产生上面那个危险的中间态 |
| `look_after_action` | `pending_observation`、`pending_stop`、`pending_presses` | 感知了但没判 stop/截断 → 中间态**可用**（stop 要等下一格才被消费） | **唯一还拆得动的**，但见 §3.3 |
| `detect_stall` | `stall_key`、`stall_count` | 同一件事的两个数（键 + 计数），拆开无意义 | **不拆**（一小组） |
| `enrich_observation` | `observation`（1 处）+ 1 条账 | 折了 object 但没记账 → 账晚一条写，**可用** | 看似可拆，但拆出来的纯记账节点**没有信息量**——账的内容正是四路的产物，它必须在这里；**结论：不拆，用改名解决**（§2.2） |

### 3.3 另一处拆得动的地方，以及为什么不做 —— **v5 撤回本节结论**

> **撤回声明。** 用户 2026-09-11 反问：**"拆开吧，不然和 `observation` 功能太像了。"**
> 把下面四条代价重算一遍，**只有第 ② 条成立**（且只是改一个常量），结论翻转为"**要拆**"
> （方案见 §3.6）。保留本节原文，是为了留下"当时为什么判错"的记录——错在两处：
> **① 把"拆节点"和"拆事件"当成同一件事**；**② 用"链内每键多一格"这种图跳数去论证"成本"**，
> 而本项目的成本口径是模型/视觉调用条数（§3.6 的验收不变量正是 `MODEL_CALL(PERCEPTION)`）。
>
> 另外，本节当时的"不做"与它**自己上面那张表**是矛盾的：§3.2 已经把 `look_after_action`
> 的中间态判为"**可用**"，而 §3.1 的判据说"中间态可用 → 是两件事，**可以拆**"。

（以下是 v4 的原文，结论已被 v5 撤回）

`look_after_action` 现在是 8 个动作：分档感知 → （中止时）补感知 → 判 `stop` → 盖步号 →
挂帧 → 登记 → 截断队列 → 写 `LOOK_AFTER`。若按"感知 / 判定"拆成
`perceive_result` + `settle_key`：

- **收益**：每格职责从 8 降到 4；名字能准。
- **代价**：① 链内每键的节点数从 6 涨到 7，**链越长代价越大**（而这次粒度的全部意义就是摊薄成本）；
  ② `recursion_limit` 要重算（现在 `NODES_PER_PRESS = 6`）；③ `LOOK_AFTER` 那条事件要拆成两条，
  但"这一键看到了什么"和"这一键为什么停"本来就是**同一份证据的两个字段**，拆成两条事件反而
  让 trace 变难读；④ `pending_stop` 与 `pending_presses` 之间的原子性靠"两个节点都不抛异常"维持，
  从"结构上不可能不一致"退化成"约定上不该不一致"。
- **判决**：~~**不做**~~ → **v5 撤回，改为"拆"**。这是典型的"用结构换观感"——但
  "观感"这次不是理由，**"两个格子做同一件事的两种说法"才是**（见下方对账）。

#### v5 重算：四条代价逐条对账

| §3.3 原代价 | v5 复算 | 成立吗 |
|---|---|---|
| ① 链内每键节点数 6 → 7，"链越长代价越大" | 涨的是**图跳数**，不是模型调用——LangGraph 的一跳是一次函数调用（微秒级），全链 100 键也就是 100 次；验收不变量（`MODEL_CALL(PERCEPTION)` 条数）**完全不受影响**。"成本"在这里用错了对象 | **不成立** |
| ② `recursion_limit` 要重算 | 真，但只是把 `NODES_PER_PRESS` 从 6 改成 7——常量本来就是为此存在（`episode_harness.py:144` 的 docstring 就写着"必须跟着 `_compile()` 走"），公式自动跟随 | **成立（一行）** |
| ③ `LOOK_AFTER` 要拆成两条 | 拆**节点**不等于拆**事件**：`LOOK_AFTER` 仍是一条，只是由新的第二格来写。这条把两件事混为一谈 | **不成立** |
| ④ `pending_stop` 与 `pending_presses` 的原子性从"结构上不可能不一致"退化成"约定上不该不一致" | 取决于接缝：§3.6 选的接缝把 `pending_stop` 留在第一格、`pending_presses` 给第二格，所以**遗留了一半**——记为已知取舍，不假装没有（§3.6 有缓解办法） | **部分成立** |

### 3.4 `act` 的扶正：A 还是 B —— **走 B，已落地**

**问题**：`act` 原本改三处（`observation`、`action`、`pending_presses`）。其中"扶正"
（`observation := pending_observation`）与"弹队首按键交给世界"没有语义关系，
它出现在这里**只是因为**：`look` 曾经兼任扶正，而扶正又必须在两个 store 之后才能发生，
两个 store 之后只隔着一条条件边——于是它被塞进了条件边的出口节点。

> 所以 `act` 的第三处**不是"刻意的原子性"，是宿主消失**。这是 v1 把它判成"不拆"时看漏的地方。

**约束（决定了能选哪些方案）**：扶正必须排在三个节点**之后**——
`store_step_episode_memory`、`store_object_semantic_memory`（这两个要 `before`=旧 `observation`
与 `after`=`pending_observation` 同时在手），以及链内的 `detect_stall`。
换句话说它的落点只能在"两个 store → 条件边"这一段。

| | A：新增扶正节点 | **B：并进步进节点（采纳）** |
|---|---|---|
| 做法 | 新增 `promote_observation`，排在 `store_object_semantic_memory` 之后 | 保留原有步进节点，把扶正并进去；调到两个 store 之后，改名 `advance_step` → `close_step` |
| 节点数 | 19 → **20** | 19 → **19（不变）** |
| `recursion_limit` | 每键 6 → 7，要重算 | **量级不变**，仍按 6 算 |
| 代价 | 多一格只为改一个赋值；图更碎 | `close_step` 改两处（`observation` + `step`）——但这两件事本质同级：**"这一步结束了" = 把帧扶正 + 把步号推一** |
| 结论 | 否 | **采纳（用户 2026-09-11 拍板"可以B"）** |

**落地的四处（代码细节见 CHANGELOG 2026-09-11（16））**：

1. `act` 只改两处：`action`、`pending_presses`；入口加
   `assert state.observation is not None, "act before close_step"`（读旧帧给 `ACT` 记账）。
2. 新方法 `close_step`（原地替换 `advance_step`，位置在两个 store 之后）：写 `STEP_ADVANCE`，
   返回 `{"observation": state.pending_observation, "step": state.step + 1}`。
3. 链内小循环的分叉出口**从 `act` 挪到 `close_step`**：
   `close_step ──(pending_presses 非空)──→ act`、`close_step ──(队列空)──→ save_checkpoint`。
4. 链首的 `record_observation` 改读 `state.observation` 并**返回 `{}`**（纯记账，不再扶正）；
   `_begin` 初始化改为 `observation=obs`（不再写 `pending_observation`）。

**安全性核对（为什么这次挪动不会动到别的东西）**：

- `save_checkpoint` 仍在 `close_step` **之前**执行 → 存档里的 `step` 与 `observation.step` 依然同步；
  而 `_begin` 用 `observation=obs` 初始化，`resume()` 的六步恢复逻辑**一字未改**。
- 链内没有任何节点读 `state.step`（都读 `state.observation.step`）→ 扶正位置后移不影响链内语义。
- `check_trace.py` 只断言 `event_id` 连续、不依赖节点顺序 → 不受影响。
- 收益：`act` 越过了"世界与观测不同步"的中间态——**扶正发生在世界已经动完、两个 store 都已落库之后**，
  中间态从"危险"变成"不存在"。

### 3.5 为什么 `record_observation` 不并进 `look_after_action`

用户问过两次的直觉：**记账这件事，交给每键都在跑的 `look_after_action` 不就行了？**

两种写法都不可取：

- **每键都写 `OBSERVE`** → 语义坏了。`OBSERVE` 的定义是"这一链的**决策输入**"，
  而链内键只有 RAM 档感知（`ram_only=True`，没有完整 `facts`）。写出来的是
  **半瞎的决策输入原件**——观测台与 replay 会把那份残缺观测当成大脑当时的视野。
  要让它不半瞎，就得让链内每键都上视觉档 → 直接推翻"感知成本不随链长增长"
  （那正是这次粒度设计的全部意义）。
- **只在链尾写**（`pending_presses` 为空时）→ 技术上可行，不破坏任何不变量。
  但代价三条：
  1. **相位错位**：账的内容是"**下一条链**的决策输入"，落点却在"**上一条链**的末尾
     节点"。trace 里 `OBSERVE` 会夹在上一链的 `LOOK_AFTER` 与 `STALL_CHECK` 之间，
     读起来像是"上一键的观测"；replay 按事件序列重放，"链从这里开始"这个相位也不
     再在 trace 里可见。
  2. **一帧两账**：链尾帧**同时**是"这一键的结果"（必须挂 `LOOK_AFTER`）与"下一条链
     的输入"（要挂 `OBSERVE`）。合并之后"一帧一个事件"这条现在很干净的规则就要改写——
     而 `StepMemory.before_frame`/`after_frame` 的取图正是靠 `_frame_event_ids` 的这条约定。
  3. **节点饱和**：`look_after_action` 已经是全图最胖的节点（分档感知 → 中止补感知 →
     判 `stop` → 盖步号 → 挂帧 → 登记 → 截断队列 → 写账，8 件）。§3.3 刚拒绝给它加东西；
     把 1 件事的 `record_observation` 并进 8 件事的节点，方向正相反。

**根本判据**：链尾那一帧有**两个身份**（上一键的结果 / 下一条链的输入）。
两个节点 = 两种身份各一条账；合并 = 在一个节点里用一个 `if` 表达两种身份，
读代码的人再也看不出这是两种东西。

**为什么这些身份不能靠"字段一样"省掉**：两条账携带的字段本来就不同——
`LOOK_AFTER` 只有机械事实（`scene`/`overlay`/`status`/`done`/`stop`），`OBSERVE` 带
完整 `facts` + `goals`。**恰好**链首的观测必然是完整档（它来自上一条链的链尾键 =
完整视觉档，或第 0 步 `_begin` = 完整档），所以"`OBSERVE` = 决策输入原件"这个承诺
是真的；一旦在链内键上写 `OBSERVE`，这个承诺就是假的。

> 附带收益：`record_observation` 的**位置**本身是信息——`save_checkpoint`（存）→
> `record_observation`（记）→ `judge`（判）构成"链首三连"，"一条链从这里开始"是图上
> 可见的相位。合并之后 `judge` 变成链首第一格，链边界只剩 `save_checkpoint` 一处。

---

### 3.6 `look_after_action` 一分为二（**v5 裁定：拆**）

用户 2026-09-11 的判据：**"拆开吧，不然和 `observation` 功能太像了。"**

这条判据成立，而且能在代码里指到具体位置：`look_after_action` 是全图**唯一从头到尾都在产出观测**
的格子（`pending_observation`），而 `record_observation` 在**登记观测**——两个名字都带
observation 的格子做的是**频率差 N:1** 的两种事（§3.5 已论证），名字却像同一件事的两种说法。

#### 接缝在哪：不是挑出来的，是被依赖逼出来的

原来的 8 个动作里，有一处把"感知"和"判读"**焊死**了：

> `中止补感知`（链中途撞墙/换图时补一次完整视觉）的触发条件就是 `stop is not None`，
> 而 `stop` 是 `compute_stop(before, action, obs)` 的输出。

所以"感知"这一半**必须先算 `stop`**——**一个纯感知节点根本不可能存在**（除非让 `compute_stop`
算两遍，见备选）。能拆的位置因此只剩一处：**"感知+判读" | "落实+留痕"**。

**A —— `perceive_after_action`（取帧并判读）**

| 步骤 | 做的事 |
|---|---|
| 1 | 分档感知：`is_chain_tail = not state.pending_presses` → `perceive_with_retry(..., ram_only=not is_chain_tail)` |
| 2 | 判读：`stop = episode_utils.compute_stop(before, action, obs, next_step=before.step+1, max_steps=…)` |
| 3 | 中止补感知：`stop is not None and not is_chain_tail` → 完整档再感知一次（它是这一圈真正的落点） |
| 4 | 盖步号：`obs = obs.model_copy(update={"step": before.step + 1})` |
| 5 | 帧进暂存表：`_pending_frames[(ep, before.step+1)] = frame_png`（**不再直接挂 `LOOK_AFTER`**） |
| **改** | `pending_observation`、`pending_stop`（**一次感知的解读，两个面**） |
| **写** | 无自己的事件；链尾键的感知账单（`MODEL_CALL(PERCEPTION)`）由 `perceive_with_retry` 写 |

**B —— `record_action_result`（落实结局并留痕）**

| 步骤 | 做的事 |
|---|---|
| 1 | 按 `state.pending_stop` 的作废范围截断队列（`BLOCKED` 丢同段剩余；`warp`/`episode_over` 整链作废） |
| 2 | 写 `LOOK_AFTER`（`scene`/`overlay`/`status`/`done`/`stop`） |
| 3 | **帧的归属分流**：链内键 → 挂在自己的 `LOOK_AFTER` 上并登记 `_frame_event_ids`；链尾键 → **不挂**，留给下一条链的链首 `OBSERVE`（见下） |
| **改** | `pending_presses` |
| **写** | `LOOK_AFTER` |

**边**：`act → perceive_after_action → record_action_result → detect_stall`
（原来是 `act → look_after_action → detect_stall`）。
**节点数** 19 → **20**；`NODES_PER_PRESS` 6 → **7**，`recursion_limit` 的公式自动跟随。

> **为什么"留存链内键的帧"这条逻辑住在 B 而不是 A**：A 只碰状态、不碰账（它的产出是
> `pending_observation`/`pending_stop`/暂存帧），B 是唯一知道"这一键该留哪条账"的格子。
> 于是"帧归谁"与"账写什么"落在同一格，读者不用跨格拼。

#### 备选接缝（更保守，但会把账和落实缝回同一格）

`A = 感知+判读+截断（三处状态全在 A）` / `B = 只挂帧 + 写 LOOK_AFTER（返回 {}）`：

- 优点：`pending_stop` 与 `pending_presses` 同格，§3.3 的"④ 原子性"连部分都不成立。
- 缺点：B 退化成"只写一条账"的格子，**结构与 `record_observation` 同形**——而用户这次的判据
  正是"不要两个格子做同一件事的两种说法"。**故不推荐。**
- **推荐案的残留取舍**：`pending_stop`（A）与 `pending_presses`（B）跨格。三点缓解：
  ① A→B 之间没有别的节点，也没有条件边；② B 唯一会失败的地方是 trace 落盘，失败即整局失败、
  状态不保留（不产生"半成品被消费"的窗口）；③ **截断规则与 `compute_stop` 一样是同一条纯判据**
  ——不存在"两处规则各算各的"。

#### 帧的承载者：链尾帧**两处都带**（v6 拍板）

用户同一句话的后半句：**"Observation 就是定调这次链开头，但我觉得记录的时候还是要带帧，
至少语义清晰。"**

现状是：**只有第 0 步那条 `OBSERVE` 带图**。之后每条链的链首 `OBSERVE` 都没有图——因为那一帧
早就挂在产出它的那次 `LOOK_AFTER` 上了，`record_observation` 里 `pop` 拿到的是 `None`。
后果是"`OBSERVE` = 这一链的决策输入"这条承诺**只兑现了一半**：要知道大脑当时看到的是什么画面，
得跳到**上一条链的最后一个格子**去取。

v5 先提了"承载者二选一"，**v6 由用户拍板走第三种：两处都带**——「都保留，重复是为了语义清晰。」

> 帧先落 `_pending_frames[(ep, step+1)]`（`_begin` 现在就是这么做的）；然后——
> **链内键**的帧由这一键的 `LOOK_AFTER` 认领（它的身份是"这一键的结果"）；
> **链尾键**的帧**两处都带**：一份留在这一键自己的 `LOOK_AFTER` 上，一份由**下一条链链首的
> `OBSERVE`** 认领（它的身份是"下一条链的决策输入"）。

- **代价（明账）**：链尾那一步的图落**两份**（逐字节相同），量级约"每链多一张图"（链越长摊得越薄）。
  换来两处自足：链尾那格的 `view(after)` 有图，下一条链的 `view(frame)` 也有图。
  v5 曾提的"只换承载者、体积不变"被否掉了——那要牺牲链尾那格的可读性。
- **收益**：`OBSERVE` 自足——replay 读到它就知道"大脑看到的画面 + 判据（`goals`）+ 完整
  `facts`"三件齐了；观测台"每条链一页"不用再翻到上一链尾取图。
- `_frame_event_ids[(ep, s)]` 的含义不变（"第 s 步的开局画面在哪个事件里"），但**登记规则明确成
  "谁先产出这一帧谁登记"**：链内键与链尾键都由那一键的 `LOOK_AFTER` 先登记，只有第 0 步那一帧
  没有前驱按键，才归 `OBSERVE`。两份内容相同、读哪份都一样，但**指向必须稳定**——不能同一时刻
  问两次答两个事件。
- **落地时踩过的一个坑（值得记）**：第一版把"链尾"判成"**截断之前**队列空"，结果撞上
  `warp` 那种"半路中止但事实上就是链尾"的键时，帧被误判成链内的、`OBSERVE` 拿不到图。
  判据必须是**截断之后**：`blocked` 只丢本段剩余（链可能接着走，这一帧就还是链内的帧），
  `warp`/`episode_over` 清空整条链时那一键就是链尾。离线核验的"每条链首的 `OBSERVE` 都带帧"
  把它抓出来了。
- **不变式核对**：`StepMemory.before_frame`/`after_frame` 按 `(ep, s)`/`(ep, s+1)` 查表，
  两个方向都查得到，**"逐键有图"这条契约不动**（RAM 档也照截图，`pyboy_world` 的
  `_ram_perceive` 同样 `frame_png=…`）。
- **恢复路径不变**：`_pending_frames` 不进 checkpoint；`resume()` 后首个链首的 `OBSERVE`
  仍然没图（与今天行为一致），`before_frame` 按 `None` 处理是既有契约。

### 3.7 三项落地（**v7**）：账的宿主、观察账的字段收敛、处置账

v6 落地后用户又提了三句，它们其实是同一件事的三个面——**"一条账该由谁写、该写什么"**：

> 「这样，lookafter 修改字段后移到 perception 节点，他只表示链内的观察，然后把 stop、截断
> process 放到 record 节点（并改名）只有真的截断了记一条截断 process trace。」
>
> 「之后没有 record 了 record 节点改名了，只负责记录截断，而且也不用记录帧了，帧是 perceive
> 的任务。Lookafter 也改名字，并且只保留 ram 读的出来的」
>
> 「要不放回节点？其他类似的也都放回节点？要不然太散了，trace 就在 harness 里记吧。」

#### 3.7.1 处置格不再兼职留痕：`record_action_result` → `apply_stop`

v6 把"落实"和"留痕"捆进同一格，事后看，**别扭的来源就是这个捆**：那一格名字里带 `record`，
于是它读起来像第二个 `record_observation`——而当初拆 `look_after_action` 的理由正是
"它和 `observation` 功能太像了"。**同一条相似性没有被拆掉，只是从"两个节点"转移到了"一个节点
in 两个角色"。**

v7 按"**观察的留痕跟着观察走、处置的留痕跟着处置走**"重新切：

| | v6 | v7 |
|---|---|---|
| 观察账 | `record_action_result` 写（`LOOK_AFTER`），每键无条件一条 | **`perceive_after_action` 写（`AFTER_ACTION`）**，每键无条件一条 |
| 处置账 | 无（截断只体现在 `LOOK_AFTER.stop` 一个字段上） | **`apply_stop` 写（`ACTION_TRUNCATED`）**，只在**真的丢了键**时一条 |
| 帧 | `record_action_result` 从暂存表认领并分流 | **`perceive_after_action` 直接挂在自己刚写的那条账上** |

节点名 `apply_stop` 与 `compute_stop`（判）、`pending_stop`（值）同词根，读起来是一条线：
**判 → 值 → 落实**。

三个账名一起定（`TraceKind` / payload `kind` 都跟着换）：

| | 旧 | 新 | type / source |
|---|---|---|---|
| 观察账 | `LOOK_AFTER`（`look_after`） | **`AFTER_ACTION`**（`after_action`） | VIEW / perception（不变） |
| 处置账 | —（无） | **`ACTION_TRUNCATED`**（`action_truncated`） | ACT / harness（与 `action_space`/`stall_check` 同族） |
| 存档账 | —（无） | **`CHECKPOINT_SAVE`**（`checkpoint_save`） | LIFECYCLE / harness（对称于 `checkpoint_restore`） |

#### 3.7.2 观察账只留 RAM 档读得出的字段

`AFTER_ACTION` 的 payload 从 `scene`/`overlay`/`status`/`done`/`stop` 五项**收到两项**：`status`、`done`。

- **为什么能收**：链内键走 RAM 档（`ram_only=True`），那一档**本来就没有** `scene`/`overlay`
  （`_ram_status` 的 docstring：「不写『你在野外』这类场景词……编一句出来就是在假观测上做决策」）。
  v6 的处理是"留着键、值为空串，靠一条约定解释"——账挪到产出格之后，**这条约定不再需要**：
  字段直接来自它刚产出的那份 `Observation`，没有的东西就根本不出现。
- **`stop` 挪去处置账**：`stop` 答的是"为什么截断"，那是处置的一部分；观察账只说"世界长什么样"。
  这样"这一键有没有被截断"就等于"有没有 `ACTION_TRUNCATED`"，不必在恒有值的字段里判空。
- **代价（明账）**：**中止键（链中间、非链尾）的 `scene`/`overlay` 没有结构化落点了。**
  信息不灭——那次感知的原始输出仍在 `MODEL_CALL(PERCEPTION)` 的 `payload["raw"]` 里，帧也挂在
  那一键的账上；但"看到什么"那两行结构化文字没了。链尾键不受影响（它的完整档会进下一条链的
  `OBSERVE`）。用户对链内观察的定性是"我按完这键、世界动了没"，故接受。

#### 3.7.3 帧归产出它的那一格（`_pending_frames` 缩到只剩第 0 步）

v6 的暂存表存在的**唯一**理由是"一帧的落点要等队列截断完才知道"（模块 docstring 原话）。
账挪到产出格之后，这个理由消失：

- `perceive_after_action` 产出帧 → **当场挂在自己那条 `AFTER_ACTION` 上**，同时登记
  `_frame_event_ids[(ep, step+1)] = event_id`；
- 下一条链的 `record_observation` 要"上一条链链尾那一帧的副本"时，**按登记的 event_id 把便利截图
  读回来**（`read_screenshot` + base64，复用现成的 `_frame_b64`）——不再需要"留在表里等下一个人取"；
- `_pending_frames` 于是只剩**第 0 步**一种去向（`_begin` 在图外、没有自己的事件可挂，只能暂存一手）。

**v6 的"两处都带"不受影响**：`OBSERVE` 仍然带这一链开局的帧（只是来源从"暂存表"换成"按 event_id
取回"），链尾那一格仍然有图（它自己那条 `AFTER_ACTION` 带的）。读者看到的图一处不少。
`_frame_event_ids` 的登记规则也更顺了——**"谁产出这一帧谁登记"**：现在产出与登记在同一格，
不再有"登记者是另一格"的情况（第 0 步仍由 `record_observation` 登记，因为那一帧的产出者 `_begin` 无事件）。

#### 3.7.4 账搬回宿主：util 不写账，只交回材料

用户的第三句打在另一件事上："太散了，trace 就在 harness 里记吧。"清点下来，全仓写账点 47 处
分布在 5 个文件：`episode_harness.py` 31（18 格的账 + 四类图外账）、`run_harness.py` 9、`brain_utils.py` 3、
`run_plan_utils.py` 2、`game_utils.py` 2。**真正"散"的是后三个 util**——一步的账写在两个文件里。

| | 现规则（"谁的循环谁记账"） | v7（"**账写在它的宿主里**"） |
|---|---|---|
| 重试循环 | 在 util | 不变 |
| 尝试账 `MODEL_CALL` | **util 边重试边写** | **宿主写**（节点 / 图外的局方法） |
| 收场（重试用尽） | util 抛 `MaxRetriesExceeded`/`PerceptionFailure` | 宿主按 util 交回的"没成功"决定抛 |
| util 的依赖 | 2 个端口（模型 + trace） | **1 个端口**（只留模型，顺带变得不起 trace 就能测） |

搬法**按调用点数出来，不是一律**：

| util | 调用方 | 搬法 |
|---|---|---|
| `brain_utils.choose_with_retry` | `think_action`（**唯一**） | **全搬** |
| `run_plan_utils.ask_planner_with_retry` | `RunHarness.plan`（**唯一**，而 `plan` 本来就是节点） | **全搬** |
| `game_utils.perceive_with_retry` | `perceive_after_action` ×2、`_begin` ×1（**图外**） | **搬一半**：节点两处自己写，`_begin` 那一处由图外方法自己写 |

**图外四类搬不动**，而且那不是"散"，是"没有宿主节点"：局边界（`_begin`/`_close`/异常路径）、
存档（`resume` 的 RESTORE、`save_checkpoint` 的 SAVE）、run 边界（`RUN_*`）、第 0 步那次感知。

所以规则不能写成"所有 trace 都写在节点里"（做不到），只能写成：
**「账写在它的宿主里」——宿主是节点就写节点，是图外的局/run 方法就写那个方法；util 只交回材料。**

落地形状：util 返回 `(结果 | None, 尝试账列表)`（`list[(attempt, ModelCall)]`），宿主用
`harness/trace_write.py` 的 `append_model_calls()` 一行写完——否则那段 `AppendReq` 样板会在
5 个写点各抄一遍。

> **（步 5a 现状，2026-09-12）**：这个函数已随 D8-③ 下沉到 `tools/trace/model_calls.py`，
> harness 侧改由 `TraceToolPort.append_model_calls(FromHarnessToTraceToolAppendModelCallsReq)`
> 交账；下面提到的 `harness/trace_write.py` 是**当时的落点**，保留原文不改。

**代价（明账，用户已认）**：`LocalTrace.append` 是**逐条原子落盘**。今天 `MODEL_CALL` 边重试边写，
"重试到第 2 次时进程被杀"仍留有前一次的账；搬完之后要等 util 返回才落盘，**进程死在模型调用里就全丢**。
窗口 ≤ 一次决策的重试条数（decision 3 / perception 2），且那时本来也不会有 `EPISODE_END`。
**事件顺序不变**：循环期间没有别的写账点，搬完 `event_id` 的相对次序与今天一致。

**顺带修掉 5 处走丢的引用**：`brain.py:187`、`ChooseOnceResp.py:18`、`trace_port.py:42`、
`world/pyboy_world.py:577`、`ROADMAP.md:163` 仍指着 `episode_utils.choose_with_retry` /
`episode_utils.perceive_with_retry` / `harness/utils.py`——那两个文件早就不存在了
（现行是 `brain_utils.py` / `game_utils.py`）。**文件位置不稳到连文档都记不住它在哪，
本身就是"散"的量化证据。** **✅ v7 已修**：4 处活代码 docstring 直接改成现行模块名；
`ROADMAP.md:163` 在一条历史条目里（0904 当时的名字是对的），**只加就地订正标记**，
不改历史论证。`trace_port.py:42` 那处顺带改成「帧由**感知的宿主**（`_begin` /
`record_observation` / `perceive_after_action`）在写事件时传入」——因为 v7 把账搬回宿主之后，
"util 传帧"这个描述本身也过期了。

#### 3.7.5 不变式核对

- `MODEL_CALL(DECISION)`/`(PERCEPTION)`/`(PLAN)` 的**条数不变**（只是写入者换了位置）；
- `event_id` 单调递增与相对次序不变；**节点数 20 不变、`NODES_PER_PRESS` 7 不变**（本次只改名）；
- `StepMemory.stop` 的盖章路径不变（仍由 `store_step_episode_memory` 从 `pending_stop` 盖上）；
- 每键的账：正常键 5 条（`ACT`/`AFTER_ACTION`/`STALL_CHECK`/`MEMORY_WRITE`/`STEP_ADVANCE`），
  **真的丢了键的那一键 +1**（`ACTION_TRUNCATED`）；每链：`OBSERVE` + `JUDGE_*` + `ACTION_SPACE`
  + 4×`RETRIEVE_NODE` + `MEMORY_READ` + `THINK`（+ 决策尝试账）；链边界 +1（`CHECKPOINT_SAVE`）；
- **20 格零哑格**：`save_checkpoint` 有了 `CHECKPOINT_SAVE`，`apply_stop` 有 `ACTION_TRUNCATED`
  （条件写，但不是没有）；
- `_frame_event_ids` 的 `(ep, s) → "第 s 步开局画面"` 语义不变，`before_frame`/`after_frame`
  两个方向都查得到；
- `resume()` 后首个链首的 `OBSERVE` 仍可能无图（`_frame_event_ids` 不持久化，既有契约）。

#### 3.7.6 被否 / 备选（留档）

| 备选 | 为什么不 |
|---|---|
| 截断账的条件写成 `stop is not None`（任何中止都记一条） | 会为"`blocked` 但队列里没有同向键可丢"的键写一条**没发生截断**的截断账。用户原话是"只有真的截断了"，所以条件取 `dropped` 非空。代价：那一类键的 `stop` 不进 trace（仍进 `StepMemory.stop`，大脑那侧不受影响） |
| 把 `dropped` 的展开逻辑塞进节点 | `AppendReq` + 渲染层已经承担"按 kind 拼 payload"，节点只该交回 `list[ActionSegment]` |
| `_pending_frames` 整个删掉 | 第 0 步那一帧没有事件可挂（`_begin` 在图外），删不掉 |
| 把尝试账的"1:N 展开"塞回渲染层（`AppendReq` 收一个 log） | 两条路都成立；选 `trace_write.py` 是因为它保住"一个写点一行、字段全在眼前"，且不动 `AppendReq` 与 `model_call` 的现有形状（`judge_call`/`verify_call` 靠包 `model_call` 实现） |

---

## 4. 新增：节点职责对照表

放在 `episode_harness_port.py` 的模块 docstring 里（接口即图，图的全貌应该在这里）。
一页看完 **20** 个格子：**它改哪一处状态、写哪条事件、一句话干什么**。
（下表已按 **v7** 同步：`record_action_result` 已改名 `apply_stop` 且只写处置账，
观察账归 `perceive_after_action`（`AFTER_ACTION`）；行数仍 **20**，行序即图的执行顺序。）

| # | 节点 | 改的 state 字段 | 写的 trace 事件 | 一句话 |
|---|---|---|---|---|
| 1 | `save_checkpoint` | —（写盘） | `CHECKPOINT_SAVE`（v7 新增） | 链边界存一份（世界快照 + state + 游标） |
| 2 | `record_observation` | —（只读；**不扶正**） | `OBSERVE`（**带本链开局帧**，§3.6） | 把本链开局这一帧登记入账——**它不感知** |
| 3 | `judge` | `done`、`success` | `JUDGE_CALL`、`JUDGE_VERDICT` | 四类终止一次判完 |
| 4 | `get_action_space` | `action_space` | `ACTION_SPACE` | 算这一步能用的按键 |
| 5 | `retrieve_step_episode_memory` | `step_episode_memories` | `RETRIEVE_NODE` | 查本局单步情景 |
| 6 | `retrieve_global_episode_memory` | `global_episode_memories` | `RETRIEVE_NODE` | 查跨局摘要 |
| 7 | `retrieve_knowledge_semantic_memory` | `knowledge_semantic_memory` | `RETRIEVE_NODE` | 查知识库 |
| 8 | `retrieve_object_semantic_memory` | `object_semantic_memory` | `RETRIEVE_NODE` | 查这张地图上的 object |
| 9 | `merge_retrieval` | `observation`（折 object） | `MEMORY_READ` | 四路汇聚 + 记合并账 |
| 10 | `think_action` | `plan`、`pending_presses` | `HUMAN_NOTE_INJECTED`、`THINK`（+决策账） | 决策出一条链 |
| 11 | `act` | `action`、`pending_presses` | `ACT` | 弹队首一键、推进世界（**只有它推世界**） |
| 12 | `perceive_after_action` | `pending_observation`、`pending_stop` | **`AFTER_ACTION`**（带帧）+ `MODEL_CALL(PERCEPTION)`（链尾/中止键） | 取新帧、判读结局（含中止补感知），**并留观察账** |
| 13 | `apply_stop` | `pending_presses` | `ACTION_TRUNCATED`（**只在真的丢了键时**） | **只落实**：按 `stop` 的作废范围截队 |
| 14 | `detect_stall` | `stall_key`、`stall_count` | `STALL_CHECK` | 算停摆（L2 护栏） |
| 15 | `store_step_episode_memory` | —（落库） | `MEMORY_WRITE` | 反思成一条情景记忆 |
| 16 | `store_object_semantic_memory` | —（落库） | `OBJECT_NOTE` | 判 object 事件并落库 |
| 17 | `close_step` | `observation`、`step` | `STEP_ADVANCE` | **扶正当前帧 + 步号加一**；链内小循环的分叉出口 |
| 18 | `retrieve_verify_step_memory` | `verify_step_entries` | `RETRIEVE_NODE` | 查本局全部 step |
| 19 | `retrieve_verify_knowledge` | `verify_knowledge` | `MEMORY_READ` | 查校验用知识 |
| 20 | `verify_and_summarize` | `verified_steps` | `VERIFY_CALL`、`VERIFY_RESULT`、`EPISODE_MEMORY_WRITE` | 一次调用：先判可信、再只用可信的写摘要 |

> **v7 只改了三行**（第 1/12/13），行数仍 20：第 1 行补 `CHECKPOINT_SAVE`；第 12 行从「无自己的事件」变成「写 `AFTER_ACTION`」；第 13 行改名 `apply_stop` 且只剩落实（留痕拆给第 12 行）。
> 这补上了 v6 拆节点时留下的另一半：v6 拆完之后「落实 + 留痕」仍捆在同一格，v7 才把两件事分干净。
>
> **v5 改了这段的形状**：19 行 → **20 行**——原第 12 行 `look_after_action` 拆成第 12/13 两行
> （`perceive_after_action` + `record_action_result`，§3.6），其后各行顺延一位；第 2 行补上
> "**带本链开局帧**"。这张表也顺带证明了一件事：**"每个节点只改一处"这条约束可以被拆解改善**
> ——第 12 行原来是"改三处"，拆完是 2 + 1。
>
> **v3 改了四行**（当时的编号）：第 2 行（`look` → `record_observation`，砍掉"扶正"这个动作描述）、
> 第 11 行（`act` 去掉 `observation`）、第 16 行（`advance_step` → `close_step`，
> 补上 `observation`，并记下它是条件边的源）、第 14/15 行（`close_step` 从两个 store
> **之前**挪到**之后**，与执行顺序一致）。
>
> **顺序口径**：这张表按**执行顺序**排（= 状态推进的先后），现在它与
> `episode_harness._compile()` 里 `add_node` 的**字面顺序**也一致——v3 顺手把
> `add_node("close_step")` 那一行从 `detect_stall` 之后挪到两个 store 之后。
> 这不是纯美观：`web/src/App.tsx` 的表头写着"顺序照抄 `add_node`"，两侧口径统一之后，
> §6 的机械核对才有可能从"比集合"升级成"**比有序列表**"。
>
> 第 9 行用的名字 **`merge_retrieval` 已落地**（§2.2，v7）；磁盘上不再有 `enrich_observation`。
>
> 这张表的价值在**多出来的两列**：改哪处 / 写哪条。现在这两件事只能从 19 段 docstring 里读出来，
> 而"每个节点只改一处"是接口对实现方的硬约束——**约束看不见，就没法检查**。

---

## 5. 明确不做（以及为什么）

| 不做 | 理由 |
|---|---|
| **并行化四路检索**（画成真菱形） | `event_id` 单调递增是 replay 与 SSE 断线补发的唯一依据；四个节点并发 `append` 会重号/缺号，`experiment/real_check/check_trace.py:56-57` 会直接判失败。换一个视觉收益，冒 trace 完整性的风险，性价比为负 |
| **合并节点**（如 `detect_stall`+`close_step`） | "每个节点只改状态里的一处"是接口对实现方的约束（`episode_harness_port.py` 原话："不只是风格建议"）。合并即破规，且这两个节点改的是不同组的字段 |
| **拆 `judge`** | 接口已明说"终止判定不该有两个节点各管一部分"；拆开会让"最后一帧仍可能达成目标"这条规则失去唯一的落点 |
| **改 `get_action_space`** | 与工具层撞名，但改动面 17 文件，收益只在"同时读两层代码"时体现（§2.3） |
| **重写 SPEC.md 的设计论证章节** | §1/§5/§7 的论证与节点数是 6 还是 19 无关，重写等于丢历史（§1.2） |
| **删掉 `look`（改为不要 `OBSERVE`）** | 链内键没有 `MODEL_CALL` 可挂全量观测，"每链一条 OBSERVE"是感知成本不变量的前提（§2.1 附） |
| **把 `record_observation` 并进 `look_after_action`** | 链尾帧有两个身份，两条账各记一种；且后者已是最胖节点（§3.5） |
| **把 `record_action_result` 的截队并回 `perceive_after_action`** | 那样第二格就只剩"写一条账"，与 `record_observation` 同形——正是本次要拆掉的相似（§3.6 备选接缝） |
| **截断账改成"任何中止都记一条"**（条件 `stop is not None`） | 会写出一条"没发生截断的截断账"（`blocked` 但队列里没有同向键可丢）；用户要求"只有真的截断了"（§3.7.6） |
| **把 `save_checkpoint` 的账省掉**（它现在是个哑格） | `resume()` 有 `CHECKPOINT_RESTORE`、存档端一条没有——恢复点可见、存档点不可见，反了；且 replay/统计要按存档切段只能反推（§3.7.1） |
| ~~**给链尾键的 `LOOK_AFTER` 补一份帧副本**~~ → **v6 做了**（用户拍板「重复是为了语义清晰」）：链尾那一步的图在 `LOOK_AFTER` 与下一条链的 `OBSERVE` 上各一份，约"每链多一张图"换两处自足（§3.6） |

---

## 6. 落地顺序与验收

**顺序**（先订正、再改名、最后加表——改名会牵动 web 与 SPEC，先改完名再统一改表可少改一遍）：

| # | 步骤 | 状态 |
|---|---|---|
| 0 | §3.4 的 B：`act` 去扶正 + `advance_step` → `close_step` + 条件边换源 | **✅ 2026-09-11 已落地** |
| 0b | 顺序口径统一：`_compile` 的 `add_node("close_step")` 挪到两个 store 之后；接口里 `close_step` 的声明同样后移（接口即图） | **✅ 2026-09-11 已落地** |
| 0c | §3.6 拆 `look_after_action`（`perceive_after_action` + `record_action_result`）+ 链尾帧两处都带 + `NODES_PER_PRESS` 6→7 + web 相位表补位 + `MAIN_END` 15→16（被插入**强制**跟着改）+ 离线核验脚本改写 | **✅ 2026-09-11 已落地**：离线核验 **56 条全绿**；`ruff` 对**本轮改的两文件**只剩 1 条历史 E501（全仓 49 条 vs HEAD 基线 50 条，本轮新增 0）；`tsc --noEmit` 通过；账见 `CHANGELOG.md`（18） |
| 0d | §3.7 三项落地：`record_action_result` → `apply_stop`（条件写 `ACTION_TRUNCATED`）+ 观察账挪回 `perceive_after_action` 并改名 `AFTER_ACTION`、字段收敛 + 帧改由 event_id 取回（`_pending_frames` 缩到第 0 步）+ `CHECKPOINT_SAVE` + 三个 util 去掉 trace 依赖（账搬回宿主） + web 相位表/`phaseKeyOf` 同步 + 离线核验脚本改写 | **✅ 2026-09-11 已落地**：离线核验 **66 条全绿**（56 → 66：新增 C 块 v7 三笔账的断言 + D 块接缝账）；`scripts/check_graph_phases.py` OK 20 节点；`tsc --noEmit` exit 0；账见 `CHANGELOG.md`（19） |
| 1 | §1.1 web 表格的"形状级"订正（`save_checkpoint` 补位、`verify_steps`+`summarize` 合一、`MAIN_END` 15→16）+ §1.3/§1.4/§1.5 三处文档订正 | **✅ 2026-09-11 已落地**：`CHAIN_PHASES` 20 条（`key` = 节点全名）、`MAIN_END` **16**、尾链三条；`ROADMAP.md:1136` 就地去句、`CHECKPOINT_handoff_2026-09-07.md` 加一行指引、`DATAFLOW.md` 一行订正 |
| 2 | §2.2 `enrich_observation` → `merge_retrieval`（代码 + 接口 + web key + docs 引用） | **✅ 2026-09-11 已落地**：活代码/活文档 25 处全改名，历史记录（`ROADMAP.md` 旧条目 / `CHECKPOINT_handoff` / `CHANGELOG.md` / 本 PLAN 的历史段落）不动 |
| 3 | §1.2 SPEC.md 的 §2/§3 替换 + 顶部现状块 | **✅ 2026-09-11 已落地**（按 §1.2 的建议：**结构重写 + 论证保留**） |
| 4 | §4 对照表进接口模块 docstring | **✅ 2026-09-11 已落地**：20 行表（节点 / 改哪处 / 写哪条 / 一句话）进了 `episode_harness_port.py` 模块 docstring，行序 = 执行顺序 |
| 5 | `CHANGELOG.md` 一条（四段式） | **✅ 2026-09-11（16）（17）（18）（19）已写**：步骤 0 / 0b / 0c / 0d+1+2+3+4 各一条 |

**验收**：

- **机械核对（新增，防再漂移）**：加一个 `scripts/check_graph_phases.py`——用 `ast` 从
  `episode_harness._compile()` 抽出 `add_node` 的字符串字面量，与 `web/src/App.tsx` 的
  `CHAIN_PHASES.key` 比对，不一致就非零退出。v3 之后两侧已是同一口径（同为执行顺序），
  所以可以先断言"集合相同"，等 §1.1 的 #1/#4 修完再收紧成"**列表逐条相同**"。
  **✅ v7 已落地并一次到位**（#1/#4 与它同日完成，不必分两步）：`scripts/check_graph_phases.py`
  直接断言**有序列表逐条相同**，当前输出 `OK  20 nodes; graph order == web CHAIN_PHASES order`。
  **这次漂移能藏两个月，就是因为没有这条断言。**
  这是本 PLAN 里唯一"新增机制"的一项，也是收益最长远的一项。
- `web/`：`npx tsc --noEmit` **通过**（v7 复跑，exit 0）；观测台点开一局，链上格数与终端 `add_node` 数一致（**20**）。
- 离线链内循环核验脚本（`~/.workbuddy/skills/pokemon-agent-offline-verify/scripts/verify_chain_inner_loop.py`）
  **✅ 66 条断言全绿**（v7 复跑 exit 0）。四块：A 图拓扑（含 `apply_stop` 顶替 `record_action_result`、
  两个旧名彻底消失）/ B 链内小循环与分档感知 / C v7 三笔新账（`AFTER_ACTION` 每键带帧且字段收敛到
  `{kind,status,done}`、`ACTION_TRUNCATED` 只在真丢键时写、「中止 ≠ 截断」、登记表指向先产出的那条
  `AFTER_ACTION`、跑完 `_pending_frames` 为空）/ D `CHECKPOINT_SAVE` 接缝账（存档点数 == 链边界数 ==
  `OBSERVE` 数，步号 `[0, 3]` 与真存档一致）。
- 真机六条命令由用户跑（AI 不碰 PyBoy）。

---

## 7. 拍板结果（2026-09-11 全数收口）

1. ~~**命名**：`enrich_observation` → `merge_retrieval`？~~ → **接受并已落地**（2026-09-11）。
   备选里没选 `regroup_for_think` 那一类：`merge_retrieval` 直接说"把四路检索合并"，
   而节点真正做的正是这件事（`observation` 折 object + 一条合并账）。
2. ~~**SPEC.md 的订正深度**：结构重写还是整篇重写？~~ → **结构重写 + 论证保留**，已落地（2026-09-11）。
   整篇重写等于丢掉 §1/§5/§7 里那些与节点数无关的设计论证。
3. ~~**`scripts/check_graph_phases.py`**：要不要加？~~ → **加，已落地**（2026-09-11）。
   它把"web 表与图一致"从约定变成断言；而且一次做到"有序逐条"（不必先比集合再收紧）。
4. ~~**`get_action_space` 撞名**~~ → **接受"不改、记为已知问题"**（2026-09-11）。
   理由见 §2.3：改动面 17 个文件，换来的只是"同时读两层代码"时少一次困惑。
5. ~~**`act` 的扶正（§3.4）**：走 B 还是 A？~~ → **已拍板 B，并已落地**（§3.4）。
6. ~~**`look` 的工作还需要吗？**~~ → **需要**：`OBSERVE` 每链一条是"感知成本不随链长增长"的前提，
   删了就没有"大脑当时看到的世界"的结构化原件。它保留为单一职责节点，改名 `record_observation`
   （§2.1 附）。
7. ~~**`look_after_action` 拆不拆？**~~ → **拆**（用户 2026-09-11："拆开吧，不然和 `observation`
   功能太像了"）。接缝被 `中止补感知 → stop` 这条依赖逼到唯一位置，方案见 §3.6。
8. ~~**帧的承载者（§3.6）**~~ → **两处都带**（用户 2026-09-11：「都保留，重复是为了语义清晰」）：
   链尾帧在那一键的 `LOOK_AFTER` 与下一条链的 `OBSERVE` 上各一份。
9. ~~**新节点的名字（§3.6）**~~ → **定名** `perceive_after_action` + `record_action_result`
   （用户 2026-09-11 拍板）。**v7 又把后者改成 `apply_stop`**（§3.7.1）。
10. ~~**观察账的落点与名字**~~ → 落回产出格 `perceive_after_action`，账名 **`AFTER_ACTION`**，
    字段收到 RAM 档的 `status`/`done`（§3.7.2）。
11. ~~**`stop` 归哪条账**~~ → **归处置账** `ACTION_TRUNCATED`（§3.7.2）。
12. ~~**`record_observation` 要不要也改名**~~ → **不改**：用户说的「没有 record 了」指的是
    `record_action_result`；`record_observation` 的职责（链首 `OBSERVE` + 第 0 步那一帧）没有变。
13. ~~**账搬回宿主**~~ → **做**（§3.7.4）：三个 util 全部去掉 trace 依赖，规则改写为
    "账写在它的宿主里"；代价（崩溃窗口）用户已认。
14. ~~**搬完之后那几处 `AppendReq` 样板怎么办**~~ → **抽成一个纯函数**
    `harness/trace_write.py::append_model_calls()`（§3.7.4）。
