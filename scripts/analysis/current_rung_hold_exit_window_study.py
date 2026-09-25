"""Offline "exit window" study driver
(``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md``).

BUILD-TIME analysis only -- never touches the live node, the live exec state
store, or any order/execution path. The exec state store is opened READ-ONLY
by ``score_live_trials.read_filled_trials_state_db`` itself; the caller is
expected to pass a read-only COPY of the store, never the live path.

Reads:

* Filled live positions from a copy of the exec ``SqliteStateStore``, via
  ``score_live_trials.read_filled_trials_state_db`` (imported unmodified --
  its signature is frozen, Stage-0). Each trial's rung is resolved the same
  way ``score_live_trials.score_live_trials`` resolves it: ``_read_bucket_
  facts_by_instrument_id`` against the persisted instrument definitions.
* Each station's NWS ASOS observation tape, ``--obs-source {cache,fetch}``
  (default ``cache``): read from the EXISTING settlement-alignment archive
  cache on disk, the SAME fixed-window cache key
  ``current_rung_hold_monitor_hypothetical_hold._load_observations_for_
  station`` uses; ``fetch`` allows a network fetch ONLY on a cache miss, via
  ``settlement_alignment_study.fetch_text_cached`` (the SAME helper
  ``asos_recent_refresh.py`` uses -- ``client.get(...)`` only, never a
  write-shaped HTTP verb, so this module stays clear of the write-egress
  firewall scan) and writes the result into the cache so the next run is
  offline. A cache miss under ``cache`` is reported as a missing input,
  never fabricated. An HTTP or transport failure on one station's fetch is
  likewise a missing input (the station and status are named) and the other
  stations still run. ``fetch_text_cached`` itself still raises, so other
  callers are unchanged. The process exits non-zero only when every station
  that attempted a fetch failed and no station loaded ASOS text, so a total
  outage still trips the unit's OnFailure alert. A partial outage exits 0.
* Each instrument's captured Depth10 frames, ``--depth-source
  {catalog,staged}`` (default: auto-select per position). ``catalog``: the
  committed quote-tape ``ParquetDataCatalog`` (``current_rung_hold_monitor_
  hypothetical_hold._load_depth_frames``, imported unmodified). ``staged``:
  the recorder's own not-yet-converted feather frames under every
  trader-instance directory (ING-1: the parquet converter can strand a
  station's committed catalog well behind the still-capturing recorder).
  Auto-selection uses ``staged`` only when the catalog's newest frame
  precedes the position's fill; each row records which source it used
  (``PositionExitRow.depth_source``). A NO-leg position's frames are read
  under its SIBLING YES instrument id (``monitor_evidence``'s NO-leg
  docstring: there is only one live order book per market).
* Settlement truth, most authoritative first: (1) a scored-trial row for
  this ``trial_id`` (``breezy.persistence.scored_trial_store
  .read_scored_trials``); (2) a non-superseded FINAL NWS CLI record in the
  settlement catalog (``ma_prelock_winner_ask_study.load_settled_tmax_for_day``,
  imported unmodified); (3) a PRELIMINARY guess from the final running max
  (``exit_window_core.infer_preliminary_settlement``), clearly flagged.

All replay/rule logic is pure and lives in ``exit_window_core.py`` /
``exit_window_report.py`` (imported unmodified) -- this module is I/O glue
only, mirroring ``current_rung_hold_monitor_hypothetical_hold.py``'s own
split for INC-8.

Writes one JSON + one Markdown file per run under
``~/.local/share/breezy/derived/exit_window_study/<run-stamp>/``.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import json
import logging
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
import pyarrow as pa
from current_rung_hold_monitor_hypothetical_hold import _load_depth_frames
from exit_window_core import FilledPosition, build_exit_timeline, infer_preliminary_settlement
from exit_window_report import (
    PositionExitRow,
    build_position_exit_row,
    build_summary,
    render_markdown,
)
from ma_prelock_winner_ask_study import (
    ASOS_FETCH_END,
    ASOS_FETCH_START,
    DEFAULT_QUOTE_TAPE_CATALOG,
    DEFAULT_SETTLEMENT_CATALOG,
    load_settled_tmax_for_day,
)
from monitor_hypothetical_core import ObservationRow
from nautilus_trader.model.data import OrderBookDepth10
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer
from portfolio_roi_report import (
    PortfolioRoiReportMalformedFieldError,
    PortfolioRoiTrialRow,
    UnknownPortfolioRoiSchemaError,
    read_portfolio_roi_report,
)
from score_live_trials import (
    DEFAULT_DERIVED_DIR,
    _read_bucket_facts_by_instrument_id,
    read_filled_trials_state_db,
)
from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
from settlement_alignment_study import (
    USER_AGENT,
    HistoricalDataClient,
    SiteSpec,
    asos_url,
    cache_path_for_url,
    fetch_text_cached,
    load_sites,
    parse_asos_rows,
)
from settlement_truth_dataset import bucket_facts

from breezy.domain.climate_day import climate_day_for_instant
from breezy.domain.instrument_leg import base_symbol_of, leg_of_symbol, symbol_of_instrument_id
from breezy.domain.season import season_for
from breezy.domain.weather_bucket_facts import WeatherBucketFacts, read_weather_bucket_facts
from breezy.ingest.iem_observations import iem_asos_rows_to_station_observations
from breezy.persistence.scored_trial_store import read_scored_trials_pooled
from breezy.registry.sites import default_registry
from breezy.runtime import alert_ladder
from breezy.runtime.health import AlertPayload, AlertSink, emit_alert, resolve_alert_sink
from breezy.settlement.trial_scorer import FilledTrial, ScoredTrial
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.monitor_evidence import Leg
from breezy.strategy.current_rung_hold.trial_day_latch import CONTINUOUS_TRIAL_KEY_PREFIX
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator

__all__ = ["main", "run_exit_window_study"]

_VENUE: Final[str] = "polymarket_us"
_DEFAULT_OUT_ROOT: Final[Path] = Path.home() / ".local/share/breezy/derived/exit_window_study"
#: Root of every trader-instance's staged (not-yet-converted-to-parquet)
#: recorder output -- ``_load_staged_depth_frames`` globs every instance
#: under it, never one hardcoded id.
_DEFAULT_LIVE_CATALOG_ROOT: Final[Path] = (
    Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us/live"
)
#: Archive rows carry no separate receipt instant (module docstring's ASOS
#: note, mirroring every sibling analysis reader's convention) -- this only
#: needs to be a real, always-visible-in-the-future instant.
_PLACEHOLDER_RECEIVED_AT_NS: Final[int] = 2**62

# --------------------------------------------------------------------------
# AUD-07 D -- EXIT_CORPUS_FROZEN, on AUD-04's shared alert_ladder
# (breezy.runtime.alert_ladder). This control owns its own latch file, its
# own state file (the previous run's trial_id set), and its own event
# names -- the streak/period-key state machine is imported, never
# re-implemented (round 3 of the AUD-04/AUD-07 plan review).
# --------------------------------------------------------------------------

EXIT_CORPUS_FROZEN_EVENT: Final[str] = "EXIT_CORPUS_FROZEN"
EXIT_CORPUS_FROZEN_CLEARED_EVENT: Final[str] = "EXIT_CORPUS_FROZEN_CLEARED"
#: Path is literal per the plan (`docs/plans/backlog/AUDIT_2026-09-21/
#: AUD-07-exit-seam-arming-verification-path.md` §6 D), under `out_root`
#: (never per-run-stamp -- it must persist ACROSS runs).
_FROZEN_STREAK_LATCH_FILENAME: Final[str] = ".frozen_streak.json"
#: This item's own previous-run state: the trial_id set the LAST run saw,
#: so "N grew" vs "N is frozen" is derived from an actual prior observation,
#: never assumed. Absent on the very first run ever (streak stays 0, no
#: alert -- nothing to compare against yet).
_PREVIOUS_TRIAL_IDS_FILENAME: Final[str] = ".previous_trial_ids.json"


def _read_previous_trial_ids(path: Path) -> frozenset[str] | None:
    """`None` (never observed before) on a missing or unparseable file --
    fail-closed toward "nothing to compare", never toward "frozen"."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    trial_ids = payload.get("trial_ids")
    if not isinstance(trial_ids, list) or not all(isinstance(t, str) for t in trial_ids):
        return None
    return frozenset(trial_ids)


