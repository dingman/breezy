"""ARCH-0 seam 8c: the sending resolver, registry side (AC 17 steps 0 to 8; AC 19).

A resolve reads a real registry database (written through the real store), an export directory, a
repo and the content-addressed store; every refusal test sits beside a control that resolves, so a
refusal cannot come from a broken world. The private ``_resolve`` is the seam that injects engine
pins (production ships none) and a fixture stage; the public entry is checked where it differs.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

import breezy.persistence.autonomy.replay as replay_mod
import breezy.persistence.autonomy.resolver as resolver_mod
from breezy.persistence.autonomy import stage_policy
from breezy.persistence.autonomy.chain import (
    ChainBroken,
    VerifiedVenueChain,
    seq_is_verified_prefix,
)
from breezy.persistence.autonomy.fold import Origin, fold
from breezy.persistence.autonomy.hwm import (
    Hwm,
    HwmAbsent,
    HwmPresent,
    HwmUnreadable,
    hwm_reading_from_bytes,
    next_hwm,
)
from breezy.persistence.autonomy.paths import ShadowPaths
from breezy.persistence.autonomy.registry_export import ExportRead
from breezy.persistence.autonomy.resolver import (
    FamilySource,
    HwmMode,
    ResolvedFamily,
    ResolverRefusal,
    ShadowResolution,
    read_family_source,
    resolve_sending_family,
)
from breezy.persistence.autonomy.schemas import (
    CauseClass,
    CauseCode,
    ExportTrailer,
    Kind,
    RefusalReason,
    StagePolicy,
    State,
    UnreadableReason,
)
from tests.support.entry_points import SRC_DIR
from tests.unit.registry_resolver_world import (
    NOW_EARLY,
    equip,
    export_all,
    forge,
    hwm_of,
    populate,
    replay_stubbed,
    resolve,
    root_chain,
    serving,
)
from tests.unit.test_registry_export import put_export
from tests.unit.test_registry_fold import CHILD, DAY, INCUMBENT, VENUE, Chain, at
from tests.unit.test_registry_fold_tallies import carried, reset
from tests.unit.test_registry_replay import ART_SHA, World, full_chain, nominate, seal, start
from tests.unit.test_registry_replay_parity import year_chain

RESOLVER_SOURCE: Final = SRC_DIR / "breezy" / "persistence" / "autonomy" / "resolver.py"
PICKUP_FIELDS: Final = frozenset(
    {
        "family_id",
        "state",
        "entries_allowed",
        "origin",
        "registry_seq",
        "chain_head",
        "authorising_seq",
        "family_bytes",
        "export_check",
        "verified_export_seq",
        "hwm",
    }
)
HOUR_NS: Final = 3_600 * 10**9
OPEN_STAGE: Final = StagePolicy(
    enabled_widening_kinds=frozenset(Kind), admission_implemented=frozenset(Kind)
)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return equip(World(tmp_path))


@pytest.fixture
def rooted(world: World) -> VerifiedVenueChain:
    """The registry holds the root alone: BOOTSTRAP, root CHAMPION."""
    return populate(world, root_chain(world))


def refusal_of(result: object) -> ResolverRefusal:
    assert isinstance(result, ResolverRefusal), result
    return result


def resolved(result: object) -> ResolvedFamily:
    assert isinstance(result, ResolvedFamily), result
    return result


# --- the control and the shape of the answer ------------------------------------------------------


def test_the_root_alone_resolves_with_the_arch_c5_pickup_fields(
    world: World, rooted: VerifiedVenueChain
) -> None:
    """test_resolved_family_carries_arch_c5_pickup_fields (ARCH :558; AUT-5 r7 :410, :441, :971)."""
    got = resolved(resolve(world, hwm_of(rooted), now=NOW_EARLY))
    assert {f.name for f in dataclasses.fields(ResolvedFamily)} == PICKUP_FIELDS
    assert (got.family_id, got.state, got.entries_allowed, got.origin) == (
        INCUMBENT, State.CHAMPION, True, Origin.ROOT,
    )  # fmt: skip
    assert (got.registry_seq, got.chain_head, got.authorising_seq) == (1, rooted.head_hash, 1)
    assert (got.export_check, got.verified_export_seq) == ("not_yet_due", 0)
    assert got.family_bytes.manifest_source == "deploy"
    assert got.family_bytes.manifest_sha256 == world.root_sha
    assert got.family_bytes.artefact_sha256 == ART_SHA
    assert got.family_bytes.artefact_store_relpath.startswith("derived/artefacts/")


def test_resolved_family_hwm_equals_next_hwm(world: World, rooted: VerifiedVenueChain) -> None:
    got = resolved(resolve(world, hwm_of(rooted), now=NOW_EARLY))
    assert got.hwm == next_hwm(rooted, export_seq=got.verified_export_seq)
    assert isinstance(got.hwm, Hwm) and got.hwm.venue_seq == rooted.head_venue_seq


def test_no_export_means_newest_export_seq_zero(world: World, rooted: VerifiedVenueChain) -> None:
    got = resolved(resolve(world, hwm_of(rooted), now=NOW_EARLY))
    assert (got.export_check, got.verified_export_seq, got.hwm.export_seq) == ("not_yet_due", 0, 0)


def test_a_verified_export_sets_the_export_seq_and_check(
    world: World, rooted: VerifiedVenueChain
) -> None:
    export_all(world, rooted, export_seq=3)
    got = resolved(resolve(world, hwm_of(rooted, 3), now=NOW_EARLY))
    assert (got.export_check, got.verified_export_seq, got.hwm.export_seq) == ("verified", 3, 3)


def test_a_halted_sender_resolves_with_entries_disallowed(world: World) -> None:
    chain = root_chain(world)
    chain.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    stored = populate(world, chain)
    got = resolved(resolve(world, hwm_of(stored), now=NOW_EARLY))
    assert (got.state, got.entries_allowed) == (State.HALTED, False)
    assert got.authorising_seq == 1  # the BOOTSTRAP that made it CHAMPION, not the HALT


# --- step 2: registry, chain, clock ---------------------------------------------------------------


def test_a_missing_registry_database_is_registry_unreadable_with_its_reason(world: World) -> None:
    refused = refusal_of(resolve(world, HwmAbsent(), now=NOW_EARLY))
    assert (refused.reason, refused.detail) == (
        RefusalReason.REGISTRY_UNREADABLE,
        UnreadableReason.IO,
    )


def test_family_source_registry_requires_bootstrap(world: World) -> None:
    """U14 / V18: only ``registry`` binds; ``registry`` on an empty chain resolves no champion."""
    assert read_family_source({}) is FamilySource.UNSET
    assert read_family_source({"BREEZY_FAMILY_SOURCE": ""}) is FamilySource.UNSET
    assert read_family_source({"BREEZY_FAMILY_SOURCE": "registry"}) is FamilySource.REGISTRY
    shadow = read_family_source({"BREEZY_FAMILY_SOURCE": "registry_shadow"})
    assert shadow is FamilySource.REGISTRY_SHADOW
    with pytest.raises(ValueError):
        read_family_source({"BREEZY_FAMILY_SOURCE": "Registry"})
    populate(world, Chain())  # an initialised registry that holds no row
    for reading in (HwmAbsent(), HwmUnreadable("bad")):
        refused = refusal_of(resolve(world, reading, now=NOW_EARLY))
        assert refused.reason is RefusalReason.EMPTY_CHAIN


def test_a_chain_that_does_not_verify_is_chain_broken(
    world: World, rooted: VerifiedVenueChain, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store cannot be made to hold a broken chain (its DDL is pinned), so the verifier is
    made to refuse; the control is the unpatched resolve."""
    assert isinstance(resolve(world, hwm_of(rooted), now=NOW_EARLY), ResolvedFamily)

    def broken(*_args: object) -> VerifiedVenueChain:
        raise ChainBroken(1, "forced")

    monkeypatch.setattr(resolver_mod, "verify_venue_chain", broken)
    assert refusal_of(resolve(world, hwm_of(rooted), now=NOW_EARLY)).reason is (
        RefusalReason.CHAIN_BROKEN
    )


