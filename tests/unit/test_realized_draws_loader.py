"""RED-first tests for WP-31's realized-outcome loader:
`breezy.persistence.realized_draws` -- scored-trial parquet -> PREREG v3 §5
admissible filter -> `StratumRow` -> `combine_station_day` -> `CombinedDraw`.

L-42 (BINDING): every parquet fixture here is written by the REAL scorer
(`score_live_trials.score_live_trials`, which calls the real
`breezy.persistence.scored_trial_store.write_scored_trials`) driven off an
exec state DB seeded with the SHIPPED encoders (`DurableFillRecord.to_bytes`,
`TrialDayRecord.to_bytes`) -- never a hand-built `CombinedDraw` and never a
hand-written parquet. The residual sidecar is likewise written by the real
`_append_excluded_fills` from the real `_admit_fill`/reader classification.
The only hand-written parquet in this file is in the schema-drift group,
where drift is the thing under test and the real writer cannot emit it.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from score_live_trials import (
    _append_excluded_fills,
    _scored_run_utc,
    score_live_trials,
)

from breezy.persistence.realized_draws import (
    RealizedDrawsSchemaDrift,
    admissible_scored_trials,
    load_realized_draws,
)
from breezy.persistence.residual_fills import residual_trial_ids
from breezy.persistence.scored_trial_store import SCORED_TRIAL_SCHEMA, read_scored_trials
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.settlement.current_rung_hold_v2 import combine_station_day
from tests.unit.test_score_live_trials_state_db_source import (
    _BASE_NS,
    _DAY_ISO,
    _INSTRUMENT_ID,
    _STATION,
    _V3_FAMILY_PREFIX,
    _driver_kwargs,
    _seed_fill,
    _seed_instrument_and_final,
    _seed_latch,
)

_LIVE_STORE = Path.home() / ".local/share/breezy/derived/scored_trials/pm_us_crh_cont"

#: A frozen, read-only snapshot of `_LIVE_STORE` as it stood on 2026-09-17
#: (the two 2026-09-16 scoring runs plus the 2026-09-17T14:15 run, before the
#: store grew further) -- copied verbatim (parquet + `excluded_fills.jsonl` +
#: `fill_order.jsonl`, real files written by the real scorer, never
#: hand-built) so the count-pinned assertions below stay hermetic instead of
#: drifting as the live store keeps accumulating new scoring runs.
_FROZEN_LIVE_SNAPSHOT = (
    Path(__file__).resolve().parents[1] / "fixtures/scored_trials/pm_us_crh_cont_2026-09-17"
)


def _run_real_scorer(tmp_path: Path, store_path: Path, **overrides: Any) -> Path:
    """Run the REAL driver and the REAL exclusion writer; return the store dir."""
    _scored, _refused, excluded = score_live_trials(
        **_driver_kwargs(tmp_path, store_path, **overrides)
    )
    derived = tmp_path / "derived"
    _append_excluded_fills(derived, excluded, scored_run_utc=_scored_run_utc(_BASE_NS))
    return derived


def _seeded_store(tmp_path: Path, **latch_kwargs: Any) -> tuple[Path, str]:
    """Seed the catalog instrument + FINAL climate day and one taken latch
    with its single admissible fill. Returns `(store_path, instrument_id)` --
    the latch must carry the FULL `<symbol>.<VENUE>` id the catalog wrote,
    which is the join key `score_live_trials` actually uses."""
    instrument_id = _seed_instrument_and_final(tmp_path / "catalog")
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(
        store, ask=Decimal("0.40"), instrument_id=instrument_id, **latch_kwargs
    )
    _seed_fill(store, venue_order_id="v1", instrument_id=instrument_id)
    store.close()
    return store_path, instrument_id


def _reseed_fill(store_path: Path, instrument_id: str, **fill_kwargs: Any) -> None:
    """Overwrite the SAME fill record with a later, residual-classified shape --
    the real re-score sequence (fee reconciliation flips, a corrected fill
    record) that leaves a run-1 scored row in the parquet while run 2
    classifies the fill residual."""
    store = SqliteStateStore(store_path)
    _seed_fill(store, venue_order_id="v1", instrument_id=instrument_id, **fill_kwargs)
    store.close()


# ---------------------------------------------------------------------------
# group 2: an admissible fill is EXACTLY ONE constituent of its station-day
# ---------------------------------------------------------------------------


def test_one_admissible_fill_is_exactly_one_constituent_of_its_station_day_draw(
    tmp_path: Path,
) -> None:
    store_path, _instrument_id = _seeded_store(tmp_path)
    derived = _run_real_scorer(tmp_path, store_path)

    loaded = load_realized_draws(derived)

    assert loaded.n_admissible_fills == 1
    assert loaded.n_dropped_residual == 0
    assert len(loaded.draws) == 1
    assert loaded.draws[0].n_constituents == 1
    assert loaded.station_days == ((_STATION, _DAY_ISO),)


def test_the_draw_is_combine_station_day_of_the_loaded_rows_not_a_second_formula(
    tmp_path: Path,
) -> None:
    """The loader must REUSE `combine_station_day`, never recompute x/variance."""
    store_path, _instrument_id = _seeded_store(tmp_path)
    derived = _run_real_scorer(tmp_path, store_path)

    loaded = load_realized_draws(derived)

    assert loaded.draws[0] == combine_station_day(loaded.stratum_rows)


# ---------------------------------------------------------------------------
# group 1: a residual row is DROPPED -- PREREG v3 §5, one test per bucket
# ---------------------------------------------------------------------------


def test_a_fee_unreconciled_residual_row_is_dropped(tmp_path: Path) -> None:
    store_path, instrument_id = _seeded_store(tmp_path)
    _run_real_scorer(tmp_path, store_path)
    _reseed_fill(store_path, instrument_id, fee_reconciled=False)
    derived = _run_real_scorer(tmp_path, store_path)

    loaded = load_realized_draws(derived)

    assert loaded.n_dropped_residual == 1
    assert loaded.n_admissible_fills == 0
    assert loaded.draws == ()


def test_a_qty_not_one_residual_row_is_dropped(tmp_path: Path) -> None:
    store_path, instrument_id = _seeded_store(tmp_path)
    _run_real_scorer(tmp_path, store_path)
    _reseed_fill(
        store_path,
        instrument_id,
        cumulative_qty=Decimal("0.37"),
        cumulative_cost=Decimal("0.1554"),
    )
    derived = _run_real_scorer(tmp_path, store_path)

    loaded = load_realized_draws(derived)

    assert loaded.n_dropped_residual == 1
    assert loaded.n_admissible_fills == 0
    assert loaded.draws == ()


def test_a_duplicate_fill_residual_row_is_dropped(tmp_path: Path) -> None:
    """PREREG §5 bucket 1. The scored-trial schema carries no
    `venue_order_id`, so a `duplicate_fill` on a trial_id cannot be
    attributed to one of its two fills from the parquet alone -- the loader
    fails CLOSED and drops the trial_id (n shrinks, never inflates)."""
    store_path, instrument_id = _seeded_store(
        tmp_path, venue_order_id="v1", family_prefix=_V3_FAMILY_PREFIX
    )
    _run_real_scorer(tmp_path, store_path, family_prefix=_V3_FAMILY_PREFIX)

    store = SqliteStateStore(store_path)
    _seed_fill(
        store,
        venue_order_id="v2",
        instrument_id=instrument_id,
        cumulative_cost=Decimal("0.44"),
    )
    store.close()
    derived = _run_real_scorer(tmp_path, store_path, family_prefix=_V3_FAMILY_PREFIX)

    loaded = load_realized_draws(derived)

    assert loaded.n_dropped_residual == 1
    assert loaded.n_admissible_fills == 0
    assert loaded.draws == ()


# ---------------------------------------------------------------------------
# group 4: schema drift is LOUD
# ---------------------------------------------------------------------------


def _dummy(field: pa.Field) -> list[Any]:
    if pa.types.is_boolean(field.type):
        return [True]
    if pa.types.is_integer(field.type):
        return [1]
    return ["x"]


def test_an_unexpected_column_raises_rather_than_being_silently_dropped(
    tmp_path: Path,
) -> None:
    drifted = SCORED_TRIAL_SCHEMA.append(pa.field("surprise", pa.string()))
    table = pa.table({f.name: _dummy(f) for f in drifted}, schema=drifted)
    tmp_path.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, tmp_path / "scored_trials_20260101T000000000000000Z.parquet")

    with pytest.raises(RealizedDrawsSchemaDrift, match="surprise"):
        load_realized_draws(tmp_path)


def test_a_missing_column_raises_rather_than_being_silently_nulled(
    tmp_path: Path,
) -> None:
    """`pq.read_table(path, schema=...)` silently materialises an absent
    column as all-NULL -- a missing `held` would score every trial a loss."""
    drifted = pa.schema([f for f in SCORED_TRIAL_SCHEMA if f.name != "held"])
    table = pa.table({f.name: _dummy(f) for f in drifted}, schema=drifted)
    tmp_path.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, tmp_path / "scored_trials_20260101T000000000000000Z.parquet")

    with pytest.raises(RealizedDrawsSchemaDrift, match="held"):
        load_realized_draws(tmp_path)


def test_a_file_missing_only_the_back_compat_optional_bucket_source_still_loads(
    tmp_path: Path,
) -> None:
    """`_scored_trial_from_row` documents that a pre-`bucket_source` file is
    a supported legacy shape -- the drift guard is WIDENED for exactly that
    column (L-12), never relaxed for any other."""
    legacy = pa.schema([f for f in SCORED_TRIAL_SCHEMA if f.name != "bucket_source"])
    table = pa.table({f.name: _dummy(f) for f in legacy}, schema=legacy)
    tmp_path.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, tmp_path / "scored_trials_20260101T000000000000000Z.parquet")

    # `_dummy` gives non-numeric Decimal fields, so only the READ must survive.
    with pytest.raises(Exception) as excinfo:
        load_realized_draws(tmp_path)
    assert not isinstance(excinfo.value, RealizedDrawsSchemaDrift)


# ---------------------------------------------------------------------------
# group 3: the REAL live store (L-42 provenance: nothing here was authored)
# ---------------------------------------------------------------------------


def test_the_frozen_2026_09_17_snapshot_loads_three_admissible_fills_in_two_station_day_draws() -> (
    None
):
    """Hermetic pin of the 2026-09-16/17 live `pm_us_crh_cont` store: FOUR
    scored parquet rows, one of which (the MIA `^no` trial) carries a
    `no_side_first_order_residual` exclusion in the sidecar. PREREG §5 admits
    THREE. This is `_FROZEN_LIVE_SNAPSHOT` -- a byte-for-byte copy of the real
    store as of 2026-09-17T14:15Z -- rather than `_LIVE_STORE` itself, because
    the live store is append-only and keeps growing (it held 7 scored rows by
    2026-09-24); pinning counts against a live, growing store is not
    hermetic. See `test_the_real_live_store_never_admits_a_residual_trial_id`
    below for the structural (non-count) invariant checked against the
    CURRENT live store."""
    loaded = load_realized_draws(_FROZEN_LIVE_SNAPSHOT)

    assert loaded.n_admissible_fills == 3
    assert loaded.n_dropped_residual == 1
    assert loaded.station_days == (("MDW", "2026-09-15"), ("SFO", "2026-09-15"))
    assert tuple(d.n_constituents for d in loaded.draws) == (2, 1)
    assert all(row.side == "yes" for row in loaded.stratum_rows)


@pytest.mark.skipif(not _LIVE_STORE.exists(), reason="no live scored-trial store on this host")
def test_the_real_live_store_never_admits_a_residual_trial_id() -> None:
    """Structural invariant (PREREG v3 §5), not a count: no matter how many
    rows the live store accumulates, (1) a trial_id the sidecar names
    residual must never appear in the admissible set, and (2) every scored
    row is accounted for exactly once across admissible / dropped-residual /
    dropped-excluded-reason. Runs against the REAL, growing store and pins
    no count -- the frozen, count-pinned snapshot of this same store as of
    2026-09-17 is
    `test_the_frozen_2026_09_17_snapshot_loads_three_admissible_fills_in_two_station_day_draws`
    above."""
    loaded = load_realized_draws(_LIVE_STORE)
    rows = read_scored_trials(_LIVE_STORE)
    residual = residual_trial_ids(_LIVE_STORE)
    admissible = admissible_scored_trials(rows, residual_trial_ids=residual)

    assert not ({trial.trial_id for trial in admissible} & residual)
    assert loaded.n_scored_rows == (
        loaded.n_admissible_fills + loaded.n_dropped_residual + loaded.n_dropped_excluded_reason
    )


# ---------------------------------------------------------------------------
# empty / absent store
# ---------------------------------------------------------------------------


def test_an_absent_store_loads_as_zero_draws_never_an_error(tmp_path: Path) -> None:
    loaded = load_realized_draws(tmp_path / "nope")

    assert loaded.draws == ()
    assert loaded.n_admissible_fills == 0


def test_a_row_with_an_excluded_reason_is_dropped_like_the_v2_tally_drops_it(
    tmp_path: Path,
) -> None:
    """`family_tally_v2.build_family_tally_v2` filters `excluded_reason is
    None` (scoring-time venue-fallback-without-NWS); the loader must not
    admit what the registered tally refuses."""
    from breezy.persistence.realized_draws import is_admissible
    from breezy.settlement.trial_scorer import ScoredTrial

    trial = ScoredTrial(
        trial_id="t",
        station=_STATION,
        climate_day=_DAY_ISO,
        instrument_id=_INSTRUMENT_ID,
        settlement_tmax_f=79,
        held=True,
        pnl=Decimal("0.5"),
        revision_seq=1,
        raw_sha256="a" * 64,
        scored_at_ns=_BASE_NS,
        score_seq=0,
        settlement_basis="venue_last_fair_price_fallback",
        excluded_reason="no_nws_final",
        slippage=Decimal(0),
        entry_ask=Decimal("0.40"),
        fill_px=Decimal("0.42"),
        fee=Decimal("0.01"),
    )

    assert is_admissible(trial, residual_trial_ids=frozenset()) is False
