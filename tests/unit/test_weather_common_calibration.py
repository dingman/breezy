"""Unit tests for the offline forecast-error model fit.

The load-bearing concern here is LOOKAHEAD BIAS: `ForecastErrorRecord.realized_high_f`
is the official climate observation, knowable only after its `target_date` has
settled. Fitting on records that overlap the evaluation window leaks the answer
into the predictor. The module documented that as a caller obligation with no
runtime enforcement; `train_end_exclusive` makes it enforceable.
"""

from __future__ import annotations

import datetime as dt

import pytest

from breezy.strategy.weather_common.calibration import ForecastErrorRecord, fit_error_model

BACKTEST_START = dt.date(2026, 8, 1)


def _record(target_date: dt.date, *, error_f: float = 1.0) -> ForecastErrorRecord:
    return ForecastErrorRecord(
        location_id="NYC",
        target_date=target_date,
        horizon_hours=24.0,
        forecast_high_f=80.0,
        realized_high_f=80.0 + error_f,
    )


def test_a_clean_train_window_fits_without_complaint() -> None:
    records = [_record(BACKTEST_START - dt.timedelta(days=n)) for n in range(1, 20)]
    model = fit_error_model(records, train_end_exclusive=BACKTEST_START)
    assert model.bias_by_key["*"] == pytest.approx(1.0)


def test_a_record_on_the_cutoff_date_is_rejected() -> None:
    """The cutoff is EXCLUSIVE: the backtest's first day is already leakage."""
    records = [_record(BACKTEST_START - dt.timedelta(days=1)), _record(BACKTEST_START)]
    with pytest.raises(ValueError, match="lookahead"):
        fit_error_model(records, train_end_exclusive=BACKTEST_START)


def test_a_record_after_the_cutoff_date_is_rejected() -> None:
    records = [_record(BACKTEST_START + dt.timedelta(days=3))]
    with pytest.raises(ValueError, match="lookahead"):
        fit_error_model(records, train_end_exclusive=BACKTEST_START)


def test_the_rejection_names_the_offending_record() -> None:
    offender = BACKTEST_START + dt.timedelta(days=2)
    with pytest.raises(ValueError) as excinfo:
        fit_error_model([_record(offender)], train_end_exclusive=BACKTEST_START)
    assert offender.isoformat() in str(excinfo.value)
    assert BACKTEST_START.isoformat() in str(excinfo.value)


def test_omitting_the_cutoff_preserves_the_unenforced_behaviour() -> None:
    """The parameter is opt-in; no existing caller changes behaviour."""
    model = fit_error_model([_record(BACKTEST_START + dt.timedelta(days=3))])
    assert model.bias_by_key["*"] == pytest.approx(1.0)
