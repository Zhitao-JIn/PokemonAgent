# PLAN —— MCP server 落码实施计划（memory + world + mcpclient）

> 2026-09-29（v2，整体重写对齐重写版 SPEC）｜ 依据：`docs/intent.md`（设计定稿）+
> `docs/spec/mcp/SPEC.md`（签名级规格，十二节定稿版）。
> 本文件管"怎么落地"：阶段、文件清单、验证、完成判据、依赖与风险。
> 实施时每阶段一个（或一组）CHANGELOG 编号条目，对应 commit 按 AGENTS.md §三.6。
> 层名已定案 ✅：`direct/`（brain/trace 直调）+ `mcpclient/`（memory/world 门面+client）。

## 总览

| Phase | 内容 | 预计规模 | 依赖 |
|---|---|---|---|
| P0 | 前置：`mcp` 依赖、CHANGELOG 条目占位 | 小 | — |
| P1 | memory server 能力面 + mcpclient 试金石（recall/memorize） | 中 | P0 |
| P2 | world server 原子层 7 条 + WorldPort 契约变更 | 中 | P0（client 模式复用 P1） |
| P3 | tables 三张表 + ScriptRun 骨架 | 中 | P2 |
| P4 | 脚本 15 条分两批（附录 A 逐脚本测试矩阵） | 大 | P3 |
| P5 | task 层适配：统一掩码选动作 + act_call + ActMemory/object 流转 | 中 | P4 |
| P6 | 事件流对齐 + rules.py 瘦身 | 中 | P2 + P4 + P5 |
| P7 | direct/ mcpclient/ 拆分落地 + build.py 开关 + 全项目文本同步 + 全量回归 | 大 | 全部 |

---

## P0 前置

- [ ] 依赖：`pyproject.toml` 加 `mcp`（官方 SDK，含 FastMCP）——确认版本与
      Streamable HTTP client API 形状、in-memory transport 可用性。
- [ ] CHANGELOG 编号条目占位（实施时逐条填）：
  ① memory server 能力面（recall/memorize）+ MemoryToolPort 收敛为两方法 +
     MemoryStorePort 降内部（**全仓调用点改造**）；② WorldPort 契约变更
     （mask/entries 统一掩码、all_actions 删除、step 返回带 event）；
     ③ world server 原子层；④ 脚本层 + ScriptRun；⑤ task 层适配
     （chooser 统一掩码 + ActMemory 脚本形状）；⑥ 事件流对齐 + rules.py 瘦身；
     ⑦ act 账改名 act_call（trace/node_io/渲染同步）；⑧ tools/ 拆分 direct/ + mcpclient/。
- [ ] **P0 完成判据**：`mcp` 可 import，官方 client session 示例在本机跑通
      （in-memory transport 优先验证，绕开网络层）。

## P1 memory server 能力面 + mcpclient 试金石

**文件**：
- `mcp_servers/__init__.py` / `mcp_servers/common.py`（返回信封组装 + 结局码词表）
- `mcp_servers/memory_server.py`：FastMCP 实例，**注册表只登记能力面 2 tools**：
  `recall` / `memorize`（构造收四族 store + 本地检索 provider）
- `memory/recall.py`：recall/memorize 能力实现——分族分流（episode_id 圈本局 /
  place 圈格 / query 语义检索 episode+knowledge）、融合排序（hint 命中族优先、
  族内相关性）、memorize 按 kind 判别落族（knowledge 判重 / object step 单调
  前置校验）；**MemoryStorePort 11 条降级为其内部接口**
- `MemoryToolPort` 收敛为两方法（CHANGELOG 条目 ①）：原 `query_*` / `store_*`
  15+ 方法全删，全仓调用点改造（感知束组装三查合一、act 后写、蒸馏落库、
  判定层精确查询走 recall conditions）
- `mcpclient/__init__.py` / `mcpclient/client.py`（session 管理：连接、tools/list
  缓存、call 转发、JSON-RPC error → Python 异常翻译）
- `mcpclient/memory_tool.py`：实现收敛后的 `MemoryToolPort`（recall/memorize
  薄转发 server）
- `tests/mcp_servers/test_mcp_memory_e2e.py`

**测试策略**：e2e 用 **in-memory transport**（client 直连 server 实例，不起端口）；
真机 HTTP 冒烟另做手跑验证，不进 CI。

**验证**：
- recall 分族/融合钉子：conditions={episode_id} → act/task 本局升序；
  conditions={place} → object 该格；query → episode/knowledge 语义融合；
  hint 命中族优先排序；
- memorize 分发钉子：五 kind 各一条落对族；knowledge 判重跳过；object step
  单调前置校验拒绝；
- 对比：进程内（memory/recall.py 直调 store）vs 经 mcpclient→server，同输入
  **逐字段一致**；