def test_clock_before_head_refuses(world: World, rooted: VerifiedVenueChain) -> None:
    head_ts = rooted.rows[-1].ts_ns
    skew = 300 * 10**9
    inside = refusal_of(resolve(world, hwm_of(rooted), now=head_ts - skew))
    assert inside.reason is RefusalReason.NO_SENDER  # tolerated skew: the head is not yet applied
    refused = refusal_of(resolve(world, hwm_of(rooted), now=head_ts - skew - 1))
    assert refused.reason is RefusalReason.CLOCK_BEFORE_HEAD
    assert isinstance(resolve(world, hwm_of(rooted), now=head_ts), ResolvedFamily)  # control


@pytest.mark.parametrize("bad", [0, -5, True, False, 1.5, "17", None])
def test_an_unusable_clock_is_clock_invalid(
    world: World, rooted: VerifiedVenueChain, bad: Any
) -> None:
    assert refusal_of(resolve(world, hwm_of(rooted), now=bad)).reason is RefusalReason.CLOCK_INVALID


# --- step 3: exports ---


def test_an_unknown_name_in_the_export_directory_is_export_unreadable(
    world: World, rooted: VerifiedVenueChain
) -> None:
    assert isinstance(resolve(world, hwm_of(rooted), now=NOW_EARLY), ResolvedFamily)
    (world.paths.export_dir() / "stray.txt").write_bytes(b"x")
    refused = refusal_of(resolve(world, hwm_of(rooted), now=NOW_EARLY))
    assert refused.reason is RefusalReason.EXPORT_UNREADABLE


