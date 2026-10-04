"""ARCH-0 seam 8c: the sending resolver, a child family and the lineage gate (AC 17 step 10).

The child is bound to its registry copy and to the committed root (ARCH 4.2); the lineage-policy
gate and the d0 and prefix rule are judged on it. See ``test_registry_resolver_bytes`` for how the
replay-first precedence is tested.
"""

from __future__ import annotations

import dataclasses
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

import breezy.persistence.autonomy.resolver as resolver_mod
from breezy.persistence.autonomy.family_bytes import (
    CHILD_MANIFEST_ALLOWLIST,
    ByteBindingFailure,
    FamilyBytes,
    manifest_equal_modulo_allowlist,
    verify_bound_bytes,
    verify_family_bytes,
)
from breezy.persistence.autonomy.fold import Origin
from breezy.persistence.autonomy.resolver import (
    ResolvedFamily,
    ResolverRefusal,
)
from breezy.persistence.autonomy.schemas import (
    CauseClass,
    CauseCode,
    Kind,
    LiveOrdersRefusal,
    RefusalReason,
    State,
)
from breezy.persistence.autonomy.verdict import VerdictKind, write_verdict
from breezy.persistence.family_manifest import FamilyManifest, parse_family_manifest
from breezy.persistence.live_orders_gate import (
    LineagePolicyDecision,
    LiveOrdersGateRefusedError,
    lineage_policy_authorized,
)
from tests.unit.registry_resolver_world import (
    NOW_LATE,
    PIN,
    equip,
    export_all,
    forge,
    hwm_of,
    refusal_of,
    replay_stubbed,
    resolve,
    resolved,
    root_file,
    serving,
)
from tests.unit.test_registry_fold import CHILD, DAY, INCUMBENT, VENUE, at
from tests.unit.test_registry_replay import (
    ART_SHA,
    World,
    _sha,
    _verdict,
    full_chain,
)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return equip(World(tmp_path))


# --- the child ---


@pytest.fixture
def promoted(world: World) -> Any:
    """The child has taken effect over the root at DAY's LAUNCH (forged: the store cannot hold a
    nomination yet); the export of the whole chain is on disk."""
    chain = forge(full_chain(world))
    export_all(world, chain)
    return chain


def run_child(world: World, chain: Any, *, stub: bool = False, **overrides: Any) -> Any:
    args: dict[str, Any] = {**PIN, **overrides}
    with serving(chain), replay_stubbed() if stub else nullcontext():
        return resolve(world, hwm_of(chain, 1), now=NOW_LATE, **args)


def new_child(world: World, edit: Any) -> Any:
    """Rewrite the child's registry manifest with ``edit`` (applied to the pristine bytes) and
    rebuild the chain and its export on it."""
    base: bytes = world.__dict__.setdefault("pristine_child", world.child_raw)
    raw = edit(base)
    assert raw != base
    for old in world.paths.export_dir().iterdir():
        old.chmod(0o644)
        old.unlink()
    path = world.data / "registry" / "families" / f"{CHILD}.json"
    path.chmod(0o644)
    world.child_raw, world.child_sha = raw, _sha(raw)
    world.put_child_manifest()
    chain = forge(full_chain(world))
    export_all(world, chain)
    return chain


def test_the_child_resolves_through_the_lineage_gate(world: World, promoted: Any) -> None:
    got = resolved(run_child(world, promoted))
    assert (got.family_id, got.origin, got.state) == (CHILD, Origin.CHILD, State.CHAMPION)
    assert got.family_bytes.manifest_source == "registry"
    head = next(r for r in promoted.rows if r.kind is Kind.PROMOTE and r.to_state is State.CHAMPION)
    assert got.authorising_seq == head.venue_seq
    assert (got.export_check, got.verified_export_seq) == ("verified", 1)


def test_child_manifest_equals_committed_root_except_allowlist(world: World) -> None:
    assert isinstance(run_child(world, forge(full_chain(world))), ResolverRefusal)  # no export yet
    for key, edit in (
        ("fee", lambda raw: raw.replace(b'"0.0695"', b'"0.0700"')),
        ("stations", lambda raw: raw.replace(b'"LAX"', b'"LGA"')),
        ("exit", lambda raw: raw.replace(b'"REGISTERED"', b'"REGISTERED",\n  "exit_rule": "x"')),
        ("boundary", lambda raw: raw.replace(b"not_applicable_boundary", b"other_boundary")),
    ):
        chain = new_child(world, edit)
        refused = refusal_of(run_child(world, chain, stub=True))
        assert refused.reason in (
            RefusalReason.CHILD_NOT_EQUAL_ROOT,
            RefusalReason.MANIFEST_INVALID,
        ), key


