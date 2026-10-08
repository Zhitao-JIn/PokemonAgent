# draft —— world_script_execute v2 用例候选

> 流程位置：world-e2e-spec.md → world-e2e-plan.md W3 → **本草稿** → 用户勾选 → W4。
> 2026-10-08：W1/W2 已落地；v1 的 106 条期望和存档未改，尚未创建 v2。
> **口径更新**：以下是 31 项公开能力定案前的旧实现候选与实测证据，不是当前公开 v2 清单。
> 按 world-e2e-spec.md §2.1–2.3 与 plan W5/W6/W3 重新迁移；shop_buy/shop_sell、circle_walk 等内部名不进入公开数据集。

---

## 一、已完成的核验

- 修复前 P0：105/106，仅 `takeover:switch_from_party_list` 失败。
- 修复后 battle_switch 四条各两轮通过；v1 最终全量两轮 212/212，sample error 0，无 flaky。
- `pass` 的 script 分组保留，新增独立 `kind_accuracy` 指标；实测两组均为 1.0。
- 源码目录实际有 **39 个脚本**，其中 38 个出现在 v1。C1 缺成功用例的有三个：
  `wait_until_scene`（无用例）、`party_field_move`（只有失败）、`pc_withdraw_pokemon`（只有失败）。
- 完整声明覆盖与失败码缺口见 [world-v2-coverage.md](world-v2-coverage.md)。覆盖不足时退出 1。
  失败出口登记在 `evals/dataset/world_script_execute/build/failure_codes.py`，包括业务出口、透传与共享菜单引擎出口。
  这是保守的源码登记，不是可达性证明；共享恢复/超时出口仍需逐项核对能否用正常游戏存档构造。

## 二、已实测候选（尚未入集）

以下每条都从 v1 states 重起，两轮判定通过。`pre=[]`；真值都核 `delta={map_id:0,x:0,y:0}`。
这些输入拒绝用例补 C2；即时等待只覆盖已就绪分支，不代替真正过场等待。

| 勾选 | case_id / 脚本 | kind | 起点存档 | 参数 | 期望 ok / code | 依据 |
|---|---|---|---|---|---|---|
| 待选 | wait_walk_ready / wait_until_scene | success | knowledge/knowledge_movement_obstacle.state | scene=walk, timeout_s=1 | true / ok | 起点野外已就绪，waited_frames=0；地图坐标不变 |
| 待选 | wait_walk_timeout / wait_until_scene | failure | knowledge/knowledge_movement_obstacle.state | scene=battle, timeout_s=1 | false / timeout | 不按键不会进入战斗；地图坐标不变 |
| 待选 | face_invalid_direction / face_direction | failure | knowledge/knowledge_movement_obstacle.state | direction=invalid | false / rejected | 非法方向在按键前拒绝 |
| 待选 | adjacent_invalid_direction / walk_to_adjacent | failure | knowledge/knowledge_movement_obstacle.state | direction=invalid | false / rejected | 非法方向在按键前拒绝 |
| 待选 | circle_invalid_laps / circle_walk | failure | knowledge/knowledge_movement_obstacle.state | laps=0 | false / rejected | 圈数必须为正 |
| 待选 | buy_count_zero / buy_item | failure | knowledge/knowledge_shop_open_buy_menu.state | item=POKé BALL, count=0 | false / count_limit | 外层数量检查先于接管调用 |
| 待选 | sell_count_zero / sell_item | failure | knowledge/knowledge_shop_open_buy_menu.state | item=POTION, count=0 | false / count_limit | 外层数量检查先于库存检查 |
| 待选 | menu_invalid_target / open_menu_to | failure | knowledge/knowledge_movement_obstacle.state | target=invalid | false / rejected | 菜单目标不在支持列表 |

两条商店候选冻结前应再加 `delta.money=0` 及相应背包数量不变；已采集 RAM 可供核对。
原始记录：`eval_results/world_candidates_1008/results.json`、`candidates.jsonl`（本地产物）。

## 三、中途干扰候选

从 `knowledge/knowledge_wild_encounter.state` 起步，`pre=[]`；每个候选重起两轮。
脚本报告与独立 RAM 都保留在 `eval_results/world_candidates_1008/interrupts.json`。

