"""Unit tests for K1-on-Kalshi -- the large-sample PRIOR for the cheap-ask family.

Everything exercised here is PURE and FIXTURE-FED. The test gate runs with OS
egress blocked (`scripts/ci/run_tests_no_egress.sh`), so not one assertion in
this file may reach the network: the Kalshi responses under
`tests/fixtures/kalshi/` were captured from the real public API during
development and are replayed byte-for-byte.

The load-bearing test in this file is
:func:`test_stratum_math_is_k1s_own_function_object` and its siblings. K1-on-
Kalshi exists ONLY to be directly comparable to K1 on our own tape; if the
statistics were forked, the comparison would be meaningless. So the tests do
not merely check that the numbers look right -- they check that the numbers
come out of K1's own function objects, for identical inputs.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

FIXTURES = REPO_ROOT / "tests/fixtures/kalshi"

import k1_cheap_open_settlement as k1
import k1_kalshi_prior as kp


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Ticker parsing -- `SERIES-YYMMMDD-Bxx.x` and `-Txx`, legacy and modern
# ---------------------------------------------------------------------------


def test_parses_a_modern_between_bucket_ticker() -> None:
    facts = kp.parse_ticker("KXHIGHNY-26SEP01-B89.5")
    assert facts is not None
    assert facts.series == "KXHIGHNY"
    assert facts.raw_series == "KXHIGHNY"
    assert facts.climate_day == dt.date(2026, 9, 1)
    assert facts.bucket_kind == "BETWEEN"
    assert facts.strike == Decimal("89.5")


def test_parses_a_modern_tail_ticker() -> None:
    facts = kp.parse_ticker("KXHIGHNY-26SEP01-T90")
    assert facts is not None
    assert facts.bucket_kind == "TAIL"
    assert facts.strike == Decimal(90)
    assert facts.climate_day == dt.date(2026, 9, 1)


def test_parses_the_legacy_unprefixed_series_ticker() -> None:
    """2021 markets carry `HIGHNY-...`, not `KXHIGHNY-...`.

    They are returned by `series_ticker=KXHIGHNY`, so the crawler sees both
    spellings for one series and MUST fold them onto one station.
    """
    facts = kp.parse_ticker("HIGHNY-21AUG06-T86")
    assert facts is not None
    assert facts.raw_series == "HIGHNY"
    assert facts.series == "KXHIGHNY"
    assert facts.climate_day == dt.date(2021, 8, 6)
    assert facts.bucket_kind == "TAIL"
    assert facts.strike == Decimal(86)


def test_parses_the_sfo_series_whose_ticker_is_not_kxhighsf() -> None:
    facts = kp.parse_ticker("KXHIGHTSFO-26JUL02-T71")
    assert facts is not None
    assert facts.series == "KXHIGHTSFO"
    assert facts.climate_day == dt.date(2026, 7, 2)


@pytest.mark.parametrize(
    ("token", "month"),
    [
        ("JAN", 1),
        ("FEB", 2),
        ("MAR", 3),
        ("APR", 4),
        ("MAY", 5),
        ("JUN", 6),
        ("JUL", 7),
        ("AUG", 8),
        ("SEP", 9),
        ("OCT", 10),
        ("NOV", 11),
        ("DEC", 12),
    ],
)
def test_climate_day_decodes_every_month_token(token: str, month: int) -> None:
    facts = kp.parse_ticker(f"KXHIGHNY-24{token}15-T80")
    assert facts is not None
    assert facts.climate_day == dt.date(2024, month, 15)


@pytest.mark.parametrize(
    "ticker",
    [
        "",
        "KXHIGHNY",
        "KXHIGHNY-26SEP01",
        "KXHIGHNY-26XXX01-T90",
        "KXHIGHNY-26SEP32-T90",
        "KXHIGHNY-26SEP01-Q90",
        "KXHIGHNY-26SEP01-B",
        "KXHIGHNY-26SEP01-Tabc",
    ],
)
def test_refuses_to_invent_facts_for_a_malformed_ticker(ticker: str) -> None:
    """`None`, never a guess. A mis-parsed climate day silently mis-dates an era."""
    assert kp.parse_ticker(ticker) is None


def test_climate_day_from_ticker_is_the_ticker_not_the_close_time() -> None:
    """The market's own close/open times are venue clock; the ticker is the DAY."""
    assert kp.climate_day_from_ticker("KXHIGHNY-26JUL02-B99.5") == dt.date(2026, 7, 2)


# ---------------------------------------------------------------------------
# Era -- the one dimension K1 lacks, with the boundary PINNED
# ---------------------------------------------------------------------------


def test_the_era_boundary_is_pinned_to_2023_01_01() -> None:
    """A moved boundary silently re-pools across the regime break the evidence
    doc forbids, so the constant is asserted, not merely used."""
    assert kp.ERA_BOUNDARY == dt.date(2023, 1, 1)


@pytest.mark.parametrize(
    ("day", "era"),
    [
        (dt.date(2021, 8, 5), kp.ERA_SINGLE_THRESHOLD),
        (dt.date(2022, 12, 31), kp.ERA_SINGLE_THRESHOLD),
        (dt.date(2023, 1, 1), kp.ERA_EXHAUSTIVE_BUCKETS),
        (dt.date(2026, 9, 1), kp.ERA_EXHAUSTIVE_BUCKETS),
    ],
)
def test_era_classification_including_both_sides_of_the_boundary(day: dt.date, era: str) -> None:
    assert kp.era_for(day) == era


