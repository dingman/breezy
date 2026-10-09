"""The scratch root of ``autonomy_health_cli --dry-run`` (plan r15 section 3.9; WP3 S6 F6).

A dry run is the real pass against a scratch copy of ``evidence/unit_health`` (the cursor, the
seen files, the heartbeat and the build-side markers, so the cursor and the markers apply as they
would), with scratch outbox and verdict roots. Nothing reaches the live data root, and the
scratch is removed on exit whatever the pass does.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from breezy.runtime.unit_health_store import health_root

__all__ = ["scratch_root"]

_PREFIX: Final = "aut6-health-dry-"
#: A pass leaves temp names (``.tmp-*``) only mid-write; a copy must not carry another run's.
_SKIP: Final = shutil.ignore_patterns(".tmp-*")


@contextmanager
def scratch_root(live_root: Path) -> Iterator[Path]:
    """A scratch data root holding a copy of the live health tree (empty when there is none)."""
    with tempfile.TemporaryDirectory(prefix=_PREFIX) as name:
        scratch = Path(name)
        source = health_root(live_root)
        if source.is_dir():
            shutil.copytree(source, health_root(scratch), ignore=_SKIP)
        yield scratch
