"""Address-space cap for offline read-only analysis scripts (F13 B0).

A bounded ``RLIMIT_AS`` turns a runaway scan into a ``MemoryError`` in the script instead of
pressure on the live node's host. Only the SOFT limit is lowered, so the cap never exceeds the
inherited hard limit and the process owner keeps the choice to raise it again.
"""

from __future__ import annotations

import resource
from typing import Final

__all__ = ["apply_address_space_cap"]

_GIB: Final[int] = 2**30


def apply_address_space_cap(gib: float) -> int:
    """Lower the soft ``RLIMIT_AS`` to ``gib`` GiB (clamped to the hard limit); return bytes."""
    if not gib > 0:
        raise ValueError(f"the memory cap must be positive GiB, was {gib!r}")
    _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    wanted = int(gib * _GIB)
    capped = wanted if hard == resource.RLIM_INFINITY else min(wanted, hard)
    resource.setrlimit(resource.RLIMIT_AS, (capped, hard))
    return capped
