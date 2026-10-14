"""交互/草丛脚本单测（P4 第一批第二批条目）：talk_to_adjacent_npc / bounce_in_tall_grass。

**对得上谁**：PLAN 附录 A #7（bounce）与 #8（talk）的单测列。`TalkConsole` 在
`GridConsole` 基础上补 NPC 占格与"按键脚本帧"（每次按键后的屏幕覆盖），对话
增量 / choice / battle 全部走骨架的真实钩子路径，不另起判定。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.world import PlaceInWorld, ScreenText
from pokemon_agent.world.interface import BUTTON_FACING
from pokemon_agent.world.scripts.interact import talk_to_adjacent_npc
from pokemon_agent.world.scripts.movement import bounce_in_tall_grass

MAP = 12


class _Mem:
    def __getitem__(self, addr: int) -> int:  # noqa: ARG002
        return 0


class TalkConsole:
    """格网 + NPC 占格 + 按键脚本帧：第 n 次按键后屏幕 = script[n-1] 的覆盖项。"""

    def __init__(
        self,
        walkable: set[tuple[int, int]],
        *,
        start: tuple[int, int],
        npcs: set[tuple[int, int]] | None = None,
        grass: set[tuple[int, int]] | None = None,
        battle_at: set[tuple[int, int]] | None = None,
        script: list[dict[str, Any]] | None = None,
        vanish_at_press: int | None = None,
    ) -> None:
        self._blocked = set(npcs or set())
        self._walkable = walkable | (grass or set()) - self._blocked
        self._grass = grass or set()
        self._battle_at = battle_at or set()
        self._battle = False
        self._script = script or []
        self.vanish_at_press = vanish_at_press
        self.x, self.y = start
        self._facing = "south"
        self._map_id = MAP
        self.presses = 0
        self.memory: Any = _Mem()
        self.rom = b""

    def press(self, key: str) -> None:
        self.presses += 1
        if self.vanish_at_press is not None and self.presses >= self.vanish_at_press:
            self._blocked.clear()  # 会走的 NPC 在按键瞬间离开了
        if key in BUTTON_FACING:  # 方向键才转朝向；a/b/start 等不改变朝向
            self._facing = BUTTON_FACING[key]
        dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.get(key, (0, 0))
        nx, ny = self.x + dx, self.y + dy
        if (nx, ny) in self._walkable and (nx, ny) not in self._blocked:
            self.x, self.y = nx, ny
            if (nx, ny) in self._battle_at:
                self._battle = True

    def tick(self, frames: int) -> None:  # noqa: ARG002
        pass

    def read(self) -> ScreenText:
        over: dict[str, Any] = {}
        if self.presses > 0 and self._script:
            over = self._script[min(self.presses - 1, len(self._script) - 1)]
        return ScreenText(
            in_battle=over.get("in_battle", self._battle),
            dialog_text=over.get("dialog_text", ""),
            options=over.get("options", []),
            has_cursor=over.get("has_cursor", False),
        )

    def map_id(self) -> int:
        return self._map_id

    def pos(self) -> PlaceInWorld:
        return PlaceInWorld(map_id=self._map_id, x=self.x, y=self.y)

    def facing(self) -> str:
        return self._facing

    def object_kind(self, x: int, y: int) -> str | None:  # noqa: ARG002
        return None

    def is_grass(self, x: int, y: int) -> bool:
        return (x, y) in self._grass

    def is_npc(self, x: int, y: int) -> bool:
        return (x, y) in self._blocked

    def scene(self) -> str:
        text = self.read()
        if text.in_battle:
            return "battle"
        if text.dialog_text:
            return "dialog"
        return "walk"


def _ground() -> set[tuple[int, int]]:
    return {(x, y) for x in range(10, 21) for y in range(5, 16)}


# ---- talk_to_adjacent_npc（附录 A #8）----


def test_talk_two_frames_full_dialog_back_to_field() -> None:
    """① 两框对话收全回野外：增量正确拼接（首框全量 + 滚动增量）。"""
    console = TalkConsole(
        _ground(),
        start=(15, 8),
        npcs={(16, 8)},
        script=[{}, {"dialog_text": "框1"}, {"dialog_text": "框2"}, {}],
    )
    res = talk_to_adjacent_npc(console, "east")
    assert res.ok and res.code == "ok"
    assert res.data["dialog"] == ["框1", "框2"]


def test_talk_choice_presented_freezes_with_dialog() -> None:
    """② 第二框后出选项 → choice_presented 冻结，已收文本照带。"""
    console = TalkConsole(
        _ground(),
        start=(15, 8),
        npcs={(16, 8)},
        script=[
            {},
            {"dialog_text": "要去冒险吗?"},
            {"options": ["YES", "NO"], "has_cursor": True},
        ],
    )
    res = talk_to_adjacent_npc(console, "east")
    assert not res.ok and res.code == "choice_presented"
    assert res.data["choice"] == "YES / NO"
    assert res.data["dialog"] == ["要去冒险吗?"]


def test_talk_no_npc_in_front() -> None:
    """③ 面前格没有 NPC → no_target。"""
    console = TalkConsole(_ground(), start=(15, 8))
    res = talk_to_adjacent_npc(console, "east")
    assert not res.ok and res.code == "no_target"


def test_talk_press_a_no_response() -> None:
    """④ 有 NPC 但按 a 不出对话框 → no_response（合法结果）。"""
    console = TalkConsole(_ground(), start=(15, 8), npcs={(16, 8)}, script=[{}])
    res = talk_to_adjacent_npc(console, "east")
    assert not res.ok and res.code == "no_response"
    assert res.data["dialog"] == []


def test_talk_trainer_battle_with_dialog() -> None:
    """⑤ 对话完进战斗（训练家型）→ battle_started + 已收 dialog（含战斗框增量）。"""
    console = TalkConsole(
        _ground(),
        start=(15, 8),
        npcs={(16, 8)},
        script=[{}, {"dialog_text": "你瞅啥!"}, {"in_battle": True, "dialog_text": "对战!"}],
    )
    res = talk_to_adjacent_npc(console, "east")
    assert res.code == "battle_started"
    assert res.data["dialog"] == ["你瞅啥!", "对战!"]


def test_talk_npc_walked_away_after_step() -> None:
    """NPC 让位复验：复验时有 NPC，按键瞬间走了且格可走 → 玩家位移 → no_target。"""
    console = TalkConsole(_ground(), start=(15, 8), npcs={(16, 8)}, script=[{}], vanish_at_press=1)
    res = talk_to_adjacent_npc(console, "east")
    assert not res.ok and res.code == "no_target"
    assert (console.x, console.y) == (16, 8), "NPC 让位后玩家挤进了那格"


def test_talk_default_direction_uses_facing() -> None:
    """direction 缺省 = 当前朝向。"""
    console = TalkConsole(
        _ground(), start=(15, 8), npcs={(15, 9)}, script=[{}, {"dialog_text": "嗨"}, {}]
    )
    console._facing = "south"
    res = talk_to_adjacent_npc(console)
    assert res.ok and res.data["dialog"] == ["嗨"]


def test_talk_budget_exhausted_still_talking() -> None:
    """长对话推不完 → still_talking。"""
    script: list[dict[str, Any]] = [{}] + [{"dialog_text": f"第{i}句"} for i in range(60)]
    console = TalkConsole(_ground(), start=(15, 8), npcs={(16, 8)}, script=script)
    res = talk_to_adjacent_npc(console, "east")
    assert not res.ok and res.code == "still_talking"


# ---- bounce_in_tall_grass（附录 A #7）----


def _grass_world(battle_at: set[tuple[int, int]] | None = None) -> TalkConsole:
    return TalkConsole(
        _ground(),
        start=(15, 10),
        grass={(15, 10), (15, 9), (15, 11), (15, 12)},
        battle_at=battle_at,
    )


def test_bounce_encounter_is_success() -> None:
    """① N 步内进战斗 → ok:battle_started（撞怪即目的）。"""
    console = _grass_world(battle_at={(15, 9)})
    res = bounce_in_tall_grass(console, steps=30)
    assert res.ok and res.code == "battle_started"
    assert res.data["encounter"] is True


def test_bounce_no_encounter_is_legal() -> None:
    """② steps 用完无怪 → no_encounter（合法，ok:true）。"""
    console = _grass_world()
    res = bounce_in_tall_grass(console, steps=10)
    assert res.ok and res.code == "no_encounter"
    assert res.data["encounter"] is False
    assert res.data["steps_used"] == 10


def test_bounce_rejected_outside_grass() -> None:
    """③ 起始格非草丛 → rejected。"""
    console = TalkConsole(_ground(), start=(10, 5))
    res = bounce_in_tall_grass(console, steps=10)
    assert not res.ok and res.code == "rejected"
