"""`TracePort` 的实现：**一条事件一个 json 文件，文件名是时间递增的 uuid**。

**全平铺**：所有事件都躺在落盘根那一个目录里，**不按 run 分层、也没有
`events/` 这一层**（0916）。"读哪一批"由 `read_events(meta=…)` 的交集匹配回答，
`run_id` 只是 `meta` 里的一个键——与 `memory/` 同一条规矩。

落盘记录就是 trace 自己的 `_Event`，六个字段：
`{uuid, kind, type, ts, meta, content}`（0914 封套改造）。

**谁盖什么**：`uuid`（= 文件名）与 `ts`（写入那一刻）归本类；`run_id` 由本类
**注入 `meta`**（它是本实例的标识、构造时给的，落盘这一层自己知道，
`_stamp_run_id`）；`kind` / `type` / `content` 与 `meta` 的其余键全部由调用方
（tool 层）给，本类**不解释**它们的取值。

**排序看 `(ts, uuid)`**（原 `event_id` 的活，0914 起）：`ts` 从死字段变成排序键，
同毫秒靠 uuid 兜底——于是"第几条"这件事不再需要一层全局计数器、也不需要
构造时扫盘接续。

**文件名是时间递增的 uuid**（RFC 9562 的 v7 布局，前 48 位是毫秒时间戳）：
跨毫秒按字典序排 ≈ 按时间排；同一毫秒内那两段随机，彼此之间不保序。文件名的
用处只有"肉眼和 `ls` 看着大致有序"，**排序的真源是 `(ts, uuid)`**。

**已删的三件**（0914，随封套改造）：

- `event_id`（全局单调序号 + 构造时扫盘接续 + `id → 文件` 索引）——
  它的唯一非内部读方是"按 id 取单条"，而那件事随 `frame_png` 一起下线了；
- `read_event(id)`——同上，画面真源搬到 `memory/step_memory/` 之后没有读者；
- `schema_version`（恒 `5`、零读方、两份副本要人工同步）。

**事件槽双写已删**（0913 晚）：`event_sink` 与 `RunDataCenter` 的内存镜像一起
下线——**磁盘账本就是唯一真相**，读的人（图内节点）直接读它（另一个读者
SSE 端点随 `api.py` 一起删了）。
"""

# pokemon_agent/trace/store.py

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .datastore.event import _Event
from .interface.event import Event


# 缺省落盘根：**进程启动目录**下的 `tracelog/`（0916 起，原名 `trace_data/`）。
# 一条事件一个文件、**全平铺**在这个目录里——不按 run 分层（run_id 在 `meta`
# 里，读侧靠 `read_events({"run_id": …})` 切片），与 `memory/` 同一条规矩。
# trace 是独立第三方模块，"项目仓库根在哪"不是它该知道的事——曾经的
# `Path(__file__)` 回溯三层已删，缺省改为启动时问一次 `cwd`。
def _default_root() -> Path:
    """缺省落盘根：启动目录下的 `tracelog/`（构造时取值，即进程启动那一刻）。"""
    return Path.cwd() / "tracelog"


def new_event_uuid() -> str:
    """造一个**时间递增**的 uuid（RFC 9562 的 v7 布局）当事件文件名。

    布局：`| 48 位毫秒时间戳 | 4 位版本号(7) | 12 位随机 A | 2 位变体(10) | 62 位随机 B |`。
    时间戳占最高位，所以**跨毫秒**生成的 id 按字典序排就是按时间排；同一毫秒内
    那两段是随机的，彼此之间不保序。**这只是给肉眼和 `ls` 的便利**，用来保证
    "同一个目录里不会撞名、大致按写入时间排列"，排序的真源是 `(ts, uuid)`
    （读侧见 `_scan_events`）。

    为什么不用标准库现成的：`uuid.uuid7()` 要到 Python 3.14 才有（本项目跑
    3.12），`uuid.uuid1()` 会把网卡 MAC 写进 id，都不合适。这段实现只用
    `time` / `os.urandom` / `uuid.UUID`，没有任何依赖。
    """
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rnd = int.from_bytes(os.urandom(10), "big")
    rand_a = (rnd >> 68) & 0x0FFF
    rand_b = rnd & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


def _stamp_run_id(meta: dict[str, Any], run_id: str) -> dict[str, Any]:
    """把 `run_id` 盖进 `meta`——**排在头一个**。

    **盖章的人只能是这里**：run_id 是本实例的标识（构造时给的），落盘这一层
    自己知道；让调用方再带一份等于同一个事实存两处。**平铺之后它是唯一能回答
    "这条账属于哪个 run"的字段**——0916 之前还有"目录名"那份对账，随按 run
    分层一起没了。

    前置条件：调用方交上来的 `meta` 不带 `run_id` 键。
    """
    assert "run_id" not in meta, "meta 不许自己带 run_id——那个键归落盘这一层盖"
    return {"run_id": run_id, **meta}


