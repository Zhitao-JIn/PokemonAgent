# spec —— `tests/mcp_servers/`：连接性单元测试（mcp 线）

> 依据：`docs/test/mcp-servers-test-intent.md`（已确认）。源码：`pokemon_agent/mcp_servers/`。
> 检查点：CP1（编号 500，派发时登记）。本线只有这一个检查点：mcp 线不迁入、不删除任何用例，世界逻辑迁移归 world 线。

## 一、决定表

| 编号 | 决定 | 理由与代价 |
|---|---|---|
| D1 | mcp 测试只证明连接性：服务端能起、工具注册正确、调用能到后端并原样返回、传输错误映射 | intent 第一节；世界语义归 world 线 |
| D2 | 世界逻辑用例**原地保留**，只在 docstring 标注「待迁 world 线」，不删除 | intent 第六节；删了就丢覆盖。代价：目录里仍有待迁用例，直到 world 线 |
| D3 | 租约协议（第一个客户端拿到、第二个被拒、只有持有者能释放、只读工具不占锁）**留 mcp** | 多客户端的会话管理属于服务端连接层（你已确认） |
| D4 | `test_state_roundtrip_is_base64` **留 mcp** | base64 是线上编码，属于传输（你已确认） |
| D5 | `test_read_wram_preserves_bytes_and_lease` 拆成两个：租约/未驱动世界部分留 mcp；字节内容部分待迁 world | intent 第五节（你已确认） |
| D6 | 删除 `test_client_roundtrip_over_mcp_transport` 中的无效断言 `assert McpClient is not None` 及其 import | 该断言不验证任何行为，只为躲未使用告警 |
| D7 | `test_load_env_file_*`（health 文件中 3 条）**不在本线**，原样保留，登记遗留 | 配置读取不属于 mcp 连接性；归属另定 |
| D8 | `tests/mcp_servers/test_mcp_memory_e2e.py` 不动 | 归 memory 线（intent 第三节） |

## 二、已知观察（不改，记遗留）

- **K1**：多处测试直接读写 `world_server._lease_owner` 与 `world_server.start` 的模块级状态（夹具里 `world_server._lease_owner = None`）。这是已存在的私有访问，本线不新增，也不修；它是 mcp 服务端用模块级单例的结果，改动属于生产代码设计，另案。
- **K2**：`test_mcp_script_tools.py` 的 `_call` 辅助与 `test_mcp_world_server.py` 里的同类调用逻辑重复。不合并（两文件独立，合并会引入跨文件依赖）。
- **K3**：`pytest` 在本环境下汇总行不渲染（与用例无关，见 memory 线 CP1 汇报）；计数以 junit 为准。

## 三、用例清单（逐条；行号以起点文件为准，执行方核对）

**保留（连接性）**

`tests/mcp_servers/test_mcp_health.py`（健康路由、探针）：
1. `test_url_shape_composes_from_base_without_doubling_slashes`（94）
2. `test_health_path_constants_agree_across_server_and_client`（101）
3. `test_health_route_reports_ready_only_after_capability_injection`（111）
4. `test_health_is_not_a_mcp_tool`（141）
5. `test_probe_passes_when_server_is_ready`（163）
6. `test_probe_rejects_unhealthy_server`（187）
7. `test_probe_reports_unreachable_server`（198）
8. `test_probe_rejects_empty_base_url`（210）

`tests/mcp_servers/test_mcp_world_server.py`（租约、健康、注册表、传输、reset 的租约）：
9. `test_first_client_takes_the_lease_and_the_second_is_rejected`（134）
10. `test_read_only_tools_do_not_take_the_lease`（144）
11. `test_only_the_holder_can_release_the_lease`（154）
12. `test_health_reports_ready_and_lease_holder`（165）
13. `test_registry_lists_the_atomic_layer`（180）
14. `test_client_roundtrip_over_mcp_transport`（247）——删除 `McpClient` 无效断言，见 D6
15. `test_reset_with_start_state_still_checks_lease_before_world`（282）
16. `test_state_roundtrip_is_base64`（122）——D4
17. `test_read_wram_keeps_lease_owner_unchanged`（294 拆出，参数化 None / c1，断言租约不变且世界未被驱动）——D5

`tests/mcp_servers/test_mcp_script_tools.py`（脚本注册与租约）：
18. `test_script_tool_registered`（51）
19. `test_script_tool_takes_lease`（108）
20. `test_release_lease_allows_next_client`（117）

`tests/mcp_servers/test_world_server_cli_options.py`：
21. `test_world_server_cli_passes_watch_and_speed_to_the_world`（16）——CLI 参数传到 world，连接层

`tests/mcp_servers/test_mcp_health.py` 的环境读取（**不动**，D7）：
- `test_load_env_file_reads_keys_and_never_overrides_real_env`（54）
- `test_env_empty_value_counts_as_unset`（79）
- `test_load_env_file_missing_is_a_noop`（86）

