"""6b paper-replay driver: converts one live-recorder capture, replays it
against a REAL ASOS observation series, and scores the resulting fills.

See `docs/plans/PAPER_REPLAY_6B_BRIEF_2026-09-04.md` (draft + "Converged
peer review", BINDING). This is a MECHANISM test only -- n<=10 station-days
can never reach the PREREG v1 floors (n>=60 kill, n>=150 survive), and this
module never prints a KILL/SURVIVE/UNDERPOWERED family-tally verdict. It
prints `MECHANISM TEST -- NO VERDICT` in place of one, and never reads
`live_family_tally.build_live_family_tally`'s outcome field.

No hand computation: every number this module prints comes from
`breezy.settlement.trial_scorer.score_trials`,
`breezy.settlement.roi_bound.compute_roi_bound`/
`breezy.runtime.paper_replay.format_roi_bound_for_paper_replay`, or
`archive_correction_probe.wilson_interval` (the study's own Wilson helper) --
never an inline Wilson or bootstrap formula (RED "no hand computation" test).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, cast

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import OrderStatus
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Money

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.core.data import Data

    from breezy.domain.nws_climate_day import NwsClimateDay

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_correction_probe import wilson_interval
from run_weather_strategy_backtests import (
    WEATHER_VENUE,
    TapeInstrument,
    _convert_live_capture,
    _load_climate_day_records,
    _select_capture_instruments,
    _synthesize_close,
)
from weather_strategy_backtest_lib import settlement_prices_for_scenario

from breezy.persistence.scored_trial_store import write_scored_trials
from breezy.registry.sites import default_registry
from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import DEFAULT_BACKTEST_TRADER_ID, backtest
from breezy.runtime.exec_state_db_path import (
    ExecStateDbNotConfiguredError,
    NodeStorePathCheckResult,
    node_store_path_check,
    resolve_store_path,
)
from breezy.runtime.health import AlertPayload, emit_alert, resolve_alert_sink
from breezy.runtime.paper_replay import (
    EXPIRATION_LEG_PREFIX,
    PAPER_TRIAL_ID_PREFIX,
    PRECISION_ARMS,
    PaperReplayInputs,
    PrecisionMode,
    ReplayEntryContext,
    build_paper_replay_config,
    filled_trials_from_engine,
    format_roi_bound_for_paper_replay,
    load_replay_observations,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.settlement.roi_bound import (
    ROIInputRow,
    compute_roi_bound,
)
from breezy.settlement.trial_scorer import FilledTrial, score_trials
from breezy.strategy.current_rung_hold.backtest_only import (
    CurrentRungHoldBacktestStrategy,
)
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_backtest_only import (
    ContinuousRungHoldBacktestStrategy,
)
from breezy.strategy.current_rung_hold.monitor_store import MarkBuffer
from breezy.strategy.current_rung_hold.monitor_wiring import build_monitor_callables
from breezy.strategy.current_rung_hold.position_monitor import PositionMonitor
from breezy.strategy.current_rung_hold.strategy import _local_hour
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    DEFAULT_TRIAL_KEY_PREFIX,
    TrialDayLatch,
    open_trial_day_latch,
)
from breezy.strategy.depth10 import best_order

__all__ = [
    "PROVENANCE_HEADER_TEMPLATE",
    "SEVEN_DAYS_NS",
    "STARTING_BALANCE_USD",
    "NoDecisionWindowCoverageError",
    "UnlistedStationDayError",
    "VenueOutsideLiveDirError",
    "assert_decision_window_has_coverage",
    "build_provenance_header",
    "climate_day_records_to_settlement",
    "close_source_label",
    "print_tape_instrument_header",
    "run_one_precision_arm",
]

#: The strategy's own `[12:00,17:00)` LST decision window (`strategy.py`'s
#: `_WINDOW_START_HOUR_LST`/`_WINDOW_END_HOUR_LST`) -- duplicated here as
#: plain constants rather than importing the private names, since the
#: strategy module does not export them; the derivation itself (`_local_hour`)
#: IS imported and reused, never re-derived (see the module's coverage
#: precondition below).
_WINDOW_START_HOUR_LST: Final[int] = 12
_WINDOW_END_HOUR_LST: Final[int] = 17  # exclusive

STARTING_BALANCE_USD: Final[int] = 10_000
SEVEN_DAYS_NS: Final[int] = 7 * 24 * 60 * 60 * 1_000_000_000
_NS_PER_MINUTE: Final[int] = 60_000_000_000

#: INC-7 (plan §6, Rev 2.1 addendum M3): a SIBLING pair under `--monitor-
#: out-dir`, deliberately NOT nested the way the live composition root
#: nests `monitor/summaries` (`composition.py`'s `_MONITOR_SUMMARIES_
#: DIRNAME`) -- a disposable replay run's catalog and its summary rollups
#: are independently disposable here, so there is no reason to couple their
#: paths.
_MONITOR_CATALOG_DIRNAME: Final[str] = "monitor"
_MONITOR_SUMMARIES_DIRNAME: Final[str] = "monitor_summaries"
_MONITOR_SIDECAR_FILENAME: Final[str] = "position_monitor_marks.jsonl"

#: Default paper-replay store -- deliberately NOT the live scored_trials
#: dir (L-22: two independent barriers, see `paper_replay.py`'s docstring).
DEFAULT_PAPER_STORE: Final[Path] = Path(
    "~/.local/share/breezy/derived/paper_replay/scored_trials",
).expanduser()
_LIVE_STORE_MARKERS: Final[tuple[str, str]] = (
    "derived/scored_trials",
    "derived/live/scored_trials",
)

PROVENANCE_HEADER_TEMPLATE: Final[str] = (
    "PROVENANCE: paper_replay -- mechanism test only, NOT the live_small "
    "evidence family. n<={n_ceiling} station-days cannot reach PREREG v1 "
    "kill (n>=60) or survive (n>=150) floors. This run computes no KILL, "
    "SURVIVE, or UNDERPOWERED verdict; it verifies the fill/scoring "
    "mechanism only.\n"
    "MECHANISM TEST -- NO VERDICT\n"
    "lag_minutes={lag_minutes} (rule: received_at_ns = observed_at_ns + "
    "lag_minutes; PREREG A1 LIVE receipt anchor, NOT the archive study's "
    "find_lagged_entry anchor)\n"
    "precision_mode={precision_mode}\n"
    "station-days requested={n_requested} converted={n_data} live={n_live}"
)


class UnlistedStationDayError(ValueError):
    """A requested station-day is not among the tape's own listed days (L-23)."""


class VenueOutsideLiveDirError(ValueError):
    """The paper writer's output path resolves under the live scored_trials
    directory. Raised, never silently redirected -- see `paper_replay.py`'s
    L-22 provenance docstring."""


