"""``breezy-capture-settlement``: the settlement writer's entry point (plan r12 3.12, 3.13).

Runs ``capture_settlement.run_settlement`` for one venue at 13:35Z. It reads the already-ingested
NWS catalog and writes only under ``--decisions-dir``; it needs no network (r12 section 3.12 bind
set: ``<decisions_dir>``, ``evidence/alerts/``, plus a READ-ONLY bind of the catalog base).

* Defers (exit 0, no work) when its worst-case span, ``FLOCK_WAIT_S + TIMEOUT_START_S`` from now,
  meets the launch window [16:30Z, 17:10Z) (``launch_window_guard``).
* Exits 1 after its durable work when any station-day errored, when an alert was not accepted by
  the outbox, or when the lock is busy (r12 section 3.13, "Exit status on a failed delivery").
* The alert seam is ``offer(event, severity, detail) -> accepted``. Until the AUT-6 outbox is wired
  in (WP8), the default offer logs to stderr and reports the alert undelivered, so an error is
  never silent.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from breezy.analysis.capture_settlement import (
    AlertOffer,
    SettlementLockBusy,
    SettlementSite,
    run_settlement,
    venue_sites,
)
from breezy.persistence.autonomy.capture_schedule import launch_window_guard
from breezy.registry.sites import default_registry

__all__ = ["FLOCK_WAIT_S", "TIMEOUT_START_S", "main"]

FLOCK_WAIT_S: Final[int] = 30
TIMEOUT_START_S: Final[int] = 300
DEFAULT_VENUE: Final[str] = "polymarket_us"
CATALOG_BASE_ENV: Final[str] = "BREEZY_CATALOG_BASE"
_NS: Final[int] = 10**9


def _undeliverable_offer(event: str, severity: str, detail: str) -> bool:
    sys.stderr.write(f"{severity} {event} {detail} (undelivered: no outbox wired)\n")
    sys.stderr.flush()
    return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="breezy-capture-settlement")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--decisions-dir", type=Path, required=True)
    parser.add_argument("--catalog-base", type=Path, default=None)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    offer: AlertOffer = _undeliverable_offer,
    clock: Callable[[], int] = time.time_ns,
    sites: Sequence[SettlementSite] | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    source = os.environ if env is None else env
    catalog_base = args.catalog_base or (
        Path(source[CATALOG_BASE_ENV]) if source.get(CATALOG_BASE_ENV) else None
    )
    if catalog_base is None:
        parser.error(f"--catalog-base or {CATALOG_BASE_ENV} is required")
    now_ns = clock()
    if not launch_window_guard(now_ns, FLOCK_WAIT_S, TIMEOUT_START_S):
        sys.stderr.write("capture settlement deferred: the run would meet the launch window\n")
        return 0
    today = dt.datetime.fromtimestamp(now_ns / _NS, tz=dt.UTC).date()
    venue_set = tuple(sites) if sites is not None else venue_sites(default_registry(), args.venue)
    try:
        result = run_settlement(
            venue=args.venue,
            today=today,
            decisions_dir=args.decisions_dir,
            catalog_base=catalog_base,
            sites=venue_set,
            offer=offer,
        )
    except SettlementLockBusy:
        sys.stderr.write("capture settlement: another run holds the lock\n")
        return 1
    sys.stderr.write(
        f"capture settlement: appended={result.appended} already={result.already_present} "
        f"pending={result.pending} errors={len(result.errors)} "
        f"delivery_failed={result.delivery_failed}\n"
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
