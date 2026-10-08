"""F13 Phase A: build the C1 lag evidence JSON from the live collector's poll ledgers (offline).

Reads ``<archive-root>/<source-key>/poll_ledger.jsonl`` (written by scripts/collect/
us_source_collector.py) and writes the evidence file the Phase A runner's ``--c1-evidence``
parses (multisource_blend_skill._check_c1, PIN-R6):

* ``lag_samples_ns``  {pin source: [UNCENSORED lag, integer ns]} for sources with a live path
* ``uncensored``      {source: count}   ``measured_days`` {source: distinct UTC run days}
  (both keyed only by the pin keys in ``C1_LAG_SOURCES``)
* ``censored`` (``late`` rows, F13-R21), ``no_live_path`` (sources C1 does not collect),
  ``ready`` (every pin source meets the day and sample minimums) and per-source stats.

Lag definitions: ``lamp-mdl`` = measured header availability - nominal cycle (the live NOMADS
LAMP feed stands in for the MDL archive); ``pfm`` = first-seen - WMO issuance (the ledger's
``available_ts`` IS the WMO header, so it carries no lag); the first ``seen`` event per
(station, run) only (later revisions are not publication lags). ``late`` rows are
right-censored and dropped. ``lav-iem`` / ``mos-gfs`` / ``obs`` come from the
availability-only collector legs (``us-lav-iem-avail``, ``us-mos-gfs-avail``,
``us-obs-avail``): availability = first-seen, so the lag is first-seen minus the nominal run
(lav: IEM hourly label; mos: model runtime; obs: routine report time), an upper bound by one poll
interval (C1-R3). ``left_truncation_ns`` {source: ns} records each leg's polling-start offset after
the nominal run (lav +10 min, mos +2 h; 0 elsewhere): a run is never polled before it, so lags
below the offset are truncated and the p50 of those legs is biased high by that floor; the p99
rule is unaffected (the pins sit far above the offset). A source whose ledger does not exist yet
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


def _measure(events: Sequence[dict[str, Any]], basis: str) -> dict[str, Any]:
    samples: list[int] = []
    days: set[str] = set()
    censored = 0
    for e in _first_seen_per_run(events):
        if e.get("late"):
            censored += 1
            continue
        run = int(e["run_ts_ns"])
        lag = int(e[basis]) - run
        if lag < 0:
            continue
        samples.append(lag)
        days.add(_day(run))
    return {"samples": samples, "days": sorted(days), "censored": censored}


def build_evidence(archive_root: Path) -> dict[str, Any]:
    lag_samples: dict[str, list[int]] = {}
    uncensored = dict.fromkeys(C1_LAG_SOURCES, 0)
    measured = dict.fromkeys(C1_LAG_SOURCES, 0)
    censored = dict.fromkeys(C1_LAG_SOURCES, 0)
    stats: dict[str, Any] = {}
    no_live: list[str] = []
    malformed = 0
    for source in C1_LAG_SOURCES:
        live = _LIVE.get(source)
        ledger = archive_root / live[0] / LEDGER_NAME if live else None
        if live is None or ledger is None or not ledger.is_file():
            no_live.append(source)
            continue
        events, bad = _read_ledger(ledger)
        malformed += bad
        got = _measure(events, live[1])
        lag_samples[source] = got["samples"]
        uncensored[source] = len(got["samples"])
        measured[source] = len(got["days"])
        censored[source] = got["censored"]
        stats[source] = _stats(got["samples"], got["days"])
    ready = all(measured[s] >= MIN_DAYS and uncensored[s] >= MIN_UNCENSORED for s in C1_LAG_SOURCES)
    return {
        "schema": "c1_lag_evidence/v1",
        "lag_samples_ns": lag_samples,
        "measured_days": measured,
        "uncensored": uncensored,
        "censored": censored,
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
    args = parser.parse_args(argv)
    if not args.archive_root.is_dir():
        print(
            f"c1_lag_evidence: archive root {args.archive_root} is not a directory", file=sys.stderr
        )
        return 2
    evidence = build_evidence(args.archive_root)
    _atomic_write(args.out, evidence)
    print(f"c1_lag_evidence: wrote {args.out} ready={evidence['ready']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
