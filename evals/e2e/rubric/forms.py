"""rubric ① 拆解质量、② 卡住后换策略（human grader）：生成人工打分表，读回人打的分。

打分表 `rubric_forms.md` 给人看；分数写进同目录的 `rubric_scores.jsonl`，一行
`{"sample_id", "item_id", "ref", "score"}`（`ref` 是被打分那条账的 uuid），`report` 重算时读回。
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.e2e.checks import RunStream
from evals.e2e.schemas import EvalSample, Rubric, RubricScore
from pokemon_agent.schemas.harness import TraceKind
from pokemon_agent.tools.trace.content import DecomposeVerdictContent, TaskEndContent

DECOMPOSE = "decompose_quality"
STRATEGY = "strategy_switch"
SCORES_FILE = "rubric_scores.jsonl"


def form_section(stream: RunStream, sample: EvalSample, rubric: Rubric) -> str:
    """一条样本的人工打分段落：每条拆解一问，每个停摆收尾的 task 一问。"""
    episodes = stream.episodes_for(sample.sample_id)
    lines = [
        f"## {sample.sample_id}",
        "",
        f"目标：{sample.goal}",
        f"可行 behavior：{sample.behavior}",
        "",
    ]
    anchors = {item.item_id: item for item in rubric.items}
    if DECOMPOSE in sample.rubric:
        for e in stream.in_episodes(episodes, TraceKind.DECOMPOSE_VERDICT):
            assert isinstance(e.content, DecomposeVerdictContent)
            lines.append(f"### ① 拆解质量 — ref `{e.uuid}`（{e.meta.episode_id}）")
            lines += [
                f"- {t.task_id}：{t.goal} ｜ 判据：{t.success_criteria}" for t in e.content.tasks
            ]
            lines += _anchor_lines(anchors[DECOMPOSE].levels) + ["- 分数：", ""]
    if STRATEGY in sample.rubric:
        for e in stream.in_episodes(episodes, TraceKind.TASK_END):
            assert isinstance(e.content, TaskEndContent)
            if e.content.termination != "stalled":
                continue
            lines.append(f"### ② 卡住后换策略 — ref `{e.uuid}`（{e.meta.task_id}）")
            lines += _anchor_lines(anchors[STRATEGY].levels) + ["- 分数：", ""]
    return "\n".join(lines)


def _anchor_lines(levels: list) -> list[str]:
    """把档位锚点列成几行。"""
    return [f"  - {level.score}：{level.anchor}" for level in levels]


def human_scores(report_dir: Path, sample: EvalSample) -> list[RubricScore]:
    """读回人打的分：同一条目多条账取平均；没打的条目给 `score=None`。"""
    by_item: dict[str, list[int]] = {}
    path = report_dir / SCORES_FILE
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("sample_id") == sample.sample_id and row.get("score") is not None:
                by_item.setdefault(row["item_id"], []).append(int(row["score"]))
    out: list[RubricScore] = []
    for item_id in (DECOMPOSE, STRATEGY):
        if item_id not in sample.rubric:
            continue
        scores = by_item.get(item_id, [])
        mean = round(sum(scores) / len(scores)) if scores else None
        out.append(
            RubricScore(item_id=item_id, grader="human", score=mean, detail={"rated": len(scores)})
        )
    return out


__all__ = ["DECOMPOSE", "SCORES_FILE", "STRATEGY", "form_section", "human_scores"]
