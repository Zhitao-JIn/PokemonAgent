"""`LearnedKnowledge` / `KnowledgeItem`：一局跑完后**从这一局里读出来的世界知识**。

**它和 `EpisodeSummary` 是两件事，所以是两个模型**：

| | 回答的问题 | 生命周期 |
|---|---|---|
| `EpisodeSummary` | **这一局**打得怎么样 | 属于那一局——绑定一个 `episode_id` |
| `LearnedKnowledge` | **这个世界**有什么新事实 | 属于世界——哪一局读到的无关，往后每局都该受益 |

混成一个模型的后果不是报错，而是**知识会被迫带上局的身份**：一条"宝可梦中心的
护士能治好全队"本该在往后每一局被检索到，一旦它长成某局的摘要正文，就只能按
`episode_id` 找到，`plan` 读 `knowledge_memory` 时看不见它。

## 为什么 `topic` 和 `content` 两块都要

`topic` 是**给索引用的短标签**（snake_case，如 `pokemon_center_heal`）——它进
metadata，让"同一件事被两局分别学到"能落到同一个桶里判重；`content` 是**给人 / 给
模型读的正文**（一句话或一小段），它进检索文本。让 LLM 自己起 `topic` 而不是让
调用方从正文里切前几个字，是因为"这两条讲的是不是同一件事"只有它判得出来。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeItem(BaseModel):
    """一条**坐标无关**的世界知识——从这一局的画面文字（对话、菜单、战斗提示）
    里**读到**的东西，不是推测出来的。"""

    topic: str = Field(
        min_length=1,
        description="短标签（snake_case），同类知识共用一个——用于判重与索引",
    )
    content: str = Field(
        min_length=1,
        description="这条知识本身，一两句话写清。**必须是画面里读到的东西**，"
        "不许写'下一步该做什么'（那是规划，不是知识）",
    )


class LearnedKnowledge(BaseModel):
    """`extract()` 的产物：这一局新读到的世界知识，可以一条都没有。"""

    items: list[KnowledgeItem] = Field(
        default_factory=list,
        description="新读到的知识。**空列表是合法且常见的**——大多数局只是"
        "在赶路，什么都没读到；宁可空手而归，也不要拿推测凑数",
    )


__all__ = ["KnowledgeItem", "LearnedKnowledge"]
