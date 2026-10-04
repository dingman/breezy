"""ARCH-0 seam 7c: ``transitions.validate`` I (drill, RESUME, E-5, the Y8 clear, E-19a).

``validate`` judges new rows against the fold of the rows already written. These tests build a
prior chain, fold it, then ask ``first_refusal`` (the rule-level form of ``validate``) about one
candidate row. Windowed budgets are the lengths of in-window slices of the fold's tally tuples
(E-21), so an exhausted budget is planted through an ``HWM_RESET`` ``carried_counters`` floor.

d0 and ``trial_id_prefix`` and the E-5 per-day cap live in ``test_registry_validate_store.py``.
The module is reached through ``tm`` so that each test fails by itself while a symbol is missing.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import pytest

import breezy.persistence.autonomy.transitions as tm
from breezy.persistence.autonomy.fold import FoldResult
from breezy.persistence.autonomy.schemas import (
    CauseClass,
    CauseCode,
    Kind,
    ManifestFacts,
    ManifestFactsReader,
    RefusalReason,
    State,
    TransitionRow,
    WriterMode,
)
from breezy.persistence.autonomy.stage_policy import STAGE
from breezy.persistence.autonomy.verdict import (
    ActionClass,
    Assumption,
    Verdict,
    VerdictKind,
    VerdictOutcome,
)
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
from tests.unit.test_registry_fold_effects import NEXT_DAY, DrillChain, activated_pair, cancel
from tests.unit.test_registry_fold_tallies import carried, reset

if TYPE_CHECKING:
    from breezy.persistence.autonomy.validate import Refusal

DAY_NS: Final = 86_400 * SEC
HOUR_NS: Final = 3_600 * SEC
INC_MAN: Final = "1" * 64
INC_ART: Final = "a" * 64
CHILD_MAN: Final = "2" * 64
CITED: Final = ("c" * 64,)
HALT_TS: Final = at(PRIOR_DAY, "13:00")
RESUME_TS: Final = at(DAY, "16:45")
DRILL_CAUSE: Final[dict[str, Any]] = {
    "halt_cause_class": CauseClass.DRILL,
    "cause_code": CauseCode.VERDICT_FAIL,
}


def no_facts(family_id: str, manifest_sha256: str) -> ManifestFacts | None:
    return None


def facts_for_child(family_id: str, manifest_sha256: str) -> ManifestFacts | None:
    return ManifestFacts(
        family_id=family_id, manifest_sha256=manifest_sha256, d0_climate_day=NEXT_DAY,
        trial_id_prefix=f"forecast_quantile_ladder/trial/{family_id}/",
        composition_kind="forecast_quantile_ladder",
    )  # fmt: skip


def champion_chain() -> DrillChain:
    """INCUMBENT CHAMPION bound to its shas; CHILD a MINT whose artefact is byte-identical."""
    chain = DrillChain()
    chain.add(
        Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT,
        manifest_sha256=INC_MAN, artefact_sha256=INC_ART,
    )  # fmt: skip
    chain.add(
        Kind.MINT, State.SHADOW, family=CHILD, manifest_sha256=CHILD_MAN, artefact_sha256=INC_ART
    )
    return chain


def freeze_venue(chain: Chain) -> None:
    """An exec-store halt (INTEGRITY) of a third family, then retired: only the freeze remains."""
    chain.add(Kind.BOOTSTRAP, State.RETIRED, family=OTHER)
    chain.add(
        Kind.HALT, State.HALTED, family=OTHER, frm=State.CHAMPION,
        halt_cause_class=CauseClass.INTEGRITY, cause_code=CauseCode.EXEC_STORE_HALT_MIRROR,
    )  # fmt: skip
    chain.add(Kind.RETIRE, State.RETIRED, family=OTHER, frm=State.HALTED)


def halt_incumbent(
    chain: Chain,
    cls: CauseClass | None,
    *,
    code: CauseCode = CauseCode.VERDICT_FAIL,
    trigger: CauseClass | None = None,
    ts: int = HALT_TS,
) -> TransitionRow:
    return chain.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, ts=ts,
        halt_cause_class=cls, cause_code=code, trigger_cause_class=trigger,
    )  # fmt: skip


def exhaust(chain: Chain, lineages: dict[str, dict[str, Any]] | None = None, **venue: Any) -> None:
    """Plant counters through an ``HWM_RESET`` floor (instants are sorted, as the fold requires)."""

    def ordered(counters: dict[str, Any]) -> dict[str, Any]:
        return {k: tuple(sorted(v)) if isinstance(v, tuple) else v for k, v in counters.items()}

    planted = {root: ordered(c) for root, c in (lineages or {}).items()}
    reset(chain, carried(planted, ordered(venue) if venue else None))


def probe(
    chain: Chain,
    now: int,
    kind: Kind,
    to: State,
    *,
    family: str,
    frm: State | None = None,
    manifests: ManifestFactsReader = no_facts,
    verdicts: dict[str, Verdict] | None = None,
    **extra: Any,
) -> Refusal | None:
    """Fold the chain as it stands, append the candidate and ask about it alone."""
    prior = run(chain, now)
    row = chain.add(kind, to, family=family, frm=frm, **extra)
    return tm.first_refusal(prior, [row], manifests=manifests, verdicts=verdicts)


def resume(
    chain: Chain,
    *,
    now: int = RESUME_TS,
    ts: int | None = None,
    frm: State = State.HALTED,
    **extra: Any,
) -> Refusal | None:
    extra.setdefault("cause_verdict_ids", CITED)
    return probe(
        chain, now, Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=frm,
        ts=RESUME_TS if ts is None else ts, **extra,
    )  # fmt: skip


def model_halted() -> DrillChain:
    chain = champion_chain()
    halt_incumbent(chain, CauseClass.RECOVERABLE_MODEL)
    return chain


def rule_of(refusal: Refusal | None) -> str | None:
    return None if refusal is None else refusal.rule.value


# --- E-5: the restorative RESUME after a failed drill close ------------------------------------

RESTORE_TS: Final = at("2026-10-13", "16:45")  # C+2: the first pass past the cooldown
RESTORE: Final[dict[str, Any]] = {
    "cause_code": CauseCode.DRILL_CLOSE_RESTORE,
    "manifest_sha256": INC_MAN,
    "artefact_sha256": INC_ART,
}


def failed_close_chain(
    *, halt: Callable[[Chain], None] | None = None, drill_halt_child: bool = False
) -> DrillChain:
    """A drill whose closing ROLLBACK failed: INCUMBENT HALTED, ROLLBACK_FAILED under DRILL."""
    chain = champion_chain()
    chain.add(
        Kind.DRILL_ADMIT, State.CHALLENGER, family=CHILD, frm=State.SHADOW, artefact_sha256=INC_ART
    )
    head, _tail = chain.drill_pair(DAY)
    chain.activate(head, ts=at(DAY, "16:45"))
    closing = chain.close_pair(NEXT_DAY)
    chain.activate(closing, ts=at(NEXT_DAY, "16:46"), family=INCUMBENT)
    if halt is None:
        halt_incumbent(
            chain, CauseClass.ROLLBACK_FAILED, code=CauseCode.ROLLBACK_FAILED,
            trigger=CauseClass.DRILL, ts=at(NEXT_DAY, "16:55"),
        )  # fmt: skip
    else:
        halt(chain)
    if drill_halt_child:
        chain.add(
            Kind.DEMOTE, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=at(NEXT_DAY, "17:05"),
            **DRILL_CAUSE,
        )  # fmt: skip
    return chain


def restore(
    chain: Chain, *, family: str = INCUMBENT, ts: int = RESTORE_TS, **extra: Any
) -> Refusal | None:
    return probe(
        chain, ts, Kind.RESUME, State.CHAMPION, family=family, frm=State.HALTED, ts=ts,
        **{**RESTORE, **extra},
    )  # fmt: skip


# --- FamilyView facts validate reads ------------------------------------------------------------


def test_family_view_binds_the_introducing_artefact_and_the_latest_manifest() -> None:
    chain = champion_chain()
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)  # carries no sha
    chain.add(Kind.ATTEST, State.CHAMPION, family=INCUMBENT, frm=State.CHAMPION)
    rebound = "3" * 64
    chain.add(
        Kind.ATTEST, State.CHAMPION, family=INCUMBENT, frm=State.CHAMPION, artefact_sha256=rebound
    )

    result = run(chain, LAUNCH)

    assert result.families[INCUMBENT].manifest_sha256 == INC_MAN
    assert result.families[INCUMBENT].artefact_sha256 == INC_ART  # A7c-R5: the introducing row's
    assert result.families[CHILD].manifest_sha256 == CHILD_MAN
    assert result.families[CHILD].artefact_sha256 == INC_ART


def test_family_view_names_the_standing_cause_only_while_halted() -> None:
    chain = champion_chain()
    halt_incumbent(
        chain, CauseClass.ROLLBACK_FAILED, code=CauseCode.ROLLBACK_FAILED,
        trigger=CauseClass.RECOVERABLE_INFRA,
    )  # fmt: skip
    halted = run(chain, LAUNCH).families[INCUMBENT]
    assert halted.standing_cause_class is CauseClass.RECOVERABLE_INFRA  # the trigger's class
    assert halted.standing_cause_code is CauseCode.ROLLBACK_FAILED

    chain.add(Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED)
    resumed = run(chain, LAUNCH).families[INCUMBENT]
    assert (resumed.standing_cause_class, resumed.standing_cause_code) == (None, None)


# --- the shape of validate ----------------------------------------------------------------------


def test_validate_maps_a_refusal_to_its_closed_reason_and_accepts_the_rest() -> None:
    chain = champion_chain()
    prior = run(chain, LAUNCH)
    bad = chain.add(
        Kind.DRILL_ADMIT, State.CHALLENGER, family=CHILD, frm=State.SHADOW, artefact_sha256="9" * 64
    )
    good = chain.add(
        Kind.DRILL_ADMIT, State.CHALLENGER, family=CHILD, frm=State.SHADOW, artefact_sha256=INC_ART
    )

    def judge(rows: list[TransitionRow]) -> RefusalReason | None:
        return tm.validate(
            prior, rows, mode=WriterMode.DAILY, now_ns=LAUNCH, stage=STAGE, manifests=no_facts
        )

    assert judge([]) is None
    assert judge([good]) is None
    assert judge([bad]) is RefusalReason.ENGINE_INCONSISTENCY
    refusal = tm.first_refusal(prior, [good, bad], manifests=no_facts)
    assert refusal is not None and refusal.row_index == 1  # the first refusal, in row order


def test_validate_is_exported_by_transitions_from_its_own_module() -> None:
    import breezy.persistence.autonomy.validate as validate_mod

    assert tm.validate is validate_mod.validate
    assert tm.first_refusal is validate_mod.first_refusal


# --- drill entry (W2, Y2, C3) -------------------------------------------------------------------

DRILL_ENTRY: Final = [
    (Kind.DRILL_ADMIT, State.SHADOW, State.CHALLENGER),
    (Kind.DRILL_PROMOTE, State.CHALLENGER, State.CHAMPION),
]


def admitted(chain: Chain) -> None:
    """The child is a CHALLENGER before a DRILL_PROMOTE (the rows' ``from_state`` are checked)."""
    chain.add(
        Kind.DRILL_ADMIT, State.CHALLENGER, family=CHILD, frm=State.SHADOW, artefact_sha256=INC_ART
    )


def drill_row(chain: Chain, kind: Kind, frm: State, to: State, **extra: Any) -> Refusal | None:
    if kind is Kind.DRILL_PROMOTE:  # a first →CHAMPION row: its manifest facts must read (U1)
        admitted(chain)
        extra.setdefault("effective_launch_date", DAY)
        extra.setdefault("manifest_sha256", CHILD_MAN)
    return probe(chain, LAUNCH, kind, to, family=CHILD, frm=frm, manifests=facts_for_child, **extra)


@pytest.mark.parametrize(("kind", "frm", "to"), DRILL_ENTRY, ids=["admit", "promote"])
def test_drill_promote_refuses_non_champion_sha(kind: Kind, frm: State, to: State) -> None:
    assert drill_row(champion_chain(), kind, frm, to, artefact_sha256=INC_ART) is None
    wrong = drill_row(champion_chain(), kind, frm, to, artefact_sha256="9" * 64)
    assert rule_of(wrong) == "drill_artefact_not_champion"
    assert rule_of(drill_row(champion_chain(), kind, frm, to)) == "drill_artefact_not_champion"


@pytest.mark.parametrize(("kind", "frm", "to"), DRILL_ENTRY, ids=["admit", "promote"])
def test_drill_refused_over_halted_incumbent(kind: Kind, frm: State, to: State) -> None:
    chain = champion_chain()
    halt_incumbent(chain, CauseClass.RECOVERABLE_MODEL)

    assert rule_of(drill_row(chain, kind, frm, to, artefact_sha256=INC_ART)) == (
        "drill_over_halted_incumbent"
    )


def test_drill_refused_without_exactly_one_sender() -> None:
    nobody = Chain()
    nobody.add(Kind.BOOTSTRAP, State.RETIRED, family=INCUMBENT)
    nobody.add(Kind.MINT, State.SHADOW, family=CHILD)
    assert rule_of(
        drill_row(nobody, Kind.DRILL_ADMIT, State.SHADOW, State.CHALLENGER, artefact_sha256=INC_ART)
    ) == ("drill_no_single_incumbent")


@pytest.mark.parametrize(("kind", "frm", "to"), DRILL_ENTRY, ids=["admit", "promote"])
def test_drill_row_refused_while_integrity_freeze_stands(kind: Kind, frm: State, to: State) -> None:
    chain = champion_chain()
    freeze_venue(chain)

    refused = drill_row(chain, kind, frm, to, artefact_sha256=INC_ART)

    assert rule_of(refused) == "drill_cause_stands"
    assert refused is not None and refused.reason is RefusalReason.ENGINE_INCONSISTENCY


@pytest.mark.parametrize("kind", [Kind.DEMOTE, Kind.HALT])
def test_drill_class_halt_refused_while_an_exec_store_halt_stands(kind: Kind) -> None:
    frozen = champion_chain()
    freeze_venue(frozen)
    assert (
        rule_of(
            probe(
                frozen,
                LAUNCH,
                kind,
                State.HALTED,
                family=INCUMBENT,
                frm=State.CHAMPION,
                **DRILL_CAUSE,
            )
        )
        == "drill_cause_stands"
    )

    clear = champion_chain()
    assert (
        probe(
            clear, LAUNCH, kind, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, **DRILL_CAUSE
        )
        is None
    )


# --- drill budgets (V15, W2) --------------------------------------------------------------------

DRILL_BUDGET_NOW: Final = at(DAY, "16:42")
DRILL_ROWS: Final[dict[str, tuple[Kind, State, State, dict[str, Any]]]] = {
    "drill_demotes": (Kind.DEMOTE, State.HALTED, State.CHAMPION, DRILL_CAUSE),
    "drill_halts": (Kind.HALT, State.HALTED, State.CHAMPION, DRILL_CAUSE),
    "drill_admits": (
        Kind.DRILL_ADMIT, State.CHALLENGER, State.SHADOW, {"artefact_sha256": INC_ART}
    ),
    "drill_promotes": (
        Kind.DRILL_PROMOTE, State.CHAMPION, State.CHALLENGER,
        {"artefact_sha256": INC_ART, "effective_launch_date": DAY, "manifest_sha256": CHILD_MAN},
    ),
}  # fmt: skip
#: A budget window is counted back from the row's effective instant: LAUNCH for a dated row.
DRILL_EFFECTIVE: Final = {c: DRILL_BUDGET_NOW for c in DRILL_ROWS} | {"drill_promotes": LAUNCH}


def drill_candidate(chain: Chain, counter: str) -> Refusal | None:
    kind, to, frm, extra = DRILL_ROWS[counter]
    if kind is Kind.DRILL_PROMOTE:
        admitted(chain)
    family = INCUMBENT if counter in ("drill_demotes", "drill_halts") else CHILD
    return probe(
        chain, DRILL_BUDGET_NOW, kind, to, family=family, frm=frm, ts=DRILL_BUDGET_NOW,
        manifests=facts_for_child, **extra,
    )  # fmt: skip


@pytest.mark.parametrize("counter", sorted(DRILL_ROWS))
def test_drill_demote_and_halt_counters_capped(counter: str) -> None:
    recent = DRILL_BUDGET_NOW - DAY_NS
    stale = DRILL_EFFECTIVE[counter] - 30 * DAY_NS  # exactly the window length: no longer counted

    spent = champion_chain()
    exhaust(spent, {INCUMBENT: {counter: (recent,)}})
    assert rule_of(drill_candidate(spent, counter)) == "drill_budget"

    lapsed = champion_chain()
    exhaust(lapsed, {INCUMBENT: {counter: (stale,)}})
    assert drill_candidate(lapsed, counter) is None

    inside = champion_chain()
    exhaust(inside, {INCUMBENT: {counter: (stale + 1,)}})
    assert rule_of(drill_candidate(inside, counter)) == "drill_budget"

    assert drill_candidate(champion_chain(), counter) is None


def test_drill_budget_is_a_venue_cap_summed_across_lineages() -> None:
    chain = champion_chain()
    exhaust(chain, {OTHER: {"drill_demotes": (DRILL_BUDGET_NOW - DAY_NS,)}})

    assert rule_of(drill_candidate(chain, "drill_demotes")) == "drill_budget"


def test_a_second_drill_row_in_one_batch_is_refused() -> None:
    chain = champion_chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=OTHER)  # a second family to halt
    prior = run(chain, LAUNCH)
    rows = [
        chain.add(Kind.DEMOTE, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, **DRILL_CAUSE),
        chain.add(Kind.HALT, State.HALTED, family=OTHER, frm=State.CHAMPION, **DRILL_CAUSE),
    ]
    assert tm.first_refusal(prior, rows[:1], manifests=no_facts) is None
    both = tm.first_refusal(prior, rows, manifests=no_facts)
    assert both is None  # a DEMOTE and a HALT are different counters

    twice = [
        rows[0],
        chain.add(Kind.DEMOTE, State.HALTED, family=OTHER, frm=State.CHAMPION, **DRILL_CAUSE),
    ]
    refused = tm.first_refusal(prior, twice, manifests=no_facts)
    assert refused is not None and (refused.rule.value, refused.row_index) == ("drill_budget", 1)


