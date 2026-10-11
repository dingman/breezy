"""EXEC-PAR BG-5c WP-D (R8.1, A6): the settlement-truth reader, the held-side outcome and the
final-outcome cache.

The truth store is the F2 dataset ``derived/fq-truth/truth_cli_finals.csv`` (schema
``fq_truth_cli/v1``), not SQLite: it is read-only by opening the file for reading only, one
fresh handle per read. Every non-final answer is ``None``, never a loss.
"""

from __future__ import annotations

import ast
import datetime as dt
import os
import stat
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.runtime import exec_par_settled_truth as mod
from breezy.runtime.exec_par_settled_truth import (
    CacheEvent,
    F2CsvTruthReader,
    FinalTruthCache,
    TruthReadError,
    TruthRecord,
    held_outcome,
)
from breezy.settlement.trial_scorer import FilledTrial, ScoredTrial, score_trial
from tests.unit.test_capture_settlement import _climate_day

DAY = dt.date(2026, 10, 12)
HEADER = (
    "station,city,climate_day,tmax_f,tmax_flag,correction_flag,issued_at_utc,"
    "product_sha256,revision_fetch_date,revision_sha256"
)
YES_ID = "KXHIGHNY-26OCT12-B72.PMUS"
NO_ID = "KXHIGHNY-26OCT12-B72^no.PMUS"
FACTS = WeatherBucketFacts(
    settlement_station="NYC", climate_day=DAY, measure=Measure.HIGH, lower_f=70, upper_f=74
)


def row(
    tmax: str = "72", flag: str = "", corr: str = "False", sha: str = "p1", day: str = ""
) -> str:
    when = day or DAY.isoformat()
    return f"NYC,New York,{when},{tmax},{flag},{corr},2026-10-13T07:27:00+00:00,{sha},2026-10-13,r1"


def write_csv(path: Path, *rows: str, header: str = HEADER) -> Path:
    path.write_text("\n".join((header, *rows)) + "\n", encoding="utf-8")
    return path


def rec(tmax: int | None, flag: str = "", token: str = "p1", station: str = "NYC") -> TruthRecord:
    return TruthRecord(
        station=station,
        climate_day=DAY,
        tmax_f=tmax,
        tmax_flag=flag,
        correction=False,
        token=token,
    )


def final(tmax: int = 72, token: str = "p1") -> TruthRecord:
    return rec(tmax, token=token)


# -- held-side outcome (A6): the leg comes from the instrument id ---------------------------


@pytest.mark.parametrize(
    ("instrument_id", "tmax", "held"),
    [
        (YES_ID, 72, True),  # YES, HIGH inside the rung -> YES wins
        (YES_ID, 80, False),  # YES, HIGH outside -> YES loses
        (NO_ID, 72, False),  # NO, HIGH inside -> NO loses
        (NO_ID, 80, True),  # NO, HIGH outside -> NO wins
        (YES_ID, 70, True),  # closed at both ends
        (YES_ID, 74, True),
        (NO_ID, 74, False),
        (NO_ID, 75, True),
    ],
)
def test_held_outcome_flips_exactly_once_for_the_no_leg(
    instrument_id: str, tmax: int, held: bool
) -> None:
    assert held_outcome(instrument_id, FACTS, final(tmax)) is held


@pytest.mark.parametrize("instrument_id", [YES_ID, NO_ID])
@pytest.mark.parametrize("tmax", [60, 70, 72, 74, 90])
def test_held_outcome_agrees_with_the_settlement_scorer(instrument_id: str, tmax: int) -> None:
    """Pins the sign against ``trial_scorer.score_trial`` (the same rule ``fq_scorer`` reuses)."""
    trial = FilledTrial(
        trial_id="t",
        station="NYC",
        climate_day=DAY.isoformat(),
        instrument_id=instrument_id,
        bucket=FACTS,
        fill_px=Decimal("0.5"),
        fee=Decimal("0.01"),
        qty=Decimal(1),
        filled_at_ns=1,
        entry_ask=Decimal("0.5"),
        scheduled_release_at_ns=1,
    )
    scored = score_trial(
        trial, _climate_day("NYC", DAY, tmax=tmax, tmin_f=40, tavg_f=tmax - 5), now_ns=10**19
    )
    assert isinstance(scored, ScoredTrial)
    assert held_outcome(instrument_id, FACTS, final(tmax)) is scored.held


@pytest.mark.parametrize(
    "record",
    [
        None,
        rec(None, "M", "x"),
        rec(72, "T", "x"),
    ],
)
@pytest.mark.parametrize("instrument_id", [YES_ID, NO_ID])
def test_a_missing_or_non_final_record_is_no_outcome_never_a_loss(
    record: TruthRecord | None, instrument_id: str
) -> None:
    assert held_outcome(instrument_id, FACTS, record) is None


def test_a_low_measure_has_no_outcome_from_a_tmax_only_store() -> None:
    low = WeatherBucketFacts(
        settlement_station="NYC", climate_day=DAY, measure=Measure.LOW, lower_f=60, upper_f=64
    )
    assert held_outcome(YES_ID, low, final(62)) is None


