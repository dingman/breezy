"""Address-space cap for offline read-only analysis scripts (F13 B0).

A bounded ``RLIMIT_AS`` turns a runaway scan into a ``MemoryError`` in the script instead of
pressure on the live node's host. Only the SOFT limit is lowered: it is never raised above the
limit the process already inherited (soft or hard), so a stricter ulimit set by the caller wins.
"""

from __future__ import annotations

import resource
from typing import Final

__all__ = ["apply_address_space_cap"]

_GIB: Final[int] = 2**30


def apply_address_space_cap(gib: float) -> int:
    """Lower the soft ``RLIMIT_AS`` to ``gib`` GiB, never above the current soft or hard limit."""
    if not gib > 0:
        raise ValueError(f"the memory cap must be positive GiB, was {gib!r}")
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    ceilings = [limit for limit in (soft, hard) if limit != resource.RLIM_INFINITY]
    capped = min([int(gib * _GIB), *ceilings])
    resource.setrlimit(resource.RLIMIT_AS, (capped, hard))
    return capped
