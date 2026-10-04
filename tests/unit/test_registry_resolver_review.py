"""ARCH-0 seam 8c review fixes (A8c-R1, R3, R6): each ruling's regression test.

R2 (the consumer guard) lives in ``test_registry_resolver_guards`` and ``test_autonomy_contracts``;
R5 (the budget op count) in ``test_registry_resolver``.
"""

from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path
from typing import Any, Final

import pytest

import breezy.persistence.autonomy.byte_binding as byte_binding_mod
import breezy.persistence.autonomy.family_bytes as family_bytes_mod
import breezy.persistence.autonomy.replay as replay_mod
import breezy.persistence.autonomy.resolver as resolver_mod
from breezy.persistence.autonomy.byte_binding import ByteBindingFailure, verify_bound_bytes
from breezy.persistence.autonomy.fold import Origin, fold
from breezy.persistence.autonomy.fold_pairs import PairStatus
from breezy.persistence.autonomy.registry_export import RegistryReader
from breezy.persistence.autonomy.resolver import (
    FAMILY_SOURCE_ENV,
    RESOLVE_BUSY_TIMEOUT_MS,
    FamilySource,
    ResolvedFamily,
    ResolverRefusal,
    read_family_source,
    resolve_sending_family,
)
from breezy.persistence.autonomy.schemas import (
    Kind,
    LiveOrdersRefusal,
    RefusalReason,
    State,
    UnreadableReason,
)
from breezy.persistence.family_manifest import parse_family_manifest
from breezy.persistence.live_orders_gate import LineagePolicyDecision
from tests.unit.registry_resolver_world import (
    NOW_EARLY,
    PIN,
    equip,
    export_all,
    forge,
    hwm_of,
    populate,
    refusal_of,
    replay_stubbed,
    resolve,
    rewrite,
    root_chain,
    root_file,
    serving,
)
from tests.unit.test_registry_fold import CHILD, DAY, INCUMBENT, VENUE, at
from tests.unit.test_registry_replay import (
    ART_SHA,
    FORWARD,
    OFFLINE,
    World,
    full_chain,
    nominate,
    start,
)
from tests.unit.test_registry_resolver_child import new_child, run_child

LATE_DATE: Final = "2026-10-25"  # after the child's d0 (2026-10-20)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return equip(World(tmp_path))


# --- A8c-R1: a child is judged against the pinned root bytes ---


def _fee_edit(raw: bytes) -> bytes:
    return raw.replace(b'"0.0695"', b'"0.0700"')


def test_an_edited_root_file_with_a_matching_child_is_refused(world: World) -> None:
    """The child equals the *edited* committed root on every field, so only the root's pinned sha
    can tell the root file was changed after the fold bound it. Replay is stubbed (it reads the
    root by its sha and would refuse first, so the resolver's own bind is isolated)."""
    chain = new_child(world, _fee_edit)  # the child carries the fee edit already
    control = run_child(world, chain, stub=True)
    assert isinstance(control, ResolverRefusal)  # the root file still has the old fee
    rewrite(
        root_file(world), _fee_edit(world.root_raw)
    )  # now child == committed root, modulo allowlist
    refused = refusal_of(run_child(world, chain, stub=True))
    assert refused.reason is RefusalReason.MANIFEST_SHA_MISMATCH


def test_the_unedited_root_with_its_pinned_sha_still_resolves(world: World) -> None:
    chain = forge(full_chain(world))
    export_all(world, chain)
    assert isinstance(run_child(world, chain), ResolvedFamily)


def test_verify_bound_bytes_checks_the_root_sha_it_is_given(world: World) -> None:
    chain = forge(full_chain(world))
    row = chain.rows[1]  # the MINT: carries the child's manifest and artefact
    args: dict[str, Any] = {
        "venue": VENUE, "family_id": CHILD, "manifest_sha256": world.child_sha,
        "artefact_sha256": ART_SHA, "paths": world.paths, "repo_root": world.repo,
        "origin": Origin.CHILD,
    }  # fmt: skip
    assert row.family_id == CHILD
    ok = verify_bound_bytes(**args, expected_root_manifest_sha256=world.root_sha)
    assert not isinstance(ok, ByteBindingFailure)
    bad = verify_bound_bytes(**args, expected_root_manifest_sha256="0" * 64)
    assert isinstance(bad, ByteBindingFailure)
    assert bad.reason is RefusalReason.MANIFEST_SHA_MISMATCH


