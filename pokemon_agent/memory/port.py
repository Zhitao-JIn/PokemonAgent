"""语义记忆的**存储协议**——`memory/` 这一层要对外承诺什么。

现在只有一类语义记忆：object（门/招牌/人）。协议按"输入 / 输出"拆成两半，
再合成一个"存储"协议，理由是三件事分别回答不同的问题：

    Reader   语义记忆能被**查**到什么           —— 输出
    Writer   什么样的观察会**写进**语义记忆      —— 输入
    Store    一个具体后端要满足的**全集**         —— 存储

拆成读写两半而不是一个protocol，是为了将来某个消费方可能**只该读、不该写**——
比如给判定器一份只读视图，类型层面就能保证它写不进去，不用靠约定。

**这是底层协议，不是大脑看到的接口。** 大脑连"语义记忆"这个词都不该知道；
`tools/memory_tool.py` 里的 `MemoryTool` 组合这个协议、翻译成 Harness 能用的方法，
`interfaces/tools.py` 的 `MemoryToolPort` 才是 Harness 真正认识的那一层。
`ObjectMemory`（`memory/semantic/object_store.py`）实现这个协议——
换存储后端（比如换成 sqlite）只需要另写一个类满足这个协议，
`MemoryTool` 和它的调用方一行都不用改。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.memory_semantic import ObjectFact
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
        """
        ...

    def query_map(self, map_id: int) -> list[ObjectFact]:
        """这张地图上全部档案，**未排序**——排序、筛选、渲染成文字都是调用方的事。

        只按地图筛，不按屏幕筛：见 `ObjectMemory`（具体实现）的说明，
        协议这一层只需要知道"按地图筛"这个粒度就够了。
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
        """
        ...

    def touch(self, place: Place, kind: str, text: str = "") -> ObjectFact:
        """确认这一格上有个东西：建档或取已有档案，`touched += 1`；`text` 非空则记一句。

        `kind` 由调用方给（当帧地标或档案兜底，见 `memory/util.py`），
        这一层不判断"这一格上到底是什么"——那是几何/解析的事，不是存储的事。
        """
        ...

    def record_attempt(self, place: Place, kind: str, key_desc: str, result: str) -> ObjectFact:
        """记下一次尝试：`place` 上那个东西，在 `key_desc` 这个姿势下，结果是 `result`。

        前置条件：`key_desc`、`result` 非空。`result` 必须是 `RESULT_NONE` /
        `RESULT_DIALOG` / 或以 `RESULT_WARP_PREFIX` 开头——**这一层不校验**，
        校验值域是调用方的事（它就是算出这个值的人），这一层只管存。
        """
        ...


@runtime_checkable
class SemanticObjectStore(SemanticObjectReader, SemanticObjectWriter, Protocol):
    """存储协议：读写的并集，是一个具体后端（`ObjectMemory`）要满足的全集。"""