def _write_previous_trial_ids(path: Path, trial_ids: frozenset[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"trial_ids": sorted(trial_ids)}, sort_keys=True), encoding="utf-8"
    )


def _apply_ladder(
    *, is_fresh: bool, latch: alert_ladder.LatchState, now_ns: int,
    stale_event: str, cleared_event: str, stale_detail: str, cleared_detail: str,
) -> tuple[alert_ladder.LatchState, AlertPayload | None]:
    """Shared plumbing behind :func:`apply_corpus_frozen_ladder` and
    :func:`apply_pnl_reconciliation_ladder` -- mirrors
    `portfolio_roi_report._apply_ladder` byte-for-byte in shape (one shared
    `alert_ladder` state machine, two LOCAL consumers, each with its own
    latch file and event names -- D8's ownership rule)."""
    previous_streak = latch.streak
    streak = alert_ladder.next_streak(is_fresh=is_fresh, previous_streak=previous_streak)

    if is_fresh:
        new_latch = alert_ladder.LatchState(
            schema_version=alert_ladder.LATCH_SCHEMA_VERSION,
            streak=0, last_alert_severity=None, last_alert_period_key=None,
        )
        if previous_streak >= alert_ladder.WARN_STREAK_THRESHOLD:
            return new_latch, AlertPayload(
                severity="INFO", event=cleared_event,
                site="current_rung_hold_exit_window_study", detail=cleared_detail,
            )
        return new_latch, None

    decision = alert_ladder.evaluate_streak(
        streak=streak, last_alert_severity=latch.last_alert_severity,
        last_alert_period_key=latch.last_alert_period_key, now_ns=now_ns,
    )
    new_latch = alert_ladder.LatchState(
        schema_version=alert_ladder.LATCH_SCHEMA_VERSION,
        streak=streak,
        last_alert_severity=(
            decision.severity if decision.should_alert else latch.last_alert_severity
        ),
        last_alert_period_key=(
            decision.period_key if decision.should_alert else latch.last_alert_period_key
        ),
    )
    if not decision.should_alert:
        return new_latch, None
    assert decision.severity is not None
    return new_latch, AlertPayload(
        severity=decision.severity, event=stale_event,
        site="current_rung_hold_exit_window_study", detail=stale_detail,
    )


EXIT_PNL_RECONCILIATION_MISMATCH_EVENT: Final[str] = "EXIT_PNL_RECONCILIATION_MISMATCH"
EXIT_PNL_RECONCILIATION_MISMATCH_CLEARED_EVENT: Final[str] = (
    "EXIT_PNL_RECONCILIATION_MISMATCH_CLEARED"
)
#: Own latch (D8's per-consumer file rule); restart-surviving, same ladder
#: cadence as `_FROZEN_STREAK_LATCH_FILENAME`.
_PNL_RECONCILIATION_LATCH_FILENAME: Final[str] = ".pnl_reconciliation_mismatch.json"
#: The reconciliation matches to the cent while no exit has ever fired
#: (`exit_gate.py:55`'s `pm_us_crh_exit_v4` stays `DRAFT_NOT_REGISTERED`) --
#: any non-zero divergence is therefore an alarm, not expected slack.
_RECONCILIATION_TOLERANCE: Final[Decimal] = Decimal(0)
#: Coordinator ruling (2026-09-25, domain review items 2/3): the exit-window
#: study runs at 15:20Z; AUD-04 (`breezy-portfolio-roi.timer`) runs at
#: 17:40Z. Comparing today's cumulative sum_hold_pnl against YESTERDAY's
#: AUD-04 total at zero tolerance produced spurious mismatches. A report
#: older than this many days past the run date is stale and SKIPPED rather
#: than compared.
_MAX_AUD04_STALENESS_DAYS: Final[int] = 2
#: Domain review item 3: this caveat must appear in the stderr line AND the
#: alert detail text, not only in a docstring.
_AUD04_RECONCILIATION_CAVEAT: Final[str] = (
    "report-level total, not per-trial; offsetting per-trial errors are invisible"
)


def _utc_date_from_ns(now_ns: int) -> str:
    return dt.datetime.fromtimestamp(now_ns / 1_000_000_000, tz=dt.UTC).date().isoformat()


def aud04_reconciliation_readiness(
    *, settled_through: str, run_date: str, max_staleness_days: int = _MAX_AUD04_STALENESS_DAYS,
) -> tuple[str | None, str | None]:
    """Decide whether AUD-04's report can be reconciled against today's run,
    and if so, the CUTOFF to restrict both sides to (domain review item 2).

    Returns ``(cutoff, skip_reason)`` -- exactly one is ``None``.
    ``settled_through`` (`PortfolioRoiReportView.settled_through`) is
    AUD-04's own climate-day bound past which its daily rows are provisional
    (`apply_settled_through`'s docstring) -- the best available "as-of"
    field the published schema carries; used here as the join cutoff for
    BOTH sides, never assumed same-day. Skips (never compares mismatched
    periods) when ``settled_through`` does not parse as an ISO-8601 date, or
    when it is more than ``max_staleness_days`` before ``run_date``.
    """
    try:
        settled_through_date = dt.date.fromisoformat(settled_through)
    except ValueError:
        return None, (
            f"AUD-04 settled_through={settled_through!r} is not a usable ISO-8601 date"
        )
    try:
        run_date_parsed = dt.date.fromisoformat(run_date)
    except ValueError:
        return None, f"run_date={run_date!r} is not a usable ISO-8601 date"
    age_days = (run_date_parsed - settled_through_date).days
    if age_days > max_staleness_days:
        return None, (
            f"WARN: AUD-04 report is stale -- settled_through={settled_through} is "
            f"{age_days} day(s) before run_date={run_date} (max {max_staleness_days})"
        )
    return settled_through, None


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Aud04ReconciliationResult:
    """One reconciliation read against AUD-04's published report, restricted
    on BOTH sides to `cutoff` (domain review item 2 -- "reconcile like with
    like", never today's cumulative exit-side sum against yesterday's
    AUD-04 total).

    **Scope, narrowed 2026-09-25 (per-row upgrade): this is now the
    `schema_version=1` FALLBACK path only.** AUD-04 has since shipped
    `trial_rows` (Stage C3, `schema_version=2`) -- its own mirror obligation
    from AUD-04 plan §8 AC#4 -- so a per-`trial_id` join is possible and is
    the PREFERRED comparison; see `reconcile_with_aud04_per_trial`. This
    report-level total comparison stays in force only when AUD-04's artefact
    predates that field (`PortfolioRoiReportView.trial_rows is None`), where
    it still carries the same residual limitation as before: offsetting
    per-trial errors on either side are invisible to a bare total, which is
    why the caller must call the per-row form whenever `trial_rows` is
    available rather than falling back to this one.
    """

    matched: bool
    cutoff: str
    sum_hold_pnl: Decimal | None
    aud04_realised_pnl_after_fees_total: Decimal
    divergence: Decimal | None


def reconcile_with_aud04(
    *, rows: Sequence[PositionExitRow], cutoff: str, aud04_realised_pnl_after_fees_total: Decimal,
) -> Aud04ReconciliationResult:
    """Pure comparison -- no I/O. Restricts the exit-side sum to positions
    with `climate_day <= cutoff` (the same universe/cutoff AUD-04's own
    `settled_through` bounds), never the study's full cumulative history.
    An empty cutoff-restricted set reconciles trivially against a zero
    AUD-04 total only; any non-zero AUD-04 total against an empty
    cutoff-restricted study is an unjoined-row mismatch.
    """
    cutoff_rows = tuple(row for row in rows if row.position.climate_day <= cutoff)
    known_hold_pnl = [row.hold_pnl for row in cutoff_rows if row.hold_pnl is not None]
    sum_hold_pnl = sum(known_hold_pnl, Decimal(0)) if known_hold_pnl else None
    if sum_hold_pnl is None:
        divergence = aud04_realised_pnl_after_fees_total
    else:
        divergence = sum_hold_pnl - aud04_realised_pnl_after_fees_total
    matched = abs(divergence) <= _RECONCILIATION_TOLERANCE
    return Aud04ReconciliationResult(
        matched=matched, cutoff=cutoff, sum_hold_pnl=sum_hold_pnl,
        aud04_realised_pnl_after_fees_total=aud04_realised_pnl_after_fees_total,
        divergence=divergence,
    )


