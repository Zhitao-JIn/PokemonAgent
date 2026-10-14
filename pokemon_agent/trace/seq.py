"""两个 trace 后端共享的进程内序号；跨进程与重启后不保证单调。"""

from itertools import count
from threading import Lock

__all__ = ["next_seq"]

_counter = count(1)
_lock = Lock()


def next_seq() -> int:
    """返回本进程内唯一且按取号次序严格递增的正整数。"""
    with _lock:
        return next(_counter)