| 勾选 | 脚本 | kind | 参数 | 期望 ok / code / 真值 | 实测与依据 |
|---|---|---|---|---|---|
| 待选 | circle_walk | interrupt | laps=30, extent=1 | false / battle_started；收尾 scene=battle，map 不变，RAM in_battle=true | 两轮一致；起点不在战斗，执行途中遇怪，未宣称完成绕圈 |
| 待选 | bounce_in_tall_grass | interrupt | steps=100 | **true** / battle_started；收尾 scene=battle，map 不变，RAM in_battle=true | 两轮一致；遇怪正是本脚本目标，必须保留成功语义 |
| 不入集 | walk_to_adjacent | interrupt | direction=north | 待重新采起点 | 两轮均 true/ok、RAM in_battle=false；没有干扰，不可计 C3 |
| 不入集 | walk_to | interrupt | x=起点x, y=起点y−10 | 待重新采路径 | 两轮均 false/not_converging、RAM in_battle=false；只能做失败候选，不能计 C3 |

circle/bounce 的候选 JSON 中最初探测用的自报期望只是探测占位；冻结应以本表和独立 RAM 定案，
尤其不能把 bounce 的 `ok` 写成 false。现有 bounce_encounter 是 success，原样保留；
新增 steps=100 与原 steps=30 使用同一存档，不能把重复路径数量当成泛化证据。

尚未通过实测的 C3 起点方案：

| 脚本 | 起点 / pre / 参数草稿 | 期望与依据 | 当前缺口 |
|---|---|---|---|
| walk_to_adjacent | 野外草丛、采在下一次方向键必遇怪之前；pre=[]，direction=north | false/battle_started；RAM 进战斗 | 现有 wild 起点第一步不遇怪，需新快照 |
| walk_to | 同上，目标选草丛内可达远格；pre=[]，坐标由起点地形确认 | false/battle_started；RAM 进战斗 | 现有向北远目标先不收敛，需核路径后采快照 |
| exit_map | 野外草丛且出口路径会经过草地；pre=[]，target_warp 为对应出口 | false/battle_started；地图未出、RAM 进战斗 | 需选择真实出口与新 RNG 起点 |
| heal_at_center | 中心站位途中的 NPC 自动对话触发帧；pre=[]，max_steps=200 | 对话/选项导致停止且尚未治疗；不可假称已回血 | 现有中心没有野生遇怪；护士正常 YES/NO 是业务确认，不算意外干扰 |
| talk_to_adjacent_npc | 可触发战斗或分支选单的相邻 NPC；pre=[]，direction 按位置填写 | false/battle_started 或 choice_presented；RAM/选单真值对应 | 现有研究所普通 NPC 不触发战斗，需新剧情存档 |
| advance_dialog | 选单尚未出现的 NPC 对话中段；pre=[]，max_presses=30 | false/choice_presented 或 battle_started；真值选单/战斗 | 起点已经有选项不能算中途干扰，需采前一框 |
| wait_until_scene | 自动战斗/自动对话启动前的过场；pre=[]，scene=walk, timeout_s=1 | false/timeout，收尾仍在战斗或对话；RAM 与读屏核对 | 脚本只 tick；稳定野外起点不可能凭空遇怪，需自动事件中的快照 |

这些是采集方案，参数和期望尚未完整核实，不能直接冻结为用例。缺口如实保留，不补虚假的 interrupt 标签。

## 四、其余 C1 / C2 缺口怎么收敛

| 缺口 | 起点 / pre / 参数草稿 | 期望 | 前置工作 |
|---|---|---|---|
| party_field_move success | 有实际可用野外招式的队伍；pre 打开队伍；pokemon/move 从 RAM 填 | true/ok 且对应世界效果 | 当前冻结队伍没有已验证的可用野外招式；需采游戏进度与招式 |
| pc_withdraw_pokemon success | 可存两只以上队伍的 PC 档；先存指定一只，再冻结；pre 打开 PC | true/ok，队伍增加、箱减少且名字对应 | 一次用例只调用一次脚本，不能把存与取合在被测调用里 |
| wait_until_scene 真正等待 success | 开门过场、稳定等待前的快照；pre=[]，scene=walk | true/ok，waited_frames>0，收尾地图/坐标对应 | 当前 start_world/pre 都会等待稳定，需在过场中采冻结帧 |
| 输入拒绝 / 错场合 | 原样复用现有存档，非法参数或适用场合外调用 | false，明确 code，地图/钱/背包/队伍均不变 | 按 coverage 表补每个脚本各自出口，不能按全局码合并 |
| no_pp / 队伍倒下 / 背包满 / PC 满 / 钱不足 | 真实游戏操作后冻结，不临时篡改 RAM | false，对应具名码，目标世界状态未变化 | 当前存档不足的先采集，不用期望迁就实现 |
| 恢复失败 / 稳定超时 / 终态复验失败 | 先核源码路径是否能在正常模拟器状态发生 | false，报告与世界真值一致 | 不为触发 defensive 分支捏造不可能的存档；不可达结论需记录依据后再讨论覆盖口径 |

本轮到草稿为止。W4 的 v2 复制、追加、默认版本切换仍未执行。
