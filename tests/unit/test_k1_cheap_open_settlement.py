"""Unit tests for the K1 cheap-open settlement measurement (RED first).

K1 asks ONE descriptive question: of the rungs that were offered cheaply in
the **D+1 book** (quoted BEFORE their climate day began), what fraction
settled YES -- and does the Wilson 95% UPPER bound on that fraction clear the
fee-inclusive break-even at the price actually offered?

Everything exercised here is PURE: climate-day boundary arithmetic, the rung
settlement predicate, first-ask selection, the Wilson interval, the venue fee
break-even, and the power arithmetic. No test in this file reads the live
tape -- the tape is exercised only by the script's own preflight, which is
reported as data rather than asserted here.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from k1_cheap_open_settlement import (
    MID_WRITE_WINDOW_NS,
    Z_95,
    AskObservation,
    break_even_probability,
    classify_parse_failure,
    clears_break_even,
    climate_day_start_ns,
    first_genuine_ask,
    is_genuine_ask,
    is_pre_climate_day,
    min_n_to_refute,
    required_n_to_discriminate,
    resolution_floor,
    settles_yes,
    summarize_stratum,
    wilson_interval,
    wilson_lower_at_rate,
)

# The repo's existing Wilson lower bound. K1's two-sided interval is pinned to
# it so the programme cannot end up with two disagreeing Wilson formulas.
from settlement_alignment_study import (
    wilson_lower_bound as wilson_lower_bound_reference,
)

# The repo's existing, settlement-path climate-day boundary rule. K1 must not
# re-author it; these tests pin K1's start-of-day to that end-of-day function.
from breezy.ingest.records import _climate_day_end_ns

# ---------------------------------------------------------------------------
# Climate-day boundary (local STANDARD midnight, never DST-aware)
# ---------------------------------------------------------------------------


def _epoch_ns(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso).timestamp() * 1_000_000_000)


def test_climate_day_start_is_local_standard_midnight_for_nyc() -> None:
    # NYC standard offset is -5.0 year round, so 2026-08-31 begins 05:00Z.
    assert climate_day_start_ns(dt.date(2026, 8, 31), -5.0) == _epoch_ns(
        "2026-08-31T05:00:00+00:00"
    )


def test_climate_day_start_is_never_dst_aware() -> None:
    """A July date must still use -5.0, not the -4.0 the IANA zone would give."""
    assert climate_day_start_ns(dt.date(2026, 7, 15), -5.0) == _epoch_ns(
        "2026-07-15T05:00:00+00:00"
    )


@pytest.mark.parametrize("offset", [-5.0, -6.0, -8.0])
def test_climate_day_start_equals_the_repo_rule_for_the_previous_days_end(
    offset: float,
) -> None:
    """Pins K1's boundary to `breezy.ingest.records._climate_day_end_ns`.

    The start of a climate day IS the end of the day before it under the same
    fixed offset. If the repo's rule ever moves, this fails RED rather than
    letting K1 drift onto a private second definition.
    """
    day = dt.date(2026, 8, 31)
    assert climate_day_start_ns(day, offset) == _climate_day_end_ns(
        day - dt.timedelta(days=1), offset
    )


def test_pre_climate_day_is_strict_before_the_boundary() -> None:
    day = dt.date(2026, 8, 31)
    boundary = climate_day_start_ns(day, -5.0)
    assert is_pre_climate_day(boundary - 1, climate_day=day, std_utc_offset_hours=-5.0)
    # The boundary instant itself is INSIDE the climate day, not before it.
    assert not is_pre_climate_day(boundary, climate_day=day, std_utc_offset_hours=-5.0)
    assert not is_pre_climate_day(boundary + 1, climate_day=day, std_utc_offset_hours=-5.0)


# ---------------------------------------------------------------------------
# Rung membership from the CLI integer
# ---------------------------------------------------------------------------


def test_interior_rung_is_inclusive_at_both_ends() -> None:
    """`gte76lt77f` decodes to the CLOSED interval [76, 77]."""
    assert not settles_yes(75, lower_f=76, upper_f=77)
    assert settles_yes(76, lower_f=76, upper_f=77)
    assert settles_yes(77, lower_f=76, upper_f=77)
    assert not settles_yes(78, lower_f=76, upper_f=77)


def test_lower_open_rung_settles_yes_at_or_below_its_inclusive_ceiling() -> None:
    """`lt76f` decodes to (None, 75)."""
    assert settles_yes(75, lower_f=None, upper_f=75)
    assert not settles_yes(76, lower_f=None, upper_f=75)


def test_upper_open_rung_settles_yes_at_or_above_its_floor() -> None:
    """`gte84f` decodes to (84, None)."""
    assert not settles_yes(83, lower_f=84, upper_f=None)
    assert settles_yes(84, lower_f=84, upper_f=None)
    assert settles_yes(120, lower_f=84, upper_f=None)


def test_a_rung_with_no_finite_bound_is_refused() -> None:
    with pytest.raises(ValueError):
        settles_yes(80, lower_f=None, upper_f=None)


# ---------------------------------------------------------------------------
# First-ask selection
# ---------------------------------------------------------------------------


def _ask(ts_event: int, price: str, size: str, ts_init: int | None = None) -> AskObservation:
    return AskObservation(
        instrument_id="tc-temp-nychigh-2026-08-31-gte82lt83f.POLYMARKET_US",
        ts_event_ns=ts_event,
        ts_init_ns=ts_event if ts_init is None else ts_init,
        ask_price=Decimal(price),
        ask_size=Decimal(size),
        source="order_book_depths",
    )


def test_a_padded_zero_level_is_not_a_genuine_ask() -> None:
    """`OrderBookDepth10` pads unfilled levels with price 0.00 / size 0.00."""
    assert not is_genuine_ask(_ask(1, "0.00", "0.00"))
    assert not is_genuine_ask(_ask(1, "0.01", "0.00"))
    assert not is_genuine_ask(_ask(1, "0.00", "10.00"))


def test_a_fully_priced_certainty_is_not_a_tradeable_ask() -> None:
    assert not is_genuine_ask(_ask(1, "1.00", "10.00"))


def test_a_populated_level_is_a_genuine_ask() -> None:
    assert is_genuine_ask(_ask(1, "0.01", "767198.02"))


def test_first_genuine_ask_takes_the_earliest_observation_not_the_best_price() -> None:
    """The strategy trades what was offered when it looked, not the best of the window."""
    chosen = first_genuine_ask(
        [
            _ask(300, "0.01", "500"),
            _ask(100, "0.05", "500"),
            _ask(200, "0.02", "500"),
        ]
    )
    assert chosen is not None
    assert chosen.ts_event_ns == 100
    assert chosen.ask_price == Decimal("0.05")


def test_first_genuine_ask_skips_non_genuine_observations() -> None:
    chosen = first_genuine_ask([_ask(100, "0.00", "0.00"), _ask(200, "0.03", "40")])
    assert chosen is not None
    assert chosen.ts_event_ns == 200


def test_first_genuine_ask_breaks_ts_event_ties_on_ts_init() -> None:
    chosen = first_genuine_ask(
        [_ask(100, "0.04", "10", ts_init=900), _ask(100, "0.02", "10", ts_init=800)]
    )
    assert chosen is not None
    assert chosen.ask_price == Decimal("0.02")


def test_first_genuine_ask_returns_none_when_no_side_was_ever_offered() -> None:
    assert first_genuine_ask([]) is None
    assert first_genuine_ask([_ask(1, "0.00", "0.00")]) is None


# ---------------------------------------------------------------------------
# Wilson 95% interval
# ---------------------------------------------------------------------------


def test_wilson_interval_is_undefined_for_an_empty_sample() -> None:
    assert wilson_interval(0, 0) is None


def test_wilson_interval_at_zero_events_has_a_zero_lower_and_positive_upper() -> None:
    interval = wilson_interval(0, 10)
    assert interval is not None
    lower, upper = interval
    assert lower == pytest.approx(0.0, abs=1e-12)
    assert 0.0 < upper < 1.0


def test_wilson_lower_matches_the_repo_reference_implementation() -> None:
    """Pins K1's interval to `settlement_alignment_study.wilson_lower_bound`."""
    for k, n in ((0, 7), (1, 7), (3, 40), (12, 100)):
        interval = wilson_interval(k, n)
        assert interval is not None
        assert interval[0] == pytest.approx(wilson_lower_bound_reference(k, n, Z_95))
        # The upper bound is the lower bound of the complementary count,
        # mirrored -- the identity the repo already uses.
        assert interval[1] == pytest.approx(1.0 - wilson_lower_bound_reference(n - k, n, Z_95))


