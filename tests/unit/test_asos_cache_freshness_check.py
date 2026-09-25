"""AUD-15 §7 step 7c(i)/(iii) -- `asos_cache_freshness_check.py`'s stale
detection and its no-false-alarm boundary.

(i) a resolved cache path that is missing, or whose mtime predates
    00:00:00Z of the current UTC day, produces exactly one WARN.
(iii) a resolved path whose mtime is today but earlier than the
    invocation (the legitimate `--obs-source fetch` same-day write,
    `current_rung_hold_exit_window_study.py:16-24`) produces NO WARN --
    pinning the current-UTC-day boundary against a tighter "later than
    this run's start" rule that would false-alarm.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import sys
from pathlib import Path
from typing import Final

import pytest

_SCRIPTS_ANALYSIS_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from asos_cache_freshness_check import (
    ASOS_CACHE_STALE_ALERT_EVENT,
    ASOS_CACHE_STALE_ALERT_SEVERITY,
    AsosCacheStaleDetail,
    check_and_alert,
    resolve_consumer_cache_paths,
    stale_paths,
)
from settlement_alignment_study import SiteSpec

_SITE: Final[SiteSpec] = SiteSpec(
    city="Testville", site=object(), std_utc_offset_hours=-6.0, iem_asos_id="TST"  # type: ignore[arg-type]
)
_OTHER_SITE: Final[SiteSpec] = SiteSpec(
    city="Otherville", site=object(), std_utc_offset_hours=-5.0, iem_asos_id="OTR"  # type: ignore[arg-type]
)
_FETCH_START: Final[dt.date] = dt.date(2026, 8, 30)
_FETCH_END: Final[dt.date] = dt.date(2026, 9, 22)
_NOW: Final[dt.datetime] = dt.datetime(2026, 9, 22, 13, 30, tzinfo=dt.UTC)


class _RecordingSink:
    def __init__(self) -> None:
        self.emitted: list[object] = []

    def emit(self, payload: object) -> None:
        self.emitted.append(payload)


def test_the_asos_refresh_wrapper_alerts_on_a_stale_consumer_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    sink = _RecordingSink()

    stale = check_and_alert(
        cache_dir=cache_dir, sites=(_SITE,), fetch_start=_FETCH_START, fetch_end=_FETCH_END,
        now=_NOW, sink=sink,
    )

    assert stale is True
    assert len(sink.emitted) == 1
    payload = sink.emitted[0]
    assert payload.severity == ASOS_CACHE_STALE_ALERT_SEVERITY == "WARN"
    assert payload.event == ASOS_CACHE_STALE_ALERT_EVENT == "asos_cache_stale"
    assert payload.detail == AsosCacheStaleDetail.CONSUMER_CACHE_KEY_MISSING_OR_STALE_TODAY.value


def test_the_staleness_check_is_quiet_when_the_key_was_written_earlier_today(
    tmp_path: Path,
) -> None:
    from asos_cache_freshness_check import resolve_consumer_cache_paths

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    paths = resolve_consumer_cache_paths(
        cache_dir=cache_dir, sites=(_SITE,), fetch_start=_FETCH_START, fetch_end=_FETCH_END
    )
    path = paths[0]
    path.write_bytes(b"fetched earlier today, e.g. --obs-source fetch")
    earlier_today = _NOW.replace(hour=6, minute=0, second=0, microsecond=0).timestamp()
    os.utime(path, (earlier_today, earlier_today))

    sink = _RecordingSink()
    stale = check_and_alert(
        cache_dir=cache_dir, sites=(_SITE,), fetch_start=_FETCH_START, fetch_end=_FETCH_END,
        now=_NOW, sink=sink,
    )

    assert stale is False
    assert sink.emitted == []


def test_an_empty_site_list_is_treated_as_stale_not_a_vacuous_pass(tmp_path: Path) -> None:
    """AUD-15 amendment, folded review finding D-iv: `load_sites()`
    returning nothing must never read as "everything is fresh" -- that is a
    worse silent failure than a genuinely stale cache."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    sink = _RecordingSink()

    stale = check_and_alert(
        cache_dir=cache_dir, sites=(), fetch_start=_FETCH_START, fetch_end=_FETCH_END,
        now=_NOW, sink=sink,
    )

    assert stale is True
    assert len(sink.emitted) == 1
    payload = sink.emitted[0]
    assert payload.severity == ASOS_CACHE_STALE_ALERT_SEVERITY
    assert payload.event == ASOS_CACHE_STALE_ALERT_EVENT
    assert payload.detail == AsosCacheStaleDetail.CONSUMER_CACHE_KEY_MISSING_OR_STALE_TODAY.value


def test_the_check_flags_one_stale_station_while_another_is_fresh(tmp_path: Path) -> None:
    """AUD-25 asos-429 fix (2026-09-25, production evidence: NYC fetched
    while SFO/MIA/MDW/LAX all 429'd): `resolve_consumer_cache_paths`
    already resolves ONE path per site in `sites`, and `check_and_alert`
    already alerts if ANY of them is stale -- this pins that the check is
    genuinely per-station, not a single aggregate key that could mask a
    4-of-5 shortfall as a pass, by giving one site a fresh cache and the
    other none at all.
    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    paths = resolve_consumer_cache_paths(
        cache_dir=cache_dir, sites=(_SITE, _OTHER_SITE), fetch_start=_FETCH_START,
        fetch_end=_FETCH_END,
    )
    fresh_path, stale_path = paths
    fresh_path.write_bytes(b"fetched today")
    fresh_today = _NOW.replace(hour=6, minute=0, second=0, microsecond=0).timestamp()
    os.utime(fresh_path, (fresh_today, fresh_today))
    # `stale_path` (the second site's) is never written -- the exact shape
    # of a station that 429'd every attempt.

    assert stale_paths(paths, now=_NOW) == (stale_path,)

    sink = _RecordingSink()
    stale = check_and_alert(
        cache_dir=cache_dir, sites=(_SITE, _OTHER_SITE), fetch_start=_FETCH_START,
        fetch_end=_FETCH_END, now=_NOW, sink=sink,
    )
    assert stale is True
    assert len(sink.emitted) == 1


def test_main_logs_alert_egress_status_before_resolving_the_sink(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AUD-15 amendment A-2: the runtime visibility call must fire on every
    invocation, before the sink is resolved -- a missing/empty alerts.env
    must leave a distinct journal line, not a silent LoggingAlertSink
    downgrade. Asserted against the exact log line
    `breezy.runtime.health.log_alert_egress_status` emits when no webhook is
    configured, which this bare env (no `BREEZY_ALERT_WEBHOOK_URL`) triggers."""
    from asos_cache_freshness_check import main

    with caplog.at_level(logging.WARNING, logger="breezy.runtime.health"):
        exit_code = main(["--cache-dir", "/nonexistent-for-this-test"], env={})

    assert exit_code == 0
    assert any(
        "NO alert egress is configured" in record.getMessage() for record in caplog.records
    )
