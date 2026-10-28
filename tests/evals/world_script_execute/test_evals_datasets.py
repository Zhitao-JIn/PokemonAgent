"""冻结数据集的读取用法、版本边界与声明式状态核对。"""

import importlib
import json
import shutil
import subprocess
import sys

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
        ("world_script_execute", 93),
        ("memory_store_recall", 1),
        pytest.param(
            "brain_judge",
            4,
            marks=pytest.mark.skip(reason="D33: 冻结旧格式数据，待新框架重新生成后取消跳过"),
        ),
    ],
)
def test_each_dataset_returns_frozen_typed_samples(name, count):
    modules = {
        "memory_store_recall": "evals.memory_store_recall.dataset",
        "world_script_execute": "evals.world_script_execute.dataset",
        "brain_judge": "evals.dataset.brain_judge",
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


def test_source_states_stay_inside_the_dataset_version_and_match_their_hashes():
    from evals.agent_short_goal_run.dataset import load as load_agent
    from evals.agent_short_goal_run.dataset.loader import DATASET_DIR as AGENT_ROOT
    from evals.agent_short_goal_run.dataset.loader import sha256_of
    from evals.world_script_execute.dataset import load as load_world
    from evals.world_script_execute.dataset.loader import state_path

    for sample in load_agent():
        version = AGENT_ROOT / sample.dataset_version
        source = contained_file(version, sample.start.source_state)
        assert source.is_relative_to(version.resolve())
        assert sha256_of(source) == sample.start.source_sha256
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


def test_missing_source_state_fails_the_frozen_file_check(tmp_path, monkeypatch):
    from evals.agent_short_goal_run.dataset import loader

    shutil.copytree(loader.DATASET_DIR / "v1", tmp_path / "v1")
    sample = loader.load()[0]
    (tmp_path / "v1" / sample.start.source_state).unlink()
    monkeypatch.setattr(loader, "DATASET_DIR", tmp_path)

    with pytest.raises(DatasetError, match="缺失"):
        loader.load()


def test_archive_marker_and_state_kind_ignore_archive_directory(tmp_path, monkeypatch):
    from evals.agent_short_goal_run.dataset import loader

    shutil.copytree(loader.DATASET_DIR / "v1", tmp_path / "v1")
    samples_path = tmp_path / "v1" / "samples.jsonl"
    rows = [json.loads(line) for line in samples_path.read_text("utf-8").splitlines()]
    rows[0]["start"]["archive"] = "archive-does-not-exist"
    rows[1]["start"]["kind"] = "state"
    rows[1]["start"].pop("archive")
    samples_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", "utf-8")
    monkeypatch.setattr(loader, "DATASET_DIR", tmp_path)

    loaded = loader.load()

    assert loaded[0].start.kind == "archive"
    assert loaded[0].start.archive == "archive-does-not-exist"
    assert loaded[1].start.kind == "state"
    assert loaded[1].start.archive == ""


def test_sample_source_state_is_required():
    from pydantic import ValidationError

    from evals.agent_short_goal_run.dataset.schemas import SampleStart

    with pytest.raises(ValidationError):
        SampleStart(kind="archive", source_sha256="abc")

    start = SampleStart(kind="state", source_state="sample.state", source_sha256="abc")
    assert start.archive == ""


def observation(view=None, scene=TaskScene.WALK, **facts):
    return TaskObservation(step=0, scene=scene, facts=Facts(**facts), takeover=view)


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
