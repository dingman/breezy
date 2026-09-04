"""6b paper-replay library -- observation loading, engine config guards, and
the fills -> `FilledTrial` adapter. See
``docs/plans/PAPER_REPLAY_6B_BRIEF_2026-09-04.md`` (draft + the "Converged
peer review" section, BINDING over the draft) for the full design.

Strategy-agnostic (layer correction, 2026-09-04): ``runtime`` may not import
``strategy``, so this module carries no reference to
``CurrentRungHoldStrategy``/``CurrentRungHoldBacktestStrategy`` at all -- the
driver (``scripts/analysis/current_rung_hold_paper_replay.py``) constructs
the strategy object and hands it to ``breezy.runtime.backtest_harness.backtest``
directly.

No price fabrication, ever
---------------------------
Every observation this module returns comes from
:func:`breezy.ingest.iem_observations.iem_asos_rows_to_station_observations`,
a verbatim archive-row parse -- this module adds NO price, and
:func:`load_replay_observations` never touches an ask/bid/settlement field.
Every market-data record a caller feeds :func:`build_paper_replay_config`
must fall inside the converted capture's own timestamp window
(``capture_window_ns``) -- an injected synthetic quote whose ``ts_init``
falls outside that window is refused, not silently accepted
(RED test 1).

The lag-anchor correction (review item 4)
-------------------------------------------
This is the PREREG §3 / A1 LIVE rule -- receipt of the R-setting
observation -- NOT the archive study's ``find_lagged_entry`` rule (which lags
the ENTRY price relative to an unlagged ``R(t)``, ``mb_current_rung_edge_
study.py:479-490``). Here, ``received_at_ns = observed_at_ns + lag_minutes``
is stamped on the OBSERVATION itself, and a quote is only ever considered
priced once its own ``ts_event >= received_at_ns`` for the observation that
set the running max at that instant -- the two anchors diverge whenever the
running max was set by a STALE row (held from an earlier observation), never
whenever it was set by the freshest one. See
``test_current_rung_hold_paper_replay.py::test_replay_receipt_time_is_synthesized_and_required``
and its stale-anchor-divergence sibling.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Literal

from nautilus_trader.model.data import OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import OrderStatus

from breezy.domain.station_observation import StationObservation
from breezy.ingest.iem_observations import iem_asos_rows_to_station_observations
from breezy.runtime.backtest_harness import BreezyBacktestConfig
from breezy.settlement.trial_scorer import FilledTrial

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.instruments import Instrument
    from nautilus_trader.model.objects import Money

    from breezy.domain.weather_bucket_facts import WeatherBucketFacts

__all__ = [
    "PAPER_TRIAL_ID_PREFIX",
    "PRECISION_ARMS",
    "ForeignReplayDataError",
    "PaperReplayInputs",
    "PrecisionMode",
    "QuoteOnlyReplayError",
    "ReplayEntryContext",
    "build_paper_replay_config",
    "filled_trials_from_engine",
    "load_replay_observations",
]

#: Every paper-replay trial id starts with this. Two independent barriers
#: keep it out of the live tally (module docstring's "L-22 unforgeable
#: provenance"): (i) `assert_live_only` refuses any non-`current_rung_hold/
#: trial/` prefix, unmodified; (ii) `assert_paper_only` (`live_family_tally.py`)
#: refuses anything ELSE. This prefix is never a caller-supplied argument --
#: see `filled_trials_from_engine`, which derives it internally.
PAPER_TRIAL_ID_PREFIX: Final[str] = "paper_replay/current_rung_hold/trial"

#: Both precision arms this harness prints, unconditionally, every run
#: (converged peer review item 5). `nws_integer_c` is the default -- see
#: `PaperReplayInputs.precision_mode`.
PRECISION_ARMS: Final[tuple[str, ...]] = ("nws_integer_c", "archive_metar")

_NS_PER_MINUTE: Final[int] = 60_000_000_000
#: Archive METAR native precision (`iem_observations.py` always stamps 5).
_ARCHIVE_METAR_PRECISION_C_TENTHS: Final[int] = 5
#: Live NWS 5-minute feed's integer-Celsius precision -- pessimistic, closer
#: to live, and the default (draft, "Precision" section).
_NWS_INTEGER_C_PRECISION_C_TENTHS: Final[int] = 10

PrecisionMode = Literal["nws_integer_c", "archive_metar"]


class ForeignReplayDataError(ValueError):
    """A market-data record's `ts_init` falls outside the converted capture
    window -- refuses an injected synthetic quote from ever reaching the
    replay (RED test 1)."""


class QuoteOnlyReplayError(ValueError):
    """An instrument carries `QuoteTick`s but no `OrderBookDepth10`.

    `SimulatedExchange.process_quote_tick` does not mutate the book when
    `book_type != L1_MBP` (`engine.pyx:4509,4551`); feeding quotes with no
    depth would decide identically to a real run and fill NEVER, silently.
    Refused explicitly instead (RED test 2).
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class PaperReplayInputs:
    """Everything one paper-replay run needs beyond the converted catalog.

    `lag_minutes` is required, no default (draft, "Receipt time is
    synthesized"): omitting it at the CLI layer is what
    `test_replay_receipt_time_is_synthesized_and_required` pins.
    """

    lag_minutes: int
    precision_mode: PrecisionMode = "nws_integer_c"
    source_channel: str = "iem_asos_metar_paper_replay"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayEntryContext:
    """Per-instrument context `filled_trials_from_engine` needs to build a
    `FilledTrial` for a fill on that instrument -- never a `trial_id`
    (derived internally, see `PAPER_TRIAL_ID_PREFIX`)."""

    station: str
    climate_day: str
    bucket: WeatherBucketFacts | None
    entry_ask: Decimal
    scheduled_release_at_ns: int