class EntryAskFromLatchMissingError(ValueError):
    """D1: a filled entry order has no corroborating `reason=='taken'`
    trial-day latch record to source its decision-instant `entry_ask` from.

    The measured defect (2026-09-01 MDW): `entry_ask` was built from
    ``ti.quotes[0].ask_price`` -- the FIRST quote of the WHOLE tape, four
    hours before the real decision. The strategy's own trial-day latch
    (`trial_day_latch.TrialDayLatch.record`) durably records the REAL
    decision-instant ask under `reason="taken"` the moment it submits, so
    that record is the only legitimate source. A filled order with no such
    record (missing, wrong `reason`, or a mismatched `instrument_id`) is
    refused here rather than ever defaulting to 0 or a tape quote.
    """


class NoDecisionWindowCoverageError(ValueError):
    """The tape carries zero `QuoteTick`s inside the station's own
    `[12:00,17:00)` LST decision window for the requested climate day.

    A 12-run sweep once printed `scored=0 refused=0` for every station-day
    on a tape whose quotes spanned 19:30 to 05:47 LST -- entirely outside
    the window -- because nothing refused the run before it silently
    zero-filled (L-23 shape: an uncovered day is refused loudly, never a
    silent zero)."""


def build_provenance_header(
    *,
    lag_minutes: int,
    precision_mode: str,
    n_requested: int,
    n_data: int,
    n_live: int,
    n_ceiling: int = 10,
) -> str:
    return PROVENANCE_HEADER_TEMPLATE.format(
        n_ceiling=n_ceiling,
        lag_minutes=lag_minutes,
        precision_mode=precision_mode,
        n_requested=n_requested,
        n_data=n_data,
        n_live=n_live,
    )


def assert_requested_days_are_listed(
    requested_days: Sequence[dt.date], listed_days: Sequence[dt.date],
) -> None:
    """L-23: a venue skips station-days; an unlisted day is refused, not a
    silent zero-fill run."""
    listed = set(listed_days)
    unlisted = [day for day in requested_days if day not in listed]
    if unlisted:
        raise UnlistedStationDayError(
            f"requested day(s) not listed by the tape: "
            f"{[d.isoformat() for d in unlisted]!r}; listed days: "
            f"{sorted(d.isoformat() for d in listed)!r}",
        )


def _lst_instant(now_ns: int, std_utc_offset_hours: float) -> dt.datetime:
    """The full LST instant for `now_ns`, for a diagnostic message.

    Mirrors `_local_hour`'s own UTC-to-LST conversion (`strategy.py`); kept
    separate because `_local_hour` intentionally returns only an hour, not
    enough precision for a "the tape's LST span was X to Y" refusal message.
    The actual [12,17) COVERAGE DECISION below is made by `_local_hour`
    itself, never re-derived here.
    """
    seconds, nanoseconds = divmod(now_ns, 1_000_000_000)
    instant = dt.datetime.fromtimestamp(seconds, tz=dt.UTC) + dt.timedelta(
        microseconds=nanoseconds // 1_000,
    )
    tz = dt.timezone(dt.timedelta(hours=std_utc_offset_hours))
    return instant.astimezone(tz)


def assert_decision_window_has_coverage(
    tape_instruments: Sequence[TapeInstrument],
    *,
    station: str,
    std_utc_offset_hours: float,
    source: Literal["quote", "depth"] = "quote",
) -> None:
    """(b) A tape with zero in-window market data is refused loudly, never
    run to a silent zero-fill (module docstring; L-23 shape).

    `"quote"` (the default -- L-28: the default IS the population, so
    every existing caller's behaviour is byte-unchanged) counts EXACTLY
    what `CurrentRungHoldStrategy.on_quote_tick` itself gates on:
    `_local_hour(tick.ts_event, std_utc_offset_hours)` in
    `[_WINDOW_START_HOUR_LST, _WINDOW_END_HOUR_LST)` -- the same
    derivation, imported, never re-derived.

    `"depth"` (SP-4 increment D) counts the SAME predicate
    `ContinuousRungHoldStrategy.on_order_book_depth` gates on -- a level
    walk via `best_order(depth.asks) is not None`
    (`breezy.strategy.depth10.best_order`, imported, never re-derived,
    L-35) -- a genuinely EXECUTABLE Depth10 ask, never merely a recorded
    depth snapshot (a one-sided book with only the size-0 Arrow pad on the
    ask side must not count as coverage).
    """
    if source == "depth":
        label = "executable Depth10 asks"
        event_ts = [
            depth.ts_event
            for ti in tape_instruments
            for depth in ti.depths
            if best_order(depth.asks) is not None
        ]
    else:
        label = "QuoteTicks"
        event_ts = [quote.ts_event for ti in tape_instruments for quote in ti.quotes]
    if not event_ts:
        raise NoDecisionWindowCoverageError(
            f"{station}: tape carries zero {label}; cannot cover the "
            f"[{_WINDOW_START_HOUR_LST:02d}:00,{_WINDOW_END_HOUR_LST:02d}:00) LST decision window."
        )
    covered = any(
        _WINDOW_START_HOUR_LST <= _local_hour(ts, std_utc_offset_hours) < _WINDOW_END_HOUR_LST
        for ts in event_ts
    )
    if covered:
        return
    lo = _lst_instant(min(event_ts), std_utc_offset_hours)
    hi = _lst_instant(max(event_ts), std_utc_offset_hours)
    raise NoDecisionWindowCoverageError(
        f"{station}: tape's {label} span {lo.isoformat()} to {hi.isoformat()} LST, "
        f"entirely outside the [{_WINDOW_START_HOUR_LST:02d}:00,{_WINDOW_END_HOUR_LST:02d}:00) "
        "LST decision window; refusing rather than a silent zero-fill run (L-23 shape)."
    )


def print_tape_instrument_header(
    tape_instruments: Sequence[TapeInstrument], std_utc_offset_hours: float,
) -> None:
    """(3) Per-instrument quote count, depth-update count, and the tape's own
    LST span -- printed unconditionally in the run header, so a capture that
    never reaches the decision window is visible without instrumentation."""
    for ti in tape_instruments:
        ts_values = [record.ts_event for record in (*ti.quotes, *ti.depths)]
        span = (
            f"{_lst_instant(min(ts_values), std_utc_offset_hours).isoformat()} to "
            f"{_lst_instant(max(ts_values), std_utc_offset_hours).isoformat()}"
            if ts_values
            else "no market data"
        )
        print(
            f"tape {ti.instrument.id}: quotes={len(ti.quotes)} "
            f"depth_updates={len(ti.depths)} lst_span={span}"
        )


def assert_paper_write_path_is_not_live(output_dir: Path) -> None:
    resolved = str(output_dir.resolve())
    if any(marker in resolved for marker in _LIVE_STORE_MARKERS):
        raise VenueOutsideLiveDirError(
            f"--output-dir {output_dir} resolves under the live scored_trials "
            "directory; the paper writer refuses to write there (L-22).",
        )


