"""`TracePort` 的实现：事件**追加写**进内存与 JSONL。

`event_id` 由这里分配，**严格单调**——replay 与断线补发依赖它，重号或回退会
让读取端静默丢事件。落盘用逐条追加的 JSONL 而不是最后一次性 dump：
进程被 Ctrl-C 掐掉时，已经跑过的那些步不该跟着没。

（`TracePort` 只负责追加写——分配 event_id、落盘、截图副本；**读端不在这里**：
事件流槽在 `harness/run_data_center.py` 的 `RunDataCenter`（前端可见状态的
唯一聚合点），`LocalTrace` 落盘成功后经 `event_sink` 双写过去。checkpoint
恢复的续写（`resume_after_event_id`）与磁盘读取（`read_disk_events`）也在这层。）
"""

# pokemon_agent/trace/store.py

import base64
import time
from pathlib import Path
from typing import Any

from pokemon_agent.schemas.datastore import TRACE_SCHEMA_VERSION, EventType, Source, TraceEvent

# 项目根目录（通过 __file__ 回溯三级）
project_root = Path(__file__).parent.parent.parent
# 数据存储目录（在项目根目录下）
STORAGE_ROOT = project_root / "trace_data"
# 感知帧的人眼可读副本——跟 trace JSONL 里 base64 的 frame_png 是同一份字节的
# 第二份拷贝，纯粹方便肉眼直接翻看，不是权威来源。0909 从项目根目录的全局
# `screenshot/` 挪进 `trace_data/<run_id>/screenshots/`——截图天然是"某个 run
# 某一局某一步"的观测产物，该跟 episodes/*.jsonl 同一个粒度按 run 分文件夹，
# 不该是不分 run 的全局目录（旧布局逼得 `void_after()` 只能靠文件名前缀在
# 全局目录里扫，见 CHANGELOG）。不再有模块级 `SCREENSHOT_ROOT`——每个
# `LocalTrace` 实例按自己的 `run_id` 算 `self._screenshots_dir`。

# 没有"每个事件一个 phase 标签"的表——TraceEvent.phase 直接取 type 的字面值
# （子语义在 payload.kind）。


