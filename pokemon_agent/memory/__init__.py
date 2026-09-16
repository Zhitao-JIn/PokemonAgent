"""记忆层：对外契约 + 统一记录存储 + 混合检索。

- `ports.py`：本层的对外契约（`MemoryStorePort`）——写入 / 等值过滤检索 /
  语义检索 / 删除 / 快照。**与实现同住一包**：拷走 `memory/` 就同时拿到契约、
  实现与算法，不需要回头翻本项目的 `interfaces/`（0910 拍板，见 ROADMAP 第 24 条）。
- `store.py`：统一记录存储（`LocalMemoryStore`）——一条记录一个 `<uuid>.json/.md`
  文件 + 每文件夹倒排索引（`index.json`，派生物、写穿、可自愈重建）+ 向量
  sidecar。四类记忆（step_memory / object_memory / episode_memory /
  knowledge_memory）**共用一个 `memory/` 根、各占一个子文件夹、各一个实例**；
  全项目不按 run 分层，`run_id` 是 metadata 里的普通过滤字段（0910 重构）。
  **快照也住这里**（0916）：`snapshot(name)` 把整个根打成
  `memory/snapshots/<name>.zip`、`restore(zip)` 以 zip 为准还原回来——zip 由本层
  管理，调用方只给名字。
- `retrieval.py`：语义检索用的混合检索纯函数（BM25 bigram + embedding
  余弦 + RRF + reranker 精排），只认字符串，不认任何记忆类型。**这五个函数不在
  本包的出口上**——它们只被 `store.py` 的 `rank()` 串联调用，而"要不要把它们逐个
  暴露出去"对消费方没有意义（要排序就调 `MemoryStorePort.search` / `rank`）。
- `embedding_provider.py` / `reranker_provider.py`：本层依赖的两个模型协议
  （`EmbeddingProviderPort` / `RerankerProviderPort`），2026-09-13 从
  `providers/interface/` 搬来——它们只被本层的检索链路消费。协议挨着实现，
  跟 `MemoryStorePort` 同住一包；**拷走 `memory/` 就拿到完整可复用的一块**。
- `fastembed_text.py` / `fastembed_reranker.py`：上面两个协议的**本地实现**
  （`LocalEmbeddingProvider` / `LocalRerankerProvider`），同批从顶层 `providers/` 搬来
  ——那个包 0913 整个解散（`openai_compatible.py` 去了 `brain/providers.py`）。
  **协议 + 实现都在本包**，拷走即得，不再需要外挂一个 `providers/`。

## 命名规矩（0916 起，与 `trace/` 同形）

- **协议一律带 `Port` 后缀**：`MemoryStorePort` / `EmbeddingProviderPort` /
  `RerankerProviderPort`（对应 `trace/` 的 `TracePort`）。
- **本包自带的实现一律带 `Local` 前缀**：`LocalMemoryStore` /
  `LocalEmbeddingProvider` / `LocalRerankerProvider`（对应 `LocalTrace`）。
  将来换远程实现就平行地叫 `HttpEmbeddingProvider` / `OpenAIXxx`，不必把技术名
  挤进同一个名字里——"角色 + 本地性"由类名说，"具体后端是哪家"由模块名说
  （`fastembed_text.py` / `fastembed_reranker.py`）。

**`MemoryStorePort` 完全不透明**：`put`/`get_many`/`filter`/`delete_many`/`snapshot`
这一整套协议只认 `metadata: dict[str, str]` + `payload: dict` 两个裸字段，
`store.py` 的实现同理，从来不 import、不需要知道 `StepMemory`/
`EpisodeMemory`/`ObjectFactEvent` 这三个类具体长什么样。按"数据形状只有在
某个模块的 Port/实现真的需要构造或消费它的具体样子时，才归那个模块自己"
这条边界，这三个类因此**不在**这个包里——它们是 `schemas.memory` 的东西
（本项目自己的跨层契约层），"发生了什么、影响了谁"的语义判定/组装分别在
`brain.brain.py::reflect()`、`harness/object_interactions.py`、
tool 层（`tools/memory_tool.py`）完成，见 `pokemon_agent/schemas/memory/
__init__.py` 的说明。

object 的交互判定在 harness（`harness/object_interactions.py`）。

本文件是统一出口：**对外契约 + 实现类 + 两个注入协议**都从这里 re-export，
消费方写 `from pokemon_agent.memory import X`，不深到子目录的模块文件。
`retrieval.py` 的纯函数与 `SNAPSHOTS_DIRNAME` 这类实现细节**不在这里**——
要对它们做单测就地 `from pokemon_agent.memory.retrieval import …`。
"""

__all__ = [
    "EmbeddingProviderPort",
    "LocalEmbeddingProvider",
    "LocalMemoryStore",
    "LocalRerankerProvider",
    "MemoryStorePort",
    "RerankerProviderPort",
]
from .embedding_provider import EmbeddingProviderPort
from .fastembed_reranker import LocalRerankerProvider
from .fastembed_text import LocalEmbeddingProvider
from .ports import MemoryStorePort
from .reranker_provider import RerankerProviderPort
from .store import LocalMemoryStore
