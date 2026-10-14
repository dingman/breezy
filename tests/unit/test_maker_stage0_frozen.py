"""MAKER-S2 WP1: the FROZEN_DATE_SET parser (E5) and the verdict ledger (code-freeze clause).

Plan r4 delta (b) and (c). The amendment text here is a fixture; no real ruling is read.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from scripts.analysis.maker_stage0_frozen import (
    FrozenDateSet,
    FrozenSetRefused,
    assert_in_frozen_set,
    load_amendment,
    parse_frozen_block,
    rule_dates,
    verify_set_matches_rule,
)
from scripts.analysis.maker_stage0_inputs import TruthTable
from scripts.analysis.maker_stage0_ledger import (
    LedgerRefused,
    append_ledger_entry,
    ledger_refuses,
    load_addendum,
    tree_digest,
    void_run_dir,
)
from tests.fixtures.maker_stage0 import make_census_fixture as fx

FIRST = dt.date(2026, 9, 18)
SHA = "ab" * 32


def _rule_days(first: dt.date = FIRST, last: dt.date = dt.date(2026, 10, 13)) -> list[dt.date]:
    span = (last - first).days + 1
    return [
        d for d in (first + dt.timedelta(days=i) for i in range(span)) if d != dt.date(2026, 10, 1)
    ]


def _fields(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "stations": "LAX MDW MIA SFO",
        "first_replayable_day": FIRST.isoformat(),
        "truth_csv_path": "/x/truth_cli_finals.csv",
        "truth_csv_sha256": SHA,
        "last_final_day": "2026-10-13",
        "dates": _rule_days(),
    }
    base.update(over)
    return base


def _block(fields: Mapping[str, object]) -> str:
    lines = ["```FROZEN_DATE_SET"]
    for key in (
        "stations",
        "first_replayable_day",
        "truth_csv_path",
        "truth_csv_sha256",
        "last_final_day",
    ):
        lines.append(f"{key}: {fields[key]}")
    dates = fields["dates"]
    if isinstance(dates, str):
        lines.append(f"dates: {dates}")
    else:
        lines.append("dates:")
        lines.extend(d.isoformat() for d in cast("list[dt.date]", dates))
    lines.append("```")
    return "# ruling\nStatus: **FINAL**\n\n" + "\n".join(lines) + "\n\ntrailer\n"


def _truth(last: dt.date = dt.date(2026, 10, 13), sha: str = SHA) -> TruthTable:
    finals = {("SFO", d): 70 for d in _rule_days(last=last)}
    return TruthTable(
        finals=finals,
        csv_sha256=sha,
        run_copy=Path("/x/c.csv"),
        cross_check_sha256="0" * 64,
        n_overlap=0,
    )


# --- parser -------------------------------------------------------------------------------


def test_a_filled_block_parses() -> None:
    fs = parse_frozen_block(_block(_fields()))
    assert fs.stations == ("LAX", "MDW", "MIA", "SFO")
    assert fs.first_replayable_day == FIRST
    assert fs.truth_csv_sha256 == SHA
    assert fs.last_final_day == dt.date(2026, 10, 13)
    assert len(fs.dates) == 25 and dt.date(2026, 10, 1) not in fs.dates


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"dates": "<FILL: ISO dates>"}, "FILL"),
        ({"truth_csv_sha256": "<FILL>"}, "FILL"),
        ({"dates": [*_rule_days(), dt.date(2026, 10, 1)]}, "2026-10-01"),
        ({"dates": [*_rule_days(), dt.date(2026, 10, 14)]}, "2026-10-14"),
        ({"stations": "LAX MDW MIA NYC"}, "NYC"),
        ({"stations": "LAX MDW MIA"}, "stations"),
        ({"first_replayable_day": "2026-09-17"}, "first_replayable_day"),
        ({"dates": [dt.date(2026, 9, 17), *_rule_days()]}, "outside the rule"),
        ({"last_final_day": "2026-10-05", "dates": _rule_days()}, "outside the rule"),
        ({"dates": list(reversed(_rule_days()))}, "ascending"),
        ({"dates": [FIRST, FIRST]}, "ascending"),
        ({"truth_csv_sha256": "xyz"}, "sha256"),
    ],
)
def test_parser_fails_closed(over: dict[str, object], why: str) -> None:
    with pytest.raises(FrozenSetRefused, match=why):
        parse_frozen_block(_block(_fields(**over)))


def test_missing_or_duplicated_block_is_refused() -> None:
    with pytest.raises(FrozenSetRefused, match="exactly one"):
        parse_frozen_block("no block here")
    text = _block(_fields())
    with pytest.raises(FrozenSetRefused, match="exactly one"):
        parse_frozen_block(text + text)


def test_unknown_or_missing_field_is_refused() -> None:
    text = _block(_fields()).replace("last_final_day:", "last_day:")
    with pytest.raises(FrozenSetRefused, match="fields"):
        parse_frozen_block(text)


def test_the_draft_template_is_refused_even_with_its_placeholders_removed(tmp_path: Path) -> None:
    text = _block(_fields()).replace("**FINAL**", "**DRAFT rev 2**")
    path = tmp_path / "amend.md"
    path.write_text(text)
    with pytest.raises(FrozenSetRefused, match="DRAFT"):
        load_amendment(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_replay_refuses_day_outside_frozen_set_or_amendment_sha_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "amend.md"
    path.write_text(_block(_fields()))
    good = hashlib.sha256(path.read_bytes()).hexdigest()
    fs = load_amendment(path, good)
    assert_in_frozen_set(fs, "SFO", dt.date(2026, 9, 18))
    for station, day, why in [
        ("SFO", dt.date(2026, 10, 1), "2026-10-01"),
        ("SFO", dt.date(2026, 10, 14), "not in the frozen"),
        ("SFO", dt.date(2026, 9, 17), "not in the frozen"),
        ("NYC", dt.date(2026, 9, 20), "NYC"),
        ("DEN", dt.date(2026, 9, 20), "not in the frozen"),
    ]:
        with pytest.raises(FrozenSetRefused, match=why):
            assert_in_frozen_set(fs, station, day)
    with pytest.raises(FrozenSetRefused, match="amendment sha"):
        load_amendment(path, "0" * 64)
    path.write_text(path.read_text() + "tampered\n")
    with pytest.raises(FrozenSetRefused, match="amendment sha"):
        load_amendment(path, good)


# --- rule ---------------------------------------------------------------------------------


def test_rule_excludes_the_sealed_day_and_caps_at_the_last_allowed_day() -> None:
    assert rule_dates(FIRST, dt.date(2026, 11, 2)) == tuple(_rule_days())
    assert rule_dates(FIRST, dt.date(2026, 9, 25)) == tuple(_rule_days(last=dt.date(2026, 9, 25)))
    assert rule_dates(dt.date(2026, 9, 19), dt.date(2026, 10, 13))[0] == dt.date(2026, 9, 19)
    assert len(rule_dates(FIRST, dt.date(2026, 10, 13))) == 25


def test_frozen_set_equals_rule_applied_to_pinned_census_and_truth() -> None:
    fs = parse_frozen_block(_block(_fields()))
    census = fx.census_grid(first_day=FIRST, n_days=26)  # 09-18 .. 10-13
    verify_set_matches_rule(fs, census, _truth())
    # A truth CSV whose sha differs from the pinned one.
    with pytest.raises(FrozenSetRefused, match="truth csv sha256"):
        verify_set_matches_rule(fs, census, _truth(sha="cd" * 32))
    # last_final_day not the truth's last FINAL day (capped by 10-13).
    with pytest.raises(FrozenSetRefused, match="last_final_day"):
        verify_set_matches_rule(fs, census, _truth(last=dt.date(2026, 10, 9)))
    # A set that dropped a date the rule includes.
    short = parse_frozen_block(_block(_fields(dates=_rule_days()[:-1])))
    with pytest.raises(FrozenSetRefused, match="differs from the rule"):
        verify_set_matches_rule(short, census, _truth())
    # A census that lacks a set date.
    thin = fx.census_grid(first_day=FIRST, n_days=20)
    with pytest.raises(FrozenSetRefused, match="census"):
        verify_set_matches_rule(fs, thin, _truth())


def test_truth_beyond_the_last_allowed_day_is_capped_not_followed() -> None:
    fs = parse_frozen_block(_block(_fields(last_final_day="2026-10-20")))
    census = fx.census_grid(first_day=FIRST, n_days=26)
    verify_set_matches_rule(fs, census, _truth(last=dt.date(2026, 10, 20)))


def test_frozen_dataclass_is_immutable() -> None:
    fs = parse_frozen_block(_block(_fields()))
    assert isinstance(fs, FrozenDateSet)
    with pytest.raises(AttributeError):
        fs.dates = ()  # type: ignore[misc]


# --- ledger -------------------------------------------------------------------------------

NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.UTC)


def _run(runs_root: Path, run_id: str, *, void: bool, files: tuple[str, ...] = ()) -> Path:
    directory = runs_root / (f"{run_id}.void" if void else run_id)
    directory.mkdir(parents=True)
    for name in files:
        (directory / name).write_text("x")
    return directory


def _addendum(path: Path, run_id: str) -> tuple[Path, str]:
    path.write_text(f"# Addendum 2026-10-16\nvoided_run_id: {run_id}\nreason: OOM\n")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_verdict_ledger_refuses_second_run_without_void_addendum(tmp_path: Path) -> None:
    ledger, runs = tmp_path / "verdict_ledger.jsonl", tmp_path / "runs"
    assert ledger_refuses(ledger, SHA, runs) is None  # no ledger yet
    append_ledger_entry(ledger, amendment_sha=SHA, run_id="r1", code_sha="c" * 40, now=NOW)
    reason = ledger_refuses(ledger, SHA, runs)
    assert reason is not None and "r1" in reason
    # An entry for a different amendment does not block this one.
    assert ledger_refuses(ledger, "ef" * 32, runs) is None
    # The entry is a keyed JSON line.
    (line,) = ledger.read_text().splitlines()
    assert json.loads(line)["amendment_sha"] == SHA


def test_second_run_is_allowed_with_an_addendum_naming_a_void_run(tmp_path: Path) -> None:
    ledger, runs = tmp_path / "verdict_ledger.jsonl", tmp_path / "runs"
    append_ledger_entry(ledger, amendment_sha=SHA, run_id="r1", code_sha="c" * 40, now=NOW)
    _run(runs, "r1", void=True, files=("progress.jsonl", "episodes.jsonl"))
    path, sha = _addendum(tmp_path / "add.md", "r1")
    addendum = load_addendum(path, sha)
    assert ledger_refuses(ledger, SHA, runs, addendum) is None
    # The addendum is consumed once it is recorded with the next entry.
    append_ledger_entry(
        ledger, amendment_sha=SHA, run_id="r2", code_sha="d" * 40, now=NOW, addendum_sha=sha
    )
    _run(runs, "r2", void=True)
    reason = ledger_refuses(ledger, SHA, runs, addendum)
    assert reason is not None and "already used" in reason


def test_addendum_must_name_the_latest_run(tmp_path: Path) -> None:
    ledger, runs = tmp_path / "verdict_ledger.jsonl", tmp_path / "runs"
    append_ledger_entry(ledger, amendment_sha=SHA, run_id="r1", code_sha="c" * 40, now=NOW)
    _run(runs, "r0", void=True)
    path, sha = _addendum(tmp_path / "add.md", "r0")
    reason = ledger_refuses(ledger, SHA, runs, load_addendum(path, sha))
    assert reason is not None and "latest" in reason


@pytest.mark.parametrize(
    "forbidden", ["scored_episodes.csv", "s3_inputs.json", "verdict.json", "verdict.md"]
)
def test_ledger_refuses_addendum_for_run_with_result_files(tmp_path: Path, forbidden: str) -> None:
    ledger, runs = tmp_path / "verdict_ledger.jsonl", tmp_path / "runs"
    append_ledger_entry(ledger, amendment_sha=SHA, run_id="r1", code_sha="c" * 40, now=NOW)
    _run(runs, "r1", void=True, files=("progress.jsonl", forbidden))
    path, sha = _addendum(tmp_path / "add.md", "r1")
    reason = ledger_refuses(ledger, SHA, runs, load_addendum(path, sha))
    assert reason is not None and forbidden in reason


def test_ledger_refuses_addendum_for_a_run_directory_not_void_renamed(tmp_path: Path) -> None:
    ledger, runs = tmp_path / "verdict_ledger.jsonl", tmp_path / "runs"
    append_ledger_entry(ledger, amendment_sha=SHA, run_id="r1", code_sha="c" * 40, now=NOW)
    _run(runs, "r1", void=False)
    path, sha = _addendum(tmp_path / "add.md", "r1")
    reason = ledger_refuses(ledger, SHA, runs, load_addendum(path, sha))
    assert reason is not None and ".void" in reason


def test_a_corrupt_ledger_refuses_rather_than_allows(tmp_path: Path) -> None:
    ledger = tmp_path / "verdict_ledger.jsonl"
    ledger.write_text("{torn\n")
    with pytest.raises(LedgerRefused, match="unreadable"):
        ledger_refuses(ledger, SHA, tmp_path / "runs")


def test_addendum_sha_mismatch_or_missing_run_id_is_refused(tmp_path: Path) -> None:
    path, _sha = _addendum(tmp_path / "add.md", "r1")
    with pytest.raises(LedgerRefused, match="sha"):
        load_addendum(path, "0" * 64)
    bare = tmp_path / "bare.md"
    bare.write_text("no run id\n")
    with pytest.raises(LedgerRefused, match="voided_run_id"):
        load_addendum(bare, hashlib.sha256(bare.read_bytes()).hexdigest())


def test_void_run_dir_renames_and_never_opens_episodes(tmp_path: Path) -> None:
    run = _run(
        tmp_path, "r9", void=False, files=("progress.jsonl", "episodes.jsonl", "run_manifest.json")
    )
    (run / "episodes.jsonl").write_text("SECRET-FILL-DATA")
    voided = void_run_dir(run)
    assert voided.path.name == "r9.void" and voided.path.is_dir() and not run.exists()
    assert "episodes.jsonl" in voided.unopened
    # The digest covers the unopened file by name and size only: its bytes cannot matter.
    before = voided.tree_sha256
    (voided.path / "episodes.jsonl").write_text("DIFFERENT-BYTES!")  # same size, other content
    assert tree_digest(voided.path) == before
    (voided.path / "progress.jsonl").write_text("changed")
    assert tree_digest(voided.path) != before
    with pytest.raises(LedgerRefused, match="already"):
        void_run_dir(voided.path)