def test_a_pending_drill_promote_counts_against_the_budget() -> None:
    chain = champion_chain()
    chain.add(
        Kind.DRILL_ADMIT, State.CHALLENGER, family=CHILD, frm=State.SHADOW, artefact_sha256=INC_ART
    )
    chain.drill_pair(DAY)

    refused = probe(
        chain, at(DAY, "16:00"), Kind.DRILL_PROMOTE, State.CHAMPION, family=CHILD,
        frm=State.CHALLENGER, artefact_sha256=INC_ART, effective_launch_date=NEXT_DAY,
    )  # fmt: skip

    assert rule_of(refused) == "drill_budget"


def test_drill_budget_separate() -> None:
    """Production budgets never block a drill row, and the drill budget never blocks production."""

    def production_spent() -> DrillChain:
        chain = champion_chain()
        exhaust(
            chain, {INCUMBENT: {"model_resumes": (RESUME_TS - HOUR_NS, RESUME_TS - 2 * HOUR_NS)}},
            infra_resumes=(RESUME_TS - HOUR_NS, RESUME_TS - 2 * HOUR_NS, RESUME_TS - 3 * HOUR_NS),
        )  # fmt: skip
        return chain

    for counter in sorted(DRILL_ROWS):  # a probe appends its row, so each counter gets a chain
        assert drill_candidate(production_spent(), counter) is None

    drill = model_halted()
    exhaust(
        drill,
        {
            INCUMBENT: {
                "drill_resumes": (RESUME_TS - HOUR_NS,),
                "drill_admits": (RESUME_TS - HOUR_NS,),
            }
        },
    )
    assert resume(drill) is None


