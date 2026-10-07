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

CASES_1: tuple[ScriptCase, ...] = (
    ScriptCase(
        case_id="circle_walk_two_laps",
        matrix_row=2,
        script="circle_walk",
        args={"laps": 2},
        state=OBSTACLE,
        pre=("up",),
        expect=ScriptExpect(ok=True, code="ok", data={"laps_done": 2}, delta=STILL),
        basis="先上一步到 (9,11)；右下左上一圈经 (10,11)(10,12)(9,12) 全开阔，两圈回起点",
    ),
    ScriptCase(
        case_id="walk_to_adjacent_open",
        matrix_row=3,
        script="walk_to_adjacent",
        args={"direction": "west"},
        state=OBSTACLE,
        expect=ScriptExpect(
            ok=True, code="ok", data={"entered_grass": False}, after={"x": 8, "y": 12}
        ),
        basis="西邻 (8,12) 是空地",
    ),
    ScriptCase(
        case_id="walk_to_adjacent_counter",
        matrix_row=3,
        script="walk_to_adjacent",
        args={"direction": "north"},
        state=CENTER,
        expect=ScriptExpect(ok=False, code="blocked", delta=STILL),
        basis="北邻 (3,2) 是柜台",
    ),
    ScriptCase(
        case_id="walk_to_adjacent_into_grass",
        matrix_row=3,
        script="walk_to_adjacent",
        args={"direction": "north"},
        state=PALLET,
        expect=ScriptExpect(
            ok=True, code="ok", data={"entered_grass": True}, after={"x": 10, "y": 1}
        ),
        basis="北邻 (10,1) 是草（真新镇北口，镇内没有野生宝可梦）",
    ),
    ScriptCase(
        case_id="walk_to_adjacent_jump_ledge",
        matrix_row=3,
        script="walk_to_adjacent",
        args={"direction": "south"},
        state=OBSTACLE,
        expect=ScriptExpect(ok=True, code="ok", after={"x": 9, "y": 14}),
        basis="南邻 (9,13) 是朝南的台阶：按 down 一步越过、落到 (9,14)（模拟器核过）",
    ),
    ScriptCase(
        case_id="walk_to_open_field",
        matrix_row=4,
        script="walk_to",
        args={"x": 12, "y": 10},
        state=OBSTACLE,
        expect=ScriptExpect(ok=True, code="ok", after={"x": 12, "y": 10}),
        basis="(9..12, 10..12) 全开阔，任意轴序都能直达",
    ),
    ScriptCase(
        case_id="walk_to_counter_target",
        matrix_row=4,
        script="walk_to",
        args={"x": 3, "y": 2},
        state=CENTER,
        expect=ScriptExpect(ok=False, code="blocked", delta=STILL),
        basis="目标 (3,2) 本身是柜台；只有北向一步能缩短距离且走不动，dx=0 无轴可换"
        "（SPEC §7.2：换轴仍失败 → blocked）",
    ),
    ScriptCase(
        case_id="walk_to_budget",
        matrix_row=4,
        script="walk_to",
        args={"x": 5, "y": 10, "max_steps": 2},
        state=OBSTACLE,
        expect=ScriptExpect(ok=False, code="budget_exhausted", delta={"map_id": 0}),
        basis="目标在 6 步外，max_steps=2（附录 A 第 4 行④）",
    ),
    ScriptCase(
        case_id="face_direction_already",
        matrix_row=5,
        script="face_direction",
        args={"direction": "south"},
        state=OBSTACLE,
        expect=ScriptExpect(
            ok=True, code="ok", data={"moved": False, "facing": "south"}, delta=STILL
        ),
        basis="已面南，no-op",
    ),
    ScriptCase(
        case_id="face_direction_turn_and_step",
        matrix_row=5,
        script="face_direction",
        args={"direction": "north"},
        state=OBSTACLE,
        expect=ScriptExpect(
            ok=True,
            code="ok",
            data={"moved": True, "facing": "north"},
            after={"x": 9, "y": 11, "facing": "north"},
        ),
        basis="北邻 (9,11) 空地：Gen1 按方向键转身即走一格",
    ),
    ScriptCase(
        case_id="face_direction_turn_blocked",
        matrix_row=5,
        script="face_direction",
        args={"direction": "east"},
        state=CENTER,
        expect=ScriptExpect(
            ok=True,
            code="ok",
            data={"moved": False, "facing": "east"},
            after={"facing": "east"},
            delta=STILL,
        ),
        basis="面北，东邻 (4,3) 站着人：原地转向不位移",
    ),
)
