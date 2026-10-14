"""事件流接口：追加写的序列 + 按需读。

协议物理上挨着它的实现（`trace/store.py` 的 `LocalTrace`、`trace/langfuse_trace.py` 的
`LangfuseTrace`）走，消费方直接
`from pokemon_agent.trace import TracePort`。

**签名里的 `type` / `kind` 是裸 `str`**（0913 降级）：trace 不可能只服务这一个
项目，它只保证"按时间记账"——**合法值域是声明方的事，trace 不认识它**。调用方
（tool 层）用 `EventType.X` / `TraceKind.X` 这些值填。

**`meta` / `content` 是"不透明载荷"**：trace 只把它们序列化并原样读回，
**不解释里面装了什么**。`meta` 的执行标签（含 `run_id` / `branch` 执行线标识，
0927 定案归 tool 层在调用时盖）由调用方交齐，存储实现只透传、不再补盖。

**读哪一批由 `meta` 的交集匹配回答**（0916）：trace 不解释标签语义，只做等值比较。
存储与读取延迟由具体实现说明：`LocalTrace` 读本地文件，Langfuse 实现接受最终一致性。

**已删的两件**（0914 封套改造）：`read_event(event_id)`——它是"按 id 取单条"的
唯一入口，而那个能力随 `frame_png` 一起下线（画面真源搬到
`memory/step_memory/`）。此前的 `cursor()` / `read_disk_events()` / `void_after()`
随 checkpoint 恢复链删掉（0913 第 57 条）；`read_screenshot` 随截图副本删掉。

**读能力只剩一条通用读方法**：`read_events` ——不做掩码、不做游标、不打标，
只回答"当前存储实现可读到什么"。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .event import Event


@runtime_checkable
class TracePort(Protocol):
    """事件的追加写 + 按需读。"""

    def append(
        self,
        type: str,
        kind: str,
        meta: dict[str, Any] | None = None,
        content: Any = None,  # noqa: ANN401 —— 账的本体就是任意可 JSON 化的对象
        *,
        started_at: float | None = None,
        ended_at: float | None = None,
    ) -> str:
        """追加一条事件，返回它的 `uuid`（= 文件名）。

        type：事件种类（字符串，取值由声明方定义）。
        kind：账名（字符串，取值由声明方定义）。
        meta：调用方交齐的签名信息——**已含 `run_id` 与 `branch`**（执行线标识，
            0927 定案由 tool 层在调用时盖；实现方对 meta 的任何键不解释、
            只透传，不再补盖）。
        content：这笔账的本体，任何可 JSON 化的对象。
        **`seq` 由实现方自行分配**（0928 325 用户拍板：trace 自己递增生成、
            进程内双后端、跨实例全局共享，每次重启置零不持久化）——盖进封套，
            作为**同刻 `ended_at` 的决胜键**；调用方不传、不许越层代管。
            跨进程不保证单调，同刻仍可能平局。
        started_at / ended_at：这笔账对应的**操作真实起止**（wall clock，
            `time.time()` 的 float；2026-09-27 双时刻定案）。调用方记了就交，
            没记（机械账/生命周期账）交 None，实现补 `start = end =` 记账时刻
            ——封套里没有独立于操作时间的"记账时刻"字段。

        `meta` / `content` 在事件形状中是 **JSON 字符串**（需要一层转义），
        序列化由实现方做一处，读端 `json.loads` 回来。后端的存储形式由实现决定。

        前置条件：`meta` 已带 `run_id` / `branch` 键（需要它们的实现就地 assert）。
        后置条件：实现已接受八字段事件并返回本地 `uuid`；本地文件实现会在返回前落盘，
            Langfuse SDK 实现可在返回后异步投递，最终一致性由实现文档声明。返回的 uuid
            是本地事件 ID，不要求与后端 observation ID 相同。
        """
        ...

    def read_events(self, meta: dict[str, Any] | None = None) -> list[Event]:
        """读当前实现可见的事件，按 `(ended_at, seq)` 升序；可按签名信息做交集筛选。

        meta：`None`（或空 dict）= 不过滤，返回实现当前可见的全部事件；给了就只返回
            **每个键都相等**的那批——键从 `meta` 自身字段中选取
            （常见为 `run_id` / `branch` / `source` / `episode_id` / `task_id` / `step`）。语义是
            **AND-of-equalities**（各条件的候选集取交集），**不支持 OR、
            不支持大小比较**（与 `MemoryStorePort.filter` 同一条）。
            `run_id` 的常见用法是"只读某一次 run"；`{"run_id": …, "episode_id": …}`
            就是"这一局"。
            事件缺某个键时**不匹配该条**（不是"当作空值相等"）。
        后置条件：按 `(ended_at, seq)` 严格升序——同刻账按实现方的 append 序决胜（0928 325）；
            无匹配时返回空列表（不抛异常）。
        一致性：具体实现可以对新写事件采用最终一致性；调用方不能假定 append 后立刻可读。
        失败：底层读取失败原样抛出——本方法不吞这一类错。
        """
        ...

    def flush(self) -> None:
        """提交实现当前缓冲事件（如有）；最终可读性由实现声明。"""
        ...

    def shutdown(self) -> None:
        """关闭实现持有的后台资源；本地同步实现可安全空操作。"""
        ...