def test_the_two_eras_are_distinct_labels() -> None:
    assert kp.ERA_SINGLE_THRESHOLD != kp.ERA_EXHAUSTIVE_BUCKETS


# ---------------------------------------------------------------------------
# Ask at open -- from the FIRST D-1 candlestick's `yes_ask`
# ---------------------------------------------------------------------------


def test_ask_at_open_uses_the_first_hours_open_when_it_is_a_genuine_offer() -> None:
    """`open` is the earliest instant in the window, so it wins when genuine --
    the direct analogue of K1's `first_genuine_ask` ordering."""
    payload = {
        "candlesticks": [{"end_period_ts": 1, "yes_ask": {"open": "0.0300", "close": "0.0100"}}]
    }
    result = kp.ask_at_open(payload)
    assert result is not None
    assert result.price == Decimal("0.03")
    assert result.field == "open"


def test_ask_at_open_falls_back_to_close_when_the_hour_opens_with_no_offer() -> None:
    """`yes_ask.open == 1.00` is "nobody is offering", not a 100c offer.

    K1's `is_genuine_ask` rejects `price >= 1` for exactly this reason, so the
    earliest RECOVERABLE genuine ask in that hour is its close.
    """
    payload = _fixture("candles_evidence_doc_B99_5.json")
    result = kp.ask_at_open(payload)
    assert result is not None
    assert result.price == Decimal("0.24")
    assert result.field == "close"


def test_ask_at_open_reads_the_live_dollars_suffixed_schema_too() -> None:
    """Post-cutoff live candlesticks name the fields `*_dollars`.

    Two schemas, one meaning: a reader that handled only one would silently
    drop every market after 2026-07-04.
    """
    payload = _fixture("candles_live_modern.json")
    result = kp.ask_at_open(payload)
    assert result is not None
    assert result.price == Decimal("0.01")
    assert result.field == "close"


def test_ask_at_open_reads_the_legacy_2021_candlestick() -> None:
    payload = _fixture("candles_historical_legacy.json")
    result = kp.ask_at_open(payload)
    assert result is not None
    assert Decimal(0) < result.price < Decimal(1)


@pytest.mark.parametrize(
    "payload",
    [
        {"candlesticks": []},
        {"candlesticks": [{"end_period_ts": 1}]},
        {"candlesticks": [{"end_period_ts": 1, "yes_ask": {"open": "1.0000", "close": "1.0000"}}]},
        {"candlesticks": [{"end_period_ts": 1, "yes_ask": {"open": "0.0000", "close": "0.0000"}}]},
        {"candlesticks": [{"end_period_ts": 1, "yes_ask": {"open": None, "close": None}}]},
        {},
    ],
)
def test_ask_at_open_is_none_when_no_genuine_offer_is_recoverable(payload: dict) -> None:
    assert kp.ask_at_open(payload) is None


def test_ask_at_open_takes_the_FIRST_candlestick_when_several_are_returned() -> None:
    payload = {
        "candlesticks": [
            {"end_period_ts": 100, "yes_ask": {"open": "0.0500", "close": "0.0400"}},
            {"end_period_ts": 200, "yes_ask": {"open": "0.0100", "close": "0.0100"}},
        ]
    }
    result = kp.ask_at_open(payload)
    assert result is not None
    assert result.price == Decimal("0.05")
    assert result.end_period_ts == 100


def test_genuine_ask_price_agrees_with_k1s_own_predicate_on_the_price_legs() -> None:
    """The comparability guarantee for the price filter.

    Kalshi candlesticks carry NO size, so K1's `size > 0` leg cannot be
    replicated. The two PRICE legs must still agree exactly, for every price
    on the venue's 1c grid.
    """
    for cents in range(102):
        price = Decimal(cents) / Decimal(100)
        reference = k1.is_genuine_ask(
            k1.AskObservation(
                instrument_id="x",
                ts_event_ns=0,
                ts_init_ns=0,
                ask_price=price,
                ask_size=Decimal(1),
                source="test",
            )
        )
        assert kp.is_genuine_ask_price(price) is reference, price


# ---------------------------------------------------------------------------
# The comparability guarantee: K1's statistics, not a fork of them
# ---------------------------------------------------------------------------


def test_stratum_math_is_k1s_own_function_object() -> None:
    assert kp.summarize_stratum is k1.summarize_stratum
    assert kp.wilson_interval is k1.wilson_interval
    assert kp.break_even_probability is k1.break_even_probability
    assert kp.resolution_floor is k1.resolution_floor
    assert kp.required_n_to_discriminate is k1.required_n_to_discriminate
    assert kp.min_n_to_refute is k1.min_n_to_refute


def test_ask_strata_are_k1s_exact_strata() -> None:
    assert kp.ASK_STRATA == k1.ASK_STRATA
    assert kp.ASK_STRATA == (
        Decimal("0.01"),
        Decimal("0.02"),
        Decimal("0.03"),
        Decimal("0.05"),
    )


def test_kalshi_taker_theta_is_0_07() -> None:
    """The ONE constant that differs from K1 on our tape (0.06)."""
    assert kp.KALSHI_TAKER_THETA == Decimal("0.07")


