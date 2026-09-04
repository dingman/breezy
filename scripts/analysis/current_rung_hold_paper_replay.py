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
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.objects import Money

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.identifiers import InstrumentId

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
from breezy.runtime.paper_replay import (
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
from breezy.strategy.current_rung_hold.trial_day_latch import (
    TrialDayLatch,
    open_trial_day_latch,
)

__all__ = [
    "PROVENANCE_HEADER_TEMPLATE",
    "SEVEN_DAYS_NS",
    "STARTING_BALANCE_USD",
    "UnlistedStationDayError",
    "VenueOutsideLiveDirError",
    "build_provenance_header",
    "climate_day_records_to_settlement",
    "close_source_label",
    "run_one_precision_arm",
]

STARTING_BALANCE_USD: Final[int] = 10_000
SEVEN_DAYS_NS: Final[int] = 7 * 24 * 60 * 60 * 1_000_000_000

#: Default paper-replay store -- deliberately NOT the live scored_trials
#: dir (L-22: two independent barriers, see `paper_replay.py`'s docstring).
DEFAULT_PAPER_STORE: Final[Path] = Path(
    "~/.local/share/breezy/derived/paper_replay/scored_trials",
).expanduser()
_LIVE_STORE_MARKER: Final[str] = "derived/live/scored_trials"

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


def assert_paper_write_path_is_not_live(output_dir: Path) -> None:
    if _LIVE_STORE_MARKER in str(output_dir.resolve()):
        raise VenueOutsideLiveDirError(
            f"--output-dir {output_dir} resolves under the live scored_trials "
            "directory; the paper writer refuses to write there (L-22).",
        )


def read_asos_rows(csv_path: Path) -> list[dict[str, str]]:
    """`station,valid,metar` rows verbatim -- no price ever derived here."""
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@contextmanager
def _latch_context(store_path: Path) -> Iterator[TrialDayLatch]:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(intent_latch)


def _latch_factory(store_path: Path) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    return lambda: _latch_context(store_path)


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


def run_one_precision_arm(
    *,
    tape_instruments: Sequence[TapeInstrument],
    observation_rows: Sequence[dict[str, str]],
    station: str,
    lag_minutes: int,
    precision_mode: PrecisionMode,
    latch_store_path: Path,
    settlement_by_key: SettlementByKey,
) -> tuple[FilledTrial, ...]:
    """Run one (lag, precision) arm of the replay and return its `FilledTrial`s.

    `tape_instruments` supplies BOTH `QuoteTick` and `OrderBookDepth10` --
    `build_paper_replay_config` refuses a quote-only instrument (RED test 2).
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
        market_data.extend(ti.quotes)
        market_data.extend(ti.depths)
    if not market_data:
        return ()
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

    strategy = CurrentRungHoldBacktestStrategy(
        cfg, trial_day_latch_factory=_latch_factory(latch_store_path),
    )

    with backtest(config, strategies=(strategy,), allow_idle_strategies=True) as engine:
        entry_contexts: dict[str, ReplayEntryContext] = {}
        for ti in tape_instruments:
            entry_contexts[str(ti.instrument.id)] = _entry_context_for(
                ti,
                scheduled_release_at_ns=max(ts_values) + SEVEN_DAYS_NS,
                entry_ask=Decimal(str(ti.quotes[0].ask_price)) if ti.quotes else Decimal(0),
            )
        return filled_trials_from_engine(engine, entry_contexts)


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
    print(f"scored={len(scored)} refused={len(refused)}")
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
    args = parser.parse_args(argv)

    assert_paper_write_path_is_not_live(args.output_dir)
    climate_day = dt.date.fromisoformat(args.climate_day)

    catalog = _convert_live_capture(
        quote_catalog=args.quote_catalog,
        instance_id=args.tape_instance_id,
        subdirectory=args.tape_subdirectory,
        work_catalog=args.work_catalog,
    )
    tape_instruments = _select_capture_instruments(catalog, climate_day=climate_day)
    listed_days = sorted({ti.facts.climate_day for ti in tape_instruments})
    assert_requested_days_are_listed([climate_day], listed_days)

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
        trials = run_one_precision_arm(
            tape_instruments=tape_instruments,
            observation_rows=observation_rows,
            station=args.station,
            lag_minutes=args.lag_minutes,
            precision_mode=precision_mode,
            latch_store_path=args.work_catalog / f"latch_{precision_mode}.db",
            settlement_by_key=settlement,
        )
        all_trials.extend(trials)
        _print_roi_and_wilson(trials, settlement, now_ns)

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