def _precision_c_tenths(mode: PrecisionMode) -> int:
    return (
        _ARCHIVE_METAR_PRECISION_C_TENTHS
        if mode == "archive_metar"
        else _NWS_INTEGER_C_PRECISION_C_TENTHS
    )


def load_replay_observations(
    *,
    station: str,
    rows: Iterable[Mapping[str, str]],
    inputs: PaperReplayInputs,
) -> tuple[StationObservation, ...]:
    """Parse archive ASOS `rows` into `StationObservation`s with a SYNTHESIZED
    per-row receipt: `received_at_ns = observed_at_ns + lag_minutes`.

    Two passes over `iem_asos_rows_to_station_observations`, never a
    duplicated parse: the first call uses a placeholder `received_at_ns`
    large enough to satisfy `StationObservation`'s "received strictly after
    observed" construction check for ANY archive row, purely to obtain the
    parsed `observed_at_ns`; the second, real `StationObservation` is then
    built from that same parsed record with the correct receipt stamped and
    this run's `precision_mode` applied. No price, no `T`-group value, and no
    other field is ever touched here -- see the module docstring.
    """
    lag_ns = inputs.lag_minutes * _NS_PER_MINUTE
    precision_c_tenths = _precision_c_tenths(inputs.precision_mode)
    # A placeholder receipt guaranteed later than any real archive
    # observation, used ONLY to get past the parser's own construction
    # check -- overwritten below, never read downstream.
    _PLACEHOLDER_RECEIVED_AT_NS: Final[int] = 2**62
    parsed, _drops = iem_asos_rows_to_station_observations(
        station=station,
        rows=rows,
        source_channel=inputs.source_channel,
        assumed_publication_lag_ns=max(lag_ns, 1),
        received_at_ns=_PLACEHOLDER_RECEIVED_AT_NS,
    )
    observations = tuple(
        StationObservation(
            station=record.station,
            observed_at_ns=record.observed_at_ns,
            received_at_ns=record.observed_at_ns + lag_ns,
            temp_c_tenths=record.temp_c_tenths,
            precision_c_tenths=precision_c_tenths,
            is_metar=record.is_metar,
            source_channel=record.source_channel,
            assumed_publication_lag_ns=max(lag_ns, 1),
        )
        for record in parsed
    )
    return observations