@pytest.mark.parametrize(
    "threshold", [Decimal("0.01"), Decimal("0.02"), Decimal("0.03"), Decimal("0.05")]
)
def test_break_even_is_k1s_formula_evaluated_at_the_kalshi_taker_fee(
    threshold: Decimal,
) -> None:
    assert kp.break_even_for(threshold) == k1.break_even_probability(
        ask=threshold, theta=Decimal("0.07")
    )


def test_identical_inputs_give_k1_identical_stratum_numbers() -> None:
    """THE comparability test: same outcomes + same theta -> same numbers.

    Run through this module's entry point and through K1's directly; every
    field must match. If this ever fails, the two reports cannot be read side
    by side and the prior is worthless.
    """
    outcomes = [True] * 37 + [False] * 1163
    for threshold in kp.ASK_STRATA:
        mine = kp.summarize_stratum(
            threshold=threshold, outcomes=outcomes, theta=kp.KALSHI_TAKER_THETA
        )
        theirs = k1.summarize_stratum(threshold=threshold, outcomes=outcomes, theta=Decimal("0.07"))
        assert mine == theirs


def test_verdict_vocabulary_is_k1s_vocabulary() -> None:
    """The two reports must use the SAME words for the same states."""
    assert set(kp.VERDICT_VOCABULARY) == {
        "FAMILY SURVIVES",
        "FAMILY DEAD",
        "UNDERPOWERED -- INCONCLUSIVE",
    }
    dead = [
        k1.summarize_stratum(
            threshold=Decimal("0.01"), outcomes=[False] * 40_000, theta=Decimal("0.07")
        )
    ]
    assert kp.overall_verdict(dead) in kp.VERDICT_VOCABULARY
    assert kp.overall_verdict(dead) == k1._overall_verdict(dead)


# ---------------------------------------------------------------------------
# Station identity and the D-1 restriction (K1's population rule)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("series", "station"),
    [
        ("KXHIGHNY", "NYC"),
        ("KXHIGHMIA", "MIA"),
        ("KXHIGHCHI", "MDW"),
        ("KXHIGHLAX", "LAX"),
        ("KXHIGHTSFO", "SFO"),
    ],
)
def test_every_series_maps_to_the_registry_cli_location(series: str, station: str) -> None:
    assert kp.station_for_series(series) == station


def test_an_unknown_series_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(KeyError):
        kp.station_for_series("KXHIGHSF")


def test_series_offsets_come_from_the_breezy_registry_not_a_literal() -> None:
    from breezy.registry.sites import default_registry

    registry = default_registry()
    for series, station in kp.SERIES_TO_CLI_LOCATION.items():
        city = next(
            c for v, c in registry.pairs() if registry.settlement_site(v, c).cli_location == station
        )
        expected = registry.climate_day_window("polymarket_us", city).std_utc_offset_hours
        assert kp.offset_hours_for_series(series) == expected


def test_a_market_opening_on_d_minus_1_qualifies_under_k1s_own_rule() -> None:
    """14:00Z on D-1 is before local-standard midnight starting D, everywhere."""
    open_ts = int(dt.datetime(2026, 9, 1, 14, 0, tzinfo=dt.UTC).timestamp())
    assert kp.is_pre_climate_day_ts(open_ts, climate_day=dt.date(2026, 9, 2), series="KXHIGHNY")


def test_a_market_opening_after_local_midnight_does_not_qualify() -> None:
    """Same rule, other side: an intraday open is not a D-1 book."""
    open_ts = int(dt.datetime(2026, 9, 2, 14, 0, tzinfo=dt.UTC).timestamp())
    assert not kp.is_pre_climate_day_ts(open_ts, climate_day=dt.date(2026, 9, 2), series="KXHIGHNY")


def test_the_d1_boundary_is_k1s_climate_day_start() -> None:
    assert kp.climate_day_start_ns is k1.climate_day_start_ns


# ---------------------------------------------------------------------------
# Population assembly, from fixtures only
# ---------------------------------------------------------------------------


def _market(ticker: str, *, result: str, open_time: str) -> dict:
    return {"ticker": ticker, "result": result, "open_time": open_time, "status": "finalized"}


def test_build_observations_joins_result_to_ask_and_stamps_era_and_station() -> None:
    markets = [_market("KXHIGHNY-26JUL02-B99.5", result="yes", open_time="2026-07-01T14:00:00Z")]
    candles = {"KXHIGHNY-26JUL02-B99.5": _fixture("candles_evidence_doc_B99_5.json")}
    observations, ledger = kp.build_observations(markets=markets, candles=candles)
    assert len(observations) == 1
    obs = observations[0]
    assert obs.station == "NYC"
    assert obs.climate_day == dt.date(2026, 7, 2)
    assert obs.era == kp.ERA_EXHAUSTIVE_BUCKETS
    assert obs.ask == Decimal("0.24")
    assert obs.settled_yes is True
    assert ledger.no_candlestick == 0


def test_settlement_truth_is_the_venue_result_field_never_re_derived() -> None:
    markets = [
        _market("KXHIGHNY-26JUL02-B99.5", result="yes", open_time="2026-07-01T14:00:00Z"),
        _market("KXHIGHNY-26JUL02-T99", result="no", open_time="2026-07-01T14:00:00Z"),
    ]
    candles = {
        "KXHIGHNY-26JUL02-B99.5": _fixture("candles_evidence_doc_B99_5.json"),
        "KXHIGHNY-26JUL02-T99": _fixture("candles_evidence_doc_B99_5.json"),
    }
    observations, _ = kp.build_observations(markets=markets, candles=candles)
    assert [o.settled_yes for o in observations] == [True, False]


