"""ARCH-0 seam 7d: ``transitions.validate`` II (Z3, introducers, mint, ROLLBACK, ATTEST, ...).

Each test builds a prior chain, folds it, and asks ``first_refusal`` (the rule-level form of
``validate``) about candidate rows; a control with the rule satisfied sits beside every refusal so
that a rule cannot pass by refusing everything. The rules live in ``validate_ii``; the walk is
``validate``'s. ``probe`` adds the partner that moves the current sender out at the same LAUNCH
(a pair is one transaction).
"""

from __future__ import annotations

from typing import Any, Final

import pytest

import breezy.persistence.autonomy.transitions as tm
from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.fold import FoldResult
from breezy.persistence.autonomy.fold_tallies import parse_carried
from breezy.persistence.autonomy.schemas import (
    CauseClass,
    CauseCode,
    DecidedBy,
    Kind,
    RefusalReason,
    State,
    TransitionRow,
    WriterMode,
)
from breezy.persistence.autonomy.stage_policy import STAGE
from tests.unit.test_registry_fold import (
    CHILD,
    DAY,
    INCUMBENT,
    LAUNCH,
    OTHER,
    PRIOR_DAY,
    SEC,
    Chain,
    at,
    run,
)
from tests.unit.test_registry_fold_effects import NEXT_DAY, activated_pair, cancel
from tests.unit.test_registry_fold_tallies import carried
from tests.unit.test_registry_fold_validate import (
    CHILD_MAN,
    DAY_NS,
    HOUR_NS,
    INC_ART,
    INC_MAN,
    RESTORE_TS,
    RESUME_TS,
    champion_chain,
    exhaust,
    facts_for_child,
    halt_incumbent,
    model_halted,
    no_facts,
    open_episode_chain,
    probe,
    restore,
    resume,
    rule_of,
)
from tests.unit.test_registry_fold_validate import (
    failed_close_chain as _failed_close_chain,
)

THIRD_DAY: Final = "2026-10-12"
SIXTH_DAY: Final = "2026-10-15"
NOW: Final = at(DAY, "16:00")
SECOND_ART: Final = "5" * 64
K_MAX: Final = pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME
SEED_RETIRED: Final = "pm_us_crh_v4"


def reason_of(refusal: Any) -> RefusalReason | None:
    return None if refusal is None else refusal.reason


def venue_only(chain: Chain) -> Chain:
    """A chain whose only family is RETIRED: the venue has no sender."""
    chain.add(Kind.BOOTSTRAP, State.RETIRED, family=INCUMBENT)
    return chain


def promoted_chain() -> Chain:
    """INCUMBENT superseded by CHILD at DAY's LAUNCH: INCUMBENT is rollback-eligible."""
    chain = champion_chain()
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)
    head, _tail = chain.promote_pair(day=DAY)
    chain.activate(head, ts=at(DAY, "16:45"))
    return chain


def ask_rollback(
    chain: Chain, *, day: str = THIRD_DAY, now: int | None = None, **extra: Any
) -> Any:
    return probe(
        chain, at(DAY, "18:00") if now is None else now, Kind.ROLLBACK, State.CHAMPION,
        family=INCUMBENT, frm=State.CHALLENGER, effective_launch_date=day, **extra,
    )  # fmt: skip


# --- introducers (Y6) -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "frm", "to"),
    [
        (Kind.DEMOTE, State.CHAMPION, State.HALTED),
        (Kind.RESUME, State.HALTED, State.CHAMPION),
        (Kind.PROMOTE, State.SHADOW, State.CHALLENGER),
        (Kind.RETIRE, State.SHADOW, State.RETIRED),
        (Kind.ATTEST, State.CHAMPION, State.CHAMPION),
        (Kind.MINT, State.SHADOW, State.SHADOW),  # an introducer with a from_state is no introducer
    ],
)
def test_validate_refuses_family_not_introduced(kind: Kind, frm: State, to: State) -> None:
    refused = probe(champion_chain(), NOW, kind, to, family=OTHER, frm=frm)
    assert refused is not None
    assert (refused.rule.value, refused.reason) == (
        "family_not_introduced", RefusalReason.FAMILY_NOT_INTRODUCED,
    )  # fmt: skip

    # a non-introducing kind from ∅ is just as unknown
    assert rule_of(probe(champion_chain(), NOW, Kind.PROMOTE, State.CHALLENGER, family=OTHER)) == (
        "family_not_introduced"
    )


def test_an_introducer_from_nothing_is_not_refused_and_the_batch_knows_what_it_introduced() -> None:
    chain = champion_chain()
    prior = run(chain, NOW)
    mint = chain.add(Kind.MINT, State.SHADOW, family=OTHER, lineage_root_family_id=INCUMBENT)
    nominate = chain.add(Kind.RETIRE, State.RETIRED, family=OTHER, frm=State.SHADOW)
    assert tm.first_refusal(prior, [mint], manifests=no_facts) is None
    # the second row names a family only the first row introduced: still introduced
    assert tm.first_refusal(prior, [mint, nominate], manifests=no_facts) is None
    # without the introducing row the same retire is refused
    refused = tm.first_refusal(prior, [nominate], manifests=no_facts)
    assert refused is not None and refused.rule.value == "family_not_introduced"


@pytest.mark.parametrize("kind", [Kind.BOOTSTRAP, Kind.ROOT_ADMIT])
def test_a_root_kind_names_its_own_family_as_its_lineage_root(kind: Kind) -> None:
    extra: dict[str, Any] = {"effective_launch_date": DAY} if kind is Kind.ROOT_ADMIT else {}
    chain = Chain()
    refused = probe(
        chain, NOW, kind, State.CHAMPION, family=INCUMBENT, lineage_root_family_id=OTHER, **extra
    )
    assert refused is not None
    assert (refused.rule.value, refused.reason) == (
        "root_lineage_mismatch", RefusalReason.ROOT_LINEAGE_MISMATCH,
    )  # fmt: skip


