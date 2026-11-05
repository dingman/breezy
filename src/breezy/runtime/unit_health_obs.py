"""The systemd side of the AUT-6 unit health pass: one validated bus snapshot (E-7e(f)).

The pass reads systemd ONLY from the bus snapshot handed over by ``ExecStartPre`` (an in-row
``systemctl`` fails by design). A snapshot older than the row's budget plus 60 s is rejected, and a
read that was skipped, timed out, overran its size cap or exited non-zero makes the pass UNKNOWN
for that read: it is never read as "no failures".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from breezy.runtime.autonomy_sandbox.bus_handoff import BusReadResult, BusSnapshot
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE
from breezy.runtime.unit_health_model import (
    SNAPSHOT_MAX_AGE_S,
    parse_failed_list,
    parse_show_blocks,
)

HEALTH_ROW_NAME: Final = "breezy-autonomy-health"
HEALTH_ROW: Final = AUTONOMY_BWRAP_TABLE[HEALTH_ROW_NAME]
_NS: Final = 1_000_000_000
_SERVICE: Final = ".service"


class SnapshotUnusable(Exception):
    """The snapshot cannot be trusted; ``reasons`` name every bad read (``<read>:<why>``)."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__(",".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True, slots=True)
class UnitObservation:
    snapshot_ts_ns: int
    #: ``Id`` to properties: the ``breezy-*`` / ``us-source-collector@*`` services and ``run-*``.
    blocks: dict[str, dict[str, str]]
    failed_names: tuple[str, ...]
    #: The stdout of every read by name, for the inventory and timer readers (S5).
    raw: Mapping[str, str]


def _read_problem(read: BusReadResult) -> str | None:
    if read.skipped:
        return "skipped"
    if read.timed_out:
        return "timed_out"
    if read.oversize:
        return "oversize"
    if read.rc != 0:
        return f"rc={read.rc}"
    return None


def parse_observation(snapshot: BusSnapshot, now_ns: int) -> UnitObservation:
    """Validate ``snapshot`` and parse it, or raise ``SnapshotUnusable``."""
    if now_ns - snapshot.ts_ns > SNAPSHOT_MAX_AGE_S * _NS:
        raise SnapshotUnusable(("bus_snapshot_stale",))
    by_name = {read.name: read for read in snapshot.reads}
    problems: list[str] = []
    for expected in HEALTH_ROW.bus_reads:
        read = by_name.get(expected.name)
        why = "missing" if read is None else _read_problem(read)
        if why is not None:
            problems.append(f"{expected.name}:{why}")
    if problems:
        raise SnapshotUnusable(tuple(problems))
    raw = {name: read.stdout for name, read in by_name.items()}
    blocks = {
        unit: props
        for unit, props in parse_show_blocks(raw["units_show"]).items()
        if unit.endswith(_SERVICE)
    }
    blocks.update(parse_show_blocks(raw["run_transient"]))
    return UnitObservation(snapshot.ts_ns, blocks, parse_failed_list(raw["failed_list"]), raw)