@pytest.mark.parametrize(
    ("result", "field"),
    [
        ("", "unsettled"),
        ("void", "voided"),
        (None, "unsettled"),
    ],
)
def test_a_market_without_a_binary_result_is_excluded_and_counted(
    result: object, field: str
) -> None:
    markets = [
        {
            "ticker": "KXHIGHNY-26JUL02-B99.5",
            "result": result,
            "open_time": "2026-07-01T14:00:00Z",
        }
    ]
    candles = {"KXHIGHNY-26JUL02-B99.5": _fixture("candles_evidence_doc_B99_5.json")}
    observations, ledger = kp.build_observations(markets=markets, candles=candles)
    assert observations == []
    assert getattr(ledger, field) == 1


def test_a_market_with_no_candlestick_is_excluded_and_counted() -> None:
    markets = [_market("KXHIGHNY-26JUL02-B99.5", result="yes", open_time="2026-07-01T14:00:00Z")]
    observations, ledger = kp.build_observations(markets=markets, candles={})
    assert observations == []
    assert ledger.no_candlestick == 1


def test_a_market_that_opened_intraday_is_excluded_and_counted() -> None:
    markets = [_market("KXHIGHNY-26JUL02-B99.5", result="yes", open_time="2026-07-02T14:00:00Z")]
    candles = {"KXHIGHNY-26JUL02-B99.5": _fixture("candles_evidence_doc_B99_5.json")}
    observations, ledger = kp.build_observations(markets=markets, candles=candles)
    assert observations == []
    assert ledger.not_pre_climate_day == 1


def test_an_unparseable_ticker_is_excluded_and_counted() -> None:
    markets = [_market("NOTAWEATHERMARKET", result="yes", open_time="2026-07-01T14:00:00Z")]
    observations, ledger = kp.build_observations(markets=markets, candles={})
    assert observations == []
    assert ledger.unparseable_ticker == 1


def _candle_for(market: dict, *, ask: str = "0.2400") -> dict:
    """A first-hour candlestick anchored to THIS market's own open."""
    open_ts = int(dt.datetime.fromisoformat(market["open_time"]).timestamp())
    return {
        "candlesticks": [
            {"end_period_ts": open_ts + 3600, "yes_ask": {"open": "1.0000", "close": ask}}
        ]
    }


def test_the_real_fixture_page_of_markets_builds_without_error() -> None:
    page = _fixture("historical_markets_KXHIGHNY_modern.json")
    candles = {m["ticker"]: _candle_for(m) for m in page["markets"]}
    observations, _ledger = kp.build_observations(markets=page["markets"], candles=candles)
    assert len(observations) == len(page["markets"])
    assert all(o.era == kp.ERA_EXHAUSTIVE_BUCKETS for o in observations)


def test_a_candlestick_from_the_wrong_climate_day_is_excluded_not_admitted() -> None:
    """The same real page, but every market handed the SAME candlestick.

    Two of the eight markets are for climate day 2026-07-01, whose local
    standard midnight (2026-07-01T05:00Z) precedes that candlestick's
    2026-07-01T15:00Z close. They are intraday for their own day and must be
    excluded -- if this ever admits all eight again, the observation-instant
    rule has been lost.
    """
    page = _fixture("historical_markets_KXHIGHNY_modern.json")
    candles = {m["ticker"]: _fixture("candles_evidence_doc_B99_5.json") for m in page["markets"]}
    observations, ledger = kp.build_observations(markets=page["markets"], candles=candles)
    assert len(observations) == 6
    assert ledger.observation_not_pre_climate_day == 2


def test_the_legacy_fixture_page_lands_in_the_single_threshold_era() -> None:
    page = _fixture("historical_markets_KXHIGHNY_legacy.json")
    candles = {m["ticker"]: _candle_for(m, ask="0.0300") for m in page["markets"]}
    observations, _ = kp.build_observations(markets=page["markets"], candles=candles)
    assert observations
    assert all(o.era == kp.ERA_SINGLE_THRESHOLD for o in observations)
    assert all(o.station == "NYC" for o in observations)


# ---------------------------------------------------------------------------
# Cache -- re-runs are offline and free, settled markets are never re-fetched
# ---------------------------------------------------------------------------


def test_cache_miss_then_hit_round_trips_the_raw_response(tmp_path: Path) -> None:
    cache = kp.CandleCache(tmp_path)
    assert cache.get("KXHIGHNY-26JUL02-B99.5") is None
    payload = _fixture("candles_evidence_doc_B99_5.json")
    cache.store("KXHIGHNY-26JUL02-B99.5", payload)
    assert cache.get("KXHIGHNY-26JUL02-B99.5") == payload


def test_a_reopened_cache_still_hits_so_reruns_are_offline(tmp_path: Path) -> None:
    payload = _fixture("candles_evidence_doc_B99_5.json")
    kp.CandleCache(tmp_path).store("KXHIGHNY-26JUL02-B99.5", payload)
    reopened = kp.CandleCache(tmp_path)
    assert reopened.get("KXHIGHNY-26JUL02-B99.5") == payload
    assert "KXHIGHNY-26JUL02-B99.5" in reopened.tickers()


