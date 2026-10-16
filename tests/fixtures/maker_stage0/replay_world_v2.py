"""MAKER-S2 second look (C6/D11): a v2 (``FROZEN_DATE_SET_V2``) fixture world, files only.

Block 2: ``block_first_day`` 2026-10-14 .. trigger 2026-11-04, all four stations, every day COVERED
and trigger-counted. Truth CSV, cross-check parquet, census, trigger rows and the amendment are
written from the fixture itself and every pinned hash is computed from those files. The trigger
rows must live under the repo root (the v2 pin is repo-relative), so the caller passes the repo;
committing that file keeps the tree clean. No real catalog, truth, node log or network.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pyarrow as pa
import pyarrow.parquet as pq

from breezy.analysis.maker_tape_census import CensusedDay
from scripts.analysis.maker_stage0_inputs import MAKER_STATIONS
from tests.fixtures.maker_stage0 import make_census_fixture as fx
from tests.fixtures.maker_stage0 import replay_world as rw
from tests.fixtures.maker_stage0.frozen_v2 import BLOCK_FIRST, TRIGGER, days, v2_fields, v2_text

TRIGGER_REL: Final[str] = "docs/evidence/trigger_rows.jsonl"
TRUTH_TMAX_F: Final[int] = 70
_NS: Final[int] = 1_000_000_000
_CSV_HEAD: Final[str] = "station,climate_day,tmax_f,tmax_flag,correction_flag,product_sha256\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _early_ns(day: dt.date) -> int:
    moment = dt.datetime.combine(day - dt.timedelta(days=1), dt.time(6), tzinfo=dt.UTC)
    return int(moment.timestamp()) * _NS


@dataclass(frozen=True)
class WorldV2:
    root: Path
    census: Path
    census_rows: list[CensusedDay]
    unit: Path
    truth: Path
    cross_check: Path
    nbp_root: Path
    node_log_dir: Path
    trigger_rows: Path
    amendment: Path
    amendment_sha: str


def _write_cross(root: Path, tmax_f: int) -> Path:
    keys = [(s, d) for d in days() for s in MAKER_STATIONS]
    table = pa.table(
        {
            "station": [s for s, _ in keys],
            "climate_day": pa.array([d for _, d in keys], type=pa.date32()),
            "status": ["FINAL"] * len(keys),
            "tmax_f": [tmax_f] * len(keys),
        }
    )
    cross = root / "cross.parquet"
    pq.write_table(table, cross)
    return cross


def _write_csv(root: Path, tmax_f: int) -> Path:
    keys = [(s, d) for d in days() for s in MAKER_STATIONS]
    csv_path = root / "truth.csv"
    csv_path.write_text(_CSV_HEAD + "".join(f"{s},{d},{tmax_f},,False,x\n" for s, d in keys))
    return csv_path


def _write_trigger(path: Path, late: frozenset[tuple[str, dt.date]]) -> None:
    """``late`` rows are first seen after D-1 12:00Z: COVERED later but not counted at trigger."""
    rows = [
        {
            "station": s,
            "climate_day": d.isoformat(),
            "reason": "COVERED",
            "first_seen_ns": _early_ns(d) + (2 * 86_400 * _NS if (s, d) in late else 0),
        }
        for d in days(last=TRIGGER)
        for s in MAKER_STATIONS
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def build_world_v2(
    root: Path,
    repo: Path,
    *,
    cross_tmax_f: int = TRUTH_TMAX_F,
    late: frozenset[tuple[str, dt.date]] = frozenset(),
    overlap: bool = True,
) -> WorldV2:
    """Write the v2 world under ``root`` (trigger rows under ``repo``); returns the paths."""
    root.mkdir(parents=True, exist_ok=True)
    csv_path, cross = _write_csv(root, TRUTH_TMAX_F), _write_cross(root, cross_tmax_f)
    if not overlap:  # a cross-check holding only a day outside the licensed set: vacuous
        far = pa.table(
            {
                "station": ["SFO"],
                "climate_day": pa.array([dt.date(2026, 6, 30)], type=pa.date32()),
                "status": ["FINAL"],
                "tmax_f": [TRUTH_TMAX_F],
            }
        )
        pq.write_table(far, cross)
    rows = fx.census_grid(first_day=BLOCK_FIRST, n_days=len(days()))
    census = fx.write_census_fixture(root / "censused_days.jsonl", rows)
    trigger = repo / TRIGGER_REL
    _write_trigger(trigger, late)
    fields = v2_fields(
        trigger_rows_path=TRIGGER_REL,
        trigger_rows_sha256=_sha(trigger),
        census_days_sha256=_sha(census),
        truth_csv_sha256=_sha(csv_path),
        cross_check_sha256=_sha(cross),
    )
    amendment = root / "amendment_v2.md"
    amendment.write_text(v2_text(fields))
    logs = root / "node_logs"
    logs.mkdir(exist_ok=True)
    return WorldV2(
        root=root,
        census=census,
        census_rows=rows,
        unit=fx.write_unit_fixture(root / "unit.json", "CONTRACTS"),
        truth=csv_path,
        cross_check=cross,
        nbp_root=rw.build_nbp(root),
        node_log_dir=logs,
        trigger_rows=trigger,
        amendment=amendment,
        amendment_sha=_sha(amendment),
    )
