"""ARCH-0 seam 8b: ``replay.replay_full`` re-runs ``validate`` over the whole chain (AC 17 step 6).

A chain is built with the 7x fixture builders, sealed (hash-linked) and replayed against a real
on-disk world: the committed root manifest in a tmp repo, a registry copy of the child manifest,
the content-addressed artefact and the verdict files. Each refusal test sits beside a control that
passes, so a refusal cannot come from a broken world. The private ``_replay_full`` is never named
here (the 6c seam scan bans it outside ``replay``); the stage is the canonical one.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import shutil
from collections.abc import Callable
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any, Final

import pytest

import breezy.persistence.autonomy.replay as replay_mod
from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.chain import (
    VerifiedVenueChain,
    genesis,
    transition_hash,
    verify_venue_chain,
)
from breezy.persistence.autonomy.family_bytes import read_manifest_facts
from breezy.persistence.autonomy.fold import FoldInvalid, fold
from breezy.persistence.autonomy.lineage import root_model_class
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths
from breezy.persistence.autonomy.replay import (
    ArtefactFailure,
    CauseFailure,
    ReplayArtefactMismatch,
    ReplayCauseUnresolved,
    ReplayInvalid,
    ReplayOk,
    replay_full,
)
from breezy.persistence.autonomy.schemas import (
    CauseClass,
    CauseCode,
    DecidedBy,
    FoldInvalidReason,
    Kind,
    RefusalReason,
    State,
    TransitionRow,
)
from breezy.persistence.autonomy.verdict import (
    ActionClass,
    Assumption,
    Verdict,
    VerdictKind,
    VerdictOutcome,
    write_verdict,
)
from tests.support.entry_points import REPO_ROOT, SRC_DIR
from tests.unit.test_registry_fold import CHILD, DAY, INCUMBENT, VENUE, Chain, at
from tests.unit.test_registry_fold_tallies import carried, reset

KIND: Final = "forecast_quantile_ladder"
ROOT_SOURCE: Final = REPO_ROOT / "deploy" / "families" / f"{INCUMBENT}.json"
#: The root's real density artefact: the bytes at its manifest's ``density_artefact_path`` (E-24:
#: a family's density pin is its bound artefact, so the pinned sha ``9c0b...`` is ``ART_SHA``).
ROOT_ARTEFACT_PATH: Final = (
    "deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json"
)
ARTEFACT: Final = (REPO_ROOT / ROOT_ARTEFACT_PATH).read_bytes()
ART_SHA: Final = hashlib.sha256(ARTEFACT).hexdigest()
#: A child keeps a synthetic artefact; its manifest pins it (path and sha) as its own.
CHILD_ARTEFACT: Final = b'{"density":"child"}\n'
CHILD_ART_SHA: Final = hashlib.sha256(CHILD_ARTEFACT).hexdigest()
CHILD_ARTEFACT_PATH: Final = "deploy/families/artefacts/child_density.json"
HOUR_NS: Final = 3_600 * 10**9
REPLAY_SOURCE: Final = SRC_DIR / "breezy" / "persistence" / "autonomy" / "replay.py"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _verdict(
    kind: VerdictKind,
    *,
    outcome: VerdictOutcome = VerdictOutcome.PASS,
    family: str = CHILD,
    artefact: str | None = CHILD_ART_SHA,
    produced: int = at("2026-10-09", "11:00"),
) -> Verdict:
    return Verdict(
        kind=kind, subject_family_id=family, outcome=outcome, detector="replay_world",
        declared_action_class=ActionClass.NONE, produced_at_ns=produced,
        valid_until_ns=produced + 20 * HOUR_NS, producer_code_sha="d" * 64,
        subject_artefact_sha256=artefact, assumptions=(Assumption.NO_POLICY_RULING,),
    )  # fmt: skip


OFFLINE: Final = _verdict(VerdictKind.OFFLINE_CHALLENGER)
FORWARD: Final = _verdict(VerdictKind.FORWARD_SHADOW)


class World:
    """A repo, a registry root and the files a replay reads; every file is a real file."""

    def __init__(self, tmp_path: Path) -> None:
        self.repo = tmp_path / "repo"
        families = self.repo / "deploy" / "families"
        families.mkdir(parents=True)
        shutil.copy(ROOT_SOURCE, families / ROOT_SOURCE.name)
        self.root_raw = ROOT_SOURCE.read_bytes()
        self.root_sha = _sha(self.root_raw)
        self.data = tmp_path / "data"
        self.data.mkdir(mode=0o700)
        self.paths = AutonomyPaths(self.data)
        child = self.root_raw.replace(INCUMBENT.encode(), CHILD.encode())
        child = child.replace(b'"2026-10-02"', b'"2026-10-20"')
        child = child.replace(ART_SHA.encode(), CHILD_ART_SHA.encode())
        self.child_raw = child.replace(ROOT_ARTEFACT_PATH.encode(), CHILD_ARTEFACT_PATH.encode())
        self.child_sha = _sha(self.child_raw)
        self.put_child_manifest()
        self.put_artefact(ARTEFACT)
        self.put_artefact(CHILD_ARTEFACT, sha=CHILD_ART_SHA)
        for verdict in (OFFLINE, FORWARD):
            write_verdict(self.paths, verdict)

    def put_child_manifest(self) -> None:
        directory = self.data / "registry" / "families"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{CHILD}.json"
        target.write_bytes(self.child_raw)
        target.chmod(0o444)

    def pin_child_to_root_artefact(self) -> None:
        """A drill child shares its incumbent's artefact (``validate``), so its manifest pins it."""
        raw = self.child_raw.replace(CHILD_ART_SHA.encode(), ART_SHA.encode())
        raw = raw.replace(CHILD_ARTEFACT_PATH.encode(), ROOT_ARTEFACT_PATH.encode())
        target = self.data / "registry" / "families" / f"{CHILD}.json"
        target.chmod(0o644)
        self.child_raw, self.child_sha = raw, _sha(raw)
        self.put_child_manifest()

    def put_artefact(self, raw: bytes, *, sha: str = ART_SHA) -> Path:
        target = self.paths.artefact_file(root_model_class(KIND), sha)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.chmod(0o644)
        target.write_bytes(raw)
        target.chmod(0o444)
        return target

    def replay(self, chain: Chain) -> Any:
        return replay_full(seal(chain), paths=self.paths, repo_root=self.repo)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def seal(chain: Chain) -> VerifiedVenueChain:
    """Hash-link the builder's rows and verify them as the venue's whole chain."""
    previous = genesis(VENUE)
    sealed: list[TransitionRow] = []
    for row in chain.rows:
        linked = dataclasses.replace(row, prev_transition_hash=previous)
        previous = transition_hash(linked, previous)
        sealed.append(dataclasses.replace(linked, transition_hash=previous))
    return verify_venue_chain(sealed, VENUE)


