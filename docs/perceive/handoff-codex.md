# Handoff —— perceive 收尾（给 Codex）

> 日期：2026-09-27 ｜ 上一棒：Claude（额度用完）｜ 仓库根：`Pokemon_Agent/`

## 0. 必须遵守的规矩（开发者定的，别破）

- **不提交**：任何 `git commit` / push 都要等开发者明说。
- **ROADMAP / AGENTS.md / CLAUDE.md 不动**（只有开发者改）。
- **每次改动写一条 CHANGELOG**（顶部追加，编号递增，格式照 288–291：改了什么 / 为什么 / 取舍 / 影响面）。
- 代码注释只在三处：文件头、函数头、步骤标记（`# 步骤 1：…`）。不写"为什么这样改"的行内注释——原因写 CHANGELOG。
- **新写单元测试要先问开发者**；受改动影响的现有测试可以随手改。测评（`evals/`）可以直接建。
- 文档只保留**最终版**，不写修改记录。
- 不跑真实模型调用（花钱）；真机验证留给开发者。
- 编码范式见 skill `ai-coding-paradigm`（契约先行、信封 `From…To…Req/Resp`、模块只经 tools 层互相依赖、统一出口懒加载、assert 执行契约、ruff format + check）。
- 避免奇怪的 shell 命令（开发者拒过一次 `find`）。git 读操作加 `GIT_OPTIONAL_LOCKS=0`，否则会残留 `.git/index.lock`。

## 1. 怎么验证

- 单测：仓库里 `pytest -p no:cacheprovider -o addopts="--basetemp=.pytest_tmp" -q`，当前 **226 passed**。
- 格式：`ruff format pokemon_agent evals` + `ruff check pokemon_agent evals`（全绿）。
- 宏测评：`python -m evals macros run` → **75/75**（约 15 秒，不调模型）。
- 视图测评：`python -m evals views run` → **8/8**。
- 读屏测评：`python -m evals screen run --version v2`（不给 `--model` 只算解码）→ 场合 1037/1037。
- world 自持核对：`python scripts/check_world_self_contained.py` → 三条全过。

## 2. 已完成（本轮）

整体方案：`docs/perceive/{intent,spec,plan}.md`；进度表在 `plan.md` 末尾。

| CHANGELOG | 内容 |
|---|---|
| 279–285 | checkpoint 重做（三级存档、图内恢复、无回放），`docs/checkpoint/` |
| 286 | perceive 文档去回放、plan 定稿 |
| 287 | P1：`perceive_task()` / `TaskObservation`（带 `scene`） |
| 288 | P2 world：宏骨架 `world/macros/engine.py`、商店 `buy/sell/quit`、起名 `enter_name`、接管视图 |
| 289 | P2 接线：brain `MacroCall`/`MacroSignature`/`Action.macro`；`GameTools._mask` 仅开放脚本的场合只给宏；`ExecuteResp.outcome`；`decide_macro.md`；`TaskState.last_macro`；`TraceKind.RUN_MACRO`；`evals/macros/` |
| 290 | P3：战斗 `fight/switch/use_item/run`、`send_out`；`MacroRun.advance`（只在 `▼` 或静止 300 帧时按 A）；停摆按宏结果比 |
| 291 | P4：`bag`（use/toss/close）、`party`（switch/field_move/stats/close）、`pc`（道具/宝可梦存取、change_box、log_off）、`learn_move`（forget/skip）；`macros/common.py`；`evals/takeover_views/` |

八个仅开放脚本的场合全部有宏与视图。关键文件：`pokemon_agent/world/macros/*.py`、`world/interface/domain/{macro_spec,macro_outcome,takeover_view}.py`、`world/scene.py`、`tools/game_tools.py`、`tools/brain_tool.py`（`Chooser`、`_signature`）、`tools/prompts/decide_action.py` + `calls/decide_action/decide_macro.md`、`harness/task/{act,plan_task,perceive/detect_stall.py,perceive/store_step_episode_memory.py}`、`tools/trace/{render,content,parse}.py`、`experiment/real_check/node_io.py`。
新存档都在 `experiment/experiment_states/macros/`（`player_keyboard / battle_low_hp / battle_faint_switch / field_two_mons / field_four_moves / learn_move`）。

