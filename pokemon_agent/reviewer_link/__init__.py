"""Run 侧的单跳同步复核适配，不导入 reviewer 进程实现。"""

from .remote_reviewer import RemoteReviewer

__all__ = ["RemoteReviewer"]
