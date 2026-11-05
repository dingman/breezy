"""AUT-1 WP5 stage 3, S2: the ``breezy-capture-live-proof`` entry point (design r3 D8; plan r12
sections 3.11.5 and 6).

For each family the run publishes the live-proof roll-up and then runs the two duties the audit's
watchdog used to run for the audit unit (r8 H7: each check is its own ``try``, so one failing check
never hides the others):

* the dead-man: the family's newest AUDIT file is older than 26 h (``CAPTURE_AUDIT_DEADMAN``). It
  reads the audit file, never the C4 HEALTH verdict, which is skipped while the producer is
  unpinned (F17);
* the missing-file check: an audit file exists for each of the last 8 elapsed days
  (``CAPTURE_AUDIT_FILE_MISSING``).

Each alert is sent at most once per ``asof``. The unit runs twice a day (``OnSuccess=`` of the
audit and a 14:35Z fallback timer), so a write-once marker
``live_proof/sent/<asof>/<event>_<family>.json`` records an ACCEPTED offer, and only then. An offer
that was refused leaves no marker and is offered again by the next run. A failed delivery exits 1.

The roll-up, ``live_proof_<family>_<asof>.json``, is written through ``replace_atomic`` at 0444
and is replaced by every run (its mtime is what the audit's ``CAPTURE_LIVE_PROOF_STALE`` reads). A
run whose worst case would meet the launch window [16:30Z, 17:10Z) defers: exit 0, no work.

The closure is lean on purpose: no ``breezy.adapters.*``, no HTTP client and no Nautilus (the unit's
``MemoryMax`` is 256M). It therefore does not import ``capture_audit_cli``; the family listing below
is that module's, restated. The default offer reports every alert undelivered (AUT-6's outbox is not
wired until stage 4), so a run that has an alert to send exits 1 and ``OnFailure=`` fires.
"""

import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from breezy.analysis.capture_audit_io import list_names, read_file
from breezy.analysis.capture_audit_model import AUDIT_DIR_REL, BACKFILL_DAYS
from breezy.analysis.capture_live_proof import build_live_proof, newest_audit_by_day
from breezy.persistence.autonomy.capture_alerts import severity_for
from breezy.persistence.autonomy.capture_epoch import epoch_relative_path
from breezy.persistence.autonomy.capture_schedule import launch_window_guard
from breezy.persistence.autonomy.paths import FAMILY_RE, default_data_root, family_component
from breezy.persistence.autonomy.single_read import (
    SingleReadReason,
    SingleReadRefused,
    ensure_dir,
    open_root,
    replace_atomic,
    walk_dirs,
    write_once,
)

