# 分层运行预算（意图 + spec + 步骤）

状态：v1.1，2026-10-14。用户已确认第七节第 1、1a 项（共用层数值、生产行为变严、评测与生产仅总量不同）；B1–B5 均可执行。第七节第 2、3 项仍待定，本项不实现。
证据：`eval_results/recent_status_20261014/REPORT.md`（现状与各层上限表）、
`eval_results/remove_vision_baseline_d40aedb_inproc/SHOP_TIMEOUT_ANALYSIS.md`（第六例超时）。
关联：视觉删除 `docs/perceive/remove-vision-plan.md`（本项完成并重建基线前，S1 暂停）。

## 一、意图

**问题。** 第六例（商店柜台）在 600 秒硬终止时没有 `run_end`，两评分器都记 N。根因不是缺按键，而是各层预算单位不同、没有连起来：
- run 的"最多 3 局"管不到一直不结束的第一局；
- episode 的 15 是"15 个子任务"，不是 15 次按键，且成功会重置连续失败计数；
- task 的动作预算由模型填写，没有统一最大值（本次最高 30）；
- 没有跨任务、跨局的累计动作上限，也没有重拆解次数上限；
- 一次拆解请求开着思考、输出上限 65536、总等待可达 435 秒，样本只剩 160 秒时仍能启动；
- 重试不知道样本剩余时间。
结果是预算耗尽不能"正常结算"，只能被外层强杀。

**做什么。**
1. 把预算收成一个明确的配置对象（预算档），由唯一装配点注入。**评测与生产共用同一套分层数值**（task、episode、拆解、模型请求），只在 run 级与总量上限上不同：评测收紧，生产放开。
2. 贯穿一条单调时钟 deadline：每次模型请求、每次重试、每次动作执行前取剩余时间，不够就不发。
3. 增加累计动作、episode 任务数、拆解轮次、task 动作上限，耗尽时走**确定的收尾路径**（不再问模型也能写出 `run_end`）。
4. 短目标档关闭规划/拆解的思考，缩小输出与单请求等待。

**不做。** 不改数据集与真值；不调评分规则；不修商店柜台的误判（那是规划质量问题，缩短预算不会让它自动变对，另案）；不碰视觉删除。

## 二、决定表

