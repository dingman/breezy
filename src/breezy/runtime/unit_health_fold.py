"""The health pass's read of the C5 fold: the unreadable check (F4) and the verdict subject.

Plan r15 section 3.3.2. The health row binds no registry store and opens no SQLite database, so the
fold is read from the newest registry EXPORT (``evidence/registry/``, plain files), the same rows
the resolver cross-checks against the store. The export is written at least daily, so the subject
it names can lag a transition by up to that long; the intraday producer, which owns the subject
choice for the per-family detectors, reads the same file.

``probe`` raises ``FoldUnreadable`` with ``unreadable`` (no export directory, a candidate that does
not read, a chain that does not verify, a fold that is invalid) or ``empty`` (no export, or a
venue chain of zero rows). Neither is "no subjects". A non-empty fold with no sender is the
legitimate ``_host`` case.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final

from breezy.persistence.autonomy.chain import ChainBroken, verify_venue_chain
from breezy.persistence.autonomy.fold import FoldInvalid, fold
from breezy.persistence.autonomy.paths import AutonomyPaths
from breezy.persistence.autonomy.registry_export import (
    ExportAbsent,
    ExportUnreadable,
    newest_export,
)
from breezy.runtime.unit_health_types import FoldUnreadable

__all__ = ["HOST_SUBJECT", "VENUE", "FoldSubject"]

#: The venue whose fold names the host-wide detectors' subject (the only live venue).
VENUE: Final = "polymarket_us"
#: The subject directory of a verdict when the fold names no sender (the engine ignores it).
HOST_SUBJECT: Final = "_host"
_UNREADABLE: Final = "unreadable"
_EMPTY: Final = "empty"


class FoldSubject:
    """One pass's view of the fold: ``probe()`` reads it, ``subject()`` names the subject."""

    def __init__(
        self,
        paths: AutonomyPaths,
        *,
        venue: str = VENUE,
        now_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._paths = paths
        self._venue = venue
        self._now_ns = now_ns
        self._sender: str | None = None

    def probe(self) -> None:
        """Read and fold the venue's rows; raise ``FoldUnreadable`` when that cannot be done."""
        self._sender = None
        export = newest_export(self._paths, self._venue)
        if isinstance(export, ExportAbsent):
            raise FoldUnreadable(_EMPTY)
        if isinstance(export, ExportUnreadable):
            raise FoldUnreadable(_UNREADABLE)
        try:
            chain = verify_venue_chain(export.rows, self._venue)
        except ChainBroken as exc:
            raise FoldUnreadable(_UNREADABLE) from exc
        if not chain.rows:
            raise FoldUnreadable(_EMPTY)
        view = fold(chain.rows, self._venue, max(self._now_ns(), chain.rows[-1].ts_ns))
        if isinstance(view, FoldInvalid):
            raise FoldUnreadable(_UNREADABLE)
        senders = view.senders
        self._sender = senders[0] if len(senders) == 1 else None

    def subject(self) -> str:
        """The sole sender (CHAMPION or HALTED) of the last good ``probe``, else ``_host``."""
        return self._sender if self._sender is not None else HOST_SUBJECT
