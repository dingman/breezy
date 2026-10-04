"""ARCH-0 seam 7c: ``validate`` RESUME rules and the E-5 restorative RESUME (fold-file tests).

A RESUME is refused while a pair is pending, unless the family is HALTED for a class that resumes,
the cause is cited, the cooldown has passed and its own cause class has budget (Y8, Z10, W2, V12);
ROLLBACK_FAILED resumes only under its ``trigger_cause_class``. The E-5 restore after a failed
drill close charges and needs no budget. Helpers are shared with ``test_registry_fold_validate.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

import breezy.persistence.autonomy.transitions as tm
from breezy.persistence.autonomy.schemas import CauseClass, CauseCode, Kind, State, WriterMode
from breezy.persistence.autonomy.stage_policy import STAGE
from tests.unit.test_registry_fold import (
    CHILD,
    DAY,
    INCUMBENT,
    OTHER,
    Chain,
    at,
    run,
)
from tests.unit.test_registry_fold_effects import NEXT_DAY, DrillChain
from tests.unit.test_registry_fold_validate import (
    CITED,
    DAY_NS,
    HALT_TS,
    HOUR_NS,
    RESTORE_TS,
    RESUME_TS,
    champion_chain,
    exhaust,
    failed_close_chain,
    freeze_venue,
    halt_incumbent,
    model_halted,
    no_facts,
    restore,
    resume,
    rule_of,
)

# --- RESUME (Y8, Z10, W2, V12) ------------------------------------------------------------------


def test_resume_accepts_a_cleared_recoverable_halt() -> None:
    chain = model_halted()
    assert resume(chain) is None
    assert (
        tm.validate(
            run(model_halted(), RESUME_TS),
            [chain.rows[-1]],
            mode=WriterMode.PRELAUNCH,
            now_ns=RESUME_TS,
            stage=STAGE,
            manifests=no_facts,
        )
        is None
    )


def test_resume_requires_every_cause_cleared() -> None:
    assert rule_of(resume(model_halted(), cause_verdict_ids=())) == "resume_uncited"

    frozen = model_halted()
    freeze_venue(frozen)
    assert rule_of(resume(frozen)) == "resume_exec_halt"

    assert resume(model_halted()) is None


def test_resume_refused_while_swap_pending() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
    chain.add(Kind.MINT, State.SHADOW, family=CHILD)
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)
    halt_incumbent(chain, CauseClass.RECOVERABLE_MODEL, ts=HALT_TS)
    head, _tail = chain.promote_pair(partner=Kind.DISPLACED)
    chain.activate(head, ts=at(DAY, "16:44"))

    before_launch = resume(chain, now=at(DAY, "16:46"), ts=at(DAY, "16:46"))

    assert rule_of(before_launch) == "resume_pair_pending"


def test_resume_is_not_refused_once_the_pair_has_lapsed() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
    chain.add(Kind.MINT, State.SHADOW, family=CHILD)
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)
    halt_incumbent(chain, CauseClass.RECOVERABLE_MODEL, ts=HALT_TS)
    chain.promote_pair(partner=Kind.DISPLACED)  # never activated: lapses at LAUNCH

    after_launch = resume(chain, now=at(DAY, "17:30"), ts=at(DAY, "17:30"))

    assert after_launch is None


@pytest.mark.parametrize(
    ("cls", "rule"),
    [
        (CauseClass.TERMINAL, "resume_class"),
        (CauseClass.INTEGRITY, "resume_exec_halt"),  # an INTEGRITY halt also freezes the venue
        (CauseClass.ROLLBACK_FAILED, "resume_class"),
        (None, "resume_class"),
    ],
    ids=["terminal", "integrity", "rollback_failed_class", "no_class"],
)
def test_resume_refused_for_a_class_that_never_resumes(cls: CauseClass | None, rule: str) -> None:
    chain = champion_chain()
    halt_incumbent(chain, cls)

    assert rule_of(resume(chain)) == rule


def test_resume_refused_for_a_family_that_is_not_halted() -> None:
    # a row whose from_state is not the fold's state is refused first (A7c-R2) ...
    assert rule_of(resume(champion_chain())) == "from_state_mismatch"
    assert rule_of(resume(Chain())) == "from_state_mismatch"
    # ... and one that names the fold's own state still finds nothing to resume
    assert rule_of(resume(champion_chain(), frm=State.CHAMPION)) == "resume_not_halted"


def test_resume_refused_inside_the_cooldown() -> None:
    cooldown = 24 * HOUR_NS
    assert rule_of(resume(model_halted(), ts=HALT_TS + cooldown - 1, now=HALT_TS + cooldown)) == (
        "resume_cooldown"
    )
    assert resume(model_halted(), ts=HALT_TS + cooldown, now=HALT_TS + cooldown) is None


@pytest.mark.parametrize(
    ("trigger", "rule"),
    [
        (CauseClass.RECOVERABLE_MODEL, None),
        (CauseClass.RECOVERABLE_INFRA, None),
        (CauseClass.DRILL, None),
        (CauseClass.TERMINAL, "resume_class"),
        (CauseClass.INTEGRITY, "resume_class"),
        (CauseClass.ROLLBACK_FAILED, "resume_class"),
        (None, "resume_class"),
    ],
)
def test_rollback_failed_resumes_only_under_trigger_class(
    trigger: CauseClass | None, rule: str | None
) -> None:
    chain = champion_chain()
    halt_incumbent(
        chain, CauseClass.ROLLBACK_FAILED, code=CauseCode.ROLLBACK_FAILED, trigger=trigger
    )

    assert rule_of(resume(chain)) == rule


def test_model_resume_budget_is_two_per_lineage_in_fourteen_days() -> None:
    floor = RESUME_TS - 14 * DAY_NS
    recent = RESUME_TS - DAY_NS

    spent = model_halted()
    exhaust(spent, {INCUMBENT: {"model_resumes": (floor + 1, recent)}})
    assert rule_of(resume(spent)) == "resume_budget"

    aged = model_halted()
    exhaust(aged, {INCUMBENT: {"model_resumes": (floor, recent)}})  # the first has left the window
    assert resume(aged) is None

    elsewhere = model_halted()
    exhaust(elsewhere, {OTHER: {"model_resumes": (recent, recent)}})  # another lineage's budget
    assert resume(elsewhere) is None


def test_infra_resume_budget_is_three_per_venue_in_seven_days() -> None:
    floor = RESUME_TS - 7 * DAY_NS
    recent = RESUME_TS - DAY_NS

    def infra_halted(*instants: int) -> DrillChain:
        chain = champion_chain()
        halt_incumbent(chain, CauseClass.RECOVERABLE_INFRA)
        exhaust(chain, infra_resumes=instants)
        return chain

    assert rule_of(resume(infra_halted(floor + 1, recent, recent))) == "resume_budget"
    assert resume(infra_halted(floor, recent, recent)) is None
    assert resume(infra_halted(recent)) is None


def test_a_second_resume_in_one_batch_sees_the_first() -> None:
    chain = champion_chain()
    halt_incumbent(chain, CauseClass.RECOVERABLE_MODEL)
    chain.add(  # a sibling of the same lineage, halted for the same class
        Kind.HALT, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=HALT_TS + 1,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    exhaust(chain, {INCUMBENT: {"model_resumes": (RESUME_TS - DAY_NS,)}})
    prior = run(chain, RESUME_TS)
    rows = [
        chain.add(
            Kind.RESUME,
            State.CHAMPION,
            family=family,
            frm=State.HALTED,
            ts=RESUME_TS,
            cause_verdict_ids=CITED,
        )
        for family in (INCUMBENT, CHILD)
    ]

    assert tm.first_refusal(prior, rows[:1], manifests=no_facts) is None
    refused = tm.first_refusal(prior, rows, manifests=no_facts)
    assert refused is not None and (refused.rule.value, refused.row_index) == ("resume_budget", 1)


def test_drill_resume_never_charges_model_budget() -> None:
    chain = champion_chain()
    halt_incumbent(chain, CauseClass.DRILL)
    exhaust(chain, {INCUMBENT: {"model_resumes": (RESUME_TS - HOUR_NS, RESUME_TS - 2 * HOUR_NS)}})
    candidate = resume(chain)
    assert candidate is None  # the exhausted model budget does not bear on a DRILL resume

    after = run(chain, RESUME_TS).lineages[INCUMBENT].tallies  # the probe appended the RESUME
    assert after.drill_resumes == (RESUME_TS,)
    assert after.model_resumes == (RESUME_TS - 2 * HOUR_NS, RESUME_TS - HOUR_NS)  # the floor only


def test_a_drill_resume_is_capped_by_the_drill_budget_alone() -> None:
    chain = champion_chain()
    halt_incumbent(chain, CauseClass.DRILL)
    exhaust(chain, {INCUMBENT: {"drill_resumes": (RESUME_TS - DAY_NS,)}})

    assert rule_of(resume(chain)) == "drill_budget"


def test_drill_close_restore_accepts_the_failed_close() -> None:
    assert restore(failed_close_chain()) is None


def test_drill_close_restore_charges_no_drill_or_production_budget() -> None:
    """Every budget exhausted: the restore waits for the cooldown, then is admitted (A7c-R1)."""
    spent = RESTORE_TS - HOUR_NS
    chain = failed_close_chain()
    exhaust(
        chain,
        {
            INCUMBENT: {
                "model_resumes": (spent, spent),
                "drill_resumes": (spent,),
                "drill_demotes": (spent,),
            }
        },
        infra_resumes=(spent, spent, spent),
    )
    soon = at(NEXT_DAY, "17:10")  # 15 minutes after the failed close: inside the cooldown
    assert rule_of(restore(failed_close_chain(), ts=soon)) == "resume_cooldown"
    almost = at(NEXT_DAY, "16:55") + 24 * HOUR_NS - 1
    assert rule_of(restore(failed_close_chain(), ts=almost)) == "resume_cooldown"

    soon = RESTORE_TS  # C+2 16:45: the halt (C 16:55) is more than 24 h old
    assert restore(chain, ts=soon) is None

    after = run(chain, soon)  # the probe appended the restore
    assert after.venue_tallies.drill_close_restores == (soon,)
    assert after.lineages[INCUMBENT].tallies.drill_resumes == (spent,)  # unchanged by the restore
    assert after.venue_tallies.infra_resumes == (spent, spent, spent)


@pytest.mark.parametrize(
    "case",
    ["model_cause", "rollback_failed_under_model", "no_drill_episode"],
)
def test_drill_close_restore_refused_after_non_drill_cause(case: str) -> None:
    def model(chain: Chain) -> None:
        halt_incumbent(chain, CauseClass.RECOVERABLE_MODEL, ts=at(NEXT_DAY, "16:55"))

    def under_model(chain: Chain) -> None:
        halt_incumbent(
            chain, CauseClass.ROLLBACK_FAILED, code=CauseCode.ROLLBACK_FAILED,
            trigger=CauseClass.RECOVERABLE_MODEL, ts=at(NEXT_DAY, "16:55"),
        )  # fmt: skip

    def no_episode() -> DrillChain:  # a ROLLBACK_FAILED/DRILL halt, but no drill ever ran
        chain = champion_chain()
        halt_incumbent(
            chain, CauseClass.ROLLBACK_FAILED, code=CauseCode.ROLLBACK_FAILED,
            trigger=CauseClass.DRILL,
        )  # fmt: skip
        return chain

    chain = {
        "model_cause": lambda: failed_close_chain(halt=model),
        "rollback_failed_under_model": lambda: failed_close_chain(halt=under_model),
        "no_drill_episode": no_episode,
    }[case]()

    assert rule_of(restore(chain)) == "restore_not_failed_drill_close"


def test_drill_close_restore_refused_while_an_exec_store_halt_stands() -> None:
    chain = failed_close_chain()
    freeze_venue(chain)

    assert rule_of(restore(chain)) == "resume_exec_halt"


@pytest.mark.parametrize(
    "sha_kwargs",
    [
        {"artefact_sha256": "9" * 64},
        {"manifest_sha256": "9" * 64},
        {"artefact_sha256": None},
        {"manifest_sha256": None},
    ],
    ids=["artefact_differs", "manifest_differs", "artefact_absent", "manifest_absent"],
)
def test_drill_close_restore_refused_when_its_shas_differ_from_the_family(
    sha_kwargs: dict[str, Any],
) -> None:
    assert rule_of(restore(failed_close_chain(), **sha_kwargs)) == "restore_sha_mismatch"
