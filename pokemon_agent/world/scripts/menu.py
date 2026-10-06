"""开始菜单导航：目标选项由调用参数给定。

所有按键经 ScriptRun；等待界面切换且不启用选项中断，按实际选项导航后核对场合。"""

from __future__ import annotations

from .engine import ScriptResult, ScriptRun, WorldConsole
from .policies import ScriptPolicy, StableWait

# 与 scene.START_ITEMS 同序（开始菜单项的固定顺序）
START_ORDER: tuple[str, ...] = ("POKéDEX", "POKéMON", "ITEM", "SAVE", "OPTION", "EXIT")
"""支持的开始菜单项；光标索引取当前读屏选项的位置。"""

TARGET_SCENE: dict[str, str] = {"POKéMON": "party", "ITEM": "bag"}
"""选中某项后该进入的接管场合（用于成败判定；其余项没有可判定的子菜单场合）。"""


def open_menu_to(console: WorldConsole, target: str) -> ScriptResult:
    """从野外开出 start 菜单并进入指定子菜单：按 start → 把光标移到 `target` 项
    （按实际选项列表和当前光标相对移动，允许尚未获得 POKéDEX）→ 按 a 选中。

    - `target` 不在菜单项里 → `rejected`；
    - 按 start 后场合仍不是 start 菜单 → `wrong_scene`；
    - 选中后场合变成预期子菜单（如 POKéMON→party）→ `ok`；
    - 选中后仍在 start 菜单（光标走偏 / 未生效）→ `wrong_scene`。
    """
    if target not in START_ORDER:
        return ScriptResult(ok=False, code="rejected", data={"target": target})

    run = ScriptRun(
        console,
        budget=0,
        start_map_id=console.map_id(),
        start_pos=console.pos(),
        policy=ScriptPolicy(wait=StableWait(minimum_frames=64)),
    )

    # 确保在 start 菜单
    if console.scene() != "start_menu":
        run.press("start")
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
    if target not in options:
        return run.finish(ok=False, code="rejected", extra={"target": target})
    tgt_idx = options.index(target)
    diff = tgt_idx - cur_idx
    if diff != 0:
        move = "down" if diff > 0 else "up"
        for _ in range(abs(diff)):
            run.press(move)

    # 选中
    run.press("a")
    scene = console.scene()
    expected = TARGET_SCENE.get(target)
    if scene != "start_menu" and (expected is None or scene == expected):
        return ScriptResult(ok=True, code="ok", data={"scene": scene, "target": target})
    return ScriptResult(ok=False, code="wrong_scene", data={"scene": scene, "target": target})


__all__ = ["open_menu_to"]
