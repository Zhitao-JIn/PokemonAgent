"""`MemoryStorePort`：memory 包的对外契约——写入 + 过滤检索 + 语义检索 + 删除 + 快照。

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
派生物。**快照打的是整个记忆根**（四族一起），不是本实例的 kind。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryStorePort(Protocol):
    """记忆的读写端：写入、点查、过滤检索、语义检索、删除、快照。

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

        前置条件：text 非空时会调用注入的 EmbeddingProviderPort，失败原样抛出
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

    def delete_many(self, uuids: Sequence[str]) -> int:
        """把一批记录删掉（摘出索引 + unlink 记录文件）——**"让记录消失"的唯一路径**。

        当前唯一调用方是 `MemoryTool._trim_summaries()`（跨局摘要超容量时按质量
        淘汰）。局正常收尾不删任何记录——step 记忆按 `episode_id` 查询天然隔离，
        没有清场的必要。

        **0916 起不再有"归档"**：原先这条叫 `archive_many`，把文件搬进
        `voided-<ts>/<kind>/` 留档；有了 `snapshot()` 之后那套中间态就没有意义了
        ——要留档就在淘汰之前先拍张快照，淘汰本身该是干脆的。

        后置条件：返回实际删掉的条数；不存在的 uuid 跳过。
        """
        ...

    def snapshot(self, name: str) -> Path:
        """把**整个记忆根**打包成一个 zip，返回 zip 路径（同名覆盖）。

        **打的是整个根、不是本实例的 kind**：四个 store 共享一个 `memory/` 根，
        "这一族"和"整个库"在快照这个语义下不是一回事——调用方要的是一份能整体
        还原的存档。

        **zip 落在哪由实现方决定**，调用方只给 `name`（一个不带路径分隔符的
        文件名）——"快照放哪、叫什么后缀、要不要单独一个目录"都是存储层自己的
        事，harness 不该知道（所以签名里没有 dest）。

        前置条件：`name` 非空、不含路径分隔符。
        后置条件：返回的路径存在且是个 zip；里面装着各 kind 子目录的记录文件与
            `index.json`。
        """
        ...

    def restore(self, archive: str | Path) -> int:
        """用一个 zip 把记忆根**还原到那一刻**，返回解出的文件数。

        **以 zip 为准**：zip 里有的记录文件按 zip 写（同名直接盖），**zip 里没有的
        记录文件从库里删掉**。"删掉库里多出来的那些"不是额外选项——它就是"恢复到
        某个存档"的定义（否则越恢复越多，快照也就不叫存档了）。实现上不必先清空
        整根：先删多出来的、再写 zip 里的即可，`index.json` 这类派生文件随 zip
        一起回来直接被覆盖。

        后置条件：各 kind 子目录的内容与 zip 逐条对应；实现方必须**重读索引**，
            让内存态与盘上重新一致（否则被删掉的记录会从旧索引里冒出来）。
        失败：`archive` 不存在或不是合法 zip 时原样抛出，不静默吞掉。
        """
        ...

    def count(self) -> int:
        """当前在索引里的记录条数（不含已删的）。"""
        ...

    def refresh_changed(self) -> None:
        """md 类记录文件被直接编辑过（mtime 变了）就重读整条记录：正文重算向量、
        frontmatter 里的 metadata 重建倒排——保留"运营改 `.md` 不重启进程就
        生效"的性质。正文与 metadata 都要刷新，否则改了过滤字段（如 `source`）
        `filter()` 查不到新值。json 类运行期写穿产物，实现方应做成 no-op。
        """
        ...
