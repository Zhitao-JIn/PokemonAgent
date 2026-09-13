"""校验 / 蒸馏两份 prompt 的组装入口。

**曾经是一次合并调用**（`Brain.verify_and_summarize()`，一份 prompt 问两件事），
拆成两个独立方法后，这里也拆成两个 `build_*_prompt()`——一份 prompt 只服务
一次调用，跟其他 `*/build_prompt` 一样，是"结构 → 文本"的唯一落点。

- `build_verify_prompt()` 服务 `Brain.verify()`，模板 `calls/verify.md`；
- `build_summarize_prompt()` 服务 `Brain.summarize()`，模板 `calls/summarize.md`。

**两者都只读 req 里的素材字段**，拼出字符串交给 `BrainTool` 的
`verify()`/`summarize()`（0913 定案：调用方就是 tool 自己）——跟
`judge_success` 同一个模式：信封里**没有 `prompt` 字段**，拼出来的字符串是
局部变量，`Brain` 不认识 `pokemon_agent.tools.prompts` 这个包。

多帧截图的网格**打包**在 provider 层（`_prepare_images`，按张计费）；prompt 里的
网格读法说明是**静态文案，只写死 3 列**，行数由模型看图自己数——0909 拍板撤掉随 n
变化的 `$images_note`，整份 prompt 不再有随帧数变化的文字。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToBrainToolVerifyReq,
)
from pokemon_agent.schemas.memory import render_sequence

from . import load

_VERIFY_TEMPLATE = load("verify")
_SUMMARIZE_TEMPLATE = load("summarize")


def build_verify_prompt(req: FromHarnessToBrainToolVerifyReq) -> str:
    """拼出校验这次调用要问的完整 prompt。

    `entries` 用 `render_sequence()` 去重相邻重复快照、`## 第 i 条` 编号
    （**编号必须与 `entries` 下标一一对应**——`verdicts.index` 要按它落回
    调用方手里的条目，错位就等于判错了对象）；`reason=False`，校验判定看
    "发生了什么"，不该看到决策者自己的说法。
    """
    rendered = render_sequence(list(req.entries), reason=False)
    steps_text = "\n\n".join(f"## 第 {i} 条\n{r}" for i, r in enumerate(rendered))
    return _VERIFY_TEMPLATE.render(
        goal=req.goal,
        steps_text=steps_text or "（本局没有任何步骤记录）",
        knowledge=req.knowledge or "（没有检索到相关领域知识）",
    )


def build_summarize_prompt(req: FromHarnessToBrainToolSummarizeReq) -> str:
    """拼出蒸馏这次调用要问的完整 prompt。

    前置条件：`req.entries` 只装**已经过滤过的可信记录**（调用方拿 `verify()`
    的 `verdicts` 筛完再传进来——"过滤归 harness"）。至少一条，调用方保证。

    `entries` 同样走 `render_sequence()`、`## 第 i 条` 编号；`reason=True`
    ——蒸馏要总结"为什么这么做"，决策者自己的说法在这里是有用素材。
    """
    rendered = render_sequence(list(req.entries), reason=True)
    steps_text = "\n\n".join(f"## 第 {i} 条\n{r}" for i, r in enumerate(rendered))
    return _SUMMARIZE_TEMPLATE.render(
        goal=req.goal,
        steps_text=steps_text or "（本局没有任何可信步骤记录）",
        result="成功完成" if req.success else "未能完成",
        steps=req.steps,
        max_steps=req.max_steps,
    )