def test_resolution_floor_is_the_wilson_upper_at_zero_events() -> None:
    assert resolution_floor(0) is None
    floor = resolution_floor(40)
    interval = wilson_interval(0, 40)
    assert floor is not None and interval is not None
    assert floor == pytest.approx(interval[1])


# ---------------------------------------------------------------------------
# Break-even at the venue fee
# ---------------------------------------------------------------------------


def test_break_even_probability_is_price_plus_the_venue_fee() -> None:
    # theta * p * (1 - p) at theta=0.06, p=0.01  ->  0.000594
    assert break_even_probability(ask=Decimal("0.01"), theta=Decimal("0.06")) == Decimal("0.010594")


def test_break_even_probability_requires_an_explicit_theta() -> None:
    """There is deliberately no default theta: it is a per-market venue fact."""
    with pytest.raises(TypeError):
        break_even_probability(ask=Decimal("0.01"))  # type: ignore[call-arg]


def test_break_even_rises_with_the_ask() -> None:
    theta = Decimal("0.06")
    prices = [Decimal("0.01"), Decimal("0.02"), Decimal("0.03"), Decimal("0.05")]
    values = [break_even_probability(ask=p, theta=theta) for p in prices]
    assert values == sorted(values)


def test_clears_break_even_is_strict_and_uses_the_upper_bound() -> None:
    assert clears_break_even(0.05, Decimal("0.010594"))
    assert not clears_break_even(0.010594, Decimal("0.010594"))
    assert not clears_break_even(0.001, Decimal("0.010594"))


