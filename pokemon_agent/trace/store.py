"""`TracePort` 的实现：**一条事件一个 json 文件**，事件名就是它的 uuid。

`event_id` 由这里分配，**严格单调**——replay 与断线补发依赖它，重号或回退会让
读取端静默丢事件。落盘从旧版"按局 JSONL 追加"改为一条事件一个
`events/<uuid>.json`（0910 重构，见 `PLAN_memory_trace_layout.md` §6）：单文件
写完即完整（临时文件 + `os.replace` 原子写）。

（`TracePort` 只负责追加写——分配 event_id、落盘、截图副本；**读端不在这里**：
事件流槽在 `harness/run_data_center.py` 的 `RunDataCenter`（前端可见状态的
唯一聚合点），`LocalTrace` 落盘成功后经 `event_sink` 双写过去。）

**磁盘读取与废弃打标已删**（原 `read_disk_events` / `void_after` / `cursor` 三件）：
它们只服务 checkpoint 存档与恢复，随恢复链一起删掉了（见 `CHANGELOG.md` 本次
条目）。`event_id` 仍然从盘上算（`_next_id` 扫一次 events/ 取 max + 1），
所以同一个 run 重启进程续写时不会与已落盘的事件撞号。

**截图与 trace 事件共享 event_id**（拍板⑦）：`frame_png` 非空时另存一份
`screenshot/<event_id>.png`——event_id 永远递增，天然不撞名，撞名 `(n)` 后缀
逻辑随之消灭。
"""

# pokemon_agent/trace/store.py

import base64
import os
import time
from pathlib import Path
from typing import Any

from .datastore import TRACE_SCHEMA_VERSION, EventType, TraceEvent

# 项目根目录（通过 __file__ 回溯三级）
project_root = Path(__file__).parent.parent.parent
# 数据存储目录（在项目根目录下）
STORAGE_ROOT = project_root / "trace_data"
# 没有"每个事件一个 phase 标签"的表——TraceEvent.phase 直接取 type 的字面值
# （子语义在 payload.kind）。


