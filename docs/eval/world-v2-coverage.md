| 脚本 | success | failure code: count | interrupt |
|---|---:|---|---:|
| face_direction | 3 | battle_started: 0, choice_presented: 0, map_changed: 0, rejected: 0 | 0 |
| walk_to_adjacent | 3 | battle_started: 0, blocked: 1, choice_presented: 0, map_changed: 0, rejected: 0 | 0 |
| walk_to | 1 | battle_started: 0, blocked: 1, budget_exhausted: 1, choice_presented: 0, map_changed: 0, not_converging: 0 | 0 |
| circle_walk | 1 | battle_started: 0, budget_exhausted: 0, choice_presented: 0, map_changed: 0, off_course: 0, rejected: 0 | 0 |
| bounce_in_tall_grass | 1 | choice_presented: 0, map_changed: 0, rejected: 1 | 0 |
| talk_to_adjacent_npc | 1 | battle_started: 0, choice_presented: 0, map_changed: 0, no_response: 0, no_target: 1, rejected: 0, still_talking: 0 | 0 |
| buy_item | 1 | battle_started: 0, blocked: 0, budget_exhausted: 0, choice_presented: 0, count_limit: 0, insufficient_funds: 1, map_changed: 0, not_converging: 0, not_sold_here: 1, step_timeout: 0, unexpected_screen: 0, unsupported_map: 0, verify_failed: 0, wrong_scene: 0 | 0 |
| sell_item | 1 | battle_started: 0, blocked: 0, budget_exhausted: 0, choice_presented: 0, count_limit: 0, insufficient_stock: 0, map_changed: 0, not_converging: 0, not_in_bag: 1, not_sold_here: 0, step_timeout: 0, unexpected_screen: 0, unsupported_map: 0, verify_failed: 0, wrong_scene: 0 | 0 |
| interact_facing | 1 | battle_started: 0, choice_presented: 0, map_changed: 0, no_response: 1 | 0 |
| advance_dialog | 1 | battle_started: 0, choice_presented: 0, map_changed: 0, still_talking: 0 | 0 |
| wait_until_scene | 0 | timeout: 0 | 0 |
| exit_map | 3 | battle_started: 0, blocked: 1, budget_exhausted: 0, choice_presented: 0, map_changed: 0, not_converging: 0, rejected: 0, unsupported_map: 0, warp_failed: 0 | 0 |
| heal_at_center | 1 | battle_started: 0, blocked: 0, budget_exhausted: 0, choice_presented: 0, map_changed: 0, not_converging: 0, still_talking: 0, unsupported_map: 1, verify_failed: 0 | 0 |
| open_menu_to | 2 | rejected: 0, wrong_scene: 0 | 0 |
| shop_buy | 5 | bad_args: 1, bag_full: 0, left_scene: 0, not_enough_money: 1, quantity_out_of_range: 1, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_item: 1, unknown_script: 0 | 0 |
| shop_sell | 2 | bad_args: 0, key_item: 0, left_scene: 0, not_in_bag: 1, quantity_out_of_range: 1, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 0 | 0 |
| shop_quit | 2 | bad_args: 0, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 0 | 0 |
| naming_enter_name | 2 | bad_args: 0, invalid_name: 3, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 1 | 0 |
| battle_fight | 4 | bad_args: 0, left_scene: 0, no_pp: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_move: 1, unknown_script: 1 | 0 |
| battle_switch | 2 | already_active: 1, bad_args: 0, left_scene: 0, pokemon_fainted: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_pokemon: 1, unknown_script: 0 | 0 |
| battle_use_item | 3 | bad_args: 0, cannot_use: 1, left_scene: 0, not_in_bag: 1, pokemon_fainted: 0, rewind_limit: 0, step_timeout: 0, target_required: 1, unexpected_screen: 0, unknown_pokemon: 0, unknown_script: 0 | 0 |
| battle_run | 1 | bad_args: 0, cannot_use: 0, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 0 | 0 |
| switch_send_out | 1 | already_active: 0, bad_args: 0, left_scene: 0, pokemon_fainted: 1, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_pokemon: 1, unknown_script: 0 | 0 |
| bag_use | 3 | bad_args: 0, cannot_use: 2, left_scene: 0, not_in_bag: 0, pokemon_fainted: 0, rewind_limit: 0, step_timeout: 0, target_required: 0, unexpected_screen: 0, unknown_pokemon: 0, unknown_script: 0 | 0 |
| bag_toss | 2 | bad_args: 0, key_item: 1, left_scene: 0, not_in_bag: 0, quantity_out_of_range: 1, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 0 | 0 |
| bag_close | 1 | bad_args: 0, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 0 | 0 |
| party_switch | 2 | bad_args: 1, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_pokemon: 1, unknown_script: 0 | 0 |
| party_field_move | 0 | bad_args: 0, cannot_use: 1, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_move: 1, unknown_pokemon: 0, unknown_script: 0 | 0 |
| party_stats | 1 | bad_args: 0, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_pokemon: 0, unknown_script: 0 | 0 |
| party_close | 1 | bad_args: 0, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 0 | 0 |
| pc_withdraw_item | 1 | bad_args: 0, bag_full: 0, left_scene: 0, not_in_bag: 1, quantity_out_of_range: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 0 | 0 |
| pc_deposit_item | 2 | bad_args: 0, bag_full: 0, left_scene: 0, not_in_bag: 0, quantity_out_of_range: 1, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 0 | 0 |
| pc_toss_item | 1 | bad_args: 0, key_item: 0, left_scene: 0, not_in_bag: 0, quantity_out_of_range: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 0 | 0 |
| pc_withdraw_pokemon | 0 | bad_args: 0, bag_full: 0, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_pokemon: 1, unknown_script: 0 | 0 |
| pc_deposit_pokemon | 1 | bad_args: 0, bag_full: 0, cannot_use: 0, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_pokemon: 0, unknown_script: 0 | 0 |
| pc_change_box | 1 | bad_args: 0, left_scene: 0, quantity_out_of_range: 1, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 0 | 0 |
| pc_log_off | 1 | bad_args: 0, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 0 | 0 |
| learn_forget | 3 | bad_args: 0, cannot_use: 0, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_move: 1, unknown_script: 0 | 0 |
| learn_skip | 1 | bad_args: 0, left_scene: 0, rewind_limit: 0, step_timeout: 0, unexpected_screen: 0, unknown_script: 0 | 0 |

