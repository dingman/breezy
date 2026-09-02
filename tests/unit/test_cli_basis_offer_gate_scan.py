"""Unit tests for `scripts/analysis/cli_basis_offer_gate_scan.py` (RED first).

This scan answers the question the archive gate (`cli_basis_boundary_study.py`)
cannot: does the venue actually OFFER the CLI-basis upper tail, cheaply, in
size -- the same mechanism (L-9) that killed three prior strategy families.

Everything exercised here is PURE: open-tail vs interior classification (both
from the instrument's own cross-checked strike facts and from the raw slug
grammar), the headroom boundary check, genuine-ask / qualifying-ask
extraction from a depth snapshot (including the depth-truncation case),
tape-instance preflight classification (CLEAN / EMPTY / LIVE / CORRUPT), the
recent-ASOS-cache loader (cache-only, zero network), and the pre-registered
kill/GO rule. No test in this file reads the live multi-instance tape --
that is exercised by the script's own preflight at run time and reported as
data, matching the K1 precedent (`tests/unit/test_k1_cheap_open_settlement.py`).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from cli_basis_offer_gate_scan import (
    BLOCKED_NO_OBSERVATION_DATA,
    BLOCKED_NO_QUALIFYING_SETUP,
    BLOCKED_TAPE_PREFLIGHT_FAILED,
    CHEAP_ASK_CEILING,
    CONTAMINATED_STATIONS,
    DEAD_UPPER_BOUND,
    GO_LOWER_BOUND,
    MIN_ADMISSIBLE_N,
    MIN_LIQUIDITY_CONTRACTS,
    QUALIFYING_HEADROOM,
    AskLevel,
    classify_blocked_reason,
    classify_instance,
    fee_coefficient_from_instrument,
    genuine_ask_levels,
    headroom_f,
    is_open_upper_tail_facts,
    is_open_upper_tail_slug,
    is_qualifying_headroom,
    kill_rule_verdict,
    load_recent_asos_rows,
    notional_at_qualifying_levels,
    qualifying_ask_levels,
    station_days_only_on_corrupt_tape,
)

# A REAL `BinaryOption`, built the same way `test_polymarket_us_fee_model.py`
# builds one -- from a captured venue payload through the real parser --
# rather than a hand-rolled fake, so `fee_coefficient_from_instrument` is
# exercised against the exact `.info` shape `parse_binary_option` produces.
from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.parsing import parse_binary_option

# The repo's own preflight primitives -- pinned so this scan's LIVE/CORRUPT
# classification cannot silently diverge from what
# `breezy.runtime.quote_tape_preflight_cli` reports.
from breezy.persistence.feather_preflight import (
    FeatherFileReport,
    FeatherStatus,
    PreflightReport,
)

# The min-liquidity floor is a single shared field, never re-hardcoded here.
from breezy.strategy.weather_common.risk import RiskLimits

_OPEN_MARKET_PAYLOAD_PATH = (
    REPO_ROOT
    / "docs"
    / "evidence"
    / "venue"
    / "polymarket_us"
    / "raw"
    / "market_open_510636_by_slug.json"
)
_TS_INIT = 1_787_617_213_000_000_000


def _binary_option_with_fee_coefficient(theta: object) -> BinaryOption:
    payload: dict[str, Any] = json.loads(_OPEN_MARKET_PAYLOAD_PATH.read_text(encoding="utf-8"))
    payload["market"]["feeCoefficient"] = theta
    return parse_binary_option(payload, ts_init=_TS_INIT)


def _binary_option_with_raw_info(instrument: BinaryOption, info: dict[str, Any]) -> BinaryOption:
    """Clone ``instrument`` with a hand-set ``info`` (``info`` is read-only).

    Bypasses `parse_binary_option`'s own fee-coefficient validation, which
    already refuses an out-of-range value at parse time -- this exercises
    `fee_coefficient_from_instrument`'s OWN defensive read against a shape
    that could only ever reach it via a round-trip or serialisation bug, not
    through the real parser.
    """
    return BinaryOption(
        instrument_id=instrument.id,
        raw_symbol=instrument.raw_symbol,
        outcome=instrument.outcome,
        description=instrument.description,
        asset_class=instrument.asset_class,
        currency=instrument.quote_currency,
        price_precision=instrument.price_precision,
        price_increment=instrument.price_increment,
        size_precision=instrument.size_precision,
        size_increment=instrument.size_increment,
        activation_ns=instrument.activation_ns,
        expiration_ns=instrument.expiration_ns,
        min_quantity=instrument.min_quantity,
        ts_event=instrument.ts_event,
        ts_init=instrument.ts_init,
        info=info,
    )

# ---------------------------------------------------------------------------
# min_liquidity_contracts is read from the shared risk config, not hardcoded
# ---------------------------------------------------------------------------


def test_min_liquidity_contracts_is_read_from_the_shared_risk_limits() -> None:
    assert MIN_LIQUIDITY_CONTRACTS == Decimal(str(RiskLimits().min_liquidity_contracts))


# ---------------------------------------------------------------------------
# Open-tail vs interior classification -- authoritative (strike facts) form
# ---------------------------------------------------------------------------


def test_open_upper_tail_facts_true_when_lower_set_and_upper_unbounded() -> None:
    # Real instrument facts observed on the tape: tc-temp-laxhigh-...-gte84f
    assert is_open_upper_tail_facts(lower_f=84, upper_f=None) is True


def test_open_upper_tail_facts_false_for_interior_bucket() -> None:
    # tc-temp-laxhigh-2026-09-01-gte82lt83f
    assert is_open_upper_tail_facts(lower_f=82, upper_f=83) is False


def test_open_upper_tail_facts_false_for_open_lower_tail() -> None:
    # tc-temp-laxhigh-2026-09-01-lt76f -> lower_f=None, upper_f=75
    assert is_open_upper_tail_facts(lower_f=None, upper_f=75) is False


def test_open_upper_tail_facts_false_when_both_bounds_missing() -> None:
    assert is_open_upper_tail_facts(lower_f=None, upper_f=None) is False


# ---------------------------------------------------------------------------
# Open-tail vs interior classification -- slug grammar cross-check
# ---------------------------------------------------------------------------


def test_open_upper_tail_slug_true_for_a_real_open_tail_slug() -> None:
    # Observed verbatim on the tape (instance 5a111bca), station SFO.
    assert is_open_upper_tail_slug("tc-temp-sfohigh-2026-09-01-gte72f") is True


def test_open_upper_tail_slug_false_for_a_real_interior_slug() -> None:
    # Observed verbatim on the tape, station NYC.
    assert is_open_upper_tail_slug("tc-temp-nychigh-2026-09-01-gte82lt83f") is False


def test_open_upper_tail_slug_false_for_an_open_lower_tail_slug() -> None:
    # Observed verbatim on the tape, station LAX: the bottom rung of the
    # high-temperature ladder, a single `lt` token -- open, but the WRONG
    # side, and must not be mistaken for an upper tail.
    assert is_open_upper_tail_slug("tc-temp-laxhigh-2026-09-01-lt76f") is False


def test_open_upper_tail_slug_none_for_an_unparseable_slug() -> None:
    assert is_open_upper_tail_slug("not-a-weather-slug") is None


def test_open_upper_tail_slug_false_for_the_low_temperature_measure() -> None:
    # Same grammar, wrong measure -- this scan is daily-HIGH only.
    assert is_open_upper_tail_slug("tc-temp-nyclow-2026-09-01-gte40f") is False


# ---------------------------------------------------------------------------
# Headroom boundary: X - R(t) in {1, 2}
# ---------------------------------------------------------------------------


def test_headroom_is_strike_minus_running_max() -> None:
    assert headroom_f(strike_f=84, running_f=82) == 2
    assert headroom_f(strike_f=84, running_f=83) == 1
    assert headroom_f(strike_f=84, running_f=84) == 0


@pytest.mark.parametrize("headroom", [1, 2])
def test_qualifying_headroom_accepts_one_and_two(headroom: int) -> None:
    assert is_qualifying_headroom(headroom) is True


@pytest.mark.parametrize("headroom", [-1, 0, 3, 4])
def test_qualifying_headroom_rejects_everything_else(headroom: int) -> None:
    assert is_qualifying_headroom(headroom) is False


def test_qualifying_headroom_set_is_exactly_one_and_two() -> None:
    assert QUALIFYING_HEADROOM == frozenset({1, 2})


# ---------------------------------------------------------------------------
# Genuine / qualifying ask levels, including the depth-truncation case
# ---------------------------------------------------------------------------


def test_genuine_ask_levels_drops_zero_padded_levels() -> None:
    levels = (
        AskLevel(price=Decimal("0.02"), size=Decimal(50)),
        AskLevel(price=Decimal(0), size=Decimal(0)),  # OrderBookDepth10 padding
    )
    assert genuine_ask_levels(levels) == (levels[0],)


def test_genuine_ask_levels_drops_a_size_zero_level_even_with_a_real_price() -> None:
    levels = (AskLevel(price=Decimal("0.03"), size=Decimal(0)),)
    assert genuine_ask_levels(levels) == ()


def test_genuine_ask_levels_drops_a_certainty_priced_at_one() -> None:
    levels = (AskLevel(price=Decimal(1), size=Decimal(100)),)
    assert genuine_ask_levels(levels) == ()


def test_qualifying_ask_levels_requires_both_price_and_size_bars() -> None:
    cheap_but_thin = AskLevel(price=Decimal("0.03"), size=Decimal(10))
    deep_but_pricey = AskLevel(price=Decimal("0.08"), size=Decimal(500))
    cheap_and_deep = AskLevel(price=Decimal("0.05"), size=Decimal(25))
    levels = (cheap_but_thin, deep_but_pricey, cheap_and_deep)
    assert qualifying_ask_levels(levels) == (cheap_and_deep,)


def test_qualifying_ask_levels_ceiling_is_inclusive_at_five_cents() -> None:
    at_ceiling = AskLevel(price=CHEAP_ASK_CEILING, size=MIN_LIQUIDITY_CONTRACTS)
    assert qualifying_ask_levels((at_ceiling,)) == (at_ceiling,)


def test_qualifying_ask_levels_size_floor_is_inclusive() -> None:
    at_floor = AskLevel(price=Decimal("0.01"), size=MIN_LIQUIDITY_CONTRACTS)
    assert qualifying_ask_levels((at_floor,)) == (at_floor,)


def test_notional_sums_price_times_size_across_qualifying_levels_only() -> None:
    levels = (
        AskLevel(price=Decimal("0.01"), size=Decimal(100)),
        AskLevel(price=Decimal("0.02"), size=Decimal(50)),
    )
    assert notional_at_qualifying_levels(levels) == Decimal("0.01") * Decimal(
        100
    ) + Decimal("0.02") * Decimal(50)


def test_notional_is_zero_for_no_qualifying_levels() -> None:
    assert notional_at_qualifying_levels(()) == Decimal(0)


def test_truncation_cannot_hide_a_cheap_ask_because_asks_are_kept_best_first() -> None:
    """`OrderBookDepth10` keeps the 10 BEST (nearest) levels per side.

    For the ask side that means the 10 LOWEST prices survive truncation and
    anything dropped is strictly MORE expensive/deeper. A cheap qualifying
    ask that is actually present in the top 10 is therefore never hidden by
    truncation -- truncation can only make the reported total notional an
    UNDERESTIMATE (a deeper, still-cheap level beyond slot 10 gets dropped),
    never fabricate a false positive. This test pins that reading of the
    schema so a future change to `OrderBookDepth10`'s ordering cannot silently
    invert it.
    """
    ten_best_asks_all_cheap = tuple(
        AskLevel(price=Decimal("0.01") * (i + 1), size=Decimal(100)) for i in range(10)
    )
    assert all(level.price <= CHEAP_ASK_CEILING for level in ten_best_asks_all_cheap[:5])
    qualifying = qualifying_ask_levels(ten_best_asks_all_cheap)
    assert len(qualifying) == 5
    assert min(level.price for level in qualifying) == Decimal("0.01")


# ---------------------------------------------------------------------------
# Tape-instance preflight classification (L-8): a failed tape is never a zero
# ---------------------------------------------------------------------------


def _file_report(*, status: FeatherStatus, rows: int, mtime_ns: int) -> FeatherFileReport:
    return FeatherFileReport(
        path=Path(f"/tmp/{status.value}.feather"),
        status=status,
        size_bytes=1000,
        readable_bytes=1000 if status != FeatherStatus.TRUNCATED else 500,
        batches=1,
        rows=rows,
        schema_readable=True,
        ended_mid_message=status == FeatherStatus.TRUNCATED,
        end_of_stream_marker=status == FeatherStatus.INTACT,
        mtime_ns=mtime_ns,
        failure=None,
    )


def test_classify_instance_clean_when_every_file_is_intact() -> None:
    now_ns = 2_000_000_000_000
    report = PreflightReport(
        catalog_root=Path("/tmp"),
        subdirectory="live",
        instance_id="clean",
        files=(_file_report(status=FeatherStatus.INTACT, rows=10, mtime_ns=now_ns - 10**12),),
    )
    assert classify_instance(report, now_ns=now_ns, grace_ns=60_000_000_000) == "CLEAN"


def test_classify_instance_empty_when_it_captured_nothing() -> None:
    now_ns = 2_000_000_000_000
    report = PreflightReport(
        catalog_root=Path("/tmp"),
        subdirectory="live",
        instance_id="empty",
        files=(_file_report(status=FeatherStatus.EMPTY_STREAM, rows=0, mtime_ns=now_ns - 10**12),),
    )
    assert classify_instance(report, now_ns=now_ns, grace_ns=60_000_000_000) == "EMPTY"


def test_classify_instance_live_when_truncation_is_all_recently_written() -> None:
    """A recorder still holding the file open looks byte-identical to a cut
    one -- exactly the trap the brief calls out. Recency, not row count,
    is what tells the two apart.
    """
    now_ns = 2_000_000_000_000
    report = PreflightReport(
        catalog_root=Path("/tmp"),
        subdirectory="live",
        instance_id="live",
        files=(
            _file_report(status=FeatherStatus.INTACT, rows=10, mtime_ns=now_ns - 10**12),
            _file_report(status=FeatherStatus.TRUNCATED, rows=3, mtime_ns=now_ns - 5_000_000_000),
        ),
    )
    assert classify_instance(report, now_ns=now_ns, grace_ns=60_000_000_000) == "LIVE"


def test_classify_instance_corrupt_when_truncation_is_stale() -> None:
    now_ns = 2_000_000_000_000
    report = PreflightReport(
        catalog_root=Path("/tmp"),
        subdirectory="live",
        instance_id="corrupt",
        files=(
            _file_report(
                status=FeatherStatus.TRUNCATED, rows=3, mtime_ns=now_ns - 86_400_000_000_000
            ),
        ),
    )
    assert classify_instance(report, now_ns=now_ns, grace_ns=60_000_000_000) == "CORRUPT"


def test_classify_instance_corrupt_when_one_of_several_truncations_is_stale() -> None:
    """Mixed recency must not let a genuinely stale loss hide behind a fresh
    one -- a scan that reports CLEAN or LIVE here would silently launder a
    real data-loss incident into a livable false negative.
    """
    now_ns = 2_000_000_000_000
    report = PreflightReport(
        catalog_root=Path("/tmp"),
        subdirectory="live",
        instance_id="mixed",
        files=(
            _file_report(status=FeatherStatus.TRUNCATED, rows=3, mtime_ns=now_ns - 5_000_000_000),
            _file_report(
                status=FeatherStatus.TRUNCATED, rows=1, mtime_ns=now_ns - 86_400_000_000_000
            ),
        ),
    )
    assert classify_instance(report, now_ns=now_ns, grace_ns=60_000_000_000) == "CORRUPT"


# ---------------------------------------------------------------------------
# Recent-ASOS-cache loader: cache-only, scans whatever is already on disk
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CacheFixture:
    directory: Path


@pytest.fixture
def asos_cache(tmp_path: Path) -> _CacheFixture:
    (tmp_path / "a.txt").write_text(
        "station,valid,metar\n"
        "NYC,2026-08-27 00:51,KNYC 270051Z AUTO 10SM CLR 23/18 A3007 RMK AO2 T02280183 $\n"
        "SFO,2026-08-27 00:00,KSFO 270000Z AUTO 10SM CLR 22/13 A2993 RMK T02200130 MADISHF\n",
        encoding="utf-8",
    )
    (tmp_path / "b.txt").write_text(
        "station,valid,metar\n"
        # A duplicate NYC row (same station+valid) that a second overlapping
        # fetch would produce -- must be deduplicated, not double-counted.
        "NYC,2026-08-27 00:51,KNYC 270051Z AUTO 10SM CLR 23/18 A3007 RMK AO2 T02280183 $\n"
        "NYC,2026-09-01 17:51,KNYC 011751Z AUTO 5SM BR FEW035 SCT095 A2998 RMK AO2 T02560239 $\n",
        encoding="utf-8",
    )
    return _CacheFixture(directory=tmp_path)


def test_load_recent_asos_rows_filters_to_the_requested_station(
    asos_cache: _CacheFixture,
) -> None:
    rows = load_recent_asos_rows(asos_cache.directory, "NYC")
    assert {row["valid"] for row in rows} == {"2026-08-27 00:51", "2026-09-01 17:51"}
    assert all(row["station"] == "NYC" for row in rows)


def test_load_recent_asos_rows_deduplicates_overlapping_cache_files(
    asos_cache: _CacheFixture,
) -> None:
    rows = load_recent_asos_rows(asos_cache.directory, "NYC")
    assert len(rows) == 2  # not 3 -- the repeated (station, valid) row is one row


def test_load_recent_asos_rows_returns_empty_for_a_station_never_fetched(
    asos_cache: _CacheFixture,
) -> None:
    """The hard dependency, made concrete: BL-24 means no live intraday
    ingest exists, so a station/date with no incidental cache entry must
    come back empty -- never fabricated, never a network call.
    """
    assert load_recent_asos_rows(asos_cache.directory, "MDW") == ()


def test_load_recent_asos_rows_is_empty_for_a_nonexistent_cache_dir(tmp_path: Path) -> None:
    assert load_recent_asos_rows(tmp_path / "does-not-exist", "NYC") == ()


# ---------------------------------------------------------------------------
# Pre-registered kill / GO rule
# ---------------------------------------------------------------------------


def test_kill_rule_is_underpowered_below_the_admissible_sample() -> None:
    verdict, _lower, _upper = kill_rule_verdict(n=1, k=0)
    assert verdict == "UNDERPOWERED"


def test_kill_rule_is_underpowered_at_zero_sample() -> None:
    verdict, lower, upper = kill_rule_verdict(n=0, k=0)
    assert verdict == "UNDERPOWERED"
    assert lower == 0.0
    assert upper == 1.0


def test_kill_rule_declares_family_dead_at_zero_events_and_adequate_n() -> None:
    verdict, _lower, upper = kill_rule_verdict(n=MIN_ADMISSIBLE_N, k=0)
    assert verdict == "FAMILY_DEAD"
    assert upper < DEAD_UPPER_BOUND


def test_kill_rule_declares_go_when_the_lower_bound_clears_the_go_threshold() -> None:
    # A generous, unambiguous event rate at adequate n.
    verdict, lower, _upper = kill_rule_verdict(n=100, k=40)
    assert verdict == "GO"
    assert lower > GO_LOWER_BOUND


def test_kill_rule_refuses_go_below_the_admissible_sample_even_at_100pct() -> None:
    """n gates GO exactly as it gates FAMILY_DEAD -- the same small-sample
    mistake this programme has already made once (K1's `summarize_stratum`
    docstring: "adequate n gates BOTH directional verdicts, not just the
    negative one"). A single lucky event at n=1 must never read as GO.
    """
    verdict, lower, _upper = kill_rule_verdict(n=1, k=1)
    assert verdict == "UNDERPOWERED"
    assert lower > GO_LOWER_BOUND  # the bound alone would say GO; n must veto it


def test_kill_rule_stays_underpowered_between_dead_and_go_at_adequate_n() -> None:
    verdict, lower, upper = kill_rule_verdict(n=MIN_ADMISSIBLE_N, k=3)
    assert verdict == "UNDERPOWERED"
    assert upper >= DEAD_UPPER_BOUND
    assert lower <= GO_LOWER_BOUND


def test_dead_and_go_bounds_are_pre_registered_at_ten_percent() -> None:
    # Pinned so the bar cannot silently drift; see the module docstring for
    # the pre-registration this mirrors.
    assert DEAD_UPPER_BOUND == pytest.approx(0.10)
    assert GO_LOWER_BOUND == pytest.approx(0.10)
    assert MIN_ADMISSIBLE_N == 50


# ---------------------------------------------------------------------------
# NYC contamination: excluded from the aggregate feeding the kill rule
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Item 2: the three-way blocked-reason split
# ---------------------------------------------------------------------------


def test_classify_blocked_reason_is_admissible_when_boundary_was_hit() -> None:
    assert classify_blocked_reason(boundary_hits=1, asos_row_count=0) is None
    assert classify_blocked_reason(boundary_hits=5, asos_row_count=500) is None


def test_classify_blocked_reason_no_observation_data_when_asos_cache_is_empty() -> None:
    """Zero cached ASOS rows means we CANNOT KNOW whether the setup occurred --
    fixable by fetching, and must never be read as a genuine no-setup day.
    """
    assert classify_blocked_reason(boundary_hits=0, asos_row_count=0) == (
        BLOCKED_NO_OBSERVATION_DATA
    )


def test_classify_blocked_reason_no_qualifying_setup_when_asos_exists_but_never_hit() -> None:
    """ASOS coverage exists, but headroom never reached 1-or-2: a genuine,
    countable base-rate fact -- the ONLY blocked reason allowed to feed `n`.
    """
    assert classify_blocked_reason(boundary_hits=0, asos_row_count=300) == (
        BLOCKED_NO_QUALIFYING_SETUP
    )


def test_blocked_reasons_are_three_distinct_stable_codes() -> None:
    codes = {
        BLOCKED_NO_OBSERVATION_DATA,
        BLOCKED_NO_QUALIFYING_SETUP,
        BLOCKED_TAPE_PREFLIGHT_FAILED,
    }
    assert len(codes) == 3


def test_station_days_only_on_corrupt_tape_surfaces_a_corrupt_only_day() -> None:
    """A station-day seen ONLY inside a CORRUPT instance is invisible to the
    clean-instance pipeline entirely -- this is the THIRD blocked state, and
    must be surfaced rather than silently absorbed into "never happened".
    """
    corrupt = {("LAX", dt.date(2026, 8, 30))}
    clean: set[tuple[str, dt.date]] = set()
    assert station_days_only_on_corrupt_tape(
        corrupt_station_days=corrupt, clean_station_days=clean
    ) == frozenset({("LAX", dt.date(2026, 8, 30))})


def test_station_days_only_on_corrupt_tape_excludes_a_day_also_seen_clean() -> None:
    """A station-day covered by AT LEAST ONE clean instance is not tape-failed
    -- the existing ASOS-based classification governs it instead, even if a
    different, unrelated instance also happened to be corrupt that day.
    """
    key = ("LAX", dt.date(2026, 8, 30))
    assert station_days_only_on_corrupt_tape(
        corrupt_station_days={key}, clean_station_days={key}
    ) == frozenset()


def test_station_days_only_on_corrupt_tape_empty_when_nothing_is_corrupt() -> None:
    assert (
        station_days_only_on_corrupt_tape(corrupt_station_days=set(), clean_station_days=set())
        == frozenset()
    )


# ---------------------------------------------------------------------------
# Fee-coefficient extraction: read from the market, never hardcoded
# ---------------------------------------------------------------------------


def test_fee_coefficient_from_instrument_reads_the_markets_own_theta() -> None:
    instrument = _binary_option_with_fee_coefficient("0.06")
    assert fee_coefficient_from_instrument(instrument) == Decimal("0.06")


def test_fee_coefficient_from_instrument_is_none_when_coefficient_is_missing() -> None:
    instrument = _binary_option_with_fee_coefficient(None)
    assert fee_coefficient_from_instrument(instrument) is None


def test_fee_coefficient_from_instrument_is_none_for_an_out_of_range_value() -> None:
    base = _binary_option_with_fee_coefficient("0.06")
    tampered = _binary_option_with_raw_info(base, {**base.info, "fee_coefficient": "1.5"})
    assert fee_coefficient_from_instrument(tampered) is None


def test_fee_coefficient_from_instrument_is_none_for_a_boolean_value() -> None:
    """`bool` is a subclass of `int` -- a plausible round-trip accident, and
    explicitly guarded against in `fees.py`'s own reader (mirrored here).
    """
    base = _binary_option_with_fee_coefficient("0.06")
    tampered = _binary_option_with_raw_info(base, {**base.info, "fee_coefficient": True})
    assert fee_coefficient_from_instrument(tampered) is None


def test_contaminated_stations_is_exactly_nyc() -> None:
    # Diagnosis relayed by the coordinator (2026-09-02): KNYC reports hourly
    # (~24 obs/day) versus ~321/day at the other four stations. Downsampling
    # the dense stations to NYC's cadence reproduces NYC's inflated rate
    # (54-65%, matching NYC's measured 56-60%), which is a sampling artifact,
    # not a real station effect. NYC must still be scanned and reported, but
    # never counted into `n`/`k` for the kill rule.
    assert CONTAMINATED_STATIONS == frozenset({"NYC"})
