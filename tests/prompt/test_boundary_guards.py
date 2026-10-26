"""The real repository passes; each boundary rule rejects a minimal violating repository."""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_prompt_boundary import python_files

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


def test_the_real_repository_obeys_all_four_rules() -> None:
    result = run_guard(ROOT)

    assert result.returncode == 0, result.stdout + result.stderr
    assert all(f"[ OK ] {rule}" in result.stdout for rule in "ABCD")


def test_the_scan_ignores_the_gitignored_eval_results_archive(tmp_path: Path) -> None:
    """`eval_results/` 是本地历史快照（.gitignore 第 48 行），不是活代码，规则扫不到它。"""
    archived = tmp_path / "eval_results" / "iter00" / "bad.py"
    archived.parent.mkdir(parents=True)
    archived.write_text(
        "from pokemon_agent.prompt.gateway import PromptGateway\n", encoding="utf-8"
    )
    live = tmp_path / "ok.py"
    live.write_text("VALUE = 1\n", encoding="utf-8")

    assert list(python_files(tmp_path)) == [live]


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


RETIRED = ".".join(("pokemon_agent", "direct", "prompts"))


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        ("consumer.py", f"import {RETIRED}\n"),
        ("consumer.py", f"from {RETIRED} import verify\n"),
        ("pokemon_agent/direct/consumer.py", "from .prompts import verify\n"),
        ("consumer.py", f"path = {RETIRED.replace('.', '/')!r}\n"),
        ("consumer.py", f"# obsolete reader: {RETIRED}\n"),
        (RETIRED.replace(".", "/") + "/__init__.py", ""),
    ],
)
def test_retired_package_guard_rejects_imports_paths_and_directory(
    tmp_path: Path, relative: str, source: str
) -> None:
    directory = tmp_path / "pokemon_agent/prompt"
    directory.mkdir(parents=True)
    (directory / "__init__.py").write_text('__all__ = ["PromptGateway"]\n', encoding="utf-8")
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")

    result = run_guard(tmp_path)

    assert result.returncode != 0
    assert "[FAIL] D " in result.stdout
    location = RETIRED.replace(".", "/") if not source else relative
    assert location in result.stdout