def start(world: World, *, art: str = ART_SHA, child_art: str = CHILD_ART_SHA) -> Chain:
    """The root CHAMPION and a MINTed child, each bound to its own artefact in the store."""
    chain = Chain()
    chain.add(
        Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT,
        manifest_sha256=world.root_sha, artefact_sha256=art,
    )  # fmt: skip
    chain.add(
        Kind.MINT, State.SHADOW, family=CHILD, manifest_sha256=world.child_sha,
        artefact_sha256=child_art,
    )  # fmt: skip
    return chain


def nominate(chain: Chain, cited: tuple[str, ...] | None = None) -> TransitionRow:
    return chain.add(
        Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW,
        lineage_root_family_id=INCUMBENT, k_life=1, alpha_k=Decimal("0.01"), n_min_eff=403,
        n_cap=480, nomination_feasible=True,
        cause_verdict_ids=(OFFLINE.verdict_id,) if cited is None else cited,
    )  # fmt: skip


def promote_pair(
    chain: Chain, cited: tuple[str, ...] | None = None, *, world: World
) -> TransitionRow:
    """The CHALLENGER to CHAMPION head with its SUPERSEDE partner and the ACTIVATE."""
    head = chain.add(
        Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=DAY, manifest_sha256=world.child_sha,
        cause_verdict_ids=(
            (FORWARD.verdict_id, OFFLINE.verdict_id) if cited is None else cited
        ),
    )  # fmt: skip
    chain.add(
        Kind.SUPERSEDE, State.CHALLENGER, family=INCUMBENT, frm=State.CHAMPION,
        paired_transition_id=head.transition_id, effective_launch_date=DAY,
    )  # fmt: skip
    chain.activate(head, ts=at(DAY, "16:45"))
    return head


