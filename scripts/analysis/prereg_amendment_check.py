#!/usr/bin/env python3
"""Sibling checker for F5 prereg amendments (A0 KILL and A1 floor; A2 later).

    prereg_amendment_check.py [--draft] <amendment.json>

Exit codes match the parent checker: 0 OK, 1 defects, 2 usage or load error.
``--draft`` replaces the freeze rule with ``frozen_sha == UNFROZEN`` and exits 0
only for an unfrozen file. It never reports a draft as frozen. On A1 it also
accepts ``PENDING_*`` strings; the key set stays exact. Without ``--draft``
those strings are refused.

The rules import ``validate_defects``, ``check_frozen_blob`` and
``check_not_refrozen``. Nothing those functions do is re-implemented. Run this
in a full clone: a shallow clone cannot prove the file was frozen only once,
and ``check_not_refrozen`` then refuses it.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis.autonomy import confidence_sequence as cs
from breezy.analysis.fq_loss_stop_core import (
    ALPHA_FLOOR_GRID,
    G3_FLOOR_MULTIPLIER,
    T_MIN_GRID,
)
from scripts.analysis import fq_mc_eprocess as mc
from scripts.analysis.multisource_blend_pin_guards import UNFROZEN, check_not_refrozen
from scripts.analysis.multisource_blend_refusal import Refusal
from scripts.analysis.prereg_precommit_check import (
    MAX_LAMBDA,
    Defect,
    check_frozen_blob,
    load_design,
    validate_defects,
)

_GIT_TIMEOUT_S: Final[int] = 20  # same bound as the parent checker; not a KILL constant
_ENVELOPE: Final = frozenset({"frozen_sha", "amendment_id", "amends", "provenance"})
_AMENDS_KEYS: Final = frozenset({"path", "frozen_sha"})
_A0_ID: Final = "F5_prereg_v2_A0_kill"
_A1_ID: Final = "F5_prereg_v2_A1_floor"
_PAYLOADS: Final[dict[str, frozenset[str]]] = {
    _A0_ID: frozenset({"kill"}),
    "F5_prereg_v2_A1_floor": frozenset({"loss_stop_floor"}),
    "F5_prereg_v2_A2_guard": frozenset({"guard", "guard_basis"}),
}
_AMENDMENT_FILENAME: Final[dict[str, str]] = {
    _A0_ID: "F5_prereg_v2_amendment_A0.json",
    "F5_prereg_v2_A1_floor": "F5_prereg_v2_amendment_A1.json",
    "F5_prereg_v2_A2_guard": "F5_prereg_v2_amendment_A2.json",
}
_EARLIER: Final[dict[str, tuple[str, ...]]] = {
    _A0_ID: (),
    "F5_prereg_v2_A1_floor": ("F5_prereg_v2_amendment_A0.json",),
    "F5_prereg_v2_A2_guard": (
        "F5_prereg_v2_amendment_A0.json",
        "F5_prereg_v2_amendment_A1.json",
    ),
}
_KILL_KEYS: Final = frozenset(
    {
        "kill_grid_points",
        "kill_grid_span",
        "kill_lambda_max",
        "kill_min_range",
        "kill_var_floor",
        "kill_prior_pseudo_days",
        "kill_prior_second_moment",
        "kill_lambda_cap_rule",
        "kill_betting_rule",
        "kill_bar_rule",
    }
)
_RULE_FIELDS: Final = (
    "kill_grid_span",
    "kill_lambda_cap_rule",
    "kill_betting_rule",
    "kill_bar_rule",
)
# r3 §4.9. Child keys of loss_stop_floor, including the two nested objects.
_FLOOR_KEYS: Final = frozenset(
    {
        "floor_mode",
        "power_class",
        "alpha_floor",
        "alpha_selection_rule",
        "g3_floor_multiplier",
        "gate_rate_rule",
        "t_unit",
        "pnl_unit",
        "qty_rule",
        "netting_rule",
        "exit_rule",
        "increment_rule",
        "bundle_null_rule",
        "boundary_rule",
        "c",
        "c_mc_se",
        "c_binding_cell",
        "t_min",
        "measured_power",
        "s6_feasible_rate",
        "t_horizon_climate_day",
        "reach_cutoff_epoch_start",
        "past_horizon_rule",
        "epoch_anchor_rule",
        "epoch_id_rule",
        "fail_latch_rule",
        "refusal_rule",
        "restart_rule",
        "inputs",
    }
)
_MEASURED_POWER_KEYS: Final = frozenset({"-0.16", "-0.08", "-0.04"})
# Under unreachable_veto these are null (or PENDING_* in draft). Measured power stays.
_VETO_NULL_FIELDS: Final = (
    "c",
    "c_mc_se",
    "t_min",
    "s6_feasible_rate",
    "reach_cutoff_epoch_start",
    "c_binding_cell",
)
_INPUT_KEYS: Final = frozenset(
    {"sign_rule", "fill_rule", "fee_rule", "void_rule", "truth_sha_rule"}
)
_FLOOR_MODES: Final = frozenset({"sqrt_boundary", "unreachable_veto"})
_SQRT_POWER_CLASSES: Final = frozenset({"edge_capable", "gross_loss_tripwire"})
_HORIZON_CLIMATE_DAY: Final = "2027-01-25"
# §4.6 power target, already imported with the KILL constants. Not retyped.
_EDGE_POWER: Final = Decimal(str(mc.POWER_TARGET))
_POWER_AT: Final = "-0.16"
_USAGE: Final = (
    "usage: prereg_amendment_check.py [--draft] <amendment.json>\n"
    "Run in a full (non-shallow) clone. A shallow clone cannot prove a single freeze."
)

__all__ = ["Defect", "load_verified_amendment", "main", "validate_amendment"]


def _git_toplevel(start: Path) -> Path | None:
    folder = start if start.is_dir() else start.parent
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=folder,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = done.stdout.strip()
    if done.returncode != 0 or not text:
        return None
    return Path(text)


def _resolve_parent(amendment_path: Path, rel: Any) -> tuple[Path | None, str | None]:
    """``amends.path`` is relative to the git top-level, never the cwd (A0-C3)."""
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        return None, f"amends.path must be a relative path, got {rel!r}"
    root = _git_toplevel(amendment_path)
    if root is None:
        return None, f"{amendment_path} is not inside a git repository"
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None, f"amends.path {rel!r} escapes the git repository"
    return candidate, None


def _as_refrozen(path: Path) -> list[Defect]:
    """Any ``check_not_refrozen`` Refusal uses the single code REFROZEN (A0-C6)."""
    try:
        check_not_refrozen(path)
    except Refusal as exc:
        return [Defect("REFROZEN", str(exc))]
    return []


def _occupied(doc: Mapping[str, Any]) -> set[str]:
    """Non-envelope keys at the top level and one level down."""
    found: set[str] = set()
    for key, value in doc.items():
        if key in _ENVELOPE:
            continue
        found.add(str(key))
        if isinstance(value, Mapping):
            found.update(str(child) for child in value)
    return found


def _check_parent(
    amendment_path: Path, amendment: Mapping[str, Any]
) -> tuple[list[Defect], Mapping[str, Any] | None]:
    amends = amendment.get("amends")
    if not isinstance(amends, Mapping):
        return [], None
    parent_path, problem = _resolve_parent(amendment_path, amends.get("path"))
    if problem is not None or parent_path is None:
        return [Defect("BAD_AMENDS", problem or "amends.path is not usable")], None
    try:
        parent = load_design(parent_path)
    except (OSError, TypeError, ValueError) as exc:
        return [Defect("PARENT_UNREADABLE", f"cannot load the parent {parent_path}: {exc}")], None
    defects = [
        *validate_defects(parent),
        *check_frozen_blob(parent_path, parent),
        *_as_refrozen(parent_path),
    ]
    if parent.get("frozen_sha") != amends.get("frozen_sha"):
        defects.append(
            Defect(
                "PARENT_SHA_MISMATCH",
                "parent frozen_sha "
                f"{parent.get('frozen_sha')!r} != amends.frozen_sha {amends.get('frozen_sha')!r}",
            )
        )
    return defects, parent


def _check_envelope(amendment: Mapping[str, Any]) -> list[Defect]:
    defects: list[Defect] = []
    amendment_id = amendment.get("amendment_id")
    payload = _PAYLOADS.get(amendment_id) if isinstance(amendment_id, str) else None
    if payload is None:
        defects.append(Defect("BAD_AMENDMENT_ID", f"unknown amendment_id {amendment_id!r}"))
    else:
        expected = _ENVELOPE | payload
        actual = set(amendment)
        if actual != expected:
            defects.append(
                Defect(
                    "BAD_KEYS",
                    f"top-level keys must be exactly {sorted(expected)}, "
                    f"extra={sorted(actual - expected)}, missing={sorted(expected - actual)}",
                )
            )
    amends = amendment.get("amends")
    if not isinstance(amends, Mapping) or set(amends) != _AMENDS_KEYS:
        got = sorted(amends) if isinstance(amends, Mapping) else amends
        defects.append(
            Defect("BAD_AMENDS", f"amends keys must be exactly {sorted(_AMENDS_KEYS)}, got {got!r}")
        )
    return defects


def _earlier_keys(path: Path, amendment_id: str) -> tuple[list[Defect], set[str]]:
    defects: list[Defect] = []
    found: set[str] = set()
    for name in _EARLIER.get(amendment_id, ()):
        earlier_path = path.parent / name
        try:
            body = json.loads(earlier_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            defects.append(Defect("EARLIER_AMENDMENT_MISSING", f"cannot read {name}: {exc}"))
            continue
        if not isinstance(body, Mapping):
            defects.append(Defect("EARLIER_AMENDMENT_MISSING", f"{name} is not a JSON object"))
            continue
        found.update(_occupied(body))
    return defects, found


def _check_additive(
    path: Path, amendment: Mapping[str, Any], parent: Mapping[str, Any] | None
) -> list[Defect]:
    defects: list[Defect] = []
    occupied = _occupied(amendment)
    if parent is not None:
        # Top-level keys, plus one level of nested keys (for example haircut.ticks).
        overlap = occupied & (set(parent) | _occupied(parent))
        if overlap:
            defects.append(
                Defect("KEY_OVERLAP", f"payload keys overlap the parent: {sorted(overlap)}")
            )
    amendment_id = amendment.get("amendment_id")
    if not isinstance(amendment_id, str):
        return defects
    earlier_defects, earlier = _earlier_keys(path, amendment_id)
    defects.extend(earlier_defects)
    overlap = occupied & earlier
    if overlap:
        defects.append(
            Defect("KEY_OVERLAP", f"payload keys overlap an earlier amendment: {sorted(overlap)}")
        )
    return defects


def _check_freeze(path: Path, amendment: Mapping[str, Any], *, draft: bool) -> list[Defect]:
    if draft:
        if amendment.get("frozen_sha") == UNFROZEN:
            return []
        return [Defect("NOT_DRAFT", f"--draft exits 0 only when frozen_sha is {UNFROZEN}")]
    return [*check_frozen_blob(path, amendment), *_as_refrozen(path)]


def _mismatch(name: str, value: Any, expected: Sequence[Any]) -> Defect | None:
    # `==` alone accepts True for 1 and 5.0 for 5; each pin must match the constant's type.
    if all(type(value) is type(item) and value == item for item in expected):
        return None
    return Defect(
        "KILL_MISMATCH", f"{name} must equal the imported KILL constant(s), got {value!r}"
    )


def _under_ceiling(value: Any) -> Defect | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value > MAX_LAMBDA:
        return Defect(
            "KILL_MISMATCH",
            f"kill_lambda_max must be <= MAX_LAMBDA ({MAX_LAMBDA!r}), got {value!r}",
        )
    return None


def _check_kill(kill: Any) -> list[Defect]:
    if not isinstance(kill, Mapping) or set(kill) != _KILL_KEYS:
        return [Defect("BAD_KILL", f"kill keys must be exactly {sorted(_KILL_KEYS)}")]
    defects = [
        defect
        for defect in (
            _mismatch(
                "kill_grid_points",
                kill["kill_grid_points"],
                (cs.KILL_GRID_POINTS, mc.KILL_GRID_POINTS),
            ),
            _mismatch(
                "kill_lambda_max",
                kill["kill_lambda_max"],
                (cs.KILL_MAX_LAMBDA, mc.MAX_LAMBDA),
            ),
            _under_ceiling(kill["kill_lambda_max"]),
            _mismatch(
                "kill_prior_pseudo_days",
                kill["kill_prior_pseudo_days"],
                (cs.PRIOR_PSEUDO_DAYS, mc.PRIOR_PSEUDO_DAYS),
            ),
            _mismatch(
                "kill_prior_second_moment",
                kill["kill_prior_second_moment"],
                (cs.PRIOR_SECOND_MOMENT, mc.PRIOR_SECOND_MOMENT),
            ),
            _mismatch("kill_min_range", kill["kill_min_range"], (cs._MIN_RANGE,)),
            _mismatch("kill_var_floor", kill["kill_var_floor"], (cs._VAR_FLOOR,)),
        )
        if defect is not None
    ]
    for name in _RULE_FIELDS:
        value = kill[name]
        if not isinstance(value, str) or not value.strip():
            defects.append(
                Defect("BAD_KILL_RULE", f"{name} must be a non-empty string, got {value!r}")
            )
    return defects


def _is_pending(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("PENDING_")


def _pending_values(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node] if _is_pending(node) else []
    if isinstance(node, Mapping):
        found: list[str] = []
        for child in node.values():
            found.extend(_pending_values(child))
        return found
    if isinstance(node, Sequence):
        found = []
        for child in node:
            found.extend(_pending_values(child))
        return found
    return []


def _as_decimal(value: Any) -> Decimal | None:
    """Finite int/float as ``Decimal(str(x))``. Bool and non-finite values are not numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return Decimal(str(value))


