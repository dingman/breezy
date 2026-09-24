"""AUD-03: daily decision-funnel digest over the offer-tape JSONL sidecar.

Read-only. One climate day's ``offer_tape_<date>.jsonl`` is aggregated into
the six entry-hunt stages the live rule already decided, and one INFO alert
is delivered through :func:`breezy.runtime.health.resolve_alert_sink`.
Shadow rows and exit rows are counted on their own lines and never enter
the entry funnel. An unrecognised ``source`` fails loud.

The stage predicates are cumulative, matching the 2026-09-20 funnel table:
a later stage is a subset of the earlier one. Margin is ``p_bound >
break_even`` (the live ``_finalize_take`` test), never ``ask < break_even``.

No strategy module is imported. Reasons are reported verbatim — there is
no fault/wait/edge taxonomy. ``no_side_calibration_unsafe`` (AUD-01a) is
classified only by those predicates plus the verbatim reason tally.

The A1-open-age line is not implemented here. AUD-02's Amendment C is not
in ``POST_FORECAST_PHASE_2026-09-20.md``, so AUD-03 §8's fallback applies.
See ``docs/plans/backlog/AUDIT_2026-09-21/AUD-03-FOLLOWUP-a1-digest-line.md``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from breezy.runtime.health import (
    MAX_ALERT_DETAIL_CHARS,
    AlertPayload,
    AlertSink,
    emit_alert,
    resolve_alert_sink,
)

_ENTRY_SOURCES: frozenset[str] = frozenset({"quote", "depth"})
_SHADOW_SOURCES: frozenset[str] = frozenset({"no_side_shadow"})
_EXIT_SOURCES: frozenset[str] = frozenset({"position_monitor"})
_KNOWN_SOURCES: frozenset[str] = _ENTRY_SOURCES | _SHADOW_SOURCES | _EXIT_SOURCES

#: Same four stations as ``config.SUPPORTED_STATIONS``. NYC is excluded
#: there and here. Not imported: that module pulls Nautilus in.
WINDOW_OPEN_STATIONS: tuple[str, ...] = ("LAX", "MDW", "MIA", "SFO")

_EVENT = "decision_funnel_daily"
_SITE = "multi"
_MISSING_DETAIL = "no decision tape found for {climate_day}"

_DEFAULT_TAPE_DIR = Path.home() / ".local/share/breezy/catalog/quote_tape/decisions"
_DEFAULT_OUTPUT_DIR = Path.home() / ".local/share/breezy/derived/decision_funnel"


class UnknownOfferTapeSourceError(ValueError):
    """A row ``source`` is outside the closed set this digest classifies."""

    def __init__(self, source: object) -> None:
        self.source = source
        super().__init__(f"unrecognised offer-tape source {source!r}")


class DecisionTapeNotFound(FileNotFoundError):
    """The climate day's sidecar is absent. Absence is not a zero funnel."""

    def __init__(self, climate_day: str) -> None:
        self.climate_day = climate_day
        super().__init__(_MISSING_DETAIL.format(climate_day=climate_day))


@dataclass(frozen=True, slots=True)
class StageCounts:
    decisions_emitted: int = 0
    rung_resolved: int = 0
    cell_legal: int = 0
    reached_price: int = 0
    margin_positive: int = 0
    orders: int = 0


@dataclass(frozen=True, slots=True)
class FunnelReport:
    totals: StageCounts
    shadow_count: int
    shadow_by_reason: tuple[tuple[str, int], ...]
    exit_fired: int
    exit_refused: int
    stalled_stations: tuple[str, ...]
    coverage_min_observed_at_ns: int | None
    coverage_max_observed_at_ns: int | None
    entry_reasons: tuple[tuple[str, int], ...]


