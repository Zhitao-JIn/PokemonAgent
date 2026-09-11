"""按键 → 物体交互事件：harness 侧的判定层。

memory 层只存事件、不做语义判定（分层原则见 AGENTS.md 四），"发生了什么、
影响了谁"全部在这里算完并构造好事件交给 memory。结构是**先圈候选格、
再按 kind 查姿势判定函数**，不是按按键类型分分支：

- 候选集：脚下这格 + 四邻（方向键）；facing 邻格 + 再往前一格（a——
  柜台/桌子会隔一格挡着，对面的人才是一步真正碰到的对象）；
- 每个候选格按 kind 查 `_POSTURES`，姿势函数自己判断"这次按键的几何关系
  属不属于我"，不属于返回 `None` 让位；命中的产出事件。

加新 kind / 加新姿势 = `_POSTURES` 加一行（机制一要求的扩展点），不碰
事件 schema、不碰 memory。

**脚下这格不会被人物精灵挡住。** 门/招牌来自 warp/sign 表，人/物/石来自精灵表——
精灵表遍历时 0 号槽位（玩家自己）被显式跳过（见 `world/ram.py::read_terrain`），
不会覆盖别的精灵的坐标，所以脚下这格该是什么就读得出是什么。

**判定只认 `before` 这一帧自己的 `landmarks`，不查 memory。** 候选格（脚下 + 四邻，
或 facing 方向）都在屏幕可见范围内，RAM 读取又是精确的、不存在"认错"，所以
`before.facts.landmarks` 本身就是这次判定需要的全部依据。查 memory 兜底曾经是这里的
一个机制，但它的前提（"当帧可能因为遮挡读不到"）已经不成立——现在真要读不到，
只可能是这一格本来就没有交互物，兜底带回来的是"以前有过、现在早就不在了"的
过期信息，对本次判定没有意义，反而会让"这次按键碰到了什么"这个问题混进历史。

**多段动作链一律不产出事件**：事件的键是「角色在哪格、按了哪个键」，而一条链的
`before` / `after` 是整条链的两头——中间哪一次按键才是撞在门上的那次，这里看不到。
把 `up×4 -> down×2` 记成"在起点按了一次 up"，写进去的是一条假事件；少记一条
只是慢一点，记错一条会让它以后永远不再试那个正确的碰法。
"""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_agent.brain import ActionFromBrain
from pokemon_agent.schemas.memory import (
    ObjectDialogEvent,
    ObjectFactEvent,
    ObjectStillEvent,
    ObjectWarpEvent,
)
from pokemon_agent.schemas.world import (
    BUTTON_FACING,
    FACING_STEP,
    INTERACT_KEY,
    ObservationFromWorld,
    PlaceInWorld,
)

INTERACTIVE = ("人", "招牌", "门", "物")
"""不含"石"：巨石不弹对话、不会消失，这一版没有推动判定（见 `_POSTURES` 之前的说明），
放进来也没有姿势函数会命中，纯粹多一次无意义的候选格查询。"""


# ---- 候选格与 kind 判定的纯函数（原 memory/semantic/util.py 收编） ----


def surrounding_cells(place: PlaceInWorld) -> list[PlaceInWorld]:
    """`place` **脚下这格 + 四个相邻格**，一共 5 格。

    这是一次方向键按下去唯一可能影响到的范围——按键要么改变自己脚下这格
    的状态（踩在门上朝外按），要么作用在某个相邻格上（从旁边推）。
    叫 `surrounding_cells` 不叫 `ring`：这五格是"十"字形（含中心），
    中心（脚下）容易被漏掉不是因为读不到——门/物这类会触发"踩上去就变"
    （warp / 拾取）的东西，恰恰是判定脚下这格才有意义。
    """
    return [place] + [
        PlaceInWorld(map_id=place.map_id, x=place.x + dx, y=place.y + dy)
        for dx, dy in FACING_STEP.values()
    ]


def kind_in_frame(
    obs: ObservationFromWorld, place: PlaceInWorld, interactive: tuple[str, ...]
) -> str | None:
    """`place` 这一格在这一帧的 `obs.facts.landmarks` 里是什么。认不出来返回 `None`。

    直接读 `Facts.landmarks`（结构化原件，见该字段文档）——不再有"渲染成文本再
    解析回来"这一趟，也不再需要向 memory 查历史兜底：候选格都在屏幕可见范围内，
    RAM 读取本身就是精确、当场的。
    """
    for mark in obs.facts.landmarks:
        if mark.place.key == place.key and mark.kind in interactive:
            return mark.kind
    return None


# ---- kind → 姿势判定函数 ----


@dataclass(frozen=True)
class _Press:
    """一次干净按键的全部上下文——姿势判定函数只看这个。"""

    episode_id: str
    step: int
    before: ObservationFromWorld
    after: ObservationFromWorld
    actor_place: PlaceInWorld
    button: str
    facing: str


def _dialog_or_still(press: _Press, place: PlaceInWorld, kind: str) -> ObjectFactEvent:
    """a 键互动的两种结局：弹出对话记正文，什么都没有记 still。"""
    text = press.after.facts.dialog_text
    common = {
        "episode_id": press.episode_id,
        "step": press.step,
        "actor_place": press.actor_place,
        "place": place,
        "kind": kind,
        "button": press.button,
    }
    if text.strip():
        return ObjectDialogEvent(**common, text=text)
    return ObjectStillEvent(**common)


