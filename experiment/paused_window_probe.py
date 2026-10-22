"""真实 PyBoy 暂停与按键探针。

运行：`uv run --project . python -m experiment.paused_window_probe`。
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from pokemon_agent.world import PyBoyWorld
from pokemon_agent.world.pyboy_world import GB_FPS


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证暂停时 PyBoy 窗口响应并按键推进")
    parser.add_argument("--rom", type=Path, default=Path("assets/rom"))
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("experiment/experiment_states/knowledge/knowledge_wild_encounter.state"),
    )
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--interval", type=float, default=0.05)
    parser.add_argument("--pause-seconds", type=float, default=0.5)
    return parser.parse_args()


def _pause_and_refresh(world: PyBoyWorld, seconds: float, interval: float) -> None:
    frame = world._pyboy.frame_count
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not world._closed:
        world._pump_idle_window()
        current_frame = world._pyboy.frame_count
        if current_frame != frame:
            raise RuntimeError(f"暂停期间帧号变化：{frame} -> {current_frame}")
        time.sleep(interval)


def _press_and_verify(world: PyBoyWorld, direction: str) -> bool:
    before = world._pyboy.frame_count
    world.step([(direction, 1)], settle=False)
    after = world._pyboy.frame_count
    if world._closed:
        print(f"窗口关闭事件中断 {direction}：帧 {before} -> {after}。", flush=True)
        return False
    if after != before + GB_FPS:
        raise RuntimeError(f"{direction} 应推进 {GB_FPS} 帧，实际从 {before} 到 {after}")
    print(f"按键 {direction}：帧 {before} -> {after}（推进 {GB_FPS} 帧）。", flush=True)
    return True


def _run_probe(world: PyBoyWorld, seconds: float, interval: float, pause_seconds: float) -> None:
    deadline = time.monotonic() + seconds
    print("探针运行中：左右交替各推进 60 帧，间隔暂停并刷新窗口。", flush=True)
    while time.monotonic() < deadline and not world._closed:
        for direction in ("left", "right"):
            if time.monotonic() >= deadline or world._closed:
                break
            if not _press_and_verify(world, direction):
                break
            _pause_and_refresh(world, pause_seconds, interval)
    print("PyBoy 窗口已关闭，探针结束。" if world._closed else "按键与暂停循环结束。", flush=True)


def main() -> None:
    arguments = _arguments()
    world = PyBoyWorld(
        str(arguments.rom), state_path=str(arguments.state_file), watch=True, speed=1
    )
    try:
        world.reset(
            task_id="paused-window-probe",
            goal="验证空闲暂停期间的窗口响应。",
            success_criteria="游戏帧保持不变且窗口持续刷新。",
            max_steps=1,
        )
        _run_probe(world, arguments.seconds, arguments.interval, arguments.pause_seconds)
    finally:
        world._pyboy.stop(save=False)


if __name__ == "__main__":
    main()
