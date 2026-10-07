"""scripts 测评的用例表（v1）：PLAN_mcp_servers 附录 A 第 2–15 行 × 现有钉死存档。

期望一律**从地图与游戏规则写出**（`basis` 记依据：存档内存读出的坐标/四邻、pokered 表、
mcp SPEC §七的脚本契约），不从脚本的实际输出抄——抄来的期望只能证明"脚本和它自己一致"。
存档事实（某格能不能走、按键后到哪）用模拟器核对过，核的是世界不是脚本。

存档速记（`experiment/experiment_states/knowledge/`）：
- OBSTACLE：Route 1（图 12）(9,12) 面南；南邻 (9,13) 是朝南的台阶（按 down 越过它落到 (9,14)），
  y=10..12 三行开阔，(14,12) 是草；金钱 3000，背包 POTION×1。
- GRASS：Route 1 (13,8) 面东，四邻全是草。
- CENTER：常青市宝可梦中心（图 41）(3,3) 面北；北邻 (3,2) 是柜台，护士 (3,1) 在柜台后，
  面北按 a 即隔台对话，回血完那句是"Thank you! Your POKéMON are fighting fit!"（模拟器核过）；
  东邻 (4,3) 站着一个人；队伍 HP 全满；正南走到 (3,7) 的门出到常青市（图 1）。
- MART：常青市友好商店（图 42）(3,5) 面北，场合 shop；店员 (0,5) 在柜台后，(1,5) 是柜台，
  隔台对话站 (2,5) 面西（shop_* 存档都停在这一格）；金钱 3000，背包 POTION×1，队伍 HP 5/25；
  正南 (3,7) 的门出到常青市（图 1）。
- MART_DIALOG：同店，店员正说"Hey! You came from PALLET TOWN?"——OAK's PARCEL 剧情。
- PALLET：真新镇（图 0）(10,2) 面东；北 (10,1) 是草；招牌 (11,5)。
- OAK_LAB：大木研究所（图 40）(4,4) 面北；人 (5,2)；正南走到 (4,11) 的门出到真新镇（图 0）。
"""

from __future__ import annotations

from evals.solvers.world_script_execute import ScriptCase, ScriptExpect

OBSTACLE = "knowledge/knowledge_movement_obstacle.state"
GRASS = "knowledge/knowledge_wild_encounter.state"
CENTER = "knowledge/knowledge_pokemon_center_heal.state"
MART = "knowledge/knowledge_shop_interaction.state"
MART_DIALOG = "knowledge/knowledge_dialogue_advance.state"
PALLET = "knowledge/knowledge_door_transition.state"
OAK_LAB = "knowledge/knowledge_npc_dialogue.state"
STILL = {"x": 0, "y": 0}

CASES_3: tuple[ScriptCase, ...] = (
    ScriptCase(
        case_id="open_menu_pokemon",
        matrix_row=11,
        script="open_menu_to",
        args={"target": "POKéMON"},
        state=OBSTACLE,
        expect=ScriptExpect(ok=True, code="ok", after={"scene": "party"}, delta=STILL),
        basis="SPEC §7.4：POKéMON → party",
    ),
    ScriptCase(
        case_id="open_menu_item",
        matrix_row=11,
        script="open_menu_to",
        args={"target": "ITEM"},
        state=OBSTACLE,
        expect=ScriptExpect(ok=True, code="ok", after={"scene": "bag"}, delta=STILL),
        basis="SPEC §7.4：ITEM → bag",
    ),
    ScriptCase(
        case_id="buy_poke_ball",
        matrix_row=12,
        script="buy_item",
        args={"item": "POKé BALL", "count": 5},
        state=MART,
        expect=ScriptExpect(
            ok=True,
            code="ok",
            data={"spent": 1000},
            delta={"money": -1000, "bag:POKé BALL": 5},
        ),
        basis="shop_layouts 图 42 在售 POKé BALL 200；5 个 1000 ≤ 3000",
    ),
    ScriptCase(
        case_id="buy_not_sold_here",
        matrix_row=12,
        script="buy_item",
        args={"item": "POTION", "count": 1},
        state=MART,
        expect=ScriptExpect(ok=False, code="not_sold_here", delta={"money": 0}),
        basis="常青市友好商店不卖 POTION",
    ),
    ScriptCase(
        case_id="buy_insufficient_funds",
        matrix_row=12,
        script="buy_item",
        args={"item": "BURN HEAL", "count": 13},
        state=MART,
        expect=ScriptExpect(ok=False, code="insufficient_funds", delta={"money": 0}),
        basis="BURN HEAL 250 × 13 = 3250 > 3000",
    ),
    ScriptCase(
        case_id="sell_potion",
        matrix_row=13,
        script="sell_item",
        args={"item": "POTION", "count": 1},
        state=MART,
        expect=ScriptExpect(
            ok=True,
            code="ok",
            data={"earned": 150},
            delta={"money": 150, "bag:POTION": -1},
        ),
        basis="POTION 买价 300，Gen1 卖价减半",
    ),
    ScriptCase(
        case_id="sell_not_in_bag",
        matrix_row=13,
        script="sell_item",
        args={"item": "ANTIDOTE", "count": 1},
        state=MART,
        expect=ScriptExpect(ok=False, code="not_in_bag", delta={"money": 0}),
        basis="背包里只有 POTION",
    ),
    ScriptCase(
        case_id="heal_at_viridian",
        matrix_row=14,
        script="heal_at_center",
        state=CENTER,
        expect=ScriptExpect(
            ok=True,
            code="ok",
            dialog=["fighting fit"],
            after={"party_hp_missing": 0, "map_id": 41},
        ),
        basis='回血成功以护士那句 "Your POKéMON are fighting fit!" 为证（存档队伍本就满血，'
        "HP 差值证明不了回血）",
    ),
    ScriptCase(
        case_id="heal_unsupported_map",
        matrix_row=14,
        script="heal_at_center",
        state=OBSTACLE,
        expect=ScriptExpect(ok=False, code="unsupported_map", delta=STILL),
        basis="图 12 不是宝可梦中心",
    ),
)
