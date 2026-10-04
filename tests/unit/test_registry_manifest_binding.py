"""ARCH-0 seam 8d, E-24 store half: a family's manifest pins its artefact, and is immutable.

* ``Rule.MANIFEST_DENSITY_NOT_BOUND``: at BOOTSTRAP and MINT the manifest the row names pins, as its
  density, the artefact the row binds (``artefact_sha_mismatch``; ``manifest_unreadable`` when the
  manifest cannot be read, which is why the engine writes the family file before its MINT row).
* ``Rule.MANIFEST_BINDING_IMMUTABLE``: a later row names the manifest the family was introduced
  with or none (``manifest_sha_mismatch``); the fold binds the family to that first sha.

A new density is a new child family: nothing here lets one family move its pin.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Final

import breezy.persistence.autonomy.transitions as tm
from breezy.persistence.autonomy.family_bytes import read_manifest_facts
from breezy.persistence.autonomy.fold import fold
from breezy.persistence.autonomy.paths import AutonomyPaths
from breezy.persistence.autonomy.replay import ReplayInvalid
from breezy.persistence.autonomy.schemas import (
    CauseClass,
    Kind,
    ManifestFacts,
    ManifestFactsReader,
    RefusalReason,
    State,
)
from tests.support.entry_points import REPO_ROOT
from tests.unit.registry_manifest_density import density_facts
from tests.unit.test_registry_fold import CHILD, INCUMBENT, OTHER, VENUE, Chain, at, run
from tests.unit.test_registry_fold_validate import CHILD_MAN, INC_ART, INC_MAN, champion_chain
from tests.unit.test_registry_replay import ART_SHA, CHILD_ART_SHA, World, start
from tests.unit.test_registry_replay_parity import through_store

KIND: Final = "forecast_quantile_ladder"
NOW: Final = at("2026-10-10", "12:00")
OTHER_ART: Final = "7" * 64
OTHER_MAN: Final = "8" * 64
SENTINEL_FILE: Final = (
    REPO_ROOT / "deploy" / "families" / "artefacts" / "not_applicable_density.json"
)
SENTINEL_SHA: Final = hashlib.sha256(SENTINEL_FILE.read_bytes()).hexdigest()

Reader = ManifestFactsReader


def pinning(table: dict[tuple[str, str], str]) -> Reader:
    """A reader whose manifest at (family, sha) pins ``table[...]``; any other is unreadable."""
    reads: list[tuple[str, str]] = []

    def read(family_id: str, manifest_sha256: str) -> ManifestFacts | None:
        reads.append((family_id, manifest_sha256))
        pin = table.get((family_id, manifest_sha256))
        if pin is None:
            return None
        return ManifestFacts(
            family_id=family_id, manifest_sha256=manifest_sha256, d0_climate_day="2099-01-01",
            trial_id_prefix=f"{KIND}/trial/{family_id}/", composition_kind=KIND,
            density_artefact_sha256=pin,
        )  # fmt: skip

    read.reads = reads  # type: ignore[attr-defined]
    return read


def refused(reader: Reader, prior: Any, rows: list[Any]) -> tuple[str, RefusalReason] | None:
    got = tm.first_refusal(prior, rows, manifests=reader)
    return None if got is None else (got.rule.value, got.reason)


# --- MANIFEST_DENSITY_NOT_BOUND -------------------------------------------------------------------


def test_mint_manifest_density_must_equal_row_artefact() -> None:
    chain = champion_chain()
    prior = run(chain, NOW)
    mint = chain.add(
        Kind.MINT, State.SHADOW, family=OTHER, manifest_sha256=OTHER_MAN, artefact_sha256=OTHER_ART
    )
    key = (OTHER, OTHER_MAN)
    assert (
        refused(pinning({key: OTHER_ART}), prior, [mint]) is None
    )  # control: the pin is the row's
    assert refused(pinning({key: INC_ART}), prior, [mint]) == (
        "manifest_density_not_bound", RefusalReason.ARTEFACT_SHA_MISMATCH,
    )  # fmt: skip
    assert refused(pinning({}), prior, [mint]) == (  # fail closed: no manifest, no MINT
        "manifest_density_not_bound", RefusalReason.MANIFEST_UNREADABLE,
    )  # fmt: skip
    # a MINT whose row names no manifest cannot be bound to anything either
    unnamed = replace(mint, manifest_sha256=None)
    assert refused(pinning({key: OTHER_ART}), prior, [unnamed]) == (
        "manifest_density_not_bound", RefusalReason.MANIFEST_UNREADABLE,
    )  # fmt: skip


def test_the_density_rule_reads_each_introduced_family_once() -> None:
    chain = champion_chain()
    prior = run(chain, NOW)
    mint = chain.add(
        Kind.MINT, State.SHADOW, family=OTHER, manifest_sha256=OTHER_MAN, artefact_sha256=OTHER_ART
    )
    reader = pinning({(OTHER, OTHER_MAN): OTHER_ART})
    assert refused(reader, prior, [mint]) is None
    assert reader.reads == [(OTHER, OTHER_MAN)]  # type: ignore[attr-defined]


def test_a_batch_reads_one_manifest_once_across_the_rules_that_need_it() -> None:
    """A MINT, its nomination and its first-champion head in one batch: the density rule and the
    d0 rule both read OTHER's manifest, and the reader is asked once."""
    chain = champion_chain()
    prior = run(chain, NOW)
    mint = chain.add(
        Kind.MINT, State.SHADOW, family=OTHER, manifest_sha256=OTHER_MAN, artefact_sha256=OTHER_ART
    )
    head = chain.add(
        Kind.PROMOTE, State.CHAMPION, family=OTHER, frm=State.SHADOW,
        effective_launch_date="2026-10-10", manifest_sha256=OTHER_MAN,
    )  # fmt: skip
    tail = chain.add(
        Kind.SUPERSEDE, State.CHALLENGER, family=INCUMBENT, frm=State.CHAMPION,
        paired_transition_id=head.transition_id, effective_launch_date="2026-10-10",
    )  # fmt: skip
    reader = pinning({(OTHER, OTHER_MAN): OTHER_ART})
    got = tm.first_refusal(prior, [mint, head, tail], manifests=reader)
    assert got is None or got.rule.value != "manifest_density_not_bound", got
    assert reader.reads == [(OTHER, OTHER_MAN)]  # type: ignore[attr-defined]


