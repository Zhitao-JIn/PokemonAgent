"""run 的返回值契约（V8，plan2 R1）：结构化 `RunResult` 取代裸四元组。

eval 从此只消费返回值，不读 trace 拿统计（intent V8 / spec2 §五）——usage 在
harness 收尾侧过滤 `_call` 账聚合（harness 本来就有 trace 权限，不算违规）；
trace 降为可选交叉核对（证据 uuid 经 `episode_bounds` 定位）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .episode_io import EpisodeOutput


class LinkUse(BaseModel):
    """一条链路的 token 用量。"""

    input: int = 0
    output: int = 0
    cached: int = 0
    reasoning: int = 0


class UsageSummary(BaseModel):
    """全 run 按链路聚合的 LLM 用量与调用结论计数。"""

    tokens_by_link: dict[str, LinkUse] = Field(default_factory=dict)
    calls_by_link: dict[str, int] = Field(default_factory=dict)
    call_failed: int = Field(default=0, description="调用尝试失败次数（`call_failed` 账数）")
    call_exhausted: int = Field(
        default=0, description="链路重试预算耗尽次数（`call_exhausted` 账数）"
    )


class EpisodeBound(BaseModel):
    """一局的证据边界（首末事件 uuid）——结果层↔过程层（Langfuse）可选交叉核对的定位键。"""

    episode_id: str
    first_event: str = ""
    last_event: str = ""


class LineCounts(BaseModel):
    """本执行线的机械计数（R2b：evals 效率层的取数源，不再各读各的 trace）。"""

    presses: int = Field(default=0, description="按键次数（`act_call` key 形账数）")
    episodes: int = Field(default=0, description="开局数（`episode_start` 账数）")
    tasks: int = Field(default=0, description="派 task 数（`task_start` 账数）")


class RunResult(BaseModel):
    """`RunHarness.run` 的返回值。"""

    run_id: str
    sample_id: str = Field(
        default="", description="eval 传入的样本标识，原样带回；非 eval 调用为空串"
    )
    branch: str = Field(default="", description="本执行线名（与 trace 账的 meta.branch 同源）")
    termination: str = Field(
        default="", description="run 级终止类别（与 `run_end` 账同值）；没跑完/打包存档为空串"
    )
    outcomes: list[EpisodeOutput] = Field(default_factory=list)
    total: int = Field(default=0, description="局数")
    succeeded: int = Field(default=0, description="达成局数")
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    started_at: float = Field(default=0.0, description="本执行线最早一账的 started_at；无账为 0")
    ended_at: float = Field(default=0.0, description="本执行线最晚一账的 ended_at；无账为 0")
    usage: UsageSummary = Field(default_factory=UsageSummary)
    counts: LineCounts = Field(default_factory=LineCounts)
    episode_bounds: list[EpisodeBound] = Field(default_factory=list)


__all__ = ["EpisodeBound", "LineCounts", "LinkUse", "RunResult", "UsageSummary"]
