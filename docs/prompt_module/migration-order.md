# 迁移顺序 —— prompt 模块（intent 的实施顺序草案）

> 依据：`docs/prompt_module/intent.md`。本文是 spec / plan 的骨架，不含文件级清单与测试清单；
> 各检查点的允许改动文件、changelog 编号、核对点在 plan 阶段补齐。
> 每个检查点 = 一次验收 = 一个提交，回退用 `git revert`。

---

## 一、排序原则

1. **先对拍、后动手。** 任何改动之前先固化「现状输出」。没有这份基线，后面每一步都无从证明「措辞零变化」。
2. **先骨架、后搬家。** 网关、注册表、版本标识先立起来，之后每个任务都经它落地。
3. **先加后减（expand / contract）。** world 先**新增**结构化字段、旧字符串字段暂留；全部消费方迁完之后，才**删除**旧字段与旧 `render`。这样每个检查点都保持全绿，也不会出现「旧渲染已删、新消费方还没迁」的空窗。
4. **由易到难迁任务。** 依赖最少的先迁（只吃记忆与标量的蒸馏类），依赖最多的最后（`decide_action`，牵涉动作空间、MCP 契约、`known_objects`）。
5. **删除放最后。** 删旧字段、旧记忆、旧包、冻结副本都集中在收尾，且每一项先确认读方清零。

## 二、检查点

### CP0 对拍基线（不改任何生产代码）

- 在改动开始前，把现有各任务的 `build_prompt` 对一批真实输入的输出固化下来，作为后续逐字节对拍的基线。
- 覆盖：`decide_action`、`judge_success`（task / episode / run 三层）、`decompose`、`run_plan`、`verify`、`summarize`、`summarize_task`、`summarize_run`，以及 `retry_prompt`。
- 输入来源待 spec 核实：测试夹具、`evals/dataset/brain_calls/v1/` 的请求记录、trace、`memory/` 下的旧记忆（**必须在删除旧记忆之前取用**）。
- 验收：基线文件可重复生成；固化出的输入不含任何密钥。

### CP1 骨架

- 新建 prompt 模块：网关、注册表加载与校验、版本元数据与 hash、`RenderedPrompt`。
- `AppConfig` 增加注册表路径；`build_real` 递裸字段给 `BrainTool.build()`，由它造出网关并注入。
- `BrainTool` 把 `(任务, 版本, hash)` 三个字符串写进每次尝试的 `ModelCall.payload`（不改模型），验证它们透传到 trace。
- 机械守卫：模块外无具体任务 import；模块对 `pokemon_agent.*` 依赖为零。
- 用临时注册表与示范单元写单元测试（用法示范风格），此时**不迁任何真实任务**。
- 验收：注册表校验失败时启动即抛；守卫脚本有负例。

### CP2 world 增量字段化（只加不删）

- world 新增结构化字段：四邻字典、地形格 `cells`、选项排布（网格、光标格、附注列表）、`BattleStatus`、观测限制标志。`task_perception.py` **同时**填新旧字段。
- `ActMemory` 内的 world 快照副本同步新增对应字段；`test_facts_dual_copy_parity` 同步扩展。
- MCP 序列化与契约测试同步（新字段进 world server 的返回）。
- 不删任何旧字符串字段与旧 `render`。
- 验收：现有全部测试不改一行仍绿；新旧字段在同一帧上互相对得上。

### CP3 记忆渲染入模块，迁移四个蒸馏类任务

- 在模块内实现记忆五类的渲染（含相邻帧去重、`index_line`），仅读字段。
- 迁入：`verify`、`summarize`、`summarize_task`、`summarize_run`。它们只依赖记忆对象与标量，是最小风险的第一批。
- `BrainTool` 对应四处改为「转字段 → 网关」。
- 验收：四个任务对拍逐字节一致；旧 `build_prompt` 调用点清零（旧文件暂留，供对拍与后续任务引用）。

### CP4 迁移 judge、decompose、run_plan，并抽出共用片段

