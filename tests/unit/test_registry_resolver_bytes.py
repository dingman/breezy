"""ARCH-0 seam 8c: the sending resolver, byte binding and the live gates (AC 17 steps 8 to 11).

The root is bound to its committed bytes, its E-14 record and its own live-orders triple; a child
to its registry copy, the committed root (ARCH 4.2) and the lineage-policy gate. Replay (step 6)
already refuses most tampering with ``replay_artefact_mismatch``; each test names which line of
defence it exercises, and the resolver's own refusal is reached with replay stubbed
(``replay_stubbed``), beside the unstubbed run that shows replay refusing first.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Final

import pytest

import breezy.persistence.autonomy.resolver as resolver_mod
from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.byte_binding import (
    ByteBindingFailure,
    FamilyBytes,
    verify_bound_bytes,
    verify_family_bytes,
)
from breezy.persistence.autonomy.family_bytes import read_manifest_facts, write_root_copy
from breezy.persistence.autonomy.fold import Origin
from breezy.persistence.autonomy.hwm import HwmAbsent
from breezy.persistence.autonomy.lineage import RootRecord, root_model_class
from breezy.persistence.autonomy.resolver import (
    ResolvedFamily,
    ResolverRefusal,
    resolve_sending_family,
)
from breezy.persistence.autonomy.schemas import (
    Kind,
    LiveOrdersRefusal,
    RefusalReason,
    State,
)
from breezy.persistence.family_manifest import FamilyManifest, parse_family_manifest
from breezy.persistence.live_orders_gate import (
    LineagePolicyDecision,
    LiveOrdersDecision,
    live_orders_authorized,
)
from tests.support.entry_points import SRC_DIR
from tests.unit.registry_resolver_world import (
    ENGINE_PINS,
    NOW_EARLY,
    NOW_LATE,
    PIN,
    POLICY_OK,
    equip,
    export_all,
    forge,
    hwm_of,
    populate,
    refusal_of,
    replay_stubbed,
    resolve,
    resolved,
    rewrite,
    root_chain,
    root_file,
    serving,
)
from tests.unit.test_registry_fold import CHILD, DAY, INCUMBENT, SHA_B, VENUE, Chain, at
from tests.unit.test_registry_replay import (
    ART_SHA,
    ARTEFACT,
    KIND,
    World,
    _sha,
)
from tests.unit.test_registry_replay_roles import NEXT_DAY, drill_episode

AUTONOMY_SRC: Final = SRC_DIR / "breezy" / "persistence" / "autonomy"
RESOLVER_SOURCE: Final = AUTONOMY_SRC / "resolver.py"


@pytest.fixture
def world(tmp_path: Path) -> World:
    return equip(World(tmp_path))


def resolve_root(world: World, *, stub: bool = False, **overrides: Any) -> Any:
    """Resolve the root-only chain held by the real registry database."""
    chain = populate(world, root_chain(world)) if not _populated(world) else _stored(world)
    with replay_stubbed() if stub else nullcontext():
        return resolve(world, hwm_of(chain), now=NOW_EARLY, **overrides)


def _populated(world: World) -> bool:
    return world.paths.registry_db().exists()


def _stored(world: World) -> Any:
    from breezy.persistence.autonomy.chain import verify_venue_chain
    from breezy.persistence.autonomy.registry_export import RegistryReader

    reader = RegistryReader(world.paths, busy_timeout_ms=0)
    return verify_venue_chain(reader.read_venue_rows(VENUE), VENUE)


def record_file(world: World) -> Path:
    return world.paths.root_record(root_model_class(KIND), ART_SHA, INCUMBENT)


# --- the root: bytes ------------------------------------------------------------------------------


def test_resolver_binds_bytes_to_row(world: World) -> None:
    """The resolved bytes are the row's: the manifest's sha is the row's, the artefact's is the
    row's, and a changed byte of either is refused (replay first, then the resolver's own check)."""
    got = resolved(resolve_root(world))
    assert got.family_bytes.manifest_raw == world.root_raw
    assert got.family_bytes.artefact_raw == ARTEFACT
    assert hashlib.sha256(got.family_bytes.manifest_raw).hexdigest() == world.root_sha
    world.put_artefact(ARTEFACT + b" ")
    assert refusal_of(resolve_root(world)).reason is RefusalReason.REPLAY_ARTEFACT_MISMATCH
    assert refusal_of(resolve_root(world, stub=True)).reason is RefusalReason.ARTEFACT_SHA_MISMATCH


def test_root_manifest_must_equal_committed_bytes(world: World) -> None:
    """A committed root edited after the row (even whitespace) is no sender (E-14 rule 7)."""
    assert isinstance(resolve_root(world), ResolvedFamily)  # control
    rewrite(root_file(world), world.root_raw + b"\n")
    assert refusal_of(resolve_root(world)).reason is RefusalReason.REPLAY_ARTEFACT_MISMATCH
    assert refusal_of(resolve_root(world, stub=True)).reason is RefusalReason.MANIFEST_SHA_MISMATCH


def test_a_root_manifest_is_never_read_from_a_registry_copy(world: World) -> None:
    """E-14 rule 3a (A6d-A2 M2): with the committed file gone, a registry copy does not serve."""
    assert isinstance(resolve_root(world), ResolvedFamily)
    copies = world.data / "registry" / "families"
    copies.mkdir(parents=True, exist_ok=True)
    (copies / f"{INCUMBENT}.json").write_bytes(world.root_raw)
    (copies / f"{INCUMBENT}.json").chmod(0o444)
    root_file(world).unlink()
    assert refusal_of(resolve_root(world, stub=True)).reason is RefusalReason.MANIFEST_UNREADABLE


def test_missing_manifest_dir_is_manifest_unreadable(world: World) -> None:
    populate(world, root_chain(world))
    for child in root_file(world).parent.iterdir():
        if child.is_file():
            child.unlink()
    root_file(world).parent.rmdir() if not any(root_file(world).parent.iterdir()) else None
    got = refusal_of(resolve_root(world, stub=True))
    assert got.reason is RefusalReason.MANIFEST_UNREADABLE


def test_registry_paths_refuse_symlinks(world: World) -> None:
    """A symlink where a file is read is refused, by every reader, as unreadable."""
    populate(world, root_chain(world))
    assert isinstance(resolve_root(world), ResolvedFamily)  # control
    cases = {
        "manifest": (root_file(world), RefusalReason.MANIFEST_UNREADABLE),
        "artefact": (
            world.paths.artefact_file(root_model_class(KIND), ART_SHA),
            RefusalReason.ARTEFACT_UNREADABLE,
        ),
        "record": (record_file(world), RefusalReason.ROOT_RECORD_MISMATCH),
    }
    for target, (path, reason) in cases.items():
        elsewhere = world.data.parent / f"elsewhere_{target}"
        original = path.read_bytes()
        elsewhere.write_bytes(original)
        path.parent.chmod(0o755)
        path.unlink()
        path.symlink_to(elsewhere)
        assert isinstance(resolve_root(world), ResolverRefusal), target  # replay or the resolver
        assert refusal_of(resolve_root(world, stub=True)).reason is reason, target
        path.unlink()  # restore the real file for the next case
        path.write_bytes(original)
        path.chmod(0o444)
    assert isinstance(resolve_root(world), ResolvedFamily)  # control: the world is whole again


def test_a_symlinked_artefact_directory_is_refused(world: World) -> None:
    populate(world, root_chain(world))
    store = world.data / "derived" / "artefacts"
    real = store.parent / "artefacts_real"
    store.rename(real)
    store.symlink_to(real)
    assert refusal_of(resolve_root(world, stub=True)).reason is RefusalReason.ARTEFACT_UNREADABLE


@pytest.mark.parametrize("facet", ["resolver"])
def test_verify_and_load_share_bytes(world: World, facet: str) -> None:
    """The resolver, ``verify_family_bytes`` and the manifest-facts reader answer from one file."""
    assert facet == "resolver"
    got = resolved(resolve_root(world))
    row = _stored(world).rows[0]
    again = verify_family_bytes(row, paths=world.paths, repo_root=world.repo, origin=Origin.ROOT)
    assert isinstance(again, FamilyBytes) and again == got.family_bytes
    facts = read_manifest_facts(
        INCUMBENT, world.root_sha, paths=world.paths, repo_root=world.repo, repo_only=True
    )
    assert facts is not None and facts.manifest_sha256 == got.family_bytes.manifest_sha256
    stored = (world.data / got.family_bytes.artefact_store_relpath).read_bytes()
    assert stored == got.family_bytes.artefact_raw


def test_the_manifest_must_name_the_rows_family_and_venue(world: World) -> None:
    populate(world, root_chain(world))
    for key, bad in (("family_id", "pm_us_crh_other"), ("venue", "kalshi")):
        raw = world.root_raw.replace(f'"{key}": "'.encode(), f'"{key}": "{bad}__'.encode())
        raw = world.root_raw.replace(json.loads(world.root_raw)[key].encode(), bad.encode(), 1)
        result = verify_bound_bytes(
            venue=VENUE, family_id=INCUMBENT, manifest_sha256=_sha(raw), artefact_sha256=ART_SHA,
            paths=world.paths, repo_root=_repo_with(world, raw), origin=Origin.ROOT,
        )  # fmt: skip
        assert isinstance(result, ByteBindingFailure)
        assert result.reason is RefusalReason.MANIFEST_IDENTITY_MISMATCH, key


def _repo_with(world: World, raw: bytes) -> Path:
    """The world's repo with the root manifest replaced by ``raw``."""
    rewrite(root_file(world), raw)
    return world.repo