def test_a_known_child_cannot_be_admitted_as_a_root_of_its_own_lineage() -> None:
    chain = venue_only(Chain())  # no sender; CHILD is a MINT child of INCUMBENT's lineage
    chain.add(Kind.MINT, State.SHADOW, family=CHILD)
    refused = probe(
        chain, NOW, Kind.ROOT_ADMIT, State.CHAMPION, family=CHILD, frm=State.SHADOW,
        lineage_root_family_id=CHILD, effective_launch_date=DAY,
    )  # fmt: skip
    assert refused is not None and refused.rule.value == "root_lineage_mismatch"


# --- BOOTSTRAP (E-6) ------------------------------------------------------------------------------


def test_bootstrap_refused_on_a_non_empty_chain() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
    refused = probe(chain, NOW, Kind.BOOTSTRAP, State.RETIRED, family=SEED_RETIRED)
    assert refused is not None and refused.rule.value == "bootstrap_not_genesis"
    assert probe(Chain(), NOW, Kind.BOOTSTRAP, State.RETIRED, family=SEED_RETIRED) is None


@pytest.mark.parametrize(
    ("family", "to", "ok"),
    [
        (INCUMBENT, State.CHAMPION, True),
        (SEED_RETIRED, State.RETIRED, True),
        (OTHER if OTHER != SEED_RETIRED else "pm_us_crh_cont", State.RETIRED, True),
        ("pm_us_crh_v9", State.RETIRED, False),  # not in the seed
        (INCUMBENT, State.RETIRED, False),  # a seed family in another state
        (SEED_RETIRED, State.CHAMPION, False),
        (INCUMBENT, State.SHADOW, False),  # no BOOTSTRAP root: ROOT_ADMIT introduces roots
    ],
)
def test_bootstrap_only_seed_families_in_their_seed_state(family: str, to: State, ok: bool) -> None:
    refused = probe(Chain(), NOW, Kind.BOOTSTRAP, to, family=family)
    assert (refused is None) is ok
    if not ok:
        assert refused is not None and refused.rule.value == "bootstrap_not_seed"


# --- ROOT_ADMIT (V6) and the terminal freeze (Y10) -----------------------------------------------


def root_admit(chain: Chain, **extra: Any) -> Any:
    return probe(
        chain, NOW, Kind.ROOT_ADMIT, State.CHAMPION, family=OTHER, frm=None,
        effective_launch_date=DAY, manifest_sha256=INC_MAN, **extra,
    )  # fmt: skip


@pytest.mark.parametrize("facet", ["validate"])
def test_root_admit_only_when_venue_has_no_sender(facet: str) -> None:
    assert facet == "validate"
    assert root_admit(venue_only(Chain())) is None  # nothing sends: the recovery is admitted

    champion = root_admit(champion_chain())
    assert champion is not None and champion.rule.value == "root_admit_venue_has_sender"

    halted = champion_chain()
    halt_incumbent(halted, CauseClass.RECOVERABLE_MODEL)  # HALTED is a sender too
    refused = root_admit(halted)
    assert refused is not None and refused.rule.value == "root_admit_venue_has_sender"

    retired = Chain()
    retired.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
    retired.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    retired.add(Kind.RETIRE, State.RETIRED, family=INCUMBENT, frm=State.HALTED)
    assert root_admit(retired) is None  # a retired family is no sender


def test_root_admit_refused_into_a_terminal_frozen_lineage() -> None:
    frozen = venue_only(Chain())
    exhaust(frozen, {OTHER: {"terminal_frozen": True}})
    refused = root_admit(frozen)
    assert refused is not None and refused.rule.value == "lineage_terminal_frozen"
    assert root_admit(venue_only(Chain())) is None  # control: the same row, no freeze


def frozen_lineage(chain: Chain) -> Chain:
    exhaust(chain, {INCUMBENT: {"terminal_frozen": True}})
    return chain


def nominated(chain: Chain) -> Chain:
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)
    return chain


def ask_promote(chain: Chain, kind: Kind = Kind.PROMOTE) -> Any:
    extra: dict[str, Any] = {"drill": True} if kind is Kind.DRILL_PROMOTE else {}
    return probe(
        chain, NOW, kind, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=DAY, manifest_sha256=CHILD_MAN, manifests=facts_for_child,
        artefact_sha256=INC_ART, **extra,
    )  # fmt: skip


def test_terminal_frozen_lineage_refuses_promote() -> None:
    assert ask_promote(nominated(champion_chain())) is None  # control
    refused = ask_promote(frozen_lineage(nominated(champion_chain())))
    assert refused is not None
    assert (refused.rule.value, refused.row_index) == ("lineage_terminal_frozen", 0)


def test_terminal_frozen_lineage_refuses_drill_promote() -> None:
    def chain() -> Chain:
        base = champion_chain()
        base.add(Kind.DRILL_ADMIT, State.CHALLENGER, family=CHILD, frm=State.SHADOW,
                 artefact_sha256=INC_ART)  # fmt: skip
        return base

    assert ask_promote(chain(), Kind.DRILL_PROMOTE) is None  # control
    refused = ask_promote(frozen_lineage(chain()), Kind.DRILL_PROMOTE)
    assert refused is not None and refused.rule.value == "lineage_terminal_frozen"


def test_terminal_frozen_lineage_refuses_rollback() -> None:
    assert ask_rollback(promoted_chain()) is None  # control
    refused = ask_rollback(frozen_lineage(promoted_chain()))
    assert refused is not None and refused.rule.value == "lineage_terminal_frozen"


def test_a_terminal_halt_freezes_what_promote_then_refuses() -> None:
    chain = nominated(champion_chain())
    halt_incumbent(chain, CauseClass.TERMINAL)  # the fold freezes the lineage (Y10)
    refused = ask_promote(chain)
    assert refused is not None and refused.rule.value == "lineage_terminal_frozen"


# --- MINT (Z3): one a day, unlimited by K_LIFETIME, a drill MINT not counted ---------------------


def mint(
    chain: Chain, ts: int, *, family: str = OTHER, art: str | None = SECOND_ART, **x: Any
) -> Any:
    return probe(
        chain, ts, Kind.MINT, State.SHADOW, family=family, ts=ts,
        lineage_root_family_id=INCUMBENT, artefact_sha256=art, **x,
    )  # fmt: skip


FIRST_ART: Final = "4" * 64


