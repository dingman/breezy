#!/usr/bin/env python
"""R3-VIABILITY plan r1 §3.5/§4; r2 delta "R3V-b": the pre-freeze
replay-corpus viability screen for R3 (batched daily replay).

**What this answers.** Whether the pre-freeze replay corpus -- the days
`replay_daily_runner.py`'s batch mode (R3V-a) has already replayed, or will
replay during the two-night backfill -- gives a plausible chance that R3's
post-freeze accrual rate will ever clear the bar the 2027-01-25 triage
needs. It is a SCREEN, not R3's own CONFIRM count (see "R3-E" below).

**n and k (r1 §5; r2 delta item 1).** ``n`` counts rows that are
COMPLETED, non-fee-void (:func:`breezy.analysis.replay_results.is_fee_schedule_void`),
whole-day (:func:`breezy.analysis.replay_sufficiency.is_replayable_whole_day`),
and pre-freeze -- see :func:`eligible_rows`. ``k`` is the subset of those
``n`` rows that produced at least one fill: whether the mechanism actually
traded that day is the observed "success" this screen powers on. Below
``n = 20`` (:data:`MIN_N`) the sample is too small to say anything; the
verdict is ``INSUFFICIENT_N`` regardless of ``k``.

**FIREWALL (binding).** Every row with ``climate_day > FREEZE_CLIMATE_DAY``
is dropped by :func:`eligible_rows` BEFORE any other field of that row --
including ``fills`` -- is ever read. :func:`compute_viability` only reads
``.fills`` on rows :func:`eligible_rows` has already returned, so a
post-freeze row's fill count is structurally never read by this module
(`tests/unit/test_r3_viability.py::test_fills_is_never_read_on_a_post_freeze_row`
proves it with a duck-typed spy).

**Freeze date (r2 delta item 2).** Sourced from the hypothesis register's
own freeze record, ``hypothesis_register.NO_SIDE_RULING_DATE`` -- never a
new literal -- and shared with `replay_daily_runner.py`'s own
``FREEZE_CLIMATE_DAY`` (its post-freeze COMPLETED-line log withholding).
``climate_day == FREEZE_CLIMATE_DAY`` itself counts as pre-freeze; the
firewall binds strictly AFTER it.

**Wilson interval (r2 delta item 3).** ``z = 1.96``
(:data:`archive_correction_probe.Z_95`), reported as "two-sided 95% /
one-sided 97.5% upper bound" -- the upper bound is what the decision rule
below reads.

**f_req (r1 §4; r2 delta item 4).** ``f_req = 300 / (r_max * D)``. ``300``
is 50% of 600 (``EDGE-4_DISPOSITION_2026-09-27.md:22``). ``r_max = 4``
station-days/day is the STRUCTURAL cap: the census counts NYC too, but NYC
is never CONFIRM-eligible (``SUPPORTED_STATIONS``,
``current_rung_hold/config.py:76``; excluded at
``replay_daily_runner.py:403``), so R3-PROJ's 5/day census figure
overstates the CONFIRM-eligible rate by exactly the one NYC slot. ``D =
120`` is the number of post-freeze climate days with a replay row expected
before the 01:20Z triage on 2027-01-25.

**Decision rule (r1 §4).** After the backfill, if the Wilson 95% upper
bound of ``k/n`` (pre-freeze) is below ``f_req``, R3 is ruled NOT_VIABLE.
Pre-freeze ``f`` describes the SEARCH corpus, so it is an upper-bound
screen, never a post-freeze CONFIRM estimate.

**R3-E.** This ruling is pre-freeze and replay-derived; it cites no census
CONFIRM count. R3-E binds only a LATER CONFIRM count -- this module's
output is never substituted for it.

**Never run against the real derived directory from a test** -- every test
in `tests/unit/test_r3_viability.py` passes an explicit `tmp_path` results/
sufficiency pair; nothing here reads
`~/.local/share/breezy/derived/replay/replay_results.jsonl` except a real,
human-invoked `main()` run.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_correction_probe import Z_95, wilson_interval
from hypothesis_register import NO_SIDE_RULING_DATE

from breezy.analysis.replay_results import (
    ReplayResult,
    is_fee_schedule_void,
    read_replay_results,
)
from breezy.analysis.replay_sufficiency import (
    ReplaySufficiency,
    is_replayable_whole_day,
    read_replay_sufficiency,
)

__all__ = [
    "D_TRIAGE_HORIZON_DAYS",
    "FREEZE_CLIMATE_DAY",
    "MIN_N",
    "R_MAX_STATION_DAYS_PER_DAY",
    "ReplayResultLike",
    "ViabilityResult",
    "ViabilityVerdict",
    "compute_viability",
    "eligible_rows",
    "main",
    "required_f",
]

#: r2 delta "R3V-b" item 2: sourced from the hypothesis register's own
#: freeze record, never a new literal. Shared with
#: `replay_daily_runner.FREEZE_CLIMATE_DAY` (module docstring above).
FREEZE_CLIMATE_DAY: Final[str] = NO_SIDE_RULING_DATE

#: r2 delta item 1: below this, the verdict is INSUFFICIENT_N regardless of k.
MIN_N: Final[int] = 20

#: r1 §4 / r2 delta item 4: the structural per-day CONFIRM-eligible cap.
R_MAX_STATION_DAYS_PER_DAY: Final[int] = 4
#: r1 §4: post-freeze climate days with a replay row expected before the
#: 01:20Z triage on 2027-01-25.
D_TRIAGE_HORIZON_DAYS: Final[int] = 120

ViabilityVerdict = Literal["NOT_VIABLE", "VIABLE", "INSUFFICIENT_N"]


class ReplayResultLike(Protocol):
    """The minimal shape `eligible_rows`/`compute_viability` need from a
    replay-result row -- satisfied by :class:`ReplayResult` and by the test
    suite's duck-typed FIREWALL spy without either importing the other."""

    @property
    def station(self) -> str: ...

    @property
    def climate_day(self) -> str: ...

    @property
    def outcome(self) -> str: ...

    @property
    def refusal_counts(self) -> object: ...

    @property
    def fills(self) -> int: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ViabilityResult:
    """One `r3_viability` verdict: k, n, the Wilson bounds, f_req and the
    resulting :data:`ViabilityVerdict`."""

    k: int
    n: int
    wilson_lower: float
    wilson_upper: float
    f_req: float
    verdict: ViabilityVerdict


