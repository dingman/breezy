"""K1 -- do cheap rungs offered in the D+1 book settle YES often enough to pay?

WHAT THIS MEASURES, AND WHAT IT DELIBERATELY DOES NOT
-----------------------------------------------------
The programme has already refuted three "lock" strategy families (L-9): the
near-certain rung has no offer side on this venue, so a long-only taker cannot
harvest certainty. A **calibration** family was proposed on the opposite
theory -- that the CHEAP rungs (asks at 0.01-0.03, where the offer side IS
deep) are underpriced.

K1 is the cheapest measurement that can settle it. For every
``(station, climate_day, rung)`` whose book was observed BEFORE its climate
day began, it records the FIRST genuine ask, then asks whether that rung
settled YES against the NWS CLI integer ``tmax_f``. Per cheap-ask stratum it
reports ``n``, ``k``, ``pi = k/n`` and the **Wilson 95% interval**, against
the fee-inclusive break-even at the stratum's price.

This is a DESCRIPTIVE settlement-frequency measurement plus a closed-form
threshold comparison. It is emphatically NOT a backtest: no order, fill,
position, slippage or P&L is simulated anywhere in this file. Nautilus Trader
is the exclusive owner of backtesting, and K1 does not compete with it.

WHY "BEFORE THE CLIMATE DAY BEGAN"
-----------------------------------
Most cheap rungs observed LATE in a climate day are rungs the day has already
MISSED -- their ask is 0.01 because they have essentially lost, and buying
them is buying a lottery whose draw has happened. That is a different and
already-understood population. K1 restricts to the **D+1 book**: the market
for tomorrow, traded today, where the outcome is genuinely still open. The
boundary is local-STANDARD midnight (never DST-aware), taken from the site
registry -- the same rule ``breezy.ingest.records._climate_day_end_ns`` uses.

WHY BOTH ``quote_tick`` AND ``order_book_depths`` ARE READ
-----------------------------------------------------------
A ``QuoteTick`` is two-sided, and
``breezy.adapters.polymarket_us.parsing.parse_book_top`` REFUSES to invent a
bid, so an instrument whose bid side is empty emits **no quote at all** --
only depth. On this venue the empty side is the BID side (the median
top-of-book bid is 0.3 contracts), which is precisely the state a deep 0.01
offer sits in. Reading ``quote_tick`` alone would therefore drop the exact
population K1 exists to measure: the tape carries 37 instruments in
``quote_tick`` against 65 in ``order_book_depths``. Both streams are read and
merged, de-duplicated on ``(instrument_id, ts_event, ts_init)``.

WHY THE TAPE IS PREFLIGHTED FILE BY FILE (L-8)
-----------------------------------------------
``ParquetDataCatalog._read_feather_file`` catches ``(pa.ArrowInvalid,
OSError)`` and returns ``None``, which ``convert_stream_to_data`` turns into a
silent ``continue``. A truncated feather -- the normal residue of an unclean
recorder shutdown -- is therefore INDISTINGUISHABLE from an empty market
through the catalog API. K1 opens every file itself and reports the parse
failures as a number, because a conclusion drawn from a silently truncated
read is worse than no conclusion.

SETTLEMENT TRUTH
----------------
The NWS CLI **integer** ``tmax_f``, read through
``breezy.persistence.catalog.read_climate_day_including_corrections`` (the
AUDIT accessor -- K1 reconstructs truth, it does not settle anything). An
observation-derived ASOS/METAR maximum is NEVER substituted: the measured
basis is NYC mean +0.655 / median +1, with 56.0% of days differing by >= 1 F,
so that substitution would silently corrupt the result.

Re-runnable by design: run it again as capture accumulates.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.model.data import OrderBookDepth10, QuoteTick
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

sys.path.insert(0, str(Path(__file__).resolve().parent))

# THE settlement predicate, with its evidence citation, is owned by
# `settlement_truth_dataset` and delegates to `WeatherBucketFacts.contains`.
# K1 re-authors no rung-boundary logic.
# The venue fee formula and the repo's Wilson lower bound, CALLED rather than
# re-derived, so K1 cannot end up carrying a second definition of either.
from price_conditional_settlement_analysis import venue_fee_per_contract
from settlement_alignment_study import wilson_lower_bound
from settlement_truth_dataset import (
    SETTLEMENT_PREDICATE_EVIDENCE,
    SETTLEMENT_PREDICATE_STATEMENT,
)
from settlement_truth_dataset import settles_yes as _settles_yes

from breezy.adapters.polymarket_us.parsing import FEE_COEFFICIENT_KEY
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
)
from breezy.normalize.climate_day import standard_time_zone
from breezy.persistence.catalog import (
    read_climate_day_including_corrections,
    station_catalog_path,
)
from breezy.registry.sites import default_registry

__all__ = [
    "ASK_STRATA",
    "MID_WRITE_WINDOW_NS",
    "Z_95",
    "AskObservation",
    "PopulationMember",
    "Stratum",
    "TapePreflight",
    "break_even_probability",
    "classify_parse_failure",
    "clears_break_even",
    "climate_day_start_ns",
    "first_genuine_ask",
    "is_genuine_ask",
    "is_pre_climate_day",
    "main",
    "min_n_to_refute",
    "required_n_to_discriminate",
    "resolution_floor",
    "settles_yes",
    "summarize_stratum",
    "wilson_interval",
    "wilson_lower_at_rate",
]

VENUE: Final[str] = "polymarket_us"

DEFAULT_QUOTE_TAPE_PATH: Final[Path] = (
    Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us"
)
DEFAULT_SETTLEMENT_CATALOG_BASE: Final[Path] = Path.home() / ".local/share/breezy/catalog"
DEFAULT_OUTPUT_PATH: Final[Path] = Path("docs/evidence/k1_cheap_open_2026-09-01.md")

#: The cheap-ask thresholds reported SEPARATELY. Deliberately plural: the
#: threshold choice is a judgement the reader must see, never one baked into
#: the measurement.
ASK_STRATA: Final[tuple[Decimal, ...]] = (
    Decimal("0.01"),
    Decimal("0.02"),
    Decimal("0.03"),
    Decimal("0.05"),
)

#: Two-sided 95% normal quantile, matching every other study in this repo
#: (`scripts/analysis/price_conditional_settlement_analysis.py:46`).
Z_95: Final[float] = 1.959963984540054

#: The discrimination K1 must be able to make for a verdict to mean anything:
#: is the true settle rate 3% (a real edge at a 1c ask) or 1% (no edge)?
POWER_P_ALT: Final[float] = 0.03
POWER_P_NULL: Final[float] = 0.01

#: How recently a file must have been written for a parse failure to be read
#: as "the recorder is still appending" rather than "this file is corrupt".
#: Capture is ONGOING while K1 runs, so the newest feather in the active run is
#: routinely mid-message. Calling that corruption would manufacture a data
#: -integrity incident out of a healthy recorder -- the mirror image of the L-8
#: failure this preflight exists to prevent.
MID_WRITE_WINDOW_NS: Final[int] = 300 * 1_000_000_000

_EPOCH: Final[dt.datetime] = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
_NS_PER_SECOND: Final[int] = 1_000_000_000
_NS_PER_MICROSECOND: Final[int] = 1_000


# ---------------------------------------------------------------------------
# Climate-day boundary -- local STANDARD midnight, never DST-aware
# ---------------------------------------------------------------------------


def climate_day_start_ns(climate_day: dt.date, std_utc_offset_hours: float) -> int:
    """UNIX nanoseconds at the START of `climate_day` in local standard time.

    The mirror of ``breezy.ingest.records._climate_day_end_ns``: the climate
    day runs local-standard midnight to midnight year-round, so its start is
    midnight at the beginning of the date under the site's FIXED offset --
    never ``ZoneInfo``, which follows DST and would alias the window across the
    spring and autumn transitions.
    """
    day_start = dt.datetime.combine(
        climate_day,
        dt.time(0, 0),
        tzinfo=standard_time_zone(std_utc_offset_hours),
    )
    delta = day_start - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * _NS_PER_SECOND + (
        delta.microseconds * _NS_PER_MICROSECOND
    )


def is_pre_climate_day(ts_ns: int, *, climate_day: dt.date, std_utc_offset_hours: float) -> bool:
    """Was `ts_ns` observed STRICTLY before `climate_day` began locally?

    Strict on purpose: the boundary instant is the day's first nanosecond, so
    a quote stamped exactly there is intraday, not D+1.
    """
    return ts_ns < climate_day_start_ns(climate_day, std_utc_offset_hours)


# ---------------------------------------------------------------------------
# Settlement predicate -- delegated, never re-authored
# ---------------------------------------------------------------------------


def settles_yes(tmax_f: int, *, lower_f: int | None, upper_f: int | None) -> bool:
    """Did the CLI integer `tmax_f` settle this rung YES?

    Thin pass-through to ``settlement_truth_dataset.settles_yes``, which is
    itself a pass-through to ``WeatherBucketFacts.contains``. Evidence for the
    predicate: ``SETTLEMENT_PREDICATE_EVIDENCE``.
    """
    return bool(_settles_yes(tmax_f, lower_f=lower_f, upper_f=upper_f))


# ---------------------------------------------------------------------------
# Ask observations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AskObservation:
    """One instant at which a rung's offer side carried a price."""

    instrument_id: str
    ts_event_ns: int
    ts_init_ns: int
    ask_price: Decimal
    ask_size: Decimal
    source: str