#: §7 step 5 (per-row upgrade, 2026-09-25): the alert detail names at most
#: this many divergent `trial_id`s, so a large mismatch still produces a
#: bounded, readable line rather than an unbounded one.
_MAX_NAMED_DIVERGENT_TRIAL_IDS: Final[int] = 10


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Aud04PerTrialReconciliationResult:
    """Per-`trial_id` join between this study's exit-side rows and AUD-04's
    `trial_rows` (`schema_version>=2`) -- the per-row form
    `Aud04ReconciliationResult`'s own docstring points to. Unlike the
    report-level total, this catches an EQUAL-AND-OPPOSITE per-trial error
    pair whose sum happens to match: every `trial_id` present on both sides
    is compared individually at the same zero tolerance
    (`_RECONCILIATION_TOLERANCE`) the total-level check uses, and a
    `trial_id` present on only one side is reported, never silently dropped.

    A `trial_id` occurring MORE THAN ONCE on either side (`n_duplicate_exit`/
    `n_duplicate_aud04`) is always divergent when joined, regardless of
    whether its values happen to compare equal -- a naive dict keyed on
    `trial_id` silently collapses duplicates to last-write-wins, which can
    reconcile as a false MATCH exactly when the duplicated rows' values
    happen to sum to the other side's single value (review finding, 2026-09-25).
    """

    matched: bool
    cutoff: str
    n_matched: int
    n_exit_only: int
    n_aud04_only: int
    n_divergent: int
    #: Count of DISTINCT trial_ids occurring more than once among the
    #: cutoff-restricted rows on that side (review finding, 2026-09-25).
    n_duplicate_exit: int = 0
    n_duplicate_aud04: int = 0
    #: First `_MAX_NAMED_DIVERGENT_TRIAL_IDS` divergent trial ids, sorted --
    #: for the alert detail. `n_divergent` is the true (unbounded) count.
    divergent_trial_ids: tuple[str, ...]
    exit_only_trial_ids: tuple[str, ...]
    aud04_only_trial_ids: tuple[str, ...]


def reconcile_with_aud04_per_trial(
    *,
    rows: Sequence[PositionExitRow],
    cutoff: str,
    aud04_trial_rows: Sequence[PortfolioRoiTrialRow],
) -> Aud04PerTrialReconciliationResult:
    """Pure comparison -- no I/O. Both sides are restricted to `climate_day
    <= cutoff` (the same universe/cutoff rule `reconcile_with_aud04` uses).
    An exit-side row whose `hold_pnl` is `None` (settlement truth not yet
    known for that trial) cannot be compared and is counted as divergent
    rather than silently treated as a match.

    Duplicate `trial_id`s on either side are counted with a `Counter`
    BEFORE either side is collapsed into a `{trial_id: pnl}` dict -- a plain
    dict comprehension silently keeps only the LAST row for a repeated key,
    which can reconcile as a false match (review finding, 2026-09-25). A
    joined `trial_id` duplicated on either side is always divergent here,
    regardless of whether the (arbitrary, last-write) value it collapsed to
    happens to compare equal.
    """
    cutoff_exit_rows = tuple(row for row in rows if row.position.climate_day <= cutoff)
    cutoff_aud04_rows = tuple(row for row in aud04_trial_rows if row.climate_day <= cutoff)

    exit_trial_id_counts = Counter(row.position.trial_id for row in cutoff_exit_rows)
    aud04_trial_id_counts = Counter(row.trial_id for row in cutoff_aud04_rows)
    duplicate_exit_trial_ids = {tid for tid, count in exit_trial_id_counts.items() if count > 1}
    duplicate_aud04_trial_ids = {tid for tid, count in aud04_trial_id_counts.items() if count > 1}

    exit_pnl_by_trial: dict[str, Decimal | None] = {
        row.position.trial_id: row.hold_pnl for row in cutoff_exit_rows
    }
    aud04_pnl_by_trial: dict[str, Decimal] = {row.trial_id: row.pnl for row in cutoff_aud04_rows}

    exit_only = tuple(sorted(set(exit_pnl_by_trial) - set(aud04_pnl_by_trial)))
    aud04_only = tuple(sorted(set(aud04_pnl_by_trial) - set(exit_pnl_by_trial)))
    joined_trial_ids = sorted(set(exit_pnl_by_trial) & set(aud04_pnl_by_trial))

    divergent: list[str] = []
    n_matched = 0
    for trial_id in joined_trial_ids:
        if trial_id in duplicate_exit_trial_ids or trial_id in duplicate_aud04_trial_ids:
            divergent.append(trial_id)
            continue
        exit_pnl = exit_pnl_by_trial[trial_id]
        aud04_pnl = aud04_pnl_by_trial[trial_id]
        if exit_pnl is not None and abs(exit_pnl - aud04_pnl) <= _RECONCILIATION_TOLERANCE:
            n_matched += 1
        else:
            divergent.append(trial_id)

    matched = not divergent and not exit_only and not aud04_only
    return Aud04PerTrialReconciliationResult(
        matched=matched, cutoff=cutoff, n_matched=n_matched,
        n_exit_only=len(exit_only), n_aud04_only=len(aud04_only), n_divergent=len(divergent),
        n_duplicate_exit=len(duplicate_exit_trial_ids),
        n_duplicate_aud04=len(duplicate_aud04_trial_ids),
        divergent_trial_ids=tuple(divergent[:_MAX_NAMED_DIVERGENT_TRIAL_IDS]),
        exit_only_trial_ids=exit_only, aud04_only_trial_ids=aud04_only,
    )


def apply_pnl_reconciliation_ladder_per_trial(
    *, result: Aud04PerTrialReconciliationResult, latch: alert_ladder.LatchState, now_ns: int,
) -> tuple[alert_ladder.LatchState, AlertPayload | None]:
    """Same ladder cadence, event names, and latch file as
    `apply_pnl_reconciliation_ladder` (D8's per-consumer-file ownership rule
    -- this is the per-row upgrade of the SAME control, not a second one).
    The report-level-total caveat is DROPPED here (it no longer applies once
    AUD-04 publishes `trial_rows`); the detail instead names the first
    `_MAX_NAMED_DIVERGENT_TRIAL_IDS` divergent `trial_id`s, the duplicate
    counts on each side, and a same-capped sample of the unjoined
    `trial_id`s on each side (review finding, 2026-09-25 -- previously only
    their counts were visible)."""
    previous_streak = latch.streak
    stale_detail = (
        f"streak={previous_streak + 1} n_divergent={result.n_divergent} "
        f"n_exit_only={result.n_exit_only} n_aud04_only={result.n_aud04_only} "
        f"n_duplicate_exit={result.n_duplicate_exit} "
        f"n_duplicate_aud04={result.n_duplicate_aud04} "
        f"divergent_trial_ids={list(result.divergent_trial_ids)} "
        f"exit_only_trial_ids="
        f"{list(result.exit_only_trial_ids[:_MAX_NAMED_DIVERGENT_TRIAL_IDS])} "
        f"aud04_only_trial_ids="
        f"{list(result.aud04_only_trial_ids[:_MAX_NAMED_DIVERGENT_TRIAL_IDS])}"
    )
    return _apply_ladder(
        is_fresh=result.matched, latch=latch, now_ns=now_ns,
        stale_event=EXIT_PNL_RECONCILIATION_MISMATCH_EVENT,
        cleared_event=EXIT_PNL_RECONCILIATION_MISMATCH_CLEARED_EVENT,
        stale_detail=stale_detail, cleared_detail=f"streak_len={previous_streak}",
    )