def minted_once(at_ns: int) -> Chain:
    """One counted MINT (its own new artefact) of INCUMBENT's lineage at ``at_ns``."""
    chain = champion_chain()
    chain.add(Kind.MINT, State.SHADOW, family=OTHER, ts=at_ns, artefact_sha256=FIRST_ART)
    return chain


def test_mint_unlimited_by_k_max_but_one_per_day() -> None:
    spent = champion_chain()
    exhaust(spent, {INCUMBENT: {"nominations": K_MAX, "infeasible_nominations": K_MAX}})
    prior = run(spent, NOW)
    assert prior.lineages[INCUMBENT].tallies.nominations == K_MAX
    assert mint(spent, NOW) is None  # K_LIFETIME limits nominations, never MINTs

    first = NOW
    third = "pm_us_crh_fq_v1_r0003"
    assert mint(minted_once(first), first + HOUR_NS, family=third) is not None
    refused = mint(minted_once(first), first + HOUR_NS, family=third)
    assert refused is not None
    assert (refused.rule.value, refused.row_index) == ("mint_rate", 0)
    # exactly a day later the first MINT has left the window; one ns earlier it has not
    assert mint(minted_once(first), first + DAY_NS - 1, family=third) is not None
    assert mint(minted_once(first), first + DAY_NS, family=third) is None


def test_mint_rate_counts_the_earlier_rows_of_the_batch_and_only_its_own_lineage() -> None:
    chain = champion_chain()
    prior = run(chain, NOW)
    rows = [
        chain.add(Kind.MINT, State.SHADOW, family=name, ts=NOW, artefact_sha256=art)
        for name, art in (("pm_us_crh_a", "6" * 64), ("pm_us_crh_b", "7" * 64))
    ]
    assert tm.first_refusal(prior, rows[:1], manifests=no_facts) is None
    refused = tm.first_refusal(prior, rows, manifests=no_facts)
    assert refused is not None and (refused.rule.value, refused.row_index) == ("mint_rate", 1)

    other_lineage = chain.add(
        Kind.MINT, State.SHADOW, family="pm_us_crh_c", ts=NOW, artefact_sha256="8" * 64,
        lineage_root_family_id=OTHER,
    )  # fmt: skip
    assert tm.first_refusal(prior, [rows[0], other_lineage], manifests=no_facts) is None


def test_drill_mint_not_counted() -> None:
    """A no-new-lineage MINT (an artefact its lineage already holds) is never counted (Y2, Z3)."""
    after_drill = champion_chain()  # CHILD is a MINT bound to INCUMBENT's artefact
    assert run(after_drill, NOW).lineages[INCUMBENT].tallies.mints == ()  # the fold charges nothing
    assert mint(after_drill, NOW + SEC) is None  # so a real MINT the same day is admitted

    counted = minted_once(NOW)
    prior = run(counted, NOW + HOUR_NS)
    assert len(prior.lineages[INCUMBENT].tallies.mints) == 1
    drill = counted.add(
        Kind.MINT, State.SHADOW, family="pm_us_crh_d", ts=NOW + HOUR_NS, artefact_sha256=INC_ART
    )
    assert tm.first_refusal(prior, [drill], manifests=no_facts) is None  # not refused either

    # inside one batch: a counted MINT then a drill MINT passes, a second counted one does not
    fresh = champion_chain()
    base = run(fresh, NOW)
    first = fresh.add(
        Kind.MINT, State.SHADOW, family="pm_us_crh_e", ts=NOW, artefact_sha256="9" * 64
    )
    again = fresh.add(
        Kind.MINT, State.SHADOW, family="pm_us_crh_f", ts=NOW, artefact_sha256=INC_ART
    )
    assert tm.first_refusal(base, [first, again], manifests=no_facts) is None


# --- sender changes (Z3) -------------------------------------------------------------------------


def ask_resume(chain: Chain) -> Any:
    return resume(chain)


def test_sender_change_daily_cap_counts_a_rolling_day() -> None:
    cap = pins.MAX_SENDER_CHANGES_PER_VENUE_PER_DAY
    inside = tuple(RESUME_TS - (i + 1) * HOUR_NS for i in range(cap))

    chain = model_halted()
    exhaust(chain, sender_changes=inside)
    refused = ask_resume(chain)
    assert refused is not None
    assert (refused.rule.value, refused.row_index) == ("sender_change_daily_cap", 0)

    under = model_halted()
    exhaust(under, sender_changes=inside[:-1])
    assert ask_resume(under) is None

    stale = model_halted()
    exhaust(stale, sender_changes=(RESUME_TS - DAY_NS, RESUME_TS - DAY_NS - HOUR_NS))
    assert ask_resume(stale) is None  # exactly a day old: out of the window


def test_sender_change_cap_applies_to_promote_and_root_admit() -> None:
    cap = pins.MAX_SENDER_CHANGES_PER_VENUE_PER_DAY
    spent = tuple(LAUNCH - (i + 1) * HOUR_NS for i in range(cap))

    promote = nominated(champion_chain())
    exhaust(promote, sender_changes=spent)
    refused = ask_promote(promote)
    assert refused is not None and refused.rule.value == "sender_change_daily_cap"

    # a ROLLBACK also counts, but the dwell window equals the cap's: any change in it is a dwell
    # refusal first (see ``test_rollback_dwell_follows_the_latest_sender_change``)

    admit = venue_only(Chain())
    exhaust(admit, sender_changes=spent)
    refused = root_admit(admit)
    assert refused is not None and refused.rule.value == "sender_change_daily_cap"