def is_genuine_ask(observation: AskObservation) -> bool:
    """Is this an offer a taker could actually have lifted?

    ``OrderBookDepth10`` pads unfilled levels with price 0.00 / size 0.00, so a
    zero on either field is padding rather than a price. An ask of 1.00 is the
    top of the binary range: nothing above it can be won, so it is not a
    tradeable cheap-rung offer either.
    """
    return observation.ask_size > 0 and observation.ask_price > 0 and observation.ask_price < 1


def first_genuine_ask(observations: Iterable[AskObservation]) -> AskObservation | None:
    """The EARLIEST genuine ask, by observation timestamp ascending.

    Not the best over the window and not an average: a strategy has to trade
    what was actually offered at the moment it looked. Ties on ``ts_event`` are
    broken on ``ts_init`` (the adapter's receipt clock), so the result is
    deterministic across re-runs and across the two tape subtrees.
    """
    genuine = [obs for obs in observations if is_genuine_ask(obs)]
    if not genuine:
        return None
    return min(genuine, key=lambda obs: (obs.ts_event_ns, obs.ts_init_ns))


# ---------------------------------------------------------------------------
# Wilson 95% interval
# ---------------------------------------------------------------------------


def wilson_lower_at_rate(rate: float, sample_count: int) -> float:
    """Wilson lower bound for an EXACT rate, allowing a fractional count.

    Used only for the power arithmetic. Rounding ``p * n`` to a whole count at
    small ``n`` inflates the rate it actually encodes (``round(0.51) == 1`` is
    5.9%, not 3%) and would report an absurdly small required sample.
    """
    if sample_count <= 0:
        return 0.0
    z = Z_95
    denom = 1.0 + z * z / sample_count
    centre = rate + z * z / (2.0 * sample_count)
    radius = z * math.sqrt((rate * (1.0 - rate) + z * z / (4.0 * sample_count)) / sample_count)
    return (centre - radius) / denom


def wilson_interval(
    hit_count: int, sample_count: int, z: float = Z_95
) -> tuple[float, float] | None:
    """Two-sided Wilson score interval, or `None` for an empty sample.

    ``None`` rather than ``(0.0, 0.0)``: an interval on nothing is UNDEFINED,
    and a zero-width interval at zero would read as the most certain cell in
    the table. The lower bound is identical to the repo's existing
    ``settlement_alignment_study.wilson_lower_bound``; the upper is its mirror
    on the complementary count, the same identity
    ``price_conditional_settlement_analysis`` already uses.
    """
    if sample_count <= 0:
        return None
    return (
        wilson_lower_bound(hit_count, sample_count, z=z),
        1.0 - wilson_lower_bound(sample_count - hit_count, sample_count, z=z),
    )


