"""MAKER-S2 WP2 -- S-6 verify-first (alignment + vintage-age lines only), synthetic store."""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Sequence
from pathlib import Path

import pytest

from breezy.persistence.nbp_derived_store import DerivedNbpRow, partition_path, write_partition
from scripts.analysis.maker_stage0_verify_first import (
    AlignmentLine,
    VintageAgeLine,
    verify_first_s6,
)
from scripts.analysis.nbp_backfill import derive_rows_for_bulletin

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nbm"
RAW_SHA = {13: "sha13", 19: "sha19", 1: "sha01"}
LAST_MODIFIED = {
    13: "Mon, 28 Sep 2026 14:04:00 GMT",
    19: "Mon, 28 Sep 2026 20:17:00 GMT",
    1: "Tue, 29 Sep 2026 02:04:00 GMT",
}
NS_PER_DAY = 86_400 * 10**9
DAY = dt.date(2026, 9, 29)


def _derive(hour: int, last_modified: str | None) -> tuple[DerivedNbpRow, ...]:
    text = (FIXTURES / f"nbptx_t{hour:02d}z_excerpt.txt").read_text()
    rows, _ = derive_rows_for_bulletin(
        text=text, source_host="fixture", last_modified=last_modified, fetched_at_ns=1,
        raw_sha256=RAW_SHA[hour], stations=frozenset({"KLAX", "KMDW", "KMIA", "KSFO"}),
    )  # fmt: skip
    return rows


def _shift(rows: Sequence[DerivedNbpRow], days: int) -> tuple[DerivedNbpRow, ...]:
    delta = days * NS_PER_DAY
    return tuple(
        dataclasses.replace(
            row,
            cycle_runtime_ns=row.cycle_runtime_ns + delta,
            valid_start_ns=row.valid_start_ns + delta,
            valid_end_ns=row.valid_end_ns + delta,
            available_at_ns=row.available_at_ns + delta,
        )
        for row in rows
    )


def _write(root: Path, rows: Sequence[DerivedNbpRow]) -> None:
    cycle = dt.datetime.fromtimestamp(rows[0].cycle_runtime_ns / 10**9, tz=dt.UTC)
    write_partition(rows, partition_path(root, cycle.date(), cycle.hour))


def test_verify_first_runs_only_on_2026_06_30_and_emits_no_fill_output(tmp_path: Path) -> None:
    june = dt.date(2026, 6, 30)
    shift = (june - DAY).days
    root = tmp_path / "june"
    for hour in (13, 19, 1):
        _write(root, _shift(_derive(hour, LAST_MODIFIED[hour]), shift))
    with pytest.raises(ValueError, match="2026-06-30"):
        verify_first_s6(root, DAY)
    report = verify_first_s6(root, june)
    assert report.climate_day == june
    assert {line.station for line in report.alignment} == {"LAX", "MDW", "MIA", "SFO"}
    assert all(line.matches_climate_day_for_txn for line in report.alignment)
    assert {line.instant for line in report.vintage_age} == {"16:50Z D-1", "00:00Z D", "02:50Z D"}
    assert all(line.within_tolerance for line in report.vintage_age)
    names = {f.name for f in dataclasses.fields(report)}
    assert names == {"climate_day", "alignment", "vintage_age"}
    forbidden = ("fill", "bid", "episode", "p_no", "p_yes", "truth")
    lines: tuple[AlignmentLine | VintageAgeLine, ...] = (*report.alignment, *report.vintage_age)
    for line in lines:
        assert not any(w in f.name for f in dataclasses.fields(line) for w in forbidden)
