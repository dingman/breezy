"""ARCH-0 seam 8d: the shadow resolver (AC 18; AC 17.0; A5-R7).

``resolve_shadow_family`` answers the same question as the sending resolver on a ``ShadowPaths``
root, but ignores the node high-water mark, runs the explicit step set {0, 2, 3, 5, 6, 7, 8} and
returns a ``ShadowResolution`` that carries no bytes, no permit and no HWM. A shadow resolve cannot
send, whatever it finds.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from typing import Final

import pytest

import breezy.persistence.autonomy.resolver as resolver_mod
from breezy.persistence.autonomy import pins, stage_policy
from breezy.persistence.autonomy.chain import VerifiedVenueChain
from breezy.persistence.autonomy.hwm import HwmAbsent
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths
from breezy.persistence.autonomy.resolver import (
    SHADOW_CALL_SITES,
    HwmMode,
    ResolvedFamily,
    ResolverRefusal,
    ShadowResolution,
    resolve_sending_family,
    resolve_shadow_family,
)
from breezy.persistence.autonomy.schemas import Kind, RefusalReason, State
from breezy.persistence.live_orders_gate import lineage_policy_authorized
from tests.support.entry_points import REPO_ROOT, SRC_DIR
from tests.unit.registry_resolver_world import (
    NOW_EARLY,
    equip,
    export_all,
    forge,
    hwm_of,
    populate,
    resolve,
    root_chain,
    serving,
)
from tests.unit.test_registry_fold import INCUMBENT, VENUE, at
from tests.unit.test_registry_replay import World

HOUR_NS: Final = 3_600 * 10**9
SHADOW_STEPS: Final = [0, 2, 3, 5, 6, 7, 8]
RESOLVER_MODULE: Final = "breezy.persistence.autonomy.resolver"
SENDING_ONLY_FIELDS: Final = frozenset(
    {
        "entries_allowed", "origin", "authorising_seq", "family_bytes",
        "export_check", "verified_export_seq", "hwm",
    }
)  # fmt: skip


@pytest.fixture
def world(tmp_path: Path) -> World:
    return equip(World(tmp_path))


@pytest.fixture
def rooted(world: World) -> VerifiedVenueChain:
    return populate(world, root_chain(world))


def shadow_of(world: World) -> ShadowPaths:
    """The shadow root over the world's files (same layout, deliberately another type)."""
    return ShadowPaths(world.data)


def shadow(world: World, *, now: int = NOW_EARLY) -> ShadowResolution | ResolverRefusal:
    return resolve_shadow_family(
        venue=VENUE, paths=shadow_of(world), repo_root=world.repo, now_ns=now
    )


def attest_chain(world: World) -> VerifiedVenueChain:
    """The root CHAMPION followed by one ATTEST: a chain a node high-water mark would have seen."""
    chain = root_chain(world)
    ts = at("2026-10-09", "12:00") + pins.ATTEST_PERIOD_H * HOUR_NS
    chain.add(
        Kind.ATTEST, State.CHAMPION, family=INCUMBENT, frm=State.CHAMPION, ts=ts,
        attest_valid_until_ns=ts + pins.ATTEST_VERDICT_VALIDITY_H * HOUR_NS,
    )  # fmt: skip
    return forge(chain)


def refusal_of(result: object) -> ResolverRefusal:
    assert isinstance(result, ResolverRefusal), result
    return result