def test_a_missing_export_directory_is_export_unreadable(
    world: World, rooted: VerifiedVenueChain
) -> None:
    world.paths.export_dir().rmdir()
    refused = refusal_of(resolve(world, hwm_of(rooted), now=NOW_EARLY))
    assert refused.reason is RefusalReason.EXPORT_UNREADABLE


def test_export_dir_listing_error_is_export_unreadable(
    world: World, rooted: VerifiedVenueChain, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(_fd: object) -> list[str]:
        raise OSError("listing failed")

    with monkeypatch.context() as patch:
        patch.setattr(os, "listdir", failing)
        refused = refusal_of(resolve(world, hwm_of(rooted), now=NOW_EARLY))
    assert refused.reason is RefusalReason.EXPORT_UNREADABLE
    assert isinstance(resolve(world, hwm_of(rooted), now=NOW_EARLY), ResolvedFamily)


def test_no_export_after_the_grace_is_export_unreadable(
    world: World, rooted: VerifiedVenueChain
) -> None:
    genesis_ts = rooted.rows[0].ts_ns
    inside = genesis_ts + 26 * HOUR_NS - 1
    assert isinstance(resolve(world, hwm_of(rooted), now=inside), ResolvedFamily)
    refused = refusal_of(resolve(world, hwm_of(rooted), now=genesis_ts + 26 * HOUR_NS))
    assert refused.reason is RefusalReason.EXPORT_UNREADABLE


def test_a_corrupt_export_blocks_resolution(world: World, rooted: VerifiedVenueChain) -> None:
    """E-18b: one bad candidate is never skipped in favour of an older good one."""
    export_all(world, rooted, export_seq=1)
    assert isinstance(resolve(world, hwm_of(rooted, 1), now=NOW_EARLY), ResolvedFamily)
    (path,) = world.paths.export_dir().iterdir()
    path.chmod(0o644)
    path.write_bytes(path.read_bytes() + b"garbage\n")
    refused = refusal_of(resolve(world, hwm_of(rooted, 1), now=NOW_EARLY))
    assert refused.reason is RefusalReason.EXPORT_UNREADABLE


def test_an_export_that_is_not_a_prefix_of_the_chain_is_refused(
    world: World, rooted: VerifiedVenueChain
) -> None:
    other = root_chain(world)
    other.rows[0] = dataclasses.replace(other.rows[0], artefact_sha256="e" * 64)
    forged = _sealed_with_seq(other)
    export_all(world, forged, export_seq=1)
    refused = refusal_of(resolve(world, hwm_of(rooted, 0), now=NOW_EARLY))
    assert refused.reason is RefusalReason.EXPORT_PREFIX_MISMATCH


def _sealed_with_seq(chain: Chain) -> VerifiedVenueChain:
    """A sealed chain whose rows also carry their global ``seq`` (as an export's rows do)."""
    sealed = seal(chain)
    rows = tuple(dataclasses.replace(r, seq=r.venue_seq) for r in sealed.rows)
    return dataclasses.replace(sealed, rows=rows)


def test_the_export_floor_covers_every_reset_after_the_newest_export() -> None:
    """B9 / E-21: the resolver's export floor is necessary, not sufficient. It is checked here
    in isolation from replay's prior-fold floor (the module docstring says why the two agree on a
    verified chain); the real-run halves are in
    ``test_a_reset_below_the_newest_export_is_refused_by_the_resolver``.

    A reset written after the export must cover the export's counters.
    """
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
    chain.add(Kind.MINT, State.SHADOW, family=CHILD)
    chain.add(
        Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW,
        lineage_root_family_id=INCUMBENT, k_life=1, alpha_k=Decimal("0.01"),
        n_min_eff=403, n_cap=480, nomination_feasible=True,
    )  # fmt: skip
    export_chain = seal(chain)
    export = ExportRead(
        ExportTrailer(venue=VENUE, venue_seq=3, chain_head=export_chain.head_hash, export_seq=1),
        export_chain.rows,
    )
    row = reset(chain, carried({}))  # no counter carried: below the export's nomination
    refused = resolver_mod._reset_floor_problem(seal(chain), export, VENUE)
    assert refused is not None and refused.reason is RefusalReason.REPLAY_INVALID
    chain.rows[3] = dataclasses.replace(row, carried_counters=_floor(chain.rows[:3]))
    assert resolver_mod._reset_floor_problem(seal(chain), export, VENUE) is None
    assert resolver_mod._reset_floor_problem(seal(chain), None, VENUE) is None  # no export


def _floor(rows: Any) -> str:
    """The canonical ``carried_counters`` equal to the fold's own tallies at the last row."""
    folded = fold(rows, VENUE, rows[-1].ts_ns)
    lineages = {
        root: {f.name: getattr(view.tallies, f.name) for f in dataclasses.fields(view.tallies)}
        for root, view in folded.lineages.items()  # type: ignore[union-attr]
    }
    venue = {
        f.name: getattr(folded.venue_tallies, f.name)  # type: ignore[union-attr]
        for f in dataclasses.fields(folded.venue_tallies)  # type: ignore[union-attr]
    }
    return carried(lineages, venue)


# --- step 4: the node high-water mark ---


def test_hwm_absent_with_rows_refuses(world: World, rooted: VerifiedVenueChain) -> None:
    assert isinstance(resolve(world, hwm_of(rooted), now=NOW_EARLY), ResolvedFamily)
    assert refusal_of(resolve(world, HwmAbsent(), now=NOW_EARLY)).reason is (
        RefusalReason.HWM_ABSENT
    )


def test_hwm_absent_on_genesis_only_chain_refuses(world: World, rooted: VerifiedVenueChain) -> None:
    """One row (the BOOTSTRAP genesis) is a non-empty chain: an absent HWM is never a pass."""
    assert rooted.head_venue_seq == 1
    assert refusal_of(resolve(world, hwm_reading_from_bytes(None), now=NOW_EARLY)).reason is (
        RefusalReason.HWM_ABSENT
    )


@pytest.mark.parametrize("reading", [HwmUnreadable("bad"), None, "x", b"{}"])
def test_hwm_unreadable_refuses(world: World, rooted: VerifiedVenueChain, reading: Any) -> None:
    assert isinstance(hwm_reading_from_bytes(b"{"), HwmUnreadable)
    refused = refusal_of(resolve(world, reading, now=NOW_EARLY))
    assert refused.reason is RefusalReason.HWM_UNREADABLE


def test_a_hwm_that_is_ahead_of_or_off_the_chain_is_regressed(
    world: World, rooted: VerifiedVenueChain
) -> None:
    head = rooted.head_hash
    ahead = HwmPresent(Hwm(venue=VENUE, venue_seq=2, chain_head=head, export_seq=0))
    off = HwmPresent(Hwm(venue=VENUE, venue_seq=1, chain_head="0" * 64, export_seq=0))
    for hwm in (ahead, off):
        assert refusal_of(resolve(world, hwm, now=NOW_EARLY)).reason is RefusalReason.HWM_REGRESSED


def test_export_absent_after_hwm_saw_export_refuses(
    world: World, rooted: VerifiedVenueChain
) -> None:
    """The node saw export 1; the directory now has none: the chain was rewound under it."""
    assert isinstance(resolve(world, hwm_of(rooted, 0), now=NOW_EARLY), ResolvedFamily)
    refused = refusal_of(resolve(world, hwm_of(rooted, 1), now=NOW_EARLY))
    assert refused.reason is RefusalReason.HWM_REGRESSED


# --- steps 5, 0: stage and role -----------------------------------------------------------------


@pytest.fixture
def promoted(world: World) -> VerifiedVenueChain:
    """The child has taken effect over the root at DAY's LAUNCH (forged: the store cannot hold a
    nomination yet)."""
    return forge(full_chain(world))


NOW_LATE: Final = at(DAY, "17:30")


def test_resolver_refuses_chain_with_unenabled_widening_row(
    world: World, promoted: VerifiedVenueChain
) -> None:
    """A hand-forged chain: the store was given a fixture stage, so a PROMOTE to CHAMPION is
    stored; the canonical stage enables no widening kind, so the resolver refuses the chain."""
    export_all(world, promoted)
    with serving(promoted):
        refused = refusal_of(resolve(world, hwm_of(promoted, 1), now=NOW_LATE))
        public = resolve_sending_family(
            venue=VENUE, paths=world.paths, repo_root=world.repo, now_ns=NOW_LATE,
            hwm=hwm_of(promoted, 1),
        )  # fmt: skip
    assert refused.reason is RefusalReason.WIDENING_KIND_NOT_ENABLED
    assert refusal_of(public).reason is RefusalReason.WIDENING_KIND_NOT_ENABLED


def test_an_enabled_but_unimplemented_widening_kind_is_admission_pending(
    world: World, promoted: VerifiedVenueChain
) -> None:
    export_all(world, promoted)
    enabled_only = StagePolicy(
        enabled_widening_kinds=frozenset(Kind), admission_implemented=frozenset()
    )
    with serving(promoted):
        refused = refusal_of(
            resolve(
                world, hwm_of(promoted, 1), now=NOW_LATE, stage=enabled_only, _fixture_stage=True
            )
        )
    assert refused.reason is RefusalReason.ADMISSION_PENDING


def test_resolve_refuses_non_canonical_stage(world: World, rooted: VerifiedVenueChain) -> None:
    assert stage_policy.STAGE is not OPEN_STAGE
    refused = refusal_of(resolve(world, hwm_of(rooted), now=NOW_EARLY, stage=OPEN_STAGE))
    assert refused.reason is RefusalReason.STAGE_NOT_CANONICAL
    fixture = resolve(world, hwm_of(rooted), now=NOW_EARLY, stage=OPEN_STAGE, _fixture_stage=True)
    assert isinstance(fixture, ResolvedFamily)  # control: only the fixture flag admits it


@pytest.mark.parametrize("facet", ["resolver"])
def test_admissibility_predicate_shared(facet: str) -> None:
    """The resolver consumes ``transitions.rows_admissible`` and compares no stage set itself."""
    assert facet == "resolver"
    tree = ast.parse(RESOLVER_SOURCE.read_text(encoding="utf-8"))
    calls = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "rows_admissible" in calls
    assert not names & {"enabled_widening_kinds", "admission_implemented"}


def test_resolve_private_rejects_skip_hwm_on_production_paths(
    world: World, rooted: VerifiedVenueChain, tmp_path: Path
) -> None:
    """AC 17.0: the hwm mode and the paths role must agree, in both directions."""
    skip = resolve(world, HwmAbsent(), now=NOW_EARLY, hwm_mode=HwmMode.SKIP_SHADOW)
    assert refusal_of(skip).reason is RefusalReason.PATHS_ROLE_MISMATCH
    assert ShadowPaths(tmp_path / "shadow").is_shadow  # a shadow root is shadow
    shadow_enforce = resolve(
        world, HwmAbsent(), now=NOW_EARLY, paths=ShadowPaths(tmp_path / "shadow")
    )
    assert refusal_of(shadow_enforce).reason is RefusalReason.PATHS_ROLE_MISMATCH
    assert isinstance(resolve(world, hwm_of(rooted), now=NOW_EARLY), ResolvedFamily)  # control
    shadow_root = ShadowPaths(world.data)  # the same files read as a shadow root: the pair agrees
    assert isinstance(
        resolve(world, HwmAbsent(), now=NOW_EARLY, hwm_mode=HwmMode.SKIP_SHADOW, paths=shadow_root),
        ShadowResolution,
    )


def test_the_public_entry_refuses_shadow_paths_before_anything_is_read(tmp_path: Path) -> None:
    """Step 1 is coded in the public entry: it reads ``is_shadow``, never ``isinstance``."""
    shadow = ShadowPaths(tmp_path / "does-not-exist")
    got = resolve_sending_family(
        venue=VENUE, paths=shadow, repo_root=tmp_path, now_ns=NOW_EARLY, hwm=HwmAbsent()
    )
    assert refusal_of(got).reason is RefusalReason.PATHS_ROLE_MISMATCH
    tree = ast.parse(RESOLVER_SOURCE.read_text(encoding="utf-8"))
    entry = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "resolve_sending_family"
    )
    private = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_resolve"
    )
    assert any(isinstance(n, ast.Attribute) and n.attr == "is_shadow" for n in ast.walk(entry))
    assert not any(  # a role is an attribute of the paths, never a class test
        isinstance(n, ast.Call)
        and getattr(n.func, "id", None) == "isinstance"
        and ast.unparse(n.args[0]) == "paths"
        for n in ast.walk(tree)
    )
    assert any(isinstance(n, ast.Attribute) and n.attr == "is_shadow" for n in ast.walk(private))