def _atomic_write_text(path: Path, text: str) -> None:
    """临时文件 + rename 的原子写：写完即完整，崩溃最多少一个未 rename 的 tmp。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _meta_of(event: Event) -> dict[str, Any]:
    """从 `meta` 那串 JSON 里取回 dict；读不动就给空 dict（残文件是预期内的）。

    给空 dict 的后果是**任何筛选条件都对不上**——正是想要的：读不动的文件
    不该混进任何一次查询的结果里。
    """
    try:
        meta = json.loads(event.meta)
    except (json.JSONDecodeError, TypeError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _matches(event_meta: dict[str, Any], wanted: dict[str, Any]) -> bool:
    """交集匹配：`wanted` 的**每个键都要等于** `event_meta` 里对应的值。

    AND-of-equalities，与 `MemoryStorePort.filter` 同一条语义（不支持 OR、
    不支持大小比较）。事件缺这个键时算不匹配——不是"当作空值相等"。
    """
    return all(event_meta.get(key) == value for key, value in wanted.items())


class LocalTrace:
    def __init__(self, run_id: str = "local", root: Path | None = None) -> None:
        """接好落盘目录（一个，不再有 run 层与 events 层）。

        `root`：**落盘根**——一条事件一个文件的那个目录，不是它下面的某一层。
        缺省用启动目录下的 `_default_root()`（0916 起——不再从 `__file__` 推
        仓库根）。做成形参是为了让调用方能换落盘位置：生产路径是启动参数
        `--trace-root` → `build_real(trace_root=…)` → `TraceTool.build(trace_root=…)`
        逐级递进来，测试用 `tmp_path`，不往启动目录写。

        `run_id`：**只用于盖进 `meta`，不参与路径**（0916 起）。同一个落盘根下
        的多个 run 平铺在一起，读侧靠 `read_events({"run_id": …})` 区分——
        与 `memory/` 同一条规矩（一条记录一个文件，run_id 在记录里）。

        构造时**不扫盘**（0914）：`event_id` 计数器与 `id → 文件` 索引都随
        `event_id` 一起下线，落盘只需要目录在。
        """
        self._run_id = run_id
        # str 与 Path 都收（与 `LocalMemoryStore` 的 root 同一条归一规矩）——
        # 覆盖链上 `build_real(trace_root=…)` 的形参就是 `str | Path`。
        self._dir = Path(root) if root is not None else _default_root()
        self._dir.mkdir(parents=True, exist_ok=True)

        self._last_ts = 0.0
        """本实例最近一次落账的 ts。**append 是单线程顺序调用**（trace 实例全图共享、
        图是同步 invoke），它当序列基线用：保证 ts 严格递增，见 `append`。"""

    def append(
        self,
        type: str,
        kind: str,
        meta: dict[str, Any] | None = None,
        content: Any = None,  # noqa: ANN401 —— 账的本体就是任意可 JSON 化的对象
    ) -> str:
        """落一条事件（文件名是时间递增 uuid），返回这个 uuid。

        `type` / `kind`：由调用方（tool 层）给，本类不解释取值。
        `meta`：调用方自报的签名信息（`source` / `episode_id` / `step`…），
            本类**盖上 `run_id`**（`_stamp_run_id`）后原样序列化成 JSON 字符串。
            调用方不要自己带 `run_id` 键。
        `content`：这笔账的本体，任何可 JSON 化的对象。

        `meta` / `content` 在盘上是 **JSON 字符串**（`json.dumps(..., ensure_ascii=False)`）
        ——需要一层转义，读端 `json.loads` 回来。序列化只在本类做一处。

        后置条件：六个字段已全部落盘；返回的 uuid 与文件名同值。
        **ts 严格递增**（0915 起）：墙上时钟的分辨率有限（实测两次相邻 append 可以
        取到**逐字节相同**的 `time.time()`，realcheck-0915-114740 第 17 步），
        撞刻时人为推进 1µs——读侧"按 `(ts, uuid)` 排序 = 按执行顺序排列"这条
        不变式才真正成立，否则平局落到随机的 uuid 上会把执行序翻掉。
        """
        event_uuid = new_event_uuid()

        now = time.time()
        if now <= self._last_ts:
            now = self._last_ts + 1e-6
        self._last_ts = now

        event = _Event(
            uuid=event_uuid,
            kind=kind,
            type=type,
            ts=now,
            meta=json.dumps(_stamp_run_id(dict(meta or {}), self._run_id), ensure_ascii=False),
            content=json.dumps(content, ensure_ascii=False),
        )

        path = self._dir / f"{event_uuid}.json"
        _atomic_write_text(path, event.model_dump_json())
        return event_uuid

    # ---- 读：只回答"盘上有什么"，不掩码、不游标、不打标 ----

    def read_events(self, meta: dict[str, Any] | None = None) -> list[Event]:
        """（契约见 `TracePort.read_events`）全量扫盘、按 `(ts, uuid)` 升序、按 `meta` 交集筛。

        每次调用重扫落盘目录——trace 不做内存缓存（内存镜像那套已删，
        需要"盘上有什么"就直接问盘）。

        筛选那几维住在 `meta` 里（封套只认 `uuid`/`kind`/`type`/`ts`），所以要先
        把那串 JSON 解回来——`_meta_of` 读不动给空 dict，于是读不动的文件
        **不匹配任何条件**（残文件是预期内的，它不该混进任何一次查询）。
        """
        events = [event for event, _path in self._scan_events()]
        if not meta:
            return events
        return [e for e in events if _matches(_meta_of(e), meta)]

    # ---- 内部辅助 ----

    def _scan_events(self) -> list[tuple[_Event, Path]]:
        """落盘根下的全部事件（连同它们的文件路径），按 `(ts, uuid)` 升序。

        残文件/旧格式文件解析失败是预期内的运行期情况，跳过不报错。返回的
        `_Event` 带 `extra="allow"`，所以旧数据（`event_id`/`payload` 那套）
        里多出来的字段原样挂在 `model_extra` 上——**它们会缺 `uuid`/`ts`，
        于是解析当场失败被跳过**，不会静默混进结果。
        """
        found: list[tuple[_Event, Path]] = []
        for path in sorted(self._dir.glob("*.json")):
            if path.name.endswith(".tmp"):
                continue
            try:
                event = _Event.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            found.append((event, path))
        found.sort(key=lambda pair: (pair[0].ts, pair[0].uuid))
        return found


__all__ = ["LocalTrace", "new_event_uuid"]
