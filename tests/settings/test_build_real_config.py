"""`build_real` 只收配置文件：预算、型号、重试等全部由配置注入，无显式参数。"""

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokemon_agent import build as assembly
from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.mcpclient.client import McpTransportError
from pokemon_agent.prompt import PromptRegistryError
from tests.prompt.unit_fixtures import file_hash, make_registry, make_unit

_TOOLS = (
    "chooser",
    "judger",
    "planner",
    "reflector",
    "verifier",
    "decomposer",
    "summarizer",
    "run_summarizer",
    "task_summarizer",
)


@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    brains, traces, snapshots = [], [], []
    tools = SimpleNamespace(**dict.fromkeys(_TOOLS, object()))

    def brain_build(**kwargs):
        brains.append(kwargs)
        return tools

    def trace_build(**kwargs):
        traces.append(kwargs)
        return SimpleNamespace(flush=lambda: None)

    monkeypatch.setattr(assembly, "load_env_file", lambda: None)
    monkeypatch.setattr(assembly.WorldMcpTool, "build", lambda *args, **kwargs: object())
    monkeypatch.setattr(assembly.MemoryTool, "build", lambda **kwargs: object())
    monkeypatch.setattr(assembly.TraceTool, "build", trace_build)
    monkeypatch.setattr(assembly.BrainTool, "build", brain_build)
    monkeypatch.setattr(assembly, "compile_task_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_episode_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_run_graph", lambda: None)
    monkeypatch.setattr(assembly, "assert_mcp_server_ready", lambda *args: {})
    real_snapshot = assembly.write_snapshot
    monkeypatch.setattr(
        assembly, "write_snapshot", lambda *args: snapshots.append(real_snapshot(*args))
    )

    def overlay(**extra):
        data = {
            "paths": {"runs_root": str(tmp_path)},
            "services": {"world_server_url": "http://w", "memory_server_url": "http://m"},
            "checkpoint": {"enabled": False},
            **extra,
        }
        path = tmp_path / "overlay.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return SimpleNamespace(brains=brains, traces=traces, snapshots=snapshots, overlay=overlay)


def test_build_real_takes_nothing_but_configuration_paths() -> None:
    assert list(inspect.signature(assembly.build_real).parameters) == ["config"]


def test_brain_tool_prompt_versions_returns_validated_registry_metadata() -> None:
    registry = Path(__file__).parents[2] / "pokemon_agent" / "prompt" / "registry.json"

    versions = BrainTool.prompt_versions(str(registry))

    assert len(versions) == 26
    assert list(versions) == sorted(versions)
    for name, fields in versions.items():
        meta_path = registry.parent / "tasks" / name / fields["version"] / "meta.json"
        if not meta_path.is_file():
            meta_path = (
                registry.parent / "tasks" / "fragments" / name / fields["version"] / "meta.json"
            )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert fields == {"version": meta["version"], "hash": meta["hash"]}


def test_the_effective_configuration_reaches_every_runtime(stubbed) -> None:
    harness, _ = assembly.build_real(stubbed.overlay(budget={"max_episodes": 3}))

    for runtime in (harness.deps, harness.deps.episode, harness.deps.episode.task):
        assert runtime.config.budget.max_episodes == 3
    assert harness.deps.deadline is None


def test_each_layer_builds_its_own_brain_from_the_configured_models(stubbed) -> None:
    assembly.build_real(stubbed.overlay(models={"plan": {"model": "deepseek-flash"}}))

    assert [kwargs["links"] for kwargs in stubbed.brains] == [
        ("plan", "judge"),
        ("plan", "judge", "summary"),
        ("text", "judge", "summary"),
    ]
    assert [kwargs["layer"] for kwargs in stubbed.brains] == ["run", "episode", "task"]
    assert all(kwargs["models"].plan.model == "deepseek-flash" for kwargs in stubbed.brains)
    assert all(kwargs["retry"].brain_max_attempts == 2 for kwargs in stubbed.brains)


