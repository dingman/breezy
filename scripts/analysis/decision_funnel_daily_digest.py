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

The A1-open-age line is not implemented here; AUD-02's Amendment C is not in
``POST_FORECAST_PHASE_2026-09-20.md``, so AUD-03 §8's fallback applied (see
``docs/plans/backlog/AUDIT_2026-09-21/AUD-03-FOLLOWUP-a1-digest-line.md``).
Its replacement -- a ``halt_enforced: yes|no|unknown`` field read from the
SAME ``FAMILY_HALT_KEY`` the submit veto reads -- IS implemented here
(coordinator build decision, 2026-09-24): :func:`read_family_halt_status`
opens its OWN read-only sqlite connection (``file:<path>?mode=ro``) directly
against the exec-state store, never the node's exclusive submit-intent flock
(``breezy.runtime.submit_intent.hold_submit_intent_process_lock``, held for
the node's full process lifetime and therefore unusable by a periodic
read-only digest -- see that test file for the two-connection proof). The
decode itself is the single shared
``breezy.strategy.current_rung_hold.trial_day_latch.decode_family_halt``
pure helper, never re-implemented here. Every read failure -- missing
store, a lock that outlives ``_HALT_BUSY_TIMEOUT_SECONDS``, a malformed
stored value, any exception -- reports ``unknown`` with a reason; this field
NEVER fails open to ``no`` or closed to ``yes``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import logging
import os
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from breezy.runtime.exec_state_db_path import ExecStateDbNotConfiguredError, resolve_store_path
from breezy.runtime.health import (
    MAX_ALERT_DETAIL_CHARS,
    AlertPayload,
    AlertSink,
    emit_alert,
    resolve_alert_sink,
)
from breezy.strategy.current_rung_hold.trial_day_latch import FAMILY_HALT_KEY, decode_family_halt

logger = logging.getLogger(__name__)

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

#: Belt-and-suspenders bound on the digest's OWN read-only connection --
#: independent of, and much shorter than, `stop_intent_marker`'s 300s
#: (that one bounds a marker's validity; this one bounds how long a
#: best-effort diagnostic read may block before reporting `unknown` rather
#: than stalling the whole digest run).
_HALT_BUSY_TIMEOUT_SECONDS: float = 2.0

_SELECT_HALT_SQL = "SELECT value FROM state WHERE key = ?"


@dataclass(frozen=True, slots=True)
class FamilyHaltStatus:
    """AUD-03 follow-up: the A1 family-halt read for the daily digest.

    Three states, never two: `unknown` is a distinct outcome from both
    `yes` and `no` for every failure mode below -- this field must never
    fail open to "not halted" nor fail closed to "halted" on a read it could
    not actually perform. `reason` is set only when `value == "unknown"`.
    """

    value: Literal["yes", "no", "unknown"]
    reason: str | None


