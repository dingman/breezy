"""ARCH-0 seam 7a: the full ``fold`` (SWAP_CANCEL voiding, freezes, flags, drill episodes).

6b's ``test_registry_fold.py`` pins the structural fold (states, pending pairs, the ACTIVATE window,
the lapse). These tests pin what 7a adds on top of it, all of it a pure function of rows and the
clock:

* a SWAP_CANCEL voids the pending pair it lists, before LAUNCH always and in [LAUNCH, 17:00Z) as a
  retroactive void of a pair that took effect (Z8); from 17:00Z it voids nothing;
* the per-family flags ``rollback_eligible``, ``demoted_for_cause`` and ``target_ineligible``;
* the lineage ``terminal_frozen`` freeze and the venue INTEGRITY freeze;
* drill episodes, ``[DRILL_PROMOTE effective, closing ROLLBACK effective)``.

Tallies are seam 7b and ``validate`` is 7c/7d, so nothing here is charged or refused: a lapsed or
voided pair is shown never to have an effect.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from breezy.persistence.autonomy.fold import (
    DrillEpisode,
    FamilyView,
    FoldResult,
    PairStatus,
    fold,
)
from breezy.persistence.autonomy.schemas import CauseClass, CauseCode, Kind, State, TransitionRow
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

NEXT_DAY = "2026-10-11"
AFTER_17 = at(DAY, "17:00")
LATE = at(DAY, "18:00")
NEXT_LAUNCH = at(NEXT_DAY, "16:50")
NEXT_LATE = at(NEXT_DAY, "18:00")
ONE_NS = 1


def cancel(
    chain: Chain,
    head: TransitionRow,
    *,
    ts: int,
    cause: CauseCode = CauseCode.PRELAUNCH_PRECHECK_FAILED,
    voids: tuple[str, ...] | None = None,
    family: str = CHILD,
) -> TransitionRow:
    return chain.add(
        Kind.SWAP_CANCEL, State.CHALLENGER, family=family, frm=State.CHALLENGER, ts=ts,
        cause_code=cause,
        voids_transition_ids=(head.transition_id,) if voids is None else voids,
    )  # fmt: skip


def activated_pair() -> tuple[Chain, TransitionRow, TransitionRow]:
    chain, head, tail = seeded_pair()
    chain.activate(head, ts=at(DAY, "16:45"))
    return chain, head, tail


def view(result: FoldResult, family: str) -> FamilyView:
    return result.families[family]


# --- SWAP_CANCEL voiding --------------------------------------------------------------------


def test_swap_cancel_before_launch_voids_the_pending_pair() -> None:
    chain, head, _tail = activated_pair()
    row = cancel(chain, head, ts=at(DAY, "16:46"))

    result = run(chain, LATE)

    pair = result.pairs[0]
    assert pair.status is PairStatus.VOIDED
    assert pair.voided_by_transition_id == row.transition_id
    assert result.states == {INCUMBENT: State.CHAMPION, CHILD: State.CHALLENGER}


def test_swap_cancel_is_not_applied_before_its_own_timestamp() -> None:
    chain, head, _tail = activated_pair()
    cancel(chain, head, ts=at(DAY, "16:46"))

    result = run(chain, at(DAY, "16:45", 30 * SEC))

    assert result.pairs[0].status is PairStatus.PENDING
    assert result.pairs[0].voided_by_transition_id is None


def test_swap_cancel_listing_a_partner_voids_the_whole_pair() -> None:
    chain, head, tail = activated_pair()
    cancel(chain, head, ts=at(DAY, "16:46"), voids=(tail.transition_id,))

    result = run(chain, LATE)

    assert result.pairs[0].status is PairStatus.VOIDED
    assert result.states[INCUMBENT] is State.CHAMPION
    assert result.states[CHILD] is State.CHALLENGER


@pytest.mark.parametrize(
    "voids",
    [(), None, ("c" * 64,)],
    ids=["empty", "none", "unknown_id"],
)
def test_swap_cancel_listing_no_pair_member_voids_nothing(voids: tuple[str, ...] | None) -> None:
    chain, head, _tail = activated_pair()
    row = chain.add(
        Kind.SWAP_CANCEL, State.CHALLENGER, family=CHILD, frm=State.CHALLENGER,
        ts=at(DAY, "16:46"), cause_code=CauseCode.ENGINE_INCONSISTENCY,
        voids_transition_ids=voids,
    )  # fmt: skip
    assert row.transition_id != head.transition_id

    result = run(chain, LATE)

    assert result.pairs[0].status is PairStatus.EFFECTIVE
    assert result.states[CHILD] is State.CHAMPION


def test_swap_cancel_written_before_the_pair_voids_nothing() -> None:
    chain, head, _tail = activated_pair()
    cancel(chain, head, ts=at(DAY, "16:46"))
    rows = list(chain.rows)
    rows.insert(rows.index(head), rows.pop())  # the cancel now precedes the pair it cites

    result = fold(rows, VENUE, LATE)

    assert isinstance(result, FoldResult)
    assert result.pairs[0].status is PairStatus.EFFECTIVE


def test_swap_cancel_voids_only_the_pair_it_lists() -> None:
    chain, head, _tail = activated_pair()
    cancel(chain, head, ts=at(DAY, "16:46"))
    second_head, _second_tail = chain.promote_pair(day=NEXT_DAY, outgoing=INCUMBENT)
    chain.activate(second_head, ts=at(NEXT_DAY, "16:45"))

    result = run(chain, NEXT_LATE)

    assert [p.status for p in result.pairs] == [PairStatus.VOIDED, PairStatus.EFFECTIVE]
    assert result.states == {INCUMBENT: State.CHALLENGER, CHILD: State.CHAMPION}


@pytest.mark.parametrize(
    ("cancel_ts", "voided"),
    [
        pytest.param(LAUNCH, True, id="at_launch"),
        pytest.param(LAUNCH + ONE_NS, True, id="just_after_launch"),
        pytest.param(AFTER_17 - ONE_NS, True, id="last_ns_before_1700"),
        pytest.param(AFTER_17, False, id="at_1700"),
        pytest.param(AFTER_17 + ONE_NS, False, id="after_1700"),
    ],
)
def test_post_launch_swap_cancel_voids_pair_only_before_1700(cancel_ts: int, voided: bool) -> None:
    chain, head, _tail = activated_pair()
    cancel(chain, head, ts=cancel_ts)

    result = run(chain, at(DAY, "23:00"))

    assert (result.pairs[0].status is PairStatus.VOIDED) is voided
    assert result.pairs[0].status in {PairStatus.VOIDED, PairStatus.EFFECTIVE}
    sender = INCUMBENT if voided else CHILD
    assert result.states[sender] is State.CHAMPION


@pytest.mark.parametrize("case", ["fold"])
def test_post_launch_swap_cancel_restores_incumbent(case: str) -> None:
    assert case == "fold"
    chain, head, _tail = activated_pair()
    cancel(chain, head, ts=at(DAY, "16:55"))

    between = run(chain, at(DAY, "16:52"))
    after = run(chain, LATE)

    assert between.states == {INCUMBENT: State.CHALLENGER, CHILD: State.CHAMPION}
    assert between.senders == (CHILD,)
    assert after.states == {INCUMBENT: State.CHAMPION, CHILD: State.CHALLENGER}
    assert after.senders == (INCUMBENT,)
    assert not view(after, INCUMBENT).rollback_eligible  # the voided SUPERSEDE never took effect
    assert not view(after, CHILD).demoted_for_cause  # a precheck cancel is no demerit


def test_swap_cancel_of_a_lapsed_pair_after_launch_leaves_it_lapsed() -> None:
    chain, head, _tail = seeded_pair()
    cancel(chain, head, ts=at(DAY, "16:55"))

    result = run(chain, LATE)

    assert result.pairs[0].status is PairStatus.LAPSED
    assert result.pairs[0].voided_by_transition_id is None


def test_swap_cancel_before_launch_voids_an_unactivated_pair() -> None:
    chain, head, _tail = seeded_pair()
    cancel(chain, head, ts=at(DAY, "16:30"))

    assert run(chain, LATE).pairs[0].status is PairStatus.VOIDED


def test_a_voided_pending_root_stays_shadow() -> None:
    chain = Chain()
    root = chain.add(
        Kind.ROOT_ADMIT, State.CHAMPION, family=OTHER, effective_launch_date=DAY,
        lineage_root_family_id=OTHER,
    )  # fmt: skip
    chain.add(
        Kind.SWAP_CANCEL, State.CHALLENGER, family=OTHER, frm=State.CHALLENGER,
        ts=at(DAY, "16:30"), cause_code=CauseCode.ENGINE_INCONSISTENCY,
        voids_transition_ids=(root.transition_id,),
    )  # fmt: skip

    result = run(chain, LATE)

    assert result.states == {OTHER: State.SHADOW}
    assert result.pairs[0].status is PairStatus.VOIDED


# --- pending-swap rules (Y8) ----------------------------------------------------------------


def test_demote_during_pending_swap_incoming() -> None:
    chain, head, _tail = activated_pair()
    cancel(chain, head, ts=at(DAY, "16:46"), cause=CauseCode.PAIR_CAUSE_INCOMING)

    result = run(chain, LATE)

    assert result.pairs[0].status is PairStatus.VOIDED
    assert result.states == {INCUMBENT: State.CHAMPION, CHILD: State.CHALLENGER}
    assert view(result, CHILD).demoted_for_cause
    assert not view(result, INCUMBENT).demoted_for_cause
    assert not view(result, INCUMBENT).rollback_eligible


def test_demote_during_pending_swap_outgoing() -> None:
    chain, head, _tail = activated_pair()
    chain.add(
        Kind.DEMOTE, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, ts=at(DAY, "16:46"),
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    cancel(chain, head, ts=at(DAY, "16:46", SEC), cause=CauseCode.PAIR_CAUSE_OUTGOING)

    result = run(chain, LATE)

    assert result.pairs[0].status is PairStatus.VOIDED
    assert result.states == {INCUMBENT: State.HALTED, CHILD: State.CHALLENGER}
    assert view(result, INCUMBENT).demoted_for_cause
    assert not view(result, INCUMBENT).rollback_eligible
    assert not view(result, CHILD).demoted_for_cause
    assert result.senders == (INCUMBENT,)

    # the incoming is re-proposed through DISPLACED, and the halted incumbent is not superseded
    again, _partner = chain.promote_pair(day=NEXT_DAY, partner=Kind.DISPLACED)
    chain.activate(again, ts=at(NEXT_DAY, "16:45"))
    later = run(chain, NEXT_LATE)
    assert later.states == {INCUMBENT: State.CHALLENGER, CHILD: State.CHAMPION}
    assert not view(later, INCUMBENT).rollback_eligible
    assert view(later, INCUMBENT).demoted_for_cause


def test_unactivated_pair_lapses_at_launch() -> None:
    """New beyond 6b: a lapsed DISPLACED pair leaves the incumbent HALTED, with no effect at all."""
    chain, head, tail = seeded_pair(partner=Kind.DISPLACED)

    before = run(chain, LAUNCH - ONE_NS)
    after = run(chain, LATE)

    assert before.states == after.states == {INCUMBENT: State.HALTED, CHILD: State.CHALLENGER}
    assert [p.status for p in (before.pairs[0], after.pairs[0])] == [
        PairStatus.PENDING, PairStatus.LAPSED,
    ]  # fmt: skip
    assert after.pairs[0].member_transition_ids == (head.transition_id, tail.transition_id)
    assert after.senders == (INCUMBENT,)
    for family in (INCUMBENT, CHILD):
        flags = view(after, family)
        assert not (flags.rollback_eligible or flags.target_ineligible or flags.drill_child)
    assert view(after, INCUMBENT).demoted_for_cause  # only its own HALT, nothing from the pair
    assert not view(after, CHILD).demoted_for_cause
    assert after.drill_episodes == ()


def test_a_lapsed_supersede_pair_charges_no_eligibility_and_a_later_pair_still_works() -> None:
    chain, _head, _tail = seeded_pair()
    later, _partner = chain.promote_pair(day=NEXT_DAY)
    chain.activate(later, ts=at(NEXT_DAY, "16:45"))

    mid = run(chain, LATE)
    end = run(chain, NEXT_LATE)

    assert not view(mid, INCUMBENT).rollback_eligible
    assert mid.states[INCUMBENT] is State.CHAMPION
    assert [p.status for p in end.pairs] == [PairStatus.LAPSED, PairStatus.EFFECTIVE]
    assert end.states == {INCUMBENT: State.CHALLENGER, CHILD: State.CHAMPION}
    assert view(end, INCUMBENT).rollback_eligible


def test_a_lapsed_or_voided_drill_promote_starts_no_episode() -> None:
    chain = drill_chain()
    lapsed_head, _ = chain.drill_pair(DAY)
    voided_head, _ = chain.drill_pair(NEXT_DAY)
    chain.activate(voided_head, ts=at(NEXT_DAY, "16:45"))
    cancel(chain, voided_head, ts=at(NEXT_DAY, "16:50", SEC))

    result = run(chain, NEXT_LATE)

    assert [p.status for p in result.pairs] == [PairStatus.LAPSED, PairStatus.VOIDED]
    assert result.drill_episodes == ()
    assert not view(result, CHILD).drill_child
    assert not view(result, INCUMBENT).rollback_eligible
    assert lapsed_head.transition_id != voided_head.transition_id


# --- restrictive rows apply at their own timestamp ------------------------------------------


def test_restrictive_flags_wait_for_the_clock() -> None:
    chain, head, _tail = activated_pair()
    cancel(chain, head, ts=at(DAY, "16:46"), cause=CauseCode.PAIR_CAUSE_INCOMING)

    early = run(chain, at(DAY, "16:45", 30 * SEC))

    assert not view(early, CHILD).demoted_for_cause


# --- terminal lineage freeze (Y10) -----------------------------------------------------------


def lineage_chain() -> Chain:
    """INCUMBENT (root) CHAMPION with a MINT child in its lineage and an unrelated root."""
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, lineage_root_family_id=INCUMBENT)
    chain.add(Kind.MINT, State.SHADOW, family=CHILD, lineage_root_family_id=INCUMBENT)
    chain.add(Kind.BOOTSTRAP, State.RETIRED, family=OTHER, lineage_root_family_id=OTHER)
    return chain


def test_terminal_halt_freezes_lineage() -> None:
    chain = lineage_chain()
    chain.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        halt_cause_class=CauseClass.TERMINAL, cause_code=CauseCode.EXEC_STORE_HALT_MIRROR,
    )  # fmt: skip

    halted = run(chain, LATE)
    chain.add(Kind.RETIRE, State.RETIRED, family=INCUMBENT, frm=State.HALTED)
    retired = run(chain, LATE)

    for result in (halted, retired):
        assert view(result, INCUMBENT).terminal_frozen
        assert view(result, CHILD).terminal_frozen  # every family of the lineage
        assert not view(result, OTHER).terminal_frozen  # another lineage is untouched
        assert not result.integrity_frozen  # a lineage freeze is not the venue freeze
    assert retired.states[INCUMBENT] is State.RETIRED


def test_a_terminal_halt_of_a_child_freezes_the_root_it_descends_from() -> None:
    chain = lineage_chain()
    chain.add(
        Kind.HALT, State.HALTED, family=CHILD, frm=State.CHAMPION,
        halt_cause_class=CauseClass.TERMINAL, cause_code=CauseCode.EXEC_STORE_HALT_MIRROR,
    )  # fmt: skip

    result = run(chain, LATE)

    assert view(result, INCUMBENT).terminal_frozen
    assert view(result, CHILD).terminal_frozen
    assert view(result, INCUMBENT).lineage_root_family_id == INCUMBENT
    assert view(result, CHILD).lineage_root_family_id == INCUMBENT
    assert not view(result, OTHER).terminal_frozen


def test_exhausted_model_resume_budget_retire_freezes_the_lineage() -> None:
    chain = lineage_chain()
    chain.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    assert not view(run(chain, LATE), CHILD).terminal_frozen
    chain.add(
        Kind.RETIRE, State.RETIRED, family=INCUMBENT, frm=State.HALTED,
        cause_code=CauseCode.MODEL_BUDGET_EXHAUSTED,
    )  # fmt: skip

    assert view(run(chain, LATE), CHILD).terminal_frozen


def test_a_policy_retire_of_a_challenger_does_not_freeze() -> None:
    chain = lineage_chain()
    chain.add(Kind.RETIRE, State.RETIRED, family=CHILD, frm=State.SHADOW)

    result = run(chain, LATE)

    assert result.states[CHILD] is State.RETIRED
    assert not view(result, INCUMBENT).terminal_frozen


def test_a_family_without_lineage_column_is_its_own_lineage() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
    chain.add(Kind.BOOTSTRAP, State.RETIRED, family=OTHER)
    chain.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        halt_cause_class=CauseClass.TERMINAL,
    )  # fmt: skip

    result = run(chain, LATE)

    assert view(result, INCUMBENT).lineage_root_family_id == INCUMBENT
    assert view(result, INCUMBENT).terminal_frozen
    assert not view(result, OTHER).terminal_frozen


# --- venue INTEGRITY freeze and the non-freezing classes ------------------------------------


def halted_champion(chain: Chain, **extra: Any) -> TransitionRow:
    return chain.add(Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, **extra)


def test_infra_cause_never_retires() -> None:
    chain = lineage_chain()
    chain.add(
        Kind.DEMOTE, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        halt_cause_class=CauseClass.RECOVERABLE_INFRA, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    infra = run(chain, LATE)
    assert infra.states[INCUMBENT] is State.HALTED
    assert not infra.integrity_frozen

    chain.add(Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED)
    halted_champion(
        chain, halt_cause_class=CauseClass.RECOVERABLE_INFRA,
        cause_code=CauseCode.INFRA_BUDGET_EXHAUSTED,
    )  # fmt: skip
    exhausted = run(chain, LATE)

    assert exhausted.states[INCUMBENT] is State.HALTED  # never RETIRED
    assert exhausted.integrity_frozen
    assert not any(v.terminal_frozen for v in exhausted.families.values())  # never lineage-frozen


def test_integrity_class_halt_freezes_the_venue_and_nothing_else() -> None:
    chain = lineage_chain()
    halted_champion(chain, halt_cause_class=CauseClass.INTEGRITY, cause_code=CauseCode.VERDICT_FAIL)

    result = run(chain, LATE)

    assert result.integrity_frozen
    assert result.states[INCUMBENT] is State.HALTED
    assert not any(v.terminal_frozen for v in result.families.values())


def test_integrity_freeze_survives_a_resume() -> None:
    chain = lineage_chain()
    halted_champion(chain, halt_cause_class=CauseClass.INTEGRITY, cause_code=CauseCode.VERDICT_FAIL)
    chain.add(Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED)

    result = run(chain, LATE)

    assert result.states[INCUMBENT] is State.CHAMPION
    assert result.integrity_frozen  # no autonomous clear (W15)


def rollback_failed_halt(chain: Chain, trigger: CauseClass | None) -> None:
    halted_champion(
        chain, halt_cause_class=CauseClass.ROLLBACK_FAILED, trigger_cause_class=trigger,
        cause_code=CauseCode.ROLLBACK_FAILED,
    )  # fmt: skip


def test_rollback_failed_never_freezes_venue() -> None:
    chain = lineage_chain()
    rollback_failed_halt(chain, CauseClass.RECOVERABLE_MODEL)

    result = run(chain, LATE)

    assert result.states[INCUMBENT] is State.HALTED
    assert not result.integrity_frozen
    assert not any(v.terminal_frozen for v in result.families.values())
    assert view(result, INCUMBENT).demoted_for_cause  # it halts its own family only


@pytest.mark.parametrize("trigger", [None, *CauseClass], ids=str)
def test_rollback_failed_freezes_nothing_whatever_its_trigger_class(
    trigger: CauseClass | None,
) -> None:
    chain = lineage_chain()
    rollback_failed_halt(chain, trigger)

    result = run(chain, LATE)

    assert not result.integrity_frozen
    assert not any(v.terminal_frozen for v in result.families.values())


@pytest.mark.parametrize(
    "cls", [CauseClass.RECOVERABLE_MODEL, CauseClass.RECOVERABLE_INFRA, CauseClass.DRILL]
)
def test_recoverable_and_drill_halts_freeze_nothing(cls: CauseClass) -> None:
    chain = lineage_chain()
    halted_champion(chain, halt_cause_class=cls, cause_code=CauseCode.VERDICT_FAIL)

    result = run(chain, LATE)

    assert not result.integrity_frozen
    assert not any(v.terminal_frozen for v in result.families.values())


# --- per-family flags ------------------------------------------------------------------------


def test_target_ineligible_marks_the_family_and_changes_no_state() -> None:
    chain, _head, _tail = seeded_pair()
    chain.add(
        Kind.TARGET_INELIGIBLE, State.CHALLENGER, family=CHILD, frm=State.CHALLENGER,
        cause_code=CauseCode.TARGET_INTEGRITY,
    )  # fmt: skip

    result = run(chain, LATE)

    assert view(result, CHILD).target_ineligible
    assert result.states[CHILD] is State.CHALLENGER
    assert not view(result, INCUMBENT).target_ineligible


def test_supersede_makes_the_outgoing_rollback_eligible_only_once_it_takes_effect() -> None:
    chain, _head, _tail = activated_pair()

    pending = run(chain, at(DAY, "16:49"))
    effective = run(chain, LATE)

    assert not view(pending, INCUMBENT).rollback_eligible
    assert view(effective, INCUMBENT).rollback_eligible
    assert not view(effective, CHILD).rollback_eligible


def test_a_family_that_becomes_champion_again_is_no_longer_a_target() -> None:
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

    result = run(chain, NEXT_LATE)

    assert result.states == {INCUMBENT: State.CHAMPION, CHILD: State.CHALLENGER}
    assert not view(result, INCUMBENT).rollback_eligible
    assert view(result, CHILD).rollback_eligible


def test_demoting_the_new_champion_leaves_the_rollback_target_eligible() -> None:
    chain, _head, _tail = activated_pair()
    chain.add(
        Kind.DEMOTE, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=at(DAY, "19:00"),
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip

    result = run(chain, at(DAY, "20:00"))

    assert view(result, CHILD).demoted_for_cause
    assert not view(result, CHILD).rollback_eligible
    assert view(result, INCUMBENT).rollback_eligible
    assert result.senders == (CHILD,)


def test_demoted_for_cause_is_sticky_across_a_resume() -> None:
    chain = lineage_chain()
    halted_champion(
        chain, halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL
    )
    chain.add(Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED)

    result = run(chain, LATE)

    assert result.states[INCUMBENT] is State.CHAMPION
    assert view(result, INCUMBENT).demoted_for_cause


def test_senders_are_the_champion_and_halted_families_in_name_order() -> None:
    chain = lineage_chain()
    assert run(chain, LATE).senders == (INCUMBENT,)
    halted_champion(chain, halt_cause_class=CauseClass.RECOVERABLE_INFRA)
    assert run(chain, LATE).senders == (INCUMBENT,)  # HALTED still holds the venue
    chain.add(Kind.RETIRE, State.RETIRED, family=INCUMBENT, frm=State.HALTED)
    assert run(chain, LATE).senders == ()


# --- drill episodes -------------------------------------------------------------------------


class DrillChain(Chain):
    def drill_pair(
        self, day: str, *, outgoing: str = INCUMBENT
    ) -> tuple[TransitionRow, TransitionRow]:
        head = self.add(
            Kind.DRILL_PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
            effective_launch_date=day, drill=True,
        )  # fmt: skip
        tail = self.add(
            Kind.SUPERSEDE, State.CHALLENGER, family=outgoing, frm=State.CHAMPION,
            paired_transition_id=head.transition_id, effective_launch_date=day,
        )  # fmt: skip
        return head, tail

    def close_pair(self, day: str, *, partner: Kind = Kind.SUPERSEDE) -> TransitionRow:
        head = self.add(
            Kind.ROLLBACK, State.CHAMPION, family=INCUMBENT, frm=State.CHALLENGER,
            effective_launch_date=day,
        )  # fmt: skip
        self.add(
            partner, State.CHALLENGER, family=CHILD,
            frm=State.CHAMPION if partner is Kind.SUPERSEDE else State.HALTED,
            paired_transition_id=head.transition_id, effective_launch_date=day,
        )  # fmt: skip
        return head


def drill_chain() -> DrillChain:
    chain = DrillChain()
    chain.seed()
    return chain


def full_episode() -> tuple[DrillChain, TransitionRow, TransitionRow]:
    chain = drill_chain()
    head, _tail = chain.drill_pair(DAY)
    chain.activate(head, ts=at(DAY, "16:45"))
    chain.add(
        Kind.DEMOTE, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=at(DAY, "20:00"),
        halt_cause_class=CauseClass.DRILL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    chain.add(Kind.RESUME, State.CHAMPION, family=CHILD, frm=State.HALTED, ts=at(NEXT_DAY, "16:45"))
    closing = chain.close_pair(NEXT_DAY)
    chain.activate(closing, ts=at(NEXT_DAY, "16:46"), family=INCUMBENT)
    return chain, head, closing


def test_drill_flag_spans_promote_to_rollback() -> None:
    chain, head, closing = full_episode()

    result = run(chain, NEXT_LATE)

    (episode,) = result.drill_episodes
    assert episode == DrillEpisode(
        family_id=CHILD, start_ns=LAUNCH, end_ns=NEXT_LAUNCH,
        drill_promote_transition_id=head.transition_id,
    )  # fmt: skip
    assert closing.family_id == INCUMBENT
    assert not episode.contains(LAUNCH - ONE_NS)
    assert episode.contains(LAUNCH)
    assert episode.contains(at(DAY, "20:00", ONE_NS))  # after the DEMOTE
    assert episode.contains(at(NEXT_DAY, "16:45", ONE_NS))  # after the RESUME
    assert episode.contains(NEXT_LAUNCH - ONE_NS)
    assert not episode.contains(NEXT_LAUNCH)  # half open
    assert result.states == {INCUMBENT: State.CHAMPION, CHILD: State.CHALLENGER}
    assert view(result, CHILD).drill_child


def test_a_drill_episode_is_open_ended_until_the_closing_rollback_takes_effect() -> None:
    chain, _head, _closing = full_episode()

    result = run(chain, at(NEXT_DAY, "16:49"))

    (episode,) = result.drill_episodes
    assert episode.end_ns is None
    assert episode.contains(at(NEXT_DAY, "16:49"))
    assert episode.contains(at(NEXT_DAY, "16:49") + 365 * 86_400 * SEC)


def test_a_drill_episode_is_not_started_before_its_pair_takes_effect() -> None:
    chain, _head, _closing = full_episode()

    assert run(chain, LAUNCH - ONE_NS).drill_episodes == ()


def test_a_displaced_close_ends_the_episode() -> None:
    chain = drill_chain()
    head, _tail = chain.drill_pair(DAY)
    chain.activate(head, ts=at(DAY, "16:45"))
    chain.add(
        Kind.HALT, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=at(DAY, "20:00"),
        halt_cause_class=CauseClass.DRILL,
    )  # fmt: skip
    closing = chain.close_pair(NEXT_DAY, partner=Kind.DISPLACED)
    chain.activate(closing, ts=at(NEXT_DAY, "16:46"), family=INCUMBENT)

    (episode,) = run(chain, NEXT_LATE).drill_episodes

    assert episode.end_ns == NEXT_LAUNCH


def test_a_retired_drill_child_ends_the_episode_at_the_retire() -> None:
    chain = drill_chain()
    head, _tail = chain.drill_pair(DAY)
    chain.activate(head, ts=at(DAY, "16:45"))
    chain.add(
        Kind.HALT, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=at(DAY, "20:00"),
        halt_cause_class=CauseClass.DRILL,
    )  # fmt: skip
    retire_ts = at(NEXT_DAY, "15:30")
    chain.add(Kind.RETIRE, State.RETIRED, family=CHILD, frm=State.HALTED, ts=retire_ts)

    (episode,) = run(chain, NEXT_LATE).drill_episodes

    assert episode.end_ns == retire_ts


def test_drill_supersede_makes_the_incumbent_eligible_but_never_the_drill_child() -> None:
    chain, _head, _closing = full_episode()

    during = run(chain, at(DAY, "18:00"))
    after = run(chain, NEXT_LATE)

    assert view(during, INCUMBENT).rollback_eligible  # the closing ROLLBACK is admissible
    assert not view(during, CHILD).rollback_eligible
    assert not view(after, CHILD).rollback_eligible  # superseded by the close: still no target
    assert view(after, CHILD).demoted_for_cause


def test_a_normal_promotion_does_not_flag_a_drill_child() -> None:
    chain, _head, _tail = activated_pair()

    result = run(chain, LATE)

    assert result.drill_episodes == ()
    assert not any(v.drill_child for v in result.families.values())


# --- shape, purity ---------------------------------------------------------------------------


def test_results_are_immutable_and_inputs_untouched() -> None:
    chain, head, _tail = activated_pair()
    cancel(chain, head, ts=at(DAY, "16:55"), cause=CauseCode.PAIR_CAUSE_INCOMING)
    snapshot = list(chain.rows)

    result = run(chain, LATE)

    assert chain.rows == snapshot
    assert result == run(chain, LATE)
    with pytest.raises(TypeError):
        result.families[INCUMBENT] = view(result, INCUMBENT)  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        view(result, INCUMBENT).rollback_eligible = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        DrillEpisode(
            family_id=CHILD, start_ns=0, end_ns=None, drill_promote_transition_id="a" * 64
        ).start_ns = 1  # type: ignore[misc]


def test_families_and_states_name_the_same_families() -> None:
    chain, _head, _tail = activated_pair()
    result = run(chain, LATE)

    assert set(result.families) == set(result.states)
    for name, family_view in result.families.items():
        assert family_view.family_id == name
        assert family_view.state is result.states[name]


def test_an_empty_chain_has_nothing_frozen() -> None:
    result = fold([], VENUE, 0)

    assert isinstance(result, FoldResult)
    assert result.families == {}
    assert result.senders == ()
    assert result.drill_episodes == ()
    assert result.integrity_frozen is False


_Builder = Callable[[], tuple[Chain, TransitionRow, TransitionRow]]


@pytest.mark.parametrize("builder", [activated_pair, seeded_pair], ids=["activated", "lapsing"])
def test_fold_is_a_pure_function_of_rows_and_clock(builder: _Builder) -> None:
    chain, _head, _tail = builder()

    assert fold(chain.rows, VENUE, LATE) == fold(tuple(chain.rows), VENUE, LATE)