# ---------------------------------------------------------------------------
# Stratum summary
# ---------------------------------------------------------------------------


def test_summarize_stratum_reports_n_k_and_a_verdict_that_names_underpower() -> None:
    stratum = summarize_stratum(
        threshold=Decimal("0.03"),
        outcomes=[True, False, False, False, False, False, False],
        theta=Decimal("0.06"),
    )
    assert stratum.n == 7
    assert stratum.k == 1
    assert stratum.pi == pytest.approx(1 / 7)
    assert stratum.wilson_upper is not None and stratum.wilson_upper > 0.3
    # n=7 cannot resolve a 3% rate at all: the zero-event Wilson upper alone
    # sits far above break-even, so the sample settles nothing.
    assert stratum.verdict == "UNDERPOWERED"


def test_summarize_stratum_reports_an_empty_stratum_as_underpowered_not_zero() -> None:
    stratum = summarize_stratum(threshold=Decimal("0.01"), outcomes=[], theta=Decimal("0.06"))
    assert stratum.n == 0
    assert stratum.pi is None
    assert stratum.wilson_upper is None
    assert stratum.verdict == "UNDERPOWERED"


def test_summarize_stratum_calls_the_family_dead_only_with_adequate_n() -> None:
    """FAMILY_DEAD needs BOTH adequate n and a Wilson upper at/below break-even."""
    n = 400
    assert n >= required_n_to_discriminate(p_alt=0.03, p_null=0.01)
    stratum = summarize_stratum(
        threshold=Decimal("0.01"), outcomes=[False] * n, theta=Decimal("0.06")
    )
    assert stratum.n == n
    assert stratum.wilson_upper is not None
    assert stratum.wilson_upper <= float(
        break_even_probability(ask=Decimal("0.01"), theta=Decimal("0.06"))
    )
    assert stratum.verdict == "FAMILY_DEAD"