def test_manifest_identity_must_match_row(world: World) -> None:
    """A venue edit is not caught by replay (its facts reader checks the family only)."""
    populate(world, root_chain(world))
    raw = world.root_raw.replace(b'"polymarket_us"', b'"kalshi"')
    assert raw != world.root_raw
    rewrite(root_file(world), raw)
    chain = root_chain(world)
    chain.rows[0] = dataclasses.replace(chain.rows[0], manifest_sha256=_sha(raw))
    forged = forge(chain)
    with serving(forged):
        refused = refusal_of(resolve(world, hwm_of(forged), now=NOW_EARLY))
    assert refused.reason is RefusalReason.MANIFEST_IDENTITY_MISMATCH


@pytest.mark.parametrize(
    ("edit", "reason"),
    [
        (
            lambda raw: raw.replace(b"REGISTERED", b"DRAFT_NOT_REGISTERED"),
            RefusalReason.MANIFEST_DRAFT,
        ),
        (
            lambda raw: raw.replace(
                b"f4b5d9df270599f55684e6ef4cb18fc440594cb23b92ecdf8bbec3dec1adc02f", b"0" * 64
            ),
            RefusalReason.MANIFEST_UNPINNED,
        ),
        (lambda raw: raw.replace(b'"stations"', b'"stationz"'), RefusalReason.MANIFEST_INVALID),
        (lambda raw: b"not json", RefusalReason.MANIFEST_INVALID),
    ],
    ids=["draft", "unpinned", "invalid-key", "not-json"],
)
def test_draft_or_unpinned_manifest_refused(world: World, edit: Any, reason: RefusalReason) -> None:
    raw = edit(world.root_raw)
    assert raw != world.root_raw
    result = verify_bound_bytes(
        venue=VENUE, family_id=INCUMBENT, manifest_sha256=_sha(raw), artefact_sha256=ART_SHA,
        paths=world.paths, repo_root=_repo_with(world, raw), origin=Origin.ROOT,
    )  # fmt: skip
    assert isinstance(result, ByteBindingFailure) and result.reason is reason


