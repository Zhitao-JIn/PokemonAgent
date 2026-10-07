"""读取冻结文件并限制版本内的文件引用。"""

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .errors import DatasetError

SampleModel = TypeVar("SampleModel", bound=BaseModel)


def version_directory(root: Path, version: str) -> Path:
    """返回存在的单级版本目录；非法版本或目录缺失抛 DatasetError。"""
    if not version or Path(version).name != version or version in {".", ".."}:
        raise DatasetError(f"非法版本：{version!r}")
    path = root / version
    if not path.is_dir():
        raise DatasetError(f"没有数据集版本：{path}")
    return path


def contained_file(directory: Path, relative: str) -> Path:
    """解析版本内相对路径；逃逸、绝对路径或文件缺失抛 DatasetError。"""
    path = directory / relative.replace("\\", "/")
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(directory.resolve()):
        raise DatasetError(f"文件引用不在版本目录内：{relative}")
    if not path.is_file():
        raise DatasetError(f"冻结文件缺失：{path}")
    return path


def read_models(
    path: Path, model: type[SampleModel], *, json_lines: bool = True
) -> list[SampleModel]:
    """读取有类型的冻结记录；文件或格式错误抛 DatasetError，顺序保持不变。"""
    try:
        text = path.read_text(encoding="utf-8")
        rows = text.splitlines() if json_lines else [text]
        return [model.model_validate_json(row) for row in rows if row.strip()]
    except (OSError, ValueError) as exc:
        raise DatasetError(f"无法读取冻结文件 {path}：{exc}") from exc
