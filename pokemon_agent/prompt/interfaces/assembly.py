"""Typed boundaries between the gateway and independently loaded assemblers."""

from typing import Protocol

from pydantic import BaseModel


class Compose(Protocol):
    """Compose only registered fragments using their exact declared parameter type."""

    def __call__(self, name: str, params: BaseModel) -> str:
        """Require a fragment name and matching params; return nonempty rendered text."""
        ...


class Assemble(Protocol):
    """A version's sole rendering function; all dependencies arrive through compose."""

    def __call__(self, params: BaseModel, compose: Compose) -> str:
        """Require validated params; return nonempty text, composing only literal names."""
        ...


class History(Protocol):
    """同一版本为 BrainPort 提供与 prompt 同源的逐条素材。"""

    def __call__(self, params: BaseModel, compose: Compose) -> list[str]:
        """返回有序的素材列表；空素材列表允许为空。"""
        ...