# --- A8c-R3: the resolver never raises ---


@pytest.mark.parametrize("venue", ["Not A Venue!", "", None, 7])
def test_a_malformed_venue_is_registry_unreadable_venue_malformed(world: World, venue: Any) -> None:
    refused = refusal_of(
        resolve(world, hwm_of(populate(world, root_chain(world))), now=NOW_EARLY, venue=venue)
    )
    assert (refused.reason, refused.detail) == (
        RefusalReason.REGISTRY_UNREADABLE,
        UnreadableReason.VENUE_MALFORMED,
    )


@pytest.mark.parametrize("error", [OSError("gone"), RuntimeError("boom")])
def test_a_ruling_file_failure_in_the_root_gate_is_ruling_missing(
    world: World, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    rooted = populate(world, root_chain(world))

    def raising(*_args: object, **_kwargs: object) -> object:
        raise error

    monkeypatch.setattr(resolver_mod, "live_orders_authorized", raising)
    refused = refusal_of(resolve(world, hwm_of(rooted), now=NOW_EARLY))
    assert (refused.reason, refused.detail) == (
        RefusalReason.RULING_REFUSED,
        LiveOrdersRefusal.RULING_MISSING,
    )


@pytest.mark.parametrize("error", [OSError("gone"), RuntimeError("boom")])
def test_a_ruling_file_failure_in_the_lineage_gate_is_ruling_missing(
    world: World, error: Exception
) -> None:
    chain = forge(full_chain(world))
    export_all(world, chain)

    def gate(*_args: object) -> LineagePolicyDecision:
        raise error

    refused = refusal_of(run_child(world, chain, lineage_gate=gate))
    assert (refused.reason, refused.detail) == (
        RefusalReason.RULING_REFUSED,
        LiveOrdersRefusal.RULING_MISSING,
    )


def test_the_shadow_step_set_stays_the_one_documented_raise() -> None:
    doc = inspect.getdoc(resolver_mod) or ""
    assert "never raises" in doc and "8d" in doc
    assert "except" in doc.split("never raises", 1)[1].split("\n\n", 1)[0]


# --- A8c-R6 ---


def _lapsed_then_effective(world: World) -> Any:
    """A first →CHAMPION head whose pair lapsed (no ACTIVATE), then a second one that takes effect
    on a later date. Only the second is the family's first *effective* champion head."""
    chain = start(world)
    nominate(chain)
    cited = (FORWARD.verdict_id, OFFLINE.verdict_id)
    first = chain.add(
        Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=DAY, manifest_sha256=world.child_sha, cause_verdict_ids=cited,
    )  # fmt: skip
    chain.add(
        Kind.SUPERSEDE, State.CHALLENGER, family=INCUMBENT, frm=State.CHAMPION,
        paired_transition_id=first.transition_id, effective_launch_date=DAY,
    )  # fmt: skip
    second = chain.add(
        Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=LATE_DATE, manifest_sha256=world.child_sha, cause_verdict_ids=cited,
        ts=at("2026-10-10", "12:00"),
    )  # fmt: skip
    chain.add(
        Kind.SUPERSEDE, State.CHALLENGER, family=INCUMBENT, frm=State.CHAMPION,
        paired_transition_id=second.transition_id, effective_launch_date=LATE_DATE,
        ts=at("2026-10-10", "12:01"),
    )  # fmt: skip
    chain.activate(second, ts=at(LATE_DATE, "16:45"))
    return forge(chain)


def test_the_d0_rule_skips_a_head_whose_pair_lapsed(world: World) -> None:
    """The lapsed head (date DAY) passes the d0 rule and the effective head (date after d0)
    breaches it: judging the lapsed one first would let the breach through."""
    chain = _lapsed_then_effective(world)
    export_all(world, chain)
    now = at("2026-10-26", "00:00")
    view = fold(chain.rows, VENUE, now)
    assert [p.status for p in view.pairs] == [PairStatus.LAPSED, PairStatus.EFFECTIVE]  # type: ignore[union-attr]
    with serving(chain), replay_stubbed():
        refused = refusal_of(resolve(world, hwm_of(chain, 1), now=now, **PIN))
    assert refused.reason is RefusalReason.D0_BREACH


@pytest.mark.parametrize("status", [PairStatus.VOIDED, PairStatus.LAPSED])
def test_a_voided_or_lapsed_head_is_never_the_first_champion_head(
    world: World, status: PairStatus
) -> None:
    chain = _lapsed_then_effective(world)
    manifest = parse_family_manifest(world.child_raw, path=root_file(world))
    view = fold(chain.rows, VENUE, at("2026-10-26", "00:00"))
    pairs = tuple(
        dataclasses.replace(p, status=status) if i == 0 else p
        for i, p in enumerate(view.pairs)  # type: ignore[union-attr]
    )
    first_problem = resolver_mod._first_champion_problem(chain, manifest, pairs)
    assert first_problem is RefusalReason.D0_BREACH
    effective_first = tuple(dataclasses.replace(p, status=PairStatus.EFFECTIVE) for p in pairs)
    assert resolver_mod._first_champion_problem(chain, manifest, effective_first) is None


def test_the_resolver_takes_a_busy_timeout_defaulting_to_the_pinned_value(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert RESOLVE_BUSY_TIMEOUT_MS == 2000
    default = inspect.signature(resolve_sending_family).parameters["busy_timeout_ms"].default
    assert default == RESOLVE_BUSY_TIMEOUT_MS
    seen: list[int] = []

    class Spy(RegistryReader):
        def __init__(self, paths: Any, *, busy_timeout_ms: int) -> None:
            seen.append(busy_timeout_ms)
            super().__init__(paths, busy_timeout_ms=busy_timeout_ms)

    monkeypatch.setattr(resolver_mod, "RegistryReader", Spy)
    rooted = populate(world, root_chain(world))
    assert isinstance(resolve(world, hwm_of(rooted), now=NOW_EARLY), ResolvedFamily)
    assert isinstance(
        resolve(world, hwm_of(rooted), now=NOW_EARLY, busy_timeout_ms=7), ResolvedFamily
    )
    assert seen == [RESOLVE_BUSY_TIMEOUT_MS, 7]


def test_an_empty_family_source_is_unset() -> None:
    assert read_family_source({FAMILY_SOURCE_ENV: ""}) is FamilySource.UNSET
    assert read_family_source({}) is FamilySource.UNSET


def test_replay_probes_artefacts_through_the_shared_memoised_read(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real = byte_binding_mod.probe_artefact

    def spy(kind: str, sha: str, *, read: Any) -> Any:
        calls.append(kind)
        return real(kind, sha, read=read)

    monkeypatch.setattr(replay_mod, "probe_artefact", spy)
    assert isinstance(world.replay(full_chain(world)), replay_mod.ReplayOk)
    assert calls


def test_one_unreadable_tuple_serves_the_manifest_reads() -> None:
    assert byte_binding_mod.__dict__["_UNREADABLE"] is family_bytes_mod._UNREADABLE
    source = inspect.getsource(byte_binding_mod)
    assert "except (SingleReadRefused, FamilyManifestError, ValueError, OSError)" not in source


def test_entries_allowed_is_documented_as_no_trade_permit_and_the_export_race_self_heals() -> None:
    assert "NOT a trade permit" in (inspect.getdoc(ResolvedFamily) or "")
    assert "self-heals" in (inspect.getdoc(resolver_mod) or "")


def test_no_resolver_test_patches_the_chain_read_step() -> None:
    """A8c-R5: only ``RegistryReader.read_venue_rows`` is patched, so step 2 always runs."""
    needle = '"_read_chain"'
    offenders = [
        p.name for p in sorted(Path(__file__).parent.glob("*resolver*.py"))
        if p.name != Path(__file__).name and needle in p.read_text(encoding="utf-8")
    ]  # fmt: skip
    assert offenders == []
