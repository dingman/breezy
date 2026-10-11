"""Scored-trial dedupe by ``trial_id`` and the scored-trial directory default (TE-1 WP-A, P34).

Moved verbatim from ``scripts/analysis/portfolio_roi_report.py`` so the label wiring
(``breezy.analysis.labeling``) can reuse one definition without importing a script. The report
re-exports every name, so its callers and tests are unchanged. ``persistence`` sits above
``settlement`` in the layers contract and ``scored_trial_store`` already imports
``breezy.settlement.trial_scorer``, so this adds no new edge.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from breezy.settlement.trial_scorer import ScoredTrial

__all__ = [
    "_SCORED_TRIAL_ECONOMIC_FIELDS",
    "DuplicateScoredTrialEconomicsMismatchError",
    "_default_scored_trials_dir",
    "_scored_trial_economic_fingerprint",
    "dedupe_scored_trials",
]


class DuplicateScoredTrialEconomicsMismatchError(Exception):
    """Two scored-trial rows share a ``trial_id`` but disagree on an
    economic field.

    ``trial_id`` (``trial_id_prefix + station/climate_day/instrument_id``,
    ``family_barrier.py:15-18``) does not encode which FAMILY minted it, and
    two families can share a ``trial_id_prefix`` (e.g. ``pm_us_crh_cont`` and
    ``pm_us_crh_v4`` both mint ``continuous_rung_hold/trial/...``). Most such
    collisions are the SAME settled trade read twice out of two family
    stores -- safe to collapse. But nothing rules out two DIFFERENT trades
    from two families landing on the same ``trial_id``; picking either row
    would silently drop the other's real P&L from ROI and the cash identity.
    This is the fail-closed guard: raised instead, naming the ``trial_id``,
    the same idiom this module already uses for
    :class:`LedgerPartitionViolationError` and :class:`UnknownOrderSideError`
    (a structural-invariant violation, not a routine daily reconciliation
    event) -- ``_run`` handles it identically: one clear stderr line naming
    the error type and the offending ``trial_id`` (never an amount),
    non-zero exit, no report written for that run.
    """


#: Fields that determine a scored trial's contribution to proceeds/P&L --
#: i.e. what makes two rows sharing a ``trial_id`` the SAME trade.
#: Deliberately excludes ``trial_id`` (the group key, identical by
#: construction) and every provenance/store field that can legitimately
#: differ between two readings of the same settled trade: ``scored_at_ns``
#: (which scoring pass produced this row -- the field this function already
#: uses to pick the latest), ``revision_seq``/``raw_sha256`` (which
#: settlement-data revision/raw input backed the row), ``score_seq`` (which
#: scoring run), and ``bucket_source`` (which store it was read from).
_SCORED_TRIAL_ECONOMIC_FIELDS: Final[tuple[str, ...]] = (
    "station",
    "climate_day",
    "instrument_id",
    "settlement_tmax_f",
    "held",
    "pnl",
    "settlement_basis",
    "excluded_reason",
    "slippage",
    "entry_ask",
    "fill_px",
    "fee",
)


def _scored_trial_economic_fingerprint(trial: ScoredTrial) -> tuple[object, ...]:
    """``trial``'s economic identity -- see :data:`_SCORED_TRIAL_ECONOMIC_FIELDS`."""
    return tuple(getattr(trial, field) for field in _SCORED_TRIAL_ECONOMIC_FIELDS)


def dedupe_scored_trials(
    scored_trials: Sequence[ScoredTrial],
) -> tuple[tuple[ScoredTrial, ...], int]:
    """One row per ``trial_id``, keeping the latest ``scored_at_ns`` --
    ONLY when every row sharing that ``trial_id`` is economically the SAME
    trade (:func:`_scored_trial_economic_fingerprint`). Raises
    :class:`DuplicateScoredTrialEconomicsMismatchError` if two rows share a
    ``trial_id`` but disagree on an economic field -- see that error's
    docstring for why a silent pick is never safe.

    The pooled store does not dedupe across family directories
    (``read_scored_trials_pooled``). Two families can share a
    ``trial_id_prefix``, so the same settled trial is readable twice.
    Proceeds, realised P&L and the lag sample must see it once.

    The returned count is the number of rows dropped. Two rows of one
    ``trial_id`` count as 1. On an equal ``scored_at_ns`` the later row
    wins.
    """
    best: dict[str, ScoredTrial] = {}
    order: list[str] = []
    n_duplicate = 0
    for trial in scored_trials:
        current = best.get(trial.trial_id)
        if current is None:
            best[trial.trial_id] = trial
            order.append(trial.trial_id)
            continue
        if _scored_trial_economic_fingerprint(trial) != _scored_trial_economic_fingerprint(current):
            raise DuplicateScoredTrialEconomicsMismatchError(
                f"trial_id={trial.trial_id!r} has two scored rows that disagree "
                "on an economic field -- refusing to collapse or pick one "
                "(they may be two different trades from two families that "
                "share a trial_id prefix, family_barrier.py:15-18)"
            )
        n_duplicate += 1
        if trial.scored_at_ns >= current.scored_at_ns:
            best[trial.trial_id] = trial
    return tuple(best[trial_id] for trial_id in order), n_duplicate


def _default_scored_trials_dir() -> Path:
    override = os.environ.get("BREEZY_SCORED_TRIALS_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "breezy" / "derived" / "scored_trials"
