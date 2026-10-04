"""AUT-1 WP5 stage 2b, W3: host reads, the journals and the bus snapshot (STUB).

Owner: stage-2b worktree W3. ``run_journal`` runs one of the literal ``journalctl`` argv templates
(r8 section 3.10; only the two time slots are substituted, each regex-validated; 30 s timeout) and
raises ``AuditInputError("journal_failed")`` on a non-zero exit, a timeout, or empty output where
the caller requires some. ``read_recorder_props`` and ``read_ingest_exit_ns`` read seam B's bus
snapshot (``bus_snapshot_missing`` / ``bus_snapshot_stale`` are ERRORs; S2-R8). The argv templates
and ``AUDIT_BUS_READS`` are CONSTANTS stage 3 copies into the unit and the bwrap row: a value may be
corrected by W3, a NAME may not. Signatures are pinned by
``tests/unit/test_capture_audit_stubs.py``.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from breezy.analysis.capture_audit_input_types import RecorderProps

__all__ = [
    "AUDIT_BUS_READS",
    "INGEST_JOURNAL_ARGV",
    "JOURNAL_TIMEOUT_S",
    "RECORDER_JOURNAL_ARGV",
    "SUPERVISOR_JOURNAL_ARGV",
    "read_ingest_exit_ns",
    "read_recorder_props",
    "run_journal",
]

JOURNAL_TIMEOUT_S: Final[float] = 30.0
#: Literal templates; ``{since}`` and ``{until}`` are the only substituted slots.
INGEST_JOURNAL_ARGV: Final[tuple[str, ...]] = (
    "journalctl",
    "--user",
    "-u",
    "breezy-quote-tape-ingest",
    "-o",
    "cat",
    "--since",
    "{since}",
    "--until",
    "{until}",
)
SUPERVISOR_JOURNAL_ARGV: Final[tuple[str, ...]] = (
    "journalctl",
    "--user",
    "-u",
    "breezy-trade-supervisor",
    "-o",
    "cat",
    "--since",
    "{since}",
    "--until",
    "{until}",
)
RECORDER_JOURNAL_ARGV: Final[tuple[str, ...]] = (
    "journalctl",
    "--user",
    "-u",
    "breezy-quote-tape.service",
    "-o",
    "json",
    "--since",
    "{since}",
    "--until",
    "{until}",
)
#: The audit row's two bus reads (S2-R8): the recorder's watchdog properties and the ingest unit's
#: last exit time. The snapshot is read FIRST in ``main``, before any scan or lock wait.
AUDIT_BUS_READS: Final[tuple[tuple[str, ...], ...]] = (
    ("-p", "WatchdogUSec,NotifyAccess,Type", "--", "breezy-quote-tape.service"),
    ("-p", "ExecMainExitTimestamp", "--", "breezy-quote-tape-ingest.service"),
)


def run_journal(
    template: Sequence[str], since: str, until: str, *, timeout_s: float = JOURNAL_TIMEOUT_S
) -> str:
    """The journal text for ``[since, until]`` through a literal argv template."""
    raise NotImplementedError("AUT-1 stage 2b W3")


def read_recorder_props(data_root: Path, *, now_ns: int) -> RecorderProps:
    """The recorder's watchdog properties from the bus snapshot."""
    raise NotImplementedError("AUT-1 stage 2b W3")


def read_ingest_exit_ns(data_root: Path, *, now_ns: int) -> int | None:
    """The ingest unit's ``ExecMainExitTimestamp`` (epoch ns) from the bus snapshot, or None."""
    raise NotImplementedError("AUT-1 stage 2b W3")
