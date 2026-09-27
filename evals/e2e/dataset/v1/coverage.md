# v1 覆盖表

类别 × 记忆状态 × 难度。v1 全部从 run 入口、空的任务 / 情景记忆起跑（知识库按批跑开关带或不带），难度未标定——第一批 k=1 结果出来后按成功率回填（plan E9）。

| 类别 | 条数 | 记忆状态 | 难度 | 可机械判定 | 样本 |
|---|---|---|---|---|---|
| battle | 7 | 空 | 未标定 | 6/7 | wild_encounter, battle_action_menu, battle_fight_menu, battle_move_select, battle_pokemon_switch, battle_item_use, battle_run_attempt |
| catch | 2 | 空 | 未标定 | 2/2 | catch_weaken_target, catch_throw_ball |
| center | 2 | 空 | 未标定 | 2/2 | pokemon_center_enter, pokemon_center_heal |
| dialog | 2 | 空 | 未标定 | 2/2 | npc_dialogue, dialogue_advance |
| movement | 2 | 空 | 未标定 | 2/2 | door_transition, movement_obstacle |
| shop | 5 | 空 | 未标定 | 5/5 | shop_interaction, shop_open_buy_menu, shop_select_item, shop_confirm_purchase, shop_cancel_purchase |

合计 20 条，全部 `split=val`；不可机械判定的样本：knowledge_battle_pokemon_switch（只看红线、judge 与 rubric）。

缺口（v2 再补）：非空记忆起点（`recovered_episode`）、多目标长程 run、`test` 切分。
