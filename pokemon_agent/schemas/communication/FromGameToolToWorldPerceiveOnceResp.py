"""世界给出的响应：一次感知的结果（`FromGameToolToWorldPerceiveOnceResp`）。

世界只有一种响应——**一次感知 + 这次调用产生的账**。`observe`/`reset` 是纯感知；
`step`/`execute` 推进世界后**在链尾感知一次**，返回的是同一种东西。
（不拆"感知响应"与"工具结果"两个类：字段完全同构、没有任何路径产出过
空观测的变体。合并决策见 `CHANGELOG.md` 2026-09-03 条目。）"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.domain import ObservationFromWorld


class FromGameToolToWorldPerceiveOnceResp(BaseModel):
    """**世界给出的一次感知**：观测 + 这次调用产生的模型调用记录。

    `calls` 不放进 `ObservationFromWorld`，因为观测是**大脑看的东西**，
    大脑不该知道 token 数、延迟这类记账信息，加进去就是把跨层契约当日志用。
    但这份记账又必须原样传到 Harness 手里去写 trace，所以让它跟观测
    平行地挂在这一层薄包装上。

    **`calls` 由产出处直接当返回值交出**——不攒实例变量缓冲、不开单独的
    "取账"方法："生产/消费分离、靠可变状态搭桥"是踩过坑的模式（完整事故
    描述见 `CHANGELOG.md` 2026-09-03 条目）。

    `calls` 为空列表表示这次调用命中缓存，没有产生新的模型调用——
    **不是 None**，调用方不用先判空值。

    **没有帧哈希**：按帧缓存感知、标注观测属于哪一帧这两个用途，都随
    "一帧只感知一次"这条结构约束失去了前提（详见 `tools/SPEC.md` 2.7）。

    **没有 `ok`，也没有 `message`**：动作是否产生预期效果由**前后两次观测
    的对比**回答（情景记忆层已经在做），恒为真的布尔比没有更糟；动作之后
    世界变成什么样，答案是**下一条完整的观测**，不是一句转述
    （完整论证见 `CHANGELOG.md` 2026-09-03 条目）。
    """

    observation: ObservationFromWorld = Field(
        description="这一帧的观测。对 `observe`/`reset` 是当前帧；"
        "对 `step`/`execute` 是推进后**链尾那一次感知**的帧"
    )
    calls: list[dict[str, str]] = Field(
        default_factory=list,
        description="这次调用（可能是重试了好几次）产生的每一条模型调用记录，"
        "按发生顺序排列。每条至少含 input_tokens/output_tokens/attempt/ok，"
        "建议一并给 raw（模型原始输出）。**不记 latency_ms**——耗时靠 trace "
        "事件的 `ts`（append 时刻）算，不额外维护这个字段。**失败的调用也在"
        "里面**——它们同样烧了 token。空列表表示命中缓存，没有产生新调用，"
        "**不是 None**",
    )
    frame_png: str = Field(
        description="这一次感知实际截下来、喂给视觉模型的那张原始 PNG。"
        "**跟 `calls` 同理，不放进 `ObservationFromWorld`**——大脑不该也不需要"
        "知道这一帧长什么样的原始像素，它只用模型解析出的 `facts`；这份原始帧"
        "纯粹是给 trace 落盘、供事后复盘用的。由 "
        "`episode_utils.perceive_with_retry()` 在给这次感知的 MODEL_CALL 调 "
        "`trace.append(..., frame_png=...)` 时直接带上，存进那一条 "
        "`TraceEvent.frame_png`（base64 文本字段，不是路径引用）——不经 "
        "`EpisodeRunState` 转手，`ObservationFromWorld` 本身不携带、"
        "也不该携带这个字段"
    )
