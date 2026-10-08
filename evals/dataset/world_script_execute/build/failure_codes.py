"""人工核对的源码失败出口；含透传出口，脚本变更时需同步审核本登记表。"""

from __future__ import annotations

from pokemon_agent.world.scripts.takeover import TAKEOVER_SCRIPTS

FIELD_INTERRUPTS = ("battle_started", "choice_presented", "map_changed")
WALK_FAILURES = (*FIELD_INTERRUPTS, "blocked", "not_converging", "budget_exhausted")

FAILURE_CODES: dict[str, tuple[str, ...]] = {
    "face_direction": ("rejected", *FIELD_INTERRUPTS),
    "walk_to_adjacent": ("rejected", "blocked", *FIELD_INTERRUPTS),
    "walk_to": WALK_FAILURES,
    "circle_walk": ("rejected", "budget_exhausted", "off_course", *FIELD_INTERRUPTS),
    "bounce_in_tall_grass": ("rejected", "choice_presented", "map_changed"),
    "talk_to_adjacent_npc": (
        "rejected",
        "no_target",
        "no_response",
        "still_talking",
        *FIELD_INTERRUPTS,
    ),
    "interact_facing": ("no_response", *FIELD_INTERRUPTS),
    "advance_dialog": ("still_talking", *FIELD_INTERRUPTS),
    "wait_until_scene": ("timeout",),
    "exit_map": ("unsupported_map", "rejected", "warp_failed", *WALK_FAILURES),
    "heal_at_center": ("unsupported_map", "still_talking", "verify_failed", *WALK_FAILURES),
    "open_menu_to": ("rejected", "wrong_scene"),
    "buy_item": (
        "unsupported_map",
        "wrong_scene",
        "not_sold_here",
        "count_limit",
        "insufficient_funds",
        "verify_failed",
        "step_timeout",
        "unexpected_screen",
        *WALK_FAILURES,
    ),
    "sell_item": (
        "unsupported_map",
        "wrong_scene",
        "count_limit",
        "not_in_bag",
        "insufficient_stock",
        "not_sold_here",
        "verify_failed",
        "step_timeout",
        "unexpected_screen",
        *WALK_FAILURES,
    ),
    "shop_buy": ("unknown_item", "quantity_out_of_range", "not_enough_money", "bag_full"),
    "shop_sell": ("not_in_bag", "quantity_out_of_range", "key_item"),
    "battle_fight": ("unknown_move", "no_pp"),
    "battle_switch": ("unknown_pokemon", "pokemon_fainted", "already_active"),
    "battle_use_item": (
        "not_in_bag",
        "cannot_use",
        "target_required",
        "unknown_pokemon",
        "pokemon_fainted",
    ),
    "battle_run": ("cannot_use",),
    "switch_send_out": ("unknown_pokemon", "pokemon_fainted", "already_active"),
    "bag_use": (
        "not_in_bag",
        "cannot_use",
        "target_required",
        "unknown_pokemon",
        "pokemon_fainted",
    ),
    "bag_toss": ("not_in_bag", "quantity_out_of_range", "key_item"),
    "party_switch": ("unknown_pokemon", "bad_args"),
    "party_stats": ("unknown_pokemon",),
    "party_field_move": ("unknown_pokemon", "cannot_use", "unknown_move"),
    "pc_withdraw_item": ("not_in_bag", "quantity_out_of_range", "bag_full"),
    "pc_deposit_item": ("not_in_bag", "quantity_out_of_range", "bag_full"),
    "pc_toss_item": ("not_in_bag", "quantity_out_of_range", "key_item"),
    "pc_withdraw_pokemon": ("unknown_pokemon", "bag_full"),
    "pc_deposit_pokemon": ("unknown_pokemon", "cannot_use", "bag_full"),
    "pc_change_box": ("quantity_out_of_range",),
    "learn_forget": ("unknown_move", "cannot_use"),
    "naming_enter_name": ("invalid_name",),
}

for _name, _definition in TAKEOVER_SCRIPTS.items():
    _shared = ("unknown_script", "bad_args", "unexpected_screen", "step_timeout")
    if _definition.policy.before is not None:
        _shared += ("rewind_limit", "left_scene")
    FAILURE_CODES[_name] = tuple(sorted(set((*FAILURE_CODES.get(_name, ()), *_shared))))
