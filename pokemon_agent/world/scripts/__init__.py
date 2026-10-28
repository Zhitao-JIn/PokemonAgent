"""脚本层（server 进程内）：ScriptRun 骨架 + 15 条机械脚本（P4 落地）。

依赖 Console/RAM/tile 直读，随 world 整体拷走——这是"脚本住 server 内"的落点
（SPEC §六/§七）。骨架在 `engine.py`，各脚本一个文件（P4）。
"""

from __future__ import annotations

from .engine import Halt, ScriptResult, ScriptRun, WorldConsole, run_script
from .flow import advance_dialog, wait_until_scene
from .interact import interact_facing, talk_to_adjacent_npc
from .menu import open_menu_to
from .movement import bounce_in_tall_grass, circle_walk, face_direction, walk_to, walk_to_adjacent
from .navigation import exit_map, heal_at_center

__all__ = [
    "Halt",
    "ScriptResult",
    "ScriptRun",
    "WorldConsole",
    "advance_dialog",
    "bounce_in_tall_grass",
    "circle_walk",
    "exit_map",
    "face_direction",
    "heal_at_center",
    "interact_facing",
    "open_menu_to",
    "run_script",
    "talk_to_adjacent_npc",
    "wait_until_scene",
    "walk_to",
    "walk_to_adjacent",
]
