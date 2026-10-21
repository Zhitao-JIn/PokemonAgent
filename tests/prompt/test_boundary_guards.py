"""The real repository passes; each boundary rule rejects a minimal violating repository."""

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
