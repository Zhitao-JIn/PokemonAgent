# plan —— task 层按场合感知与机械接管：落地顺序

> 流程位置：intent.md → spec.md → **plan.md** → PR → production
> 状态：**已定**（2026-09-26），按期落码
> 依据：`spec.md`（第十三节 1–4 已定）。回放已随 checkpoint 改为图内恢复删除（CHANGELOG 279），本 plan 不再有回放相关条目。每期结束：`ruff format` + `ruff check`、现有 `pytest` 全绿、跑本期列出的测评，
> 写一条 CHANGELOG；同期同步 `docs/spec/**` 里受影响的活文档（它们描述"现在"，必须跟代码走）。
> **不提交**（等开发者说）；ROADMAP / AGENTS.md / CLAUDE.md 不动。

---

## P0 —— 前置（不改运行时代码）

| # | 做什么 | 产出 | 验收 |
|---|---|---|---|
| 0.1 | 开发者核对 v2 读屏数据集（核对页已发），回写标注、`label_checked=True` | `evals/screen_reading/dataset/v2/` 冻结 | 跑 `python -m evals screen run --version v2`，得到第一份真分数 |
| 0.2 | 补测 spec 第十三节第 5 条：学新招整条流程（需一份能触发的存档）、其它商店图块集、PC 存入 / 丢弃按 B 路径、飞天选目的地、学招机 / 进化石画面流 | `p0-findings.md` 第七节 | 每项写明实测结论；测不到的在 spec 里降级或删掉 |

## P1 —— 场合与 `TaskObservation`

| # | 改哪里 | 做什么 |
|---|---|---|
| 1.1 | `world/interface/domain/task_scene.py`、`task_observation.py`（新增）；`world/interface/domain/__init__.py`、`world/interface/__init__.py` 出口 | `TaskScene`、`TaskObservation`、`TaskPerceived`；契约先行，**先给开发者看再往下写** |
| 1.2 | `world/scene.py`（新增） | 原型 `evals/screen_reading/classify.py` 的 `classify` / `at_start` 迁入，入参换成 world 自己的 `ScreenText` + 内存 |
| 1.3 | `world/interface/world_port.py`、`world/pyboy_world.py` | `WorldPort.perceive_task()`；`_ram_observe` 改产 `TaskObservation`，`walk_map` / `screen` 互斥；删掉 `perceive_once` 的 `ram_only` 档 |
| 1.4 | `tools/interface/ports.py`、`tools/game_tools.py` | `GameToolPort.perceive_task()`；task 档另立响应信封（`schemas/harness/communication/` 新增一个 `…PerceiveTaskResp`） |
| 1.5 | spec 第四节第 0 小节列出的 task 层消费方 | 换型为 `TaskObservation`；`ActMemory` 前后帧换型、历史渲染照旧保留 `screen` |
| 1.7 | `evals/screen_reading/` | `classify` / `at_start` 改用 `world/scene.py`；删原型 |

**验收**：读屏测评在 v2 上场合与初态的分数与原型一致；`tests/test_task_layer.py` 等现有测试过（受换型影响的测试要改，**改测试前先问**）；
真机短跑一个 task（走路 + 对话），trace 里 `sense_frame` 带 `scene`。
**活文档**：`docs/spec/world/SPEC.md`、`tools/SPEC.md`、`DATAFLOW.md`。

## P2 —— 宏骨架 + 商店 + 起名

| # | 改哪里 | 做什么 |
|---|---|---|
| 2.1 | `world/interface/domain/`：`macro_spec.py`、`macro_outcome.py`、`takeover_view.py`（新增） | `MacroSpec`、`MacroOutcome`（`status` / `reason_code` 闭集 / `summary` / `steps`）、各接管视图；**契约先给开发者看** |
| 2.2 | `world/macros/engine.py`（新增） | 回初态（等稳定、`at_start`、按 B、上限）→ 校验 → 逐步核对 → 收尾；私有常量 `STABLE_POLLS` 等 |
| 2.3 | `world/macros/shop.py`、`naming.py`（新增）；名字表从 `experiment/observation_check/id_tables/` 搬入 world | `buy` / `sell` / `quit`、`enter_name`；`ShopItemsView`、`NamingView` |
| 2.4 | `WorldPort.run_macro`；`ActionSpace.macros`；`GameTools.execute` 分派 + `…ExecuteResp`（新增） | 开放按键的场合照旧键掩码，仅开放脚本的场合给宏签名 |
| 2.5 | `brain/interface/domain/action.py`（`Action.macro`、新增 `MacroCall`）；`brain/brain.py::_parse` | 解析宏调用，只查名字与参数类型 |
| 2.6 | `schemas/harness/domain/trace_kind.py`（`RUN_MACRO`）；`tools/trace/render.py`；`harness/task/act/act.py` | 宏走一次 `execute`，记 `run_macro`；决策预算 +1 |
| 2.7 | `FromHarnessToBrainToolChooseOnceReq.last_macro`；`tools/prompts/decide_action.py` + 模板 | 仅开放脚本的场合渲染视图与宏签名；上一宏结果放观测之后 |
| 2.8 | `evals/macros/`（新增） | 从存档调 `buy` / `sell` / `enter_name`：成功、被拒（钱不够、数量越界、名字非法）、从数量框 / YES/NO / 已打字中途开跑 |