def test_the_record_must_be_for_the_facts_station_and_day() -> None:
    other = rec(72, station="LAX")
    assert held_outcome(YES_ID, FACTS, other) is None


# -- the F2 csv reader -----------------------------------------------------------------------


def test_reader_returns_the_final_row_for_the_station_day(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "t.csv", row("72"), row("65", day="2026-10-11"))
    record = F2CsvTruthReader(path).read("NYC", DAY)
    assert record is not None and record.tmax_f == 72 and record.is_final_grade
    assert record.station == "NYC" and record.climate_day == DAY


def test_reader_returns_none_for_an_absent_station_day(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "t.csv", row("72"))
    reader = F2CsvTruthReader(path)
    assert reader.read("NYC", dt.date(2026, 10, 13)) is None
    assert reader.read("LAX", DAY) is None


def test_a_sentinel_tmax_is_a_record_that_is_not_final_grade(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "t.csv", row("", flag="M"))
    record = F2CsvTruthReader(path).read("NYC", DAY)
    assert record is not None and not record.is_final_grade and record.tmax_f is None


def test_reader_fails_on_a_missing_file_a_bad_header_and_a_garbled_row(tmp_path: Path) -> None:
    with pytest.raises(TruthReadError):
        F2CsvTruthReader(tmp_path / "absent.csv").read("NYC", DAY)
    with pytest.raises(TruthReadError):
        F2CsvTruthReader(write_csv(tmp_path / "h.csv", row(), header="a,b")).read("NYC", DAY)
    with pytest.raises(TruthReadError):
        F2CsvTruthReader(write_csv(tmp_path / "g.csv", row("hot"))).read("NYC", DAY)


def test_conflicting_duplicate_rows_are_an_error_not_a_pick(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "t.csv", row("72"), row("73", sha="p2"))
    with pytest.raises(TruthReadError):
        F2CsvTruthReader(path).read("NYC", DAY)


def test_reader_works_on_a_read_only_file_in_a_read_only_directory(tmp_path: Path) -> None:
    store = tmp_path / "ro"
    store.mkdir()
    path = write_csv(store / "t.csv", row("72"))
    before = path.stat().st_mtime_ns
    path.chmod(stat.S_IRUSR)
    store.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        assert F2CsvTruthReader(path).read("NYC", DAY) is not None
    finally:
        store.chmod(stat.S_IRWXU)
    assert path.stat().st_mtime_ns == before
    assert sorted(os.listdir(store)) == ["t.csv"]


def test_a_changed_product_or_value_changes_the_revision_token(tmp_path: Path) -> None:
    first = F2CsvTruthReader(write_csv(tmp_path / "a.csv", row("72", sha="p1"))).read("NYC", DAY)
    revised_sha = F2CsvTruthReader(write_csv(tmp_path / "b.csv", row("72", sha="p2"))).read(
        "NYC", DAY
    )
    revised_val = F2CsvTruthReader(write_csv(tmp_path / "c.csv", row("73", sha="p1"))).read(
        "NYC", DAY
    )
    corrected = F2CsvTruthReader(
        write_csv(tmp_path / "d.csv", row("72", sha="p1", corr="True"))
    ).read("NYC", DAY)
    assert first is not None and revised_sha is not None
    assert revised_val is not None and corrected is not None
    assert len({first.token, revised_sha.token, revised_val.token, corrected.token}) == 4


def test_the_truth_modules_import_no_network_and_name_no_evidence_path() -> None:
    for name in ("exec_par_settled_truth", "exec_par_settled_pnl_driver"):
        source = Path(mod.__file__).with_name(f"{name}.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not imported & {"urllib", "socket", "httpx", "requests", "aiohttp", "sqlite3"}
        assert "docs/evidence" not in source
        assert "asdict" not in source
        assert "breezy.analysis" not in source


# -- the final-outcome cache -----------------------------------------------------------------

KEY = ("NYC", DAY)


def test_only_final_outcomes_are_cached() -> None:
    cache = FinalTruthCache()
    assert cache.land(KEY, None) is CacheEvent.IGNORED
    assert cache.land(KEY, rec(None, "M", "x")) is CacheEvent.IGNORED
    assert cache.get(KEY) is None
    assert cache.land(KEY, final(72)) is CacheEvent.STORED
    assert cache.get(KEY) == final(72)


def test_the_same_value_is_unchanged_and_a_revised_value_replaces_the_entry() -> None:
    cache = FinalTruthCache()
    cache.land(KEY, final(72, "p1"))
    assert cache.land(KEY, final(72, "p1")) is CacheEvent.UNCHANGED
    assert cache.land(KEY, final(73, "p2")) is CacheEvent.REVISED
    assert cache.get(KEY) == final(73, "p2")


def test_a_cached_final_that_the_store_no_longer_shows_as_final_is_invalidated() -> None:
    cache = FinalTruthCache()
    cache.land(KEY, final(72))
    assert cache.land(KEY, None) is CacheEvent.INVALIDATED
    assert cache.get(KEY) is None
    cache.land(KEY, final(72))
    assert cache.land(KEY, rec(None, "M", "y")) is CacheEvent.INVALIDATED
    assert cache.get(KEY) is None
