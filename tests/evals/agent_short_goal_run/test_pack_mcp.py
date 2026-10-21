"""pack_one 的顺序：清空记忆 → build_real → 绑定起点 → run；两个入口不再抛 NotImplementedError。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.agent_short_goal_run.dataset.schemas import EvalSample, SampleStart
from pokemon_agent.mcpclient.client import McpToolError


def _sample() -> EvalSample:
    return EvalSample(
        sample_id="s1",
        dataset_version="v1",
        category="movement",
        start=SampleStart(
            kind="archive", archive="s1", source_state="s1.state", source_sha256="match"
        ),
        goal="g",
        success_criteria="-",
        max_steps=10,
        behavior="b",
        check_id=None,
        rubric=["r1"],
        red_lines=["l1"],
        k_metric="pass_at_k",
        split="val",
    )


@pytest.mark.parametrize("failure_point", ["bind", "run"])
@pytest.mark.parametrize("release_fails", [False, True])
def test_pack_one_clears_memory_then_binds_start_state_before_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure_point: str, release_fails: bool
) -> None:
    """绑定或 run 异常均释放租约；释放也失败时保留两份异常。"""
    import evals.agent_short_goal_run.dataset.build.pack as pack

    version = "v1"
    state = tmp_path / version / "s1.state"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_bytes(b"state-bytes")

    events: list[object] = []
    monkeypatch.setattr(pack, "DATASET_DIR", tmp_path)
    monkeypatch.setattr(pack, "sha256_of", lambda path: "match")
    monkeypatch.setattr(pack, "load_env_file", lambda: None)
    monkeypatch.setattr(pack, "env_str", lambda name: "http://fake")
    monkeypatch.setattr(pack, "run_id_for", lambda sample_id: "eval-s1")

    def fake_memory_build(*, memory_server_url, memory_root=None):
        events.append("memory_build")
        return object()

    monkeypatch.setattr(pack, "MemoryTool", SimpleNamespace(build=fake_memory_build))
    monkeypatch.setattr(pack, "clear_memory", lambda tool: events.append("clear_memory"))

    class _Game:
        def use_start_state(self, path: Path) -> None:
            events.append(("use_start_state", path))
            if failure_point == "bind":
                raise OSError("start state disappeared")

        def release_lease(self) -> None:
            events.append("release_lease")
            if release_fails:
                raise McpToolError("release rejected")

    class _Harness:
        def run(self, run_id: str, tasks: list, checkpoint_only: bool = False) -> None:
            events.append(("harness.run", run_id, checkpoint_only))
            raise RuntimeError("stop")

    def fake_build_real(**kwargs):
        events.append("build_real")
        return (_Harness(), _Game())

    monkeypatch.setattr(pack, "build_real", fake_build_real)

    expected_error = OSError if failure_point == "bind" else RuntimeError
    with pytest.raises(ExceptionGroup if release_fails else expected_error) as raised:
        pack.pack_one(_sample(), version)

    if release_fails:
        assert isinstance(raised.value.exceptions[0], expected_error)
        assert isinstance(raised.value.exceptions[1], McpToolError)
    assert events == [
        "memory_build",
        "clear_memory",
        "build_real",
        ("use_start_state", state),
        *([("harness.run", "eval-s1", True)] if failure_point == "run" else []),
        "release_lease",
    ]


def test_pack_one_rejects_hash_mismatch_before_any_side_effect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """哈希对不上 → ValueError，且清空记忆与装配都没发生。"""
    import evals.agent_short_goal_run.dataset.build.pack as pack

    version = "v1"
    state = tmp_path / version / "s1.state"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_bytes(b"state-bytes")

    events: list[str] = []
    monkeypatch.setattr(pack, "DATASET_DIR", tmp_path)
    monkeypatch.setattr(pack, "sha256_of", lambda path: "different")
    monkeypatch.setattr(pack, "load_env_file", lambda: None)
    monkeypatch.setattr(pack, "env_str", lambda name: "http://fake")
    monkeypatch.setattr(pack, "MemoryTool", SimpleNamespace(build=lambda **k: "mem"))
    monkeypatch.setattr(pack, "clear_memory", lambda tool: events.append("clear_memory"))
    monkeypatch.setattr(pack, "build_real", lambda **k: events.append("build_real"))

    with pytest.raises(ValueError, match="哈希"):
        pack.pack_one(_sample(), version)

    assert events == []


def test_main_no_longer_raises_not_implemented(monkeypatch: pytest.MonkeyPatch) -> None:
    """main 走过了旧 NotImplementedError 位置：版本不一致先断言。"""
    import evals.agent_short_goal_run.dataset.build.pack as pack

    monkeypatch.setattr(pack, "load_env_file", lambda path=None: None)

    with pytest.raises(AssertionError, match="version"):
        pack.main(["--version", "v99"])