def test_the_density_rule_covers_bootstrap_and_only_the_introducing_kinds() -> None:
    boot = Chain()
    row = boot.add(
        Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT,
        manifest_sha256=INC_MAN, artefact_sha256=INC_ART,
    )  # fmt: skip
    prior = run(Chain(), NOW)
    assert refused(pinning({(INCUMBENT, INC_MAN): INC_ART}), prior, [row]) is None
    assert refused(pinning({(INCUMBENT, INC_MAN): OTHER_ART}), prior, [row]) == (
        "manifest_density_not_bound", RefusalReason.ARTEFACT_SHA_MISMATCH,
    )  # fmt: skip
    # a later row of the family is not an introducer: it reads no manifest for the density pin
    chain = champion_chain()
    prior = run(chain, NOW)
    demote = chain.add(
        Kind.DEMOTE, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL,
    )  # fmt: skip
    boom = pinning({})
    assert refused(boom, prior, [demote]) is None
    assert boom.reads == []  # type: ignore[attr-defined]


def test_sentinel_root_bootstrap_density_equals_artefact(tmp_path: Path) -> None:
    """A sentinel root binds the sentinel file: its manifest pins that file's sha, and the BOOTSTRAP
    must bind the same (read through the real manifest reader over the committed file)."""
    manifest = REPO_ROOT / "deploy" / "families" / "pm_us_crh_v4.json"
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    reader = partial(
        read_manifest_facts, paths=AutonomyPaths(tmp_path), repo_root=REPO_ROOT, repo_only=True
    )
    facts = reader("pm_us_crh_v4", sha)
    assert facts is not None and facts.density_artefact_sha256 == SENTINEL_SHA
    prior = fold((), VENUE, NOW)
    chain = Chain()
    bound = chain.add(
        Kind.BOOTSTRAP, State.RETIRED, family="pm_us_crh_v4",
        manifest_sha256=sha, artefact_sha256=SENTINEL_SHA,
    )  # fmt: skip
    assert not isinstance(prior, tuple) and refused(reader, prior, [bound]) is None  # control
    chain = Chain()
    wrong = chain.add(
        Kind.BOOTSTRAP, State.RETIRED, family="pm_us_crh_v4",
        manifest_sha256=sha, artefact_sha256=ART_SHA,
    )  # fmt: skip
    assert refused(reader, prior, [wrong]) == (
        "manifest_density_not_bound", RefusalReason.ARTEFACT_SHA_MISMATCH,
    )  # fmt: skip


# --- MANIFEST_BINDING_IMMUTABLE and the fold ---------------------------------------------------


def _promote(chain: Chain, manifest: str | None) -> Any:
    extra: dict[str, Any] = {} if manifest is None else {"manifest_sha256": manifest}
    return chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW, **extra)


def test_family_manifest_binding_immutable() -> None:
    """A later row of CHILD names its introducing manifest or none; any other sha is refused."""
    chain = champion_chain()  # CHILD introduced by a MINT carrying CHILD_MAN
    prior = run(chain, NOW)
    anything = pinning({})  # the rule reads no manifest
    same = _promote(chain, CHILD_MAN)
    assert refused(anything, prior, [same]) is None  # control: the same sha
    none = _promote(chain, None)
    assert refused(anything, prior, [none]) is None  # control: no sha
    other = _promote(chain, OTHER_MAN)
    assert refused(anything, prior, [other]) == (
        "manifest_binding_immutable", RefusalReason.MANIFEST_SHA_MISMATCH,
    )  # fmt: skip