# --- step 6: replay ------------------------------------------------------------------------------


def test_a_replay_refusal_gives_no_champion_with_its_closed_reason(
    world: World, promoted: VerifiedVenueChain
) -> None:
    export_all(world, promoted)
    args: dict[str, Any] = {"stage": OPEN_STAGE, "_fixture_stage": True}
    with serving(promoted):
        assert isinstance(resolve(world, hwm_of(promoted, 1), now=NOW_LATE, **args), ResolvedFamily)
        world.put_artefact(b'{"density":"tampered"}\n')
        refused = refusal_of(resolve(world, hwm_of(promoted, 1), now=NOW_LATE, **args))
    assert refused.reason is RefusalReason.REPLAY_ARTEFACT_MISMATCH


# --- step 7: one sender --------------------------------------------------------------------------


def test_two_senders_is_engine_inconsistency(world: World) -> None:
    """Replay and ``validate`` both refuse two senders, so a chain that reaches step 7 with two is
    an engine inconsistency. The chain is forged in memory: the real run is refused by replay
    (``replay_invalid``), the stubbed run reaches the resolver's own step 7."""
    chain = root_chain(world)
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family="pm_us_crh_v4", artefact_sha256=ART_SHA)
    forged = forge(chain)
    with serving(forged):
        real = refusal_of(resolve(world, hwm_of(forged), now=NOW_EARLY))
    assert real.reason is RefusalReason.REPLAY_INVALID
    with serving(forged), replay_stubbed():
        stubbed = refusal_of(resolve(world, hwm_of(forged), now=NOW_EARLY))
    assert stubbed.reason is RefusalReason.ENGINE_INCONSISTENCY