def _in_unit_interval(value: Any) -> bool:
    number = _as_decimal(value)
    return number is not None and Decimal(0) <= number <= Decimal(1)


def _measured_power_defects(measured: Mapping[str, Any], *, allow_pending: bool) -> list[Defect]:
    defects: list[Defect] = []
    for key in sorted(_MEASURED_POWER_KEYS):
        value = measured[key]
        if allow_pending and _is_pending(value):
            continue
        if not _in_unit_interval(value):
            defects.append(
                _floor_value(
                    f"measured_power[{key!r}] must be a finite number in [0, 1], got {value!r}"
                )
            )
    return defects


def _matches_imported(value: Any, expected: Any) -> bool:
    # `==` alone accepts True for 1. The pin must match the constant's type.
    return type(value) is type(expected) and value == expected


def _on_imported_grid(value: Any, grid: Sequence[Any]) -> bool:
    return any(_matches_imported(value, item) for item in grid)


def _bad_floor_keys(value: Any, expected: frozenset[str], kind: str) -> Defect:
    actual = set(value) if isinstance(value, Mapping) else set()
    got = sorted(actual) if isinstance(value, Mapping) else value
    return Defect(
        "BAD_FLOOR_KEYS",
        f"{kind} keys must be exactly {sorted(expected)}, "
        f"extra={sorted(actual - expected)}, missing={sorted(expected - actual)}, got={got!r}",
    )


