"""判定门面的独立响应契约；每次尝试的账按顺序保留。"""

from pydantic import Field

from pokemon_agent.schemas.harness.domain.judgement import Judgement

from .ModelCall import ModelCall


class FromHarnessToBrainToolJudgeResp(Judgement):
    """无法取得合法结果时抛 MaxRetriesExceeded，不伪造 continue。"""

    calls: list[ModelCall] = Field(min_length=1)