@pytest.mark.parametrize("facet", ["counting_rule"])
def test_damping_ceilings(facet: str) -> None:
    """Z3 counting rule: a non-drill →CHAMPION head, ROOT_ADMIT and RESUME count; the rest never do.

    With the daily cap already spent, each counting kind is refused and none of the kinds ARCH
    says never count is.
    """
    assert facet == "counting_rule"
    cap = pins.MAX_SENDER_CHANGES_PER_VENUE_PER_DAY
    full = tuple(LAUNCH - (i + 1) * HOUR_NS for i in range(cap))

    def spent() -> Chain:  # a probe appends its row: one chain per question
        chain = champion_chain()
        chain.add(Kind.MINT, State.SHADOW, family=OTHER, ts=at(PRIOR_DAY, "13:00"),
                  artefact_sha256=SECOND_ART)  # fmt: skip
        exhaust(chain, sender_changes=full)
        return chain

    nomination = probe(spent(), NOW, Kind.PROMOTE, State.CHALLENGER, family=OTHER, frm=State.SHADOW)
    assert nomination is None  # SHADOW to CHALLENGER never counts
    mint_row = probe(
        spent(), NOW, Kind.MINT, State.SHADOW, family="pm_us_crh_g", ts=NOW,
        lineage_root_family_id=INCUMBENT, artefact_sha256="3" * 64,
    )  # fmt: skip
    assert mint_row is None
    demote = probe(
        spent(), NOW, Kind.DEMOTE, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    assert demote is None  # restrictive rows never count
    attest = probe(
        spent(), NOW, Kind.ATTEST, State.CHAMPION, family=INCUMBENT, frm=State.CHAMPION, ts=NOW,
        attest_valid_until_ns=NOW + HOUR_NS,
    )  # fmt: skip
    assert attest is None

    def spent_before(instant: int) -> tuple[int, ...]:
        return tuple(instant - (n + 1) * HOUR_NS for n in range(cap))

    drill = open_episode_chain()  # drill-episode rows count only against the drill budget
    close_launch = at(NEXT_DAY, "16:50")
    exhaust(drill, sender_changes=spent_before(close_launch))
    closing = probe(
        drill, at(DAY, "20:00"), Kind.ROLLBACK, State.CHAMPION, family=INCUMBENT,
        frm=State.CHALLENGER, effective_launch_date=NEXT_DAY, drill=True,
    )  # fmt: skip
    assert closing is None

    failed = _failed_close_chain()
    exhaust(failed, sender_changes=spent_before(RESTORE_TS))
    assert restore(failed) is None  # a close restore is no sender change either

    drill_halted = champion_chain()
    halt_incumbent(drill_halted, CauseClass.DRILL)
    exhaust(drill_halted, sender_changes=spent_before(RESUME_TS))
    assert ask_resume(drill_halted) is None  # nor is the RESUME of a DRILL-class halt

    counting = model_halted()
    exhaust(counting, sender_changes=tuple(RESUME_TS - (i + 1) * HOUR_NS for i in range(cap)))
    assert rule_of(ask_resume(counting)) == "sender_change_daily_cap"


def test_one_logical_pair_is_one_sender_change_in_the_fold() -> None:
    chain, _head, _tail = activated_pair()  # a PROMOTE pair that takes effect at DAY's LAUNCH
    prior = run(chain, at(DAY, "18:00"))
    assert prior.venue_tallies.sender_changes == (LAUNCH,)  # head, partner and ACTIVATE: one


def test_a_pending_pair_is_a_reservation_against_the_daily_cap() -> None:
    cap = pins.MAX_SENDER_CHANGES_PER_VENUE_PER_DAY

    def second_head(spent: int) -> Any:
        chain = champion_chain()
        chain.add(Kind.MINT, State.SHADOW, family=OTHER, ts=at(PRIOR_DAY, "13:00"),
                  artefact_sha256=SECOND_ART)  # fmt: skip
        chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)
        chain.add(Kind.PROMOTE, State.CHALLENGER, family=OTHER, frm=State.SHADOW)
        chain.promote_pair(day=DAY)  # CHILD over INCUMBENT, pending: one reservation
        exhaust(chain, sender_changes=(LAUNCH - HOUR_NS,) * spent)
        prior = run(chain, NOW)
        assert prior.pairs[0].status.value == "pending"
        head = chain.add(
            Kind.PROMOTE, State.CHAMPION, family=OTHER, frm=State.CHALLENGER,
            effective_launch_date=DAY, manifest_sha256=CHILD_MAN, artefact_sha256=SECOND_ART,
        )  # fmt: skip
        return tm.first_refusal(prior, [head], manifests=facts_for_child)

    refused = second_head(cap - 1)  # one in the tally plus the reservation reaches the cap
    assert refused is not None and refused.rule.value == "sender_change_daily_cap"
    # one fewer in the tally: the cap rule passes (the head is then refused as a second sender)
    passed = second_head(cap - 2)
    assert passed is not None and passed.rule.value == "single_sender"


# --- ROLLBACK (A7c-R3) ---------------------------------------------------------------------------


def test_rollback_target_must_be_eligible_and_not_target_ineligible() -> None:
    assert ask_rollback(promoted_chain()) is None  # control: superseded, eligible

    never_superseded = champion_chain()
    never_superseded.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)
    refused = probe(
        never_superseded, NOW, Kind.ROLLBACK, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=THIRD_DAY,
    )  # fmt: skip
    assert refused is not None
    assert (refused.rule.value, refused.reason) == (
        "rollback_target_not_eligible", RefusalReason.ENGINE_INCONSISTENCY,
    )  # fmt: skip

    ineligible = promoted_chain()
    ineligible.add(
        Kind.TARGET_INELIGIBLE, State.CHALLENGER, family=INCUMBENT, frm=State.CHALLENGER,
        cause_code=CauseCode.TARGET_INTEGRITY, ts=at(DAY, "17:30"),
    )  # fmt: skip
    refused = ask_rollback(ineligible)
    assert refused is not None and refused.rule.value == "rollback_target_ineligible"


def test_rollback_target_max_age_counts_from_the_supersede() -> None:
    # INCUMBENT left CHAMPION at DAY's LAUNCH: ROLLBACK_TARGET_MAX_AGE_D days later is the last day
    limit = pins.ROLLBACK_TARGET_MAX_AGE_D
    assert limit == 30
    last_day = "2026-11-09"  # DAY + 30 d
    assert ask_rollback(promoted_chain(), day=last_day) is None
    refused = ask_rollback(promoted_chain(), day="2026-11-10")
    assert refused is not None and refused.rule.value == "rollback_target_too_old"