def required_f() -> float:
    """f_req = 300 / (r_max * D) (r1 §4; r2 delta item 4). ``300`` is 50%
    of 600 (`EDGE-4_DISPOSITION_2026-09-27.md:22`)."""
    return 300 / (R_MAX_STATION_DAYS_PER_DAY * D_TRIAGE_HORIZON_DAYS)


def _is_pre_freeze(climate_day: str) -> bool:
    """FIREWALL step 1: ISO `YYYY-MM-DD` strings compare correctly
    lexicographically. `climate_day == FREEZE_CLIMATE_DAY` is pre-freeze;
    the firewall binds strictly AFTER it (module docstring)."""
    return climate_day <= FREEZE_CLIMATE_DAY


def eligible_rows(
    *,
    results: Sequence[ReplayResultLike],
    sufficiency: Sequence[ReplaySufficiency],
) -> tuple[ReplayResultLike, ...]:
    """COMPLETED, non-fee-void, whole-day, pre-freeze rows only (r2 delta
    "R3V-b" item 1).

    FIREWALL: a row's `climate_day` is checked, and the row dropped if
    post-freeze, BEFORE any other field of that row -- `outcome`,
    `refusal_counts`, and above all `fills` -- is read. `fills` itself is
    never read here at all; :func:`compute_viability` reads it only on the
    tuple this function returns.
    """
    whole_days = {
        (row.station, row.climate_day)
        for row in sufficiency
        if is_replayable_whole_day(row)
    }
    eligible: list[ReplayResultLike] = []
    for row in results:
        if not _is_pre_freeze(row.climate_day):
            continue
        if row.outcome != "COMPLETED":
            continue
        if (row.station, row.climate_day) not in whole_days:
            continue
        if is_fee_schedule_void(row):  # type: ignore[arg-type]
            continue
        eligible.append(row)
    return tuple(eligible)


def compute_viability(
    *,
    results: Sequence[ReplayResultLike],
    sufficiency: Sequence[ReplaySufficiency],
) -> ViabilityResult:
    """`eligible_rows` first (the FIREWALL), then -- and only then -- read
    `.fills` on the surviving pre-freeze rows to form k/n."""
    eligible = eligible_rows(results=results, sufficiency=sufficiency)
    n = len(eligible)
    k = sum(1 for row in eligible if row.fills > 0)
    wilson_lower, wilson_upper = wilson_interval(k, n, z=Z_95)
    f_req = required_f()
    verdict: ViabilityVerdict
    if n < MIN_N:
        verdict = "INSUFFICIENT_N"
    elif wilson_upper < f_req:
        verdict = "NOT_VIABLE"
    else:
        verdict = "VIABLE"
    return ViabilityResult(
        k=k, n=n, wilson_lower=wilson_lower, wilson_upper=wilson_upper,
        f_req=f_req, verdict=verdict,
    )


def _default_replay_root() -> Path:
    return Path.home() / ".local" / "share" / "breezy" / "derived" / "replay"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    root = _default_replay_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replay-results", type=Path, default=root / "replay_results.jsonl",
    )
    parser.add_argument(
        "--replay-sufficiency", type=Path, default=root / "replay_sufficiency.jsonl",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    results: Sequence[ReplayResult] = read_replay_results(args.replay_results)
    sufficiency = read_replay_sufficiency(args.replay_sufficiency)
    result = compute_viability(results=results, sufficiency=sufficiency)
    print(
        f"R3_VIABILITY k={result.k} n={result.n} "
        f"wilson_95=({result.wilson_lower:.4f}, {result.wilson_upper:.4f}) "
        "[two-sided 95% / one-sided 97.5% upper bound] "
        f"f_req={result.f_req:.4f} verdict={result.verdict}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
