"""脚本评分结论。"""

from pydantic import BaseModel, Field


class ScriptVerdict(BaseModel):
    """一条用例的判定：两面各自的问题清单，空 = 该面通过。"""

    code_problems: list[str] = Field(default_factory=list)
    truth_problems: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        """两面都没问题。"""
        return not self.code_problems and not self.truth_problems
