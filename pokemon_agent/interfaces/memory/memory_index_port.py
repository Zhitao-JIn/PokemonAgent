"""`MemoryIndexPort`：项目无关的记忆检索接口——写入 + 过滤检索 + 语义检索 + 删除。

0908 会话拍板（`docs/ROADMAP.md` 第 24 条）的接口设计：memory 不再为每种
检索维度（按局、按图、按格、按场景……）各开一个专用方法，只对外提供这一份
通用接口。字段叫什么、值是什么、payload 装的是什么，对这个接口完全不透明——
调用方（tool 层）自己决定怎么拼 metadata、怎么拼检索用的 text。

**过滤检索只支持等值/成员匹配（AND-of-equalities），不支持大小比较**——这是
索引支持的操作类型的限制，不是字段身份的限制：任何字段都能做等值查询，
地位完全对等，没有谁是"主键"。数值型的大小比较（比如"哪些记录的 step 小于
某个数"）由调用方自己先用等值条件（比如 episode_id）把候选集筛到足够小，
再对候选集里的字段做数值比较——这是调用方的领域知识，不是这个接口该内置
的规则。

**语义检索内部怎么排（分词/BM25/embedding/RRF/reranker）对外完全不透明**——
调用方只给一句话，回来的是排好序的 uuid，不需要也不能干预排序过程。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryIndexPort(Protocol):
    """记忆索引的读写端：写入、点查、过滤检索、语义检索、删除。"""

    def put(self, metadata: dict[str, str], payload: dict, text: str = "") -> str:
        """写入一条记录，返回 memory 生成的 uuid。

        metadata：字段→值，过滤检索用（值本身怎么序列化由调用方决定）。
        payload：调用方自己的结构化数据，原样存取，检索不碰、也不解析——
            二进制内容（比如截图）由调用方自己转成 base64 字符串放进去。
        text：给语义检索用的、渲染好的文本；空字符串表示这条记录不参与语义
            检索（仍然能被 filter() 命中，只是 search() 搜不出来）。写入时
            就把 text 的向量算好缓存，search() 不用每次现算。

        前置条件：text 非空时会调用注入的 EmbeddingProvider，失败原样抛出
            （不静默降级成"这条没有向量"）。
        后置条件：返回的 uuid 全局唯一，不带任何语义，调用方不能从
            metadata 反推出它。
        """
        ...

    def get(self, uuid: str) -> tuple[dict[str, str], dict] | None:
        """按 uuid 点查一条记录，返回 (metadata, payload)；不存在返回 None。"""
        ...

    def get_many(self, uuids: Sequence[str]) -> list[tuple[str, dict[str, str], dict]]:
        """批量点查，返回 [(uuid, metadata, payload), ...]。

        后置条件：跳过不存在的 uuid（不报错、结果比传入的 uuids 短），
            返回顺序不保证跟传入顺序一致。
        """
        ...

    def filter(self, conditions: dict[str, str]) -> list[str]:
        """等值过滤检索：conditions 里全部字段都命中的记录，返回它们的 uuid。

        conditions：字段→值，只支持 AND-of-equalities，不支持 OR、不支持
            大小比较。为空表示不过滤，返回全部记录的 uuid。
        """
        ...

    def search(
        self, query: str, limit: int, conditions: dict[str, str] | None = None
    ) -> list[str]:
        """语义相似度检索：给一句话，按相关性降序返回最多 limit 个 uuid。

        conditions 非空时先做等值过滤圈定候选范围，再在候选范围内检索排序
        （只在有 text 的记录里找，没写 text 的记录搜不到）。

        前置条件：query 非空、limit > 0。
        后置条件：返回长度 <= limit，候选范围为空时返回空列表（不报错）。
        """
        ...

    def delete_many(self, uuids: Sequence[str]) -> None:
        """按 uuid 列表删除记录（幂等——传进来的 uuid 不存在就跳过）。

        不接受条件式删除：要删一批"满足某个条件"的记录，调用方自己先
        filter()（必要时再用 get_many() 拿到的字段做数值判断筛一遍），
        拿到 uuid 列表再传进来——跟"大小比较不进过滤检索"是同一个道理，
        删除也不例外。
        """
        ...