def test_a_wilson_upper_below_break_even_is_still_underpowered_below_required_n() -> None:
    """Adequate n gates BOTH verdicts; a tiny sample can never kill the family."""
    stratum = summarize_stratum(
        threshold=Decimal("0.01"), outcomes=[False] * 5, theta=Decimal("0.06")
    )
    assert stratum.verdict == "UNDERPOWERED"


def test_summarize_stratum_says_survives_when_the_lower_bound_clears() -> None:
    stratum = summarize_stratum(
        threshold=Decimal("0.01"), outcomes=[True] * 60 + [False] * 40, theta=Decimal("0.06")
    )
    assert stratum.n >= required_n_to_discriminate(p_alt=0.03, p_null=0.01)
    assert stratum.wilson_lower is not None
    assert stratum.wilson_lower > float(
        break_even_probability(ask=Decimal("0.01"), theta=Decimal("0.06"))
    )
    assert stratum.verdict == "FAMILY_SURVIVES"


# ---------------------------------------------------------------------------
# Power
# ---------------------------------------------------------------------------


def test_required_n_is_the_smallest_sample_whose_wilson_lower_excludes_the_null() -> None:
    """Defined on the EXACT rate, not on a rounded integer count.

    Rounding ``0.03 * n`` to a whole count at small n inflates the observed
    rate (``round(0.51) == 1`` is 5.9%, not 3%) and would report a required
    sample of 17 -- an artefact of the rounding, not of the statistics.
    """
    n = required_n_to_discriminate(p_alt=0.03, p_null=0.01)
    assert isinstance(n, int) and n > 0
    assert wilson_lower_at_rate(0.03, n) > 0.01
    assert wilson_lower_at_rate(0.03, n - 1) <= 0.01


def test_wilson_lower_at_rate_agrees_with_the_integer_interval_on_whole_counts() -> None:
    for k, n in ((3, 100), (25, 500)):
        interval = wilson_interval(k, n)
        assert interval is not None
        assert wilson_lower_at_rate(k / n, n) == pytest.approx(interval[0])


def test_required_n_grows_as_the_alternatives_get_closer() -> None:
    assert required_n_to_discriminate(p_alt=0.03, p_null=0.01) < required_n_to_discriminate(
        p_alt=0.02, p_null=0.01
    )


def test_required_n_refuses_an_alternative_at_or_below_the_null() -> None:
    with pytest.raises(ValueError):
        required_n_to_discriminate(p_alt=0.01, p_null=0.01)


# ---------------------------------------------------------------------------
# Parse-failure classification
# ---------------------------------------------------------------------------


def test_a_file_the_live_recorder_is_still_writing_is_not_called_corrupt() -> None:
    """Capture is ONGOING, so the newest feather is legitimately mid-message.

    Reporting an actively-appended file as corruption would manufacture a data
    -integrity incident out of a healthy recorder -- the mirror image of the
    L-8 failure this preflight exists to prevent.
    """
    now = 1_788_294_512_000_000_000
    assert (
        classify_parse_failure(file_mtime_ns=now - 5_000_000_000, now_ns=now)
        == "MID_WRITE_SUSPECTED"
    )


def test_a_file_untouched_for_a_long_time_is_called_corrupt() -> None:
    now = 1_788_294_512_000_000_000
    assert classify_parse_failure(file_mtime_ns=now - 86_400_000_000_000, now_ns=now) == "CORRUPT"


