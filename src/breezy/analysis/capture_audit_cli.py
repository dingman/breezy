"""AUT-1 WP5 stage 2b, W3: the ``breezy-capture-audit`` entry point (plan r12 sections 3.11, 3.13).

Stage 3 wires the unit to ``python -m breezy.analysis.capture_audit_cli``. Imports no
``breezy.adapters.*`` module (r12 section 3.11.1).

Order matters (S2-R8): the seam-B bus snapshot is read FIRST, before the launch-window check, any
scan or any lock wait, because the wrapper takes it in ``ExecStartPre`` and it goes stale. Its first
read is cached, so a snapshot error surfaces later as that day's ERROR (``PRE_CAPTURE`` masks it).
Then ``launch_window_guard``: a run whose worst case (``flock -w 600`` plus
``TimeoutStartSec=1500``) would meet [16:30Z, 17:10Z) defers (exit 0, no work).

Then the unit's studies lock is taken IN PROCESS (``studies_lock.acquire_studies_lock``, wait <=
``FLOCK_WAIT_S``; S3-R13/R14), not by ``flock -w`` in front of the wrapper, so the wait cannot age
the snapshot. A missing, refused or timed-out lock exits 1 with no writes (``OnFailure=`` pages).
The clock and ``today`` are then RE-READ (S3-R26): the wait may be 600 s.

Once ``DEADLINE`` is set, heal runs first, before the family loop and even with no family
(S3-R25, S3-R46), under ``min(now + HEAL_BUDGET_S, DEADLINE)``; its failures fold into the exit.

``DEADLINE`` is set ONCE here, before any family runs, and ``run_audit`` only reads it (S3-R41):
every family sees the same absolute instant, ``min(lock_acquired + AUDIT_WORK_BUDGET_S,
exec_start + AUDIT_EXEC_TIMEOUT_S - AUDIT_MARGIN_S)`` (S3-R48), so a long wait cannot carry the
run past the ExecStart ``timeout -k 5 1470``. The duties that belong to the run rather than to a
family (the missing-settlement check) run once, after the family loop, inside the same deadline.

Families are enumerated by construction: every ``evidence/capture/epoch/<family>.json`` plus each
``--family-id`` given. The exit code is 1 on any ERROR day, failed day, failed delivery or failed
once-per-run duty, decided after every write (``run_audit``). The default alert offer reports every
alert undelivered (AUT-6's outbox is not wired, C9), so an audit that has something to say exits 1
and ``OnFailure=`` fires.
"""

import argparse
import datetime as dt
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from breezy.analysis import capture_audit_inputs
from breezy.analysis.capture_audit import run_audit, run_once_duties
from breezy.analysis.capture_audit_host import read_recorder_props
from breezy.analysis.capture_audit_inputs import DEADLINE
from breezy.analysis.capture_audit_io import list_names
from breezy.analysis.capture_audit_model import (
    AUDIT_EXEC_TIMEOUT_S,
    AUDIT_MARGIN_S,
    AUDIT_WORK_BUDGET_S,
    AuditInputError,
)
from breezy.analysis.capture_heal import HEAL_BUDGET_S
from breezy.analysis.capture_heal_io import run_heal_duty
from breezy.analysis.capture_settlement import AlertOffer
from breezy.persistence.autonomy.capture_alerts import severity_for
from breezy.persistence.autonomy.capture_epoch import epoch_relative_path
from breezy.persistence.autonomy.capture_schedule import launch_window_guard
from breezy.persistence.autonomy.paths import FAMILY_RE, default_data_root
from breezy.runtime.autonomy_sandbox.bwrap import default_roots
from breezy.runtime.autonomy_sandbox.run_mounts import STUDIES_LOCK_NAME
from breezy.runtime.autonomy_sandbox.studies_lock import StudiesLockError, acquire_studies_lock

__all__ = ["FLOCK_WAIT_S", "TIMEOUT_START_S", "families_by_construction", "main"]

_LOGGER: Final = logging.getLogger(__name__)
FLOCK_WAIT_S: Final[int] = 600
TIMEOUT_START_S: Final[int] = 1500
LOCK_POLL_S: Final[float] = 0.5
_NS: Final[int] = 10**9
_EPOCH_FILE_RE: Final[re.Pattern[str]] = re.compile(r"\A(?P<family>[a-z0-9_]{1,64})\.json\Z")


def _undeliverable_offer(event: str, severity: str, detail: str) -> bool:
    sys.stderr.write(f"{severity} {event} {detail} (undelivered: no outbox wired)\n")
    sys.stderr.flush()
    return False


class _OfferHealSender:
    """The ``HealSender`` over the alert ``offer``: the severity comes from ``severity_for`` and
    ``attempt_kind`` rides in ``detail`` (the stage-4 shim: AUT-6's outbox takes it natively)."""

    def __init__(self, offer: AlertOffer) -> None:
        self._offer = offer

    def send(self, event: str, detail: str, attempt_kind: str) -> bool:
        return bool(
            self._offer(event, severity_for(event), f"{detail} attempt_kind={attempt_kind}")
        )


