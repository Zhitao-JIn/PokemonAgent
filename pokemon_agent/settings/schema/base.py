"""所有配置段共用的基类：不可变、严格类型、拒绝未知键。"""

from pydantic import BaseModel, ConfigDict


class Section(BaseModel):
    """配置段基类；未知键、错误类型直接拒绝，实例创建后不可改。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
