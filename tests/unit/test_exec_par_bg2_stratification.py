"""EXEC-PAR BG-2: fills are stratified by K-epoch on ``ts_event`` (J1).

``score_live_trials`` records the parallel-epoch fills in ``epoch_strata.jsonl``;
``family_tally_v2`` reports them as separate strata. When every epoch is K=1 (or
there are no epoch rows) neither script may change a byte of its output.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from breezy.persistence.epoch_strata import (
    EPOCH_STRATA_FILENAME,
    append_epoch_strata,
    parallel_trial_ids,
)
from breezy.runtime.exec_par_epochs import k_forced_amendment
from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    EpochRow,
    encode_record,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from tests.unit.test_family_tally_v2_mixed_side_disclosure_2026_09_25 import (
    _manifest,
    _row,
    _synthetic_artefact,
)
from tests.unit.test_score_live_trials_state_db_source import (
    _BASE_NS,
    _driver_kwargs,
    _seed_fill,
    _seed_instrument_and_final,
    _seed_latch,
)

score_live_trials = importlib.import_module("score_live_trials").score_live_trials

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOUR_NS = 3_600 * 1_000_000_000


def _put_epoch(store: SqliteStateStore, row: EpochRow) -> None:
    store.set(f"{EXEC_PAR_PREFIX}epoch/{row.boot_ts}", encode_record(row))


def _score(tmp_path: Path, *epochs: EpochRow, forced_amendment_ts: int | None = None) -> Path:
    catalog_base = tmp_path / "catalog"
    instrument_id = _seed_instrument_and_final(catalog_base)
    store_path = tmp_path / "state.sqlite"
    with SqliteStateStore(store_path) as store:
        _seed_latch(store, ask=Decimal("0.40"), instrument_id=instrument_id)
        _seed_fill(store, venue_order_id="v1", instrument_id=instrument_id, ts_event=_BASE_NS)
        for row in epochs:
            _put_epoch(store, row)
        if forced_amendment_ts is not None:
            amendment = k_forced_amendment(ts_ns=forced_amendment_ts, commit_sha="a", reason="r")
            store.set(f"{EXEC_PAR_PREFIX}amendment/{amendment.ts_ns}", encode_record(amendment))
    scored, _refused, excluded = score_live_trials(
        **_driver_kwargs(tmp_path, store_path, catalog_base=catalog_base)
    )
    assert len(scored) == 1 and excluded == ()
    return tmp_path / "derived"


def _artefacts(derived: Path) -> dict[str, bytes]:
    return {
        p.name: p.read_bytes()
        for p in sorted(derived.rglob("*"))
        if p.is_file() and p.suffix != ".parquet"
    }


def test_parallel_epoch_fill_is_recorded_with_its_stratum(tmp_path: Path) -> None:
    derived = _score(tmp_path, EpochRow("a", 2, None, _BASE_NS - _HOUR_NS))

    (line,) = (derived / EPOCH_STRATA_FILENAME).read_text().splitlines()
    record = json.loads(line)
    assert record["stratum"] == "parallel"
    assert record["filled_at_ns"] == _BASE_NS
    assert parallel_trial_ids(derived) == frozenset({record["trial_id"]})


def test_fill_after_a_later_k1_epoch_is_not_parallel(tmp_path: Path) -> None:
    derived = _score(
        tmp_path,
        EpochRow("a", 2, None, _BASE_NS - 2 * _HOUR_NS),
        EpochRow("a", 1, None, _BASE_NS - _HOUR_NS),
    )

    assert not (derived / EPOCH_STRATA_FILENAME).exists()


def test_k1_only_epochs_leave_every_artefact_byte_identical(tmp_path: Path) -> None:
    with_epochs = _score(tmp_path / "a", EpochRow("a", 1, None, _BASE_NS - _HOUR_NS))
    without = _score(tmp_path / "b")

    assert not (with_epochs / EPOCH_STRATA_FILENAME).exists()
    assert _artefacts(with_epochs) == _artefacts(without)


def test_a_forced_row_or_amendment_keeps_the_epoch_single(tmp_path: Path) -> None:
    forced_row = _score(tmp_path / "a", EpochRow("a", 1, "marker_absent", _BASE_NS - _HOUR_NS))
    amended = _score(
        tmp_path / "b",
        EpochRow("a", 2, None, _BASE_NS - _HOUR_NS),
        forced_amendment_ts=_BASE_NS - _HOUR_NS + 1,
    )

    assert not (forced_row / EPOCH_STRATA_FILENAME).exists()
    assert not (amended / EPOCH_STRATA_FILENAME).exists()


def test_appending_is_idempotent_on_trial_id(tmp_path: Path) -> None:
    append_epoch_strata(tmp_path, {"t1": 5})
    append_epoch_strata(tmp_path, {"t1": 5, "t2": 6})

    assert parallel_trial_ids(tmp_path) == frozenset({"t1", "t2"})
    assert len((tmp_path / EPOCH_STRATA_FILENAME).read_text().splitlines()) == 2


def test_no_parallel_fills_writes_nothing(tmp_path: Path) -> None:
    append_epoch_strata(tmp_path, {})

    assert not (tmp_path / EPOCH_STRATA_FILENAME).exists()
    assert parallel_trial_ids(tmp_path) == frozenset()


def test_a_malformed_sidecar_line_is_refused(tmp_path: Path) -> None:
    (tmp_path / EPOCH_STRATA_FILENAME).write_text("not json\n")

    with pytest.raises(ValueError):
        parallel_trial_ids(tmp_path)


# -- family_tally_v2 ---------------------------------------------------------------


@pytest.fixture(scope="module")
def tally_mod() -> ModuleType:
    scripts = _REPO_ROOT / "scripts" / "analysis"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("family_tally_v2", scripts / "family_tally_v2.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_tally_reports_a_separate_parallel_stratum(tmp_path: Path, tally_mod: ModuleType) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    rows = tuple(_row(i, ask="0.30") for i in range(10))
    parallel = frozenset(r.trial_id for r in rows[:4])

    tally = tally_mod.build_family_tally_v2(
        rows, manifest=manifest, artefact=artefact, parallel_trial_ids=parallel
    )

    labels = {s.label: s.n for s in tally.epoch_strata}
    assert labels == {"epoch:single": 6, "epoch:parallel": 4}
    report = tally_mod.render_markdown_v2(tally, source_paths=(), as_of="2026-10-11")
    assert "| epoch:parallel | 4 |" in report
    assert "| epoch:single | 6 |" in report


def test_tally_is_byte_identical_when_no_fill_is_parallel(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    rows = tuple(_row(i, ask="0.30") for i in range(10))

    default = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)
    explicit = tally_mod.build_family_tally_v2(
        rows, manifest=manifest, artefact=artefact, parallel_trial_ids=frozenset()
    )

    assert default.epoch_strata == ()
    report_default = tally_mod.render_markdown_v2(default, source_paths=(), as_of="x")
    assert report_default == tally_mod.render_markdown_v2(explicit, source_paths=(), as_of="x")
    assert "epoch:" not in report_default


def test_a_parallel_id_for_a_row_not_in_the_tally_is_ignored(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    rows = tuple(_row(i, ask="0.30") for i in range(10))

    tally = tally_mod.build_family_tally_v2(
        rows, manifest=manifest, artefact=artefact, parallel_trial_ids=frozenset({"gone"})
    )

    assert tally.epoch_strata == ()
