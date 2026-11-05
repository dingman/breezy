"""Producer staleness ``#26 aut6.producer_stale`` and daily-verdict absence ``#27`` (plan r15
sections 3.4.2, 3.4.4 and 3.11; WP3 S5).

#26 FAILs on an intraday heartbeat older than 900 s, on ``fold_ok=false`` and, inside
``[17:05Z, 01:00Z)``, on any (subject, intraday detector) without a verdict whose ``valid_until_ns``
is in the future. #27 FAILs when a subject's newest daily verdict is older than 30 h, carrying the
daily skip records (``last_skip_reason``, ``skips_since_last_verdict``); the first skip of a UTC day
is a WARNING. The verdict readers belong to WP6/WP7 and are injected: a reader that is not wired
makes the pass UNKNOWN, never a silent pass.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Protocol

from breezy.persistence.autonomy.detector_catalog import CATALOG
from breezy.runtime.monitor_watch_model import (
    NS,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    DetectorResult,
    Outcome,
    WatchFinding,
)

DETECTOR_PRODUCER: Final = "aut6.producer_stale"
DETECTOR_DAILY: Final = "aut6.daily_verdict_absent"
PRODUCER_HEARTBEAT_STALE_S: Final = 900
DAILY_VERDICT_STALE_S: Final = 30 * 3600
WINDOW_START_S: Final = 17 * 3600 + 5 * 60
WINDOW_END_S: Final = 1 * 3600
HEARTBEAT_RELPATH: Final = "derived/verdicts/.aut6-intraday.heartbeat"
SKIPS_RELDIR: Final = "derived/verdicts/_aut6_daily_skips"
_MAX_JSON_BYTES: Final = 65_536
_MAX_LISTED: Final = 5
REASON_UNWIRED: Final = "producer_reader_unwired"
#: Clock skew tolerated before a heartbeat stamped in the future is a finding.
HEARTBEAT_FUTURE_SLACK_S: Final = 60
VERDICTS_RELDIR: Final = "derived/verdicts"
_DAY_DIR_RE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_VERDICTS_READ_PER_FAMILY: Final = 20
_CADENCE_BY_DETECTOR: Final = {row.id: row.cadence for row in CATALOG}
PRODUCER_CADENCES: Final = frozenset({"intraday", "daily"})


class ReaderUnwired(Exception):
    """The WP6/WP7 verdict reader is not wired into this source."""


class ProducerSource(Protocol):
    def heartbeat(self) -> Mapping[str, Any] | None:
        """The intraday heartbeat; ``None`` when absent. Raises ``OSError``/``ValueError``."""

    def missing_intraday(self, now_ns: int) -> Sequence[str]:
        """``subject/detector`` of every pair with no verdict valid at ``now_ns``."""

    def newest_daily_verdict_ns(self) -> Mapping[str, int]:
        """Subject to the ``produced_at_ns`` of its newest daily verdict."""

    def daily_skips(self) -> Sequence[Mapping[str, Any]]:
        """The daily skip records ``{ts_ns, slot, reason}``. Raises ``OSError``/``ValueError``."""


def _read_json(path: Path) -> Mapping[str, Any]:
    with path.open("rb") as handle:
        raw = handle.read(_MAX_JSON_BYTES + 1)
    if len(raw) > _MAX_JSON_BYTES:
        raise ValueError("record too large")
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise TypeError("record is not an object")
    return body


class FileProducerSource:
    """Heartbeat and skip records from the data root; the verdict readers are injected."""

    def __init__(
        self,
        data_root: Path,
        *,
        missing: Callable[[int], Sequence[str]] | None = None,
        daily: Callable[[], Mapping[str, int]] | None = None,
    ) -> None:
        self._root = data_root
        self._missing = missing
        self._daily = daily

    def heartbeat(self) -> Mapping[str, Any] | None:
        try:
            return _read_json(self._root / HEARTBEAT_RELPATH)
        except FileNotFoundError:
            return None

    @property
    def intraday_reader_wired(self) -> bool:
        return self._missing is not None

    @property
    def daily_reader_wired(self) -> bool:
        return self._daily is not None

    def missing_intraday(self, now_ns: int) -> Sequence[str]:
        if self._missing is None:
            raise ReaderUnwired
        return self._missing(now_ns)

    def newest_daily_verdict_ns(self) -> Mapping[str, int]:
        if self._daily is None:
            raise ReaderUnwired
        return self._daily()

    def daily_skips(self) -> Sequence[Mapping[str, Any]]:
        directory = self._root / SKIPS_RELDIR
        try:
            names = sorted(os.listdir(directory))
        except FileNotFoundError:
            return []
        return [_read_json(directory / n) for n in names if n.endswith(".json")]


def scan_verdict_cadences(data_root: Path) -> frozenset[str]:
    """Which producers have left verdict files: ``intraday`` and/or ``daily``.

    The newest day directory of every family directory is sampled (the health pass's own
    ``_host`` verdicts and the ``_aut6_*`` state are skipped) and each verdict's ``detector`` is
    looked up in the catalogue for its cadence. A missing verdict root is no evidence; any other
    listing error raises ``OSError`` so the caller can fail closed.
    """
    root = data_root / VERDICTS_RELDIR
    try:
        families = sorted(p for p in root.iterdir() if p.is_dir() and p.name[0] not in "._")
    except FileNotFoundError:
        return frozenset()
    found: set[str] = set()
    for family in families:
        days = sorted(p.name for p in family.iterdir() if _DAY_DIR_RE.fullmatch(p.name))
        if not days:
            continue
        newest = family / days[-1]
        for name in sorted(os.listdir(newest))[:_VERDICTS_READ_PER_FAMILY]:
            try:
                detector = _read_json(newest / name).get("detector")
            except (OSError, ValueError, TypeError):
                continue  # one unreadable file is not the absence of evidence from the others
            cadence = _CADENCE_BY_DETECTOR.get(str(detector))
            if cadence in PRODUCER_CADENCES:
                found.add(str(cadence))
    return frozenset(found)


def in_decision_window(second_of_day: int) -> bool:
    return second_of_day >= WINDOW_START_S or second_of_day < WINDOW_END_S


def _finding(
    detector: str, kind: str, severity: str, today: str, detail: str, metrics: Mapping[str, str]
) -> WatchFinding:
    return WatchFinding(detector, kind, "_host", severity, f"{kind}-{today}", detail, dict(metrics))


def evaluate_producer(
    source: ProducerSource, *, now_ns: int, today: str, enabled_since_ns: int | None = None
) -> DetectorResult:
    unknown: list[str] = []
    findings: list[WatchFinding] = []
    try:
        beat = source.heartbeat()
    except (OSError, ValueError):
        return DetectorResult(
            DETECTOR_PRODUCER, Outcome.INCONCLUSIVE, (), {}, ("producer_heartbeat_unreadable",)
        )
    if beat is None:
        if (
            enabled_since_ns is not None
            and now_ns - enabled_since_ns < PRODUCER_HEARTBEAT_STALE_S * NS
        ):
            return DetectorResult(
                DETECTOR_PRODUCER, Outcome.INCONCLUSIVE, (), {"unknown_reason": "heartbeat_pending"}
            )
        findings.append(
            _finding(
                DETECTOR_PRODUCER,
                "producer_heartbeat_missing",
                SEVERITY_CRITICAL,
                today,
                "intraday heartbeat absent",
                {},
            )
        )
    else:
        stamp, fold_ok = beat.get("ts_ns"), beat.get("fold_ok")
        if type(stamp) is not int or not isinstance(fold_ok, bool):
            return DetectorResult(
                DETECTOR_PRODUCER, Outcome.INCONCLUSIVE, (), {}, ("producer_heartbeat_unreadable",)
            )
        age_s = (now_ns - stamp) // NS
        if -age_s > HEARTBEAT_FUTURE_SLACK_S:
            findings.append(
                _finding(
                    DETECTOR_PRODUCER,
                    "producer_heartbeat_future",
                    SEVERITY_CRITICAL,
                    today,
                    f"intraday heartbeat dated {-age_s}s in the future",
                    {"ahead_s": str(-age_s)},
                )
            )
        elif age_s > PRODUCER_HEARTBEAT_STALE_S:
            findings.append(
                _finding(
                    DETECTOR_PRODUCER,
                    "producer_heartbeat_stale",
                    SEVERITY_CRITICAL,
                    today,
                    f"intraday heartbeat age {age_s}s",
                    {"heartbeat_age_s": str(age_s)},
                )
            )
        if not fold_ok:
            reason = str(beat.get("fold_reason", ""))[:40]
            findings.append(
                _finding(
                    DETECTOR_PRODUCER,
                    "producer_fold_not_ok",
                    SEVERITY_CRITICAL,
                    today,
                    f"intraday fold not ok: {reason}",
                    {"fold_reason": reason},
                )
            )
    second = (now_ns // NS) % 86_400
    if in_decision_window(second):
        try:
            missing = list(source.missing_intraday(now_ns))
        except ReaderUnwired:
            unknown.append(REASON_UNWIRED)
            missing = []
        except (OSError, ValueError):
            unknown.append("intraday_verdicts_unreadable")
            missing = []
        if missing:
            names = ",".join(sorted(missing)[:_MAX_LISTED])
            findings.append(
                _finding(
                    DETECTOR_PRODUCER,
                    "intraday_verdict_missing",
                    SEVERITY_CRITICAL,
                    today,
                    f"no valid intraday verdict: {names}",
                    {"missing": names},
                )
            )
    outcome = Outcome.FAIL if findings else Outcome.PASS
    return DetectorResult(DETECTOR_PRODUCER, outcome, tuple(findings), {}, tuple(unknown))


def _skip_stamp(record: Mapping[str, Any]) -> int:
    stamp = record.get("ts_ns")
    return stamp if type(stamp) is int else -1


def evaluate_daily(
    source: ProducerSource,
    *,
    now_ns: int,
    today: str,
    deployed_since_ns: int | None = None,
) -> DetectorResult:
    try:
        verdicts = dict(source.newest_daily_verdict_ns())
        skips = list(source.daily_skips())
    except ReaderUnwired:
        return DetectorResult(DETECTOR_DAILY, Outcome.INCONCLUSIVE, (), {}, (REASON_UNWIRED,))
    except (OSError, ValueError):
        return DetectorResult(
            DETECTOR_DAILY, Outcome.INCONCLUSIVE, (), {}, ("daily_verdicts_unreadable",)
        )
    stamps = [s.get("ts_ns") for s in skips]
    skip_ts = sorted(t for t in stamps if type(t) is int)
    last_reason = ""
    if skip_ts:
        newest = max(skips, key=_skip_stamp)
        last_reason = str(newest.get("reason", ""))[:60]
    findings: list[WatchFinding] = []
    stale = sorted(s for s, t in verdicts.items() if now_ns - t > DAILY_VERDICT_STALE_S * NS)
    newest_verdict = max(verdicts.values(), default=0)
    since = sum(1 for t in skip_ts if t > newest_verdict)
    metrics = {"last_skip_reason": last_reason, "skips_since_last_verdict": str(since)}
    if stale:
        names = ",".join(stale[:_MAX_LISTED])
        findings.append(
            _finding(
                DETECTOR_DAILY,
                "daily_verdict_absent",
                SEVERITY_CRITICAL,
                today,
                f"daily verdict older than 30h: {names} last_skip_reason={last_reason}",
                {**metrics, "subjects": names},
            )
        )
    elif any(now_ns - t < DAILY_VERDICT_STALE_S * NS and _same_day(t, today) for t in skip_ts):
        findings.append(
            _finding(
                DETECTOR_DAILY,
                "daily_producer_skipped",
                SEVERITY_WARNING,
                today,
                f"daily producer skipped a slot: {last_reason}",
                metrics,
            )
        )
    if not verdicts and not findings:
        return _no_subjects(metrics, now_ns, today, deployed_since_ns)
    outcome = Outcome.FAIL if findings else Outcome.PASS
    return DetectorResult(DETECTOR_DAILY, outcome, tuple(findings), metrics)


def _same_day(ts_ns: int, today: str) -> bool:
    return dt.datetime.fromtimestamp(ts_ns / NS, tz=dt.UTC).date().isoformat() == today


def _no_subjects(
    metrics: Mapping[str, str], now_ns: int, today: str, deployed_since_ns: int | None
) -> DetectorResult:
    """No daily verdict exists at all: pending for 30 h after the deployment, a FAIL after."""
    base = {**metrics, "unknown_reason": "no_daily_subjects"}
    if deployed_since_ns is None:
        return DetectorResult(
            DETECTOR_DAILY, Outcome.INCONCLUSIVE, (), {**base, "deployment_evidence_missing": "1"}
        )
    if now_ns - deployed_since_ns <= DAILY_VERDICT_STALE_S * NS:
        return DetectorResult(DETECTOR_DAILY, Outcome.INCONCLUSIVE, (), base)
    finding = _finding(
        DETECTOR_DAILY,
        "daily_verdict_absent",
        SEVERITY_CRITICAL,
        today,
        "no daily verdict 30h after the daily producer was first seen",
        {**metrics, "subjects": ""},
    )
    return DetectorResult(DETECTOR_DAILY, Outcome.FAIL, (finding,), metrics)
