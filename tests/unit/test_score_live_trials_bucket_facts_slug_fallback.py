"""RED-first regression suite for the slug-fallback defect (2026-09-16,
measured against a copy of the live `pm_us_crh_cont` store after the L-38
prefix fix `cbd5fec`): with an EMPTY NWS instrument catalog (ING-1 ingest
strand), `score_live_trials` used to exclude every trial
`instrument_unavailable` even though each trial's rung is fully determined
by its own instrument id / market slug.

Reuses the exact five-fill live-store fixture from
`test_score_live_trials_l38_family_prefix` (venue order ids, prices, fees,
instrument ids copied from a read-only copy of the live
`exec_polymarket_us.sqlite`) rather than re-deriving a parallel fixture.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from score_live_trials import FillExclusion

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.persistence.catalog import open_station_catalog, write_records
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.settlement.trial_scorer import ScoredTrial, ScoreRefusal
from tests.unit.test_score_live_trials_l38_family_prefix import (
    _BASE_NS,
    _CONT_PREFIX,
    _SHA,
    _VENUE,
    _score,
    _seed_fill,
    _seed_five_real_fills,
    _seed_instrument_and_final,
    _seed_latch,
)

#: The three 2026-09-15 YES trials' CLI FINAL truth (matches the defect
#: report: "MDW 85, SFO 73, MIA 93 for 2026-09-15" -- MIA's fills are
#: excluded before ever reaching bucket resolution, so its FINAL is not
#: needed here). Every rung is narrow enough that the FINAL falls outside
#: it, so all three settle held=False regardless of bucket-boundary
#: inclusivity (mirrors the sibling L-38 suite's own reasoning).
_MDW_TMAX_F = 85
_SFO_TMAX_F = 73

_EXPECTED_INSTRUMENTS = {
    "tc-temp-mdwhigh-2026-09-15-gte80lt81f.POLYMARKET_US",
    "tc-temp-mdwhigh-2026-09-15-gte82lt83f.POLYMARKET_US",
    "tc-temp-sfohigh-2026-09-15-gte71lt72f.POLYMARKET_US",
}


def _seed_final_only(
    catalog_base: Path,
    *,
    station: str,
    climate_day_iso: str,
    tmax_f: int,
) -> None:
    """`_seed_instrument_and_final` without the paired `BinaryOption`
    instrument write -- reproduces the ING-1 shape: a FINAL NWS CLI record
    exists, but the catalog holds zero persisted instrument definitions."""
    catalog = open_station_catalog(catalog_base, _VENUE, station)
    write_records(
        catalog,
        [
            NwsClimateDay(
                station=station,
                climate_day=dt.date.fromisoformat(climate_day_iso),
                tmax_f=tmax_f,
                tmin_f=tmax_f - 15,
                tavg_f=tmax_f - 7,
                tavg_flag=None,
                tmax_flag=None,
                tmin_flag=None,
                is_final=True,
                correction_flag=False,
                revision_seq=1,
                is_superseded=False,
                issuing_office="TEST",
                issuance_time_ns=_BASE_NS - 240_000_000_000,
                retrieved_at_ns=_BASE_NS,
                parser_version="test",
                registry_version="test",
                raw_sha256=_SHA,
                source_channel="test",
                schema_version=CLIMATE_DAY_SCHEMA_VERSION,
                ts_event=_BASE_NS,
            )
        ],
    )


def _run_over_five_real_fills(
    tmp_path: Path, catalog_base: Path
) -> tuple[list[ScoredTrial], list[ScoreRefusal], list[FillExclusion]]:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_five_real_fills(store)
    store.close()

    all_scored: list[ScoredTrial] = []
    all_refused: list[ScoreRefusal] = []
    all_excluded: list[FillExclusion] = []
    for city in ("LAX", "MDW", "MIA", "SFO"):
        scored, refused, excluded = _score(
            tmp_path,
            family_prefix=_CONT_PREFIX,
            city=city,
            store_path=store_path,
            catalog_base=catalog_base,
        )
        all_scored.extend(scored)
        all_refused.extend(refused)
        all_excluded.extend(excluded)
    return all_scored, all_refused, all_excluded


def test_empty_catalog_falls_back_to_slug_and_scores_all_three(tmp_path: Path) -> None:
    catalog_base = tmp_path / "catalog"
    _seed_final_only(catalog_base, station="MDW", climate_day_iso="2026-09-15", tmax_f=_MDW_TMAX_F)
    _seed_final_only(catalog_base, station="SFO", climate_day_iso="2026-09-15", tmax_f=_SFO_TMAX_F)

    scored, refused, excluded = _run_over_five_real_fills(tmp_path, catalog_base)

    assert refused == [], refused
    assert len(scored) == 3
    assert {row.instrument_id for row in scored} == _EXPECTED_INSTRUMENTS
    for row in scored:
        assert row.climate_day == "2026-09-15"
        assert row.held is False
        assert row.settlement_basis == "nws_final"
        assert row.bucket_source == "slug"

    # The two residual MIA fills are still excluded by the SAME rules as
    # ever -- the slug fallback never touches admission/residual exclusion.
    reasons = {e.reason for e in excluded}
    assert reasons == {"no_side_first_order_residual", "fee_unverified"}
    assert len(excluded) == 2


def test_catalog_present_resolves_via_catalog_with_identical_numbers(tmp_path: Path) -> None:
    catalog_base = tmp_path / "catalog"
    _seed_instrument_and_final(
        catalog_base,
        station="MDW",
        instrument_id="tc-temp-mdwhigh-2026-09-15-gte80lt81f.POLYMARKET_US",
        climate_day_iso="2026-09-15",
        lower_f=80,
        upper_f=81,
        tmax_f=_MDW_TMAX_F,
    )
    _seed_instrument_and_final(
        catalog_base,
        station="MDW",
        instrument_id="tc-temp-mdwhigh-2026-09-15-gte82lt83f.POLYMARKET_US",
        climate_day_iso="2026-09-15",
        lower_f=82,
        upper_f=83,
        tmax_f=_MDW_TMAX_F,
    )
    _seed_instrument_and_final(
        catalog_base,
        station="SFO",
        instrument_id="tc-temp-sfohigh-2026-09-15-gte71lt72f.POLYMARKET_US",
        climate_day_iso="2026-09-15",
        lower_f=71,
        upper_f=72,
        tmax_f=_SFO_TMAX_F,
    )

    scored, refused, excluded = _run_over_five_real_fills(tmp_path, catalog_base)

    assert refused == [], refused
    assert len(scored) == 3
    assert {row.instrument_id for row in scored} == _EXPECTED_INSTRUMENTS
    for row in scored:
        assert row.climate_day == "2026-09-15"
        assert row.held is False
        assert row.settlement_basis == "nws_final"
        assert row.bucket_source == "catalog"

    reasons = {e.reason for e in excluded}
    assert reasons == {"no_side_first_order_residual", "fee_unverified"}
    assert len(excluded) == 2


def test_unparseable_instrument_id_still_excludes_instrument_unavailable(
    tmp_path: Path,
) -> None:
    """An empty catalog PLUS a slug that does not match the observed weather
    grammar at all must still refuse `instrument_unavailable` -- the slug
    fallback is never a license to fabricate a rung for an unrecognised id."""
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(
        store,
        station="MDW",
        climate_day="2026-09-15",
        instrument_id="not-a-weather-market-slug.POLYMARKET_US",
        ask=Decimal("0.50"),
        venue_order_id="CGZUNPARSEABLE",
    )
    _seed_fill(
        store,
        venue_order_id="CGZUNPARSEABLE",
        instrument_id="not-a-weather-market-slug.POLYMARKET_US",
        cost=Decimal("0.50"),
        fee=Decimal("0.01"),
        fee_reconciled=True,
        ts_event=1789495204346084927,
    )
    store.close()

    catalog_base = tmp_path / "catalog"
    scored, refused, excluded = _score(
        tmp_path,
        family_prefix=_CONT_PREFIX,
        city="MDW",
        store_path=store_path,
        catalog_base=catalog_base,
    )

    assert scored == ()
    assert excluded == ()
    assert len(refused) == 1
    assert refused[0].reason == "instrument_unavailable"
    assert refused[0].trial_id.endswith("not-a-weather-market-slug.POLYMARKET_US")
