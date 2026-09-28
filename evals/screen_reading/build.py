"""造数据集 v1：observation_check 406 帧（截图还原缓冲）+ 0926 探测 45 帧（存档实采）。

一次性：要 ROM（`assets/rom`，不进 git）与 `experiment_states/knowledge/*.state`；产物
`dataset/v1/samples.jsonl` 与字形库 `dataset/v1/glyphs.json` 冻结进仓库，跑测评不再要 ROM。
"""

from __future__ import annotations

import base64
import io
import json
import zlib
from pathlib import Path

from .glyphs import build_libraries, reconstruct
from .schemas import ScreenLabel, ScreenSample

DATASET_DIR = Path(__file__).resolve().parent / "dataset"
REPO_ROOT = DATASET_DIR.parents[2]
ROM = REPO_ROOT / "assets" / "rom"
STATES = REPO_ROOT / "experiment" / "experiment_states" / "knowledge"
OBSERVATION_CHECK = (
    REPO_ROOT
    / "experiment"
    / "observation_check"
    / "captures"
    / "manual-20260918-143419"
    / "manifest.jsonl"
)
PROBE_BAG = [(0x14, 3), (0x04, 5), (0x05, 1), (0x0B, 2), (0x0F, 1), (0x10, 4), (0x1D, 6), (0x13, 2)]
"""0926 探测里塞进背包的 8 样东西（测翻页用）。"""


def build(version: str = "v1") -> Path:
    """重造数据集，返回 `samples.jsonl` 路径。"""
    out_dir = DATASET_DIR / version
    libraries = build_libraries(ROM, STATES)
    (out_dir / "glyphs.json").write_text(json.dumps(libraries), encoding="utf-8")
    samples = _from_observation_check(libraries) + _from_probe(out_dir / "probe_0926.json")
    path = out_dir / "samples.jsonl"
    path.write_text("".join(s.model_dump_json() + "\n" for s in samples), encoding="utf-8")
    return path


def build_v2(capture_dir: Path, version: str = "v2") -> Path:
    """数据集 v2：一次人工采集（每帧存了真屏幕缓冲与整块 WRAM）+ 0926 探测 45 帧。

    标注由规则与内存预标。

    预标只是起点（`label_checked=False`），要在核对页上人工校过才算数。
    """
    out_dir = DATASET_DIR / version
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = _from_capture(capture_dir) + _from_probe(DATASET_DIR / "v1" / "probe_0926.json")
    samples = [
        s.model_copy(update={"label": _prelabel_probe(s)}) if s.source == "probe_0926" else s
        for s in samples
    ]
    path = out_dir / "samples.jsonl"
    path.write_text("".join(s.model_dump_json() + "\n" for s in samples), encoding="utf-8")
    return path


