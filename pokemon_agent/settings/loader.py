"""配置加载：保底 `default.json` 依次叠加覆盖文件，合并后一次性校验。

优先级只有两层：保底 < 覆盖文件（按传入顺序，后者胜）。没有显式参数、没有环境变量
这类第三来源，所以"某个值从哪来"只需看这几份文件。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .errors import ConfigFileError, ConfigValidationError
from .schema import AppConfig, ResolvedConfig

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "default.json"
"""随包分发的保底文件；全填、零缺省。"""


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """递归合并两个 JSON 对象，返回新对象。

    两边都是对象的键递归合并；其余情况（标量、列表、类型不同）整体以 overlay 为准。
    不修改入参。
    """
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_object(path: Path) -> dict[str, Any]:
    """读一份 JSON 文件，要求顶层是对象；读不到或格式不对抛 `ConfigFileError`。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigFileError(f"无法读取配置文件 {path}：{exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigFileError(f"配置文件不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ConfigFileError(f"配置文件顶层必须是对象：{path}")
    return data


def load_config(overlays: str | Path | Sequence[str | Path] | None = None) -> ResolvedConfig:
    """加载生效配置。

    `overlays`：None 只用保底；单个路径或路径序列依次覆盖，后者胜。覆盖文件只写要改的键。
    失败：文件读不到 / 非法 JSON / 顶层非对象 → `ConfigFileError`；
    合并结果未知键、类型错误、跨段约束不成立 → `ConfigValidationError`。
    后置条件：`sha256` 是 `merged_json` 的摘要；`sources[0]` 恒为保底文件。
    """
    # 步骤 1：归一化覆盖文件列表。
    if overlays is None:
        overlay_paths: list[Path] = []
    elif isinstance(overlays, (str, Path)):
        overlay_paths = [Path(overlays)]
    else:
        overlay_paths = [Path(item) for item in overlays]

    # 步骤 2：保底在前、覆盖在后，逐份深度合并。
    sources = [DEFAULT_CONFIG_PATH, *overlay_paths]
    merged: dict[str, Any] = {}
    for path in sources:
        merged = deep_merge(merged, _read_object(path))
    source_names = tuple(str(path) for path in sources)

    # 步骤 3：规范化后按 JSON 模式校验（JSON 模式下数组可直接进 tuple，严格类型不受影响）。
    merged_json = json.dumps(merged, ensure_ascii=False, sort_keys=True, indent=2)
    try:
        config = AppConfig.model_validate_json(merged_json)
    except ValidationError as exc:
        issues = tuple(
            f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigValidationError(issues, source_names) from exc

    # 步骤 4：打包出处与摘要。
    digest = hashlib.sha256(merged_json.encode("utf-8")).hexdigest()
    resolved = ResolvedConfig(
        config=config, sources=source_names, merged_json=merged_json, sha256=digest
    )
    assert resolved.sources[0] == str(DEFAULT_CONFIG_PATH), "default config must come first"
    return resolved
