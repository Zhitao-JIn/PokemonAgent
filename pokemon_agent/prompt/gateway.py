"""The sole rendering gateway for task versions and their registered fragments."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .meta import version_hash
from .registry import load_registry


class RenderedPrompt(BaseModel):
    """Rendered text plus the exact task, active version, and validated source digest."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    text: str
    task: str
    version: str
    hash: str


class PromptGateway:
    """Load once and render only registered tasks; initialization validates every unit."""

    def __init__(self, registry_path: Path | None) -> None:
        """None 使用随包注册表；配置不完整或版本不匹配时抛 PromptRegistryError。"""
        path = (
            registry_path
            if registry_path is not None
            else Path(__file__).with_name("registry.json")
        )
        self._units = load_registry(path.resolve())

    def render(self, task: str, params: BaseModel) -> RenderedPrompt:
        """Require a registered task and its exact params type; return text and valid metadata."""
        assert task in self._units, f"Task not registered: {task}"
        unit = self._units[task]
        assert unit.meta.kind == "task", f"render requires kind=task: {task}"
        text = self._assemble(task, params)
        rendered = RenderedPrompt(
            text=text, task=task, version=unit.meta.version, hash=unit.meta.hash
        )
        assert rendered.text, "Rendered prompt must be nonempty"
        assert rendered.hash == version_hash(unit.directory), "Version changed after loading"
        return rendered

    def render_history(
        self, task: str, params: BaseModel, *, part: Literal["history", "goals"] = "history"
    ) -> list[str]:
        """以同一活动版本产生 BrainPort 的逐条素材，不改变模型 prompt。"""
        assert task in self._units, f"Task not registered: {task}"
        unit = self._units[task]
        assert unit.meta.kind == "task", f"history requires kind=task: {task}"
        assert type(params) is unit.params_type, f"Wrong params type for {task}"
        assert part in ("history", "goals"), f"Unknown material part: {part}"
        renderer = unit.history if part == "history" else unit.goals
        assert renderer is not None, f"Material assembler missing: {task}.{part}"
        records = renderer(params, self._compose)
        assert isinstance(records, list) and all(isinstance(record, str) for record in records)
        assert unit.meta.hash == version_hash(unit.directory), f"Version changed: {task}"
        return records

    def _compose(self, name: str, params: BaseModel) -> str:
        """Require a registered fragment and matching params; return its rendered text."""
        assert name in self._units, f"Fragment not registered: {name}"
        assert self._units[name].meta.kind == "fragment", f"compose requires kind=fragment: {name}"
        return self._assemble(name, params)

    def _assemble(self, name: str, params: BaseModel) -> str:
        """Require the exact contract type; verify nonempty output and unchanged source hash."""
        unit = self._units[name]
        assert type(params) is unit.params_type, f"Wrong params type for {name}"
        text = unit.assemble(params, self._compose)
        assert isinstance(text, str) and text, f"Empty or non-string output: {name}"
        assert unit.meta.hash == version_hash(unit.directory), f"Version changed: {name}"
        return text