- 注册表核对：tools/list 恰好暴露 recall/memorize 两条（运维口不暴露）；
- 全仓 `query_*` / `store_*` 调用点清零 grep；ruff + 定向 pytest 绿。

**完成判据**：全部钉子绿 + 调用点清零 = 能力面收敛、注册表暴露、传输/异常翻译
全部验证通过，world 直接复用同一套 client 骨架。

## P2 world server 原子层 + WorldPort 契约变更

**文件**：
- `mcp_servers/world_server.py`：FastMCP 实例，构造收 world 实例 + 视觉 provider
  （**可注入**——测试用 fake，真机用 PyBoyWorld；server 不 new PyBoy）
- WorldPort 契约变更落码（CHANGELOG 条目 ②）：
  - mask/entries 统一能力掩码计算上移 world（原 GameToolPort.get_action_space
    职责迁入）；`all_actions` 删除；
  - `step` 返回值 None → `{moved, event?}`（裸事件协议）；
  - 会话缓存（对话增量"已见行集合"）+ reset/load_state 清空；
  - 单实例租约（第二 client initialize → `occupied`）。
- `mcpclient/world_tool.py`：实现 `GameToolPort`，7 方法转发（复用 client.py）。

**验证**：
- 单测：注入 fake world，7 方法逐条——重点 `step` 的 event 产出规则
  （入流过滤三例：普通移动无事件 / 撞挡无事件 / 换图 warp）；租约单测。
- 真机冒烟（用户本机起 server）：reset → get_action_space → perceive_task →
  step ×3 → save/load 手跑核对。

**完成判据**：fake 单测绿 + 真机冒烟通过（用户确认）。

## P3 tables 三张表 + ScriptRun 骨架

**文件**：
- `world/tables/warps.json`（map 12：出口格 + 触发方式 + 通往图）
- `world/tables/shop_layouts.json` / `pokecenter_layouts.json`（已知图先行）
- `world/scripts/__init__.py` / `world/scripts/engine.py`：ScriptRun 骨架
  （预算、events[]、三钩子 BattleStarted/ChoicePresented/MapChanged、放弃动作、
  对话增量缓存——已见行集合）；脚本**放 world 包内**（依赖 Console/RAM/tile
  直读，随 world 整体拷走）

**验证**：
- 骨架单测（FakeConsole）：三钩子各一条、预算耗尽一条、对话增量三例
  （首框全量 / 滚动增量 / 全已见无事件）——钉子测试。

**完成判据**：骨架钉子测试绿；map 12 warps 表与真机抽查一致（用户核对）。

## P4 脚本 14 条分两批（逐脚本测试矩阵见附录 A）

**第一批**（覆盖历史全部任务模式）：
`walk_to_adjacent` → `walk_to` → `circle_walk` → `talk_to_adjacent_npc` →
`bounce_in_tall_grass` → `buy_item` / `sell_item`

**第二批**：`face_direction` → `exit_map` → `interact_facing` → `advance_dialog` →
`open_menu_to` → `heal_at_center` → `wait_until_scene`

**每条完成判据 = 附录 A 对应行单测矩阵全绿 + 真机验收场景用户确认。**

## P5 task 层适配（统一掩码选动作 + act_call + 记忆流转）

**1. chooser：统一能力掩码选动作**
- `{mask, entries}` 进 chooser prompt：每条目可读描述（键 = 按键语义；
  脚本 = 名字/参数/适用场合）；
- chooser 输出**一个动作名**（脚本另带 args）→ 断言：名字 ∈ 掩码且 enabled
  → 非法 = ParseFailure → trace 错误账 → 重试（现有机制）；
- prompt 模板（`brain/calls/*.md`）同步改。

**2. TaskRuntime.act：按名字归属分流执行**
- key → `step`（响应带 event）；script → mcpclient 调 world server 对应脚本
  API（同步到底，终态报告 + events[] + calls[] 返回）；
- **占步语义**：一次脚本调用占 harness 账一步（内部 N 键不展开）——
  task 循环仍是一动作一决策圈。

**3. ActMemory / trace / object memory 流转**
- **act 账改名 `act_call`**（CHANGELOG 条目 ⑦）：content 按 key/script 两形
  （§SPEC 3.6）；node_io STEP 模板/source 表同步；渲染模板（JEV）兼容；
- ActMemory：script 动作 button 记 `script:<name>`、payload 带 args 与终态
  报告摘要（ok/code）——verify 标记、summaries 蒸馏链兼容；
- judge：脚本终态报告 `ok/code` 直接作为"行为是否达成"的机械证据
  （判据只认达成的现有约定不变）；
- object memory：逐键路径读 step 响应 `event`；脚本路径收 `events[]` 批量——
  两路径交 rules.py 汇合（P6 对齐）；落库经 `memorize`（kind=object）。

