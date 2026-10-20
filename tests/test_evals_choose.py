"""单步评测用法：假 chooser、冻结信封、确定性比较与原生 DeepEval 分母。"""

from collections import Counter
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import evals.common.run as evaluation
from evals.brain_choose.cases import build_cases
from evals.brain_choose.compare import is_legal, matches
from evals.brain_choose.legacy import main, run_cases, select_cases
from evals.brain_choose.scorer import Acceptable, AcceptableBy, Legal, Parsed, build_metrics
from evals.brain_choose.solver import ChooseRun, ProviderUnreachable, choose_case
from evals.dataset.brain_choose import ActionMatcher, ChooseCase
from evals.dataset.errors import DatasetError
from pokemon_agent.brain.interface import Action, ActionSegment, Goal
from pokemon_agent.brain.interface.domain.script_call import ScriptCall
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    ModelCall,
)
from pokemon_agent.world import ActionSpace, TaskObservation


def key(name="up", times=1):
    return Action(sequence=[ActionSegment(name=name, times=times)])


def case(case_id="hit", **updates):
    req = FromHarnessToBrainToolChooseOnceReq(
        goals=[Goal(goal=case_id, criteria="单帧可判断")],
        obs=TaskObservation(step=0, scene="walk", status="站在路上"),
        space=ActionSpace(names=["up", "down"], mask={"up": True, "down": True, "a": False}),
        memories=[],
    )
    return ChooseCase(
        **{
            "case_id": case_id,
            "request": req,
            "acceptable": [ActionMatcher(key="up")],
            "scene": "walk",
            "source": "frame",
            "label_source": "human",
            "label_note": "人工示例",
            "origin": "handmade",
            **updates,
        }
    )


class FakeChooser:
    """按目标选择预设结果，接到的只有生产请求，无法读取 acceptable。"""

    def __init__(self, outcomes):
        self.outcomes = outcomes

    def choose(self, req):
        outcome = self.outcomes[req.goals[-1].goal]
        if isinstance(outcome, Exception):
            raise outcome
        return FromHarnessToBrainToolChooseOnceResp(action=outcome, calls=[ModelCall()])


def examples():
    cases = [case(name) for name in ("hit", "miss", "parse", "illegal")]
    chooser = FakeChooser(
        {
            "hit": key(),
            "miss": key("down"),
            "illegal": key("a"),
            "parse": MaxRetriesExceeded(
                1, "bad JSON", [ModelCall(error_kind="ParseFailure", error="bad JSON")]
            ),
        }
    )
    return cases, chooser


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"key": "up", "script": "walk_to"},
        {"key": ""},
        {"key": "up", "args": {}},
        {"script": "walk_to", "max_times": 1},
        {"key": "up", "max_times": 0},
    ],
)
def test_matcher_rejects_invalid_shape(fields):
    with pytest.raises(ValidationError):
        ActionMatcher(**fields)


@pytest.mark.parametrize("updates", [{"acceptable": []}, {"scene": "unknown"}])
def test_case_rejects_empty_answers_or_unknown_scene(updates):
    with pytest.raises(ValidationError):
        case(**updates)


@pytest.mark.parametrize(
    "action,matchers,expected",
    [
        (key(times=2), [ActionMatcher(key="up", max_times=2)], True),
        (key(times=3), [ActionMatcher(key="up", max_times=2)], False),
        (
            Action(sequence=[ActionSegment(name="up"), ActionSegment(name="down")]),
            [ActionMatcher(key="up")],
            False,
        ),
        (key(times=5), [ActionMatcher(key="up")], True),
        (
            Action(script=ScriptCall(name="walk_to", args={"x": 2, "y": 3})),
            [ActionMatcher(script="walk_to", args={"x": 2})],
            True,
        ),
        (
            Action(script=ScriptCall(name="walk_to", args={"x": 3})),
            [ActionMatcher(script="walk_to", args={"x": 2})],
            False,
        ),
        (Action(script=ScriptCall(name="walk_to")), [ActionMatcher(script="walk_to")], True),
        (
            Action(script=ScriptCall(name="walk_to")),
            [ActionMatcher(script="walk_to", args={"x": 2})],
            False,
        ),
        (key(), [ActionMatcher(script="up")], False),
        (Action(script=ScriptCall(name="up")), [ActionMatcher(key="up")], False),
        (Action.model_construct(sequence=[], script=None), [ActionMatcher(key="up")], False),
    ],
)
def test_matches_checks_every_segment_and_script_argument_subset(action, matchers, expected):
    assert matches(action, matchers) is expected


def test_legality_uses_only_mask_even_when_names_disagree():
    space = ActionSpace(names=["a"], mask={"up": True, "a": False, "walk_to": True})

    assert is_legal(key(), space)
    assert not is_legal(key("a"), space)
    assert not is_legal(key("missing"), space)
    assert is_legal(Action(script=ScriptCall(name="walk_to")), space)
    assert not is_legal(Action(script=ScriptCall(name="missing")), space)


