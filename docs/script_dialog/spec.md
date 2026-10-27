# spec —— 脚本内对话文字进账

> 版本 v1.1（2026-10-27 修订：执行方前置核对确认真实报告是扁平结构，MCP 服务端与账的解析模型会丢弃或拒绝新字段，`DialogCache.deltas` 是按段不是按行；改 D1、D3、D4，新增 D9，扩 CP1 文件清单）。依据：`docs/script_dialog/intent.md`（已确认的决定：ActMemory 新增独立字段；去重沿用 `DialogCache` 现有行为；不截断；不改等待逻辑）。基线：主线 `e7155c3d922f28e92289e3deacf4f4fb02ad6582`。
> 凡"待执行方核实"的项，在对应检查点先核实，与此处不符就停下汇报。

## 一、决定表

| 编号 | 决定 | 取舍 |
|---|---|---|
| D1 | `ScriptResult`（`pokemon_agent/world/scripts/control_flow.py`）新增顶层字段 `dialog: list[str]`，默认空列表，**一个元素一行文字**；`ScriptRun.finish`（`pokemon_agent/world/scripts/engine.py`）把 `self.dialog.deltas`（每次 `ingest` 一段，同帧多行用换行拼成一段）按 `splitlines()` 拆成行、去掉空行后按出现顺序填入。脚本本身一行不改 | 一处统一出口；按行存，渲染与评分最直接 |
| D2 | `advance_dialog` 现在放进 `data["dialog"]` 的那份保持原样，不删不改 | 避免牵连现有读方 |
| D3 | 真实终态报告是**扁平**的：MCP 服务端把信封 `data` 组装成 `{"ok", "code", **result.data, "calls"}`（`pokemon_agent/mcp_servers/world_server.py` 约 242–246 行），客户端 `pokemon_agent/mcpclient/world_tool.py` 约 181–183 行重建为 `{**body["data"], "events": ...}`。因此在服务端 `data` 字典**最后**加 `"dialog": result.dialog`（排在 `**result.data` 之后，使它覆盖 `advance_dialog` 放进 `data["dialog"]` 的按段旧值）；客户端不改 | 一行透传；覆盖顺序避免同名冲突 |
| D4 | `act_call` 账：生成位置是 `pokemon_agent/direct/trace/render.py` 的 `act_call`（约 549–581 行）：在 `if "events" in report` 之后加 `if "dialog" in report: content["dialog"] = report["dialog"]`；账的解析模型 `ActCallContent`（`pokemon_agent/direct/trace/content.py` 约 110–123 行，基类 `extra="forbid"`）新增 `dialog: list[str] | None = None`。注意真实报告是扁平的，`render.py` 里 `if "data" in report` 那条分支在真实路径上不触发，不要照它的嵌套形状写；按键动作的账不变 | 账与解析模型同步，否则解析会因多余键报错 |
| D5 | `ActMemory`（`pokemon_agent/schemas/memory/datastore/act_memory.py`）新增独立字段 `dialog: list[str] = Field(default_factory=list)`；`store_step_episode_memory` 从 `state.last_report["dialog"]` 取值；按键动作为空列表；旧记忆文件缺字段读作默认值，不写兼容逻辑 | 用户已确认独立字段 |
| D6 | prompt：新增 `memory_records` 片段版本 `v3`（`pokemon_agent/prompt/tasks/fragments/memory_records/v3/`，按现有 v1、v2 的结构复制再改），在 `result` 行之后逐行渲染 `dialog`，全文不截断，标签文字写在该版本的 md 里；`records.py` 的输入契约（`ActRecord`）新增 `dialog`；旧版本不改；经 `pokemon_agent/prompt/registry.json` 把激活版本切到 v3 | 遵守"一个 md 一个版本、旧版不改" |
| D7 | 不改等待与稳定检测，不改 `events[]` 与对象记忆，不改按键模式 | 范围收窄 |
| D8 | 对话增量沿用 `DialogCache` 的去重（同一次调用内同一行只记一次）；每个 `ScriptRun` 自己一个 `DialogCache`，天然按调用隔离 | 已确认 |
| D9 | 同名冲突：`advance_dialog` 现有 `data["dialog"]`（按段）与新的顶层 `dialog`（按行）在扁平报告里同名，以 D3 的覆盖顺序保证最终报告里只有按行的那份；测试需覆盖 `advance_dialog` 的报告 `dialog` 等于逐行列表而不是按段列表 | 不改 `advance_dialog` |

## 二、检查点