def test_the_cache_records_a_market_that_genuinely_has_no_candlestick(tmp_path: Path) -> None:
    """A negative result must be cached too, or every re-run re-fetches it."""
    cache = kp.CandleCache(tmp_path)
    cache.store("KXHIGHNY-26JUL02-T99", {"candlesticks": []})
    assert cache.get("KXHIGHNY-26JUL02-T99") == {"candlesticks": []}
    assert "KXHIGHNY-26JUL02-T99" in cache.tickers()


def test_fetch_missing_never_calls_the_network_for_a_cached_ticker(tmp_path: Path) -> None:
    """The resumability guarantee, asserted rather than assumed."""
    cache = kp.CandleCache(tmp_path)
    cache.store("A", {"candlesticks": []})
    calls: list[str] = []

    def fetcher(ticker: str) -> dict:
        calls.append(ticker)
        return {"candlesticks": []}

    fetched = kp.fetch_missing_candles(
        tickers=["A", "B", "A"], cache=cache, fetch=fetcher, progress=None
    )
    assert calls == ["B"]
    assert set(fetched) == {"A", "B"}


def test_a_corrupt_cache_line_is_skipped_not_fatal(tmp_path: Path) -> None:
    """An interrupted append leaves a partial last line. Losing one cached
    market is recoverable; refusing to start is not."""
    cache = kp.CandleCache(tmp_path)
    cache.store("A", {"candlesticks": []})
    cache.path.write_text(
        cache.path.read_text(encoding="utf-8") + '{"ticker": "B", "resp', encoding="utf-8"
    )
    assert kp.CandleCache(tmp_path).tickers() == {"A"}


# ---------------------------------------------------------------------------
# Egress: the module is import-safe under a blocked network
# ---------------------------------------------------------------------------


def test_importing_the_module_opens_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Import-time I/O would make the test gate fail under `--unshare-net`."""
    import urllib.request

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("the module performed network I/O at import time")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    monkeypatch.setattr("socket.create_connection", explode)
    importlib.reload(kp)


def test_no_http_client_object_exists_at_module_scope() -> None:
    for name, value in vars(kp).items():
        assert not isinstance(value, kp.KalshiHttp), f"{name} is a live client"


def test_the_script_imports_nothing_from_the_execution_path() -> None:
    """A research script must not touch the order path or the NO-SEND firewall."""
    source = (REPO_ROOT / "scripts/analysis/k1_kalshi_prior.py").read_text(encoding="utf-8")
    for forbidden in ("polymarket_us.exec", "exec.client", "OrderFactory", "submit_order"):
        assert forbidden not in source


# ---------------------------------------------------------------------------
# Report -- K1's shape, plus the mandatory prior disclaimer
# ---------------------------------------------------------------------------


def _tiny_report() -> str:
    markets = [_market("KXHIGHNY-26JUL02-B99.5", result="yes", open_time="2026-07-01T14:00:00Z")]
    candles = {"KXHIGHNY-26JUL02-B99.5": _fixture("candles_evidence_doc_B99_5.json")}
    observations, ledger = kp.build_observations(markets=markets, candles=candles)
    return kp.render_report(
        observations=observations,
        ledger=ledger,
        crawl=kp.CrawlSummary(
            series_seen=("KXHIGHNY",),
            markets_listed=1,
            candles_cached=1,
            candles_fetched=0,
            fetch_failures=(),
            complete=True,
        ),
        generated_at=dt.datetime(2026, 9, 2, tzinfo=dt.UTC),
    )


def test_report_carries_k1s_six_sections_and_measured_population() -> None:
    report = _tiny_report()
    for heading in (
        "## 1.",
        "## 2.",
        "## 3.",
        "## 4.",
        "## 5.",
        "## 6. VERDICT",
    ):
        assert heading in report
    assert "MEASURED POPULATION" in report


def test_report_states_it_is_a_kalshi_prior_and_not_a_polymarket_measurement() -> None:
    """MANDATORY. The evidence doc's binding caveat 1, in the artifact itself."""
    report = _tiny_report()
    assert "Kalshi" in report
    assert "Polymarket.us" in report
    lowered = report.lower()
    assert "prior" in lowered
    assert "cannot estimate" in lowered


def test_report_stratifies_by_era_and_by_station() -> None:
    report = _tiny_report()
    assert kp.ERA_EXHAUSTIVE_BUCKETS in report
    assert kp.ERA_SINGLE_THRESHOLD in report
    assert "NYC" in report


def test_report_labels_the_pooled_across_era_table_as_forbidden_to_read_alone() -> None:
    """A pooled rate across the regime break is the one result the evidence doc
    forbids; it may appear only alongside the stratified tables, so labelled."""
    report = _tiny_report()
    assert "POOLED" in report
    assert "INDICATIVE ONLY" in report


