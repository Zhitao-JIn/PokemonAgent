"""冻结短场景的必要里程碑；仅适用于当前目标尚要求且现状尚未满足的步骤。"""

MILESTONES: dict[str, list[str]] = {
    "wild_encounter": ["在可通行草地内移动", "核对野生遭遇已触发"],
    "door_transition": ["抵达可进入的门或换图口", "跨过入口并核对地图变化"],
    "npc_dialogue": ["抵达目标 NPC 可交互的位置和朝向", "交互并核对对话出现"],
    "movement_obstacle": ["识别阻挡并选择可通行绕行路线", "抵达指定地图与位置"],
    "dialogue_advance": ["推进当前对话", "核对对话关闭并交还控制"],
    "shop_interaction": ["抵达店员的可交互位置和朝向", "交互并核对商店菜单出现"],
    "shop_open_buy_menu": ["进入商店交互菜单", "选择 BUY 并核对商品列表"],
    "shop_select_item": ["定位目标商品", "选择并核对数量或确认界面"],
    "shop_confirm_purchase": ["核对商品与数量后确认", "核对交易成功证据"],
    "shop_cancel_purchase": ["取消当前购买", "核对返回商品列表且没有购买支出"],
    "battle_action_menu": ["在当前战斗菜单移动光标到 RUN", "停留在 RUN，禁止确认或逃跑"],
    "battle_fight_menu": ["在行动菜单选择 FIGHT", "核对招式列表出现"],
    "battle_move_select": ["定位指定招式并确认", "核对 PP 或战斗文字等招式使用证据"],
    "battle_pokemon_switch": ["在行动菜单选择 PKMN", "核对宝可梦列表已出现；不要求实际换人"],
    "battle_item_use": ["在行动菜单选择 ITEM", "核对道具列表已出现；不要求实际使用道具"],
    "battle_run_attempt": ["在战斗中选择 RUN 并确认", "核对逃跑成功或失败的实际反馈"],
    "catch_weaken_target": ["选择能削弱目标的行动", "核对对手当前 HP 比调用前历史记录低"],
    "catch_throw_ball": ["选择精灵球并使用", "核对投球或捕获结果的真实反馈"],
    "pokemon_center_enter": ["抵达宝可梦中心入口", "进入并核对地图变化"],
    "pokemon_center_heal": ["与护士交互并选择治疗", "核对治疗完成话语；队伍恢复只作辅助证据"],
}