## 3. 做了一半、还没写 CHANGELOG（第一件事先补上）

**P5.1 "屏幕怎么读"共用片段 —— 代码已改完、测试已过，缺 CHANGELOG 292 与活文档：**
- 新增 `pokemon_agent/tools/prompts/calls/read_screen.md`（`screen` 字符含义：`▶` / `▷` 上一层 / `▼` / `-` 空招式位 / `·`；字面内容以 `screen` 为准）。
- `tools/prompts/__init__.py` 新增常量 `READ_SCREEN = load("read_screen").text`（进 `__all__`）。
- `decide_action.md` 原来那段屏幕说明换成 `$read_screen`；`judge_success.md` 在"`场景` 字段可能是空的"那段后面加了 `$read_screen`；`decide_action.build_prompt` 与 `judge_success.build_prompt` 都传 `read_screen=READ_SCREEN`。
- 要补：CHANGELOG 292；`docs/spec/tools/SPEC.md` 的 prompts 表（`decide_action.py` / `judge_success.py` 行、目录树加 `read_screen.md`）。

## 4. 剩下的 P5（plan.md「P5 —— 收尾」）

1. **5.2 对话闸门**：`harness/task/perceive/store_object_semantic_memory/rules.py::_dialog_or_still`（约 140 行）现在 `if not press.after.perceived: return None`——task 层的帧 `perceived` 恒为 False，所以 task 层一条对话事件都记不下来。改成"这一帧的文字读过"：`TaskObservation`（task 层解码，文字可信）直接用 `facts.dialog_text`；episode 层 `Observation` 仍看 `perceived`。模块 docstring 第 42–45 行和函数 docstring 同步改。`rules.py` 的入参已是 `TaskObservation`。
2. **5.3 登记**：`docs/spec/OVERVIEW.md`、`docs/spec/README.md` 登记新模块 `world/scene.py`、`world/macros/`、`world/items.py`、`world/moves.py`，以及测评目录 `evals/macros/`、`evals/takeover_views/`。
3. **5.4 端到端**（`python -m evals e2e`）要调模型 → **不做**，留给开发者。
4. 完成后更新 `docs/perceive/plan.md` 进度表的 P5 行，写 CHANGELOG。

## 5. 已知限制 / 留给开发者的

- 真机（调模型）一次都没跑：P1 短跑 task、P2"去商店买 5 个精灵球"、P3 打一场野战、checkpoint 的 `check_checkpoint.py --record`。
- `field_move` 不支持 FLY（要在城镇地图选目的地）；招式学习器在 `bag.use` 里被拒。
- 训练家对战没有存档：禁逃、禁扔球只按 `wIsInBattle == 2` 写了前提，未实测。
- 除常青市以外的商店图块集未核（`scene.MART_TILESET`）。
- P0（v2 数据集人工核对、补测）归开发者。
- `TaskState` 结构改过多次，旧 checkpoint 一律 `CheckpointIncompatible`（预期内）。

## 6. 容易踩的坑（本轮实测得来）

- 战斗文字大多自己走、没有 `▼`；等稳定就按 A 会落在紧接着出现的行动菜单上替 JEV 选 FIGHT。推进文字一律走 `MacroRun.advance(stop)`。
- 换画面时有几百帧整屏空白，`classify_scene` 会判成 `walk`——停止条件只认光标 `▶`，别按场合判。
- 数量框在后续提示（"Is it OK to toss?" / "Threw away"）里一直画着；`wait_for` 的默认 advance 不按有数量框的帧，这些地方传 `advance=lambda t: not t.has_cursor`。
- PC 打开时 "Accessed …" 几句显示期间主菜单光标还在；换箱存档期间画面静止几百帧，用 `idle_until`。
- 球要等抓捕流程（含起名询问）走完才从背包扣。
