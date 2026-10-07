"""``metar_routine_store.py rederive``: offline re-parse of the stored raw ``metar`` column.

Existing store files were written with the probe's looser T-group parse. ``rederive`` recomputes
``tmpf`` / ``tgroup_c`` / ``tmpf_source`` with the LIVE parser from the stored raw METAR, rewrites
files atomically and updates the manifest sha256. Tests use tmp copies only; sockets are blocked
by ``tests/conftest.py`` so a network touch fails loudly.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCRIPT_PATH: Final[Path] = REPO_ROOT / "scripts/archive/metar_routine_store.py"
for _sibling in ("analysis", "venue", "archive"):
    _path = str(REPO_ROOT / "scripts" / _sibling)
    if _path not in sys.path:
        sys.path.insert(0, _path)

COLUMNS: Final[tuple[str, ...]] = (
    "station", "valid_utc", "tmpf", "tgroup_c", "report_type", "tmpf_source", "metar",
)  # fmt: skip
#: (valid_utc, tmpf, tgroup_c, tmpf_source, raw metar) as an OLD-parse store holds it
_OLD_ROWS: Final[list[tuple[str, str, str, str, str]]] = [
    # old parse: a 4-digit group counted; live needs all 8 digits -> tgroup becomes column
    ("2021-02-01T00:51Z", "32", "0.0", "tgroup", "KNYC 011951Z CLR RMK AO2 T0000"),
    # unchanged: a full group after RMK
    ("2021-02-01T01:51Z", "35", "1.7", "tgroup", "KNYC X RMK T00170022"),
    # old parse needed RMK; live searches the whole string -> column becomes tgroup (172 -> 63 F)
    ("2021-02-01T02:51Z", "63", "", "column", "KNYC X T01720022"),
    # unchanged: no group at all, the column was missing
    ("2021-02-01T03:51Z", "", "", "missing", "KNYC X RMK AO2"),
    # unchanged: no group, the column value was kept
    ("2021-02-01T04:51Z", "40", "", "column", "KNYC X RMK AO2"),
]


@pytest.fixture(scope="module")
def store() -> ModuleType:
    spec = importlib.util.spec_from_file_location("breezy_script_metar_store_rd", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_old_store(root: Path) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for valid, tmpf, tgroup, source, raw in _OLD_ROWS:
        writer.writerow(["KNYC", valid, tmpf, tgroup, "3", source, raw])
    data = out.getvalue().encode("utf-8")
    path = root / "KNYC" / "2021.csv"
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    manifest = {
        "schema": "metar_routine_store/v1",
        "entries": {
            "KNYC/2021": {
                "path": "KNYC/2021.csv",
                "sha256": hashlib.sha256(data).hexdigest(),
                "rows": len(_OLD_ROWS),
                "window": ["2021-01-01", "2022-01-01"],
                "fetched_at": "2026-10-07T00:00:00+00:00",
            }
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return data


def _rederive(
    store: ModuleType, tmp_path: Path, mode: str, root: Path | None = None
) -> tuple[int, dict[str, Any]]:
    report = tmp_path / f"report_{mode}.json"
    code = store.main(
        [
            "rederive",
            f"--{mode}",
            "--archive-root", str(root or tmp_path / "root"),
            "--report-json", str(report),
            "--stations", "KNYC",
            "--years", "2021",
        ]
    )  # fmt: skip
    return code, json.loads(report.read_text())


def test_dry_run_reports_the_rows_that_would_change_and_writes_nothing(
    store: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    before = _write_old_store(root)
    manifest_before = (root / "manifest.json").read_bytes()

    code, report = _rederive(store, tmp_path, "dry-run")

    assert code == 0 and report["status"] == "dry_run"
    assert report["rows_total"] == 5 and report["rows_changed"] == 2
    assert report["tgroup_to_column"] == 1 and report["column_or_missing_to_tgroup"] == 1
    assert report["tgroup_value_changed"] == 0
    assert report["per_station_year"]["KNYC/2021"]["rows_changed"] == 2
    assert (root / "KNYC" / "2021.csv").read_bytes() == before
    assert (root / "manifest.json").read_bytes() == manifest_before


def test_apply_rewrites_the_changed_rows_and_the_manifest_sha(
    store: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    _write_old_store(root)

    code, report = _rederive(store, tmp_path, "apply")

    assert code == 0 and report["status"] == "applied" and report["rows_changed"] == 2
    data = (root / "KNYC" / "2021.csv").read_bytes()
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["entries"]["KNYC/2021"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert not list(root.rglob("*.tmp"))
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    assert [r["valid_utc"] for r in rows] == [r[0] for r in _OLD_ROWS]  # order and instants kept
    assert [r["metar"] for r in rows] == [r[4] for r in _OLD_ROWS]
    assert [(r["tmpf"], r["tgroup_c"], r["tmpf_source"]) for r in rows] == [
        ("32", "", "column"),  # the old T-group tmpf is kept as the column value
        ("35", "1.7", "tgroup"),
        ("63", "17.2", "tgroup"),
        ("", "", "missing"),
        ("40", "", "column"),
    ]


def test_the_rederived_store_reads_through_the_helper(store: ModuleType, tmp_path: Path) -> None:
    import datetime as dt

    root = tmp_path / "root"
    _write_old_store(root)
    _rederive(store, tmp_path, "apply")

    rows = store.read_routine_metar("KNYC", dt.date(2021, 2, 1), dt.date(2021, 2, 2), root)

    assert [r.tmpf_source for r in rows] == ["column", "tgroup", "tgroup", "missing", "column"]


def test_apply_is_idempotent(store: ModuleType, tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write_old_store(root)
    _rederive(store, tmp_path, "apply")
    once = (root / "KNYC" / "2021.csv").read_bytes()

    code, report = _rederive(store, tmp_path, "apply")

    assert code == 0 and report["rows_changed"] == 0
    assert (root / "KNYC" / "2021.csv").read_bytes() == once


def test_a_tampered_station_year_is_refused_and_nothing_is_written(
    store: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    _write_old_store(root)
    (root / "KNYC" / "2021.csv").write_text("tampered")

    code, report = _rederive(store, tmp_path, "apply")

    assert code == 2 and "sha256" in report["error"]
    assert (root / "KNYC" / "2021.csv").read_text() == "tampered"


def test_a_station_year_missing_from_the_manifest_is_refused(
    store: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    _write_old_store(root)

    report_path = tmp_path / "r.json"
    code = store.main(
        ["rederive", "--dry-run", "--archive-root", str(root), "--report-json", str(report_path),
         "--stations", "KNYC", "--years", "2022"]
    )  # fmt: skip

    assert (
        code == 2
        and "not in the routine-METAR archive" in json.loads(report_path.read_text())["error"]
    )
