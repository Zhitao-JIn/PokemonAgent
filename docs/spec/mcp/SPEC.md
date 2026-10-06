# mcp —— server 与 mcpclient 规格

> 最后更新：2026-09-29（整份重写，反映全部定案）｜ 活文档：跟随代码更新，与代码冲突时以代码为准
> 设计定稿源：`docs/intent.md`（背景与修正决策史）；落码计划：`docs/PLAN_mcp_servers.md`。

## 一、职责与边界

三个新件 + 一次拆分（`tools/` 拆成 `direct/` 与 `mcpclient/`，2026-09-29 定案）：

- **`direct/`**：`tools/` 拆出的进程内一半，**只保留 brain / trace 的直调门面**
  （BrainTool / TraceTool）。trace 的 Langfuse backend 不变。
- **`mcpclient/`**：`tools/` 拆出的对外一半，**带逻辑属性**——memory / world 两个
  门面随迁（`memory_tool.py` 实现 `MemoryToolPort`、`world_tool.py` 实现
  `GameToolPort`）：**信封翻译与组装逻辑由 mcpclient 担任**（升序 / 判重 /
  键拼装随迁自原 MemoryTool / GameTools），底层调用换成 MCP client 转发。
  **不持账本坐标**——三章（episode_id/step/run_id）归 harness 判定层。
- **`mcp_servers/memory_server`**：`MemoryStorePort` 11 方法的 1:1 JSON 直译，
  **零领域逻辑**。持有 MemoryStore 与两个本地检索 provider（配置注入）。
- **`mcp_servers/world_server`**：`WorldPort` 裸方法直译（原子层）+ **脚本层**
  （ScriptRun 骨架 + 15 条机械脚本）。持有 PyBoy 与视觉 provider（可注入）。
  outcome / object_kind 判定在这里；账本三章不在。

边界铁律（沿用 AGENTS.md）：

- server 不 import harness / tools 的任何东西——不认识信封、不认识 MemoryTool；
- mcpclient 持"信封↔裸面"翻译与组装，**不持账本坐标**；补三章归 harness 判定层
  （rules.py 瘦身版）；
- 落库 append-only：跨次调用 / 跨 run 不去重，去重与归并归机制一消费侧。

分层总览：

```
┌ harness（图节点、runtime、账本坐标持有人）─────────────────────┐
│  脚本执行格 / 判定层 rules.py（瘦身后：补三章 + 组装 put）        │
└──────┬───────────────────────────────┬────────────────────────┘
       │ 进程内直调                      │ 进程内直调（信封不变）
┌──────▼──────────────┐   ┌─────────────▼────────────────────┐
│ direct/             │   │ mcpclient/                        │
│  BrainTool          │   │  memory_tool（MemoryToolPort）    │
│  TraceTool          │   │  world_tool（GameToolPort）       │
│                     │   │  信封翻译+组装 + MCP client 转发   │
└──────┬──────────────┘   └──────┬─────────────────┬──────────┘
       ▼                         │ MCP             │ MCP
   brain / trace                 ▼                 ▼
   （Langfuse 不变）      mcp_servers/memory   mcp_servers/world
                          （11 裸面）           （7 原子 + 16 脚本）
```

## 二、目录结构（新增部分）

