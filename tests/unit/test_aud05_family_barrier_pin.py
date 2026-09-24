"""AUD-05 pin: cont and v4 stay separated under their shared trial-id prefix.

The tally-time barrier is why BLOCKER-1 does not re-issue the v4 manifest
(`docs/evidence/RULING_live_family_tally_scope_2026-09-21.md`).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from breezy.persistence.family_manifest import load_family_manifest
from breezy.settlement.family_barrier import FamilyBarrierRefusal, assert_family_only
from breezy.settlement.trial_scorer import ScoredTrial

_REPO = Path(__file__).resolve().parents[2]
_PREFIX = "continuous_rung_hold/trial/"


def _row(*, climate_day: str, station: str = "MIA") -> ScoredTrial:
    return ScoredTrial(
        trial_id=f"{_PREFIX}{station}/{climate_day}/0",
        station=station,
        climate_day=climate_day,
        instrument_id="instrument-1",
        settlement_tmax_f=80,
        held=True,
        pnl=Decimal("0.10"),
        revision_seq=0,
        raw_sha256="deadbeef",
        scored_at_ns=1,
        score_seq=0,
        settlement_basis="nws_final",
        excluded_reason=None,
        slippage=Decimal(0),
        entry_ask=Decimal("0.40"),
        fill_px=Decimal("0.40"),
        fee=Decimal("0.01"),
    )


def test_the_barrier_separates_cont_from_v4_under_their_shared_prefix() -> None:
    cont = load_family_manifest(_REPO / "deploy" / "families" / "pm_us_crh_cont.json")
    v4 = load_family_manifest(_REPO / "deploy" / "families" / "pm_us_crh_v4.json")
    assert cont.trial_id_prefix == v4.trial_id_prefix == _PREFIX
    assert cont.terminal_climate_day == "2026-09-19"
    assert v4.d0_climate_day == "2026-09-20"
    with pytest.raises(FamilyBarrierRefusal):
        assert_family_only((_row(climate_day="2026-09-15"),), v4)
    with pytest.raises(FamilyBarrierRefusal):
        assert_family_only((_row(climate_day="2026-09-21"),), cont)
