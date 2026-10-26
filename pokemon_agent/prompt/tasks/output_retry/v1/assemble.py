"""输出纠正附录单列版本：动作空间说明只在决策节点渲染，其余文字与 v1 逐字一致。"""

import re
from pathlib import Path
from string import Template

from ...interfaces.assembly import Compose
from .params import OutputRetryParams

_PARTS = dict(
    re.findall(
        r"<!-- part:(\w+) -->\n(.*?)\n<!-- endpart -->",
        Path(__file__).with_name("prompt.md").read_text(encoding="utf-8"),
        re.S,
    )
)
_TEMPLATE = Template(_PARTS["main"])


def assemble(params: OutputRetryParams, compose: Compose) -> str:
    """基础前缀不变，两个换行后追加纠正模板；动作空间段按调用方开关。"""
    appendix = _TEMPLATE.substitute(
        attempt=params.attempt,
        reason=params.reason,
        raw=params.raw,
    )
    if params.include_action_space_note:
        appendix = appendix + "\n" + _PARTS["action_space_note"]
    return params.base_prompt + "\n\n" + appendix
