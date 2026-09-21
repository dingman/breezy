"""AUD-15 re-home: freshness check for the `--since`-anchored ASOS refresh.

WHY THIS EXISTS
----------------
`asos_recent_refresh.py --since <ASOS_FETCH_START>` is fail-soft by design
(module docstring): a per-site fetch shortfall is logged and `main()` still
returns 0. That is correct for the refresh itself, but it means a systemd
`OnFailure=` alert (AUD-15a) can never fire on a night the refresh silently
writes nothing useful -- the unit still exits 0.

The consumer this refresh feeds is NOT fail-soft:
`current_rung_hold_monitor_hypothetical_hold._load_observations_for_station`
raises a hard `SystemExit` on a cache miss for the CURRENT UTC day's key
(`:169-170`), and `current_rung_hold_exit_window_study.py` (default
`--obs-source cache`) reports a missing input the same way. This module
closes that gap: it resolves the SAME cache key the consumer reads --
never re-derived by hand, always through `settlement_alignment_study`'s own
`asos_url`/`cache_path_for_url` -- and alerts through the shared sink
(`breezy.runtime.health`) 90 minutes before the first consumer runs, on
every scheduled invocation, whether or not the refresh itself ran.

**Epoch-mtime, never existence alone.** The cache key hashes a URL that
carries BOTH the fixed `ASOS_FETCH_START` anchor and today's date
(`ASOS_FETCH_END = default_asos_fetch_end() = date.today()`), so the key
ROTATES every UTC day: a file resolved under today's key can only ever have
been written today. "Missing" is therefore the dominant failure signal, but
the mtime leg is what keeps the rule correct if the key ever stops rotating
(an anchor change) -- see
`docs/plans/backlog/AUDIT_2026-09-21/AUD-15-failing-study-units-fix-or-retire-and-alert.md`
§6 for the full derivation, including why a fixed hour threshold (an
earlier revision's `36h`) is dead code on a key that rotates daily.

**No `src/` change beyond reusing the existing sink** (the plan's own
constraint on 15b/15c): this module lives under `scripts/analysis/`, next to
every other study driver, and imports `breezy.runtime.health` unmodified.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ma_prelock_winner_ask_study import ASOS_FETCH_START, default_asos_fetch_end
from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
from settlement_alignment_study import SiteSpec, asos_url, cache_path_for_url, load_sites

from breezy.runtime.health import (
    AlertPayload,
    AlertSink,
    emit_alert,
    log_alert_egress_status,
    resolve_alert_sink,
)

__all__ = [
    "ASOS_CACHE_STALE_ALERT_EVENT",
    "ASOS_CACHE_STALE_ALERT_SEVERITY",
    "ASOS_CACHE_STALE_ALERT_SITE",
    "AsosCacheStaleDetail",
    "check_and_alert",
    "main",
    "resolve_consumer_cache_paths",
    "stale_paths",
]

#: The one `AlertPayload.event` this module ever emits.
ASOS_CACHE_STALE_ALERT_EVENT: Final[str] = "asos_cache_stale"

#: WARN: the refresh ran (or was skipped for a known reason) and the unit
#: still exits 0 -- this is a data-freshness signal, never a unit failure,
#: so it must never be folded into 15a's `study_unit_failed` enum.
ASOS_CACHE_STALE_ALERT_SEVERITY: Final[str] = "WARN"

ASOS_CACHE_STALE_ALERT_SITE: Final[str] = "global"


class AsosCacheStaleDetail(str, Enum):
    """Closed set of ``detail`` values -- no path, no count, no timestamp,
    matching every other alert-detail contract in this repo."""

    CONSUMER_CACHE_KEY_MISSING_OR_STALE_TODAY = "consumer_cache_key_missing_or_stale_today"


def resolve_consumer_cache_paths(
    *,
    cache_dir: Path,
    sites: Sequence[SiteSpec],
    fetch_start: dt.date,
    fetch_end: dt.date,
) -> tuple[Path, ...]:
    """The exact cache path(s) the live-path consumer resolves for today's
    window, one per site -- via the consumer's own key-building helpers
    (`asos_url` + `cache_path_for_url`), never re-derived by hand."""
    return tuple(
        cache_path_for_url(cache_dir, asos_url(spec.iem_asos_id, fetch_start, fetch_end), ".txt")
        for spec in sites
    )


def _is_stale(path: Path, *, now: dt.datetime) -> bool:
    """Missing, or an epoch mtime before 00:00:00Z of `now`'s UTC date."""
    if not path.exists():
        return True
    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
    today_start = dt.datetime.combine(now.date(), dt.time.min, tzinfo=dt.UTC)
    return mtime < today_start


