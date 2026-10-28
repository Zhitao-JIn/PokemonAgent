"""Frozen choose inputs are self-contained and match the approved review."""

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from evals.dataset.brain_choose import load


@pytest.mark.skip(reason="D33: 冻结旧格式数据，待新框架重新生成后取消跳过")
def test_frozen_dataset_matches_approved_history_review_and_manifest() -> None:
    """Load all six scenes without capture files or a model provider."""
    root = Path(__file__).resolve().parents[1] / "evals/dataset/brain_choose"
    manifest = json.loads((root / "v1/manifest.json").read_text(encoding="utf-8"))

    cases = load("v1")

    assert len(cases) == manifest["cases"] == 189
    assert dict(Counter(str(case.scene) for case in cases)) == manifest["scenes"]
    assert hashlib.sha256((root / "v1/cases.jsonl").read_bytes()).hexdigest() == manifest["sha256"]
    assert all(case.acceptable and case.label_source == "rule" for case in cases)
    assert (root / "v1/cases.jsonl").read_bytes() == (
        root / "build/cases_history_reviewed.jsonl"
    ).read_bytes()
