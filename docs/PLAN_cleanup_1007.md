> **状态：已执行完（2026-10-07，CHANGELOG 354–360）**。执行记录与提交分组见 `docs/CLEANUP_1007_REVIEW.md`；
> 本文件留档，其中"347–353 全部未提交"一句与实际不符（已提交至 f168289），以 360 的纠正为准。

# PLAN —— 宏并入脚本 / 测评收敛之后的收尾（2026-10-07）

> 交接对象：接手的 AI。起点：CHANGELOG 第 353 条之后的工作区（**全部未提交**）。
> 基线（2026-10-07 实测）：pytest 490 passed / 2 skipped（Langfuse 检查按配置跳过）；
> `ruff check pokemon_agent evals tests scripts` 净，只有 `experiment/real_check/` 剩 4 条旧告警；
> 代码侧 `run_macro` / `MacroOutcome` / `MacroCall` / `last_macro` / `RUN_MACRO` 零残留；AGENTS.md 与 CLAUDE.md 同步。

## 0. 必须遵守的规矩（开发者定的）

- **不提交**：`git commit` / push 等开发者明说。git 读操作加 `GIT_OPTIONAL_LOCKS=0`，否则会残留 `.git/index.lock`。
- **每一阶段一条 CHANGELOG**（顶部追加，编号从 354 起；四段：改了什么 / 为什么 / 取舍 / 影响面）。原因只进 CHANGELOG，代码注释只在文件头、函数头、步骤标记三处。
- 编码范式按 skill `ai-coding-paradigm`。
- **新写测试要先问开发者**；受改动影响的现有测试可以直接改或删（删要在 CHANGELOG 写明测的是什么死代码）。
- **ROADMAP 不动**；`docs/checkpoint|eval|experiences|perceive|web_reviewer`、`HANDOFF_*`、`docs/roadmap/` 是冻结文档（344 口径），不改。
- 不跑真实模型调用（花钱），真机验证留给开发者。world_actions 的真模拟器用例不调模型，可以跑。
- 标 **【需开发者拍板】** 的步骤：先把选项与推荐写出来问开发者，拿到答复再动手；不要替开发者选。

## 1. 阶段一：清残留（无需拍板，可直接做）

| # | 对象 | 现状 | 动作 |
|---|---|---|---|
| 1.1 | `evals/tasks/macros/`、`evals/tasks/takeover_views/`、`evals/tasks/eval_results/inspect/` | 空目录 | 删除 |
| 1.2 | `scripts/r0_smoke.py`、`scripts/_tmp_payload_scan.py` | 一次性冒烟 / 自标"临时" | 删除；先 `git grep` 确认零引用 |
| 1.3 | `evals/e2e` 旧批跑链：`cli.py` 的 `run` / `report` / `dataset` 子命令、`runner/batch.py`、`runner/view.py`、`report/`（assemble / evaluate / grader / markdown）、`process/`、`rubric/`、`cases/` | `evals/cli.py` 只路由 `e2e run-one`；现行 inspect task（`tasks/e2e.py`、`tasks/result_grade.py`）不引用它们；只剩 `tests/test_evals_scoring.py`、`tests/test_run_result.py` 在测 | 只保留 `runner/one.py` 与它依赖的东西（`RUN_RECORD` / `RUN_RESULT` 常量就地移进 `runner/one.py` 或其旁边，别留一个只为两个常量存在的 `report/`）；其余删除。两个测试里**只测死代码的用例删掉**，测 `RunResult` / run-one 产物的用例保留。**`diff` 子命令与 `core/evallog.py` 本步不动**，见阶段 1b |
| 1.4 | 连带零消费者清扫 | 删完 1.3 后，`evals/schema`（`report.py` / `verdict.py` / `sample.py` 里的部分模型）、`evals/scorers/model_graded.py`、`evals/data` 里的 `load_rubric` / `rubric.json` 等可能变成零消费者 | 逐个按"三问"核：有没有实现在用、有没有类型标注在用、引用者是不是只有文档。**零消费者才删**。`ReportHeader` / `SampleResult` / `COMPARABLE_FIELDS` 是 diff 的输入形状，**等阶段 1b 定了再处理** |
| 1.5 | `experiment/observation_check/` | 348 说读屏采集 / 复核工具已移进 `evals/data`；这份旧目录仍在 | 逐文件对照 `evals/data/` 下的对应物：已有等价物的删；`run_vision_model.py` / `equiv_probe.py` / `sync_vendor.py`（vendor 出去单调视觉模型的旁路，vision_perceive 已覆盖）删；对不上的列出来问开发者 |