```
pokemon_agent/
├── direct/                         进程内直调门面（原 tools/ 拆出）
│   ├── brain_tool.py               BrainTool（brain 六链路）
│   └── trace/                      TraceTool（backend 照旧：local/langfuse）
├── mcpclient/                      memory/world 门面 + MCP client（带逻辑属性）
│   ├── __init__.py
│   ├── client.py                   MCP session 管理：连接、tools/list 缓存、
│   │                               调用转发、JSON-RPC error → 异常翻译
│   ├── memory_tool.py              实现 MemoryToolPort：信封翻译 + 组装随迁
│   │                               （升序/判重/键拼装）+ 转发裸面
│   └── world_tool.py               实现 GameToolPort：信封翻译 + 转发
│                                   （脚本动作入口也在此）
├── mcp_servers/
│   ├── __init__.py
│   ├── common.py                   统一返回信封组装、结局码词表、共享工具
│   ├── memory_server.py            FastMCP 实例：能力面 2 tools（recall/memorize）
│   │                               + /health 路由（普通 HTTP，不进能力面）
│   └── world_server.py             FastMCP 实例：原子层 7 tools + release_lease
│                                   + /health（含 lease_owner）；单实例租约
│   └── world_server.py             FastMCP 实例：7 原子 + 16 脚本 tools
└── world/
    ├── scripts/                    脚本层（ScriptRun 骨架 + 15 条；随 world 拷走）
    └── tables/                     （扩）warps / shop_layouts / pokecenter_layouts
memory/（模块内新增）
    └── recall.py                   （新）recall/memorize 能力实现：分族分流、
                                    融合排序、kind 判别落族（一份实现两模式共用；
                                    MemoryStorePort 11 条降级为其内部接口）
tests/test_mcp_memory_e2e.py        端到端：in-memory transport，与进程内逐字段一致
```


> **地址与探活（2026-09-29 补）**：env / 装配只给 **base**
> （`.env::MCP_MEMORY_SERVER_URL=http://127.0.0.1:8766`）——端点 = base+`/mcp`、
> 探活 = base+`/health`，两个路径是协议常量（两侧各一份字面量，测试钉住）。
> 装配点（`build.py::build_real`）**装配置前先探活**：服务不在场或 `ready=false`
> 就地抛错，与 Langfuse 同款先例——MCP 这条路上的失败是静默的。

## 三、统一约定

### 3.1 返回信封

所有 tool 返回统一 JSON 结构：

```jsonc
{
  "ok": true,                 // 工具层成败
  "code": "ok",               // 结局码，词表见 3.3
  "data": { ... },            // 各 API 载荷；失败时为现状快照
  "events": [ ... ],          // 脚本路径：裸事件流（§三.4）；原子层恒 []
  "error": null               // ok=false 时的人类可读补充
}
```

transport 级失败（JSON-RPC error）由 mcpclient 翻译成 Python 异常抛出，
与进程内实现的异常行为对齐。

### 3.2 transport 与生命周期

- **Streamable HTTP**（Windows 沙箱 stdio 有前科）；两 server 由**用户本机起跑**
  （0924 口径），启动参数给 memory_root / rom / state_file；
- world server **单实例租约**：同时只服务一个 client，第二连接 initialize 即拒
  （`occupied`）——防两模拟器并存（Event 41 红线）；
- `reset()` / `load_state()` 清空 server 内全部会话缓存（对话增量集合、事件缓冲）。

### 3.3 结局码词表（`code`）

`ok` / `rejected` / `blocked` / `off_course` / `not_converging` /
`budget_exhausted` / `battle_started` / `choice_presented` / `map_changed` /
`no_target` / `no_response` / `no_encounter` / `not_sold_here` / `not_in_bag` /
`count_limit` / `insufficient_funds` / `insufficient_stock` / `verify_failed` /
`warp_failed` / `wrong_scene` / `timeout` / `still_talking` / `perception_failed` /
`unsupported_map` / `stalled`

### 3.4 裸事件（跨两 server 的协议货币）

```jsonc
{
  "outcome": "dialog" | "warp" | "still",
  "actor_place": {"map_id": 12, "x": 13, "y": 8},   // 按键那一刻角色格
  "place":       {"map_id": 12, "x": 14, "y": 8},   // 被影响的物体格
  "object_kind": "npc",       // npc/sign/stone/tree/door/exit/grass…（tile/对象表直读）
  "button": "a",
  "text": "…",                // 仅 dialog：本框**新增**文本（§三.5）
  "map_id": 7                 // 仅 warp：进入的新图
}
```

