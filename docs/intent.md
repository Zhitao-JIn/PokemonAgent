# INTENT —— 模块 MCP 化改造定案（world / memory）
> 视觉感知档已于 2026-10-16 删除，见 docs/perceive/remove-vision-spec.md；本文为历史记录，正文未改。

> 2026-09-29 与用户逐轮定向后的最终设计。取代此前所有被否的中间方案
> （McpMemoryStore proxy / RemoteMemoryTool stub / server 持有 MemoryTool——均废弃）。
> 本文档是落码依据；动代码前先改这里。

## 〇、一句话

把 **world 与 memory 变成独立 MCP server**，harness 侧新立一层 **mcpclient**
（memory/world 的门面 + MCP client，带信封翻译与组装逻辑）调它们；brain / trace 留进程内直调（原 tool 层改名 `direct/`）。server 只做
**Port 的 1:1 JSON 直译**（返回值 + 状态码），一切领域逻辑归 harness 侧；机械脚本
（组合 step / run_macro 的长程任务）作为 server 内部能力，一脚本一条对外 API。

## 一、为什么做 / 为什么这样做

- **动机**：模拟器与世界能力独立成进程（契合"起跑交回用户本机"口径）、
  记忆库可被多个消费者共享、对外能力用标准协议暴露（MCP tools/list 自描述）。
  **memory server 的未来消费者（2026-09-29 用户定案）**：① agentic memory——
  模型自主选择查/写记忆（当前 harness 是图节点固定时机写死调用，届时演进为
  模型工具面）；② 前端人格 agent——WebReviewer 侧的人格 agent 作为记忆库的
  独立消费者。这两条是 memory server 与 world 同批建设的依据。
- **关键修正（讨论定案）**：
  1. MCP 的标准图景是"LLM 应用（client）↔ 能力进程（server）"；harness 不是 LLM 应用，
     它经 mcpclient 以**写死的代码**调 server（MCP 允许，协议不要求调用方是模型）。
  2. server **不持有任何 harness 概念**（无信封、无 MemoryTool、无账本坐标）——
     只有 Port 裸方法的 JSON 直译；领域组装逻辑（升序/判重/episode 过滤/补章）全在 harness 侧。
  3. **脚本层必须在 server 进程内**：脚本内部高频循环（每键 press/tick/读 RAM），
     走 RPC 会把节奏打碎；对外 RPC 次数从 O(按键数) 压到 O(1)。
  4. 补三章（账本坐标）归 harness 判定层（rules.py 瘦身版）；mcpclient 持
     信封翻译与组装（升序/判重/键拼装），但不持账本坐标。

## 二、分层架构

```
┌ harness（图节点、runtime、账本坐标持有人）────────────────────┐
│  脚本执行格 / 判定层 rules.py（补三章 + 组装 put）              │
└──────┬──────────────────────────────┬────────────────────────┘
       │ 进程内直调                     │ 进程内直调
┌──────▼─────────────┐   ┌────────────▼──────────────────────┐
│ direct/（brain/trace│   │ mcpclient/（memory/world 门面       │
│ 改名）              │   │ 纯传输：注册表缓存 + 转发，零领域逻辑）│
│ BrainTool/TraceTool │   └──────┬─────────────┬──────────────┘
└──────┬─────────────┘          │ MCP          │ MCP
       ▼                        ▼              ▼
   brain / trace          mcp_servers/     mcp_servers/
   （Langfuse 后端不变）    memory_server    world_server
                          （MemoryStore 裸面） （WorldPort+脚本层）
```

