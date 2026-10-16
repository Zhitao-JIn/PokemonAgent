# plan —— 测评体系 v1
> 视觉感知档已于 2026-10-16 删除，见 docs/perceive/remove-vision-spec.md；本文为历史记录，正文未改。

> 流程位置：intent.md → spec.md → **plan.md** → PR → production
> 依据：`docs/eval/spec.md`（09-25 晚定稿：S1～S10、W1～W4、红线 R1～R3）｜ 起草：2026-09-25 ｜ 状态：**草案，待确认**（§三 的 D1～D4）

---

## 〇、排序原则

1. **先 world、后 evals**：机械判定要读的真值（`ram` 对象、战斗字段）来自 world，world 不先改好，evals 写了也没东西可读。
2. **先记录、后切换**：world 先把新数据**记进 trace 而不改行为**（E2），拿一次真机数据看清楚，再切字段来源（E3）。
   这样每次切换前都有数据，不盲改。
3. **每步独立可验**：结束时 `pytest` 全过；动到 world / harness 的步骤另跑一次 `check_harness`（真机），`node_io` 全过。
4. **每步 = 一条 CHANGELOG 编号条目**；被测系统（`pokemon_agent/`）与 `evals/` 分开提交；commit 等你说再做。
5. **测试只写 spec S8 那两类**：解析层回环测试（E5）、机械判据正反例（E7）。现有测试随行为改动同步改，不另加（加的话按 D3 先问）。
6. **不改 ROADMAP**；活文档（`docs/spec/`）在各步末尾同步，`AGENTS.md` / `CLAUDE.md` 的文字留给你看。

## 一、步骤总览

| 步 | 内容 | 改谁 | 依赖 |
|---|---|---|---|
| E0 | 探测（不改代码）：补测没进过的界面、核战斗字段地址与敌方名字来源、定覆盖判定规则 | 无 | — |
| E1 | W1：战斗状态框改读游戏变量；`perceive_screen.md` 删状态框读法；下游同步 | world、prompt、tasks.py | E0 |
| E2 | 解码修两处 bug + 覆盖判定 + trace 加 `ram` 对象（**只记录，不改字段来源**）；跑一次真机拿数据 | world、trace 渲染 | E1 |
| E3a | **已撤销（09-26）**，由两层读数分工取代（见 spec 〇）。原：W4 切换（看档路径）：已覆盖帧的对话 / 选项 / 光标 / 叠加层改用解码；`perceive_screen.md` 与 `screen_state.py` 收窄 | world、prompt | E2 |
| E3b | **已撤销（09-26）**：task 层不补视觉，给整屏原样由模型读（见 spec 〇）。原：W4 盲区帧（task 层）：未覆盖帧是否补一次视觉——**按 E2 数据由你定（D1）** | world / harness | E2、D1 |
| E4 | W3：`run_entry` 加"只存 run 级档、不进图"的开关 | harness | — |
| E5 | 读侧解析层：`tools/trace/` 每种账一个类型化模型 + `parse(event)` 出口 + 回环测试 | tools/trace | E2 |
| E6 | `evals/` 骨架 + 数据集 v1：打包 20 条 run_begin 存档、写 `samples.jsonl` 与覆盖表 | evals | E4、E1 |
| E7 | 机械判据：20 条各一个判据函数（优先游戏变量）+ 正反例测试 | evals | E5、E6 |
| E8 | 批跑 + 报表：runner、红线、rubric、judge 一致性、感知一致率、bad case、diff | evals | E7 |
| E9 | 第一份跑通报告（k=1）+ 三项标定 | 无（只跑） | E3a、E8 |
| E10 | 活文档同步与收尾 | docs | E9 |

---

## E0 探测（不改代码）

产出 `docs/eval/p0-findings.md`，内容与做法：

1. **补测解码盲区**：起名键盘、PC 箱子、进化 / 学招式、标题画面、城镇地图。手上存档进不去的界面，用 `capture_manual_play.py` 手动玩到那里存档再测；
   每个界面按 spec W4 的表归类（归解码 / 交回视觉 / 修解码）。
2. **覆盖判定规则原型**：spec W4 的规则（屏幕上有字表文字却不在对话框和光标框里，或有光标却切不出选项 → 未覆盖），
   在 09-25 已测的全部界面 + 第 1 条新测的界面上跑一遍。验收：已覆盖界面**零误判为未覆盖**，盲区界面**全部判为未覆盖**。