class ReplayLatchStoreIsLiveError(ValueError):
    """A replay candidate path resolves to (or under) the RUNNING node's own
    exec-state store. Names ONLY the offending replay path -- mirroring
    `node_store_path_check`'s own no-leak discipline -- never the live
    path itself."""


#: SP-4 increment E (E-1, AM-13): MERGED with `_LIVE_STORE_MARKERS` (no
#: separate `_LIVE_LATCH_MARKERS`), extended with the live state-store
#: root component -- read from this repo's OWN binding prohibition ("never
#: open anything under `~/.local/share/breezy/state`") and the naming
#: convention `deploy/systemd/breezy-trade-supervisor.service` uses for
#: every OTHER path it documents (`~/.local/share/breezy/logs/...`); the
#: unit file itself never inlines the exec-state DB path (it is supplied
#: by a gitignored `EnvironmentFile=`, never read here -- L-24: this
#: module never reads operator/venue credentials). This is layer 4 --
#: additive on top of layers 1-3's path-derived teeth, so an imprecise
#: marker only ever makes the guard MORE conservative, never less
#: (L-12 widen-never-relax).
_LIVE_STATE_STORE_ROOT_MARKER: Final[str] = "local/share/breezy/state"
_GUARD_MARKERS: Final[tuple[str, ...]] = (*_LIVE_STORE_MARKERS, _LIVE_STATE_STORE_ROOT_MARKER)


@dataclass(frozen=True, slots=True)
class GuardReport:
    """`assert_replay_latch_store_is_not_live`'s report -- printed by `main`
    so a DEGRADED run (layer 1 unavailable, layer 2 unset) is never
    mistaken for a passed one."""

    oracle: str
    env_set: bool
    markers_checked: int
    candidates_checked: int

    def render(self) -> str:
        return (
            f"live_store_guard=oracle:{self.oracle} "
            f"env:{'set' if self.env_set else 'unset'} "
            f"markers:{self.markers_checked} candidates:{self.candidates_checked}"
        )


def assert_replay_latch_store_is_not_live(
    candidates: Sequence[Path],
    *,
    environ: Mapping[str, str] | None = None,
    proc_root: Path = Path("/proc"),
) -> GuardReport:
    """SP-4 increment E: FOUR ordered layers over EVERY candidate path,
    composing the SHIPPED `node_store_path_check` oracle rather than
    re-deriving it (L-11 -- the native exists and is USED). Never opens,
    connects to, or reads any DB. Raises `ReplayLatchStoreIsLiveError`
    naming ONLY the offending replay candidate, never the live path.

    Layer 1 (PRIMARY): the running `breezy-trade` node's OWN `/proc`
    environ, via `node_store_path_check` -- `MATCH` refuses immediately.
    `MISMATCH`/`NO_NODE` are recorded, never treated as a pass signal (the
    oracle compares exact paths only and cannot see directories);
    `DISCOVERY_FAILED` is recorded as a degraded run, never silently read
    as clean (see the module-level docstring on this function's own
    degradation stance, below).
    Layer 2: env resolution (`resolve_store_path`); unset in THIS process
    is expected -- the node's own environ, read by layer 1, is what
    matters here.
    Layer 3: when layer 2 yields a path, refuse a candidate equal to it,
    equal to its parent, or descending from that parent -- the latch DB
    and its `-wal`/`-shm`/flock sidecars share the store's directory, the
    real collision surface the exact-match oracle cannot express.
    Layer 4 (always, in addition): the MERGED `_GUARD_MARKERS`.

    Degradation stance: if layer 1 returns `DISCOVERY_FAILED` for every
    candidate AND layer 2 is unset, only layer 4 has genuinely run. The
    run is ALLOWED TO PROCEED -- refusing every replay on an unreadable
    `/proc` would block real work for no safety gain while layer 4 still
    fires -- but `GuardReport.render()` makes the degradation visible; the
    artefact must carry it.
    """
    oracle_results: list[NodeStorePathCheckResult] = [
        node_store_path_check(candidate, proc_root=proc_root) for candidate in candidates
    ]
    for candidate, result in zip(candidates, oracle_results, strict=True):
        if result == "MATCH":
            raise ReplayLatchStoreIsLiveError(
                f"{candidate} is the RUNNING breezy-trade node's own exec "
                "state store (node_store_path_check: MATCH); refusing.",
            )
    if "DISCOVERY_FAILED" in oracle_results:
        oracle_summary = "DISCOVERY_FAILED"
    elif "MISMATCH" in oracle_results:
        oracle_summary = "MISMATCH"
    else:
        oracle_summary = "NO_NODE"

    source = os.environ if environ is None else environ
    try:
        live_path: Path | None = resolve_store_path(source)
        env_set = True
    except ExecStateDbNotConfiguredError:
        live_path = None
        env_set = False

    if live_path is not None:
        live_real = Path(os.path.realpath(live_path))
        live_parent = live_real.parent
        for candidate in candidates:
            candidate_real = Path(os.path.realpath(candidate))
            if candidate_real == live_real or candidate_real == live_parent or (
                live_parent in candidate_real.parents
            ):
                raise ReplayLatchStoreIsLiveError(
                    f"{candidate} resolves to, or under, the exec state "
                    "store's own directory; refusing.",
                )

    for candidate in candidates:
        candidate_str = str(candidate.resolve())
        if any(marker in candidate_str for marker in _GUARD_MARKERS):
            raise ReplayLatchStoreIsLiveError(
                f"{candidate} matches a live-store marker; refusing.",
            )

    return GuardReport(
        oracle=oracle_summary,
        env_set=env_set,
        markers_checked=len(_GUARD_MARKERS),
        candidates_checked=len(candidates),
    )


def read_asos_rows(csv_path: Path) -> list[dict[str, str]]:
    """`station,valid,metar` rows verbatim -- no price ever derived here."""
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@contextmanager
def _latch_context(
    store_path: Path, *, key_prefix: str = DEFAULT_TRIAL_KEY_PREFIX,
) -> Iterator[TrialDayLatch]:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(intent_latch, key_prefix=key_prefix)


def _latch_factory(
    store_path: Path, *, key_prefix: str = DEFAULT_TRIAL_KEY_PREFIX,
) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    return lambda: _latch_context(store_path, key_prefix=key_prefix)


def _entry_context_for(
    tape_instrument: TapeInstrument, *, scheduled_release_at_ns: int, entry_ask: Decimal,
) -> ReplayEntryContext:
    facts = tape_instrument.facts
    return ReplayEntryContext(
        station=facts.settlement_station,
        climate_day=facts.climate_day.isoformat(),
        bucket=facts,
        entry_ask=entry_ask,
        scheduled_release_at_ns=scheduled_release_at_ns,
    )