def test_shadow_resolution_ignores_hwm_and_cannot_send(world: World) -> None:
    """AC 18 checks (i) to (v)."""
    chain = attest_chain(world)
    now = chain.rows[-1].ts_ns + HOUR_NS
    # (i) an ATTEST-bearing chain with no HWM resolves.
    with serving(chain):
        got = shadow(world, now=now)
    assert isinstance(got, ShadowResolution), got
    assert (got.family_id, got.state) == (INCUMBENT, State.CHAMPION)
    assert (got.registry_seq, got.chain_head) == (chain.head_venue_seq, chain.head_hash)
    # (ii) the sending resolver on the same chain and no HWM is refused.
    with serving(chain):
        sending = resolve(world, HwmAbsent(), now=now)
        control = resolve(world, hwm_of(chain), now=now)
    assert refusal_of(sending).reason is RefusalReason.HWM_ABSENT
    assert isinstance(control, ResolvedFamily)  # the chain is otherwise sendable
    # (iii) the answer has none of the sending-only fields and no shared base.
    names = {f.name for f in dataclasses.fields(ShadowResolution)}
    assert names == {"family_id", "state", "registry_seq", "chain_head"}
    assert not names & SENDING_ONLY_FIELDS
    assert not any(hasattr(got, field) for field in SENDING_ONLY_FIELDS)
    assert ShadowResolution.__mro__[1:] == (object,)
    assert not issubclass(ShadowResolution, ResolvedFamily)
    assert not issubclass(ResolvedFamily, ShadowResolution)
    assert dataclasses.is_dataclass(got) and got.__dataclass_params__.frozen  # type: ignore[attr-defined]
    # (iv) nothing outside SHADOW_CALL_SITES calls the shadow resolver (empty until AUT-5a).
    assert SHADOW_CALL_SITES == frozenset()
    assert shadow_call_sites(SCAN_ROOTS) == set()
    # (v) the spy records exactly the steps {0, 2, 3, 5, 6, 7, 8}.
    steps: list[int] = []
    with serving(chain):
        traced = resolver_mod._resolve(
            venue=VENUE, paths=shadow_of(world), repo_root=world.repo, now_ns=now,
            hwm=HwmAbsent(), stage=stage_policy.STAGE,
            lineage_gate=lineage_policy_authorized,
            hwm_mode=HwmMode.SKIP_SHADOW, _trace=steps.append,
        )  # fmt: skip
    assert isinstance(traced, ShadowResolution)
    assert steps == SHADOW_STEPS