def read_family_halt_status(
    store_path: Path,
    *,
    busy_timeout_s: float = _HALT_BUSY_TIMEOUT_SECONDS,
    connect: Callable[..., sqlite3.Connection] = sqlite3.connect,
) -> FamilyHaltStatus:
    """Read `FAMILY_HALT_KEY` through the digest's OWN read-only sqlite
    connection -- `file:<path>?mode=ro`, never a write, never the node's
    exclusive submit-intent flock (`breezy.runtime.submit_intent.
    hold_submit_intent_process_lock`, a SEPARATE sidecar file
    `<store_path>.intent.lock` the node holds for its whole process
    lifetime; a digest that acquired or waited on THAT lock could never
    report anything but "held" while the node is live -- exactly when this
    field matters most).

    `busy_timeout_s` bounds how long sqlite's own locking layer may block
    this connection (WAL readers are not normally blocked by a writer, but
    this is a belt-and-suspenders cap regardless) before this function gives
    up and reports `unknown` rather than stalling the digest.

    Every failure -- the store file does not exist, the read stays locked
    past `busy_timeout_s`, the stored value is not `bytes` (schema drift/
    corruption), or any other `sqlite3.Error`/`OSError` -- reports `unknown`
    with a `reason` naming what went wrong. Never fails open to `no` or
    closed to `yes`: an
    operator reading a stale "no" here would wrongly believe entry is
    enabled when it might not be; a stale "yes" would wrongly believe the
    family is protected when it might not be. `unknown` names the read
    itself as untrustworthy in either direction.
    """
    try:
        conn = connect(f"file:{store_path}?mode=ro", uri=True, timeout=busy_timeout_s)
    except (sqlite3.Error, OSError) as exc:
        return FamilyHaltStatus(value="unknown", reason=f"{type(exc).__name__}: {exc}")
    try:
        try:
            row = conn.execute(_SELECT_HALT_SQL, (FAMILY_HALT_KEY,)).fetchone()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        return FamilyHaltStatus(value="unknown", reason=f"{type(exc).__name__}: {exc}")

    raw = row[0] if row is not None else None
    if raw is not None and not isinstance(raw, bytes | bytearray):
        return FamilyHaltStatus(
            value="unknown",
            reason=f"malformed FAMILY_HALT_KEY value: expected bytes, got {type(raw).__name__}",
        )
    # `decode_family_halt` is a pure `bytes | None -> bool` comparison (see
    # its docstring) -- it cannot raise on the `bytes | None` this function
    # already guarantees above, so no further try/except is warranted here
    # (YAGNI: an unreachable defensive branch is dead code, not safety).
    halted = decode_family_halt(bytes(raw) if raw is not None else None)
    return FamilyHaltStatus(value="yes" if halted else "no", reason=None)


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
    #: F-2 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): per-station SUMS of the
    #: day's hourly `diagnostics` deltas, read from the diagnostics-summary
    #: sidecar (F-2's own artefact) -- `{}` when that sidecar is absent or
    #: unreadable, in which case the digest's output is byte-identical to
    #: before this field existed (AC6). Populated by `main` via `replace`,
    #: never by `funnel_for_day` itself (that function reads only the
    #: offer-tape rows).
    pre_tape_by_station: dict[str, dict[str, int]] = field(default_factory=dict)


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


def _stall_token(station: str, pre_tape_by_station: Mapping[str, Mapping[str, int]]) -> str:
    """F-2 AC6: ``STATION(top_reason:count)`` when the diagnostics-summary
    sidecar has pre-tape counts for ``station``, else the plain station
    name (byte-identical to before this field existed -- the missing/empty
    case)."""
    counts = pre_tape_by_station.get(station)
    if not counts:
        return station
    top_reason, top_count = max(counts.items(), key=lambda item: item[1])
    return f"{station}({top_reason}:{top_count})"


def format_digest_detail(
    report: FunnelReport,
    *,
    climate_day: str,
    halt: FamilyHaltStatus | None = None,
    capped_total: int = 0,
) -> str:
    """One alert line. Shadow is labelled as outside the orders funnel.

    Stays within ``MAX_ALERT_DETAIL_CHARS`` by dropping fields in priority
    order, most-expendable first: the F-2 pre-tape ``stall=STATION(reason:
    count)`` enrichment, then the halt-unknown free-text ``reason``
    (unbounded length, diagnostic only), then the ``why=`` reason tally,
    then finally falling back to the short form. ``halt=<value>`` itself
    (when ``halt`` is given at all) is never dropped -- it is one of three
    fixed short tokens. ``halt`` is ``None`` only for callers that predate
    AUD-03's follow-up and omit the field entirely (back-compat). Never
    relies on ``AlertPayload`` truncation, which would cut a token in half.
    """
    totals = report.totals
    if report.coverage_min_observed_at_ns is None or report.coverage_max_observed_at_ns is None:
        coverage = "absent"
    else:
        coverage = f"{report.coverage_min_observed_at_ns}-{report.coverage_max_observed_at_ns}"
    halt_reason = f"halt_reason={halt.reason}" if halt is not None and halt.reason else None
    why = ",".join(f"{name}:{count}" for name, count in report.entry_reasons)

    def _base(stall: str) -> str:
        rendered = (
            f"day={climate_day} e={totals.decisions_emitted} r={totals.rung_resolved} "
            f"c={totals.cell_legal} p={totals.reached_price} m={totals.margin_positive} "
            f"o={totals.orders} shadow={report.shadow_count}(not-orders) "
            f"xf={report.exit_fired} xr={report.exit_refused} stall={stall} cov={coverage}"
        )
        if halt is not None:
            rendered = f"{rendered} halt={halt.value}"
        if capped_total > 0:
            rendered = f"{rendered} truncated=1"
        return rendered

    if report.stalled_stations:
        enriched_stall = ",".join(
            _stall_token(station, report.pre_tape_by_station) for station in report.stalled_stations
        )
        plain_stall = ",".join(report.stalled_stations)
    else:
        enriched_stall = plain_stall = "-"

    # F-2 AC6: the enriched stall token is the FIRST thing dropped -- tried
    # richest to leanest at EVERY tier (halt_reason+why, why-only, base
    # alone) before falling back to the plain station-name stall field and
    # repeating the SAME cascade.
    for stall in (enriched_stall, plain_stall):
        base = _base(stall)
        with_reason = f"{base} {halt_reason}" if halt_reason else base
        candidate = f"{with_reason} why={why}" if why else with_reason
        if len(candidate) <= MAX_ALERT_DETAIL_CHARS:
            return candidate
        candidate = f"{base} why={why}" if why else base
        if len(candidate) <= MAX_ALERT_DETAIL_CHARS:
            return candidate
        if len(base) <= MAX_ALERT_DETAIL_CHARS:
            return base

    short = (
        f"day={climate_day} e={totals.decisions_emitted} r={totals.rung_resolved} "
        f"c={totals.cell_legal} p={totals.reached_price} m={totals.margin_positive} "
        f"o={totals.orders} shadow={report.shadow_count}(not-orders) "
        f"stall={len(report.stalled_stations)}"
    )
    if halt is not None:
        short = f"{short} halt={halt.value}"
    if capped_total > 0:
        short = f"{short} truncated=1"
    return short[:MAX_ALERT_DETAIL_CHARS]


