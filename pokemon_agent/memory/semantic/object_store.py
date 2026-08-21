"""`ObjectMemory` —— `SemanticObjectStore` 协议（见 `memory/port.py`）的具体实现。

**纯存储，没有编排逻辑。** 它只知道"按坐标存一条 `ObjectFact`、按坐标/按地图取"，
不知道"一次按键该查哪几格候选""这次尝试算不算数"这类**编排**问题——
那些是 `tools/memory_tool.py` 的活（它是 Harness 真正调用的那一层，
拿着 `before`/`action`/`after` 三个观测去决定该调这个类的哪个方法）。

这条边界是这次重写要立的规矩：以前的 `ObjectMemory.note_step()` 一个方法里
混了"这次按键碰到了什么候选""朝向算不算数""要不要跳过连按"和"写进哪条档案"——
存储和编排揉在一起，换存储后端（哪怕只是想加个 sqlite）就得把编排逻辑照抄一遍。
拆开之后这个类只有五个方法，**没有一个知道"按键""朝向""连按"这些游戏概念**。
"""

from __future__ import annotations

from pokemon_agent.schemas.memory_semantic import ObjectFact
from pokemon_agent.schemas.observation import Landmark, Place


class ObjectMemory:
    """`SemanticObjectStore` 的默认实现：进程内的一个 `dict`。

    **不随 episode 清空**——"地图39 x=2 y=3 那个人不是母亲"这件事，
    下一局仍然成立，跨局复用正是要验证的东西。清空的话机是每次 `Harness.reset()`
    该做的事，不是这个类自己的责任。
    """

    def __init__(self) -> None:
        self._objects: dict[str, ObjectFact] = {}
        """`(map_id,x,y)` 的 key → 那一格的档案。**语义记忆的全部状态都在这一个字典里。**"""

    # ---- SemanticObjectReader ----

    def query(self, place: Place) -> ObjectFact | None:
        return self._objects.get(place.key)

    def query_map(self, map_id: int) -> list[ObjectFact]:
        return [f for f in self._objects.values() if f.landmark.place.map_id == map_id]

    # ---- SemanticObjectWriter ----

    def see(self, marks: list[Landmark], stamp: str) -> None:
        for mark in marks:
            fact = self._objects.setdefault(
                mark.place.key, ObjectFact(landmark=mark, first_seen=stamp)
            )
            fact.seen += 1
            fact.last_seen = stamp

    def touch(self, place: Place, kind: str, text: str = "") -> ObjectFact:
        fact = self._objects.setdefault(
            place.key, ObjectFact(landmark=Landmark(kind=kind, place=place))
        )
        fact.touched += 1
        if text:
            fact.see(text)
        return fact

    def record_attempt(self, place: Place, kind: str, key_desc: str, result: str) -> ObjectFact:
        fact = self._objects.setdefault(
            place.key, ObjectFact(landmark=Landmark(kind=kind, place=place))
        )
        fact.record(key_desc, result)
        return fact
