"""Mechanics of `scripts/analysis/forecast_tape_screen.py` (WP-6 scaffolding only).

WP-6 builds the screen's MECHANICS and unit-tests them on fixtures. It does NOT
sweep a variant space: the multi-variant cheap screen is WP-7 and is blocked on
a pre-declared variant set with prediction-market sign-off BEFORE its first run.
The test below pins that refusal, so a later change cannot quietly turn this
module into a multiplicity laundry.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"


def _load_module(name: str) -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def screen() -> ModuleType:
    return _load_module("forecast_tape_screen")


def _quote(screen: ModuleType, ask: float):
    return screen.TapeQuote(
        station="KSFO",
        climate_day=dt.date(2025, 7, 1),
        rung_lower_f=70,
        ask_probability=ask,
    )


# ---------------------------------------------------------------------------
# WP-7 containment -- the reason this module is scaffolding and not a study
# ---------------------------------------------------------------------------


def test_a_variant_sweep_is_refused_here(screen: ModuleType) -> None:
    with pytest.raises(screen.VariantSweepRefused, match="WP-7"):
        screen.screen_tape(
            quotes=(_quote(screen, 0.4),),
            model_probability={("KSFO", dt.date(2025, 7, 1), 70): 0.6},
            variants=(screen.ScreenVariant(0.05), screen.ScreenVariant(0.10)),
        )


def test_exactly_one_variant_is_allowed(screen: ModuleType) -> None:
    decisions = screen.screen_tape(
        quotes=(_quote(screen, 0.4),),
        model_probability={("KSFO", dt.date(2025, 7, 1), 70): 0.6},
        variants=(screen.ScreenVariant(0.05),),
    )
    assert len(decisions) == 1


def test_zero_variants_is_refused(screen: ModuleType) -> None:
    with pytest.raises(screen.VariantSweepRefused):
        screen.screen_tape(
            quotes=(),
            model_probability={},
            variants=(),
        )


# ---------------------------------------------------------------------------
# Edge mechanics
# ---------------------------------------------------------------------------


def test_edge_is_net_of_the_declared_fee(screen: ModuleType) -> None:
    edge = screen.net_edge(model_probability=0.60, ask_probability=0.50, fee=0.0695)
    assert edge == pytest.approx(0.60 - 0.50 - 0.0695)


def test_a_take_needs_edge_strictly_above_the_threshold(screen: ModuleType) -> None:
    variant = screen.ScreenVariant(min_edge=0.03)
    quotes = (_quote(screen, 0.55),)
    probs = {("KSFO", dt.date(2025, 7, 1), 70): 0.60}
    decision = screen.screen_tape(quotes=quotes, model_probability=probs, variants=(variant,))[0]
    # 0.60 - 0.55 - 0.0695 = -0.0195 -> below 0.03 -> no take.
    assert decision.take is False
    assert decision.reason == screen.REASON_EDGE_BELOW_THRESHOLD


def test_a_sufficient_edge_takes(screen: ModuleType) -> None:
    variant = screen.ScreenVariant(min_edge=0.03)
    quotes = (_quote(screen, 0.30),)
    probs = {("KSFO", dt.date(2025, 7, 1), 70): 0.60}
    decision = screen.screen_tape(quotes=quotes, model_probability=probs, variants=(variant,))[0]
    assert decision.take is True
    assert decision.reason == screen.REASON_TAKE


def test_a_quote_with_no_model_probability_is_skipped_not_guessed(screen: ModuleType) -> None:
    decision = screen.screen_tape(
        quotes=(_quote(screen, 0.30),),
        model_probability={},
        variants=(screen.ScreenVariant(min_edge=0.03),),
    )[0]
    assert decision.take is False
    assert decision.reason == screen.REASON_NO_MODEL_PROBABILITY


def test_a_probability_outside_the_unit_interval_is_refused(screen: ModuleType) -> None:
    with pytest.raises(ValueError):
        screen.net_edge(model_probability=1.5, ask_probability=0.5, fee=0.0)


def test_a_short_side_is_never_produced(screen: ModuleType) -> None:
    """allow_short stays False: the screen only ever emits a BUY-side take."""
    decision = screen.screen_tape(
        quotes=(_quote(screen, 0.30),),
        model_probability={("KSFO", dt.date(2025, 7, 1), 70): 0.60},
        variants=(screen.ScreenVariant(min_edge=0.03),),
    )[0]
    assert decision.side == screen.SIDE_BUY
