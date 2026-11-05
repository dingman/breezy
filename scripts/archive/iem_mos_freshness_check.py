"""AUD-18: closed-day freshness alert for the nightly IEM MOS refresh.

WHY THIS EXISTS
----------------
`iem_mos_backfill.py --closed-days-lookback N` is self-healing by design: a
missed night heals on the next run, up to `N` nights back. That means a
single missed night is silent by construction -- there is no unit failure to
alert on, because nothing failed. This module closes that gap the same way
`asos_cache_freshness_check.py` closes it for the ASOS refresh: it resolves
the EXACT manifest key the readers need (never re-derived by hand, always
through `iem_mos_window_request`) for the LATEST settled closed UTC day, and
alerts through the shared sink if that key is missing.

**Exact-key, never age-based.** The freshness rule is not "how old is the
newest entry" -- it is "does the manifest have the specific 1-day entry for
day L = (now - CLOSED_DAY_SETTLE_H).date() - 1". A wider entry that merely
SPANS L (the acknowledged wide 2026-09-20..2026-09-27 entry, for example)
does not satisfy it: `resolve_mos_coverage`'s narrowest-wins rule means the
1-day entry is what future reads actually resolve to once it exists, so its
absence is the real gap even while the wide entry still answers reads today.

**No `src/` change beyond reusing the existing sink** (mirrors
`asos_cache_freshness_check.py`'s own constraint): this module lives under
`scripts/archive/`, next to `iem_mos_backfill.py`, and imports
`breezy.runtime.health` unmodified.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Final

# N2: an explicit bootstrap, mirroring asos_cache_freshness_check.py:49,
# rather than relying on sys.path[0] (which is only the script's own
# directory when this module is run directly, never when it is imported).
_THIS_DIR: Final[Path] = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from iem_mos_backfill import (
    CLOSED_DAY_SETTLE_H,
    DEFAULT_MODEL,
    STATIONS,
    default_cache_root,
    settled_day_bound,
)

from breezy.persistence.archive_cache import (
    IEM_MOS_SOURCE,
    ArchiveCache,
    ArchiveCacheManifestError,
)
from breezy.persistence.archive_request import iem_mos_window_request
from breezy.runtime.health import (
    AlertPayload,
    AlertSink,
    emit_alert,
    log_alert_egress_status,
    resolve_alert_sink,
)

__all__ = [
    "IEM_MOS_ARCHIVE_STALE_EVENT",
    "IemMosFreshnessDetail",
    "check_and_alert",
    "latest_closed_day",
    "main",
]

#: The one `AlertPayload.event` this module ever emits.
IEM_MOS_ARCHIVE_STALE_EVENT: Final[str] = "iem_mos_archive_stale"
_SEVERITY_WARN: Final[str] = "WARN"
_GLOBAL_SITE: Final[str] = "global"

_NANOSECONDS_PER_SECOND: Final[int] = 1_000_000_000


class IemMosFreshnessDetail(str, Enum):
    """Closed set of `detail` values -- no path, no station count, no
    timestamp, matching every other alert-detail contract in this repo
    (idiom mirrors `asos_cache_freshness_check.AsosCacheStaleDetail`)."""

    LATEST_CLOSED_DAY_MISSING = "latest_closed_day_missing"
    MANIFEST_MISSING = "manifest_missing"
    MANIFEST_UNREADABLE = "manifest_unreadable"


class _WallClock:
    def timestamp_ns(self) -> int:
        return time.time_ns()


def _refuse_fetch(request: object) -> bytes:
    raise RuntimeError("the freshness check is read-only and never fetches")


def latest_closed_day(clock: object, settle_h: float = CLOSED_DAY_SETTLE_H) -> dt.date:
    """`L` -- the latest UTC day that is BOTH settled and closed.

    One day before `settled_day_bound`: the settled bound is the newest day
    that may be CLAIMED (checked by the window-mode guard); `L` is the newest
    day the nightly closed-day plan actually PRODUCES an entry for (the plan
    runs from `settled_bound - 1` down to `settled_bound - lookback`).
    """
    return settled_day_bound(clock, settle_h) - dt.timedelta(days=1)


def _manifest_path(cache_root: Path) -> Path:
    return cache_root / IEM_MOS_SOURCE / "coverage.json"


def check_and_alert(
    *,
    cache_root: Path,
    stations: Sequence[str],
    model: str,
    latest_day: dt.date,
    sink: AlertSink,
) -> bool:
    """Return True (and emit at least one WARN) iff any station's exact 1-day
    key for `latest_day` is missing, or the manifest is missing/unreadable.

    Never raises: `emit_alert` contains every sink failure by contract.
    """
    manifest_path = _manifest_path(cache_root)
    # The manifest's existence is checked explicitly BEFORE resolving
    # entries: ArchiveCache reads a missing manifest as `{}`
    # (archive_cache.py:435-437), which would otherwise read as "no station is
    # covered" -- true, but for the wrong reason, and indistinguishable from
    # "the archive has never been populated" without this explicit check.
    if not manifest_path.is_file():
        emit_alert(
            sink,
            AlertPayload(
                severity=_SEVERITY_WARN,
                event=IEM_MOS_ARCHIVE_STALE_EVENT,
                site=_GLOBAL_SITE,
                detail=IemMosFreshnessDetail.MANIFEST_MISSING.value,
            ),
        )
        return True

    cache = ArchiveCache(root=cache_root, fetch=_refuse_fetch, clock=_WallClock())
    try:
        entries = cache.entries(IEM_MOS_SOURCE)
    except ArchiveCacheManifestError:
        emit_alert(
            sink,
            AlertPayload(
                severity=_SEVERITY_WARN,
                event=IEM_MOS_ARCHIVE_STALE_EVENT,
                site=_GLOBAL_SITE,
                detail=IemMosFreshnessDetail.MANIFEST_UNREADABLE.value,
            ),
        )
        return True

    covered_keys = {entry.cache_key for entry in entries}
    any_stale = False
    for station in stations:
        # The EXACT 1-day key, never re-derived by hand: a wider entry that
        # merely spans `latest_day` (the acknowledged wide 09-20..09-27
        # entry) has a DIFFERENT cache key and does not satisfy this check.
        request = iem_mos_window_request(
            station, latest_day, latest_day + dt.timedelta(days=1), model
        )
        if request.cache_key() not in covered_keys:
            any_stale = True
            emit_alert(
                sink,
                AlertPayload(
                    severity=_SEVERITY_WARN,
                    event=IEM_MOS_ARCHIVE_STALE_EVENT,
                    site=station,
                    detail=IemMosFreshnessDetail.LATEST_CLOSED_DAY_MISSING.value,
                ),
            )
    return any_stale


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", default=None)
    parser.add_argument("--stations", nargs="+", default=list(STATIONS))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    clock: object | None = None,
) -> int:
    args = _parse_args(argv)
    root = Path(args.cache_root) if args.cache_root else default_cache_root()
    resolved_clock = clock if clock is not None else time.time_ns
    latest_day = latest_closed_day(resolved_clock)
    source: Mapping[str, str] = os.environ if env is None else env
    # Runtime visibility BEFORE resolving the sink -- mirrors
    # asos_cache_freshness_check.main's own call, so a missing/empty
    # alerts.env leaves a distinct journal line every run rather than a
    # silent LoggingAlertSink downgrade.
    log_alert_egress_status(source, component="iem_mos_freshness_check")
    sink = resolve_alert_sink(source)
    stale = check_and_alert(
        cache_root=root,
        stations=tuple(args.stations),
        model=args.model,
        latest_day=latest_day,
        sink=sink,
    )
    print(f"[iem-mos-freshness] latest_closed_day={latest_day} stale={stale}")
    # Always 0: a stale archive is a data-freshness signal, never a unit
    # failure -- routing it through a non-zero exit would fire the ASOS
    # unit's OnFailure= and misclassify staleness as a study crash (mirrors
    # asos_cache_freshness_check.main's own contract). Non-zero only on an
    # unexpected internal exception, which this function does not catch.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