def test_the_mid_write_window_boundary_is_inclusive_of_older_files() -> None:
    now = 1_788_294_512_000_000_000
    window = MID_WRITE_WINDOW_NS
    assert classify_parse_failure(file_mtime_ns=now - window, now_ns=now) == "CORRUPT"
    assert (
        classify_parse_failure(file_mtime_ns=now - window + 1, now_ns=now) == "MID_WRITE_SUSPECTED"
    )


# ---------------------------------------------------------------------------
# Sample size needed to REFUTE (stricter than the discrimination sample)
# ---------------------------------------------------------------------------


def test_min_n_to_refute_is_where_a_zero_yes_sample_falls_to_break_even() -> None:
    """The binding constraint for FAMILY DEAD, and it is not `required_n`.

    Discriminating 3% from 1% needs far fewer observations than driving the
    Wilson UPPER bound down to a 1c break-even, because the latter must hold
    even when NOTHING settles YES.
    """
    theta = Decimal("0.06")
    n = min_n_to_refute(threshold=Decimal("0.01"), theta=theta)
    break_even = float(break_even_probability(ask=Decimal("0.01"), theta=theta))

    at_n = resolution_floor(n)
    below = resolution_floor(n - 1)
    assert at_n is not None and below is not None
    assert at_n <= break_even
    assert below > break_even


def test_min_n_to_refute_falls_as_the_stratum_gets_more_expensive() -> None:
    """A pricier stratum has a higher break-even, so it is easier to refute."""
    theta = Decimal("0.06")
    cheap = min_n_to_refute(threshold=Decimal("0.01"), theta=theta)
    dear = min_n_to_refute(threshold=Decimal("0.05"), theta=theta)
    assert dear < cheap


def test_min_n_to_refute_exceeds_the_discrimination_sample_at_one_cent() -> None:
    assert min_n_to_refute(
        threshold=Decimal("0.01"), theta=Decimal("0.06")
    ) > required_n_to_discriminate(p_alt=0.03, p_null=0.01)


# ---------------------------------------------------------------------------
# Streaming depth loader -- must match the materializing loader exactly, and
# must never hold more than one file's rows in memory at once (the live tape
# is 1,787 feather files / 21 GB; materializing every OrderBookDepth10 for
# the WHOLE tape at once is what drove K1's measured 14.9-23.6 GB peak).
# ---------------------------------------------------------------------------

import weakref

import k1_cheap_open_settlement as k1
import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer


def _depth_side(
    levels: list[tuple[str, str]],
    side: OrderSide,
    price_precision: int,
    size_precision: int,
) -> tuple[list[BookOrder], list[int]]:
    orders = [
        BookOrder(
            side,
            Price(float(price), price_precision),
            Quantity(float(size), size_precision),
            0,
        )
        for price, size in levels
    ]
    counts = [1] * len(orders)
    filler = BookOrder(side, Price(0, price_precision), Quantity(0, size_precision), 0)
    while len(orders) < 10:
        orders.append(filler)
        counts.append(0)
    return orders, counts


def _make_depth(
    *,
    instrument_id: InstrumentId,
    ask_levels: list[tuple[str, str]],
    bid_levels: list[tuple[str, str]],
    ts_event: int,
    ts_init: int,
    sequence: int,
    price_precision: int = 2,
    size_precision: int = 2,
) -> OrderBookDepth10:
    bids, bid_counts = _depth_side(bid_levels, OrderSide.BUY, price_precision, size_precision)
    asks, ask_counts = _depth_side(ask_levels, OrderSide.SELL, price_precision, size_precision)
    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=bids,
        asks=asks,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=sequence,
        ts_event=ts_event,
        ts_init=ts_init,
    )


def _write_feather(path: Path, depths: list[OrderBookDepth10]) -> None:
    table = ArrowSerializer.serialize_batch(depths, data_cls=OrderBookDepth10)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pa.OSFile(str(path), "wb") as sink:
        writer = pa.ipc.new_stream(sink, table.schema)
        writer.write_table(table)
        writer.close()


