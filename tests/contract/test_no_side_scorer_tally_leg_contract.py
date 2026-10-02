"""Contract: a NO-leg trial scores inverted, round-trips through
`scored_trial_store` with the schema UNTOUCHED, and is classified NO by
`family_tally_v2._stratum_row` (S5 Track D fix-first review, plan
`docs/plans/NO_SIDE_EDGE_2026-09-14.md` R3-5(i)).

End-to-end: `score_trial` -> `write_scored_trials`/`read_scored_trials` ->
`family_tally_v2._stratum_row`. Confirms the inversion the scorer applies is
never re-applied downstream (exactly-once, end to end) and that no column
was added to `SCORED_TRIAL_SCHEMA` to carry the leg -- it stays derived from
`instrument_id` at every hop.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.persistence.scored_trial_store import (
    SCORED_TRIAL_SCHEMA,
    read_scored_trials,
    write_scored_trials,
)
from breezy.settlement.trial_scorer import FilledTrial, ScoredTrial, score_trial

pytestmark = pytest.mark.contract

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

_STATION = "LAX"
_DAY = dt.date(2026, 8, 31)
_BASE_NS = int(dt.datetime(2026, 9, 1, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)


def _load_family_tally_v2() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "family_tally_v2.py"
    spec = importlib.util.spec_from_file_location("family_tally_v2", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_no_leg_scored_trial_round_trips_through_the_untouched_schema_and_tallies_as_no(
    tmp_path: Path,
) -> None:
    bucket = WeatherBucketFacts(
        settlement_station=_STATION,
        climate_day=_DAY,
        measure=Measure.HIGH,
        lower_f=78,
        upper_f=79,
    )
    trial = FilledTrial(
        trial_id="current_rung_hold/trial/LAX/2026-08-31",
        station=_STATION,
        climate_day=_DAY.isoformat(),
        instrument_id="LAX-2026-08-31-gte78lt80f^no.POLYMARKET_US",
        bucket=bucket,
        fill_px=Decimal("0.42"),
        fee=Decimal("0.01"),
        qty=Decimal(10),
        filled_at_ns=_BASE_NS - 3_600_000_000_000,
        entry_ask=Decimal("0.40"),
        scheduled_release_at_ns=_BASE_NS - 3_600_000_000_000,
    )
    record = NwsClimateDay(
        station=_STATION,
        climate_day=_DAY,
        tmax_f=79,  # inside the [78, 79] rung -- a YES leg would hold; NO must not.
        tmin_f=63,
        tavg_f=71,
        tavg_flag=None,
        tmax_flag=None,
        tmin_flag=None,
        is_final=True,
        correction_flag=False,
        revision_seq=1,
        is_superseded=False,
        issuing_office="KLAX",
        issuance_time_ns=_BASE_NS - 240_000_000_000,
        retrieved_at_ns=_BASE_NS,
        parser_version="test",
        registry_version="test",
        raw_sha256=hashlib.sha256(b"no-side-contract-test").hexdigest(),
        source_channel="iem_afos_forecast",
        schema_version=CLIMATE_DAY_SCHEMA_VERSION,
        ts_event=_BASE_NS,
    )

    scored = score_trial(trial, record, now_ns=_BASE_NS)
    assert isinstance(scored, ScoredTrial)
    assert scored.held is False  # inverted: HIGH landed IN the rung, but this is the NO leg.
    assert scored.pnl == Decimal(0) - Decimal("0.42") - Decimal("0.01")

    store_dir = tmp_path / "scored_trials"
    write_scored_trials(store_dir, (scored,), now_ns=_BASE_NS)
    read_back = read_scored_trials(store_dir)
    assert read_back == (scored,)

    # The schema itself carries NO leg/side column -- it is derived at read
    # time from `instrument_id`, at every hop, never persisted directly.
    assert "side" not in SCORED_TRIAL_SCHEMA.names
    assert "leg" not in SCORED_TRIAL_SCHEMA.names

    tally_mod = _load_family_tally_v2()
    row = tally_mod._stratum_row(read_back[0])
    assert row.side == "no"
    assert row.held is False  # exactly-once inversion: never re-inverted downstream.
    assert row.rung == "LAX-2026-08-31-gte78lt80f"