__all__ = [
    "DEADMAN_EVENT",
    "DEADMAN_MAX_AGE_H",
    "FILE_MISSING_EVENT",
    "FLOCK_WAIT_S",
    "LIVE_PROOF_DIR_REL",
    "TIMEOUT_START_S",
    "main",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
#: The unit's ``flock -w 30`` and ``TimeoutStartSec=300`` (r3 section 1, E-9 table).
FLOCK_WAIT_S: Final[int] = 30
TIMEOUT_START_S: Final[int] = 300
#: An audit verdict younger than this must exist (plan section 3.11.5).
DEADMAN_MAX_AGE_H: Final[int] = 26
DEADMAN_EVENT: Final[str] = "CAPTURE_AUDIT_DEADMAN"
FILE_MISSING_EVENT: Final[str] = "CAPTURE_AUDIT_FILE_MISSING"
LIVE_PROOF_DIR_REL: Final[tuple[str, ...]] = ("evidence", "capture", "live_proof")
_SENT_DIR: Final[str] = "sent"
_ROLLUP_MODE: Final[int] = 0o444
_MARKER_MODE: Final[int] = 0o444
_NS: Final[int] = 1_000_000_000
_HOUR_NS: Final[int] = 3600 * _NS
_EPOCH_FILE_RE: Final[re.Pattern[str]] = re.compile(r"\A(?P<family>[a-z0-9_]{1,64})\.json\Z")
AlertOffer = Callable[[str, str, str], bool]


def _undeliverable_offer(event: str, severity: str, detail: str) -> bool:
    sys.stderr.write(f"{severity} {event} {detail} (undelivered: no outbox wired)\n")
    sys.stderr.flush()
    return False


def _families(data_root: Path, explicit: Sequence[str]) -> tuple[str, ...]:
    """Each epoch file's family and each explicitly named one (``capture_audit_cli``'s rule)."""
    *parent, _name = epoch_relative_path("x")
    found = {
        match["family"]
        for name in list_names(data_root, parent)
        if (match := _EPOCH_FILE_RE.fullmatch(name)) is not None
    }
    found.update(explicit)
    return tuple(sorted(found))


# -- the audit directory -----------------------------------------------------------------------


def _audit_rel(family_id: str) -> tuple[str, ...]:
    return (*AUDIT_DIR_REL.split("/"), family_component(family_id))


def _newest_audit_mtime_ns(data_root: Path, family_id: str) -> int:
    """The newest mtime over the family's NEWEST audit file of each day; 0 when there is none."""
    rootfd = open_root(data_root)
    try:
        try:
            dirfd = walk_dirs(rootfd, _audit_rel(family_id))
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return 0
            raise
    finally:
        os.close(rootfd)
    try:
        names = newest_audit_by_day(sorted(os.listdir(dirfd))).values()
        return max(
            (os.stat(name, dir_fd=dirfd, follow_symlinks=False).st_mtime_ns for name in names),
            default=0,
        )
    finally:
        os.close(dirfd)


def _missing_audit_days(data_root: Path, family_id: str, asof: dt.date) -> list[dt.date]:
    """The days of ``[asof - 8, asof - 1]`` with no audit file, oldest first."""
    present = newest_audit_by_day(list_names(data_root, _audit_rel(family_id)))
    window = (asof - dt.timedelta(days=back) for back in range(BACKFILL_DAYS, 0, -1))
    return [day for day in window if day not in present]


# -- delivery, at most once per asof -----------------------------------------------------------


class _Sender:
    """Offers an alert once per ``(asof, event, family)`` and counts the failed deliveries."""

    def __init__(self, data_root: Path, offer: AlertOffer) -> None:
        self._root = data_root
        self._offer = offer
        self.failed = 0

    def _rel(self, asof: dt.date) -> tuple[str, ...]:
        return (*LIVE_PROOF_DIR_REL, _SENT_DIR, asof.isoformat())

    def send_once(self, asof: dt.date, event: str, family_id: str, detail: str) -> None:
        name = f"{event}_{family_id}.json"
        if read_file(self._root, self._rel(asof), name) is not None:
            return  # an earlier run of this asof already had it accepted
        try:
            accepted = bool(self._offer(event, severity_for(event), detail))
        except Exception:  # noqa: BLE001 - an outbox failure is a failed delivery, not a crash
            accepted = False
        if not accepted:
            self.failed += 1
            _LOGGER.error("capture live proof: %s undelivered", event)
            return
        self._mark(asof, name, event, family_id)

    def _mark(self, asof: dt.date, name: str, event: str, family_id: str) -> None:
        rel = self._rel(asof)
        body = {"event": event, "family_id": family_id, "asof": asof.isoformat()}
        rootfd = open_root(self._root)
        try:
            os.close(ensure_dir(rootfd, rel))
        finally:
            os.close(rootfd)
        data = (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode()
        write_once(self._root.joinpath(*rel, name), data, root=self._root, mode=_MARKER_MODE)


# -- one family ----------------------------------------------------------------------------------


def _publish_rollup(data_root: Path, family_id: str, asof: dt.date) -> None:
    document = build_live_proof(data_root, family_id, asof)
    data = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    rootfd = open_root(data_root)
    try:
        os.close(ensure_dir(rootfd, LIVE_PROOF_DIR_REL))
    finally:
        os.close(rootfd)
    path = data_root.joinpath(
        *LIVE_PROOF_DIR_REL, f"live_proof_{family_id}_{asof.isoformat()}.json"
    )
    replace_atomic(path, data, root=data_root, mode=_ROLLUP_MODE)


def _check_deadman(
    data_root: Path, family_id: str, asof: dt.date, now_ns: int, sender: _Sender
) -> None:
    newest = _newest_audit_mtime_ns(data_root, family_id)
    if newest == 0 or now_ns - newest > DEADMAN_MAX_AGE_H * _HOUR_NS:
        sender.send_once(asof, DEADMAN_EVENT, family_id, f"family={family_id}")


def _check_file_missing(data_root: Path, family_id: str, asof: dt.date, sender: _Sender) -> None:
    missing = _missing_audit_days(data_root, family_id, asof)
    if missing:
        days = ",".join(day.isoformat() for day in missing)
        sender.send_once(asof, FILE_MISSING_EVENT, family_id, f"family={family_id} days={days}")


def _run_family(
    data_root: Path, family_id: str, asof: dt.date, now_ns: int, sender: _Sender
) -> int:
    """The roll-up, then each duty in its own ``try``; returns the number that failed."""
    steps: tuple[tuple[str, Callable[[], None]], ...] = (
        ("rollup", lambda: _publish_rollup(data_root, family_id, asof)),
        ("deadman", lambda: _check_deadman(data_root, family_id, asof, now_ns, sender)),
        ("file_missing", lambda: _check_file_missing(data_root, family_id, asof, sender)),
    )
    failures = 0
    for name, step in steps:
        try:
            step()
        except Exception:
            _LOGGER.exception("capture live proof: %s failed for %s", name, family_id)
            failures += 1
    return failures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="breezy-capture-live-proof")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--family-id", action="append", default=[], dest="families")
    return parser


def _main(argv: Sequence[str] | None, *, offer: AlertOffer, clock: Callable[[], int]) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if any(FAMILY_RE.fullmatch(f) is None for f in args.families):
        parser.error("--family-id must match [a-z0-9_]{1,64}")
    data_root = args.data_root if args.data_root is not None else default_data_root()
    now_ns = clock()
    if not launch_window_guard(now_ns, FLOCK_WAIT_S, TIMEOUT_START_S):
        sys.stderr.write("capture live proof deferred: the run would meet the launch window\n")
        return 0
    asof = dt.datetime.fromtimestamp(now_ns // _NS, tz=dt.UTC).date()
    families = _families(data_root, args.families)
    if not families:
        sys.stderr.write("capture live proof: no family (no epoch file, no --family-id)\n")
        return 0
    sender = _Sender(data_root, offer)
    failed = sum(_run_family(data_root, f, asof, now_ns, sender) for f in families)
    failed += sender.failed
    sys.stderr.write(f"capture live proof: families={len(families)} failures={failed}\n")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the live-proof unit; the return value is the process exit code."""
    return _main(argv, offer=_undeliverable_offer, clock=time.time_ns)


if __name__ == "__main__":
    raise SystemExit(main())
