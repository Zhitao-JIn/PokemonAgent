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

from .schemas import ScriptCase, ScriptExpect

OBSTACLE = "knowledge/knowledge_movement_obstacle.state"
GRASS = "knowledge/knowledge_wild_encounter.state"
CENTER = "knowledge/knowledge_pokemon_center_heal.state"
MART = "knowledge/knowledge_shop_interaction.state"
MART_DIALOG = "knowledge/knowledge_dialogue_advance.state"
PALLET = "knowledge/knowledge_door_transition.state"
OAK_LAB = "knowledge/knowledge_npc_dialogue.state"
STILL = {"x": 0, "y": 0}

CASES_2: tuple[ScriptCase, ...] = (
    ScriptCase(
        case_id="exit_map_path_blocked",
        matrix_row=6,
        script="exit_map",
        state=OBSTACLE,
        expect=ScriptExpect(ok=False, code="blocked", after={"map_id": 12}),
        basis="图 12 的出口只有南北边缘方向（SPEC §7.2 边缘出口只给方向、直走）；"
        "(9,12) 正北 (9,9) 是树，正南直走到 y=22 被挡（模拟器核过）——去出口途中被挡 → "
        "blocked（附录 A 第 6 行④），不是表过期的 warp_failed",
    ),
    ScriptCase(
        case_id="exit_map_center",
        matrix_row=6,
        script="exit_map",
        state=CENTER,
        expect=ScriptExpect(ok=True, code="ok", data={"to_map": 1}, after={"map_id": 1}),
        basis="室内唯一出口是南面的门 (3,7)/(4,7)，通往常青市（图 1）",
    ),
    ScriptCase(
        case_id="exit_map_mart",
        matrix_row=6,
        script="exit_map",
        state=MART,
        expect=ScriptExpect(ok=True, code="ok", data={"to_map": 1}, after={"map_id": 1}),
        basis="店门 (3,7)/(4,7) 通往常青市（图 1）",
    ),
    ScriptCase(
        case_id="exit_map_oak_lab",
        matrix_row=6,
        script="exit_map",
        state=OAK_LAB,
        expect=ScriptExpect(ok=True, code="ok", data={"to_map": 0}, after={"map_id": 0}),
        basis="研究所门 (4,11)/(5,11) 通往真新镇（图 0）",
    ),
    ScriptCase(
        case_id="bounce_encounter",
        matrix_row=7,
        script="bounce_in_tall_grass",
        args={"steps": 30},
        state=GRASS,
        expect=ScriptExpect(
            ok=True, code="battle_started", data={"encounter": True}, delta={"map_id": 0}
        ),
        basis="四邻全草，Route 1 遇敌率下 30 步内必遇（存档确定、模拟器确定）",
    ),
    ScriptCase(
        case_id="bounce_not_on_grass",
        matrix_row=7,
        script="bounce_in_tall_grass",
        state=OBSTACLE,
        expect=ScriptExpect(ok=False, code="rejected", delta=STILL),
        basis="(9,12) 不是草",
    ),
    ScriptCase(
        case_id="talk_npc_oak_lab",
        matrix_row=8,
        script="talk_to_adjacent_npc",
        state=OAK_LAB,
        pre=("right", "up"),
        expect=ScriptExpect(ok=True, code="ok", events=["dialog"], delta=STILL),
        basis="右、上到 (5,3) 面北，人在 (5,2)；对话收完回到可走状态",
    ),
    ScriptCase(
        case_id="talk_npc_no_target",
        matrix_row=8,
        script="talk_to_adjacent_npc",
        state=OBSTACLE,
        expect=ScriptExpect(ok=False, code="no_target", delta=STILL),
        basis="面南是台阶，面前没人",
    ),
    ScriptCase(
        case_id="interact_sign",
        matrix_row=9,
        script="interact_facing",
        state=PALLET,
        pre=("right", "down", "down"),
        expect=ScriptExpect(ok=True, code="ok", events=["dialog"], delta=STILL),
        basis="右、下、下到 (11,4) 面南，招牌在 (11,5)",
    ),
    ScriptCase(
        case_id="interact_nothing",
        matrix_row=9,
        script="interact_facing",
        state=OBSTACLE,
        expect=ScriptExpect(ok=False, code="no_response", delta=STILL),
        basis="面南是台阶，按 a 无反应",
    ),
    ScriptCase(
        case_id="advance_dialog_parcel",
        matrix_row=10,
        script="advance_dialog",
        state=MART_DIALOG,
        expect=ScriptExpect(ok=True, code="ok", events=["dialog"], delta={"bag:OAK's PARCEL": 1}),
        basis="Gen1 剧情：店员问完是否来自真新镇后交出 OAK's PARCEL，对话结束回店内",
    ),
)
