"""合并后的生效配置及其出处：落盘快照的原料。"""

from pydantic import Field

from .app_config import AppConfig
from .base import Section


class ResolvedConfig(Section):
    """`load_config()` 的结果。

    `sources` 保底在前、覆盖在后；`merged_json` 是键排序的规范化 JSON；`sha256` 是它的摘要，
    两次实验的参数是否相同，比一个摘要即可。
    """

    config: AppConfig
    sources: tuple[str, ...] = Field(min_length=1)
    merged_json: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
