"""解析纠正说明单列版本，不重新装配基础请求。"""

from pathlib import Path
from string import Template

from ...interfaces.assembly import Compose
from .params import DecideActionRetryParams


def assemble(params: DecideActionRetryParams, compose: Compose) -> str:
    """基础前缀不变，两个换行后追加原有纠正模板。"""
    template = Template(Path(__file__).with_name("prompt.md").read_text(encoding="utf-8"))
    return (
        params.base_prompt
        + "\n\n"
        + template.substitute(attempt=params.attempt, reason=params.reason, raw=params.raw)
    )