3. **战斗字段来源**：HP / 最大 HP / 等级 / 状态的地址已在 `capture_manual_play.py` 编译验证过，只核"战斗中读数与画面一致"；
   对手名字二选一（D4）：内存里的对手名字字段（地址待编译验证）或种类号查名字表。
4. **两处解码 bug 的修法**：对话框被小菜单压住时怎么截断；价格 `¥` / 数量 `×` 挂到上一项还是另出字段——给出修法与样例，E2 照做。

**验收**：`p0-findings.md` 写完，你看过。

## E1 W1：战斗状态框改读游戏变量

- `world/ram.py` 登记地址（我方 `wBattleMon*`、对手 `wEnemyMon*`、状态），`pyboy_world.py` 两条路径在战斗标志非 0 时填具名字段：
  `my_hp` / `my_max_hp` / `my_level` / `my_name` / `my_status`、`foe_*` 同名一组；`Facts` 增加这些具名字段。
- `world/prompts/perceive_screen.md`：删第二节战斗状态框的读法（HP 五档、等级、名字、状态异常）与输出样例里的这些键；
  scene=battle 的判定保留。`screen_state.py` 的视觉输出契约同步删这些键。
- 下游：`tools/prompts/calls/judge_success.md` 里 HP 挡位的说法改成数值；`schemas/memory/datastore/act_memory.py` 的 `Facts` 快照同步具名字段；
  `experiment/tasks.py` 的 `catch_weaken_target` 判据改成"`foe_hp` 比历史里那几步小"。
- `observation_check` 的评测范围里去掉这几个字段（不再是视觉的职责）。

**验收**：`pytest` 全过；`check_harness` 真机一局，战斗帧的 HP 字段与画面一致、视觉输出里不再出现这些键。

## E2 解码修 bug + 覆盖判定 + trace 加 `ram`（只记录）

- `world/screen_text.py`：按 E0 第 4 条修两处 bug；加覆盖判定（E0 第 2 条的规则），`ScreenText` 增加 `covered: bool`。
- `sense_frame` 的正文加 `ram` 对象（spec W2）：`in_battle`、`text_source`、`menu`（`wCurrentMenuItem` / `wMaxMenuItem` / `wTopMenuItemX`）、
  金钱、背包内容、队伍数量与每只 HP / 最大 HP / 状态。**本步 `text_source` 如实记现状**（看档路径 = `vlm`，内存档路径 = `decode`），
  另记 `would_be`（按 W4 规则切换后会是哪边），供 E3 前看数据。
- 为了给 E3a 当闸门：看档路径上这一帧**解码出的文字也一并记进 `ram`**（`decoded_dialog` / `decoded_options` / `decoded_cursor`），
  和视觉给的并排——E3a 切换完成后删掉这三个字段。
- 同步：`tools/trace/render.sense_frame`、`real_check/node_io.py` 的正文契约、`docs/spec/DATAFLOW.md` / `docs/spec/trace/SPEC.md` 的事件表。
  （这是 trace 结构改动，字段清单即 spec W2，已经你确认。）
- **跑一次 `check_harness` 真机**（尽量走到菜单、商店、战斗、队伍列表），统计写进 `p0-findings.md`：
  1. 看档帧上解码与视觉的逐项分歧，分歧帧看 `frame` 截图裁决谁对——这是 E3a 的闸门（取代 spec 里"406 帧闸门"：那批标注没存屏幕缓冲，解码没法在上面重跑）；
  2. 未覆盖帧占全部帧的比例，分 task 层 / 看档层——这是 D1 的依据；
  3. 目标局终帧、run 终帧在 trace 里存在且与 judge 看的是同一帧（spec §七 的 P0 项）。

**验收**：`pytest` 全过；`node_io` 全过；三项统计写进 `p0-findings.md`。

## E3a W4 切换（看档路径）

**前提**：E2 闸门——已覆盖帧上，解码的对话 / 选项 / 光标不比视觉差（分歧帧里解码错的不多于视觉错的）。不满足就先回 E2 修解码。

