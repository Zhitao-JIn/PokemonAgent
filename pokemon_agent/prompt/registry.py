"""Load an entire registry, validate all versions and contracts, and resolve composition edges."""

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import PromptRegistryError
from .interfaces.assembly import Assemble, History
from .loading import load_source, task_package
from .meta import PromptMeta, version_hash
from .references import composition_names


class ActiveVersion(BaseModel):
    """The registry is the sole selector of a unit's active version."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    active: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class RegistryData(BaseModel):
    """Pure data mapping unit names to active versions."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    tasks: dict[str, ActiveVersion]


@dataclass(frozen=True)
class PromptUnit:
    """A fully validated version and its typed rendering dependencies."""

    meta: PromptMeta
    params_type: type[BaseModel]
    assemble: Assemble
    directory: Path
    fragments: frozenset[str]
    history: History | None = None
    goals: History | None = None


def load_unit(root: Path, task: str, version: str) -> PromptUnit:
    """Load one task or fragment; reject absent or mismatched source and contract data."""
    if not task.isidentifier():
        raise PromptRegistryError(f"Invalid unit name: {task}")
    packaged = Path(__file__).resolve().parent
    candidates = list(
        dict.fromkeys(
            directory
            for base in (packaged, root)
            for directory in (base / "tasks" / task, base / "tasks" / "fragments" / task)
        )
    )
    directories = [path for path in candidates if path.is_dir()]
    if len(directories) != 1:
        raise PromptRegistryError(f"Unit directory missing or ambiguous: {task}")
    task_directory = directories[0]
    directory = task_directory / version
    if not directory.is_dir():
        raise PromptRegistryError(f"Version directory missing: {directory}")
    meta = PromptMeta.model_validate_json((directory / "meta.json").read_bytes())
    if meta.task != task or meta.version != version:
        raise PromptRegistryError(f"Metadata identity mismatch: {directory}")
    if meta.hash != version_hash(directory):
        raise PromptRegistryError(f"Version hash mismatch: {directory}")
    package = task_package(task_directory)
    contracts = load_source(f"{package}.params", task_directory / "params.py")
    params_type = getattr(contracts, meta.params, None)
    if not isinstance(params_type, type) or not issubclass(params_type, BaseModel):
        raise PromptRegistryError(f"Contract class missing: {task}.{meta.params}")
    fragments = composition_names(directory / "assemble.py")
    module = load_source(f"{package}._assemble_{meta.hash}", directory / "assemble.py")
    assemble = getattr(module, "assemble", None)
    if not callable(assemble) or inspect.iscoroutinefunction(assemble):
        raise PromptRegistryError(f"Synchronous assemble function missing: {directory}")
    arguments = list(inspect.signature(assemble).parameters.values())
    if [argument.name for argument in arguments] != ["params", "compose"] or any(
        argument.kind not in (argument.POSITIONAL_ONLY, argument.POSITIONAL_OR_KEYWORD)
        for argument in arguments
    ):
        raise PromptRegistryError(f"Expected assemble(params, compose): {directory}")
    materials: dict[str, History | None] = {}
    for name in ("history", "goals"):
        renderer = getattr(module, name, None)
        if renderer is not None and (
            not callable(renderer)
            or inspect.iscoroutinefunction(renderer)
            or list(inspect.signature(renderer).parameters) != ["params", "compose"]
        ):
            raise PromptRegistryError(f"Expected {name}(params, compose): {directory}")
        materials[name] = cast(History | None, renderer)
    return PromptUnit(
        meta,
        params_type,
        cast(Assemble, assemble),
        directory,
        fragments,
        materials["history"],
        materials["goals"],
    )


def validate_composition(units: dict[str, PromptUnit]) -> None:
    """Reject absent fragments, task composition, and recursive fragment cycles at startup."""
    for task, unit in units.items():
        for fragment in unit.fragments:
            if fragment not in units:
                raise PromptRegistryError(f"{task}: fragment not registered: {fragment}")
            if units[fragment].meta.kind != "fragment":
                raise PromptRegistryError(f"{task}: compose requires kind=fragment: {fragment}")
    complete: set[str] = set()

    def visit(name: str, active: frozenset[str]) -> None:
        if name in active:
            raise PromptRegistryError(f"Composition cycle: {name}")
        if name in complete:
            return
        for fragment in units[name].fragments:
            visit(fragment, active | {name})
        complete.add(name)

    for task in units:
        visit(task, frozenset())


def load_registry(path: Path) -> dict[str, PromptUnit]:
    """Return only a completely validated registry; external failures become registry errors."""
    try:
        data = RegistryData.model_validate_json(path.read_bytes())
        units = {
            task: load_unit(path.parent, task, version.active)
            for task, version in data.tasks.items()
        }
        validate_composition(units)
    except PromptRegistryError:
        raise
    except (OSError, ValidationError, ImportError, SyntaxError, TypeError, ValueError) as error:
        raise PromptRegistryError(f"Cannot load registry {path}: {error}") from error
    return units


def active_versions(registry_path: Path | None) -> dict[str, tuple[str, str]]:
    """Return sorted active version and validated source hash for every registered unit."""
    path = registry_path if registry_path is not None else Path(__file__).with_name("registry.json")
    units = load_registry(path.resolve())
    return {name: (unit.meta.version, unit.meta.hash) for name, unit in sorted(units.items())}
