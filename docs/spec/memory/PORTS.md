# memory 模块对外暴露的 Port 与出口清单

- 日期：2026-09-16
- 关联：`AGENTS.md` 铁律 2/3、`docs/experiences/2026-09-13-memory-decoupling-audit.md`
- 用途：查"memory 对外承诺了什么"，改 memory 前先核这里
- 原则：**端口收裸字段，不认识本项目的 `*Req` 信封**（铁律 3）
- 分工：**这份讲契约与边界核对**（怎么改才不破约）；
  逐方法的调用姿势、落盘样例、最小用法见 [`API.md`](./API.md)；
  模块全貌见 [`SPEC.md`](./SPEC.md)

---

## 一、总览：一个 Port，零个信封

```
memory/
├── ports.py                  ← 【对外唯一 Port】MemoryStorePort
├── embedding_provider.py     ← 【对外协议】EmbeddingProviderPort
├── reranker_provider.py      ← 【对外协议】RerankerProviderPort
├── store.py                  ← 【实现】LocalMemoryStore（implements MemoryStorePort）
├── fastembed_text.py         ← 【实现】LocalEmbeddingProvider（implements EmbeddingProviderPort）
├── fastembed_reranker.py     ← 【实现】LocalRerankerProvider（implements RerankerProviderPort）
├── retrieval.py              ← 【纯函数库】5 个检索函数，非 Port
└── __init__.py               ← 【统一出口】6 个名字 re-export（0916 收窄）
```

**对外只有 1 个 Port**（`MemoryStorePort`），另有 **2 个协议**（embedding /
reranker）是给注入用的，**不是** memory 自己的对外能力。

三者关系：`MemoryStorePort` 是 memory 的**唯一对外契约**；两个 provider 协议是
memory **对内要求调用方提供**的东西（依赖注入的另一侧，见铁律「依赖注入」）。

**零信封**：memory 从来看不到 `FromHarnessToMemoryTool*` 那 22 个信封
（12 个 `…Req` + 10 个 `…Resp`）。信封由 harness 组装、`tools/memory_tool.py` 拆解，
到 memory 边界只剩裸字段。

---

## 二、`MemoryStorePort`（`memory/ports.py`）

```python
@runtime_checkable
class MemoryStorePort(Protocol):
    """记忆的读写端：写入、点查、过滤检索、语义检索、删除、快照。"""
```

**11 个方法**（铁律：超过 6 个该拆——这里靠"读写两层职责"划的界，
写入/删除/快照一组、点查/检索一组，见下）。全部只收裸字段：

| # | 方法 | 签名 | 属于 |
|---|---|---|---|
| 1 | `put` | `(metadata: dict[str,str], payload: dict, text: str = "") -> str` | 写 |
| 2 | `get` | `(uuid: str) -> tuple[dict[str,str], dict, str] \| None` | 读 |
| 3 | `get_many` | `(uuids: Sequence[str]) -> list[tuple[str, dict[str,str], dict, str]]` | 读 |
| 4 | `filter` | `(conditions: dict[str,str]) -> list[str]` | 检索 |
| 5 | `search` | `(query: str, limit: int, conditions: dict[str,str] \| None = None) -> list[str]` | 检索 |
| 6 | `rank` | `(uuids: Sequence[str], query: str, fuse_top_k: int) -> list[tuple[str, float]]` | 检索 |
| 7 | `delete_many` | `(uuids: Sequence[str]) -> int` | 写 |
| 8 | `count` | `() -> int` | 读 |
| 9 | `refresh_changed` | `() -> None` | 写 |
| 10 | `snapshot` | `(name: str) -> Path` | 快照 |
| 11 | `restore` | `(archive: str \| Path) -> int` | 快照 |
| — | `reload` | `() -> None` | 实现方公开（非契约方法）|

### 关键契约（改前必读）

**`put`** — 写一条，返回 memory 生成的 uuid。
- `metadata`：字段→值，**过滤检索用**（值怎么序列化由调用方决定）
- `payload`：调用方自己的结构化数据，**原样存取，检索不碰、不解析**；
  二进制（截图）由调用方自己转 base64 放进来
- `text`：语义检索用的渲染文本；空串 = 不参与语义检索（仍能被 `filter()` 命中）
- **前置**：`text` 非空时会调注入的 `EmbeddingProviderPort`，**失败原样抛出**
  （不静默降级成"这条没有向量"）
