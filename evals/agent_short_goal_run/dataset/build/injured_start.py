"""离线生成治疗用例的受伤起点；只修改首只宝可梦的 HP，不推进游戏。"""

from pathlib import Path

from pokemon_agent.world.ram import W_PARTY_MON1_HP
from pokemon_agent.world.readout import read_party

from .writable_memory import WritableMemory


def injure_first_member(memory: WritableMemory) -> None:
    """首只 HP 改为最大 HP 的一半；空队伍、濒死或无效最大 HP 显式拒绝。"""
    party = read_party(memory)
    if not party or party[0].max_hp < 2 or party[0].hp == 0:
        raise ValueError("治疗起点必须有存活且最大 HP 至少为 2 的首只宝可梦")
    hp = max(1, party[0].max_hp // 2)
    memory[W_PARTY_MON1_HP] = hp >> 8
    memory[W_PARTY_MON1_HP + 1] = hp & 0xFF


def write_injured_start(rom: Path, source: Path, target: Path) -> None:
    """读独立模拟器、保存新文件；输出已存在时拒绝覆盖原始存档。"""
    from pyboy import PyBoy

    if target.exists():
        raise FileExistsError(target)
    emulator = PyBoy(str(rom), window="null", sound_emulated=False)
    try:
        with source.open("rb") as stream:
            emulator.load_state(stream)
        injure_first_member(emulator.memory)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            emulator.save_state(stream)
    finally:
        emulator.stop(save=False)