def _filled_instrument_ids(engine: BacktestEngine) -> list[str]:
    """Every FILLED, non-expiration-leg order's `instrument_id` (D1).

    Applies the SAME filter `filled_trials_from_engine` applies internally --
    duplicated here (that filter is a private detail of a function this
    module still calls afterwards) using the exported `EXPIRATION_LEG_PREFIX`
    so this refusal can run BEFORE `entry_contexts` even exists.
    """
    return [
        str(order.instrument_id)
        for order in engine.cache.orders()
        if order.status == OrderStatus.FILLED
        and not str(order.client_order_id).startswith(EXPIRATION_LEG_PREFIX)
    ]


def _entry_contexts_from_latch(
    tape_instruments: Sequence[TapeInstrument],
    engine: BacktestEngine,
    *,
    station: str,
    climate_day: str,
    latch_store_path: Path,
    scheduled_release_at_ns: int,
    latch_key_prefix: str = DEFAULT_TRIAL_KEY_PREFIX,
) -> dict[str, ReplayEntryContext]:
    """D1: `entry_ask` for the ONE latched instrument, sourced from the
    strategy's own trial-day latch record -- never the tape's first quote.

    Reads the latch AFTER `engine.run()` has already completed (the
    strategy's own `on_stop` releases its flock before `backtest()` ever
    yields the engine -- `strategy.py`'s "Close the trial-day latch this
    strategy owns, unconditionally" -- so re-opening it here is safe, not a
    second concurrent opener). A filled order on an instrument the latch does
    not corroborate is refused (`EntryAskFromLatchMissingError`), never
    silently dropped by `filled_trials_from_engine`'s `ctx is None` skip.
    Instruments with no fill get no entry (they need none -- see the module
    docstring).
    """
    filled_ids = _filled_instrument_ids(engine)
    if not filled_ids:
        return {}
    # Plan S1 (operator ruling 2026-09-14): the v3 latch keys TRIAL by
    # instrument-day, not station-day alone -- read per filled instrument,
    # through `record_with_legacy_fallback` so a v2-default-prefix record
    # (never instrument-keyed) is still found unchanged (byte-identical for
    # v2). Multiple filled instruments on the same station-day are now
    # legitimate (no longer a one-contract-per-station ceiling) and each
    # gets its own corroborated entry context.
    with _latch_context(latch_store_path, key_prefix=latch_key_prefix) as latch:
        records = {
            instrument_id: latch.record_with_legacy_fallback(
                station, climate_day, key_instrument_id=instrument_id,
            )
            for instrument_id in filled_ids
        }
    unexplained = sorted(
        instrument_id
        for instrument_id, record in records.items()
        if record is None or record.reason != "taken" or record.instrument_id != instrument_id
    )
    if unexplained:
        raise EntryAskFromLatchMissingError(
            f"{station}/{climate_day}: filled order(s) on instrument(s) "
            f"{unexplained!r} have no corroborating reason='taken' trial-day "
            f"latch record (records={records!r}).",
        )
    entry_contexts: dict[str, ReplayEntryContext] = {}
    for instrument_id, record in records.items():
        assert record is not None  # narrowed by the unexplained check above
        ti = next(
            ti for ti in tape_instruments if str(ti.instrument.id) == instrument_id
        )
        entry_contexts[instrument_id] = _entry_context_for(
            ti, scheduled_release_at_ns=scheduled_release_at_ns, entry_ask=record.ask,
        )
    return entry_contexts


SettlementByKey = dict[tuple[str, str], "NwsClimateDay"]


def close_source_label(tape_instruments: Sequence[TapeInstrument]) -> str:
    """Which settlement-close source this run uses -- printed verbatim in the
    run header, never inferred by a reader from behaviour.

    `_select_capture_instruments` populates `TapeInstrument.closes` from the
    capture's OWN recorded `CONTRACT_EXPIRED` closes when present; a tape
    with none for ANY instrument falls back to the documented
    `_synthesize_close` precedent (`run_weather_strategy_backtests.py:722-738`)
    for every instrument in this run -- a cosmetic `close_price`, real
    economics from `settlement_prices` derived from the FINAL climate day.
    """
    if all(ti.closes for ti in tape_instruments):
        return "closes=recorded"
    return "closes=synthesized_after_last_tick (price cosmetic; settlement_prices from FINAL)"


def _settlement_prices_for_synthesis(
    tape_instruments: Sequence[TapeInstrument], settlement_by_key: SettlementByKey,
) -> dict[InstrumentId, float]:
    """`settlement_prices_for_scenario` restricted to the instruments that
    need a SYNTHESIZED close, using ONLY stations with a FINAL record.

    An instrument whose (station, climate_day) has no FINAL record yet is
    deliberately left OUT of both the returned prices and (by the caller)
    the closes list -- the existing `SettlementInvariantError`
    (`assert_settlement_invariants`'s CLOSE rule) then refuses the run, the
    same refusal path a genuinely close-less capture already takes. Never a
    fabricated settlement price for a PENDING station-day.
    """
    facts_by_id = {
        ti.instrument.id: ti.facts
        for ti in tape_instruments
        if not ti.closes
        and (ti.facts.settlement_station, ti.facts.climate_day.isoformat())
        in settlement_by_key
    }
    observed_by_station = {
        ti.facts.settlement_station: cast(
            int,
            settlement_by_key[
                (ti.facts.settlement_station, ti.facts.climate_day.isoformat())
            ].tmax_f,
        )
        for ti in tape_instruments
        if ti.instrument.id in facts_by_id
    }
    if not facts_by_id:
        return {}
    return settlement_prices_for_scenario(facts_by_id, observed_by_station)