def apply_pnl_reconciliation_ladder(
    *, matched: bool, latch: alert_ladder.LatchState, now_ns: int,
) -> tuple[alert_ladder.LatchState, AlertPayload | None]:
    """Same ladder cadence as `apply_corpus_frozen_ladder`: `matched=True` is
    fresh (silent, or one `INFO` `..._CLEARED` recovering from a streak);
    `matched=False` increments the streak toward a weekly `WARN`, daily
    `CRITICAL` at `streak >= 14`. The detail text always carries the
    report-level-total caveat (domain review item 3)."""
    previous_streak = latch.streak
    return _apply_ladder(
        is_fresh=matched, latch=latch, now_ns=now_ns,
        stale_event=EXIT_PNL_RECONCILIATION_MISMATCH_EVENT,
        cleared_event=EXIT_PNL_RECONCILIATION_MISMATCH_CLEARED_EVENT,
        stale_detail=f"streak={previous_streak + 1} caveat={_AUD04_RECONCILIATION_CAVEAT}",
        cleared_detail=f"streak_len={previous_streak} caveat={_AUD04_RECONCILIATION_CAVEAT}",
    )


def apply_corpus_frozen_ladder(
    *, n_positions_new_since_previous_run: int | None,
    latch: alert_ladder.LatchState, now_ns: int,
) -> tuple[alert_ladder.LatchState, AlertPayload | None]:
    """Drives `breezy.runtime.alert_ladder`'s shared state machine over this
    control's own local predicate: fresh (no alert, streak clears) iff no
    previous run exists to compare against, or this run added at least one
    NEW position; stale (streak increments) iff a previous run exists and
    `n_positions_new_since_previous_run == 0`.

    Returns the next latch state to persist and an `AlertPayload` to emit
    through the caller's sink, or `None` when this run stays silent.
    """
    is_fresh = n_positions_new_since_previous_run is None or n_positions_new_since_previous_run > 0
    previous_streak = latch.streak
    return _apply_ladder(
        is_fresh=is_fresh, latch=latch, now_ns=now_ns,
        stale_event=EXIT_CORPUS_FROZEN_EVENT, cleared_event=EXIT_CORPUS_FROZEN_CLEARED_EVENT,
        stale_detail=f"streak={previous_streak + 1} n_positions_new_since_previous_run=0",
        cleared_detail=f"streak_len={previous_streak}",
    )


#: Bounded retry for a 429/5xx ASOS fetch (module docstring's fetch-failure
#: note) -- the exit-window study's OWN wrapper around
#: ``settlement_alignment_study.fetch_text_cached``, which itself stays
#: UNCHANGED for its other callers (``asos_recent_refresh.py``,
#: ``current_rung_hold_resting_bid_study.py``, and
#: ``settlement_alignment_study.main`` itself all still get exactly one
#: attempt -- see ``_fetch_text_with_retry``'s own docstring). Exponential
#: backoff is used when the origin sends no usable ``Retry-After``; at most
#: ``_MAX_FETCH_RETRIES`` retries per station, and every wait -- backoff or
#: ``Retry-After`` -- is capped at ``_MAX_RETRY_WAIT_S``.
#:
#: Per-station worst case (``_MAX_FETCH_RETRIES`` retries, each capped at
#: ``_MAX_RETRY_WAIT_S``) is 360s; across the whole four-station family that
#: is 1440s -- uncomfortably close to the unit's own ``TimeoutStartSec``.
#: ``_TOTAL_RETRY_WAIT_BUDGET_S`` (see ``_RetryWaitBudget``) is the hard
#: backstop for that: a single ceiling on the SUM of every wait across
#: every station in one run, never per-station alone.
_RETRY_BACKOFFS_S: Final[tuple[float, ...]] = (5.0, 15.0, 45.0)
_MAX_RETRY_WAIT_S: Final[float] = 120.0
_MAX_FETCH_RETRIES: Final[int] = 3
_TOTAL_RETRY_WAIT_BUDGET_S: Final[float] = 600.0
#: Shared between `_asos_fetch_failure` (below) and `main`'s own
#: partial-run WARN filter -- one literal, not two independently
#: maintained ones.
_ASOS_FETCH_FAILURE_MARKER: Final[str] = "ASOS fetch failed for"
#: A detector without delivery is not a control (AUD-15's own lesson):
#: fired once per run when any station is still missing after
#: `_fetch_text_with_retry` exhausts its retries. Never fired on a TOTAL
#: outage -- that path already exits 1 and trips the unit's own
#: `OnFailure=` alert (`main`'s own guard).
EXIT_WINDOW_ASOS_FETCH_PARTIAL_OUTAGE_EVENT: Final[str] = (
    "EXIT_WINDOW_ASOS_FETCH_PARTIAL_OUTAGE"
)


def _retry_wait_seconds(exc: httpx.HTTPStatusError, attempt: int) -> float:
    """Seconds to wait before retrying `exc`'s station (`attempt` is
    0-indexed: 0 is the wait before the FIRST retry). Honours `Retry-After`
    in its seconds form only -- an HTTP-date `Retry-After`, or one that
    fails to parse as a float, falls back to `_RETRY_BACKOFFS_S`, exactly
    like a station that sent no header at all. Always capped at
    `_MAX_RETRY_WAIT_S`.
    """
    seconds = _RETRY_BACKOFFS_S[attempt]
    retry_after = exc.response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            parsed = float(retry_after)
        except ValueError:
            pass
        else:
            if parsed >= 0:
                seconds = parsed
    return min(seconds, _MAX_RETRY_WAIT_S)


@dataclasses.dataclass(slots=True)
class _RetryWaitBudget:
    """A per-RUN ceiling on the TOTAL retry wait summed across EVERY
    station -- shared (one instance) across the whole `run_exit_window_study`
    loop, never per-station. Once exhausted, `_fetch_text_with_retry` stops
    retrying immediately: the failing station becomes an ordinary missing
    input, exactly like exhausting its own `_MAX_FETCH_RETRIES`, and later
    stations get no further retries either once the shared budget is gone.
    """

    remaining_s: float

    def consume(self, seconds: float) -> bool:
        """`True` (and decrements `remaining_s`) iff the FULL `seconds` fits
        in what remains; `False` (unchanged) otherwise. Never a partial
        wait -- the sum of every wait this budget ever approves can never
        exceed the value it was constructed with.
        """
        if seconds > self.remaining_s:
            return False
        self.remaining_s -= seconds
        return True


def _fetch_text_with_retry(
    client: HistoricalDataClient, cache_dir: Path, url: str, delay_s: float,
    *, sleep: Callable[[float], None], budget: _RetryWaitBudget,
) -> str:
    """Bounded retry around `fetch_text_cached`, for THIS study's own
    per-station fetch path only -- `fetch_text_cached` itself is never
    modified, so every other caller keeps its original single-attempt
    behaviour. Retries ONLY HTTP 429 and 5xx, at most `_MAX_FETCH_RETRIES`
    times (`_MAX_FETCH_RETRIES + 1` attempts total) AND only while `budget`
    (shared across every station in this run) can still cover the next
    wait; any other `httpx.HTTPStatusError` (e.g. 404) or a
    `httpx.TransportError` (a connection failure, never a rate limit) is
    raised on the very first attempt, exactly like this study's own
    pre-retry behaviour.
    """
    for attempt in range(_MAX_FETCH_RETRIES + 1):
        try:
            return fetch_text_cached(client, cache_dir, url, delay_s)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status == 429 or 500 <= status < 600
            if not retryable or attempt == _MAX_FETCH_RETRIES:
                raise
            wait_s = _retry_wait_seconds(exc, attempt)
            if not budget.consume(wait_s):
                raise
            sleep(wait_s)
    raise AssertionError("unreachable: the loop above always returns or raises")


