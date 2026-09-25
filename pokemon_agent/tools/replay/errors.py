"""回放模块自己的错误词汇。"""

from __future__ import annotations


class ReplayDiverged(Exception):
    """回放走偏了：本该产出的账、模型请求或读到的记录与录下的对不上，或没走到目标 task。

    它说明"同样的输入没有走出同样的路"——代码版本变了、磁带不完整、或有未录下的输入。
    恢复中止，原样上抛。
    """


__all__ = ["ReplayDiverged"]
