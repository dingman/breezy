"""Construction-time guards for `RunningExtremeLockStrategy`.

The load-bearing property under test (C1a, PLAN_observation_freshness.md
"PEER REVIEW OUTCOME"): this is the FIRST observation-kind weather strategy.
`RiskLimits.stale_observation_hours` defaults `None`, and `None` REFUSES every
order as `observation_limit_unset` -- a counted refusal that
`RefusalAlerter._conditions` (which hardcodes only `SHORTS_DISABLED`) never
alerts on. A strategy wired with no bound would silently refuse every order in
live. Construction must raise instead of shipping that silent failure mode.
"""

from __future__ import annotations

import pytest
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue

from breezy.strategy.running_extreme_lock.config import RunningExtremeLockConfig
from breezy.strategy.running_extreme_lock.strategy import (
    MissingObservationBoundError,
    RunningExtremeLockStrategy,
)

INSTRUMENT_ID = InstrumentId(Symbol("nyc-ge80"), Venue("POLYMARKET_US"))


def _config(**overrides: object) -> RunningExtremeLockConfig:
    fields: dict[str, object] = {
        "instrument_ids": (INSTRUMENT_ID,),
        "stale_observation_hours": 12.665,
        **overrides,
    }
    return RunningExtremeLockConfig(**fields)  # type: ignore[arg-type]


def test_constructing_with_stale_observation_hours_none_raises() -> None:
    with pytest.raises(MissingObservationBoundError):
        RunningExtremeLockStrategy(_config(stale_observation_hours=None))


def test_constructing_with_an_explicit_bound_succeeds() -> None:
    strategy = RunningExtremeLockStrategy(_config(stale_observation_hours=12.665))

    assert strategy is not None


def test_omitting_stale_observation_hours_is_a_type_error() -> None:
    """No default exists anywhere in the call chain -- an explicit operator act."""
    with pytest.raises(TypeError):
        RunningExtremeLockConfig(instrument_ids=(INSTRUMENT_ID,))  # type: ignore[call-arg]


def test_open_tail_only_false_is_not_implemented_in_v1() -> None:
    with pytest.raises(NotImplementedError):
        RunningExtremeLockStrategy(_config(open_tail_only=False))


def test_allow_short_defaults_false() -> None:
    assert _config().allow_short is False
