"""model-graded scorer 协议（spec2 §六，V3/D6）：判分模型由装配侧注入，evals 不绑 provider。

协议只有两件事：

1. `ModelGrader`——LLM 判分口的形状：收一段拼好的 rubric prompt，回结构化 `ModelGrade`。
   解析与重试归注入方（包 DeepSeekProvider 或 mock），evals 侧零 provider 依赖、零 LLM 调用；
2. `model_graded_scorer`——把 rubric 条目 + 注入的 grader 包成统一 `Scorer`，产
   `Score(kind="graded")`，与机械判定**分列**（V3：档位分不混进机械成功率）。

默认关（D6）：CLI 不给旗标就不装配本 scorer——机械判定第一真源，模型分只作参照列。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel, Field

from evals.core.score import Score
from evals.core.scorer import Scorer
from evals.schema import EvalSample, RubricItem
from evals.scorers import RunStream


class ModelGrade(BaseModel):
    """grader 回来的结构化结论（解析归注入方）。"""

    score: int = Field(description="rubric 档位（按 item.levels 的分值）")
    reason: str = ""
    detail: dict[str, float] = Field(default_factory=dict, description="打分依据的原始量")


class ModelGrader(Protocol):
    """LLM 判分口。前置条件：`grade` 对同一 prompt 幂等性不作要求（评分允许抖动，
    抖动本身是观测对象）；后置条件：返回的 `ModelGrade.score` 落在 item.levels 的分值集合内
    （越界即注入方的 bug）。"""

    def grade(self, prompt: str) -> ModelGrade: ...


Context = Callable[[RunStream, EvalSample], str]
"""从账本拼判定上下文的函数（rubric ①② 的渲染函数就是现成的实现）。"""


def model_graded_scorer(item: RubricItem, grader: ModelGrader, context: Context) -> Scorer:
    """一条 rubric 条目的 model-graded scorer。

    前置条件：`item.grader == "model"`（code/human 条目不该走模型判分）；
    后置条件：产出 `Score(kind="graded")`，`scorer_id = model:<item_id>`。
    """
    assert item.grader == "model", f"{item.item_id} 的 grader 是 {item.grader}，不走模型判分"
    anchors = "\n".join(f"- {lv.score}：{lv.anchor}" for lv in item.levels)

    def score(stream: RunStream, sample: EvalSample) -> Score:
        prompt = (
            f"## 评分条目\n{item.question}\n\n"
            f"## 档位锚点\n{anchors}\n\n"
            f"## 该样本的执行记录\n{context(stream, sample)}\n\n"
            '只回一个 JSON：{"score": <档位>, "reason": "<一句话依据>"}'
        )
        grade = grader.grade(prompt)
        return Score(
            scorer_id=f"model:{item.item_id}",
            kind="graded",
            score=grade.score,
            reason=grade.reason,
            detail=dict(grade.detail),
            sample_id=sample.sample_id,
        )

    return score


__all__ = ["Context", "ModelGrade", "ModelGrader", "model_graded_scorer"]
