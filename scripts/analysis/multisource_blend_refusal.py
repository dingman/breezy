"""The runner's refusal exception, in its own module so helper modules can raise it cycle-free."""

from __future__ import annotations

__all__ = ["Refusal"]


class Refusal(Exception):
    """The run is refused; nothing was scored (or nothing further is scored)."""