**待迁 world 线（原地保留，docstring 标注，不删）**

`tests/mcp_servers/test_mcp_world_server.py`：
- `test_step_is_the_only_key_execution_gate_and_reports_moved`（86）
- `test_step_reports_not_moved_when_the_world_did_not_move`（96）
- `test_get_action_space_exposes_one_flat_namespace`（103）
- `test_perceive_task_returns_the_memory_scene`（115）
- `test_reset_passes_start_state_only_when_supplied`（268）
- `test_read_wram_returns_the_world_bytes_base64`（294 拆出，字节内容部分；新名字，见 D5）

`tests/mcp_servers/test_mcp_script_tools.py`：
- `test_walk_to_adjacent_forwarding`（83）
- `test_walk_to_adjacent_blocked_envelope`（92）
- `test_buy_item_end_to_end`（99）

**本 CP 不触碰、登记在案**（位于 `tests/mcpclient/world_tool/`，不在本目录）：
- `test_mcp_world_tool.py`：`test_execute_sends_one_key_and_reports_moved`、`test_get_action_space_revalidates_the_server_mask`、`test_perceive_task_returns_the_memory_scene`、`test_state_files_round_trip_on_the_client_side`、`test_evolve_remains_explicitly_unsupported`、`test_shop_quit_returns_its_report_over_real_mcp_transport`、`test_shop_quit_rejects_wrong_scene_with_a_named_report`
- `test_world_mcp_script_e2e.py`：`test_world_mcp_tool_executes_script_over_mcp`

## 四、CP1（500）改动清单

允许改动的文件（仅此）：
1. `tests/mcp_servers/test_mcp_world_server.py`：
   - 删除 `test_client_roundtrip_over_mcp_transport` 中的 `assert McpClient is not None` 行，并删除 `from pokemon_agent.mcpclient import McpClient` 这一行（若它仅此处使用）；
   - 把 `test_read_wram_preserves_bytes_and_lease` 拆成两个：`test_read_wram_keeps_lease_owner_unchanged`（参数化 None / c1，只断言 ok、租约不变、世界未被驱动）与 `test_read_wram_returns_the_world_bytes_base64`（只断言字节内容，docstring 标「待迁 world 线」）；
   - 给待迁用例（第三节「待迁 world 线」列出的 6 条）的 docstring 第一行加前缀「【待迁 world 线】」，其余 docstring 不变。
2. `tests/mcp_servers/test_mcp_script_tools.py`：给 `test_walk_to_adjacent_forwarding`、`test_walk_to_adjacent_blocked_envelope`、`test_buy_item_end_to_end` 的 docstring 第一行加同样前缀。
3. `tests/mcp_servers/test_mcp_health.py`：文件 docstring 第一行后加一句「本文件的环境读取用例（3 条）不属于连接性，归属待定，见 spec D7」——只改 docstring。
4. `CHANGELOG.md`：顶部追加一条，编号 500。

**用例数变化**：`test_read_wram_preserves_bytes_and_lease`（参数化 2 例）→ 拆为 `keeps_lease_owner_unchanged`（参数化 2 例）+ `returns_the_world_bytes_base64`（1 例）。`tests/mcp_servers/` 总数 **+1**。其余用例数不变。执行方用 junit 实测，与此核对。

## 五、验证

- 起点与终点：`tests/mcp_servers/` 默认 pytest 全部通过；junit 的 `failures=0, errors=0, skipped=0`。
- 目录耗时：`tests/mcp_servers/` 默认 pytest 下 **≤ 3 秒**（用 `--durations=10` 记录最慢三例）。超出 → 停下汇报，不自行改。
- 迁移前后用例名集合：除 `test_read_wram_preserves_bytes_and_lease` 被拆成两个新名字外，其余名字完全一致。
- 破坏验证：临时把 `world_server` 里 `read_wram` 的租约检查改成抢锁（或删掉 `release_lease` 的持有者判断），应有相应租约用例失败；还原后 `git diff` 对 `pokemon_agent/` 为空。
- 全仓三项检查：全量 pytest（junit 计数）、`ruff check .`、`ruff format --check .` 全绿。

## 六、停止条件

- 拆分 read_wram 后，任一租约用例在修复前后结果不一致 → 停，汇报；
- 目录耗时 > 3 秒 → 停，汇报；
- 发现某条「保留」用例实际依赖世界逻辑（断言了按键语义、场景内容等）→ 停，汇报，不自行迁移或删除；
- 发现需要修改 `pokemon_agent/` 才能通过的情况 → 停，汇报。

## 七、非目标

- 不迁移任何用例到 `tests/world/`（world 线）；
- 不删除任何世界逻辑用例；
- 不修 K1 的私有访问（另案）；
- 不测 `mcpclient/` 的客户端装配（另案）；
- 不测 memory 相关 MCP 用例（memory 线）。
