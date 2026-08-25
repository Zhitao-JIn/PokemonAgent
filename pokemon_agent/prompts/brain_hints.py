"""组装好的、大脑决策相关的 prompt 常量。目前只剩 `retry_note()`。

和 `game_hints.py` 是同一类文件：内容在 `prompts/*.md` 里，这里只做**组装**——
`retry_note()` 要在渲染结果前面拼两个换行（"怎么拼接"，不是 prompt 文字本身）。
这件事不该留在 `brain/brain.py` 里：那个模块该管"怎么决策"，
不该同时管"这段说明文字怎么拼出来"。

这里曾经还有一个 `INTENT_HELP`（每类 intent 给大脑的说明），
随 intent 分派一起删了——拆子目标的机制在别处重写时，它要不要回来是那时的决定。
"""

from __future__ import annotations

from . import load

_RETRY_PROMPT = load("retry_note")


def retry_note(attempt: int, reason: str, raw: str) -> str:
    """重试时追加在 prompt **末尾**的纠正块（内容见 `prompts/retry_note.md`）。

    前面两个换行是刻意的：`prompts/retry_note.md` 里的内容从 `---` 开始，
    留出和上文的视觉分隔——这两行属于"怎么拼接"，不属于 prompt 文字本身，
    所以留在这里，不进 .md 文件。

    早一版重试是原样再问一遍，指望模型的随机性碰对——那等于把三次调用当一次用，
    而且最常见的那类错误（判据里写屏幕坐标）是**系统性的**，重试多少次都一样错。

    追加在末尾是刻意的：前缀一个字没动，三次尝试共享同一段缓存。

    拼出追加在 prompt 末尾的那段纠正说明。
    """
    return "\n\n" + _RETRY_PROMPT.render(attempt=attempt, reason=reason, raw=raw)
