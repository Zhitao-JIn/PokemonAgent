"""治疗起点实际受伤才能打包；夹具生成仅改变 HP，不伪造治疗结果。"""

import pytest
from _doubles.script_frames import frame

from evals.agent_short_goal_run.dataset import load
from evals.agent_short_goal_run.dataset.build.injured_start import injure_first_member
from evals.agent_short_goal_run.dataset.build.preconditions import validate_start
from evals.dataset.errors import DatasetError
from pokemon_agent.world.interface import PartyMon
from pokemon_agent.world.ram import W_PARTY_COUNT, W_PARTY_MON1_HP


def healing_sample():
    return next(s for s in load() if s.check_id == "party_healed")


@pytest.mark.parametrize("hp", [0, 20])
def test_full_health_or_fainted_party_cannot_be_packed_as_a_healing_start(hp):
    ram = frame()[1].model_copy(
        update={"party": [PartyMon(species=1, level=5, hp=hp, max_hp=20, status="ok")]}
    )

    with pytest.raises(DatasetError, match="存活且受伤"):
        validate_start(healing_sample(), ram)


def test_injured_party_is_a_valid_healing_start():
    ram = frame()[1].model_copy(
        update={"party": [PartyMon(species=1, level=5, hp=10, max_hp=20, status="ok")]}
    )

    validate_start(healing_sample(), ram)


def test_injury_changes_only_the_hp_bytes():
    memory = bytearray(65536)
    memory[W_PARTY_COUNT] = 1
    memory[W_PARTY_MON1_HP + 1] = 20
    memory[W_PARTY_MON1_HP + 0x22] = 20
    before = bytes(memory)

    injure_first_member(memory)

    assert memory[W_PARTY_MON1_HP + 1] == 10
    assert [i for i, (old, new) in enumerate(zip(before, memory, strict=True)) if old != new] == [
        W_PARTY_MON1_HP + 1
    ]
