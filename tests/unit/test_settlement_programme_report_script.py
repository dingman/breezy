"""CLI script tests for settlement programme reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from breezy.settlement.reporting import EvidenceStratumMismatchError

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())
import settlement_programme_report


def _write_inputs(tmp_path: Path, *, missing_stratum: bool = False) -> tuple[Path, Path, Path]:
    cells = {
        city: {
            "[0,1)": "NO_GO" if city == "MDW" else "GO",
            "[1,2)": "GO",
            "[2,3)": "GO",
            "[3,5)": "GO",
            "[5,inf)": "GO",
        }
        for city in ("LAX", "MDW", "MIA", "NYC", "SFO")
    }
    evidence_figures = {}
    for stratum in ("[0,1)", "[1,2)", "[2,3)", "[3,5)", "[5,inf)"):
        evidence_figures[stratum] = {
            "availability": "REPORTED",
            "cases": 240,
            "agreements": 238,
            "wilson_lower": "0.9710",
            "break_even": "0.981176",
            "signed_error_direction": "METAR_ABOVE_CLI",
            "mean_signed_error": "0.14",
            "power_floor": {"floor_n": 200, "anchor": "0.9800", "met": "MET"},
            "note": "fixture",
        }
    evidence_figures["[0,1)"]["signed_error_direction"] = "METAR_BELOW_CLI"
    if missing_stratum:
        del evidence_figures["[1,2)"]
    evidence = {
        "evaluation_index": 1,
        "entries": [
            {
                "city": city,
                "evaluation_index": 1,
                "tape_window": "2020-01-01..2026-08-26",
                "figures": evidence_figures,
            }
            for city in ("LAX", "MDW", "MIA", "NYC", "SFO")
        ],
    }
    cells_path = tmp_path / "cells.json"
    evidence_path = tmp_path / "evidence.json"
    output = tmp_path / "report.md"
    cells_path.write_text(json.dumps(cells), encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    return cells_path, evidence_path, output


def test_main_writes_report_and_both_sidecars(tmp_path: Path) -> None:
    cells, evidence, output = _write_inputs(tmp_path)

    exit_code = settlement_programme_report.main(
        [
            "--cells",
            str(cells),
            "--evidence",
            str(evidence),
            "--output",
            str(output),
            "--generated-at-utc",
            "2026-08-27T00:00:00Z",
        ]
    )

    assert exit_code == 0
    assert output.exists()
    assert output.with_suffix(output.suffix + ".sha256").exists()
    assert output.with_suffix(output.suffix + ".meta.json").exists()
    assert output.with_suffix(output.suffix + ".sha256").read_text(encoding="utf-8").strip()


def test_main_exits_zero_when_gaps_are_stated(tmp_path: Path) -> None:
    cells, evidence, output = _write_inputs(tmp_path)
    data = json.loads(evidence.read_text(encoding="utf-8"))
    data["entries"][1]["figures"]["[1,2)"]["availability"] = "NOT_DERIVED"
    data["entries"][1]["figures"]["[1,2)"]["cases"] = None
    data["entries"][1]["figures"]["[1,2)"]["agreements"] = None
    data["entries"][1]["figures"]["[1,2)"]["wilson_lower"] = None
    data["entries"][1]["figures"]["[1,2)"]["break_even"] = None
    data["entries"][1]["figures"]["[1,2)"]["signed_error_direction"] = "NOT_DERIVED"
    data["entries"][1]["figures"]["[1,2)"]["mean_signed_error"] = None
    evidence.write_text(json.dumps(data), encoding="utf-8")

    exit_code = settlement_programme_report.main(
        [
            "--cells",
            str(cells),
            "--evidence",
            str(evidence),
            "--output",
            str(output),
            "--generated-at-utc",
            "2026-08-27T00:00:00Z",
        ]
    )

    assert exit_code == 0
    assert "STRATUM_FIGURE_NOT_DERIVED" in output.read_text(encoding="utf-8")


def test_main_exits_two_when_the_builder_refuses(tmp_path: Path) -> None:
    cells, evidence, output = _write_inputs(tmp_path)
    data = json.loads(evidence.read_text(encoding="utf-8"))
    data["entries"] = [entry for entry in data["entries"] if entry["city"] != "MDW"]
    evidence.write_text(json.dumps(data), encoding="utf-8")

    exit_code = settlement_programme_report.main(
        [
            "--cells",
            str(cells),
            "--evidence",
            str(evidence),
            "--output",
            str(output),
            "--generated-at-utc",
            "2026-08-27T00:00:00Z",
        ]
    )

    assert exit_code == 2
    assert not output.exists()


def test_loader_rejects_an_evidence_entry_missing_a_stratum(tmp_path: Path) -> None:
    _cells, evidence, _output = _write_inputs(tmp_path, missing_stratum=True)

    try:
        settlement_programme_report.load_city_evidence(evidence)
    except EvidenceStratumMismatchError as exc:
        assert "[1,2)" in str(exc)
    else:
        raise AssertionError("missing stratum was accepted")


def test_loader_rejects_an_unknown_cell_classification(tmp_path: Path) -> None:
    cells, _evidence, _output = _write_inputs(tmp_path)
    data = json.loads(cells.read_text(encoding="utf-8"))
    data["MDW"]["[0,1)"] = "MAYBE"
    cells.write_text(json.dumps(data), encoding="utf-8")

    try:
        settlement_programme_report.load_city_cells(cells)
    except ValueError as exc:
        assert "MAYBE" in str(exc)
    else:
        raise AssertionError("unknown classification was accepted")
