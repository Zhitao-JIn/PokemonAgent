"""将版本内的冻结路径翻译为生产恢复器可读的路径。"""

import json
from pathlib import Path

from evals.agent_short_goal_run.dataset import EvalSample
from evals.agent_short_goal_run.dataset.loader import DATASET_DIR
from evals.dataset.io import contained_file


def prepare_archive(sample: EvalSample, directory: Path) -> Path:
    """生成工作目录中的恢复清单；冻结数据不写回，缺失引用抛 DatasetError。"""
    version = DATASET_DIR / sample.dataset_version
    source = contained_file(version, f"archives/{sample.start.archive}/manifest.json")
    manifest = json.loads(source.read_text(encoding="utf-8"))
    manifest["memory_archive"] = str(contained_file(version, manifest["memory_archive"]).resolve())
    manifest["world_file"] = str(contained_file(source.parent, manifest["world_file"]).resolve())
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
