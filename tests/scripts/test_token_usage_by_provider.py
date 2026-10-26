"""Synthetic trace examples for reproducible offline token accounting."""

import csv
import json
from pathlib import Path

import pytest

from scripts.token_usage_by_provider import (
    NODE_LINKS,
    main,
    model_snapshot,
    provider_for,
    read_calls,
    usage_tables,
)


def write_call(root: Path, name: str = "one", **changes: object) -> Path:
    """Persist the real string-valued payload shape without a model field."""
    path = root / "runs" / "sample" / "trace" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = {
        "thinking_node": "task.choose",
        "prompt_task": "decide_action",
        "prompt_version": "v9",
        "input_tokens": "100",
        "cached_tokens": "30",
        "output_tokens": "20",
        "reasoning_tokens": "5",
        "ok": "true",
    }
    content.update(changes)
    path.write_text(json.dumps({"type": "model_call", "content": json.dumps(content)}))
    return path


def snapshot(root: Path, **models: str) -> Path:
    """Write a result-level configuration snapshot."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "run_config.json"
    path.write_text(
        json.dumps({"models": {key: {"model": value} for key, value in models.items()}})
    )
    return path


@pytest.mark.parametrize(
    ("model", "provider"),
    [
        ("qwen3.8-flash", "dashscope"),
        ("dashscope/foo", "dashscope"),
        ("deepseek-flash", "deepseek"),
        ("claude-haiku-5-5", "anthropic"),
        ("other", "unknown:other"),
        ("unknown", "unknown"),
    ],
)
def test_provider_prefix_mapping_is_explicit(model: str, provider: str) -> None:
    assert provider_for(model) == provider


@pytest.mark.parametrize("model", ["qwen-test", "deepseek-flash", "claude-haiku-5-5", "other"])
@pytest.mark.parametrize("node,link", sorted(NODE_LINKS.items()))
def test_each_node_uses_its_configured_link(
    tmp_path: Path, node: str, link: str, model: str
) -> None:
    snapshot(tmp_path, **{link: model})
    write_call(tmp_path, thinking_node=node)

    calls, _ = read_calls([tmp_path], {})

    assert calls[0]["model"] == model
    assert calls[0]["provider"] == provider_for(model)
    assert "model_source" not in calls[0]


def test_three_providers_sum_tokens_and_explain_claude(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot(tmp_path, text="qwen-test", judge="deepseek-flash", summary="claude-haiku-5-5")
    for number, node in enumerate(["task.choose", "episode.judge", "run.summarize"]):
        for repeat in range(2):
            write_call(tmp_path, f"{number}-{repeat}", thinking_node=node)

    calls, violations = read_calls([tmp_path], {})
    rows = usage_tables(calls, False)["provider"]
    main([str(tmp_path)])
    output = capsys.readouterr().out

    assert [row["provider"] for row in rows] == ["anthropic", "dashscope", "deepseek"]
    for row in rows:
        assert (row["calls"], row["failed_calls"]) == (2, 0)
        assert (row["input_tokens"], row["uncached_tokens"], row["cached_tokens"]) == (200, 140, 60)
        assert (row["output_tokens"], row["reasoning_tokens"], row["hit_rate"]) == (40, 10, 0.3)
    assert not violations
    assert "Claude: uncached includes cache_creation" in output
    assert "already including thinking/reasoning" in output
    assert "NOT recorded per call" not in output


def test_failed_missing_and_zero_are_distinct(tmp_path: Path) -> None:
    write_call(tmp_path, "failed", ok="false")
    write_call(tmp_path, "missing", input_tokens=None)
    write_call(tmp_path, "missing_cached", cached_tokens=None)
    write_call(tmp_path, "missing_output", output_tokens=None)
    write_call(
        tmp_path,
        "zero",
        input_tokens="0",
        cached_tokens="0",
        output_tokens="0",
        reasoning_tokens=None,
    )

    absent = write_call(tmp_path, "absent")
    absent.write_text(json.dumps({"type": "model_call", "content": {"ok": "false"}}))

    calls, _ = read_calls([tmp_path], {})
    row = usage_tables(calls, False)["provider"][0]

    assert (row["calls"], row["failed_calls"]) == (6, 5)
    assert (row["input_tokens"], row["cached_tokens"], row["output_tokens"]) == (0, 0, 0)
    assert row["reasoning_tokens"] is None
    assert row["hit_rate"] is None


def test_cache_invariant_is_listed_without_clamping(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_call(tmp_path, input_tokens="10", cached_tokens="12")
    output = tmp_path.parent / "violations.json"

    main([str(tmp_path), "--json", str(output)])
    rendered = capsys.readouterr().out
    tables = json.loads(output.read_text(encoding="utf-8"))["tables"]

    assert tables["provider"][0]["uncached_tokens"] == -2
    violation = tables["violations"][0]
    assert (violation["input_tokens"], violation["cached_tokens"]) == (10, 12)
    assert violation["node"] == "task/decide_action"
    assert violation["sample"].endswith("/runs/sample")
    assert "### violations" in rendered and "one.json" in rendered


def test_snapshot_priority_and_nearest_ancestor_lookup(tmp_path: Path) -> None:
    path = write_call(tmp_path)
    baseline = tmp_path / "baseline_context.json"
    baseline.write_text(json.dumps({"models": {"text_model": "qwen-test"}}))

    assert model_snapshot(path.parent.parent) == {"text": "qwen-test"}
    snapshot(tmp_path, text="deepseek-flash")
    for root in [tmp_path, tmp_path / "runs", path.parent.parent]:
        calls, _ = read_calls([root], {})
        assert calls[0]["model"] == "deepseek-flash"
    snapshot(path.parent.parent, text="claude-haiku-5-5")
    assert model_snapshot(path.parent.parent) == {"text": "claude-haiku-5-5"}


@pytest.mark.parametrize("node", [None, "future.choose"])
def test_absent_or_unknown_node_remains_unknown(tmp_path: Path, node: str | None) -> None:
    snapshot(tmp_path, text="qwen-test")
    path = write_call(tmp_path, thinking_node=node)
    if node is None:
        event = json.loads(path.read_text())
        content = json.loads(event["content"])
        del content["thinking_node"]
        event["content"] = content
        path.write_text(json.dumps(event))

    calls, _ = read_calls([tmp_path], {"text": "deepseek-flash"})

    assert calls[0]["model"] == calls[0]["provider"] == "unknown"


def test_missing_snapshot_remains_unknown(tmp_path: Path) -> None:
    write_call(tmp_path)

    calls, _ = read_calls([tmp_path], {})

    assert calls[0]["model"] == calls[0]["provider"] == "unknown"
    assert "model_source" not in calls[0]


def test_manual_models_override_snapshot_through_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot(tmp_path, text="deepseek-flash")
    write_call(tmp_path)

    main([str(tmp_path), "--models", "text=qwen-test,judge=x,summary=y,plan=z"])

    output = capsys.readouterr().out
    assert "qwen-test" in output
    assert "deepseek-flash" not in output


def test_exports_and_repeated_output_are_stable_and_discovery_is_selective(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "input"
    path = write_call(root, "z")
    write_call(root, "a", thinking_node="run.plan", prompt_task="run_plan")
    snapshot(root, text="qwen-test", plan="deepseek-flash")
    (root / "unrelated.json").write_text("not json")
    (path.parent / "ignored.txt").write_text("not json")
    (path.parent / "view.json").write_text(json.dumps({"type": "view"}))
    unrelated = root / "other" / "trace"
    unrelated.mkdir(parents=True)
    (unrelated / "bad.json").write_text("not json")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    json_path, csv_path = tmp_path / "report.json", tmp_path / "report.csv"
    argv = [
        str(root),
        str(root / "runs"),
        "--by-sample",
        "--json",
        str(json_path),
        "--csv",
        str(csv_path),
    ]

    main(argv)
    first = (capsys.readouterr().out, json_path.read_bytes(), csv_path.read_bytes())
    main(argv)
    second = (capsys.readouterr().out, json_path.read_bytes(), csv_path.read_bytes())

    assert first == second
    report = json.loads(first[1])
    assert "NOT recorded per call" not in report["policy"]
    assert sum(row["calls"] for row in report["tables"]["provider"]) == 2
    assert report["tables"]["sample_node"]
    with csv_path.open(encoding="utf-8", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    assert {row["section"] for row in csv_rows} >= {"policy", "provider", "model", "node"}
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_compare_direction_percent_and_added_or_removed_nodes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before, after = tmp_path / "before", tmp_path / "after"
    for root in (before, after):
        snapshot(root, text="deepseek-flash", plan="qwen-test")
    write_call(before)
    write_call(after, input_tokens="200", cached_tokens="60", output_tokens="10")
    write_call(after, "new", thinking_node="run.plan")
    report = tmp_path / "compare.json"

    main([str(before), "--compare", str(after), "--json", str(report)])
    capsys.readouterr()
    tables = json.loads(report.read_text(encoding="utf-8"))["tables"]
    row = next(row for row in tables["compare_provider"] if row["provider"] == "deepseek")

    assert (row["uncached_tokens_delta"], row["uncached_tokens_percent"]) == (70, 100)
    assert (row["cached_tokens_delta"], row["cached_tokens_percent"]) == (30, 100)
    assert (row["output_tokens_delta"], row["output_tokens_percent"]) == (-10, -50)
    added = next(row for row in tables["compare_node"] if row["provider"] == "dashscope")
    assert added["uncached_tokens_percent"] is None


def test_exports_cannot_write_into_input_directory(tmp_path: Path) -> None:
    write_call(tmp_path)

    with pytest.raises(SystemExit, match="2"):
        main([str(tmp_path), "--json", str(tmp_path / "report.json")])

    assert not (tmp_path / "report.json").exists()


@pytest.mark.parametrize("kind", ["none", "some", "all", "two_models"])
def test_recorded_identity_wins_and_all_exports_omit_source_labels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    root, report, exported = tmp_path / "input", tmp_path / "r.json", tmp_path / "r.csv"
    snapshot(root, text="qwen-test")
    for index in range(2):
        recorded = kind in {"all", "two_models"} or (kind == "some" and index == 0)
        model = "deepseek-other" if kind == "two_models" and index else "deepseek-flash"
        identity = {"provider": "deepseek", "model": model} if recorded else {}
        write_call(root, str(index), **identity)
    arguments = [str(root), "--models", "text=deepseek-flash", "--compare", str(root)]

    main([*arguments, "--json", str(report), "--csv", str(exported)])
    output = capsys.readouterr().out
    tables = json.loads(report.read_text(encoding="utf-8"))["tables"]

    expected = {"deepseek-flash", "deepseek-other"} if kind == "two_models" else {"deepseek-flash"}
    assert {row["model"] for row in tables["provider"]} == expected
    assert all(
        not {"source", "model_source"} & row.keys() for rows in tables.values() for row in rows
    )
    assert sum(row["calls"] for row in tables["provider"]) == 2
    assert "NOT recorded per call" not in output
    with exported.open(encoding="utf-8", newline="") as stream:
        assert not {"source", "model_source"} & set(csv.DictReader(stream).fieldnames or [])
