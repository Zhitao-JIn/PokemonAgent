"""Synthetic, offline examples for prompt blocks, calibration and cache breakpoints."""

import base64
import hashlib
import itertools
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.prompt_block_usage import (
    BLOCKS,
    SECTIONS,
    analyze,
    calibrate,
    fit,
    image_size,
    main,
    read_calls,
    split_blocks,
)


def png(width: int = 160, height: int = 144) -> str:
    header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", width, height)
    payload = header + b"\x08\x06\0\0\0" + b"\0" * 4
    return "data:image/png;base64," + base64.b64encode(payload).decode()


def write_call(root: Path, seq: int | str = 1, sample: str = "one", **changes: object) -> Path:
    path = root / "runs" / sample / "trace" / f"{seq}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = dict(
        thinking_node="task.choose",
        prompt_task="decide_action",
        prompt_version="v10",
        provider="qwen",
        model="test",
        prompt="## 规则\n规则\n## 目标\n目标\n",
        images=[],
        input_tokens="100",
        cached_tokens="40",
        output_tokens="5",
        ok="true",
    )
    content.update(changes)
    event = dict(
        uuid=f"event-{seq}",
        seq=seq,
        kind="choose_call",
        type="model_call",
        meta=json.dumps({"run_id": "run", "task_id": "task"}),
        content=json.dumps(content),
    )
    path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_blocks_cover_every_character_and_keep_actual_order(newline: str) -> None:
    prompt = newline.join(f"## {name}{newline}正文{name}" for name in BLOCKS)

    blocks, repeats = split_blocks(prompt)

    assert [name for name, _ in blocks] == list(BLOCKS)
    assert "".join(body for _, body in blocks) == prompt.replace("\r\n", "\n")
    assert repeats == 0


@pytest.mark.parametrize("prompt", ["", "没有规范标题\n", "## 规则  \n正文\n"])
def test_no_exact_heading_leaves_text_in_preamble(prompt: str) -> None:
    blocks, repeats = split_blocks(prompt)

    assert blocks == ([("(前导)", prompt)] if prompt else [])
    assert repeats == 0


def test_empty_blocks_are_omitted_and_article_headings_are_not_boundaries() -> None:
    prompt = "## 规则\n规则\n## 检索知识\n## NPC\n内容\n## 第 1 条\n更多\n"

    blocks, _ = split_blocks(prompt)

    assert [name for name, _ in blocks] == ["规则", "检索知识"]
    assert "## NPC\n内容" in blocks[-1][1]
    assert sum(len(body) for _, body in blocks) == len(prompt)


def test_repeated_canonical_heading_stays_in_current_block_and_is_anomalous() -> None:
    prompt = "## 规则\nA\n## 目标\nB\n## 规则\nC\n"

    blocks, repeats = split_blocks(prompt)

    assert [name for name, _ in blocks] == ["规则", "目标"]
    assert blocks[-1][1] == "## 目标\nB\n## 规则\nC\n"
    assert repeats == 1 and sum(len(body) for _, body in blocks) == len(prompt)


def test_report_exposes_order_counts_sections_duplicates_and_anomalies(tmp_path: Path) -> None:
    prompt = (
        "前导\n## 规则\n开头\n### 小节\n规则正文\n## 检索知识\n"
        "## 相同标题\n第一份\n## 相同标题\n第二份\n## 另一标题\n第一份\n"
        "## 本层历史\n### 历史条目\n事实\n## 规则\n重复标题\n"
    )
    write_call(tmp_path, 1, prompt=prompt, images=[png(), "bad"])
    write_call(tmp_path, 2, prompt="## 规则\nR\n## 目标\nG\n## 检索知识\nK\n")
    write_call(tmp_path, 3, prompt="## 规则\nR\n## 目标\nG\n## 检索知识\nK\n")

    tables = analyze([tmp_path])

    overview = tables["节点概览"][0]
    assert overview["common_order_count"] == 2 and len(overview["orders"]) == 2
    assert overview["resolutions"] == ["160x144"] and overview["unparseable_images"] == 1
    section = next(r for r in tables["规则小节"] if r["title"] == "小节")
    assert section["mean_chars"] == len("### 小节\n规则正文\n")
    intro = next(r for r in tables["规则小节"] if r["title"] == "(规则开头)")
    assert intro["occurrences"] == 3
    article = next(r for r in tables["检索知识条目"] if r["title"] == "相同标题")
    assert article["occurrences"] == article["duplicate_titles"] == article["duplicates"] == 2
    assert article["duplicate_hashes"] == 1
    assert sum(article["char_counts"].values()) == 2
    assert hashlib.sha256("第一份".encode()).hexdigest()[:8] in article["hashes"]
    assert {r["category"]: r["count"] for r in tables["异常"]}["同名块标题"] == 1
    history = next(r for r in tables["块构成"] if r["block"] == "本层历史")
    assert any(s["title"] == "历史条目" for s in history["subheadings"])