def test_report_marks_a_partial_crawl_as_partial() -> None:
    markets = [_market("KXHIGHNY-26JUL02-B99.5", result="yes", open_time="2026-07-01T14:00:00Z")]
    candles = {"KXHIGHNY-26JUL02-B99.5": _fixture("candles_evidence_doc_B99_5.json")}
    observations, ledger = kp.build_observations(markets=markets, candles=candles)
    report = kp.render_report(
        observations=observations,
        ledger=ledger,
        crawl=kp.CrawlSummary(
            series_seen=("KXHIGHNY",),
            markets_listed=29_403,
            candles_cached=10,
            candles_fetched=10,
            fetch_failures=(),
            complete=False,
        ),
        generated_at=dt.datetime(2026, 9, 2, tzinfo=dt.UTC),
    )
    assert "PARTIAL" in report


def test_report_names_the_ask_at_open_definition_and_its_divergence_from_k1() -> None:
    report = _tiny_report()
    assert "yes_ask" in report
    assert "size" in report.lower()


# ---------------------------------------------------------------------------
# Ticker shapes found in the real crawl that a naive parser silently drops
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ticker", "strike", "kind"),
    [
        ("HIGHCHI-24JAN16-T-1", Decimal(-1), "TAIL"),
        ("HIGHCHI-24JAN16-B-0.5", Decimal("-0.5"), "BETWEEN"),
        ("HIGHCHI-22DEC23-T-3", Decimal(-3), "TAIL"),
    ],
)
def test_parses_a_negative_strike(ticker: str, strike: Decimal, kind: str) -> None:
    """Chicago in January genuinely trades sub-zero highs.

    Found in the real crawl: 12 settled `HIGHCHI` markets carry a NEGATIVE
    strike. A parser that requires `\\d+` drops them silently -- and it drops
    them non-randomly, from the coldest days of the coldest station, which is
    exactly the kind of selective loss that biases a base rate.
    """
    facts = kp.parse_ticker(ticker)
    assert facts is not None
    assert facts.strike == strike
    assert facts.bucket_kind == kind
    assert facts.series == "KXHIGHCHI"


@pytest.mark.parametrize(
    "ticker",
    ["HIGHMIA--23MAY11-T89", "HIGHCHI-2-24FEB28-B54.5"],
)
def test_a_relisted_variant_ticker_is_refused_but_named_separately(ticker: str) -> None:
    """Also found in the real crawl: re-listed duplicates of an existing day.

    `HIGHMIA--23MAY11` (double hyphen) and `HIGHCHI-2-24FEB28` (a `-2` re-list
    segment) name the SAME bucket as a market already in the sample. Admitting
    them would double-count an outcome; lumping them into "not a weather
    ticker" would hide that a real weather market was dropped. So they are
    refused AND counted under their own name.
    """
    assert kp.parse_ticker(ticker) is None
    assert kp.is_relisted_variant(ticker)


@pytest.mark.parametrize("ticker", ["KXHIGHNY-26SEP01-B89.5", "HIGHCHI-24JAN16-T-1", "GARBAGE"])
def test_a_normal_ticker_is_not_mistaken_for_a_relisted_variant(ticker: str) -> None:
    assert not kp.is_relisted_variant(ticker)


def test_a_relisted_variant_gets_its_own_ledger_line() -> None:
    markets = [_market("HIGHMIA--23MAY11-T89", result="yes", open_time="2023-05-10T14:00:00Z")]
    observations, ledger = kp.build_observations(markets=markets, candles={})
    assert observations == []
    assert ledger.relisted_variant == 1
    assert ledger.unparseable_ticker == 0


def test_a_scalar_settled_market_is_excluded_as_non_binary() -> None:
    """Found in the real crawl: `result == "scalar"` on two KXHIGHMIA markets."""
    markets = [
        {
            "ticker": "KXHIGHMIA-26APR11-B80.5",
            "result": "scalar",
            "open_time": "2026-04-10T14:00:00Z",
        }
    ]
    observations, ledger = kp.build_observations(markets=markets, candles={})
    assert observations == []
    assert ledger.voided == 1


# ---------------------------------------------------------------------------
# A permanent data gap is a RESULT, not a retry forever
# ---------------------------------------------------------------------------


def test_a_market_absent_from_both_endpoints_is_recorded_as_unavailable() -> None:
    """404 on historical AND live is DETERMINISTIC: the data does not exist.

    Returning `None` would leave it uncached, re-fetched on every run, and
    would pin the report at PARTIAL forever -- so a permanent gap is recorded
    as a gap. A transient failure still raises and stays uncached.
    """
    import urllib.error

    class AlwaysMissing(kp.KalshiHttp):
        def get_json(self, path: str, params=None):  # type: ignore[no-untyped-def]
            raise urllib.error.HTTPError(path, 404, "not found", {}, None)  # type: ignore[arg-type]

    payload = AlwaysMissing().first_hour_candlesticks(
        ticker="KXHIGHNY-26JUL02-T99",
        series="KXHIGHNY",
        open_ts=1_782_914_400,
        climate_day=dt.date(2026, 7, 2),
    )
    assert payload is not None
    assert payload["candlesticks"] == []
    assert kp.is_unavailable(payload)


def test_a_recorded_gap_is_counted_apart_from_a_market_that_merely_had_no_offer() -> None:
    """Two different findings: "the venue has no data" vs "nobody was offering"."""
    markets = [
        _market("KXHIGHNY-26JUL02-T99", result="no", open_time="2026-07-01T14:00:00Z"),
        _market("KXHIGHNY-26JUL02-T106", result="no", open_time="2026-07-01T14:00:00Z"),
    ]
    candles = {
        "KXHIGHNY-26JUL02-T99": kp.UNAVAILABLE_PAYLOAD,
        "KXHIGHNY-26JUL02-T106": {
            "candlesticks": [{"end_period_ts": 1, "yes_ask": {"open": "1.0", "close": "1.0"}}]
        },
    }
    observations, ledger = kp.build_observations(markets=markets, candles=candles)
    assert observations == []
    assert ledger.candlesticks_unavailable == 1
    assert ledger.no_genuine_ask == 1


