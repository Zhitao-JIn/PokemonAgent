# spec —— 批 ②a：补齐 `WorldMcpTool` 相对 `GameTools` 缺的三样

> 流程位置：intent（`docs/mcp/mcp-only-intent.md`）→ 批 ① 已完成 → **批 ②a（本文，v1）** → 批 ②b（删进程内 world）→ 批 ③（评测走 MCP）
> 分支：`refactor/mcp-only`，基线 `8ec7353`（含批 ①），`state_schema_hash = 4f1cac6fcc7216d5`（本批不应改变它）。
> 性质：**行为修复**。MCP 模式是实际使用的路径，它与进程内 `GameTools` 有三处不一致；删进程内路径前必须先补齐，否则那三样行为会随进程内路径一起消失。

---

## 一、事实（读码核对，基线 `8ec7353`）

| # | 进程内 `GameTools` | MCP `WorldMcpTool` | 后果（MCP 模式） |
|---|---|---|---|
| 1 | `execute` 键动作返回 `resp.event`（`observe_step` 的本键裸事件） | server 的 `step` 返回 `{moved, event}`，但 `execute` 没读，返回空 resp | `harness/task/act/act.py` 的 `last_event` 恒为 `None`，`store_object_semantic_memory` 不写按键触发的 object 记忆 |
| 2 | `get_action_space` 在 world 掩码上补 `descriptions`（按键说明）、`note`（连按用法）、`map_note`（地图规则，脚本接管场合为空） | 原样验回 server 的 `ActionSpace`，不补 | `direct/prompts/decide_action.py` 的"可用动作"里每个键是"（无说明）"，缺连按用法与地图规则两段 |
| 3 | `execute` 前置断言：脚本名在本帧空间里且可用；键为单键且在掩码里 | 只断言单键，不校验掩码与脚本名 | 大脑幻觉出的键或脚本会变成语义不明的 server 侧错误 |

补文案与事件是**恢复设计本来的行为**（用户已认可）。

## 二、决定表

**D1 提取提示文案补充为独立纯函数。** 把 `game_tools.py::_action_space` 拆成两步，放新模块 `pokemon_agent/mcpclient/action_space.py`：
- `with_prompt_text(space: ActionSpace, obs: TaskObservation) -> ActionSpace`：在已有的 `ActionSpace` 上补 `descriptions` / `note` / `map_note`，规则与现 `_action_space` 的后半段**逐字相同**（`space.names` 为空则原样返回；`overlay` 取 `obs.facts.overlay or Facts.Overlay.NONE`；`map_note` 在 `obs.covered_by_script` 时为空串）。
- `action_space_for(obs, all_actions) -> ActionSpace`：`with_prompt_text(compute_action_space(obs, all_actions), obs)`。
- `GameTools` 的 `get_action_space` / `execute` 改为调这两个函数（行为不变）；原 `_action_space` 删除，`tests/mcpclient/game_tools/test_game_tools_action_space.py` 改 import 并随批 ②b 一起处理（本批只保它绿）。

**D2 `WorldMcpTool.get_action_space`**：仍由 server 算掩码（server 的那一份是真相），客户端验回后调 `with_prompt_text(space, req.observation)` 补文案。`req.observation` 的角色从"一致性前提"变为也供文案补充，文档注释同步。

**D3 `WorldMcpTool.execute` 的前置校验**：与 `GameTools.execute` 对齐——用 `action_space_for(req.observation, list(ALL_BUTTONS))` 在**本地**算一份掩码做断言（不多发一次 MCP 往返）：脚本动作断言脚本名在空间的条目里且 `enabled`；键动作断言单键且 `space.contains(name)`。断言文案与 `GameTools` 一致。
- `ALL_BUTTONS` 现在定义在 `world/pyboy_world.py`。若 import 它会拖入 `pyboy`，则允许把该常量移到 `world/action_space.py`（无 pyboy 依赖）并由 `pyboy_world.py` 从那里 import；这是本批对 `world/` 唯一允许的改动。不拖入则不动 `world/`。
- 本地掩码是为了前置校验；与 server 那份在同一帧同一观测下必然相同（server 同步单 client，见现有注释）。

**D4 `WorldMcpTool.execute` 的事件**：键动作读 `body["data"]["event"]` 放进 `resp.event`（缺键或 `null` → `None`）；脚本动作不变（事件在 `report["events"]`）。

**D5 缓存规则（用户要求）。** 补进的文案全部来自既有常量 `BUTTON_HELP` / `MAP_HINT` / `REPEAT_HINT`，**只依赖 overlay 与 `covered_by_script`，不含任何每帧变化的数据**，所以渲染结果与进程内路径逐字节一致；`decide_action.py` 里"静态说明在前、动态数据在后"的模板顺序不动（本批不改任何 prompt 文件）。由测试钉住（见第三节），不靠说明。