**验收**：宏测评全过；真机跑"去商店买 5 个精灵球"一个 task，trace 里一条 `run_macro`。
**活文档**：`world/SPEC.md`、`tools/SPEC.md`、`brain/SPEC.md`、`harness/SPEC.md`、`checkpoint/SPEC.md`、`DATAFLOW.md`、`schemas/SPEC.md`。

## P3 —— 战斗

| # | 改哪里 | 做什么 |
|---|---|---|
| 3.1 | `world/macros/battle.py`（新增） | `fight` / `switch` / `use_item` / `run`、`send_out`；`BattleMenuView`、`FaintSwitchView` |
| 3.2 | `world/macros/engine.py` | 自动推进战斗文字：等稳定 → 按 A；遇任意 `▶`、战斗标志清零、`ADVANCE_LIMIT` 即停 |
| 3.3 | `evals/macros/` | 野战出招到战斗结束；倒下换人；战斗中用伤药；逃跑；自动推进遇到 "Use next POKéMON?" 必须停 |

**验收**：宏测评全过；真机打一场野战，JEV 调用只发生在 `battle_menu` / `faint_switch`。

## P4 —— PC、背包、队伍、学新招

| # | 改哪里 | 做什么 |
|---|---|---|
| 4.1 | `world/macros/pc.py`、`bag.py`、`party.py`、`learn_move.py`（新增） | spec 第五节表里其余的宏与视图 |
| 4.2 | `evals/macros/`、`evals/takeover_views/`（新增） | 每个宏三例；初态帧视图逐帧核对 |

**验收**：宏测评、视图测评全过；`learn_move` 若 P0.2 没拿到存档，本期只落代码框架并在 spec 标"未验证"。

## P5 —— 收尾

| # | 改哪里 | 做什么 |
|---|---|---|
| 5.1 | `tools/prompts/` 与决策 / 判定模板 | "屏幕怎么读"抽成共用片段，两处引用 |
| 5.2 | `harness/task/perceive/store_object_semantic_memory/rules.py` | 对话闸门改为"这一帧的文字读过" |
| 5.3 | `docs/spec/OVERVIEW.md`、`README.md` | 登记新模块（`world/scene.py`、`world/macros/`）与测评文件夹 |
| 5.4 | 端到端 | `python -m evals e2e` 批跑一轮，与改前一轮对比 |

## 风险与回退

- **换型面大（P1）**：`TaskObservation` 牵动约十个文件；先加新类型、task 层逐个切，episode 层不动，任何一步可停。
- **宏卡死**：`REWIND_LIMIT` / `STEP_TIMEOUT_FRAMES` / `ADVANCE_LIMIT` 兜底，超限返回 `aborted` 并回初态，不抛异常；真机跑时看 trace 明细调常量。
- **旧存档读不回**：P1 起 task 层状态换型，`state_schema_hash` 变了，此前的 checkpoint 一律拒载（`CheckpointIncompatible`）。

## 已定（2026-09-26，开发者："按你的建议来"）

1. 分期与顺序 P1 → P5。
2. 受换型影响的现有测试随各期一起改，不再逐期问；新写的单元测试仍按范式另问。
3. `evals/macros/`、`evals/takeover_views/` 是测评，直接建。
4. "契约先给开发者看"改为：契约随代码落地，逐项写进当期 CHANGELOG，开发者事后审。

## 进度

| 期 | 状态 | CHANGELOG | 未做 |
|---|---|---|---|
| P0 | 待开发者 | — | 0.1 数据集核对；0.2 补测 |
| P1 | ✅ 代码落地（读屏测评已改用 `world/scene.py`） | 287 及之前 | 真机短跑一个 task |
| P2 | ✅ 代码落地，宏测评 21 例全过 | 288、289 | 真机跑"去商店买 5 个精灵球" |
| P3 | ✅ 代码落地，战斗 20 例宏测评全过 | 290 | 真机打一场野战；训练家对战（无存档） |
| P4 | ✅ 代码落地，宏测评 75/75、视图测评 8/8；学新招用改内存 + RARE CANDY 造了存档 | 291 | FLY 选目的地；真机跑 |
| P5 | 5.1–5.3 已完成 | 292–293 | 5.4 端到端（需真实模型，留给开发者） |
