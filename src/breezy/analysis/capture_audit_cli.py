"""AUT-1 WP5 stage 2b, W3: the ``breezy-capture-audit`` entry point (plan r12 sections 3.11, 3.13).

Stage 3 wires the unit to ``python -m breezy.analysis.capture_audit_cli``. Imports no
``breezy.adapters.*`` module (r12 section 3.11.1).

Order matters (S2-R8): the seam-B bus snapshot is read FIRST, before the launch-window check, any
scan or any lock wait, because the wrapper takes it in ``ExecStartPre`` and it goes stale. Its first
read is cached, so a snapshot error surfaces later as that day's ERROR (``PRE_CAPTURE`` masks it).
Then ``launch_window_guard``: a run whose worst case (``flock -w 600`` plus
``TimeoutStartSec=1500``) would meet [16:30Z, 17:10Z) defers (exit 0, no work).

Families are enumerated by construction: every ``evidence/capture/epoch/<family>.json`` plus each
``--family-id`` given. The exit code is 1 on any ERROR day, failed day or failed delivery, decided
after every write (``run_audit``). The default alert offer reports every alert undelivered (AUT-6's
outbox is not wired, C9), so an audit that has something to say exits 1 and ``OnFailure=`` fires.
"""

import argparse
import datetime as dt
import re
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from breezy.analysis.capture_audit import run_audit
from breezy.analysis.capture_audit_host import read_recorder_props
from breezy.analysis.capture_audit_inputs import list_names
from breezy.analysis.capture_audit_model import AuditInputError
from breezy.analysis.capture_settlement import AlertOffer
from breezy.persistence.autonomy.capture_epoch import epoch_relative_path
from breezy.persistence.autonomy.capture_schedule import launch_window_guard
from breezy.persistence.autonomy.paths import FAMILY_RE, default_data_root

__all__ = ["FLOCK_WAIT_S", "TIMEOUT_START_S", "families_by_construction", "main"]

FLOCK_WAIT_S: Final[int] = 600
TIMEOUT_START_S: Final[int] = 1500
_NS: Final[int] = 10**9
_EPOCH_FILE_RE: Final[re.Pattern[str]] = re.compile(r"\A(?P<family>[a-z0-9_]{1,64})\.json\Z")


def _undeliverable_offer(event: str, severity: str, detail: str) -> bool:
    sys.stderr.write(f"{severity} {event} {detail} (undelivered: no outbox wired)\n")
    sys.stderr.flush()
    return False


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


def _main(argv: Sequence[str] | None, *, offer: AlertOffer, clock: Callable[[], int]) -> int:
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
    today = dt.datetime.fromtimestamp(now_ns // _NS, tz=dt.UTC).date()
    families = families_by_construction(data_root, args.families)
    if not families:
        sys.stderr.write("capture audit: no family to audit (no epoch file, no --family-id)\n")
        return 0
    codes = [run_audit(data_root, f, today, now_ns=now_ns, offer=offer) for f in families]
    return 1 if any(codes) else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the audit; the return value is the process exit code."""
    return _main(argv, offer=_undeliverable_offer, clock=time.time_ns)


if __name__ == "__main__":
    raise SystemExit(main())