def _atomic_write_text(path: Path, text: str) -> None:
    """临时文件 + rename 的原子写：写完即完整，崩溃最多少一个未 rename 的 tmp。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class LocalTrace:
    def __init__(
        self,
        run_id: str = "local",
        event_sink: Any = None,
    ) -> None:
        """接好 run 目录与事件槽（读端在 `RunDataCenter`，见模块 docstring）。

        构造时**扫一遍 events/ 目录**：`_next_id` 从盘上最大 event_id + 1 起算
        （同 run 重启进程续写时不撞号）；顺路记下已完整收尾的局（episode_end 判定用）。
        `event_sink`：落盘成功后的双写目标（`RunDataCenter.publish_event`），
        注入不构成 import 依赖。
        """
        self._run_id = run_id
        self._run_dir = STORAGE_ROOT / run_id
        self._events_dir = self._run_dir / "events"
        self._screenshot_dir = self._run_dir / "screenshot"
        self._event_sink = event_sink

        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._events_dir.mkdir(exist_ok=True)
        self._screenshot_dir.mkdir(exist_ok=True)

        # 扫盘：_next_id 与"已完整收尾的局"集合都从这里来。
        self._next_id = 0
        self._completed_episodes: set[str] = set()
        for event in self._scan_events():
            self._next_id = max(self._next_id, event.event_id + 1)
            if event.type == EventType.LIFECYCLE and event.payload.get("kind") == "episode_end":
                self._completed_episodes.add(event.episode_id)

    def append(
        self,
        episode_id: str,
        step: int,
        type: str,
        source: str,
        payload: dict[str, str] | None = None,
        frame_png: str | None = None,
    ) -> int:
        """分配单调的 event_id，落一个 json 文件，返回这个 id。

        frame_png：这一步感知到的原始画面，直接进这一条
            `TraceEvent.frame_png`。**非 None 时额外另存一份 PNG 到这个 run
            自己的 `trace_data/<run_id>/screenshot/`，文件名 = 这条事件自己的
            event_id**（共享 id，永远递增零撞名）——trace json 里的 base64 只
            适合程序读，这份是给人肉眼直接翻看用的，两份是同一份字节的独立
            拷贝，权威来源仍是 `TraceEvent.frame_png`，这份丢了不影响任何
            回放/复现逻辑。**引用方式是记 event_id**（谁要用这一帧，从事件里
            读 event_id 来定位文件），不再有按 step 号拼文件名的公式。
        """
        # 校验前置条件
        assert step >= 0, "step 必须非负"

        # 生成 event_id
        event_id = self._next_id
        self._next_id += 1

        # 构造完整事件
        event = TraceEvent(
            event_id=event_id,
            run_id=self._run_id,
            episode_id=episode_id,
            step=step,
            type=type,
            phase=type,
            source=source,
            payload=payload or {},
            frame_png=frame_png,
            ts=time.time(),
            schema_version=TRACE_SCHEMA_VERSION,
        )

        # 已完成的一局不允许覆盖（首条事件就撞上完整存档 = 调用方重复用 id）。
        # 跑一半的局（进程被杀）允许重跑覆盖——各写各的 uuid 文件，互不干扰。
        if event_id == 0 and self._episode_is_complete(episode_id):
            raise ValueError(
                f"严重错误: episode_id '{episode_id}' 已存在! 原因: 不允许覆盖已完成的阶段"
            )

        # 持久化到磁盘（一条事件一个文件，原子写）
        _atomic_write_text(
            self._events_dir / f"{self._event_filename(event)}.json", event.model_dump_json()
        )
        if frame_png is not None:
            self._save_screenshot(event)

        # 完整收尾标记同步维护（episode_end 判定的内存副本）
        if type == EventType.LIFECYCLE and (payload or {}).get("kind") == "episode_end":
            self._completed_episodes.add(episode_id)

        # 双写：事件槽（前端可见状态，RunDataCenter.publish_event）。
        if self._event_sink is not None:
            self._event_sink(event)

        return event_id

    def _event_filename(self, event: TraceEvent) -> str:
        """事件文件主名：`<run_id>-<event_id>`——run 前缀给人肉眼对账，
        event_id 是排序与截图共享的那个数；文件名的语义不参与任何程序内
        查找（读端一律扫目录解析 event_id）。"""
        return f"{self._run_id}-{event.event_id:012d}"

    def _save_screenshot(self, event: TraceEvent) -> None:
        """把这一帧原始画面另存一份 PNG 到这个 run 自己的
        `trace_data/<run_id>/screenshot/`，文件名 = 这条事件自己的 event_id。

        **纯粹是人眼翻看的便利副本，不是权威数据源**——那份是
        `TraceEvent.frame_png`（已经落进事件 json）。event_id 全 run 单调递增，
        天然不撞名，不覆盖、不加后缀。跟 `_save_screenshot` 的调用方一样不做
        try/except——磁盘层面的失败（比如空间写满）应该跟事件落盘一样直接
        暴露，不该假装这一步成功了。截图不参与 void：废弃事件的截图原地
        保留（拍板⑨）。
        """
        path = self._screenshot_dir / f"{event.event_id}.png"
        # 入参是 base64 文本（`TraceEvent.frame_png` 的统一形态），落盘前解码。
        path.write_bytes(base64.b64decode(event.frame_png or ""))

    def _scan_events(self) -> list[TraceEvent]:
        """盘上的全部事件，按 event_id 升序。

        构造时用它算 `_next_id` 与"已完整收尾的局"集合。残文件/旧格式文件解析
        失败是预期内的运行期情况，跳过不报错。
        """
        events: list[TraceEvent] = []
        for path in sorted(self._events_dir.glob("*.json")):
            if path.suffix != ".json" or path.name.endswith(".tmp"):
                continue
            try:
                event = TraceEvent.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            events.append(event)
        events.sort(key=lambda e: e.event_id)
        return events

    def _episode_is_complete(self, episode_id: str) -> bool:
        """这一局是不是已经完整收尾（盘上有 lifecycle/episode_end）。

        用构造时扫盘建好的内存集合，O(1)——集合在 append 时同步维护。"""
        return episode_id in self._completed_episodes


def screenshot_filename(event_id: int) -> str:
    """算"这条帧事件的截图该叫什么文件名"——`<event_id>.png`。

    截图与 trace 事件**共享 event_id**（拍板⑦）：事件 json 里的 event_id 就是
    截图文件名，引用从"按 step 号拼公式"变"记 event_id"。模块级函数、不挂在
    `LocalTrace` 上——纯字符串计算，调用方不该为了调它去牵一个 `LocalTrace`
    实例。**不保证文件真的存在**——截图只是便利副本，调用方自己兜底
    （`read_screenshot` 读不到返回 None）。
    """
    return f"{event_id}.png"


def read_screenshot(run_id: str, event_id: int) -> bytes | None:
    """按 `(run_id, event_id)` 读一张已存的截图，读不到（没落盘、那一步感知
    失败）就返回 `None`——调用方按"这张图可能缺"处理，不能因为一张便利副本
    缺失就让判定链路整个失败。"""
    path = STORAGE_ROOT / run_id / "screenshot" / screenshot_filename(event_id)
    if not path.exists():
        return None
    return path.read_bytes()
