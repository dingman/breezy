"""ARCH-0 seam 8b review (A8b-R1, A8b-R2; E-22): role-based citations and the model class.

A ROLLBACK or ROOT_ADMIT cites by role, not by "a PASS of the row's family": the outgoing family
F's halting causes (FAIL verdicts whose subject is F and whose artefact is F's bound sha) and the
DRIFT ``fee_schedule`` PASS for the champion. Each verdict resolves in its subject's directory,
searched only in the row's family, the batch partner and the prior senders. An artefact's model
class is found by probing ``pins.MODEL_CLASS_COMPONENTS`` and requiring exactly one match.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.lineage import model_class_of
from breezy.persistence.autonomy.replay import (
    ArtefactFailure,
    CauseFailure,
    ReplayArtefactMismatch,
    ReplayCauseUnresolved,
    ReplayInvalid,
    ReplayOk,
)
from breezy.persistence.autonomy.schemas import CauseClass, CauseCode, Kind, State, TransitionRow
from breezy.persistence.autonomy.verdict import (
    Verdict,
    VerdictKind,
    VerdictOutcome,
    write_verdict,
)
from tests.unit.test_registry_fold import CHILD, DAY, INCUMBENT, Chain, at
from tests.unit.test_registry_replay import (
    ART_SHA,
    KIND,
    OFFLINE,
    World,
    _verdict,
    nominate,
    promote_pair,
    start,
)

THIRD_DAY: Final = "2026-10-12"
NEXT_DAY: Final = "2026-10-11"


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def fail_of(family: str, *, artefact: str | None = ART_SHA, minute: int = 0) -> Verdict:
    return _verdict(
        VerdictKind.LIVE_SEQUENTIAL,
        outcome=VerdictOutcome.FAIL,
        family=family,
        artefact=artefact,
        produced=at(DAY, "17:10") + minute * 60 * 10**9,
    )


def fee_of(
    family: str, *, outcome: VerdictOutcome = VerdictOutcome.PASS, detector: str = "fee_schedule"
) -> Verdict:
    base = _verdict(
        VerdictKind.DRIFT,
        outcome=outcome,
        family=family,
        artefact=None,
        produced=at(THIRD_DAY, "09:00"),
    )
    return dataclasses.replace(base, detector=detector)


def put(world: World, *verdicts: Verdict) -> tuple[str, ...]:
    for verdict in verdicts:
        write_verdict(world.paths, verdict)
    return tuple(v.verdict_id for v in verdicts)


def halted_child(world: World, *, code: CauseCode = CauseCode.VERDICT_FAIL) -> Chain:
    """CHILD is CHAMPION from DAY's LAUNCH (INCUMBENT is a rollback-eligible CHALLENGER), HALTED."""
    chain = start(world)
    nominate(chain)
    promote_pair(chain, world=world)
    halt: dict[str, Any] = {"halt_cause_class": CauseClass.RECOVERABLE_MODEL, "cause_code": code}
    if code is CauseCode.ROLLBACK_FAILED:
        halt = {
            "halt_cause_class": CauseClass.ROLLBACK_FAILED,
            "cause_code": code,
            "trigger_cause_class": CauseClass.RECOVERABLE_MODEL,
        }
    chain.add(
        Kind.HALT, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=at(DAY, "18:00"), **halt
    )
    return chain


def rollback(chain: Chain, world: World, cited: tuple[str, ...]) -> TransitionRow:
    head = chain.add(
        Kind.ROLLBACK, State.CHAMPION, family=INCUMBENT, frm=State.CHALLENGER,
        ts=at(THIRD_DAY, "16:45"), effective_launch_date=THIRD_DAY,
        lineage_root_family_id=INCUMBENT,
        manifest_sha256=world.root_sha, artefact_sha256=ART_SHA, cause_verdict_ids=cited,
    )  # fmt: skip
    chain.add(
        Kind.DISPLACED, State.CHALLENGER, family=CHILD, frm=State.HALTED,
        ts=at(THIRD_DAY, "16:45"), paired_transition_id=head.transition_id,
        effective_launch_date=THIRD_DAY,
    )  # fmt: skip
    chain.activate(head, ts=at(THIRD_DAY, "16:46"))
    return head


# --- ROLLBACK (E-22 a) ----------------------------------------------------------------------------


def test_rollback_cites_the_halting_cause_and_the_fee_pass_by_role(world: World) -> None:
    chain = halted_child(world)
    cited = put(world, fail_of(CHILD), fee_of(CHILD))
    rollback(chain, world, cited)
    assert isinstance(world.replay(chain), ReplayOk)


