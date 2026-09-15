"""`summarize.md` 的装配逻辑：加载、拼装，都在这一个文件里。

服务 `Brain.summarize()`——拼好的字符串交给 `BrainTool.summarize()`，跟
`verify.py` 是**拆开的一对**：两者原先是 `Brain.verify_and_summarize()` 的
一次合并调用（模板 `calls/verify_and_summarize.md`），拆成两次独立调用后
（CHANGELOG 第 39 条）各占一份 prompt、一个装配模块。取舍与截图说明同
`verify.py` 的模块 docstring。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import FromHarnessToBrainToolSummarizeReq
from pokemon_agent.schemas.memory import render_sequence

from . import load

_TEMPLATE = load("summarize")


def build_prompt(req: FromHarnessToBrainToolSummarizeReq) -> str:
    """拼出蒸馏这次调用要问的完整 prompt。

    前置条件：`req.entries` 只装**已经过滤过的可信记录**（调用方拿 `verify()`
    的 `verdicts` 筛完再传进来——"过滤归 harness"）。至少一条，调用方保证。

    `entries` 同样走 `render_sequence()`、`## 第 i 条` 编号；`reason=True`
    ——蒸馏要总结"为什么这么做"，决策者自己的说法在这里是有用素材。
    """
    rendered = render_sequence(list(req.entries), reason=True)
    steps_text = "\n\n".join(f"## 第 {i} 条\n{r}" for i, r in enumerate(rendered))
    return _TEMPLATE.render(
        goal=req.goal,
        steps_text=steps_text or "（本局没有任何可信步骤记录）",
        result="成功完成" if req.success else "未能完成",
        steps=req.steps,
        max_steps=req.max_steps,
    )
