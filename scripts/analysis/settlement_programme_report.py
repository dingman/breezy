"""Render a settlement programme report from strict JSON inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from breezy.settlement.coverage import CellClassification
from breezy.settlement.programme import ProgrammeInputError, determine_programme
from breezy.settlement.reporting import (
    CityEvidence,
    CityEvidenceTable,
    FigureAvailability,
    FigureProvenance,
    PowerFloor,
    PowerFloorStatus,
    ReportStamp,
    SettlementReportError,
    SignedErrorDirection,
    Stratum,
    StratumFigure,
    build_programme_report,
    render_markdown,
)


def load_city_cells(path: Path) -> dict[str, dict[str, CellClassification]]:
    data = _load_object(path)
    result: dict[str, dict[str, CellClassification]] = {}
    for city, cells in data.items():
        if not isinstance(city, str) or not isinstance(cells, dict):
            raise TypeError("cells JSON must be an object of city -> stratum object")
        result[city] = {}
        for stratum, value in cells.items():
            if not isinstance(stratum, str) or not isinstance(value, str):
                raise TypeError(f"invalid cell entry for {city!r}")
            try:
                result[city][stratum] = CellClassification[value]
            except KeyError as exc:
                raise ValueError(f"unknown CellClassification {value!r}") from exc
    return result


def load_city_evidence(path: Path) -> CityEvidenceTable:
    data = _load_object(path)
    _assert_keys(data, {"evaluation_index", "entries"}, label="evidence")
    entries = data["entries"]
    if not isinstance(entries, list):
        raise TypeError("evidence.entries must be a list")
    parsed = tuple(_parse_evidence_entry(entry) for entry in entries)
    return CityEvidenceTable(entries=parsed, evaluation_index=_int(data["evaluation_index"]))


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cells", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--generated-at-utc", required=True)
    return parser.parse_args(argv)


def write_sidecars(*, output: Path, command: str, inputs: Mapping[str, str]) -> None:
    body = output.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(digest + "\n", encoding="utf-8")
    output.with_suffix(output.suffix + ".meta.json").write_text(
        json.dumps(
            {
                "command": command,
                "output_sha256": digest,
                "inputs": dict(sorted(inputs.items())),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        cells = load_city_cells(args.cells)
        evidence = load_city_evidence(args.evidence)
        determination = determine_programme(
            in_scope_cities=tuple(sorted(cells)),
            city_cells=cells,
            evaluations_elapsed_by_city={
                entry.city: entry.evaluation_index for entry in evidence.entries
            },
        )
        cells_sha = _sha256_file(args.cells)
        evidence_sha = _sha256_file(args.evidence)
        report = build_programme_report(
            determination,
            evidence,
            stamp=ReportStamp(
                generated_at_utc=args.generated_at_utc,
                cells_sha256=cells_sha,
                evidence_sha256=evidence_sha,
                command="settlement_programme_report",
            ),
        )
    except (ProgrammeInputError, SettlementReportError):
        return 2
    rendered = render_markdown(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    write_sidecars(
        output=args.output,
        command="settlement_programme_report",
        inputs={"cells": _sha256_file(args.cells), "evidence": _sha256_file(args.evidence)},
    )
    return 0


def _parse_evidence_entry(entry: object) -> CityEvidence:
    if not isinstance(entry, dict):
        raise TypeError("evidence entry must be an object")
    _assert_keys(entry, {"city", "evaluation_index", "tape_window", "figures"}, label="entry")
    figures = entry["figures"]
    if not isinstance(figures, dict):
        raise TypeError("entry.figures must be an object")
    parsed = {_stratum(key): _parse_figure(key, value) for key, value in figures.items()}
    return CityEvidence(
        city=_str(entry["city"]),
        figures=parsed,
        evaluation_index=_int(entry["evaluation_index"]),
        tape_window=_str(entry["tape_window"]),
    )


def _parse_figure(stratum_value: object, data: object) -> StratumFigure:
    if not isinstance(data, dict):
        raise TypeError("figure must be an object")
    _assert_keys(
        data,
        {
            "availability",
            "cases",
            "agreements",
            "wilson_lower",
            "break_even",
            "signed_error_direction",
            "mean_signed_error",
            "power_floor",
            "note",
        },
        optional={"provenance"},
        label="figure",
    )
    power = data["power_floor"]
    if not isinstance(power, dict):
        raise TypeError("power_floor must be an object")
    _assert_keys(power, {"floor_n", "anchor", "met"}, label="power_floor")
    return StratumFigure(
        stratum=_stratum(stratum_value),
        availability=FigureAvailability[_str(data["availability"])],
        provenance=FigureProvenance[
            _str(
                data.get(
                    "provenance",
                    FigureProvenance.HINDSIGHT_STRATIFIED_BY_FINAL_METAR_MAX.name,
                )
            )
        ],
        cases=_optional_int(data["cases"]),
        agreements=_optional_int(data["agreements"]),
        wilson_lower=_optional_str(data["wilson_lower"]),
        break_even=_optional_str(data["break_even"]),
        signed_error_direction=SignedErrorDirection[_str(data["signed_error_direction"])],
        mean_signed_error=_optional_str(data["mean_signed_error"]),
        power_floor=PowerFloor(
            floor_n=_optional_int(power["floor_n"]),
            anchor=_optional_str(power["anchor"]),
            met=PowerFloorStatus[_str(power["met"])],
        ),
        note=_str(data["note"]),
    )


def _load_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return data


def _assert_keys(
    data: Mapping[str, object],
    required: set[str],
    *,
    label: str,
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    keys = set(data)
    if keys - allowed or required - keys:
        raise ValueError(
            f"{label} keys mismatch: missing={sorted(required - keys)!r}, "
            f"unexpected={sorted(keys - allowed)!r}"
        )


def _stratum(value: object) -> Stratum:
    text = _str(value)
    for stratum in Stratum:
        if stratum.value == text:
            return stratum
    raise ValueError(f"unknown Stratum {text!r}")


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"expected string, got {value!r}")
    return value


def _int(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError(f"expected integer, got {value!r}")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _int(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return _str(value)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