def test_a_rollback_whose_f_halt_carries_no_verdict_may_cite_nothing(world: World) -> None:
    quiet = halted_child(world, code=CauseCode.ROLLBACK_FAILED)
    rollback(quiet, world, ())
    assert isinstance(world.replay(quiet), ReplayOk)
    loud = halted_child(world)  # a verdict-bearing halt: an empty list is not allowed
    rollback(loud, world, ())
    result = world.replay(loud)
    assert isinstance(result, ReplayCauseUnresolved) and result.why is CauseFailure.NOT_CITED


def test_a_rollback_citing_a_fail_of_the_wrong_subject_is_refused(world: World) -> None:
    chain = halted_child(world)
    wrong = fail_of(INCUMBENT)  # the target's FAIL is no cause of F's halt
    cited = put(world, wrong, fee_of(CHILD))
    rollback(chain, world, cited)
    result = world.replay(chain)
    assert isinstance(result, ReplayCauseUnresolved)
    assert (result.why, result.verdict_id) == (CauseFailure.ROLE_MISMATCH, wrong.verdict_id)


@pytest.mark.parametrize(
    "fee",
    [
        fee_of(CHILD, outcome=VerdictOutcome.FAIL),
        fee_of(CHILD, detector="not_the_fee"),
    ],
    ids=["fee_fail", "other_detector"],
)
def test_a_rollback_needs_the_fee_pass(world: World, fee: Verdict) -> None:
    chain = halted_child(world)
    rollback(chain, world, put(world, fail_of(CHILD), fee))
    result = world.replay(chain)
    assert isinstance(result, ReplayCauseUnresolved)
    assert result.why in (CauseFailure.ROLE_MISMATCH, CauseFailure.NOT_PASS)


def test_a_rollback_with_a_cause_but_no_fee_verdict_is_refused(world: World) -> None:
    chain = halted_child(world)
    rollback(chain, world, put(world, fail_of(CHILD)))
    result = world.replay(chain)
    assert isinstance(result, ReplayCauseUnresolved) and result.why is CauseFailure.KIND_MISMATCH


def test_a_rollback_verdict_outside_the_three_places_is_not_found(world: World) -> None:
    chain = halted_child(world)
    stray = _verdict(
        VerdictKind.DRIFT, family="pm_us_crh_v4", artefact=None, produced=at(THIRD_DAY, "09:01")
    )
    stray = dataclasses.replace(stray, detector="fee_schedule")
    rollback(chain, world, put(world, fail_of(CHILD), stray))
    result = world.replay(chain)
    assert isinstance(result, ReplayCauseUnresolved)
    assert (result.why, result.verdict_id) == (CauseFailure.NOT_FOUND, stray.verdict_id)


# --- ROOT_ADMIT (E-22 b) --------------------------------------------------------------------------


def root_admit(world: World, cited: tuple[str, ...]) -> Chain:
    chain = Chain()
    chain.add(
        Kind.ROOT_ADMIT, State.CHAMPION, family=INCUMBENT, ts=at("2026-10-09", "16:45"),
        effective_launch_date=DAY, manifest_sha256=world.root_sha, artefact_sha256=ART_SHA,
        cause_verdict_ids=cited,
    )  # fmt: skip
    return chain


def test_a_root_admit_carries_the_fee_pass(world: World) -> None:
    ok = root_admit(world, put(world, fee_of(INCUMBENT)))
    assert isinstance(world.replay(ok), ReplayOk)
    bad = root_admit(world, put(world, fee_of(INCUMBENT, detector="other")))
    result = world.replay(bad)
    assert isinstance(result, ReplayCauseUnresolved)
    assert result.why in (CauseFailure.ROLE_MISMATCH, CauseFailure.KIND_MISMATCH)
    none = world.replay(root_admit(world, ()))
    assert isinstance(none, ReplayCauseUnresolved) and none.why is CauseFailure.NOT_CITED


# --- drill rows and the E-5 restore ---------------------------------------------------------------


def drill_episode(world: World, *, close: bool = True) -> Chain:
    """A drill child is promoted over INCUMBENT at DAY and the drill closes at NEXT_DAY."""
    chain = start(world)
    chain.add(
        Kind.DRILL_ADMIT, State.CHALLENGER, family=CHILD, frm=State.SHADOW,
        manifest_sha256=world.child_sha, artefact_sha256=ART_SHA,
        lineage_root_family_id=INCUMBENT, drill=True,
    )  # fmt: skip
    head = chain.add(
        Kind.DRILL_PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=DAY, manifest_sha256=world.child_sha, artefact_sha256=ART_SHA,
        drill=True, lineage_root_family_id=INCUMBENT,
    )  # fmt: skip
    chain.add(
        Kind.SUPERSEDE, State.CHALLENGER, family=INCUMBENT, frm=State.CHAMPION,
        paired_transition_id=head.transition_id, effective_launch_date=DAY,
    )  # fmt: skip
    chain.activate(head, ts=at(DAY, "16:45"))
    if not close:
        return chain
    closing = chain.add(
        Kind.ROLLBACK, State.CHAMPION, family=INCUMBENT, frm=State.CHALLENGER,
        ts=at(NEXT_DAY, "16:40"), effective_launch_date=NEXT_DAY, drill=True,
        lineage_root_family_id=INCUMBENT, manifest_sha256=world.root_sha, artefact_sha256=ART_SHA,
    )  # fmt: skip
    chain.add(
        Kind.SUPERSEDE, State.CHALLENGER, family=CHILD, frm=State.CHAMPION,
        ts=at(NEXT_DAY, "16:40"), paired_transition_id=closing.transition_id,
        effective_launch_date=NEXT_DAY,
    )  # fmt: skip
    chain.activate(closing, ts=at(NEXT_DAY, "16:46"), family=INCUMBENT)
    return chain