- **后置**：uuid 全局唯一、不带语义，**调用方不能从 metadata 反推**

**`get_many`** — **后置**：跳过不存在的 uuid（不报错、结果比传入短），
**返回顺序不保证跟传入一致**。

**`filter`** — 只支持 **AND-of-equalities**（各条件候选集取交集），
**不支持 OR、不支持大小比较**。空 dict = 不过滤，返回全部 uuid。
> 数值型大小比较由调用方自己先用等值条件（如 `episode_id`）把候选筛小，
> 再对候选做数值比较——这是调用方的领域知识，不是接口该内置的。

**`search`** — `filter` 圈候选 + 截断的便捷封装。**前置**：`query` 非空、
`limit > 0`。**后置**：返回长度 ≤ limit，候选为空返回空列表（不报错）。
只在有 `text` 的记录里找。
**内部排序（分词/BM25/RRF/reranker）对外完全不透明**——调用方不能干预。

**`rank`** — 对**给定候选集**做混合检索排序，返回 `[(uuid, 分数)]` 降序。
`search()` 的底层原语；调用方按自己的领域规则先筛候选（场景匹配、质量粗筛）
再进来，**过滤逻辑不归这一层**。没有 `text` 的候选直接跳过。

**`delete_many`** — 摘出索引 + unlink 记录文件，**"让记录消失"的唯一路径**（0916 起）。
此前叫 `archive_many`（搬进 `dest_dir` 留档、**不 unlink**）——那套归档已整个删掉，
换成快照：要留档就在淘汰之前先 `snapshot()`，淘汰本身该是干脆的。
当前唯一调用方是 `MemoryTool._trim_summaries()`（摘要超容量按质量淘汰最差的一条）。
不存在的 uuid 跳过、不报错；返回实际删掉的条数。

**`count`** — 当前在索引里的条数（不含已删的）。

**`snapshot`** — 把**整个记忆根**（不是本实例那个 kind）打成一个 zip，返回路径。
`name` 只是文件名（不含路径分隔符），zip 落哪由实现方决定
（`LocalMemoryStore` 落在 `<根>/snapshots/<name>.zip`）。同名覆盖。
**先在临时目录打好再挪进目标位置**（zip 落点在根里面，边写边长会被卷进去自我引用），
且打进 zip 时排除 `snapshots/` 自身。

**`restore`** — 用一个 zip **还原**记忆根，返回解出的文件数。
**以 zip 为准**（0916 定稿）：zip 里有的记录文件按 zip 写（同名直接盖），
**zip 里没有的记录文件从库里删掉**——"恢复到某个存档"就是这个意思，
没有"只加不减"的另一半入口。`snapshots/` 子目录不受影响（存档 zip 自己不被
还原动掉）。只认 `<kind>/<file>` 两层路径（zip 可能来自别处，防目录穿越）。
恢复后**内存态要重读**（`LocalMemoryStore` 内部 `_load_or_rebuild`；另外三族由
`MemoryTool.restore_memory()` 挨个 `reload()`）。

> **签名不对称是故意的**：`snapshot` 收**名字**（放哪由 memory 决定，harness 不该知道），
> `restore` 收**路径**（必须能接受任意来源的 zip，那正是"覆盖读取"的价值）。

**`reload`** — 把内存态（倒排索引 / uuid 集合 / mtime / 向量缓存）从盘上重读一遍。
**不是 Port 契约方法**，是实现方公开的辅助口；唯一调用方是
`MemoryTool.restore_memory()`（恢复是整根覆盖，而每个实例只刷新自己那一族）。

**`refresh_changed`** — md 类记录文件 mtime 变了就重读整条：正文重算向量、
frontmatter 里的 metadata 重建倒排——保留"运营改 `.md` 不重启进程就生效"。
**正文与 metadata 都要刷新**，否则改了过滤字段（如 `source`）`filter()` 查不到新值。
json 类运行期写穿产物，实现方做成 no-op。

---

## 三、两个注入协议（memory 的"依赖的另一侧"）

这两个**不是 memory 的对外能力**，而是 memory **要求调用方提供**的。按铁律 3
收裸字段、按 P2 第二类（内部协议）与实现同住包内。

### `EmbeddingProviderPort`（`memory/embedding_provider.py`）

