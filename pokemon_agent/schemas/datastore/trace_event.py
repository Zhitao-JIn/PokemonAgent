"""追加写的 trace 事件。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from . import TRACE_SCHEMA_VERSION, EventType, Source


class TraceEvent(BaseModel):
    """追加写的 trace 事件。

    这是 replay / checkpoint / SSE 观测台 / 成本统计 / 失败聚合 / 实验归因
    的共同底座，所以它是**不可变的事件**，不是可变的状态快照——
    不要往里加"当前状态"这类字段，那样就没法重放了。
    """

    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")
    # 0907：`frame_png` 从 `bytes` 改为 base64 `str`——JSONL 落盘本来就是
    # base64（pydantic 对 bytes 自动编码，磁盘格式不变），但 python 模式的
    # `model_dump()` 会原样吐 bytes，凡是把事件直接塞进 HTTP 响应的路径
    # （`GET /runs/{id}/review` 带完整 episode_trace）都会在 JSON 序列化时
    # 炸"invalid utf-8"。改成 str 后内存/磁盘/HTTP 三处形态统一，
    # 也跟 `StepMemory.before_frame`/`VisionCompletionReq.images` 同一约定。

    event_id: int = Field(description="全局单调递增，SSE 断线重连靠它补发。**排序的唯一依据**")
    run_id: str = Field(
        description="哪一次实验。**manifest 的 join key**——"
        "没有它，一份记着模型与 prompt 的 manifest 和一堆事件对不上"
    )
    episode_id: str = Field(description="所属 episode")
    step: int = Field(description="发生在第几步。**不是主键**——一步内有多条事件")
    type: EventType
    phase: str = Field(
        default="",
        description="循环阶段（observe / retrieve_memory / think / act 等）。"
        "由事件类型推导，和 episode_id + step 一起供观测台聚合。",
    )
    source: Source = Field(description="由哪一层产生。成本拆分与失败归因都按它切")
    payload: dict[str, str] = Field(default_factory=dict, description="该类型的结构化内容")
    frame_png: str | None = Field(
        default=None,
        description="这一步感知到的原始画面，只有 `VIEW` 类事件"
        "（`observe()`/`look_after()` 拼出来的那两种）才会非空——`payload` 保持"
        "`dict[str, str]` 纯文本不变，二进制单独开一个字段，JSONL 其余内容"
        "仍然是人可以直接读的文本。`None` = 这条事件没有对应的落盘帧"
        "（非视觉世界、或这条根本不是感知事件）。",
    )
    ts: float = Field(
        description="Unix 时间戳，秒。用于算延迟与对齐外部日志；"
        "**不能替代 event_id 排序**——同毫秒多条事件、时钟回拨都会让时间序失真"
    )
    schema_version: int = Field(default=TRACE_SCHEMA_VERSION)
