"""`summarize.md` 的装配逻辑：episode 级蒸馏的 prompt 拼装。

原料是本局全部 TaskMemory + verify 的正/负标注——**负样本不丢**，打标后
与正样本一起作参考。`labeled_blocks()` 是"素材行"的唯一真源：
`build_prompt()` 与 `BrainTool` 传给 brain 的 `history` 都调它。
"""

from __future__ import annotations

from collections.abc import Sequence

from pokemon_agent.brain.interface import VerifyVerdict
from pokemon_agent.schemas.harness import FromHarnessToBrainToolSummarizeReq

from . import load

_TEMPLATE = load("summarize")


def labeled_blocks(rendered: Sequence[str], verdicts: Sequence[VerifyVerdict]) -> list[str]:
    """把已渲染的记录逐条打上正/负样本标与依据。

    前置条件：`verdicts` 与 `rendered` 等长或更短（缺标的条目标"未校验"）。
    """
    by_index = {verdict.index: verdict for verdict in verdicts}
    blocks: list[str] = []
    for i, text in enumerate(rendered):
        verdict = by_index.get(i)
        if verdict is None:
            tag = "【未校验】"
        elif verdict.positive:
            tag = f"【正样本】{verdict.why}"
        else:
            tag = f"【负样本】{verdict.why}"
        blocks.append(f"## 第 {i} 条 {tag}\n{text}")
    return blocks


def build_prompt(req: FromHarnessToBrainToolSummarizeReq) -> str:
    """拼出 episode 蒸馏这次调用要问的完整 prompt。前置条件：`req.entries` 非空。"""
    steps_text = "\n\n".join(labeled_blocks([m.render() for m in req.entries], req.verdicts))
    return _TEMPLATE.render(
        goal=req.goal,
        steps_text=steps_text,
        result=("成功完成" if req.success else "未能完成")
        + f"（{req.termination.value}）；判定依据：{req.judge_reason or '（无）'}",
        steps=req.steps,
        max_steps=req.max_steps,
    )