def _iter_jsonl(path: Path) -> Iterator[dict[str, object]]:
    """Stream one JSONL file line by line -- bounded memory regardless of
    file size (F-3 AC4). Transparent `.gz` support (F-3 AC7): a `.gz` suffix
    opens through :func:`gzip.open` in text mode, byte-identical decoding to
    the plain path otherwise. A truncated or malformed final line raises
    exactly as it would mid-stream (F-3 AC5) -- the caller's own
    ``except (json.JSONDecodeError, ValueError, TypeError)`` around
    consuming this generator is unchanged.
    """
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, mode="rt", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise TypeError("offer-tape line is not a JSON object")
            yield payload


def _resolve_readable_path(path: Path) -> Path:
    """F-3 AC7: `.jsonl` or its `.jsonl.gz` sibling, whichever exists.

    `path` itself is returned unchanged when it exists (including when the
    caller already passed a `.gz` path directly), or when NEITHER form
    exists -- the caller's own missing-file diagnostic is unchanged either
    way; this function only redirects to a `.gz` sibling that is actually on
    disk.
    """
    if path.is_file():
        return path
    gz_sibling = path.with_name(path.name + ".gz")
    if gz_sibling.is_file():
        return gz_sibling
    return path


@dataclass(frozen=True, slots=True)
class _DiagnosticsSummaryTotals:
    capped_total: int
    pre_tape_by_station: dict[str, dict[str, int]]


def _read_diagnostics_summary_totals(
    tape_path: Path, climate_day: str
) -> _DiagnosticsSummaryTotals:
    """F-3 AC3 + F-2 AC6, ONE pass: sums `offer_tape_capped` AND, per
    station, the day's `diagnostics` deltas -- across the SAME diagnostics-
    summary sidecar (F-2's own artefact, `diagnostics_summary_<day>.jsonl
    [.gz]`). Read-only and best-effort, exactly like
    :func:`read_family_halt_status`: any read/decode failure here must
    never fail the main offer-tape funnel, and reading the file only ONCE
    (rather than once per field) means a corrupt sidecar logs exactly one
    WARNING, not one per caller. Returns all-empty when the sidecar is
    absent, unreadable, or carries no usable rows -- never raises.
    """
    candidate = tape_path.parent / f"diagnostics_summary_{climate_day}.jsonl"
    summary_path = _resolve_readable_path(candidate)
    if not summary_path.is_file():
        return _DiagnosticsSummaryTotals(capped_total=0, pre_tape_by_station={})
    capped_total = 0
    per_station: dict[str, Counter[str]] = {}
    try:
        for row in _iter_jsonl(summary_path):
            value = row.get("offer_tape_capped")
            if isinstance(value, int) and not isinstance(value, bool):
                capped_total += value
            station = row.get("station")
            diagnostics = row.get("diagnostics")
            if isinstance(station, str) and isinstance(diagnostics, dict):
                bucket = per_station.setdefault(station, Counter())
                for key, count in diagnostics.items():
                    if isinstance(count, int) and not isinstance(count, bool):
                        bucket[key] += count
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning(
            "decision_funnel_daily_digest: diagnostics-summary sidecar %s is "
            "corrupt or unreadable (%s: %s); truncated/pre_tape_by_station stay "
            "unreported for %s",
            summary_path,
            type(exc).__name__,
            exc,
            climate_day,
        )
        return _DiagnosticsSummaryTotals(capped_total=0, pre_tape_by_station={})
    return _DiagnosticsSummaryTotals(
        capped_total=capped_total,
        pre_tape_by_station={station: dict(counter) for station, counter in per_station.items()},
    )


