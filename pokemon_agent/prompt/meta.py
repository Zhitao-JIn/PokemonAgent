"""Version metadata and SHA256 over sorted, LF-normalized source file bytes."""

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PromptMeta(BaseModel):
    """One version's identity, contract class name, purpose, kind, and content digest."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task: str = Field(min_length=1)
    version: str = Field(min_length=1)
    kind: Literal["task", "fragment"]
    params: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    reason: str = Field(min_length=1)
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def version_hash(directory: Path) -> str:
    """Hash assemble.py then prompt.md bytes with CRLF normalized to LF; omit metadata."""
    digest = hashlib.sha256()
    for name in sorted(("prompt.md", "assemble.py")):
        digest.update((directory / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()
