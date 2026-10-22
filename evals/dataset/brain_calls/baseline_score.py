"""在参考冻结后离线评估旧响应；此模块不参与标签生成。"""

import json
from collections import Counter, defaultdict
from pathlib import Path

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.agent_short_goal_run.scorer import mechanical_scorer
from evals.agent_short_goal_run.scorer.stream import RunStream
from evals.brain_choose.compare import is_legal, matches
from evals.dataset.brain_choose.schemas import ActionMatcher
from evals.paths import REPO_ROOT
from pokemon_agent.brain.interface import Action
from pokemon_agent.direct.trace import parse
from pokemon_agent.schemas.harness import TraceEvent

from .native_versions import pairs


def evaluate_baseline(root: Path, batch: Path) -> dict:
    """只对有独立标签的响应计分，失败计错；未知标签不进分母。"""
    judges = defaultdict(Counter)
    for case, ref in pairs(root, "judge"):
        if ref.achieved is None:
            continue
        path = REPO_ROOT / (case.source.baseline_file or "missing")
        response = json.loads(path.read_text("utf-8")) if path.is_file() else {}
        predicted = response.get("done")
        category = (
            ("TP" if ref.achieved else "FP")
            if predicted is True
            else (("FN" if ref.achieved else "TN") if predicted is False else "error")
        )
        judges[case.layer][category] += 1
    choices = Counter()
    for case, ref in pairs(root, "choose"):
        if ref.evaluation != "action_set":
            continue
        choices["labelled"] += 1
        path = REPO_ROOT / (case.source.baseline_file or "missing")
        response = json.loads(path.read_text("utf-8")) if path.is_file() else {}
        if "action" not in response:
            choices["error"] += 1
            continue
        action = Action.model_validate(response["action"])
        choices["acceptable"] += matches(
            action, [ActionMatcher.model_validate(row) for row in ref.constraints["acceptable"]]
        )
        choices["legal"] += is_legal(action, case.request.space)
    return {
        "judge": {key: dict(value) for key, value in judges.items()},
        "choose": dict(choices),
        "short_goal_mechanical": short_goal_truth(batch),
    }


def short_goal_truth(batch: Path) -> list[dict]:
    """原始场景目标由既有机械规则评估，独立于 harness 的 goal_done。"""
    records = []
    for sample in load_samples():
        directory = batch / "runs" / sample.sample_id / "trace"
        events = [
            TraceEvent.model_validate_json(path.read_text("utf-8"))
            for path in directory.glob("*.json")
        ]
        events.sort(key=lambda event: (event.seq, event.uuid))
        score = mechanical_scorer()(RunStream([parse(event) for event in events]), sample)
        records.append(
            {
                "sample_id": sample.sample_id,
                "outcome": score.outcome,
                "reason": score.reason,
                "evidence": score.evidence,
            }
        )
    return records