| # | 决定 | 取舍 |
|---|---|---|
| D1 | 新增预算档模型 `RunBudget`（类型化，字段见第三节）。**分两层取值：共用层**（task / episode / 拆解 / 模型请求的数值，评测与生产相同）写在 `pokemon_agent/config.py` 的默认预算档；**run 级与总量层**（`max_episodes`、`max_total_actions`、`wall_clock_s`）由运行场合覆盖：评测在配置文件的 `budget` 段里收紧，生产使用放开的取值。`RUN_MAX_EPISODES` 常量并入预算档，生产值恢复 50（`bcd4cc9` 改成 3 是为评测） | 评测与生产的差别只剩总量，评测测到的行为才代表生产；代价：生产的分层限制比现在严，见第七节 |
| D2 | 预算档只在唯一装配点构造并注入运行上下文（`RunRuntime`），模块内不读全局可变状态；brain 契约保持无状态，不加全局计数器 | 符合依赖注入原则 |
| D3 | deadline 用 `time.monotonic()` 的绝对截止点；对象 `Deadline(remaining() -> float)` 由装配点创建（run 开始时刻 + 总时长），经上下文传到 brain 门面（`direct/brain_tool.py`）与 harness | 单一时钟源，可在测试里替换成假时钟 |
| D4 | 每次模型尝试前：`allowed = min(该链路单请求上限, remaining() - 收尾预留)`；`allowed < 最小有用时长（默认 3 秒）` 则**不发请求**，抛类型化的 `BudgetExhausted`；provider 的 socket timeout 与总等待闸（现为 timeout+15）都取 `allowed`，不能只改 socket timeout | 修的是"剩 160 秒仍启动 435 秒请求" |
| D5 | 软停止：`remaining() <= 收尾预留`（60 秒）后，harness 不再派新 task / 新拆解，把 run 标 `time_exhausted` 并进入收尾。收尾路径**不得依赖模型**：run 摘要用机械摘要（已有字段拼接），保证 `run_end` 一定写出；若原本的收尾要调模型，则在软停止后跳过该调用并在 trace 里记明跳过原因 | "预留 60 秒"单独不保证收尾，必须同时去掉收尾的模型依赖 |
| D6 | 累计动作计数进入 run 状态，**不因成功重置**。单位：一次按键或一次脚本调用计 1（脚本内部按键不逐个计，沿用现状）。耗尽→`actions_exhausted` | 若需要限物理按键量，另定计量项，本项不做 |
| D7 | task 动作预算：模型给的 `max_steps` 取 `min(模型值, task_max_steps)`；越界**不静默**：clamp 并在该 task 的 trace 记 `budget_clamped`（原值、新值）；模型未给的用 `task_default_steps` | 不静默截断 |
| D8 | episode：任务数硬上限（`episode_max_tasks`，6）与拆解轮次上限（`max_decompositions`，2）；耗尽→episode 以 `tasks_exhausted` / `decompositions_exhausted` 结算，**失败**，并计入 run 的连续失败；这两项独立于数据集里冻结的 `max_steps=15`，数据不改 | 15 与运行预算分开 |
| D9 | 停滞规则本轮不动（task 5、episode/run 3），仅在文档里标明它们是辅助诊断、不承担累计预算职责 | 调低可能误伤合法菜单/对话，先回归再说 |
| D10 | 共用层的模型配置：规划/拆解 `plan_thinking=False`、`plan_max_tokens=4096`、单请求上限 45 秒（`BrainLlmConfig` 已有字段，改装配值）；模型尝试最多 2 次（含首发）且受 D4 约束。**生产也使用这组值**（不再保留 `PLAN_THINKING=True` / 65536 / 420 秒 / 3 次的现行值） | 关思考后"空 JSON"失败模式随之消失（原先 65536 就是为它加的）；代价：生产的规划/拆解质量可能变化，由重建的基线量出来；需要长推理的任务以后另开显式、受限的推理档，不是默认 |
| D11 | 起始数值（**待验证**）。共用层：`reserve_s=60`、`episode_max_tasks=6`、`max_decompositions=2`、`task_default_steps=8`、`task_max_steps=12`、`min_request_s=3`。评测覆盖：`wall_clock_s=600`（与样本硬终止一致）、`max_episodes=3`、`max_total_actions=60`。生产：`wall_clock_s=None`、`max_episodes=50`、`max_total_actions=None`。共用层数值写在 `config.py`，评测覆盖写在配置文件的 `budget` 段 | 改数字只改配置 |
| D12 | 请求开始/结束/取消事件与关联 ID（定位"卡在哪一链"）涉及 trace 落点与结构，**必须先与用户商定**，本版不实现，列入第七节 | trace 落点须与开发者商谈 |
| D13 | `state_schema_hash` 若因新增状态字段变化：**立即停下报告**，由我决定是否接受并重建存档；不自行重建 | hash 是存档兼容的哨兵 |
| D14 | **统一的配置入口**：唯一装配点 `build_real`（`pokemon_agent/build.py`）新增入参 `config: str \| Path \| None = None`（运行配置文件路径；None=默认档）。文件是 JSON，顶层按段组织，本项只有 `budget` 段：`{"budget": {"wall_clock_s": 600, "max_episodes": 3, "max_total_actions": 60}}`；**只写要覆盖的字段**，其余取共用层默认；未知字段与类型错误在装配期就报错（`extra="forbid"`），不静默忽略。解析函数 `load_run_config(path) -> RunConfig`（类型化，放在 `pokemon_agent/config.py` 同层的配置模块，不放进 brain/world），`build_real` 只把解析出的 `RunBudget` 递给各层，仍是"装配点只递裸字段"。**本项不新增命令行入口**：仓库当前没有通用起跑脚本，`build_real` 的调用方只有评测 worker 与数据集打包脚本；等将来有了起跑入口，它只需把 `--config` 透传给 `build_real(config=…)`（2026-10-14 裁决：不新增 `python -m pokemon_agent`，那是另一项产品面决定）。评测不再自己拼预算：`evals/config.json` 的 `budget` 段在评测启动时被写成报告目录下的 `run_config.json`（逐字节落盘），`RunOneRequest` 携带这个文件的路径，worker 把它交给 `build_real(config=…)`；`baseline_context.json` 记录该文件路径与 sha256，视觉删除前后两次基线用同一文件即证明同口径 | 评测与生产走同一条读取路径；配置文件是可复现、可哈希的证据；段结构为以后收纳别的实验旋钮留口，但本项不迁移任何现有参数 |

## 三、`RunBudget` 字段

`max_episodes`、`max_total_actions`、`episode_max_tasks`、`max_decompositions`、`task_default_steps`、`task_max_steps`、`wall_clock_s`（None=不限）、`reserve_s`（收尾预留）、`min_request_s`、`brain_max_attempts`、`plan_thinking`、`plan_max_tokens`、`plan_timeout_s`。

| 层 | 字段 | 评测 | 生产 |
|---|---|---|---|
| 总量 / run 级（可不同） | `wall_clock_s` | 600 | 不限 |
| | `max_episodes` | 3 | 50 |
| | `max_total_actions` | 60 | 不限 |
| 共用层（必须相同） | `reserve_s` / `episode_max_tasks` / `max_decompositions` / `task_default_steps` / `task_max_steps` / `min_request_s` | 60 / 6 / 2 / 8 / 12 / 3 | 同左 |
| | `plan_thinking` / `plan_max_tokens` / `plan_timeout_s` / `brain_max_attempts` | 关 / 4096 / 45 / 2 | 同左 |