- 无账本坐标（三章由 harness 判定层补）；
- **入流过滤**：普通移动（位移成功、未换图、面前无物体）不产生事件；
  **移动被障碍挡不产生事件**（碰撞静态可推，blocked 由 code 传达）；
  移动触发换图产生 warp（连通性入账）。

### 3.5 对话增量规则（写侧主动增量，用户定案）

- 抄屏只在画面稳定后（连续 STABLE_POLLS=6 帧一致），`text` = **本框新增文本**；
- server 为当前对话段维护"已见行集合"（reset/load_state 清空）：新稳定帧中
  不在集合内的行 = 新增 → `text` = 新增行拼接；首框全量；全帧已见 → 无事件；
- 消费方按序直接拼接 dialog 事件 = 完整对话（无需 diff）；
- 落库仍 append-only：跨次调用/跨 run 同格同事件**不去重**——归并归机制一。

### 3.6 act 账（trace，用户定案：复用 + 改名）

- act 账改名 **`act_call`**（与 brain 六链路 `*_call` 命名对齐），**不新增 kind**；
- content 按动作类型扩展：
  - key 动作：`{kind:"key", button, moved, event?}`（event = 本键裸事件或 null）；
  - script 动作：`{kind:"script", name, args, ok, code, data 摘要, events[]}`——
    脚本内部 N 键**不逐键记账**（不在 harness 视野，账本坐标只算一步）；
- **脚本内部模型调用账必须带回**：脚本期间 perceive_once 的 ModelCall 记录
  随终态报告 `calls[]` 返回，harness 按现有 `*_call` kind 逐条落账；
- node_io：STEP 模板 / source 表随 `act_call` 改名同步；META_KEYS 三章不变。

## 四、memory server（能力面：`recall` + `memorize`，注册表暴露）

> **用户定案（2026-09-29）**：一口气全改，不留旧 query_*/store_*；MCP 注册表
> 对外暴露的是**能力**（`recall` / `memorize`），不是存储原语（put/get/filter…
> 这 11 条降级为 memory 包内部接口，不再是对外 Port）。

### 4.1 MemoryToolPort 收敛为两方法

```python
class MemoryToolPort(Protocol):
    def recall(self, req: RecallReq) -> RecallResp:
        """统一回忆口：不指定记忆种类，分族检索后融合排序。
        conditions 只放上下文 hint（episode_id / map_id / place…），不放 kind。"""
    def memorize(self, req: MemorizeReq) -> MemorizeResp:
        """统一记忆口：写侧一个口，records 按 kind 判别落族。"""
```

- `RecallReq = {query, conditions?, limit}`；
- `RecallResp = {items: [{kind, uuid, score, content, payload}]}`——每条自带身份，
  content 为渲染好的可读文本（感知束组装 / 未来模型直接可用）；
- `MemorizeReq = {records: [MemoryRecord]}`——判别联合（act / task / episode /
  knowledge / object），复用现有 schemas；种类由产生方天然决定（判定层产
  object 事件、蒸馏产 summary），调用方不猜；
- 原 `query_*` / `store_*` 15+ 方法**全删**；判定层的精确查询
  （如"这一格发生过什么"）走 `recall(conditions={map_id, x, y})` 圈定。

### 4.2 注册表（MCP 向外暴露能力）

- server 启动时 FastMCP 登记两个 tool：**`recall` / `memorize`**——docstring 即
  模型说明书；
- `tools/list` 对外暴露这两个能力，任何 MCP 客户端（agentic memory / 前端
  人格 agent / WorkBuddy）可发现并调用；
- 运维能力（snapshot / restore / count / refresh_changed）**不进 MCP 面**——
  留 server 启动参数与本地管理命令。

### 4.3 分族逻辑落点（一份实现，两模式共用）

- `recall` / `memorize` 的实现住 **memory 包**（`memory/recall.py`）：
  进程内模式 MemoryTool 直调、MCP 模式由 server 调——一份代码两处用；