def _floor_value(message: str) -> Defect:
    return Defect("BAD_FLOOR_VALUE", message)


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed.isoformat() == value


def _check_floor_common(floor: Mapping[str, Any]) -> list[Defect]:
    defects: list[Defect] = []
    alpha = floor["alpha_floor"]
    if not _is_pending(alpha) and not _on_imported_grid(alpha, ALPHA_FLOOR_GRID):
        defects.append(
            _floor_value(f"alpha_floor must be one of {list(ALPHA_FLOOR_GRID)}, got {alpha!r}")
        )
    multiplier = floor["g3_floor_multiplier"]
    if not _is_pending(multiplier) and not _matches_imported(multiplier, G3_FLOOR_MULTIPLIER):
        defects.append(
            _floor_value(
                "g3_floor_multiplier must equal the imported "
                f"G3_FLOOR_MULTIPLIER ({G3_FLOOR_MULTIPLIER!r}), got {multiplier!r}"
            )
        )
    horizon = floor["t_horizon_climate_day"]
    if not _is_pending(horizon) and horizon != _HORIZON_CLIMATE_DAY:
        defects.append(
            _floor_value(
                f"t_horizon_climate_day must be the ISO date {_HORIZON_CLIMATE_DAY}, "
                f"got {horizon!r}"
            )
        )
    return defects


