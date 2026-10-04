"""Shared builders for the seam 8c resolver tests (``test_registry_resolver*.py``).

A resolve reads a real registry database, an export directory, a repo (the committed root manifest
and its sha-pinned ruling) and the content-addressed store. ``populate`` writes a chain through the
real ``RegistryStore`` (a fixture stage, so a widening row is storable); ``resolve`` then asks the
private ``_resolve`` with the canonical stage and injected engine pins, because production ships no
engine pin (every production resolve refuses ``engine_code_unpinned`` by design).
"""

from __future__ import annotations

import dataclasses
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

import pytest

import breezy.persistence.autonomy.resolver as resolver_mod
from breezy.persistence.autonomy import stage_policy
from breezy.persistence.autonomy.chain import VerifiedVenueChain, verify_venue_chain
from breezy.persistence.autonomy.family_bytes import write_root_copy
from breezy.persistence.autonomy.hwm import HwmPresent, HwmReading, next_hwm
from breezy.persistence.autonomy.lineage import RootRecord
from breezy.persistence.autonomy.registry_export import RegistryReader
from breezy.persistence.autonomy.replay import ReplayOk
from breezy.persistence.autonomy.resolver import (
    HwmMode,
    ResolvedFamily,
    ResolverRefusal,
    _resolve,
)
from breezy.persistence.autonomy.schemas import ExportTrailer, Kind, StagePolicy, State
from breezy.persistence.live_orders_gate import LineagePolicyDecision
from tests.support.entry_points import REPO_ROOT
from tests.unit.test_registry_export import put_export
from tests.unit.test_registry_fold import DAY, INCUMBENT, SHA_B, VENUE, Chain, at
from tests.unit.test_registry_replay import ART_SHA, ARTEFACT, KIND, World, seal
from tests.unit.test_registry_replay_parity import through_store

RULING: Final = "RULING_operator_fq_live_real_orders_2026-10-01"
RULING_SRC: Final = REPO_ROOT / "deploy" / "families" / "rulings" / f"{RULING}.md"
ENGINE_PINS: Final = frozenset({SHA_B})
#: Inside the 26 h export grace of the chain's genesis (``at("2026-10-09", "12:00")``).
NOW_EARLY: Final = at("2026-10-09", "13:00")
POLICY_OK: Final = LineagePolicyDecision(authorized=True, reason="ok", ruling_sha256="a" * 64)

Result = ResolvedFamily | ResolverRefusal
Gate = Callable[..., LineagePolicyDecision]


def policy_gate(*_args: object) -> LineagePolicyDecision:
    """A lineage gate that authorises (the production allowlist is empty at ARCH-0)."""
    return POLICY_OK


def equip(world: World) -> World:
    """The root's ruling in the repo, its E-14 copy in the store and the export directory."""
    rulings = world.repo / "deploy" / "families" / "rulings"
    rulings.mkdir(parents=True, exist_ok=True)
    shutil.copy(RULING_SRC, rulings / RULING_SRC.name)
    record = RootRecord(
        family_id=INCUMBENT,
        manifest_sha256=world.root_sha,
        artefact_sha256=ART_SHA,
        committed_path=f"deploy/families/{INCUMBENT}.json",
    )
    write_root_copy(world.paths, record=record, artefact_raw=ARTEFACT, composition_kind=KIND)
    exports = world.paths.export_dir()
    exports.mkdir(parents=True, exist_ok=True)
    for directory in (exports.parent, exports):
        directory.chmod(0o700)
    return world


def populate(world: World, chain: Chain) -> VerifiedVenueChain:
    """Write ``chain`` through the real store and return the stored, verified chain."""
    stored, refused = through_store(world, chain)
    assert refused is None, refused
    return verify_venue_chain(stored, VENUE)


def hwm_of(chain: VerifiedVenueChain, export_seq: int = 0) -> HwmPresent:
    return HwmPresent(next_hwm(chain, export_seq=export_seq))


