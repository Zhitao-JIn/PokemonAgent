"""按键 → 物体交互事件：**判定层（P6 起唯一的裁判，住 world）**。

**为什么住 world**：判定需要"这一帧哪些格子上有什么"（landmarks / 物体表），
只有 world（server 进程）读得到——P6 把逐键判定从 harness 的 `rules.py` 前移到
这里，两条执行路径共用同一份规则：

- **逐键路径**：`step` 响应带本键的裸事件（`observe_step`）；
- **脚本路径**：`ScriptRun.press` 逐键调 `judge_press`，事件随终态报告的
  `events[]` 批量带出。

两路产出**同一个 dict 形状**（outcome/actor_place/place/object_kind/button
+ dialog 的 text / warp 的 map_id），harness 侧只做补三章与落库（`rules.py`
瘦身后只剩这件事）。

结构是**先圈候选格、再按 kind 查姿势判定函数**：

- 候选集：脚下这格 + facing 邻格（方向键）；facing 邻格，它不是交互物时再加
  往前一格（a——柜台/桌子会隔一格挡着，对面的人才是一步真正碰到的对象）；
- 每个候选格按 kind 查 `_POSTURES`，姿势函数自己判断"这次按键的几何关系
  属不属于我"，不属于返回 `None` 让位；命中的产出事件。

**脚下这格不会被人物精灵挡住**（精灵表 0 号槽位=玩家自己，读地形时显式跳过）。
**判定只认本次按键自己的依据**（传入的 kind 查询函数 / 对话文字），不查记忆。

**多段动作链一律不产出事件**：事件的键是「角色在哪格、按了哪个键」，一条链的
两头拼不出"哪一次按键才是撞上去的那次"。执行粒度是单键后这条恒成立，保留当
输入契约。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .interface import BUTTON_FACING, INTERACT_KEY, PlaceInWorld, TaskObservation

INTERACTIVE = ("人", "招牌", "门", "物")
"""不含"石"：巨石不弹对话、不会消失，这一版没有推动判定，放进来也没有姿势
函数会命中，纯粹多一次无意义的候选格查询。"""

KindAt = Callable[[PlaceInWorld], "str | None"]
"""「这一格是什么交互物」的查询函数；不是交互物返回 `None`。

