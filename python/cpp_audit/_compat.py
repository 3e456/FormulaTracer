"""Compatibility helpers for the supported Python 3.10+ range."""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:  # Python 3.10
    from enum import Enum

    class StrEnum(str, Enum):
        """Backport the string behavior used by :class:`enum.StrEnum`."""

        def __str__(self) -> str:
            return str(self.value)

        def __format__(self, format_spec: str) -> str:
            return format(self.value, format_spec)


__all__ = ["StrEnum"]
