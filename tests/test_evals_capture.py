"""choose 采集用法：信封可还原、对象原样透传；采集装配仅使用假依赖。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.common.recorder import RecordingChooser
from pokemon_agent.brain.interface import Action, ActionSegment, Goal
from pokemon_agent.direct.interface import ChoosePort
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    ModelCall,
)
from pokemon_agent.settings import load_config
from pokemon_agent.world import ActionSpace, TaskObservation


def request() -> FromHarnessToBrainToolChooseOnceReq:
    """手造一份生产信封，不接帧集、模拟器或模型。"""
    return FromHarnessToBrainToolChooseOnceReq(
        goals=[Goal(goal="向上走一格", criteria="主角位于上一格")],
        obs=TaskObservation(facts={"overlay": "none"}, step=0, scene="walk"),
        space=ActionSpace(names=["up"], mask={"up": True, "a": False}),
        memories=[],
        last_result="上一动作失败",
        knowledge="向上可走",
        human_note="先向上",
    )


def response() -> FromHarnessToBrainToolChooseOnceResp:
    """返回有调用账的生产响应。"""
    return FromHarnessToBrainToolChooseOnceResp(
        action=Action(sequence=[ActionSegment(name="up")]),
        calls=[ModelCall(payload={"raw": "up"})],
    )


class FakeChooser:
    """预设响应或异常，并在调用当时核对请求已经落盘。"""

    def __init__(self, out: Path, result=None, error=None) -> None:
        self.out, self.result, self.error = out, result, error
        self.requests = []

    def choose(self, req):
        self.requests.append(req)
        path = self.out / f"{len(self.requests):06d}.request.json"
        assert (
            FromHarnessToBrainToolChooseOnceReq.model_validate_json(path.read_text("utf-8")) == req
        )
        if self.error is not None:
            raise self.error
        return self.result


def test_recording_chooser_writes_request_before_call_and_preserves_response(tmp_path):
    expected = response()
    inner = FakeChooser(tmp_path, result=expected)
    recorder = RecordingChooser(inner, tmp_path)
    req = request()
    before = req.model_dump_json()

    actual = recorder.choose(req)

    assert isinstance(recorder, ChoosePort)
    assert actual is expected
    assert inner.requests[0] is req
    assert req.model_dump_json() == before
    assert (
        FromHarnessToBrainToolChooseOnceResp.model_validate_json(
            (tmp_path / "000001.response.json").read_text("utf-8")
        )
        == expected
    )


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("unexpected failure"),
        MaxRetriesExceeded(
            1, "bad JSON", calls=[ModelCall(error_kind="ParseFailure", error="bad JSON")]
        ),
        KeyboardInterrupt("cancelled"),
    ],
)
def test_recording_chooser_records_and_reraises_the_same_exception(tmp_path, error):
    inner = FakeChooser(tmp_path, error=error)
    recorder = RecordingChooser(inner, tmp_path)

    with pytest.raises(type(error)) as raised:
        recorder.choose(request())

    assert raised.value is error
    saved = json.loads((tmp_path / "000001.response.json").read_text("utf-8"))
    assert saved["error_type"] == type(error).__name__
    assert saved["error"] == str(error)
    assert saved["calls"] == (
        [call.model_dump(mode="json") for call in error.calls]
        if isinstance(error, MaxRetriesExceeded)
        else []
    )


def test_recording_chooser_keeps_old_pairs_and_continues_numbering(tmp_path):
    inner = FakeChooser(tmp_path, result=response())
    recorder = RecordingChooser(inner, tmp_path)
    recorder.choose(request())
    first_bytes = (tmp_path / "000001.request.json").read_bytes()

    recorder = RecordingChooser(inner, tmp_path)
    recorder.choose(request())

    assert (tmp_path / "000001.request.json").read_bytes() == first_bytes
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "000001.request.json",
        "000001.response.json",
        "000002.request.json",
        "000002.response.json",
    ]


def test_failed_response_write_does_not_replace_the_inner_exception(tmp_path):
    error = RuntimeError("inner failure")
    inner = FakeChooser(tmp_path, error=error)
    recorder = RecordingChooser(inner, tmp_path)
    (tmp_path / "000001.response.json").write_text("existing", encoding="utf-8")

    with pytest.raises(RuntimeError) as raised:
        recorder.choose(request())

    assert raised.value is error
    assert "response recording failed" in error.__notes__[0]
    assert (tmp_path / "000001.response.json").read_text("utf-8") == "existing"


def test_request_collision_prevents_call_and_keeps_existing_file(tmp_path):
    inner = FakeChooser(tmp_path, result=response())
    recorder = RecordingChooser(inner, tmp_path)
    path = tmp_path / "000001.request.json"
    path.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        recorder.choose(request())

    assert inner.requests == []
    assert path.read_text("utf-8") == "existing"


class FakeWorld:
    """只核对绑定与释放，不读取存档内容。"""

    def __init__(self, state, events, bind_error, release_error):
        self.state, self.events = state, events
        self.bind_error, self.release_error = bind_error, release_error

    def use_start_state(self, actual):
        self.events.append("bind")
        assert actual == self.state.resolve()
        if self.bind_error:
            raise self.bind_error

    def release_lease(self):
        self.events.append("release")
        if self.release_error:
            raise self.release_error


def collection_inputs(tmp_path, monkeypatch, capture):
    """提供假状态路径与全新输出路径。"""
    states = tmp_path / "states"
    states.mkdir()
    state = states / "scene.state"
    state.write_bytes(b"fake state; never loaded by a simulator")
    monkeypatch.setattr(capture, "STATES_DIR", states)
    return state, tmp_path / "capture"


@pytest.mark.parametrize("failure_point", [None, "bind", "run"])
@pytest.mark.parametrize("release_fails", [False, True])
def test_collection_wires_only_task_chooser_budget_state_and_releases_lease(
    tmp_path, monkeypatch, failure_point, release_fails
):
    import evals.dataset.brain_choose.build.collect as capture

    state, out = collection_inputs(tmp_path, monkeypatch, capture)
    original = FakeChooser(out, result=response())
    task_runtime = SimpleNamespace(chooser=original)
    events = []
    original_error = RuntimeError("capture failure")
    release_error = OSError("release failure")

    def run(run_id, tasks, *, run_goal):
        events.append("run")
        assert tasks[0].goal == run_goal.goal == "目标"
        assert tasks[0].success_criteria == run_goal.criteria == "判据"
        assert tasks[0].max_steps == 7
        assert isinstance(task_runtime.chooser, RecordingChooser)
        task_runtime.chooser.choose(request())
        if failure_point == "run":
            raise original_error
        return SimpleNamespace(model_dump_json=lambda **kwargs: '{"finished": true}')

    def build(config):
        effective = load_config(config).config
        assert effective.budget.max_total_actions == 7
        assert effective.trace.backend == "local"
        assert effective.paths.runs_root == str(out)
        harness = SimpleNamespace(
            deps=SimpleNamespace(episode=SimpleNamespace(task=task_runtime)), run=run
        )
        game = FakeWorld(
            state,
            events,
            original_error if failure_point == "bind" else None,
            release_error if release_fails else None,
        )
        return harness, game

    monkeypatch.setattr(capture, "build_real", build)
    if failure_point or release_fails:
        with pytest.raises(Exception) as raised:
            capture.collect(state, "目标", "判据", 7, out)
        if failure_point and release_fails:
            assert raised.value.exceptions == (original_error, release_error)
        else:
            assert raised.value is (original_error if failure_point else release_error)
    else:
        capture.collect(state, "目标", "判据", 7, out)
        assert json.loads((out / "run_result.json").read_text("utf-8")) == {"finished": True}
    assert events == ["bind", *(["run"] if failure_point != "bind" else []), "release"]


def test_collection_rejects_archives_before_creating_output_or_assembling(tmp_path):
    from evals.dataset.brain_choose.build.collect import collect

    out = tmp_path / "out"

    with pytest.raises(ValueError, match="原始 .state"):
        collect(tmp_path / "archives/world.state", "g", "c", 1, out)

    assert not out.exists()


def test_collection_cli_passes_all_five_required_arguments(tmp_path, monkeypatch):
    import evals.dataset.brain_choose.build.collect as capture

    calls = []
    monkeypatch.setattr(capture, "collect", lambda *args: calls.append(args))

    assert (
        capture.main(
            [
                "--state",
                "scene.state",
                "--goal",
                "目标",
                "--criteria",
                "判据",
                "--steps",
                "9",
                "--out",
                str(tmp_path),
            ]
        )
        == 0
    )

    assert calls == [(Path("scene.state"), "目标", "判据", 9, tmp_path)]


@pytest.mark.parametrize("steps,goal,criteria", [(0, "g", "c"), (1, " ", "c"), (1, "g", " ")])
def test_collection_rejects_invalid_inputs_and_existing_output(
    tmp_path, monkeypatch, steps, goal, criteria
):
    import evals.dataset.brain_choose.build.collect as capture

    state = tmp_path / "source.state"
    state.write_bytes(b"fake")
    monkeypatch.setattr(capture, "STATES_DIR", tmp_path)
    out = tmp_path / "out"

    with pytest.raises(ValueError, match="正整数"):
        capture.collect(state, goal, criteria, steps, out)
    assert not out.exists()

    out.mkdir()
    with pytest.raises(FileExistsError):
        capture.collect(state, "g", "c", 1, out)
    assert list(out.iterdir()) == []
