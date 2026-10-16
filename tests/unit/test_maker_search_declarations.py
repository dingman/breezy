"""MAKER S2 second look, unit C1 -- the SEARCH-declaration registry and the firewall rows.

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3.md section 3 "C1".
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pytest

from breezy.analysis import maker_search_declarations as reg
from breezy.analysis import maker_tape_census as mtc
from breezy.analysis.maker_tape_census import FirewallRefused, require_firewall_clearance

REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC_A = REPO_ROOT / "docs/evidence/RULING_MAKER-S2_second_look_SEARCH_declaration_2026-10-16.md"
_DOC_A_SHA = "bc15908052ff223abc889859133edb4645d4a6642b5fae559c0101251df9a05b"
_FIRST_SHA = "38663caad38e455ab1512ca91a049f97d31c2dcfb1477c42db02ceca407abbc6"
_SECOND_SHA = reg.SEARCH_DECLARATIONS[1].sha256


def test_second_look_day_cleared_only_with_second_declaration_sha() -> None:
    day = dt.date(2026, 10, 14)

    assert require_firewall_clearance("LAX", day, _SECOND_SHA) == "SEARCH_DECLARED"
    assert require_firewall_clearance("SFO", dt.date(2026, 11, 15), _SECOND_SHA) == (
        "SEARCH_DECLARED"
    )
    for wrong in (None, "0" * 64, _FIRST_SHA):
        with pytest.raises(FirewallRefused):
            require_firewall_clearance("LAX", day, wrong)


def test_first_block_day_refused_with_second_declaration_sha() -> None:
    for day in (dt.date(2026, 9, 26), dt.date(2026, 10, 13)):
        with pytest.raises(FirewallRefused):
            require_firewall_clearance("MIA", day, _SECOND_SHA)
        assert require_firewall_clearance("MIA", day, _FIRST_SHA) == "SEARCH_DECLARED"


def test_day_after_second_look_ceiling_refused() -> None:
    after = dt.date(2026, 11, 16)

    for sha in (_SECOND_SHA, _FIRST_SHA, None):
        with pytest.raises(FirewallRefused):
            require_firewall_clearance("LAX", after, sha)


def test_registry_rows_are_disjoint_and_pinned() -> None:
    first, second = reg.SEARCH_DECLARATIONS

    assert len(reg.SEARCH_DECLARATIONS) == 2
    assert first.stations == second.stations == frozenset({"LAX", "MDW", "MIA", "SFO"})
    assert (first.first_day, first.last_day, first.sha256) == (
        dt.date(2026, 9, 26),
        dt.date(2026, 10, 13),
        _FIRST_SHA,
    )
    assert (second.first_day, second.last_day, second.sha256) == (
        dt.date(2026, 10, 14),
        dt.date(2026, 11, 15),
        _DOC_A_SHA,
    )
    assert first.last_day < second.first_day
    assert first.sha256 != second.sha256
    assert mtc.SEARCH_DECLARED is first
    assert mtc.SEARCH_DECLARATION_SHA256 == first.sha256


def test_registry_stations_equal_census_maker_stations() -> None:
    assert reg.MAKER_STATIONS == mtc.MAKER_STATIONS
    for row in reg.SEARCH_DECLARATIONS:
        assert row.stations == mtc.MAKER_STATIONS


def test_registry_row1_sha_matches_committed_doc_a() -> None:
    digest = hashlib.sha256(_DOC_A.read_bytes()).hexdigest()

    assert digest == reg.SEARCH_DECLARATIONS[1].sha256 == _DOC_A_SHA


def test_declaration_row_lookup_and_token_contract() -> None:
    assert reg.declaration_row("LAX", dt.date(2026, 9, 25)) is None
    assert reg.declaration_row("LAX", dt.date(2026, 9, 26)) == 0
    assert reg.declaration_row("LAX", dt.date(2026, 10, 14)) == 1
    assert reg.declaration_row("NYC", dt.date(2026, 10, 14)) is None
    assert reg.declaration_row("LAX", dt.date(2026, 11, 16)) is None
    assert reg.is_trigger_check_token("abc") is True
    for bad in (None, "", "   ", 5):
        assert reg.is_trigger_check_token(bad) is False
