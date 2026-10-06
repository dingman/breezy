#!/usr/bin/env python3
"""Pre-commit check for the PREREG FQ v2 design JSON (FQ loss response F5).

Validates that a design file carries EVERY key E-25 (`ARCH-ERRATA-rev9_2.md`, as amended by
FQ-R15/R20/R26/R37-R39/R55) consumes, that each value is typed and in range, and that the file
is frozen at a 40-hex git SHA. It exits 0 only when the design is complete and in range; any
other outcome exits non-zero with one line per defect on stderr. It reads the one file named on
the command line, and it runs read-only local `git` commands (rev-parse, cat-file, merge-base,
show) in that file's repository to read the frozen blob. No network, no write.

    prereg_precommit_check.py <design.json>

Beyond shape and range it is MANDATORY against the committed blob: the design file must equal
(canonical JSON, the `frozen_sha` key itself excluded because a commit cannot contain its own
sha) the blob `git show <frozen_sha>:<path>`. The sha must be a commit that is an ancestor of HEAD
(`git merge-base --is-ancestor`), not merely one that exists. It also pins theta, ask_floor, the
haircut and both betting rules to the constants the N Monte-Carlo ran with, imported from it (no
duplicated literals).

This script does not choose any value. The values are the coordinator's, pinned after the
joint-power N Monte-Carlo (`fq_resume_n_mc.py`) and the peer loop.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from scripts.analysis.fq_mc_eprocess import BETTING_RULE
from scripts.analysis.fq_mc_livedata import LoopConfig

#: The values the N Monte-Carlo ran with. The design must carry exactly these.
PINNED_THETA: Final[float] = LoopConfig().theta
PINNED_ASK_FLOOR: Final[float] = LoopConfig().ask_floor
PINNED_HAIRCUT: Final[float] = LoopConfig().haircut  # one tick = ticks * tick_size
PINNED_BETTING_RULE: Final[str] = BETTING_RULE
_GIT_TIMEOUT_S: Final[int] = 20


@dataclass(frozen=True, slots=True)
class Defect:
    """One validation failure: a stable ``code`` for callers and tests, a ``message`` for people."""

    code: str
    message: str


__all__ = [
    "REQUIRED_KEYS",
    "Defect",
    "check_frozen_blob",
    "load_design",
    "main",
    "validate_defects",
    "validate_design",
]

_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")

#: E-25 hard ceilings (rule 3 / FQ-R15 / FQ-R55).
MAX_LAMBDA: Final[float] = 0.5
M_CAP_CHOICES: Final[tuple[int, ...]] = (2, 3)
ALPHA_KILL_PINNED: Final[float] = 0.05
ALPHA_TOTAL_PINNED: Final[float] = 0.025
MIN_BOOTSTRAP_REPLICATES: Final[int] = 200
MAX_NOMINATIONS_PER_LINEAGE_LIFETIME: Final[int] = 4  # pins.py:38; a ceiling for T

#: Every key E-25 consumes. `T` may be replaced by `per_epoch_budgets` (exactly one is pinned).
REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "frozen_sha",
    "alpha_total",
    "gamma_schedule",
    "T",
    "delta_h",
    "n_e_power",
    "n_e_power_basis",
    "take_rate_lower",
    "uptime_floor",
    "earliest_look_n",
    "m_cap",
    "x_max",
    "lambda_max",
    "mu_max",
    "betting_rule_e_a",
    "betting_rule_e_b",
    "alpha_kill",
    "n_par",
    "delta_par",
    "alpha_par",
    "parity_bootstrap_seed",
    "parity_bootstrap_replicates",
    "stale_parity_h",
    "ask_floor",
    "haircut",
    "theta",
    "rounding",
)
_OPTIONAL_KEYS: Final[tuple[str, ...]] = ("per_epoch_budgets",)
_ALLOWED: Final = frozenset(REQUIRED_KEYS) | frozenset(_OPTIONAL_KEYS)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _num_in(
    value: Any, lo: float, hi: float, *, lo_open: bool = True, hi_open: bool = False
) -> bool:
    if not _is_num(value):
        return False
    above = value > lo if lo_open else value >= lo
    below = value < hi if hi_open else value <= hi
    return bool(above and below)


def _check_sha(value: Any) -> str | None:
    if isinstance(value, str) and _SHA_RE.match(value):
        return None
    return "frozen_sha must be a 40-char lowercase hex git SHA"


def _check_m_cap(value: Any) -> str | None:
    if _is_int(value) and value in M_CAP_CHOICES:
        return None
    return f"m_cap must be an int in {M_CAP_CHOICES}, got {value!r}"


def _num_check(name: str, lo: float, hi: float, **kw: bool) -> Callable[[Any], str | None]:
    def check(value: Any) -> str | None:
        if _num_in(value, lo, hi, **kw):
            return None
        left = "(" if kw.get("lo_open", True) else "["
        right = ")" if kw.get("hi_open") else "]"
        return f"{name} must be a number in {left}{lo}, {hi}{right}, got {value!r}"

    return check


def _check_exact(name: str, expected: float) -> Callable[[Any], str | None]:
    def check(value: Any) -> str | None:
        if _is_num(value) and value == expected:
            return None
        return f"{name} must be exactly {expected}, got {value!r}"

    return check


def _int_min(name: str, minimum: int) -> Callable[[Any], str | None]:
    def check(value: Any) -> str | None:
        if _is_int(value) and value >= minimum:
            return None
        return f"{name} must be an int >= {minimum}, got {value!r}"

    return check


def _nonempty_str(name: str) -> Callable[[Any], str | None]:
    def check(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return None
        return f"{name} must be a non-empty string, got {value!r}"

    return check


def _check_haircut(value: Any) -> str | None:
    if (
        isinstance(value, Mapping)
        and set(value) == {"ticks", "tick_size"}
        and _is_int(value["ticks"])
        and value["ticks"] >= 0
        and _num_in(value["tick_size"], 0.0, 0.1)
    ):
        return None
    return f"haircut must be {{'ticks': int >= 0, 'tick_size': number in (0, 0.1]}}, got {value!r}"


_FIELD_CHECKS: Final[dict[str, Callable[[Any], str | None]]] = {
    "frozen_sha": _check_sha,
    "alpha_total": _check_exact("alpha_total", ALPHA_TOTAL_PINNED),
    "gamma_schedule": lambda v: (
        None
        if v == "elond_heavy_tailed_v1"
        else f"gamma_schedule must be 'elond_heavy_tailed_v1', got {v!r}"
    ),
    "delta_h": _num_check("delta_h", 0.0, 1.0, hi_open=True),
    "take_rate_lower": _num_check("take_rate_lower", 0.0, 20.0),
    "uptime_floor": _num_check("uptime_floor", 0.0, 1.0),
    "earliest_look_n": _int_min("earliest_look_n", 1),
    "m_cap": _check_m_cap,
    "x_max": _num_check("x_max", 0.0, 1000.0),
    "lambda_max": _num_check("lambda_max", 0.0, MAX_LAMBDA),
    "mu_max": _num_check("mu_max", 0.0, MAX_LAMBDA),
    "betting_rule_e_a": _nonempty_str("betting_rule_e_a"),
    "betting_rule_e_b": _nonempty_str("betting_rule_e_b"),
    "alpha_kill": _check_exact("alpha_kill", ALPHA_KILL_PINNED),
    "n_par": _int_min("n_par", 1),
    "delta_par": _num_check("delta_par", 0.0, 1.0),
    "alpha_par": _num_check("alpha_par", 0.0, 1.0, hi_open=True),
    "parity_bootstrap_seed": lambda v: (
        None if _is_int(v) and v >= 0 else f"parity_bootstrap_seed must be an int >= 0, got {v!r}"
    ),
    "parity_bootstrap_replicates": _int_min(
        "parity_bootstrap_replicates", MIN_BOOTSTRAP_REPLICATES
    ),
    "stale_parity_h": _num_check("stale_parity_h", 0.0, 24.0 * 30),
    "ask_floor": _num_check("ask_floor", 0.0, 0.5),
    "haircut": _check_haircut,
    "theta": _num_check("theta", 0.0, 1.0),
    "rounding": _nonempty_str("rounding"),
}


def _check_gamma_pin(design: Mapping[str, Any]) -> tuple[list[Defect], int | None]:
    """Exactly one of `T` / `per_epoch_budgets` is pinned (E-25 rule 4); (defects, look_count).

    A missing `T` with no budgets is reported once, as MISSING_KEY, by `validate_defects`.
    """
    has_t, has_budgets = "T" in design, "per_epoch_budgets" in design
    if has_t and has_budgets:
        return [
            Defect("GAMMA_PIN_BOTH", "pin exactly one of T and per_epoch_budgets, not both")
        ], None
    if has_budgets:
        budgets = design["per_epoch_budgets"]
        if (
            isinstance(budgets, Sequence)
            and not isinstance(budgets, str)
            and budgets
            and all(_num_in(b, 0.0, 1.0) for b in budgets)
        ):
            return [], len(budgets)
        message = "per_epoch_budgets must be a non-empty list of numbers in (0, 1]"
        return [Defect("BAD_per_epoch_budgets", message)], None
    if not has_t:
        return [], None
    t = design["T"]
    if _is_int(t) and 1 <= t <= MAX_NOMINATIONS_PER_LINEAGE_LIFETIME:
        return [], t
    message = f"T must be an int in 1..{MAX_NOMINATIONS_PER_LINEAGE_LIFETIME}, got {t!r}"
    return [Defect("BAD_T", message)], None


def _check_n_e_power(design: Mapping[str, Any], looks: int | None) -> list[Defect]:
    defects: list[Defect] = []
    if design.get("n_e_power_basis") != "joint_min_ea_eb":
        message = "n_e_power_basis must be 'joint_min_ea_eb' (joint power of min(e_a, e_b))"
        defects.append(Defect("BAD_n_e_power_basis", message))
    table = design.get("n_e_power")
    if not isinstance(table, Mapping) or not table:
        return [*defects, Defect("BAD_n_e_power", "n_e_power must be a non-empty {k: n} table")]
    if looks is not None and set(table) != {str(k) for k in range(1, looks + 1)}:
        message = f"n_e_power keys must be exactly '1'..'{looks}', got {sorted(table)}"
        defects.append(Defect("BAD_n_e_power", message))
    if not all(_is_int(n) and n > 0 for n in table.values()):
        defects.append(Defect("BAD_n_e_power", "n_e_power values must be ints > 0"))
    return defects


def _check_pins(design: Mapping[str, Any]) -> list[Defect]:
    """theta, ask floor, haircut and both betting rules must be what the MC ran with."""
    wanted: dict[str, Any] = {
        "theta": PINNED_THETA,
        "ask_floor": PINNED_ASK_FLOOR,
        "betting_rule_e_a": PINNED_BETTING_RULE,
        "betting_rule_e_b": PINNED_BETTING_RULE,
    }
    defects = [
        Defect("PIN_MISMATCH", f"{key} must equal the MC constant {value!r}, got {design[key]!r}")
        for key, value in wanted.items()
        if key in design and design[key] != value
    ]
    haircut = design.get("haircut")
    if isinstance(haircut, Mapping) and _check_haircut(haircut) is None:
        ticks = haircut["ticks"] * haircut["tick_size"]
        if not math.isclose(ticks, PINNED_HAIRCUT, abs_tol=1e-12):
            message = f"haircut ticks*tick_size must equal {PINNED_HAIRCUT!r}, got {ticks!r}"
            defects.append(Defect("PIN_MISMATCH", message))
    return defects


def validate_defects(design: Mapping[str, Any]) -> list[Defect]:
    """Every shape, range and pin defect in ``design``; empty when it is acceptable."""
    defects: list[Defect] = []
    for key in REQUIRED_KEYS:
        if key not in design and not (key == "T" and "per_epoch_budgets" in design):
            defects.append(Defect("MISSING_KEY", f"missing required key: {key}"))
    defects.extend(
        Defect("UNKNOWN_KEY", f"unknown key: {key}") for key in sorted(set(design) - _ALLOWED)
    )
    for key, check in _FIELD_CHECKS.items():
        if key in design and (message := check(design[key])):
            defects.append(Defect(f"BAD_{key}", message))
    gamma_defects, looks = _check_gamma_pin(design)
    defects.extend(gamma_defects)
    if "n_e_power" in design or "n_e_power_basis" in design:
        defects.extend(_check_n_e_power(design, looks))
    defects.extend(_check_pins(design))
    return defects


def validate_design(design: Mapping[str, Any]) -> list[str]:
    """The messages of `validate_defects`, for callers that only print."""
    return [d.message for d in validate_defects(design)]


def _canonical(design: Mapping[str, Any]) -> str:
    """Canonical JSON of a design, without `frozen_sha` (a commit cannot contain its own sha)."""
    body = {k: v for k, v in design.items() if k != "frozen_sha"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )


def check_frozen_blob(path: Path, design: Mapping[str, Any]) -> list[Defect]:
    """Refuse a design whose content differs from the blob committed at `frozen_sha`."""
    sha = design.get("frozen_sha")
    if not isinstance(sha, str) or not _SHA_RE.match(sha):
        return [Defect("BAD_frozen_sha", "frozen_sha must be a 40-char lowercase hex git SHA")]
    folder = path.resolve().parent
    try:
        top = _git(folder, "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            return [Defect("NOT_IN_GIT_REPO", f"{path} is not inside a git repository")]
        root = Path(top.stdout.strip())
        if _git(root, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            return [Defect("FROZEN_SHA_UNREACHABLE", f"frozen_sha {sha} is not a commit here")]
        # existence is not enough: a commit on a side branch must not freeze a design
        if _git(root, "merge-base", "--is-ancestor", sha, "HEAD").returncode != 0:
            message = f"frozen_sha {sha} is not an ancestor of HEAD"
            return [Defect("FROZEN_SHA_NOT_ANCESTOR", message)]
        rel = path.resolve().relative_to(root).as_posix()
        blob = _git(root, "show", f"{sha}:{rel}")
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return [Defect("GIT_FAILED", f"cannot read the committed blob: {exc}")]
    if blob.returncode != 0:
        return [Defect("FROZEN_BLOB_MISSING", f"{rel} does not exist at commit {sha}")]
    try:
        committed = json.loads(blob.stdout)
    except ValueError:
        return [Defect("FROZEN_BLOB_DIFFERS", f"the blob at {sha}:{rel} is not valid JSON")]
    if not isinstance(committed, Mapping) or _canonical(committed) != _canonical(design):
        return [Defect("FROZEN_BLOB_DIFFERS", f"{rel} differs from the blob committed at {sha}")]
    return []


def load_design(path: Path) -> Mapping[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise TypeError(f"{path}: the design must be a JSON object")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: prereg_precommit_check.py <design.json>", file=sys.stderr)
        return 2
    path = Path(args[0])
    try:
        design = load_design(path)
    except (OSError, TypeError, ValueError) as exc:  # JSONDecodeError is a ValueError
        print(f"cannot load design: {exc}", file=sys.stderr)
        return 2
    defects = validate_defects(design)
    defects.extend(check_frozen_blob(path, design))
    for defect in defects:
        print(f"[{defect.code}] {defect.message}", file=sys.stderr)
    if defects:
        print(f"FAIL: {len(defects)} defect(s)", file=sys.stderr)
        return 1
    print("OK: design is complete, in range, pinned, and equals its committed blob")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