def test_child_manifest_allowlisted_keys_may_differ(world: World, promoted: Any) -> None:
    """The allowlisted keys (id, prefix, d0 here) differ from the root's and the child resolves."""
    root = parse_family_manifest(world.root_raw, path=root_file(world))
    child = parse_family_manifest(world.child_raw, path=root_file(world))
    assert manifest_equal_modulo_allowlist(child, root) == ()
    assert {"family_id", "trial_id_prefix", "d0_climate_day"} <= {
        f.name
        for f in dataclasses.fields(FamilyManifest)
        if getattr(child, f.name) != getattr(root, f.name)
    }
    assert isinstance(run_child(world, promoted), ResolvedFamily)


def test_equality_covers_new_manifest_fields(world: World) -> None:
    """Every ``FamilyManifest`` field outside the allowlist is compared; so is a future one."""
    root = parse_family_manifest(world.root_raw, path=root_file(world))
    assert CHILD_MANIFEST_ALLOWLIST <= {f.name for f in dataclasses.fields(FamilyManifest)}
    compared = {f.name for f in dataclasses.fields(FamilyManifest)} - CHILD_MANIFEST_ALLOWLIST
    for name in sorted(compared - {"manifest_sha256"}):
        changed = _changed(root, name)
        assert manifest_equal_modulo_allowlist(changed, root) == (name,), name
    assert manifest_equal_modulo_allowlist(_changed(root, "manifest_sha256"), root) == ()

    @dataclasses.dataclass
    class Future:
        name: str

    both = lambda _cls: [*dataclasses.fields(FamilyManifest), Future("future_knob")]
    child, parent = _Bag(future_knob=1, **_attrs(root)), _Bag(future_knob=2, **_attrs(root))
    assert manifest_equal_modulo_allowlist(child, parent, fields_of=both) == ("future_knob",)


class _Bag:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


def _attrs(manifest: FamilyManifest) -> dict[str, Any]:
    return {f.name: getattr(manifest, f.name) for f in dataclasses.fields(FamilyManifest)}


def _changed(manifest: FamilyManifest, name: str) -> FamilyManifest:
    value = getattr(manifest, name)
    other: Any
    if isinstance(value, bool):
        other = not value
    elif isinstance(value, tuple):
        other = (*value, "ZZZ")
    elif isinstance(value, Path):
        other = value / "other"
    elif value is None:
        other = "x"
    elif isinstance(value, str):
        other = value + "x"
    else:
        other = value + 1
    return dataclasses.replace(manifest, **{name: other})


def test_child_regex_root_must_equal_lineage_root(world: World, promoted: Any) -> None:
    """The root the id names must be the root the fold names (ARCH Y6)."""
    row = promoted.rows[1]  # the MINT
    bad = verify_family_bytes(
        row, paths=world.paths, repo_root=world.repo, origin=Origin.CHILD,
        expected_root="pm_us_crh_v4",
    )  # fmt: skip
    assert isinstance(bad, ByteBindingFailure) and bad.reason is RefusalReason.CHILD_ROOT_MISMATCH
    ok = verify_family_bytes(
        row, paths=world.paths, repo_root=world.repo, origin=Origin.CHILD, expected_root=INCUMBENT
    )
    assert isinstance(ok, FamilyBytes)
    copy = world.data / "registry" / "families" / f"{INCUMBENT}.json"
    copy.write_bytes(world.root_raw)  # a registry copy of the root's file, so the read succeeds
    copy.chmod(0o444)
    not_a_child = verify_bound_bytes(
        venue=VENUE, family_id=INCUMBENT, manifest_sha256=world.root_sha,
        artefact_sha256=ART_SHA, paths=world.paths, repo_root=world.repo, origin=Origin.CHILD,
    )  # fmt: skip
    assert isinstance(not_a_child, ByteBindingFailure)
    assert not_a_child.reason is RefusalReason.CHILD_ROOT_MISMATCH  # a root id is no child id


@pytest.mark.parametrize("facet", ["resolver"])
def test_child_d0_and_trial_prefix_pinned(world: World, facet: str) -> None:
    """The first →CHAMPION head binds the child's d0 and prefix (replay judges it first; the
    resolver re-checks)."""
    assert facet == "resolver"
    early = new_child(world, lambda raw: raw.replace(b'"2026-10-20"', b'"2026-10-09"'))
    assert refusal_of(run_child(world, early)).reason is RefusalReason.REPLAY_INVALID
    assert refusal_of(run_child(world, early, stub=True)).reason is RefusalReason.D0_BREACH
    equal = new_child(world, lambda raw: raw.replace(b'"2026-10-20"', f'"{DAY}"'.encode()))
    assert isinstance(run_child(world, equal), ResolvedFamily)  # d0 equal to the date: fine
    bad = new_child(
        world, lambda raw: raw.replace(f"trial/{CHILD}/".encode(), b"trial/pm_us_crh_fq_v1_r0002/")
    )
    assert (
        refusal_of(run_child(world, bad, stub=True)).reason is RefusalReason.TRIAL_PREFIX_MISMATCH
    )