# --- ROLLBACK drill column and the infeasible-α rule (A7b obligations) --------------------------


def open_episode_chain() -> DrillChain:
    chain = champion_chain()
    chain.add(
        Kind.DRILL_ADMIT, State.CHALLENGER, family=CHILD, frm=State.SHADOW, artefact_sha256=INC_ART
    )
    head, _tail = chain.drill_pair(DAY)
    chain.activate(head, ts=at(DAY, "16:45"))
    return chain


def superseded_chain() -> DrillChain:
    """INCUMBENT superseded by CHILD in an ordinary (non-drill) pair that has taken effect."""
    chain = champion_chain()
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)
    head, _tail = chain.promote_pair(day=DAY)
    chain.activate(head, ts=at(DAY, "16:45"))
    return chain


def rollback(chain: Chain, now: int, *, drill: bool, family: str = INCUMBENT) -> Refusal | None:
    return probe(
        chain, now, Kind.ROLLBACK, State.CHAMPION, family=family, frm=State.CHALLENGER,
        effective_launch_date=NEXT_DAY, drill=drill,
    )  # fmt: skip


def test_rollback_drill_column_must_match_an_open_episode() -> None:
    during = at(DAY, "20:00")
    assert rollback(open_episode_chain(), during, drill=True) is None
    assert rule_of(rollback(open_episode_chain(), during, drill=False)) == "rollback_drill_column"

    assert rollback(superseded_chain(), during, drill=False) is None
    assert rule_of(rollback(superseded_chain(), during, drill=True)) == "rollback_drill_column"