缺口：
- face_direction: C2 rejected, C2 battle_started, C2 choice_presented, C2 map_changed
- walk_to_adjacent: C2 rejected, C2 battle_started, C2 choice_presented, C2 map_changed, C3 interrupt
- walk_to: C2 battle_started, C2 choice_presented, C2 map_changed, C2 not_converging, C3 interrupt
- circle_walk: C2 rejected, C2 budget_exhausted, C2 off_course, C2 battle_started, C2 choice_presented, C2 map_changed, C3 interrupt
- bounce_in_tall_grass: C2 choice_presented, C2 map_changed, C3 interrupt
- talk_to_adjacent_npc: C2 rejected, C2 no_response, C2 still_talking, C2 battle_started, C2 choice_presented, C2 map_changed, C3 interrupt
- buy_item: C2 unsupported_map, C2 wrong_scene, C2 count_limit, C2 verify_failed, C2 step_timeout, C2 unexpected_screen, C2 battle_started, C2 choice_presented, C2 map_changed, C2 blocked, C2 not_converging, C2 budget_exhausted
- sell_item: C2 unsupported_map, C2 wrong_scene, C2 count_limit, C2 insufficient_stock, C2 not_sold_here, C2 verify_failed, C2 step_timeout, C2 unexpected_screen, C2 battle_started, C2 choice_presented, C2 map_changed, C2 blocked, C2 not_converging, C2 budget_exhausted
- interact_facing: C2 battle_started, C2 choice_presented, C2 map_changed
- advance_dialog: C2 still_talking, C2 battle_started, C2 choice_presented, C2 map_changed, C3 interrupt
- wait_until_scene: C1 success, C2 timeout, C3 interrupt
- exit_map: C2 unsupported_map, C2 rejected, C2 warp_failed, C2 battle_started, C2 choice_presented, C2 map_changed, C2 not_converging, C2 budget_exhausted, C3 interrupt
- heal_at_center: C2 still_talking, C2 verify_failed, C2 battle_started, C2 choice_presented, C2 map_changed, C2 blocked, C2 not_converging, C2 budget_exhausted, C3 interrupt
- open_menu_to: C2 rejected, C2 wrong_scene
- shop_buy: C2 bag_full, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- shop_sell: C2 bad_args, C2 key_item, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- shop_quit: C2 bad_args, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- naming_enter_name: C2 bad_args, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen
- battle_fight: C2 bad_args, C2 left_scene, C2 no_pp, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen
- battle_switch: C2 bad_args, C2 left_scene, C2 pokemon_fainted, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- battle_use_item: C2 bad_args, C2 left_scene, C2 pokemon_fainted, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_pokemon, C2 unknown_script
- battle_run: C2 bad_args, C2 cannot_use, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- switch_send_out: C2 already_active, C2 bad_args, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- bag_use: C2 bad_args, C2 left_scene, C2 not_in_bag, C2 pokemon_fainted, C2 rewind_limit, C2 step_timeout, C2 target_required, C2 unexpected_screen, C2 unknown_pokemon, C2 unknown_script
- bag_toss: C2 bad_args, C2 left_scene, C2 not_in_bag, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- bag_close: C2 bad_args, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- party_switch: C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- party_field_move: C1 success, C2 bad_args, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_pokemon, C2 unknown_script
- party_stats: C2 bad_args, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_pokemon, C2 unknown_script
- party_close: C2 bad_args, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- pc_withdraw_item: C2 bad_args, C2 bag_full, C2 left_scene, C2 quantity_out_of_range, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- pc_deposit_item: C2 bad_args, C2 bag_full, C2 left_scene, C2 not_in_bag, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- pc_toss_item: C2 bad_args, C2 key_item, C2 left_scene, C2 not_in_bag, C2 quantity_out_of_range, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- pc_withdraw_pokemon: C1 success, C2 bad_args, C2 bag_full, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- pc_deposit_pokemon: C2 bad_args, C2 bag_full, C2 cannot_use, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_pokemon, C2 unknown_script
- pc_change_box: C2 bad_args, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- pc_log_off: C2 bad_args, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- learn_forget: C2 bad_args, C2 cannot_use, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script
- learn_skip: C2 bad_args, C2 left_scene, C2 rewind_limit, C2 step_timeout, C2 unexpected_screen, C2 unknown_script

C2 含人工审核的源码出口（failure_codes.py）；源码变更后须同步审核。
