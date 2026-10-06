"""RED-first tests for the shared FQ take-rule shim (F13 review item P5).

``scripts/analysis/fq_evaluate_shim.py`` is the one public home of the single call of the shipped
``forecast_quantile_ladder.decision.evaluate`` that both the F5 Monte-Carlo
(``fq_mc_livedata``) and the F13 descriptive veto (``blend_veto_descriptive``) use. Synthetic
inputs only.
"""

from __future__ import annotations

import datetime as dt
import sys
import typing
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, REPO_ROOT.as_posix())

from breezy.strategy.forecast_quantile_ladder.decision import SidedAsk, Take
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.ladder_ev.quantile_density import Rung
from scripts.analysis import blend_veto_descriptive as veto
from scripts.analysis import fq_evaluate_shim as shim
from scripts.analysis import fq_mc_livedata as live

_DAY = dt.date(2026, 5, 10)
_LADDER = (Rung("proxy", None, None),)


def _call(side: str, p_hat: float, ask: float, cfg: Any = None) -> Any:
    loop = cfg if cfg is not None else live.LoopConfig()
    return shim.call_evaluate(
        climate_day=_DAY,
        station="NYC",
        ladder=_LADDER,
        rung_id="proxy",
        side=side,  # type: ignore[arg-type]
        ask=SidedAsk(side=side, instrument_id="PROXY", price=ask),  # type: ignore[arg-type]
        p_hat=p_hat,
        cfg=loop,
        h_hours=loop.h_hours,
        latch=QuantileLadderLatch(),
    )


def test_shim_is_the_public_home_and_livedata_re_exports_it() -> None:
    assert shim.call_evaluate is live._call_evaluate
    assert typing.get_args(shim.Side) == ("yes", "no")


def test_shim_yes_take_and_refusal_match_the_shipped_rule() -> None:
    assert isinstance(_call("yes", 0.60, 0.30), Take)
    assert not isinstance(_call("yes", 0.60, 0.55), Take)  # ask at the lower bound: no edge


def test_shim_no_leg_reads_the_upper_bound() -> None:
    assert isinstance(_call("no", 0.10, 0.40), Take)
    assert not isinstance(_call("no", 0.60, 0.40), Take)


def test_shim_refuses_a_side_outside_the_literal() -> None:
    with pytest.raises(ValueError, match="side"):
        _call("maybe", 0.5, 0.3)


def test_shim_uses_the_cfg_it_is_given() -> None:
    wide = live.LoopConfig(bound_halfwidth=0.30)
    assert isinstance(_call("yes", 0.60, 0.30), Take)
    assert not isinstance(_call("yes", 0.60, 0.30, wide), Take)  # lower bound 0.30 = ask


def test_veto_would_take_types_side_without_type_ignore() -> None:
    source = (REPO_ROOT / "scripts" / "analysis" / "blend_veto_descriptive.py").read_text("utf-8")
    assert "type: ignore" not in source
    assert veto.would_take(side="yes", p_yes=0.60, ask=0.30, climate_day=_DAY, station="NYC")