def _assert_no_foreign_market_data(
    market_data: Sequence[Data], capture_window_ns: tuple[int, int],
) -> None:
    lo, hi = capture_window_ns
    foreign = [record for record in market_data if not (lo <= record.ts_init <= hi)]
    if foreign:
        raise ForeignReplayDataError(
            f"{len(foreign)} market-data record(s) carry a ts_init outside the "
            f"converted capture window [{lo}, {hi}] -- every record fed to a "
            "paper replay must come from the converted work catalog, never an "
            "injected synthetic quote.",
        )


def _assert_every_quote_instrument_has_depth(market_data: Sequence[Data]) -> None:
    quote_ids = {r.instrument_id for r in market_data if type(r) is QuoteTick}
    depth_ids = {r.instrument_id for r in market_data if type(r) is OrderBookDepth10}
    missing = sorted(str(iid) for iid in quote_ids - depth_ids)
    if missing:
        raise QuoteOnlyReplayError(
            f"{len(missing)} instrument(s) carry QuoteTick data with no "
            f"OrderBookDepth10: {missing!r}. Under L2_MBP, "
            "`SimulatedExchange.process_quote_tick` does not mutate the book "
            "(engine.pyx:4509,4551) -- a quote-only replay would decide "
            "identically to a real run and fill NEVER, silently.",
        )


def build_paper_replay_config(
    *,
    instruments: Sequence[Instrument],
    market_data: Sequence[Data],
    weather_data: Sequence[Data] = (),
    settlement_prices: Mapping[InstrumentId, float] = {},
    starting_balances: Sequence[Money],
    capture_window_ns: tuple[int, int],
    instruments_without_close: frozenset[InstrumentId] = frozenset(),
) -> BreezyBacktestConfig:
    """Build the `BreezyBacktestConfig` for one paper-replay run.

    Runs the two paper-replay-specific guards (RED tests 1, 2) BEFORE
    constructing the config; `breezy.runtime.backtest_harness.
    build_backtest_engine` still runs its own §5 settlement guards when the
    engine is built -- these are additive, not a replacement.
    """
    _assert_no_foreign_market_data(market_data, capture_window_ns)
    _assert_every_quote_instrument_has_depth(market_data)
    return BreezyBacktestConfig(
        instruments=tuple(instruments),
        market_data=tuple(market_data),
        settlement_prices=dict(settlement_prices),
        starting_balances=tuple(starting_balances),
        weather_data=tuple(weather_data),
        instruments_without_close=instruments_without_close,
    )


def filled_trials_from_engine(
    engine: BacktestEngine,
    entry_contexts: Mapping[str, ReplayEntryContext],
) -> tuple[FilledTrial, ...]:
    """Every FILLED order in `engine.cache`, turned into a `FilledTrial`.

    `trial_id` is derived internally (`paper_replay/current_rung_hold/
    trial/{station}/{climate_day}`) -- never a caller-supplied argument
    (L-22, converged peer review item 6). An order on an instrument with no
    entry context (i.e. not part of this replay's candidate set) is
    skipped, never fabricated a trial. `CurrentRungHoldConfig.order_quantity`
    is pinned to 1, so the venue's per-order commission IS the per-contract
    fee -- no division.
    """
    trials: list[FilledTrial] = []
    for order in engine.cache.orders():
        if order.status != OrderStatus.FILLED:
            continue
        instrument_id = str(order.instrument_id)
        ctx = entry_contexts.get(instrument_id)
        if ctx is None:
            continue
        fee = Decimal(0)
        for money in order.commissions():
            fee += Decimal(str(money.as_double()))
        trial_id = f"{PAPER_TRIAL_ID_PREFIX}/{ctx.station}/{ctx.climate_day}"
        trials.append(
            FilledTrial(
                trial_id=trial_id,
                station=ctx.station,
                climate_day=ctx.climate_day,
                instrument_id=instrument_id,
                bucket=ctx.bucket,
                fill_px=Decimal(str(order.avg_px)) if order.avg_px is not None else Decimal(0),
                fee=fee,
                qty=Decimal(str(order.filled_qty)),
                filled_at_ns=int(order.ts_last),
                entry_ask=ctx.entry_ask,
                scheduled_release_at_ns=ctx.scheduled_release_at_ns,
            ),
        )
    return tuple(trials)
