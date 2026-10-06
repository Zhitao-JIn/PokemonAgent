"""文本读屏的交接契约；输入必须是核过的真值观测，不能使用待测解码器输出。"""

from inspect_ai.util import StoreModel

from evals.data.screen_reading.schemas import ScreenAnswer


class InterpretRecord(StoreModel):
    """模型响应与解析失败留在 sample store。"""

    answer: ScreenAnswer | None = None
    raw: str = ""
    failure: str = ""
