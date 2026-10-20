"""冻结数据集的读取用法、版本边界与声明式状态核对。"""

import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from evals.dataset.errors import DatasetError
from evals.dataset.io import contained_file
from evals.world_script_execute.compare.checks import check_declaration
from evals.world_script_execute.dataset import ScriptCheck
from pokemon_agent.world import Facts, TaskObservation, TaskScene
from pokemon_agent.world.interface.domain.takeover_view import (
    BagEntry,
    BattleMenuView,
    BoxEntry,
    MonEntry,
    MoveEntry,
    PartyView,
    PcView,
    ShopItemsView,
)


@pytest.mark.parametrize(
    "name,count",
    [
        ("frames", 1045),
        ("agent_short_goal_run", 20),
        ("world_script_execute", 106),
        ("memory_store_recall", 1),
        ("brain_goal_judge", 4),
    ],
)
def test_each_dataset_returns_frozen_typed_samples(name, count):
    modules = {
        "memory_store_recall": "evals.memory_store_recall.dataset",
        "world_script_execute": "evals.world_script_execute.dataset",
        "brain_goal_judge": "evals.dataset.brain_goal_judge",
        "agent_short_goal_run": "evals.agent_short_goal_run.dataset",
    }
    dataset = importlib.import_module(modules.get(name, f"evals.dataset.{name}"))

    rows = dataset.load()

    assert len(rows) == count
    assert all(isinstance(row, BaseModel) for row in rows)
    assert "load" in dataset.__all__


def test_frame_dataset_import_does_not_load_build_tools_or_pyboy():
    code = "import sys; import evals.dataset.frames; assert 'pyboy' not in sys.modules; "
    code += "assert not any(n.startswith('evals.dataset.frames.build') for n in sys.modules)"

    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


def test_referenced_archives_and_states_stay_inside_the_dataset_version():
    from evals.agent_short_goal_run.dataset import load as load_agent
    from evals.agent_short_goal_run.dataset.loader import DATASET_DIR as AGENT_ROOT
    from evals.world_script_execute.dataset import load as load_world
    from evals.world_script_execute.dataset.loader import state_path

    for sample in load_agent():
        version = AGENT_ROOT / sample.dataset_version
        contained_file(version, sample.start.source_state)
        manifest = contained_file(version, f"archives/{sample.start.archive}/manifest.json")
        references = json.loads(manifest.read_text("utf-8"))
        contained_file(version, references["memory_archive"])
        contained_file(manifest.parent, references["world_file"])
    for case in load_world():
        assert state_path(case.state).is_file()


@pytest.mark.parametrize("reference", ["../outside.state", "missing.state"])
def test_invalid_frozen_file_references_raise_dataset_error(tmp_path, reference):
    with pytest.raises(DatasetError):
        contained_file(tmp_path, reference)


def test_duplicate_truth_is_a_named_dataset_failure(tmp_path, monkeypatch):
    from evals.dataset.frames import loader
    from evals.dataset.frames.schemas import FrameTruth

    truth = FrameTruth(sample_id="demo", labeler="human", note="demonstration")
    path = tmp_path / "truth.jsonl"
    path.write_text((truth.model_dump_json() + "\n") * 2, "utf-8")
    monkeypatch.setattr(loader, "TRUTH_FILE", path)

    with pytest.raises(DatasetError, match="重复"):
        loader.load_truth()


def test_changed_source_state_fails_the_frozen_hash_check(tmp_path, monkeypatch):
    from evals.agent_short_goal_run.dataset import loader

    shutil.copytree(loader.DATASET_DIR / "v1", tmp_path / "v1")
    sample = loader.load()[0]
    (tmp_path / "v1" / sample.start.source_state).write_bytes(b"changed")
    monkeypatch.setattr(loader, "DATASET_DIR", tmp_path)

    with pytest.raises(DatasetError, match="哈希"):
        loader.load()


def test_archive_adapter_preserves_frozen_manifest_and_resolves_its_paths(tmp_path):
    from evals.agent_short_goal_run.dataset import load
    from evals.agent_short_goal_run.dataset.loader import DATASET_DIR
    from evals.agent_short_goal_run.solver.runner.archive import prepare_archive

    sample = load()[0]
    source = DATASET_DIR / "v1" / "archives" / sample.start.archive / "manifest.json"
    frozen = source.read_bytes()

    manifest = json.loads(prepare_archive(sample, tmp_path).read_text("utf-8"))

    assert source.read_bytes() == frozen
    assert Path(manifest["memory_archive"]).is_absolute()
    assert Path(manifest["world_file"]).is_file()


