"""Prompt registry selection; versions are selected only in the registry itself."""

from .base import Section


class PromptSection(Section):
    """A registry path relative to the repository root, or None for the bundled registry."""

    registry: str | None