**验证**：
- chooser 解析单测：动作名解析/越权（掩码外）拒绝/脚本 args 校验；
- act 单测：脚本动作占一步、ActMemory 形状、act_call 两形 content、
  calls[] 带回落账；
- e2e（FakeLLM + fake world + in-memory server）："模型选脚本"决策圈全流程，
  ActMemory / object 事件 / trace 三处形状核对。

**完成判据**：四组单测绿 + e2e 绿。

## P6 事件流对齐 + rules.py 瘦身

**文件**：
- `harness/episode/store/store_object_semantic_memory/rules.py` 瘦身：
  逐键判定（outcome/object_kind）**前移 server**（删），补三章 + 组装 put
  三件套（键 map_id:x:y）保留；
- 消费端改造：判定层/图节点读 `step` 响应的 `event`（不再自判）；
- MCP 模式下 object 事件落库 = rules.py 补三章 → mcpclient `memorize`（kind=object）→
  server 分族落库。

**验证**：
- 两路径对齐钉子测试：同一操作序列，脚本批量 events 与逐键 step 事件
  拼接流**逐字段一致**；
- 增量规则钉子（§SPEC 3.5）在真事件流上复验；
- 入流过滤：普通移动零事件、blocked 零事件、warp 入流。

**完成判据**：对齐测试绿；现有测试不回归（判定层老路径对非脚本交互保留）。

## P7 direct/ mcpclient/ 拆分落地 + 装配开关 + 全项目文本同步 + 全量回归

**文件（代码）**：
- `tools/` 拆分：BrainTool / TraceTool → `direct/`；memory/world 门面 →
  `mcpclient/`（若 P1/P2 已按新址落码则此步只剩收尾核对）；全仓 import 替换；
- `build.py` 加裸字段开关：`world_server_url` / `memory_server_url`
  （缺省进程内，行为不变）；
- import 清零核对：server/mcpclient 对四模块的依赖面检查（同 world SPEC §八手法）。

**全项目文本同步清单**（跟码改，历史文档冻结不动）：

| 文档 | 要改的内容 |
|---|---|
| `AGENTS.md` | 目录结构（tools/ → direct/ + mcpclient/ + mcp_servers/）、铁律 2 与门面描述、"谁依赖 brain 唯一答案 tool 层"表述、装配描述 |
| `docs/spec/tools/SPEC.md` | 整份重写/拆分：direct（brain/trace）与 mcpclient（memory/world 门面+client）两节 |
| `docs/spec/OVERVIEW.md` / `README.md` / `CLAUDE.md` / `docs/spec/README.md` | 总览图与分层描述 |
| `docs/spec/memory/SPEC.md` / `PORTS.md` / `API.md` | MemoryToolPort 收敛两方法（recall/memorize）、MemoryStorePort 降内部、recall.py 能力实现 |
| `docs/spec/world/SPEC.md` | "mcpclient/game_tools.py 唯一调用方"等引用 → mcpclient/world_tool；mask/entries 契约 |
| `docs/spec/trace/SPEC.md` / `API.md` / `TRACE_37_accounts_examples.md` | act 账改名 act_call、content 扩 event/script 字段、kind 清单 |
| `docs/spec/harness/SPEC.md` / `schemas/SPEC.md` | tool 层引用、信封描述 |
| 73 个 `.py` 的 docstring | "tool 层"/"tools/"字样随落码逐文件改（各 Phase 动到的文件同步改） |

**历史文档冻结**：`docs/checkpoint/`、`docs/eval/`、`docs/experiences/`、
`docs/perceive/`、`docs/web_reviewer/`、`docs/HANDOFF_*.md`——过去时记录，不改。

**同步规则**：每个 Phase 落码时同步改**该 Phase 动到的文件**的 docstring 与
spec 对应节；P7 收口全局（AGENTS/README/OVERVIEW/tools SPEC/trace 账名）。

**验证**：
- 全量 pytest（新 basetemp，`.venv` 主力）；
- 真机 smoke + rehearsal（用户起跑）；
- 确认缺省装配（不传 server_url）行为与改造前逐字段一致；
- 文本核对：`grep -r "tools/" --include="*.py"` 在活代码中清零（历史文档除外）。

**完成判据**：全量绿 + rehearsal 三树全对 + 缺省模式无感 + 活文档与代码无冲突。

---

## 附录 A：逐脚本测试矩阵

单测全部用 FakeConsole（可编程：RAM 值、屏幕帧序列、按键副作用）；
真机验收场景由用户本机执行。**每行全绿 = 该脚本完成**。

