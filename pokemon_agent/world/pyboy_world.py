"""`WorldPort` 的唯一实现：PyBoy 模拟器与内存观测。"""

from __future__ import annotations

import io
import pathlib
from dataclasses import dataclass

from pyboy import PyBoy

from .action_space import ALL_BUTTONS, compute_action_space
from .interface import (
    OVERLAY_ACTIONS,
    ActionSpace,
    TaskPerceived,
)
from .ram import map_settled, read_terrain
from .screen_text import read_screen_text
from .task_perception import observe_task


@dataclass
class _Task:
    """`reset()`/`set_task()` 收到的裸字段，攒成一个内部记账用的小结构。"""

    task_id: str
    goal: str
    success_criteria: str
    max_steps: int
    initial_state_hint: str = ""


assert {b for buttons in OVERLAY_ACTIONS.values() for b in buttons} <= set(ALL_BUTTONS), (
    "OVERLAY_ACTIONS references a button that the world cannot execute"
)

GB_FPS = 60  # Game Boy 大约每秒 60 帧；下面几个常量都按这个换算成秒
PRESS_FRAMES = 10  # 按键按住多少帧
BOOT_FRAMES = 10 * GB_FPS  # 无存档时空转多少帧越过开机 logo


class PyBoyWorld:
    """真实的宝可梦红世界。"""

    def __init__(
        self,
        rom: str,
        *,
        state_path: str | None = None,
        watch: bool = False,
        speed: int = 0,
    ) -> None:
        """构造模拟器；ROM 或显式存档不存在时失败。"""
        if state_path and not pathlib.Path(state_path).is_file():
            raise FileNotFoundError(
                f"找不到存档 {state_path}。传 state_path=None 从开机跑起，"
                "或者用实验入口跑一局让它存下起点存档。"
            )
        if not pathlib.Path(rom).is_file():
            raise FileNotFoundError(f"找不到 ROM {rom}")

        self._pyboy = PyBoy(
            rom,
            window="SDL2" if watch else "null",
            scale=4,
            no_input=True,
        )
        self._watch = watch
        self._pyboy.set_emulation_speed(speed)
        self._state_path = state_path
        self._rom = pathlib.Path(rom).read_bytes()
        """ROM 原样：脚本与接管视图从里面读道具价格这类常量表。"""

        self._task: _Task | None = None
        self._closed = False
        self._idle_paused = False
        """窗口被关了。**这是 world 唯一有资格宣告的终止**——世界没了，跑不下去。"""

    # ---- WorldPort ----

    def reset(
        self,
        *,
        task_id: str,
        goal: str,
        success_criteria: str,
        max_steps: int,
        initial_state_hint: str = "",
        start_state: bytes | None = None,
    ) -> None:
        """按任务重置，不感知；起点优先级为 start_state、state_path、开机。

        前置条件：max_steps > 0；start_state 非 None 时必须非空。
        字节起点与文件起点读档后都推进一帧；不指定字节时保留原行为。
        """
        assert max_steps > 0, f"max_steps must be > 0, got {max_steps}"

        # 步骤 1。
        if start_state is not None:
            assert start_state, "reset() got empty start_state"
            self._pyboy.load_state(io.BytesIO(start_state))
            self._tick(1)
        elif self._state_path:
            with open(self._state_path, "rb") as f:
                self._pyboy.load_state(f)
            self._tick(1)
        else:
            self._tick(BOOT_FRAMES)

        # 步骤 2。
        self._task = _Task(task_id, goal, success_criteria, max_steps, initial_state_hint)
        self._closed = False

    def save_state(self) -> bytes:
        """模拟器完整状态 → 字节串（`pyboy.save_state`）。不推进世界。"""
        buf = io.BytesIO()
        self._pyboy.save_state(buf)
        data = buf.getvalue()
        assert data, "pyboy.save_state produced no bytes"
        return data

    def read_wram(self) -> bytes:
        """数据集冻结用的只读口：返回 0xC000–0xDFFF，不推进世界。

        后置条件：返回恰好 8192 字节，否则断言失败。
        """
        data = bytes(self._pyboy.memory[0xC000:0xE000])
        assert len(data) == 8192, "read_wram() must return 8192 bytes"
        return data

    def load_state(self, data: bytes) -> None:
        """字节串 → 模拟器完整状态（`pyboy.load_state`）。**读档后不 tick**。"""
        assert data, "load_state() got empty bytes"
        self._pyboy.load_state(io.BytesIO(data))

    def get_action_space(self) -> ActionSpace:
        """按当前这一帧算能力掩码（纯函数委托，见 `world/action_space.py`）。"""
        assert self._task is not None, "get_action_space() before reset()"
        observation = self.perceive_task().observation
        return compute_action_space(observation, list(ALL_BUTTONS))

    def all_actions(self) -> list[str]:
        """全部动作名，与状态无关。掩码是 harness 的事，不在这里做。"""
        return list(ALL_BUTTONS)

    def step(self, segments: list[tuple[str, int]], *, settle: bool = True) -> None:
        """按动作段执行按键；等待由调用方统一处理。"""
        assert self._task is not None, "step() before reset()"
        assert not self._closed, "step() called after the window was closed"

        # 步骤 1。
        for name, _times in segments:
            assert name in ALL_BUTTONS, f"unknown action {name!r}"

        # 步骤 2：依次执行各动作段。
        for name, times in segments:
            for _ in range(times):
                self._pyboy.button(name, delay=PRESS_FRAMES)

    def perceive_task(self) -> TaskPerceived:
        """task 层的一帧：**不问模型**，只读内存与屏幕缓冲（`task_perception.observe_task`）。"""
        assert self._task is not None, "perceive_task() before reset()"
        png = self._frame_png()
        memory = self._pyboy.memory
        terrain = read_terrain(memory) if map_settled(memory) else None
        return observe_task(
            terrain,
            read_screen_text(memory),
            png,
            memory=memory,
            rom=self._rom,
            closed=self._closed,
        )

    # ---- 内部 ----

    def _tick(self, frames: int) -> None:
        """逐帧推进；窗口关闭时标记 closed 并停止。"""
        if frames and self._idle_paused:
            from pyboy.utils import WindowEvent

            self._pyboy.send_input(WindowEvent.UNPAUSE)
            self._idle_paused = False
        for _ in range(frames):
            self._pump_window_events()
            if not self._pyboy.tick(1):
                self._closed = True  # 窗口被关，世界没了——这是 world 唯一的终止权
                return

    def _pump_idle_window(self) -> None:
        """暂停游戏帧时调用 PyBoy tick，让窗口插件处理消息并刷新。"""
        if not self._watch or self._closed:
            return

        from pyboy.utils import WindowEvent

        self._pump_window_events()
        if not self._idle_paused:
            self._pyboy.send_input(WindowEvent.PAUSE)
            self._idle_paused = True
        self._pyboy.send_input(WindowEvent._INTERNAL_RENDERER_FLUSH)
        if not self._pyboy.tick(1):
            self._closed = True

    def _pump_window_events(self) -> None:
        """处理 SDL 系统事件并丢弃物理按键，维持可视窗口刷新。"""
        if not self._watch:
            return

        import ctypes

        import sdl2
        from pyboy.utils import WindowEvent

        event = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            if event.type == sdl2.SDL_QUIT or (
                event.type == sdl2.SDL_WINDOWEVENT
                and event.window.event == sdl2.SDL_WINDOWEVENT_CLOSE
            ):
                self._pyboy.send_input(WindowEvent.QUIT)

    def _frame_png(self) -> bytes:
        """把当前画面截成 PNG 字节。"""
        import io

        buf = io.BytesIO()
        self._pyboy.screen.image.save(buf, format="PNG")
        return buf.getvalue()

    def stop(self) -> None:
        """关掉模拟器。"""
        self._pyboy.stop()

    def evolve(self, frames: int) -> None:
        """无输入推进 N 帧——世界自己演化（音乐、动画、NPC 走动），不感知。"""
        assert frames >= 0, f"evolve() got negative frames: {frames}"
        self._tick(frames)
