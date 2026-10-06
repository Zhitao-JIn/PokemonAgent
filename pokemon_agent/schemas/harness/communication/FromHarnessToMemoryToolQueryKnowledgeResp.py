"""`FromHarnessToMemoryToolQueryKnowledgeResp`：harness → `MemoryTool` 的知识检索响应。"""

from __future__ import annotations

from pydantic import BaseModel


class FromHarnessToMemoryToolQueryKnowledgeResp(BaseModel):
    """**记忆库给出的检索结果**：内容及其来源 + 分段耗时（0928 324）。

    对齐模型 provider"返回带 usage"的先例：检索的产出不止命中清单，还有
    这次检索自己花掉的时间——观测数据随返回值出来，不搞旁路通道。
    """

    contents: list[str]
    sources: list[str]
    timings: dict[str, float] = {}
    """分段耗时（段名 → 秒）：`prepare` / `bm25` / `vector` / `rrf` / `rerank`，
    五段之和 ≈ 检索调用时长。空检索（无候选）也可能只有 prepare 一段。
    记账走 `FromHarnessToTraceToolAppendReq.timings` → `read_knowledge` 账的 content。"""
