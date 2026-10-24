"""保留 worker 异常组的有序叶子根因，不生成 harness trace。"""

from pydantic import BaseModel


class FailureLeaf(BaseModel):
    """一个真实叶子异常的类型与消息。"""

    type: str
    message: str


def exception_leaves(error: BaseException) -> list[FailureLeaf]:
    """按异常组从左到右的深度优先顺序展开；普通异常保留为一项。"""
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in exception_leaves(child)]
    return [FailureLeaf(type=type(error).__name__, message=str(error))]
