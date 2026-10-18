"""run 蒸馏响应：brain 正文、门面盖章的记忆与整条重试账。"""

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import RunSummary
from pokemon_agent.schemas.memory import RunMemory

from .ModelCall import ModelCall


class FromHarnessToBrainToolSummarizeRunResp(BaseModel):
    """记忆尚未落库；失败由门面抛 MaxRetriesExceeded 或 BudgetExhausted。"""

    summary: RunSummary
    run_memory: RunMemory
    calls: list[ModelCall] = Field(min_length=1)
