"""Build a dated, reproducible archive of tracked evaluation assets."""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

MAX_FILE_SIZE = 1024 * 1024
CHANGELOG_KEYWORDS_HEADING = "CHANGELOG 关键词"
EXCLUSION_HEADING = "始终排除"


@dataclass
class ManifestSection:
    """A named manifest section with include, exclude, or keyword entries."""

    title: str
    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


def parse_manifest(manifest_text: str) -> list[ManifestSection]:
    """Parse section headers and their include, exclude, and keyword patterns."""
    sections: list[ManifestSection] = []
    current: ManifestSection | None = None
    for raw_line in manifest_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            current = ManifestSection(line[3:].strip())
            sections.append(current)
            continue
        if current is None:
            raise ValueError("manifest entries must follow a section heading")
        if line.startswith("include: "):
            current.includes.append(line.removeprefix("include: ").strip())
        elif line.startswith("exclude: "):
            current.excludes.append(line.removeprefix("exclude: ").strip())
        elif line.startswith("keyword: "):
            current.keywords.append(line.removeprefix("keyword: ").strip())
        else:
            raise ValueError(f"unrecognized manifest entry: {line}")
    return sections


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def choose_files(
    tracked_files: list[str], manifest_text: str, file_sizes: dict[str, int]
) -> dict[str, list[str]]:
    """Select files from tracked paths using ordered sections and global exclusions."""
    sections = parse_manifest(manifest_text)
    exclusions = [pattern for section in sections for pattern in section.excludes]
    included_sections = [
        section for section in sections if section.includes and section.title != EXCLUSION_HEADING
    ]
    chosen: dict[str, list[str]] = {section.title: [] for section in included_sections}
    for path in sorted(set(tracked_files)):
        if file_sizes.get(path, 0) > MAX_FILE_SIZE or _matches(path, exclusions):
            continue
        for section in included_sections:
            if _matches(path, section.includes) and not _matches(path, section.excludes):
                chosen[section.title].append(path)
                break
    return chosen


def select_changelog_entries(changelog_text: str, keywords: list[str]) -> list[tuple[str, str]]:
    """Return entries whose title lines contain a keyword, in source order."""
    blocks = re.split(r"(?=^## )", changelog_text, flags=re.MULTILINE)
    selected: list[tuple[str, str]] = []
    for block in blocks:
        heading_match = re.match(r"^## ([^\r\n]+)", block)
        if not heading_match:
            continue
        heading = heading_match.group(1).strip()
        if not any(keyword in heading for keyword in keywords):
            continue
        number_match = re.search(r"（(\d+)）", heading)
        selected.append((number_match.group(1) if number_match else "", heading))
    return selected


def render_changelog_excerpt(changelog_text: str, keywords: list[str]) -> str:
    """Render complete entries whose title lines contain a keyword."""
    blocks = re.split(r"(?=^## )", changelog_text, flags=re.MULTILINE)
    selected: list[str] = []
    for block in blocks:
        heading_match = re.match(r"^## ([^\r\n]+)", block)
        if not heading_match:
            continue
        heading = heading_match.group(1)
        if any(keyword in heading for keyword in keywords):
            selected.append(block.rstrip())
    return "# 评测相关 CHANGELOG 摘录\n\n" + "\n\n".join(selected) + "\n"


def render_index(
    selected: dict[str, list[str]],
    generated_on: date,
    revision: str,
    excluded_large: list[tuple[str, int]],
    sections: list[ManifestSection],
) -> str:
    """Render counts, exact section paths, provenance, and exclusions."""
    lines = [
        "# 测评资产包索引",
        "",
        f"- 生成日期：{generated_on:%Y-%m-%d}",
        f"- Git HEAD：`{revision}`",
        "",
    ]
    for title, paths in selected.items():
        lines.extend([f"## {title}（{len(paths)} 个文件）", ""])
        lines.extend(f"- `{path}`" for path in paths)
        lines.append("")
    total = sum(map(len, selected.values()))
    lines.extend([f"## 合计（{total} 个文件）", "", "## 未包含", ""])
    exclusions = [pattern for section in sections for pattern in section.excludes]
    lines.extend(f"- 排除规则：`{pattern}`" for pattern in exclusions)
    lines.append(f"- 大于 1 MiB 的文件（阈值 {MAX_FILE_SIZE} 字节）：")
    if excluded_large:
        lines.extend(f"  - `{path}`：{size} 字节" for path, size in excluded_large)
    else:
        lines.append("  - 无")
    lines.extend(["", "本包由 `scripts/pack_eval_assets.py` 生成，请勿手工编辑。", ""])
    return "\n".join(lines)


def _git_output(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout


def build_pack(
    root: Path, generated_on: date, suffix: str = ""
) -> tuple[Path, Path, dict[str, list[str]]]:
    """Build the dated directory and ZIP from the repository's tracked files."""
    manifest_text = (root / "scripts/eval_assets_manifest.txt").read_text(encoding="utf-8")
    sections = parse_manifest(manifest_text)
    tracked = _git_output(root, "ls-files").splitlines()
    sizes = {path: (root / path).stat().st_size for path in tracked if (root / path).is_file()}
    selected = choose_files(tracked, manifest_text, sizes)
    included = {path for paths in selected.values() for path in paths}
    excluded_large = sorted(
        (path, size)
        for path, size in sizes.items()
        if size > MAX_FILE_SIZE and any(_matches(path, section.includes) for section in sections)
    )
    changelog_keywords = next(
        section.keywords for section in sections if section.title == CHANGELOG_KEYWORDS_HEADING
    )
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    head = _git_output(root, "rev-parse", "HEAD").strip()
    pack_name = f"eval_assets_pack_{generated_on:%Y%m%d}{suffix}"
    output_dir = root / pack_name
    output_zip = root / f"{pack_name}.zip"
    if output_dir.exists() or output_zip.exists():
        raise FileExistsError(f"refusing to overwrite existing pack: {pack_name}")
    output_dir.mkdir()
    for path in sorted(included):
        destination = output_dir / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((root / path).read_bytes())
    (output_dir / "CHANGELOG_eval_entries.md").write_text(
        render_changelog_excerpt(changelog, changelog_keywords), encoding="utf-8"
    )
    (output_dir / "INDEX.md").write_text(
        render_index(selected, generated_on, head, excluded_large, sections), encoding="utf-8"
    )
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(output_dir).as_posix())
    return output_dir, output_zip, selected


def main() -> None:
    """Generate today's asset pack in the current repository root."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--suffix", default="", help="optional output-name suffix")
    arguments = parser.parse_args()
    directory, archive, selected = build_pack(
        arguments.root.resolve(), date.today(), arguments.suffix
    )
    print(f"Generated {directory.name}: {sum(map(len, selected.values()))} source files")
    print(f"Archive: {archive.name}")


if __name__ == "__main__":
    main()
