"""ForecastQuantileLadderConfig (SL-12) -- guards restated for this new package.

Mirrors ``ladder_ev.config``'s own construction guards: ``allow_short`` stays
False, and there is no live refitting -- the calibration artefact sha must be
pinned (64 lowercase hex, not all-zero) at construction, before any I/O.
"""

from __future__ import annotations

import pytest

_STATIONS = ("KMIA",)
_PATH = "/tmp/does-not-matter.json"
_PINNED_SHA = "a" * 64


def test_default_construction_succeeds() -> None:
    from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig

    cfg = ForecastQuantileLadderConfig(
        stations=_STATIONS,
        calibration_artefact_path=_PATH,
        calibration_artefact_sha256=_PINNED_SHA,
    )

    assert cfg.allow_short is False
    assert cfg.stations == _STATIONS


def test_allow_short_true_is_refused() -> None:
    from breezy.strategy.forecast_quantile_ladder.config import (
        AllowShortNotPermittedError,
        ForecastQuantileLadderConfig,
    )

    with pytest.raises(AllowShortNotPermittedError):
        ForecastQuantileLadderConfig(
            stations=_STATIONS,
            calibration_artefact_path=_PATH,
            calibration_artefact_sha256=_PINNED_SHA,
            allow_short=True,
        )


def test_an_unpinned_all_zero_sha_is_refused() -> None:
    from breezy.strategy.forecast_quantile_ladder.config import (
        ForecastQuantileLadderConfig,
        UnpinnedCalibrationArtefactError,
    )

    with pytest.raises(UnpinnedCalibrationArtefactError):
        ForecastQuantileLadderConfig(
            stations=_STATIONS,
            calibration_artefact_path=_PATH,
            calibration_artefact_sha256="0" * 64,
        )


def test_an_empty_sha_is_refused() -> None:
    from breezy.strategy.forecast_quantile_ladder.config import (
        ForecastQuantileLadderConfig,
        UnpinnedCalibrationArtefactError,
    )

    with pytest.raises(UnpinnedCalibrationArtefactError):
        ForecastQuantileLadderConfig(
            stations=_STATIONS,
            calibration_artefact_path=_PATH,
            calibration_artefact_sha256="",
        )


def test_a_malformed_sha_is_refused() -> None:
    from breezy.strategy.forecast_quantile_ladder.config import (
        ForecastQuantileLadderConfig,
        UnpinnedCalibrationArtefactError,
    )

    with pytest.raises(UnpinnedCalibrationArtefactError):
        ForecastQuantileLadderConfig(
            stations=_STATIONS,
            calibration_artefact_path=_PATH,
            calibration_artefact_sha256="NOT-HEX",
        )


def test_kelly_stake_fraction_is_not_a_field() -> None:
    """Plan §3.3: sizing never reads ``kelly_stake_fraction``."""
    from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig

    cfg = ForecastQuantileLadderConfig(
        stations=_STATIONS,
        calibration_artefact_path=_PATH,
        calibration_artefact_sha256=_PINNED_SHA,
    )

    assert not hasattr(cfg, "kelly_stake_fraction")


def test_no_operator_reserved_fields_are_present() -> None:
    """Plan §8: never name, assign or read an operator-reserved control."""
    from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig

    field_names = frozenset(ForecastQuantileLadderConfig.__struct_fields__)
    reserved = {"max_daily_budget", "max_per_position", "daily_budget", "per_position_cap"}
    assert field_names.isdisjoint(reserved)


def test_stations_must_be_non_empty() -> None:
    from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig

    with pytest.raises(ValueError, match="stations"):
        ForecastQuantileLadderConfig(
            stations=(),
            calibration_artefact_path=_PATH,
            calibration_artefact_sha256=_PINNED_SHA,
        )
