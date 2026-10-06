"""ARCH-0 seams 3a and 3b: the veto vocabulary (AC 23) and the C6 plug-in contract (AC 26)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Final

import pytest

from breezy.analysis.autonomy import offline_plugins
from breezy.analysis.autonomy.offline_plugins import OFFLINE_PLUGINS
from breezy.persistence.autonomy import plugin, veto
from breezy.persistence.autonomy.plugin import (
    CaptureAdapter,
    Detector,
    DetectorKind,
    DriftDetectors,
    Evaluator,
    PluginRefused,
    Refitter,
    RefusingPlugin,
    Scorer,
    is_complete,
)
from breezy.persistence.autonomy.veto import VetoReason, compose_entry_vetoes
from breezy.persistence.family_manifest import _COMPOSITION_KINDS
from breezy.strategy.autonomy import node_plugins
from breezy.strategy.autonomy.node_plugins import NODE_PLUGINS
from tests.support.autonomy_owner import OwnerPending
from tests.support.autonomy_owner_stub import await_owner

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


# --- Seam 3b: C6 plug-in contract (AC 26) -------------------------------------------------

#: ARCH C6 member table (AUTONOMY_ARCHITECTURE.md:742-752), one literal copy.
ARCH_C6_KINDS: Final[frozenset[str]] = frozenset(
    {"current_rung_hold", "continuous_rung_hold", "forecast_ladder", "forecast_quantile_ladder"}
)
C6_PROTOCOLS: Final[tuple[type, ...]] = (
    CaptureAdapter,
    Scorer,
    Evaluator,
    DriftDetectors,
    Refitter,
)


#: AUT-2 FQ-R41: the offline registry's exact per-kind plug-in type. FQ and both CRH kinds carry a
#: real Scorer (``label``) and stay ``refusing`` for everything else; ``forecast_ladder`` has no
#: fills and no scorer, so it stays the plain RefusingPlugin.
EXPECTED_OFFLINE_TYPES: Final[dict[str, str]] = {
    "current_rung_hold": "CurrentRungHoldOfflinePlugin",
    "continuous_rung_hold": "ContinuousRungHoldOfflinePlugin",
    "forecast_ladder": "RefusingPlugin",
    "forecast_quantile_ladder": "FqOfflinePlugin",
}


def _registry_literal(module: ModuleType) -> dict[str, str]:
    """Key -> constructor name of the module's registry literal, read from the source."""
    tree = ast.parse(Path(inspect.getfile(module)).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Name) and call.func.id == "MappingProxyType":
                assert isinstance(call.args[0], ast.Dict)
                assert all(isinstance(k, ast.Constant) for k in call.args[0].keys)
                assert all(
                    isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                    for v in call.args[0].values
                )
                return {
                    str(k.value): v.func.id  # type: ignore[attr-defined]
                    for k, v in zip(call.args[0].keys, call.args[0].values, strict=True)
                    if isinstance(k, ast.Constant)
                }
    raise AssertionError("no literal MappingProxyType registry found")


def _registry_literal_keys(module: ModuleType) -> list[str]:
    return list(_registry_literal(module))


#: Every C6 member except ``label``: each must refuse on every offline plug-in, scorer or not.
NON_LABEL_MEMBERS: Final[tuple[tuple[str, tuple[object, ...]], ...]] = (
    ("decision_record", (None, None)),
    ("order_tags", ("d",)),
    ("offline", (None, None)),
    ("forward_shadow", (None, None, None)),
    ("live", (None,)),
    ("refit", (None,)),
)


def test_family_plugin_exact_set() -> None:
    assert ARCH_C6_KINDS == _COMPOSITION_KINDS
    assert set(NODE_PLUGINS) == set(OFFLINE_PLUGINS) == _COMPOSITION_KINDS
    for registry in (NODE_PLUGINS, OFFLINE_PLUGINS):
        assert isinstance(registry, MappingProxyType)
        assert len(registry) == 4
    # NODE_PLUGINS is untouched: every kind is still the plain RefusingPlugin
    assert all(type(v) is RefusingPlugin for v in NODE_PLUGINS.values())
    # OFFLINE_PLUGINS: each kind is EXACTLY its named class (``type(...) is``, no subclass slips in)
    assert {k: type(v).__name__ for k, v in OFFLINE_PLUGINS.items()} == EXPECTED_OFFLINE_TYPES
    assert sorted(_registry_literal_keys(node_plugins)) == sorted(_COMPOSITION_KINDS)
    assert sorted(_registry_literal_keys(offline_plugins)) == sorted(_COMPOSITION_KINDS)
    assert _registry_literal(offline_plugins) == EXPECTED_OFFLINE_TYPES
    assert set(_registry_literal(node_plugins).values()) == {"RefusingPlugin"}