def _write_parquet(path: Path, depths: list[OrderBookDepth10]) -> None:
    table = ArrowSerializer.serialize_batch(depths, data_cls=OrderBookDepth10)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def _mini_depth_tape(tape_root: Path) -> tuple[InstrumentId, InstrumentId, InstrumentId]:
    """Three depth files, three instruments, BOTH tape subtrees and layouts.

    `instrument_c` deliberately carries a DIFFERENT price precision AND a
    different size precision from `instrument_a`/`instrument_b` --
    `minimumTradeQty` changed 1 -> 0.01 on 06-14, so the real tape mixes
    `size_precision=0` and `size_precision=2` files, and price/size precision
    are not the same value within a file either.
    """
    instrument_a = InstrumentId.from_str(
        "tc-temp-nychigh-2026-08-31-gte82lt83f.POLYMARKET_US"
    )
    instrument_b = InstrumentId.from_str(
        "tc-temp-laxhigh-2026-08-31-gte90f.POLYMARKET_US"
    )
    instrument_c = InstrumentId.from_str(
        "tc-temp-mdwhigh-2026-08-31-gte93lt94f.POLYMARKET_US"
    )

    # `data/` parquet -- best ask is level 1, not level 0: pins the "min over
    # populated levels" rule, not "trust level 0".
    depth_a = _make_depth(
        instrument_id=instrument_a,
        ask_levels=[("0.05", "5"), ("0.03", "20")],
        bid_levels=[("0.01", "10")],
        ts_event=100,
        ts_init=101,
        sequence=0,
    )
    _write_parquet(
        tape_root / "data" / "order_book_depths" / "instrument_a" / "part-0.parquet",
        [depth_a],
    )

    # `live/<run>/` feather -- one row with NO offered ask at all (must still
    # be counted in the preflight, but must yield no observation), one with a
    # genuine ask.
    depth_b_no_ask = _make_depth(
        instrument_id=instrument_b,
        ask_levels=[],
        bid_levels=[("0.20", "10")],
        ts_event=200,
        ts_init=201,
        sequence=0,
    )
    depth_b_genuine = _make_depth(
        instrument_id=instrument_b,
        ask_levels=[("0.02", "40")],
        bid_levels=[("0.20", "10")],
        ts_event=300,
        ts_init=301,
        sequence=1,
    )
    _write_feather(
        tape_root
        / "live"
        / "run-1"
        / "order_book_depths"
        / "instrument_b"
        / "instrument_b_1.feather",
        [depth_b_no_ask, depth_b_genuine],
    )

    # `live/<run>/` feather, no per-instrument subfolder (the OTHER layout
    # `_tape_files` globs) -- price_precision=3, size_precision=0, and the
    # best (lowest) ask sits at level 1, not level 0.
    depth_c = _make_depth(
        instrument_id=instrument_c,
        ask_levels=[("0.500", "12"), ("0.125", "7")],
        bid_levels=[("0.100", "5")],
        ts_event=400,
        ts_init=401,
        sequence=0,
        price_precision=3,
        size_precision=0,
    )
    _write_feather(
        tape_root / "live" / "run-2" / "order_book_depths" / "instrument_c_1.feather",
        [depth_c],
    )
    return instrument_a, instrument_b, instrument_c


def _observation_key(observation: AskObservation) -> tuple[str, int, int, Decimal, Decimal]:
    return (
        observation.instrument_id,
        observation.ts_event_ns,
        observation.ts_init_ns,
        observation.ask_price,
        observation.ask_size,
    )