def _from_capture(capture_dir: Path) -> list[ScreenSample]:
    """采集目录里的 `manifest.jsonl`：一帧一条，缓冲与 WRAM 都是真的。"""
    samples = []
    for line in (capture_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        tiles = list(bytes.fromhex(row["tilemap_hex"]))
        sample = ScreenSample(
            sample_id=f"c-{row['seq']:04d}",
            source="capture_0926",
            category="",
            in_battle=bool(row.get("is_in_battle")),
            tiles=[tiles[r * 20 : r * 20 + 20] for r in range(18)],
            frame_png=row["frame_png"],
            label=ScreenLabel(overlay="none"),
            note=row.get("map_name") or "",
            wram=row["wram_zlib_b64"],
        )
        samples.append(sample.model_copy(update={"label": prelabel(sample)}))
    return samples


def prelabel(sample: ScreenSample) -> ScreenLabel:
    """预标：界面种类用规则原型，字段用屏幕解码；队伍列表用内存补（解码切不出来）。

    数量框都在宏里（买卖、PC 存取丢、背包丢弃），不标数量。
    """
    from .observe import scene_of, screen_text

    text = screen_text(sample)
    ram = wram_bytes(sample)
    scene, start = scene_of(text, ram)
    label = ScreenLabel(
        scene=scene,
        at_start=start,
        overlay=_overlay_value(text),
        dialog_text=text.dialog_text,
        options=text.options,
        cursor=text.cursor,
    )
    party_list = text.has_cursor and not text.options and ":L" in text.screen
    if ram and party_list:
        count = ram[0xD163 - 0xC000]
        names = [_name(ram, 0xD2B5 + 11 * i) for i in range(min(count, 6))]
        current = ram[0xCC26 - 0xC000]
        label = label.model_copy(
            update={"options": names, "cursor": names[current] if current < len(names) else ""}
        )
    return label


def _prelabel_probe(sample: ScreenSample) -> ScreenLabel:
    """0926 探测帧已有人工标注：只补上界面种类与是否在初态（规则预标）。"""
    from .observe import scene_of, screen_text

    text, ram = screen_text(sample), wram_bytes(sample)
    scene, start = scene_of(text, ram)
    return sample.label.model_copy(update={"scene": scene, "at_start": start})


def _overlay_value(text: object) -> str:
    """叠加层（与 task 层同一条规则）。"""
    from pokemon_agent.world.pyboy_world import _overlay_of

    return _overlay_of(text).value  # type: ignore[arg-type]


def wram_bytes(sample: ScreenSample) -> bytes:
    """样本存的整块 WRAM（0xC000 起）；没有时为空。"""
    return zlib.decompress(base64.b64decode(sample.wram)) if sample.wram else b""


def _name(ram: bytes, address: int) -> str:
    """WRAM 里 0x50 结尾的名字。"""
    from pokemon_agent.world.screen_text import CHARMAP

    out = []
    for byte in ram[address - 0xC000 : address - 0xC000 + 11]:
        if byte == 0x50:
            break
        out.append(CHARMAP.get(byte, "?"))
    return "".join(out)


def _from_observation_check(libraries: dict[str, dict[str, int]]) -> list[ScreenSample]:
    """406 帧：缓冲由截图还原，标注取 `claude_label`（看图人工标的）。"""
    samples = []
    for line in OBSERVATION_CHECK.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        label = row["claude_label"]
        samples.append(
            ScreenSample(
                sample_id=f"oc-{row['seq']:03d}",
                source="observation_check",
                category="",
                in_battle=bool(row["is_in_battle"]),
                tiles=reconstruct(row["frame_png"], libraries),
                frame_png=row["frame_png"],
                label=ScreenLabel(
                    overlay=label.get("overlay") or "none",
                    dialog_text=label.get("dialog_text") or "",
                    options=label.get("options") or [],
                    cursor=label.get("cursor") or "",
                ),
            )
        )
    return samples


def _from_probe(spec_path: Path) -> list[ScreenSample]:
    """0926 探测：按场景开存档、按键、在 `@` 处取真缓冲与截图。"""
    from pyboy import PyBoy

    from pokemon_agent.world.screen_text import W_IS_IN_BATTLE, read_tiles

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    samples = []
    for scenario in spec["scenarios"]:
        pb = PyBoy(str(ROM), window="null", sound_emulated=False)
        with open(STATES / f"{scenario['state']}.state", "rb") as f:
            pb.load_state(f)
        pb.tick(1)
        pb.tick(29)
        mem = pb.memory
        if scenario.get("bag"):
            _stuff_bag(mem)
        for step in scenario["steps"]:
            if isinstance(step, int):
                pb.tick(step)
            elif step.startswith("@"):
                sid = step[1:]
                label = spec["labels"][sid]
                samples.append(
                    ScreenSample(
                        sample_id=f"p-{sid}",
                        source="probe_0926",
                        category=label["category"],
                        in_battle=mem[W_IS_IN_BATTLE] != 0,
                        tiles=read_tiles(mem),
                        frame_png=_png(pb),
                        label=ScreenLabel(
                            **{k: label[k] for k in ScreenLabel.model_fields if k in label}
                        ),
                        note=label["note"],
                        label_checked=True,
                        wram=base64.b64encode(
                            zlib.compress(bytes(mem[a] for a in range(0xC000, 0xE000)), 9)
                        ).decode(),
                    )
                )
            else:
                pb.button(step, 3)
                pb.tick(40)
        pb.stop(save=False)
    return samples


def _stuff_bag(mem: object) -> None:
    """背包写满 `PROBE_BAG`。"""
    mem[0xD31D] = len(PROBE_BAG)  # type: ignore[index]
    for i, (item, qty) in enumerate(PROBE_BAG):
        mem[0xD31E + 2 * i] = item  # type: ignore[index]
        mem[0xD31F + 2 * i] = qty  # type: ignore[index]
    mem[0xD31E + 2 * len(PROBE_BAG)] = 0xFF  # type: ignore[index]


def _png(pb: object) -> str:
    """当前画面 → data URI。"""
    buf = io.BytesIO()
    pb.screen.image.convert("RGB").save(buf, "PNG")  # type: ignore[attr-defined]
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def load_samples(version: str = "v1") -> list[ScreenSample]:
    """读冻结的数据集。"""
    path = DATASET_DIR / version / "samples.jsonl"
    return [
        ScreenSample.model_validate_json(x)
        for x in path.read_text(encoding="utf-8").splitlines()
        if x
    ]


__all__ = [
    "DATASET_DIR",
    "REPO_ROOT",
    "build",
    "build_v2",
    "load_samples",
    "prelabel",
    "wram_bytes",
]