def test_a_normal_empty_candlestick_response_is_not_mistaken_for_a_gap() -> None:
    assert not kp.is_unavailable({"candlesticks": []})
    assert not kp.is_unavailable({"candlesticks": [{"yes_ask": {"close": "0.03"}}]})


# ---------------------------------------------------------------------------
# The headline verdict must not come from the table the evidence doc forbids
# ---------------------------------------------------------------------------


def _strata(k: int, n: int) -> list:
    outcomes = [True] * k + [False] * (n - k)
    return [
        kp.summarize_stratum(threshold=t, outcomes=outcomes, theta=kp.KALSHI_TAKER_THETA)
        for t in kp.ASK_STRATA
    ]


def test_headline_verdict_is_a_conjunction_over_eras_not_a_pooled_rate() -> None:
    """A pooled rate across the regime break is forbidden as a FINDING, so the
    headline may not be computed from it. It is the conjunction of the two
    era verdicts, each computed by K1's own `_overall_verdict`."""
    dead = _strata(0, 40_000)
    alive = _strata(4_000, 40_000)
    assert kp.headline_verdict(
        {kp.ERA_SINGLE_THRESHOLD: dead, kp.ERA_EXHAUSTIVE_BUCKETS: dead}
    ) == ("FAMILY DEAD")
    assert (
        kp.headline_verdict({kp.ERA_SINGLE_THRESHOLD: dead, kp.ERA_EXHAUSTIVE_BUCKETS: alive})
        == "FAMILY SURVIVES"
    )


def test_one_dead_era_alone_does_not_kill_the_family_if_the_other_is_underpowered() -> None:
    """Refuting one regime is not refuting the family."""
    dead = _strata(0, 40_000)
    thin = _strata(0, 3)
    assert (
        kp.headline_verdict({kp.ERA_SINGLE_THRESHOLD: thin, kp.ERA_EXHAUSTIVE_BUCKETS: dead})
        == "UNDERPOWERED -- INCONCLUSIVE"
    )


def test_an_era_with_no_observations_does_not_veto_the_other() -> None:
    """An era Kalshi simply did not run at a station is absence of data, not
    evidence -- it must not force the headline to UNDERPOWERED on its own."""
    dead = _strata(0, 40_000)
    empty = _strata(0, 0)
    assert (
        kp.headline_verdict({kp.ERA_SINGLE_THRESHOLD: empty, kp.ERA_EXHAUSTIVE_BUCKETS: dead})
        == "FAMILY DEAD"
    )


def test_headline_verdict_only_ever_speaks_k1s_vocabulary() -> None:
    for k, n in ((0, 0), (0, 5), (0, 40_000), (4_000, 40_000), (1, 40_000)):
        verdict = kp.headline_verdict(
            {kp.ERA_SINGLE_THRESHOLD: _strata(k, n), kp.ERA_EXHAUSTIVE_BUCKETS: _strata(k, n)}
        )
        assert verdict in kp.VERDICT_VOCABULARY


# ---------------------------------------------------------------------------
# Within-day dependence -- K1 carries this caveat, so must its Kalshi port
# ---------------------------------------------------------------------------


def test_report_states_that_buckets_within_a_station_day_are_not_independent() -> None:
    """In the exhaustive-bucket era exactly ONE of ~6 buckets settles YES per
    station-day, so observations inside a day are negatively correlated and
    the effective sample is smaller than n. K1's own report says so; a port
    that dropped the caveat would overstate its power."""
    report = _tiny_report()
    lowered = report.lower()
    assert "not independent" in lowered
    assert "station-day" in lowered


def test_report_counts_the_distinct_station_days_behind_the_sample() -> None:
    """n alone hides clustering; the station-day count exposes it."""
    report = _tiny_report()
    assert "station-days" in report.lower()


def test_distinct_station_days_counts_days_not_markets() -> None:
    observations = [
        kp.Observation(
            ticker=f"KXHIGHNY-26JUL02-B{i}.5",
            series="KXHIGHNY",
            station="NYC",
            climate_day=dt.date(2026, 7, 2),
            era=kp.ERA_EXHAUSTIVE_BUCKETS,
            bucket_kind="BETWEEN",
            strike=Decimal(f"{i}.5"),
            ask=Decimal("0.01"),
            ask_field="close",
            settled_yes=False,
        )
        for i in (80, 82, 84)
    ]
    assert kp.distinct_station_days(observations) == 1
    assert kp.distinct_station_days([]) == 0


# ---------------------------------------------------------------------------
# An UNDERPOWERED verdict must say WHICH kind of underpowered it is
# ---------------------------------------------------------------------------