- **recall 分族规则（机械）**：
  - `conditions.episode_id` → act / task 圈本局（step 升序）；
  - `conditions.place / map_id` → object 圈格；
  - `query` 语义检索 → episode / knowledge（BM25+向量+融合，现有管线）；
  - 融合：hint 命中族优先，族内按相关性——机械可解释；
- **memorize 分发规则**：按 kind 判别落族——act/task/episode 落族+索引、
  knowledge 判重（topic+正文逐字相同跳过）、object 追加（step 单调前置校验）。

### 4.4 波及面（大改，独立 CHANGELOG 条目）

- MemoryTool 全部消费点改造：感知束组装（三处查询 → 一个 recall）、act 后写
  （store_act_memory → memorize）、蒸馏落库（store_* → memorize）、判定层
  精确查询（query_object_events_at → recall conditions）；
- `MemoryStorePort` 降级为 memory 包内部接口（`memory/ports.py` 重构）；
- memory 相关测试全改。

**并发**：单写者约定（同刻一个 client 有写权），冲突后再议文件锁。

## 五、world server——原子层（7 条）

| # | tool | 入参 | data | 契约要点 |
|---|---|---|---|---|
| 1 | `reset` | task_id, goal, success_criteria, max_steps, initial_state_hint? | null | 载 task 存档；max_steps>0；不感知；清会话缓存 |
| 2 | `get_action_space` | — | `{mask:{name:bool}, entries:[{kind,name,params?,desc?}], scene}` | **统一能力掩码**（用户定案）：原子键与脚本**等价**——同一 `name→enabled` 命名空间，LLM 同权选择；`entries` 带各条目载荷（脚本带 params/desc）。吸收并替代原 all_actions / 宏签名表（删） |
| 3 | `perceive_task` | — | `{scene, screen\|walk_map, pos}` | 只读内存与屏幕缓冲；不失败不重试 |
| 4 | `perceive_once` | — | Perceived JSON | 调一次视觉模型不重试；失败 → `perception_failed`；ModelCall 记录随 Perceived 交调用方 |
| 5 | `step` | segments:[[key,times],…], settle:bool | `{moved:bool, event:裸事件\|null}` | **唯一按键执行口**；每段键断言在动作空间；响应带本键裸事件——判定前移 server 的输出点 |
| 6 | `save_state` | — | state_base64 | 全量导出逐字节，不 tick |
| 7 | `load_state` | state_base64 | null | 原样恢复不 tick；清会话缓存 |

**契约变更**（Port 层，过 CHANGELOG 编号条目）：mask/scripts 计算上移 world
（原 GameToolPort.get_action_space 职责迁入）；`all_actions` 删除；`step`
返回值 None → 结局结构。

## 六、world server——ScriptRun 骨架（server 进程内）

### 6.0 动作空间获取与选择链路（task 层决策圈）

```
① perceive_task（mcpclient→server）→ TaskObservation（scene/screen/pos）
② get_action_space（mcpclient→server）→ {mask, entries, scene}
   统一能力掩码：原子键与脚本等价（name→enabled），LLM 同权选择
   两次调用间无 step（server 同步单 client），帧不变，无竞态
   **description 由 server 产出**（entries 自带，mcpclient 纯转发）：
   键 = 按键语义；脚本 = 名字/参数/适用场合；
   **shop 类脚本条目附在售摘要**（如 `buy_item(item, count)——本店在售:
   POKé BALL/ANTIDOTE/PARLYZ HEAL/BURN HEAL`）——Gen1 各店清单 ROM 硬编码
   恒定不变，写进 desc 省一次目录预查；item 名/价格的逐字真源是
   `shop_layouts.goods` 表，buy/sell 执行校验直查表（无目录 API）
③ chooser prompt（direct 层组装）：观测 + 全条目动作描述（直接读 entries.description）
④ 模型输出一个动作名（+ 脚本时带 args）→ 断言：名字 ∈ 掩码且 enabled
   → 非法 = ParseFailure → trace 错误账 → 重试（现有机制）
⑤ execute：按名字归属分流——key → step（响应带 event）；
   script → 脚本 API（报告+events+calls）
⑥ judge（判据只认达成）→ 下一决策圈
```

