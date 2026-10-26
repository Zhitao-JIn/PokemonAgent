"""知识正文全文逐篇拼接，空列表由调用方跳过组合。"""

from ....interfaces.assembly import Compose
from .params import KnowledgeParams


def assemble(params: KnowledgeParams, compose: Compose) -> str:
    """空列表返回空串；否则按输入顺序保留每篇的全部文本，不产生标题。"""
    return "\n\n".join(params.entries)
