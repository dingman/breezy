"""PREREG v3 §5 residual classification -- the ONE definition.

Before WP-31 the vocabulary (`FillExclusionReason`, `RESIDUAL_EXCLUSION_REASONS`)
lived in `scripts/analysis/score_live_trials.py` and the `excluded_fills.jsonl`
reader (`ExcludedFill`, `read_excluded_fills`) lived in
`scripts/analysis/family_tally_v2.py`. A `src/` consumer cannot import a
script, so either would have had to be copied -- and a second copy of a
residual predicate is exactly the drift PREREG §5 exists to prevent. Both are
EXTRACTED here verbatim; the two scripts now import them back, so there is
still exactly one definition and every pre-existing message string, key set
and refusal is byte-unchanged.

PREREG v3 §5 (`docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md`):
residual is THREE mutually exclusive per-fill buckets, first-match-wins --
`duplicate_fill`, `q≠1` (spelled `partial_fill`/`multi_fill` here), and
`fee_unreconciled` (spelled `fee_unverified`, and including resolver
GET-FILLED rows which are `fee_reconciled=False` by construction). The
FOURTH bucket, `no_side_first_order_residual`, is registered by **PREREG v3
§5.1 amendment A1 (2026-09-20)** -- last in the first-match-wins ordering,
applying from climate_day 2026-09-15, additive and conservative (L-12:
widened, never relaxed; it only ever REMOVES fills from `n`).

The earlier "PREREG amendment §8" citation carried here was FALSE -- §8 of
that document is "Boundary Artefact" and the document mentioned NO-side
nowhere. Corrected per ruling
`docs/evidence/RULING_v3_admissibility_divergence_2026-09-20.md` R3.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, Literal

__all__ = [
    "EXCLUDED_FILLS_FILENAME",
    "RESIDUAL_EXCLUSION_REASONS",
    "ExcludedFill",
    "ExcludedFillsMalformed",
    "FillExclusionReason",
    "read_excluded_fills",
    "residual_trial_ids",
]

#: distinct from `"duplicate_fill_for_latch"` (v2's "N fills joined ONE
#: latch, pick none" heuristic, unchanged). Widened, never relaxed (L-12): no
#: member removed or re-spelled.
FillExclusionReason = Literal[
    "partial_fill",
    "multi_fill",
    "fill_below_ask",
    "fee_unverified",
    "duplicate_fill_for_latch",
    "no_taken_latch",
    "ambiguous_latch",
    "duplicate_fill",
    # NO-SIDE S5 (E2-1(iii)/E3-3, PREREG v3 §5.1 amendment A1 2026-09-20 --
    # NOT §8, which is "Boundary Artefact"): the first live NO create-path
    # trial, marked residual by the durable first-order key while the
    # bounded containment window (`is_no_side_pending`) is open.
    # Widened, never relaxed (L-12): no member removed or re-spelled.
    "no_side_first_order_residual",
]

#: Slice 4 item B2 (plan rev 6.1) + PREREG v3 §5.1 amendment A1
#: (2026-09-20, the registered fourth bucket): the mutually exclusive
#: residual set -- every unscored fill in one of these buckets contributes
#: `qty * (fill_px + fee)` to `compute_residual`, first-match-wins,
#: `"duplicate_fill"` checked before `"partial_fill"`/`"multi_fill"` (q != 1)
#: before `"fee_unverified"`. `duplicate_fill` is excluded upstream, in
#: `read_filled_trials_state_db`, before a fill ever reaches `_admit_fill`
#: -- so a fill can never land in more than one of these buckets by
#: construction (PREREG mutual-exclusivity requirement);
#: `"no_side_first_order_residual"` is checked LAST, after all three
#: registered buckets, per amendment A1.
RESIDUAL_EXCLUSION_REASONS: Final[frozenset[FillExclusionReason]] = frozenset(
    {
        "duplicate_fill",
        "partial_fill",
        "multi_fill",
        "fee_unverified",
        # NO-SIDE S5 (E3-3), registered by PREREG v3 §5.1 amendment A1
        # (2026-09-20): additive, never relaxed (L-12).
        "no_side_first_order_residual",
    }
)

#: I3c (`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md` 3.0(c)): the
#: driver-local `FillExclusion`'s 8-key artefact line, read back here.
EXCLUDED_FILLS_FILENAME: Final[str] = "excluded_fills.jsonl"
_EXCLUDED_FILL_KEYS: Final[tuple[str, ...]] = (
    "trial_id",
    "station",
    "climate_day",
    "venue_order_id",
    "qty",
    "reason",
    "filled_at_ns",
    "scored_run_utc",
)
#: 3.0(g): `YYYY-MM-DDTHH:MM:SSZ`, UTC and lexically sortable.
_SCORED_RUN_UTC_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
#: shape only (mirrors `_SCORED_RUN_UTC_RE`'s non-calendar-validating style).
_CLIMATE_DAY_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: 3.0(c)/I2 BLOCK-3: the sole reason for which `trial_id`/`station`/
#: `climate_day` may be blank -- a fill whose instrument never reached a
#: taken latch has no trial identity yet.
NO_TAKEN_LATCH_REASON: Final[str] = "no_taken_latch"


class ExcludedFillsMalformed(Exception):
    """A line of `excluded_fills.jsonl` failed its fail-closed validation.

    `family_tally_v2.read_excluded_fills` re-raises this, message verbatim,
    as its own `ScoredTrialDataIntegrityError` so that caller's refusal
    surface is byte-unchanged by the extraction.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class ExcludedFill:
    """One line of `<store_dir>/excluded_fills.jsonl` (I3c, 3.0(c)) --
    driver-local, never a `ScoreRefusal` (that struct carries only
    `trial_id, reason, detail` and is v1-BINDING inside the AST-pure
    `settlement` package)."""

    trial_id: str
    station: str
    climate_day: str
    venue_order_id: str
    qty: Decimal
    reason: str
    filled_at_ns: int
    scored_run_utc: str