def test_no_sender_when_nobody_is_champion_or_halted(world: World) -> None:
    chain = root_chain(world)
    chain.add(Kind.RETIRE, State.RETIRED, family=INCUMBENT, frm=State.CHAMPION)
    forged = forge(chain)
    with serving(forged), replay_stubbed():
        refused = refusal_of(resolve(world, hwm_of(forged), now=NOW_EARLY))
    assert refused.reason is RefusalReason.NO_SENDER


# --- the closed refusal set, read-only, budget ---

#: The closed set of ``RefusalReason`` members (the plan's AC 17 list, verbatim).
CLOSED_REASONS: Final = frozenset(
    [
        "registry_unreadable",
        "empty_chain",
        "chain_broken",
        "clock_invalid",
        "clock_before_head",
        "hwm_unreadable",
        "hwm_absent",
        "hwm_regressed",
        "export_unreadable",
        "export_prefix_mismatch",
        "widening_kind_not_enabled",
        "admission_pending",
        "replay_invalid",
        "replay_cause_unresolved",
        "replay_artefact_mismatch",
        "engine_inconsistency",
        "no_sender",
        "paths_role_mismatch",
        "stage_not_canonical",
        "family_not_introduced",
        "root_lineage_mismatch",
        "engine_code_unpinned",
        "engine_code_revoked",
        "manifest_unreadable",
        "manifest_invalid",
        "manifest_draft",
        "manifest_unpinned",
        "prereg_ineligible",
        "manifest_sha_mismatch",
        "manifest_identity_mismatch",
        "kind_not_live_gate_routed",
        "artefact_unreadable",
        "artefact_sha_mismatch",
        "root_record_mismatch",
        "child_root_mismatch",
        "child_not_equal_root",
        "root_not_lineage_allowlisted",
        "ruling_not_policy",
        "ruling_refused",
        "no_live_orders_ruling",
        "d0_breach",
        "trial_prefix_mismatch",
    ]
)