| 检查点 | 内容 | 验收核对点 |
|---|---|---|
| CP1 账与记忆 | D1–D5、D7、D8：`ScriptResult.dialog`、`finish`、`act_call` 的 `dialog`、`ActMemory.dialog`、`store_step_episode_memory`；测试 | 用控制台替身跑一段多行对话的 `advance_dialog`，`ScriptResult.dialog` 恰好是依次出现的行；`act_call` 内容含该列表；写出的 ActMemory 含同样的行；按键动作的 `act_call` 与 ActMemory 与改动前一致；旧记忆文件缺 `dialog` 字段可读 |
| CP2 prompt 渲染 | D6：`memory_records` v3、`ActRecord.dialog`、`registry.json` 切换；测试 | v3 渲染含 `dialog` 各行且在 `result` 之后；`dialog` 为空时渲染与 v2 逐字相同；旧版本文件无改动；`registry.json` 激活 v3 |

## 三、文件改动清单（允许范围）

- CP1：`pokemon_agent/world/scripts/control_flow.py`、`pokemon_agent/world/scripts/engine.py`、`pokemon_agent/mcp_servers/world_server.py`（仅 D3 那一处）、`pokemon_agent/direct/trace/render.py`、`pokemon_agent/direct/trace/content.py`、`pokemon_agent/harness/task/act/act.py`（仅在需要时）、`pokemon_agent/harness/task/perceive/store_step_episode_memory.py`、`pokemon_agent/schemas/memory/datastore/act_memory.py`、对应测试（含 `tests/direct/trace/` 的解析与回环、`tests/mcp_servers/`）、`CHANGELOG.md`。
- CP2：`pokemon_agent/prompt/tasks/fragments/memory_records/v3/`（新增）、`pokemon_agent/prompt/tasks/fragments/memory_records/params.py`（若需登记版本）、`pokemon_agent/prompt/records.py`、`pokemon_agent/prompt/registry.json`、对应测试、`CHANGELOG.md`。
- 若某文件不存在或函数名不同，停下汇报。

## 四、待执行方先核实的事项

1. 生成 `act_call` 账内容（`script`、`args`、`ok`、`code`、`events`）的位置：是从 `report` 里挑字段，还是别处；加 `dialog` 只许改这一处。
2. `ScriptResult` 到 `resp.report` 之间的序列化路径（MCP 服务端、客户端模型）是否会丢弃未知顶层字段；若会，报告需要同步改的文件，超出允许范围就停下。
3. 读侧对 `act_call` 与 ActMemory 的字段假设：检索 `evals/agent_short_goal_run/scorer/`、`pokemon_agent/reviewer*`、`pokemon_agent/trace`、记忆蒸馏与 `summarize` 的取字段方式；发现严格校验未知字段就停下汇报。
4. `ActMemory` 新字段是否影响 `state_schema_hash` 或记忆存档的校验；若影响，记入 CHANGELOG 并停下汇报是否需要改允许范围外的测试夹具。
5. `memory_records` 的 v1、v2 目录结构与 `registry.json` 的切换规则，按 `docs/prompt_module/` 的约定执行。

## 五、测试清单

- CP1：见验收核对点；另加：同一次调用内重复的行只出现一次；没有对话的脚本调用 `dialog == []`；`ScriptResult` 其他字段行为不变。
- CP2：见验收核对点；另加：多行 `dialog` 逐行渲染顺序与输入一致，不截断（用 200 行样例断言）。

## 五点五、已知基线失败（环境原因，不属于本任务）

起点全量 pytest 有 3 条失败：`tests/evals/test_eval_service_wiring.py::test_world_case_caller_closes_world_service_after_each_worker_outcome[success|timeout|worker_error]`。原因是该用例把模块级 `subprocess.run` 换成替身，而执行沙箱的 safe-delete 守卫在 `TemporaryDirectory` 清理时也调用 `subprocess.run`，被替身拦下；守卫的 `SystemExit` 还会吞掉 pytest 的统计尾行。处理方式：这 3 条视为已知基线失败；全量运行时加 `--deselect tests/evals/test_eval_service_wiring.py::test_world_case_caller_closes_world_service_after_each_worker_outcome` 以拿到完整统计尾行；每个检查点汇报时，除这 3 条外不得有任何新增失败。用户会在本机另行核对这 3 条在正常环境下是否通过。

## 六、验证方式

不调用真实模型，不启动模拟器，全部用手写替身与固定文本。

## 七、停止条件

遇到下列任一情形停下汇报，不要重试、不要绕过：改动超出允许文件范围；起点不是全绿；读侧严格校验未知字段（核实项 3）；`state_schema_hash` 或记忆校验受影响且需要改范围外文件（核实项 4）；需要执行被禁止的 git 命令；任何真实模型调用。

## 八、非目标

不改等待逻辑与稳定检测；不逐帧读屏、不截图、不加 `▼` 检测；不截断对话；不改 `events[]` 与对象记忆；不改机械判据（读新字段的判据在中期样本构建时另案加）；文档（AGENTS.md、CLAUDE.md）同步另案。
