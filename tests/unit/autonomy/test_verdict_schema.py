"""AUT-4 WP2: AUT-4's closed vocabulary agrees with the ARCH-0 `verdict/v1` schema (§3.1a).

These are characterisation tests: the ARCH-0 `Verdict` already enforces the rules, so they pass
on first run. Their job is to fail if either side drifts from the other.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from breezy.analysis.autonomy import metric_registry as registry
from breezy.persistence.autonomy.verdict import (
    ActionClass,
    Assumption,
    StatTestKind,
    Verdict,
    VerdictKind,
    VerdictOutcome,
)
from breezy.persistence.autonomy.wire import WireRefused

_SHA = "a" * 64
_POLICY = "b" * 64
_PREREG = "c" * 64
_FIELDS = {
    "subject_family_id": "forecast_quantile_ladder_v1",
    "outcome": VerdictOutcome.INCONCLUSIVE,
    "detector": "aut4_eval",
    "declared_action_class": ActionClass.NONE,
    "produced_at_ns": 1_000,
    "valid_until_ns": 2_000,
    "producer_code_sha": _SHA,
}


def _verdict(kind: VerdictKind, **overrides: object) -> Verdict:
    params: dict[str, object] = {**_FIELDS, "kind": kind, "policy_ruling_sha256": _POLICY}
    if kind is VerdictKind.FORWARD_SHADOW:
        params["test_kind"] = StatTestKind.FIXED_N  # E-25 rule 1: never null on FORWARD_SHADOW
    params.update(overrides)
    return Verdict(**params)  # type: ignore[arg-type]


def test_assumptions_closed_five_tags() -> None:
    assert {a.value for a in Assumption} == registry.ASSUMPTION_TAGS
    assert len(registry.ASSUMPTION_TAGS) == 5
    assert not {"fixture_candidate", "fill_selection_sensitive", "sigma_source_contaminated"} & (
        registry.ASSUMPTION_TAGS
    )


def test_two_ruling_sha_fields_per_kind() -> None:
    for kind_name in registry.AUT4_KINDS:
        kind = VerdictKind(kind_name)
        assert set(registry.RULING_SHA_COLUMNS) <= {
            "policy_ruling_sha256",
            "family_prereg_sha256",
        }
        # policy_ruling_sha256 is allowed on every kind ...
        _verdict(kind)
        # ... and null exactly with the no_policy_ruling assumption.
        _verdict(kind, policy_ruling_sha256=None, assumptions=(Assumption.NO_POLICY_RULING,))
        with pytest.raises(WireRefused):
            _verdict(kind, policy_ruling_sha256=None)
        # family_prereg_sha256 is accepted for LIVE_SEQUENTIAL only.
        if kind is VerdictKind.LIVE_SEQUENTIAL:
            _verdict(kind, family_prereg_sha256=_PREREG)
            assert "family_prereg_sha256" not in registry.NULL_COLUMNS_BY_KIND[kind_name]
        else:
            with pytest.raises(WireRefused):
                _verdict(kind, family_prereg_sha256=_PREREG)
            assert "family_prereg_sha256" in registry.NULL_COLUMNS_BY_KIND[kind_name]


def test_forward_shadow_only_columns_agree_with_arch0() -> None:
    values = {"k_life": 1, "alpha_k": Decimal("0.0125"), "n_min_eff": 403, "n_cap": 89}
    assert set(registry.FORWARD_SHADOW_ONLY_COLUMNS) == set(values)
    _verdict(VerdictKind.FORWARD_SHADOW, **values)
    for kind_name in registry.AUT4_KINDS:
        if kind_name == registry.KIND_FORWARD_SHADOW:
            assert not set(values) & registry.NULL_COLUMNS_BY_KIND[kind_name]
            continue
        assert set(values) <= registry.NULL_COLUMNS_BY_KIND[kind_name]
        for column, value in values.items():
            with pytest.raises(WireRefused):
                _verdict(VerdictKind(kind_name), **{column: value})


def test_registry_kinds_are_arch0_kinds() -> None:
    assert set(registry.AUT4_KINDS) <= {k.value for k in VerdictKind}
    assert set(registry.NULL_COLUMNS_BY_KIND) == set(registry.AUT4_KINDS)


def test_decimal_fields_canonical_string() -> None:
    verdict = _verdict(
        VerdictKind.FORWARD_SHADOW,
        k_life=1,
        alpha_k=Decimal("0.0125"),
        alpha_spent=Decimal("0.0125"),
        n_min_eff=403,
        n_cap=89,
    )
    wire = verdict.to_wire()
    assert wire["alpha_k"] == "0.0125"
    assert wire["alpha_spent"] == "0.0125"
    zero = _verdict(
        VerdictKind.FORWARD_SHADOW,
        k_life=0,
        alpha_k=Decimal("0.0"),
        alpha_spent=Decimal("0.00"),
        n_min_eff=403,
        n_cap=89,
    ).to_wire()
    assert zero["alpha_k"] == "0"  # zero is exactly "0", never "0.0"
    assert zero["alpha_spent"] == "0"
    with pytest.raises(WireRefused):
        _verdict(VerdictKind.LIVE_SEQUENTIAL, alpha_spent=0.0125)  # a float is never admitted


def test_verdict_e_process_fields_null_on_other_kinds() -> None:
    """The registry and `Verdict` agree on where test_kind / eta_ns / window_end must be null."""
    assert set(registry.FORWARD_SHADOW_E_PROCESS_ONLY_COLUMNS) == {"eta_ns", "window_end"}
    values = {"eta_ns": 5, "window_end": "2026-11-20"}
    fs = _verdict(VerdictKind.FORWARD_SHADOW, test_kind=StatTestKind.E_PROCESS, **values)
    assert fs.eta_ns == 5
    for kind_name in registry.AUT4_KINDS:
        nulls = registry.NULL_COLUMNS_BY_KIND[kind_name]
        if kind_name == registry.KIND_FORWARD_SHADOW:
            assert not {"test_kind", "eta_ns", "window_end"} & nulls
            continue
        assert set(registry.FORWARD_SHADOW_E_PROCESS_ONLY_COLUMNS) <= nulls
        kind = VerdictKind(kind_name)
        for column, value in values.items():
            with pytest.raises(WireRefused):
                _verdict(kind, **{column: value})
        if kind is VerdictKind.LIVE_SEQUENTIAL:
            # test_kind is the one new column LIVE_SEQUENTIAL may carry (e_process only).
            assert "test_kind" not in nulls
            assert _verdict(kind, test_kind=StatTestKind.E_PROCESS)
        else:
            assert "test_kind" in nulls
            for member in StatTestKind:
                with pytest.raises(WireRefused):
                    _verdict(kind, test_kind=member)
