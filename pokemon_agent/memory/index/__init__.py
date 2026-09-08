"""Index memory boundary：项目无关的记忆检索——写入 / 过滤检索 / 语义检索 / 删除。

只留一个文件：`index_store.py`（`MemoryIndexStore`）。跟 `memory/episode/`、
`memory/semantic/` 不同——那两类各自理解一份具体的记忆形状（单步/摘要、
object/knowledge），这一类刻意不理解：字段叫什么、值是什么、payload 装的是
什么，对这里都不透明，调用方（tool 层）自己决定怎么拼字段、怎么拼检索用的
文本。语义检索内部的排序（分词/BM25/embedding/RRF/reranker）也不透明，
调用方只给一句话，回来的是排好序的 uuid（见 `interfaces/memory/memory_index_port.py`
的接口文档）。
"""
