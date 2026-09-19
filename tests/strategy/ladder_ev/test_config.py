"""T7: ``LadderEvConfig`` construction-time refusals (spec §10 / §13)."""

from __future__ import annotations

import pytest

from breezy.strategy.ladder_ev.config import (
    AllowShortNotPermittedError,
    LadderEvConfig,
    ModeFullNotPermittedError,
    RawCorpusPinMismatchError,
)
from breezy.strategy.ladder_ev.density_table import CORPUS_SHA256


def test_default_construction_succeeds() -> None:
    config = LadderEvConfig()
    assert config.allow_short is False
    assert config.mode == "degraded"
    assert config.n_min_cell == 90
    assert config.margin_m0 == 0.02
    assert config.margin_m24 == 0.06
    assert config.executable_ask_lower == 0.05
    assert config.executable_ask_upper == 0.95
    assert config.kelly_enabled is False
    assert config.kelly_fraction == 0.25
    assert config.order_quantity == 1
    assert config.entry_only_halt is True
    assert config.raw_corpus_pin == CORPUS_SHA256


def test_allow_short_true_is_refused() -> None:
    with pytest.raises(AllowShortNotPermittedError):
        LadderEvConfig(allow_short=True)


def test_mode_full_is_refused() -> None:
    with pytest.raises(ModeFullNotPermittedError):
        LadderEvConfig(mode="full")


def test_n_min_cell_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="n_min_cell"):
        LadderEvConfig(n_min_cell=0)


def test_margin_m24_below_m0_is_refused() -> None:
    with pytest.raises(ValueError, match="margin"):
        LadderEvConfig(margin_m0=0.08, margin_m24=0.06)


def test_executable_ask_band_must_be_strictly_ordered() -> None:
    with pytest.raises(ValueError, match="executable_ask"):
        LadderEvConfig(executable_ask_lower=0.95, executable_ask_upper=0.05)


def test_raw_corpus_pin_default_passes_and_mismatch_raises() -> None:
    config = LadderEvConfig()
    assert config.raw_corpus_pin == CORPUS_SHA256
    with pytest.raises(RawCorpusPinMismatchError):
        LadderEvConfig(raw_corpus_pin="0" * 64)


def test_config_is_frozen() -> None:
    config = LadderEvConfig()
    with pytest.raises(AttributeError):
        config.allow_short = True  # type: ignore[misc]


def test_mode_forecast_is_accepted_with_a_manifest_shaped_pin() -> None:
    pin = "ab" * 32
    config = LadderEvConfig(mode="forecast", forecast_corpus_pin=pin)
    assert config.mode == "forecast"
    assert config.forecast_corpus_pin == pin
    assert config.allow_short is False
    assert config.window_start_hour_lst == 12
    assert config.window_end_hour_lst == 17
    assert config.forecast_staleness_bound_ns >= 0
    assert config.publication_lag_ns >= 0
    assert config.raw_corpus_pin == CORPUS_SHA256


def test_mode_full_stays_hard_refused_when_forecast_is_legal() -> None:
    with pytest.raises(ModeFullNotPermittedError):
        LadderEvConfig(mode="full", forecast_corpus_pin="ab" * 32)


def test_forecast_mode_refuses_an_unpinned_or_malformed_corpus_pin() -> None:
    from breezy.strategy.ladder_ev.config import ForecastCorpusPinMismatchError

    with pytest.raises(ForecastCorpusPinMismatchError):
        LadderEvConfig(mode="forecast", forecast_corpus_pin="")
    with pytest.raises(ForecastCorpusPinMismatchError):
        LadderEvConfig(mode="forecast", forecast_corpus_pin="0" * 64)
    with pytest.raises(ForecastCorpusPinMismatchError):
        LadderEvConfig(mode="forecast", forecast_corpus_pin="not-a-sha")


def test_forecast_mode_still_enforces_the_raw_archive_corpus_pin() -> None:
    with pytest.raises(RawCorpusPinMismatchError):
        LadderEvConfig(
            mode="forecast",
            forecast_corpus_pin="ab" * 32,
            raw_corpus_pin="0" * 64,
        )


def test_src_does_not_define_a_forecast_corpus_sha256_constant() -> None:
    from pathlib import Path

    src_root = Path(__file__).resolve().parents[3] / "src"
    offenders = [
        str(path.relative_to(src_root))
        for path in src_root.rglob("*.py")
        if "FORECAST_CORPUS_SHA256" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_forecast_timing_bounds_must_be_non_negative() -> None:
    with pytest.raises(ValueError, match="forecast_staleness_bound_ns"):
        LadderEvConfig(forecast_staleness_bound_ns=-1)
    with pytest.raises(ValueError, match="publication_lag_ns"):
        LadderEvConfig(publication_lag_ns=-1)


def test_allow_short_stays_false_in_forecast_mode() -> None:
    with pytest.raises(AllowShortNotPermittedError):
        LadderEvConfig(mode="forecast", forecast_corpus_pin="ab" * 32, allow_short=True)


def test_config_has_no_operator_reserved_budget_or_position_cap() -> None:
    field_names = frozenset(LadderEvConfig.__struct_fields__)
    reserved = {
        "max_daily_budget_usd",
        "max_position_cost_usd",
        "max_daily_trading_budget",
        "max_notional_per_position",
        "max_position_contracts",
        "max_event_notional",
        "max_location_notional",
        "max_equity_fraction",
    }
    assert not (field_names & reserved)
