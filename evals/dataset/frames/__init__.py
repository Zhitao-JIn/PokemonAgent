"""类型化冻结帧与唯一读取入口。"""

from .loader import load
from .schemas import FrameTruth, ScreenLabel, ScreenSample

__all__ = ["load", "ScreenSample", "ScreenLabel", "FrameTruth"]