def _artefact(
    report: FunnelReport,
    *,
    climate_day: str,
    halt: FamilyHaltStatus | None = None,
    capped_total: int = 0,
) -> dict[str, object]:
    totals = report.totals
    artefact: dict[str, object] = {
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
    if halt is not None:
        artefact["halt_enforced"] = halt.value
        artefact["halt_reason"] = halt.reason
    if capped_total > 0:
        artefact["truncated"] = 1
    # F-2 AC6: stalled stations get their pre-tape counts in the artefact --
    # never for a station that is NOT stalled, and never at all when the
    # sidecar is absent (an empty `pre_tape_by_station` produces an empty
    # dict here too, so the key is simply omitted, byte-identical to before
    # this field existed).
    stalled_pre_tape = {
        station: counts
        for station, counts in report.pre_tape_by_station.items()
        if station in report.stalled_stations
    }
    if stalled_pre_tape:
        artefact["pre_tape_by_station"] = stalled_pre_tape
    return artefact


def _write_artefact(
    directory: Path,
    report: FunnelReport,
    *,
    climate_day: str,
    halt: FamilyHaltStatus | None = None,
    capped_total: int = 0,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"decision_funnel_{climate_day}.json"
    artefact = _artefact(report, climate_day=climate_day, halt=halt, capped_total=capped_total)
    path.write_text(
        json.dumps(artefact, indent=2, sort_keys=True) + "\n",
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
    parser.add_argument(
        "--store-path",
        default=None,
        help=(
            "exec state-DB path for the halt_enforced read-only read; falls back to "
            "EXEC_STATE_DB_ENV_VAR"
        ),
    )
    return parser.parse_args(argv)


def _resolve_halt_status(
    args: argparse.Namespace, source_env: Mapping[str, str]
) -> FamilyHaltStatus:
    """Never raises: a misconfigured/absent store is `unknown`, not a digest
    failure -- `halt_enforced` is supplementary to the offer-tape funnel,
    which is this digest's binding read-only contract (module docstring)."""
    if args.store_path:
        return read_family_halt_status(Path(args.store_path))
    try:
        store_path = resolve_store_path(source_env)
    except ExecStateDbNotConfiguredError as exc:
        return FamilyHaltStatus(value="unknown", reason=str(exc))
    return read_family_halt_status(store_path)


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    """Deliver one INFO digest. Missing tape is a named diagnostic, exit 0.

    Exit 0 on a missing file is deliberate: the diagnostic is INFO, and a
    non-zero status would also trip the unit's ``OnFailure=`` page. A
    malformed tape or an unknown ``source`` returns 1 — that is not an
    ordinary no-trade day.
    """
    args = _parse_args(argv)
    source_env = os.environ if env is None else env
    sink = resolve_alert_sink(env)
    if args.climate_day:
        climate_day = args.climate_day
    else:
        climate_day = default_climate_day(dt.datetime.now(dt.UTC)).isoformat()
    tape = _resolve_readable_path(
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
        report = funnel_for_day(_iter_jsonl(tape), window_open_stations=stations)
    except UnknownOfferTapeSourceError as exc:
        _emit(sink, detail=f"unrecognised offer-tape source {exc.source!r} for {climate_day}")
        return 1
    except (json.JSONDecodeError, ValueError, TypeError):
        _emit(sink, detail=f"decision tape unreadable for {climate_day}")
        return 1
    halt = _resolve_halt_status(args, source_env)
    summary_totals = _read_diagnostics_summary_totals(tape, climate_day)
    capped_total = summary_totals.capped_total
    if summary_totals.pre_tape_by_station:
        report = replace(report, pre_tape_by_station=summary_totals.pre_tape_by_station)
    _emit(
        sink,
        detail=format_digest_detail(
            report, climate_day=climate_day, halt=halt, capped_total=capped_total
        ),
    )
    _write_artefact(
        output_dir, report, climate_day=climate_day, halt=halt, capped_total=capped_total
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
