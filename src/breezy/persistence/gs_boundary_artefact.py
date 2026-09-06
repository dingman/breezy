"""Load + sha256-pin-check the PREREG v2 group-sequential boundary artefact.

Lives under `persistence/`, not `settlement/`: this loader does real file
I/O (`Path.read_bytes`, `json.loads`) -- forbidden under the AST-enforced
pure `settlement` package (`tests/unit/test_settlement_purity_guard.py`,
rule D1). The layer contract (`pyproject.toml` `[tool.importlinter]`)
places `persistence` ABOVE `settlement`, the same direction
`scored_trial_store.py` and `family_manifest.py` already use.

`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` rev b SS3/SS7
and `docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md` commit 2. The
artefact itself (`deploy/families/gs_boundary_pm_us_crh_v2.json`) is
produced by the sibling-owned generator
`scripts/analysis/crh_group_sequential_boundaries.py` -- NEVER imported or
edited here (that script sits outside the `breezy` root_packages the
import-linter layer contract governs, and the blueprint's placement rule
explicitly forbids a `src/` -> `scripts/` edge for the pure `settlement`
package; the same direction is preserved here by not importing it at all).

**Duplication, reported not hidden.** The Lan-DeMets / Armitage-McPherson-
Rowe recursive joint-density boundary solver below (`_solve_boundary` and
its helpers) is a second, independent implementation of the identical
algorithm in `scripts/analysis/crh_group_sequential_boundaries.py`
(`boundary_for`, `one_sided_spend`, `_convolve_density`, `_tail_probs`).
This is a deliberate placement decision, not an oversight: PREREG v2 rev b
SS3 requires the LIVE per-look decision to call a solver "at the realized
`t_k`", and the blueprint's layer rule forbids `persistence` (this module)
from importing `scripts/analysis/...` the same way it forbids `settlement`
from doing so. The two implementations are pinned to agree by
`load_boundary_artefact` replaying the committed 16-row reference fixture
on every load (see `_replay_reference_rows`) and refusing to load on any
disagreement -- the mitigation the blueprint's own "Solver-vs-generator
disagreement" risk entry calls for. A future change should consider
extracting the shared numerics into one library both `scripts/` and `src/`
import, but that refactor is out of this file's scope.

Two independent things can go stale and must both be checked before a
report is trusted: (1) `inputs_sha256`, which pins the design PARAMETERS
(alpha, spending function, `n_max`, `i_max`, `look_step`) -- an edited
artefact with different parameters is refused; (2) the recorded
`reference_table` VALUES, which this loader's own solver must reproduce --
a hand-edited or generator-drifted table is refused even if the parameter
hash still matches.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import cumulative_trapezoid
from scipy.optimize import brentq
from scipy.stats import norm

__all__ = [
    "ALPHA_ONE_SIDED",
    "GRID_HALFWIDTH_SD",
    "GRID_NPTS",
    "I_MAX",
    "BoundaryArtefact",
    "BoundaryArtefactError",
    "BoundaryArtefactValidationError",
    "BoundaryPinMismatch",
    "ReferenceRow",
    "SpendingSpec",
    "load_boundary_artefact",
]

#: `n_max/4` -- the Bernoulli variance bound `BE*(1-BE) <= 1/4`, fixed
#: before the first fill (PREREG v2 rev b SS3). Never re-derived from a
#: sample; an artefact declaring any other value is refused.
I_MAX: Final[float] = 40.0

#: Two one-sided tests, each at this level (PREREG v2 rev b SS7). An
#: artefact declaring any other value is refused.
ALPHA_ONE_SIDED: Final[float] = 0.025

#: Numerical-grid resolution for the recursive integration -- matches
#: `crh_group_sequential_boundaries.GRID_NPTS`/`GRID_HALFWIDTH_SD` exactly,
#: so replaying the reference fixture reproduces it to numerical precision,
#: not merely to a looser tolerance chosen to paper over a resolution
#: mismatch.
GRID_NPTS: Final[int] = 2001
GRID_HALFWIDTH_SD: Final[float] = 9.0

#: Absolute tolerance for the load-time reference-fixture replay check.
_REPRODUCTION_TOLERANCE: Final[float] = 1e-6

#: B4 (loader reproduction tolerance): a reference row whose recorded
#: `alpha_spent_eff` AND `alpha_spent_fut` are both below this threshold is
#: an extreme-tail early look (boundaries ~7.8 SD, mathematically
#: unreachable by any real score) where the recursive joint-density
#: integration is numerically ill-conditioned -- tiny grid-resolution
#: differences between this module's solver and the generator's
#: (`crh_group_sequential_boundaries.py`) produce boundary differences well
#: past 1e-6 despite both being correct to their own precision. Such a row
#: compares its `b_eff`/`b_fut` at `_EXTREME_TAIL_REPRODUCTION_TOLERANCE`
#: instead; `alpha_spent` itself is never independently recomputed by this
#: loader (only recorded), so it always keeps the tight tolerance
#: implicitly. Every other row keeps `_REPRODUCTION_TOLERANCE` unchanged.
_EXTREME_TAIL_ALPHA_SPENT_THRESHOLD: Final[float] = 1e-6
_EXTREME_TAIL_REPRODUCTION_TOLERANCE: Final[float] = 5e-2

_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "alpha",
        "i_max",
        "inputs_sha256",
        "look_step",
        "n_max",
        "reference_table",
        "spending_id",
    }
)
_REQUIRED_ROW_KEYS: Final[frozenset[str]] = frozenset(
    {"look_k", "n_k", "t_k", "b_eff", "b_fut", "alpha_spent_eff", "alpha_spent_fut"}
)


class BoundaryArtefactError(Exception):
    """Base for every boundary-artefact load failure."""


class BoundaryArtefactValidationError(BoundaryArtefactError):
    """Malformed artefact: missing key, wrong shape, `i_max`/`alpha` off-pin, empty table."""


class BoundaryPinMismatch(BoundaryArtefactError):
    """`inputs_sha256` drift (self-inconsistent or against the caller's pin), or the
    solver cannot reproduce a recorded reference row."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceRow:
    """One row of the committed 16-row equal-`t` regression fixture.

    REGRESSION ONLY (blueprint SS7): never the live per-look decision path,
    which calls `BoundaryArtefact.boundary_for` at the realized (unequally
    spaced) `t_k`.
    """

    look_k: int
    n_k: int
    t_k: float
    b_eff: float
    b_fut: float
    alpha_spent_eff: float
    alpha_spent_fut: float


@dataclass(frozen=True, slots=True, kw_only=True)
class SpendingSpec:
    """The pinned design parameters the generator's input sha256 covers."""

    spending_id: str
    alpha_one_sided: float
    n_max: int
    look_step: int


@dataclass(frozen=True, slots=True, kw_only=True)
class BoundaryArtefact:
    """A loaded, pin-verified, reference-fixture-verified boundary artefact.

    `boundary_for`/`alpha_spent`/`remaining_alpha` are the LIVE decision
    surface `scripts/analysis/family_tally_v2.py` calls at each look, over
    the realized (data-dependent, possibly unequally spaced) `t_history` --
    never the `reference_rows` table, which is regression-only.
    """

    inputs_sha256: str
    i_max: float
    alpha_one_sided: float
    spending: SpendingSpec
    reference_rows: tuple[ReferenceRow, ...]

    def boundary_for(
        self, t_history: Sequence[float], *, is_terminal: bool = False
    ) -> tuple[float, float]:
        """The current-look `(b_eff, b_fut)` on the Z-scale, given the full
        realized history of information fractions up to and including the
        current look (`t_history[-1]`).

        `is_terminal=True` retargets the LAST look's solve to spend exactly
        the remaining alpha (`alpha_one_sided - alpha_spent(t_history[:-1])`)
        instead of the natural spending-function increment -- the terminal
        look's boundary (PREREG v2 rev b SS4), used by the CLI at
        truncation. A tie (`t_history[-1] == t_history[-2]`) is a valid
        zero-increment look with a degenerate `(+inf, -inf)` boundary
        (CONTINUE-forced); only a strict decrease raises `ValueError`.
        """
        _validate_t_history(t_history)
        return _solve_boundary(tuple(t_history), self.alpha_one_sided, is_terminal=is_terminal)

    def alpha_spent(self, t_history: Sequence[float]) -> float:
        """Natural (non-terminal) cumulative one-sided alpha spent through
        `t_history[-1]`. The Lan-DeMets spending function is a pure function
        of `t` alone (PREREG v2 rev b SS3), so only the last element matters
        -- this is asserted, not merely assumed, by
        `test_alpha_spent_depends_only_on_the_last_t_not_the_path`.
        """
        _validate_t_history(t_history)
        return _one_sided_spend(t_history[-1], self.alpha_one_sided)

    def remaining_alpha(self, t_history_completed: Sequence[float]) -> float:
        """`alpha_one_sided - alpha_spent(last completed look)`, or the full
        `alpha_one_sided` if no scheduled look has yet completed (look 0)."""
        if not t_history_completed:
            return self.alpha_one_sided
        return self.alpha_one_sided - self.alpha_spent(t_history_completed)


def load_boundary_artefact(path: Path, *, expected_sha256: str) -> BoundaryArtefact:
    """Load and strictly validate one boundary-generator artefact JSON file.

    Raises `BoundaryPinMismatch` if the artefact's own `inputs_sha256` does
    not match its recomputed input-manifest hash (a hand-edited file), or
    does not match `expected_sha256` (the caller's pin, e.g. a
    `FamilyManifest.boundary_inputs_sha256`), or if this module's own
    solver cannot reproduce every row of the committed reference table to
    `_REPRODUCTION_TOLERANCE`. Raises `BoundaryArtefactValidationError` on
    a malformed file, `i_max != 40`, or `alpha != 0.025`.
    """
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BoundaryArtefactValidationError(f"{path}: not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BoundaryArtefactValidationError(f"{path}: artefact must be a JSON object")

    missing = _REQUIRED_KEYS - set(payload)
    if missing:
        raise BoundaryArtefactValidationError(f"{path}: missing required key(s): {sorted(missing)}")

    alpha = payload["alpha"]
    i_max = payload["i_max"]
    look_step = payload["look_step"]
    n_max = payload["n_max"]
    spending_id = payload["spending_id"]
    inputs_sha256 = payload["inputs_sha256"]
    reference_table_raw = payload["reference_table"]

    if not isinstance(inputs_sha256, str) or not _looks_like_sha256(inputs_sha256):
        raise BoundaryArtefactValidationError(
            f"{path}: inputs_sha256 must be 64 lowercase hex characters"
        )

    recomputed_manifest = _inputs_manifest(alpha, spending_id, n_max, i_max, look_step)
    recomputed_sha = _sha256_of_inputs(recomputed_manifest)
    if recomputed_sha != inputs_sha256:
        raise BoundaryPinMismatch(
            f"{path}: artefact's own inputs_sha256 {inputs_sha256!r} does not match "
            f"its recomputed input-manifest hash {recomputed_sha!r} -- "
            "the file was hand-edited or the generator drifted"
        )
    if inputs_sha256 != expected_sha256:
        raise BoundaryPinMismatch(
            f"{path}: inputs_sha256 {inputs_sha256!r} does not match the caller's "
            f"pinned expected_sha256 {expected_sha256!r}"
        )

    if float(i_max) != I_MAX:
        raise BoundaryArtefactValidationError(f"{path}: i_max {i_max!r} != {I_MAX!r}")
    if float(alpha) != ALPHA_ONE_SIDED:
        raise BoundaryArtefactValidationError(f"{path}: alpha {alpha!r} != {ALPHA_ONE_SIDED!r}")

    # B5 (look-schedule invariant): every scheduled look_n the driver ever
    # visits is a multiple of look_step up to n_max (family_tally_v2.py's
    # `scheduled_ns = range(look_step, min(n, n_max) + 1, look_step)`) --
    # n_max itself must therefore land exactly on that grid, or the
    # terminal "n_max reached" trigger could never fire on-schedule.
    if int(n_max) % int(look_step) != 0:
        raise BoundaryArtefactValidationError(
            f"{path}: n_max {n_max!r} is not a multiple of look_step {look_step!r} "
            "-- the look schedule would never land exactly on n_max"
        )

    if not isinstance(reference_table_raw, list) or not reference_table_raw:
        raise BoundaryArtefactValidationError(f"{path}: reference_table must be non-empty")

    # Forward-compatible with the generator owner's additive top-level keys
    # (coordinator note, 2026-09-04): only the REQUIRED keys above are
    # asserted -- this loader never asserts an exact top-level key set, so
    # `usage`/`solver_fingerprint` (or any other future additive key) pass
    # through unrejected. `usage`, when present, is a non-authoritative
    # human-readable note that the reference table is regression-only; it
    # is checked only for that substring, never parsed as a control value.
    usage = payload.get("usage")
    if usage is not None and (not isinstance(usage, str) or "regression_fixture_only" not in usage):
        raise BoundaryArtefactValidationError(
            f"{path}: usage key is present but does not state 'regression_fixture_only'"
        )

    reference_rows = tuple(
        _reference_row_from_dict(path, idx, row) for idx, row in enumerate(reference_table_raw)
    )
    _validate_t_history(tuple(row.t_k for row in reference_rows))
    _replay_reference_rows(path, reference_rows, alpha=float(alpha))

    return BoundaryArtefact(
        inputs_sha256=inputs_sha256,
        i_max=float(i_max),
        alpha_one_sided=float(alpha),
        spending=SpendingSpec(
            spending_id=spending_id,
            alpha_one_sided=float(alpha),
            n_max=int(n_max),
            look_step=int(look_step),
        ),
        reference_rows=reference_rows,
    )


def _reference_row_from_dict(path: Path, idx: int, row: Any) -> ReferenceRow:
    if not isinstance(row, dict):
        raise BoundaryArtefactValidationError(
            f"{path}: reference_table[{idx}] must be a JSON object"
        )
    missing = _REQUIRED_ROW_KEYS - set(row)
    if missing:
        raise BoundaryArtefactValidationError(
            f"{path}: reference_table[{idx}] missing key(s): {sorted(missing)}"
        )
    return ReferenceRow(
        look_k=int(row["look_k"]),
        n_k=int(row["n_k"]),
        t_k=float(row["t_k"]),
        b_eff=float(row["b_eff"]),
        b_fut=float(row["b_fut"]),
        alpha_spent_eff=float(row["alpha_spent_eff"]),
        alpha_spent_fut=float(row["alpha_spent_fut"]),
    )


def _replay_reference_rows(path: Path, rows: tuple[ReferenceRow, ...], *, alpha: float) -> None:
    t_history = tuple(row.t_k for row in rows)
    for idx, (row, (b_eff, b_fut)) in enumerate(
        zip(rows, _iter_boundary_looks(t_history, alpha, is_terminal=True), strict=True)
    ):
        is_extreme_tail = (
            row.alpha_spent_eff < _EXTREME_TAIL_ALPHA_SPENT_THRESHOLD
            and row.alpha_spent_fut < _EXTREME_TAIL_ALPHA_SPENT_THRESHOLD
        )
        tolerance = (
            _EXTREME_TAIL_REPRODUCTION_TOLERANCE if is_extreme_tail else _REPRODUCTION_TOLERANCE
        )
        if abs(b_eff - row.b_eff) > tolerance or abs(b_fut - row.b_fut) > tolerance:
            raise BoundaryPinMismatch(
                f"{path}: reference_table[{idx}] (look_k={row.look_k}): this module's "
                f"solver reproduces (b_eff={b_eff!r}, b_fut={b_fut!r}) but the artefact "
                f"records (b_eff={row.b_eff!r}, b_fut={row.b_fut!r}) (tolerance={tolerance!r}, "
                f"extreme_tail={is_extreme_tail!r})"
            )


def _looks_like_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    return all(c in "0123456789abcdef" for c in value)


def _inputs_manifest(
    alpha: float, spending_id: str, n_max: int, i_max: float, look_step: int
) -> dict[str, Any]:
    """Mirrors `crh_group_sequential_boundaries.inputs_manifest` exactly
    (restated, not imported -- see module docstring)."""
    return {
        "alpha": alpha,
        "spending_function_id": spending_id,
        "n_max": n_max,
        "i_max": i_max,
        "look_step": look_step,
    }


def _sha256_of_inputs(manifest: dict[str, Any]) -> str:
    """Mirrors `crh_group_sequential_boundaries.sha256_of_inputs` exactly."""
    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _validate_t_history(t_history: Sequence[float]) -> None:
    if not t_history:
        raise ValueError("t_history must be non-empty")
    prev = 0.0
    for t in t_history:
        if not (0.0 < t <= 1.0):
            raise ValueError(f"t_history value {t!r} is outside (0, 1]")
        if t < prev:
            raise ValueError(
                "t_history must be non-decreasing (a strict decrease is a wiring defect)"
            )
        prev = t


# --- Recursive joint-density boundary solver --------------------------------
#
# Duplicated from `scripts/analysis/crh_group_sequential_boundaries.py`
# (`one_sided_z_half`, `one_sided_spend`, `_convolve_density`,
# `_tail_probs`, `boundary_for`) -- see the module docstring "Duplication,
# reported not hidden" for why this module cannot import that script
# directly.


def _one_sided_z_half(alpha: float) -> float:
    return float(norm.ppf(1.0 - alpha))


def _one_sided_spend(t: float, alpha: float) -> float:
    if t <= 0.0:
        return 0.0
    t = min(t, 1.0)
    z_half = _one_sided_z_half(alpha)
    return 1.0 - float(norm.cdf(z_half / np.sqrt(t)))


def _convolve_density(
    grid_prev: NDArray[np.float64],
    dens_prev: NDArray[np.float64],
    grid_new: NDArray[np.float64],
    dt: float,
) -> NDArray[np.float64]:
    diffs = grid_new[:, None] - grid_prev[None, :]
    kernel = norm.pdf(diffs, 0.0, np.sqrt(dt))
    result: NDArray[np.float64] = np.trapezoid(kernel * dens_prev[None, :], grid_prev, axis=1)
    return result


def _tail_probs(
    grid: NDArray[np.float64], dens: NDArray[np.float64]
) -> tuple[float, Callable[[float], float], Callable[[float], float]]:
    cum = cumulative_trapezoid(dens, grid, initial=0.0)
    total = float(cum[-1])

    def upper(b: float) -> float:
        return total - float(np.interp(b, grid, cum, left=0.0, right=total))

    def lower(b: float) -> float:
        return float(np.interp(b, grid, cum, left=0.0, right=total))

    return total, upper, lower


def _look_step(
    t: float,
    prev_t: float,
    grid: NDArray[np.float64] | None,
    dens: NDArray[np.float64] | None,
    target: float,
    npts: int,
    halfwidth_sd: float,
) -> tuple[float, float, NDArray[np.float64] | None, NDArray[np.float64] | None, float]:
    """Advance the joint-density recursion by one look.

    Returns Brownian-scale `(b_eff, b_fut)`, the truncated `(grid, dens)` to
    carry forward, and `t` as the next `prev_t`. A tie (`dt == 0`) yields a
    degenerate CONTINUE-forced boundary and leaves the density unchanged.
    """
    dt = t - prev_t
    if dt < 0.0:
        raise ValueError("t_history must be non-decreasing (a strict decrease is a wiring defect)")
    if dt == 0.0:
        return float("inf"), float("-inf"), grid, dens, t

    hw = max(6.0, halfwidth_sd * np.sqrt(t))
    newgrid = np.linspace(-hw, hw, npts)
    if grid is None or dens is None:
        newdens = norm.pdf(newgrid, 0.0, np.sqrt(t))
    else:
        newdens = _convolve_density(grid, dens, newgrid, dt)

    _total, upper, lower = _tail_probs(newgrid, newdens)

    def cross_eff(
        b: float, upper: Callable[[float], float] = upper, target: float = target
    ) -> float:
        return upper(b) - target

    def cross_fut(
        b: float, lower: Callable[[float], float] = lower, target: float = target
    ) -> float:
        return lower(b) - target

    b_eff = brentq(cross_eff, newgrid[0], newgrid[-1], xtol=1e-10)
    b_fut = brentq(cross_fut, newgrid[0], newgrid[-1], xtol=1e-10)
    mask = (newgrid > b_fut) & (newgrid < b_eff)
    return b_eff, b_fut, newgrid, newdens * mask, t


def _iter_boundary_looks(
    t_history: tuple[float, ...],
    alpha: float,
    *,
    is_terminal: bool,
    npts: int = GRID_NPTS,
    halfwidth_sd: float = GRID_HALFWIDTH_SD,
) -> Iterator[tuple[float, float]]:
    """Yield Z-scale `(b_eff, b_fut)` at each look, carrying density forward.

    `is_terminal=True` retargets only the LAST look to remaining alpha.
    Arbitrary live `t_history` still starts from t=0 on every call; equal-t
    replay/table builders consume this generator once instead of restarting.
    """
    if not t_history:
        raise ValueError("t_history must be non-empty")
    target_cum = [_one_sided_spend(t, alpha) for t in t_history]
    incr = np.diff(np.concatenate(([0.0], target_cum)))

    grid: NDArray[np.float64] | None = None
    dens: NDArray[np.float64] | None = None
    prev_t = 0.0
    n_looks = len(t_history)
    for idx, t in enumerate(t_history):
        is_last = idx == n_looks - 1
        if is_terminal and is_last:
            prev_natural_cum = target_cum[idx - 1] if idx > 0 else 0.0
            target = alpha - prev_natural_cum
        else:
            target = float(incr[idx])
        b_eff, b_fut, grid, dens, prev_t = _look_step(
            t, prev_t, grid, dens, target, npts, halfwidth_sd
        )
        z_scale = np.sqrt(t)
        yield b_eff / z_scale, b_fut / z_scale


def _solve_boundary(
    t_history: tuple[float, ...],
    alpha: float,
    *,
    is_terminal: bool,
    npts: int = GRID_NPTS,
    halfwidth_sd: float = GRID_HALFWIDTH_SD,
) -> tuple[float, float]:
    result: tuple[float, float] | None = None
    for result in _iter_boundary_looks(
        t_history, alpha, is_terminal=is_terminal, npts=npts, halfwidth_sd=halfwidth_sd
    ):
        pass
    if result is None:
        raise ValueError("t_history must be non-empty")
    return result
