"""``--seed-cursor-now``: the activation baseline of the health journal cursor (X-14, X-16 step 4).

It writes a cursor that reads the journal from now on and journals the reason
``activation_baseline``. It drops journal HISTORY only: ``reconcile`` judges every owned unit in the
snapshot's failed list whatever the cursor says, so a unit that is still failed still pages. It
refuses (writing nothing) when a cursor already exists, because a second seed would silently drop
unprocessed failures, and when a pass holds the health lock.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

from breezy.runtime.unit_health_store import HealthStore, day_of_ns, health_root

__all__ = ["EXIT_CURSOR_EXISTS", "EXIT_LOCKED", "REASON", "run_seed_cursor"]

REASON: Final = "activation_baseline"
EXIT_CURSOR_EXISTS: Final = 4
EXIT_LOCKED: Final = 5
_US_PER_NS: Final = 1000


def run_seed_cursor(root: Path | None = None, *, now_ns: Callable[[], int] = time.time_ns) -> int:
    """Seed the cursor at ``now``. ``root`` is the health tree (default: the live one)."""
    store = HealthStore(root if root is not None else health_root())
    with store.lock() as held:
        if not held:
            sys.stderr.write("seed-cursor-now: a health pass holds the lock\n")
            return EXIT_LOCKED
        if store.read_cursor() is not None:
            sys.stderr.write("seed-cursor-now: a cursor already exists; nothing written\n")
            return EXIT_CURSOR_EXISTS
        now = now_ns()
        store.write_cursor_reset(day_of_ns(now), now, REASON)
        store.write_cursor(None, now, now // _US_PER_NS)
    sys.stdout.write(
        f"AUTONOMY_HEALTH_SEED cursor=baseline reason={REASON} since_us={now // 1000}\n"
    )
    return 0
