"""每起点独立打包尝试；失败现场保留，正式起点仅在成功后安装。"""

import json
import shutil
from pathlib import Path
from uuid import uuid4

from .capture_services import capture_services, start_process, stop_process
from .capture_state import ControlState, save_state


def pack_sample(directory: Path, state: ControlState, sample_id: str) -> Path:
    """使用新尝试目录；只移动本批次内的未确认旧产物，不覆盖历史。"""
    key = f"pack:{sample_id}"
    attempt = state.attempts.get(key, 0) + 1
    state.attempts[key] = attempt
    state.current_sample = sample_id
    save_state(directory, state)
    attempt_root = directory / "pack_attempts" / f"attempt{attempt}"
    with capture_services(directory / "pack_services" / f"attempt{attempt}" / sample_id) as env:
        process = start_process(
            [
                "-m",
                "evals.agent_short_goal_run.dataset.build.pack",
                "--samples",
                sample_id,
                "--archive-root",
                str(attempt_root),
            ],
            directory / "pack_logs" / f"{sample_id}.attempt{attempt}.log",
            env,
        )
        try:
            if process.wait(timeout=180):
                raise RuntimeError(f"pack failed: {sample_id}; see pack log")
        finally:
            stop_process(process)
    return install_archive(directory, attempt_root / sample_id, sample_id)


def install_archive(directory: Path, source: Path, sample_id: str) -> Path:
    """拷贝到正式批次目录；原尝试和未确认的旧目录均保留。"""
    destination = directory / "archives" / sample_id
    if destination.exists():
        retained = directory / "incomplete_archives" / uuid4().hex / sample_id
        root = directory.resolve()
        if not destination.resolve().is_relative_to(root) or not retained.resolve().is_relative_to(
            root
        ):
            raise ValueError("archive move escaped the batch directory")
        retained.parent.mkdir(parents=True, exist_ok=False)
        destination.rename(retained)
    shutil.copytree(source, destination)
    path = destination / "manifest.json"
    manifest = json.loads(path.read_text("utf-8"))
    name = Path(manifest["memory_archive"]).name
    manifest["memory_archive"] = str((destination / "memory" / "snapshots" / name).resolve())
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return path


def payload_paths(manifest_path: Path) -> list[Path]:
    """正式世界与记忆快照都必须位于本批次目录内。"""
    manifest = json.loads(manifest_path.read_text("utf-8"))
    paths = [
        (manifest_path.parent / manifest["world_file"]).resolve(),
        Path(manifest["memory_archive"]).resolve(),
    ]
    root = manifest_path.parent.parent.parent.resolve()
    if any(not path.is_relative_to(root) for path in paths):
        raise ValueError("archive payload escaped batch directory")
    return paths
