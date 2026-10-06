"""菜单类脚本（§7.6）：open_menu_to。

**为什么走 raw 按键**：start 菜单本身常驻光标（`▶` + 选项），`ScriptRun.press`
的 `choice_presented` 钩子会在"移动光标 / 选中"的每一步都冻结——菜单导航
本来就是脚本在替调用方做决策（选哪个子菜单是任务指定的），所以这里直接
`console.press` + `console.tick` 绕过钩子，自行判场合成败。

`START_ORDER` 与 `scene.START_ITEMS` 同序（菜单项固定顺序）；`TARGET_SCENE`
是"选中某项后该进的接管场合"——用于成败判定。
"""

from __future__ import annotations

from .engine import ScriptResult, WorldConsole
from .takeover.engine import POLL_FRAMES, STABLE_POLLS

# 与 scene.START_ITEMS 同序（开始菜单项的固定顺序）
START_ORDER: tuple[str, ...] = ("POKéDEX", "POKéMON", "ITEM", "SAVE", "OPTION", "EXIT")
"""开始菜单项固定顺序（光标索引据此算）。"""

TARGET_SCENE: dict[str, str] = {"POKéMON": "party", "ITEM": "bag"}
"""选中某项后该进入的接管场合（用于成败判定；其余项没有可判定的子菜单场合）。"""


def _settle(console: WorldConsole) -> None:
    console.tick(POLL_FRAMES * STABLE_POLLS)


def open_menu_to(console: WorldConsole, target: str) -> ScriptResult:
    """从野外开出 start 菜单并进入指定子菜单：按 start → 把光标移到 `target` 项
    （默认光标在 POKéDEX，按当前光标相对移动）→ 按 a 选中。

    - `target` 不在菜单项里 → `rejected`；
    - 按 start 后场合仍不是 start 菜单 → `wrong_scene`；
    - 选中后场合变成预期子菜单（如 POKéMON→party）→ `ok`；
    - 选中后仍在 start 菜单（光标走偏 / 未生效）→ `wrong_scene`。
    """
    if target not in START_ORDER:
        return ScriptResult(ok=False, code="rejected", data={"target": target})

    # 确保在 start 菜单
    if console.scene() != "start_menu":
        console.press("start")
        _settle(console)
        if console.scene() != "start_menu":
            return ScriptResult(
                ok=False,
                code="wrong_scene",
                data={"scene": console.scene(), "target": target},
            )

    # 相对当前光标移动
    options = console.read().options
    cursor = console.read().cursor
    try:
        cur_idx = options.index(cursor) if cursor in options else 0
    except ValueError:
        cur_idx = 0
    tgt_idx = START_ORDER.index(target)
    diff = tgt_idx - cur_idx
    if diff != 0:
        move = "down" if diff > 0 else "up"
        for _ in range(abs(diff)):
            console.press(move)
            _settle(console)

    # 选中
    console.press("a")
    _settle(console)
    scene = console.scene()
    expected = TARGET_SCENE.get(target)
    if scene != "start_menu" and (expected is None or scene == expected):
        return ScriptResult(ok=True, code="ok", data={"scene": scene, "target": target})
    return ScriptResult(ok=False, code="wrong_scene", data={"scene": scene, "target": target})


__all__ = ["open_menu_to"]
