"""Re-export shim for the fill-time Take counter (R2.2).

Implementation: ``breezy.analysis.fill_time_count`` (sqlite-only; no Nautilus
import and no catalog). This path stays so ``from fill_time_count import
count_filled_takes`` and ``from fill_time_count import _open_readonly`` --
the one read-only connect -- keep resolving. Do not open sqlite here.
"""

from __future__ import annotations

from breezy.analysis.fill_time_count import (
    _TAKEN_REASON,  # noqa: F401
    _open_readonly,  # noqa: F401
    count_filled_takes,
)

__all__ = ["count_filled_takes"]