def test_rollback_dwell_follows_the_latest_sender_change() -> None:
    day_ns = DAY_NS
    launch = at(THIRD_DAY, "16:50")
    just_inside = launch - pins.ROLLBACK_MIN_DWELL_H * HOUR_NS + 1
    exactly = launch - pins.ROLLBACK_MIN_DWELL_H * HOUR_NS
    assert day_ns == 24 * HOUR_NS == pins.ROLLBACK_MIN_DWELL_H * HOUR_NS

    refused_chain = promoted_chain()
    exhaust(refused_chain, sender_changes=(just_inside,))
    refused = ask_rollback(refused_chain)
    assert refused is not None and refused.rule.value == "rollback_dwell"

    ok_chain = promoted_chain()
    exhaust(ok_chain, sender_changes=(exactly,))
    assert ask_rollback(ok_chain) is None


def test_rollback_dwell_follows_the_current_senders_epoch() -> None:
    """The anchor is also the current sender's epoch start: a RESUME opens one (Z3)."""
    chain = promoted_chain()  # CHILD CHAMPION since DAY's LAUNCH
    chain.add(
        Kind.HALT, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=at(DAY, "17:30"),
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    chain.add(
        Kind.RESUME, State.CHAMPION, family=CHILD, frm=State.HALTED, ts=at(THIRD_DAY, "10:00"),
        cause_verdict_ids=("c" * 64,),
    )  # fmt: skip
    refused = ask_rollback(chain, now=at(THIRD_DAY, "11:00"))
    assert refused is not None and refused.rule.value == "rollback_dwell"
    assert ask_rollback(chain, day="2026-10-14", now=at(THIRD_DAY, "11:00")) is None


def test_rollback_budget_sums_every_lineages_slice_over_thirty_days() -> None:
    cap = pins.MAX_ROLLBACKS_PER_VENUE_30D
    launch = at(THIRD_DAY, "16:50")
    recent = tuple(launch - (i + 5) * DAY_NS for i in range(cap))

    both_in_one = promoted_chain()
    exhaust(both_in_one, {INCUMBENT: {"rollbacks": recent}})
    refused = ask_rollback(both_in_one)
    assert refused is not None and refused.rule.value == "rollback_budget"

    split = promoted_chain()  # E-21: the venue cap sums the in-window slices across lineages
    exhaust(split, {INCUMBENT: {"rollbacks": recent[:1]}, OTHER: {"rollbacks": recent[1:]}})
    refused = ask_rollback(split)
    assert refused is not None and refused.rule.value == "rollback_budget"

    under = promoted_chain()
    exhaust(under, {INCUMBENT: {"rollbacks": recent[:1]}})
    assert ask_rollback(under) is None

    old = promoted_chain()
    stale = launch - 30 * DAY_NS  # exactly the window: out
    exhaust(old, {INCUMBENT: {"rollbacks": (stale, stale - DAY_NS)}})
    assert ask_rollback(old) is None

    just_in = promoted_chain()
    exhaust(just_in, {INCUMBENT: {"rollbacks": (stale + 1, stale + 2)}})
    refused = ask_rollback(just_in)
    assert refused is not None and refused.rule.value == "rollback_budget"


def test_a_drill_rollback_is_exempt_from_dwell_and_the_rollback_budget() -> None:
    cap = pins.MAX_ROLLBACKS_PER_VENUE_30D
    chain = open_episode_chain()  # CHILD took over at DAY's LAUNCH; the close is a day later
    exhaust(chain, {INCUMBENT: {"rollbacks": (LAUNCH,) * cap}}, sender_changes=(LAUNCH,))
    closing = probe(
        chain, at(DAY, "20:00"), Kind.ROLLBACK, State.CHAMPION, family=INCUMBENT,
        frm=State.CHALLENGER, effective_launch_date=NEXT_DAY, drill=True,
    )  # fmt: skip
    assert closing is None  # W3: the drill's closing ROLLBACK is admitted


# --- ATTEST (Y3, W1, Z4) -------------------------------------------------------------------------


ATTEST_AT: Final = at(PRIOR_DAY, "13:00")


def attest(chain: Chain, ts: int, until: int | None, *, now: int | None = None) -> Any:
    return probe(
        chain, ts if now is None else now, Kind.ATTEST, State.CHAMPION, family=INCUMBENT,
        frm=State.CHAMPION, ts=ts, attest_valid_until_ns=until,
    )  # fmt: skip


def test_attest_validity_is_capped_at_the_verdict_validity_window() -> None:
    ceiling = ATTEST_AT + pins.ATTEST_VERDICT_VALIDITY_H * HOUR_NS
    assert attest(champion_chain(), ATTEST_AT, ceiling) is None
    refused = attest(champion_chain(), ATTEST_AT, ceiling + 1)
    assert refused is not None and refused.rule.value == "attest_validity"
    missing = attest(champion_chain(), ATTEST_AT, None)
    assert missing is not None and missing.rule.value == "attest_validity"


def test_attest_cadence_one_per_period_with_the_first_of_an_epoch_exempt() -> None:
    period = pins.ATTEST_PERIOD_H * HOUR_NS

    def after_one() -> Chain:
        chain = champion_chain()
        chain.add(Kind.ATTEST, State.CHAMPION, family=INCUMBENT, frm=State.CHAMPION,
                  ts=ATTEST_AT, attest_valid_until_ns=ATTEST_AT + HOUR_NS)  # fmt: skip
        return chain

    soon = ATTEST_AT + period - 1
    refused = attest(after_one(), soon, soon + HOUR_NS)
    assert refused is not None and refused.rule.value == "attest_cadence"
    due = ATTEST_AT + period
    assert attest(after_one(), due, due + HOUR_NS) is None
    assert attest(champion_chain(), soon, soon + HOUR_NS) is None  # the first ever: exempt

    # a RESUME opens a new epoch: its first ATTEST is exempt again
    resumed = after_one()
    resumed.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, ts=ATTEST_AT + HOUR_NS,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    resumed.add(
        Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED,
        ts=ATTEST_AT + 2 * HOUR_NS, cause_verdict_ids=("c" * 64,),
    )  # fmt: skip
    again = ATTEST_AT + 3 * HOUR_NS
    assert attest(resumed, again, again + HOUR_NS) is None


def test_attest_cadence_counts_the_earlier_rows_of_the_batch() -> None:
    chain = champion_chain()
    prior = run(chain, ATTEST_AT)
    rows = [
        chain.add(
            Kind.ATTEST,
            State.CHAMPION,
            family=INCUMBENT,
            frm=State.CHAMPION,
            ts=ts,
            attest_valid_until_ns=ts + HOUR_NS,
        )
        for ts in (ATTEST_AT, ATTEST_AT + HOUR_NS)
    ]
    assert tm.first_refusal(prior, rows[:1], manifests=no_facts) is None
    refused = tm.first_refusal(prior, rows, manifests=no_facts)
    assert refused is not None and (refused.rule.value, refused.row_index) == ("attest_cadence", 1)


# --- SWAP_CANCEL voids a subset of the pending pairs ---------------------------------------------


def ask_cancel(chain: Chain, now: int, voids: tuple[str, ...]) -> Any:
    return probe(
        chain, now, Kind.SWAP_CANCEL, State.CHALLENGER, family=CHILD, frm=State.CHALLENGER,
        ts=now, voids_transition_ids=voids, cause_code=CauseCode.PRELAUNCH_PRECHECK_FAILED,
    )  # fmt: skip


def test_swap_cancel_may_void_only_members_of_a_pending_pair() -> None:
    before = at(DAY, "16:46")

    def ask(pick: Any) -> Any:  # a probe appends its row, so each question gets its own chain
        chain, head, tail = activated_pair()
        return ask_cancel(chain, before, pick(head, tail))

    assert ask(lambda h, t: (h.transition_id,)) is None
    assert ask(lambda h, t: (t.transition_id,)) is None
    assert ask(lambda h, t: (h.transition_id, t.transition_id)) is None

    refused = ask(lambda h, t: ("e" * 64,))
    assert refused is not None
    assert (refused.rule.value, refused.reason) == (
        "swap_cancel_voids_not_pending", RefusalReason.ENGINE_INCONSISTENCY,
    )  # fmt: skip
    mixed = ask(lambda h, t: (h.transition_id, "e" * 64))
    assert mixed is not None and mixed.rule.value == "swap_cancel_voids_not_pending"


def test_swap_cancel_of_a_lapsed_or_voided_pair_is_refused() -> None:
    lapsed, head, _tail = activated_pair()
    lapsed.rows = [r for r in lapsed.rows if r.kind is not Kind.ACTIVATE]  # never activated
    refused = ask_cancel(lapsed, at(DAY, "18:00"), (head.transition_id,))
    assert refused is not None and refused.rule.value == "swap_cancel_voids_not_pending"

    voided, head, _tail = activated_pair()
    cancel(voided, head, ts=at(DAY, "16:46"))
    refused = ask_cancel(voided, at(DAY, "16:47"), (head.transition_id,))
    assert refused is not None and refused.rule.value == "swap_cancel_voids_not_pending"


def test_a_post_launch_swap_cancel_is_valid_only_inside_the_launch_window() -> None:
    # an effective pair: the cancel names the incoming family as CHALLENGER (A7c-A2)
    chain, head, _tail = activated_pair()
    assert ask_cancel(chain, at(DAY, "16:55"), (head.transition_id,)) is None
    chain, head, _tail = activated_pair()
    after = ask_cancel(chain, at(DAY, "17:00"), (head.transition_id,))
    assert after is not None and after.rule.value == "swap_cancel_voids_not_pending"


def test_swap_cancel_may_void_a_pair_written_earlier_in_the_same_batch() -> None:
    chain = champion_chain()
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)
    prior = run(chain, NOW)
    head, tail = chain.promote_pair(day=DAY)
    cancel_row = cancel(chain, head, ts=NOW + SEC)
    batch = [head, tail, cancel_row]
    refused = tm.first_refusal(prior, batch, manifests=facts_for_child)
    assert refused is None or refused.rule.value != "swap_cancel_voids_not_pending"
    lone = tm.first_refusal(prior, [cancel_row], manifests=facts_for_child)
    assert lone is not None and lone.rule.value == "swap_cancel_voids_not_pending"