- `pyboy_world.py` 看档路径：已覆盖帧的 `dialog_text` / `options` / `option_lines` / `cursor` / `option_layout` 用解码，`overlay` 由解码推出；
  未覆盖帧照旧用视觉。删掉"视觉说有对话框却没抄出字就降级"那段自洽修补。`ram.text_source` 改为按帧如实记。
- `perceive_screen.md`：删对话框与黑边的区分、选项框抄写、`overlay` 判定；这些键**只在未覆盖帧需要**——
  按 prompt 规则"同一信息不两处传"，改为由调用方在未覆盖帧上换用一份"含文字字段"的模板，已覆盖帧用只含 `scene` / `overview` 的模板
  （两份模板都住 `world/prompts/`；具体拆法在本步定，拆完给你看）。
- `screen_state.py` / `parse_screen` 按两份模板的输出收窄。删 E2 临时加的 `decoded_*` 三个字段。

**验收**：`pytest` 全过；`check_harness` 真机一局，`node_io` 全过；已覆盖帧的视觉输出不再含文字字段。

## E3b 盲区帧（task 层）—— 待 D1

task 层现在每键只走内存档。E2 统计出 task 层未覆盖帧的占比后，你在两条里选：
(a) 未覆盖帧补一次视觉（只要文字四项的那份模板）；(b) 不补，task 层在这些界面上文字为空，`text_source` 记 `none`。
选 (a) 改 `pyboy_world._ram_observe` 与对应 task 感知单元；选 (b) 本步只补 trace 的 `none` 取值。

## E4 W3：只存档不进图

- `run_entry.new_run` 加一个开关（如 `checkpoint_only: bool = False`）：存完 run 级档、记 `checkpoint_save` 后直接返回，不进 run 图、不记 `run_end`。
  开关从 `build_real` 之外的调用方传入（`RunHarness.run` 的参数），装配点不动。
- 用法：`evals/dataset/pack.py` 调它打包；其余调用方不受影响。

**验收**：`pytest` 全过；打包出的存档用 `restore_run` 能恢复并跑完（`check_checkpoint.py` 的 run 级路径加一个"从只存档的存档恢复"场景）。

## E5 读侧解析层

- `tools/trace/` 下每个 `TraceKind` 一个 content 模型，与 `render.py` 各渲染函数一一对应；`parse(event) -> 类型化事件` 为分派出口，
  由 `tools/trace/__init__.py` 导出。覆盖范围按 spec §八（eval 用得到的先做，其余后补），含 E2 新加的 `ram`。
- 测试（S8 第一类）：每个已覆盖的 kind 一条"渲染 → 落盘 → 解析 → 字段相等"。
- `real_check/node_io.py`、`checkpoint/restore.py` 里手写 `json.loads` 摸字段的地方**本步不改**，登记为后续可选。

**验收**：`pytest` 全过（含新回环测试）。

## E6 `evals/` 骨架 + 数据集 v1

- 目录按 spec §三建：`schemas/`、`dataset/`、`runner/`、`checks/`、`rubric/`、`process/`、`report/`、`cases/`、`cli.py`；每个子包一个出口。
- `evals/schemas/`：`EvalSample` / `SampleStart` / `RubricItem` / `RubricLevel` / `RedLine` / `CheckVerdict` / `SampleResult` / `Report*`（spec §四、§七、§十）。
- `dataset/pack.py`：20 条任务，每条 = 钉死 `.state` + `Task(goal, success_criteria, max_steps)` → E4 开关打包成 run_begin 存档，
  拷进 `evals/dataset/v1/checkpoints/<sample_id>/`，算哈希。
- `dataset/v1/samples.jsonl`：每条补齐 `category`、`behavior`、`check_id`（E7 的函数名；写不出机械判据的留 None）、`rubric`（spec §七 三条 + 锚点）、`red_lines`、`k_metric`、`split`（D2）。
- `dataset/v1/coverage.md`：类别 × 记忆状态 × 难度覆盖表；v1 记忆状态全是"空记忆"，照实写。
- `dataset/loader.py`：读 + 哈希校验，对不上即拒。

**验收**：`python -m evals dataset check` 20 条全过校验；任选一条存档用 `restore_run` 真机起跑一局。

## E7 机械判据

