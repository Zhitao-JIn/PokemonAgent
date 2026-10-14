# intent —— memory MCP 服务补齐 snapshot / restore

> 流程位置：**intent.md（本文）** → spec.md → plan → PR → production
> 状态：**v1 草案，待确认**
> 起草：2026-10-13
> 关联：`docs/mcp/memory-admin-spec.md`
> 性质：生产代码改动（memory 的 MCP 服务端与客户端门面）。**独立于**"删除视觉感知档"，两件事不混在同一批提交里。

---

## 一、一句话意图

让 `MemoryToolPort` 的两种实现（进程内 `MemoryTool`、MCP 远程门面 `MemoryMcpTool`）**能力一致**：MCP 模式下同样能 `snapshot_memory` / `restore_memory`，checkpoint、存档恢复和 agent 评测在两种模式下都能跑。

## 二、为什么做

1. **同一个 Port，两种实现，能力不一致。** harness 只认 `MemoryToolPort`，其中 `snapshot_memory` / `restore_memory` 是声明了的方法。进程内实现有，MCP 门面没有，于是切到 MCP 就在恢复存档时抛 `AttributeError`。这违背了"换传输不换行为"的前提。
2. **checkpoint 链路因此不能替换。** `Checkpointer.save` 要拍记忆快照、`open_branch` 要用快照还原记忆；这两步在 MCP 模式下一个会静默缺失、一个会炸。2026-10-13 的基线首跑就是在这里停下的（`'MemoryMcpTool' object has no attribute 'restore'`）。
3. **此前的说法需要纠正。** 2026-09-29 的定案是"运维（snapshot/restore/count）不进 MCP 面"，当时的目的是不让注册表暴露存储原语。它描述的是**当时的实现取舍**，不是对 Port 的要求；Port 本身一直包含这两个方法。本文要做的是：保留"能力面干净"的初衷，同时让 Port 的契约在 MCP 模式下成立。

## 三、做什么

- memory MCP 服务新增两个 tool：`snapshot_memory`、`restore_memory`。
- `MemoryMcpTool` 实现与进程内版本**同一份契约**的 `snapshot` / `restore`，使 `MemoryTool` 在 MCP 模式下的 `snapshot_memory` / `restore_memory` 与进程内行为一致（Port 信封不变，harness 与 checkpoint 代码不动）。
- **快照在客户端与服务端之间如何传递**：不假设两端能访问同一个文件路径。快照 zip 的**内容**经 MCP 调用传输（带完整性校验），客户端把它落在自己一侧的 `<memory_root>/snapshots/`，恢复时再由客户端把内容送回服务端。
- 验证：MCP 模式下存档、恢复可用，`agent_short_goal_run` 能在 MCP 模式下恢复存档并跑完。

## 四、不做什么

- 不改 Port 信封（`FromHarnessToMemoryTool{Snapshot,Restore}MemoryReq/Resp` 保持原样）。
- 不改 checkpoint 逻辑、不改 `memory/store.py` 的打包与还原语义。
- 不改 recall / memorize 的行为。
- 不做增量快照、不做快照压缩策略调整、不做多客户端并发恢复的协调（本地单客户端使用）。
- 不在本项修 `count` 等其他运维口。

## 五、需要确认的一点

**管理面是否默认暴露。** MCP 注册表是任何 MCP 客户端（前端人格 agent、agentic memory 等）都能发现并调用的能力清单；`restore_memory` 会**整库覆盖**，误调代价很高。倾向：两个 tool 只在服务端以 `--enable-admin` 启动时才注册，默认不暴露；门面发现服务端没开时给出明确报错（指向该开关）。这样既满足"Port 契约在 MCP 模式下成立"，又不改变现有默认的能力面。如果你希望默认就开，spec 里只需改一个默认值。

## 六、风险

- **体积与耗时。** 快照 zip 经 JSON 传输（base64），记忆库当前约 46 MB，压缩后体积和单次调用耗时需实测；每个 checkpoint 都会传一次。
- **整库覆盖的误用。** 见第五节。
- **两端行为漂移。** 同一契约两份实现，必须有对照测试钉住，否则会重蹈本次的缺口。
- **与进行中的工作冲突。** `docs/spec/tools/SPEC.md`、`CHANGELOG.md` 也是"删除视觉感知档"要改的文件，两项提交不要交叉。

## 七、成功的样子

- 把 `MCP_MEMORY_SERVER_URL` 指向服务端（带 `--enable-admin`），`agent_short_goal_run` 与进程内模式一样能恢复存档并跑完；
- 对照测试：同一串 memorize → snapshot → 再 memorize → restore → recall，两种实现结果一致；
- 服务端与客户端使用**不同的** memory 根目录也成立（证明没有依赖共享路径）；
- 服务端默认启动时注册表仍只有 `recall` / `memorize`。