def _station_asos_text(
    *, cache_dir: Path, spec: SiteSpec, obs_source: Literal["cache", "fetch"],
    client: HistoricalDataClient | None, sleep: Callable[[float], None] = time.sleep,
    budget: _RetryWaitBudget,
) -> str | None:
    """The FIXED-window ASOS text for ``spec``'s whole station (never a
    per-day fetch -- one fetch covers every climate day this run needs,
    matching ``current_rung_hold_monitor_hypothetical_hold
    ._load_observations_for_station``'s own cache key).

    ``obs_source="cache"``: read-only, ``None`` on a miss (the caller reports
    it, never fabricates). ``obs_source="fetch"``: fetch-on-miss via
    :func:`_fetch_text_with_retry` (a bounded-retry wrapper around
    ``settlement_alignment_study.fetch_text_cached`` -- the SAME helper
    ``asos_recent_refresh.py`` uses, calling only ``client.get(...)`` (never
    ``.post``/``.put``/``.patch``/``.delete``/``.request``, so this module
    stays clear of the write-egress firewall scan)) -- and WRITES the result
    into ``cache_dir`` so the next run is offline. ``sleep`` is a test seam
    (defaults to the real ``time.sleep``): production retries really wait;
    tests inject a no-op/recording fake so they never really sleep.
    ``budget`` is the run-wide :class:`_RetryWaitBudget`, shared across
    every station -- always passed explicitly by the caller, never
    defaulted (a fresh per-call budget would defeat the whole-run cap)."""
    url = asos_url(spec.iem_asos_id, ASOS_FETCH_START, ASOS_FETCH_END)
    path = cache_path_for_url(cache_dir, url, ".txt")
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if obs_source != "fetch" or client is None:
        return None
    return _fetch_text_with_retry(client, cache_dir, url, 1.0, sleep=sleep, budget=budget)


def _station_observations(*, spec: SiteSpec, text: str) -> tuple[ObservationRow, ...]:
    """Every parsed observation for ``spec``'s station, ANY climate day --
    the caller filters to one day via :func:`_observations_for_day`."""
    parsed, _drops = iem_asos_rows_to_station_observations(
        station=spec.iem_asos_id,
        rows=parse_asos_rows(text),
        source_channel="iem_asos_metar_exit_window_study",
        assumed_publication_lag_ns=1,
        received_at_ns=_PLACEHOLDER_RECEIVED_AT_NS,
    )
    return tuple(
        ObservationRow(
            observed_at_ns=row.observed_at_ns, temp_c_tenths=row.temp_c_tenths,
            precision_c_tenths=row.precision_c_tenths, is_metar=row.is_metar,
        )
        for row in parsed
    )


def _observations_for_day(
    observations: Sequence[ObservationRow], *, spec: SiteSpec, climate_day: dt.date,
) -> tuple[ObservationRow, ...]:
    return tuple(
        row
        for row in observations
        if climate_day_for_instant(
            dt.datetime.fromtimestamp(row.observed_at_ns / 1_000_000_000, tz=dt.UTC),
            spec.std_utc_offset_hours,
        )
        == climate_day
    )


def _read_staged_feather_frames(path: Path) -> tuple[OrderBookDepth10, ...]:
    """Every ``OrderBookDepth10`` batch in one staged feather file.

    Mirrors the scratchpad probe's ``staged_last`` reader (Arrow IPC stream,
    stop cleanly on a truncated tail batch -- ``pa.ArrowInvalid``, the
    recorder's own in-progress-write shape) but keeps EVERY non-empty batch,
    never only the last one: a single feather file holds the whole session's
    frames, not one snapshot.
    """
    batches = []
    with path.open("rb") as handle:
        reader = pa.ipc.open_stream(handle)
        schema = reader.schema
        while True:
            try:
                batch = reader.read_next_batch()
            except StopIteration:
                break
            except pa.ArrowInvalid:
                break
            if batch.num_rows:
                batches.append(batch)
    if not batches:
        return ()
    table = pa.Table.from_batches(batches, schema=schema)
    return tuple(ArrowSerializer.deserialize(OrderBookDepth10, table))


def _load_staged_depth_frames(*, live_root: Path, slug: str) -> tuple[OrderBookDepth10, ...]:
    """Every staged Depth10 frame for ``slug``, across EVERY trader-instance
    directory under ``live_root`` (never a single hardcoded/guessed instance
    id -- a redeploy rotates to a new instance directory, and a station-day's
    frames can straddle a restart; see LESSONS' "paper replay instance
    selection" -- never guess the first-listed instance). De-duplicated by
    ``ts_init`` (a real wall-clock nanosecond stamp, safe to merge across
    instances) and returned ``ts_init``-ascending."""
    frames_by_ts: dict[int, OrderBookDepth10] = {}
    for path in sorted(live_root.glob(f"*/order_book_depths/{slug}/*.feather")):
        for frame in _read_staged_feather_frames(path):
            frames_by_ts[frame.ts_init] = frame
    return tuple(sorted(frames_by_ts.values(), key=lambda frame: frame.ts_init))


def _select_depth_frames(
    *,
    depth_source: Literal["catalog", "staged"] | None,
    catalog_frames: tuple[OrderBookDepth10, ...],
    live_root: Path,
    slug: str,
    filled_at_ns: int,
) -> tuple[tuple[OrderBookDepth10, ...], Literal["catalog", "staged"]]:
    """Pick the Depth10 source for one position (module docstring's
    ``--depth-source`` note). An explicit ``depth_source`` always wins;
    otherwise "staged" only when the committed catalog's newest frame
    precedes the fill (ING-1: the parquet converter can strand a station
    well behind the still-capturing recorder) AND the staged tape actually
    covers something -- never silently discarding a working catalog read."""
    catalog_covers_fill = any(frame.ts_init > filled_at_ns for frame in catalog_frames)
    if depth_source == "catalog" or (depth_source is None and catalog_covers_fill):
        return catalog_frames, "catalog"
    staged_frames = _load_staged_depth_frames(live_root=live_root, slug=slug)
    if depth_source == "staged" or staged_frames:
        return staged_frames, "staged"
    return catalog_frames, "catalog"


def _quote_tape_bucket_by_instrument(catalog_root: Path) -> dict[str, WeatherBucketFacts]:
    """Fallback instrument-definition source: the FLAT quote-tape catalog
    the live trading node itself writes to. Measured 2026-09-16: the
    per-station settlement catalog (``_read_bucket_facts_by_instrument_id``'s
    normal source) holds zero instrument definitions in this environment --
    only the quote-tape catalog carries them. Reuses ``read_weather_bucket
    _facts`` (never re-derives the rung math) over the SAME unfiltered
    ``catalog.instruments()`` read ``_read_bucket_facts_by_instrument_id``
    itself uses, for the identical BinaryOption-identifier-filter reason
    (score_live_trials.py's own docstring, review item 7)."""
    catalog = ParquetDataCatalog(str(catalog_root))
    facts: dict[str, WeatherBucketFacts] = {}
    for instrument in catalog.instruments():
        try:
            resolved = read_weather_bucket_facts(instrument.info)
        except Exception as exc:  # noqa: BLE001 -- a non-weather instrument is skipped, not fatal
            logging.getLogger(__name__).debug(
                "skipping non-weather instrument %s: %s", instrument.id, exc,
            )
            continue
        facts.setdefault(str(instrument.id), resolved)
    return facts


def _accumulator_for(
    observations: Sequence[ObservationRow], *, std_utc_offset_hours: float,
) -> RunningExtremeAccumulator:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=std_utc_offset_hours)
    for row in observations:
        accumulator.push(
            row.observed_at_ns, row.temp_c_tenths, row.precision_c_tenths, row.is_metar,
            row.observed_at_ns,
        )
    return accumulator


def _catalog_instrument_id(instrument_id: str) -> str:
    """The Depth10 catalog key for ``instrument_id`` -- the sibling YES
    instrument for a NO-leg id (only one live order book per market;
    ``monitor_evidence`` module docstring). ``instrument_id`` is
    ``"<symbol>.<VENUE>"``; the venue suffix must survive the NO-leg strip,
    never dropped along with the ``^no`` marker."""
    symbol = symbol_of_instrument_id(instrument_id)
    if leg_of_symbol(symbol) != "no":
        return instrument_id
    venue_suffix = instrument_id[len(symbol) :]
    return base_symbol_of(symbol) + venue_suffix


def _leg_of(instrument_id: str) -> Leg:
    return "NO" if leg_of_symbol(symbol_of_instrument_id(instrument_id)) == "no" else "YES"


def _resolved_trial(
    trial: FilledTrial, bucket_by_instrument: Mapping[str, WeatherBucketFacts],
) -> FilledTrial | None:
    """``trial`` with its ``bucket`` resolved, or ``None`` when no persisted
    instrument definition exists for it (mirrors ``score_live_trials
    .score_live_trials``'s own ``instrument_unavailable`` gate)."""
    if trial.bucket is not None:
        return trial
    bucket = bucket_by_instrument.get(trial.instrument_id)
    if bucket is None:
        return None
    return dataclasses.replace(trial, bucket=bucket)