def resolution_floor(sample_count: int) -> float | None:
    """The smallest Wilson 95% UPPER bound a sample of this size can report.

    Attained at ZERO observed events. Any break-even below this figure is
    unreachable with the corpus on hand -- a statement about statistical POWER,
    never about the venue.
    """
    interval = wilson_interval(0, sample_count)
    return None if interval is None else interval[1]


def required_n_to_discriminate(*, p_alt: float = POWER_P_ALT, p_null: float = POWER_P_NULL) -> int:
    """Smallest `n` whose Wilson 95% lower bound at `p_alt` clears `p_null`.

    Answers the operator's question directly: how many qualifying station-days
    of D+1 capture are needed before an observed 3% settle rate is
    distinguishable from 1%?
    """
    if not 0.0 < p_null < p_alt < 1.0:
        raise ValueError(
            f"p_alt must lie strictly above p_null and inside (0, 1); "
            f"got p_alt={p_alt}, p_null={p_null}"
        )
    sample = 1
    while sample <= 10_000_000:
        if wilson_lower_at_rate(p_alt, sample) > p_null:
            return sample
        sample += 1
    raise ValueError(f"no sample below 10,000,000 separates {p_alt} from {p_null}")


# ---------------------------------------------------------------------------
# Break-even at the venue's own fee
# ---------------------------------------------------------------------------


def break_even_probability(*, ask: Decimal, theta: Decimal) -> Decimal:
    """The settle rate at which buying at `ask` exactly breaks even.

    ``ask + theta * ask * (1 - ask)``. ``theta`` is REQUIRED and has no
    default: the venue publishes one coefficient per market and Breezy reads it
    from ``instrument.info[FEE_COEFFICIENT_KEY]``. Defaulting it here would be
    the same silent-wrong-number failure ``PolymarketUSFeeModel`` refuses.
    """
    return ask + venue_fee_per_contract(theta=theta, executable_price=ask)


def min_n_to_refute(*, threshold: Decimal, theta: Decimal) -> int:
    """Smallest `n` at which a ZERO-YES sample refutes the stratum.

    This -- not :func:`required_n_to_discriminate` -- is the binding
    constraint on a FAMILY DEAD verdict, and it is much larger. The Wilson
    UPPER bound at zero events is ``z**2 / (n + z**2)``, so pushing it down to
    a 1c break-even (~0.0106) takes hundreds of observations however lopsided
    the outcomes are. Reporting only the discrimination sample would let a
    reader believe the family could be killed far sooner than it can.
    """
    break_even = float(break_even_probability(ask=threshold, theta=theta))
    if break_even <= 0:
        raise ValueError("a zero break-even can never be refuted")
    sample = 1
    while sample <= 10_000_000:
        floor = resolution_floor(sample)
        if floor is not None and floor <= break_even:
            return sample
        sample += 1
    raise ValueError(f"no sample below 10,000,000 refutes a break-even of {break_even}")


def clears_break_even(wilson_upper: float, break_even: Decimal) -> bool:
    """Does the settle rate clear the fee-inclusive cost of buying the rung?

    Strict: a rate that exactly equals break-even earns nothing.
    """
    return wilson_upper > float(break_even)


# ---------------------------------------------------------------------------
# Stratum summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Stratum:
    """One cheap-ask threshold's settlement frequency, with its verdict."""

    threshold: Decimal
    n: int
    k: int
    pi: float | None
    wilson_lower: float | None
    wilson_upper: float | None
    break_even: Decimal
    clears: bool | None
    resolution_floor: float | None
    required_n: int
    verdict: str


