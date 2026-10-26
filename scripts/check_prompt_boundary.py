"""Check prompt isolation (A), public imports (B), build isolation (C), and retirement (D)."""

from __future__ import annotations

import argparse
import ast
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

PROMPT = "pokemon_agent.prompt"
RETIRED = ".".join(("pokemon_agent", "direct", "prompts"))


@dataclass(frozen=True)
class Violation:
    """One boundary violation with its rule and precise source location."""

    rule: str
    path: str
    line: int
    detail: str


def python_files(root: Path) -> Iterator[Path]:
    """Scan source files, excluding hidden worktrees, environments, generated caches, and the
    gitignored `eval_results` archive (frozen copies of older packages, not live code)."""
    for directory, names, files in os.walk(root):
        names[:] = sorted(
            name
            for name in names
            if not name.startswith(".")
            and name not in {"__pycache__", "node_modules", "venv", "eval_results"}
        )
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(directory) / name


def public_names(root: Path) -> frozenset[str]:
    """Read the literal public export list without importing production modules."""
    path = root / "pokemon_agent/prompt/__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            values = ast.literal_eval(node.value)
            if isinstance(values, (list, tuple)) and all(
                isinstance(value, str) for value in values
            ):
                return frozenset(values)
    raise ValueError(f"{path}: literal __all__ export list required")


def import_edges(tree: ast.AST, relative: Path) -> Iterator[tuple[int, str, str | None]]:
    """Resolve absolute and relative imports into (line, module, imported name)."""
    parts = list(relative.with_suffix("").parts)
    package = parts[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, None
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            for alias in node.names:
                yield node.lineno, module, alias.name


def is_prompt(module: str) -> bool:
    """Match the prompt package and descendants without matching similarly named packages."""
    return module == PROMPT or module.startswith(PROMPT + ".")


def check(root: Path) -> list[Violation]:
    """Return violations from every source import, including imports inside functions."""
    exports = public_names(root)
    violations: list[Violation] = []
    retired_path = Path(*RETIRED.split("."))
    if (root / retired_path).exists():
        violations.append(Violation("D", retired_path.as_posix(), 0, "retired package exists"))
    for path in python_files(root):
        relative = path.relative_to(root)
        inside = relative.is_relative_to(Path("pokemon_agent/prompt"))
        build = relative == Path("pokemon_agent/build.py")
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        for line, module, name in import_edges(tree, relative):
            target = f"{module}.{name}" if name else module
            if target == RETIRED or target.startswith(RETIRED + "."):
                violations.append(Violation("D", relative.as_posix(), line, target))
            touches_prompt = is_prompt(module) or is_prompt(target)
            detail = f"from {module} import {name}" if name else f"import {module}"
            if inside:
                if (module == "pokemon_agent" or module.startswith("pokemon_agent.")) and not (
                    is_prompt(module) or (module == "pokemon_agent" and name == "prompt")
                ):
                    violations.append(Violation("A", relative.as_posix(), line, detail))
            elif touches_prompt and not (module == PROMPT and name in exports):
                violations.append(Violation("B", relative.as_posix(), line, detail))
            if build and touches_prompt:
                violations.append(Violation("C", relative.as_posix(), line, detail))
        for line, text in enumerate(source.splitlines(), start=1):
            normalized = text.replace("\\", "/")
            if RETIRED in normalized or RETIRED.replace(".", "/") in normalized:
                violations.append(
                    Violation("D", relative.as_posix(), line, "retired package reference")
                )
    return violations


def main() -> int:
    """Print locations and return nonzero for any invalid boundary or unparseable source."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        violations = check(args.root.resolve())
    except (OSError, SyntaxError, ValueError) as error:
        print(f"[FAIL] Cannot check prompt boundary: {error}")
        return 1
    for violation in violations:
        print(f"[FAIL] {violation.rule} {violation.path}:{violation.line} {violation.detail}")
    failed = {violation.rule for violation in violations}
    for rule in "ABCD":
        if rule not in failed:
            print(f"[ OK ] {rule}")
    return int(bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
