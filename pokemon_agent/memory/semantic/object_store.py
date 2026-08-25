"""`SemanticObjectStore` 的实现：按"地图 + 坐标"存一格上的东西。**不认识游戏规则。**

键是 `Place.key`，**跨 episode 稳定**——同一张地图上的同一格永远是同一个键，
所以这份档案会随着一局又一局越攒越厚，这正是它的用处。

`see` 和 `touch` 分开：前者看到就记（没互动过的也建档），后者确认碰到了。
"我见过 7 次一次没进过的那扇门"只有在两者分开时才数得出来。

"哪一格算面朝的那一格"不在这里算——那要知道朝向和按键语义，是上一层的事。
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
        """接好底层存储。"""
        self._objects: dict[str, ObjectFact] = {}
        """`(map_id,x,y)` 的 key → 那一格的档案。**语义记忆的全部状态都在这一个字典里。**"""

    # ---- SemanticObjectReader ----

    def query(self, place: Place) -> ObjectFact | None:
        """取这一格的档案，没有就返回 None。"""
        return self._objects.get(place.key)

    def query_map(self, map_id: int) -> list[ObjectFact]:
        """取这张地图上的全部档案，未排序。"""
        return [f for f in self._objects.values() if f.landmark.place.map_id == map_id]

    # ---- SemanticObjectWriter ----

    def see(self, marks: list[Landmark], stamp: str) -> None:
        """把这一帧看到的地标各记一次「见过」。"""
        for mark in marks:
            fact = self._objects.setdefault(
                mark.place.key, ObjectFact(landmark=mark, first_seen=stamp)
            )
            fact.seen += 1
            fact.last_seen = stamp

    def touch(self, place: Place, kind: str, text: str = "") -> ObjectFact:
        """确认这一格上有东西，建档或取回已有档案。"""
        fact = self._objects.setdefault(
            place.key, ObjectFact(landmark=Landmark(kind=kind, place=place))
        )
        fact.touched += 1
        if text:
            fact.see(text)
        return fact

    def record_attempt(self, place: Place, kind: str, key_desc: str, result: str) -> ObjectFact:
        """记下「在这个姿势下碰它得到了什么」。"""
        fact = self._objects.setdefault(
            place.key, ObjectFact(landmark=Landmark(kind=kind, place=place))
        )
        fact.record(key_desc, result)
        return fact
