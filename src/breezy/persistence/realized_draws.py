"""WP-31: REALIZED trade outcomes -> a decision-consumable statistic.

The chain, end to end, with no new arithmetic anywhere in it:

    scored_trials_*.parquet            (`read_scored_trials`, reused)
      -> PREREG v3 §5 admissible filter (`residual_fills`, extracted)
      -> `StratumRow`                   (`stratum_row_from_scored_trial`, extracted)
      -> `combine_station_day`          (reused verbatim)
      -> `CombinedDraw`                 (the statistic WP-26 / the screens consume)

This module is a LOADER. It is deliberately not wired into any live
decision path, and it changes no live family's behaviour.

Why the filter is load-bearing
------------------------------
A residual fill admitted into the ledger silently inflates `n` on a
sequential test that is already spending alpha -- a statistical integrity
failure, not a data-cleanliness nicety. PREREG v3 §5 names three mutually
exclusive residual buckets (`duplicate_fill`, `q≠1`, `fee_unreconciled`);
`residual_fills.RESIDUAL_EXCLUSION_REASONS` is their single definition and
this module never restates it.

A residual fill is normally diverted to `excluded_fills.jsonl` BEFORE it is
ever scored, so it never reaches the parquet at all. It reaches the parquet
when a fill is scored on one run and RECLASSIFIED residual on a later one --
fee reconciliation flipping to `False`, a corrected fill record, a second
genuine fill appearing on an already-consumed station-day. That is not
hypothetical: the live 2026-09-16 `pm_us_crh_cont` store holds four scored
rows, one of which (the MIA `^no` trial) carries a
`no_side_first_order_residual` exclusion. PREREG §5 admits three of them.

`duplicate_fill` and the venue_order_id gap
-------------------------------------------
`ScoredTrial` carries no `venue_order_id`, so when a `duplicate_fill`
exclusion names a `trial_id` that ALSO has a scored row, the parquet alone
cannot say which of the two fills was scored. The loader fails CLOSED and
drops the trial_id: `n` shrinks, never inflates, and PREREG §5 halts the
family on a duplicate fill anyway. Closing the gap properly needs a
`venue_order_id` column on the scored-trial schema -- a schema change, out
of WP-31's scope.

Schema drift
------------
`pq.read_table(path, schema=SCORED_TRIAL_SCHEMA)` SILENTLY drops an
unexpected column and SILENTLY materialises a missing one as all-NULL --
a file missing `held` would decode every trial as `held=None`, i.e. a loss.
:func:`load_realized_draws` therefore compares each file's OWN schema to
`SCORED_TRIAL_SCHEMA` first and raises :class:`RealizedDrawsSchemaDrift`.
The single tolerated absence is `bucket_source`, whose back-compat default
`_scored_trial_from_row` already documents -- widened for that one column,
never relaxed (L-12).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pyarrow.parquet as pq

from breezy.domain.instrument_leg import base_symbol_of, leg_of_symbol, symbol_of_instrument_id
from breezy.persistence.residual_fills import residual_trial_ids
from breezy.persistence.scored_trial_store import SCORED_TRIAL_SCHEMA, read_scored_trials
from breezy.settlement.current_rung_hold_v2 import (
    CombinedDraw,
    StratumRow,
    combine_station_day,
)
from breezy.settlement.trial_scorer import ScoredTrial

__all__ = [
    "RealizedDraws",
    "RealizedDrawsSchemaDrift",
    "admissible_scored_trials",
    "is_admissible",
    "load_realized_draws",
    "stratum_row_from_scored_trial",
]

_FILE_GLOB: Final[str] = "scored_trials_*.parquet"
_FILL_ORDER_FILENAME: Final[str] = "fill_order.jsonl"
#: The ONLY column whose absence is tolerated -- see the module docstring.
_BACK_COMPAT_OPTIONAL_COLUMNS: Final[frozenset[str]] = frozenset({"bucket_source"})


class RealizedDrawsSchemaDrift(Exception):
    """A scored-trial parquet file's columns are not the expected set."""