def _check_sqrt_boundary(floor: Mapping[str, Any]) -> list[Defect]:
    defects: list[Defect] = []
    boundary = floor["c"]
    boundary_d = None if _is_pending(boundary) else _as_decimal(boundary)
    if not _is_pending(boundary) and (boundary_d is None or boundary_d <= 0):
        defects.append(_floor_value(f"c must be finite and > 0, got {boundary!r}"))
    standard_error = floor["c_mc_se"]
    error_d = None if _is_pending(standard_error) else _as_decimal(standard_error)
    if not _is_pending(standard_error) and (error_d is None or error_d <= 0):
        defects.append(_floor_value(f"c_mc_se must be finite and > 0, got {standard_error!r}"))
    t_min = floor["t_min"]
    if not _is_pending(t_min) and not _on_imported_grid(t_min, T_MIN_GRID):
        defects.append(_floor_value(f"t_min must be an int in {list(T_MIN_GRID)}, got {t_min!r}"))
    defects.extend(_check_measured_power(floor, error_d))
    reach = floor["reach_cutoff_epoch_start"]
    if not _is_pending(reach) and not _is_iso_date(reach):
        defects.append(_floor_value(f"reach_cutoff_epoch_start must be an ISO date, got {reach!r}"))
    return defects


def _check_measured_power(floor: Mapping[str, Any], error_d: Decimal | None) -> list[Defect]:
    """G3, the power-class split at the imported power target, and the S6 bound."""
    measured = floor["measured_power"]
    if not isinstance(measured, Mapping):
        return [_bad_floor_keys(measured, _MEASURED_POWER_KEYS, "measured_power")]
    defects = _measured_power_defects(measured, allow_pending=False)
    power = measured[_POWER_AT]
    # Out of range is already a defect. Do not also score G3 or the class split on it.
    power_d = _as_decimal(power) if _in_unit_interval(power) else None
    alpha = floor["alpha_floor"]
    multiplier = floor["g3_floor_multiplier"]
    alpha_d = None if _is_pending(alpha) else _as_decimal(alpha)
    multiplier_d = None if _is_pending(multiplier) else _as_decimal(multiplier)
    if (
        power_d is not None
        and alpha_d is not None
        and multiplier_d is not None
        and power_d < multiplier_d * alpha_d
    ):
        defects.append(
            Defect(
                "FLOOR_POWER_BELOW_G3",
                f"measured_power[{_POWER_AT!r}] {power_d} < "
                f"g3_floor_multiplier {multiplier_d} * alpha_floor {alpha_d}",
            )
        )
    power_class = floor["power_class"]
    if not _is_pending(power_class):
        if power_class not in _SQRT_POWER_CLASSES:
            defects.append(
                _floor_value(
                    f"power_class must be edge_capable or gross_loss_tripwire, got {power_class!r}"
                )
            )
        elif power_d is not None and not _power_class_consistent(power_class, power_d):
            defects.append(
                Defect(
                    "FLOOR_CLASS_INCONSISTENT",
                    f"power_class {power_class!r} disagrees with "
                    f"measured_power[{_POWER_AT!r}] {power_d} "
                    f"(edge_capable requires >= {_EDGE_POWER})",
                )
            )
    defects.extend(_check_s6(floor, alpha_d, error_d))
    return defects