def test_every_offline_plugin_is_incomplete_and_refuses_everything_but_label() -> None:
    for kind, instance in OFFLINE_PLUGINS.items():
        assert instance.refusing is True, kind
        assert is_complete(instance) is False, kind
        assert isinstance(instance, RefusingPlugin), kind
        for name, args in NON_LABEL_MEMBERS:
            with pytest.raises(PluginRefused):
                getattr(instance, name)(*args)
        with pytest.raises(PluginRefused):
            _ = instance.detectors


def test_no_offline_plugin_class_overrides_a_member_other_than_label() -> None:
    members = {name for name, _ in NON_LABEL_MEMBERS} | {"detectors", "refusing"}
    for kind, instance in OFFLINE_PLUGINS.items():
        if type(instance) is RefusingPlugin:
            continue  # the base class itself defines every refusing member
        for klass in type(instance).__mro__[: type(instance).__mro__.index(RefusingPlugin)]:
            assert set(vars(klass)) & members == set(), (kind, klass.__name__)
        own: set[str] = set()
        assert own == set(), (kind, own)


def test_only_the_three_scorer_kinds_have_a_real_label() -> None:
    for kind, instance in OFFLINE_PLUGINS.items():
        has = getattr(instance, "has_scorer", False)
        assert has is (kind != "forecast_ladder"), kind
        if not has:
            with pytest.raises(PluginRefused):
                instance.label(None, None, None)


def test_registries_are_read_only() -> None:
    with pytest.raises(TypeError):
        NODE_PLUGINS["forecast_ladder"] = RefusingPlugin()  # type: ignore[index]
    with pytest.raises(TypeError):
        OFFLINE_PLUGINS["extra"] = RefusingPlugin()  # type: ignore[index]


def _protocol_members(proto: type) -> dict[str, object]:
    return {
        n: v
        for n, v in vars(proto).items()
        if not n.startswith("_") and (callable(v) or isinstance(v, property))
    }


def test_refusing_plugin_refuses_every_member() -> None:
    refusing = RefusingPlugin()
    names: set[str] = set()
    for proto in C6_PROTOCOLS:
        names |= set(_protocol_members(proto))
    assert names == {
        "decision_record",
        "order_tags",
        "label",
        "offline",
        "forward_shadow",
        "live",
        "detectors",
        "refit",
    }
    for name in sorted(names):
        member = inspect.getattr_static(RefusingPlugin, name)
        with pytest.raises(PluginRefused):
            if isinstance(member, property):
                getattr(refusing, name)
            else:
                method = getattr(refusing, name)
                method(*([object()] * len(inspect.signature(method).parameters)))
    assert refusing.refusing is True


def test_detector_protocol_members_are_properties() -> None:
    for name in ("id", "kind"):
        assert isinstance(vars(Detector)[name], property)
    assert isinstance(vars(DriftDetectors)["detectors"], property)
    assert {m.value for m in DetectorKind} == {"node_local", "verdict"}


def test_is_complete_rejects_refusing_and_unmarked_plugins() -> None:
    class Real:
        refusing = False

    class Marked:
        refusing = True

    assert is_complete(Real()) is True
    assert is_complete(RefusingPlugin()) is False
    assert is_complete(Marked()) is False
    assert is_complete(object()) is False  # fail closed: no marker is not complete


def test_plugin_module_is_stdlib_and_veto_only() -> None:
    tree = ast.parse(Path(plugin.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add(node.module or "")
    assert not {r for r in roots if r.startswith("breezy")} - {"breezy.persistence.autonomy.veto"}


@pytest.mark.parametrize("module", [node_plugins, offline_plugins])
def test_plugin_package_inits_hold_no_import_nodes(module: ModuleType) -> None:
    init = Path(inspect.getfile(module)).parent / "__init__.py"
    tree = ast.parse(init.read_text(encoding="utf-8"))
    assert [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)] == []


@pytest.mark.parametrize(
    "kind",
    [
        pytest.param(
            "capture",
            id="capture",
            marks=pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-1; blocks none"),
        ),
        pytest.param(
            "scorer",
            id="scorer",
            marks=pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-2; blocks none"),
        ),
        pytest.param(
            "evaluator",
            id="evaluator",
            marks=pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-4; blocks none"),
        ),
        pytest.param(
            "detectors",
            id="detectors",
            marks=pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none"),
        ),
        pytest.param(
            "refitter",
            id="refitter",
            marks=pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-3; blocks none"),
        ),
    ],
)
def test_every_non_retired_manifest_resolves_to_full_plugins(kind: str) -> None:
    await_owner(f"test_every_non_retired_manifest_resolves_to_full_plugins[{kind}]")