def test_trace_follows_the_configured_backend_and_run_identity(stubbed, tmp_path) -> None:
    assembly.build_real(stubbed.overlay(run={"run_id": "exp-1", "branch": "b"}))

    request = stubbed.traces[0]
    assert (request["run_id"], request["branch"], request["backend"]) == ("exp-1", "b", "local")
    assert request["trace_root"] == tmp_path / "tracelog"


def test_a_wall_clock_budget_creates_the_run_deadline(stubbed) -> None:
    harness, _ = assembly.build_real(stubbed.overlay(budget={"wall_clock_s": 600}))

    assert harness.deps.deadline is not None


def test_the_effective_configuration_is_snapshotted_for_the_run(stubbed, tmp_path) -> None:
    assembly.build_real(stubbed.overlay(run={"run_id": "snap"}))

    [path] = stubbed.snapshots
    assert path.parent == tmp_path / "config_snapshots" and path.name.startswith("snap-")
    payload = json.loads(path.read_text(encoding="utf-8"))
    prompts = payload["prompts"]
    assert len(prompts) == 26
    assert list(prompts) == sorted(prompts)
    print("prompts preview:", list(prompts.items())[:5])
    print("prompts count:", len(prompts))


def test_a_changed_prompt_registry_changes_the_snapshot_identity(stubbed, tmp_path) -> None:
    make_unit(tmp_path, name="sample_prompt")
    version_two = make_unit(tmp_path / "version-two", name="sample_prompt")
    version_two_path = tmp_path / "tasks" / "sample_prompt" / "v2"
    version_two_path.mkdir(parents=True, exist_ok=True)
    for source in version_two.iterdir():
        destination = version_two_path / source.name
        destination.write_bytes(source.read_bytes())
    meta_path = version_two_path / "meta.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata["version"] = "v2"
    prompt_path = version_two_path / "prompt.md"
    prompt_path.write_text(prompt_path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
    metadata["hash"] = file_hash(version_two_path)
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    registry_path = make_registry(tmp_path, sample_prompt="v1")

    overlay = stubbed.overlay(prompt={"registry": str(registry_path)}, run={"run_id": "same-run"})
    assembly.build_real(overlay)
    [first] = stubbed.snapshots
    first_payload = json.loads(first.read_text(encoding="utf-8"))

    registry_path.write_text(
        json.dumps({"tasks": {"sample_prompt": {"active": "v2"}}}), encoding="utf-8"
    )
    assembly.build_real(overlay)
    second = stubbed.snapshots[-1]
    second_payload = json.loads(second.read_text(encoding="utf-8"))

    assert first != second
    assert first_payload["sha256"] != second_payload["sha256"]
    assert first.name != second.name
    assert first_payload["prompts"]["sample_prompt"]["version"] == "v1"
    assert second_payload["prompts"]["sample_prompt"]["version"] == "v2"
    assert (
        first_payload["prompts"]["sample_prompt"]["hash"]
        != second_payload["prompts"]["sample_prompt"]["hash"]
    )


def test_a_prompt_registry_entry_without_active_version_fails(stubbed, tmp_path) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({"tasks": {"sample_prompt": {}}}), encoding="utf-8")

    with pytest.raises(PromptRegistryError):
        assembly.build_real(stubbed.overlay(prompt={"registry": str(registry_path)}))


def test_a_missing_active_prompt_meta_file_fails(stubbed, tmp_path) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps({"tasks": {"sample_prompt": {"active": "v1"}}}), encoding="utf-8"
    )
    (tmp_path / "tasks" / "sample_prompt" / "v1").mkdir(parents=True)

    with pytest.raises(PromptRegistryError, match="No such file"):
        assembly.build_real(stubbed.overlay(prompt={"registry": str(registry_path)}))


@pytest.mark.parametrize("missing", ["world_server_url", "memory_server_url"])
def test_a_missing_service_address_fails_at_assembly(stubbed, missing) -> None:
    services = {"world_server_url": "http://w", "memory_server_url": "http://m", missing: None}

    with pytest.raises(McpTransportError):
        assembly.build_real(stubbed.overlay(services=services))