### 6.1 trace 记账

- act 账改名 **`act_call`**（复用，不新增 kind），content 按动作类型扩展
  （key / script 两形，见 §3.6）；
- 脚本内部模型调用随 `calls[]` 带回落账；
- node_io：STEP 模板 / source 表随改名同步；META_KEYS 三章不变。

### 6.2 骨架

脚本 = 同一个 ScriptRun + 前置校验 + 业务步骤 + 成功谓词。稳定等待、中断、初态恢复、
失败恢复与收尾由各脚本的 ScriptPolicy 或步骤声明；不存在第二类执行器。
私有帧预算集中在 scripts/timing.py（POLL_FRAMES / STABLE_POLLS /
STEP_TIMEOUT_FRAMES=900 / NAV_LIMIT=120 / QUIET_PRESS_FRAMES / ARROW_WINDOW）。

```
ScriptRun 持有：预算（steps/帧）；events[]；对话增量缓存（已见行集合）
地图操作脚本显式选择 field_policy，按键后核以下三种中断：
  ① scene 变 BATTLE    → BattleStarted（bounce 捕获为正常终止，其余终止）
  ② 屏幕出现选项框      → ChoicePresented（冻结；选项文本进返回 choice；绝不代选）
  ③ map_id 变化        → MapChanged（exit_map 捕获为成功；其余终止 map_changed）
放弃动作：预算耗尽 / 钩子触发 / blocked → 停止按键 → 冻结现场 →
          {ok:false, code, data:现状快照(pos/scene/screen_text), events[]}
原则：脚本只做确定性的事；分叉停并上报，决策权回调用方。
```

菜单脚本声明 menu_policy：严格稳定等待、准备时恢复初态、失败时恢复，成功收尾可选。
开始菜单导航与回血确认同样使用 ScriptRun，但显式不启用选项中断；目标菜单或 YES 已由
脚本目的给定。执行器不根据脚本所在目录自动决定这些规则。

## 七、world server——脚本层（15 条，一脚本一 API）

接管场合的多步操作也是脚本（接管脚本，`scripts/takeover/`，对外名带场合前缀），与常规脚本同一种动作；
进程内经 `GameTools.execute` 执行，MCP 面暂未注册（WorldMcpTool 就地报错）。泛型 run_script 废。
成功谓词机械可判；终态报告统一带 `events[]` 与现状快照。

### 7.1 商店类（多地图：按当前 map_id 查 tables，白名单外 → `unsupported_map`）

**`buy_item(item, count)`** → `{spent, remaining_money, stock}`
① 前置同上 → ② 读 money0/stock0/在售表（单价以表为准）→
③ 不在售 → `not_sold_here` →
④ count>99 → `count_limit`；count×price>money0 → `insufficient_funds` →
⑤ `console.run_script("shop_buy")`（内部接管脚本）：光标选中（NAV_LIMIT）→ 数量框调 count → 确认框**机械代答
"是"**（机械确认非分叉）→ 等购买文本稳定 → 退出菜单 →
⑥ 终态校验 money0−money1==price×count 且 stock 增量==count → `verify_failed` 兜底。

**`sell_item(item, count)`** → `{earned, remaining_money, stock}`
① 前置同上 → ② 读 money0/stock0 → `not_in_bag` / count>stock0 →
`insufficient_stock` → ③ `console.run_script("shop_sell")`：开背包 → 选中 → "卖出" →
调数量 → 确认 → ④ 校验 money 增量==实际卖价×count → `verify_failed` 兜底。

### 7.2 移动 / 导航类

**`circle_walk(laps, extent?=1)`** → `{laps_done, final_pos}`
每轮四段（右×d/下×d/左×d/上×d），每步断言位移=1、圈末回起点。
失败：位移 0 → `off_course`；battle → 钩子。

