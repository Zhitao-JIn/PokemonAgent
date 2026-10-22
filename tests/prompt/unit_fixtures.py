"""Temporary example units for gateway tests; fixtures never install a real task."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class ExampleParams(BaseModel):
    """The task-level contract shared by both example versions and fragments."""

    value: str


def file_hash(directory: Path) -> str:
    return hashlib.sha256(
        (directory / "assemble.py").read_bytes().replace(b"\r\n", b"\n")
        + (directory / "prompt.md").read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()


def make_unit(
    root: Path,
    name: str = "example",
    *,
    kind: Literal["task", "fragment"] = "task",
    version: str = "v1",
    text: str = "Hello {value}.\n",
    body: str | None = None,
    newline: bytes = b"\n",
) -> Path:
    """Create params.py, one version, and its independently computed metadata."""
    task_directory = root / "tasks"
    if kind == "fragment":
        task_directory /= "fragments"
    directory = task_directory / name / version
    directory.mkdir(parents=True)
    (directory.parent / "params.py").write_bytes(
        b"from prompt.unit_fixtures import ExampleParams\n".replace(b"\n", newline)
    )
    source = (
        "from collections.abc import Callable\n"
        "from pathlib import Path\n"
        "from pydantic import BaseModel\n"
        "from .params import ExampleParams\n\n"
        "def assemble(params: ExampleParams, "
        "compose: Callable[[str, BaseModel], str]) -> str:\n"
    )
    if body is None:
        body = (
            'text = Path(__file__).with_name("prompt.md").read_text(encoding="utf-8")\n'
            "return text.format(value=params.value)"
        )
    source += "\n".join("    " + line for line in body.splitlines()) + "\n"
    (directory / "assemble.py").write_bytes(source.encode().replace(b"\n", newline))
    (directory / "prompt.md").write_bytes(text.encode().replace(b"\n", newline))
    metadata = {
        "task": name,
        "version": version,
        "kind": kind,
        "params": "ExampleParams",
        "reason": "CP1 example",
        "hash": file_hash(directory),
    }
    (directory / "meta.json").write_bytes((json.dumps(metadata) + "\n").encode())
    return directory


def make_registry(root: Path, **tasks: str) -> Path:
    """Write only the active-version mapping; all unit sources live beside the registry."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "registry.json"
    data = {"tasks": {name: {"active": version} for name, version in tasks.items()}}
    path.write_bytes((json.dumps(data) + "\n").encode())
    return path
