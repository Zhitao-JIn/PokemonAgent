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