@dataclass(frozen=True, slots=True)
class PrecisionArmResult:
    """`run_one_precision_arm`'s full return.

    (a) Reporting gap: the strategy's own `RefusalCounter.counts` snapshot
    rides along with the arm's `FilledTrial`s, so a caller can never discard
    the strategy object and lose visibility into refusals it counted
    (`CurrentRungHoldStrategy.on_quote_tick` recorded 21,086
    `outside_decision_window` refusals that a prior version of this driver
    never reported). `strategy_refusals` is a wholly DIFFERENT vocabulary
    from the 6c scorer's `refused` count over `FilledTrial`s -- see
    `_print_roi_and_wilson`'s `scoring_refused` label; the two must never be
    conflated under one name.

    `strategy_diagnostics` is the strategy's `self.diagnostics` snapshot --
    the WAIT-state counts (`in_window_not_executable`,
    `in_window_no_running_max_yet`, `in_window_rung_not_current`), a
    DIFFERENT vocabulary again from `strategy_refusals` (see
    `strategy.py`'s `_DIAG_*` module docstring: never a refusal reason,
    never added to `RefusalAlerter`).

    `strategy_position_events` is the strategy's `self.position_events`
    snapshot (SP-4 increment C, AM-4): a THIRD, again different vocabulary
    (`startup_evidence_missing`, `unreconciled_long_no_fill`,
    `family_halt_at_start`, `fill_walk_unreadable`, `unjoinable_fill_halt`,
    `fill_join_error`) -- never a refusal, never a WAIT diagnostic. Both
    `CurrentRungHoldStrategy` and `ContinuousRungHoldStrategy` carry this
    attribute, so it is populated UNCONDITIONALLY, never behind a
    `hasattr`/`isinstance` branch (AM-4 -- the old "v2 lacks
    `position_events`" premise was WITHDRAWN AS FALSE).
    """

    trials: tuple[FilledTrial, ...]
    strategy_refusals: Mapping[str, int] = field(default_factory=dict)
    strategy_diagnostics: Mapping[str, int] = field(default_factory=dict)
    strategy_position_events: Mapping[str, int] = field(default_factory=dict)


class ReplayEvidenceUnboundError(RuntimeError):
    """`_FlatStartupEvidence` was called before `bind()`."""


class _FlatStartupEvidence:
    """SP-4 increment C (AM-6): a `position_evidence_reader` for
    `ContinuousRungHoldBacktestStrategy` that supplies a COMPLETE, flat
    (`net_position="0"`) startup-evidence dict for every slug in the BOUND
    strategy's OWN `_facts`, read at CALL time -- never derived from a
    snapshot instrument list, so it can never diverge from what `on_start`
    actually resolved.

    Constructed UNBOUND and passed to the strategy's constructor (the
    strategy object does not exist yet); the driver calls :meth:`bind`
    immediately after construction, before the engine ever calls
    `on_start`. Calling this before `bind()` raises
    :class:`ReplayEvidenceUnboundError` rather than emitting an empty
    `positions` list, which would read as UNKNOWN for every slug and
    silently halt the never-arm walk -- a plan failure disguised as a
    mechanism result (L-24).

    The positions this supplies are SYNTHETIC (L-24): this is a mechanism
    test, never a live position read.
    """

    def __init__(self) -> None:
        self._strategy: ContinuousRungHoldBacktestStrategy | None = None
        self.emitted_slugs: frozenset[str] = frozenset()
        #: `False` until this reader is actually invoked. A family halt (or
        #: any other check `_run_never_arm_walk` runs BEFORE consulting
        #: evidence) can legitimately short-circuit before this is ever
        #: called -- the driver's coupling assertion below only compares
        #: `emitted_slugs` once it knows a comparison is meaningful.
        self.called: bool = False

    def bind(self, strategy: ContinuousRungHoldBacktestStrategy) -> None:
        self._strategy = strategy

    def __call__(self) -> dict[str, object]:
        if self._strategy is None:
            raise ReplayEvidenceUnboundError(
                "_FlatStartupEvidence was called before bind() -- the "
                "driver must bind it to the just-constructed strategy "
                "before the engine ever calls on_start().",
            )
        self.called = True
        slugs = {InstrumentId.from_str(iid).symbol.value for iid in self._strategy._facts}
        self.emitted_slugs = frozenset(slugs)
        return {
            "v": 1,
            "position_read_refused": False,
            "eof_complete": True,
            "fill_walk_complete": True,
            "positions": [{"slug": slug, "net_position": "0"} for slug in sorted(slugs)],
        }


def install_position_monitor(
    strategy: ContinuousRungHoldBacktestStrategy,
    *,
    out_dir: Path,
    clock_ns: Callable[[], int],
) -> PositionMonitor:
    """INC-7 (plan §6, Rev 2.1 addendum M3): attach a shadow
    :class:`PositionMonitor` to `strategy` inside the v3 paper-replay
    harness, run under a real engine ``TestClock``.

    F1 DRY extraction: the eight read-only closures over the strategy's own
    cache/latch/facts/accumulators (never a direct reference to its mutating
    surface, M7 D3 pin: never `_hunt_tick`/`_maybe_submit`, never
    `_decision_ask_by_station_day`) now come from
    :func:`build_monitor_callables` (``monitor_wiring.py``) -- the SAME
    factory ``composition.py::_build_position_monitor_for`` and the contract
    test's ``_wire_monitor`` also call. This function still owns the
    directory layout the live composition root does not use (`out_dir/
    monitor` plus a SIBLING `out_dir/monitor_summaries`, never nested the
    way the live root nests `monitor/summaries`) and a `MarkBuffer` carrying
    a JSONL sidecar (a replay run is disposable, so a best-effort on-disk
    trail of every mark is worth the write cost the live node's bare
    `MarkBuffer()` deliberately avoids).

    `clock_ns` is taken as a caller-supplied callable, never derived
    internally from `strategy.clock.timestamp_ns` at call time: a
    backtest-only strategy's `.clock` attribute is a placeholder `Clock()`
    until `Strategy.register()` swaps in the engine's real `TestClock`
    (`nautilus_trader.trading.strategy.Strategy.__init__`/`register_base`),
    and this function always runs BEFORE that registration (the same
    ordering `composition.py` uses). Binding a bare method reference at
    THIS call site would capture the placeholder forever; the caller must
    pass a callable that reads `strategy.clock` fresh on every invocation
    (e.g. ``lambda: strategy.clock.timestamp_ns()``), which stays correct
    across the registration swap.

    Default OFF (module docstring; plan spec): a caller that never invokes
    this leaves `strategy._position_monitor` at its inherited `None`, so
    every existing replay artefact stays byte-identical.
    """
    monitor_root = out_dir / _MONITOR_CATALOG_DIRNAME
    summaries_dir = out_dir / _MONITOR_SUMMARIES_DIRNAME
    sink = resolve_alert_sink()

    def _report(event: str, detail: Mapping[str, object]) -> None:
        emit_alert(
            sink,
            AlertPayload(
                severity="WARN", event=event, site=str(strategy.id), detail=str(dict(detail)),
            ),
        )

    callables = build_monitor_callables(strategy)
    monitor = PositionMonitor(
        clock_ns=clock_ns,
        positions_open=callables.positions_open,
        accumulators=strategy._accumulators,
        latch_record=callables.latch_record,
        rung_geometry=callables.rung_geometry,
        fee_coefficient_for=callables.fee_coefficient_for,
        leg_for=callables.leg_for,
        station_for=callables.station_for,
        climate_day_for=callables.climate_day_for,
        hour_lst_for=callables.hour_lst_for,
        stale_observation_bound_ns=strategy._config.stale_observation_minutes * _NS_PER_MINUTE,
        trial_id_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        buffer=MarkBuffer(sidecar_path=out_dir / _MONITOR_SIDECAR_FILENAME),
        catalog_root=monitor_root,
        summaries_dir=summaries_dir,
        report=_report,
    )
    strategy._position_monitor = monitor
    return monitor