def summarize_stratum(*, threshold: Decimal, outcomes: Sequence[bool], theta: Decimal) -> Stratum:
    """Summarize one stratum's YES/NO outcomes against its break-even.

    Break-even is evaluated at the stratum THRESHOLD -- the most expensive ask
    admitted to the stratum -- so the comparison is the conservative one for
    every member of it.

    Adequate ``n`` gates BOTH directional verdicts, not just the negative one.
    With a handful of observations the Wilson lower bound after a single lucky
    YES already sits above a 1c break-even; calling that FAMILY_SURVIVES would
    repeat exactly the small-sample mistake this programme has made before.
    """
    n = len(outcomes)
    k = sum(1 for outcome in outcomes if outcome)
    break_even = break_even_probability(ask=threshold, theta=theta)
    interval = wilson_interval(k, n)
    required = required_n_to_discriminate()

    if interval is None:
        return Stratum(
            threshold=threshold,
            n=n,
            k=k,
            pi=None,
            wilson_lower=None,
            wilson_upper=None,
            break_even=break_even,
            clears=None,
            resolution_floor=resolution_floor(n),
            required_n=required,
            verdict="UNDERPOWERED",
        )

    lower, upper = interval
    if n < required:
        verdict = "UNDERPOWERED"
    elif lower > float(break_even):
        verdict = "FAMILY_SURVIVES"
    elif upper <= float(break_even):
        verdict = "FAMILY_DEAD"
    else:
        verdict = "UNDERPOWERED"

    return Stratum(
        threshold=threshold,
        n=n,
        k=k,
        pi=k / n,
        wilson_lower=lower,
        wilson_upper=upper,
        break_even=break_even,
        clears=clears_break_even(upper, break_even),
        resolution_floor=resolution_floor(n),
        required_n=required,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# Tape preflight (L-8) -- every file opened, every failure counted
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TapePreflight:
    """What was ACTUALLY read off disk, per data class, with failures named."""

    data_class: str
    files_found: int
    files_parsed: int
    files_failed: int
    failures: tuple[tuple[str, str, str], ...]
    raw_rows: int
    deduplicated_rows: int
    instruments: int
    rows_per_instrument: dict[str, int]
    ts_event_min_ns: int | None
    ts_event_max_ns: int | None


def classify_parse_failure(*, file_mtime_ns: int, now_ns: int) -> str:
    """Is an unreadable file corrupt, or simply still being written?

    Both are reported -- neither is swallowed -- but they mean opposite things.
    A CORRUPT file is lost tape and a finding; a MID_WRITE_SUSPECTED file is
    the live recorder doing its job and will read cleanly on the next run.
    """
    return "MID_WRITE_SUSPECTED" if now_ns - file_mtime_ns < MID_WRITE_WINDOW_NS else "CORRUPT"


def _read_arrow_table(path: Path) -> pa.Table:
    """Open one tape file, whichever subtree it came from.

    ``data/`` holds catalog Parquet; ``live/<run-id>/`` holds the streaming
    Feather the recorder writes. Both are read here DIRECTLY rather than
    through ``ParquetDataCatalog``, so a truncated file raises instead of
    silently contributing zero rows.
    """
    if path.suffix == ".parquet":
        return pq.read_table(path)
    with pa.ipc.open_stream(pa.memory_map(str(path))) as reader:
        return reader.read_all()


def _tape_files(tape_root: Path, folder: str) -> list[Path]:
    """Every file for one data class across BOTH tape subtrees.

    A previous audit read only one subtree and understated the tape by an
    order of magnitude.
    """
    return sorted(
        list((tape_root / "data" / folder).rglob("*.parquet"))
        + list(tape_root.glob(f"live/*/{folder}/*/*.feather"))
        + list(tape_root.glob(f"live/*/{folder}/*.feather"))
    )


def _load_stream(tape_root: Path, folder: str, data_cls: type) -> tuple[TapePreflight, list[Any]]:
    files = _tape_files(tape_root, folder)
    now_ns = int(dt.datetime.now(dt.UTC).timestamp() * _NS_PER_SECOND)
    parsed_objects: list[Any] = []
    failures: list[tuple[str, str, str]] = []
    files_parsed = 0
    raw_rows = 0
    seen: set[tuple[str, int, int]] = set()
    rows_per_instrument: dict[str, int] = defaultdict(int)
    ts_min: int | None = None
    ts_max: int | None = None

    for path in files:
        try:
            table = _read_arrow_table(path)
            objects = ArrowSerializer.deserialize(data_cls, table)
        except Exception as exc:  # noqa: BLE001 -- the count IS the finding
            mtime_ns = int(path.stat().st_mtime * _NS_PER_SECOND)
            failures.append(
                (
                    str(path),
                    f"{type(exc).__name__}: {exc}",
                    classify_parse_failure(file_mtime_ns=mtime_ns, now_ns=now_ns),
                )
            )
            continue
        files_parsed += 1
        raw_rows += len(objects)
        for obj in objects:
            # Data types expose `instrument_id`; an `Instrument` exposes `id`.
            identifier = getattr(obj, "instrument_id", None)
            instrument_id = str(obj.id if identifier is None else identifier)
            key = (instrument_id, int(obj.ts_event), int(obj.ts_init))
            if key in seen:
                continue
            seen.add(key)
            rows_per_instrument[instrument_id] += 1
            parsed_objects.append(obj)
            ts_event = int(obj.ts_event)
            ts_min = ts_event if ts_min is None else min(ts_min, ts_event)
            ts_max = ts_event if ts_max is None else max(ts_max, ts_event)

    preflight = TapePreflight(
        data_class=data_cls.__name__,
        files_found=len(files),
        files_parsed=files_parsed,
        files_failed=len(failures),
        failures=tuple(failures),
        raw_rows=raw_rows,
        deduplicated_rows=len(seen),
        instruments=len(rows_per_instrument),
        rows_per_instrument=dict(rows_per_instrument),
        ts_event_min_ns=ts_min,
        ts_event_max_ns=ts_max,
    )
    return preflight, parsed_objects


# ---------------------------------------------------------------------------
# Population assembly
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstrumentFacts:
    """The rung identity K1 joins on, taken from the venue's own instrument."""

    instrument_id: str
    station: str
    climate_day: dt.date
    lower_f: int | None
    upper_f: int | None
    theta: Decimal


@dataclass(frozen=True, slots=True)
class PopulationMember:
    """One `(station, climate_day, rung)` with a D+1 entry ask and an outcome."""

    facts: InstrumentFacts
    entry: AskObservation
    tmax_f: int
    settled_yes: bool


def _instrument_facts(instrument: BinaryOption) -> InstrumentFacts | None:
    info = instrument.info
    try:
        station = str(info[SETTLEMENT_STATION_KEY])
        climate_day = dt.date.fromisoformat(str(info[CLIMATE_DAY_KEY]))
        raw_lower = info[STRIKE_LOWER_F_KEY]
        raw_upper = info[STRIKE_UPPER_F_KEY]
        theta = Decimal(str(info[FEE_COEFFICIENT_KEY]))
    except (KeyError, ValueError):
        return None
    return InstrumentFacts(
        instrument_id=str(instrument.id),
        station=station,
        climate_day=climate_day,
        lower_f=None if raw_lower is None else int(raw_lower),
        upper_f=None if raw_upper is None else int(raw_upper),
        theta=theta,
    )


def _asks_from_depth(depths: Iterable[OrderBookDepth10]) -> list[AskObservation]:
    """Best genuine ask per depth snapshot.

    ``min`` over the populated levels rather than level 0: depth is stored
    best-first, but selecting by price cannot be broken by a venue that stops
    sorting a side.
    """
    observations: list[AskObservation] = []
    for depth in depths:
        levels = [(Decimal(str(level.price)), Decimal(str(level.size))) for level in depth.asks]
        populated = [(price, size) for price, size in levels if size > 0 and price > 0]
        if not populated:
            continue
        price, size = min(populated, key=lambda level: level[0])
        observations.append(
            AskObservation(
                instrument_id=str(depth.instrument_id),
                ts_event_ns=int(depth.ts_event),
                ts_init_ns=int(depth.ts_init),
                ask_price=price,
                ask_size=size,
                source="order_book_depths",
            )
        )
    return observations


def _asks_from_quotes(quotes: Iterable[QuoteTick]) -> list[AskObservation]:
    return [
        AskObservation(
            instrument_id=str(quote.instrument_id),
            ts_event_ns=int(quote.ts_event),
            ts_init_ns=int(quote.ts_init),
            ask_price=Decimal(str(quote.ask_price)),
            ask_size=Decimal(str(quote.ask_size)),
            source="quote_tick",
        )
        for quote in quotes
    ]


def _station_offsets() -> dict[str, tuple[str, float]]:
    """Map CLI location -> (registry city, fixed standard UTC offset).

    Joined on ``cli_location`` because that is what both the instrument's
    ``settlement_station`` and the ``NwsClimateDay.station`` field hold. The
    registry city key is NOT interchangeable with it.
    """
    registry = default_registry()
    mapping: dict[str, tuple[str, float]] = {}
    for venue, city in registry.pairs():
        if venue != VENUE:
            continue
        site = registry.settlement_site(venue, city)
        window = registry.climate_day_window(venue, city)
        mapping[site.cli_location] = (city, window.std_utc_offset_hours)
    return mapping


@dataclass(frozen=True, slots=True)
class ExclusionLedger:
    """Why members of the candidate set did not reach the measured population."""

    no_instrument_record: int
    unknown_station: int
    no_ask_at_all: int
    no_pre_climate_day_ask: int
    no_settlement_record: int
    settlement_not_final: int
    settlement_tmax_missing: int


def build_population(
    *,
    tape_root: Path,
    settlement_base: Path,
) -> tuple[list[TapePreflight], list[PopulationMember], ExclusionLedger, dict[str, Any]]:
    instrument_preflight, instrument_objects = _load_stream(
        tape_root, "binary_option", BinaryOption
    )
    depth_preflight, depth_objects = _load_stream(tape_root, "order_book_depths", OrderBookDepth10)
    quote_preflight, quote_objects = _load_stream(tape_root, "quote_tick", QuoteTick)

    facts_by_id: dict[str, InstrumentFacts] = {}
    for instrument in instrument_objects:
        facts = _instrument_facts(instrument)
        if facts is not None:
            facts_by_id[facts.instrument_id] = facts

    observations: dict[str, list[AskObservation]] = defaultdict(list)
    for observation in _asks_from_depth(depth_objects) + _asks_from_quotes(quote_objects):
        observations[observation.instrument_id].append(observation)

    offsets = _station_offsets()
    settlement_cache: dict[tuple[str, dt.date], Any] = {}

    def settlement(station: str, climate_day: dt.date) -> Any:
        key = (station, climate_day)
        if key not in settlement_cache:
            city = offsets[station][0]
            catalog_path = station_catalog_path(settlement_base, VENUE, city)
            if not catalog_path.exists():
                settlement_cache[key] = None
            else:
                settlement_cache[key] = read_climate_day_including_corrections(
                    ParquetDataCatalog(catalog_path),
                    station=station,
                    climate_day=climate_day,
                )
        return settlement_cache[key]

    no_instrument = unknown_station = no_ask = no_pre_day = 0
    no_settlement = not_final = tmax_missing = 0
    population: list[PopulationMember] = []
    pre_day_entries: list[tuple[InstrumentFacts, AskObservation]] = []
    #: Earliest observation of ANY rung of a station-day, pre-day or not. This
    #: is what says whether the recorder was even running before local
    #: midnight -- the precondition for a D+1 book to exist at all.
    first_observation_by_day: dict[tuple[str, dt.date], int] = {}

    for instrument_id in sorted(observations):
        facts = facts_by_id.get(instrument_id)
        if facts is None:
            no_instrument += 1
            continue
        if facts.station not in offsets:
            unknown_station += 1
            continue
        _, offset = offsets[facts.station]
        day_key = (facts.station, facts.climate_day)
        for obs in observations[instrument_id]:
            previous = first_observation_by_day.get(day_key)
            if previous is None or obs.ts_event_ns < previous:
                first_observation_by_day[day_key] = obs.ts_event_ns
        pre_day = [
            obs
            for obs in observations[instrument_id]
            if is_pre_climate_day(
                obs.ts_event_ns,
                climate_day=facts.climate_day,
                std_utc_offset_hours=offset,
            )
        ]
        if not observations[instrument_id]:
            no_ask += 1
            continue
        entry = first_genuine_ask(pre_day)
        if entry is None:
            no_pre_day += 1
            continue
        pre_day_entries.append((facts, entry))

        record = settlement(facts.station, facts.climate_day)
        if record is None:
            no_settlement += 1
            continue
        if not record.is_final:
            not_final += 1
            continue
        if record.tmax_f is None:
            tmax_missing += 1
            continue
        population.append(
            PopulationMember(
                facts=facts,
                entry=entry,
                tmax_f=int(record.tmax_f),
                settled_yes=settles_yes(
                    int(record.tmax_f), lower_f=facts.lower_f, upper_f=facts.upper_f
                ),
            )
        )

    ledger = ExclusionLedger(
        no_instrument_record=no_instrument,
        unknown_station=unknown_station,
        no_ask_at_all=no_ask,
        no_pre_climate_day_ask=no_pre_day,
        no_settlement_record=no_settlement,
        settlement_not_final=not_final,
        settlement_tmax_missing=tmax_missing,
    )
    # Why each D+1 station-day did or did not reach the population. Without
    # this the report cannot distinguish "settlement ingestion is broken" from
    # "the climate day has not finished yet", which are opposite findings.
    settlement_status: dict[tuple[str, dt.date], str] = {}
    for facts, _entry in pre_day_entries:
        key = (facts.station, facts.climate_day)
        if key in settlement_status:
            continue
        record = settlement(facts.station, facts.climate_day)
        if record is None:
            settlement_status[key] = "no CLI record yet (climate day not closed)"
        elif not record.is_final:
            settlement_status[key] = "CLI record present but PRELIMINARY"
        elif record.tmax_f is None:
            settlement_status[key] = "FINAL CLI record but tmax_f is missing"
        else:
            settlement_status[key] = f"FINAL, tmax_f = {record.tmax_f}"

    context = {
        "pre_day_entries": pre_day_entries,
        "instrument_count": len(facts_by_id),
        "observed_instrument_count": len(observations),
        "settlement_status": settlement_status,
        "first_observation_by_day": first_observation_by_day,
    }
    return (
        [instrument_preflight, depth_preflight, quote_preflight],
        population,
        ledger,
        context,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _ns_to_utc(ts_ns: int | None) -> str:
    if ts_ns is None:
        return "n/a"
    return (
        dt.datetime.fromtimestamp(ts_ns / _NS_PER_SECOND, dt.UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _overall_verdict(strata: Sequence[Stratum]) -> str:
    if any(s.verdict == "FAMILY_SURVIVES" for s in strata):
        return "FAMILY SURVIVES"
    powered = [s for s in strata if s.verdict == "FAMILY_DEAD"]
    if powered and all(s.verdict == "FAMILY_DEAD" for s in strata if s.n > 0):
        return "FAMILY DEAD"
    return "UNDERPOWERED -- INCONCLUSIVE"


def render_report(
    *,
    preflights: Sequence[TapePreflight],
    population: Sequence[PopulationMember],
    ledger: ExclusionLedger,
    context: dict[str, Any],
    tape_root: Path,
    settlement_base: Path,
    generated_at: dt.datetime,
) -> str:
    lines: list[str] = []
    add = lines.append

    add("# K1 -- cheap D+1 rungs: do they settle YES often enough to pay?")
    add("")
    add(f"Generated {generated_at.isoformat(timespec='seconds').replace('+00:00', 'Z')}")
    add("")
    add(f"- Quote tape: `{tape_root}`")
    add(f"- Settlement catalog: `{settlement_base}`")
    add("- Regenerate: `python scripts/analysis/k1_cheap_open_settlement.py`")
    add("")
    add(
        "This is a DESCRIPTIVE settlement-frequency measurement plus a closed-form "
        "break-even comparison. No order, fill, position or P&L is simulated: "
        "Nautilus Trader is the exclusive owner of backtesting."
    )
    add("")

    # -- preflight ----------------------------------------------------------
    add("## 1. Tape preflight (L-8)")
    add("")
    add(
        "`ParquetDataCatalog._read_feather_file` swallows `(ArrowInvalid, OSError)` "
        "and returns `None`, which `convert_stream_to_data` turns into a silent "
        "`continue`. Every file below was opened DIRECTLY, so a truncated file is "
        "counted rather than read as an empty market. Both the `data/` and `live/` "
        "subtrees are read."
    )
    add("")
    add(
        "| Data class | Files | Parsed | FAILED (corrupt) | FAILED (mid-write) | "
        "Raw rows | Dedup rows | Instruments |"
    )
    add("|---|---:|---:|---:|---:|---:|---:|---:|")
    for pf in preflights:
        corrupt = sum(1 for _, _, kind in pf.failures if kind == "CORRUPT")
        add(
            f"| {pf.data_class} | {pf.files_found} | {pf.files_parsed} | "
            f"{corrupt} | {pf.files_failed - corrupt} | {pf.raw_rows} | "
            f"{pf.deduplicated_rows} | {pf.instruments} |"
        )
    add("")
    add(
        "Capture is ONGOING while this script runs, so the newest feather in the "
        "active recorder run is routinely mid-message. Those are separated from "
        "genuine corruption by file mtime rather than pooled: a mid-write file "
        "reads cleanly on the next run, a corrupt one never will. Neither is "
        "swallowed."
    )
    add("")
    add(
        "Raw rows exceed dedup rows because the recorder writes each frame to the "
        "streaming `live/` feather AND the consolidated `data/` parquet; rows are "
        "de-duplicated on `(instrument_id, ts_event, ts_init)`."
    )
    add("")
    for pf in preflights:
        if pf.files_failed:
            add(f"### Parse failures -- {pf.data_class} ({pf.files_failed})")
            add("")
            for path, reason, kind in pf.failures:
                add(f"- [{kind}] `{path}`")
                add(f"  - {reason}")
            add("")
    if not any(pf.files_failed for pf in preflights):
        add("No file failed to parse.")
        add("")

    starts = [pf.ts_event_min_ns for pf in preflights if pf.ts_event_min_ns is not None]
    ends = [pf.ts_event_max_ns for pf in preflights if pf.ts_event_max_ns is not None]
    if starts and ends:
        add(
            f"**Observed tape span (ts_event):** {_ns_to_utc(min(starts))}"
            f" -> {_ns_to_utc(max(ends))}"
        )
        add("")

    add("### Rows per instrument (deduplicated)")
    add("")
    add("| Instrument | order_book_depths | quote_tick |")
    add("|---|---:|---:|")
    depth_rows = next(
        (pf.rows_per_instrument for pf in preflights if pf.data_class == "OrderBookDepth10"),
        {},
    )
    quote_rows = next(
        (pf.rows_per_instrument for pf in preflights if pf.data_class == "QuoteTick"), {}
    )
    for instrument_id in sorted(set(depth_rows) | set(quote_rows)):
        add(
            f"| `{instrument_id}` | {depth_rows.get(instrument_id, 0)} | "
            f"{quote_rows.get(instrument_id, 0)} |"
        )
    add("")
    add(
        f"`order_book_depths` covers {len(depth_rows)} instruments against "
        f"{len(quote_rows)} in `quote_tick`. A `QuoteTick` is two-sided and "
        "`parse_book_top` refuses to invent a bid, so a market whose BID side is "
        "empty -- the normal state of a deep cheap offer here -- emits depth only. "
        "Reading quotes alone would drop exactly the population K1 measures."
    )
    add("")

    # -- population ---------------------------------------------------------
    add("## 2. Population as implemented")
    add("")
    add(
        "One member per `(station, climate_day, rung)` whose book carried a genuine "
        "ask STRICTLY before its climate day began in local STANDARD time (the "
        "registry's fixed `std_utc_offset_hours`, never DST-aware -- the same rule "
        "as `breezy.ingest.records._climate_day_end_ns`). The entry price is the "
        "FIRST such ask by `ts_event` ascending, ties broken on `ts_init`; never an "
        "average and never the best of the window."
    )
    add("")
    add(
        f"Settlement truth is the NWS CLI integer `tmax_f` via "
        f"`read_climate_day_including_corrections`, requiring `is_final`. No "
        f"ASOS/METAR maximum is ever substituted. Predicate: "
        f"{SETTLEMENT_PREDICATE_STATEMENT} (evidence: "
        f"`{SETTLEMENT_PREDICATE_EVIDENCE}`)."
    )
    add("")
    add("| Stage | Count |")
    add("|---|---:|")
    add(f"| Instruments recorded in the tape | {context['instrument_count']} |")
    add(f"| Instruments with any ask observation | {context['observed_instrument_count']} |")
    add(f"| Dropped: no instrument definition record | {ledger.no_instrument_record} |")
    add(f"| Dropped: station not in registry | {ledger.unknown_station} |")
    add(f"| Dropped: no genuine ask before the climate day | {ledger.no_pre_climate_day_ask} |")
    add(f"| **D+1 entries found** | **{len(context['pre_day_entries'])}** |")
    add(f"| Dropped: no CLI record for that station-day | {ledger.no_settlement_record} |")
    add(f"| Dropped: CLI record not FINAL (day still open) | {ledger.settlement_not_final} |")
    add(f"| Dropped: FINAL record has no `tmax_f` | {ledger.settlement_tmax_missing} |")
    add(f"| **MEASURED POPULATION** | **{len(population)}** |")
    add("")

    add("### Capture coverage per station-day")
    add("")
    add(
        "A D+1 book exists only if the recorder was RUNNING before that station-"
        "day's local-standard midnight. `First observation` below is the "
        "earliest tape observation of ANY rung of that station-day; `Day began` "
        "is its local-standard midnight in UTC. Where the first observation "
        "falls after the day began, the entire station-day is intraday and "
        "contributes nothing to K1 -- by construction, not by defect."
    )
    add("")
    add("| Station | Climate day | Day began (UTC) | First observation (UTC) | D+1? | Settlement |")
    add("|---|---|---|---|:--:|---|")
    offsets = _station_offsets()
    first_by_day: dict[tuple[str, dt.date], int] = context["first_observation_by_day"]
    status: dict[tuple[str, dt.date], str] = context["settlement_status"]
    for station, climate_day in sorted(first_by_day):
        if station not in offsets:
            continue
        began = climate_day_start_ns(climate_day, offsets[station][1])
        first = first_by_day[(station, climate_day)]
        is_d1 = first < began
        add(
            f"| {station} | {climate_day.isoformat()} | {_ns_to_utc(began)} | "
            f"{_ns_to_utc(first)} | {'YES' if is_d1 else 'no'} | "
            f"{status.get((station, climate_day), 'n/a -- no D+1 entry')} |"
        )
    add("")

    # -- ask distribution ---------------------------------------------------
    add("## 3. Entry-ask distribution (D+1 entries, all outcomes)")
    add("")
    entry_prices = sorted(entry.ask_price for _, entry in context["pre_day_entries"])
    if not entry_prices:
        add("No D+1 entry asks were observed.")
        add("")
    else:
        histogram: dict[Decimal, int] = defaultdict(int)
        for price in entry_prices:
            histogram[price] += 1
        add("| Entry ask | Count |")
        add("|---:|---:|")
        for price in sorted(histogram):
            add(f"| {price} | {histogram[price]} |")
        add("")
        add(
            f"Min {entry_prices[0]}, median {entry_prices[len(entry_prices) // 2]}, "
            f"max {entry_prices[-1]}, n={len(entry_prices)}."
        )
        add("")

    # -- per-station / per-stratum -----------------------------------------
    add("## 4. Settlement frequency by station and cheap-ask stratum")
    add("")
    add(
        "Break-even is `ask + theta * ask * (1 - ask)` evaluated at the stratum "
        "THRESHOLD (the most expensive ask admitted), with `theta` read per market "
        "from `instrument.info[fee_coefficient]` -- never defaulted. `clears?` asks "
        "whether the Wilson 95% UPPER bound exceeds break-even."
    )
    add("")

    thetas = {member.facts.theta for member in population}
    theta = thetas.pop() if len(thetas) == 1 else Decimal("0.06")
    if len(thetas) > 0:
        add(f"WARNING: multiple fee coefficients observed; tables use {theta}.")
        add("")

    by_station: dict[str, list[PopulationMember]] = defaultdict(list)
    for member in population:
        by_station[member.facts.station].append(member)

    header = (
        "| Scope | Ask <= | n | k | pi | Wilson 95% low | Wilson 95% high | "
        "Break-even | Clears? | Resolution floor | Verdict |"
    )
    divider = "|---|---:|---:|---:|---:|---:|---:|---:|:--:|---:|---|"

    add("### Per station (PRIMARY -- G-01: WFOs are not exchangeable)")
    add("")
    add(header)
    add(divider)
    if not by_station:
        add("| _no station has a measured population_ | | | | | | | | | | |")
    for station in sorted(by_station):
        members = by_station[station]
        for threshold in ASK_STRATA:
            outcomes = [m.settled_yes for m in members if m.entry.ask_price <= threshold]
            member_thetas = {m.facts.theta for m in members if m.entry.ask_price <= threshold}
            stratum_theta = member_thetas.pop() if len(member_thetas) == 1 else theta
            stratum = summarize_stratum(threshold=threshold, outcomes=outcomes, theta=stratum_theta)
            add(
                f"| {station} | {threshold} | {stratum.n} | {stratum.k} | "
                f"{_rate(stratum.pi)} | {_rate(stratum.wilson_lower)} | "
                f"{_rate(stratum.wilson_upper)} | {stratum.break_even} | "
                f"{'-' if stratum.clears is None else ('YES' if stratum.clears else 'no')} | "
                f"{_rate(stratum.resolution_floor)} | {stratum.verdict} |"
            )
    add("")

    add("### Pooled across stations (INDICATIVE ONLY)")
    add("")
    add(
        "G-01 established that WFOs are not exchangeable, so pooling mixes "
        "populations with different forecast skill and different climatology. "
        "Reported for scale only; it is not the finding."
    )
    add("")
    pooled_strata: list[Stratum] = []
    add(header)
    add(divider)
    for threshold in ASK_STRATA:
        outcomes = [m.settled_yes for m in population if m.entry.ask_price <= threshold]
        stratum = summarize_stratum(threshold=threshold, outcomes=outcomes, theta=theta)
        pooled_strata.append(stratum)
        add(
            f"| POOLED | {threshold} | {stratum.n} | {stratum.k} | "
            f"{_rate(stratum.pi)} | {_rate(stratum.wilson_lower)} | "
            f"{_rate(stratum.wilson_upper)} | {stratum.break_even} | "
            f"{'-' if stratum.clears is None else ('YES' if stratum.clears else 'no')} | "
            f"{_rate(stratum.resolution_floor)} | {stratum.verdict} |"
        )
    add("")

    if population:
        add("### Every measured member (the whole sample, listed)")
        add("")
        add("| Station | Climate day | Rung | Entry ask | Entry (UTC) | CLI tmax_f | Settled |")
        add("|---|---|---|---:|---|---:|:--:|")
        for member in sorted(
            population,
            key=lambda m: (m.facts.station, m.facts.climate_day, m.entry.ask_price),
        ):
            bounds = f"[{member.facts.lower_f}, {member.facts.upper_f}]"
            add(
                f"| {member.facts.station} | {member.facts.climate_day.isoformat()} | "
                f"{bounds} | {member.entry.ask_price} | "
                f"{_ns_to_utc(member.entry.ts_event_ns)} | {member.tmax_f} | "
                f"{'YES' if member.settled_yes else 'no'} |"
            )
        add("")

    # -- power --------------------------------------------------------------
    required = required_n_to_discriminate()
    add("## 5. Power")
    add("")
    add(
        f"To distinguish a true settle rate of {POWER_P_ALT:.0%} (a real edge at a "
        f"1c ask) from {POWER_P_NULL:.0%} (no edge) at 95% confidence -- i.e. for "
        f"the Wilson 95% lower bound at {POWER_P_ALT:.0%} to clear "
        f"{POWER_P_NULL:.0%} -- requires **n = {required}** qualifying D+1 "
        f"observations per cell."
    )
    add("")
    add("")
    add(
        "That is only the DISCRIMINATION sample. The binding constraint on a "
        "FAMILY DEAD verdict is stricter: the Wilson 95% UPPER bound must fall "
        "to break-even even when NOTHING settles YES, and at zero events that "
        "bound is `z^2 / (n + z^2)`."
    )
    add("")
    add(
        "| Stratum (ask <=) | Break-even | n to discriminate 3% from 1% | n to REFUTE at zero YES |"
    )
    add("|---:|---:|---:|---:|")
    for threshold in ASK_STRATA:
        add(
            f"| {threshold} | "
            f"{break_even_probability(ask=threshold, theta=theta)} | {required} | "
            f"{min_n_to_refute(threshold=threshold, theta=theta)} |"
        )
    add("")
    largest = max((s.n for s in pooled_strata), default=0)
    add(
        f"The pooled sample currently reaches n = {largest}. A shortfall is a "
        f"statement about how much capture has accumulated, not about the venue."
    )
    add("")
    floor = resolution_floor(largest)
    if floor is not None:
        add(
            f"At n = {largest} the smallest Wilson 95% upper bound obtainable -- at "
            f"ZERO observed YES settlements -- is {floor:.4f}. Any break-even below "
            f"that figure is UNREACHABLE with the corpus on hand: the measurement "
            f"cannot refute the family no matter what the outcomes are."
        )
        add("")
    add(
        f"Capture yields roughly one D+1 book per station per day across "
        f"{len(_station_offsets())} stations and 6 rungs per station-day, so "
        f"n = {required} qualifying observations is on the order of "
        f"{math.ceil(required / max(6 * len(_station_offsets()), 1))} more full "
        f"capture days IF every station-day is captured before its local midnight. "
        f"Rungs within one station-day are NOT independent (they partition the same "
        f"outcome), so the effective station-day requirement is materially larger "
        f"than that arithmetic suggests -- treat it as a floor."
    )
    add("")

    # -- verdict ------------------------------------------------------------
    verdict = _overall_verdict(pooled_strata)
    add("## 6. VERDICT")
    add("")
    add(f"**{verdict}**")
    add("")
    if verdict.startswith("UNDERPOWERED"):
        add(
            f"The measurement settles nothing yet. Capture began recently and is "
            f"ongoing; the D+1 window (a rung's book observed before its own "
            f"climate day starts) is the scarcest slice of it. "
            f"n = {required} per cell is needed to discriminate "
            f"{POWER_P_ALT:.0%} from {POWER_P_NULL:.0%}; the largest cell here is "
            f"n = {largest}."
        )
        add("")
        pending = len(context["pre_day_entries"]) - len(population)
        if pending > 0:
            add(
                f"**{pending} D+1 entries are already captured and waiting only "
                f"on settlement truth.** They belong to climate days that have "
                f"not closed yet; they enter the population automatically on the "
                f"next run after their FINAL CLI product is ingested. The "
                f"measurement is wired end to end -- what is missing is elapsed "
                f"time, not code."
            )
            add("")
        add(
            "Do NOT read this as evidence for or against the calibration family. "
            "Re-run this script as capture accumulates -- it is idempotent and "
            "takes the catalog path as an argument."
        )
    elif verdict == "FAMILY DEAD":
        add(
            "Every populated stratum's Wilson 95% UPPER bound sits at or below its "
            "fee-inclusive break-even at adequate n. Cheap D+1 rungs do not settle "
            "YES often enough to pay for themselves, and the forecast-ingestion "
            "build the calibration family would require is not justified."
        )
    else:
        add(
            "At least one stratum's Wilson 95% LOWER bound exceeds its fee-inclusive "
            "break-even at adequate n. The family is not refuted by this "
            "measurement and warrants the next step."
        )
    add("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quote-tape",
        default=DEFAULT_QUOTE_TAPE_PATH.as_posix(),
        help="Root of the Polymarket.us quote tape (has both data/ and live/).",
    )
    parser.add_argument(
        "--settlement-catalog",
        default=DEFAULT_SETTLEMENT_CATALOG_BASE.as_posix(),
        help="Base of the NWS settlement catalog (holds <venue>/<CITY>).",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH.as_posix())
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    tape_root = Path(args.quote_tape)
    settlement_base = Path(args.settlement_catalog)
    output_path = Path(args.output)

    if not tape_root.exists():
        raise FileNotFoundError(f"quote tape not found: {tape_root}")

    preflights, population, ledger, context = build_population(
        tape_root=tape_root, settlement_base=settlement_base
    )
    report = render_report(
        preflights=preflights,
        population=population,
        ledger=ledger,
        context=context,
        tape_root=tape_root,
        settlement_base=settlement_base,
        generated_at=dt.datetime.now(dt.UTC),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