def export_all(world: World, chain: VerifiedVenueChain, export_seq: int = 1) -> ExportTrailer:
    """Write a full-history export of ``chain`` and return its trailer."""
    put_export(world.paths, chain.rows, export_seq)
    last = chain.rows[-1]
    assert last.venue_seq is not None and last.transition_hash is not None
    return ExportTrailer(
        venue=VENUE,
        venue_seq=last.venue_seq,
        chain_head=last.transition_hash,
        export_seq=export_seq,
    )


def resolve(world: World, hwm: HwmReading, *, now: int, **overrides: Any) -> Result:
    """The private resolve with the canonical stage unless a fixture stage is passed."""
    args: dict[str, Any] = {
        "venue": VENUE,
        "paths": world.paths,
        "repo_root": world.repo,
        "now_ns": now,
        "hwm": hwm,
        "stage": stage_policy.STAGE,
        "lineage_gate": policy_gate,
        "hwm_mode": HwmMode.ENFORCE,
        "_engine_pins": ENGINE_PINS,
    }
    args.update(overrides)
    return _resolve(**args)


def root_chain(world: World) -> Chain:
    """The root BOOTSTRAPped as CHAMPION, bound to the world's files."""
    chain = Chain()
    chain.add(
        Kind.BOOTSTRAP,
        State.CHAMPION,
        family=INCUMBENT,
        manifest_sha256=world.root_sha,
        artefact_sha256=ART_SHA,
    )
    return chain


def forge(chain: Chain) -> VerifiedVenueChain:
    """``chain`` sealed and verified in memory, rows carrying their global ``seq`` (as stored)."""
    sealed = seal(chain)
    rows = tuple(dataclasses.replace(r, seq=r.venue_seq) for r in sealed.rows)
    return dataclasses.replace(sealed, rows=rows)


@contextmanager
def serving(chain: VerifiedVenueChain) -> Iterator[None]:
    """Make the reader return ``chain``'s rows instead of the database's.

    The real store refuses a nomination (``NominationRequiresPolicy``) and an HWM_RESET until their
    owners land, so a chain with either can only be forged. Only ``RegistryReader.read_venue_rows``
    is patched (A8c-R5), so the clock check, the chain verification and everything after the read
    are real and step 2 always runs.
    """
    patch = pytest.MonkeyPatch()
    patch.setattr(RegistryReader, "read_venue_rows", lambda _self, *_args, **_kw: chain.rows)
    try:
        yield
    finally:
        patch.undo()


@contextmanager
def replay_stubbed() -> Iterator[None]:
    """Make step 6 pass, to reach the resolver's own binding checks (steps 8 to 11).

    Replay already refuses a tampered or unreadable manifest or artefact
    (``replay_artefact_mismatch``)
    before the resolver binds bytes, so the resolver's own refusal is reachable only in isolation.
    Tests assert both: the real run (replay first) and the stubbed run (the resolver's own reason).
    """
    patch = pytest.MonkeyPatch()
    patch.setattr(
        resolver_mod,
        "replay_full",
        lambda chain, **_kwargs: ReplayOk(chain.head_venue_seq, chain.head_hash),
    )
    try:
        yield
    finally:
        patch.undo()


NOW_LATE: Final = at(DAY, "17:30")
OPEN_STAGE: Final = StagePolicy(
    enabled_widening_kinds=frozenset(Kind), admission_implemented=frozenset(Kind)
)
PIN: Final = {"stage": OPEN_STAGE, "_fixture_stage": True}


def refusal_of(result: object) -> ResolverRefusal:
    assert isinstance(result, ResolverRefusal), result
    return result


def resolved(result: object) -> ResolvedFamily:
    assert isinstance(result, ResolvedFamily), result
    return result


def rewrite(path: Path, data: bytes) -> None:
    """Replace a read-only file's bytes (the tamper step of a test)."""
    path.chmod(0o644)
    path.write_bytes(data)
    path.chmod(0o444)


def root_file(world: World) -> Path:
    return world.repo / "deploy" / "families" / f"{INCUMBENT}.json"