def _power_class_consistent(power_class: object, power: Decimal) -> bool:
    at_edge = power >= _EDGE_POWER
    if power_class == "edge_capable":
        return at_edge
    return not at_edge


def _check_s6(
    floor: Mapping[str, Any], alpha_d: Decimal | None, error_d: Decimal | None
) -> list[Defect]:
    # The bound is defined only when α and c_mc_se are usable. A bad se is its own defect.
    rate = floor["s6_feasible_rate"]
    if _is_pending(rate):
        return []
    rate_d = _as_decimal(rate)
    if rate_d is None or not _in_unit_interval(rate):
        return [_floor_value(f"s6_feasible_rate must be a finite number in [0, 1], got {rate!r}")]
    if alpha_d is None or error_d is None or error_d <= 0:
        return []
    bound = alpha_d + Decimal(3) * error_d
    if rate_d > bound:
        return [
            Defect(
                "FLOOR_S6_FAILED",
                f"s6_feasible_rate {rate_d} > alpha_floor + 3*c_mc_se ({bound})",
            )
        ]
    return []


def _check_unreachable_veto(floor: Mapping[str, Any]) -> list[Defect]:
    defects: list[Defect] = []
    for name in _VETO_NULL_FIELDS:
        value = floor[name]
        if not _is_pending(value) and value is not None:
            defects.append(_floor_value(f"unreachable_veto requires {name} null, got {value!r}"))
    power_class = floor["power_class"]
    if not _is_pending(power_class) and power_class != "none":
        defects.append(
            _floor_value(f"unreachable_veto requires power_class 'none', got {power_class!r}")
        )
    measured = floor["measured_power"]
    if not isinstance(measured, Mapping):
        defects.append(_bad_floor_keys(measured, _MEASURED_POWER_KEYS, "measured_power"))
        return defects
    defects.extend(_measured_power_defects(measured, allow_pending=True))
    return defects


