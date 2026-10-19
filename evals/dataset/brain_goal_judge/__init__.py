"""版本化目标判定评测数据集。"""

from .loader import load
from .schemas import JudgeCase, JudgeCaseV1, JudgeCaseV2

__all__ = ["load", "JudgeCase", "JudgeCaseV1", "JudgeCaseV2"]