def _position_from_trial(trial: FilledTrial, *, season: str) -> FilledPosition:
    assert trial.bucket is not None
    return FilledPosition(
        trial_id=trial.trial_id,
        station=trial.station,
        climate_day=trial.climate_day,
        season=season,
        instrument_id=trial.instrument_id,
        leg=_leg_of(trial.instrument_id),
        rung=(trial.bucket.lower_f, trial.bucket.upper_f),
        fill_px=trial.fill_px,
        fee=trial.fee,
        held_qty=int(trial.qty),
        filled_at_ns=trial.filled_at_ns,
    )


def _resolve_settlement(
    *, trial: FilledTrial, position: FilledPosition, accumulator: RunningExtremeAccumulator,
    std_utc_offset_hours: float, scored_by_trial_id: Mapping[str, ScoredTrial],
) -> tuple[bool | None, bool]:
    """``(settled_held, preliminary)`` -- scored-trial row, else a
    non-superseded FINAL catalog record, else a PRELIMINARY running-max
    guess (module docstring's three-tier resolution).

    L-44 (2026-09-16): ``trial.bucket.contains(tmax_f)`` answers the YES
    leg's own win condition -- a NO leg wins iff the settled value lands
    OUTSIDE the rung, the exact complement, never ``contains(...)`` taken
    directly (rung bounds are CLOSED everywhere in this repo and at the
    venue; ``WeatherBucketFacts.contains`` uses ``<=``). ``scored.held`` (the
    first tier) is already leg-correct -- it comes from the real settlement
    scorer, which has always handled this."""
    scored = scored_by_trial_id.get(trial.trial_id)
    if scored is not None:
        return scored.held, False

    climate_day = dt.date.fromisoformat(trial.climate_day)
    tmax_f, count, _provenance = load_settled_tmax_for_day(
        catalog_base=DEFAULT_SETTLEMENT_CATALOG, city=trial.station, climate_day=climate_day,
    )
    if tmax_f is not None and count > 0:
        assert trial.bucket is not None
        yes_wins = trial.bucket.contains(tmax_f)
        return (yes_wins if position.leg == "YES" else not yes_wins), False

    facts = bucket_facts(
        lower_f=position.rung[0], upper_f=position.rung[1], station=position.station,
        climate_day=climate_day,
    )
    end_of_day = int(
        dt.datetime.combine(
            climate_day, dt.time(23, 59, 59),
            tzinfo=dt.timezone(dt.timedelta(hours=std_utc_offset_hours)),
        ).timestamp()
        * 1_000_000_000,
    )
    final_running_max = accumulator.value_at(end_of_day)
    return (
        infer_preliminary_settlement(
            facts=facts, final_running_max=final_running_max, leg=position.leg,
        ),
        True,
    )


class _TotalAsosFetchOutage(Exception):
    """Every station this run tried to fetch failed, and none loaded from cache.

    Carries the rows and missing-input list already collected so ``main`` can
    still write the report, then exit non-zero. A partial outage does not
    raise: the failed stations are ordinary ``missing`` entries.
    """

    def __init__(
        self, rows: tuple[PositionExitRow, ...], missing: tuple[str, ...],
    ) -> None:
        super().__init__("every attempted ASOS station fetch failed")
        self.rows = rows
        self.missing = missing


