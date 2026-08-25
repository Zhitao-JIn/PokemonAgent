"""语义记忆（object）的存储接口：**"那一格上的东西是什么"**。

和情景记忆是两类东西，别混：情景记忆记"我在那种画面里选了什么"（作用域是一次
经过、有时效），这里记"地图 39 的 x=2 y=3 站着的人会说什么"（作用域是那一格，
域内恒真、域会再现）。混进一张表，就数不出"它认识了多少个东西"——
而那是语义记忆有没有用的直接指标。

**这一层不认识游戏规则**，只做存取：建档、计数、记一次尝试的结果。
"哪一格算面朝的那一格"是上面算好了递进来的。

`see`（看到就建档，没互动过的也建）和 `touch`（确认碰到了）分开，是因为
"我见过 7 次一次没进过的那扇门"正是这份档案最有用的一类条目。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.object_fact import ObjectFact
from pokemon_agent.schemas.observation import Landmark, Place


@runtime_checkable
class SemanticObjectReader(Protocol):
    """语义记忆（object）的读端：查"世界是什么样"，不改变任何状态。"""

    def query(self, place: Place) -> ObjectFact | None:
        """这一格有没有档案。**没有就返回 None，不返回空对象**——

        调用方要能区分"这一格什么都不知道"和"知道但是空的"，
        后者在这套设计里不会出现（`touch()`/`record_attempt()`/`see()`
        建档时至少会留下 `seen`/`touched` 计数），但协议不该靠"反正不会发生"
        去回避这个区分。

        取这一格的档案，没有就返回 None。
        """
        ...

    def query_map(self, map_id: int) -> list[ObjectFact]:
        """这张地图上全部档案，**未排序**——排序、筛选、渲染成文字都是调用方的事。

        只按地图筛，不按屏幕筛：见 `ObjectMemory`（具体实现）的说明，
        协议这一层只需要知道"按地图筛"这个粒度就够了。

        取这张地图上的全部档案，未排序。
        """
        ...


@runtime_checkable
class SemanticObjectWriter(Protocol):
    """语义记忆（object）的写端：三种写入对应三类不同的观察，**不合并成一个方法**——

    合并了就没法在类型层面看出"这次调用到底在断言什么"，而这三类断言的
    可信来源完全不同（说明见各自的 docstring）。
    """

    def see(self, marks: list[Landmark], stamp: str) -> None:
        """这一帧看到的地标全部记一遍 `seen`，**没互动过的也建档**。

        前置条件：`stamp` 非空，且**调用方保证一步只调一次**——
        `seen` 答的是"进过几次视野"，调两次这个数就没有意义了，
        但这一层不知道"一步"是什么，这条约束靠调用方（`MemoryTool`）守。

        把这一帧看到的地标各记一次「见过」。
        """
        ...

    def touch(self, place: Place, kind: str, text: str = "") -> ObjectFact:
        """确认这一格上有个东西：建档或取已有档案，`touched += 1`；`text` 非空则记一句。

        `kind` 由调用方给（当帧地标或档案兜底，见 `memory/util.py`），
        这一层不判断"这一格上到底是什么"——那是几何/解析的事，不是存储的事。

        确认这一格上有东西，建档或取回已有档案。
        """
        ...

    def record_attempt(self, place: Place, kind: str, key_desc: str, result: str) -> ObjectFact:
        """记下一次尝试：`place` 上那个东西，在 `key_desc` 这个姿势下，结果是 `result`。

        前置条件：`key_desc`、`result` 非空。`result` 必须是 `RESULT_NONE` /
        `RESULT_DIALOG` / 或以 `RESULT_WARP_PREFIX` 开头——**这一层不校验**，
        校验值域是调用方的事（它就是算出这个值的人），这一层只管存。

        记下「在这个姿势下碰它得到了什么」。
        """
        ...


@runtime_checkable
class SemanticObjectStore(SemanticObjectReader, SemanticObjectWriter, Protocol):
    """存储协议：读写的并集，是一个具体后端（`ObjectMemory`）要满足的全集。"""