**B1 的验收不再是"行为逐字节不变"**（共用层让生产变严了），而是：预算档值与上表一致、评测覆盖只改总量三项、`build_real(config=…)` 是唯一读取配置文件的地方。

## 四、步骤（每步一个提交；动手前都要三项检查全绿）

| 步 | 内容 | 提交信息 |
|---|---|---|
| B1 | `RunBudget` 模型 + 共用层数值 + `load_run_config` + `build_real(config=…)` 入参（D14，不含命令行入口） + 装配点注入（含把模型配置值接入既有的 `plan_thinking` / `plan_max_tokens` / 单请求上限 / `BRAIN_MAX_ATTEMPTS` 装配）+ `RUN_MAX_EPISODES` 并入预算档、生产值 50 + 测试（档的取值与上表一致；评测覆盖只改总量三项；字段校验）。本步只放数值与注入，限制的执行在 B2/B3 | `feat(budget): 2026-10-14（453）—— 引入分层运行预算档与共用层数值` |
| B2 | deadline 贯穿：`Deadline` 对象、brain 门面每次尝试前取 `allowed`、provider 接受单次 timeout 覆盖（含总等待闸）、`BudgetExhausted` 类型化错误；测试用假时钟：剩余不足不发请求、重试受剩余限制、生产档（无 `wall_clock_s`）不设 deadline、行为不变 | `feat(budget): 2026-10-14（454）—— 模型请求与重试受剩余时间约束` |
| B3 | 计数与收尾：累计动作、task clamp + `budget_clamped` 记账、episode 任务数与拆解轮次上限、软停止、机械收尾保证 `run_end`；测试覆盖每个耗尽原因都得到 `run_end` 且不调模型 | `feat(budget): 2026-10-14（455）—— 累计预算与确定的收尾路径` |
| B4 | 评测接线：`evals/config.json` 加 `budget` 块（总量三项覆盖）；评测启动时写出报告目录下的 `run_config.json`；`RunOneRequest` 增加该文件路径字段，worker 传给 `build_real(config=…)`；`baseline_context.json` 记录该文件路径与 sha256；样本硬终止仍 600 秒；文档与 CHANGELOG | `feat(evals): 2026-10-14（456）—— 短目标评测使用独立预算档` |
| B5 | 无模型端到端冒烟：假时钟 + 脚本化假 provider，演示"拆解卡住 → 软停止 → 机械收尾 → `run_end` 写出"，以及累计动作耗尽；证据目录 `eval_results/budget_smoke_<HEAD前七位>/` | 不提交代码，只提交证据说明时另给提交信息 |

CHANGELOG 编号按提交时仓库最新编号顺延（上表为预估，以实际为准）。

## 五、测试清单
档取值与第三节表一致；`load_run_config`（只覆盖所写字段、未知字段与类型错误报错、缺文件报错、`None` 取默认档）；`build_real(config=…)` 把解析结果递给各层；评测写出的 `run_config.json` 与 worker 读到的逐字节一致；`Deadline`（假时钟）；`allowed` 计算与"不发请求"；重试受剩余约束；provider 单次 timeout 覆盖含总等待闸；`BudgetExhausted` 被 harness 捕获并转为结算；累计动作不因成功重置；task clamp 记账；episode 任务数/拆解轮次上限；软停止后无模型调用的机械收尾；`run_end` 在每个耗尽原因下都存在；`state_schema_hash` 断言。

## 六、停止条件（任一出现就停下汇报，不重试、不绕过）
- `state_schema_hash` 变化（D13）。
- 需要修改 brain 的无状态契约（`brain/interface`）或 trace 事件结构才能实现。
- 收尾路径无法做到不依赖模型。
- 任何测试失败；起点 pytest/ruff 不绿。
- 任何真实模型调用的需要（本项全部步骤都不得调用真实模型）。
- 别的会话在做的未提交改动与本项文件重叠。

## 七、需用户确认
1. （**已确认 2026-10-14**）共用层数值与"软停止留 60 秒"是否接受（D11，改配置即可）。
1a. （**已确认 2026-10-14，用户要求评测与生产除 run 级与总量外一致**）**生产行为变严**：规划关思考且输出 4096、task 最多 12 步、episode 最多 6 个任务和 2 轮拆解、模型最多 2 次尝试。长路线或需要深度推理的生产任务可能因此被拆得更碎或提前结算；若不接受，把对应字段改成"评测与生产分设"即可，代码结构不变。
2. D12：请求生命周期事件是否现在做、trace 落点放哪（建议另开一项，先出方案再实现）。
3. 第五例评分口径：见 `docs/eval/` 另案（模型评分器没拿到"历史里出现过 dialog_text"的证据，而成功判据要求它）。

## 八、非目标
商店柜台误判与执行偏航（另案，需回归材料）；评分规则与真值；停滞阈值；视觉删除。