def test_rollback_drill_column_after_the_episode_closed() -> None:
    chain = failed_close_chain(halt=lambda _c: None)
    after = at(NEXT_DAY, "18:00")  # the closing ROLLBACK took effect at 16:50
    refused = rollback(chain, after, drill=True, family=CHILD)  # the child the close superseded
    assert rule_of(refused) == "rollback_drill_column"


def test_a_drill_rollback_is_capped_by_the_drill_budget() -> None:
    chain = open_episode_chain()
    exhaust(chain, {INCUMBENT: {"drill_rollbacks": (at(DAY, "10:00"),)}})

    assert rule_of(rollback(chain, at(DAY, "20:00"), drill=True)) == "drill_budget"


@pytest.mark.parametrize(
    ("feasible", "alpha", "rule"),
    [
        (False, Decimal("0.01"), "infeasible_alpha"),
        (False, Decimal(0), None),
        (False, None, None),
        (True, Decimal("0.01"), None),
    ],
    ids=["infeasible_with_alpha", "infeasible_zero", "infeasible_none", "feasible_with_alpha"],
)
def test_infeasible_nomination_refuses_nonzero_alpha(
    feasible: bool, alpha: Decimal | None, rule: str | None
) -> None:
    chain = champion_chain()

    refused = probe(
        chain, LAUNCH, Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW,
        k_life=1, alpha_k=alpha, n_min_eff=403, n_cap=89 if not feasible else 480,
        nomination_feasible=feasible,
    )  # fmt: skip

    assert rule_of(refused) == rule


