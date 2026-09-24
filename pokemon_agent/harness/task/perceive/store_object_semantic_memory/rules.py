"""按键 → 物体交互事件：**判定层**（`store/store_object_semantic_memory/rules.py`）。

**它为什么住在 store 域**：这 200 多行是"这一步碰到了什么"的判定规则，唯一的消费者是
`store/object_semantic_memory` 那个节点——按"删掉它唯一的调用者之后还有没有人要"这条
判据，它跟着节点走；而 270 行的判定层塞进节点文件
会让"一节点一文件"的体积失衡，所以那个域拆成包（节点本体在 `__init__.py`，规则在这里）。

memory 层只存事件、不做语义判定（分层原则见 AGENTS.md 四），"发生了什么、
影响了谁"全部在这里算完并构造好事件交给 memory。结构是**先圈候选格、
再按 kind 查姿势判定函数**，不是按按键类型分分支：

- 候选集：脚下这格 + facing 邻格（方向键）；facing 邻格，它不是交互物时再加往前一格
  （a——柜台/桌子会隔一格挡着，对面的人才是一步真正碰到的对象）；
- 每个候选格按 kind 查 `_POSTURES`，姿势函数自己判断"这次按键的几何关系
  属不属于我"，不属于返回 `None` 让位；命中的产出事件。

加新 kind / 加新姿势 = `_POSTURES` 加一行（机制一要求的扩展点），不碰
事件 schema、不碰 memory。

**脚下这格不会被人物精灵挡住。** 门/招牌来自 warp/sign 表，人/物/石来自精灵表——
精灵表遍历时 0 号槽位（玩家自己）被显式跳过（见 `world/ram.py::read_terrain`），
不会覆盖别的精灵的坐标，所以脚下这格该是什么就读得出是什么。

**判定只认 `before` 这一帧自己的 `landmarks`，不查 memory。** 候选格（脚下 + facing 邻格，
或 facing 方向一到两格）都在屏幕可见范围内，RAM 读取又是精确的、不存在"认错"，所以
`before.facts.landmarks` 本身就是这次判定需要的全部依据。查 memory 兜底曾经是这里的
一个机制，但它的前提（"当帧可能因为遮挡读不到"）已经不成立——现在真要读不到，
只可能是这一格本来就没有交互物，兜底带回来的是"以前有过、现在早就不在了"的
过期信息，对本次判定没有意义，反而会让"这次按键碰到了什么"这个问题混进历史。

**多段动作链一律不产出事件**：事件的键是「角色在哪格、按了哪个键」，而一条链的
`before` / `after` 是整条链的两头——中间哪一次按键才是撞在门上的那次，这里看不到。
把 `up×4 -> down×2` 记成"在起点按了一次 up"，写进去的是一条假事件；少记一条
只是慢一点，记错一条会让它以后永远不再试那个正确的碰法。

**这条限制现在被执行粒度消掉了**：`step` 就是一个键（连按已经在 Harness 的
链内小循环里展开），所以本模块收到的恒是单键动作、`len(segments) == 1` 恒成立，
判定层不用改就覆盖了链的每一步。
下面那条多段即返回空的过滤保留着当**前置条件**——它是这一层的输入契约，
不是它要处理的情况。

**没有视觉证据时不判对话**：对话文字只有视觉模型读得出，而链内按键的帧是
`perceived=False`（只读了内存）。这时 `dialog_text` 为空**不是"没弹出对话"，
是"没读过"**——照旧记 `still` 会记出一条假事件（"这个碰法没用"，而事实是
"这次没看见"），比漏记一条贵得多。见 `_dialog_or_still`。
"""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_agent.brain import Action
from pokemon_agent.schemas.memory import (
    ObjectDialogEvent,
    ObjectFactEvent,
    ObjectStillEvent,
    ObjectWarpEvent,
)
from pokemon_agent.world import (
    BUTTON_FACING,
    INTERACT_KEY,
    Observation,
    PlaceInWorld,
)

INTERACTIVE = ("人", "招牌", "门", "物")
"""不含"石"：巨石不弹对话、不会消失，这一版没有推动判定（见 `_POSTURES` 之前的说明），
放进来也没有姿势函数会命中，纯粹多一次无意义的候选格查询。"""


