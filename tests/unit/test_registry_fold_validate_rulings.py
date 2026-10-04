"""ARCH-0 seam 7c review rulings A7c-R2, R4, R5, R7, R8 (R1 flips a test in the resume file).

The generic ``from_state`` rule, the DRILL-class halt gate, E-5 bound to the actual failed close,
the immutable artefact binding, the incumbent ``demoted_for_cause`` check and the verdict-backed
RESUME. The module is reached through ``tm`` so each test fails by itself while a rule is missing.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

import breezy.persistence.autonomy.transitions as tm
from breezy.persistence.autonomy.schemas import (
    CauseClass,
    CauseCode,
    Kind,
    RefusalReason,
    State,
)
from breezy.persistence.autonomy.verdict import VerdictOutcome
from tests.unit.test_registry_fold import (
    CHILD,
    DAY,
    INCUMBENT,
    LAUNCH,
    OTHER,
    SEC,
    Chain,
    at,
    run,
)
from tests.unit.test_registry_fold_effects import NEXT_DAY, cancel
from tests.unit.test_registry_fold_validate import (
    CITED,
    DRILL_CAUSE,
    HALT_TS,
    INC_ART,
    INC_MAN,
    RESTORE,
    RESTORE_TS,
    RESUME_TS,
    admitted,
    champion_chain,
    facts_for_child,
    forward_shadow,
    model_halted,
    no_facts,
    probe,
    restore,
    resume,
    rule_of,
)

# --- A7c-R2: every row's from_state equals the fold state ------------------------------------


@pytest.mark.parametrize(
    ("frm", "rule"),
    [
        (State.CHAMPION, None),
        (State.CHALLENGER, "from_state_mismatch"),
        (None, "from_state_mismatch"),
    ],
    ids=["equal", "other_state", "introducer_shape"],
)
def test_from_state_must_equal_the_fold_state(frm: State | None, rule: str | None) -> None:
    refused = probe(
        champion_chain(), LAUNCH, Kind.HALT, State.HALTED, family=INCUMBENT, frm=frm,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL,
    )  # fmt: skip
    assert rule_of(refused) == rule


def test_an_introducing_row_has_no_from_state_and_a_known_family_cannot_be_introduced() -> None:
    chain = champion_chain()
    new = probe(chain, LAUNCH, Kind.MINT, State.SHADOW, family=OTHER, frm=None,
                lineage_root_family_id=INCUMBENT)  # fmt: skip
    assert new is None
    wrong = probe(champion_chain(), LAUNCH, Kind.MINT, State.SHADOW, family=OTHER, frm=State.SHADOW)
    assert rule_of(wrong) == "from_state_mismatch"
    again = probe(champion_chain(), LAUNCH, Kind.MINT, State.SHADOW, family=CHILD, frm=None)
    assert rule_of(again) == "from_state_mismatch"


def test_from_state_follows_the_rows_earlier_in_the_batch() -> None:
    chain = champion_chain()
    prior = run(chain, LAUNCH)
    first = chain.add(Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION)
    second = chain.add(Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION)
    refused = tm.first_refusal(prior, [first, second], manifests=no_facts)
    assert refused is not None and (refused.rule.value, refused.row_index) == (
        "from_state_mismatch", 1,
    )  # fmt: skip


def test_a_model_halted_family_cannot_be_re_halted_as_drill_class() -> None:
    """V12 first cause wins: the laundering route to a budget-free restore is closed."""
    for extra in (
        DRILL_CAUSE,
        {"halt_cause_class": CauseClass.ROLLBACK_FAILED, "cause_code": CauseCode.ROLLBACK_FAILED,
         "trigger_cause_class": CauseClass.DRILL},
    ):  # fmt: skip
        by_state = probe(
            model_halted(), RESUME_TS, Kind.HALT, State.HALTED, family=INCUMBENT,
            frm=State.CHAMPION, **extra,
        )  # fmt: skip
        assert rule_of(by_state) == "from_state_mismatch"
        # even a row that states the fold's own state is refused: the family is not CHAMPION
        by_class = probe(
            model_halted(), RESUME_TS, Kind.HALT, State.HALTED, family=INCUMBENT,
            frm=State.HALTED, **extra,
        )  # fmt: skip
        assert rule_of(by_class) == "drill_cause_stands"
    assert rule_of(restore(model_halted())) == "restore_not_failed_drill_close"


def test_a_drill_class_halt_of_a_champion_with_a_standing_cause_is_refused() -> None:
    chain = champion_chain()
    cancel(chain, chain.rows[0], ts=at(DAY, "10:00"), cause=CauseCode.PAIR_CAUSE_INCOMING,
           voids=("e" * 64,), family=INCUMBENT)  # fmt: skip
    chain.rows[-1] = replace(chain.rows[-1], from_state=State.CHAMPION, to_state=State.CHAMPION)
    assert run(chain, LAUNCH).families[INCUMBENT].demoted_for_cause
    refused = probe(chain, LAUNCH, Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
                    **DRILL_CAUSE)  # fmt: skip
    assert rule_of(refused) == "drill_cause_stands"
    clear = probe(champion_chain(), LAUNCH, Kind.HALT, State.HALTED, family=INCUMBENT,
                  frm=State.CHAMPION, **DRILL_CAUSE)  # fmt: skip
    assert clear is None


# --- A7c-R7: the drill incumbent is not demoted_for_cause --------------------------------------


@pytest.mark.parametrize("kind", [Kind.DRILL_ADMIT, Kind.DRILL_PROMOTE])
def test_drill_entry_refused_over_a_demoted_for_cause_incumbent(kind: Kind) -> None:
    chain = champion_chain()
    cancel(chain, chain.rows[0], ts=at(DAY, "10:00"), cause=CauseCode.PAIR_CAUSE_INCOMING,
           voids=("e" * 64,), family=INCUMBENT)  # fmt: skip
    assert run(chain, LAUNCH).families[INCUMBENT].demoted_for_cause
    if kind is Kind.DRILL_PROMOTE:
        admitted(chain)
    frm = State.SHADOW if kind is Kind.DRILL_ADMIT else State.CHALLENGER
    to = State.CHALLENGER if kind is Kind.DRILL_ADMIT else State.CHAMPION
    extra: dict[str, Any] = {"effective_launch_date": DAY} if kind is Kind.DRILL_PROMOTE else {}
    refused = probe(chain, LAUNCH, kind, to, family=CHILD, frm=frm, artefact_sha256=INC_ART,
                    manifest_sha256="2" * 64, manifests=facts_for_child, **extra)  # fmt: skip
    assert rule_of(refused) == "drill_cause_stands"


# --- A7c-R4: E-5 binds to the actual failed close --------------------------------------------


def failed_close_then(*, halt_after_close: bool = True, who: str = INCUMBENT) -> Chain:
    """A drill (child promoted at LAUNCH D) whose episode ends when the child is RETIRED."""
    chain = champion_chain()
    chain.add(Kind.DRILL_ADMIT, State.CHALLENGER, family=CHILD, frm=State.SHADOW,
              artefact_sha256=INC_ART)  # fmt: skip
    head, _tail = chain.drill_pair(DAY)
    chain.activate(head, ts=at(DAY, "16:45"))
    if not halt_after_close:
        _halt(chain, who, at(DAY, "20:00"))
    chain.add(
        Kind.RETIRE, State.RETIRED, family=CHILD, frm=State.CHAMPION, ts=at(NEXT_DAY, "10:00")
    )
    if halt_after_close:
        _halt(chain, who, at(NEXT_DAY, "16:55"))
    return chain


def _halt(chain: Chain, who: str, ts: int) -> None:
    chain.add(Kind.HALT, State.HALTED, family=who, frm=State.CHAMPION, ts=ts,
              halt_cause_class=CauseClass.ROLLBACK_FAILED, cause_code=CauseCode.ROLLBACK_FAILED,
              trigger_cause_class=CauseClass.DRILL)  # fmt: skip


def test_restore_needs_a_closed_episode_and_a_halt_at_or_after_its_end() -> None:
    assert restore(failed_close_then()) is None
    before_end = failed_close_then(halt_after_close=False)
    assert rule_of(restore(before_end)) == "restore_not_failed_drill_close"


def test_restore_refused_while_the_latest_episode_is_still_open() -> None:
    chain = champion_chain()
    chain.add(Kind.DRILL_ADMIT, State.CHALLENGER, family=CHILD, frm=State.SHADOW,
              artefact_sha256=INC_ART)  # fmt: skip
    head, _tail = chain.drill_pair(DAY)
    chain.activate(head, ts=at(DAY, "16:45"))
    _halt(chain, INCUMBENT, at(NEXT_DAY, "16:55"))
    assert rule_of(restore(chain)) == "restore_not_failed_drill_close"


def test_restore_refused_for_a_family_the_drill_did_not_supersede() -> None:
    chain = failed_close_then()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=OTHER, manifest_sha256=INC_MAN,
              artefact_sha256=INC_ART)  # fmt: skip
    _halt(chain, OTHER, at(NEXT_DAY, "17:30"))
    refused = restore(chain, family=OTHER)
    assert rule_of(refused) == "restore_not_the_incumbent"


# --- A7c-R5: the artefact binding is immutable -------------------------------------------------


def test_family_artefact_binding_immutable() -> None:
    chain = champion_chain()
    chain.add(Kind.ATTEST, State.CHAMPION, family=INCUMBENT, frm=State.CHAMPION,
              artefact_sha256="3" * 64)  # fmt: skip
    assert run(chain, LAUNCH).families[INCUMBENT].artefact_sha256 == INC_ART  # the fold keeps it

    for other, rule in (("3" * 64, "artefact_binding_immutable"), (INC_ART, None), (None, None)):
        refused = probe(
            champion_chain(), LAUNCH, Kind.ATTEST, State.CHAMPION, family=INCUMBENT,
            frm=State.CHAMPION, artefact_sha256=other,
        )  # fmt: skip
        assert rule_of(refused) == rule
        if rule:
            assert refused is not None and refused.reason is RefusalReason.ARTEFACT_SHA_MISMATCH


# --- A7c-R8: verdict-backed RESUME and the missing halt instant ----------------------------------


def _resume_with(verdict_ns: int, outcome: VerdictOutcome = VerdictOutcome.PASS,
                 *, resolve: bool = True) -> Any:  # fmt: skip
    verdict = forward_shadow(outcome, produced_at_ns=verdict_ns, family=INCUMBENT)
    return resume(
        model_halted(), cause_verdict_ids=(verdict.verdict_id,),
        verdicts={verdict.verdict_id: verdict} if resolve else {},
    )  # fmt: skip


def test_resume_with_verdicts_needs_each_cited_one_to_pass_after_the_halt() -> None:
    assert _resume_with(HALT_TS + SEC) is None
    assert rule_of(_resume_with(HALT_TS)) == "resume_verdict_not_pass"
    assert rule_of(_resume_with(HALT_TS - SEC)) == "resume_verdict_not_pass"
    assert rule_of(_resume_with(HALT_TS + SEC, VerdictOutcome.FAIL)) == "resume_verdict_not_pass"
    assert rule_of(_resume_with(HALT_TS + SEC, resolve=False)) == "resume_verdict_not_pass"
    assert resume(model_halted()) is None  # no mapping supplied: the replay (8b) judges them


@pytest.mark.parametrize("restoring", [False, True], ids=["ordinary", "restore"])
def test_a_halted_family_without_a_halt_instant_is_refused(restoring: bool) -> None:
    chain = failed_close_then() if restoring else model_halted()
    prior = run(chain, RESTORE_TS if restoring else RESUME_TS)
    view = replace(prior.families[INCUMBENT], halted_since_ns=None)
    prior = replace(prior, families={**prior.families, INCUMBENT: view})
    extra: dict[str, Any] = dict(RESTORE) if restoring else {"cause_verdict_ids": CITED}
    row = chain.add(Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED,
                    ts=RESTORE_TS if restoring else RESUME_TS, **extra)  # fmt: skip
    refused = tm.first_refusal(prior, [row], manifests=no_facts)
    assert refused is not None and refused.rule.value == "resume_no_halt_instant"


def test_a_drill_class_halt_of_a_family_that_is_not_champion_is_refused() -> None:
    chain = champion_chain()
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)
    refused = probe(
        chain, LAUNCH, Kind.HALT, State.HALTED, family=CHILD, frm=State.CHALLENGER, **DRILL_CAUSE
    )
    assert rule_of(refused) == "drill_cause_stands"