def run_one_precision_arm(
    *,
    tape_instruments: Sequence[TapeInstrument],
    observation_rows: Sequence[dict[str, str]],
    station: str,
    lag_minutes: int,
    precision_mode: PrecisionMode,
    latch_store_path: Path,
    settlement_by_key: SettlementByKey,
    strategy_cls: type[
        CurrentRungHoldBacktestStrategy | ContinuousRungHoldBacktestStrategy
    ] = CurrentRungHoldBacktestStrategy,
    latch_key_prefix: str = DEFAULT_TRIAL_KEY_PREFIX,
    monitor_out_dir: Path | None = None,
) -> PrecisionArmResult:
    """Run one (lag, precision) arm of the replay; return its `FilledTrial`s
    AND the strategy's own refusal counts (`PrecisionArmResult`).

    `tape_instruments` supplies BOTH `QuoteTick` and `OrderBookDepth10` --
    `build_paper_replay_config` refuses a quote-only instrument (RED test 2).

    `monitor_out_dir` (INC-7): `None` (default) never installs a
    `PositionMonitor` -- byte-identical to before this parameter existed.
    Non-`None` is meaningful only for the continuous arm
    (`strategy_cls is ContinuousRungHoldBacktestStrategy`); passing it
    alongside `CurrentRungHoldBacktestStrategy` is a silent no-op, since the
    v2 strategy carries no `_position_monitor` hook at all.

    Review finding F2: `main` calls this function once per entry in
    `PRECISION_ARMS`, all sharing the ONE `monitor_out_dir` an operator
    passes on the CLI. Neither `PositionMarkRecord` nor
    `PositionMonitorSummary` carries a precision-arm discriminator, so two
    arms writing to the identical `monitor_out_dir/monitor` catalog and
    `monitor_out_dir/monitor_summaries` directory can collide --
    `read_monitor_summaries`' dedup by `(trial_id, max monitor_seq)` would
    then silently keep only one arm's row. `install_position_monitor` is
    therefore called against `monitor_out_dir / precision_mode`, giving
    each arm its own `<mode>/monitor` + `<mode>/monitor_summaries` pair.
    """
    inputs = PaperReplayInputs(lag_minutes=lag_minutes, precision_mode=precision_mode)
    # `StationObservation.station` must carry the IEM ASOS/ICAO id
    # (`CurrentRungHoldStrategy.on_data` maps it back via `_STATION_BY_ICAO`,
    # `strategy.py:162-166`) -- NOT the settlement station code `station`
    # (used below for `CurrentRungHoldConfig.stations`, a different registry
    # key). Native accessor, mirrors `breezy/registry/sites.toml`'s
    # `iem_asos_id` (`registry/sites.py::SettlementSite.iem_asos_id`).
    icao = default_registry().settlement_site(WEATHER_VENUE, station).iem_asos_id
    observations = load_replay_observations(
        station=icao, rows=observation_rows, inputs=inputs,
    )
    instruments = [ti.instrument for ti in tape_instruments]
    market_data: list[Data] = []
    for ti in tape_instruments:
        # D2: depths BEFORE quotes. The adapter stamps a quote and its own
        # depth snapshot with the IDENTICAL `ts_init` (one WS message --
        # `adapters/polymarket_us/parsing.py:734,824`). `_group_market_data`
        # groups by first-appearance order in this list
        # (`backtest_harness.py`'s `market_data` docstring), and
        # `BacktestEngine.add_data` re-sorts its accumulated `_data` by
        # `ts_init` with Python's stable `sorted()`
        # (`backtest/engine.pyx:899`, `self._data = sorted(self._data,
        # key=lambda x: x.ts_init)`) after EACH `add_data` call. Whichever
        # group is added first stays earlier for a tied `ts_init`, so
        # depths-first here is what makes an `OrderBookDepth10` precede its
        # own-instant `QuoteTick` -- the book already reflects the new
        # snapshot when `on_quote_tick` submits the IOC, instead of the
        # PREVIOUS (stale) snapshot.
        market_data.extend(ti.depths)
        market_data.extend(ti.quotes)
    if not market_data:
        return PrecisionArmResult(
            trials=(),
            strategy_refusals={},
            strategy_diagnostics={},
            strategy_position_events={},
        )
    ts_values = [record.ts_init for record in market_data]
    capture_window_ns = (min(ts_values), max(ts_values))

    # The capture's OWN recorded `InstrumentClose`s (`TapeInstrument.closes`,
    # populated by `_select_capture_instruments`) -- stamped as recorded,
    # never synthesized, for instruments that carry one. `instruments_without_
    # close` is NEVER passed here: an instrument with neither a recorded
    # close NOR a FINAL climate day to synthesize one from still refuses via
    # `SettlementInvariantError` (the invariant working, not a bypass).
    recorded_closes: list[Data] = [close for ti in tape_instruments for close in ti.closes]
    settlement_prices: dict[InstrumentId, float] = {
        close.instrument_id: float(close.close_price)
        for ti in tape_instruments
        for close in ti.closes
    }

    # `run_weather_strategy_backtests.py::_synthesize_close` precedent (module
    # docstring): one CONSTRUCTED `CONTRACT_EXPIRED` close per instrument that
    # the capture itself never closed, strictly after that instrument's last
    # market-data record, with a COSMETIC `close_price`. Real economics flow
    # ONLY through `settlement_prices`, derived here from the FINAL climate
    # day via `settlement_prices_for_scenario` -- never the synthesized
    # close's own price.
    synthesized_settlement_prices = _settlement_prices_for_synthesis(
        tape_instruments, settlement_by_key,
    )
    synthesized_closes: list[Data] = [
        _synthesize_close(ti)
        for ti in tape_instruments
        if not ti.closes and ti.instrument.id in synthesized_settlement_prices
    ]
    closes: list[Data] = [*recorded_closes, *synthesized_closes]
    settlement_prices = {**settlement_prices, **synthesized_settlement_prices}

    config = build_paper_replay_config(
        instruments=instruments,
        market_data=[*market_data, *closes],
        weather_data=as_backtest_data(list(observations)),
        settlement_prices=settlement_prices,
        starting_balances=(Money(STARTING_BALANCE_USD, USD),),
        capture_window_ns=capture_window_ns,
    )

    cfg = CurrentRungHoldConfig(
        instrument_ids=tuple(i.id for i in instruments), stations=(station,),
    )

    evidence: _FlatStartupEvidence | None = None
    strategy: CurrentRungHoldBacktestStrategy | ContinuousRungHoldBacktestStrategy
    if strategy_cls is ContinuousRungHoldBacktestStrategy:
        # AM-6: constructed UNBOUND, bound to the strategy AFTER
        # construction -- the reader reads `strategy._facts` at CALL time,
        # never a snapshot instrument list. Explicit `is` branch, never
        # `getattr`/dynamic-import duck-typing (L-12/AM-5). Calls the
        # CONCRETE class directly (not through `strategy_cls`) so mypy can
        # see the `position_evidence_reader` kwarg -- narrowing a `type[A |
        # B]`-typed variable via `is` does not narrow its call signature.
        evidence = _FlatStartupEvidence()
        strategy = ContinuousRungHoldBacktestStrategy(
            cfg,
            trial_day_latch_factory=_latch_factory(
                latch_store_path, key_prefix=latch_key_prefix,
            ),
            position_evidence_reader=evidence,
        )
        evidence.bind(strategy)
        if monitor_out_dir is not None:
            # F2: keyed per arm -- see this function's own docstring.
            install_position_monitor(
                strategy,
                out_dir=monitor_out_dir / precision_mode,
                clock_ns=lambda: strategy.clock.timestamp_ns(),
            )
    else:
        strategy = strategy_cls(
            cfg,
            trial_day_latch_factory=_latch_factory(
                latch_store_path, key_prefix=latch_key_prefix,
            ),
        )

    with backtest(config, strategies=(strategy,), allow_idle_strategies=True) as engine:
        # D1: `entry_ask` comes from the strategy's own trial-day latch
        # record, never a tape quote. `tape_instruments` is non-empty here
        # (guarded by the `market_data` emptiness check above) and every
        # entry shares one `climate_day` -- `_select_capture_instruments`
        # filters to exactly one before this function is ever called.
        climate_day = tape_instruments[0].facts.climate_day.isoformat()
        entry_contexts = _entry_contexts_from_latch(
            tape_instruments,
            engine,
            station=station,
            climate_day=climate_day,
            latch_store_path=latch_store_path,
            scheduled_release_at_ns=max(ts_values) + SEVEN_DAYS_NS,
            latch_key_prefix=latch_key_prefix,
        )
        trials = filled_trials_from_engine(engine, entry_contexts)
    if evidence is not None and evidence.called:
        # AM-20/NB-6 (driver-side half): the evidence reader's own record of
        # what it last emitted must equal the strategy's own `_facts` slug
        # set -- a plan failure disguised as a mechanism result (an empty
        # `positions` list reading as UNKNOWN for every slug) diverges here,
        # never silently. Skipped when the reader was never consulted at
        # all (e.g. a family halt short-circuits `_run_never_arm_walk`
        # BEFORE it reads evidence) -- there is nothing to compare.
        facts_slugs = frozenset(
            InstrumentId.from_str(iid).symbol.value for iid in strategy._facts
        )
        assert evidence.emitted_slugs == facts_slugs, (
            f"evidence emitted {sorted(evidence.emitted_slugs)!r} but "
            f"strategy._facts holds {sorted(facts_slugs)!r}"
        )
    return PrecisionArmResult(
        trials=trials,
        strategy_refusals=dict(strategy.refusals.counts),
        strategy_diagnostics=dict(strategy.diagnostics.counts),
        strategy_position_events=dict(strategy.position_events.counts),
    )


