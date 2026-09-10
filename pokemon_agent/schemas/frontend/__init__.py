"""Frontend（api.py）产出的契约：前端发起的第一跳信封。

`RunHarness.run()` 不在这里：入参与返回值都走裸字段，不包装（返回
`(outcomes, total, succeeded, success_rate)`）。`RunResp` 只活在 harness 内部，
供 RUN_END 事件内嵌，见 `schemas/harness/`。

本文件是 `schemas/frontend/` 的统一出口，只做 re-export、不定义任何实体；
消费方只写 `from pokemon_agent.schemas.frontend import X`。
"""

__all__ = [
    "FromFrontendToRunHarnessSubmitEditReq",
    "FromFrontendToGameToolLatestFrameReq",
    "FromFrontendToGameToolLatestFrameResp",
]
from .communication.FromFrontendToGameToolLatestFrameReq import FromFrontendToGameToolLatestFrameReq
from .communication.FromFrontendToGameToolLatestFrameResp import (
    FromFrontendToGameToolLatestFrameResp,
)
from .communication.FromFrontendToRunHarnessSubmitEditReq import (
    FromFrontendToRunHarnessSubmitEditReq,
)