- `evals/checks/rules/` 按类别分文件，每条判据一个纯函数 `check_xxx(stream: RunStream) -> CheckVerdict`，`registry.py` 注册。
- **优先写成游戏变量**（spec §二推论）：买成功 = 金钱减少且背包该物品数量加一；治疗 = 队伍每只 HP 等于最大 HP；打出招式 = 对手 HP 下降；
  扔球 = 背包精灵球少一个；逃跑 = 战斗标志归 0；进门 = `map_id` 变化；走到某格 = 坐标。对话 / 菜单类用解码文字，`text_source=vlm` 的帧记 unjudgeable。
  逐条写法在 `samples.jsonl` 的 `check_id` 与判据 docstring 里各记一份对照表（哪条读哪个变量）。
- `RunStream`：用 E5 的解析出口，按 `meta` 切 run / episode / task 三层流（切法同 `node_io`），给出"目标局终帧""run 终帧"两个取帧函数。
- 测试（S8 第二类）：每条判据一个正例一个反例，手工构造事件流；反例优先取 `docs/experiments/0827-knowledge-baseline.md` 记录过的真实误判。

**验收**：`pytest` 全过；20 条里可机械判定的条数写进 `coverage.md`。

## E8 批跑与报表

- `runner/batch.py`：spec §六（拷存档进工作目录 → `restore_run` → 关模拟器）；开跑前写 `header.json` 口径头。
- `report/`：红线 R1～R3（spec §七）→ 结果判定 → rubric（③ 冗余路由代码折档，① ② 生成人工打分表 `rubric_forms.md`）→
  judge 一致性（run / 目标局 episode 两层四格，task 层只出分布）→ 效率（按链路 token、调用次数、`call_failed`、按键数、局数、墙钟）→
  `results.jsonl` / `report.md`。
- `process/`：judge 一致性；感知一致率（视觉 `scene=battle` vs `ram.in_battle`；E3b 选 (a) 时再加未覆盖帧上视觉文字 vs `ram.menu` 光标项）。
- `cases/`：红线命中 / 机械 fail / judge FP、FN 追加进 `bad_cases.jsonl`，`triage=pending`。
- `cli.py`：`run` / `report` / `diff`（口径头不一致即拒）。

**验收**：用 E6 的一条样本真机跑通 `run → report`，报告各节都有数（k=1 区间列为 `n/a`）。

## E9 第一份跑通报告

- 20 条全跑，k=1，出 `eval_results/<id>/`。
- 三项标定，写进 `p0-findings.md` 的续篇：
  1. 每条样本的局数分布——若明显偏长，回到 spec S1 议是否给 `build_real` 加预算参数；
  2. 冗余路三项指标的分布——定 ③ 的 0 / 1 / 2 档阈值，冻结进 rubric 版本；
  3. 未覆盖帧占比（E3b 之后的实际值）。
- ① ② 人工打分表由你打；打完 `report` 重算一次。

**验收**：报告给你看；它**不作正式基线**（k=1）。

## E10 收尾

- `docs/spec/world/SPEC.md`（字段三档来源、`ram`）、`docs/spec/trace/SPEC.md`（`sense_frame.ram`、解析出口）、`docs/spec/experiment/SPEC.md`（与 `evals/` 的分工）、
  `docs/spec/DATAFLOW.md` 同步；新增 `docs/spec/evals/SPEC.md`（活文档，照代码写）。
- `AGENTS.md` / `CLAUDE.md` 需要改的地方列出来给你看，不直接改。

---

## 三、待你确认

| # | 问题 | 建议 |
|---|---|---|
| D1 | E3b：task 层未覆盖帧补不补视觉 | 等 E2 数据：task 层未覆盖帧占比低（如 < 5%）就补；高的话先看是哪些界面，再议 |
| D2 | 数据集 v1 的切分 | 20 条全部标 `val`，只用于跑通；WikiSkill 复现开始前按它的协议重切 train / val / test，发 v2 |
| D3 | 是否给 `tests/world/test_screen_text.py` 补两条用例（E2 修的两处 bug） | 补：它们是解码的用法示范，且防回退；不补则只靠 E2 的真机统计 |
| D4 | 对手名字来源 | 内存里的对手名字字段（E0 用编译验证法核地址）；核不上再退回种类号查表（表从 ROM 数据生成，住 `world/`，不 import `experiment/`） |

另：spec 原先写的"406 帧闸门"已改为 E2 的真机逐帧对照（那批标注没存屏幕缓冲，解码无法在上面重跑），spec 同步改过。