def full_chain(world: World) -> Chain:
    chain = start(world)
    nominate(chain)
    promote_pair(chain, world=world)
    return chain


# --- the walk -----------------------------------------------------------------------------------


def test_resolver_replays_validate_over_full_fold(world: World) -> None:
    chain = full_chain(world)
    result = world.replay(chain)
    assert isinstance(result, ReplayOk)
    assert result.head_venue_seq == len(chain.rows) == 6
    assert result.chain_head == seal(chain).head_hash


def test_replay_is_ok_for_the_root_alone_and_for_an_empty_chain(world: World) -> None:
    root_only = Chain()
    root_only.add(
        Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT,
        manifest_sha256=world.root_sha, artefact_sha256=ART_SHA,
    )  # fmt: skip
    ok = world.replay(root_only)
    assert isinstance(ok, ReplayOk) and ok.head_venue_seq == 1
    empty = world.replay(Chain())
    assert isinstance(empty, ReplayOk) and empty.head_venue_seq == 0
    assert empty.chain_head == genesis(VENUE)


def test_a_row_validate_refuses_is_replay_invalid_at_its_venue_seq(world: World) -> None:
    chain = start(world)
    bad = chain.add(Kind.HALT, State.HALTED, family=CHILD, frm=State.CHAMPION)  # CHILD is SHADOW
    nominate(chain)  # a later row cannot hide the first refusal
    result = world.replay(chain)
    assert isinstance(result, ReplayInvalid)
    assert result.reason is RefusalReason.REPLAY_INVALID
    assert (result.venue_seq, result.rule) == (bad.venue_seq, "from_state_mismatch")


def test_a_pair_is_judged_as_one_batch_not_row_by_row(world: World) -> None:
    """A lone →CHAMPION head leaves two senders at LAUNCH; its SUPERSEDE partner makes it one."""
    chain = full_chain(world)
    assert isinstance(world.replay(chain), ReplayOk)
    lone = start(world)
    nominate(lone)
    lone.add(
        Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=DAY, manifest_sha256=world.child_sha,
        cause_verdict_ids=(FORWARD.verdict_id, OFFLINE.verdict_id),
    )  # fmt: skip
    result = world.replay(lone)
    assert isinstance(result, ReplayInvalid) and result.rule == "single_sender"


def test_a_child_manifest_is_read_from_the_registry_copy_and_refused_without_it(
    world: World,
) -> None:
    assert isinstance(world.replay(full_chain(world)), ReplayOk)  # control: the copy serves
    copy = world.data / "registry" / "families" / f"{CHILD}.json"
    copy.chmod(0o644)
    copy.unlink()
    result = world.replay(full_chain(world))
    assert isinstance(result, ReplayArtefactMismatch)
    assert (result.venue_seq, result.why) == (2, ArtefactFailure.MANIFEST_UNREADABLE)