# --- E-19a: the launch-window cause goes through SWAP_CANCEL ------------------------------------

LATE: Final = at(DAY, "18:00")


def window_demote(kind: Kind, ts: int, *, family: str = CHILD) -> Refusal | None:
    chain, _head, _tail = activated_pair()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=OTHER)  # an unrelated sender
    return probe(
        chain, LATE, kind, State.HALTED, family=family, frm=State.CHAMPION, ts=ts,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip


@pytest.mark.parametrize("kind", [Kind.DEMOTE, Kind.HALT])
def test_demote_of_incoming_in_launch_window_refused(kind: Kind) -> None:
    refused = window_demote(kind, at(DAY, "16:55"))

    assert rule_of(refused) == "launch_window_cause"
    assert refused is not None and refused.reason is RefusalReason.ENGINE_INCONSISTENCY


def test_launch_window_is_half_open_from_launch_to_window_end() -> None:
    assert rule_of(window_demote(Kind.DEMOTE, LAUNCH)) == "launch_window_cause"
    assert rule_of(window_demote(Kind.DEMOTE, at(DAY, "17:00") - 1)) == "launch_window_cause"
    assert window_demote(Kind.DEMOTE, at(DAY, "17:00")) is None  # the window has closed


def test_launch_window_rule_binds_only_the_incoming_family_of_an_activated_pair() -> None:
    assert window_demote(Kind.DEMOTE, at(DAY, "16:55"), family=OTHER) is None

    chain, head, _tail = activated_pair()
    cancel(chain, head, ts=at(DAY, "16:46"))  # voided before LAUNCH: no pair took effect
    voided = probe(
        chain, LATE, Kind.DEMOTE, State.HALTED, family=CHILD, frm=State.CHALLENGER,
        ts=at(DAY, "16:55"), halt_cause_class=CauseClass.RECOVERABLE_MODEL,
        cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    assert voided is None


def test_the_swap_cancel_alternative_is_accepted_in_the_launch_window() -> None:
    chain, head, _tail = activated_pair()
    prior = run(chain, LATE)
    row = cancel(chain, head, ts=at(DAY, "16:55"), cause=CauseCode.PAIR_CAUSE_INCOMING)

    assert tm.first_refusal(prior, [row], manifests=no_facts) is None
    assert (
        tm.validate(
            prior, [row], mode=WriterMode.INTRADAY, now_ns=LATE, stage=STAGE, manifests=no_facts
        )
        is None
    )


# --- Y8: a demoted family is promotable only after a later FORWARD_SHADOW PASS ------------------


def forward_shadow(
    outcome: VerdictOutcome = VerdictOutcome.PASS,
    *,
    produced_at_ns: int,
    family: str = CHILD,
    kind: VerdictKind = VerdictKind.FORWARD_SHADOW,
) -> Verdict:
    return Verdict(
        kind=kind, subject_family_id=family, outcome=outcome, detector="forward_shadow",
        declared_action_class=ActionClass.NONE, produced_at_ns=produced_at_ns,
        valid_until_ns=produced_at_ns + HOUR_NS, producer_code_sha="d" * 64,
        assumptions=(Assumption.NO_POLICY_RULING,),
    )  # fmt: skip


CAUSE_NS: Final = at(DAY, "16:46")


def demoted_child_chain() -> Chain:
    """CHILD CHALLENGER after a SWAP_CANCEL pair_cause_incoming at 16:46Z; it never was champion."""
    chain, head, _tail = activated_pair()
    cancel(chain, head, ts=CAUSE_NS, cause=CauseCode.PAIR_CAUSE_INCOMING)
    return chain


def repromote(verdicts: list[Verdict], *, cited: bool = True) -> Refusal | None:
    chain = demoted_child_chain()
    return probe(
        chain, LATE, Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=NEXT_DAY, manifest_sha256=CHILD_MAN, manifests=facts_for_child,
        cause_verdict_ids=tuple(v.verdict_id for v in verdicts) if cited else (),
        verdicts={v.verdict_id: v for v in verdicts},
    )  # fmt: skip


def test_demoted_for_cause_family_is_not_promotable_without_a_forward_shadow_pass() -> None:
    assert rule_of(repromote([])) == "demoted_not_cleared"
    after = forward_shadow(produced_at_ns=CAUSE_NS + 1)
    assert repromote([after]) is None


@pytest.mark.parametrize(
    "verdict",
    [
        forward_shadow(produced_at_ns=CAUSE_NS),
        forward_shadow(produced_at_ns=CAUSE_NS - SEC),
        forward_shadow(VerdictOutcome.FAIL, produced_at_ns=CAUSE_NS + SEC),
        forward_shadow(produced_at_ns=CAUSE_NS + SEC, family=INCUMBENT),
        forward_shadow(produced_at_ns=CAUSE_NS + SEC, kind=VerdictKind.DRIFT),
    ],
    ids=["same_instant", "before_cause", "fail", "other_family", "other_kind"],
)
def test_a_verdict_that_does_not_clear_the_cause_refuses(verdict: Verdict) -> None:
    assert rule_of(repromote([verdict])) == "demoted_not_cleared"


def test_a_cited_verdict_the_caller_did_not_resolve_refuses() -> None:
    cleared = forward_shadow(produced_at_ns=CAUSE_NS + SEC)
    chain = demoted_child_chain()
    refused = probe(
        chain, LATE, Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=NEXT_DAY, manifest_sha256=CHILD_MAN, manifests=facts_for_child,
        cause_verdict_ids=(cleared.verdict_id,),
    )  # fmt: skip
    assert rule_of(refused) == "demoted_not_cleared"


def test_the_clear_also_gates_a_rollback_target() -> None:
    def rollback_child(verdicts: list[Verdict]) -> Refusal | None:
        return probe(
            demoted_child_chain(), LATE, Kind.ROLLBACK, State.CHAMPION, family=CHILD,
            frm=State.CHALLENGER, effective_launch_date=NEXT_DAY,
            cause_verdict_ids=tuple(v.verdict_id for v in verdicts),
            verdicts={v.verdict_id: v for v in verdicts},
        )  # fmt: skip

    assert rule_of(rollback_child([])) == "demoted_not_cleared"
    assert rollback_child([forward_shadow(produced_at_ns=CAUSE_NS + SEC)]) is None


# --- restrictive writes are always permitted ----------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "frm", "to", "extra"),
    [
        (
            Kind.DEMOTE,
            State.CHAMPION,
            State.HALTED,
            {"halt_cause_class": CauseClass.RECOVERABLE_MODEL},
        ),
        (Kind.HALT, State.CHAMPION, State.HALTED, {"halt_cause_class": CauseClass.TERMINAL}),
        (
            Kind.SWAP_CANCEL,
            State.CHALLENGER,
            State.CHALLENGER,
            {"voids_transition_ids": ("e" * 64,)},
        ),
        (
            Kind.TARGET_INELIGIBLE,
            State.CHALLENGER,
            State.CHALLENGER,
            {"cause_code": CauseCode.TARGET_INTEGRITY},
        ),
        (
            Kind.ATTEST,
            State.CHAMPION,
            State.CHAMPION,
            {"attest_valid_until_ns": RESUME_TS + HOUR_NS},
        ),
    ],
    ids=["demote", "halt", "swap_cancel", "target_ineligible", "attest"],
)
def test_restrictive_rows_are_not_refused_by_budgets_or_freezes(
    kind: Kind, frm: State, to: State, extra: dict[str, Any]
) -> None:
    chain = champion_chain()
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)
    family = CHILD if frm is State.CHALLENGER else INCUMBENT  # each in the state its row names
    freeze_venue(chain)
    spent = RESUME_TS - HOUR_NS
    exhaust(
        chain,
        {
            INCUMBENT: {
                "model_resumes": (spent, spent),
                "drill_demotes": (spent,),
                "drill_halts": (spent,),
            }
        },
        infra_resumes=(spent, spent, spent),
    )

    assert probe(chain, RESUME_TS, kind, to, family=family, frm=frm, **extra) is None


def test_validate_does_not_mutate_its_inputs() -> None:
    chain = model_halted()
    prior: FoldResult = run(chain, RESUME_TS)
    row = chain.add(
        Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED, ts=RESUME_TS,
        cause_verdict_ids=CITED,
    )  # fmt: skip
    rows = [row]
    first = tm.first_refusal(prior, rows, manifests=no_facts)
    second = tm.first_refusal(prior, rows, manifests=no_facts)

    assert first == second is None
    assert rows == [row]
