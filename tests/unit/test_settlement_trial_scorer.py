"""RED-first tests for the 6c settlement scorer
(`docs/plans/SCORER_TALLY_BCA_BRIEF_2026-09-04.md`, converged review BINDING
over the draft). Pure fixtures throughout -- no catalog, no clock, no
Nautilus.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal
from typing import Any

import pytest

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.settlement.trial_scorer import (
    FilledTrial,
    ScoredTrial,
    ScoreRefusal,
    score_trial,
    score_trials,
)

_BASE_NS = int(dt.datetime(2026, 9, 1, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_SHA = hashlib.sha256(b"settlement-trial-scorer-test").hexdigest()
_STATION = "LAX"
_DAY = dt.date(2026, 8, 31)
_DAY_ISO = _DAY.isoformat()
_SEVEN_DAYS_NS = 7 * 24 * 60 * 60 * 1_000_000_000


def _record(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": _STATION,
        "climate_day": _DAY,
        "tmax_f": 79,
        "tmin_f": 63,
        "tavg_f": 71,
        "tavg_flag": None,
        "tmax_flag": None,
        "tmin_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KLAX",
        "issuance_time_ns": _BASE_NS - 240_000_000_000,
        "retrieved_at_ns": _BASE_NS,
        "parser_version": "test",
        "registry_version": "test",
        "raw_sha256": _SHA,
        "source_channel": "iem_afos_forecast",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": _BASE_NS,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def _bucket(*, lower_f: int | None, upper_f: int | None) -> WeatherBucketFacts:
    return WeatherBucketFacts(
        settlement_station=_STATION,
        climate_day=_DAY,
        measure=Measure.HIGH,
        lower_f=lower_f,
        upper_f=upper_f,
    )


def _trial(**overrides: Any) -> FilledTrial:
    kwargs: dict[str, Any] = {
        "trial_id": "current_rung_hold/trial/LAX/2026-08-31",
        "station": _STATION,
        "climate_day": _DAY_ISO,
        "instrument_id": "LAX-2026-08-31-gte78lt80f",
        "bucket": _bucket(lower_f=78, upper_f=79),
        "fill_px": Decimal("0.42"),
        "fee": Decimal("0.01"),
        "qty": Decimal(10),
        "filled_at_ns": _BASE_NS - 3_600_000_000_000,
        "entry_ask": Decimal("0.40"),
        "scheduled_release_at_ns": _BASE_NS - 3_600_000_000_000,
    }
    kwargs.update(overrides)
    return FilledTrial(**kwargs)


def test_a_final_print_inside_the_rung_scores_held_with_pnl_one_minus_price_minus_fee() -> None:
    trial = _trial()
    result = score_trial(trial, _record(tmax_f=79), now_ns=_BASE_NS)
    assert isinstance(result, ScoredTrial)
    assert result.held is True
    assert result.pnl == Decimal(1) - Decimal("0.42") - Decimal("0.01")
    assert result.settlement_basis == "nws_final"
    assert result.excluded_reason is None


def test_a_final_print_outside_the_rung_scores_lost_with_pnl_negative_price_minus_fee() -> None:
    trial = _trial()
    result = score_trial(trial, _record(tmax_f=85), now_ns=_BASE_NS)
    assert isinstance(result, ScoredTrial)
    assert result.held is False
    assert result.pnl == Decimal(0) - Decimal("0.42") - Decimal("0.01")


def test_a_preliminary_only_day_is_refused_not_scored() -> None:
    trial = _trial()
    result = score_trial(trial, _record(is_final=False), now_ns=_BASE_NS)
    assert isinstance(result, ScoreRefusal)
    assert result.reason == "preliminary_only"


def test_a_superseded_final_is_refused_not_scored() -> None:
    trial = _trial()
    result = score_trial(trial, _record(is_superseded=True), now_ns=_BASE_NS)
    assert isinstance(result, ScoreRefusal)
    assert result.reason == "superseded"


def test_a_sentinel_tmax_on_a_final_record_is_refused() -> None:
    trial = _trial()
    result = score_trial(
        trial, _record(tmax_f=None, tmax_flag="M"), now_ns=_BASE_NS
    )
    assert isinstance(result, ScoreRefusal)
    assert result.reason == "sentinel_tmax"


def test_a_correction_after_scoring_appends_a_re_score_and_keeps_the_prior_row() -> None:
    trial = _trial()
    first_sha = hashlib.sha256(b"first-final").hexdigest()
    second_sha = hashlib.sha256(b"corrected-final").hexdigest()

    first = score_trial(
        trial, _record(tmax_f=79, raw_sha256=first_sha), now_ns=_BASE_NS, score_seq=0
    )
    second = score_trial(
        trial,
        _record(tmax_f=85, raw_sha256=second_sha, revision_seq=2),
        now_ns=_BASE_NS + 1,
        score_seq=1,
    )
    assert isinstance(first, ScoredTrial) and isinstance(second, ScoredTrial)
    assert first.raw_sha256 != second.raw_sha256
    assert first.score_seq == 0
    assert second.score_seq == 1
    assert first.held != second.held


def test_a_fill_whose_rung_cannot_be_resolved_is_refused() -> None:
    trial = _trial(bucket=None)
    result = score_trial(trial, _record(), now_ns=_BASE_NS)
    assert isinstance(result, ScoreRefusal)
    assert result.reason == "rung_unresolved"


def test_a_record_for_a_different_station_day_is_refused() -> None:
    trial = _trial()
    other_day_record = _record(climate_day=dt.date(2026, 9, 1))
    result = score_trial(trial, other_day_record, now_ns=_BASE_NS)
    assert isinstance(result, ScoreRefusal)
    assert result.reason == "station_day_mismatch"


def test_pnl_is_decimal_and_never_float() -> None:
    trial = _trial()
    result = score_trial(trial, _record(tmax_f=79), now_ns=_BASE_NS)
    assert isinstance(result, ScoredTrial)
    assert isinstance(result.pnl, Decimal)
    assert not isinstance(result.pnl, float)


def test_scored_plus_refused_always_equals_the_input_count() -> None:
    trial = _trial()
    pairs = [
        (trial, _record(tmax_f=79)),
        (trial, _record(is_final=False)),
        (trial, None),
    ]
    scored, refused = score_trials(pairs, now_ns=_BASE_NS)
    assert len(scored) + len(refused) == len(pairs)


def test_containment_uses_weather_bucket_facts_on_both_closed_boundaries() -> None:
    trial = _trial(bucket=_bucket(lower_f=78, upper_f=79))
    lower_edge = score_trial(trial, _record(tmax_f=78), now_ns=_BASE_NS)
    upper_edge = score_trial(trial, _record(tmax_f=79), now_ns=_BASE_NS)
    assert isinstance(lower_edge, ScoredTrial) and lower_edge.held is True
    assert isinstance(upper_edge, ScoredTrial) and upper_edge.held is True


def test_open_tail_rungs_score_on_one_bound() -> None:
    trial = _trial(bucket=_bucket(lower_f=80, upper_f=None))
    below = score_trial(trial, _record(tmax_f=79), now_ns=_BASE_NS)
    at_bound = score_trial(trial, _record(tmax_f=80), now_ns=_BASE_NS)
    assert isinstance(below, ScoredTrial) and below.held is False
    assert isinstance(at_bound, ScoredTrial) and at_bound.held is True


def test_the_scorer_rejects_a_fee_inclusive_realized_pnl_input() -> None:
    with pytest.raises(TypeError):
        FilledTrial(
            trial_id="t",
            station=_STATION,
            climate_day=_DAY_ISO,
            instrument_id="i",
            bucket=_bucket(lower_f=78, upper_f=79),
            fill_px=Decimal("0.42"),
            fee=Decimal("0.01"),
            qty=Decimal(10),
            filled_at_ns=_BASE_NS,
            entry_ask=Decimal("0.40"),
            scheduled_release_at_ns=_BASE_NS,
            realized_pnl=Decimal(1),  # type: ignore[call-arg]
        )


def test_zero_trials_returns_empty_scored_and_empty_refused() -> None:
    scored, refused = score_trials([], now_ns=_BASE_NS)
    assert scored == ()
    assert refused == ()


def test_fee_is_treated_as_per_contract_never_multiplied_by_qty() -> None:
    trial = _trial(qty=Decimal(100), fee=Decimal("0.01"))
    result = score_trial(trial, _record(tmax_f=79), now_ns=_BASE_NS)
    assert isinstance(result, ScoredTrial)
    # pnl subtracts `fee` once, never `fee * qty` -- a per-contract fee
    # multiplied by a 100-lot qty would produce a wildly different number.
    assert result.pnl == Decimal(1) - trial.fill_px - trial.fee


def test_slippage_is_fill_px_minus_entry_ask() -> None:
    trial = _trial(fill_px=Decimal("0.45"), entry_ask=Decimal("0.40"))
    result = score_trial(trial, _record(tmax_f=79), now_ns=_BASE_NS)
    assert isinstance(result, ScoredTrial)
    assert result.slippage == Decimal("0.05")


def test_venue_fallback_scores_only_after_seven_days_with_a_venue_reading() -> None:
    trial = _trial(
        scheduled_release_at_ns=_BASE_NS,
        venue_settlement_tmax_f=79,
    )
    too_early = score_trial(trial, None, now_ns=_BASE_NS + _SEVEN_DAYS_NS - 1)
    assert isinstance(too_early, ScoreRefusal)
    assert too_early.reason == "no_record"

    on_time = score_trial(trial, None, now_ns=_BASE_NS + _SEVEN_DAYS_NS)
    assert isinstance(on_time, ScoredTrial)
    assert on_time.settlement_basis == "venue_last_fair_price_fallback"
    assert on_time.excluded_reason == "venue_settled_without_nws"
    assert on_time.settlement_tmax_f == 79


def test_venue_fallback_never_fires_without_a_recorded_venue_reading() -> None:
    trial = _trial(scheduled_release_at_ns=_BASE_NS, venue_settlement_tmax_f=None)
    result = score_trial(trial, None, now_ns=_BASE_NS + _SEVEN_DAYS_NS + 1)
    assert isinstance(result, ScoreRefusal)
    assert result.reason == "no_record"