def stale_paths(paths: Sequence[Path], *, now: dt.datetime) -> tuple[Path, ...]:
    return tuple(path for path in paths if _is_stale(path, now=now))


def check_and_alert(
    *,
    cache_dir: Path,
    sites: Sequence[SiteSpec],
    fetch_start: dt.date,
    fetch_end: dt.date,
    now: dt.datetime,
    sink: AlertSink,
) -> bool:
    """Return True (and emit exactly one WARN) iff any site's resolved
    consumer cache path is stale, OR `sites` is empty. Never raises:
    `emit_alert` contains every sink failure by contract.

    **An empty `sites` list is treated as stale, never a vacuous pass**
    (AUD-15 amendment, folded review finding D-iv): `load_sites()` returning
    nothing would otherwise make `stale_paths` iterate zero paths and report
    `False` -- "everything is fresh" when in fact nothing was checked at
    all. That is a worse silent failure than a stale cache, so it alerts
    identically.
    """
    if not sites:
        emit_alert(
            sink,
            AlertPayload(
                severity=ASOS_CACHE_STALE_ALERT_SEVERITY,
                event=ASOS_CACHE_STALE_ALERT_EVENT,
                site=ASOS_CACHE_STALE_ALERT_SITE,
                detail=AsosCacheStaleDetail.CONSUMER_CACHE_KEY_MISSING_OR_STALE_TODAY.value,
            ),
        )
        return True
    paths = resolve_consumer_cache_paths(
        cache_dir=cache_dir, sites=sites, fetch_start=fetch_start, fetch_end=fetch_end
    )
    stale = stale_paths(paths, now=now)
    if stale:
        emit_alert(
            sink,
            AlertPayload(
                severity=ASOS_CACHE_STALE_ALERT_SEVERITY,
                event=ASOS_CACHE_STALE_ALERT_EVENT,
                site=ASOS_CACHE_STALE_ALERT_SITE,
                detail=AsosCacheStaleDetail.CONSUMER_CACHE_KEY_MISSING_OR_STALE_TODAY.value,
            ),
        )
    return bool(stale)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir", default=DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR.as_posix()
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    args = _parse_args(argv)
    cache_dir = Path(args.cache_dir)
    now = dt.datetime.now(dt.UTC)
    source: Mapping[str, str] = os.environ if env is None else env
    # AUD-15 amendment (2026-09-22): runtime visibility BEFORE resolving the
    # sink -- see study_failure_notifier.py's identical call for the full
    # rationale (a missing/empty alerts.env must leave a distinct journal
    # line every run, not just a silent LoggingAlertSink downgrade).
    log_alert_egress_status(source, component="asos_cache_freshness_check")
    sink = resolve_alert_sink(source)
    stale = check_and_alert(
        cache_dir=cache_dir,
        sites=load_sites(),
        fetch_start=ASOS_FETCH_START,
        fetch_end=default_asos_fetch_end(today=now.date()),
        now=now,
        sink=sink,
    )
    print(f"[asos-cache-freshness] stale={stale}")
    # Always 0: this is a data-freshness signal, never a unit failure (see
    # module docstring -- routing this through a non-zero exit would fire
    # 15a's OnFailure= and misclassify a stale cache as a study crash).
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
