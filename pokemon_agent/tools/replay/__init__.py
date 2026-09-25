"""回放：从一份 episode 存档出发，按录下的账把前面的 task 原样喂回去，到目标 task 开局切回真件。

`docs/checkpoint/spec.md` v2 §七。五个磁带件共用一卷 `Tape`；装配点（`build.py`）在有磁带时
把真件包成磁带件，其余代码不知道自己在回放。统一出口。
"""

from .errors import ReplayDiverged
from .tape import NOT_COMPARED_KINDS, RecordedCall, Tape, comparable, event_content, event_meta
from .tape_game import TapeGame
from .tape_memory import TapeMemory
from .tape_provider import TapeProvider
from .tape_reviewer import TapeReviewer
from .tape_trace import TapeTrace

__all__ = [
    "NOT_COMPARED_KINDS",
    "RecordedCall",
    "ReplayDiverged",
    "Tape",
    "TapeGame",
    "TapeMemory",
    "TapeProvider",
    "TapeReviewer",
    "TapeTrace",
    "comparable",
    "event_content",
    "event_meta",
]