def _asos_fetch_failure(city: str, iem_asos_id: str, exc: httpx.HTTPError) -> str:
    """One station's fetch failure, named for the report's missing section
    (after `_fetch_text_with_retry` already exhausted its retries for a
    429/5xx, or immediately for anything else)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return (
            f"{city}: {_ASOS_FETCH_FAILURE_MARKER} {iem_asos_id} "
            f"(HTTP {exc.response.status_code})"
        )
    return (
        f"{city}: {_ASOS_FETCH_FAILURE_MARKER} {iem_asos_id} "
        f"(transport error: {type(exc).__name__})"
    )


def run_exit_window_study(
    *,
    state_db: Path,
    stations: Sequence[str],
    since_climate_day: str,
    catalog_root: Path = DEFAULT_QUOTE_TAPE_CATALOG,
    scored_trials_dir: Path = DEFAULT_DERIVED_DIR,
    asos_cache_dir: Path = DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    obs_source: Literal["cache", "fetch"] = "cache",
    depth_source: Literal["catalog", "staged"] | None = None,
    live_catalog_root: Path = _DEFAULT_LIVE_CATALOG_ROOT,
    sleep: Callable[[float], None] = time.sleep,
    retry_wait_budget_s: float = _TOTAL_RETRY_WAIT_BUDGET_S,
) -> tuple[tuple[PositionExitRow, ...], tuple[str, ...]]:
    """Build one exit-window row per filled position across ``stations``.

    Returns ``(rows, missing)`` -- ``missing`` names inputs that could not be
    resolved, reported rather than fabricated. A per-station HTTP 429/5xx is
    retried (bounded per station AND by a run-wide `retry_wait_budget_s`
    shared across every station, see `_fetch_text_with_retry`/
    `_RetryWaitBudget`) before becoming one of those missing inputs; any
    other HTTP or transport failure is missing on the first attempt. When
    every attempted fetch failed and no station loaded ASOS text, raises
    :class:`_TotalAsosFetchOutage` instead of returning (``main`` turns
    that into a non-zero exit after writing the report). ``sleep`` and
    ``retry_wait_budget_s`` are test seams (default to the real
    ``time.sleep`` and ``_TOTAL_RETRY_WAIT_BUDGET_S``).
    """
    config = CurrentRungHoldConfig(stations=tuple(stations))
    fee_coefficient = config.required_fee_coefficient
    stale_observation_bound_ns = config.stale_observation_minutes * 60_000_000_000
    registry = default_registry()
    specs_by_city = {spec.city: spec for spec in load_sites() if spec.city in stations}
    #: ONE budget, shared across every station this run -- see
    #: `_RetryWaitBudget`'s own docstring for why a fresh per-station budget
    #: would defeat the whole-run cap.
    retry_budget = _RetryWaitBudget(remaining_s=retry_wait_budget_s)
    #: L-38 (`cbd5fec`): each REGISTERED family's rows now live under their
    #: own `<scored_trials_dir>/<family_id>/` subdirectory -- pooled here
    #: across every family plus any legacy top-level rows (see
    #: `read_scored_trials_pooled`'s docstring).
    scored_by_trial_id = {
        trial.trial_id: trial for trial in read_scored_trials_pooled(scored_trials_dir).rows
    }
    #: Built once, shared across every city (module docstring's fallback note).
    quote_tape_bucket_by_instrument = _quote_tape_bucket_by_instrument(catalog_root)

    rows: list[PositionExitRow] = []
    missing: list[str] = []
    #: Stations whose ASOS text loaded (cache hit or a successful fetch) versus
    #: stations whose fetch raised. A total outage is "at least one fetch failed
    #: and nothing loaded" -- a cache hit is not a failed attempt, so one cached
    #: station plus one HTTP 429 is a partial outage and does not raise.
    loaded_stations = 0
    failed_fetches = 0
    #: `no_taken_latch`/`ambiguous_latch` exclusions carry an empty
    #: `station` by design and are emitted IDENTICALLY by every city's
    #: invocation (`read_filled_trials_state_db`'s own docstring) -- keyed
    #: by `(venue_order_id, reason)` here so each is reported exactly once,
    #: never per-city-filtered away (a fill excluded under an empty station
    #: is invisible to any `exclusion.station == city` test).
    seen_exclusions: set[tuple[str, str]] = set()

    #: httpx.Client only calls `.get(...)` (never `.post`/`.put`/`.patch`/
    #: `.delete`/`.request`) -- see `_station_asos_text`'s docstring for why
    #: that keeps this module clear of the write-egress firewall scan.
    #: Built lazily only when a fetch could actually happen.
    client_cm: httpx.Client | contextlib.AbstractContextManager[None] = (
        httpx.Client(headers={"User-Agent": USER_AGENT})
        if obs_source == "fetch"
        else contextlib.nullcontext()
    )
    with client_cm as client:
        for city in stations:
            spec = specs_by_city.get(city)
            if spec is None:
                missing.append(f"{city}: no registered site spec")
                continue
            cli_location = registry.settlement_site(_VENUE, city).cli_location
            trials, exclusions, _fee_reconciled, _no_side_residual = read_filled_trials_state_db(
                state_db, family_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, city=city,
                cli_location=cli_location, since_climate_day=since_climate_day, stations=stations,
            )
            for exclusion in exclusions:
                key = (exclusion.venue_order_id, exclusion.reason)
                if key in seen_exclusions:
                    continue
                seen_exclusions.add(key)
                label = exclusion.station or city
                missing.append(
                    f"{label}: excluded fill ({exclusion.reason}: {exclusion.detail}) -- "
                    "belongs to a different family/latch shape than this v3 "
                    f"({CONTINUOUS_TRIAL_KEY_PREFIX!r})-scoped study",
                )
            if not trials:
                missing.append(f"{city}: no filled trials since {since_climate_day}")
                continue

            #: Settlement-catalog definitions win on conflict; the flat
            #: quote-tape catalog only fills in what the (in this environment,
            #: empty) per-station settlement catalog never received.
            settlement_catalog_bucket_by_instrument = _read_bucket_facts_by_instrument_id(
                DEFAULT_SETTLEMENT_CATALOG, venue=_VENUE, city=city,
            )
            bucket_by_instrument = {
                **quote_tape_bucket_by_instrument,
                **settlement_catalog_bucket_by_instrument,
            }

            try:
                station_text = _station_asos_text(
                    cache_dir=asos_cache_dir, spec=spec, obs_source=obs_source, client=client,
                    sleep=sleep, budget=retry_budget,
                )
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                failed_fetches += 1
                missing.append(_asos_fetch_failure(city, spec.iem_asos_id, exc))
                continue
            if station_text is None:
                missing.append(
                    f"{city}: ASOS cache miss for {spec.iem_asos_id} (window "
                    f"{ASOS_FETCH_START}..{ASOS_FETCH_END}); pass --obs-source fetch "
                    "to populate it",
                )
                continue
            loaded_stations += 1
            station_observations = _station_observations(spec=spec, text=station_text)

            accumulator_by_day: dict[dt.date, RunningExtremeAccumulator] = {}
            observations_by_day: dict[dt.date, tuple[ObservationRow, ...]] = {}
            depth_by_instrument: dict[str, tuple[OrderBookDepth10, ...]] = {}

            for raw_trial in trials:
                trial = _resolved_trial(raw_trial, bucket_by_instrument)
                if trial is None:
                    missing.append(
                        f"{city}: no persisted instrument definition for "
                        f"{raw_trial.instrument_id!r}",
                    )
                    continue

                climate_day = dt.date.fromisoformat(trial.climate_day)
                season = season_for(climate_day)
                if climate_day not in observations_by_day:
                    observations_by_day[climate_day] = _observations_for_day(
                        station_observations, spec=spec, climate_day=climate_day,
                    )
                    accumulator_by_day[climate_day] = _accumulator_for(
                        observations_by_day[climate_day],
                        std_utc_offset_hours=spec.std_utc_offset_hours,
                    )

                catalog_instrument_id = _catalog_instrument_id(trial.instrument_id)
                if catalog_instrument_id not in depth_by_instrument:
                    depth_by_instrument.update(
                        _load_depth_frames(
                            catalog_root=catalog_root, instrument_ids=[catalog_instrument_id],
                        ),
                    )
                catalog_frames = depth_by_instrument.get(catalog_instrument_id, ())
                depth_frames, used_depth_source = _select_depth_frames(
                    depth_source=depth_source, catalog_frames=catalog_frames,
                    live_root=live_catalog_root, slug=catalog_instrument_id,
                    filled_at_ns=trial.filled_at_ns,
                )
                if not depth_frames:
                    missing.append(
                        f"{city} {climate_day}: no Depth10 tape for {catalog_instrument_id} "
                        "in either the catalog or the staged recorder output",
                    )
                    continue
                if not any(frame.ts_init > trial.filled_at_ns for frame in depth_frames):
                    last_frame_at = dt.datetime.fromtimestamp(
                        depth_frames[-1].ts_init / 1_000_000_000, tz=dt.UTC,
                    )
                    fill_at = dt.datetime.fromtimestamp(
                        trial.filled_at_ns / 1_000_000_000, tz=dt.UTC,
                    )
                    missing.append(
                        f"{city} {climate_day} {catalog_instrument_id}: {used_depth_source} "
                        f"Depth10 tape ends {last_frame_at.isoformat()}, BEFORE the "
                        f"{fill_at.isoformat()} fill -- last_executable_ts_ns/R-DEAD/R-THREAT/"
                        "R-BEST fillability are UNDEFINED for this position (a tape gap, "
                        "never 'no liquidity all day')",
                    )

                position = _position_from_trial(trial, season=season)
                observation_ts_ns = tuple(
                    sorted({row.observed_at_ns for row in observations_by_day[climate_day]}),
                )
                timeline = build_exit_timeline(
                    position=position,
                    accumulator=accumulator_by_day[climate_day],
                    std_utc_offset_hours=spec.std_utc_offset_hours,
                    fee_coefficient=fee_coefficient,
                    stale_observation_bound_ns=stale_observation_bound_ns,
                    depth_frames=depth_frames,
                    observation_ts_ns=observation_ts_ns,
                )
                settled_held, preliminary = _resolve_settlement(
                    trial=trial, position=position, accumulator=accumulator_by_day[climate_day],
                    std_utc_offset_hours=spec.std_utc_offset_hours,
                    scored_by_trial_id=scored_by_trial_id,
                )
                rows.append(
                    build_position_exit_row(
                        timeline=timeline, settled_held=settled_held,
                        settlement_preliminary=preliminary, depth_source=used_depth_source,
                    ),
                )

    result = (tuple(rows), tuple(missing))
    if failed_fetches > 0 and loaded_stations == 0:
        raise _TotalAsosFetchOutage(result[0], result[1])
    return result


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-db", required=True, type=Path)
    parser.add_argument("--stations", nargs="+", required=True)
    parser.add_argument("--since-climate-day", required=True, type=str)
    parser.add_argument("--catalog-root", type=Path, default=DEFAULT_QUOTE_TAPE_CATALOG)
    parser.add_argument("--scored-trials-dir", type=Path, default=DEFAULT_DERIVED_DIR)
    parser.add_argument(
        "--asos-cache-dir", type=Path, default=DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    )
    parser.add_argument(
        "--obs-source", choices=("cache", "fetch"), default="cache",
        help="'fetch' allows a network fetch ONLY on a cache miss, writing the "
        "result into --asos-cache-dir so the next run is offline (default: cache-only).",
    )
    parser.add_argument(
        "--depth-source", choices=("catalog", "staged"), default=None,
        help="Force one Depth10 source; omit to auto-select 'staged' only when the "
        "committed catalog's newest frame precedes a position's fill (ING-1).",
    )
    parser.add_argument("--live-catalog-root", type=Path, default=_DEFAULT_LIVE_CATALOG_ROOT)
    parser.add_argument("--run-stamp", required=True, type=str)
    parser.add_argument("--out-root", type=Path, default=_DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--aud04-report", type=Path, default=None,
        help=(
            "AUD-07 standing reconciliation: optional path to AUD-04's "
            "PRIVATE_portfolio_roi_<stamp>.json for the SAME period. Read "
            "through AUD-04's own schema_version reader, never re-parsed "
            "Markdown. Omitted on any date AUD-04's artefact does not yet "
            "exist -- the reconciliation is then skipped, never faked."
        ),
    )
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    sink: AlertSink | None = None,
    now_ns: int | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """`sink`/`now_ns`/`sleep` are keyword-only test seams (never CLI flags,
    mirroring `score_live_trials.main`'s own `proc_root` convention):
    production resolves all three from the real environment/clock/
    `time.sleep`.
    """
    args = _parse_args(argv)
    out_dir: Path = args.out_root / args.run_stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved_sink = resolve_alert_sink(os.environ) if sink is None else sink
    resolved_now_ns = time.time_ns() if now_ns is None else now_ns
    resolved_sleep = time.sleep if sleep is None else sleep

    total_fetch_outage = False
    try:
        rows, missing = run_exit_window_study(
            state_db=args.state_db, stations=tuple(args.stations),
            since_climate_day=args.since_climate_day, catalog_root=args.catalog_root,
            scored_trials_dir=args.scored_trials_dir, asos_cache_dir=args.asos_cache_dir,
            obs_source=args.obs_source, depth_source=args.depth_source,
            live_catalog_root=args.live_catalog_root, sleep=resolved_sleep,
        )
    except _TotalAsosFetchOutage as exc:
        rows, missing = exc.rows, exc.missing
        total_fetch_outage = True

    # AUD-07 D: read the PREVIOUS run's trial-id set (persisted under
    # out_root, never per-run-stamp) before building this run's summary, so
    # "N grew" vs "N is frozen" is derived from an actual prior observation.
    previous_trial_ids_path = args.out_root / _PREVIOUS_TRIAL_IDS_FILENAME
    previous_trial_ids = _read_previous_trial_ids(previous_trial_ids_path)
    summary = build_summary(rows, previous_trial_ids=previous_trial_ids)
    _write_previous_trial_ids(
        previous_trial_ids_path, frozenset(row.position.trial_id for row in rows)
    )

    markdown = render_markdown(rows, summary)
    if missing:
        markdown += "\nMISSING INPUTS (reported, not fabricated):\n" + "\n".join(
            f"- {item}" for item in missing
        ) + "\n"

    (out_dir / "exit_window_study.json").write_text(
        json.dumps(
            {
                "rows": [row.to_dict() for row in rows],
                "summary": summary.to_dict(),
                "missing_inputs": list(missing),
            },
            indent=2, sort_keys=True,
        ),
        encoding="utf-8",
    )
    (out_dir / "exit_window_study.md").write_text(markdown, encoding="utf-8")
    print(f"[exit-window-study] {len(rows)} position(s); wrote {out_dir}", file=sys.stderr)
    for item in missing:
        print(f"[exit-window-study] MISSING: {item}", file=sys.stderr)

    # Partial-run WARN: a detector without delivery is not a control
    # (AUD-15's own lesson). Fired exactly once per run (never once per
    # missing station), naming every station+status still missing after
    # `_fetch_text_with_retry` exhausted its retries. Never fired on a
    # TOTAL outage -- that path already exits 1 below and trips the unit's
    # own `OnFailure=` alert; this WARN would be a duplicate signal for the
    # identical condition.
    asos_partial_failures = tuple(item for item in missing if _ASOS_FETCH_FAILURE_MARKER in item)
    if asos_partial_failures and not total_fetch_outage:
        emit_alert(
            resolved_sink,
            AlertPayload(
                severity="WARN",
                event=EXIT_WINDOW_ASOS_FETCH_PARTIAL_OUTAGE_EVENT,
                site="current_rung_hold_exit_window_study",
                detail="; ".join(asos_partial_failures),
            ),
        )

    # AUD-07 D: EXIT_CORPUS_FROZEN, on AUD-04's shared re-alert ladder.
    frozen_streak_latch_path = args.out_root / _FROZEN_STREAK_LATCH_FILENAME
    frozen_streak_latch = alert_ladder.read_latch_state(frozen_streak_latch_path)
    new_frozen_streak_latch, alert_payload = apply_corpus_frozen_ladder(
        n_positions_new_since_previous_run=summary.n_positions_new_since_previous_run,
        latch=frozen_streak_latch, now_ns=resolved_now_ns,
    )
    alert_ladder.write_latch_state(frozen_streak_latch_path, new_frozen_streak_latch)
    if alert_payload is not None:
        emit_alert(resolved_sink, alert_payload)

    # AUD-07 standing reconciliation with AUD-04 (§6, "on any date both
    # artefacts exist"). Skipped entirely -- never faked as matched, and
    # never compared across mismatched periods -- when AUD-04's artefact for
    # this date was not supplied, is unreadable/malformed, or is stale.
    if args.aud04_report is not None:
        try:
            aud04_view = read_portfolio_roi_report(args.aud04_report)
        except (
            OSError,
            json.JSONDecodeError,
            UnknownPortfolioRoiSchemaError,
            PortfolioRoiReportMalformedFieldError,
        ) as exc:
            print(
                f"[exit-window-study] AUD-04 reconciliation SKIPPED: could not read "
                f"{args.aud04_report}: {type(exc).__name__}",
                file=sys.stderr,
            )
        else:
            run_date = _utc_date_from_ns(resolved_now_ns)
            cutoff, skip_reason = aud04_reconciliation_readiness(
                settled_through=aud04_view.settled_through, run_date=run_date,
            )
            if skip_reason is not None:
                print(
                    f"[exit-window-study] AUD-04 reconciliation SKIPPED: {skip_reason}",
                    file=sys.stderr,
                )
            else:
                assert cutoff is not None
                reconciliation_latch_path = args.out_root / _PNL_RECONCILIATION_LATCH_FILENAME
                reconciliation_latch = alert_ladder.read_latch_state(reconciliation_latch_path)
                if aud04_view.trial_rows is not None:
                    # AUD-04 schema_version>=2: a per-trial_id breakdown
                    # exists, so join on it instead of comparing bare totals
                    # (§6 "standing P&L reconciliation with AUD-04", the
                    # per-row upgrade -- catches an equal-and-opposite
                    # per-trial error pair a total alone would miss).
                    per_trial_result = reconcile_with_aud04_per_trial(
                        rows=rows, cutoff=cutoff, aud04_trial_rows=aud04_view.trial_rows,
                    )
                    cap = _MAX_NAMED_DIVERGENT_TRIAL_IDS
                    print(
                        f"[exit-window-study] AUD-04 per-trial reconciliation: "
                        f"matched={per_trial_result.matched} cutoff={cutoff} "
                        f"n_divergent={per_trial_result.n_divergent} "
                        f"n_exit_only={per_trial_result.n_exit_only} "
                        f"n_aud04_only={per_trial_result.n_aud04_only} "
                        f"n_duplicate_exit={per_trial_result.n_duplicate_exit} "
                        f"n_duplicate_aud04={per_trial_result.n_duplicate_aud04} "
                        f"divergent_trial_ids={list(per_trial_result.divergent_trial_ids)} "
                        f"exit_only_trial_ids="
                        f"{list(per_trial_result.exit_only_trial_ids[:cap])} "
                        f"aud04_only_trial_ids="
                        f"{list(per_trial_result.aud04_only_trial_ids[:cap])}",
                        file=sys.stderr,
                    )
                    new_reconciliation_latch, reconciliation_payload = (
                        apply_pnl_reconciliation_ladder_per_trial(
                            result=per_trial_result, latch=reconciliation_latch,
                            now_ns=resolved_now_ns,
                        )
                    )
                else:
                    # AUD-04 schema_version=1: no per-trial breakdown exists
                    # yet -- fall back to the report-level total, caveat
                    # intact (Aud04ReconciliationResult's docstring).
                    reconciliation = reconcile_with_aud04(
                        rows=rows, cutoff=cutoff,
                        aud04_realised_pnl_after_fees_total=aud04_view.realised_pnl_after_fees_total,
                    )
                    print(
                        f"[exit-window-study] AUD-04 reconciliation: "
                        f"matched={reconciliation.matched} "
                        f"cutoff={cutoff} divergence={reconciliation.divergence} "
                        f"caveat={_AUD04_RECONCILIATION_CAVEAT}",
                        file=sys.stderr,
                    )
                    new_reconciliation_latch, reconciliation_payload = (
                        apply_pnl_reconciliation_ladder(
                            matched=reconciliation.matched, latch=reconciliation_latch,
                            now_ns=resolved_now_ns,
                        )
                    )
                alert_ladder.write_latch_state(reconciliation_latch_path, new_reconciliation_latch)
                if reconciliation_payload is not None:
                    emit_alert(resolved_sink, reconciliation_payload)

    if total_fetch_outage:
        print(
            "[exit-window-study] every attempted ASOS fetch failed; no station loaded",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
