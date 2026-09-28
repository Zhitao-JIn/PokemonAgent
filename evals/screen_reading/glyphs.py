"""截图 → 屏幕缓冲：Game Boy 一格 8×8 像素就是一个 tile，逐块与字形库精确比对就能还原 tile id。

字形库直接从 VRAM 解（2bpp 图块按 BGP 调色板转明暗级），图样按"明暗级首次出现的顺序"重新编号
（`_canonical`），这样招式动画改了调色板（反色、变暗）的帧也认得出；招式动画还会让整屏抖动，
所以 8×8 网格的起点在 0–7 像素里逐个试，取命中非空白块最多的那个。
不同界面载入的图块不同（野外 / 队伍列表 / 能力页 / 训练家卡片 / 战斗），各存一份；
还原时挑命中块数最多的那份。只收 0x60–0xFF（文字、边框、
HUD 图块），其余一律当 0x00（非文字）。0926 在 45 帧真缓冲上核过：44 帧解码字段逐项一致，
唯一不同的是对话逐字打出时截图比缓冲慢一帧（截图才是屏幕上真显示的）。
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image

TEXT_TILES = range(0x60, 0x100)
SHADE_OF_RGB: dict[tuple[int, int, int], int] = {
    (255, 255, 255): 0,
    (153, 153, 153): 1,
    (85, 85, 85): 2,
    (0, 0, 0): 3,
}
"""PyBoy 默认调色板的四级明暗。"""

CONTEXTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "field": ("knowledge_shop_confirm_purchase", ()),
    "party": ("knowledge_movement_obstacle", ("start", "a")),
    "stats": ("knowledge_movement_obstacle", ("start", "a", "a", "a")),
    "card": ("knowledge_movement_obstacle", ("start", "down", "down", "a")),
    "battle": ("knowledge_battle_action_menu", ()),
}
"""字形库的取样场景：存档名（`experiment_states/knowledge/`）+ 进场按键。"""

Library = dict[str, int]
"""8×8 明暗图样（hex）→ tile id。"""

HUD_TILES = frozenset(range(0x62, 0x79))
HUD_CONTEXTS = frozenset({"party", "stats", "battle"})
"""等级 / 血条 / HUD 框线图块只在这几种界面里真的是 HUD；别的界面里同一块图样是地图图块，不认。"""


def build_libraries(rom: Path, states_dir: Path) -> dict[str, Library]:
    """按 `CONTEXTS` 逐个开模拟器取字形库。前置条件：ROM 与存档都在。"""
    from pyboy import PyBoy

    libraries: dict[str, Library] = {}
    for name, (state, keys) in CONTEXTS.items():
        pb = PyBoy(str(rom), window="null", sound_emulated=False)
        with open(states_dir / f"{state}.state", "rb") as f:
            pb.load_state(f)
        pb.tick(5)
        for key in keys:
            pb.button(key, 3)
            pb.tick(80)
        mem, bgp = pb.memory, pb.memory[0xFF47]
        library: Library = {}
        for tile in TEXT_TILES:
            library.setdefault(_canonical(_tile_shades(mem, tile, bgp)), tile)
        libraries[name] = library
        pb.stop(save=False)
    return libraries


def _tile_shades(mem: object, tile: int, bgp: int) -> np.ndarray:
    """VRAM 里一个 BG 图块的 8×8 明暗级（LCDC.4=0：0x80 起在 0x8800，0x00–0x7F 在 0x9000）。"""
    base = 0x8000 + tile * 16 if tile >= 0x80 else 0x9000 + tile * 16
    out = np.zeros((8, 8), dtype=np.uint8)
    for y in range(8):
        lo, hi = mem[base + 2 * y], mem[base + 2 * y + 1]  # type: ignore[index]
        for x in range(8):
            bit = 7 - x
            color = ((hi >> bit) & 1) << 1 | ((lo >> bit) & 1)
            out[y, x] = (bgp >> (2 * color)) & 3
    return out


def _canonical(block: np.ndarray) -> str:
    """8×8 明暗块按首次出现顺序重编号后的 hex：同形不同色的块得到同一个键。"""
    order: dict[int, int] = {}
    flat = [order.setdefault(int(v), len(order)) for v in block.reshape(-1)]
    return bytes(flat).hex()


def reconstruct(frame_png: str, libraries: dict[str, Library]) -> list[list[int]]:
    """截图（data URI）→ 18 × 20 tile id。认不出的块给 0x00。"""
    raw = base64.b64decode(frame_png.split(",", 1)[1])
    rgb = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
    assert rgb.shape == (144, 160, 3), f"不是原尺寸的 Game Boy 截图：{rgb.shape}"
    shades = np.zeros((144, 160), dtype=np.uint8)
    for color, shade in SHADE_OF_RGB.items():
        shades[np.all(rgb == color, axis=2)] = shade
    padded = np.zeros((152, 168), dtype=np.uint8)
    padded[:144, :160] = shades
    blank = _canonical(np.zeros((8, 8), dtype=np.uint8))
    best_hits, best_tiles = -1, [[0x00] * 20 for _ in range(18)]
    for dy in range(8):
        for dx in range(8):
            patterns = [
                [
                    _canonical(padded[dy + r * 8 : dy + r * 8 + 8, dx + c * 8 : dx + c * 8 + 8])
                    for c in range(20)
                ]
                for r in range(18)
            ]
            for name, lib in libraries.items():
                hits = sum(p in lib and p != blank for row in patterns for p in row)
                if hits > best_hits:
                    best_hits = hits
                    best_tiles = [
                        [_accept(lib.get(p, 0x00), name) for p in row] for row in patterns
                    ]
    # 步骤：一个字都没有的帧（走路）里，HUD 图样只可能是地图图块碰巧同形，一律当非文字。
    letters = {t for t in range(0x80, 0xC0)} | {t for t in range(0xF6, 0x100)}
    if not any(t in letters for row in best_tiles for t in row):
        best_tiles = [[0x00 if t in HUD_TILES else t for t in row] for row in best_tiles]
    return best_tiles


def _accept(tile: int, context: str) -> int:
    """HUD 图块只在 HUD 界面里收，别处当非文字。"""
    return 0x00 if tile in HUD_TILES and context not in HUD_CONTEXTS else tile


__all__ = ["CONTEXTS", "Library", "build_libraries", "reconstruct"]