def _check_floor(floor: Any, *, draft: bool) -> list[Defect]:
    if not isinstance(floor, Mapping) or set(floor) != _FLOOR_KEYS:
        return [_bad_floor_keys(floor, _FLOOR_KEYS, "loss_stop_floor")]
    defects: list[Defect] = []
    measured = floor["measured_power"]
    inputs = floor["inputs"]
    if not isinstance(measured, Mapping) or set(measured) != _MEASURED_POWER_KEYS:
        defects.append(_bad_floor_keys(measured, _MEASURED_POWER_KEYS, "measured_power"))
    if not isinstance(inputs, Mapping) or set(inputs) != _INPUT_KEYS:
        defects.append(_bad_floor_keys(inputs, _INPUT_KEYS, "inputs"))
    if defects:
        return defects
    if not draft:
        pending = _pending_values(floor)
        if pending:
            defects.append(
                Defect(
                    "FLOOR_PENDING",
                    "PENDING_* values are refused outside --draft "
                    f"({len(pending)} found, first {pending[0]!r})",
                )
            )
    defects.extend(_check_floor_common(floor))
    mode = floor["floor_mode"]
    if _is_pending(mode):
        return defects
    if mode == "sqrt_boundary":
        defects.extend(_check_sqrt_boundary(floor))
    elif mode == "unreachable_veto":
        defects.extend(_check_unreachable_veto(floor))
    else:
        defects.append(
            _floor_value(f"floor_mode must be one of {sorted(_FLOOR_MODES)}, got {mode!r}")
        )
    return defects