def _warp_or_still(press: _Press, place: PlaceInWorld, kind: str) -> ObjectFactEvent:
    """方向键的两种结局：穿过这格进新图记 warp，否则记 still。"""
    common = {
        "episode_id": press.episode_id,
        "step": press.step,
        "actor_place": press.actor_place,
        "place": place,
        "kind": kind,
        "button": press.button,
    }
    after_place = press.after.place
    assert after_place is not None
    if after_place.map_id != press.before.place.map_id:
        return ObjectWarpEvent(**common, map_id=after_place.map_id)
    return ObjectStillEvent(**common)


def _door_walk_into(press: _Press, candidate: PlaceInWorld, kind: str) -> ObjectFactEvent | None:
    """姿势：面向门走过去——门在 facing 邻格，角色朝它走进去。"""
    if candidate != press.actor_place.step_toward(press.facing):
        return None
    return _warp_or_still(press, candidate, kind)


def _pickup_or_still(press: _Press, candidate: PlaceInWorld, kind: str) -> ObjectFactEvent | None:
    """姿势：走上物品格——拾取脚本在踏入的同一拍触发，弹出「获得了 XXX」对话，
    跟 a 键弹对话框是同一种结局判定（复用 `_dialog_or_still`），只是触发键
    是方向键（走进去），不是 a——面朝物品按 a 在游戏里什么都不会发生。

    前置条件：candidate 是 facing 邻格（跟 `_door_walk_into` 同一个姿势几何，
    物品不会像门那样"站在格子上朝外按"，因为站上去的同一拍它已经被捡走了）。
    """
    if press.button == INTERACT_KEY:
        return None
    if candidate != press.actor_place.step_toward(press.facing):
        return None
    return _dialog_or_still(press, candidate, kind)


def _door_stand_on_push(
    press: _Press, candidate: PlaceInWorld, kind: str
) -> ObjectFactEvent | None:
    """姿势：踩在门格上朝外按方向——角色位置就是门格本身。"""
    if candidate != press.actor_place:
        return None
    return _warp_or_still(press, candidate, kind)


def _interact_dialog(press: _Press, candidate: PlaceInWorld, kind: str) -> ObjectFactEvent | None:
    """姿势：正对着它（或隔柜台）按 a——只有 a 键算对话尝试。"""
    if press.button != INTERACT_KEY:
        return None
    return _dialog_or_still(press, candidate, kind)


_POSTURES: dict[str, tuple] = {
    "门": (_door_walk_into, _door_stand_on_push, _interact_dialog),
    "人": (_interact_dialog,),
    "招牌": (_interact_dialog,),
    "物": (_pickup_or_still,),
}


# ---- 入口 ----


def object_fact_events(
    before: ObservationFromWorld,
    action: ActionFromBrain,
    after: ObservationFromWorld,
    episode_id: str,
    step: int,
) -> list[ObjectFactEvent]:
    """判定这次按键碰到了哪些物体、各发生了什么，产出待追加的交互事件。

    前置条件：`before`/`after` 都带 `place`（角色位置）——多段动作链
        （`segments()` 多于一段）**不产出事件**：链的两头拼不出"哪一次
        按键才是撞上去的那次"，宁可漏记不记错。
    后置条件：返回的事件按 `place` 唯一（同格只出一条）；列表可为空
        （这次按键没有碰到任何已知交互物，空列表不是错误）。
    """
    # 步骤 1：前提过滤——没位置、没按键、多段链，都不产出。
    if before.place is None or after.place is None or not action.segments():
        return []
    segments = action.segments()
    if len(segments) != 1:
        return []
    segment = segments[0]

    facing = BUTTON_FACING.get(segment.name, before.facts.facing)
    if not facing:
        return []
    press = _Press(
        episode_id=episode_id,
        step=step,
        before=before,
        after=after,
        actor_place=before.place,
        button=segment.name,
        facing=facing,
    )

    # 步骤 2：按按键类型圈候选格。a 的目标在 facing 方向（可能隔一个柜台）；
    # 方向键影响脚下 + 四邻，且只认"没有先转向"的那一步——先转向再走
    # 不算一次干净的碰撞尝试。
    if segment.name == INTERACT_KEY:
        ahead = before.place.step_toward(facing)
        candidates = [ahead]
        if kind_in_frame(before, ahead, INTERACTIVE) is None:
            candidates.append(ahead.step_toward(facing))
    else:
        if segment.times != 1:
            return []
        if before.facts.facing != facing:
            return []
        candidates = surrounding_cells(before.place)

    # 步骤 3：按 kind 查姿势函数，命中的产出事件。
    events: list[ObjectFactEvent] = []
    for candidate in candidates:
        kind = kind_in_frame(before, candidate, INTERACTIVE)
        if kind is None:
            continue
        for posture in _POSTURES.get(kind, ()):
            event = posture(press, candidate, kind)
            if event is not None:
                events.append(event)
    return events
