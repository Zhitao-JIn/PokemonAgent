"""world 的内部失败根；不依赖 harness 或 brain 的异常家族。"""


class WorldError(Exception):
    """世界模块内部失败。"""


__all__ = ["WorldError"]
