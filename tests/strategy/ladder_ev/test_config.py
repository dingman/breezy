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