def test_underpowered_reason_distinguishes_too_few_from_interval_straddles() -> None:
    """Two very different states share one word.

    `n` below `required_n_to_discriminate` means *collect more data*. `n` well
    ABOVE it, with the Wilson interval still straddling break-even, means the
    data is in and the answer is genuinely between the two hypotheses --
    blaming sample size there would send the reader to gather data that will
    not resolve it.
    """
    thin = kp.summarize_stratum(
        threshold=Decimal("0.01"), outcomes=[False] * 5, theta=kp.KALSHI_TAKER_THETA
    )
    assert kp.underpowered_reason([thin]) == kp.REASON_TOO_FEW

    straddling = kp.summarize_stratum(
        threshold=Decimal("0.02"),
        outcomes=[True] + [False] * 190,
        theta=kp.KALSHI_TAKER_THETA,
    )
    assert straddling.n > kp.required_n_to_discriminate()
    assert straddling.verdict == "UNDERPOWERED"
    assert kp.underpowered_reason([straddling]) == kp.REASON_STRADDLES

    assert kp.underpowered_reason([thin, straddling]) == kp.REASON_MIXED
    assert kp.underpowered_reason([]) == kp.REASON_TOO_FEW


def test_report_does_not_blame_sample_size_when_n_already_clears_the_requirement() -> None:
    """Regression: the first draft said "the largest cell is n = 685 against
    n = 96" under an UNDERPOWERED headline, which reads as a shortfall when
    685 is seven times the requirement."""
    observations = [
        kp.Observation(
            ticker=f"KXHIGHNY-26JUL{(i % 28) + 1:02d}-B{i}.5",
            series="KXHIGHNY",
            station="NYC",
            climate_day=dt.date(2026, 7, (i % 28) + 1),
            era=kp.ERA_EXHAUSTIVE_BUCKETS,
            bucket_kind="BETWEEN",
            strike=Decimal(i),
            ask=Decimal("0.02"),
            ask_field="close",
            settled_yes=i == 0,
        )
        for i in range(191)
    ]
    report = kp.render_report(
        observations=observations,
        ledger=kp.ExclusionLedger(),
        crawl=kp.CrawlSummary(
            series_seen=("KXHIGHNY",),
            markets_listed=191,
            candles_cached=191,
            candles_fetched=0,
            fetch_failures=(),
            complete=True,
        ),
        generated_at=dt.datetime(2026, 9, 2, tzinfo=dt.UTC),
    )
    assert "UNDERPOWERED -- INCONCLUSIVE" in report
    assert kp.REASON_STRADDLES in report
    assert "against n = 96" not in report


# ---------------------------------------------------------------------------
# K1's D-1 rule binds on the OBSERVATION instant, not on the market's open
# ---------------------------------------------------------------------------


def test_the_close_branch_observation_must_itself_precede_the_climate_day() -> None:
    """The `close` branch observes at the END of the first hour.

    A market that opened 30 minutes before local-standard midnight passes the
    `open_time` test, but its close-of-hour ask was standing 30 minutes INSIDE
    the climate day -- an intraday quote, which is exactly the population K1
    excludes ("buying a lottery whose draw has happened"). The rule must bind
    on the instant the price was observed.
    """
    # NYC standard midnight starting 2026-07-02 is 2026-07-02T05:00:00Z.
    open_ts = int(dt.datetime(2026, 7, 2, 4, 30, tzinfo=dt.UTC).timestamp())
    markets = [
        _market(
            "KXHIGHNY-26JUL02-B99.5",
            result="yes",
            open_time="2026-07-02T04:30:00Z",
        )
    ]
    candles = {
        "KXHIGHNY-26JUL02-B99.5": {
            "candlesticks": [
                {
                    "end_period_ts": open_ts + 3600,  # 05:30Z -- inside the day
                    "yes_ask": {"open": "1.0000", "close": "0.2400"},
                }
            ]
        }
    }
    observations, ledger = kp.build_observations(markets=markets, candles=candles)
    assert observations == []
    assert ledger.observation_not_pre_climate_day == 1


def test_the_open_branch_of_that_same_market_still_qualifies() -> None:
    """The open-instant observation DID precede the day, so it is admitted --
    the rule excludes the late observation, not the market."""
    open_ts = int(dt.datetime(2026, 7, 2, 4, 30, tzinfo=dt.UTC).timestamp())
    markets = [_market("KXHIGHNY-26JUL02-B99.5", result="yes", open_time="2026-07-02T04:30:00Z")]
    candles = {
        "KXHIGHNY-26JUL02-B99.5": {
            "candlesticks": [
                {"end_period_ts": open_ts + 3600, "yes_ask": {"open": "0.2400", "close": "0.9900"}}
            ]
        }
    }
    observations, _ = kp.build_observations(markets=markets, candles=candles)
    assert len(observations) == 1
    assert observations[0].ask_field == "open"
    assert observations[0].ask == Decimal("0.24")


def test_the_normal_14z_market_is_untouched_by_the_observation_instant_rule() -> None:
    """A 14:00Z D-1 open closes its first hour at 15:00Z D-1 -- still ~14 hours
    before the earliest local-standard midnight of any of the five stations."""
    markets = [_market("KXHIGHNY-26JUL02-B99.5", result="yes", open_time="2026-07-01T14:00:00Z")]
    candles = {"KXHIGHNY-26JUL02-B99.5": _fixture("candles_evidence_doc_B99_5.json")}
    observations, ledger = kp.build_observations(markets=markets, candles=candles)
    assert len(observations) == 1
    assert ledger.observation_not_pre_climate_day == 0
