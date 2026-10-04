"""ARCH-0 seam 7b: ``HWM_RESET`` ``carried_counters`` are floors (Z17, B9).

A reset appends the counters of the rows it dropped, and the fold applies them as floors so that no
budget is refunded: a counter becomes the larger of its fold so far and the carried value. The
shape of the object is the fold's to define (``fold_tallies``); a malformed object is
``FoldInvalid(carried_counters_malformed)`` whatever the clock. Whether a carried value is below
the export's is validate's (B9, seams 7c and 7d), not tested here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Final

import pytest

import breezy.persistence.autonomy.fold as fm
from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.schemas import FoldInvalidReason, State
from tests.unit.test_registry_fold import CHILD, DAY, INCUMBENT, OTHER, VENUE, at, run
from tests.unit.test_registry_fold_tallies import (
    LATE,
    LINEAGE_FIELDS,
    carried,
    lineage_of,
    nominate,
    reset,
    rooted,
    view,
)


def test_carried_counters_are_floors() -> None:
    chain = rooted()
    nominate(chain, CHILD, k=1, alpha="0.025")
    over = {
        "nominations": 3, "infeasible_nominations": 2, "alpha_spent": Decimal("0.04375"),
        "mints": (5, 6, 7), "promotions": (8,), "rollbacks": 2, "terminal_frozen": True,
        "drill_admits": 1, "drill_promotes": 1, "drill_demotes": 1, "drill_resumes": 1,
        "drill_halts": 1, "drill_rollbacks": 1,
    }  # fmt: skip
    reset(chain, carried({INCUMBENT: over}, {"infra_resumes": 2, "drill_close_restores": 1}))

    result = run(chain, LATE)
    got = lineage_of(result)

    assert got["nominations"] == 3
    assert got["infeasible_nominations"] == 2
    assert got["alpha_spent"] == Decimal("0.04375")
    assert got["mints"] == (5, 6, 7)  # the longer record wins; two mint rows are in the chain
    assert got["promotions"] == (8,)
    assert got["rollbacks"] == 2
    assert got["terminal_frozen"] is True
    assert view(result, INCUMBENT).terminal_frozen  # one lineage freeze, seen both ways
    assert {k: got[k] for k in LINEAGE_FIELDS if k.startswith("drill_")} == {
        k: 1 for k in LINEAGE_FIELDS if k.startswith("drill_")
    }
    assert result.venue_tallies == fm.VenueTallies(infra_resumes=2, drill_close_restores=1)


def test_a_carried_value_below_the_fold_refunds_nothing() -> None:
    chain = rooted()
    nominate(chain, CHILD, k=2, alpha="0.0125")
    reset(chain, carried({INCUMBENT: {"nominations": 1, "alpha_spent": Decimal("0.001")}}))

    got = lineage_of(run(chain, LATE))

    assert got["nominations"] == 2
    assert got["alpha_spent"] == Decimal("0.0125")
    assert len(got["mints"]) == 2  # carried () is shorter than the two mint rows


def test_rows_after_the_reset_charge_on_top_of_the_floor() -> None:
    chain = rooted()
    reset(chain, carried({INCUMBENT: {"nominations": 1, "alpha_spent": Decimal("0.025")}}))
    nominate(chain, CHILD, k=2, alpha="0.0125")

    got = lineage_of(run(chain, LATE))

    assert got["nominations"] == 2
    assert got["alpha_spent"] == Decimal("0.025") + Decimal("0.0125")  # floor, then this charge


def test_a_carried_lineage_with_no_rows_left_still_has_its_tallies() -> None:
    chain = rooted()
    reset(chain, carried({OTHER: {"nominations": 4, "terminal_frozen": True}}))

    result = run(chain, LATE)

    assert result.lineages[OTHER].family_ids == ()
    assert lineage_of(result, OTHER)["nominations"] == 4
    assert lineage_of(result, OTHER)["terminal_frozen"] is True


def test_a_reset_waits_for_the_clock_like_every_row() -> None:
    chain = rooted()
    row = reset(chain, carried({INCUMBENT: {"nominations": 4}}), ts=at(DAY, "19:00"))

    assert lineage_of(run(chain, row.ts_ns - 1))["nominations"] == 0
    assert lineage_of(run(chain, row.ts_ns))["nominations"] == 4


def test_the_carried_object_is_not_mutated_and_a_reset_changes_no_state() -> None:
    chain = rooted()
    row = reset(chain, carried({INCUMBENT: {"nominations": 1}}))
    snapshot = row.carried_counters

    result = run(chain, LATE)

    assert row.carried_counters == snapshot
    assert result.states[INCUMBENT] is State.CHAMPION


def _mutate(text: str, edit: Callable[[dict[str, Any]], None]) -> str:
    obj = json.loads(text)
    edit(obj)
    return canonical_json(obj).decode("utf-8")


BASE: Final = carried({INCUMBENT: {"nominations": 1}})


@pytest.mark.parametrize(
    "bad",
    [
        _mutate(BASE, lambda o: o.pop("venue")),
        _mutate(BASE, lambda o: o.update(extra=1)),
        _mutate(BASE, lambda o: o["venue"].update(infra_resumes=-1)),
        _mutate(BASE, lambda o: o["venue"].update(infra_resumes=True)),
        _mutate(BASE, lambda o: o["venue"].pop("drill_close_restores")),
        _mutate(BASE, lambda o: o["lineages"][INCUMBENT].pop("rollbacks")),
        _mutate(BASE, lambda o: o["lineages"][INCUMBENT].update(surprise=1)),
        _mutate(BASE, lambda o: o["lineages"][INCUMBENT].update(nominations="1")),
        _mutate(BASE, lambda o: o["lineages"][INCUMBENT].update(alpha_spent="0.10")),
        _mutate(BASE, lambda o: o["lineages"][INCUMBENT].update(terminal_frozen=1)),
        _mutate(BASE, lambda o: o["lineages"][INCUMBENT].update(mints=[3, 2])),
        _mutate(BASE, lambda o: o["lineages"][INCUMBENT].update(mints=[-1])),
        _mutate(BASE, lambda o: o["lineages"].update({"Bad Name": o["lineages"][INCUMBENT]})),
        _mutate(BASE, lambda o: o.update(lineages=[])),
        "{}",
    ],
    ids=[
        "no_venue",
        "unknown_top_key",
        "negative_infra",
        "bool_infra",
        "missing_close_restores",
        "missing_lineage_field",
        "unknown_lineage_field",
        "string_count",
        "non_canonical_alpha",
        "int_as_bool",
        "unsorted_mints",
        "negative_mint",
        "bad_lineage_key",
        "lineages_not_object",
        "empty_object",
    ],
)
def test_malformed_carried_counters_fold_invalid(bad: str) -> None:
    chain = rooted()
    reset(chain, bad, ts=at("2026-10-30", "00:00"))  # not yet applied: still checked

    assert fm.fold(chain.rows, VENUE, LATE) == fm.FoldInvalid(
        FoldInvalidReason.CARRIED_COUNTERS_MALFORMED
    )
