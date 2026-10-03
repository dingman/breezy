"""ARCH-0 seam 3a: the veto vocabulary (AC 23). Plug-in tests join in seam 3b."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from breezy.persistence.autonomy import veto
from breezy.persistence.autonomy.veto import VetoReason, compose_entry_vetoes

#: ARCH C5 "Entry-veto contract" reasons (AUTONOMY_ARCHITECTURE.md:642-662), one literal copy.
ARCH_VETO_REASONS: frozenset[str] = frozenset(
    {
        # registry
        "registry_not_champion",
        "registry_halted",
        "registry_unreadable",
        "registry_regressed",
        "registry_restrictive_pending",
        # dead engine
        "registry_attest_expired",
        "registry_engine_heartbeat_stale",
        "registry_chain_stale",
        # transient, node-local
        "feed_stale",
        "recorder_stale",
        "permit_lapsed",
        "capture_gap",
        "capture_untagged",
        "alerts_undeliverable",
        # position
        "rung_net_position_held",
    }
)


def test_veto_reason_closed_set_equals_arch() -> None:
    assert len(ARCH_VETO_REASONS) == 15
    assert {m.value for m in VetoReason} == ARCH_VETO_REASONS
    assert len(VetoReason) == 15
    assert all(m.name.lower() == m.value for m in VetoReason)


def test_veto_module_has_no_entry_veto_alias() -> None:
    assert not hasattr(veto, "EntryVeto")
    tree = ast.parse(Path(veto.__file__).read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef | ast.FunctionDef)
    }
    assert "EntryVeto" not in names


def test_capture_untagged_is_a_veto_reason() -> None:
    assert VetoReason("capture_untagged") is VetoReason.CAPTURE_UNTAGGED


def test_veto_reason_rejects_unknown_member() -> None:
    with pytest.raises(ValueError):
        VetoReason("registry_ok")


def test_compose_returns_none_when_no_check_vetoes() -> None:
    assert compose_entry_vetoes([]) is None
    assert compose_entry_vetoes([lambda: None, lambda: None]) is None


def test_compose_returns_the_first_veto_and_stops() -> None:
    calls: list[str] = []

    def a() -> VetoReason | None:
        calls.append("a")
        return None

    def b() -> VetoReason | None:
        calls.append("b")
        return VetoReason.FEED_STALE

    def c() -> VetoReason | None:
        calls.append("c")
        return VetoReason.REGISTRY_HALTED

    assert compose_entry_vetoes([a, b, c]) is VetoReason.FEED_STALE
    assert calls == ["a", "b"]


def test_compose_exception_is_registry_unreadable() -> None:
    def boom() -> VetoReason | None:
        raise RuntimeError("reader exploded")

    assert compose_entry_vetoes([boom]) is VetoReason.REGISTRY_UNREADABLE
    # An earlier clean check does not mask it; a later check is never reached.
    reached: list[int] = []
    assert (
        compose_entry_vetoes([lambda: None, boom, lambda: reached.append(1)])
        is VetoReason.REGISTRY_UNREADABLE
    )
    assert reached == []


def test_compose_non_veto_return_value_is_registry_unreadable() -> None:
    """A check returning something that is not a VetoReason is a broken check: fail closed."""
    assert compose_entry_vetoes([lambda: "feed_stale"]) is VetoReason.REGISTRY_UNREADABLE  # type: ignore[list-item,return-value]