def read_excluded_fills(store_dir: Path) -> tuple[ExcludedFill, ...]:
    """Read `<store_dir>/excluded_fills.jsonl` (I3c, 3.0(c)).

    An absent file returns no rows, never an error -- day one has none, not
    a refusal. A malformed line (missing key, bad JSON, a `scored_run_utc`
    not shaped `YYYY-MM-DDTHH:MM:SSZ`, a non-decimal `qty`, a blank
    `venue_order_id`, a blank `trial_id`/`station`/`climate_day` for any
    reason other than `no_taken_latch`, or a `climate_day` not shaped
    `YYYY-MM-DD`) refuses the whole tally loudly.
    """
    path = store_dir / EXCLUDED_FILLS_FILENAME
    if not path.exists():
        return ()
    fills: list[ExcludedFill] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        fills.append(_excluded_fill_from_line(line, path=path, lineno=lineno))
    return tuple(fills)


def _excluded_fill_from_line(line: str, *, path: Path, lineno: int) -> ExcludedFill:
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ExcludedFillsMalformed(
            f"refusing to tally: malformed {path}:{lineno} -- invalid JSON: {exc}"
        ) from exc
    missing = [key for key in _EXCLUDED_FILL_KEYS if key not in row]
    if missing:
        raise ExcludedFillsMalformed(
            f"refusing to tally: malformed {path}:{lineno} -- missing key(s) {missing!r}"
        )
    scored_run_utc = row["scored_run_utc"]
    if not isinstance(scored_run_utc, str) or not _SCORED_RUN_UTC_RE.match(scored_run_utc):
        raise ExcludedFillsMalformed(
            f"refusing to tally: malformed {path}:{lineno} -- scored_run_utc "
            f"{scored_run_utc!r} is not YYYY-MM-DDTHH:MM:SSZ"
        )
    try:
        qty = Decimal(str(row["qty"]))
    except (InvalidOperation, TypeError) as exc:
        raise ExcludedFillsMalformed(
            f"refusing to tally: malformed {path}:{lineno} -- non-decimal qty {row['qty']!r}"
        ) from exc
    try:
        filled_at_ns = int(row["filled_at_ns"])
    except (TypeError, ValueError) as exc:
        raise ExcludedFillsMalformed(
            f"refusing to tally: malformed {path}:{lineno} -- non-integer filled_at_ns "
            f"{row['filled_at_ns']!r}"
        ) from exc
    reason = row["reason"]
    if not isinstance(reason, str) or not reason:
        raise ExcludedFillsMalformed(
            f"refusing to tally: malformed {path}:{lineno} -- empty/non-string reason"
        )
    venue_order_id = row["venue_order_id"]
    if not isinstance(venue_order_id, str) or not venue_order_id:
        raise ExcludedFillsMalformed(
            f"refusing to tally: malformed {path}:{lineno} -- empty/non-string venue_order_id"
        )
    trial_id = row["trial_id"]
    station = row["station"]
    climate_day = row["climate_day"]
    if reason != NO_TAKEN_LATCH_REASON:
        for field_name, value in (
            ("trial_id", trial_id),
            ("station", station),
            ("climate_day", climate_day),
        ):
            if not isinstance(value, str) or not value:
                raise ExcludedFillsMalformed(
                    f"refusing to tally: malformed {path}:{lineno} -- empty/non-string "
                    f"{field_name} (reason {reason!r} requires it; only "
                    f"{NO_TAKEN_LATCH_REASON!r} may leave it blank)"
                )
    if climate_day and (not isinstance(climate_day, str) or not _CLIMATE_DAY_RE.match(climate_day)):
        raise ExcludedFillsMalformed(
            f"refusing to tally: malformed {path}:{lineno} -- climate_day "
            f"{climate_day!r} is not YYYY-MM-DD"
        )
    return ExcludedFill(
        trial_id=trial_id,
        station=station,
        climate_day=climate_day,
        venue_order_id=venue_order_id,
        qty=qty,
        reason=reason,
        filled_at_ns=filled_at_ns,
        scored_run_utc=scored_run_utc,
    )


def residual_trial_ids(store_dir: Path) -> frozenset[str]:
    """Every `trial_id` that `excluded_fills.jsonl` records in a PREREG §5
    residual bucket.

    A blank `trial_id` (only `no_taken_latch` may carry one, and that reason
    is not residual) is never returned -- it identifies no trial and would
    otherwise match nothing or, worse, everything.
    """
    return frozenset(
        fill.trial_id
        for fill in read_excluded_fills(store_dir)
        if fill.trial_id and fill.reason in RESIDUAL_EXCLUSION_REASONS
    )
