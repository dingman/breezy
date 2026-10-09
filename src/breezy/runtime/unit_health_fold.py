"""The health pass's read of the C5 fold: the unreadable check (F4) and the verdict subject.

Plan r15 section 3.3.2. The health row binds no registry store and opens no SQLite database, so the
fold is read from the newest registry EXPORT (``evidence/registry/``, plain files), the same rows
the resolver cross-checks against the store. The export is written at least daily, so the subject
it names can lag a transition by up to that long; the intraday producer, which owns the subject
choice for the per-family detectors, reads the same file.

``probe`` raises ``FoldUnreadable`` with ``unreadable`` (a candidate that does not read, a chain
that does not verify, a fold that is invalid, an unreadable export directory) or ``empty`` (no
export of the venue, or a venue chain of zero rows). Neither is "no subjects". A non-empty fold
with no sender is the legitimate ``_host`` case.

X-12 (binding activation ruling): the registry export is a listed not-yet-deployed artifact,
``(registry_export, AUT-5a, not_expected_until=2026-11-16)``. ``FoldNotDeployed`` (not a failure,
listed in the rollup's ``not_deployed``) is raised only if the row stands (before the deadline),
the write-once latch ``evidence/unit_health/fold_export_seen`` does not exist (an unreadable latch
counts as seen), and ``evidence/registry/`` is absent or holds no file. The first pass that sees
any file there, of any venue, writes the latch; after that, and after the deadline, F4 applies in
full.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from typing import Final

from breezy.persistence.autonomy.chain import ChainBroken, verify_venue_chain
from breezy.persistence.autonomy.fold import FoldInvalid, fold
from breezy.persistence.autonomy.paths import AutonomyPaths
from breezy.persistence.autonomy.registry_export import (
    ExportAbsent,
    ExportUnreadable,
    newest_export,
)
from breezy.runtime.unit_health_store import HealthStore, day_of_ns
from breezy.runtime.unit_health_types import FoldNotDeployed, FoldUnreadable

__all__ = ["HOST_SUBJECT", "NOT_YET_DEPLOYED", "VENUE", "FoldSubject"]

#: The venue whose fold names the host-wide detectors' subject (the only live venue).
VENUE: Final = "polymarket_us"
#: The subject directory of a verdict when the fold names no sender (the engine ignores it).
HOST_SUBJECT: Final = "_host"
#: artifact -> (owner plan, first day its absence stops being expected).
NOT_YET_DEPLOYED: Final[Mapping[str, tuple[str, str]]] = {
    "registry_export": ("AUT-5a", "2026-11-16")
}
_ARTIFACT: Final = "registry_export"
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
        store: HealthStore | None = None,
        today: Callable[[], str] | None = None,
    ) -> None:
        self._paths = paths
        self._store = store
        self._today = today if today is not None else (lambda: day_of_ns(now_ns()))
        self._venue = venue
        self._now_ns = now_ns
        self._sender: str | None = None

    def probe(self) -> None:
        """Read and fold the venue's rows; raise ``FoldUnreadable`` when that cannot be done."""
        self._sender = None
        self._check_not_deployed()
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

    def _check_not_deployed(self) -> None:
        """X-12: raise ``FoldNotDeployed`` while the export is still expected to be absent."""
        store = self._store
        if store is None:
            return
        try:
            names = os.listdir(self._paths.export_dir())
        except FileNotFoundError:
            names = []
        except OSError:
            return  # an unreadable directory is never "not deployed": F4 takes it
        if names and not store.fold_export_seen():
            try:
                store.mark_fold_export_seen(self._now_ns())
            except OSError:
                return
        deadline = NOT_YET_DEPLOYED[_ARTIFACT][1]
        if not names and self._today() < deadline and not store.fold_export_seen():
            raise FoldNotDeployed(_ARTIFACT)

    def subject(self) -> str:
        """The sole sender (CHAMPION or HALTED) of the last good ``probe``, else ``_host``."""
        return self._sender if self._sender is not None else HOST_SUBJECT