def test_resolver_refusals_give_no_champion() -> None:
    """A refusal is a closed reason (and at most a closed detail) and carries no bytes."""
    assert {r.value for r in RefusalReason} == CLOSED_REASONS
    assert {f.name for f in dataclasses.fields(ResolverRefusal)} == {"reason", "detail"}
    named: set[str] = set()
    for source in (RESOLVER_SOURCE, SRC_DIR / "breezy/persistence/autonomy/family_bytes.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "RefusalReason"
            ):
                named.add(node.attr)
    assert named and {n.lower() for n in named} <= CLOSED_REASONS
    refusal = ResolverRefusal(RefusalReason.NO_SENDER)
    assert not any(hasattr(refusal, name) for name in PICKUP_FIELDS - {"state"})


def test_a_resolve_writes_nothing(world: World, rooted: VerifiedVenueChain) -> None:
    """The resolver reads the registry root and the repo and never writes either."""

    def snapshot() -> dict[str, tuple[int, int]]:
        found: dict[str, tuple[int, int]] = {}
        for base in (world.data, world.repo):
            for path in sorted(base.rglob("*")):
                info = path.lstat()
                found[str(path)] = (info.st_mtime_ns, info.st_size)
        return found

    before = snapshot()
    assert isinstance(resolve(world, hwm_of(rooted), now=NOW_EARLY), ResolvedFamily)
    assert snapshot() == before