def test_replay_maps_fold_invalid_to_replay_invalid(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A prefix the fold rejects is ``replay_invalid``, at the first row of the previous batch.

    Every natural ``FoldInvalid`` is caught by ``validate`` first, so the fold is made to fail for
    the three rows before the pair batch to pin the mapping (A8b-R5 L1).
    """
    chain = full_chain(world)
    real = fold
    refusal = FoldInvalid(FoldInvalidReason.HEAD_MISSING_LAUNCH_DATE)

    def bad_prefix(rows: Any, venue: str, now_ns: int) -> Any:
        return refusal if len(rows) == 3 else real(rows, venue, now_ns)

    monkeypatch.setattr(replay_mod, "fold", bad_prefix)
    result = world.replay(chain)
    assert isinstance(result, ReplayInvalid) and result.reason is RefusalReason.REPLAY_INVALID
    assert result.rule == FoldInvalidReason.HEAD_MISSING_LAUNCH_DATE.value
    assert result.venue_seq == 3  # the first row of the batch before the one that could not start


def test_replay_maps_a_fold_invalid_full_chain_to_replay_invalid(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A whole chain the fold rejects after every batch validated is ``replay_invalid`` at the head.

    ``validate`` catches the natural cases, so only the final fold of all six rows is made to fail.
    """
    chain = full_chain(world)
    real = fold
    refusal = FoldInvalid(FoldInvalidReason.ROOT_LINEAGE_MISMATCH)
    size = len(chain.rows)

    def bad_full(rows: Any, venue: str, now_ns: int) -> Any:
        return refusal if len(rows) == size else real(rows, venue, now_ns)

    monkeypatch.setattr(replay_mod, "fold", bad_full)
    result = world.replay(chain)
    assert isinstance(result, ReplayInvalid) and result.venue_seq == size
    assert result.rule == FoldInvalidReason.ROOT_LINEAGE_MISMATCH.value


# --- B9: carried counters ------------------------------------------------------------------------


def _floor_of(chain: Chain, at_ns: int) -> str:
    """The canonical ``carried_counters`` equal to the fold's own tallies (the tightest floor)."""
    folded = fold(chain.rows, VENUE, at_ns)
    assert not isinstance(folded, FoldInvalid)
    lineages = {
        root: {f.name: getattr(view.tallies, f.name) for f in dataclasses.fields(view.tallies)}
        for root, view in folded.lineages.items()
    }
    venue = {
        f.name: getattr(folded.venue_tallies, f.name)
        for f in dataclasses.fields(folded.venue_tallies)
    }
    return carried(lineages, venue)


@pytest.mark.parametrize("floor", ["equal", "below"])
def test_replay_refuses_carried_counters_below_prior_fold(world: World, floor: str) -> None:
    chain = start(world)
    nominate(chain)
    text = _floor_of(chain, chain.rows[-1].ts_ns + 1) if floor == "equal" else carried({})
    row = reset(chain, text)
    result = world.replay(chain)
    if floor == "equal":
        assert isinstance(result, ReplayOk)
    else:
        assert isinstance(result, ReplayInvalid)
        assert (result.venue_seq, result.rule) == (row.venue_seq, "hwm_carried_below_export")


def test_a_carried_value_above_the_prior_fold_is_accepted(world: World) -> None:
    chain = start(world)
    nominate(chain)
    text = _floor_of(chain, chain.rows[-1].ts_ns + 1)
    raised = text.replace('"nominations":1', '"nominations":2')
    assert raised != text
    reset(chain, raised)
    assert isinstance(world.replay(chain), ReplayOk)


def test_an_hwm_reset_without_carried_counters_is_replay_invalid(world: World) -> None:
    chain = start(world)
    row = chain.add(
        Kind.HWM_RESET, State.CHAMPION, family=INCUMBENT, frm=State.CHAMPION,
        decided_by=DecidedBy.OPERATOR_CLI, hwm_from=3, hwm_to=4,
    )  # fmt: skip
    result = world.replay(chain)
    assert isinstance(result, ReplayInvalid) and result.venue_seq == row.venue_seq


# --- causes ---------------------------------------------------------------------------------------


def _promote_with(world: World, cited: tuple[str, ...]) -> Any:
    chain = start(world)
    nominate(chain, cited)
    return world.replay(chain)


def test_forged_promote_without_resolvable_cause_refused(world: World) -> None:
    assert isinstance(_promote_with(world, (OFFLINE.verdict_id,)), ReplayOk)  # control
    forged = "f" * 64
    result = _promote_with(world, (forged,))
    assert isinstance(result, ReplayCauseUnresolved)
    assert result.reason is RefusalReason.REPLAY_CAUSE_UNRESOLVED
    assert (result.venue_seq, result.verdict_id, result.why) == (3, forged, CauseFailure.NOT_FOUND)


def test_a_promote_that_cites_nothing_is_unresolved(world: World) -> None:
    result = _promote_with(world, ())
    assert isinstance(result, ReplayCauseUnresolved) and result.why is CauseFailure.NOT_CITED


def test_a_verdict_file_whose_bytes_do_not_match_its_id_is_unresolved(world: World) -> None:
    path = world.paths.verdict_file(CHILD, OFFLINE.valid_until_date(), OFFLINE.verdict_id)
    path.chmod(0o644)
    path.write_bytes(path.read_bytes().replace(b"replay_world", b"replay_forge"))
    result = _promote_with(world, (OFFLINE.verdict_id,))
    assert isinstance(result, ReplayCauseUnresolved) and result.why is CauseFailure.NOT_FOUND


def test_a_verdict_of_another_family_is_not_resolved_for_the_row(world: World) -> None:
    other = _verdict(VerdictKind.OFFLINE_CHALLENGER, family=INCUMBENT)
    write_verdict(world.paths, other)
    result = _promote_with(world, (other.verdict_id,))
    assert isinstance(result, ReplayCauseUnresolved) and result.why is CauseFailure.NOT_FOUND


@pytest.mark.parametrize(
    ("label", "verdict", "why"),
    [
        (
            "kind",
            _verdict(VerdictKind.FORWARD_SHADOW, produced=at("2026-10-09", "11:01")),
            CauseFailure.KIND_MISMATCH,
        ),
        (
            "outcome",
            _verdict(
                VerdictKind.OFFLINE_CHALLENGER,
                outcome=VerdictOutcome.FAIL,
                produced=at("2026-10-09", "11:02"),
            ),
            CauseFailure.NOT_PASS,
        ),
        (
            "artefact",
            _verdict(
                VerdictKind.OFFLINE_CHALLENGER,
                artefact="e" * 64,
                produced=at("2026-10-09", "11:03"),
            ),
            CauseFailure.SUBJECT_ARTEFACT_MISMATCH,
        ),
        (
            "artefact_null",
            _verdict(
                VerdictKind.OFFLINE_CHALLENGER, artefact=None, produced=at("2026-10-09", "11:04")
            ),
            CauseFailure.SUBJECT_ARTEFACT_MISMATCH,
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_a_resolved_verdict_must_fit_the_row(
    world: World, label: str, verdict: Verdict, why: CauseFailure
) -> None:
    write_verdict(world.paths, verdict)
    result = _promote_with(world, (verdict.verdict_id,))
    assert isinstance(result, ReplayCauseUnresolved), label
    expected = None if why is CauseFailure.KIND_MISMATCH else verdict.verdict_id
    assert (result.why, result.verdict_id) == (why, expected)


def test_a_promote_to_champion_needs_both_screening_and_forward_passes(world: World) -> None:
    chain = start(world)
    nominate(chain)
    promote_pair(chain, (OFFLINE.verdict_id,), world=world)
    result = world.replay(chain)
    assert isinstance(result, ReplayCauseUnresolved)
    assert (result.venue_seq, result.why) == (4, CauseFailure.KIND_MISMATCH)
    assert isinstance(world.replay(full_chain(world)), ReplayOk)  # control: both cited


def _halted_then_resumed(world: World, verdict: Verdict | None) -> Chain:
    chain = start(world)
    chain.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        ts=at("2026-10-09", "13:00"),
        halt_cause_class=CauseClass.RECOVERABLE_MODEL,
        cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    chain.add(
        Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED,
        ts=at(DAY, "16:45"),
        cause_verdict_ids=() if verdict is None else (verdict.verdict_id,),
    )  # fmt: skip
    return chain


def test_a_verdict_resolved_for_one_family_never_serves_another(world: World) -> None:
    chain = start(world)
    nominate(chain)  # resolves and caches OFFLINE, the child's verdict
    chain.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        ts=at("2026-10-09", "13:00"), halt_cause_class=CauseClass.RECOVERABLE_MODEL,
        cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    chain.add(
        Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED,
        ts=at(DAY, "16:45"), cause_verdict_ids=(OFFLINE.verdict_id,),
    )  # fmt: skip
    result = world.replay(chain)
    assert isinstance(result, ReplayCauseUnresolved)
    assert (result.venue_seq, result.why) == (5, CauseFailure.NOT_FOUND)


def test_resume_cited_verdict_must_be_a_pass_after_the_halt(world: World) -> None:
    """A7c-R8: replay resolves the cited verdicts, so validate judges their outcome and age."""
    good = _verdict(
        VerdictKind.HEALTH, family=INCUMBENT, artefact=None, produced=at("2026-10-09", "13:30")
    )
    stale = _verdict(
        VerdictKind.HEALTH, family=INCUMBENT, artefact=None, produced=at("2026-10-09", "12:30")
    )
    failed = _verdict(
        VerdictKind.HEALTH,
        family=INCUMBENT,
        artefact=None,
        outcome=VerdictOutcome.FAIL,
        produced=at("2026-10-09", "13:31"),
    )
    for verdict in (good, stale, failed):
        write_verdict(world.paths, verdict)
    assert isinstance(world.replay(_halted_then_resumed(world, good)), ReplayOk)
    # A FAIL is refused by the kind-agnostic PASS rule; a pre-halt PASS by validate's R8 rule.
    refused = world.replay(_halted_then_resumed(world, failed))
    assert isinstance(refused, ReplayCauseUnresolved) and refused.why is CauseFailure.NOT_PASS
    old = world.replay(_halted_then_resumed(world, stale))
    assert isinstance(old, ReplayInvalid) and old.rule == "resume_verdict_not_pass"
    uncited = world.replay(_halted_then_resumed(world, None))
    assert isinstance(uncited, ReplayCauseUnresolved) and uncited.why is CauseFailure.NOT_CITED


# --- artefact and manifest bytes ------------------------------------------------------------------


def test_artefact_bytes_must_equal_row_sha_at_resolve(world: World) -> None:
    chain = full_chain(world)
    assert isinstance(world.replay(chain), ReplayOk)  # control
    world.put_artefact(ARTEFACT + b" ")
    result = world.replay(chain)
    assert isinstance(result, ReplayArtefactMismatch)
    assert result.reason is RefusalReason.REPLAY_ARTEFACT_MISMATCH
    assert (result.venue_seq, result.why) == (1, ArtefactFailure.ARTEFACT_SHA_MISMATCH)


def test_a_missing_or_symlinked_artefact_is_unreadable(world: World, tmp_path: Path) -> None:
    chain = full_chain(world)
    path = world.put_artefact(ARTEFACT)
    path.unlink()
    result = world.replay(chain)
    assert isinstance(result, ReplayArtefactMismatch)
    assert result.why is ArtefactFailure.ARTEFACT_UNREADABLE
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_bytes(ARTEFACT)
    path.symlink_to(elsewhere)  # right bytes behind a symlink are still refused
    again = world.replay(chain)
    assert isinstance(again, ReplayArtefactMismatch)
    assert again.why is ArtefactFailure.ARTEFACT_UNREADABLE


def test_a_group_writable_artefact_is_unreadable(world: World) -> None:
    path = world.put_artefact(ARTEFACT)
    path.chmod(0o666)
    result = world.replay(full_chain(world))
    assert isinstance(result, ReplayArtefactMismatch)
    assert result.why is ArtefactFailure.ARTEFACT_UNREADABLE


def test_a_row_naming_an_unreadable_manifest_cannot_locate_its_artefact(world: World) -> None:
    chain = Chain()
    chain.add(
        Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT,
        manifest_sha256="9" * 64, artefact_sha256=ART_SHA,
    )  # fmt: skip
    result = world.replay(chain)
    assert isinstance(result, ReplayArtefactMismatch)
    assert result.why is ArtefactFailure.MANIFEST_UNREADABLE


def test_a_row_with_an_artefact_but_no_manifest_is_unreadable(world: World) -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, artefact_sha256=ART_SHA)
    result = world.replay(chain)
    assert isinstance(result, ReplayArtefactMismatch)
    assert result.why is ArtefactFailure.MANIFEST_UNREADABLE


def test_root_manifests_are_read_repo_only_never_from_a_registry_copy(world: World) -> None:
    """E-14 3a, A6d-A2 M2: a registry copy of a root, however exact, is never a source."""
    chain = full_chain(world)
    directory = world.data / "registry" / "families"
    planted = directory / f"{INCUMBENT}.json"
    planted.write_bytes(world.root_raw)
    planted.chmod(0o444)
    assert isinstance(world.replay(chain), ReplayOk)  # control: the repo file is there
    (world.repo / "deploy" / "families" / f"{INCUMBENT}.json").unlink()
    result = world.replay(chain)
    assert isinstance(result, ReplayArtefactMismatch)
    assert (result.venue_seq, result.why) == (1, ArtefactFailure.MANIFEST_UNREADABLE)


def test_a_drifted_committed_root_manifest_is_not_retried_against_the_registry(
    world: World,
) -> None:
    chain = full_chain(world)
    committed = world.repo / "deploy" / "families" / f"{INCUMBENT}.json"
    committed.write_bytes(world.root_raw + b"\n")
    result = world.replay(chain)
    assert isinstance(result, ReplayArtefactMismatch)
    assert result.why is ArtefactFailure.MANIFEST_UNREADABLE


def test_read_manifest_facts_repo_only_refuses_the_registry_copy(world: World) -> None:
    reader = partial(read_manifest_facts, paths=world.paths, repo_root=world.repo)
    assert reader(CHILD, world.child_sha) is not None  # a child: the registry copy serves
    assert reader(CHILD, world.child_sha, repo_only=True) is None
    assert reader(INCUMBENT, world.root_sha, repo_only=True) is not None  # a repo file serves


def test_shadow_paths_replay_reads_the_shadow_root(world: World, tmp_path: Path) -> None:
    shadow_root = tmp_path / "shadow"
    shadow_root.mkdir(mode=0o700)
    shadow = ShadowPaths(shadow_root)
    result = replay_full(seal(full_chain(world)), paths=shadow, repo_root=world.repo)
    assert result == ReplayArtefactMismatch(1, ArtefactFailure.ARTEFACT_UNREADABLE)


# --- shape ----------------------------------------------------------------------------------------


def _tree() -> ast.Module:
    return ast.parse(REPLAY_SOURCE.read_text(encoding="utf-8"))


def test_replay_full_is_the_only_public_entry_and_has_the_planned_signature() -> None:
    tree = _tree()
    public = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]
    assert public == ["replay_full"]
    (entry,) = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "replay_full"]
    assert [a.arg for a in entry.args.args] == ["chain"]
    assert [a.arg for a in entry.args.kwonlyargs] == ["paths", "repo_root"]


def test_replay_keeps_a_private_seam_and_never_reads_the_stage() -> None:
    tree = _tree()
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "_replay_full" in names
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom | ast.Import)
        for alias in node.names
    }
    assert "stage_policy" not in imported and "STAGE" not in imported


