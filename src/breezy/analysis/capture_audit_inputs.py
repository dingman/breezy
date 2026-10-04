"""AUT-1 WP5 stage 2b, W3: input gathering (STUB).

Owner: stage-2b worktree W3 (I/O and orchestration). ``gather_inputs`` is the ONE place the audit
reads the world: single-read ``O_NOFOLLOW`` files under the data root, the exec store through the
E-8 snapshot (``take_flock=False``, advisory), the node logs (one ``scan_node_log`` per log per run
with the W2 sinks, S2-R6), the journals through ``capture_audit_host`` and the recorder catalog. An
unreadable or untrusted input raises ``AuditInputError`` with a cause of the closed set. The catalog
is read with ``pyarrow.dataset`` (column-projected, ``to_batches()`` only, S2-R7) and loaded EAGERLY
here; ``write_scan_cache`` is this module's only write (the audit's E-8 cache directory). Signatures
are pinned by ``tests/unit/test_capture_audit_stubs.py`` and must not change.
"""

import datetime as dt
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from breezy.analysis.capture_audit_input_types import AuditInputs, ExecView

__all__ = [
    "RecorderCatalogTape",
    "boot_census",
    "gather_inputs",
    "read_exec_view",
    "write_scan_cache",
]


class RecorderCatalogTape:
    """The recorder catalog as a ``TapeIndex``, scoped to one day's instruments."""

    def __init__(self, catalog_root: Path, day: dt.date, instruments: frozenset[str]) -> None:
        raise NotImplementedError("AUT-1 stage 2b W3")

    def lookup(
        self, frame_kind: str, instrument_id: str, ts_event: int
    ) -> Mapping[str, Any] | None:
        raise NotImplementedError("AUT-1 stage 2b W3")

    def quote_rows(
        self, instrument_id: str, start_ns: int, end_ns: int
    ) -> Iterable[Mapping[str, Any]]:
        raise NotImplementedError("AUT-1 stage 2b W3")

    def depth_rows(
        self, instrument_id: str, start_ns: int, end_ns: int
    ) -> Iterable[Mapping[str, Any]]:
        raise NotImplementedError("AUT-1 stage 2b W3")

    def best_ask_at(self, instrument_id: str, ts_ns: int) -> float | None:
        raise NotImplementedError("AUT-1 stage 2b W3")


def boot_census(data_root: Path, day: dt.date, *, supervisor_journal: str) -> tuple[str, ...]:
    """The instance ids of every boot overlapping ``day``: log ids, capture ``node_boot_id``s,
    ``live/<instance_id>/`` directories and supervisor spawns, counted by ``instance_id``."""
    raise NotImplementedError("AUT-1 stage 2b W3")


def read_exec_view(data_root: Path) -> ExecView:
    """The advisory exec-store view (venue ids hashed); raises ``AuditInputError`` on failure."""
    raise NotImplementedError("AUT-1 stage 2b W3")


def gather_inputs(data_root: Path, family_id: str, day: dt.date, *, now_ns: int) -> AuditInputs:
    """Everything one day's legs read, or ``AuditInputError``."""
    raise NotImplementedError("AUT-1 stage 2b W3")


def write_scan_cache(data_root: Path, key: str, body: bytes) -> None:
    """Write one per-log reducer cache entry below ``AUDIT_CACHE_DIR`` (atomic replace)."""
    raise NotImplementedError("AUT-1 stage 2b W3")