BUDGET_ROWS: Final = 2_000
#: Measured on this host: about 1.4 s for ``BUDGET_ROWS`` rows (replay's re-fold dominates); the
#: bound is about 3x. ARCH's 10,000 rows in 2 s is not reachable: replay alone is quadratic.
BUDGET_S: Final = 5.0


#: Fold invocations of one resolve of ``BUDGET_ROWS`` rows, pinned exactly (A8c-R5): replay folds
#: the prefix once per batch (every row of ``year_chain`` is its own batch: ``BUDGET_ROWS`` folds),
#: then once over the whole chain, and the resolver folds the head once (no HWM_RESET, so no B9
#: export fold). A regression in the replay's cost shows here deterministically, where a tighter
#: clock bound would flake on this memory-pressured host.
BUDGET_FOLD_CALLS: Final = BUDGET_ROWS + 2


def test_resolver_under_budget(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    chain = forge(year_chain(world))
    assert chain.head_venue_seq == BUDGET_ROWS
    export_all(world, chain)
    now = chain.rows[-1].ts_ns + HOUR_NS
    calls = {"fold": 0}

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls["fold"] += 1
        return real_fold(*args, **kwargs)

    real_fold = fold
    monkeypatch.setattr(resolver_mod, "fold", counted)
    monkeypatch.setattr(replay_mod, "fold", counted)
    started = time.monotonic()
    with serving(chain):  # RegistryReader.read_venue_rows is patched, so step 2 runs for real
        got = resolved(resolve(world, hwm_of(chain, 1), now=now))
    elapsed = time.monotonic() - started
    print(f"resolve of {BUDGET_ROWS} rows: {elapsed:.2f}s, {calls['fold']} folds")
    assert got.registry_seq == BUDGET_ROWS
    assert elapsed < BUDGET_S
    assert calls["fold"] == BUDGET_FOLD_CALLS


@pytest.mark.parametrize("facet", ["resolver"])
def test_node_relaunch_rule_family_id_and_seq_prefix(world: World, facet: str) -> None:
    """The resolver half of Z7: a relaunch re-resolves, the family id is unchanged and the seq the
    first resolve returned is a verified prefix of the longer chain the second one reads."""
    assert facet == "resolver"
    chain = root_chain(world)
    first = forge(chain)
    chain.add(
        Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION,
        ts=first.rows[-1].ts_ns + 6 * HOUR_NS,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    longer = forge(chain)
    with serving(first):
        before = resolved(resolve(world, hwm_of(first), now=NOW_EARLY))
    with serving(longer):
        after = resolved(resolve(world, hwm_of(longer), now=NOW_EARLY + 7 * HOUR_NS))
    assert after.family_id == before.family_id  # a HALTED sender is still the same family
    assert (before.registry_seq, after.registry_seq) == (1, 2)
    assert seq_is_verified_prefix(longer, before.registry_seq, before.chain_head)
    assert not seq_is_verified_prefix(longer, before.registry_seq, "0" * 64)


def test_a_reset_below_the_newest_export_is_refused_by_the_resolver(world: World) -> None:
    """B9 / E-21 at the resolver: an HWM_RESET written after the newest export must carry the
    export's counters. Replay is stubbed (its prior-fold floor would refuse the same row), so only
    the resolver's own export floor can; the control carries exactly the export's counters."""
    chain = start(world)  # the root CHAMPION and a MINTed child, bound to real files
    nominate(chain)  # cites the world's offline verdict, so replay can resolve its cause
    reset_row = reset(chain, carried({}))
    low = forge(chain)
    put_export(world.paths, low.rows[:3], 1)  # the export holds the first three rows only
    with serving(low):  # the real run: replay's own prior-fold floor refuses the same row first
        real = refusal_of(resolve(world, hwm_of(low, 1), now=NOW_EARLY))
    assert real.reason is RefusalReason.REPLAY_INVALID
    with serving(low), replay_stubbed():
        refused = refusal_of(resolve(world, hwm_of(low, 1), now=NOW_EARLY))
    assert refused.reason is RefusalReason.REPLAY_INVALID
    chain.rows[3] = dataclasses.replace(reset_row, carried_counters=_floor(chain.rows[:3]))
    covered = forge(chain)
    with serving(covered), replay_stubbed():
        assert isinstance(resolve(world, hwm_of(covered, 1), now=NOW_EARLY), ResolvedFamily)
    with serving(covered):  # the real control: replay admits a reset that covers the export
        assert isinstance(resolve(world, hwm_of(covered, 1), now=NOW_EARLY), ResolvedFamily)