def test_resume_not_subject_to_d0_rule(world: World) -> None:
    """A child halted and RESUMEd after its own d0 date still resolves: d0 binds the first
    →CHAMPION head, not a RESUME (U1)."""
    chain = full_chain(world)
    halted = at("2026-10-12", "12:00")
    chain.add(
        Kind.DEMOTE, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=halted,
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    health = _verdict(
        VerdictKind.HEALTH, family=CHILD, artefact=None, produced=at("2026-10-12", "13:00")
    )
    write_verdict(world.paths, health)
    resumed = at("2026-10-25", "16:45")  # after the child's d0 (2026-10-20)
    resume = chain.add(
        Kind.RESUME, State.CHAMPION, family=CHILD, frm=State.HALTED, ts=resumed,
        cause_verdict_ids=(health.verdict_id,),
    )  # fmt: skip
    forged = forge(chain)
    export_all(world, forged)
    with serving(forged):
        got = resolved(resolve(world, hwm_of(forged, 1), now=at("2026-10-26", "00:00"), **PIN))
    assert (got.family_id, got.authorising_seq) == (CHILD, resume.venue_seq)
    assert got.family_bytes.manifest.d0_climate_day < "2026-10-25"  # the rule would have refused


def test_rollback_to_earlier_child_passes_d0_rule(world: World, promoted: Any) -> None:
    """The d0 and prefix rule is the first →CHAMPION head's alone: a family whose champion epoch a
    later ROLLBACK opened is judged by that old head, never by the rollback's date."""
    manifest = parse_family_manifest(world.child_raw, path=root_file(world))
    assert resolver_mod._first_champion_problem(promoted, manifest) is None
    # the same child, but a rollback date long after its d0 appended to the chain: still none
    later = full_chain(world)
    later.add(
        Kind.ROLLBACK, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        ts=at("2026-12-01", "16:40"), effective_launch_date="2026-12-02",
    )  # fmt: skip
    rolled = forge(later)
    assert resolver_mod._first_champion_problem(rolled, manifest) is None
    # control: the rule does bind the head (a d0 before its date is a breach)
    early = dataclasses.replace(manifest, d0_climate_day="2026-10-09")
    assert resolver_mod._first_champion_problem(rolled, early) is RefusalReason.D0_BREACH


# --- the lineage gate ---


def test_the_shipped_lineage_allowlist_names_no_root(world: World, promoted: Any) -> None:
    got = run_child(world, promoted, lineage_gate=lineage_policy_authorized)
    assert refusal_of(got).reason is RefusalReason.ROOT_NOT_LINEAGE_ALLOWLISTED


@pytest.mark.parametrize(
    ("raised", "reason", "detail"),
    [
        ("not_allowlisted", RefusalReason.ROOT_NOT_LINEAGE_ALLOWLISTED, None),
        ("ruling_missing", RefusalReason.RULING_REFUSED, LiveOrdersRefusal.RULING_MISSING),
        (
            "ruling_sha_mismatch",
            RefusalReason.RULING_REFUSED,
            LiveOrdersRefusal.RULING_SHA_MISMATCH,
        ),
        (
            "ruling_outside_evidence",
            RefusalReason.RULING_REFUSED,
            LiveOrdersRefusal.RULING_OUTSIDE_EVIDENCE,
        ),
    ],
)
def test_lineage_gate_refusals_map_to_closed_reasons(
    world: World, promoted: Any, raised: Any, reason: RefusalReason, detail: Any
) -> None:
    def gate(*_args: object) -> LineagePolicyDecision:
        raise LiveOrdersGateRefusedError(raised, "forced")

    refused = refusal_of(run_child(world, promoted, lineage_gate=gate))
    assert (refused.reason, refused.detail) == (reason, detail)


def test_a_child_declaring_no_policy_ruling_is_ruling_not_policy(
    world: World, promoted: Any
) -> None:
    def gate(*_args: object) -> LineagePolicyDecision:
        return LineagePolicyDecision(authorized=False, reason="no_ruling")

    refused = refusal_of(run_child(world, promoted, lineage_gate=gate))
    assert refused.reason is RefusalReason.RULING_NOT_POLICY