**`walk_to_adjacent(direction)`** → `{final_pos, entered_grass}`
单步 step → 到位=成功；没动=`blocked`（一步即判）。

**`walk_to(x, y, max_steps?=200)`** → `{final_pos, steps_used}`
固定轴序选缩短曼哈顿距离的方向 → 位移失败换另一轴试一次 → 仍失败 `blocked` →
每 5 步校验距离收敛，不收敛 `not_converging`。不做 BFS（绕行决策交调用方）。

**`face_direction(direction)`** → `{moved, facing}`
游戏物理：前方可走即真移动。已面向 no-op；否则 step 一次，moved 如实报。

**`exit_map(target_warp?=-1)`** → `{dir, to_map}`
查 `tables.warps[map_id]` 全部出口（门 warp 优先，带坐标先内联 walk_to 到门口；
边缘出口只有方向）→ 朝触发方向反复走 → MapChanged 钩子 → `to_map`。
按键不换图 → `warp_failed`（静态表过期——修 tables，不是脚本兜底）；
map 不在白名单 → `unsupported_map`；`target_warp` 越界 → `rejected`。

**`bounce_in_tall_grass(steps?=30)`** → `{steps_used, encounter:bool}`
前置当前格草丛 tile，否则 `rejected` → 双方向来回走 → 进战斗 →
`ok:true, battle_started`（撞怪即目的）；steps 用完 → `no_encounter`（合法）。

### 7.3 交互类

**`talk_to_adjacent_npc(direction?=当前朝向)`** → `{dialog:[增量片段], choice?, final_screen_text}`
① 读对象表确认面前格 NPC（会走，按键瞬间复验 → `no_target`）→
② step(direction)：位移了 → `no_target` → ③ 按 a → 等对话框（不出 →
`no_response`）→ ④ 循环抄稳定帧（增量规则）→ 按 a → 直至回野外 →
⑤ ChoicePresented 冻结；训练家型 → `battle_started` + dialog。

**`interact_facing()`** → `{dialog, final_screen_text}`
按 a 一次看反应：进对话框 → `ok`（dialog + 终帧）；仍野外 → `ok:false,
no_response`（确认无反应是合法结果）；其它场合（choice/battle 等钩子已拦）照实上报。

**`advance_dialog(max_presses?=30)`** → `{presses, dialog, final_screen_text}`
循环按 a（骨架钩子路径）→ 回野外（无对话文字无光标）→ `ok`；
中途出选项框 → `choice_presented`（冻结，绝不代选）；预算耗尽 → `still_talking`。

### 7.4 菜单 / 系统类

**`open_menu_to(target)`** → `{scene, cursor}`
非 start_menu 先按 start 进菜单（仍不是 → `wrong_scene`）→ 读当前光标
（`ScreenText.cursor` ∈ START_ORDER）算相对位移移过去 → 按 a 选中 →
校验 scene（POKéMON→party / ITEM→bag 有预期，其余只要求离开主菜单）；
不符 → `wrong_scene`；非法 target → `rejected`。
选项框常驻光标 → raw 按键绕钩子（与 heal 的 YES 确认同理）。

**`heal_at_center(max_steps?=60)`** → `{healed, party_size}`
当前 map 在 `tables.pokecenter_layouts` 白名单（否则 `unsupported_map`）→
内联 walk_to 到站位 → 面朝护士 → 按 a 触发对话 → 遇"是否回血"YES/NO
选项**机械确认 YES**（raw 按键绕 choice 钩子——固定流程确认非分叉）→
推进对话回野外 → 读队伍 RAM（`readout.read_party`）校验全满，
未满 → `verify_failed`；对话推不完 → `still_talking`。

**`wait_until_scene(scene, timeout_s)`** → `{waited_frames, scene}`
无输入 tick 循环每 POLL_FRAMES 读 scene；超时 → `timeout` + 当前 scene。

**`get_action_desc_with_mask(mask)`** —— mcpclient 侧本地辅助（不是 server API）：
掩码条目 → 模型可读动作描述。