**验收**：pytest 全绿（数量会因 1.3 删测试而下降，CHANGELOG 写清删了哪些、为什么）；`ruff check pokemon_agent evals tests scripts` 净；`python -m evals list` 仍列出 7 个 task；`python -m evals e2e run-one --help` 能跑；`git grep` 被删模块名零引用（文档里的历史提及除外）。

## 1b. 阶段一 b：diff（两份测评结果对比）的去留 【需开发者拍板】

事实（2026-10-07 核过）：`core/evallog.diff(a, b)` 读两个**报告目录**里的 `header.json`（口径，`ReportHeader`）
与 `results.jsonl`（逐样本 `SampleResult`）：口径字段（`COMPARABLE_FIELDS`）不一致就拒绝对比，一致就列出
各样本 `final` 结论的翻转。这两个文件**只由旧批跑链写出**（`runner/batch.py` 写 header、`report/assemble.py`
写 results）；现行 7 个 inspect task 只产出 `.eval` 日志，不写它们。所以 diff 在当前流程里**已经没有输入**——
问题不只是删了 `e2e/cli.py diff` 会丢入口，而是保留入口也读不到东西。spec2 §一 明确要留"口径一致性校验"
（Inspect View 的日志历史只展示、不校验可不可比）。

问开发者（给推荐）：
- A（推荐，落实 spec2 原意）：把 diff 改造成读 inspect 的 `.eval` 日志（`inspect_ai.log.read_eval_log`）。
  口径取日志头里已有的东西：task 名与 task 参数（`-T`）、数据集版本与样本集、模型配置、`pokemon_agent.config`
  快照（若 task 已写进 metadata；没写就先列出缺哪些、问开发者要不要补）、git commit。逐样本对比 score 值与
  NOANSWER 状态的翻转。入口放到 `evals/cli.py`：`python -m evals diff <log_a> <log_b>`。
  完成后旧 `core/evallog.py` 的报告目录读法、`ReportHeader` / `SampleResult` / `COMPARABLE_FIELDS`（若再无他用）
  与 `e2e/cli.py diff` 子命令一起删，`e2e/cli.py` 收成只剩 `run-one`。
  这一步要先把"口径字段清单"列给开发者确认（它决定什么样的两次跑批算可比），再写代码；
  测试属于新写测试，要先问。
- B：不要 diff。与 1.3 一起删 `core/evallog.py`、`e2e/cli.py diff`、相关 schema；CHANGELOG 注明这是对
  spec2 §一 "保留 diff 口径校验" 的有意偏离，并问开发者是否同步改 spec2（spec2 属规格文档，改前要问）。

无论选哪个，`docs/spec/evals/SPEC.md` 里 diff 的入口与说明都要同步。

## 2. 阶段二：`experiment/real_check/` 【需开发者拍板】

现状：三图完整性核对已迁 `tests/test_harness_integrity.py`（350）；记忆写读 / 检索已进 memory task（348）；
`check_checkpoint.py` 开发者说过准备删；`check_web_reviewer.py`（Web Reviewer 端到端自测）去留未定。
目录里还有 4 条 ruff 旧告警。

问开发者（给推荐）：
- 推荐：整个 `experiment/real_check/` 删除；`check_web_reviewer` 若要留，改写成 `tests/` 下的集成测试（属于"新写测试"，要先问）。
- 删之前核：`pokemon_agent/config.py`、`direct/trace/render.py`、`world/ram.py` 等文件 docstring 里提到 `real_check` 的地方一并改掉；`experiment/real_check/common.py` 的 `TRACE_BACKEND` 读法（346）随目录一起消失，CHANGELOG 注明。

## 3. 阶段三：MCP 面注册接管脚本 【需开发者拍板：做不做、怎么注册】