world 侧由本帧 landmarks 查表实现（`_kind_lookup`），脚本侧由
`WorldConsole.object_kind` 实现——判定规则本身不关心来源。
"""


# ---- 候选格与 kind 查询 ----


def press_cells(place: PlaceInWorld, facing: str) -> list[PlaceInWorld]:
    """一次方向键的候选格：`place` **脚下这格 + facing 邻格**，一共 2 格。

    方向键只可能碰到这两格：踩在门上朝外按（脚下这格），或者朝某格走进去
    （门 / 物，都在 facing 邻格）。侧面与背后的格子这次按键碰不到。
    """
    return [place, place.step_toward(facing)]


def _kind_lookup(obs: TaskObservation) -> KindAt:
    """从这一帧的 `facts.landmarks` 建查询表（逐键 step 路径用）。"""
    marks: dict[tuple[int, int], str] = {}
    for mark in obs.facts.landmarks:
        if mark.kind in INTERACTIVE:
            marks[(mark.place.x, mark.place.y)] = mark.kind

    def lookup(place: PlaceInWorld) -> str | None:
        return marks.get((place.x, place.y))

    return lookup


# ---- 姿势判定（产出裸事件 dict）----


def _dialog_or_still(
    *,
    button: str,
    actor_place: PlaceInWorld,
    candidate: PlaceInWorld,
    kind: str,
    dialog_text: str,
) -> dict[str, Any]:
    """a 键互动的两种结局：弹出对话记正文，什么都没有记 still。

    `dialog_text` 是按键之后那一帧从屏幕 tile 缓冲解码的文字；空值表示这一帧
    没有对话文字，不依赖任何视觉感知标记。
    """
    event: dict[str, Any] = {
        "outcome": "still",
        "actor_place": actor_place.model_dump(),
        "place": candidate.model_dump(),
        "object_kind": kind,
        "button": button,
    }
    if dialog_text.strip():
        event["outcome"] = "dialog"
        event["text"] = dialog_text
    return event


def _warp_or_still(
    *,
    button: str,
    actor_place: PlaceInWorld,
    candidate: PlaceInWorld,
    kind: str,
    after_place: PlaceInWorld,
) -> dict[str, Any]:
    """方向键的两种结局：穿过这格进新图记 warp，否则记 still。"""
    event: dict[str, Any] = {
        "outcome": "still",
        "actor_place": actor_place.model_dump(),
        "place": candidate.model_dump(),
        "object_kind": kind,
        "button": button,
    }
    if after_place.map_id != actor_place.map_id:
        event["outcome"] = "warp"
        event["map_id"] = after_place.map_id
    return event


def _door_walk_into(
    *,
    button: str,
    actor_place: PlaceInWorld,
    facing: str,
    candidate: PlaceInWorld,
    kind: str,
    after_place: PlaceInWorld,
    dialog_text: str,
) -> dict[str, Any] | None:
    """姿势：面向门走过去——门在 facing 邻格，角色朝它走进去。

    游戏里有两种门：室外进室内的门走上去当拍切图（记 warp）；室内出去、门房这类门
    走上去不切图，要站在门格上再朝外按一次（那一次归 `_door_stand_on_push` 判）。
    所以**走上了门格、地图没变**不是"这个碰法没用"，只是还没到判定的那一拍——
    让位不产出事件；只有被挡住、根本没走上去时才记 still。
    """
    if candidate != actor_place.step_toward(facing):
        return None
    if after_place.map_id == actor_place.map_id and after_place.key == candidate.key:
        return None
    return _warp_or_still(
        button=button,
        actor_place=actor_place,
        candidate=candidate,
        kind=kind,
        after_place=after_place,
    )


def _pickup_or_still(
    *,
    button: str,
    actor_place: PlaceInWorld,
    facing: str,
    candidate: PlaceInWorld,
    kind: str,
    after_place: PlaceInWorld,
    dialog_text: str,
) -> dict[str, Any] | None:
    """姿势：走上物品格——拾取在踏入的同一拍触发，弹出「获得了 XXX」对话，
    跟 a 键弹对话框是同一种结局判定（复用 `_dialog_or_still`），只是触发键
    是方向键（走进去），不是 a——面朝物品按 a 在游戏里什么都不会发生。"""
    if button == INTERACT_KEY:
        return None
    if candidate != actor_place.step_toward(facing):
        return None
    return _dialog_or_still(
        button=button,
        actor_place=actor_place,
        candidate=candidate,
        kind=kind,
        dialog_text=dialog_text,
    )


def _door_stand_on_push(
    *,
    button: str,
    actor_place: PlaceInWorld,
    facing: str,
    candidate: PlaceInWorld,
    kind: str,
    after_place: PlaceInWorld,
    dialog_text: str,
) -> dict[str, Any] | None:
    """姿势：踩在门格上朝外按方向——角色位置就是门格本身。"""
    if candidate != actor_place:
        return None
    return _warp_or_still(
        button=button,
        actor_place=actor_place,
        candidate=candidate,
        kind=kind,
        after_place=after_place,
    )


def _interact_dialog(
    *,
    button: str,
    actor_place: PlaceInWorld,
    facing: str,
    candidate: PlaceInWorld,
    kind: str,
    after_place: PlaceInWorld,
    dialog_text: str,
) -> dict[str, Any] | None:
    """姿势：正对着它（或隔柜台）按 a——只有 a 键算对话尝试。"""
    if button != INTERACT_KEY:
        return None
    return _dialog_or_still(
        button=button,
        actor_place=actor_place,
        candidate=candidate,
        kind=kind,
        dialog_text=dialog_text,
    )


_POSTURES: dict[str, tuple] = {
    "门": (_door_walk_into, _door_stand_on_push, _interact_dialog),
    "人": (_interact_dialog,),
    "招牌": (_interact_dialog,),
    "物": (_pickup_or_still,),
}


# ---- 入口 ----


def judge_press(
    *,
    actor_place: PlaceInWorld | None,
    facing_before: str,
    button: str,
    times: int,
    after_place: PlaceInWorld | None,
    dialog_text: str,
    kind_at: KindAt,
) -> list[dict[str, Any]]:
    """判定这次按键碰到了哪些物体、各发生了什么，产出裸事件（dict）。

    前置条件：`actor_place`/`after_place` 非 `None`——多段动作链**不产出事件**，
        调用方保证单键（`times` 是这一键的连按次数，方向键连按不判）。
    后置条件：事件按 `place` 唯一（同格只出一条）；列表可为空
        （普通移动 / blocked / 没有交互物——空列表不是错误）。
    """
    if actor_place is None or after_place is None:
        return []
    facing = BUTTON_FACING.get(button, facing_before)
    if not facing:
        return []

    # 圈候选格。a：facing 一格，不是交互物再看两格；方向键：脚下 + facing 邻格，
    # 且只认"没有先转向"的那一步——先转向再走不算一次干净的碰撞尝试。
    if button == INTERACT_KEY:
        ahead = actor_place.step_toward(facing)
        candidates = [ahead]
        if kind_at(ahead) is None:
            candidates.append(ahead.step_toward(facing))
    else:
        if times != 1:
            return []
        if facing_before != facing:
            return []
        candidates = press_cells(actor_place, facing)

    events: list[dict[str, Any]] = []
    for candidate in candidates:
        kind = kind_at(candidate)
        if kind is None:
            continue
        for posture in _POSTURES.get(kind, ()):
            event = posture(
                button=button,
                actor_place=actor_place,
                facing=facing,
                candidate=candidate,
                kind=kind,
                after_place=after_place,
                dialog_text=dialog_text,
            )
            if event is not None:
                events.append(event)
    return events


def observe_step(
    world: Any,  # noqa: ANN401 —— WorldPort（协议按鸭子类型用，避免循环 import）
    pairs: list[tuple[str, int]],
    *,
    settle: bool = True,
) -> tuple[bool, dict[str, Any] | None]:
    """按一段键并判定本键的对象事件（`step` 路径的完整一拍）。

    前后各感知一次 task 帧（RAM + 屏幕缓冲，不问模型）——`moved` 由前后两帧
    位置机械判定，事件由 `judge_press` 判定。多段链（不该出现）只报 moved
    不产事件。
    """
    before = world.perceive_task().observation
    world.step(pairs, settle=settle)
    after = world.perceive_task().observation
    moved = before.place != after.place
    event: dict[str, Any] | None = None
    if len(pairs) == 1:
        name, times = pairs[0]
        events = judge_press(
            actor_place=before.place,
            facing_before=before.facts.facing,
            button=name,
            times=times,
            after_place=after.place,
            dialog_text=after.facts.dialog_text,
            kind_at=_kind_lookup(before),
        )
        event = events[0] if events else None
    return moved, event


__all__ = ["INTERACTIVE", "judge_press", "observe_step", "press_cells"]
