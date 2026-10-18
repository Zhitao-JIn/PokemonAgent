# intent —— mcp_servers 单元测试：收敛到连接性，world 逻辑迁往 world 模块

> 状态：**已确认**（2026-10-17，用户回复「可以，可以」）。
> 范围：`pokemon_agent/mcp_servers/` 的测试只管**连接性**（服务端能起、工具注册正确、调用能到达后端并把结果原样返回、传输层的错误映射）。world 的游戏逻辑归 world 模块，不在 mcp 线测试。
> 关联：`docs/test/memory-test-intent.md`（memory 线，同一做法）；AGENTS.md 第三节第 4、5 条。

## 一、一句话意图

`mcp_servers/` 的测试只证明三件事：服务端能起来并报告就绪；工具注册表里的名字与参数形状正确；一次调用能穿过传输层到达后端、结果原样回来。world 的按键语义、脚本行为、读内存细节，全部属于 world 模块，不在这里测。

## 二、为什么现在做

1. `tests/mcp_servers/` 下 5 个文件约 1000 行，混了大量 world 逻辑（按键语义、脚本端到端、读内存），测的是 world，不是 mcp。
2. memory 线已经确定：memory 行为归 memory，mcp 只管暴露。world 线要做时，逻辑测试得有明确去处。
3. 现有连接性用例是对的，但和逻辑测试混在一起，读者分不清哪些是契约、哪些是行为。

## 三、是什么 / 不是什么

**是**：
- 保留并整理连接性用例：健康检查与就绪、URL 与路径常量一致、探针的通过/拒绝/不可达、注册表条目、一次真 FastMCP 传输的往返（唯一端到端，作为用法示范）、CLI 参数能传到 world；
- 迁移清单：世界逻辑的用例**登记清单，不删除，原地保留**，等 world 线开始时逐条迁入 `tests/world/`。

**不是**：
- 不重写 world 的按键、脚本、读内存、场景逻辑；
- 不测 `memory_server.py`（归 memory 线）；
- 不测 `mcpclient/` 的客户端装配（另案）；
- 不起 PyBoy，不需要 ROM，不联网。

## 四、硬边界

1. 零 ROM、零 PyBoy、零联网、零真实模型；假后端用手写小类，与 `_doubles/world_console.py` 的 `StubConsole` 同形即可。
2. 不测私有成员（以 `_` 开头的属性与方法）。注意：`world_server._lease_owner` 等在现有测试里被直接读写，是已知的私有访问，本线不新增，已有的在 spec 里逐条登记。
3. 一个用例只钉一件事；Arrange / Act / Assert 三段空行分开；不用 `MagicMock`。
4. 传输端到端只保留一条（`test_client_roundtrip_over_mcp_transport`），其余连接性用例不起真端口。
5. 默认 pytest 下 `tests/mcp_servers/` **≤ 3 秒**；不加 `slow`；不 sleep。
6. 测试文件名全仓唯一。

## 五、分类结果（逐条见 spec）

**保留（连接性）**：健康检查与探针、注册表、传输往返、CLI 参数、租约协议、脚本工具注册。

**留在 mcp 线，但属于待定→已决**：线上存档的 base64 编码（`test_state_roundtrip_is_base64`）留 mcp，理由是它是传输编码。

**迁移清单（世界逻辑，原地保留，world 线开始时迁入）**：按键语义与 `moved` 判定、`get_action_space` 的命名空间、`perceive_task` 的场景内容、`reset` 的起始状态转发、读 WRAM 的字节内容、脚本的 `walk_to_adjacent` 转发与被阻挡信封、`buy_item` 端到端，以及 `mcpclient/world_tool/` 下的世界逻辑用例。

## 六、迁移约定

- 本线**不删**任何世界逻辑用例，只在 spec 里登记清单；
- world 线开始时，按清单逐条迁入 `tests/world/`，迁移前后用例名集合对得上；
- 被迁走的用例在 mcp 线删除，必须与 world 线的迁入在同一检查点、同一 CHANGELOG 条目里完成。

## 七、成功的样子

- `tests/mcp_servers/` 里的连接性用例读完就知道服务端怎么起、工具怎么注册、一次调用怎么穿过传输层；
- 逻辑用例全部登记在清单里，没有丢失；
- 默认 pytest 下目录耗时 ≤ 3 秒；
- 租约、就绪、注册表、传输往返四类契约各有清晰的测试名。

## 八、遗留（另案）

- `test_load_env_file_*` 等配置读取测试的归属（不在 mcp 线，待定）；
- `mcpclient/` 的客户端装配测试（另案）；
- `memory_server.py` 相关测试由 memory 线处理。