def test_resolver_runs_prereg_check_on_source_dir(world: World) -> None:
    """A mechanism-test marker in the manifest directory makes it PREREG-ineligible."""
    populate(world, root_chain(world))
    assert isinstance(resolve_root(world), ResolvedFamily)  # control
    marker = root_file(world).parent / "mechanism_trials.csv"
    marker.write_text("mechanism_test_only\ntrue\n", encoding="utf-8")
    assert refusal_of(resolve_root(world, stub=True)).reason is RefusalReason.PREREG_INELIGIBLE


# --- the root: the E-14 record ---


def _record_wire(world: World, **over: Any) -> dict[str, Any]:
    wire = RootRecord(
        family_id=INCUMBENT, manifest_sha256=world.root_sha, artefact_sha256=ART_SHA,
        committed_path=f"deploy/families/{INCUMBENT}.json",
    ).to_wire()  # fmt: skip
    wire.update(over)
    return wire


@pytest.mark.parametrize(
    "over",
    [
        {"family_id": "pm_us_crh_v4"},
        {"manifest_sha256": "1" * 64},
        {"artefact_sha256": "2" * 64},
        {"committed_path": "deploy/families/other.json"},
        {"extra": 1},
        {"schema": "root/v2"},
    ],
    ids=["family", "manifest", "artefact", "path", "extra-key", "schema"],
)
def test_root_record_identity_checked(world: World, over: dict[str, Any]) -> None:
    populate(world, root_chain(world))
    assert isinstance(resolve_root(world), ResolvedFamily)  # control
    path = record_file(world)
    path.parent.chmod(0o755)
    rewrite(path, json.dumps(_record_wire(world, **over), sort_keys=True).encode())
    assert refusal_of(resolve_root(world, stub=True)).reason is RefusalReason.ROOT_RECORD_MISMATCH