def test_the_drill_promote_and_the_closing_rollback_to_fq_v1_cite_nothing(world: World) -> None:
    """The live drill's closing ROLLBACK: F (the drill child) still folds CHAMPION, no halt."""
    result = world.replay(drill_episode(world))
    assert isinstance(result, ReplayOk), result


def test_the_e5_restore_after_a_failed_close_cites_nothing(world: World) -> None:
    chain = drill_episode(world)
    chain.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, ts=at(NEXT_DAY, "17:05"),
        halt_cause_class=CauseClass.ROLLBACK_FAILED, cause_code=CauseCode.ROLLBACK_FAILED,
        trigger_cause_class=CauseClass.DRILL,
    )  # fmt: skip
    chain.add(
        Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED,
        ts=at("2026-10-13", "16:45"), cause_code=CauseCode.DRILL_CLOSE_RESTORE,
        manifest_sha256=world.root_sha, artefact_sha256=ART_SHA,
    )  # fmt: skip
    result = world.replay(chain)
    assert isinstance(result, ReplayOk), result


# --- A8b-R2: the model class ----------------------------------------------------------------------


RECAL: Final = b'{"recalibration":"affine"}\n'
RECAL_SHA: Final = hashlib.sha256(RECAL).hexdigest()


def recal_chain(world: World) -> Chain:
    """A MINT whose artefact is a ``rung_recalibration`` refit, not a ``density_table``."""
    chain = Chain()
    chain.add(
        Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT,
        manifest_sha256=world.root_sha, artefact_sha256=ART_SHA,
    )  # fmt: skip
    chain.add(
        Kind.MINT, State.SHADOW, family=CHILD, manifest_sha256=world.child_sha,
        artefact_sha256=RECAL_SHA,
    )  # fmt: skip
    return chain


def put_recal(world: World, component: str = "rung_recalibration") -> Path:
    target = world.paths.artefact_file(model_class_of(KIND, component), RECAL_SHA)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(RECAL)
    target.chmod(0o444)
    return target


def test_the_model_class_components_are_a_reviewed_literal() -> None:
    assert pins.MODEL_CLASS_COMPONENTS == ("density_table", "rung_recalibration")
    assert pins.ROOT_ARTEFACT_COMPONENT in pins.MODEL_CLASS_COMPONENTS


def test_a_rung_recalibration_child_resolves_its_artefact_by_probing(world: World) -> None:
    chain = recal_chain(world)
    absent = world.replay(chain)
    assert isinstance(absent, ReplayArtefactMismatch)
    assert (absent.venue_seq, absent.why) == (2, ArtefactFailure.ARTEFACT_UNREADABLE)
    put_recal(world)
    assert isinstance(world.replay(chain), ReplayOk)


def test_the_same_artefact_under_two_model_classes_is_ambiguous(world: World) -> None:
    chain = recal_chain(world)
    put_recal(world)
    put_recal(world, "density_table")
    result = world.replay(chain)
    assert isinstance(result, ReplayArtefactMismatch)
    assert result.why is ArtefactFailure.ARTEFACT_UNREADABLE


def test_a_component_outside_the_pinned_set_is_never_probed(world: World) -> None:
    put_recal(world, "not_a_component")
    result = world.replay(recal_chain(world))
    assert isinstance(result, ReplayArtefactMismatch)
    assert result.why is ArtefactFailure.ARTEFACT_UNREADABLE


def test_a_tampered_unique_artefact_is_a_sha_mismatch(world: World) -> None:
    path = put_recal(world)
    path.chmod(0o644)
    path.write_bytes(RECAL + b" ")
    result = world.replay(recal_chain(world))
    assert isinstance(result, ReplayArtefactMismatch)
    assert result.why is ArtefactFailure.ARTEFACT_SHA_MISMATCH


def test_the_shared_world_still_replays_after_these_rules(world: World) -> None:
    chain = start(world)
    nominate(chain, (OFFLINE.verdict_id,))
    assert isinstance(world.replay(chain), ReplayOk)
    assert not isinstance(world.replay(chain), ReplayInvalid)
