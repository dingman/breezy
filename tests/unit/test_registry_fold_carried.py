"""ARCH-0 seam 7b: ``HWM_RESET`` ``carried_counters`` are floors (Z17, B9).

A reset appends the counters of the rows it dropped, and the fold applies them as floors so that no
budget is refunded: an int becomes the larger of its fold so far and the carried value, a bool is
ORed, and a list of instants is merged by sorted multiset union (A7b-R2, E-21). The
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
    DRILL_FIELDS,
    LATE,
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
        "nomination_instants": (1, 2), "mints": (5, 6, 7), "promotions": (8,),
        "rollbacks": (9, 10), "model_resumes": (11,), "terminal_frozen": True,
        "drill_admits": (12,), "drill_promotes": (13,), "drill_demotes": (14,),
        "drill_resumes": (15,), "drill_halts": (16,), "drill_rollbacks": (17,),
    }  # fmt: skip
    venue = {"infra_resumes": (18, 19), "drill_close_restores": (20,), "sender_changes": (21,)}
    reset(chain, carried({INCUMBENT: over}, venue))

    result = run(chain, LATE)
    got = lineage_of(result)
    nomination = chain.rows[3].ts_ns

    assert got["nominations"] == 3
    assert got["infeasible_nominations"] == 2
    assert got["alpha_spent"] == Decimal("0.04375")
    assert got["nomination_instants"] == (1, 2, nomination)
    assert got["mints"] == (5, 6, 7, chain.rows[1].ts_ns, chain.rows[2].ts_ns)
    assert got["promotions"] == (8,)
    assert got["rollbacks"] == (9, 10)
    assert got["model_resumes"] == (11,)
    assert got["terminal_frozen"] is True
    assert view(result, INCUMBENT).terminal_frozen  # one lineage freeze, seen both ways
    assert {k: got[k] for k in DRILL_FIELDS} == {
        k: (n,) for k, n in zip(DRILL_FIELDS, range(12, 18))
    }
    assert result.venue_tallies == fm.VenueTallies(
        infra_resumes=(18, 19), drill_close_restores=(20,), sender_changes=(21,)
    )


def test_a_carry_of_older_instants_never_drops_the_folds_recent_ones() -> None:
    chain = rooted()
    mints = (chain.rows[1].ts_ns, chain.rows[2].ts_ns)
    reset(chain, carried({INCUMBENT: {"mints": (1, 2, 3, 4)}}))  # longer, but all older

    got = lineage_of(run(chain, LATE))

    assert got["mints"] == (1, 2, 3, 4, *mints)  # a longer-list rule would lose both of these


def test_the_union_keeps_each_instant_at_its_higher_multiplicity() -> None:
    chain = rooted()
    first, second = chain.rows[1].ts_ns, chain.rows[2].ts_ns
    reset(chain, carried({INCUMBENT: {"mints": (5, first, first, first)}}))

    got = lineage_of(run(chain, LATE))

    assert got["mints"] == (5, first, first, first, second)  # carried x3 beats fold x1; second kept


def test_a_carried_value_below_the_fold_refunds_nothing() -> None:
    chain = rooted()
    nominate(chain, CHILD, k=2, alpha="0.0125")
    reset(chain, carried({INCUMBENT: {"nominations": 1, "alpha_spent": Decimal("0.001")}}))

    got = lineage_of(run(chain, LATE))

    assert got["nominations"] == 2
    assert got["alpha_spent"] == Decimal("0.0125")
    assert got["mints"] == (chain.rows[1].ts_ns, chain.rows[2].ts_ns)  # carried () drops nothing
    assert len(got["nomination_instants"]) == 1


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
        _mutate(BASE, lambda o: o["venue"].update(infra_resumes=[-1])),
        _mutate(BASE, lambda o: o["venue"].update(infra_resumes=[True])),
        _mutate(BASE, lambda o: o["venue"].update(infra_resumes=1)),
        _mutate(BASE, lambda o: o["venue"].update(sender_changes=[2, 1])),
        _mutate(BASE, lambda o: o["venue"].pop("sender_changes")),
        _mutate(BASE, lambda o: o["venue"].pop("drill_close_restores")),
        _mutate(BASE, lambda o: o["lineages"][INCUMBENT].update(rollbacks=2)),
        _mutate(BASE, lambda o: o["lineages"][INCUMBENT].update(drill_halts=[5, 4])),
        _mutate(BASE, lambda o: o["lineages"][INCUMBENT].update(nomination_instants=[-1])),
        _mutate(BASE, lambda o: o["lineages"][INCUMBENT].update(model_resumes=["1"])),
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
        "old_int_shape",
        "unsorted_sender_changes",
        "missing_sender_changes",
        "missing_close_restores",
        "int_rollbacks",
        "unsorted_drill_halts",
        "negative_nomination_instant",
        "string_model_resume",
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