def test_shadow_runs_no_byte_binding_gate_or_hwm_step(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Steps 4 and 9 to 12 are not merely unreported: their functions are never called."""
    chain = attest_chain(world)

    def forbidden(name: str) -> object:
        def raiser(*_a: object, **_k: object) -> object:
            raise AssertionError(f"shadow resolve called {name}")

        return raiser

    for name in ("hwm_check", "next_hwm", "verify_bound_bytes", "_root_gate", "_child_gate",
                 "_engine_problem", "_is_routed"):  # fmt: skip
        monkeypatch.setattr(resolver_mod, name, forbidden(name))
    with serving(chain):
        got = shadow(world, now=chain.rows[-1].ts_ns + HOUR_NS)
    assert isinstance(got, ShadowResolution), got


def test_shadow_refusals_are_the_sending_refusals_of_the_same_steps(world: World) -> None:
    """A shadow resolve refuses on the chain's own faults: empty, a clock before the head."""
    empty = shadow(world)
    assert refusal_of(empty).reason in {
        RefusalReason.REGISTRY_UNREADABLE,
        RefusalReason.EMPTY_CHAIN,
    }
    chain = populate(world, root_chain(world))
    early = refusal_of(shadow(world, now=chain.rows[-1].ts_ns - 301 * 10**9))
    assert early.reason is RefusalReason.CLOCK_BEFORE_HEAD
    assert isinstance(shadow(world, now=chain.rows[-1].ts_ns), ShadowResolution)  # control
    assert refusal_of(shadow(world, now=0)).reason is RefusalReason.CLOCK_INVALID


def test_shadow_with_no_champion_refuses_no_sender(world: World) -> None:
    chain = root_chain(world)
    chain.add(Kind.RETIRE, State.RETIRED, family=INCUMBENT, frm=State.CHAMPION)
    forged = forge(chain)
    with serving(forged):
        got = shadow(world)
    assert refusal_of(got).reason in {RefusalReason.NO_SENDER, RefusalReason.REPLAY_INVALID}


def test_paths_role_mismatch_both_directions(world: World, tmp_path: Path) -> None:
    """The sending entry refuses a shadow root; the shadow entry refuses a production root."""
    chain = populate(world, root_chain(world))
    unread = tmp_path / "never-read"  # nothing exists here: a refusal that reads would differ
    to_sending = resolve_sending_family(
        venue=VENUE, paths=ShadowPaths(unread), repo_root=world.repo, now_ns=NOW_EARLY,
        hwm=hwm_of(chain),
    )  # fmt: skip
    assert refusal_of(to_sending).reason is RefusalReason.PATHS_ROLE_MISMATCH
    to_shadow = resolve_shadow_family(
        venue=VENUE, paths=AutonomyPaths(unread), repo_root=world.repo, now_ns=NOW_EARLY
    )
    assert refusal_of(to_shadow).reason is RefusalReason.PATHS_ROLE_MISMATCH
    to_shadow_real = resolve_shadow_family(
        venue=VENUE, paths=world.paths, repo_root=world.repo, now_ns=NOW_EARLY
    )  # a real production root is refused as well
    assert refusal_of(to_shadow_real).reason is RefusalReason.PATHS_ROLE_MISMATCH
    assert isinstance(shadow(world), ShadowResolution)  # control: the right role resolves


def test_shadow_day2_without_export_refuses(world: World) -> None:
    """Step 3 applies unchanged: ``not_yet_due`` holds only within 26 h of shadow genesis."""
    chain = populate(world, root_chain(world))
    genesis = chain.rows[0].ts_ns
    inside = genesis + (pins.EXPORT_FIRST_DUE_H * HOUR_NS) - 1
    assert isinstance(shadow(world, now=inside), ShadowResolution)  # day 1: no export is fine
    day2 = genesis + pins.EXPORT_FIRST_DUE_H * HOUR_NS
    assert refusal_of(shadow(world, now=day2)).reason is RefusalReason.EXPORT_UNREADABLE
    export_all(world, chain)
    assert isinstance(shadow(world, now=day2), ShadowResolution)  # an export clears it


# --- (iv): the call-site scan ---------------------------------------------------------------------

SCAN_ROOTS: Final = (SRC_DIR, REPO_ROOT / "scripts")


def _module_of(path: Path) -> str:
    if path.is_relative_to(SRC_DIR):
        parts = path.relative_to(SRC_DIR).with_suffix("").parts
    else:
        parts = ("scripts", *path.relative_to(REPO_ROOT / "scripts").with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def names_shadow_resolver(source: str) -> bool:
    """Whether ``source`` names ``resolve_shadow_family`` in any form (call, import, attribute,
    string, alias)."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id == "resolve_shadow_family":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "resolve_shadow_family":
            return True
        if isinstance(node, ast.alias) and node.name == "resolve_shadow_family":
            return True
        if isinstance(node, ast.Constant) and node.value == "resolve_shadow_family":
            return True
    return False


def shadow_call_sites(roots: tuple[Path, ...]) -> set[str]:
    """Modules, other than the resolver, that name the shadow resolver and are not sanctioned."""
    hits: set[str] = set()
    judged = 0
    for base in roots:
        for path in sorted(base.rglob("*.py")):
            module = _module_of(path)
            if module == RESOLVER_MODULE:
                continue
            judged += 1
            if names_shadow_resolver(path.read_text(encoding="utf-8")) and (
                module not in SHADOW_CALL_SITES
            ):
                hits.add(module)
    assert judged > 300  # not vacuous
    return hits


@pytest.mark.parametrize(
    "planted",
    [
        "from breezy.persistence.autonomy.resolver import resolve_shadow_family\n",
        "import breezy.persistence.autonomy.resolver as r\nr.resolve_shadow_family()\n",
        "getattr(r, 'resolve_shadow_family')\n",
        "from breezy.persistence.autonomy.resolver import resolve_shadow_family as go\n",
    ],
)
def test_the_call_site_scan_catches_every_planted_form(planted: str) -> None:
    assert names_shadow_resolver(planted)
    assert not names_shadow_resolver("from breezy.persistence.autonomy.resolver import x\n")
