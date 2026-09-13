"""`MemoryStorePort`：memory 包的对外契约——写入 + 过滤检索 + 语义检索 + 归档。

**这个文件随 `memory/` 包一起走。** 0910 拍板（`docs/ROADMAP.md` 第 24 条）：
memory 子系统要能被整体拷到别的项目里用，所以它的契约不住在 `interfaces/`
（那是本项目的跨层港口目录），而是与实现同住一个包——拷 `memory/` 就同时拿到
契约 + 实现 + 检索算法，不需要回头翻本项目的 `interfaces/`。

0908 会话拍板的接口形状：memory 不再为每种检索维度（按局、按图、按格、按场景……）
各开一个专用方法，只对外提供这一份通用接口。字段叫什么、值是什么、payload 装的
是什么，对这个接口完全不透明——调用方（tool 层）自己决定怎么拼 metadata、
怎么拼检索用的 text。

**过滤检索只支持等值/成员匹配（AND-of-equalities 取交集），不支持大小比较**——这是
索引支持的操作类型的限制，不是字段身份的限制：任何字段都能做等值查询，
地位完全对等，没有谁是"主键"。数值型的大小比较（比如"哪些记录的 step 小于
某个数"）由调用方自己先用等值条件（比如 episode_id）把候选集筛到足够小，
再对候选集里的字段做数值比较——这是调用方的领域知识，不是这个接口该内置
的规则。

**语义检索内部怎么排（分词/BM25/embedding/RRF/reranker）对外完全不透明**——
调用方只给一句话，回来的是排好序的 uuid，不需要也不能干预排序过程。

**实现方约定（`memory/store.py`）**：一个实例绑定一个 kind（=
`memory/` 下的一个子文件夹）；每文件夹一份倒排索引 `index.json` 随记录写穿，
真相永远是记录文件（一条记录一个 `<uuid>.json/.md`），索引是可自愈重建的
派生物——见 `PLAN_memory_trace_layout.md` §5.1。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryStorePort(Protocol):
    """记忆的读写端：写入、点查、过滤检索、语义检索、归档。

    名字里的 Store 是**角色**而不是"只写"：这一层既是记录的落点，也是
    过滤检索与语义检索的入口，读和写都从它走。
    """

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

    def get(self, uuid: str) -> tuple[dict[str, str], dict, str] | None:
        """按 uuid 点查一条记录，返回 (metadata, payload, text)；不存在返回 None。"""
        ...

    def get_many(self, uuids: Sequence[str]) -> list[tuple[str, dict[str, str], dict, str]]:
        """批量点查，返回 [(uuid, metadata, payload, text), ...]。

        后置条件：跳过不存在的 uuid（不报错、结果比传入的 uuids 短），
            返回顺序不保证跟传入顺序一致。
        """
        ...

    def filter(self, conditions: dict[str, str]) -> list[str]:
        """等值过滤检索：conditions 里全部字段都命中的记录，返回它们的 uuid。

        conditions：字段→值，只支持 AND-of-equalities（各条件候选集取交集），
            不支持 OR、不支持大小比较。为空表示不过滤，返回全部记录的 uuid。
        """
        ...

    def search(self, query: str, limit: int, conditions: dict[str, str] | None = None) -> list[str]:
        """语义相似度检索：给一句话，按相关性降序返回最多 limit 个 uuid。

        conditions 非空时先做等值过滤圈定候选范围（同一套交集），再在候选
        范围内检索排序（只在有 text 的记录里找，没写 text 的记录搜不到）。

        前置条件：query 非空、limit > 0。
        后置条件：返回长度 <= limit，候选范围为空时返回空列表（不报错）。
        """
        ...

    def rank(self, uuids: Sequence[str], query: str, fuse_top_k: int) -> list[tuple[str, float]]:
        """对一个**给定候选集**做混合检索排序，返回 [(uuid, 相关性分)] 降序。

        `search()` 是"filter 圈候选 + 截断"的便捷封装；`rank` 是底层原语——
        调用方要按自己的领域规则先把候选筛过一遍（场景匹配、质量粗筛等）
        再进来，过滤逻辑不归这一层。没有 text 的候选直接跳过。

        前置条件：query 非空、fuse_top_k > 0。
        后置条件：返回长度 <= len(uuids)，按相关性降序。
        """
        ...

    def archive_many(self, uuids: Sequence[str], dest_dir: Path) -> int:
        """把一批记录搬进 `dest_dir` 并摘出索引——**"让记录消失"的唯一路径**，
        不 unlink："落盘了就不丢"贯彻到退出检索的每一条记录，归档文件仍在盘上可查。

        当前唯一调用方是 `MemoryTool._trim_summaries()`（跨局摘要超容量时按质量
        淘汰，搬进 `memory/voided-<ts>/<kind>/`）。局正常收尾不搬任何记录——
        step 记忆按 `episode_id` 查询天然隔离，没有清场的必要。

        后置条件：返回实际归档的条数；不存在的 uuid 跳过。
        """
        ...

    def count(self) -> int:
        """当前在索引里的记录条数（不含已归档的）。"""
        ...

    def refresh_changed(self) -> None:
        """md 类记录文件被直接编辑过（mtime 变了）就重读整条记录：正文重算向量、
        frontmatter 里的 metadata 重建倒排——保留"运营改 `.md` 不重启进程就
        生效"的性质。正文与 metadata 都要刷新，否则改了过滤字段（如 `source`）
        `filter()` 查不到新值。json 类运行期写穿产物，实现方应做成 no-op。
        """
        ...
