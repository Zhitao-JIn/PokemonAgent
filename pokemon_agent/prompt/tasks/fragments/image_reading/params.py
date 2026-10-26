"""附图来源的适用层；图片本身仍走已有独立通道。"""

from typing import Literal

from pydantic import BaseModel


class ImageReadingParams(BaseModel):
    """按层说明帧来源、去重与数量帽，不改变图片处理。"""

    scope: Literal["task", "episode", "run"]