# --- HWM_RESET floors (B9) -----------------------------------------------------------------------


def _reset_row(chain: Chain, text: str | None) -> TransitionRow:
    return chain.add(
        Kind.HWM_RESET, State.CHAMPION, family=INCUMBENT, frm=State.CHAMPION,
        decided_by=DecidedBy.OPERATOR_CLI, hwm_from=3, hwm_to=4, carried_counters=text,
    )  # fmt: skip


def ask_reset(row_counters: str | None, export: Any) -> Any:
    chain = champion_chain()
    prior = run(chain, NOW)
    row = _reset_row(chain, row_counters)
    return tm.first_refusal(prior, [row], manifests=no_facts, export_counters=export)


T1: Final = at(PRIOR_DAY, "14:00")
T2: Final = at(PRIOR_DAY, "15:00")


@pytest.mark.parametrize(
    ("facet", "export", "carry", "refused"),
    [
        ("equal", {"nominations": 2, "mints": (T1,)}, {"nominations": 2, "mints": (T1,)}, False),
        (
            "higher",
            {"nominations": 2, "mints": (T1,)},
            {"nominations": 3, "mints": (T1, T2)},
            False,
        ),
        ("int_below", {"nominations": 2}, {"nominations": 1}, True),
        ("infeasible_below", {"infeasible_nominations": 1}, {}, True),
        ("alpha_below", {"alpha_spent": "0.05"}, {"alpha_spent": "0.04"}, True),
        ("alpha_equal", {"alpha_spent": "0.05"}, {"alpha_spent": "0.05"}, False),
        ("instant_missing", {"rollbacks": (T1,)}, {}, True),
        ("instant_other", {"rollbacks": (T1,)}, {"rollbacks": (T2,)}, True),
        ("multiplicity", {"rollbacks": (T1, T1)}, {"rollbacks": (T1,)}, True),
        ("multiplicity_ok", {"rollbacks": (T1, T1)}, {"rollbacks": (T1, T1, T2)}, False),
        ("frozen_dropped", {"terminal_frozen": True}, {"terminal_frozen": False}, True),
        ("frozen_added", {"terminal_frozen": False}, {"terminal_frozen": True}, False),
    ],
)
def test_hwm_reset_store_refuses_carried_counters_below_export(
    facet: str, export: dict[str, Any], carry: dict[str, Any], refused: bool
) -> None:
    result = ask_reset(carried({INCUMBENT: _sorted(carry)}), carried({INCUMBENT: _sorted(export)}))
    assert (result is not None) is refused, facet
    if refused:
        assert result is not None
        assert (result.rule.value, result.reason) == (
            "hwm_carried_below_export", RefusalReason.ENGINE_INCONSISTENCY,
        )  # fmt: skip


