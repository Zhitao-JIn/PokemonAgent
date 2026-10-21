"""静态片段不接收运行时文字。"""

from pydantic import BaseModel


class JudgeInterruptParams(BaseModel):
    pass
