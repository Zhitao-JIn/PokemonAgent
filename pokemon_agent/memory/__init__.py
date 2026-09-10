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

旧的按类拆分的存储实现（`episode/`、`semantic/` 包）已退役：它们的存储职责
全部并入 `store.py`，领域对象的组装（`StepMemory`/`EpisodeMemory`/`ObjectFactEvent`
的解析与渲染）在 tool 层（`tools/memory_tool.py`）完成——"发生了什么、影响了谁"
的语义判定归 tool 层，memory 只机械执行（AGENTS.md 四·分层原则）。

object 的交互判定在 harness（`harness/object_interactions.py`）。

本文件同时是统一出口：契约、存储类与检索纯函数从这里 re-export，
消费方只写 `from pokemon_agent.memory import X`，不深到子目录的模块文件。
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