@pytest.mark.parametrize(
    "uri", ["bad", "data:image/png;base64,%%%%", "data:image/png;base64,YQ==", None]
)
def test_invalid_images_are_countable_without_raising(uri: object) -> None:
    assert image_size(uri) is None


def test_png_header_resolution_is_read_without_exposing_pixels() -> None:
    assert image_size(png(320, 288)) == "320x288"


def calibration_calls(root: Path, negative: bool = False, constant_images: bool = False) -> list:
    for seq, (chinese, other, images) in enumerate(
        itertools.product((10, 20, 30), (100, 200, 300), range(3))
    ):
        images = 1 if constant_images else images
        total = (
            (-0.6 if negative else 0.6) * chinese + (2 if negative else 0.3) * other + 1200 * images
        )
        write_call(
            root,
            seq,
            prompt="汉" * chinese + "x" * other,
            images=[png()] * images,
            input_tokens=str(round(total)),
        )
    return read_calls([root])[0]


def test_calibration_recovers_known_cjk_other_and_image_coefficients(tmp_path: Path) -> None:
    result = calibrate(calibration_calls(tmp_path))

    assert result["fit"] == "a" and result["samples"] == 27
    assert result["coefficients"] == pytest.approx(dict(cjk=0.6, other=0.3, images=1200))
    assert result["r_squared"] == pytest.approx(1)
    assert result["median_abs_residual_percent"] == pytest.approx(0, abs=1e-8)


