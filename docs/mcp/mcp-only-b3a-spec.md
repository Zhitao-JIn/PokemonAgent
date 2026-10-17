# spec —— 批 ③a：world server 增加「reset 接受起点」与「读 WRAM」两个口

> 流程位置：批 ①、②a 已合入主工作区 → 批 ②b 已提交（`8ec5c13`，未合）→ **批 ③a（本文，v1）** → 批 ③b（评测脚本改走 MCP）→ ②b+③a+③b 一起合入。
> 分支：`refactor/mcp-only`，基线 `8ec5c13`，`state_schema_hash = 4f1cac6fcc7216d5`（本批不应改变它）。
> 性质：**能力补齐（生产代码）**。批 ③b 把评测改走 MCP，需要 world server 多两个口；本批只加这两个口及其客户端入口，不动评测。

---

## 一、事实（读码核对，基线 `8ec5c13`）

1. `PyBoyWorld.reset()` 的起点只有两种：构造时给的 `state_path`（读文件、`tick(1)`），或不给（`tick(BOOT_FRAMES)` 从开机起）。server 的 `reset` tool 与 `WorldPort.reset` 都没有"本次 reset 用哪份起点"的参数。
2. 打包（`evals/.../pack.py`）要让每条样本从**自己的** `.state` 起跑；harness 每局开头调 `reset`，会把 server 启动时的 `--state-file` 重载回来，事后 `load_state` 会被盖掉。
3. 冻结工具（`freeze.py`、`terrain.py`）读整块 WRAM `0xC000–0xDFFF`（8192 字节）：现在靠 `world._pyboy.memory`。MCP 面没有对应的口。
4. world server 的 tool 全部住在 `pokemon_agent/mcp_servers/world_server.py`；变更类 tool 走 `_take_lease(client_id)`；只读类（`get_action_space` / `perceive_task` / `save_state`）不带 `client_id`。
5. `PyBoyWorld` 没有单元测试（需要 ROM）；`tests/mcp_servers/test_mcp_world_server.py` 与 `tests/mcpclient/world_tool/conftest.py` 里各有一个假 world（`reset(**kwargs)`）。

## 二、决定表

**D1 `WorldPort.reset` 增加可选起点。** 签名末尾加关键字参数 `start_state: bytes | None = None`。语义：给了 → 本次 reset 用这份字节恢复模拟器（不读 `state_path`、不走开机）；不给 → 行为与现在完全相同。docstring 写清这一条与前置条件（给了则非空）。

**D2 `PyBoyWorld.reset` 实现。** `start_state` 非 None 时：断言非空，`self._pyboy.load_state(io.BytesIO(start_state))`，然后 `self._tick(1)`（与 `state_path` 分支一致）。优先级：`start_state` > `state_path` > 开机。其余不动。

**D3 server `reset` tool 增加 `state_base64: str | None = None`。** 放在 `initial_state_hint` 之后、`client_id` 之前。非 None → `base64.b64decode` 后作为 `start_state` 传给 `_w().reset(...)`；None → 不传。租约规则不变（仍先 `_take_lease`）。tool 的 docstring 补一句说明。

**D4 `WorldMcpTool` 增加客户端入口。** 新方法 `use_start_state(path: Path | None) -> None`：给了路径 → 读字节（断言非空）存在实例上；`None` → 清除。`reset` 在实例上存有起点时，把 `state_base64` 放进 MCP 调用参数；没有则不放这个键（与现状请求逐字相同）。起点对**之后每一次** `reset` 都生效，直到清除。`FromHarnessToGameToolResetReq`、`Task`、harness 都不动。

**D5 `PyBoyWorld.read_wram` 与 `WorldPort.read_wram`。** `WorldPort` 增加 `read_wram(self) -> bytes`：返回 `0xC000–0xDFFF` 共 8192 字节；`PyBoyWorld` 实现为 `bytes(self._pyboy.memory[0xC000:0xE000])`，后置断言长度恰为 8192。docstring 注明这是数据集冻结用的只读口，不推进世界。

**D6 server 增加只读 tool `read_wram`。** 无参数、不带 `client_id`、不占租约、不推进世界。返回 `envelope(data={"wram_base64": ...})`，内容为 D5 的字节的 base64。放在只读面（`save_state` 之后）。

**D7 `WorldMcpTool.read_wram() -> bytes`。** 调同名 tool，base64 解码，断言长度 8192，返回字节。

**D8 缓存与协议边界。** 不改任何 prompt 文件与渲染；不改 `step` / `load_state` / `save_state` / 租约逻辑；不改 `/health`。`WorldPort` 增加的两处都是可选/只读，进程内没有第二个实现需要同步（`PyBoyWorld` 是唯一实现）。

