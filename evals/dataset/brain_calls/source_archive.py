"""保留原始录制和 trace 的压缩审计包，脱离本机 ignored 目录仍可验源。"""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from pydantic import BaseModel

from evals.agent_short_goal_run.dataset.loader import DATASET_DIR
from evals.paths import REPO_ROOT
from pokemon_agent.schemas.harness import TraceKind

SOURCE_KINDS: frozenset[str] = frozenset(
    {
        # 数据集构建：export_dataset.load_events() 按这些调用账配对模型尝试
        TraceKind.CHOOSE_CALL,
        TraceKind.JUDGE_CALL,
        TraceKind.PLAN_CALL,
        TraceKind.DECOMPOSE_CALL,
        TraceKind.VERIFY_CALL,
        TraceKind.SUMMARIZE_EPISODE_CALL,
        TraceKind.SUMMARIZE_TASK_CALL,
        TraceKind.SUMMARIZE_RUN_CALL,
        # 独立参考：scope_audit 取局身份，RunStream 取局与帧
        TraceKind.EPISODE_START,
        TraceKind.SENSE_FRAME,
        # 机械判据：rules/shop.py 读执行动作与对象记忆
        TraceKind.ACT_CALL,
        TraceKind.WRITE_OBJECT_MEMORY,
    }
)
"""来源归档里数据集构建与评测实际消费的账；其余账按原样跳过（D22）。"""


class SourceArchiveManifest(BaseModel):
    """每个归档条目使用原 repo 相对路径与字节哈希。"""

    archive: str
    archive_sha256: str
    entries: dict[str, str]


def frozen_start_files(batch: Path) -> list[Path]:
    """核对 pack 时实际使用的 manifest 字节，并保留正式世界与空记忆快照。"""
    pack = json.loads((batch / "pack_report.json").read_text("utf-8"))
    files = []
    for sample_id, expected in pack["archive_hashes"].items():
        archive_root = (
            Path(pack["archive_root"]) if pack.get("archive_root") else DATASET_DIR / "v1/archives"
        )
        path = archive_root / sample_id / "manifest.json"
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"captured start manifest changed: {sample_id}")
        manifest = json.loads(path.read_text("utf-8"))
        files += [
            path,
            path.parent / manifest["world_file"],
            Path(manifest["memory_archive"])
            if Path(manifest["memory_archive"]).is_absolute()
            else DATASET_DIR / "v1" / manifest["memory_archive"],
        ]
    return files


def archive_sources(batch: Path, output: Path) -> SourceArchiveManifest:
    """封存正式起点、原始账和录制，不带服务端存储、ROM、密钥或临时存档。"""
    files = frozen_start_files(batch)
    files += list((batch / "reports").glob("*.json"))
    files += [batch / name for name in ("pack_report.json", "batch_report.json")]
    files += [batch / "continuation.json"]
    for report_path in sorted((batch / "reports").glob("*.json")):
        report = json.loads(report_path.read_text("utf-8"))
        work = (
            Path(report["work_directory"])
            if report.get("work_directory")
            else batch / "runs" / report_path.stem
        )
        files += list((work / "brain_calls").glob("*/*/*.json"))
        files += list((work / "trace").glob("*.json"))
        files += list((work / "review_calls").glob("*/*/*.json"))
        files += [work / "review_wait_report.json"]
        files += [work / name for name in ("sample.json", "run_config.json", "run_result.json")]
    archive = output / "sources.zip"
    entries = {}
    with ZipFile(archive, "x", compression=ZIP_DEFLATED, compresslevel=9) as stream:
        for path in sorted(set(files)):
            if not path.exists():
                continue
            name, data = path.relative_to(REPO_ROOT).as_posix(), path.read_bytes()
            entries[name] = hashlib.sha256(data).hexdigest()
            info = ZipInfo(name, date_time=(2026, 10, 19, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            stream.writestr(info, data, compresslevel=9)
    manifest = SourceArchiveManifest(
        archive=archive.name,
        archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        entries=entries,
    )
    (output / "sources.manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return manifest


def verify_sources(root: Path) -> dict[str, bytes]:
    """验证归档字节和每份原料，不向文件系统解压；任何漂移均失败。"""
    manifest = SourceArchiveManifest.model_validate_json(
        (root / "sources.manifest.json").read_text("utf-8")
    )
    archive = root / manifest.archive
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest.archive_sha256:
        raise ValueError("source archive hash mismatch")
    with ZipFile(archive) as stream:
        if set(stream.namelist()) != set(manifest.entries):
            raise ValueError("source archive inventory mismatch")
        data = {name: stream.read(name) for name in manifest.entries}
    if any(hashlib.sha256(data[name]).hexdigest() != sha for name, sha in manifest.entries.items()):
        raise ValueError("source archive entry hash mismatch")
    return data


def load_source_events(root: Path, sample_id: str) -> list:
    """从已冻结来源包重读单个样本的有序 trace，只解析白名单内的账（D22）。

    前置条件：`root` 下有 `sources.manifest.json` 与它指的归档。
    后置条件：返回事件的种类都属于 `SOURCE_KINDS`，顺序按 `(seq, uuid)`；
    其余种类不交给 `parse()`——来源归档里的记忆写账不是数据集原料。
    """
    from pokemon_agent.direct.trace import parse
    from pokemon_agent.schemas.harness import TraceEvent

    manifest = SourceArchiveManifest.model_validate_json(
        (root / "sources.manifest.json").read_text("utf-8")
    )
    events = []
    with ZipFile(root / manifest.archive) as stream:
        for name, expected in manifest.entries.items():
            if f"/runs/{sample_id}/trace/" not in name:
                continue
            data = stream.read(name)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("source trace hash mismatch")
            events.append(TraceEvent.model_validate_json(data))
    events.sort(key=lambda event: (event.seq, event.uuid))
    return [parse(event) for event in events if event.kind in SOURCE_KINDS]
