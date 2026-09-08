"""Semantic memory boundary：object（按坐标的事件日志）+ knowledge（不挂坐标）。

只留两个文件，与 `memory/episode/` 对称：`semantic_store.py`
（`EventObjectStore` + `KnowledgeStore`）。`knowledge/` 是纯数据目录
（运营维护的 md 分片），不是代码包。两类记忆都跨 episode 持久：object 是
agent 自己探索出来的交互事件，knowledge 是开局就该知道的先验。
object 的交互判定在 harness（`harness/object_interactions.py`）——
这里只做读写与索引，不做语义判定。
"""