## 八、tables/ 新增静态数据

| 表 | 内容 | 先行范围 |
|---|---|---|
| `warps[map_id]` | 出口格坐标 + 触发方式（踩上/按方向）+ 通往图 | map 12 |
| `shop_layouts[map_id]` | 在售表（item/price）+ 柜台坐标 | 已知商店图 |
| `pokecenter_layouts[map_id]` | 柜台/护士坐标 | 已知中心图 |

来源：ROM 静态提取优先，提不出先手工。表与实际不符以 `warp_failed` 等可观测
信号暴露——表是数据，修表不是脚本兜底。

## 九、mcpclient 契约

- `mcpclient/memory_tool.py`：实现 `MemoryToolPort`（收敛后两方法 `recall` /
  `memorize`，信封面，harness 消费不变）——薄转发至 server 对应 tool；
  分族/融合/判重逻辑在 server（`memory/recall.py` 的一份实现两模式共用）；
- `mcpclient/world_tool.py`：实现 `GameToolPort`（信封面）——原 GameTools 的
  信封翻译随迁，world 调用换 MCP 转发（脚本动作入口也在此）；
- **不持账本坐标**：三章由 harness 判定层补——mcpclient 持有的是
  "信封↔裸面"翻译与转发，不是账本行为；
- **进程内模式**（server_url 缺省）：mcpclient 内部直调 `memory/recall.py`
  / 进程内 world，行为与现状语义一致——**门面唯一，传输切换**。

## 十、验证（全部 pytest，无测评体系）

1. **端到端对比**（memory 先行）：起 server（in-memory transport）→ client 调
   `recall` / `memorize` → 与进程内实现（`memory/recall.py` 直调 store）同输入
   逐字段比对：分族分流规则（episode_id 圈本局 / place 圈格 / query 语义）、
   融合排序、memorize 各 kind 落族与判重、choice/注册表暴露清单。
2. **world 原子层**：FakeWorld 单测（pytest）覆盖 7 方法——重点 step 的 event
   产出规则（入流过滤三例）；真机行为由用户手跑核对（人工冒烟清单，非测试体系）。
3. **脚本单测**：每脚本按 PLAN 附录 A 矩阵（FakeConsole）——成功谓词、预算耗尽、
   钩子触发逐条钉死。
4. **事件流对齐**：脚本批量 events 与逐键 step 事件拼起来的流逐字段一致；
   增量规则三条例子（§3.5）作为钉子测试；入流过滤三例复验。
5. **契约核对**：server/mcpclient 对四个模块的 import 清零核对
   （同 world SPEC §八手法）；MemoryToolPort 收敛后全仓调用点清零核对。

除上述 pytest 外无任何自动化测评；真机验收仅为人工冒烟核对清单。

## 十一、待定向（开工前确认）

1. ✅ 层名定案：`direct/`（brain/trace 直调）+ `mcpclient/`（memory/world 门面+client）；
2. WorldPort / MemoryToolPort 契约变更清单（§五契约变更段、act_call 改名）——
   CHANGELOG 编号条目拆分；
3. tables 三张表的图覆盖范围（map 12 先行）；
4. 脚本第一批实现顺序（建议：walk_to_adjacent → walk_to → circle_walk →
   talk_to_adjacent_npc → bounce_in_tall_grass → buy_item/sell_item）；
5. 长脚本阻塞：先同步到底，撞上再加进度轮询 API。

## 十二、全项目文本同步

见 `docs/PLAN_mcp_servers.md` P7 清单：AGENTS.md / spec/tools/SPEC（重写拆分）/
OVERVIEW / README / CLAUDE / spec/{memory,world,trace,harness,schemas}/SPEC /
TRACE_37_accounts_examples / 73 个 `.py` docstring。历史文档冻结
（checkpoint/eval/experiences/perceive/web_reviewer/HANDOFF）。同步跟码走：
每个 Phase 动到的文件同步改其 docstring，P7 收口全局。
