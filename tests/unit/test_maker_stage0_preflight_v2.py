"""MAKER-S2 second look (C2/C6): the v2 checks that run BEFORE the ledger claim."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from breezy.analysis.maker_tape_census import CensusedDay, write_censused_days
from scripts.analysis.maker_stage0_frozen import (
    FrozenDateSet,
    parse_frozen_block_v2,
    truth_keys,
)
from scripts.analysis.maker_stage0_inputs import (
    MAKER_STATIONS,
    InputRefused,
    TruthConflict,
)
from scripts.analysis.maker_stage0_preflight_v2 import check_v2_before_claim, needs_v2_checks
from tests.fixtures.maker_stage0 import make_census_fixture as fx
from tests.fixtures.maker_stage0.frozen_v2 import BLOCK_FIRST, TRIGGER, days, v2_fields, v2_text

_NS = 1_000_000_000
_CSV_HEAD = "station,climate_day,tmax_f,tmax_flag,correction_flag,product_sha256\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _early_ns(day: dt.date) -> int:
    moment = dt.datetime.combine(day - dt.timedelta(days=1), dt.time(6), tzinfo=dt.UTC)
    return int(moment.timestamp()) * _NS


@dataclass
class World:
    fs: FrozenDateSet
    root: Path
    census: list[CensusedDay]

    def check(self) -> list[tuple[str, dt.date]]:
        return check_v2_before_claim(
            self.fs,
            repo_root=self.root,
            truth_csv=self.root / "truth.csv",
            cross_check=self.root / "cross.parquet",
            census_days=self.root / "censused_days.jsonl",
            census=self.census,
        )


def _write_trigger(root: Path, last: dt.date) -> None:
    rows = [
        {
            "station": s,
            "climate_day": d.isoformat(),
            "reason": "COVERED",
            "first_seen_ns": _early_ns(d),
        }
        for d in days(last=last)
        for s in MAKER_STATIONS
    ]
    (root / "trigger.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _write_cross(root: Path, cross_tmax: int = 70) -> None:
    keys = [(s, d) for d in days() for s in MAKER_STATIONS]
    table = pa.table(
        {
            "station": [s for s, _ in keys],
            "climate_day": pa.array([d for _, d in keys], type=pa.date32()),
            "status": ["FINAL"] * len(keys),
            "tmax_f": [cross_tmax] * len(keys),
        }
    )
    pq.write_table(table, root / "cross.parquet")


def _world(root: Path, *, csv_tmax: int = 70, cross_tmax: int = 70, overlap: bool = True) -> World:
    lines = [f"{s},{d},{csv_tmax},,False,x\n" for d in days() for s in MAKER_STATIONS]
    (root / "truth.csv").write_text(_CSV_HEAD + "".join(lines))
    _write_cross(root, cross_tmax)
    if not overlap:  # a cross-check that holds only days outside the licensed set
        far = pa.table(
            {
                "station": ["SFO"],
                "climate_day": pa.array([dt.date(2026, 6, 30)], type=pa.date32()),
                "status": ["FINAL"],
                "tmax_f": [70],
            }
        )
        pq.write_table(far, root / "cross.parquet")
    census = fx.census_grid(first_day=BLOCK_FIRST, n_days=len(days()))
    write_censused_days(root / "censused_days.jsonl", census)
    _write_trigger(root, TRIGGER)
    fields = v2_fields(
        trigger_rows_path="trigger.jsonl",
        trigger_rows_sha256=_sha(root / "trigger.jsonl"),
        census_days_sha256=_sha(root / "censused_days.jsonl"),
        truth_csv_sha256=_sha(root / "truth.csv"),
        cross_check_sha256=_sha(root / "cross.parquet"),
    )
    return World(parse_frozen_block_v2(v2_text(fields)), root, census)


def test_a_consistent_v2_world_passes(tmp_path: Path) -> None:
    _world(tmp_path).check()


def test_v2_trigger_day_must_recompute_from_pinned_rows(tmp_path: Path) -> None:
    world = _world(tmp_path)
    _write_trigger(tmp_path, TRIGGER - dt.timedelta(days=1))  # one fewer day: E moves or vanishes
    pinned = _sha(tmp_path / "trigger.jsonl")
    fs = parse_frozen_block_v2(
        v2_text(
            v2_fields(
                trigger_rows_path="trigger.jsonl",
                trigger_rows_sha256=pinned,
                census_days_sha256=world.fs.census_days_sha256,
                truth_csv_sha256=world.fs.truth_csv_sha256,
                cross_check_sha256=world.fs.cross_check_sha256,
            )
        )
    )
    with pytest.raises(InputRefused, match="trigger_day"):
        World(fs, tmp_path, world.census).check()


def test_v2_trigger_rows_sha_mismatch_refused_before_claim(tmp_path: Path) -> None:
    world = _world(tmp_path)
    (tmp_path / "trigger.jsonl").write_text("tampered\n")
    with pytest.raises(InputRefused, match="trigger rows"):
        world.check()


def test_v2_cross_check_sha_mismatch_refused_before_claim(tmp_path: Path) -> None:
    world = _world(tmp_path)
    with (tmp_path / "cross.parquet").open("ab") as handle:
        handle.write(b"\0")
    with pytest.raises(InputRefused, match="cross-check"):
        world.check()


def test_v2_census_days_sha_mismatch_refused_before_claim(tmp_path: Path) -> None:
    world = _world(tmp_path)
    with (tmp_path / "censused_days.jsonl").open("ab") as handle:
        handle.write(b"\n")
    with pytest.raises(InputRefused, match="census"):
        world.check()


def test_v2_cross_check_without_overlap_refused_before_claim(tmp_path: Path) -> None:
    world = _world(tmp_path, overlap=False)
    fs = parse_frozen_block_v2(
        v2_text(
            v2_fields(
                trigger_rows_path="trigger.jsonl",
                trigger_rows_sha256=world.fs.trigger_rows_sha256,
                census_days_sha256=world.fs.census_days_sha256,
                truth_csv_sha256=world.fs.truth_csv_sha256,
                cross_check_sha256=_sha(tmp_path / "cross.parquet"),
            )
        )
    )
    with pytest.raises(InputRefused, match="vacuous"):
        World(fs, tmp_path, world.census).check()


def test_v2_truth_conflict_refused_before_claim(tmp_path: Path) -> None:
    world = _world(tmp_path, cross_tmax=71)
    with pytest.raises(TruthConflict):
        world.check()


def test_v2_truth_csv_sha_mismatch_refused_before_claim(tmp_path: Path) -> None:
    world = _world(tmp_path)
    (tmp_path / "truth.csv").write_text((tmp_path / "truth.csv").read_text() + "\n")
    with pytest.raises(InputRefused, match="sha256"):
        world.check()


def test_preflight_keys_superset_of_score_keys(tmp_path: Path) -> None:
    fs = _world(tmp_path).fs
    preflight_keys = truth_keys(fs.stations, fs.dates)
    # report.score derives its keys from the replayed station-days (report.py:118)
    sd_rows = [
        SimpleNamespace(station=s, climate_day=d.isoformat())
        for s in fs.stations
        for d in fs.dates[:3]
    ]
    score_keys = {(r.station, dt.date.fromisoformat(r.climate_day)) for r in sd_rows}
    assert score_keys <= preflight_keys
    assert preflight_keys == {(s, d) for s in fs.stations for d in fs.dates}


def test_v1_preflight_unchanged() -> None:
    v1 = FrozenDateSet(
        ("SFO",),
        dt.date(2026, 9, 18),
        "/x",
        "ab" * 32,
        dt.date(2026, 9, 19),
        (dt.date(2026, 9, 18),),
    )
    assert not needs_v2_checks(v1, "verdict")
    v2 = _v2_stub()
    assert needs_v2_checks(v2, "verdict")
    for mode in ("bench", "tail-only", "verify-first"):
        assert not needs_v2_checks(v2, mode)


def _v2_stub() -> FrozenDateSet:
    return parse_frozen_block_v2(v2_text(v2_fields()))


def _with_census(world: World, census: list[CensusedDay]) -> World:
    write_censused_days(world.root / "censused_days.jsonl", census)
    fs = parse_frozen_block_v2(
        v2_text(
            v2_fields(
                trigger_rows_path="trigger.jsonl",
                trigger_rows_sha256=world.fs.trigger_rows_sha256,
                census_days_sha256=_sha(world.root / "censused_days.jsonl"),
                truth_csv_sha256=world.fs.truth_csv_sha256,
                cross_check_sha256=world.fs.cross_check_sha256,
            )
        )
    )
    return World(fs, world.root, census)


def test_v2_counted_day_not_covered_in_final_census_refused_before_claim(tmp_path: Path) -> None:
    world = _world(tmp_path)
    census = [
        fx.census_row(r.station, r.climate_day, reason="NO_TAPE")
        if (r.station, r.climate_day) == ("SFO", BLOCK_FIRST)
        else r
        for r in world.census
    ]
    with pytest.raises(InputRefused, match="not COVERED"):
        _with_census(world, census).check()


def test_v2_uncounted_day_covered_in_final_census_is_disclosed_not_refused(tmp_path: Path) -> None:
    world = _world(tmp_path)
    lines = (tmp_path / "trigger.jsonl").read_text().splitlines()
    late = json.loads(lines[0])
    late["first_seen_ns"] = _early_ns(BLOCK_FIRST) + 2 * 86_400 * _NS  # listed after D-1 12:00Z
    extra = [
        {
            "station": s,
            "climate_day": (TRIGGER - dt.timedelta(days=1)).isoformat(),
            "reason": "COVERED",
            "first_seen_ns": 0,
        }
        for s in MAKER_STATIONS
    ]
    rows = [json.dumps(late), *lines[1:], *(json.dumps(r) for r in extra)]
    (tmp_path / "trigger.jsonl").write_text("\n".join(rows) + "\n")
    fields = v2_fields(
        trigger_rows_path="trigger.jsonl",
        trigger_rows_sha256=_sha(tmp_path / "trigger.jsonl"),
        census_days_sha256=world.fs.census_days_sha256,
        truth_csv_sha256=world.fs.truth_csv_sha256,
        cross_check_sha256=world.fs.cross_check_sha256,
    )
    fs = parse_frozen_block_v2(v2_text(fields))
    disclosed = World(fs, tmp_path, world.census).check()
    assert disclosed == [(late["station"], dt.date.fromisoformat(late["climate_day"]))]


def test_v2_field_set_equals_doc_a_template() -> None:
    from scripts.analysis import maker_stage0_frozen as frozen

    assert frozen._FIELDS_V2 == (
        "stations", "block_first_day", "trigger_day", "trigger_rows_path",
        "trigger_rows_sha256", "census_days_path", "census_days_sha256", "truth_csv_path",
        "truth_csv_sha256", "cross_check_path", "cross_check_sha256", "last_final_day", "dates",
    )  # fmt: skip
