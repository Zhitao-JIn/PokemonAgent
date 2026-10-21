"""覆盖检查的公开用法：声明缺口、拒绝不完整新版数据、保持 v1 冻结文件。"""

import json

import pytest

from evals.dataset.errors import DatasetError
from evals.world_script_execute.dataset import load
from evals.world_script_execute.dataset import loader as dataset_loader
from evals.world_script_execute.dataset.build.coverage import coverage, main, render


def test_coverage_distinguishes_success_failure_and_mid_script_interrupt():
    example = load()[0]
    success = example.model_copy(update={"script": "walk_to", "kind": "success"})
    failure = success.model_copy(
        update={
            "kind": "failure",
            "expect": success.expect.model_copy(update={"ok": False, "code": "blocked"}),
        }
    )
    interrupt = success.model_copy(update={"kind": "interrupt"})

    rows = coverage(
        [success, failure, interrupt], ["walk_to"], {"walk_to": ["blocked", "not_converging"]}
    )

    assert rows[0].success == rows[0].interrupt == 1
    assert rows[0].failures == {"blocked": 1, "not_converging": 0}
    assert rows[0].missing == ["C2 not_converging"]
    assert "not_converging: 0" in render(rows)


def test_v1_load_infers_kind_without_rewriting_frozen_data():
    path = dataset_loader.DATASET_DIR / "v1" / "cases.jsonl"
    before = path.read_bytes()

    cases = load("v1")

    assert path.read_bytes() == before
    assert all(case.kind == ("success" if case.expect.ok else "failure") for case in cases)
    assert cases[0].model_dump(mode="json")["kind"] == cases[0].kind


def test_a_new_version_must_declare_each_case_kind(tmp_path, monkeypatch):
    case = load()[0]
    version = tmp_path / "v2"
    state = version / "states" / case.state
    state.parent.mkdir(parents=True)
    state.write_bytes(b"example")
    data = case.model_dump(mode="json", exclude={"kind"})
    (version / "cases.jsonl").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(dataset_loader, "DATASET_DIR", tmp_path)

    with pytest.raises(DatasetError, match="缺少 kind"):
        load("v2")

    data["kind"] = "success"
    (version / "cases.jsonl").write_text(json.dumps(data), encoding="utf-8")
    assert load("v2")[0].kind == "success"


def test_v1_coverage_fails_and_reports_all_missing_successes(capsys):
    result = main(["--version", "v1"])

    output = capsys.readouterr().out
    assert result == 1
    for script in ("wait_until_scene", "party_field_move", "pc_withdraw_pokemon"):
        assert f"{script}: C1 success" in output


def test_unknown_scripts_and_contradictory_kinds_are_rejected():
    case = load()[0]

    with pytest.raises(ValueError, match="未知脚本"):
        coverage([case], [])
    with pytest.raises(ValueError, match="failure 用例期望成功"):
        coverage([case.model_copy(update={"kind": "failure"})], [case.script])


def test_script_metrics_skip_other_scripts_instead_of_counting_them_as_failures():
    from deepeval.errors import MissingTestCaseParamsError
    from deepeval.test_case import LLMTestCase

    from evals.world_script_execute.scorer import ScriptPass

    case = load()[0]
    metric = ScriptPass("another-script")
    test_case = LLMTestCase(
        input=case.case_id, actual_output="{}", expected_output=case.model_dump_json()
    )

    with pytest.raises(MissingTestCaseParamsError):
        metric.measure(test_case)

    assert metric.__name__ == "pass.another-script"
