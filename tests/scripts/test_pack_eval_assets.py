"""Examples of deterministic asset selection and generated pack metadata."""

from datetime import date

from scripts.pack_eval_assets import (
    choose_files,
    parse_manifest,
    render_index,
    select_changelog_entries,
)


def test_exclude_patterns_override_matching_includes() -> None:
    manifest = "## Assets\ninclude: assets/**\nexclude: assets/private/**\n"

    selected = choose_files(
        ["assets/keep.md", "assets/private/secret.md"],
        manifest,
        {"assets/keep.md": 10, "assets/private/secret.md": 10},
    )

    assert selected == {"Assets": ["assets/keep.md"]}


def test_always_exclusions_remove_state_archive_png_and_results() -> None:
    manifest = (
        "## Assets\ninclude: evals/**\n"
        "## 始终排除\nexclude: *.state\nexclude: *.zip\n"
        "exclude: *.png\nexclude: **/eval_results/**\n"
    )

    selected = choose_files(
        [
            "evals/a.json",
            "evals/start.state",
            "evals/archive.zip",
            "evals/frame.png",
            "evals/eval_results/run.json",
        ],
        manifest,
        {},
    )

    assert selected == {"Assets": ["evals/a.json"]}


def test_files_larger_than_one_mib_are_excluded_but_threshold_is_inclusive() -> None:
    manifest = "## Assets\ninclude: evals/**\n"
    sizes = {"evals/limit.bin": 1024 * 1024, "evals/large.bin": 1024 * 1024 + 1}

    selected = choose_files(list(sizes), manifest, sizes)

    assert selected == {"Assets": ["evals/limit.bin"]}


def test_changelog_selection_uses_title_keywords_only_and_preserves_order() -> None:
    changelog = (
        "## 2026-10-28（12）—— 评测样本起点\n\n**改了什么**：无关描述。\n"
        "**为什么这么改**：无关。\n\n"
        "## 2026-10-27（11）—— 普通维护\n\n**改了什么**：更新冻结评分数据集。\n"
        "**取舍**：无关。\n\n"
        "## 2026-10-26（10）—— 评测量表整理\n\n**改了什么**：无关描述。\n"
    )

    selected = select_changelog_entries(changelog, ["评测", "起点", "量表"])

    assert selected == [
        ("12", "2026-10-28（12）—— 评测样本起点"),
        ("10", "2026-10-26（10）—— 评测量表整理"),
    ]


def test_index_lists_sections_counts_large_exclusions_and_generation_note() -> None:
    selected = {"Docs": ["docs/a.md", "docs/b.md"], "Code": ["evals/a.py"]}
    sections = parse_manifest("## Docs\ninclude: docs/**\n## 始终排除\nexclude: *.state\n")

    index = render_index(
        selected,
        date(2026, 10, 28),
        "abc123",
        [("docs/large.bin", 1048577)],
        sections,
    )

    assert "## Docs（2 个文件）" in index
    assert "## Code（1 个文件）" in index
    assert "## 合计（3 个文件）" in index
    assert "`docs/a.md`" in index
    assert "`docs/large.bin`：1048577 字节" in index
    assert "本包由 `scripts/pack_eval_assets.py` 生成，请勿手工编辑。" in index