def observation(view=None, scene=TaskScene.WALK, **facts):
    return TaskObservation(step=0, status="", scene=scene, facts=Facts(**facts), takeover=view)


def mon(name, hp=10, moves=()):
    return MonEntry(name=name, level=5, hp=hp, max_hp=10, moves=list(moves))


def shop(money, quantity):
    return observation(ShopItemsView(money=money, bag=[BagEntry(name="POTION", quantity=quantity)]))


def pc(quantity, size):
    return observation(
        PcView(
            box_number=1,
            items=[BagEntry(name="POTION", quantity=quantity)],
            box=[BoxEntry(name="A", level=5)] * size,
        )
    )


def battle(mine, hp):
    return observation(BattleMenuView(mine=mine, foe=mon("FOE", hp)))


def party(members):
    return observation(PartyView(party=members))


a, b = mon("A"), mon("B")
CHECK_EXAMPLES = [
    ("money", {"delta": -10}, shop(100, 2), shop(90, 2), shop(100, 2)),
    ("bag", {"item": "POTION", "delta": -1}, shop(100, 2), shop(100, 1), shop(100, 2)),
    (
        "scene",
        {"scene": "dialog"},
        observation(),
        observation(scene=TaskScene.DIALOG),
        observation(),
    ),
    (
        "left",
        {"scene": "dialog"},
        observation(),
        observation(),
        observation(scene=TaskScene.DIALOG),
    ),
    (
        "battle_start",
        {},
        observation(),
        observation(scene=TaskScene.BATTLE_MENU, cursor="FIGHT"),
        observation(),
    ),
    ("in_play", {"name": "B"}, battle(a, 10), battle(b, 10), battle(a, 10)),
    ("foe_hurt", {}, battle(a, 10), battle(a, 9), battle(a, 10)),
    ("shop_start", {}, observation(), observation(screen="BUY ▶"), observation(screen="BUY ▷")),
    ("pc", {"item": "POTION", "delta": -1}, pc(2, 1), pc(1, 1), pc(2, 1)),
    ("order", {"names": ["B", "A"]}, party([a, b]), party([b, a]), party([a, b])),
    ("box", {"delta": 1}, pc(2, 1), pc(2, 2), pc(2, 1)),
    (
        "knows",
        {"pokemon": "A", "move": "TACKLE", "yes": True},
        party([a]),
        party([mon("A", moves=[MoveEntry(name="TACKLE", pp=10)])]),
        party([a]),
    ),
]


@pytest.mark.parametrize("kind,args,before,positive,negative", CHECK_EXAMPLES)
def test_each_declarative_check_accepts_progress_and_rejects_the_wrong_state(
    kind,
    args,
    before,
    positive,
    negative,
):
    check = ScriptCheck(kind=kind, args=args)

    passed = check_declaration(check, before, positive)
    failed = check_declaration(check, before, negative)

    assert passed == ""
    assert failed


def test_frame_build_can_create_a_new_version_without_changing_the_frozen_source(
    tmp_path, monkeypatch
):
    from evals.dataset.frames import loader
    from evals.dataset.frames.build import storage

    sample = next(frame for frame in loader.load() if frame.terrain_truth)
    original = (loader.DATASET_DIR / "v2" / "samples.jsonl").read_bytes()
    monkeypatch.setattr(storage, "DATASET_DIR", tmp_path)

    storage.save_frames([sample], version="v3", replace_sources=[sample.source])

    assert (loader.DATASET_DIR / "v2" / "samples.jsonl").read_bytes() == original
    monkeypatch.setattr(loader, "DATASET_DIR", tmp_path)
    assert loader.load("v3")[0].model_dump() == sample.model_dump()


@pytest.mark.parametrize(
    "name",
    [
        "agent_short_goal_run",
    ],
)
def test_remaining_inspect_tasks_assemble_from_the_public_dataset_exports(name, tmp_path):
    from inspect_ai import Task

    module = importlib.import_module(f"evals.{name}.task")
    is_agent = name == "agent_short_goal_run"
    options = {"log_dir": str(tmp_path), "grader_model": None} if is_agent else {}

    task = getattr(module, name)(**options)

    assert isinstance(task, Task)
    assert len(task.dataset) > 0
