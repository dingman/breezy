"""MAKER-S2 S-5: hand a station-day's freed heap back to the OS (outcome-neutral, no data touched).

A station-day builds and drops millions of small frame/print objects and Rust-side query buffers.
The live allocations that remain after it are flat, but glibc keeps the freed chunks that sit below
a surviving allocation inside the process: bench 4 showed ~170 MB of resident memory kept per
station-day with ``mallinfo2().uordblks`` (in use) flat and ``fordblks`` (free, unreturned) growing.
``malloc_trim(0)`` returns those pages. It changes no value the replay computes.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import gc

__all__ = ["release_free_heap"]


def _libc_trim() -> ctypes.CDLL | None:
    name = ctypes.util.find_library("c")
    if name is None:
        return None
    libc = ctypes.CDLL(name)
    return libc if hasattr(libc, "malloc_trim") else None


_LIBC = _libc_trim()


def release_free_heap() -> bool:
    """Collect cycles and trim the allocator; ``False`` without ``malloc_trim`` (non-glibc)."""
    gc.collect()
    if _LIBC is None:
        return False
    _LIBC.malloc_trim(0)
    return True
