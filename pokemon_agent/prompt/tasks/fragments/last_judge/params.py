"""last_judge 的原始素材。"""

from pydantic import BaseModel

from ....records import JudgeFeedbackRecord


class LastJudgeParams(BaseModel):
    feedback: JudgeFeedbackRecord
    serialized: bool = False
