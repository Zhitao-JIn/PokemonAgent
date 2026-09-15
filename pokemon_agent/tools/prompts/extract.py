"""`extract.md` 的装配逻辑：加载、拼装，都在这一个文件里。

服务 `Brain.extract()`——拼好的字符串交给 `BrainTool.extract()`。

**和 `summarize.py` 是两条并行的链路，不是一对拆分**：两者收同一类素材
（`req.entries` 里过滤后的可信记录）、用同一份渲染（`render_sequence(reason=True)`），
但问的是两个问题——`summarize` 问"**这一局**打得怎么样"，`extract` 问
"**这个世界**有什么我之前不知道的"。产物归属不同（摘要属于那一局、知识属于
世界），所以模板、装配模块、prompt、账各占一份，没有共用片段。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import FromHarnessToBrainToolExtractReq
from pokemon_agent.schemas.memory import render_sequence

from . import load

_TEMPLATE = load("extract")


def build_prompt(req: FromHarnessToBrainToolExtractReq) -> str:
    """拼出抽取这次调用要问的完整 prompt。

    前置条件：`req.entries` 只装**已经过滤过的可信记录**（调用方拿 `verify()`
    的 `verdicts` 筛完再传进来——"过滤归 harness"）。

    `reason=True`：抽取要和 `summarize` 看到同一份材料（含决策者的论据）——
    "为什么这么做"里常常藏着"这个世界怎么回事"，把它裁掉会让抽取漏掉一部分。
    """
    rendered = render_sequence(list(req.entries), reason=True)
    steps_text = "\n\n".join(f"## 第 {i} 条\n{r}" for i, r in enumerate(rendered))
    return _TEMPLATE.render(
        goal=req.goal,
        steps_text=steps_text or "（本局没有任何可信步骤记录）",
    )


__all__ = ["build_prompt"]
