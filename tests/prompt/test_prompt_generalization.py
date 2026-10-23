"""prompt 泛化 lint：抄了样本短语必须命中，活动注册表对 e2e 样本必须零命中。"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "lint_prompt_generalization.py"
SAMPLES = (
    REPO_ROOT
    / "evals"
    / "agent_short_goal_run"
    / "dataset"
    / "v20261021_merged_583"
    / "samples.jsonl"
)


def run_lint(*arguments: str) -> subprocess.CompletedProcess[str]:
    """在仓库根上跑 lint，参数原样透传。"""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_a_prompt_copying_a_sample_phrase_is_reported_with_its_sample_id(
    tmp_path: Path,
) -> None:
    criteria = "scene 是 battle，或对话框里出现 `WILD ... appeared!`"
    unit = tmp_path / "tasks" / "example" / "v1"
    unit.mkdir(parents=True)
    (unit / "prompt.md").write_text(f"照着判据抄：{criteria}\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"tasks": {"example": {"active": "v1"}}}), encoding="utf-8")
    samples = tmp_path / "samples.jsonl"
    samples.write_text(
        json.dumps(
            {
                "sample_id": "fake_wild_encounter",
                "goal": "在草丛里一直走，直到撞上一只野生宝可梦",
                "success_criteria": criteria,
                "initial_state_hint": {"scene": "field", "overlay": "none"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_lint(
        "--registry",
        str(registry),
        "--samples",
        str(samples),
        "--allow",
        str(tmp_path / "absent-allow.txt"),
    )

    assert result.returncode == 1
    assert "WILD ... appeared!" in result.stdout
    assert "fake_wild_encounter" in result.stdout


def test_the_active_registry_matches_no_e2e_sample_text() -> None:
    result = run_lint("--samples", str(SAMPLES))

    assert result.returncode == 0, result.stdout
    assert "命中 0 处" in result.stdout