def test_a_missing_root_record_is_a_mismatch(world: World) -> None:
    populate(world, root_chain(world))
    path = record_file(world)
    path.parent.chmod(0o755)
    path.unlink()
    assert refusal_of(resolve_root(world, stub=True)).reason is RefusalReason.ROOT_RECORD_MISMATCH


def test_rollback_to_root_reads_content_addressed_copy(world: World) -> None:
    """The closing ROLLBACK of a drill makes the root CHAMPION again: it stands on the store's
    content-addressed artefact (the repo carries no density file at all), and on the committed
    manifest, with its authorising row the ROLLBACK."""
    chain = forge(drill_episode(world))
    export_all(world, chain)
    later = at(NEXT_DAY, "17:30")
    with serving(chain):
        got = resolved(resolve(world, hwm_of(chain, 1), now=later, **PIN))
    assert (got.family_id, got.origin) == (INCUMBENT, Origin.ROOT)
    rollback = next(r for r in chain.rows if r.kind is Kind.ROLLBACK)
    assert got.authorising_seq == rollback.venue_seq
    assert got.family_bytes.artefact_store_relpath == (
        f"derived/artefacts/{root_model_class(KIND)}/{ART_SHA}/artefact.json"
    )
    assert got.family_bytes.manifest_source == "deploy"
    assert not (world.repo / "deploy" / "families" / "artefacts").exists()


# --- the root: the live-orders gate ---