def climate_day_records_to_settlement(
    tape_instruments: Sequence[TapeInstrument], weather_catalog_root: Path,
) -> dict[tuple[str, str], NwsClimateDay]:
    """The highest-`revision_seq` FINAL `NwsClimateDay` per (station,
    climate_day), keyed for `score_trials` -- never a preliminary print
    (RED test 9, "settlement comes from the final climate day only")."""
    stations = sorted({ti.facts.settlement_station for ti in tape_instruments})
    climate_days = sorted({ti.facts.climate_day for ti in tape_instruments})
    by_key: dict[tuple[str, str], NwsClimateDay] = {}
    for climate_day in climate_days:
        records = _load_climate_day_records(
            weather_catalog_root, stations=stations, climate_day=climate_day,
        )
        best: dict[str, NwsClimateDay] = {}
        for record in records:
            if not record.is_final:
                continue
            current = best.get(record.station)
            if current is None or record.revision_seq > current.revision_seq:
                best[record.station] = record
        for station, record in best.items():
            by_key[(station, climate_day.isoformat())] = record
    return by_key


def _pairs_with_settlement(
    trials: Sequence[FilledTrial], settlement_by_key: SettlementByKey,
) -> tuple[tuple[FilledTrial, NwsClimateDay | None], ...]:
    return tuple(
        (trial, settlement_by_key.get((trial.station, trial.climate_day)))
        for trial in trials
    )


