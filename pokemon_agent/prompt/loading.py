"""Load task contracts and version files without turning version directories into packages."""

import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def task_package(directory: Path) -> str:
    """Preserve packaged contract identity; isolate external unit trees by absolute path."""
    own_root = Path(__file__).resolve().parent
    if directory.is_relative_to(own_root):
        suffix = ".".join(directory.relative_to(own_root).parts)
        name = f"{__package__}.{suffix}"
        importlib.import_module(name)
        return name
    name = "_prompt_unit_" + hashlib.sha256(str(directory).encode("utf-8")).hexdigest()
    if name not in sys.modules:
        package = ModuleType(name)
        package.__path__ = [str(directory)]
        package.__package__ = name
        sys.modules[name] = package
    return name


def load_source(name: str, path: Path) -> ModuleType:
    """Load exact source bytes; a contract imported earlier keeps its class identity."""
    if name in sys.modules:
        return sys.modules[name]
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    except BaseException:
        del sys.modules[name]
        raise
    return module
