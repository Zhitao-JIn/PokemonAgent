"""Configuration errors raised before a prompt registry can serve requests."""


class PromptRegistryError(ValueError):
    """A registry, version, contract, or composition dependency is invalid."""
