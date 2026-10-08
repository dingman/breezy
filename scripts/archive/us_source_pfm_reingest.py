"""Offline re-ingest of quarantined PFM products (``us_source_backfill --reingest-quarantine``).

A refused backfill product is kept verbatim as ``<sha256>.raw`` with a line in ``refusals.jsonl``
(see ``RefusalQuarantine``). After a parser fix, this replays those products through the CURRENT
``parse_pfm_product`` and appends the ones that now parse through the same store path the backfill
uses (``_append``: same payload bytes, same ``run_ts_ns`` = the recorded issuance, ``model`` = WFO),
so a product already in the store is UNCHANGED (sha dedupe) and a re-run is idempotent.

No network, no clock beyond the store's own stamp; a product that still refuses is counted by its
new reason and left in the quarantine (never rewritten). ``dry_run`` parses only and never touches
the store.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from us_source_backfill import (  # type: ignore[import-not-found]
    _NS,
    LegReport,
    _append,
)
from us_source_pfm_support import RefusalQuarantine  # type: ignore[import-not-found]

from breezy.ingest.pfm_parse import PfmParseError, parse_pfm_product
from breezy.persistence.us_source_revision_store import UsSourceRevisionStore

__all__ = ["reingest_quarantine"]

_FALLBACK_REASON: Final[str] = "unparsed"


def _lines(quarantine_dir: Path) -> list[dict[str, Any]]:
    log = quarantine_dir / RefusalQuarantine.LOG_NAME
    if not log.is_file():
        raise FileNotFoundError(f"{log} not found")
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def reingest_quarantine(
    quarantine_dir: Path,
    store: UsSourceRevisionStore | None,
    *,
    only_reasons: frozenset[str] | None = None,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    """Replay the quarantine; ``store=None`` is a dry run. Returns the JSON-able report."""
    seen: set[tuple[str, str]] = set()
    legs: dict[str, LegReport] = {}
    skipped: Counter[str] = Counter()
    still_refused: Counter[str] = Counter()
    would_accept: Counter[str] = Counter()
    # One batch for the run: payloads stay durable, coverage.json is rewritten
    # every COVERAGE_FLUSH_EVERY products and again when the run exits.
    batch = contextlib.nullcontext(None) if store is None else store.coverage_batch()
    with batch as outcome:
        for entry in _lines(quarantine_dir):
            if only_reasons is not None and entry["reason"] not in only_reasons:
                skipped["reason_filter"] += 1
                continue
            key = (entry["station"], entry["sha256"])
            if key in seen:
                skipped["duplicate_line"] += 1
                continue
            seen.add(key)
            if not entry.get("issued"):
                skipped["no_issuance"] += 1
                continue
            raw_path = quarantine_dir / entry["raw_file"]
            if not raw_path.is_file():
                skipped["raw_missing"] += 1
                continue
            raw = raw_path.read_bytes()
            issued = dt.datetime.fromisoformat(entry["issued"])
            station, wfo = entry["station"], entry["wfo"]
            report = legs.setdefault(station, LegReport(station=station, wfo=wfo))
            report.products_seen += 1
            try:
                parse_pfm_product(
                    raw, station=station, reference_time=issued + dt.timedelta(seconds=1)
                )
            except PfmParseError as exc:
                reason = exc.reason or _FALLBACK_REASON
                report.refused[reason] = report.refused.get(reason, 0) + 1
                still_refused[f"{station}:{reason}"] += 1
                continue
            would_accept[station] += 1
            if store is None:
                continue
            if not _append(
                store,
                report,
                sleep,
                station=station,
                run_ts_ns=int(issued.timestamp()) * _NS,
                wfo=wfo,
                payload=raw,
            ):
                report.status = "store_busy"
                break
    flushed = 0 if outcome is None else int(outcome.flushed)
    dropped = 0 if outcome is None else len(outcome.dropped)
    stranded = [] if outcome is None else list(outcome.stranded)
    if dropped or stranded:
        for leg in legs.values():
            if leg.status == "complete":
                leg.status = "coverage_incomplete"
    return {
        "mode": "dry_run" if store is None else "apply",
        "quarantine_dir": str(quarantine_dir),
        "would_accept": dict(sorted(would_accept.items())),
        "still_refused": dict(sorted(still_refused.items())),
        "skipped": dict(sorted(skipped.items())),
        "legs": [leg.to_dict() for leg in legs.values()],
        "coverage_flushed": flushed,
        "coverage_dropped": dropped,
        "coverage_stranded_sources": stranded,
        "complete": all(leg.status == "complete" for leg in legs.values())
        and not dropped
        and not stranded,
    }
