"""组装好的、大脑决策相关的 prompt 常量：`INTENT_HELP` 和 `retry_note()`。

和 `game_hints.py` 是同一类文件：内容在 `prompts/*.md` 里，这里只做**组装**——
`INTENT_HELP` 要按 `Intent` 分类（依赖 `schemas.action`），`retry_note()` 要在
渲染结果前面拼两个换行（"怎么拼接"，不是 prompt 文字本身）。这两件事都不该
留在 `brain/brain.py` 里：那个模块该管"怎么决策"，不该同时管"这段说明文字
怎么拼出来"。
"""

from __future__ import annotations

from pokemon_agent.schemas.action import Intent

from . import load, load_sections

_RETRY_PROMPT = load("retry_note")


def retry_note(attempt: int, reason: str, raw: str) -> str:
    """重试时追加在 prompt **末尾**的纠正块（内容见 `prompts/retry_note.md`）。

    前面两个换行是刻意的：`prompts/retry_note.md` 里的内容从 `---` 开始，
    留出和上文的视觉分隔——这两行属于"怎么拼接"，不属于 prompt 文字本身，
    所以留在这里，不进 .md 文件。

    早一版重试是原样再问一遍，指望模型的随机性碰对——那等于把三次调用当一次用，
    而且最常见的那类错误（判据里写屏幕坐标）是**系统性的**，重试多少次都一样错。

    追加在末尾是刻意的：前缀一个字没动，三次尝试共享同一段缓存。
    """
    return "\n\n" + _RETRY_PROMPT.render(attempt=attempt, reason=reason, raw=raw)


_INTENT_SECTIONS = load_sections("intent_help")
INTENT_HELP: dict[Intent, str] = {
    Intent.PRESS: _INTENT_SECTIONS["press"],
    Intent.PUSH_GOAL: _INTENT_SECTIONS["push_goal"],
}
"""每类 intent 给大脑的说明。

和 `BUTTON_HELP` 一样，这是**接口的一部分**而不是 prompt 模板的一部分：
大脑能做哪几类事由 `ActionSpace.intents` 决定，说明得跟着实际下发的那几类走。
写死在模板里的话，掩掉一类之后说明还在，模型会去选一个用不了的东西。

`PRESS` 那条特意点出"唯一不可逆"：另外两类选错了只是浪费一轮，
按错键可能要走十步回来。代价不对称，就该让它知道。
"""
