"""MAKER-S2 second look (C2): the FROZEN_DATE_SET_V2 fence, parser and rule."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pytest

from scripts.analysis.maker_stage0_frozen import (
    SECOND_LOOK_FIRST_DAY,
    SECOND_LOOK_MAX_DAY,
    FrozenDateSet,
    FrozenSetRefused,
    load_amendment,
    parse_frozen_block,
    parse_frozen_block_v2,
    truth_keys,
    verify_set_matches_rule,
)
from scripts.analysis.maker_stage0_inputs import TruthTable
from tests.fixtures.maker_stage0 import make_census_fixture as fx
from tests.fixtures.maker_stage0.frozen_v2 import (
    SHA_CROSS,
    SHA_TRUTH,
    TRIGGER,
    days,
    v2_fields,
    v2_text,
)

COMMITTED = (
    Path(__file__).resolve().parents[2]
    / "docs/evidence/RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md"
)
COMMITTED_SHA = "cf9a4dad826f61016b2616d32fbc1ca82f73b339b7da8e74fb6a9f25f4c818d0"
V1_BLOCK = (
    "```FROZEN_DATE_SET\nstations: LAX MDW MIA SFO\nfirst_replayable_day: 2026-09-18\n"
    f"truth_csv_path: /x/t.csv\ntruth_csv_sha256: {SHA_TRUTH}\nlast_final_day: 2026-09-19\n"
    "dates:\n2026-09-18\n2026-09-19\n```\n"
)


def _truth(last: dt.date = TRIGGER, sha: str = SHA_TRUTH) -> TruthTable:
    finals = {("SFO", d): 70 for d in days(last=last)}
    return TruthTable(finals, sha, Path("/x/c.csv"), SHA_CROSS, 0)


def _census(last: dt.date = TRIGGER) -> list:  # type: ignore[type-arg]
    return [fx.census_row("SFO", d) for d in days(last=last)]


def test_v2_block_parses_and_matches_rule() -> None:
    fs = parse_frozen_block_v2(v2_text(v2_fields()))
    assert fs.block == 2 and fs.trigger_day == TRIGGER
    assert fs.first_replayable_day == SECOND_LOOK_FIRST_DAY == dt.date(2026, 10, 14)
    assert fs.dates == tuple(days())
    assert fs.trigger_rows_sha256 and fs.census_days_sha256 and fs.cross_check_sha256 == SHA_CROSS
    assert fs.cross_check_path == "out/cross_check.parquet"
    verify_set_matches_rule(fs, _census(), _truth())


@pytest.mark.parametrize("bad", ["2026-10-13", "2026-10-01", "2026-09-30"])
def test_v2_refuses_any_block1_date(bad: str) -> None:
    dates = [dt.date.fromisoformat(bad), *days()]
    with pytest.raises(FrozenSetRefused, match=bad):
        parse_frozen_block_v2(v2_text(v2_fields(dates=dates)))


def test_v2_refuses_last_final_before_trigger_day() -> None:
    fields = v2_fields(last_final_day="2026-10-19")
    with pytest.raises(FrozenSetRefused, match="last_final_day"):
        parse_frozen_block_v2(v2_text(fields))


def test_v2_accepts_last_final_day_after_trigger_day() -> None:
    late = (TRIGGER + dt.timedelta(days=2)).isoformat()
    fs = parse_frozen_block_v2(v2_text(v2_fields(last_final_day=late)))
    verify_set_matches_rule(fs, _census(), _truth(last=TRIGGER))


def test_v2_refuses_trigger_day_after_cap() -> None:
    over = SECOND_LOOK_MAX_DAY + dt.timedelta(days=1)
    fields = v2_fields(trigger_day=over.isoformat(), last_final_day=over.isoformat())
    with pytest.raises(FrozenSetRefused, match="trigger_day"):
        parse_frozen_block_v2(v2_text(fields))
    assert SECOND_LOOK_MAX_DAY == dt.date(2026, 11, 15)


@pytest.mark.parametrize(
    ("over", "why"),
    [
        (
            {"block_first_day": "2026-10-15", "dates": days(dt.date(2026, 10, 15))},
            "block_first_day",
        ),
        ({"stations": "LAX MDW MIA NYC"}, "NYC"),
        ({"trigger_day": "<FILL>"}, "FILL"),
        ({"cross_check_sha256": "xyz"}, "sha256"),
        ({"dates": [*days(), TRIGGER + dt.timedelta(days=1)]}, "outside the rule"),
    ],
)
def test_v2_parser_fails_closed(over: dict[str, object], why: str) -> None:
    with pytest.raises(FrozenSetRefused, match=why):
        parse_frozen_block_v2(v2_text(v2_fields(**over)))


def test_v2_missing_date_is_refused_by_the_rule() -> None:
    fs = parse_frozen_block_v2(v2_text(v2_fields(dates=days()[:-1])))
    with pytest.raises(FrozenSetRefused, match="differs from the rule"):
        verify_set_matches_rule(fs, _census(), _truth())


def test_v2_trigger_day_must_not_precede_block_first_day() -> None:
    fields = v2_fields(trigger_day="2026-10-13", last_final_day="2026-10-20")
    with pytest.raises(FrozenSetRefused):
        parse_frozen_block_v2(v2_text(fields))


def test_v2_unfilled_or_draft_amendment_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text(v2_text(v2_fields()).replace("**FINAL**", "**DRAFT**"))
    with pytest.raises(FrozenSetRefused, match="DRAFT"):
        load_amendment(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_load_amendment_dispatches_on_the_fence(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text(v2_text(v2_fields()))
    fs = load_amendment(path, hashlib.sha256(path.read_bytes()).hexdigest())
    assert fs.block == 2


def test_v1_parser_refuses_v2_only_doc() -> None:
    with pytest.raises(FrozenSetRefused, match="exactly one"):
        parse_frozen_block(v2_text(v2_fields()))


def test_v2_parser_refuses_v1_doc() -> None:
    with pytest.raises(FrozenSetRefused, match="exactly one"):
        parse_frozen_block_v2("Status: **FINAL**\n" + V1_BLOCK)


def test_both_fences_refused(tmp_path: Path) -> None:
    both = v2_text(v2_fields()) + V1_BLOCK
    for parser in (parse_frozen_block, parse_frozen_block_v2):
        with pytest.raises(FrozenSetRefused, match="both"):
            parser(both)
    path = tmp_path / "a.md"
    path.write_text(both)
    with pytest.raises(FrozenSetRefused, match="both"):
        load_amendment(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_v1_parse_of_committed_amendment_is_unchanged() -> None:
    fs = load_amendment(COMMITTED, COMMITTED_SHA)
    assert fs.block == 1 and fs.trigger_day is None
    assert len(fs.dates) == 24
    assert fs.dates[0] == dt.date(2026, 9, 18) and fs.dates[-1] == dt.date(2026, 10, 12)
    assert dt.date(2026, 10, 1) not in fs.dates
    assert hashlib.sha256(COMMITTED.read_bytes()).hexdigest() == COMMITTED_SHA


def test_v1_construction_sites_unchanged() -> None:
    fs = FrozenDateSet(
        ("SFO",),
        dt.date(2026, 9, 18),
        "/x",
        SHA_TRUTH,
        dt.date(2026, 9, 19),
        (dt.date(2026, 9, 18),),
    )
    assert fs.block == 1
    assert fs.trigger_day is None and fs.trigger_rows_path is None
    assert fs.trigger_rows_sha256 is None and fs.census_days_path is None
    assert fs.census_days_sha256 is None and fs.cross_check_path is None
    assert fs.cross_check_sha256 is None
    assert parse_frozen_block(V1_BLOCK).block == 1


def test_truth_keys_is_the_station_day_product() -> None:
    keys = truth_keys(("LAX", "SFO"), (dt.date(2026, 10, 14), dt.date(2026, 10, 15)))
    assert keys == {
        ("LAX", dt.date(2026, 10, 14)),
        ("LAX", dt.date(2026, 10, 15)),
        ("SFO", dt.date(2026, 10, 14)),
        ("SFO", dt.date(2026, 10, 15)),
    }
