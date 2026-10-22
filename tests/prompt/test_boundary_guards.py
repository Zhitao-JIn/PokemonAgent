"""The real repository passes; each boundary rule rejects a minimal violating repository."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_prompt_boundary.py"


def run_guard(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_the_real_repository_obeys_all_three_rules() -> None:
    result = run_guard(ROOT)

    assert result.returncode == 0, result.stdout + result.stderr
    assert all(f"[ OK ] {rule}" in result.stdout for rule in "ABC")


@pytest.mark.parametrize(
    ("rule", "relative", "source"),
    [
        ("A", "pokemon_agent/prompt/bad.py", "from pokemon_agent.world import Facts\n"),
        ("A", "pokemon_agent/prompt/bad.py", "from ..world import Facts\n"),
        ("A", "pokemon_agent/prompt/bad.py", "from .. import world\n"),
        ("B", "consumer.py", "from pokemon_agent.prompt.gateway import PromptGateway\n"),
        ("B", "consumer.py", "from pokemon_agent.prompt import hidden\n"),
        ("B", "consumer.py", "from pokemon_agent.prompt import *\n"),
        ("B", "consumer.py", "from pokemon_agent import prompt\n"),
        ("C", "pokemon_agent/build.py", "from pokemon_agent.prompt import PromptGateway\n"),
        ("C", "pokemon_agent/build.py", "from .prompt import PromptGateway\n"),
    ],
)
def test_each_violation_reports_its_rule_and_source_location(
    tmp_path: Path, rule: str, relative: str, source: str
) -> None:
    directory = tmp_path / "pokemon_agent/prompt"
    directory.mkdir(parents=True)
    (directory / "__init__.py").write_bytes(
        b'__all__ = ["PromptGateway", "RenderedPrompt", "PromptRegistryError"]\n'
    )
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.encode())

    result = run_guard(tmp_path)

    assert result.returncode != 0
    assert f"[FAIL] {rule} {relative}:1" in result.stdout


MIGRATED = frozenset(
    [
        "Chooser",
        "Decomposer",
        "Judger",
        "Planner",
        "RunSummarizer",
        "Summarizer",
        "TaskSummarizer",
        "Verifier",
    ]
)
LEGACY_NAMES = frozenset(
    [
        "decide_action_prompt",
        "decompose_prompt",
        "judge_success_prompt",
        "run_plan_prompt",
        "summarize_prompt",
        "summarize_run_prompt",
        "summarize_task_prompt",
        "verify_prompt",
    ]
)


def migrated_legacy_references(source: str) -> list[int]:
    """能力体内不得出现旧模板调用或局部导入。"""
    failures: list[int] = []
    for node in ast.parse(source).body:
        if not isinstance(node, ast.ClassDef) or node.name not in MIGRATED:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in LEGACY_NAMES:
                failures.append(child.lineno)
            if isinstance(child, ast.ImportFrom) and "prompts" in (child.module or ""):
                failures.append(child.lineno)
    return failures


def test_migrated_capabilities_have_no_legacy_prompt_calls() -> None:
    path = ROOT / "pokemon_agent/direct/brain_tool.py"

    failures = migrated_legacy_references(path.read_text(encoding="utf-8"))

    assert failures == []


@pytest.mark.parametrize(
    "body",
    [
        "verify_prompt.build_prompt(req)",
        "from pokemon_agent.direct.prompts import verify",
    ],
)
def test_migrated_capability_guard_rejects_legacy_calls_and_imports(body: str) -> None:
    source = "class Verifier:\n    def verify(self, req):\n        " + body + "\n"

    failures = migrated_legacy_references(source)

    assert failures == [3]
