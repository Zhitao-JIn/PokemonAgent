"""知识库记录的写入形态：**一条和坐标无关的世界知识**。

`knowledge_memory/` 这个家族原先只有**离线灌入**的先验（手写的 `.md`，metadata
里只有 `source` / `topic`），run 期间学到的东西**写不进任何地方**——这是
`docs/PLAN_planner_v2.md` §3.6 点名的缺口。本类就是那个写入口要的形状。

**它和 `ObjectFactEvent` 的分界是"坐标"**：object 事件锚在 `(map_id, x, y)` 上，
回答"那一格上有什么"；本类**刻意不带任何坐标**，回答"这个世界的规则是什么"。
把位置绑进知识里，会让"宝可梦中心的护士能治好全队"这种全世界都成立的事
只在那一格被检索到。

**和 `EpisodeMemory` 的分界是"归属"**：摘要属于那一局（`episode_id` 是它的
身份），知识属于世界（`run_id`/`episode_id` 只是**来源**，不是它的身份——
它以后会在别的 run 里被检索到）。

落盘形态与这个家族的既有记录**逐字一致**：metadata 放过滤字段、payload 空、
正文是 `text`（`LocalMemoryStore.put(metadata, {}, text=text)`）——
手工写的先验与 run 产出的知识因此长同一样子，读口（`query_knowledge`）
不需要区分它们。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeRecord(BaseModel):
    """一条要落进 `knowledge_memory/` 的世界知识。"""

    topic: str = Field(
        min_length=1,
        description="短标签（snake_case），讲同一件事的条目共用一个——判重按它分组",
    )
    text: str = Field(
        min_length=1,
        description="正文（落库时它就是记录的 text，也是检索打分的对象）",
    )

    source: str = Field(
        min_length=1,
        description="这条知识从哪来。run 产出的记成 `{run_id}/{episode_id}`——"
        "手工先验记的是文件名，两种来源在 metadata 里必须分得开",
    )
    run_id: str = Field(description="产出它的 run（追溯用，不是它的身份）")
    episode_id: str = Field(description="产出它的那一局（追溯用，不是它的身份）")

    def render(self) -> str:
        """渲染成进 prompt 的样子——**就是正文本身**。

        知识库没有"来源章"要摆在第一行（那是 `EpisodeMemory` 的规矩：成败是
        机械判定，必须压过 LLM 的叙述）。一条知识没有"成没成"可言，
        正文就是它的全部；`source` 只进 metadata 供人追溯，不进 prompt——
        读者关心"这个世界的规则是什么"，不关心它是哪一局读到的。
        """
        return self.text


__all__ = ["KnowledgeRecord"]
