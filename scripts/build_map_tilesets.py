"""从英文红版 ROM 地图头生成运行时静态 tileset 表，不采集模拟器状态。"""

import argparse
import json
from pathlib import Path

MAP_POINTERS = 0x01AE
MAP_BANKS = 0xC23D
MAP_COUNT = 248
BANK_SIZE = 0x4000


def build_table(rom: bytes) -> dict[str, int]:
    """返回各地图头首字节；ROM 地址无效时失败，调用方须提供英文红版 ROM。"""
    result: dict[str, int] = {}
    for map_id in range(MAP_COUNT):
        offset = MAP_POINTERS + map_id * 2
        pointer = int.from_bytes(rom[offset : offset + 2], "little")
        bank = rom[MAP_BANKS + map_id]
        address = bank * BANK_SIZE + pointer - BANK_SIZE
        if not BANK_SIZE <= pointer < BANK_SIZE * 2 or not 0 <= address < len(rom):
            raise ValueError(f"invalid map header: {map_id}")
        result[str(map_id)] = rom[address]
    return result


def main() -> None:
    """生成表到显式输出路径；不修改 ROM。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=Path("assets/rom"))
    parser.add_argument(
        "--output", type=Path, default=Path("pokemon_agent/world/tables/map_tilesets.json")
    )
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(build_table(args.rom.read_bytes()), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
