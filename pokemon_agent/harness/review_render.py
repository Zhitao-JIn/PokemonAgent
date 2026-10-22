"""复核记账使用的模型结论种类标签。"""

from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeResp


def outcome_kind(outcome: FromHarnessToBrainToolJudgeResp) -> str:
    """被审对象的种类标签：`JudgeVerdict`。"""
    return "JudgeVerdict"


__all__ = ["outcome_kind"]