**D9 文档。** 同步事实性的几句：`docs/spec/world/SPEC.md`（WorldPort 接口、reset 起点优先级、read_wram）、`docs/spec/mcp/SPEC.md`（world server 的 tool 清单与参数；若文中有「45 个工具」之类的总数，改成实际总数，执行方用代码里 `mcp` 注册表的实数核对）、`docs/spec/tools/SPEC.md` 若列了 `WorldMcpTool` 方法则补两个新方法。其余历史引用不动。

## 三、测试

测试不起端口、不起模拟器、不调模型。

1. **server `reset` 透传起点**（`tests/mcp_servers/test_mcp_world_server.py` 扩展；假 world 的 `reset` 记录了 kwargs）：不带 `state_base64` → 假 world 收到的 kwargs **不含** `start_state`；带 → 收到 `start_state == 原字节`；带起点时租约仍生效（另一 `client_id` 持租约 → 被拒绝，假 world 未被调用）。
2. **server `read_wram`**：假 world 的 `read_wram` 返回 8192 个已知字节；tool 返回的 `wram_base64` 解码后逐字节相同；调用前后租约不变（不带 `client_id` 也能调、不改变 `lease_owner`）。
3. **`WorldMcpTool` 起点**（`tests/mcpclient/world_tool/` 新增，沿用 conftest 的 in-memory 传输）：未 `use_start_state` 时 `reset` 的 MCP 参数不含 `state_base64`；`use_start_state(path)` 后含且解码等于文件字节，并且**连续两次** `reset` 都带；`use_start_state(None)` 后不再带；空文件 → 断言失败。
4. **`WorldMcpTool.read_wram`**：经 in-memory 传输取回与假 world 相同的 8192 字节。
5. **`PyBoyWorld.reset` 起点优先级**（`tests/world/` 下新增，用 `object.__new__(PyBoyWorld)` 加假 `_pyboy`、假 `_tick`、`_state_path` 手工置位，不构造真对象）：给 `start_state` → 假 `_pyboy.load_state` 收到的流内容等于该字节且 `_tick` 被调 1 次，**没有**读 `state_path` 文件（`state_path` 指向不存在的路径也不报错）；不给且有 `state_path` → 读文件；不给也没有 `state_path` → `_tick(BOOT_FRAMES)`。`start_state=b""` → 断言失败。`read_wram`：假 `_pyboy.memory` 支持切片，返回长度 8192；长度不对时后置断言失败。
6. **破坏验证**（执行方做，汇报）：①把 D3 的透传去掉 → 测试 1 须失败；②把 D4 里 `reset` 带 `state_base64` 的分支去掉 → 测试 3 须失败；③把 D2 的优先级调成 `state_path` 优先 → 测试 5 须失败。每次都恢复。

## 四、允许改动的文件

生产：`pokemon_agent/world/interface/world_port.py`、`pokemon_agent/world/pyboy_world.py`、`pokemon_agent/mcp_servers/world_server.py`、`pokemon_agent/mcpclient/world_tool.py`。
测试：`tests/mcp_servers/test_mcp_world_server.py`、`tests/mcpclient/world_tool/conftest.py`（假 world 若需要）、`tests/mcpclient/world_tool/` 下新文件、`tests/world/` 下新文件。
文档：D9 点名的三个 SPEC、`CHANGELOG.md`（编号 482，四段式）。
**不得改**：评测目录、`build.py`、`world_server_cli.py`、`pokemon_agent/harness/`、`pokemon_agent/schemas/`、任何 prompt。

## 五、验收

- 全量 `pytest`、`ruff check .`、`ruff format --check .` 三项通过；`state_schema_hash` 仍为 `4f1cac6fcc7216d5`（实测报出）。
- 搜索：`read_wram` 与 `start_state` 的所有出现点列表汇报；`pokemon_agent/` 内没有新增 `_pyboy` 的私有访问（除 `pyboy_world.py` 自身）。
- 破坏验证三项均按 D 汇报。

## 六、停止条件

需要改「不得改」里的文件；假 world 的 `reset(**kwargs)` 之外有别的 `WorldPort` 实现需要同步；发现 `reset` 在 harness 里被调用时已带别的起点语义；全量不绿且不是本批改动引起（例如已有的定向失败 `test_brain_factory_uses_the_injected_plan_timeout` 只在特定子集顺序下出现，全量通过则不算）。

## 七、非目标

评测脚本迁移（批 ③b）；`/health` 报哈希；`load_state` 语义变化；WRAM 以外的内存口；`speed` / `watch` 管线清理。