**D6 不动的东西。** `world_server.py` 不改（它已经返回 `{moved, event}` 与完整 `ActionSpace`）；prompt 模板与渲染（`direct/prompts/`）不改；`GameTools` 的进程内路径本批**保留**（批 ②b 才删）；`build.py` 不改。

## 三、测试

**新增 / 调整**（放 `tests/mcpclient/world_tool/`，用该目录现有的 in-memory 传输 + `_FakeWorld`，不起端口、不起模拟器；`_FakeWorld.step` 需要能让 `observe_step` 产生事件，或用 monkeypatch 让 server 的 `step` 返回确定的事件，由执行方选更简单的）：

- `test_execute_returns_the_event_the_server_judged`：server 的 `step` 返回非空 `event` → `resp.event` 等于它；返回 `null` → `resp.event is None`。
- `test_get_action_space_adds_prompt_text_like_the_in_process_path`：对 `TaskScene` 与 `Facts.Overlay` 的组合（至少 WALK×{NONE, CHOICE}、PARTY×NONE、一个 `covered_by_script` 场合），`WorldMcpTool.get_action_space(...)` 的 `model_dump()` 与 `action_space_for(obs, ALL_BUTTONS)` 逐项相等（含 `descriptions` / `note` / `map_note`）。**这条同时是缓存规则的守卫**：两条路径渲染出的 prompt 一致。
- `test_prompt_text_is_deterministic_and_frame_independent`：同一 overlay 下，换不同坐标 / 不同 `step` 的观测，补出的 `descriptions` / `note` / `map_note` 不变（确认没有每帧变化的内容）。
- `test_execute_rejects_a_key_outside_the_mask` / `test_execute_rejects_a_script_outside_the_space`：断言文案与进程内一致；断言在发出 MCP 调用**之前**触发（用记录调用的 client 确认零调用）。
- `tests/mcpclient/game_tools/test_game_tools_action_space.py`：改 import 为 `pokemon_agent.mcpclient.action_space`，用例内容不变。

**既有测试**：`test_mcp_world_tool.py` 里现有的 `test_execute_sends_one_key_and_reports_moved`、`test_get_action_space_revalidates_the_server_mask` 等不得删；若因 D3 的前置校验失败（它们的观测是否在掩码内），调整测试数据而不是放松断言。

## 四、允许改动的文件

生产：`pokemon_agent/mcpclient/action_space.py`（新）、`pokemon_agent/mcpclient/game_tools.py`、`pokemon_agent/mcpclient/world_tool.py`；仅在 D3 条件满足时 `pokemon_agent/world/pyboy_world.py` 与 `pokemon_agent/world/action_space.py`。
测试：`tests/mcpclient/world_tool/`、`tests/mcpclient/game_tools/test_game_tools_action_space.py`，及新增用例所在文件。
文档：`docs/spec/tools/SPEC.md`、`docs/spec/mcp/SPEC.md` 里描述 `WorldMcpTool` 的相应句子；`CHANGELOG.md`（四段，+10 行左右，编号由设计侧在派发时给）。
其他一律不动。

## 五、验证

- 全量 `pytest`、`ruff check .`、`ruff format --check .` 全绿。
- 汇报实测 `state_schema_hash`，应为 `4f1cac6fcc7216d5`。
- 破坏验证：把 `WorldMcpTool.get_action_space` 里的 `with_prompt_text` 调用临时去掉，对照测试必须失败；把 `execute` 里读 `event` 的一行去掉，事件测试必须失败；恢复后转绿。
- 汇报：补文案前后，用 `decide_action.build_prompt` 渲染同一份观测（用测试里的假观测），MCP 路径与进程内路径输出的 prompt 全文是否一致（应一致）。

## 六、停止条件

- 需要改 `world_server.py`、任何 prompt 文件、`build.py` 或第四节之外的文件。
- `with_prompt_text` 无法做到与现 `_action_space` 后半段逐字相同。
- `ALL_BUTTONS` 的位置迫使你改 `world/` 里不止那一个常量的移动。
- 事件测试在不改 `observe_step` 的前提下无法构造。
- 发现补进文案后进程内路径的现有测试输出变化（说明拆分改变了行为）。

## 七、非目标

删除进程内 `GameTools` 路径、`build.py` 的 world 回退、评测脚本（批 ②b / ③）；`evolve`；`WorldMcpTool` 的租约逻辑；改 prompt 内容或位置。

## 八、待用户确认

- **Q1** 把"提示文案补充"提取成独立模块 `mcpclient/action_space.py`（`GameTools` 与 `WorldMcpTool` 共用，批 ②b 后只剩 `WorldMcpTool` 用），可以吗？
- **Q2** 前置校验在客户端本地算掩码（不多一次 MCP 往返），可以吗？