def _check_payload(amendment: Mapping[str, Any], *, draft: bool = False) -> list[Defect]:
    amendment_id = amendment.get("amendment_id")
    if amendment_id == _A0_ID:
        return _check_kill(amendment.get("kill"))
    if amendment_id == _A1_ID:
        return _check_floor(amendment.get("loss_stop_floor"), draft=draft)
    if isinstance(amendment_id, str) and amendment_id in _PAYLOADS:
        return [
            Defect(
                "PAYLOAD_NOT_YET_DEFINED",
                f"{amendment_id} payload rules are not yet defined",
            )
        ]
    return []


def _check_amendment_filename(path: Path, amendment: Mapping[str, Any]) -> list[Defect]:
    """The basename is ``F5_prereg_v2_amendment_{A0|A1|A2}.json`` for a known id."""
    amendment_id = amendment.get("amendment_id")
    if not isinstance(amendment_id, str):
        return []
    expected = _AMENDMENT_FILENAME.get(amendment_id)
    if expected is None or path.name == expected:
        return []
    return [
        Defect(
            "BAD_AMENDMENT_FILENAME",
            f"file name must be {expected} for amendment_id {amendment_id!r}, got {path.name!r}",
        )
    ]


def _collect(path: Path, amendment: Mapping[str, Any], *, draft: bool) -> list[Defect]:
    parent_defects, parent = _check_parent(path, amendment)
    return [
        *parent_defects,
        *_check_envelope(amendment),
        *_check_amendment_filename(path, amendment),
        *_check_additive(path, amendment, parent),
        *_check_freeze(path, amendment, draft=draft),
        *_check_payload(amendment, draft=draft),
    ]


def validate_amendment(path: Path, *, draft: bool = False) -> list[Defect]:
    """R1–R5 for ``path``. ``draft`` replaces the freeze rule with the UNFROZEN check."""
    return _collect(path, load_design(path), draft=draft)


def load_verified_amendment(path: Path, amendment_id: str) -> Mapping[str, Any]:
    """The frozen amendment, or a :class:`Refusal`. Same order as ``load_verified_prereg``."""
    try:
        amendment = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refusal(f"cannot read the amendment {path}: {exc}") from exc
    if not isinstance(amendment, Mapping):
        raise Refusal(f"{path}: the amendment must be a JSON object")
    if amendment.get("frozen_sha") == UNFROZEN:
        raise Refusal(
            f"frozen_sha is {UNFROZEN}: the draft amendment has not been frozen; nothing is scored"
        )
    if amendment.get("amendment_id") != amendment_id:
        raise Refusal(
            f"amendment_id must be {amendment_id!r}, got {amendment.get('amendment_id')!r}"
        )
    defects = _collect(Path(path), amendment, draft=False)
    if defects:
        raise Refusal("; ".join(f"[{item.code}] {item.message}" for item in defects))
    return amendment


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    draft = "--draft" in args
    paths = [arg for arg in args if arg != "--draft"]
    if len(paths) != 1 or paths[0].startswith("-"):
        print(_USAGE, file=sys.stderr)
        return 2
    path = Path(paths[0])
    try:
        amendment = load_design(path)
    except (OSError, TypeError, ValueError) as exc:
        print(f"cannot load amendment: {exc}", file=sys.stderr)
        return 2
    defects = _collect(path, amendment, draft=draft)
    for defect in defects:
        print(f"[{defect.code}] {defect.message}", file=sys.stderr)
    if defects:
        print(f"FAIL: {len(defects)} defect(s)", file=sys.stderr)
        return 1
    if draft:
        print(f"OK: draft amendment is complete and {UNFROZEN}")
    else:
        print("OK: amendment is complete, additive, and equals its committed blob")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
