"""脚本执行骨架（server 进程内，随 world 整体拷走）。

**与 `takeover/engine.py` 共用物理量**：接管脚本管"接管场合内的按键序列"，这里管
"跨场合任务链"——`POLL_FRAMES` / `STABLE_POLLS` / `STEP_TIMEOUT_FRAMES`… 从
`takeover.engine` 复用，不另起一套。骨架只提供确定性控制流与事件采集，
**不替调用方做分叉决策**（§6.2 原则：分叉停并上报，决策权回调用方）。

**依赖面**（刻意压到最小，便于进程内/跨进程两种形态共用）：
- `WorldConsole`：脚本看得到的那一小块模拟器（按键 / 推进 / 读屏 / 读内存 / 坐标 /
  当前 map_id）。真机由 `PyBoyWorld` 适配；测试用 `FakeConsole`。
- `classify_scene` / `ScreenText`：纯函数判定场合与读屏事实，不调模型。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..interface import Memory, PlaceInWorld, ScreenText, TaskScene
from ..object_events import judge_press
from ..scene import classify_scene
from .takeover.engine import POLL_FRAMES, STABLE_POLLS, STEP_TIMEOUT_FRAMES

_TABLES = Path(__file__).resolve().parent.parent / "tables"


def _load_table(name: str) -> dict[str, Any]:
    """读取 `world/tables/<name>`（表是数据，缺文件不报错——P4 脚本按需取）。"""
    path = _TABLES / name
    if not path.exists():
        return {}
    import json

    return json.loads(path.read_text(encoding="utf-8"))


# ---- 静态表（P3 建骨架；内容为占位，需真机核对，见各 JSON 的 `_note`）----
WARPS: dict[str, Any] = _load_table("warps.json")
SHOP_LAYOUTS: dict[str, Any] = _load_table("shop_layouts.json")
POKECENTER_LAYOUTS: dict[str, Any] = _load_table("pokecenter_layouts.json")


class WorldConsole(Protocol):
    """脚本看得到的那一小块模拟器（接管脚本 `Console` 的超集）。

    比接管脚本多三样：当前 `map_id`、当前坐标 `pos`、以及稳定的读屏 `read()`——
    脚本判定场合变化 / 换图 / 选项框都靠它们，不另调模型。
    """

    memory: Memory
    rom: bytes

    def press(self, key: str) -> None:
        """按下并按住一小会儿（松开在之后的帧里发生）。"""
        ...

    def tick(self, frames: int) -> None:
        """推进 N 帧。"""
        ...

    def read(self) -> ScreenText:
        """解码这一帧的屏幕缓冲。"""
        ...

    def map_id(self) -> int:
        """当前所处地图 id（RAM 直读；换图判定用）。"""
        ...

    def pos(self) -> PlaceInWorld:
        """角色当前格（全项目唯一位置表示）。"""
        ...

    def facing(self) -> str:
        """角色当前朝向（`north/south/west/east`，`FACING_BY_BYTE` 同词；读不出为空串）。"""
        ...

    def is_grass(self, x: int, y: int) -> bool:
        """这一格是不是高草丛（walk_to_adjacent 的 `entered_grass` 判定用）。"""
        ...

    def is_npc(self, x: int, y: int) -> bool:
        """这一格此刻有没有 NPC（会走，按键瞬间以实读为准——talk 的 `no_target` 复验）。"""
        ...

    def object_kind(self, x: int, y: int) -> str | None:
        """这一格的交互物 kind（人/招牌/门/物/石…，P6 起判事件用）；没有为 `None`。"""
        ...

    def scene(self) -> str:
        """当前帧的场合（`TaskScene.value`：walk/dialog/battle/…，与 `classify_scene` 同源）。"""
        ...

    def money(self) -> int:
        """现金（`read_money`，买/卖的校验读数）。"""
        ...

    def bag_count(self, item: str) -> int:
        """背包里某道具的持有数（名字逐字匹配 `read_bag` 的渲染名）。"""
        ...

    def run_script(self, name: str, args: dict[str, str | int]) -> ScriptResult:
        """执行另一条脚本并拿回它的终态报告（脚本组合：如 `buy_item` 调 `shop_buy`）。"""
        ...


class DialogCache:
    """对话增量缓存（§3.5 写侧主动增量）：已见行集合，reset/load_state 清空。

    `ingest` 返回**本帧新增**文本（不在已见集合里的行），并就地更新集合——
    消费方按序直接拼接各事件 `text` 即完整对话，无需 diff。
    """

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.deltas: list[str] = []
        """每次 `ingest` 的增量文本，按发生顺序（P6 起脚本的对话载荷从这取——
        events[] 已交给判定层统一产出，不再兼职对话记录）。"""

    def reset(self) -> None:
        self.seen.clear()
        self.deltas.clear()

    def ingest(self, dialog_text: str) -> str:
        lines = [line for line in dialog_text.splitlines() if line.strip()]
        new = [line for line in lines if line not in self.seen]
        self.seen.update(lines)
        delta = "\n".join(new)
        if delta:
            self.deltas.append(delta)
        return delta


class Halt(Exception):
    """脚本内部控制流信号：被钩子 / 预算触发，由 `execute` 接住转成 `ScriptResult`。"""

    def __init__(self, code: str, *, ok: bool = False, extra: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code, self.ok, self.extra = code, ok, extra or {}


@dataclass
class ScriptResult:
    """一次脚本调用的终态报告（统一带 `events[]` 与现状快照）。"""

    ok: bool
    code: str
    data: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    calls: list[Any] = field(default_factory=list)


class ScriptRun:
    """一次脚本调用的现场：预算（步）、events[]、对话增量缓存、三钩子。

    用法：脚本按自己的主循环调 `press(key)` 推进世界；任一钩子 / 预算触发即抛
    `Halt`，`execute()` 接住转成 `ScriptResult`。`blocked` 不是全局钩子——
    移动被挡不产生事件，由脚本自己断言位移（见 §3.4 / §6.2）。
    """

    def __init__(
        self,
        console: WorldConsole,
        *,
        budget: int,
        start_map_id: int,
        start_pos: PlaceInWorld,
    ) -> None:
        self.console = console
        self.budget = budget
        self.start_map_id = start_map_id
        self.start_pos = start_pos
        self.events: list[dict[str, Any]] = []
        self.dialog = DialogCache()
        self.calls: list[Any] = []

    # ---- 稳定等待（复用接管脚本的物理量）----
    def settle(self) -> None:
        """推进到屏幕缓冲连续 `STABLE_POLLS` 次不变（`▼` 闪烁不算变）。"""
        waited, same, last = 0, 0, None
        while waited < STEP_TIMEOUT_FRAMES:
            self.console.tick(POLL_FRAMES)
            waited += POLL_FRAMES
            now = self.console.read().screen.replace("▼", " ")
            same = same + 1 if now == last else 0
            last = now
            if same >= STABLE_POLLS:
                return

    # ---- 每步自动钩子（三钩子，所有脚本共享）----
    def _check_hooks(self, key: str) -> None:
        text = self.console.read()
        scene = classify_scene(text, self.console.memory)
        # ① 进战斗 → BattleStarted（bounce 捕获为正常终止，其余终止）
        if scene is TaskScene.BATTLE or text.in_battle:
            raise Halt("battle_started")
        # ② 出现选项框 → ChoicePresented（冻结；选项文本进返回；绝不代选）
        if text.has_cursor and text.options:
            raise Halt("choice_presented", extra={"choice": " / ".join(text.options)})
        # ③ 换图 → MapChanged（exit_map 捕获为成功；其余终止 map_changed）。
        # warp 事件本身由 `judge_press` 统一判定产出（P6），这里只管终止。
        if self.console.map_id() != self.start_map_id:
            raise Halt("map_changed", extra={"map_id": self.console.map_id()})

    def press(self, key: str, *, settle: bool = True) -> bool:
        """按一键、等稳定、判事件、跑三钩子。返回**是否发生位移**（供脚本判 blocked）。

        事件判定走 `object_events.judge_press`（P6 起与 `step` 路径同一裁判）：
        对话增量另存 `dialog.deltas` 供脚本载荷用，不再进 events[]。
        """
        pos_before = self.console.pos()
        facing_before = self.console.facing()
        self.console.press(key)
        if settle:
            self.settle()
        moved = self.console.pos() != pos_before
        after_text = self.console.read()
        self.dialog.ingest(after_text.dialog_text)
        self.events.extend(
            judge_press(
                actor_place=pos_before,
                facing_before=facing_before,
                button=key,
                times=1,
                after_place=self.console.pos(),
                dialog_text=after_text.dialog_text,
                kind_at=lambda p: self.console.object_kind(p.x, p.y),
            )
        )
        self._check_hooks(key)
        return moved

    def _snapshot(self) -> dict[str, Any]:
        text = self.console.read()
        return {
            "pos": self.console.pos().model_dump(),
            "scene": classify_scene(text, self.console.memory).value,
            "screen_text": text.screen,
        }

    def execute(self, steps: Iterable[str], *, settle: bool = True) -> ScriptResult:
        """逐键跑一段按键序列；任一钩子 / 预算触发即停，返回终态报告。

        预算先扣后按：预算为 N 时，第 N+1 次迭代在按下前即报 `budget_exhausted`。
        """
        try:
            for key in steps:
                if self.budget <= 0:
                    raise Halt("budget_exhausted")
                self.budget -= 1
                self.press(key, settle=settle)
        except Halt as halt:
            data = self._snapshot()
            data.update(halt.extra)
            return ScriptResult(
                ok=halt.ok, code=halt.code, data=data, events=self.events, calls=self.calls
            )
        data = self._snapshot()
        return ScriptResult(ok=True, code="ok", data=data, events=self.events, calls=self.calls)

    def finish(self, *, ok: bool, code: str, extra: dict[str, Any] | None = None) -> ScriptResult:
        """脚本手写主循环的收尾口：现状快照 + 脚本自有载荷合并成终态报告。

        供绕过 `execute()` 的脚本（walk_to / circle_walk 这类每步要做位移断言的）
        调用；钩子触发时先 `except Halt` 换成对应结局码，再落到这里收尾。
        """
        data = self._snapshot()
        if extra:
            data.update(extra)
        return ScriptResult(ok=ok, code=code, data=data, events=self.events, calls=self.calls)


def _dialog_texts(run: ScriptRun) -> list[str]:
    """本 run 收到的对话增量片段（按发生顺序；`DialogCache.deltas`）。"""
    return list(run.dialog.deltas)


def run_script(
    console: WorldConsole,
    steps: Iterable[str],
    *,
    budget: int,
    start_map_id: int,
    start_pos: PlaceInWorld,
    settle: bool = True,
) -> ScriptResult:
    """一次性跑一段按键序列的便捷入口（P4 脚本大多在此之上包装前置校验 + 成功谓词）。"""
    return ScriptRun(
        console, budget=budget, start_map_id=start_map_id, start_pos=start_pos
    ).execute(steps, settle=settle)


__all__ = [
    "Halt",
    "WARPS",
    "SHOP_LAYOUTS",
    "POKECENTER_LAYOUTS",
    "DialogCache",
    "ScriptResult",
    "ScriptRun",
    "WorldConsole",
    "run_script",
]
