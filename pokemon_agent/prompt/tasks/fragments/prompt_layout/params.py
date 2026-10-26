"""共享布局原料；块的名称仅在此声明，顺序由版本装配器管理。"""

from enum import StrEnum

from pydantic import BaseModel


class Block(StrEnum):
    RULES = "规则"
    GOAL = "目标"
    KNOWLEDGE = "检索知识"
    INDEX = "背景索引"
    OBJECTS = "地图交互事实"
    HISTORY = "本层历史"
    FEEDBACK = "状态与反馈"
    FRAME = "当前现场"
    BUDGET = "预算与进度"
    HUMAN = "人类插话"


class PromptLayoutParams(BaseModel):
    """调用方提供非空规则及已渲染的正文；空白正文不产生块。"""

    blocks: dict[Block, str]
