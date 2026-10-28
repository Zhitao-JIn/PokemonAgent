"""长期探索知识原子的字节正文与主题校验。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from evals.agent_short_goal_run.dataset import load, loader
from evals.dataset.errors import DatasetError

BODY = """## 探索时怎么找线索

- 走到路牌或告示牌的正前方，面向它按 `a`，读出上面的地名；每到一个新地图，先看有没有路牌和门。
- 家里的电视和遇到的每个 NPC 都可以面向它按 `a` 对话，把对话里出现的人名、地名、该去哪里记下来。
- 被人拦住、被叫去某个地方时，对话里说的就是下一步该做什么。
- 在地图边缘继续朝一个方向走，会进入相邻的区域；记住自己是从哪个方向进来的。
- 走不通时先看有没有别的门或出口，再换方向，不要在同一处反复撞墙。"""


def test_explore_and_read_atom_body_is_exact_and_topic_is_registered() -> None:
    root = Path(__file__).resolve().parents[3]
    path = root / "memory" / "knowledge_memory" / "b4e68608cece42e3b2746712ea4b3651.md"
    text = path.read_text(encoding="utf-8")
    frontmatter, body = text.split("\n---\n", maxsplit=1)
    metadata = json.loads(frontmatter.removeprefix("---\n"))

    assert body.removeprefix("\n").rstrip("\n") == BODY
    assert metadata["metadata"]["topic"] == "explore_and_read"
    assert loader._validate_knowledge_topics(["map_connections"]) == []
    assert loader._validate_knowledge_topics(["missing_long_topic"])
    sample = load("v20261028_long")[0]
    assert sample.knowledge_exclude_topics == ["map_connections"]


def test_dataset_check_rejects_unknown_knowledge_topic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = loader.DATASET_DIR / "v20261028_long"
    target = tmp_path / "v20261028_long"
    shutil.copytree(source, target)
    sample_path = target / "samples.jsonl"
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    sample["knowledge_exclude_topics"] = ["missing_long_topic"]
    sample_path.write_text(json.dumps(sample, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(loader, "DATASET_DIR", tmp_path)

    with pytest.raises(DatasetError):
        loader.check("v20261028_long")