def test_root_resolves_under_live_orders_allowlist(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fq_v1 resolves by its own allowlisted triple, asked with ``permit_present=False``."""
    seen: list[dict[str, Any]] = []
    real = live_orders_authorized

    def spy(manifest: FamilyManifest, repo_root: Path, **kwargs: Any) -> LiveOrdersDecision:
        seen.append(kwargs)
        return real(manifest, repo_root, **kwargs)

    monkeypatch.setattr(resolver_mod, "live_orders_authorized", spy)
    assert isinstance(resolve_root(world), ResolvedFamily)
    assert seen == [{"permit_present": False}]


@pytest.mark.parametrize("facet", ["resolver"])
def test_root_admit_requires_own_allowlist_triple(world: World, facet: str) -> None:
    """A ROOT_ADMIT root is authorised only by its own triple: fq_v1 re-admitted resolves, a
    root the allowlist does not name is ``ruling_refused`` (not_allowlisted)."""
    assert facet == "resolver"
    own = Chain()
    head = own.add(
        Kind.ROOT_ADMIT, State.CHAMPION, family=INCUMBENT, manifest_sha256=world.root_sha,
        artefact_sha256=ART_SHA, effective_launch_date=DAY,
    )  # fmt: skip
    own.activate(head, ts=at(DAY, "16:45"))
    admitted = forge(own)
    other = _other_root(world)
    export_all(world, admitted)
    with serving(admitted), replay_stubbed():
        assert isinstance(resolve(world, hwm_of(admitted, 1), now=NOW_LATE, **PIN), ResolvedFamily)
    for old in world.paths.export_dir().iterdir():
        old.chmod(0o644)
        old.unlink()
    export_all(world, other)
    with serving(other), replay_stubbed():
        refused = refusal_of(resolve(world, hwm_of(other, 1), now=NOW_LATE, **PIN))
    assert refused.reason is RefusalReason.RULING_REFUSED
    assert refused.detail is LiveOrdersRefusal.NOT_ALLOWLISTED


def _other_root(world: World) -> Any:
    """A committed root the live-orders allowlist does not name, ROOT_ADMITted."""
    name = "pm_us_crh_other"
    raw = world.root_raw.replace(INCUMBENT.encode(), name.encode())
    (world.repo / "deploy" / "families" / f"{name}.json").write_bytes(raw)
    record = RootRecord(
        family_id=name, manifest_sha256=_sha(raw), artefact_sha256=ART_SHA,
        committed_path=f"deploy/families/{name}.json",
    )  # fmt: skip
    write_root_copy(world.paths, record=record, artefact_raw=ARTEFACT, composition_kind=KIND)
    chain = Chain()
    head = chain.add(
        Kind.ROOT_ADMIT, State.CHAMPION, family=name, manifest_sha256=_sha(raw),
        artefact_sha256=ART_SHA, effective_launch_date=DAY,
    )  # fmt: skip
    chain.activate(head, ts=at(DAY, "16:45"))
    return forge(chain)


def test_root_named_like_child_is_not_routed_as_child(world: World) -> None:
    """The route is the fold's ``origin``, never the id's shape: a BOOTSTRAPped root called
    ``<root>_r0001`` meets the live-orders gate, not the lineage gate."""
    raw = world.child_raw
    (world.repo / "deploy" / "families" / f"{CHILD}.json").write_bytes(raw)
    record = RootRecord(
        family_id=CHILD, manifest_sha256=_sha(raw), artefact_sha256=ART_SHA,
        committed_path=f"deploy/families/{CHILD}.json",
    )  # fmt: skip
    write_root_copy(world.paths, record=record, artefact_raw=ARTEFACT, composition_kind=KIND)
    chain = Chain()
    chain.add(
        Kind.BOOTSTRAP, State.CHAMPION, family=CHILD, manifest_sha256=_sha(raw),
        artefact_sha256=ART_SHA,
    )  # fmt: skip
    forged = forge(chain)
    asked: list[str] = []

    def lineage(*_args: object) -> LineagePolicyDecision:
        asked.append("lineage")
        return POLICY_OK

    with serving(forged), replay_stubbed():
        refused = refusal_of(
            resolve(world, hwm_of(forged), now=NOW_EARLY, lineage_gate=lineage, **PIN)
        )
    assert asked == []  # a root never meets the lineage gate
    assert refused.reason is RefusalReason.RULING_REFUSED
    assert refused.detail is LiveOrdersRefusal.NOT_ALLOWLISTED  # the live-orders gate refused it


def test_root_ruling_reasons_map_to_live_orders_refusal(world: World) -> None:
    """Each live-orders refusal is carried as a closed ``LiveOrdersRefusal`` detail."""
    manifest = parse_family_manifest(world.root_raw, path=root_file(world))
    assert resolver_mod._root_gate(manifest, world.repo) is None  # control: permit_absent passes
    ruling = world.repo / "deploy" / "families" / "rulings" / f"{_ruling_id()}.md"
    original = ruling.read_bytes()
    rewrite(ruling, original + b" ")
    tampered = resolver_mod._root_gate(manifest, world.repo)
    assert tampered == ResolverRefusal(
        RefusalReason.RULING_REFUSED, LiveOrdersRefusal.RULING_SHA_MISMATCH
    )
    ruling.unlink()
    missing = resolver_mod._root_gate(manifest, world.repo)
    assert missing == ResolverRefusal(
        RefusalReason.RULING_REFUSED, LiveOrdersRefusal.RULING_MISSING
    )
    undeclared = parse_family_manifest(
        world.root_raw.replace(b',\n  "live_orders_ruling": "' + _ruling_id().encode() + b'"', b""),
        path=root_file(world),
    )
    assert undeclared.live_orders_ruling is None
    assert resolver_mod._root_gate(undeclared, world.repo) == ResolverRefusal(
        RefusalReason.NO_LIVE_ORDERS_RULING
    )


def _ruling_id() -> str:
    from tests.unit.registry_resolver_world import RULING

    return RULING


def test_the_gate_is_asked_for_a_ruling_and_never_for_a_permit(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only ``permit_absent`` passes: a gate that says ``ok`` (a permit) is refused too."""
    monkeypatch.setattr(
        resolver_mod,
        "live_orders_authorized",
        lambda *_a, **_k: LiveOrdersDecision(enabled=True, reason="ok", ruling_sha256="a" * 64),
    )
    refused = refusal_of(resolve_root(world))
    assert refused.reason is RefusalReason.RULING_REFUSED
    assert refused.detail is LiveOrdersRefusal.OK


def test_resolver_never_returns_enabled_or_permit(world: World) -> None:
    names = {f.name for f in dataclasses.fields(ResolvedFamily)}
    assert not {n for n in names if "enabled" in n.replace("entries_allowed", "") or "permit" in n}
    tree = ast.parse(RESOLVER_SOURCE.read_text(encoding="utf-8"))
    permit_keywords = [
        ast.unparse(kw.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        for kw in n.keywords
        if kw.arg == "permit_present"
    ]
    assert permit_keywords == ["False"]  # the one call site, and it never says True
    assert "OrderSubmissionPermit" not in RESOLVER_SOURCE.read_text(encoding="utf-8")
    got = resolved(resolve_root(world))
    assert not hasattr(got, "enabled") and not hasattr(got, "permit")


# --- engine pins and live-gate routing ---


def test_every_production_resolve_refuses_the_unpinned_engine(world: World) -> None:
    """At ARCH-0 ``pins.ENGINE_SOURCE_SHA256`` is empty: the public entry never resolves."""
    chain = populate(world, root_chain(world))
    got = resolve_sending_family(
        venue=VENUE, paths=world.paths, repo_root=world.repo, now_ns=NOW_EARLY,
        hwm=hwm_of(chain),
    )  # fmt: skip
    assert refusal_of(got).reason is RefusalReason.ENGINE_CODE_UNPINNED
    assert pins.ENGINE_SOURCE_SHA256 == frozenset() and pins.REVOKED_SOURCE_SHA256 == frozenset()


def test_a_revoked_engine_code_is_refused_even_when_pinned(world: World) -> None:
    assert isinstance(resolve_root(world, _engine_pins=frozenset({SHA_B})), ResolvedFamily)
    got = resolve_root(world, _engine_pins=frozenset({SHA_B}), _revoked_pins=frozenset({SHA_B}))
    assert refusal_of(got).reason is RefusalReason.ENGINE_CODE_REVOKED
    other = resolve_root(world, _engine_pins=frozenset({"c" * 64}))
    assert refusal_of(other).reason is RefusalReason.ENGINE_CODE_UNPINNED
    assert ENGINE_PINS == frozenset({SHA_B})


def test_live_gate_routing_reads_manifest_kind(world: World) -> None:
    """A manifest of a kind outside ``LIVE_GATE_ROUTED_KINDS`` can never send."""
    kind = "current_rung_hold"
    raw = world.root_raw.replace(KIND.encode(), kind.encode())
    manifest = parse_family_manifest(raw, path=root_file(world))
    assert manifest.composition_kind == kind and not resolver_mod._is_routed(manifest)
    real = parse_family_manifest(world.root_raw, path=root_file(world))
    assert resolver_mod._is_routed(real)


@pytest.mark.parametrize("facet", ["resolver"])
def test_registry_champion_requires_live_orders_gate_for_every_kind(
    world: World, facet: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever the manifest's kind, the gate runs before a champion is built, and a kind the
    gate does not route is refused after it: only ``forecast_quantile_ladder`` resolves."""
    assert facet == "resolver"
    calls: list[str] = []
    real = resolver_mod._root_gate

    def spy(manifest: FamilyManifest, repo_root: Path) -> ResolverRefusal | None:
        calls.append(manifest.composition_kind)
        return real(manifest, repo_root)

    monkeypatch.setattr(resolver_mod, "_root_gate", spy)
    kinds = (
        "forecast_quantile_ladder",
        "current_rung_hold",
        "continuous_rung_hold",
        "forecast_ladder",
    )
    for kind in kinds:
        raw = (
            world.root_raw if kind == KIND else world.root_raw.replace(KIND.encode(), kind.encode())
        )
        rewrite(root_file(world), raw)
        if kind != KIND:
            record = RootRecord(
                family_id=INCUMBENT, manifest_sha256=_sha(raw), artefact_sha256=ART_SHA,
                committed_path=f"deploy/families/{INCUMBENT}.json",
            )  # fmt: skip
            write_root_copy(
                world.paths, record=record, artefact_raw=ARTEFACT, composition_kind=kind
            )
        chain = Chain()
        chain.add(
            Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, manifest_sha256=_sha(raw),
            artefact_sha256=ART_SHA,
        )  # fmt: skip
        forged = forge(chain)
        with serving(forged):
            got = resolve(world, hwm_of(forged), now=NOW_EARLY)
        if kind in pins.LIVE_GATE_ROUTED_KINDS:
            assert isinstance(got, ResolvedFamily), kind
        else:
            assert refusal_of(got).reason is RefusalReason.KIND_NOT_LIVE_GATE_ROUTED, kind
    assert calls == list(kinds)  # the gate ran for every kind, routed or not
    tree = ast.parse(RESOLVER_SOURCE.read_text(encoding="utf-8"))
    bind = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_bind_sender"
    )
    sites = sorted(
        (n.lineno, n.col_offset, n.func.id)
        for n in ast.walk(bind)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in {"_root_gate", "_child_gate", "_is_routed", "ResolvedFamily"}
    )
    assert [name for _, _, name in sites][-1] == "ResolvedFamily"  # built last, after every gate
    assert {name for _, _, name in sites} == {
        "_root_gate",
        "_child_gate",
        "_is_routed",
        "ResolvedFamily",
    }


def test_a_hwm_absent_resolve_never_reaches_the_bytes(world: World) -> None:
    """The HWM is checked before any byte is read: a refusal there reads no manifest."""
    populate(world, root_chain(world))
    root_file(world).unlink()  # would be manifest_unreadable if it were reached
    got = refusal_of(resolve(world, HwmAbsent(), now=NOW_EARLY))
    assert got.reason is RefusalReason.HWM_ABSENT
    assert NOW_LATE > NOW_EARLY