- **direct/**：原 tool 层改名，只剩 brain / trace 直调门面。trace 的 Langfuse
  backend 本就是远程 HTTP，不受影响。
- **mcpclient/**：memory/world 门面 + MCP client（带逻辑属性）。启动时经 `tools/list` 拉取注册表缓存；
  转发请求、回传结果。不做任何判定、不碰账本。
- **mcp_servers/**：两个独立进程，用户本机起跑（0924 口径），Streamable HTTP
  transport（Windows 沙箱 stdio 有前科）。统一返回信封：
  `{ok: bool, code: string, data: ..., events: [...], error: string|null}`。

## 三、事件流协议（ObjectFactEvent 对齐）

三类结局（现有 schema，不改判别联合；battle **不加**第四类）：

| outcome | 载荷 | 触发 |
|---|---|---|
| `dialog` | text（逐框文本） | 面对物体按键出字 |
| `warp` | map_id（新图） | **任何键**穿过出口格换图——含普通移动键 |
| `still` | 无 | 交互按键无变化（无反应物体 / 对话关闭）；移动被挡不入流 |

**入流规则（过滤垃圾）**：普通移动（位移成功、未换图、面前无物体）**不进流**；
移动被障碍挡**不入流**（碰撞可静态推导，blocked 由脚本 `code` 传达）；
移动触发换图（warp）进流。移动键入流的唯一情形 = warp。

**dialog 增量规则（写侧主动增量，用户定案）**：抄屏发生在画面稳定之后
（STABLE_POLLS），text 存**本框新增文本**而非整框：

- server 为当前对话段维护"已见行集合"（reset / load_state 时清空）；
- 新稳定帧的行中，不在集合里的 = 新增 → `text` = 新增行拼接；首框 = 整框全量；
- 新帧全部行都已在集合里 → 不产生新事件（同帧/已见内容跳过）；
- choice / 对话结束清空集合；
- 消费方按序直接拼接 dialog 事件即得完整对话，无需 diff。

落库仍为 append-only（跨次调用 / 跨 run 的同格同事件**不去重**——归并归
机制一消费侧；增量只消解单段对话内的滚动重叠，是写入正确性的一部分）。

**裸事件字段**（server 侧判定，无账本坐标）：
`{outcome, actor_place:{map_id,x,y}, place:{map_id,x,y}, object_kind, button, text?, map_id?}`
——`object_kind`（npc/sign/stone/tree/door/exit/grass…）判定**前移到 server**
（它有 tile/对象表直读）。

**两条路径对称出口**：

| 路径 | 事件出口 |
|---|---|
| 模型逐键 | **每次 `step` 响应带单条 `event`**（或 null）——判定层免自判 |
| 脚本（批量） | 终态报告 `events[]`（保序） |

**落库全链**（五环节）：

```
① server 脚本/step 判定 → 裸 events[]（无三章）
② harness 脚本执行格收报告 → 交判定层
③ rules.py（瘦身）：补三章（episode_id/run_id/step）+ 组装 put 三件套
   （metadata 含键 map_id:x:y——键算法留在 harness，与真身一致）
④ mcpclient 循环 put → memory server → store 写穿（现有逻辑零改动；
   "step ≥ 本局最大 step"前置天然满足）
⑤ 检索闭环：filter({map_id,x,y}) → 判定层拿到"这格发生过什么"
```

- **step 语义**：一次脚本调用在 harness 账记**一步**，N 事件同 step、数组保序。
- 两条路径（模型逐键走判定层老路径 / 脚本批量回灌）产出同一形状，落库口共用。

## 四、脚本骨架：ScriptRun（宏引擎的姊妹篇）

宏（`macros/`，八场合）管"场合内按键序列"；脚本管"跨场合任务链"。共用
Abort / 预算 / 稳定判定的物理量，骨架在 server 进程内：

```
ScriptRun 持有：预算（steps/帧，复用 STEP_TIMEOUT_FRAMES=900、NAV_LIMIT=120）
               事件流 events[]
每步自动钩子（三钩子，所有脚本共享）：
  ① scene 变 BATTLE   → BattleStarted（终止；bounce 例外——撞怪即目的）
  ② 屏幕出选项框       → ChoicePresented（冻结，选项文本随返回出去；绝不代选）
  ③ map_id 变化       → MapChanged（exit_map 捕获为成功；其余脚本终止 map_changed）
放弃动作：预算耗尽/钩子触发 → 停止按键 → 冻结现场 → {ok:false, code, 现场快照}
成功谓词：每脚本一条，机械可判
```

原则：**脚本只做确定性的事；分叉（choice/battle/换图）停并上报，决策权回调用方。**

## 五、World Server API（原子 7 + 脚本 14 = 21 条）

`run_macro` **不对外**——被脚本拆解消化，是 server 内部实现细节（脚本骨架调它）。

### 原子层

| # | API | 入参 | 返回 data |
|---|---|---|---|
| 1 | `reset` | task_id, goal, success_criteria, max_steps, initial_state_hint? | null |
| 2 | `get_action_space` | — | `{mask:{key:bool}, scripts:[名], scene}`（合并版：掩码+场合可用脚本；原 all_actions/macro_specs 被吸收，删） |
| 3 | `perceive_task` | — | `{scene, screen\|walk_map, pos}` |
| 4 | `perceive_once` | — | Perceived JSON（视觉档；重试归调用方） |
| 5 | `step` | segments, settle | `{moved, event?}`——**唯一执行口**，响应带本键裸事件（见 §三） |
| 6 | `save_state` | — | state_base64 |
| 7 | `load_state` | state_base64 | null |

### 脚本层（一脚本一 API，终态报告统一带 events[]）

| # | API | 入参 | 成功谓词 | 关键失败码 |
|---|---|---|---|---|
| 9 | `buy_item` | item, count | 扣款/入库校验通过 | not_sold_here, count_limit, insufficient_funds, verify_failed |
| 10 | `sell_item` | item, count | 收款/出库校验通过 | not_in_bag, insufficient_stock, verify_failed |
| 11 | `circle_walk` | laps, extent?=1 | 回起点计满 | off_course, battle_started |
| 12 | `walk_to_adjacent` | direction | pos==目标 | blocked |
| 13 | `walk_to` | x, y, max_steps?=200 | pos==目标 | blocked, not_converging |
| 14 | `face_direction` | direction | 朝向就位（moved 如实报） | — |
| 15 | `exit_map` | target_warp?=-1 | map_id 变化 | warp_failed（表过期）, blocked |
| 16 | `bounce_in_tall_grass` | steps?=30 | steps 用完或进战斗 | —（no_encounter/battle_started 均 ok） |
| 17 | `talk_to_adjacent_npc` | direction? | 对话收完回野外 | no_target, no_response, choice_presented, battle_started |
| 18 | `interact_facing` | — | 有反应或确认无反应（no_response 合法） | — |
| 19 | `advance_dialog` | max_presses?=30 | 画面静止无 ▼ | still_talking |
| 20 | `open_menu_to` | target | scene==目标子菜单 | wrong_scene |
| 21 | `heal_at_center` | max_steps?=60 | 队伍 HP 全满 | unsupported_map, verify_failed |
| 22 | `wait_until_scene` | scene, timeout_s | scene 匹配 | timeout |
| 23 | `get_action_desc_with_mask`（client 侧辅助，mcpclient 提供，不在 server） | mask | 动作可读描述 | — |

关键流程要点（完整伪逻辑见讨论记录，此处浓缩）：

- **buy_item**：前置白名单 map → 读 money0/stock0/在售表 → item 逐字匹配目录（单价以表为准）→
  count 校验 →
  run_macro(shop buy)：光标/数量 NAV_LIMIT 兜底，确认框**宏代答"是"**（机械确认非分叉）→
  终态校验 money0−money1==price×count 且 stock 增量==count。
- **heal_at_center**：按当前 map_id 查 `tables.pokecenter_layouts`（护士/站位坐标）
  → 内联 walk_to 到站位 → 面朝护士按 a 对话 → YES/NO 选项机械确认 YES（raw 绕钩子）
  → 推进回野外 → 读队伍 RAM 校验全满。
- **exit_map**：查 `tables.warps[map_id]` 全部出口 g[] → 已在 g 上按触发方向，
  否则内联 walk_to 最近/指定 g → 触发 → MapChanged 钩子 → 校验新图；
  站 g 按了没反应 → `warp_failed`（表过期，修 tables 不是脚本兜底）。
- **事件例**（判定规则实例化）：对 NPC 三框对话 = dialog/dialog/still；
  choice 弹出 = 最后一键 dialog + 终止 code 带选项；对石头按 a = still（无 text）；
  walk 撞树 = still(object_kind:tree)；walk_to 换图 = warp(object_kind:exit)；
  普通移动键 = 无事件。

### tables/ 新增静态数据（map 12 先行）

- `warps[map_id]`：出口格 + 触发方向 + 通往图
- `shop_layouts[map_id]`：在售表 + 柜台坐标
- `pokecenter_layouts[map_id]`：柜台/护士坐标
- map 不在白名单 → `rejected("unsupported_map")`（不同店/中心 map_id 不同，脚本按表区分）

## 六、Memory Server API（11 条，裸面零领域逻辑）

put / get / get_many / filter / search / rank / delete_many / snapshot / restore /
count / refresh_changed——签名即 `MemoryStorePort` 1:1。领域组装
（升序、判重、episode 过滤、键拼装、三章）全在 harness 侧（rules.py 补三章 / mcpclient 组装，各持其半）。
批量落库 = 调用方循环 put。

## 七、不做的（防止回潮）

- ❌ brain MCP 化（无状态但关键路径，加跳数零收益）
- ❌ harness 内部用 MCP 替代进程内调用（"把 MCP 当 RPC 改造 harness"已证伪）
- ❌ server 端组装逻辑 / server 持有 MemoryTool / mcpclient 补三章
- ❌ run_macro 对外暴露；泛型 run_script(name,args)（一脚本一 API）
- ❌ battle 第四类事件；普通移动键入流

## 八、待定向（开工前需用户确认）

1. ✅ 层名定案：`direct/`（brain/trace 直调）+ `mcpclient/`（memory/world 门面+client）
2. WorldPort 契约变更（mask/scripts 并入 get_action_space、all_actions 删除、
   step 返回带 event）——过 CHANGELOG 编号条目
3. tables/ 三张表的 map 覆盖范围（map 12 先行）
4. 脚本第一批实现顺序（建议：walk_to_adjacent → walk_to → circle_walk →
   talk_to_adjacent_npc → bounce_in_tall_grass → buy_item/sell_item）
5. run_script 长脚本的阻塞问题（先同步到底 + 终态报告，撞上再加进度轮询）

## 九、实施顺序（建议）

0. ✅ 签名级规格已落 `docs/spec/mcp/SPEC.md`（2026-09-29）——落码以它为直接依据
1. ~~`docs/spec/` 落 SPEC~~ + CHANGELOG 编号条目（契约变更拆独立条目）
2. memory server 先行：`mcp_servers/memory_server.py`（11 条裸面）+ mcpclient 骨架 +
   一条端到端测试（起 server → 调 → 与进程内实现逐字段一致）
3. world server：原子 7 条 → tables 三张表 → 脚本骨架 ScriptRun → 脚本分批
4. rules.py 瘦身（判定前移 server，补章保留）+ 事件流对齐测试
5. direct/ 改名 + build.py 装配开关（server_url 裸字段）
