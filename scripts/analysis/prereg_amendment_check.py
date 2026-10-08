#!/usr/bin/env python3
"""Sibling checker for F5 prereg amendments (A0 KILL now; A1 and A2 later).

    prereg_amendment_check.py [--draft] <amendment.json>

Exit codes match the parent checker: 0 OK, 1 defects, 2 usage or load error.
``--draft`` replaces the freeze rule with ``frozen_sha == UNFROZEN`` and exits 0
only for an unfrozen file. It never reports a draft as frozen.

The rules import ``validate_defects``, ``check_frozen_blob`` and
``check_not_refrozen``. Nothing those functions do is re-implemented. Run this
in a full clone: a shallow clone cannot prove the file was frozen only once,
and ``check_not_refrozen`` then refuses it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis.autonomy import confidence_sequence as cs
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


def _check_payload(amendment: Mapping[str, Any]) -> list[Defect]:
    amendment_id = amendment.get("amendment_id")
    if amendment_id == _A0_ID:
        return _check_kill(amendment.get("kill"))
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
        *_check_payload(amendment),
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