def _sorted(counters: dict[str, Any]) -> dict[str, Any]:
    return {k: tuple(sorted(v)) if isinstance(v, tuple) else v for k, v in counters.items()}


def test_hwm_reset_floors_cover_venue_counters_and_missing_lineages() -> None:
    export = carried({INCUMBENT: {}}, {"sender_changes": (T1,), "infra_resumes": (T2,)})
    ok = carried({INCUMBENT: {}}, {"sender_changes": (T1, T2), "infra_resumes": (T2,)})
    short = carried({INCUMBENT: {}}, {"sender_changes": (T1,)})
    assert ask_reset(ok, export) is None
    refused = ask_reset(short, export)
    assert refused is not None and refused.rule.value == "hwm_carried_below_export"

    no_lineage = carried({}, {"sender_changes": (T1,), "infra_resumes": (T2,)})
    refused = ask_reset(no_lineage, export)  # the export's lineage is missing from the carry
    assert refused is not None and refused.rule.value == "hwm_carried_below_export"


def test_hwm_reset_needs_the_export_and_a_well_formed_carry() -> None:
    export = carried({INCUMBENT: {}})
    missing = ask_reset(export, None)
    assert missing is not None and missing.rule.value == "hwm_export_missing"
    unreadable = ask_reset(export, "{}")  # an export that is not of the counters shape
    assert unreadable is not None and unreadable.rule.value == "hwm_export_missing"
    for bad in (None, "{}"):  # absent, or an object that is not of the counters shape
        refused = ask_reset(bad, export)
        assert refused is not None and refused.rule.value == "hwm_counters_malformed"
    assert ask_reset(export, export) is None  # text and parsed forms both work
    parsed = parse_carried(export)
    assert parsed is not None and ask_reset(export, parsed) is None


def test_validate_takes_the_export_and_returns_its_closed_reason() -> None:
    chain = champion_chain()
    prior = run(chain, NOW)
    row = _reset_row(chain, carried({INCUMBENT: {"nominations": 1}}))
    kwargs: dict[str, Any] = {
        "mode": WriterMode.OPERATOR_CLI,
        "now_ns": NOW,
        "stage": STAGE,
        "manifests": no_facts,
    }
    export = carried({INCUMBENT: {"nominations": 2}})
    assert tm.validate(prior, [row], export_counters=export, **kwargs) is (
        RefusalReason.ENGINE_INCONSISTENCY
    )
    assert tm.validate(prior, [row], export_counters=carried({INCUMBENT: {}}), **kwargs) is None


# --- single sender (ARCH:462; Z3) ----------------------------------------------------------------


def test_a_lone_head_leaves_two_senders_at_launch_and_is_refused() -> None:
    chain = nominated(champion_chain())
    prior = run(chain, NOW)
    head = chain.add(
        Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=DAY, manifest_sha256=CHILD_MAN, artefact_sha256=INC_ART,
    )  # fmt: skip
    refused = tm.first_refusal(prior, [head], manifests=facts_for_child)
    assert refused is not None
    assert (refused.rule.value, refused.row_index) == ("single_sender", 0)
    assert refused.reason is RefusalReason.ENGINE_INCONSISTENCY

    partner = chain.add(
        Kind.SUPERSEDE, State.CHALLENGER, family=INCUMBENT, frm=State.CHAMPION,
        paired_transition_id=head.transition_id, effective_launch_date=DAY,
    )  # fmt: skip
    assert tm.first_refusal(prior, [head, partner], manifests=facts_for_child) is None


def test_a_halted_senders_partner_is_displaced_and_leaves_one_sender() -> None:
    chain = nominated(champion_chain())
    halt_incumbent(chain, CauseClass.RECOVERABLE_MODEL)
    assert ask_promote(chain) is None  # probe adds the DISPLACED partner of the HALTED sender


def test_a_pending_pair_of_the_prior_counts_toward_the_next_launch() -> None:
    def second_root_admit(*, with_pending: bool) -> Any:
        chain = venue_only(Chain())  # no sender now: ROOT_ADMIT's own rule is satisfied
        if with_pending:
            chain.add(
                Kind.ROOT_ADMIT, State.CHAMPION, family=OTHER, effective_launch_date=DAY,
                manifest_sha256=INC_MAN,
            )  # fmt: skip
        prior = run(chain, NOW)
        row = chain.add(
            Kind.ROOT_ADMIT, State.CHAMPION, family="pm_us_crh_cont", effective_launch_date=DAY,
            manifest_sha256=INC_MAN,
        )  # fmt: skip
        return tm.first_refusal(prior, [row], manifests=no_facts)

    assert second_root_admit(with_pending=False) is None
    refused = second_root_admit(with_pending=True)  # two roots would both send at DAY's LAUNCH
    assert refused is not None and refused.rule.value == "single_sender"


def test_a_head_the_batch_cancels_leaves_no_second_sender() -> None:
    chain = nominated(champion_chain())
    prior = run(chain, NOW)
    head = chain.add(
        Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=DAY, manifest_sha256=CHILD_MAN, artefact_sha256=INC_ART,
    )  # fmt: skip
    voiding = cancel(chain, head, ts=NOW + SEC)
    assert tm.first_refusal(prior, [head, voiding], manifests=facts_for_child) is None