```python
@runtime_checkable
class EmbeddingProviderPort(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

- **前置**：`texts` 非空
- **后置**：返回向量与 `texts` 等长、顺序一致；维度相同；不保证单位向量
- **失败**：底层模型不可用时**抛异常**，不返回空列表或全零向量

### `RerankerProviderPort`（`memory/reranker_provider.py`）

```python
@runtime_checkable
class RerankerProviderPort(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[float]: ...
```

- **前置**：`query` 非空、`documents` 非空
- **后置**：返回分数与 `documents` 等长、顺序一致，**未排序**
- **失败**：抛异常，不返回全零分数

> **P5 备用判据**：若将来 world / brain 也需要 embedding 能力，**不要**把这两个
> 协议提到共用层；按「同形不同约」各自声明一份 + 靠鸭子类型桥接。

---

## 四、`LocalMemoryStore`（默认实现，`memory/store.py`）

```python
class LocalMemoryStore:                      # 注意：不是 Protocol 子类，是结构化满足
    def __init__(
        self,
        embedder: EmbeddingProviderPort,    # 依赖注入，不自己 new
        reranker: RerankerProviderPort,
        kind: str,                      # = memory/ 下一个子文件夹
        root: str | pathlib.Path | None = None,
    ) -> None:
        ...
```

**比 Port 多一个成员**：`kind` 只读属性（`@property def kind(self) -> str`）。
这是实现绑定 kind 的自然产物，不是 Port 的一部分——**mock 不必实现它**。

**合法 kind**（模块级 `_KINDS` fset）：

| kind | 记录格式 |
|---|---|
| `step_memory` | `<uuid>.json` |
| `object_memory` | `<uuid>.json` |
| `episode_memory` | `<uuid>.md`（frontmatter + 正文） |
| `knowledge_memory` | `<uuid>.md` |

**落盘布局**（每 kind 一实例一文件夹）：

```
memory/<kind>/
├── <uuid>.json / <uuid>.md   # 真相永远是记录文件
├── index.json                # 倒排索引（派生、写穿、可自愈重建）
└── vectors.jsonl             # 向量缓存 sidecar（有 text 的文件夹才有意义）
```

**性能特征**（写代码时要知道的）：
- 索引落盘换来的收益 → **`filter` 查询零扫描**（直接走 `index.json`）
- 启动**不读记录文件**（对账通过时），记录按 uuid **惰性读取**
- 只有语义检索召回候选时才读文件取 `text`
- 构造时读 `index.json` 并对账，不一致就**全量扫描重建**（自愈，不需要 WAL）
- `assert kind in _KINDS` —— kind 传错在构造期就炸

---

## 五、`memory/__init__.py` 统一出口（6 个名字，0916 收窄）

消费方一律写 `from pokemon_agent.memory import X`，**不深到子目录模块文件**。
命名与 `trace/` 同形：**协议带 `Port` 后缀，本包自带的实现带 `Local` 前缀**。

```python
__all__ = [
    # —— 协议（3）——
    "EmbeddingProviderPort",
    "MemoryStorePort",
    "RerankerProviderPort",
    # —— 实现（3）——
    "LocalRerankerProvider",
    "LocalEmbeddingProvider",
    "LocalMemoryStore",
]
```

**0916 收窄掉五个检索纯函数与 `SNAPSHOTS_DIRNAME`**：`tokenize` / `bm25_rank` /
`embedding_rank` / `reciprocal_rank_fusion` / `hybrid_retrieve` 全仓零仓外消费方
（`LocalMemoryStore.search` / `rank` 已覆盖全部需求），要排序就调 Port 的
`search` / `rank`；`SNAPSHOTS_DIRNAME`（值 `"snapshots"`）是实现细节，
"快照放哪"本就不该被消费方依赖。它们仍在 `retrieval.py` / `store.py` 里，
单测就地深 import。

实测 `dir()` 确认：除这 6 个公开名外只有 7 个子模块名（`ports`/`store`/`retrieval`/
`fastembed_text`/`fastembed_reranker`/`embedding_provider`/`reranker_provider`），
**没有额外公开名泄漏**。

逐名字的用途说明与"不在这里的东西"见 [`API.md`](./API.md) 第一节。

---

## 六、检索纯函数（`memory/retrieval.py`）——不是 Port，也不在包出口上

**不碰库也不碰模型**（向量与精排分数由调用方算好传进来），所以能脱离 provider
单测。只认字符串，不认任何记忆类型。**0916 起不在 `memory/__init__.py` 的
`__all__` 里**（全仓零仓外消费方）——要对它们做单测就地
`from pokemon_agent.memory.retrieval import …`。

| 函数 | 签名 | 说明 |
|---|---|---|
| `tokenize` | `(text: str) -> list[str]` | 中文**字符 bigram**，供 BM25 |
| `bm25_rank` | `(query, documents: list[str]) -> list[int]` | 返回**降序下标**（0-based） |
| `embedding_rank` | `(query, documents, embedder, document_vectors=None) -> list[int]` | 余弦，返回降序下标 |
| `reciprocal_rank_fusion` | `(rankings: list[list[int]], k=RRF_K) -> dict[int, float]` | RRF 融合；**只含至少一路出现过的下标** |
| `hybrid_retrieve` | `(query, documents, embedder, reranker, fuse_top_k=10, document_vectors=None) -> list[tuple[int, float]]` | 完整两阶段 |

`hybrid_retrieve` 返回 `(原始下标, reranker 分数)` 降序、长度
`min(fuse_top_k, len(documents))`：
- 带**原始下标** → 调用方能把结果映回 `documents` 之外的元数据
  （`MemoryTool` 要映回 `EpisodeMemory` 对象本身）
- 带**分数** → 调用方能在其上叠加别的信号（质量分、成败），不用重算

`RRF_K = 60`：Cormack et al. 2009 的经验值，**不需要针对本项目调**。
两路分数必须先归一化才能直接相加（BM25 无上界、余弦在 [-1,1]），
RRF 只看排名不看绝对分，**连归一化都省了**。

---

## 七、一致性与边界核对

| 项 | 状态 |
|---|---|
| `LocalMemoryStore` 是否 `Protocol` 子类 | ❌ 结构化满足（鸭子类型），符合铁律「用 Protocol 而非继承基类」 |
| mock 能否无痛替换 | ✅ 只需 11 个方法结构对上，无显式继承要求 |
| Port 是否收信封 | ✅ 全是 `dict` / `str` / `Sequence[str]` / `Path` 裸字段 |
| 是否泄漏姊妹模块类型 | ✅ 零处——`StepMemory` 等在 `schemas.memory`，Port 不认识 |
| 方法数是否超标 | ⚠️ 11 个 > 6。已按"读写/检索"划界，暂未拆；若要拆，自然断点是 `{put,delete_many,refresh_changed,snapshot,restore}` vs `{get,get_many,filter,search,rank,count}` |
| `__init__` 是否背包网关客户端 | ✅ 不背；fastembed 的 import 在函数内 |
| 独立导入屏障 | ⚠️ `rank_bm25` 在 `retrieval.py` 顶部 → `import pokemon_agent.memory` 需要它（纯 Python 小包，代价可忽略） |

---

## 附：全项目对 memory 的消费点

```
tools/memory_tool.py:42    from pokemon_agent.memory import EmbeddingProviderPort, LocalMemoryStore, RerankerProviderPort
                            ↑ LocalMemoryStore() 在该文件 __init__ 内 new 四次（四个 kind 各一实例）
tools/memory_tool.py:173   from pokemon_agent.memory import LocalRerankerProvider, LocalEmbeddingProvider
                            ↑ 在 MemoryTool.build() 函数体内 —— 装配点唯一入口（0913 深夜十二）
experiment/real_check/check_memory_roundtrip.py  实验脚本，走 MemoryTool.build()
build.py                   ✅ 对 memory **零 import**（改走 MemoryTool.build()）
harness/**, schemas/**     ✅ 零处引用 memory 包（引用的是 schemas.memory 的形状）
```

### 五个接线工厂（同形，都在 tool 层）

| 工厂 | 造什么 | 住哪 |
|---|---|---|
| `BrainTool.build(...)` | brain 的 provider（**按需**，未传为 None）+ `Brain` | `tools/brain_tool.py` |
| `build_vision_provider(model=…)` | world 的感知 provider | `tools/vision_factory.py` |
| **`MemoryTool.build(memory_root=…, max_summaries=…)`** | **memory 的两个检索 provider + `MemoryTool`** | **`tools/memory_tool.py`** |
| `GameTools.build(rom, …)` | `PyBoyWorld` + 感知 provider | `tools/game_tools.py` |
| `TraceTool.build(run_id=…, trace_root=…)` | `LocalTrace` | `tools/trace/__init__.py` |

`build.py` 只递型号名 / 路径这类裸字段，一个工厂都不越过。
