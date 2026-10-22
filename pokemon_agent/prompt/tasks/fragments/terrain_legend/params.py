"""地形符号与含义是 world 提供的数据。"""

from pydantic import BaseModel


class TerrainLegendParams(BaseModel):
    meanings: dict[str, str]