def test_fake_chooser_produces_hit_miss_parse_and_illegal_metric_results():
    cases, chooser = examples()

    runs = [choose_case(item, chooser) for item in cases]
    tests = build_cases(cases, runs)

    assert [Acceptable().measure(item) for item in tests] == [1, 0, 0, 0]
    assert [Parsed().measure(item) for item in tests] == [1, 1, 0, 1]
    assert [Legal().measure(tests[index]) for index in (0, 1, 3)] == [1, 1, 0]
    from deepeval.errors import MissingTestCaseParamsError

    with pytest.raises(MissingTestCaseParamsError):
        Legal().measure(tests[2])
    with pytest.raises(MissingTestCaseParamsError):
        AcceptableBy("dialog").measure(tests[0])
    assert AcceptableBy("walk").measure(tests[0]) == 1


@pytest.mark.parametrize("kind", ["ToolTimeout", "ProviderRejected"])
def test_provider_failure_keeps_calls_but_produces_no_scored_result(kind):
    item = case()
    call = ModelCall(error_kind=kind, error="unreachable")
    error = MaxRetriesExceeded(1, "unreachable", [call])

    with pytest.raises(ProviderUnreachable) as raised:
        choose_case(item, FakeChooser({"hit": error}))

    assert raised.value.calls[0] is call
    assert raised.value.__cause__ is error


def test_native_deepeval_counts_parsed_failure_once_and_skips_legal(tmp_path, monkeypatch):
    cases, chooser = examples()
    cases[0].tags = ["read_screen"]
    test_cases = build_cases(cases, [choose_case(item, chooser) for item in cases])
    native_evaluate = evaluation.evaluate
    results = []

    def capture(**kwargs):
        result = native_evaluate(**kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(evaluation, "evaluate", capture)
    monkeypatch.chdir(tmp_path)

    status = evaluation.run_evaluation(
        test_cases=test_cases,
        metrics=build_metrics(cases),
        results_folder=str(tmp_path / "results"),
        hyperparameters={"dataset": "handmade", "cases": 4},
    )

    assert status == 1
    totals = Counter(
        metric.name for result in results[0].test_results for metric in result.metrics_data
    )
    assert totals == {
        "acceptable": 4,
        "parsed": 4,
        "legal": 3,
        "acceptable.walk": 4,
        "acceptable.read_screen": 1,
    }
    assert sum(result.success is True for result in results[0].test_results) == 1


def test_loader_reads_in_order_and_rejects_missing_files_or_duplicate_ids(tmp_path, monkeypatch):
    import evals.dataset.brain_choose.loader as loader

    monkeypatch.setattr(loader, "DATASET_DIR", tmp_path)
    with pytest.raises(DatasetError):
        loader.load()
    (tmp_path / "v1").mkdir()
    with pytest.raises(DatasetError):
        loader.load()
    path = tmp_path / "v1/cases.jsonl"
    path.write_text(
        case("a").model_dump_json() + "\n" + case("b").model_dump_json(), encoding="utf-8"
    )

    assert [item.case_id for item in loader.load()] == ["a", "b"]

    path.write_text(case().model_dump_json() + "\n" + case().model_dump_json(), encoding="utf-8")
    with pytest.raises(DatasetError, match="重复"):
        loader.load()


@pytest.mark.parametrize(
    "case_ids,scenes,tags", [(["unknown"], [], []), ([], ["bad"], []), ([], [], ["bad"])]
)
def test_unknown_filters_are_errors(case_ids, scenes, tags):
    with pytest.raises(ValueError, match="未知"):
        select_cases([case()], case_ids, scenes, tags)


def test_cli_excludes_unreachable_cases_and_preserves_model_override(monkeypatch, capsys):
    import evals.brain_choose.legacy as entry

    cases = [case("hit", tags=["read_screen"]), case("network", tags=["read_screen"])]
    chooser = FakeChooser(
        {
            "hit": key(),
            "network": MaxRetriesExceeded(
                1, "offline", [ModelCall(error_kind="ToolTimeout", error="offline")]
            ),
        }
    )
    builds, evaluations = [], []
    monkeypatch.setattr(entry, "load", lambda version: cases)
    monkeypatch.setattr(
        entry,
        "BrainTool",
        SimpleNamespace(build=lambda **kw: builds.append(kw) or SimpleNamespace(chooser=chooser)),
    )
    monkeypatch.setattr(entry, "run_evaluation", lambda **kw: evaluations.append(kw) or 0)

    assert main(["--text-model", "fake-model", "--workers", "2", "--tag", "read_screen"]) == 0

    assert builds == [{"text": "fake-model"}]
    assert evaluations[0]["hyperparameters"] == {
        "dataset": "v3",
        "cases": 1,
        "text_model": "fake-model",
    }
    assert [item.name for item in evaluations[0]["test_cases"]] == ["hit"]
    assert "network" in capsys.readouterr().out


def test_thread_pool_retains_input_order_and_unknown_exceptions_propagate():
    cases, chooser = examples()

    scored, runs, skipped = run_cases(cases, chooser, 2)

    assert [item.case_id for item in scored] == [item.case_id for item in cases]
    assert len(runs) == 4 and skipped == []
    error = RuntimeError("programming error")
    with pytest.raises(RuntimeError) as raised:
        choose_case(case(), FakeChooser({"hit": error}))
    assert raised.value is error


@pytest.mark.parametrize("fields", [{}, {"action": key(), "failure": "bad"}])
def test_run_requires_exactly_one_outcome(fields):
    with pytest.raises(ValidationError):
        ChooseRun(**fields)
