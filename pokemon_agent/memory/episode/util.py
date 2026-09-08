"""纯函数：解析跨局摘要的 md、清洗文件名。**不碰任何存储状态**。

这是它们和 `memory/episode/episode_store.py`（有状态的 `_steps` / `_summaries`
实例）的唯一区别，也是拆成单独文件的理由：纯函数可以脱离"有没有建过档"
单独测试，将来别的存储实现要复用同一套 md 格式时，不需要牵连任何存储状态。
与 `memory/semantic/util.py` 同层对称——每类记忆两个文件：`xxx_store.py` + `util.py`。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pokemon_agent.schemas.datastore import EpisodeMemory


def safe_filename(filename: str) -> str:
    """把 LLM 给的文件名洗成安全的 snake_case。"""
    safe = re.sub(r"[^a-z0-9_-]+", "_", filename.lower()).strip("_-")
    return safe or "episode_memory"


def parse_md(path: Path) -> EpisodeMemory | None:
    """解析一个 md 文件：`---` 之间的 JSON frontmatter + 之后的正文。

    返回重建的 `EpisodeMemory`；没有 frontmatter（旧格式纯正文）返回 `None`——
    调用方（`FileEpisodeMemoryStore._load_all`）据此跳过旧存档不崩。
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    try:
        meta = json.loads(text[4:end])
        body = text[end + 5 :]
    except json.JSONDecodeError:
        return None
    return EpisodeMemory(**meta, markdown=body.strip())