@pytest.mark.parametrize(("count", "expected"), [(2, "未校准"), (3, "c"), (6, "b")])
def test_small_sample_counts_use_simpler_models(tmp_path: Path, count: int, expected: str) -> None:
    for seq in range(count):
        size, images = (seq + 1) * 10, seq % 2
        write_call(
            tmp_path,
            seq,
            prompt="x" * size,
            images=[png()] * images,
            input_tokens=str(size // 2 + 100 * images),
        )

    result = calibrate(read_calls([tmp_path])[0])

    assert result["fit"] == expected


def test_constant_image_counts_are_not_given_an_independent_coefficient(tmp_path: Path) -> None:
    result = calibrate(calibration_calls(tmp_path, constant_images=True))

    assert result["fit"] == "c" and "images" not in result["coefficients"]


def test_negative_full_model_coefficient_falls_back_to_nonnegative_simpler_fit(
    tmp_path: Path,
) -> None:
    result = calibrate(calibration_calls(tmp_path, negative=True))

    assert result["fit"] == "b"
    assert all(v >= 0 for v in result["coefficients"].values())


def test_prefixes_follow_numeric_sequence_and_detect_append(tmp_path: Path) -> None:
    before, after = "## 规则\nR\n## 目标\nold\n", "## 规则\nR\n## 目标\nnew\n"
    write_call(tmp_path, "9", prompt=before)
    write_call(tmp_path, "10", prompt=after, cached_tokens="80")
    write_call(tmp_path, "11", prompt=after + "more\n", cached_tokens="60")

    result = analyze([tmp_path])["共同前缀断点"][0]

    assert result["pairs"] == 2 and result["pure_append_pairs"] == 1
    assert result["break_blocks"] == {"目标": 2}
    assert result["mean_cache_hit_rate"] == pytest.approx(0.7)


def test_failures_are_excluded_from_calibration_and_hits_but_keep_text(tmp_path: Path) -> None:
    write_call(tmp_path, 1, provider=None, model=None, input_tokens="0", cached_tokens="0")
    write_call(tmp_path, 2, provider=None, model=None, ok="false", input_tokens="900")
    write_call(tmp_path, 3, provider=None, model=None, input_tokens=None)
    write_call(tmp_path, 4, provider=None, model=None, input_tokens="10", cached_tokens="5")

    tables = analyze([tmp_path])

    assert tables["节点概览"][0]["failed"] == 2
    assert tables["token 校准"][0]["samples"] == 2
    assert tables["token 校准"][0]["provider"] == "unknown"
    assert tables["块构成"] and tables["节点概览"][0]["mean_estimated_tokens"] is None
    assert tables["共同前缀断点"][0]["mean_cache_hit_rate"] == 0.5


def test_output_is_reproducible_complete_and_does_not_write_inputs(tmp_path: Path, capsys) -> None:
    root = tmp_path / "inputs"
    write_call(root, 1, images=[png()], prompt="## 规则\nDO_NOT_ECHO_FULL_TEXT\n")
    (root / "unrelated.json").write_text("not json", encoding="utf-8")

    def hashes() -> dict[str, str]:
        return {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*")
            if p.is_file()
        }

    before = hashes()
    json_path, csv_path = tmp_path / "out.json", tmp_path / "out.csv"
    args = [str(root), str(root / "runs"), "--json", str(json_path), "--csv", str(csv_path)]
    main(args)
    first = (capsys.readouterr().out, json_path.read_bytes(), csv_path.read_bytes())
    main(args)

    assert (capsys.readouterr().out, json_path.read_bytes(), csv_path.read_bytes()) == first
    assert hashes() == before
    assert all(f"### {name}" in first[0] for name in SECTIONS)
    assert set(json.loads(first[1])["tables"]) == set(SECTIONS)
    assert all(name.encode() in first[2] for name in SECTIONS)
    assert "DO_NOT_ECHO_FULL_TEXT" not in first[0] and png() not in first[0]
    assert "data:image/png" not in first[1].decode()
    with pytest.raises(SystemExit):
        main([str(root), "--json", str(root / "forbidden.json")])
    assert hashes() == before


def test_cli_runs_as_a_script_and_never_compares_different_samples(tmp_path: Path) -> None:
    write_call(tmp_path, 1, sample="a")
    write_call(tmp_path, 2, sample="b")

    result = subprocess.run(
        [sys.executable, "-X", "utf8", "scripts/prompt_block_usage.py", str(tmp_path)],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )

    assert "估计 token 是回归估计" in result.stdout
    assert analyze([tmp_path])["共同前缀断点"][0]["pairs"] == 0


def test_provider_fits_pool_directories_then_sum_mixed_node_estimates(tmp_path: Path) -> None:
    roots, totals = [tmp_path / "a", tmp_path / "b"], []
    for provider, factor, image_cost in (("qwen", 0.5, 100), ("claude", 0.8, 200)):
        for seq in range(6):
            size, images = (seq + 1) * 10, seq % 2
            total = round(factor * size + image_cost * images)
            totals.append(total)
            write_call(
                roots[seq // 3],
                seq,
                sample=provider,
                provider=provider,
                prompt="x" * size,
                images=[png()] * images,
                input_tokens=str(total),
            )
    tables = analyze(roots)
    assert [r["fit"] for r in tables["token 校准"]] == ["b", "b"]
    assert [r["samples"] for r in tables["token 校准"]] == [6, 6]
    assert tables["节点概览"][0]["mean_estimated_tokens"] == pytest.approx(sum(totals) / 12)
    assert len(tables["节点概览"][0]["identities"]) == 2
    parts = [r["mean_estimated_tokens"] for r in tables["块构成"]]
    assert sum(parts) == pytest.approx(sum(totals) / 12)


def test_ill_conditioned_columns_are_rejected() -> None:
    assert fit([[1, 1], [1, 1 + 1e-10], [1, 1 - 1e-10]], [2, 2, 2]) is None
