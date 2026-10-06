"""独立成功判定集：真值目标、观测历史与人工标签。"""

from inspect_ai.util import StoreModel
from pydantic import BaseModel

from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq


class JudgeCase(BaseModel):
    """标签不会传给判定器，只由 scorer 消费。"""

    case_id: str
    request: FromHarnessToBrainToolJudgeReq
    achieved: bool


class JudgeRecord(StoreModel):
    """模型判定与理由，供四格 scorer 读取。"""

    done: bool | None = None
    why: str = ""