def test_family_manifest_binding_immutable_within_one_batch() -> None:
    """The introducing row is in the batch itself: the family is bound from its first row."""
    chain = Chain()
    chain.add(
        Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT,
        manifest_sha256=INC_MAN, artefact_sha256=INC_ART,
    )  # fmt: skip
    prior = run(chain, NOW)
    mint = chain.add(
        Kind.MINT, State.SHADOW, family=CHILD, manifest_sha256=CHILD_MAN, artefact_sha256=INC_ART
    )
    reader = pinning({(CHILD, CHILD_MAN): INC_ART})
    same = _promote(chain, CHILD_MAN)
    assert refused(reader, prior, [mint, same]) is None  # control
    other = _promote(chain, OTHER_MAN)
    assert refused(reader, prior, [mint, other]) == (
        "manifest_binding_immutable", RefusalReason.MANIFEST_SHA_MISMATCH,
    )  # fmt: skip


def test_the_fold_binds_a_family_to_its_introducing_manifest() -> None:
    """E-24 supersedes "the latest manifest sha": the fold keeps the first one."""
    chain = champion_chain()
    _promote(chain, OTHER_MAN)  # a forged later sha; validate refuses it, the fold must not follow
    result = run(chain, NOW)
    assert result.families[CHILD].manifest_sha256 == CHILD_MAN
    assert result.families[INCUMBENT].manifest_sha256 == INC_MAN


# --- through the real store and the real replay ------------------------------------------------


def test_the_family_file_is_written_before_its_mint_row(tmp_path: Path) -> None:
    """The store reads the child's manifest at its MINT: without the file the MINT is refused
    (``manifest_unreadable``), with it the same row is stored."""
    world = World(tmp_path)
    chain = start(world)
    copy = world.data / "registry" / "families" / f"{CHILD}.json"
    copy.chmod(0o644)
    copy.unlink()
    stored, rule = through_store(world, chain)
    assert rule == "manifest_density_not_bound"
    assert [r.kind for r in stored] == [Kind.BOOTSTRAP]  # the root was stored; the MINT was not
    world = World(tmp_path / "again")
    stored, rule = through_store(world, start(world))
    assert rule is None and any(r.kind is Kind.MINT for r in stored)  # control: file first


def test_replay_refuses_a_mint_whose_manifest_pins_another_artefact(tmp_path: Path) -> None:
    world = World(tmp_path)
    other = b'{"density":"other"}\n'
    other_sha = hashlib.sha256(other).hexdigest()
    world.put_artefact(other, sha=other_sha)
    chain = Chain()
    chain.add(
        Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT,
        manifest_sha256=world.root_sha, artefact_sha256=ART_SHA,
    )  # fmt: skip
    chain.add(
        Kind.MINT, State.SHADOW, family=CHILD,
        manifest_sha256=world.child_sha, artefact_sha256=other_sha,
    )  # fmt: skip
    got = world.replay(chain)  # the child's manifest pins CHILD_ART_SHA, the MINT binds ``other``
    assert isinstance(got, ReplayInvalid), got
    assert (got.venue_seq, got.rule, got.validate_reason) == (
        2, "manifest_density_not_bound", RefusalReason.ARTEFACT_SHA_MISMATCH,
    )  # fmt: skip
    assert CHILD_ART_SHA != other_sha


def test_the_density_fixture_reader_is_not_a_back_door() -> None:
    """The fixture reader answers only for manifests a builder registered; others are unreadable."""
    assert density_facts(CHILD, "9" * 64, d0="2099-01-01", composition=KIND) is None


def test_the_validate_rule_set_is_exact() -> None:
    """The rules a store or replay refusal can name; E-24 adds the last two."""
    assert {r.value for r in tm.Rule} == {
        "drill_no_single_incumbent",
        "drill_over_halted_incumbent",
        "drill_cause_stands",
        "drill_artefact_not_champion",
        "drill_budget",
        "rollback_drill_column",
        "infeasible_alpha",
        "resume_not_halted",
        "resume_pair_pending",
        "resume_exec_halt",
        "resume_class",
        "resume_uncited",
        "resume_verdict_not_pass",
        "resume_no_halt_instant",
        "from_state_mismatch",
        "artefact_binding_immutable",
        "manifest_density_not_bound",
        "manifest_binding_immutable",
        "restore_not_the_incumbent",
        "resume_cooldown",
        "resume_budget",
        "restore_not_failed_drill_close",
        "restore_drill_child",
        "restore_sha_mismatch",
        "restore_daily_cap",
        "first_champion_manifest",
        "first_champion_prefix",
        "first_champion_d0",
        "demoted_not_cleared",
        "launch_window_cause",
    }