# ---- 候选格与 kind 判定的纯函数（原 memory/semantic/util.py 收编） ----


def press_cells(place: PlaceInWorld, facing: str) -> list[PlaceInWorld]:
    """一次方向键的候选格：`place` **脚下这格 + facing 邻格**，一共 2 格。

    方向键只可能碰到这两格：踩在门上朝外按（脚下这格），或者朝某格走进去
    （门 / 物，都在 facing 邻格）。侧面与背后的格子这次按键碰不到。
    脚下这格不能漏——门这类"站在上面朝外按才切图"的东西只在这里判得出来。
    """
    return [place, place.step_toward(facing)]


def kind_in_frame(
    obs: Observation, place: PlaceInWorld, interactive: tuple[str, ...]
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
    before: Observation
    after: Observation
    actor_place: PlaceInWorld
    button: str
    facing: str


def _common_fields(press: _Press, place: PlaceInWorld, kind: str) -> dict:
    """三种事件共用的字段，**把 `PlaceInWorld` 真身拍平成 `ObjectFactEventBase.
    Place` 快照**——这是本文件（唯一的事件组装方）跟 `schemas.memory` 的边界：
    事件的 `actor_place`/`place` 字段类型是 `ObjectFactEventBase.Place`
    （跟 `PlaceInWorld` 字段一致但类不互相引用的内部类型），不能直接塞真身
    进去，要在这里转一次。
    """
    return {
        "episode_id": press.episode_id,
        "step": press.step,
        "actor_place": press.actor_place.model_dump(),
        "place": place.model_dump(),
        "object_kind": kind,
        "button": press.button,
    }


def _dialog_or_still(press: _Press, place: PlaceInWorld, kind: str) -> ObjectFactEvent | None:
    """a 键互动的两种结局：弹出对话记正文，什么都没有记 still。

    **这一帧没做过视觉感知就直接让位**（返回 `None`，不产出事件）：链内按键
    的 `after` 是 RAM-only 快照，`dialog_text` 恒为空——那是"没读过"，
    不是"读出来什么都没有"。硬判成 `still` 会把"这次没看见"写成
    "这个碰法没用"，而被写错的记忆会被以后每一步当真。
    """
    if not press.after.perceived:
        return None
    text = press.after.facts.dialog_text
    common = _common_fields(press, place, kind)
    if text.strip():
        return ObjectDialogEvent(**common, text=text)
    return ObjectStillEvent(**common)


def _warp_or_still(press: _Press, place: PlaceInWorld, kind: str) -> ObjectFactEvent:
    """方向键的两种结局：穿过这格进新图记 warp，否则记 still。"""
    common = _common_fields(press, place, kind)
    after_place = press.after.place
    assert after_place is not None
    if after_place.map_id != press.before.place.map_id:
        return ObjectWarpEvent(**common, map_id=after_place.map_id)
    return ObjectStillEvent(**common)


def _door_walk_into(press: _Press, candidate: PlaceInWorld, kind: str) -> ObjectFactEvent | None:
    """姿势：面向门走过去——门在 facing 邻格，角色朝它走进去。

    游戏里有两种门：室外进室内的门走上去当拍切图（记 warp）；室内出去、门房这类门
    走上去不切图，要站在门格上再朝外按一次（那一次归 `_door_stand_on_push` 判）。
    所以**走上了门格、地图没变**不是"这个碰法没用"，只是还没到判定的那一拍——
    让位不产出事件；只有被挡住、根本没走上去时才记 still。
    """
    if candidate != press.actor_place.step_toward(press.facing):
        return None
    after = press.after.place
    assert after is not None
    if after.map_id == press.before.place.map_id and after.key == candidate.key:
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
    before: Observation,
    action: Action,
    after: Observation,
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
    # ========== 1. 前提过滤——没位置、没按键、多段链，都不产出。 ==========
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

    # ========== 2. 按按键类型圈候选格。a：facing 一格，不是交互物再看两格； ==========
    # 方向键：脚下 + facing 邻格，且只认"没有先转向"的那一步——先转向再走
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
        candidates = press_cells(before.place, facing)

    # ========== 3. 按 kind 查姿势函数，命中的产出事件。 ==========
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