class RealizedDrawsOrderingRefusal(Exception):
    """A `fill_order.jsonl` sidecar exists but has no entry for an admissible
    row, so the sequential-look order of the draws is undetermined."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RealizedDraws:
    """One family store's realized outcomes, as the statistic and its audit.

    `draws[i]` is the `CombinedDraw` for `station_days[i]`, ordered by the
    EARLIEST constituent fill (`fill_order.jsonl`) so a caller may feed them
    to `score_combined`/`look_verdict` in registered look order.

    The three counts are the audit trail a caller must be able to show: how
    many fills the parquet held, how many PREREG §5 refused, and how many
    survived. `n_admissible_fills` is the CONSTITUENT count; the trial unit
    registered for the sequential test is `len(draws)`, the station-day.
    """

    draws: tuple[CombinedDraw, ...]
    station_days: tuple[tuple[str, str], ...]
    stratum_rows: tuple[StratumRow, ...]
    n_scored_rows: int
    n_admissible_fills: int
    n_dropped_residual: int
    n_dropped_excluded_reason: int


def stratum_row_from_scored_trial(trial: ScoredTrial) -> StratumRow:
    """`side`/`rung` are DERIVED from `trial.instrument_id` (S5 Track D
    fix-first review, plan NO_SIDE_EDGE_2026-09-14 S6a, R3-5 item i) --
    never read via `getattr` on a dormant attribute `ScoredTrial`'s
    17-column schema does not carry (that was the CRITICAL bug: every real
    trial silently reported `side="yes"`/`rung=None`, folding a genuine NO
    trial in as YES). `instrument_id` is a plain `str` (in production
    `str(InstrumentId)`, `"<symbol>.<VENUE>"`; legacy fixtures use a bare
    symbol) -- `symbol_of_instrument_id` strips the optional `.VENUE`
    suffix, `leg_of_symbol`/`base_symbol_of` read the `^no` composite
    suffix, matching `breezy.adapters.polymarket_us.symbology.leg_of`/
    `base_slug_of` byte-for-byte (contract test:
    `test_instrument_leg_layer_agreement_contract.py`).

    `held` is passed through UNCHANGED: `score_trial`
    (`breezy.settlement.trial_scorer`) already inverts it for a NO leg
    (`held = 1{HIGH ∉ r}`), so this function must never invert it a second
    time -- the inversion is applied EXACTLY ONCE, end to end.

    `rung` is the market's own base venue slug, recovered off EITHER leg's
    instrument id -- a YES/NO pair shares one rung slug but has two
    distinct instrument ids.
    """
    symbol = symbol_of_instrument_id(trial.instrument_id)
    side = leg_of_symbol(symbol)
    return StratumRow(
        entry_ask=trial.entry_ask,
        fee=trial.fee,
        held=trial.held,
        station=trial.station,
        side=side,
        rung=base_symbol_of(symbol),
    )


def is_admissible(trial: ScoredTrial, *, residual_trial_ids: frozenset[str]) -> bool:
    """PREREG v3 §5 admissibility for one scored row.

    Three refusals, in order:

    1. `trial_id` carries a residual exclusion (`duplicate_fill` / `q≠1` /
       `fee_unreconciled`, plus `no_side_first_order_residual`, registered
       by PREREG v3 §5.1 amendment A1 2026-09-20 -- NOT §8, which is
       "Boundary Artefact"; corrected per ruling
       `docs/evidence/RULING_v3_admissibility_divergence_2026-09-20.md` R3)
       -- the bucket set is `RESIDUAL_EXCLUSION_REASONS`, never restated
       here.
    2. `excluded_reason is not None` -- the scoring-time
       venue-fallback-without-NWS concept, which the registered
       `family_tally_v2.build_family_tally_v2` already refuses. A loader
       that admitted what the tally refuses would disagree with the
       registered statistic.
    3. `qty != 1` read off the row itself. `ScoredTrial` carries no `qty`
       column today, so `getattr` returns `None` and this guard is DORMANT
       -- exactly as `family_tally_v2._assert_no_partial_or_multi_fill`
       documents. It activates the instant a future schema attaches real
       qty, and it DROPS (PREREG §5 classifies q≠1 as residual) where the
       v2 tally RAISES.
    """
    if trial.trial_id in residual_trial_ids:
        return False
    if trial.excluded_reason is not None:
        return False
    qty = getattr(trial, "qty", None)
    return qty is None or qty == 1


def admissible_scored_trials(
    rows: tuple[ScoredTrial, ...], *, residual_trial_ids: frozenset[str]
) -> tuple[ScoredTrial, ...]:
    """`rows` filtered by :func:`is_admissible`, order preserved."""
    return tuple(row for row in rows if is_admissible(row, residual_trial_ids=residual_trial_ids))


def _assert_no_schema_drift(store_dir: Path) -> None:
    expected = {field.name for field in SCORED_TRIAL_SCHEMA}
    for path in sorted(store_dir.glob(_FILE_GLOB)):
        found = set(pq.read_schema(path).names)
        unexpected = sorted(found - expected)
        if unexpected:
            raise RealizedDrawsSchemaDrift(
                f"refusing to load {path}: unexpected column(s) {unexpected!r} -- "
                "pq.read_table(schema=...) would drop them silently"
            )
        absent = sorted(expected - found - _BACK_COMPAT_OPTIONAL_COLUMNS)
        if absent:
            raise RealizedDrawsSchemaDrift(
                f"refusing to load {path}: missing column(s) {absent!r} -- "
                "pq.read_table(schema=...) would materialise them as all-NULL"
            )


def _fill_order_index(store_dir: Path) -> dict[tuple[str, int], int] | None:
    """`(trial_id, score_seq) -> filled_at_ns` from the `fill_order.jsonl`
    sidecar `score_live_trials.py` appends for every scored fill (B3).

    `None` when the sidecar is absent -- a synthetic or pre-B3 store, for
    which the caller falls back to the `(climate_day, trial_id)`
    chronological proxy `family_tally_v2._ordered_for_looks` uses in the
    same situation.
    """
    path = store_dir / _FILL_ORDER_FILENAME
    if not path.exists():
        return None
    index: dict[tuple[str, int], int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        index[(row["trial_id"], row["score_seq"])] = row["filled_at_ns"]
    return index


def _ordered(rows: tuple[ScoredTrial, ...], *, store_dir: Path) -> tuple[ScoredTrial, ...]:
    index = _fill_order_index(store_dir)
    if index is None:
        return tuple(sorted(rows, key=lambda r: (r.climate_day, r.trial_id)))
    missing = [r.trial_id for r in rows if (r.trial_id, r.score_seq) not in index]
    if missing:
        raise RealizedDrawsOrderingRefusal(
            f"refusing to order realized draws: no {_FILL_ORDER_FILENAME} entry for "
            f"trial_id(s) {missing!r} -- score_live_trials.py must append one per "
            "admitted fill (B3)"
        )
    return tuple(
        sorted(rows, key=lambda r: (index[(r.trial_id, r.score_seq)], r.climate_day, r.trial_id))
    )


def load_realized_draws(store_dir: Path) -> RealizedDraws:
    """Load one family's scored-trial store as PREREG §5-admissible
    station-day :class:`CombinedDraw`\\ s.

    An absent or empty store loads as zero draws, never an error -- a fresh
    deployment that has not filled yet is a normal state, the same contract
    `read_scored_trials` itself carries.

    Raises :class:`RealizedDrawsSchemaDrift` on column drift and
    :class:`RealizedDrawsOrderingRefusal` on an incomplete `fill_order.jsonl`.
    A station-day whose constituent cell probabilities sum above 1 raises
    `StationDayAdmissionRefusal` from `combine_station_day` -- propagated
    unchanged, never caught, because that gate fires at draw construction by
    design.
    """
    if not store_dir.exists():
        return RealizedDraws(
            draws=(),
            station_days=(),
            stratum_rows=(),
            n_scored_rows=0,
            n_admissible_fills=0,
            n_dropped_residual=0,
            n_dropped_excluded_reason=0,
        )
    _assert_no_schema_drift(store_dir)
    rows = read_scored_trials(store_dir)
    residual = residual_trial_ids(store_dir)
    admissible = admissible_scored_trials(rows, residual_trial_ids=residual)
    ordered = _ordered(admissible, store_dir=store_dir)

    groups: dict[tuple[str, str], list[StratumRow]] = {}
    order: list[tuple[str, str]] = []
    for trial in ordered:
        key = (trial.station, trial.climate_day)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(stratum_row_from_scored_trial(trial))

    draws = tuple(combine_station_day(groups[key]) for key in order)
    return RealizedDraws(
        draws=draws,
        station_days=tuple(order),
        stratum_rows=tuple(row for key in order for row in groups[key]),
        n_scored_rows=len(rows),
        n_admissible_fills=len(admissible),
        n_dropped_residual=sum(1 for row in rows if row.trial_id in residual),
        n_dropped_excluded_reason=sum(
            1
            for row in rows
            if row.trial_id not in residual and row.excluded_reason is not None
        ),
    )
