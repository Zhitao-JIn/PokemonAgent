"""冻结样本的数据契约。"""

from pydantic import BaseModel

from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq


class JudgeCase(BaseModel):
    """标签不会传给判定器，只由 scorer 消费。"""

    case_id: str
    request: FromHarnessToBrainToolJudgeReq
    achieved: bool
