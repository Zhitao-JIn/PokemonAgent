"""结构化知识检索结果。内容和来源必须来自同一次检索。"""

from pydantic import BaseModel


class KnowledgeQueryResult(BaseModel):
    """一次知识库检索返回的内容及其来源。"""

    contents: list[str]
    sources: list[str]
