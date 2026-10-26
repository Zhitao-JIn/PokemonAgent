"""稳定内容在前、追加历史居中、动态现场在后的唯一布局出口。"""

import re
from pathlib import Path

from ....interfaces.assembly import Compose
from .params import Block, PromptLayoutParams

BLOCK_ORDER: tuple[Block, ...] = (
    Block.RULES,
    Block.GOAL,
    Block.KNOWLEDGE,
    Block.INDEX,
    Block.OBJECTS,
    Block.HISTORY,
    Block.FEEDBACK,
    Block.FRAME,
    Block.BUDGET,
    Block.HUMAN,
)


def assemble(params: PromptLayoutParams, compose: Compose) -> str:
    """前置：规则非空；后置：只渲染非空块，规则独占本次输入之前。"""
    assert params.blocks.get(Block.RULES, "").strip(), "Layout requires rules"
    parts: list[str] = []
    marker = Path(__file__).with_name("prompt.md").read_text(encoding="utf-8").strip()
    for block in BLOCK_ORDER:
        if block == Block.GOAL:
            parts.append(marker)
        body = params.blocks.get(block, "")
        if body.strip():
            if block in {Block.RULES, Block.HUMAN}:
                body = re.sub(r"^(#{1,5}) ", r"#\1 ", body, flags=re.MULTILINE)
            parts.append(f"## {block.value}\n\n{body}")
    result = "\n\n".join(parts) + "\n"
    assert result.startswith(f"## {Block.RULES.value}\n")
    return result