def test_streaming_depth_loader_matches_the_materializing_loader(tmp_path: Path) -> None:
    """The new streaming path must yield exactly the same observations.

    Compared against the OLD path -- `_load_stream` + `_asks_from_depth` --
    kept reachable under its private name for exactly this comparison.
    """
    _mini_depth_tape(tmp_path)

    old_preflight, depth_objects = k1._load_stream(
        tmp_path, "order_book_depths", OrderBookDepth10
    )
    expected = k1._asks_from_depth(depth_objects)

    new_preflight, streamed = k1._load_depth_ask_observations(tmp_path)

    assert {_observation_key(o) for o in streamed} == {_observation_key(o) for o in expected}
    assert len(streamed) == len(expected) == 3

    # The preflight is what K1 tells the reader was on disk -- only the ASK
    # extraction changed, so this accounting must be byte-for-byte identical.
    assert new_preflight.files_found == old_preflight.files_found == 3
    assert new_preflight.files_parsed == old_preflight.files_parsed == 3
    assert new_preflight.files_failed == old_preflight.files_failed == 0
    assert new_preflight.raw_rows == old_preflight.raw_rows == 4
    assert new_preflight.deduplicated_rows == old_preflight.deduplicated_rows == 4
    assert new_preflight.instruments == old_preflight.instruments == 3
    assert new_preflight.rows_per_instrument == old_preflight.rows_per_instrument
    assert new_preflight.ts_event_min_ns == old_preflight.ts_event_min_ns == 100
    assert new_preflight.ts_event_max_ns == old_preflight.ts_event_max_ns == 400

    # Explicit, per-instrument Decimal check on the mixed-precision file
    # (price_precision=3, size_precision=0): the streaming path must decode
    # the SAME winning (out-of-order) level as the materializing path, at
    # the file's OWN precision, not a precision borrowed from another file.
    instrument_c = "tc-temp-mdwhigh-2026-08-31-gte93lt94f.POLYMARKET_US"
    streamed_c = next(o for o in streamed if o.instrument_id == instrument_c)
    expected_c = next(o for o in expected if o.instrument_id == instrument_c)
    assert streamed_c.ask_price == expected_c.ask_price == Decimal("0.125")
    assert streamed_c.ask_size == expected_c.ask_size == Decimal(7)
    assert str(streamed_c.ask_price) == str(expected_c.ask_price)
    assert str(streamed_c.ask_size) == str(expected_c.ask_size)


def test_streaming_depth_loader_reports_a_corrupt_file_the_same_way(tmp_path: Path) -> None:
    """A truncated/corrupt file must still be counted as a failure, not raise."""
    _mini_depth_tape(tmp_path)
    corrupt = tmp_path / "live" / "run-1" / "order_book_depths" / "corrupt" / "bad.feather"
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_bytes(b"not an arrow stream")

    old_preflight, _ = k1._load_stream(tmp_path, "order_book_depths", OrderBookDepth10)
    new_preflight, _ = k1._load_depth_ask_observations(tmp_path)

    assert new_preflight.files_found == old_preflight.files_found == 4
    assert new_preflight.files_failed == old_preflight.files_failed == 1
    assert new_preflight.files_parsed == old_preflight.files_parsed == 3


def test_depth_loader_never_holds_more_than_one_files_table_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The streaming loader must drop file N's table before opening file N+1.

    Proven with `weakref`: by the time a NEW file's table is read, every
    earlier file's table must already be unreachable -- if the loader were
    still accumulating a tape-wide list (the original bug), the earlier
    table would still be alive here.
    """
    _mini_depth_tape(tmp_path)
    original_read = k1._read_arrow_table
    live_refs: list[weakref.ReferenceType] = []

    def _tracking_read(path: Path) -> pa.Table:
        table = original_read(path)
        assert all(ref() is None for ref in live_refs), (
            "a previous file's Arrow table is still alive while the next "
            "file is being read -- the loader is holding more than one "
            "file's rows at once"
        )
        live_refs.append(weakref.ref(table))
        return table

    monkeypatch.setattr(k1, "_read_arrow_table", _tracking_read)

    _, observations = k1._load_depth_ask_observations(tmp_path)

    assert len(live_refs) == 3
    assert len(observations) == 3
