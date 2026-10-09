"""Data types of the AUT-6 unit health pass: its environment, result and small exceptions."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from breezy.registry.health_model import AlertPayload
from breezy.runtime.autonomy_sandbox.bus_handoff import BusSnapshot
from breezy.runtime.health_dropins import DROPIN_ALLOWLIST, DropinAllow, read_dropin_file
from breezy.runtime.monitor_watch import WatchWiring
from breezy.runtime.unit_health_daemon_support import DaemonWiring
from breezy.runtime.unit_health_journal import JournalSource
from breezy.runtime.unit_health_store import HealthStore
from breezy.runtime.unit_health_support import DriftFinding, default_worktrees, read_meminfo

PRODUCER_STALE_DETECTOR: Final = "aut6.producer_stale"


class FoldUnreadable(Exception):
    """The fold could not be read (F4); ``reason`` is ``unreadable`` or ``empty``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class FoldNotDeployed(Exception):
    """The fold's registry export is a listed not-yet-deployed artifact (X-12): not a failure."""

    def __init__(self, artifact: str) -> None:
        super().__init__(artifact)
        self.artifact = artifact


@dataclass(frozen=True, slots=True)
class HostVerdict:
    """A ``#26`` FAIL for the ``_host`` subject; S6 makes it a C4 verdict (the pin lands last)."""

    detector: str
    outcome: str
    metrics: Mapping[str, str]
    ts_ns: int


@dataclass(frozen=True, slots=True)
class NewFailure:
    unit: str
    invocation_id: str
    unit_class: str
    severity: str


@dataclass(frozen=True, slots=True)
class PassResult:
    pass_result: str  # OK | FINDINGS | UNKNOWN | LOCKED
    unknown_reasons: tuple[str, ...] = ()
    failed_units: int | None = None
    new_failures: tuple[NewFailure, ...] = ()
    foreign_failed: tuple[str, ...] = ()
    journal_blind: tuple[str, ...] = ()
    cursor_reset: bool = False
    drift: tuple[DriftFinding, ...] = ()
    allowlisted: tuple[str, ...] = ()


@dataclass
class PassEnv:
    store: HealthStore
    read_snapshot: Callable[[], BusSnapshot]
    journal: JournalSource
    alert: Callable[[AlertPayload], bool]
    delivered: Callable[[str, str], bool]
    now_ns: Callable[[], int] = time.time_ns
    monotonic: Callable[[], float] = time.monotonic
    #: ``worktrees(timeout_s)``; raises ``WorktreesUnavailable`` when git cannot answer.
    worktrees: Callable[[float], Sequence[str]] = default_worktrees
    meminfo: Callable[[], tuple[int, int] | None] = read_meminfo
    fold_probe: Callable[[], None] | None = None
    host_verdict: Callable[[HostVerdict], None] | None = None
    #: ``None`` skips the drift check (no committed baseline was readable): inconclusive.
    committed_dropins: Mapping[str, frozenset[str]] | None = None
    #: ``read_dropin(path)``: the bytes of a regular, non-symlink drop-in, else ``None`` (X-13).
    read_dropin: Callable[[str], bytes | None] = read_dropin_file
    dropin_allowlist: Sequence[DropinAllow] = DROPIN_ALLOWLIST
    invocation_id: str = ""
    #: The daemon and intraday-stage rules' seams (S4); ``None`` skips them.
    daemons: DaemonWiring | None = None
    #: The meta-detectors' seams (WP3 S5: timers, producer, delivery, memory); ``None`` skips them.
    watch: WatchWiring | None = None
