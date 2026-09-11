"""记忆层：对外契约 + 统一记录存储 + 混合检索纯函数。

- `ports.py`：本层的对外契约（`MemoryStorePort`）——写入 / 等值过滤检索 /
  语义检索 / 归档。**与实现同住一包**：拷走 `memory/` 就同时拿到契约、实现与
  算法，不需要回头翻本项目的 `interfaces/`（0910 拍板，见 ROADMAP 第 24 条）。
- `store.py`：统一记录存储（`MemoryStore`）——一条记录一个 `<uuid>.json/.md`
  文件 + 每文件夹倒排索引（`index.json`，派生物、写穿、可自愈重建）+ 向量
  sidecar。四类记忆（step_memory / object_memory / episode_memory /
  knowledge_memory）各一个文件夹、各一个实例；全项目不按 run 分层，`run_id`
  是 metadata 里的普通过滤字段（0910 重构，见 `PLAN_memory_trace_layout.md`）。
- `retrieval.py`：语义检索用的混合检索纯函数（BM25 bigram + embedding
  余弦 + RRF + reranker 精排），只认字符串，不认任何记忆类型。

**`MemoryStorePort` 完全不透明**：`put`/`get_many`/`filter`/`archive_many`
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

本文件是统一出口：契约、存储类、检索纯函数都从这里 re-export，消费方写
`from pokemon_agent.memory import X`，不深到子目录的模块文件。
"""

__all__ = [
    "MemoryStore",
    "MemoryStorePort",
    "bm25_rank",
    "embedding_rank",
    "hybrid_retrieve",
    "reciprocal_rank_fusion",
    "tokenize",
]
from .ports import MemoryStorePort
from .retrieval import (
    bm25_rank,
    embedding_rank,
    hybrid_retrieve,
    reciprocal_rank_fusion,
    tokenize,
)
from .store import MemoryStore