| # | 脚本 | 单测用例（FakeConsole） | 真机验收场景 |
|---|---|---|---|
| 1 | `get_action_space` | 野外 mask 全开；菜单场合 mask 收窄；scripts 条目按 map 白名单变化；entries 形状（键无载荷/脚本带 params） | 三个场合各查一次，人工比对掩码与脚本清单 |
| 2 | `circle_walk` | ① 空地 2 圈回起点 ok；② 圈内预设 NPC 占位 → off_course；③ max_steps 耗尽 → budget_exhausted；④ 中途进战斗 → battle_started | 起点绕圈 2 圈，核对终态位置与事件 |
| 3 | `walk_to_adjacent` | ① 开阔地成功；② 目标格树 → blocked；③ 目标格 NPC → blocked；④ 目标格草丛 → ok+entered_grass | 东西南北各走一步核对 |
| 4 | `walk_to` | ① 直线到达；② 直线上预设一棵树 → 换轴绕行到达；③ 四方向全挡 → not_converging；④ max_steps 耗尽 → budget_exhausted；⑤ 途中踩出口 → map_changed 终止 | 跨越障碍物走到指定格 |
| 5 | `face_direction` | ① 已面向 → moved=false；② 前方可走 → moved=true（位移如实）；③ 前方障碍 → moved=false（原地转向） | 朝向变化与位移人工核对 |
| 6 | `exit_map` | ① 站 g 上按触发方向 → warp 成功；② 不在 g → 先 walk 再触发；③ g 上按键 map_id 不变 → warp_failed；④ 去 g 途中 blocked | map 12 西出口换图往返 |
| 7 | `bounce_in_tall_grass` | ① N 步内进战斗 → ok+battle_started；② steps 用完无怪 → no_encounter；③ 起始格非草丛 → rejected | 草丛走位至遇怪 |
| 8 | `talk_to_adjacent_npc` | ① 两框对话收全回野外 → dialog 增量正确；② 第二框后出选项 → choice_presented + 已收文本；③ 面前无 NPC → no_target；④ 按 a 无框 → no_response；⑤ 对话完进战斗 → battle_started+dialog | 与 (14,x) 巡逻 NPC 对话一次 |
| 9 | `interact_facing` | ① 对招牌 → dialog；② 对石头 → no_response | 招牌与石头各一次 |
| 10 | `advance_dialog` | ① 三框推进到结束；② 预算内推不完 → still_talking | 长对话推进到底 |
| 11 | `open_menu_to` | ① start→POKéMON 子菜单成功；② 光标走偏 → wrong_scene（回初态） | 开菜单进 POKéMON 页 |
| 12 | `buy_item` | ① 成功：扣款==price×count 且入库；② 不在售 → not_sold_here；③ count>99 → count_limit；④ 钱不够 → insufficient_funds；⑤ 宏走偏 → verify_failed | 商店买精灵球 ×5，核对钱与背包 |
| 13 | `sell_item` | ① 成功：收款==卖价×count；② 背包无此物 → not_in_bag；③ count>stock → insufficient_stock；④ verify_failed | 卖出上月库存道具 |
| 14 | `heal_at_center` | ① 全流程 HP 满；② map 非白名单 → unsupported_map；③ 宏 aborted → 卡环上报；④ HP 未满 → verify_failed | 中心回血一轮 |
| 15 | `wait_until_scene` | ① 预设 scene 变化 → 成功；② 超时 → timeout | 换图淡入等待 |

**事件流专项钉子**（跨脚本，FakeConsole 层）：① 普通移动零事件；② 移动被挡
零事件（blocked 只在 code）；③ 换图 warp 入流；④ dialog 增量三例（§SPEC 3.5）；
⑤ 脚本批量 events 与逐键 step 拼流逐字段一致。

---

## 风险清单

| 风险 | 缓解 |
|---|---|
| mcp SDK 的 Windows HTTP 细节（防火墙/localhost 绑定） | 测试用 in-memory transport；HTTP 只在真机冒烟 |
| world server 单实例租约实现（initialize 拒绝第二连接） | FastMCP 层做连接计数；P2 就位 |
| 对话增量缓存与 checkpoint 一致性（load_state 后缓存残留） | reset/load_state 清空缓存（P2 落码）——测试钉住 |
| WorldPort 契约变更波及 GameTools / 图节点 | 独立 CHANGELOG 条目；P2 内一次迁完不留双轨 |
| act_call 改名波及 trace/node_io/渲染 | 独立 CHANGELOG 条目（⑦）；钉子测试先行 |
| 统一掩码引发 chooser prompt/解析回归 | P5 独立条目；FakeLLM e2e 先行，真机回归兜底 |
| 长脚本阻塞（脚本同步到底） | 先接受；真机撞上再加 `script_progress` 轮询 API |
| tools/ 拆分全仓波及 | 放最后（P7），一次性替换，全量回归兜底 |

## 明确不做（本期）

- brain MCP 化；泛型 run_script；run_macro 对外；battle 第四类事件；
  移动 blocked 入流；server 端组装逻辑/补三章；mcpclient 持账本坐标。
  ——理由均在 `docs/intent.md` §七。