def families_by_construction(data_root: Path, explicit: Sequence[str]) -> tuple[str, ...]:
    """The families to audit: each epoch file's family and each explicitly named one."""
    *parent, _name = epoch_relative_path("x")
    found = {
        match["family"]
        for name in list_names(data_root, parent)
        if (match := _EPOCH_FILE_RE.fullmatch(name)) is not None
    }
    found.update(explicit)
    return tuple(sorted(found))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="breezy-capture-audit")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--family-id", action="append", default=[], dest="families")
    return parser


def _default_lock() -> int:
    """Take the real host studies lock (the file the wrapper re-binds); never called by a test."""
    path = default_roots().run_user / STUDIES_LOCK_NAME
    return acquire_studies_lock(path, wait_s=FLOCK_WAIT_S, poll_s=LOCK_POLL_S)


def _main(
    argv: Sequence[str] | None,
    *,
    offer: AlertOffer,
    clock: Callable[[], int],
    lock: Callable[[], int],
) -> int:
    exec_start = capture_audit_inputs.MONOTONIC()  # the ExecStart ``timeout`` starts here
    parser = _parser()
    args = parser.parse_args(argv)
    bad = [f for f in args.families if FAMILY_RE.fullmatch(f) is None]
    if bad:
        parser.error("--family-id must match [a-z0-9_]{1,64}")
    data_root = args.data_root if args.data_root is not None else default_data_root()
    now_ns = clock()
    try:
        read_recorder_props(data_root, now_ns=now_ns)  # S2-R8: the snapshot first, consumed once
    except AuditInputError:
        pass  # cached: every day reports it (a PRE_CAPTURE day masks it, S2-R9)
    if not launch_window_guard(now_ns, FLOCK_WAIT_S, TIMEOUT_START_S):
        sys.stderr.write("capture audit deferred: the run would meet the launch window\n")
        return 0
    try:
        lock_fd = lock()
    except StudiesLockError as exc:
        sys.stderr.write(f"capture audit: {exc.code}\n")
        return 1
    try:
        return _run_locked(data_root, args.families, exec_start, clock, offer)
    finally:
        os.close(lock_fd)


def _run_locked(
    data_root: Path,
    explicit: Sequence[str],
    exec_start: float,
    clock: Callable[[], int],
    offer: AlertOffer,
) -> int:
    now_ns = clock()  # S3-R26: the lock wait may have been 600 s
    today = dt.datetime.fromtimestamp(now_ns // _NS, tz=dt.UTC).date()
    deadline = min(
        capture_audit_inputs.MONOTONIC() + AUDIT_WORK_BUDGET_S,
        exec_start + AUDIT_EXEC_TIMEOUT_S - AUDIT_MARGIN_S,
    )
    token = DEADLINE.set(deadline)  # once (S3-R41)
    try:
        heal_failures = _run_heal(data_root, now_ns, deadline, offer)
        return _run_families(data_root, explicit, today, now_ns, offer, heal_failures)
    finally:
        DEADLINE.reset(token)


def _run_heal(data_root: Path, now_ns: int, deadline: float, offer: AlertOffer) -> int:
    """Heal runs first, before the family loop and with zero families (S3-R25, S3-R46), under its
    own budget capped by ``DEADLINE``; heal never writes ``DEADLINE``. An overrun is a failure
    (S3-R41), and so is a raise: the family audits still run, and the exit code carries it."""
    heal_deadline = min(capture_audit_inputs.MONOTONIC() + HEAL_BUDGET_S, deadline)
    try:
        return run_heal_duty(
            data_root,
            now_ns=now_ns,
            heal_deadline=heal_deadline,
            sender=_OfferHealSender(offer),
        )
    except Exception:
        _LOGGER.exception("capture audit: the heal duty raised")
        return 1


def _run_families(
    data_root: Path,
    explicit: Sequence[str],
    today: dt.date,
    now_ns: int,
    offer: AlertOffer,
    heal_failures: int,
) -> int:
    families = families_by_construction(data_root, explicit)
    if not families:
        sys.stderr.write("capture audit: no family to audit (no epoch file, no --family-id)\n")
        return 1 if heal_failures else 0
    codes = [run_audit(data_root, f, today, now_ns=now_ns, offer=offer) for f in families]
    once_failures = run_once_duties(data_root, today, now_ns=now_ns, offer=offer)
    return 1 if heal_failures or any(codes) or once_failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the audit; the return value is the process exit code."""
    return _main(argv, offer=_undeliverable_offer, clock=time.time_ns, lock=_default_lock)


if __name__ == "__main__":
    raise SystemExit(main())