现状：`mcp_servers/world_server.py` 22 个 tool，只注册了 14 条常规脚本；接管脚本 25 条（`shop_buy` / `shop_sell`
是只经 `buy_item` / `sell_item` 组合调用的内部脚本，对外 23 条）。`mcpclient/world_tool.py::execute` 遇到
`TAKEOVER_SCRIPTS` 里的名字就地抛 `McpToolError`——MCP 模式下在商店 / 战斗 / 背包 / 队伍 / PC / 学招 / 起名场合会卡死。

选项（问开发者）：
- A（推荐，符合 MCP SPEC "一脚本一 API"）：23 条接管脚本各写一个显式 `@mcp.tool()` 壳（签名照 `ActionEntry.params`，内部走现有 `_run_script`）。
- B：从 `SCRIPT_SPECS` 动态生成 tool（少写代码，但 FastMCP 靠函数签名出 schema，动态构造可读性差）。

做的话：删 `world_tool.py` 的拦截与 docstring 里的"已知缺口"；`tests/test_mcp_world_server.py::test_registry_lists_the_atomic_layer` 的精确名单、`test_mcp_world_tool.py::test_takeover_scripts_and_evolve_are_explicitly_unsupported` 同步改（evolve 那半保留）；`docs/spec/mcp/SPEC.md` 第七节、`docs/spec/tools/SPEC.md` 的 `execute` 行同步。
**验收**：用现有 MCP 测试替身跑通一条接管脚本（如 `shop_quit`）经 `WorldMcpTool.execute` 返回 `report`。

## 4. 阶段四：主链路 trace 后端缺省 【需开发者拍板】

现状：`pokemon_agent/config.py::TRACE_BACKEND = "langfuse"`（345），而开发者当前关着 Langfuse，`evals/config.json` 用 `local`。
直接起跑 `build_real` 会在装配期被 Langfuse 健康检查拦下。

问开发者：系统缺省改 `local`，还是保持 `langfuse`（起跑前自己开服务）。改的话只动这一个常量 +
`tests/test_build.py` 里钉 `"langfuse"` 的断言 + 常量 docstring；不要在别处再加一份缺省（345 定案：只留 config 一处）。

## 5. 阶段五：决策 prompt 的覆盖 【新测试要先问】

- `tests/test_decide_action_prompt.py` 只测了常规场合；接管场合走 `direct/prompts/decide_action.py::_build_takeover_prompt` + `calls/decide_action/decide_takeover.md`，没有测试。问开发者要不要补一条"接管场合 prompt 只列本场合脚本、输出格式是 `args` 对象"的用法示范。
- 解析器同时接受 `{"action": ..., "args": {...}}` 与参数平铺（347），平铺写法没有专门测试，同上一起问。
- 真模型验证 `decide_takeover.md`：**不要做**，留给开发者本机。

## 6. 阶段六：测评数据缺口（多数要人工真值，AI 只做准备）

来自 348–351 自己记下的缺口：
- decode：scene / at_start 标注未独立核对；文字组 40/45；地形只 2 帧。
- memory、judge：只有示范小库；memory 的相关性标注要扩充。
- `decide_action`（大脑选动作）组件测评未立项，开发者排版时定。

AI 可做：列出每项缺多少条、建议采样方案、准备好标注工具入口（`evals/data/` 下现有工具）；**不要用待测实现的输出当真值**（348 / 351 原则）。具体标注由开发者做。

## 7. 阶段七：版本控制 【需开发者拍板】

- `.gitignore` 第 12 行 `tests/`、第 17 行 `/experiment/`：测试与实验目录不进版本库，347–353 的测试改动都不会被提交。问开发者是否有意为之。
- 347–353 全部未提交。可以给出一份按 CHANGELOG 编号分组的提交建议（每条一个 commit，先列 `git status` 与每组文件清单），**等开发者确认后再提交**。

## 推荐执行顺序

阶段一（直接做，1.3 不碰 diff 那一支）→ 汇总阶段 1b、二、三、四、五、七的拍板问题一次性问开发者 → 按答复做 → 阶段六只出清单。
每阶段结束跑：`pytest`、`ruff check pokemon_agent evals tests scripts`、`GIT_OPTIONAL_LOCKS=0 git grep` 残留扫描；
动了 world 脚本就再跑 world_actions 真模拟器用例（`python -m evals run world_actions`，不调模型），应保持全过。
