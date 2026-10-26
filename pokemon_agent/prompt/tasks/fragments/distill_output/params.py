"""蒸馏输出字段与紧凑规则的适用层；不承载调用素材。"""

from typing import Literal

from pydantic import BaseModel


class DistillOutputParams(BaseModel):
    """三层当前字段集相同，各层保留自己的正文长度建议。"""

    scope: Literal["task", "episode", "run"]
