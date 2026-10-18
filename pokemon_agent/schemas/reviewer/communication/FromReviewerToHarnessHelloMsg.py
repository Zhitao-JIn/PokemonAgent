"""Reviewer 连上即声明席位模式，run 据此选择断线等待策略。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class FromReviewerToHarnessHelloMsg(BaseModel):
    """从未收到 hello 的客户端不得推测当前是无人值守 AI 模式。"""

    model_config = ConfigDict(extra="forbid")
    msg: Literal["hello"] = "hello"
    mode: Literal["human", "ai", "both"]
