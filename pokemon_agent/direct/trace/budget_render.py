"""预算策略账的正文渲染；复用 trace 信封，不增加事件字段。"""

import json

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq
from pokemon_agent.trace import EventType

from .render import Rendered


def budget_record(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """调用方以 text 交预算字段；落盘标量均转为字符串。"""
    assert req.text, "budget record needs text"
    content = json.loads(req.text)
    return Rendered(
        EventType.LIFECYCLE, req.kind, {key: str(value) for key, value in content.items()}
    )
