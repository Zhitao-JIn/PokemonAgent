"""检索知识按篇传入，渲染不截断、不改变检索。"""

from pydantic import BaseModel, Field


class KnowledgeParams(BaseModel):
    entries: list[str] = Field(default_factory=list)