def default_climate_day(now: dt.datetime) -> dt.date:
    """The climate day a post-09:00Z run should read: the previous UTC date.

    At 09:20Z every watched station's local date is already that UTC date,
    and yesterday's ``[12:00, 17:00)`` LST window has closed. Settlement of
    that climate day is done by 08:00Z (venue clock).
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(dt.UTC).date() - dt.timedelta(days=1)


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _observed_ns(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _sorted_counts(counter: Counter[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(counter.items()))


def _accumulate_entry(row: Mapping[str, object], bucket: list[int], reasons: Counter[str]) -> None:
    """Mutates ``bucket`` counts in stage order. ``bucket`` is local."""
    reason = str(row.get("reason") or "")
    reasons[reason] += 1
    bucket[0] += 1
    if reason == "observation_ambiguous":
        return
    bucket[1] += 1
    if row.get("illegal_cell") is not False or reason == "illegal_cell":
        return
    bucket[2] += 1
    if row.get("ask") is None or row.get("break_even") is None:
        return
    bucket[3] += 1
    p_bound = _decimal(row.get("p_bound"))
    break_even = _decimal(row.get("break_even"))
    if p_bound is None or break_even is None or not (p_bound > break_even):
        return
    bucket[4] += 1
    if row.get("decision") == "take":
        bucket[5] += 1


def funnel_for_day(
    rows: Iterable[Mapping[str, object]],
    *,
    window_open_stations: Iterable[str] = (),
) -> FunnelReport:
    """Aggregate one climate day. Raises on any ``source`` outside the closed set."""
    entry = [0, 0, 0, 0, 0, 0]
    entry_reasons: Counter[str] = Counter()
    entry_by_station: Counter[str] = Counter()
    shadow_reasons: Counter[str] = Counter()
    exit_fired = 0
    exit_refused = 0
    coverage_min: int | None = None
    coverage_max: int | None = None

    for row in rows:
        source = row.get("source")
        if source not in _KNOWN_SOURCES:
            raise UnknownOfferTapeSourceError(source)
        observed = _observed_ns(row.get("observed_at_ns"))
        if observed is not None:
            coverage_min = observed if coverage_min is None else min(coverage_min, observed)
            coverage_max = observed if coverage_max is None else max(coverage_max, observed)
        if source in _ENTRY_SOURCES:
            _accumulate_entry(row, entry, entry_reasons)
            entry_by_station[str(row.get("station") or "")] += 1
        elif source in _SHADOW_SOURCES:
            shadow_reasons[str(row.get("reason") or "")] += 1
        else:
            decision = row.get("decision")
            exit_decision = row.get("exit_decision")
            if decision == "exit_fired" or exit_decision == "fired":
                exit_fired += 1
            elif decision == "exit_refused" or exit_decision == "refused":
                exit_refused += 1

    stalled = tuple(
        sorted(station for station in window_open_stations if entry_by_station[station] == 0)
    )
    return FunnelReport(
        totals=StageCounts(*entry),
        shadow_count=sum(shadow_reasons.values()),
        shadow_by_reason=_sorted_counts(shadow_reasons),
        exit_fired=exit_fired,
        exit_refused=exit_refused,
        stalled_stations=stalled,
        coverage_min_observed_at_ns=coverage_min,
        coverage_max_observed_at_ns=coverage_max,
        entry_reasons=_sorted_counts(entry_reasons),
    )


def format_digest_detail(report: FunnelReport, *, climate_day: str) -> str:
    """One alert line. Shadow is labelled as outside the orders funnel.

    Stays within ``MAX_ALERT_DETAIL_CHARS`` by dropping the reason tally
    first, then shortening the stall list. Never relies on ``AlertPayload``
    truncation, which would cut a token in half.
    """
    totals = report.totals
    stall = ",".join(report.stalled_stations) if report.stalled_stations else "-"
    if report.coverage_min_observed_at_ns is None or report.coverage_max_observed_at_ns is None:
        coverage = "absent"
    else:
        coverage = f"{report.coverage_min_observed_at_ns}-{report.coverage_max_observed_at_ns}"
    base = (
        f"day={climate_day} e={totals.decisions_emitted} r={totals.rung_resolved} "
        f"c={totals.cell_legal} p={totals.reached_price} m={totals.margin_positive} "
        f"o={totals.orders} shadow={report.shadow_count}(not-orders) "
        f"xf={report.exit_fired} xr={report.exit_refused} stall={stall} cov={coverage}"
    )
    why = ",".join(f"{name}:{count}" for name, count in report.entry_reasons)
    if why:
        detailed = f"{base} why={why}"
        if len(detailed) <= MAX_ALERT_DETAIL_CHARS:
            return detailed
    if len(base) <= MAX_ALERT_DETAIL_CHARS:
        return base
    short = (
        f"day={climate_day} e={totals.decisions_emitted} r={totals.rung_resolved} "
        f"c={totals.cell_legal} p={totals.reached_price} m={totals.margin_positive} "
        f"o={totals.orders} shadow={report.shadow_count}(not-orders) "
        f"stall={len(report.stalled_stations)}"
    )
    return short[:MAX_ALERT_DETAIL_CHARS]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise TypeError("offer-tape line is not a JSON object")
            rows.append(payload)
    return rows


def _artefact(report: FunnelReport, *, climate_day: str) -> dict[str, object]:
    totals = report.totals
    return {
        "climate_day": climate_day,
        "totals": {
            "decisions_emitted": totals.decisions_emitted,
            "rung_resolved": totals.rung_resolved,
            "cell_legal": totals.cell_legal,
            "reached_price": totals.reached_price,
            "margin_positive": totals.margin_positive,
            "orders": totals.orders,
        },
        "shadow_count": report.shadow_count,
        "shadow_note": "shadow evaluations, never counted toward the orders funnel",
        "shadow_by_reason": dict(report.shadow_by_reason),
        "exit_fired": report.exit_fired,
        "exit_refused": report.exit_refused,
        "stalled_stations": list(report.stalled_stations),
        "entry_reasons": dict(report.entry_reasons),
        "coverage_min_observed_at_ns": report.coverage_min_observed_at_ns,
        "coverage_max_observed_at_ns": report.coverage_max_observed_at_ns,
    }


def _write_artefact(directory: Path, report: FunnelReport, *, climate_day: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"decision_funnel_{climate_day}.json"
    path.write_text(
        json.dumps(_artefact(report, climate_day=climate_day), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _emit(sink: AlertSink, *, detail: str) -> None:
    emit_alert(sink, AlertPayload(severity="INFO", event=_EVENT, site=_SITE, detail=detail))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--climate-day", default=None)
    parser.add_argument("--tape", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--stations", default=None, help="Comma-separated window-open stations")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    """Deliver one INFO digest. Missing tape is a named diagnostic, exit 0.

    Exit 0 on a missing file is deliberate: the diagnostic is INFO, and a
    non-zero status would also trip the unit's ``OnFailure=`` page. A
    malformed tape or an unknown ``source`` returns 1 — that is not an
    ordinary no-trade day.
    """
    args = _parse_args(argv)
    sink = resolve_alert_sink(env)
    if args.climate_day:
        climate_day = args.climate_day
    else:
        climate_day = default_climate_day(dt.datetime.now(dt.UTC)).isoformat()
    tape = (
        Path(args.tape)
        if args.tape
        else _DEFAULT_TAPE_DIR / f"offer_tape_{climate_day}.jsonl"
    )
    output_dir = Path(args.output_dir) if args.output_dir else _DEFAULT_OUTPUT_DIR
    stations: tuple[str, ...] = (
        tuple(part for part in args.stations.split(",") if part)
        if args.stations is not None
        else WINDOW_OPEN_STATIONS
    )
    if not tape.is_file():
        missing = DecisionTapeNotFound(climate_day)
        _emit(sink, detail=str(missing))
        return 0
    try:
        rows = _read_jsonl(tape)
        report = funnel_for_day(rows, window_open_stations=stations)
    except UnknownOfferTapeSourceError as exc:
        _emit(sink, detail=f"unrecognised offer-tape source {exc.source!r} for {climate_day}")
        return 1
    except (json.JSONDecodeError, ValueError, TypeError):
        _emit(sink, detail=f"decision tape unreadable for {climate_day}")
        return 1
    _emit(sink, detail=format_digest_detail(report, climate_day=climate_day))
    _write_artefact(output_dir, report, climate_day=climate_day)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