def test_replay_never_writes_and_stays_within_the_module_size_cap() -> None:
    source = REPLAY_SOURCE.read_text(encoding="utf-8")
    assert len(source.splitlines()) <= 800
    for banned in ("write_once", "write_verdict", "ensure_dir", "os.rename", "os.unlink"):
        assert banned not in source


def test_results_are_closed_and_carry_their_refusal_reason() -> None:
    reasons: dict[Callable[..., Any], RefusalReason] = {
        ReplayInvalid: RefusalReason.REPLAY_INVALID,
        ReplayCauseUnresolved: RefusalReason.REPLAY_CAUSE_UNRESOLVED,
        ReplayArtefactMismatch: RefusalReason.REPLAY_ARTEFACT_MISMATCH,
    }
    for cls, reason in reasons.items():
        assert cls.reason is reason  # type: ignore[attr-defined]
    assert not hasattr(ReplayOk, "reason")


def test_artefact_reads_are_memoised_by_model_class_and_sha(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two rows bind one artefact; each (model class, sha) pair is read once (A8b-R5 L3)."""
    calls: list[tuple[str, str]] = []
    real = replay_mod._read_artefact

    def counting(paths: Any, model_class: str, sha: str) -> bytes | None:
        calls.append((model_class, sha))
        return real(paths, model_class, sha)

    monkeypatch.setattr(replay_mod, "_read_artefact", counting)
    assert isinstance(world.replay(full_chain(world)), ReplayOk)
    # the root's and the child's artefact, each probed under every component once
    assert len(calls) == len(set(calls)) == 2 * len(pins.MODEL_CLASS_COMPONENTS)


def test_the_artefact_read_cap_is_a_pin() -> None:
    assert pins.ARTEFACT_MAX_BYTES == 64 * 1024 * 1024
    assert not hasattr(replay_mod, "ARTEFACT_MAX_BYTES")