- 迁入：`judge_success`（含 `judge_interrupt`）、`decompose`、`run_plan`。
- 同时抽出共用片段为独立单元：读屏幕说明、人类插话、上一次判定行、目标表与任务表的行渲染。
- 模块内实现「观测渲染」（读新增的结构化字段）、`TakeoverView` 的 9 个视图渲染。
- `knowledge_query` 的 query 改为不再拼 `status`（行为变化，单独在 changelog 说明）。
- 验收：三个任务三层对拍一致；`judge` 不再向 `decompose` / `run_plan` 借函数。

### CP5 迁移 decide_action（最大的一步，可拆 5a / 5b）

- **5a**：`decide_action` 模板收编为一个 md，分段承载按键说明、读图提示、连按提示、读图范例、重试纠正说明；`MAP_HINT` / `BUTTON_HELP` / `REPEAT_HINT` 常量消失；`ActionSpace` 去掉文本字段；`mcpclient/action_space.py` 的文本注入删除；MCP 契约、`docs/mcp/` 与相关测试同步。
- **5b**：`task_frame` 的按场合投影、`known_objects` 的渲染（harness 改传原始事件）、脚本签名与说明的排版、`retry_prompt` 并入模块。
- 验收：对拍一致（含开放脚本与按键同时出现的场合）；`harness` 对 prompt 渲染的 import 清零。

### CP6 world 与记忆收缩（只减不加）

- 删除 world 与记忆对象上的旧字符串字段与全部 `render` / `index_line` / `signature` / `render_*`。
- 同步消费方：`trace/render.py` 对 `status` 的使用；reviewer 为界面渲染 `index_line` 改为自管；decode eval 与真值数据集改比对结构；`choose_review` 改读 `cells`；`agent_short_goal_run` 里读 `option_details` 的规则改读结构化字段。
- 删除 `memory/` 下的旧记忆文件。
- `ActMemory` 内的快照副本去掉旧字段；`test_facts_dual_copy_parity` 改写其意图。
- 验收：第六节读方清零检查；全量测试通过。

### CP7 收口

- 删除 `direct/prompts/` 整包；`evals/common/legacy_requests/` 中冻结的 prompt 副本改为「指向历史注册表」或直接删除。
- 守卫全开：唯一出口、依赖为零、无模块级 prompt 常量、无残留旧符号。
- 文档同步：`AGENTS.md` / `CLAUDE.md` 第二、四、六节中关于 `direct/prompts`、`providers`、`BUTTON_HELP` 等的描述；`docs/spec/` 相关页；对拍基线的使用说明。
- 验收：intent 第八节八项全部机械通过。

## 三、依赖与并行

| 检查点 | 前置 | 可否并行 |
|---|---|---|
| CP0 | 无 | 先做；必须早于「删旧记忆」与 world 形状变化 |
| CP1 | CP0 | 与 CP2 无文件交集，可并行 |
| CP2 | CP0 | 与 CP1 可并行 |
| CP3 | CP1、CP2 | 串行 |
| CP4 | CP3 | 串行（共用片段在此建立） |
| CP5 | CP4 | 串行 |
| CP6 | CP3–CP5 全部完成 | 串行 |
| CP7 | CP6 | 串行 |

## 四、需要在派发前处理的事

- **文件交集**：运行 `python .coordination/overlap.py`。已知 `codex/pyboy-paused-window-pump` 在改 world 的 `walk_to`，可能与 CP2、CP6 的 world 改动有交集；`tests/trace-unit` 与 CP1 的 trace 账改动可能有交集。
- **changelog 编号**：当前 CHANGELOG 顶号 578；台账记录 `codex/pyboy-paused-window-pump` 已用到 582。派发时用脚本取号，不在此预设。
- **worktree**：建议 `.worktrees/prompt-module/`，分支 `refactor/prompt-module`，基线取派发时的 main。
- **删除权限**：CP6 删旧记忆需要在用户本机的 `memory/` 上执行删除，需要到时申请删除授权。
- **真实模型运行**：迁移全程不需要；若要在迁移完成后验证端到端行为，另行授权。
- **合并顺序**：整个分支合入前，核对基线之后主线上是否有别的任务改了 world、`schemas/memory`、`direct/prompts` 这几处。
