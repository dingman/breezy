"""ARCH-0 seam 7b: ``origin``, the root-lineage check, tallies charged on effect, halted-since.

6b and 7a pinned the structure, the flags and the episodes. These tests pin what 7b adds, all of it
a pure function of rows and the clock:

* ``FamilyView.origin`` comes from the introducing row (root or child) and a root kind that names a
  foreign lineage root is ``FoldInvalid(root_lineage_mismatch)``;
* ``LineageTallies`` and ``VenueTallies`` (the ARCH C5 counters minus ``holdout_opens``), charged
  when a change takes effect: a lapsed, voided or still pending pair is never charged, a drill row
  charges only the drill counters, and ``HWM_RESET`` ``carried_counters`` apply as floors;
* ``FamilyView.halted_since_ns`` (AUT-6 r15 #30).

The fold meets the ARCH names through the module (``fm``), so each test fails by itself while a
symbol is missing. Validate I/II (7c, 7d) are not here: nothing in this file refuses a row.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

import breezy.persistence.autonomy.fold as fm
from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.schemas import (
    CauseClass,
    CauseCode,
    DecidedBy,
    FoldInvalidReason,
    Kind,
    State,
    TransitionRow,
)
from tests.unit.test_registry_fold import (
    CHILD,
    DAY,
    INCUMBENT,
    LAUNCH,
    OTHER,
    SEC,
    VENUE,
    Chain,
    at,
    run,
    seeded_pair,
)
from tests.unit.test_registry_fold_effects import (
    NEXT_DAY,
    NEXT_LATE,
    activated_pair,
    cancel,
    drill_chain,
    full_episode,
)

LATE = at(DAY, "18:00")
SECOND = "pm_us_crh_fq_v1_r0002"
ARCH_FILE: Final = (
    Path(__file__).resolve().parents[2]
    / "docs/plans/backlog/AUTONOMY_2026-10-03/AUTONOMY_ARCHITECTURE.md"
)
LINEAGE_FIELDS: Final = (
    "nominations", "infeasible_nominations", "nomination_instants", "alpha_spent", "mints",
    "promotions", "rollbacks", "model_resumes", "terminal_frozen", "drill_admits",
    "drill_promotes", "drill_demotes", "drill_resumes", "drill_halts", "drill_rollbacks",
)  # fmt: skip
VENUE_FIELDS: Final = ("infra_resumes", "drill_close_restores", "sender_changes")
SCALAR_FIELDS: Final = ("nominations", "infeasible_nominations", "alpha_spent", "terminal_frozen")
TUPLE_FIELDS: Final = tuple(f for f in LINEAGE_FIELDS if f not in SCALAR_FIELDS)
DRILL_FIELDS: Final = tuple(f for f in LINEAGE_FIELDS if f.startswith("drill_"))
ZERO_LINEAGE: Final[dict[str, Any]] = {
    **dict.fromkeys(TUPLE_FIELDS, ()), "nominations": 0, "infeasible_nominations": 0,
    "alpha_spent": Decimal(0), "terminal_frozen": False,
}  # fmt: skip
NEXT_LAUNCH = at(NEXT_DAY, "16:50")


def lineage_of(result: fm.FoldResult, root: str = INCUMBENT) -> dict[str, Any]:
    tallies = result.lineages[root].tallies
    return {f.name: getattr(tallies, f.name) for f in fields(tallies)}


def view(result: fm.FoldResult, family: str) -> fm.FamilyView:
    return result.families[family]


def rooted() -> Chain:
    """INCUMBENT (a root) CHAMPION and two MINT children of its lineage, both SHADOW."""
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, lineage_root_family_id=INCUMBENT)
    chain.add(Kind.MINT, State.SHADOW, family=CHILD, lineage_root_family_id=INCUMBENT)
    chain.add(Kind.MINT, State.SHADOW, family=SECOND, lineage_root_family_id=INCUMBENT)
    return chain


def nominate(
    chain: Chain, family: str, *, k: int, alpha: str, feasible: bool = True
) -> TransitionRow:
    return chain.add(
        Kind.PROMOTE, State.CHALLENGER, family=family, frm=State.SHADOW,
        lineage_root_family_id=INCUMBENT, k_life=k, alpha_k=Decimal(alpha), n_min_eff=403,
        n_cap=480 if feasible else 89, nomination_feasible=feasible,
    )  # fmt: skip


def carried(
    lineages: dict[str, dict[str, Any]] | None = None, venue: dict[str, Any] | None = None
) -> str:
    """Canonical text of a ``carried_counters`` object (the shape 7b fixes)."""
    full = {
        root: {
            **{k: _wire(v) for k, v in ZERO_LINEAGE.items()},
            **{k: _wire(v) for k, v in over.items()},
        }
        for root, over in (lineages or {}).items()
    }
    venue_part = {
        **{k: [] for k in VENUE_FIELDS},
        **{k: _wire(v) for k, v in (venue or {}).items()},
    }
    return canonical_json({"lineages": full, "venue": venue_part}).decode("utf-8")


def _wire(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, tuple):
        return list(value)
    return value


def reset(chain: Chain, text: str, *, ts: int | None = None) -> TransitionRow:
    return chain.add(
        Kind.HWM_RESET, State.CHAMPION, family=INCUMBENT, frm=State.CHAMPION, ts=ts,
        decided_by=DecidedBy.OPERATOR_CLI, hwm_from=3, hwm_to=4, carried_counters=text,
    )  # fmt: skip


# --- origin and the root-lineage check ------------------------------------------------------


def test_family_origin_from_introducing_row() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, lineage_root_family_id=INCUMBENT)
    chain.add(Kind.MINT, State.SHADOW, family=CHILD, lineage_root_family_id=INCUMBENT)
    chain.add(
        Kind.ROOT_ADMIT, State.CHAMPION, family=OTHER, lineage_root_family_id=OTHER,
        effective_launch_date=DAY,
    )  # fmt: skip
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)  # a later row

    result = run(chain, LATE)

    assert view(result, INCUMBENT).origin is fm.Origin.ROOT
    assert view(result, CHILD).origin is fm.Origin.CHILD
    assert view(result, OTHER).origin is fm.Origin.ROOT  # a pending ROOT_ADMIT root
    assert view(result, CHILD).lineage_root_family_id == INCUMBENT
    assert view(result, OTHER).lineage_root_family_id == OTHER
    assert {o.value for o in fm.Origin} == {"root", "child"}


def test_origin_is_a_root_even_when_the_name_looks_like_a_child() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=CHILD, lineage_root_family_id=CHILD)
    chain.add(Kind.MINT, State.SHADOW, family=INCUMBENT, lineage_root_family_id=CHILD)

    result = run(chain, LATE)

    assert view(result, CHILD).origin is fm.Origin.ROOT
    assert view(result, INCUMBENT).origin is fm.Origin.CHILD


@pytest.mark.parametrize("kind", [Kind.BOOTSTRAP, Kind.ROOT_ADMIT])
def test_root_kind_with_foreign_lineage_root_is_invalid(kind: Kind) -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, lineage_root_family_id=INCUMBENT)
    chain.add(
        kind, State.CHAMPION, family=OTHER, lineage_root_family_id=INCUMBENT,
        effective_launch_date=DAY if kind is Kind.ROOT_ADMIT else None,
    )  # fmt: skip

    assert fm.fold(chain.rows, VENUE, LATE) == fm.FoldInvalid(
        FoldInvalidReason.ROOT_LINEAGE_MISMATCH
    )


@pytest.mark.parametrize("kind", [Kind.MINT, Kind.BOOTSTRAP, Kind.ROOT_ADMIT])
def test_an_introducing_row_without_a_lineage_column_is_invalid(kind: Kind) -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, lineage_root_family_id=INCUMBENT)
    chain.add(
        kind, State.SHADOW if kind is Kind.MINT else State.CHAMPION, family=CHILD,
        lineage_root_family_id=None,
        effective_launch_date=DAY if kind is Kind.ROOT_ADMIT else None,
    )  # fmt: skip

    assert fm.fold(chain.rows, VENUE, LATE) == fm.FoldInvalid(
        FoldInvalidReason.ROOT_LINEAGE_MISMATCH
    )  # E-14 rule 3 (A7b-R3)


def test_the_first_invalid_row_in_chain_order_names_the_reason() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, lineage_root_family_id=OTHER)
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)

    assert fm.fold(chain.rows, VENUE, LATE) == fm.FoldInvalid(
        FoldInvalidReason.ROOT_LINEAGE_MISMATCH
    )


# --- the tally field set ---------------------------------------------------------------------


def arch_counter_names() -> set[str]:
    """The identifiers named in ARCH C5 ``lineage_counters``, minus the row columns they cite."""
    text = ARCH_FILE.read_text(encoding="utf-8")
    start = text.index("- `lineage_counters`:")
    block = text[start : text.index("\n\n", start)]
    names = set(re.findall(r"`([a-z][a-z_]*)`", block)) - {"lineage_counters"}
    return names - set(TransitionRow.__dataclass_fields__)


def test_lineage_tallies_fields_equal_arch_counters_minus_non_derivable() -> None:
    non_derivable = {"holdout_opens"}  # no row source: the AUT-5 WP4 cache
    lineage = {f.name for f in fields(fm.LineageTallies)}
    venue = {f.name for f in fields(fm.VenueTallies)}

    assert tuple(f.name for f in fields(fm.LineageTallies)) == LINEAGE_FIELDS
    assert venue == set(VENUE_FIELDS)
    added = {"drill_close_restores", "nomination_instants", "model_resumes", "sender_changes"}
    expected = (arch_counter_names() - non_derivable) | added  # E-5 and E-21 add these
    assert lineage | venue == expected
    assert not (lineage | venue) & non_derivable
    scalars = {
        f.name
        for f in fields(fm.LineageTallies)
        if not isinstance(getattr(fm.LineageTallies(), f.name), tuple)
    }
    assert scalars == set(SCALAR_FIELDS)  # E-21: every windowed counter is a tuple of instants
    assert all(isinstance(getattr(fm.VenueTallies(), n), tuple) for n in VENUE_FIELDS)


def test_tallies_are_frozen_and_the_result_carries_one_per_lineage() -> None:
    chain = rooted()
    result = run(chain, LATE)

    assert set(result.lineages) == {INCUMBENT}
    assert result.lineages[INCUMBENT].root_family_id == INCUMBENT
    assert result.lineages[INCUMBENT].family_ids == (INCUMBENT, CHILD, SECOND)
    mints = (chain.rows[1].ts_ns, chain.rows[2].ts_ns)
    assert lineage_of(result) == {**ZERO_LINEAGE, "mints": mints}
    with pytest.raises(FrozenInstanceError):
        result.lineages[INCUMBENT].tallies.nominations = 9  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.lineages["x"] = result.lineages[INCUMBENT]  # type: ignore[index]
    assert result.venue_tallies == fm.VenueTallies()


def test_an_empty_chain_has_no_lineages_and_zero_venue_tallies() -> None:
    result = run(Chain(), LATE)

    assert dict(result.lineages) == {}
    assert result.venue_tallies == fm.VenueTallies()


# --- nominations, alpha and mints ------------------------------------------------------------


def test_nominations_are_the_max_feasible_k_and_every_nomination_uses_a_slot() -> None:
    chain = rooted()
    first = nominate(chain, CHILD, k=1, alpha="0.025")
    second = nominate(chain, SECOND, k=4, alpha="0.003125")
    chain.add(
        Kind.MINT, State.SHADOW, family="pm_us_crh_fq_v1_r0003", lineage_root_family_id=INCUMBENT
    )
    third = nominate(chain, "pm_us_crh_fq_v1_r0003", k=4, alpha="0", feasible=False)

    got = lineage_of(run(chain, LATE))

    assert got["nominations"] == 4  # the largest feasible k_life: neither 3 rows nor 2 feasible
    assert got["infeasible_nominations"] == 1
    assert got["nomination_instants"] == (first.ts_ns, second.ts_ns, third.ts_ns)  # E-21 slot
    assert got["alpha_spent"] == Decimal("0.028125")  # the sum of alpha_k over the rows
    assert got["promotions"] == ()  # a nomination is no sender change


def test_tallies_alpha_spent_equals_sum_alpha_k() -> None:
    chain = rooted()
    alphas = ["0.025", "0.0125"]
    nominate(chain, CHILD, k=1, alpha=alphas[0])
    nominate(chain, SECOND, k=2, alpha=alphas[1])

    spent = lineage_of(run(chain, LATE))["alpha_spent"]

    assert isinstance(spent, Decimal)
    assert spent == sum((Decimal(a) for a in alphas), Decimal(0))
    assert lineage_of(run(chain, LATE))["promotions"] == ()


def test_alpha_spent_is_exact_beyond_the_default_decimal_precision() -> None:
    chain = rooted()
    first, second = "0.1234567890123456789012345678901234", "0.2234567890123456789012345678901234"
    nominate(chain, CHILD, k=1, alpha=first)  # 34 digits each: the sum is past the default 28
    nominate(chain, SECOND, k=2, alpha=second)

    spent = lineage_of(run(chain, LATE))["alpha_spent"]

    assert spent == Decimal("0.3469135780246913578024691357802468")


def test_a_nomination_is_charged_when_the_clock_reaches_it() -> None:
    chain = rooted()
    nom = nominate(chain, CHILD, k=1, alpha="0.025")

    before = lineage_of(run(chain, nom.ts_ns - 1))
    after = lineage_of(run(chain, nom.ts_ns))

    assert before["nominations"] == 0
    assert before["nomination_instants"] == ()
    assert before["alpha_spent"] == 0
    assert after["nominations"] == 1
    assert after["nomination_instants"] == (nom.ts_ns,)
    assert after["promotions"] == ()


def test_only_a_shadow_to_challenger_promote_is_a_nomination() -> None:
    chain, head, _tail = seeded_pair()
    chain.activate(head, ts=at(DAY, "16:45"))

    got = lineage_of(run(chain, LATE))

    assert got["nominations"] == 0  # the seed PROMOTE carries no nomination columns
    assert got["nomination_instants"] == ()
    assert got["alpha_spent"] == 0


def test_mints_are_the_timestamps_of_mint_rows_per_lineage() -> None:
    chain = rooted()
    chain.add(Kind.BOOTSTRAP, State.RETIRED, family=OTHER, lineage_root_family_id=OTHER)
    mint = chain.rows[1]
    later = chain.add(
        Kind.MINT, State.SHADOW, family="pm_us_crh_fq_v1_r0003", lineage_root_family_id=INCUMBENT
    )

    result = run(chain, LATE)

    assert lineage_of(result)["mints"] == (mint.ts_ns, chain.rows[2].ts_ns, later.ts_ns)
    assert lineage_of(result, OTHER)["mints"] == ()
    assert lineage_of(run(chain, mint.ts_ns))["mints"] == (mint.ts_ns,)


# --- promotions, rollbacks and the pair that never takes effect --------------------------------


def test_an_effective_promote_pair_charges_one_promotion_at_launch() -> None:
    chain, _head, _tail = activated_pair()

    assert lineage_of(run(chain, LAUNCH - 1))["promotions"] == ()  # still pending
    effective = run(chain, LAUNCH)

    assert lineage_of(effective)["promotions"] == (LAUNCH,)  # the pair counts once
    assert lineage_of(effective)["rollbacks"] == ()
    assert effective.venue_tallies.sender_changes == (LAUNCH,)
    assert run(chain, LAUNCH - 1).venue_tallies.sender_changes == ()


def test_an_effective_rollback_pair_charges_one_rollback_at_launch() -> None:
    chain, _head, _tail = activated_pair()
    back = chain.add(
        Kind.ROLLBACK, State.CHAMPION, family=INCUMBENT, frm=State.CHALLENGER,
        effective_launch_date=NEXT_DAY,
    )  # fmt: skip
    chain.add(
        Kind.SUPERSEDE, State.CHALLENGER, family=CHILD, frm=State.CHAMPION,
        paired_transition_id=back.transition_id, effective_launch_date=NEXT_DAY,
    )  # fmt: skip
    chain.activate(back, ts=at(NEXT_DAY, "16:45"), family=INCUMBENT)

    got = lineage_of(run(chain, NEXT_LATE))

    assert got["rollbacks"] == (NEXT_LAUNCH,)
    assert got["promotions"] == (LAUNCH,)  # only the earlier PROMOTE: a rollback is no promotion
    assert got["drill_rollbacks"] == ()
    assert run(chain, NEXT_LATE).venue_tallies.sender_changes == (LAUNCH, NEXT_LAUNCH)


def lapsed(chain: Chain, head: TransitionRow) -> None:
    del chain, head  # no ACTIVATE: the pair lapses at LAUNCH


def voided_before(chain: Chain, head: TransitionRow) -> None:
    chain.activate(head, ts=at(DAY, "16:45"))
    cancel(chain, head, ts=at(DAY, "16:46"))


def voided_after(chain: Chain, head: TransitionRow) -> None:
    chain.activate(head, ts=at(DAY, "16:45"))
    cancel(chain, head, ts=LAUNCH + 60 * SEC)


@pytest.mark.parametrize("settle", [lapsed, voided_before, voided_after])
@pytest.mark.parametrize("kind", [Kind.PROMOTE, Kind.DRILL_PROMOTE, Kind.ROLLBACK])
def test_lapsed_pair_never_charged(
    kind: Kind, settle: Callable[[Chain, TransitionRow], None]
) -> None:
    chain = drill_chain()
    head = chain.add(
        kind, State.CHAMPION, family=CHILD, frm=State.CHALLENGER, effective_launch_date=DAY,
        drill=kind is Kind.DRILL_PROMOTE,
    )  # fmt: skip
    chain.add(
        Kind.SUPERSEDE, State.CHALLENGER, family=INCUMBENT, frm=State.CHAMPION,
        paired_transition_id=head.transition_id, effective_launch_date=DAY,
    )  # fmt: skip
    settle(chain, head)

    result = run(chain, at(NEXT_DAY, "00:00"))

    assert result.pairs[0].status in (fm.PairStatus.LAPSED, fm.PairStatus.VOIDED)
    got = lineage_of(result)  # every family descends from INCUMBENT
    assert got["promotions"] == ()
    assert got["rollbacks"] == ()
    assert got["drill_promotes"] == ()
    assert got["drill_rollbacks"] == ()
    assert dict(result.states) == {INCUMBENT: State.CHAMPION, CHILD: State.CHALLENGER}
    assert result.venue_tallies == fm.VenueTallies()


def test_a_lapsed_pair_then_an_effective_pair_charges_only_the_effective_one() -> None:
    chain, _head, _tail = seeded_pair()  # lapses at DAY: no ACTIVATE
    second = chain.add(
        Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=NEXT_DAY,
    )  # fmt: skip
    chain.add(
        Kind.SUPERSEDE, State.CHALLENGER, family=INCUMBENT, frm=State.CHAMPION,
        paired_transition_id=second.transition_id, effective_launch_date=NEXT_DAY,
    )  # fmt: skip
    chain.activate(second, ts=at(NEXT_DAY, "16:45"))

    got = lineage_of(run(chain, NEXT_LATE))

    assert got["promotions"] == (NEXT_LAUNCH,)
    assert run(chain, NEXT_LATE).venue_tallies.sender_changes == (NEXT_LAUNCH,)


def test_root_admit_is_a_sender_change_and_no_promotion() -> None:
    chain = Chain()
    root = chain.add(
        Kind.ROOT_ADMIT, State.CHAMPION, family=OTHER, lineage_root_family_id=OTHER,
        effective_launch_date=DAY,
    )  # fmt: skip
    chain.activate(root, ts=at(DAY, "16:45"))

    result = run(chain, LATE)

    assert result.states[OTHER] is State.CHAMPION
    assert lineage_of(result, OTHER) == ZERO_LINEAGE
    assert result.venue_tallies == fm.VenueTallies(sender_changes=(LAUNCH,))


# --- drill budget ----------------------------------------------------------------------------


def test_drill_admit_charges_only_drill_budget() -> None:
    chain = drill_chain(admit=True)
    result = run(chain, LATE)

    got = lineage_of(result)

    assert got["drill_admits"] == (chain.rows[2].ts_ns,)
    assert got["nominations"] == 0
    assert got["infeasible_nominations"] == 0
    assert got["alpha_spent"] == 0  # no alpha, no K_LIFETIME
    assert got["nomination_instants"] == ()
    assert got["promotions"] == ()
    assert got["rollbacks"] == ()
    assert got["model_resumes"] == ()
    assert got["mints"] == (chain.rows[1].ts_ns,)  # the MINT is a mint, the admit is not
    assert {k: got[k] for k in DRILL_FIELDS if k != "drill_admits"} == {
        k: () for k in DRILL_FIELDS if k != "drill_admits"
    }
    assert result.venue_tallies == fm.VenueTallies()


def test_drill_episode_rows_charge_only_the_drill_counters() -> None:
    chain, _head, _closing = full_episode()
    chain.add(
        Kind.HALT, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=at(NEXT_DAY, "20:00"),
        halt_cause_class=CauseClass.DRILL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    result = run(chain, at(NEXT_DAY, "21:00"))

    child = incumbent = lineage_of(result)  # one lineage: the drill child descends from INCUMBENT

    assert child["drill_promotes"] == (LAUNCH,)
    assert child["drill_demotes"] == (at(DAY, "20:00"),)
    assert child["drill_resumes"] == (at(NEXT_DAY, "16:45"),)
    assert child["drill_halts"] == (at(NEXT_DAY, "20:00"),)
    assert incumbent["drill_rollbacks"] == (NEXT_LAUNCH,)  # the ROLLBACK that closed the episode
    assert child["promotions"] == ()
    assert child["rollbacks"] == ()
    assert child["model_resumes"] == ()
    assert child["terminal_frozen"] is False
    assert result.venue_tallies == fm.VenueTallies()  # no production counter, no sender change


# --- RESUME is charged to the cause class of its halt -----------------------------------------


def halt_then_resume(
    cls: CauseClass | None,
    *,
    trigger: CauseClass | None = None,
    resume_code: CauseCode | None = None,
) -> tuple[fm.FoldResult, int]:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, lineage_root_family_id=INCUMBENT)
    chain.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, halt_cause_class=cls,
        cause_code=CauseCode.ROLLBACK_FAILED if trigger else CauseCode.VERDICT_FAIL,
        trigger_cause_class=trigger,
    )  # fmt: skip
    resume = chain.add(
        Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED, cause_code=resume_code
    )
    return run(chain, LATE), resume.ts_ns


@pytest.mark.parametrize(
    ("cls", "trigger", "bucket"),
    [
        (CauseClass.RECOVERABLE_INFRA, None, "infra"),
        (CauseClass.DRILL, None, "drill"),
        (CauseClass.RECOVERABLE_MODEL, None, "model"),
        (CauseClass.ROLLBACK_FAILED, CauseClass.RECOVERABLE_INFRA, "infra"),
        (CauseClass.ROLLBACK_FAILED, CauseClass.DRILL, "drill"),
        (CauseClass.ROLLBACK_FAILED, CauseClass.RECOVERABLE_MODEL, "model"),
        (None, None, "none"),  # a halt with no class (7c/7d refuse it): a sender change only
    ],
)
def test_resume_charges_the_budget_of_its_own_cause_class(
    cls: CauseClass | None, trigger: CauseClass | None, bucket: str
) -> None:
    result, ts = halt_then_resume(cls, trigger=trigger)
    got = lineage_of(result)

    assert result.venue_tallies.infra_resumes == ((ts,) if bucket == "infra" else ())
    assert got["drill_resumes"] == ((ts,) if bucket == "drill" else ())
    assert got["model_resumes"] == ((ts,) if bucket == "model" else ())  # E-21: 14D budget
    assert result.venue_tallies.sender_changes == (() if bucket == "drill" else (ts,))  # Z3
    assert result.venue_tallies.drill_close_restores == ()
    assert got["promotions"] == ()


def test_a_drill_close_restore_charges_only_its_own_counter() -> None:
    result, ts = halt_then_resume(CauseClass.DRILL, resume_code=CauseCode.DRILL_CLOSE_RESTORE)

    assert result.venue_tallies == fm.VenueTallies(drill_close_restores=(ts,))
    assert lineage_of(result)["drill_resumes"] == ()
    assert lineage_of(result)["model_resumes"] == ()


def test_a_second_halt_is_charged_to_its_own_class_not_the_first() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, lineage_root_family_id=INCUMBENT)
    resumes = []
    for cls in (CauseClass.DRILL, CauseClass.RECOVERABLE_INFRA):
        chain.add(
            Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, halt_cause_class=cls,
            cause_code=CauseCode.VERDICT_FAIL,
        )  # fmt: skip
        row = chain.add(Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED)
        resumes.append(row.ts_ns)

    result = run(chain, LATE)

    assert lineage_of(result)["drill_resumes"] == (resumes[0],)
    assert result.venue_tallies.infra_resumes == (resumes[1],)


def test_resumes_are_charged_when_the_clock_reaches_them() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, lineage_root_family_id=INCUMBENT)
    chain.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        halt_cause_class=CauseClass.RECOVERABLE_INFRA, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    resume = chain.add(Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED)

    assert run(chain, resume.ts_ns - 1).venue_tallies.infra_resumes == ()
    assert run(chain, resume.ts_ns).venue_tallies.infra_resumes == (resume.ts_ns,)


# --- restrictive rows, TARGET_INELIGIBLE and the terminal freeze -------------------------------


def test_target_ineligible_never_counted_or_operator_cleared() -> None:
    chain, _head, _tail = activated_pair()
    before = run(chain, LATE)
    chain.add(
        Kind.TARGET_INELIGIBLE, State.CHALLENGER, family=INCUMBENT, frm=State.CHALLENGER,
        cause_code=CauseCode.TARGET_INTEGRITY,
    )  # fmt: skip
    for family, state in ((CHILD, State.CHAMPION), (INCUMBENT, State.CHALLENGER)):
        chain.add(
            Kind.HWM_RESET, state, family=family, frm=state, decided_by=DecidedBy.OPERATOR_CLI,
            hwm_from=1, hwm_to=2, carried_counters=carried(),
        )  # fmt: skip

    after = run(chain, LATE)

    assert view(after, INCUMBENT).target_ineligible  # the operator row did not clear it
    assert not view(before, INCUMBENT).target_ineligible
    assert lineage_of(after) == lineage_of(before)
    assert after.venue_tallies == before.venue_tallies


def test_restrictive_and_attest_rows_are_never_counted() -> None:
    chain = rooted()
    before = lineage_of(run(chain, LATE))
    chain.add(
        Kind.ATTEST, State.CHAMPION, family=INCUMBENT, frm=State.CHAMPION,
        attest_valid_until_ns=at(DAY, "23:00"),
    )  # fmt: skip
    chain.add(
        Kind.SWAP_CANCEL, State.SHADOW, family=CHILD, frm=State.SHADOW,
        cause_code=CauseCode.PAIR_CAUSE_INCOMING, voids_transition_ids=("d" * 64,),
    )  # fmt: skip
    chain.add(
        Kind.DEMOTE, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip

    assert lineage_of(run(chain, LATE)) == before


def test_terminal_frozen_tally_follows_the_lineage_freeze() -> None:
    chain = rooted()
    chain.add(Kind.BOOTSTRAP, State.RETIRED, family=OTHER, lineage_root_family_id=OTHER)
    chain.add(
        Kind.HALT, State.HALTED, family=CHILD, frm=State.SHADOW,
        halt_cause_class=CauseClass.TERMINAL, cause_code=CauseCode.EXEC_STORE_HALT_MIRROR,
    )  # fmt: skip

    result = run(chain, LATE)

    assert lineage_of(result)["terminal_frozen"] is True
    assert lineage_of(result, OTHER)["terminal_frozen"] is False
    assert view(result, INCUMBENT).terminal_frozen


# --- halted_since_ns -------------------------------------------------------------------------


def test_halted_since_is_the_instant_of_the_row_that_made_the_family_halted() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, lineage_root_family_id=INCUMBENT)
    halt = chain.add(
        Kind.DEMOTE, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, ts=at(DAY, "10:00"),
        halt_cause_class=CauseClass.RECOVERABLE_INFRA, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    chain.add(
        Kind.HWM_RESET, State.HALTED, family=INCUMBENT, frm=State.HALTED, ts=at(DAY, "11:00"),
        decided_by=DecidedBy.OPERATOR_CLI, hwm_from=1, hwm_to=2, carried_counters=carried(),
    )  # fmt: skip

    halted = view(run(chain, LATE), INCUMBENT)

    assert halted.state is State.HALTED
    assert halted.halted_since_ns == halt.ts_ns  # a same-state row does not restart it
    assert view(run(chain, halt.ts_ns - 1), INCUMBENT).halted_since_ns is None


def test_halted_since_clears_on_resume_and_restarts_on_the_next_halt() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, lineage_root_family_id=INCUMBENT)
    chain.add(Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, ts=at(DAY, "10:00"))
    chain.add(Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED, ts=at(DAY, "11:00"))
    resumed = view(run(chain, at(DAY, "12:00")), INCUMBENT)
    again = chain.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, ts=at(DAY, "13:00")
    )

    assert resumed.halted_since_ns is None
    assert view(run(chain, LATE), INCUMBENT).halted_since_ns == again.ts_ns


def test_halted_since_clears_when_a_displaced_halted_family_returns_to_challenger() -> None:
    chain, head, _tail = seeded_pair(partner=Kind.DISPLACED)
    chain.activate(head, ts=at(DAY, "16:45"))

    before = run(chain, LAUNCH - 1)
    after = run(chain, LATE)

    assert view(before, INCUMBENT).halted_since_ns is not None
    assert view(after, INCUMBENT).halted_since_ns is None
    assert view(after, CHILD).halted_since_ns is None


def test_a_family_that_was_never_halted_has_no_halted_since() -> None:
    result = run(rooted(), LATE)

    assert all(v.halted_since_ns is None for v in result.families.values())


# --- the added fields change no earlier result ------------------------------------------------


def test_new_result_fields_are_deterministic() -> None:
    chain, _head, _tail = activated_pair()

    first = run(chain, LATE)
    second = run(chain, LATE)

    assert first == second
    assert first.lineages == second.lineages
