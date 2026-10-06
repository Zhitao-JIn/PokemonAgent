"""按当前帧算**统一能力掩码**——原子键与宏（P4 起加机械脚本）在同一命名空间。

**为什么住 world 而不是 tool 层**（2026-09-29）：掩码依赖这一帧的 overlay 与
场合，而"这一帧"只有 world 有（server 模式下 tool 层在另一个进程，拿不到帧）。
tool 层（`mcpclient/game_tools.py`）仍用它——但只在**进程内模式**下按调用方交出的
那份观测算，两边共用同一个纯函数，不存在第二份规则。

**纯函数**：不碰 world、不读全局状态——`obs` 与 `all_actions` 全由调用方给。
"""

from __future__ import annotations

from .interface import OVERLAY_ACTIONS
from .interface.domain import ActionEntry, ActionSpace, Facts, TaskObservation
from .macros import macro_specs
from .scripts.catalog import script_entries


def compute_action_space(obs: TaskObservation, all_actions: list[str]) -> ActionSpace:
    """按这份观测的 overlay / 场合算此刻的能力掩码。**纯函数。**

    后置条件：
    - `mask` 覆盖**整个命名空间**（全部键 + 本场合的宏 + 全部脚本名），不可用的
      显式 `False`——让调用方（模型）看得见"有这个动作但此刻不能用"，而不是让它去猜；
    - `names` 与 `macros` 恰好一个非空（走投无路也必须给至少一个动作：
      空动作空间是这一层的 bug，不能推给大脑处理）；
    - 有宏的接管场合只给宏（JEV 在那里不直接按键）；
    - 脚本条目按场合给（`scripts/catalog.SCENE_SCRIPTS` 唯一规则）：walk 给全部、
      dialog 只给对话推进类，其余场合不给。
    """
    macros = macro_specs(obs.scene)
    scene = str(obs.scene)
    scripts = [] if macros else script_entries(scene)

    if macros:
        names: list[str] = []
        entries = [
            ActionEntry(kind="macro", name=m.name, params=m.params, description=m.description)
            for m in macros
        ]
    else:
        overlay = obs.facts.overlay or Facts.Overlay.NONE
        names = [a for a in OVERLAY_ACTIONS[overlay] if a in all_actions]
        assert names, f"action space must never be empty (overlay={overlay})"
        entries = [ActionEntry(kind="key", name=name) for name in names]
    entries.extend(scripts)

    universe = list(all_actions) + [m.name for m in macros] + [e.name for e in scripts]
    enabled = set(names) | {m.name for m in macros} | {e.name for e in scripts}
    return ActionSpace(
        scene=scene,
        names=names,
        macros=macros,
        mask={name: name in enabled for name in universe},
        entries=entries,
    )


__all__ = ["compute_action_space"]