class LocalTrace:
    def __init__(
        self,
        run_id: str = "local",
        resume_after_event_id: int | None = None,
        event_sink: Any = None,
    ) -> None:
        """接好 run 目录与事件槽（读端在 `RunDataCenter`，见模块 docstring）。

        `resume_after_event_id`（checkpoint 恢复续写，PLAN_checkpoint §5 步骤 4）：
        给出时 `_next_id` 从游标 +1 起算——主前缀的重建由恢复管线调
        `read_disk_events()` 交给 `RunDataCenter.rebuild()`，这里只管续写。
        `event_sink`：落盘成功后的双写目标（`RunDataCenter.publish_event`），
        注入不构成 import 依赖。
        """
        self._run_id = run_id
        self._run_dir = STORAGE_ROOT / run_id
        self._episodes_dir = self._run_dir / "episodes"
        self._screenshots_dir = self._run_dir / "screenshots"
        self._event_sink = event_sink
        self._next_id = 0

        # 确保存储结构
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._episodes_dir.mkdir(exist_ok=True)
        self._screenshots_dir.mkdir(exist_ok=True)
        if resume_after_event_id is not None:
            self._next_id = resume_after_event_id + 1

    def append(
        self,
        episode_id: str,
        step: int,
        type: EventType,
        source: Source,
        payload: dict[str, str] | None = None,
        frame_png: str | None = None,
        screenshot_step: int | None = None,
    ) -> int:
        """分配单调的 event_id，落盘，返回这个 id。

        frame_png：这一步感知到的原始画面，直接进这一条
            `TraceEvent.frame_png`。**非 None 时额外另存一份 PNG 到这个 run
            自己的 `trace_data/<run_id>/screenshots/`**（命名见 `screenshot_filename()`，
            见 `_save_screenshot`）——trace JSONL 里的 base64 只适合程序读，
            这份是给人肉眼直接翻看用的，两份是同一份字节的独立拷贝，
            权威来源仍是 `TraceEvent.frame_png`，这份丢了不影响任何回放/复现逻辑。
        screenshot_step（关键字参数，缺省等于 `step`）：
            截图文件名单独用的 step 号，跟这条 `TraceEvent` 自己的 `step` 字段
            解耦。**唯一现在会用到它的调用方**是
            `episode_utils.perceive_with_retry()`——`look_after_action()` 感知
            到的其实是"下一步"的开局画面，MODEL_CALL 事件本身仍然按"这次感知
            发生在哪一步的回合里"记账（`step` 不变），但对应的截图要按
            "这张图是第几步的开局画面"存，两者数值不一样时才需要传这个参数。
            没有这个参数时 `_begin()`/`look_after_action()` 会共用同一个
            `before.step` 存图（撞名风险，见 `_save_screenshot`），
            导致开局第一帧（`_begin` 存的）和第 0 步做完动作后的画面（0 号 loop
            的 `look_after_action` 存的）撞名——不覆盖但会追加 `(1)` 后缀，
            "按 step 号算文件名"这个公式因此在这两帧上失真。
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
            phase=type.value,
            source=source,
            payload=payload or {},
            frame_png=frame_png,
            ts=time.time(),
            schema_version=TRACE_SCHEMA_VERSION,
        )

        # 已完成的一局不允许覆盖（首条事件就撞上完整存档 = 调用方重复用 id）。
        # 用"有没有 EPISODE_END"判完整，不用索引文件——episode_id 已带 run_id
        # 前缀，跨 run 撞号不会发生；跑一半的局（进程被杀）允许重跑覆盖。
        if event_id == 0 and self._episode_is_complete(episode_id):
            raise ValueError(
                f"严重错误: episode_id '{episode_id}' 已存在! 原因: 不允许覆盖已完成的阶段"
            )

        # 持久化到磁盘
        self._save_event(event)
        if frame_png is not None:
            self._save_screenshot(
                self._run_id,
                episode_id,
                step if screenshot_step is None else screenshot_step,
                frame_png,
            )

        # 双写：事件槽（前端可见状态，RunDataCenter.publish_event）。
        if self._event_sink is not None:
            self._event_sink(event)

        return event_id

    def _save_event(self, event: TraceEvent) -> None:
        """**直接追加一行**，不做"写临时文件再原子重命名"。

        那个模式只对**整份文件重写**成立：把完整内容写进 temp、再一次性换过去。
        这里是追加，写完一行就 `os.replace(temp, path)`，等于每次都用"只含这一条
        事件的临时文件"把已有的整份覆盖掉——**磁盘上永远只剩最后一条**。
        换成直接追加。单进程写、每次一行、行长远小于 `PIPE_BUF`，
        POSIX 下这一次 `write` 本身就是原子的，不需要额外的重命名把戏。

        把这条事件追加进 JSONL 文件。
        """
        episode_path = self._episodes_dir / f"{event.episode_id}.jsonl"
        with episode_path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def _save_screenshot(
        self, run_id: str, episode_id: str, step: int, frame_png: str
    ) -> None:
        """把这一帧原始画面另存一份 PNG 到这个 run 自己的
        `trace_data/<run_id>/screenshots/`，命名见 `screenshot_filename()`。

        **纯粹是人眼翻看的便利副本，不是权威数据源**——那份是 `TraceEvent.frame_png`
        （已经落进 JSONL）。三者拼在一起理论上已经唯一（同一个 episode 同一步
        只应该感知一次），但历史遗留文件、手工重跑等边界情况仍可能撞名，
        撞了就依次加 `(1)`、`(2)`……**不覆盖已有文件**，不确定哪张是最新的
        总比悄悄丢掉一张历史截图安全。跟 `_save_event` 一样不做 try/except——
        磁盘层面的失败（比如空间写满）应该跟事件落盘一样直接暴露，不该假装
        这一步成功了。

        **`StepMemory` 按这个命名约定去引用截图文件**
        （见 `episode_harness.store_step_episode_memory`），所以这里的命名
        不只是"人眼翻看的便利"——撞名加 `(n)` 后缀会让"按 step 号算文件名"
        这个公式在撞名那一刻起失真（引用会算出 `_N.png`，可磁盘上那个位置
        其实是撞名前的旧文件）。接受这个残余风险——撞名只在历史遗留文件/
        手工重跑时才可能触发；`screenshot_step`（见
        `episode_utils.perceive_with_retry`）已堵住"同一个 step 号在正常运行
        下被写两次"的源头（0 号帧、before/after 共用 step 号）。
        """
        base = screenshot_filename(run_id, episode_id, step).removesuffix(".png")
        path = self._screenshots_dir / f"{base}.png"
        n = 1
        while path.exists():
            path = self._screenshots_dir / f"{base}({n}).png"
            n += 1
        # 入参现在是 base64 文本（`TraceEvent.frame_png` 的统一形态），落盘前解码。
        path.write_bytes(base64.b64decode(frame_png))

    def cursor(self) -> int:
        """当前游标：最后一条已分配的 event_id（没有事件时 -1）。

        checkpoint 保存（`save_checkpoint` 节点）用它当快照游标——恢复时
        `resume_after_event_id` 从它 +1 续写，保证 id 严格单调不断链。
        """
        return self._next_id - 1

    def read_disk_events(self) -> list[TraceEvent]:
        """读盘上全部事件（各局 JSONL 合并，event_id 升序）——checkpoint 恢复的
        主前缀来源：恢复管线把它交给 `RunDataCenter.rebuild()` 做前端单点重建。

        崩溃残行按预期内情况跳过。**只应在 void 截断之后调用**——截断前盘上
        还有废弃时间线的行。
        """
        events: list[TraceEvent] = []
        for path in sorted(self._episodes_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(TraceEvent.model_validate_json(line))
                except Exception:
                    continue
        events.sort(key=lambda e: e.event_id)
        return events

    def _episode_is_complete(self, episode_id: str) -> bool:
        """这一局是不是已经完整收尾（jsonl 里有 lifecycle/episode_end）。"""
        path = self._episodes_dir / f"{episode_id}.jsonl"
        if not path.exists():
            return False
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                ev = TraceEvent.model_validate_json(line)
                if ev.type is EventType.LIFECYCLE and ev.payload.get("kind") == "episode_end":
                    return True
            except Exception:
                # 最后一行可能是写到一半被杀的残行，跳过
                continue
        return False


def screenshot_filename(run_id: str, episode_id: str, step: int) -> str:
    """算"第 `step` 步的截图该叫什么文件名"——`_save_screenshot` 存的时候、
    `StepMemory.before_frame`/`after_frame` 引用的时候，都调这一个函数，
    不能各自拼字符串（拼错一处就对不上）。**不保证文件真的存在**——
    截图只是便利副本，可能因为撞名改了后缀、或者这一步感知失败没能落盘，
    调用方（`read_screenshot`）自己兜底。模块级函数、不挂在 `LocalTrace` 上——
    这是纯字符串计算，`StepMemory`/harness 拼文件名时不该为了调它去牵一个
    `LocalTrace` 实例。
    """
    return f"{run_id}_{episode_id}_{step}.png"


def read_screenshot(run_id: str, filename: str) -> bytes | None:
    """按 `(run_id, filename)` 读一张已存的截图，读不到（没落盘、被撞名改了
    后缀）就返回 `None`——调用方（judge/verify_steps 拼多模态请求那几处）按
    "这张图可能缺"处理，不因为一张便利副本缺失就让判定链路整个失败。

    0909 起截图按 run 分文件夹（`trace_data/<run_id>/screenshots/`），模块级
    函数因此需要 `run_id` 才能算出路径——文件名本身仍含 run_id 前缀
    （`screenshot_filename()` 不变），这里的 `run_id` 只用来定位目录，不做
    二次校验。"""
    path = STORAGE_ROOT / run_id / "screenshots" / filename
    if not path.exists():
        return None
    return path.read_bytes()