def _print_roi_and_wilson(
    trials: Sequence[FilledTrial], settlement_by_key: SettlementByKey, now_ns: int,
) -> None:
    scored, refused = score_trials(
        _pairs_with_settlement(trials, settlement_by_key), now_ns=now_ns,
    )
    # Relabelled from the old `scored=... refused=...` -- `refused` here is
    # the 6c scorer's own vocabulary over `FilledTrial`s, a DIFFERENT count
    # from the strategy's own `RefusalCounter` (`PrecisionArmResult.
    # strategy_refusals`, printed separately in `main`). The two must never
    # share a bare `refused=` label -- that conflation is exactly how
    # 21,086 real `outside_decision_window` refusals stayed invisible while
    # this line printed `scored=0 refused=0` for every station-day.
    print(f"scored={len(scored)} scoring_refused={len(refused)}")
    if scored:
        held = sum(1 for row in scored if row.held)
        lower, upper = wilson_interval(held, len(scored))
        print(f"realized hold rate Wilson interval: [{lower:.4f}, {upper:.4f}] (n={len(scored)})")
        slippages = [row.slippage for row in scored]
        print(
            f"slippage: n={len(slippages)}, mean={sum(slippages) / len(slippages)}, "
            f"max={max(slippages)}",
        )
    roi_inputs = tuple(
        ROIInputRow(pnl=row.pnl, cost=row.fill_px + row.fee, excluded_reason=None)
        for row in scored
    )
    print(format_roi_bound_for_paper_replay(compute_roi_bound(roi_inputs)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--climate-day", required=True, type=str)
    parser.add_argument("--station", required=True, type=str)
    parser.add_argument("--tape-instance-id", required=True, type=str)
    parser.add_argument("--tape-subdirectory", default="live", type=str)
    parser.add_argument("--quote-catalog", required=True, type=Path)
    parser.add_argument("--work-catalog", required=True, type=Path)
    parser.add_argument("--asos-cache-csv", required=True, type=Path)
    parser.add_argument("--weather-catalog-root", required=True, type=Path)
    parser.add_argument(
        "--lag-minutes", required=True, type=int,
        help="REQUIRED, no default -- see PaperReplayInputs.lag_minutes.",
    )
    parser.add_argument("--output-dir", default=DEFAULT_PAPER_STORE, type=Path)
    parser.add_argument(
        "--strategy",
        choices=("current_rung_hold", "continuous_rung_hold"),
        default="current_rung_hold",
        type=str,
        help=(
            "Which BACKTEST-ONLY strategy subclass to replay. Default "
            "'current_rung_hold' keeps the v2 golden transcript byte-"
            "identical; 'continuous_rung_hold' selects "
            "ContinuousRungHoldBacktestStrategy (SP-4)."
        ),
    )
    parser.add_argument(
        "--monitor-out-dir",
        default=None,
        type=Path,
        help=(
            "INC-7: install a shadow PositionMonitor under this directory, "
            "one <precision_mode>/monitor + <precision_mode>/monitor_summaries "
            "pair per PRECISION_ARMS entry (F2: never a shared pair, which "
            "could hide one arm's row). Meaningful only with "
            "--strategy continuous_rung_hold; default None never installs "
            "one, so every existing replay artefact stays byte-identical."
        ),
    )
    args = parser.parse_args(argv)

    # Explicit `if`, never `getattr`/dynamic-import duck-typing (L-12/AM-5;
    # test_the_dynamic_import_call_site_count_is_unchanged pins the count).
    if args.strategy == "continuous_rung_hold":
        strategy_cls: type[
            CurrentRungHoldBacktestStrategy | ContinuousRungHoldBacktestStrategy
        ] = ContinuousRungHoldBacktestStrategy
        latch_key_prefix = CONTINUOUS_TRIAL_KEY_PREFIX
    else:
        strategy_cls = CurrentRungHoldBacktestStrategy
        latch_key_prefix = DEFAULT_TRIAL_KEY_PREFIX

    assert_paper_write_path_is_not_live(args.output_dir)
    climate_day = dt.date.fromisoformat(args.climate_day)

    # SP-4 increment E (CX-B3): runs immediately after the check above and
    # BEFORE `_convert_live_capture`, which WRITES (and `mkdir`s)
    # `args.work_catalog` -- necessary, not merely preferable
    # (`run_weather_strategy_backtests.py:1270`). The candidate set is
    # built by ITERATING `PRECISION_ARMS`, never a hand-typed mode list, so
    # a future third arm cannot silently escape layer 1's exact-match
    # oracle (N-3).
    guard_candidates = [
        args.work_catalog,
        *(args.work_catalog / f"latch_{mode}.db" for mode in PRECISION_ARMS),
    ]
    assert len(guard_candidates) == len(PRECISION_ARMS) + 1
    guard_report = assert_replay_latch_store_is_not_live(guard_candidates)
    print(guard_report.render())

    catalog = _convert_live_capture(
        quote_catalog=args.quote_catalog,
        instance_id=args.tape_instance_id,
        subdirectory=args.tape_subdirectory,
        work_catalog=args.work_catalog,
    )
    tape_instruments = _select_capture_instruments(catalog, climate_day=climate_day)
    listed_days = sorted({ti.facts.climate_day for ti in tape_instruments})
    assert_requested_days_are_listed([climate_day], listed_days)

    std_utc_offset_hours = default_registry().climate_day_window(
        WEATHER_VENUE, args.station,
    ).std_utc_offset_hours
    # (3) Printed BEFORE the coverage precondition below, unconditionally --
    # an uncovered tape's own counts/span must be visible even (especially)
    # when this run goes on to refuse it.
    print_tape_instrument_header(tape_instruments, std_utc_offset_hours)
    # (b) L-23 shape: a tape with zero in-window market data is refused
    # loudly here, never run to a silent `scored=0 refused=0`. Increment D:
    # the continuous arm hunts on Depth10 asks too, so its coverage basis
    # is the SAME executable-ask predicate, never the v2 QuoteTick-only one.
    coverage_source: Literal["quote", "depth"] = (
        "depth" if strategy_cls is ContinuousRungHoldBacktestStrategy else "quote"
    )
    assert_decision_window_has_coverage(
        tape_instruments,
        station=args.station,
        std_utc_offset_hours=std_utc_offset_hours,
        source=coverage_source,
    )

    observation_rows = read_asos_rows(args.asos_cache_csv)
    settlement = climate_day_records_to_settlement(tape_instruments, args.weather_catalog_root)
    print(close_source_label(tape_instruments))

    all_trials: list[FilledTrial] = []
    now_ns = max(
        (record.ts_init for ti in tape_instruments for record in (*ti.quotes, *ti.depths)),
        default=0,
    )
    for precision_mode in PRECISION_ARMS:
        precision_mode = cast(PrecisionMode, precision_mode)
        print(
            build_provenance_header(
                lag_minutes=args.lag_minutes,
                precision_mode=precision_mode,
                n_requested=1,
                n_data=len(tape_instruments),
                n_live=len(tape_instruments),
            ),
        )
        result = run_one_precision_arm(
            tape_instruments=tape_instruments,
            observation_rows=observation_rows,
            station=args.station,
            lag_minutes=args.lag_minutes,
            precision_mode=precision_mode,
            latch_store_path=args.work_catalog / f"latch_{precision_mode}.db",
            settlement_by_key=settlement,
            strategy_cls=strategy_cls,
            latch_key_prefix=latch_key_prefix,
            monitor_out_dir=args.monitor_out_dir,
        )
        all_trials.extend(result.trials)
        # (a) reporting gap: the strategy's own refusal counts, sorted for a
        # deterministic line -- never conflated with `scoring_refused` above.
        print(f"strategy refusals: {dict(sorted(result.strategy_refusals.items()))}")
        # WAIT-state diagnostics (`strategy.py`'s `_DIAG_*`) -- a DIFFERENT
        # vocabulary from `strategy_refusals` above, never conflated.
        print(f"strategy diagnostics: {dict(sorted(result.strategy_diagnostics.items()))}")
        # New stdout line, printed ONLY for the continuous arm -- the v2
        # golden transcript stays byte-identical except the plan-mandated
        # `live_store_guard` line (increment E's `GuardReport.render()`,
        # which `main` prints unconditionally for every arm; increment C
        # spec only ever covered this "strategy position events" line).
        if strategy_cls is ContinuousRungHoldBacktestStrategy:
            print(
                "strategy position events: "
                f"{dict(sorted(result.strategy_position_events.items()))}",
            )
        _print_roi_and_wilson(result.trials, settlement, now_ns)

    scored, _refused = score_trials(
        _pairs_with_settlement(all_trials, settlement), now_ns=now_ns,
    )
    if scored:
        write_scored_trials(args.output_dir, scored, now_ns=now_ns)
    print(f"trial_id prefix used: {PAPER_TRIAL_ID_PREFIX}")
    print(f"trader_id: {DEFAULT_BACKTEST_TRADER_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
