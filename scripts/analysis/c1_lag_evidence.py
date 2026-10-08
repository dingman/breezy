"""F13 Phase A: build the C1 lag evidence JSON from the live collector's poll ledgers (offline).

Reads ``<archive-root>/<source-key>/poll_ledger.jsonl`` (written by scripts/collect/
us_source_collector.py) and writes the evidence file the Phase A runner's ``--c1-evidence``
parses (multisource_blend_skill._check_c1, PIN-R6):

* ``lag_samples_ns``  {pin source: [UNCENSORED lag, integer ns]} for sources with a live path
* ``uncensored``      {source: count}   ``measured_days`` {source: distinct UTC run days}
  (both keyed only by the pin keys in ``C1_LAG_SOURCES``)
* ``censored`` (``late`` rows, F13-R21), ``censored_poll_gap`` (a ``seen`` row whose
  firing is the first one after a ``skipped`` firing of the same source, within one
  scheduled gap, C1-R5), ``no_live_path`` (sources C1 does not collect),
  ``ready`` (every pin source meets the day and sample minimums) and per-source stats.

Lag definitions: ``lamp-mdl`` = measured header availability - nominal cycle (the live NOMADS
LAMP feed stands in for the MDL archive); ``pfm`` = first-seen - WMO issuance (the ledger's
``available_ts`` IS the WMO header, so it carries no lag); the first ``seen`` event per
(station, run) only (later revisions are not publication lags). ``late`` rows are
right-censored and dropped. ``lav-iem`` / ``mos-gfs`` / ``obs`` come from the
availability-only collector legs (``us-lav-iem-avail``, ``us-mos-gfs-avail``,
``us-obs-avail``): availability = first-seen, so the lag is first-seen minus the nominal run
(lav: IEM hourly label; mos: model runtime; obs: routine report time), an upper bound by one poll
interval (C1-R3). A ``seen`` row is ``censored_poll_gap`` only when a ``skipped`` row for the
same source (a ledger row, or a row in the historical skips file) has its timestamp in
``[first_seen_ns - MAX_POLL_GAP_NS, first_seen_ns)``. That is the first firing after a skipped
firing, within one scheduled gap (max OnCalendar gap plus 5 min). A long gap with no skipped
firing is kept: ledgers are event-driven and do not write a row for an unchanged run.
``left_truncation_ns`` {source: ns} records each leg's polling-start offset after the nominal
run (lav +10 min, mos +2 h; 0 elsewhere): a run is never polled before it, so lags below the
offset are truncated and the p50 of those legs is biased high by that floor; the p99 rule is
unaffected (the pins sit far above the offset). A source whose ledger does not exist yet
is listed under ``no_live_path``; it is XX
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from breezy.analysis.multisource_blend_stats import C1_LAG_SOURCES

__all__ = ["build_evidence", "main"]

LEDGER_NAME: Final[str] = "poll_ledger.jsonl"
MIN_DAYS: Final[int] = 14
MIN_UNCENSORED: Final[int] = 30
_NS_PER_MIN: Final[int] = 60 * 10**9
_NS_PER_S: Final[int] = 10**9
_LAMP_EXT: Final[str] = "ALLEXT"
#: pin source -> (ledger source key, lag basis); absent = no live C1 path.
_LIVE: Final[Mapping[str, tuple[str, str]]] = {
    "lamp-mdl": ("us-lamp-live", "available_ts_ns"),
    "lav-iem": ("us-lav-iem-avail", "available_ts_ns"),
    "pfm": ("us-pfm-afos", "first_seen_ns"),
    "mos-gfs": ("us-mos-gfs-avail", "available_ts_ns"),
    "obs": ("us-obs-avail", "available_ts_ns"),
}
#: polling-start offset per source (scripts/collect/us_source_lag_legs.IEM_LEGS start_offset_ns);
#: lags below it are left-truncated. 0 = polled from the nominal time.
_LEFT_TRUNCATION_NS: Final[Mapping[str, int]] = {
    "lamp-mdl": 0,
    "lav-iem": 10 * _NS_PER_MIN,
    "pfm": 0,
    "mos-gfs": 120 * _NS_PER_MIN,
    "obs": 0,
}
#: Max scheduled OnCalendar gap plus 5 min, keyed like ``_LIVE`` (C1-R5).
#: deploy/systemd/us-source-collector@.timer and the lav/mos/obs/pfm schedule drop-ins.
#: lamp 15:31Z→17:10Z = 99 min; pfm 15:40Z→17:10Z = 90; lav/obs 16:20Z→17:10Z = 50;
#: mos 16:15Z→17:15Z = 60.
_POLL_GAP_TOLERANCE_MIN: Final[int] = 5
MAX_POLL_GAP_NS: Final[Mapping[str, int]] = {
    "lamp-mdl": (99 + _POLL_GAP_TOLERANCE_MIN) * _NS_PER_MIN,
    "lav-iem": (50 + _POLL_GAP_TOLERANCE_MIN) * _NS_PER_MIN,
    "pfm": (90 + _POLL_GAP_TOLERANCE_MIN) * _NS_PER_MIN,
    "mos-gfs": (60 + _POLL_GAP_TOLERANCE_MIN) * _NS_PER_MIN,
    "obs": (50 + _POLL_GAP_TOLERANCE_MIN) * _NS_PER_MIN,
}
_HISTORICAL_SKIPS_SCHEMA: Final[str] = "c1_historical_skips/v1"
_DEFAULT_HISTORICAL_SKIPS: Final[Path] = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evidence"
    / "f13"
    / "c1_historical_skips_2026-10.json"
)
#: Journal ``source=`` is the ledger key (``us-pfm-afos``). Map it through ``_LIVE``.
_PIN_BY_LEDGER_KEY: Final[Mapping[str, str]] = {
    ledger_key: pin for pin, (ledger_key, _basis) in _LIVE.items()
}


def _read_ledger(path: Path) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    bad = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            bad += 1
    return events, bad


def _first_seen_per_run(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    firsts: dict[tuple[str, int], dict[str, Any]] = {}
    for e in events:
        if e.get("kind") != "seen" or e.get("station") == _LAMP_EXT:
            continue
        if e.get("routine") is False:  # obs ledger rows are routine-only; defence in depth
            continue
        try:
            key = (str(e.get("station")), int(e["run_ts_ns"]))
            int(e["available_ts_ns"])
            int(e["first_seen_ns"])
        except (KeyError, TypeError, ValueError):
            continue
        firsts.setdefault(key, e)
    return list(firsts.values())


def _day(run_ts_ns: int) -> str:
    return dt.datetime.fromtimestamp(run_ts_ns // _NS_PER_S, dt.UTC).date().isoformat()


def _nearest_rank(ordered: Sequence[int], num: int, den: int) -> int:
    rank = -(-num * len(ordered) // den)
    return ordered[max(rank, 1) - 1]


def _stats(samples: Sequence[int], days: Sequence[str]) -> dict[str, Any]:
    if not samples:
        return {"n": 0}
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "p50_min": _nearest_rank(ordered, 50, 100) / _NS_PER_MIN,
        "p99_min": _nearest_rank(ordered, 99, 100) / _NS_PER_MIN,
        "max_min": ordered[-1] / _NS_PER_MIN,
        "first_day": min(days),
        "last_day": max(days),
    }


def _fetched_at_ns(event: Mapping[str, Any]) -> int | None:
    """Ledger poll time. Every real row carries ``fetched_at_ns``; a synthetic row may not."""
    raw = event.get("fetched_at_ns")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def _skipped_ts_ns(events: Sequence[Mapping[str, Any]]) -> list[int]:
    """Timestamps of ledger ``skipped`` rows. Other kinds are not polls that were missed."""
    stamps: list[int] = []
    for event in events:
        if event.get("kind") != "skipped":
            continue
        stamp = _fetched_at_ns(event)
        if stamp is not None:
            stamps.append(stamp)
    return stamps


def _pin_for_skip_source(raw: str) -> str | None:
    if raw in _LIVE:
        return raw
    return _PIN_BY_LEDGER_KEY.get(raw)


def _load_historical_skips(path: Path | None) -> dict[str, list[int]]:
    """Pin source -> skip timestamps. A missing file adds nothing. A bad schema refuses."""
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != _HISTORICAL_SKIPS_SCHEMA:
        raise ValueError(f"historical skips {path} is not {_HISTORICAL_SKIPS_SCHEMA}")
    rows = payload.get("skips")
    if not isinstance(rows, list):
        raise TypeError(f"historical skips {path} has no skips list")
    by_pin: dict[str, list[int]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError(f"historical skips {path} has a non-object skip")
        raw_source = row.get("source")
        raw_ts = row.get("ts_ns")
        if (
            not isinstance(raw_source, str)
            or isinstance(raw_ts, bool)
            or not isinstance(raw_ts, int)
        ):
            raise TypeError(f"historical skips {path} has a skip without source and ts_ns")
        pin = _pin_for_skip_source(raw_source)
        if pin is None:
            continue
        by_pin.setdefault(pin, []).append(raw_ts)
    return by_pin


def _follows_skipped_firing(seen_at: int, skip_ts: Sequence[int], max_poll_gap_ns: int) -> bool:
    """True when some skip lies in ``[seen_at - max_poll_gap_ns, seen_at)``."""
    window_start = seen_at - max_poll_gap_ns
    return any(window_start <= stamp < seen_at for stamp in skip_ts)


def _measure(
    events: Sequence[dict[str, Any]],
    basis: str,
    max_poll_gap_ns: int,
    extra_skip_ns: Sequence[int] = (),
) -> dict[str, Any]:
    samples: list[int] = []
    days: set[str] = set()
    censored = 0
    censored_poll_gap = 0
    skip_ts = [*_skipped_ts_ns(events), *extra_skip_ns]
    for e in _first_seen_per_run(events):
        if e.get("late"):
            censored += 1
            continue
        if _follows_skipped_firing(int(e["first_seen_ns"]), skip_ts, max_poll_gap_ns):
            censored_poll_gap += 1
            continue
        run = int(e["run_ts_ns"])
        lag = int(e[basis]) - run
        if lag < 0:
            continue
        samples.append(lag)
        days.add(_day(run))
    return {
        "samples": samples,
        "days": sorted(days),
        "censored": censored,
        "censored_poll_gap": censored_poll_gap,
    }


def build_evidence(archive_root: Path, historical_skips: Path | None = None) -> dict[str, Any]:
    lag_samples: dict[str, list[int]] = {}
    uncensored = dict.fromkeys(C1_LAG_SOURCES, 0)
    measured = dict.fromkeys(C1_LAG_SOURCES, 0)
    censored = dict.fromkeys(C1_LAG_SOURCES, 0)
    censored_poll_gap = dict.fromkeys(C1_LAG_SOURCES, 0)
    stats: dict[str, Any] = {}
    no_live: list[str] = []
    malformed = 0
    historical = _load_historical_skips(historical_skips)
    for source in C1_LAG_SOURCES:
        live = _LIVE.get(source)
        ledger = archive_root / live[0] / LEDGER_NAME if live else None
        if live is None or ledger is None or not ledger.is_file():
            no_live.append(source)
            continue
        events, bad = _read_ledger(ledger)
        malformed += bad
        got = _measure(events, live[1], MAX_POLL_GAP_NS[source], historical.get(source, ()))
        lag_samples[source] = got["samples"]
        uncensored[source] = len(got["samples"])
        measured[source] = len(got["days"])
        censored[source] = got["censored"]
        censored_poll_gap[source] = got["censored_poll_gap"]
        stats[source] = _stats(got["samples"], got["days"])
    ready = all(measured[s] >= MIN_DAYS and uncensored[s] >= MIN_UNCENSORED for s in C1_LAG_SOURCES)
    return {
        "schema": "c1_lag_evidence/v1",
        "lag_samples_ns": lag_samples,
        "measured_days": measured,
        "uncensored": uncensored,
        "censored": censored,
        "censored_poll_gap": censored_poll_gap,
        "left_truncation_ns": dict(_LEFT_TRUNCATION_NS),
        "no_live_path": no_live,
        "stats": stats,
        "malformed_lines": malformed,
        "min_days": MIN_DAYS,
        "min_uncensored": MIN_UNCENSORED,
        "ready": ready,
    }


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--historical-skips",
        type=Path,
        default=_DEFAULT_HISTORICAL_SKIPS,
        help="c1_historical_skips/v1 JSON from journalctl. A missing file is ignored.",
    )
    args = parser.parse_args(argv)
    if not args.archive_root.is_dir():
        print(
            f"c1_lag_evidence: archive root {args.archive_root} is not a directory", file=sys.stderr
        )
        return 2
    evidence = build_evidence(args.archive_root, args.historical_skips)
    _atomic_write(args.out, evidence)
    print(f"c1_lag_evidence: wrote {args.out} ready={evidence['ready']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