def two_sender_prior() -> FoldResult:
    """The chain 7c refuses (E-19a) and the fold pins: INCUMBENT CHAMPION and CHILD HALTED."""
    chain, head, _tail = activated_pair()
    chain.add(
        Kind.DEMOTE, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=at(DAY, "16:55"),
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    cancel(chain, head, ts=at(DAY, "16:56"), cause=CauseCode.PAIR_CAUSE_INCOMING)
    prior = run(chain, at(DAY, "18:00"))
    assert prior.senders == (INCUMBENT, CHILD)
    return prior


def test_a_non_restrictive_batch_over_two_senders_is_refused_but_a_restrictive_one_never_is() -> (
    None
):
    prior = two_sender_prior()
    mint_row = _plain_row(
        Kind.MINT, State.SHADOW, family=OTHER, lineage_root_family_id=INCUMBENT,
        artefact_sha256=SECOND_ART,
    )  # fmt: skip
    refused = tm.first_refusal(prior, [mint_row], manifests=no_facts)
    assert refused is not None and refused.rule.value == "single_sender"

    demote = _plain_row(
        Kind.DEMOTE, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    assert tm.first_refusal(prior, [demote], manifests=no_facts) is None  # restrictive: permitted


def _plain_row(kind: Kind, to: State, *, family: str, frm: State | None = None, **x: Any) -> Any:
    scratch = Chain()
    scratch.rows = []
    return scratch.add(kind, to, family=family, frm=frm, ts=at(DAY, "18:00"), **x)


# --- restrictive batches never add a sender: the reachability the exemption rests on -------------


def _scenarios() -> list[tuple[str, Chain, int]]:
    pending, _h, _t = _pair_chain(activate=True)
    window, _h2, _t2 = _pair_chain(activate=True)
    after, _h3, _t3 = _pair_chain(activate=True)
    unactivated, _h4, _t4 = _pair_chain(activate=False)
    return [
        ("pending", pending, at(DAY, "16:46")),
        ("launch_window", window, at(DAY, "16:55")),
        ("after_window", after, at(DAY, "17:30")),
        ("lapsed", unactivated, at(DAY, "17:30")),
    ]


def _pair_chain(*, activate: bool) -> tuple[Chain, TransitionRow, TransitionRow]:
    chain, head, tail = _seeded()
    if activate:
        chain.activate(head, ts=at(DAY, "16:45"))
    return chain, head, tail


def _seeded() -> tuple[Chain, TransitionRow, TransitionRow]:
    chain = Chain()
    chain.seed()
    head, tail = chain.promote_pair(day=DAY)
    return chain, head, tail


@pytest.mark.parametrize("name", ["pending", "launch_window", "after_window", "lapsed"])
def test_a_restrictive_batch_that_validate_accepts_never_leaves_two_senders(name: str) -> None:
    """The exemption's premise: with E-19a no accepted restrictive batch yields two senders.

    Every restrictive row of each family (and every pair of them), in every phase of an ordinary
    pair, is asked of ``validate``; each accepted batch is folded at every interesting instant.
    """
    scenario = {n: (c, ts) for n, c, ts in _scenarios()}[name]
    chain, now = scenario
    prior = run(chain, now)
    head = next(r for r in chain.rows if r.kind is Kind.PROMOTE and r.effective_launch_date)
    candidates: list[dict[str, Any]] = []
    halting = {
        "halt_cause_class": CauseClass.RECOVERABLE_MODEL,
        "cause_code": CauseCode.VERDICT_FAIL,
    }
    for family in (INCUMBENT, CHILD):
        for kind in (Kind.DEMOTE, Kind.HALT):
            for state in (State.CHAMPION, State.HALTED, State.CHALLENGER):
                candidates.append(
                    {"kind": kind, "to": State.HALTED, "family": family, "frm": state, **halting}
                )
        for cause in (CauseCode.PAIR_CAUSE_INCOMING, CauseCode.PAIR_CAUSE_OUTGOING):
            candidates.append(
                {
                    "kind": Kind.SWAP_CANCEL, "to": State.CHALLENGER, "family": family,
                    "frm": State.CHALLENGER, "cause_code": cause,
                    "voids_transition_ids": (head.transition_id,),
                }
            )  # fmt: skip
        candidates.append(
            {
                "kind": Kind.TARGET_INELIGIBLE, "to": State.CHALLENGER, "family": family,
                "frm": State.CHALLENGER, "cause_code": CauseCode.TARGET_INTEGRITY,
            }
        )  # fmt: skip
    # only shapes the store's ``ALLOWED`` table admits ever reach ``validate``
    candidates = [c for c in candidates if (c["frm"], c["to"]) in tm.ALLOWED[c["kind"]]]

    accepted = 0
    for first in candidates:
        for second in (None, *candidates):
            scratch = Chain()
            scratch.rows = list(chain.rows)
            scratch._ts = chain._ts
            scratch._last_seq = dict(chain._last_seq)
            batch = [scratch.add(ts=now, **first)]
            if second is not None:
                batch.append(scratch.add(ts=now, **second))
            if tm.first_refusal(prior, batch, manifests=no_facts) is not None:
                continue
            accepted += 1
            for instant in (
                now,
                LAUNCH - 1,
                LAUNCH,
                at(DAY, "16:59"),
                at(DAY, "17:30"),
                at(NEXT_DAY, "18:00"),
            ):
                result = run(scratch, instant)
                assert len(result.senders) <= 1, (name, first, second, instant, result.states)
    assert accepted > 0  # the matrix is not vacuous


# --- the walk's other duties ---------------------------------------------------------------------


def test_validate_reads_no_manifest_for_a_restrictive_or_neutral_row() -> None:
    def boom(family_id: str, manifest_sha256: str) -> Any:
        raise AssertionError("a restrictive or neutral row must not read manifests")

    chain = champion_chain()
    prior = run(chain, NOW)
    rows = [
        chain.add(
            Kind.DEMOTE,
            State.HALTED,
            family=INCUMBENT,
            frm=State.CHAMPION,
            halt_cause_class=CauseClass.RECOVERABLE_MODEL,
            cause_code=CauseCode.VERDICT_FAIL,
        ),
    ]
    assert tm.first_refusal(prior, rows, manifests=boom) is None
    fresh = champion_chain()
    base = run(fresh, NOW)
    mint_row = fresh.add(Kind.MINT, State.SHADOW, family=OTHER, artefact_sha256=SECOND_ART)
    assert tm.first_refusal(base, [mint_row], manifests=boom) is None


def test_every_rule_ii_name_is_unique_and_wired() -> None:
    names = [r.value for r in tm.RuleII]
    assert len(names) == len(set(names)) == len(tm.RuleII)
    assert not set(names) & {r.value for r in tm.Rule}  # a refusal names exactly one rule
