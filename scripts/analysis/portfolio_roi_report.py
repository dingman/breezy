"""Portfolio-level ROI report (AUD-04).

**Stage C1a scope only.** This module currently provides:

- the four verified loaders (ledger fills, scored trials, residual trial
  ids, admissible scored trials) named in
  ``docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md``
  section 7 step 2;
- fill bucketing (scored / residual / unreconciled) and per-leg,
  fee-inclusive, never-netted realised P&L and capital-deployed helpers
  (section 6 D3/D4's ledger-only pieces);
- the balance-series line parser, anchored on the literal ``AccountState(``
  token, fail-closed to ``None`` (UNKNOWN) on any non-match (section 7
  step 2's balance-line parser).

**Stage C1b adds:** the cash-identity reconciliation and its
settlement-date-proxy / proxy-lag classification (D4 R2/R3), the
settled-through cutoff and its minimum-sample statistic selection (D4
R4/R5/R6), the pure core of the D9 permanently-unsettled left-anti-join
detector (flagging and `days_past_horizon` only), and ROI vs the two
registered baselines (D5).

**Stage C2 adds (this stage):** the versioned JSON schema and its sanctioned
reader (D7), including the `roi_status`/`UnsettledCapitalRoiError` gating;
the PRIVATE Markdown report and its header assembly; the D6 no-currency
journal line; the D8 frozen-input detector and the D9
permanently-unsettled-position alert, both driven by the shared
``breezy.runtime.alert_ladder`` state machine; the fill -> `trial_id` join
via ``score_live_trials.read_filled_trials_state_db`` (one call per
(REGISTERED ``polymarket_us`` family manifest, station) pair, the same loop
``score-live-trials-run.sh`` already drives); and the CLI ``main``.

**Stage C3 adds (this addition):** the per-trial P&L breakdown
(``trial_rows``, one :class:`PortfolioRoiTrialRow` per settled trial --
``trial_id``, ``family_id``, ``climate_day``, ``side``, ``pnl`` and
``settlement_basis``) an AUD-07-style consumer can join on ``trial_id`` to
catch an equal-and-opposite per-trial error a report-level total alone
cannot reveal. This is the field that bumps ``PORTFOLIO_ROI_SCHEMA_VERSION``
to 2 (every prior C2 addition stayed additive-within-version-1; this one
does not, precisely so the reader can tell "no rows because this report
predates the field" (``schema_version=1`` -> ``trial_rows is None``) apart
from "no rows because zero trials settled this run" (``schema_version=2``
-> ``trial_rows == ()``) -- a distinction a bare additive key can't carry
for a *list*-shaped field the way a dimensionless count's ``0`` default
safely can). The reader still accepts ``schema_version=1`` unmodified.

``family_id`` is resolved per trial from every REGISTERED ``polymarket_us``
family manifest's declared ``trial_id_prefix`` and
``d0_climate_day..terminal_climate_day`` window, via
``position_monitor_nightly_report.resolve_trial_family`` (reused for parity
rather than re-implemented -- see :func:`_family_id_of_trial`). An earlier
revision attributed by scored-trial-store subdirectory instead
(dict-overwrite in alphabetical order), which silently mislabelled a
shared-``trial_id_prefix`` collision (e.g. a superseding family reusing its
predecessor's namespace) in favour of whichever family sorted last -- the
window-based resolution this module now shares with AUD-07 fixes that.

**Known gap, deliberately deferred, not a contradiction with the plan text
naming only four loaders:** the plan's four named loaders do not, on their
own, give a `DurableFillRecord` (keyed by `venue_order_id`) a `trial_id` --
`ScoredTrial` and `residual_fills.ExcludedFill.trial_id` both key by
`trial_id`, but only `ExcludedFill` also carries `venue_order_id`; a
*scored* (non-residual) ledger fill's `venue_order_id` -> `trial_id` join
requires the same `TrialDayRecord` join
`scripts/analysis/score_live_trials.read_filled_trials_state_db` already
performs, which is I/O-heavy domain logic out of this stage's four named
loaders. This module therefore takes that join as an input
(:class:`AttributedFill`) rather than resolving it -- keeping the bucketing
and arithmetic below pure and independently testable -- and leaves
constructing that mapping to the (also out-of-scope-this-stage) CLI
``main``, which can reuse ``read_filled_trials_state_db`` unmodified.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Final, Literal

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError
from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.adapters.polymarket_us.fees import taker_fee_at_fill
from breezy.adapters.polymarket_us.operator_controls import _round_cost_up_to_cent
from breezy.domain.instrument_leg import leg_of_symbol, symbol_of_instrument_id
from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.weather_bucket_facts import WeatherBucketFacts
from breezy.persistence.catalog import (
    CatalogPathError,
    open_station_catalog,
    read_climate_day_including_corrections,
)
from breezy.persistence.external_capital_flows import (
    STATUS_NOT_CONFIGURED,
    ExternalFlowEvidence,
    WindowFlows,
    load_evidence,
    window_flows,
)
from breezy.persistence.family_manifest import (
    FamilyManifest,
    FamilyManifestError,
    load_family_manifest,
)
from breezy.persistence.realized_draws import admissible_scored_trials
from breezy.persistence.residual_fills import ExcludedFill, read_excluded_fills, residual_trial_ids
from breezy.persistence.scored_trial_store import read_scored_trials, read_scored_trials_pooled
from breezy.registry.sites import SiteNotFoundError, default_registry
from breezy.runtime import alert_ladder
from breezy.runtime.health import (
    AlertPayload,
    AlertSink,
    emit_alert,
    log_alert_egress_status,
    resolve_alert_sink,
)
from breezy.settlement.trial_scorer import (
    FilledTrial,
    ScoredTrial,
    ScoreRefusal,
    SettlementBasis,
    score_trial,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from position_monitor_nightly_report import (
    _AMBIGUOUS_FAMILY_LABEL,
    resolve_trial_family,
)
from score_live_trials import (
    DEFAULT_NWS_CATALOG_BASE,
    FillSourceUnreadableError,
    StorePositiveControlFailedError,
    _bucket_facts_from_instrument_id,
    _read_bucket_facts_by_instrument_id,
    _with_scheduled_release_at_ns,
    read_filled_trials_state_db,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BALANCE_UNKNOWN_LABEL",
    "BASELINE_B0_CASH",
    "FEE_RECONCILED_LABEL",
    "FEE_UNRECONCILED_LABEL",
    "FROZEN_INPUTS_CLEARED_EVENT",
    "FROZEN_INPUTS_EVENT",
    "MIN_LAG_SAMPLE_N",
    "ORDER_SIDE_BUY",
    "ORDER_SIDE_SELL",
    "PERMANENTLY_UNSETTLED_EVENT",
    "PORTFOLIO_ROI_SCHEMA_VERSION",
    "PROCEEDS_DATE_PROXY_LABEL",
    "ROI_STATUS_GATED_UNSETTLED_CAPITAL",
    "ROI_STATUS_OK",
    "SETTLEMENT_HORIZON_GRACE_DAYS",
    "STALE_INPUT_THRESHOLD_DAYS",
    "STRUCTURAL_FALLBACK_LAG_DAYS",
    "UNEXPLAINED_CAPITAL_FLOW_LABEL",
    "UNEXPLAINED_OK_LABEL",
    "UNEXPLAINED_PROXY_LAG_LABEL",
    "UNKNOWN_TRIAL_FAMILY_LABEL",
    "UNRECONCILED_EXIT_LABEL",
    "AttributedFill",
    "BalancePoint",
    "CumulativeReconciliation",
    "DailyUnexplained",
    "DailyUnexplainedSummaryRow",
    "DuplicateScoredTrialEconomicsMismatchError",
    "FamilyManifestAttribution",
    "FamilyStationResult",
    "FillBucket",
    "FreshnessAlertDecision",
    "LedgerPartitionViolationError",
    "LedgerReadResult",
    "PermanentlyUnsettledTrial",
    "PortfolioRoiReportData",
    "PortfolioRoiReportMalformedFieldError",
    "PortfolioRoiReportView",
    "PortfolioRoiTrialRow",
    "ResidualPending",
    "ResidualSettlement",
    "RoiAgainstBaselines",
    "UnknownOrderSideError",
    "UnknownPortfolioRoiSchemaError",
    "UnsettledCapitalRoiError",
    "admissible_scored_trials",
    "apply_freshness_ladder",
    "apply_settled_through",
    "apply_unsettled_positions_ladder",
    "assert_ledger_partition",
    "attribute_fills_via_family_manifests",
    "baseline_b1_fee_drag",
    "bucket_for_fill",
    "bucket_ledger_fills",
    "build_attribution_from_results",
    "capital_deployed_by_day",
    "capital_deployed_for_fill",
    "compute_settled_through",
    "count_exit_fills",
    "cumulative_reconciliation",
    "daily_balance_series",
    "days_since_newest_input",
    "enumerate_family_station_pairs",
    "exit_label_for_fill",
    "fee_reconciliation_label",
    "fill_side_label",
    "is_input_fresh",
    "journal_line",
    "leg_of_fill",
    "leg_of_scored_trial",
    "main",
    "max_settlement_horizon_ns",
    "parse_account_state_line",
    "per_day_tolerance",
    "permanently_unsettled_trials",
    "power_caveat",
    "proceeds_by_day",
    "proceeds_date",
    "read_ledger_fills",
    "read_ledger_fills_with_counts",
    "read_portfolio_roi_report",
    "read_scored_trials",
    "read_scored_trials_pooled",
    "reconcile_daily",
    "render_markdown_report",
    "residual_settlement",
    "residual_trial_ids",
    "residual_trial_ids_pooled",
    "roi",
    "roi_against_baselines",
    "settled_through_statistic_label",
    "settlement_lag_days",
    "settlement_payout",
    "total_capital_deployed",
    "total_realised_pnl_admissible",
    "total_realised_pnl_all_settled",
    "total_realised_pnl_residual",
    "trial_rows_of",
    "write_portfolio_roi_json",
]

# --------------------------------------------------------------------------
# I1 -- ledger fill loader
# --------------------------------------------------------------------------


def _open_ledger_readonly(path: Path) -> sqlite3.Connection | None:
    """Open ``path`` read-only, or return ``None``.

    Deliberately mirrors ``scripts/analysis/fill_time_count.py``'s own
    ``_open_readonly`` (:84-98) byte-for-byte in policy -- the same
    read-only ``mode=ro`` URI idiom, so this reader can never contend with
    the live process's own writer. Not imported from that module because it
    is that module's own private helper; this is the SAME policy restated,
    not a second one invented.
    """
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        conn.execute("SELECT 1 FROM state LIMIT 1")
        return conn
    except sqlite3.Error:
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class LedgerReadResult:
    """F4: the raw fill-prefixed row count and the undecodable-row count,
    alongside the decoded fills -- so the partition
    ``n_scored + n_residual + n_unreconciled == n_fills`` (§8 AC #2) can be
    checked against something other than a count DERIVED from the very
    buckets it is meant to validate, and so a row that fails to decode is
    counted rather than silently dropped."""

    fills: tuple[DurableFillRecord, ...]
    n_ledger_rows: int
    n_undecodable_ledger_rows: int


def read_ledger_fills_with_counts(source_path: Path) -> LedgerReadResult | None:
    """Every durable fill record under ``FILL_KEY_PREFIX`` in the exec-state
    store at ``source_path``, plus the raw and undecodable row counts.

    Fail-closed: returns ``None`` -- never an empty result -- when
    ``source_path`` is absent or unreadable as this schema, mirroring
    ``fill_time_count.count_filled_takes`` (:119-121). A row that fails to
    decode as a ``DurableFillRecord`` is COUNTED (``n_undecodable_ledger_rows``),
    never silently skipped with no trace (F4 defect: the pre-fix
    :func:`read_ledger_fills` swallowed such a row via a bare ``continue``).
    """
    conn = _open_ledger_readonly(source_path)
    if conn is None:
        return None
    try:
        rows = conn.execute("SELECT key, value FROM state").fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()

    fills: list[DurableFillRecord] = []
    n_ledger_rows = 0
    n_undecodable = 0
    for key, value in rows:
        if not isinstance(key, str) or not key.startswith(FILL_KEY_PREFIX):
            continue
        n_ledger_rows += 1
        try:
            fills.append(DurableFillRecord.from_bytes(value))
        except ExecutionReportMappingError:
            n_undecodable += 1
            continue
    return LedgerReadResult(
        fills=tuple(fills), n_ledger_rows=n_ledger_rows, n_undecodable_ledger_rows=n_undecodable
    )


def read_ledger_fills(source_path: Path) -> tuple[DurableFillRecord, ...] | None:
    """Every durable fill record under ``FILL_KEY_PREFIX`` in the exec-state
    store at ``source_path``.

    Fail-closed: returns ``None`` -- never an empty tuple -- when
    ``source_path`` is absent or unreadable as this schema, mirroring
    ``fill_time_count.count_filled_takes`` (:119-121). A row that fails to
    decode as a ``DurableFillRecord`` is skipped (as
    ``count_filled_takes`` already does), never treated as absence of the
    whole store. Thin wrapper over :func:`read_ledger_fills_with_counts`,
    kept for every existing caller of this exact signature.
    """
    result = read_ledger_fills_with_counts(source_path)
    if result is None:
        return None
    return result.fills


class LedgerPartitionViolationError(Exception):
    """F4/§8 AC #2: the partition ``n_scored + n_residual + n_unreconciled ==
    n_fills`` (or the raw == decoded + undecodable ledger-row count) does not
    hold. Raised, never bypassed -- ``_run`` treats this as fail-loud: a
    non-zero exit and no report written for that run."""


def assert_ledger_partition(
    *,
    ledger_result: LedgerReadResult,
    buckets: Mapping[FillBucket, tuple[AttributedFill, ...]],
) -> None:
    """Assert both halves of §8 AC #2's partition, non-bypassably (F4):
    every DECODED fill lands in exactly one bucket, and every RAW
    fill-prefixed row is either decoded or counted undecodable -- never a
    count silently derived from the buckets themselves."""
    n_bucketed = sum(len(rows) for rows in buckets.values())
    if n_bucketed != len(ledger_result.fills):
        raise LedgerPartitionViolationError(
            f"bucketed={n_bucketed} != decoded_fills={len(ledger_result.fills)}"
        )
    expected_raw = len(ledger_result.fills) + ledger_result.n_undecodable_ledger_rows
    if ledger_result.n_ledger_rows != expected_raw:
        raise LedgerPartitionViolationError(
            f"raw_ledger_rows={ledger_result.n_ledger_rows} != "
            f"decoded={len(ledger_result.fills)} + "
            f"undecodable={ledger_result.n_undecodable_ledger_rows}"
        )


# --------------------------------------------------------------------------
# Leg-aware, never-netted capital deployed (D3/D4)
# --------------------------------------------------------------------------


def leg_of_fill(fill: DurableFillRecord) -> Literal["yes", "no"]:
    """``"no"`` for a fill on a composite ``^no`` instrument id, else
    ``"yes"`` -- the same rule ``realized_draws.stratum_row_from_scored_trial``
    applies, restated here over a ledger fill instead of a ``ScoredTrial``."""
    return leg_of_symbol(symbol_of_instrument_id(fill.instrument_id))


def leg_of_scored_trial(trial: ScoredTrial) -> Literal["yes", "no"]:
    """The mirror of :func:`leg_of_fill`, over a ``ScoredTrial`` instead of a
    ``DurableFillRecord`` -- same rule (a composite ``^no`` instrument id is
    the NO leg), restated over the settlement-side record so the per-trial
    P&L breakdown (:func:`trial_rows_of`) never has to reach for a ledger
    fill just to label a trial's side."""
    return leg_of_symbol(symbol_of_instrument_id(trial.instrument_id))


#: F5: `DurableFillRecord.order_side` on this ledger is already NORMALISED
#: (its own docstring: "a SELL record NETS against the longs (an R-8/R-9
#: partial exit)") -- BUY is an open (capital deployed), SELL is an exit.
#: No other value is a recognised side.
ORDER_SIDE_BUY: Final[str] = "BUY"
ORDER_SIDE_SELL: Final[str] = "SELL"

#: F5: a SELL exit whose cash-proceeds/fee-sign semantics this reader cannot
#: independently verify from `DurableFillRecord` alone. The plan itself
#: never names this label or a SELL-handling fallback -- it only states
#: (Section 6, "Null hypothesis" verdict), quoted verbatim from
#: `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md:114`:
#: "the live family never sells (G-12)". `UNRECONCILED_EXIT` and this whole
#: SELL branch are review-driven hardening, added because an exit seam
#: (AUD-07) now exists even though the live family does not yet use it --
#: see :func:`exit_label_for_fill`'s docstring for why exclusion, rather
#: than a guess, is the conservative choice.
UNRECONCILED_EXIT_LABEL: Final[str] = "UNRECONCILED_EXIT"


class UnknownOrderSideError(Exception):
    """F5: a ledger fill's ``order_side`` is neither ``BUY`` nor ``SELL`` --
    fail loud rather than silently treating an unrecognised venue-side value
    as an open (which would silently inflate capital deployed) or as an exit
    (which would silently exclude real capital from the denominator)."""


def fill_side_label(fill: DurableFillRecord) -> str:
    """``"BUY"`` or ``"SELL"``; raises :class:`UnknownOrderSideError` on any
    other recorded ``order_side`` (F5)."""
    if fill.order_side in (ORDER_SIDE_BUY, ORDER_SIDE_SELL):
        return fill.order_side
    raise UnknownOrderSideError(
        f"ledger fill venue_order_id={fill.venue_order_id!r} has an unrecognised "
        f"order_side={fill.order_side!r}; refusing to guess whether it is an "
        "open or an exit"
    )


def exit_label_for_fill(fill: DurableFillRecord) -> str:
    """The label a SELL exit is reported under (F5). `DurableFillRecord`
    carries no field distinguishing a genuine cash-proceeds figure from a
    netting-only cost basis on its ``cumulative_cost``/``cumulative_fee``
    (`client.py`'s own docstring only says a SELL record "nets against the
    longs" for ENTRY-PRICE purposes, `_entry_price_from_records`, never that
    its cost figure is a venue cash credit) -- so this reader cannot verify
    the fee sign or the cash-proceeds semantics of an exit fill from the
    record alone.

    The plan itself never anticipates a SELL at all: it assumed the live
    family never sells (see :data:`UNRECONCILED_EXIT_LABEL`'s docstring for
    the exact plan citation) and named no fallback for one. Handling a SELL
    exit is therefore review-driven hardening, not a plan-documented
    behaviour, added because an exit seam (AUD-07) now exists in the code
    even though the live family has not yet used it. Given that gap in
    verifiable semantics, `UNRECONCILED_EXIT` is the conservative choice:
    every SELL is excluded from capital deployed and never folded into
    `proceeds` (D4's `proceeds(D)` stays scored-trial-derived only,
    unchanged by this fill) -- rather than guessed into either total -- and
    is instead counted visibly via the dimensionless `n_exit_fills`. Only
    called on a fill already known to be a SELL via :func:`fill_side_label`.
    """
    return UNRECONCILED_EXIT_LABEL


def capital_deployed_for_fill(fill: DurableFillRecord) -> Decimal:
    """One fill's cash-out: cost + fee, rounded UP to the cent via the same
    helper ``order_cost_usd`` and the ledger true-up already share
    (``operator_controls._round_cost_up_to_cent``) -- so this figure is
    quantised identically to D4's later tolerance derivation. Reads no
    operator-reserved control and assigns no value to one; it is a pure
    rounding function over already-recorded ledger amounts.

    Callers -- :func:`total_capital_deployed` and
    :func:`capital_deployed_by_day` -- filter to BUY fills only (F5); this
    function itself is side-agnostic arithmetic, kept usable on its own by
    :func:`TestLegAwareCapitalDeployed`-style direct-cost assertions.
    """
    return _round_cost_up_to_cent(fill.cumulative_cost + fill.cumulative_fee)


def total_capital_deployed(fills: Iterable[DurableFillRecord]) -> Decimal:
    """Σ of :func:`capital_deployed_for_fill` over every given BUY (open)
    fill (F5) -- never a SELL exit, whose cash this reader cannot verify
    (see :func:`exit_label_for_fill`).

    Leg-aware by construction, never netted: a YES fill and its sibling
    ``^no`` fill on the same station-day are two distinct
    ``DurableFillRecord`` rows (two distinct ``instrument_id``s), and this
    sums both -- there is no station-day accumulator here to net them
    into (§6 D4, R1 two-leg test).
    """
    return sum(
        (
            capital_deployed_for_fill(fill)
            for fill in fills
            if fill_side_label(fill) == ORDER_SIDE_BUY
        ),
        start=Decimal(0),
    )


def count_exit_fills(fills: Iterable[DurableFillRecord]) -> int:
    """F5: the dimensionless count of SELL exits, reported as
    ``n_exit_fills`` -- visibility for the capital this report deliberately
    excludes from both the denominator and ROI."""
    return sum(1 for fill in fills if fill_side_label(fill) == ORDER_SIDE_SELL)


# --------------------------------------------------------------------------
# Fee reconciliation labelling -- never silently modelled
# --------------------------------------------------------------------------

FEE_RECONCILED_LABEL: Final[str] = "fee_reconciled"
FEE_UNRECONCILED_LABEL: Final[str] = "fee_unreconciled"


def fee_reconciliation_label(fill: DurableFillRecord) -> str:
    """Name the fill's fee-reconciliation state; never silently treats an
    unreconciled fee as reconciled, and never zeroes or otherwise models a
    substitute fee value -- the recorded ``cumulative_fee`` is used as-is
    either way, the label is metadata a later stage's totals can key on."""
    return FEE_RECONCILED_LABEL if fill.fee_reconciled else FEE_UNRECONCILED_LABEL


# --------------------------------------------------------------------------
# Fill bucketing -- scored / residual / unreconciled (I3 partition)
# --------------------------------------------------------------------------


class FillBucket(str, Enum):
    """Exactly one of these three, never more than one, for every ledger
    fill (§8 AC #2's partition)."""

    SCORED = "scored"
    RESIDUAL = "residual"
    UNRECONCILED = "unreconciled"


@dataclass(frozen=True, slots=True, kw_only=True)
class AttributedFill:
    """One ledger fill, with the ``trial_id`` it has already been
    attributed to by the caller's own ``TrialDayRecord`` join (module
    docstring's "known gap"). ``trial_id is None`` means no attribution was
    ever made -- the fill is `unreconciled` regardless of what
    ``scored_trial_ids``/``residual_trial_ids`` contain."""

    fill: DurableFillRecord
    trial_id: str | None


def bucket_for_fill(
    attributed: AttributedFill,
    *,
    scored_trial_ids: frozenset[str],
    residual_trial_ids: frozenset[str],
) -> FillBucket:
    """One fill's bucket. Checked in a fixed order (scored, then residual,
    then unreconciled) -- a `trial_id` present in both sets would be a data
    contradiction, not decided by this pure function."""
    if attributed.trial_id is not None and attributed.trial_id in scored_trial_ids:
        return FillBucket.SCORED
    if attributed.trial_id is not None and attributed.trial_id in residual_trial_ids:
        return FillBucket.RESIDUAL
    return FillBucket.UNRECONCILED


def bucket_ledger_fills(
    fills: Sequence[AttributedFill],
    *,
    scored_trial_ids: frozenset[str],
    residual_trial_ids: frozenset[str],
) -> dict[FillBucket, tuple[AttributedFill, ...]]:
    """Partition every fill into exactly one bucket.

    The three buckets' combined length always equals ``len(fills)`` --
    every fill lands somewhere, never dropped and never counted twice
    (§8 AC #2).
    """
    buckets: dict[FillBucket, list[AttributedFill]] = {
        FillBucket.SCORED: [],
        FillBucket.RESIDUAL: [],
        FillBucket.UNRECONCILED: [],
    }
    for attributed in fills:
        bucket = bucket_for_fill(
            attributed,
            scored_trial_ids=scored_trial_ids,
            residual_trial_ids=residual_trial_ids,
        )
        buckets[bucket].append(attributed)
    return {bucket: tuple(rows) for bucket, rows in buckets.items()}


def residual_trial_ids_pooled(base_dir: Path) -> frozenset[str]:
    """Union of :func:`residual_trial_ids` over every per-family subdirectory
    of ``base_dir``, mirroring ``read_scored_trials_pooled``'s own per-family
    iteration (``scored_trial_store.py:186``) -- but WITHOUT that reader's
    legacy top-level union.

    Every production caller of ``residual_trial_ids``/``read_excluded_fills``
    passes a per-family ``store_dir`` -- ``family_tally_v2.py``'s own CLI
    declares ``--store-dir`` as "6c scored-trial parquet directory"
    (`family_tally_v2.py:1216`) and always resolves to one family's own
    subdirectory; ``build_family_tally_v2`` (`family_tally_v2.py:633`) never
    receives the family-agnostic parent. There is no documented pre-L-38
    top-level ``excluded_fills.jsonl`` layout to stay backward-compatible
    with (unlike ``scored_trials_*.parquet``'s legacy top-level files,
    `scored_trial_store.py:152-163`), so a parent-level ``excluded_fills.jsonl``
    is deliberately never read here.
    """
    if not base_dir.exists():
        return frozenset()
    ids: set[str] = set()
    for child in sorted(p for p in base_dir.iterdir() if p.is_dir()):
        ids |= residual_trial_ids(child)
    return frozenset(ids)


def scored_trial_ids_of(scored_trials: Iterable[ScoredTrial]) -> frozenset[str]:
    """The set of `trial_id`s carried by every given (already-loaded)
    `ScoredTrial` row -- a plain projection, kept as a named function so a
    caller never inlines ``{t.trial_id for t in ...}`` independently at each
    call site."""
    return frozenset(trial.trial_id for trial in scored_trials)


# --------------------------------------------------------------------------
# FU-3d AC4/AC5: the Markdown-only fee_unverified residual disclosure.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class FeeUnverifiedResidualDisclosure:
    """FU-3d AC4: three quantities over settled `fee_unverified` residual
    fills, deduped by `venue_order_id` -- Markdown-only, never JSON, never a
    correction to any booked P&L (§8 AC #3's residual-cash-identity rule
    extends here unchanged)."""

    n_fee_unverified_settled: int
    model_minus_recorded_fee: Decimal
    n_fee_unverified_unmodelled: int


def _fee_unverified_fills_deduped(scored_trials_dir: Path) -> dict[str, ExcludedFill]:
    """AC5: every `reason == "fee_unverified"` line under `scored_trials_dir`
    -- read from the legacy top-level `excluded_fills.jsonl` (dedupe input
    only; `residual_trial_ids_pooled` deliberately never unions this level
    for BOOKING, see its own docstring -- this function reads it anyway
    because AC5 requires it for the dedupe identity, and booking is decided
    separately, downstream, by :func:`fee_unverified_residual_disclosure`'s
    `residual_settlement_trial_ids` filter) and every per-family child
    directory -- deduped by `venue_order_id`, latest `scored_run_utc` wins
    (the `family_tally_v2.py:1130-1142` rule, restated here since this
    module does not import that script)."""
    all_fills: list[ExcludedFill] = []
    if scored_trials_dir.exists():
        all_fills.extend(read_excluded_fills(scored_trials_dir))
        for child in sorted(p for p in scored_trials_dir.iterdir() if p.is_dir()):
            all_fills.extend(read_excluded_fills(child))
    latest: dict[str, ExcludedFill] = {}
    for fill in all_fills:
        if fill.reason != "fee_unverified":
            continue
        current = latest.get(fill.venue_order_id)
        if current is None or fill.scored_run_utc >= current.scored_run_utc:
            latest[fill.venue_order_id] = fill
    return latest


def fee_unverified_residual_disclosure(
    *,
    fee_unverified_fills: Mapping[str, ExcludedFill],
    filled_trials: Sequence[FilledTrial],
    fee_reconciled_by_trial_id: Mapping[str, tuple[bool, str, bool]],
    residual_settlement_trial_ids: frozenset[str],
) -> FeeUnverifiedResidualDisclosure:
    """Pure (AC4/AC5/Edge Cases): compute (i) `n`, (ii) the signed model-
    minus-recorded fee sum over fills whose theta resolves, and (iii)
    `n_unmodelled`, from already-loaded inputs -- no I/O here.

    A fill is disclosed only if (a) its `trial_id` has a booked
    :class:`ResidualSettlement` (`residual_settlement_trial_ids`) and (b) the
    state DB does not now say `fee_reconciled=True` for it (the state DB is
    authoritative over a stale sidecar line, per the tuple's first element).
    `fee_coefficient_at_fill=None` always -- `FilledTrial` carries no theta
    field, so this uses the dated schedule at the fill's own `filled_at_ns`
    (`taker_fee_at_fill`'s own documented fallback). An out-of-range price
    (`ValueError`) is caught per fill and counted in `n_unmodelled`, never
    aborting the whole disclosure. The NO leg is never discriminated: `fee`
    is the leg's own recorded per-contract fee and `p(1-p)` is symmetric.
    """
    trial_by_id = {trial.trial_id: trial for trial in filled_trials}
    n_settled = 0
    model_minus_recorded = Decimal(0)
    n_unmodelled = 0
    for fill in fee_unverified_fills.values():
        trial_id = fill.trial_id
        if not trial_id or trial_id not in residual_settlement_trial_ids:
            continue
        fee_reconciled, _venue_order_id, _skip_ask_guard = fee_reconciled_by_trial_id.get(
            trial_id, (False, "", False),
        )
        if fee_reconciled:
            continue
        trial = trial_by_id.get(trial_id)
        if trial is None:
            continue
        n_settled += 1
        try:
            modelled = taker_fee_at_fill(
                quantity=trial.qty,
                price=trial.fill_px,
                ts_event_ns=trial.filled_at_ns,
                fee_coefficient_at_fill=None,
            )
        except ValueError:
            logger.warning(
                "portfolio_roi_report: fee_unverified disclosure: out-of-range "
                "price for trial_id=%s -- counted unmodelled, not raised",
                trial_id,
            )
            n_unmodelled += 1
            continue
        if modelled is None:
            n_unmodelled += 1
            continue
        model_minus_recorded += modelled.as_decimal() - trial.qty * trial.fee
    return FeeUnverifiedResidualDisclosure(
        n_fee_unverified_settled=n_settled,
        model_minus_recorded_fee=model_minus_recorded,
        n_fee_unverified_unmodelled=n_unmodelled,
    )


#: `trial_rows_of`'s fallback whenever `resolve_trial_family` cannot bind a
#: trial to exactly one REGISTERED family -- no prefix match at all, or a
#: prefix match whose declared `d0_climate_day..terminal_climate_day` window
#: doesn't resolve to exactly one family for this trial's `climate_day`
#: (zero or several candidates). A diagnostic label only, never a value any
#: reported P&L or the sum invariant depends on, and never a guess (review
#: finding: dict-overwrite-by-directory-order silently mislabelled a
#: shared-`trial_id_prefix` collision; window-based resolution replaces it).
UNKNOWN_TRIAL_FAMILY_LABEL: Final[str] = "UNKNOWN"


def _load_registered_family_manifests(families_dir: Path) -> tuple[FamilyManifest, ...]:
    """Every REGISTERED ``polymarket_us`` family manifest under
    ``families_dir`` -- the same REGISTERED-only rule
    ``position_monitor_nightly_report.py``'s own CLI applies
    (``load_family_manifest`` with no ``allow_draft``, so a
    DRAFT_NOT_REGISTERED manifest is skipped rather than refused: a family
    that cannot yet arm anything cannot own a settled trial's attribution
    either). Best-effort, mirroring :func:`enumerate_family_station_pairs`:
    any unreadable/invalid manifest file is skipped, never aborting the
    whole report. Absent ``families_dir`` returns ``()``.
    """
    if not families_dir.exists():
        return ()
    manifests: list[FamilyManifest] = []
    for manifest_path in sorted(families_dir.glob("*.json")):
        try:
            manifest = load_family_manifest(manifest_path)
        except FamilyManifestError:
            continue
        if manifest.venue != "polymarket_us":
            continue
        manifests.append(manifest)
    return tuple(manifests)


def _family_id_of_trial(
    trial: ScoredTrial, registered_manifests: Sequence[FamilyManifest]
) -> str:
    """``trial``'s owning REGISTERED family, resolved by
    :func:`resolve_trial_family` (``position_monitor_nightly_report.py``,
    reused for parity rather than re-implemented) over its
    ``trial_id``/``climate_day`` and each candidate's declared date window.
    Both of that function's "can't tell" outcomes -- ``None`` (no
    ``trial_id_prefix`` matches at all) and ``_AMBIGUOUS_FAMILY_LABEL``
    (a prefix matches but the window resolution is zero-or-several) --
    collapse to :data:`UNKNOWN_TRIAL_FAMILY_LABEL` here: this report's own
    label for "never a guess", distinct from AUD-07's own string constant.
    """
    resolved = resolve_trial_family(trial.trial_id, trial.climate_day, registered_manifests)
    if resolved is None or resolved == _AMBIGUOUS_FAMILY_LABEL:
        return UNKNOWN_TRIAL_FAMILY_LABEL
    return resolved


# --------------------------------------------------------------------------
# Realised P&L -- I3: portfolio P&L is never scoped by n's admissibility
# --------------------------------------------------------------------------


def total_realised_pnl_all_settled(scored_trials: Iterable[ScoredTrial]) -> Decimal:
    """Σ ``pnl`` over EVERY given settled trial, including one whose
    `trial_id` is ALSO a PREREG v3 §5 residual exclusion.

    `n` (the admissible, sequential-test-eligible count -- see
    :func:`admissible_scored_trials`) is a narrower set; the account does
    not know or care about `n`'s admissibility filter (plan §6, "I3 is the
    single most important correctness property of this item"). A residual
    fill still moved real money and must never be dropped from portfolio
    P&L just because it is excluded from `n`.
    """
    return sum((trial.pnl for trial in scored_trials), start=Decimal(0))


def total_realised_pnl_admissible(
    scored_trials: tuple[ScoredTrial, ...], *, residual_trial_ids: frozenset[str]
) -> Decimal:
    """Σ ``pnl`` over only the admissible subset (`n`'s own rows) -- the
    narrower, statistically-scoped figure, distinct from
    :func:`total_realised_pnl_all_settled`."""
    admissible = admissible_scored_trials(scored_trials, residual_trial_ids=residual_trial_ids)
    return total_realised_pnl_all_settled(admissible)


def total_realised_pnl_residual(settlements: Iterable[ResidualSettlement]) -> Decimal:
    """Σ ``realised_pnl`` over every settled residual fill (FU-3c AC1/AC2).

    Deliberately over :class:`ResidualSettlement`, never :class:`ScoredTrial`
    -- this is the numerator term AUD-04 I3 was missing (a residual fill
    moved real money and must count in portfolio P&L), kept strictly
    separate from :func:`total_realised_pnl_all_settled`/
    :func:`total_realised_pnl_admissible` so it can never reach
    `admissible_scored_trials`, `n_scored`, `trial_rows`, or the lags sample
    (AC5).
    """
    return sum((settlement.realised_pnl for settlement in settlements), start=Decimal(0))


# --------------------------------------------------------------------------
# I4 -- balance-series line parser
# --------------------------------------------------------------------------

#: Strips terminal colour escapes the node log wraps every line in, so the
#: timestamp/field regexes below never have to account for them.
_ANSI_ESCAPE_RE: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;]*m")

#: The ISO-8601 UTC instant at the start of every node log line.
_ISO_TS_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)"
)

#: Anchored on the literal ``AccountState(`` token (plan §7 step 2). Only
#: ``account_id`` and the first (and, on this venue, only) balance's
#: ``total`` figure are extracted -- the two fields needed to build a
#: :class:`BalancePoint`. No fallback pattern: a line whose shape has
#: drifted from this one is UNKNOWN, never partially parsed.
_ACCOUNT_STATE_RE: Final[re.Pattern[str]] = re.compile(
    r"AccountState\(account_id=(?P<account_id>[^,]+),.*?"
    r"balances=\[AccountBalance\(total=(?P<total_usd>-?\d+\.\d+) USD"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class BalancePoint:
    """One successfully parsed ``AccountState(`` line."""

    ts_iso: str
    account_id: str
    total_usd: Decimal


def parse_account_state_line(line: str) -> BalancePoint | None:
    """Parse one node-log line into a :class:`BalancePoint`, or ``None``.

    Fail-closed on ANY non-match: no ``AccountState(`` token, no parseable
    timestamp, an unexpected field shape, or a non-decimal balance all
    return ``None`` -- never a partial `BalancePoint`, and never a second,
    looser fallback regex.
    """
    if "AccountState(" not in line:
        return None
    cleaned = _ANSI_ESCAPE_RE.sub("", line)
    ts_match = _ISO_TS_RE.search(cleaned)
    account_match = _ACCOUNT_STATE_RE.search(cleaned)
    if ts_match is None or account_match is None:
        return None
    try:
        total_usd = Decimal(account_match.group("total_usd"))
    except InvalidOperation:
        return None
    return BalancePoint(
        ts_iso=ts_match.group("ts"),
        account_id=account_match.group("account_id"),
        total_usd=total_usd,
    )


def daily_balance_series(
    lines: Iterable[str], *, days: Sequence[str]
) -> Mapping[str, BalancePoint | None]:
    """One entry per day in ``days`` (an explicit, caller-supplied list of
    UTC calendar-day strings), so a day this run received NO parseable
    balance line -- node never booted, log rotated away -- still appears in
    the result, mapped to ``None`` (UNKNOWN), rather than being silently
    absent (which a caller could not distinguish from "never asked about").
    Never interpolates: a missing day's value is ``None``, not the previous
    or next day's balance.

    When more than one line parses for the same day, the LAST one
    encountered (in the order ``lines`` iterates) wins -- callers are
    expected to pass lines in chronological order, matching how the node
    log itself is written.
    """
    latest_by_day: dict[str, BalancePoint] = {}
    for line in lines:
        point = parse_account_state_line(line)
        if point is None:
            continue
        day = point.ts_iso[:10]
        latest_by_day[day] = point
    return {day: latest_by_day.get(day) for day in days}


#: G1: how far back `_latest_balance_before` will search the SAME log lines
#: for a genuine prior balance before the report period's earliest
#: known-balance day. Bounded, never unbounded -- a value found further
#: back than this is treated the same as none found (falls back to an
#: explicit `NO_PRIOR_BALANCE` row rather than an arbitrarily stale diff).
OPENING_BALANCE_LOOKBACK_DAYS: Final[int] = 7


def _latest_balance_before(
    lines: Iterable[str], *, before_day: str, max_lookback_days: int
) -> BalancePoint | None:
    """The most recent :class:`BalancePoint` whose day is strictly before
    ``before_day`` and within ``max_lookback_days`` of it (G1) -- lets
    ``_run`` supply a genuine prior balance for the report period's
    earliest known-balance day when the node log carries an
    ``AccountState(`` line from before the reporting period itself (e.g.
    the node was already running before the first fill). Bounded and
    best-effort: ``None`` when no such line exists in range, in which case
    the caller falls back to an explicit ``NO_PRIOR_BALANCE_LABEL`` row
    rather than fabricating one. When more than one line parses for the
    same day, the LAST one encountered wins -- mirrors
    :func:`daily_balance_series`.
    """
    earliest_allowed_day = _shift_iso_day(before_day, -max_lookback_days)
    latest_by_day: dict[str, BalancePoint] = {}
    for line in lines:
        point = parse_account_state_line(line)
        if point is None:
            continue
        day = point.ts_iso[:10]
        if earliest_allowed_day <= day < before_day:
            latest_by_day[day] = point
    if not latest_by_day:
        return None
    return latest_by_day[max(latest_by_day)]


# --------------------------------------------------------------------------
# C1b -- day-of helpers shared by the cash identity and the D9 detector
# --------------------------------------------------------------------------

_NS_PER_DAY: Final[int] = 24 * 60 * 60 * 1_000_000_000

#: Restated from ``breezy.settlement.trial_scorer._SEVEN_DAYS_NS``
#: (`trial_scorer.py:56`) rather than importing that module's private name --
#: same structural fallback window, cited per §6 D9's "read verbatim from
#: source" instruction.
_SEVEN_DAYS_NS: Final[int] = 7 * 24 * 60 * 60 * 1_000_000_000


def _utc_day_of_ns(ts_ns: int) -> str:
    """The UTC calendar-day (ISO date string) containing ``ts_ns``.

    Integer nanosecond division, never a float -- the same discipline
    ``operator_controls.utc_day_for_ns`` uses for the analogous conversion.
    """
    return datetime.fromtimestamp(ts_ns // 1_000_000_000, tz=UTC).date().isoformat()


def _utc_day_of_fill(fill: DurableFillRecord) -> str:
    """The UTC calendar day a ledger fill OPENED on -- ``capital_deployed``'s
    dating rule (§6 D4: 'capital_deployed(D) = Sum over fills whose open is
    dated D')."""
    return _utc_day_of_ns(fill.ts_event)


def _shift_iso_day(day: str, delta_days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=delta_days)).isoformat()


def _utc_midnight_ns(day: str) -> int:
    """Epoch nanoseconds of 00:00:00.000000000Z on ``day``. Integer arithmetic
    only -- ``datetime.timestamp()`` is a float and is not used here."""
    midnight = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = midnight - epoch
    return delta.days * _NS_PER_DAY + delta.seconds * 1_000_000_000


def _end_of_utc_day_ns(day: str) -> int:
    """Last nanosecond of ``day`` UTC.

    A day-keyed balance with no snapshot clock is stamped here, so an event
    anywhere on that calendar day falls in the interval that closes on that
    day. That is the pre-existing calendar-day fixture behaviour. A real
    ``AccountState`` timestamp overrides it.
    """
    return _utc_midnight_ns(_shift_iso_day(day, 1)) - 1


def balance_point_ts_ns(ts_iso: str) -> int:
    """Epoch nanoseconds of one ``BalancePoint.ts_iso`` (``...Z``)."""
    if not ts_iso.endswith("Z"):
        raise ValueError(f"balance timestamp {ts_iso!r} is not a Zulu instant")
    body = ts_iso[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        digits = "".join(ch for ch in frac if ch.isdigit())
        frac_ns = int((digits + "000000000")[:9])
    else:
        head = body
        frac_ns = 0
    day, hms = head.split("T", 1)
    hour_s, minute_s, second_s = hms.split(":")
    return (
        _utc_midnight_ns(day)
        + int(hour_s) * 3_600 * 1_000_000_000
        + int(minute_s) * 60 * 1_000_000_000
        + int(second_s) * 1_000_000_000
        + frac_ns
    )


def _snapshot_ts_ns(day: str, balance_timestamps_ns: Mapping[str, int] | None) -> int:
    if balance_timestamps_ns is not None and day in balance_timestamps_ns:
        return balance_timestamps_ns[day]
    return _end_of_utc_day_ns(day)


def _cash_between(
    *,
    buy_fills: Sequence[DurableFillRecord],
    scored_trials: Sequence[ScoredTrial],
    after_ts: int | None,
    through_ts: int,
    residual_settlements: Sequence[ResidualSettlement] = (),
) -> tuple[Decimal, Decimal, int]:
    """Capital, proceeds, and BUY-fill count for one snapshot interval.

    ``after_ts is None`` selects events at or before ``through_ts`` (the
    opening snapshot, which has no previous print). Otherwise the interval
    is ``(after_ts, through_ts]``.

    Inclusive at ``through_ts``: an event stamped exactly at the closing
    snapshot's own ts happened no later than the balance it is being
    reconciled against, so it belongs to the interval that closes there.

    FU-3b: ``residual_settlements`` contributes to ``proceeds`` exactly like
    a scored trial's :func:`settlement_payout`, dated by ``dated_at_ns``
    instead of ``scored_at_ns`` -- it never touches ``capital`` (a residual
    fill's cost is already counted via ``buy_fills``) or the BUY-fill count.
    """
    if after_ts is None:
        chosen_fills = tuple(fill for fill in buy_fills if fill.ts_event <= through_ts)
        chosen_trials = tuple(trial for trial in scored_trials if trial.scored_at_ns <= through_ts)
        chosen_residuals = tuple(
            residual for residual in residual_settlements if residual.dated_at_ns <= through_ts
        )
    else:
        chosen_fills = tuple(
            fill for fill in buy_fills if after_ts < fill.ts_event <= through_ts
        )
        chosen_trials = tuple(
            trial for trial in scored_trials if after_ts < trial.scored_at_ns <= through_ts
        )
        chosen_residuals = tuple(
            residual
            for residual in residual_settlements
            if after_ts < residual.dated_at_ns <= through_ts
        )
    capital = sum((capital_deployed_for_fill(fill) for fill in chosen_fills), start=Decimal(0))
    proceeds = sum((settlement_payout(trial) for trial in chosen_trials), start=Decimal(0)) + sum(
        (residual.payout for residual in chosen_residuals), start=Decimal(0)
    )
    return capital, proceeds, len(chosen_fills)


# --------------------------------------------------------------------------
# C1b -- the cash identity's two ledger-scoped terms (§6 D4)
# --------------------------------------------------------------------------


def capital_deployed_by_day(fills: Iterable[DurableFillRecord]) -> dict[str, Decimal]:
    """Sum of :func:`capital_deployed_for_fill` grouped by each fill's OPEN
    day (§6 D4: 'capital_deployed(D) = Sum over fills whose open is dated D,
    of cost + fee (cash OUT)'). BUY fills only (F5) -- a SELL exit never
    contributes to this term."""
    totals: dict[str, Decimal] = {}
    for fill in fills:
        if fill_side_label(fill) != ORDER_SIDE_BUY:
            continue
        day = _utc_day_of_fill(fill)
        totals[day] = totals.get(day, Decimal(0)) + capital_deployed_for_fill(fill)
    return totals


def _fills_opened_count_by_day(fills: Iterable[DurableFillRecord]) -> dict[str, int]:
    """BUY (open) fills only (F5) -- matches :func:`capital_deployed_by_day`,
    so the per-day tolerance (`n_fills_that_day x $0.01`) is derived from the
    same population as the capital-deployed term it bounds."""
    counts: dict[str, int] = {}
    for fill in fills:
        if fill_side_label(fill) != ORDER_SIDE_BUY:
            continue
        day = _utc_day_of_fill(fill)
        counts[day] = counts.get(day, 0) + 1
    return counts


def settlement_payout(trial: ScoredTrial) -> Decimal:
    """The cash settlement payout for one settled trial.

    ``score_trial`` computes ``pnl = (1 if held else 0) - fill_px - fee``
    (`trial_scorer.py:206`) for a qty-1 admitted trial, so the payout is
    recoverable as ``pnl + fill_px + fee`` regardless of the win/lose
    outcome -- §6 D4's worked example: 'realised_pnl(position) = payout -
    cost - fee, booked once, on the settlement date.'
    """
    return trial.pnl + trial.fill_px + trial.fee


#: FU-3b: the proxy-lag window granted to a residual settlement's own dated
#: day, mirroring the "lag > 1" rule :func:`_days_potentially_explained_by_
#: proxy_lag` already applies to a normally-scored trial's
#: ``settlement_lag_days``. A residual is never scored, so it has no
#: ``scored_at_ns`` to measure an observed lag from -- this is a fixed
#: structural window (the release day itself, plus one day for ordinary
#: venue processing lag) rather than an observed statistic.
_RESIDUAL_PROXY_LAG_DAYS: Final[int] = 2


@dataclass(frozen=True, slots=True, kw_only=True)
class ResidualSettlement:
    """One residual (PREREG-excluded) fill's cash settlement payout.

    FU-3b: a residual fill's cost is already counted in
    ``capital_deployed`` (it is a real ledger fill), but absent this type its
    payout was never counted anywhere -- a false ``UNEXPLAINED_CAPITAL_FLOW``
    on the day it actually paid out. This is a plain cash record: it is never
    a ``ScoredTrial``, never written to the scored-trial store, and never
    reaches ``n_scored``/``trial_rows``/the lags sample/``total_realised_
    pnl_*`` (§8 AC #3).
    """

    trial_id: str
    climate_day: str
    payout: Decimal
    dated_at_ns: int
    settlement_basis: SettlementBasis
    #: FU-3c AC1: ``qty * (1{held} - fill_px - fee)`` -- the same formula
    #: `score_trial` uses for a `ScoredTrial.pnl` (`trial_scorer.py:206`),
    #: scaled by `qty` for consistency with `payout`/`capital_deployed`
    #: (never per-contract like the scored path, which is per-fill = per-
    #: contract because both scored-store writers admit qty==1 fills only,
    #: ruling Q1 + the FU-3d guard). This field
    #: feeds ONLY `total_realised_pnl_residual`; it must never reach
    #: `admissible_scored_trials`, `n_scored`, `trial_rows`, the lags sample,
    #: or the scored-trial store (AC5).
    realised_pnl: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class ResidualPending:
    """A residual fill whose settlement truth has not landed yet.

    Its capital is already deployed with no proceeds yet -- absent this
    type, that shows up as a false ``UNEXPLAINED_CAPITAL_FLOW``. From
    ``release_day`` on, it is instead tagged ``UNEXPLAINED_PROXY_LAG`` (§8 AC
    #4), the same reclassification :func:`_days_potentially_explained_by_
    proxy_lag` already applies to a normally-scored trial's lag.
    """

    trial_id: str
    release_day: str


def residual_settlement(
    trial: FilledTrial, record: NwsClimateDay | None, *, now_ns: int
) -> ResidualSettlement | ResidualPending:
    """One residual fill's cash settlement, or the fact that it is still
    pending.

    Calls :func:`score_trial` and keeps the returned ``ScoredTrial`` --
    ``held`` and ``settlement_basis`` only -- strictly LOCAL to this
    function: it is never returned, stored, or otherwise let escape into any
    scored statistic (§8 AC #3). The payout is ``qty * 1{held}`` -- never
    :func:`settlement_payout`, which is per-CONTRACT (assumes ``qty=1``) and
    would silently under-pay a multi-contract residual.
    """
    scored_or_refusal = score_trial(trial, record, now_ns=now_ns)
    if isinstance(scored_or_refusal, ScoreRefusal):
        return ResidualPending(
            trial_id=trial.trial_id,
            release_day=_utc_day_of_ns(trial.scheduled_release_at_ns),
        )
    scored = scored_or_refusal
    held_indicator = Decimal(1) if scored.held else Decimal(0)
    payout = trial.qty * held_indicator
    # FU-3c AC1: qty * (1{held} - fill_px - fee) -- `fill_px`/`fee` are
    # per-contract (`FilledTrial`'s own contract, `trial_scorer.py:93`), so
    # the whole bracket is scaled by `qty` here, exactly like `payout` above.
    realised_pnl = trial.qty * (held_indicator - trial.fill_px - trial.fee)
    return ResidualSettlement(
        trial_id=trial.trial_id,
        climate_day=trial.climate_day,
        payout=payout,
        dated_at_ns=trial.scheduled_release_at_ns,
        settlement_basis=scored.settlement_basis,
        realised_pnl=realised_pnl,
    )


#: §6 D4 R3: "proceeds(D) is dated by the UTC calendar day of scored_at_ns,
#: and by nothing else."
PROCEEDS_DATE_PROXY_LABEL: Final[str] = "scored_at_ns_utc_day"


def proceeds_date(trial: ScoredTrial) -> str:
    """The day ``proceeds(D)`` attributes ``trial`` to (§6 D4 R3 quote
    above) -- the UTC day of ``scored_at_ns``, never ``climate_day``."""
    return _utc_day_of_ns(trial.scored_at_ns)


def settlement_lag_days(trial: ScoredTrial) -> int:
    """``scored_at_ns``'s UTC day minus ``climate_day`` (§6 D4 R3: '...the
    measured distribution of settlement_lag_days (scored_at_ns's UTC day
    minus climate_day)')."""
    scored_day = date.fromisoformat(proceeds_date(trial))
    climate_day = date.fromisoformat(trial.climate_day)
    return (scored_day - climate_day).days


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
        if _scored_trial_economic_fingerprint(
            trial
        ) != _scored_trial_economic_fingerprint(current):
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


def proceeds_by_day(scored_trials: Iterable[ScoredTrial]) -> dict[str, Decimal]:
    """Sum of :func:`settlement_payout` grouped by :func:`proceeds_date`.

    Deduped by ``trial_id`` first (:func:`dedupe_scored_trials`), so one
    trial stored under two families contributes its payout once. Dating is
    still the UTC day of the kept row's ``scored_at_ns`` (§6 D4 R3).
    """
    kept, _n_duplicate = dedupe_scored_trials(tuple(scored_trials))
    totals: dict[str, Decimal] = {}
    for trial in kept:
        day = proceeds_date(trial)
        totals[day] = totals.get(day, Decimal(0)) + settlement_payout(trial)
    return totals


def _days_potentially_explained_by_proxy_lag(
    scored_trials: Iterable[ScoredTrial],
) -> dict[str, int]:
    """Every day a proxy-lagged trial could plausibly explain a breach on --
    both its ``climate_day`` (the credit-day proxy) and its
    :func:`proceeds_date` -- mapped to the largest lag applicable that day.

    Quotes §6 D4 R3: 'a same-day cash-out/cash-in mismatch caused by the
    proxy shows up as a nonzero unexplained(D) on the credit day and an
    equal-and-opposite unexplained(D') on the scoring day' and 'A day whose
    entire breach is explained by rows with settlement_lag_days > 1 or
    settlement_basis == "venue_last_fair_price_fallback" is reported as
    UNEXPLAINED_PROXY_LAG.'
    """
    explained: dict[str, int] = {}
    for trial in scored_trials:
        lag = settlement_lag_days(trial)
        is_proxy_lag = lag > 1 or trial.settlement_basis == "venue_last_fair_price_fallback"
        if not is_proxy_lag:
            continue
        for day in (trial.climate_day, proceeds_date(trial)):
            explained[day] = max(explained.get(day, 0), lag)
    return explained


# --------------------------------------------------------------------------
# C1b -- the per-day tolerance (§6 D4). The balance-delta term itself is now
# computed windowed, over known-balance-to-known-balance intervals, by
# `_balance_windows` (F3, below `reconcile_daily`) rather than a flat
# day-over-day `balance_deltas` helper -- a hole in the series must never be
# coerced into a known-zero delta on the day right after it.
# --------------------------------------------------------------------------


def per_day_tolerance(fills_opened_that_day: int) -> Decimal:
    """§6 D4: 'The tolerance is not an asserted constant: it is
    TOLERANCE_day = n_fills_that_day x $0.01, because the only rounding this
    pipeline performs is the venue-cent ROUND_UP quantisation ... so the
    maximum accumulated round-up error on a day is exactly one cent per
    fill.'
    """
    return Decimal("0.01") * fills_opened_that_day


# --------------------------------------------------------------------------
# C1b -- the per-day reconciliation row and the cash identity itself
# --------------------------------------------------------------------------

UNEXPLAINED_OK_LABEL: Final[str] = "OK"
UNEXPLAINED_CAPITAL_FLOW_LABEL: Final[str] = "UNEXPLAINED_CAPITAL_FLOW"
UNEXPLAINED_PROXY_LAG_LABEL: Final[str] = "UNEXPLAINED_PROXY_LAG"
PROVISIONAL_IN_FLIGHT_LABEL: Final[str] = "PROVISIONAL_IN_FLIGHT"
#: F3: a day whose own balance is unknown (a "hole") -- its delta cannot be
#: computed, so it is never coerced into a known zero. Excluded from every
#: cumulative sum, never breaches, counted only in the dimensionless
#: `n_balance_unknown_days`.
BALANCE_UNKNOWN_LABEL: Final[str] = "BALANCE_UNKNOWN"

#: G1: the earliest known-balance day in the whole series has no PRIOR
#: balance to diff against -- its delta is genuinely UNKNOWN, exactly like a
#: hole day, but it is NOT a hole (its own balance IS known) so
#: :data:`BALANCE_UNKNOWN_LABEL` would be the wrong label. Excluded from
#: every cumulative sum, never breaches, counted only in the dimensionless
#: `n_no_prior_balance_days` (mirrors `n_balance_unknown_days`).
NO_PRIOR_BALANCE_LABEL: Final[str] = "NO_PRIOR_BALANCE"

#: FU-13b AC6: the net-of-external-flow classification labels. Distinct from
#: the raw labels above -- a row's raw `classification` never changes; these
#: are assigned separately to `net_classification` by :func:`_classify_net`.
EXPLAINED_EXTERNAL_FLOW_LABEL: Final[str] = "EXPLAINED_EXTERNAL_FLOW"
EXTERNAL_FLOW_MISMATCH_LABEL: Final[str] = "EXTERNAL_FLOW_MISMATCH"
EXTERNAL_FLOW_UNVERIFIABLE_LABEL: Final[str] = "EXTERNAL_FLOW_UNVERIFIABLE"


@dataclass(frozen=True, slots=True, kw_only=True)
class DailyUnexplained:
    """One reconciliation row (§6 D4):
    ``unexplained(D) = Delta_balance(D) - proceeds(D) + capital_deployed(D)``.

    ``provisional`` is ``False`` until :func:`apply_settled_through` (or
    :func:`cumulative_reconciliation`) marks a day past ``SETTLED_THROUGH``
    -- the per-day tolerance, breach detection and classification are
    unchanged on both sides of that cutoff (§8 AC #12: 'this criterion
    narrows nothing').

    **F3 -- balance holes are never coerced to a known zero.** ``day`` is
    always the row's own resolving calendar day (never a range string, so
    every existing string/date comparison over ``.day`` -- e.g.
    :func:`apply_settled_through` -- is unaffected). Two shapes:

    - A day whose OWN balance is unknown (a hole): ``classification ==
      BALANCE_UNKNOWN_LABEL``, ``delta_balance is None``,
      ``unexplained is None``, never breaches, excluded from every
      cumulative sum.
    - A day that RESOLVES a balance delta spanning one or more hole days
      (``window_start_day != day``, ``spans_hole is True``): the row is
      never silently attributed to just that one day. ``capital_deployed``
      and ``proceeds`` are the events in
      ``(previous AccountState ts, this AccountState ts]`` -- the previous
      print is the known balance on the day before ``window_start_day`` --
      compared against the one known delta that spans the hole, and named
      via ``spans_hole``/``window_start_day``. With no snapshot clock each
      print is the last nanosecond of its UTC day, so the interval is that
      calendar span.
    """

    day: str
    window_start_day: str
    spans_hole: bool
    capital_deployed: Decimal
    proceeds: Decimal
    delta_balance: Decimal | None
    unexplained: Decimal | None
    tolerance: Decimal
    breaches_tolerance: bool
    settlement_lag_days: int | None
    proceeds_date_proxy: str | None
    classification: str
    provisional: bool = False
    #: FU-13b: net-of-external-flow fields, additive-only over the raw
    #: identity above (AC3: the raw fields are never touched by these).
    #: All three default to `None`/`False` -- BALANCE_UNKNOWN/NO_PRIOR_BALANCE
    #: rows and any row with no external-flow evidence keep these defaults
    #: (AC6 "pass through unchanged").
    external_flow_window_covered: bool = False
    external_flow_cents: int | None = None
    unexplained_net: Decimal | None = None
    net_classification: str | None = None


def _days_between_inclusive(start_day: str, end_day: str) -> tuple[str, ...]:
    """Every ISO calendar-day string from ``start_day`` to ``end_day``
    inclusive."""
    start = date.fromisoformat(start_day)
    end = date.fromisoformat(end_day)
    span = (end - start).days
    return tuple((start + timedelta(days=i)).isoformat() for i in range(span + 1))


@dataclass(frozen=True, slots=True, kw_only=True)
class _BalanceWindow:
    """One known-balance-to-known-balance interval (F3). ``spans_hole`` is
    ``True`` exactly when ``window_start_day != end_day`` -- i.e. at least
    one calendar day between the previous known balance and this one has no
    known balance of its own."""

    window_start_day: str
    end_day: str
    delta: Decimal
    spans_hole: bool


def _balance_windows(daily_balances: Mapping[str, Decimal | None]) -> tuple[_BalanceWindow, ...]:
    known_days = sorted(day for day, balance in daily_balances.items() if balance is not None)
    windows: list[_BalanceWindow] = []
    previous_day: str | None = None
    previous_balance: Decimal | None = None
    for day in known_days:
        balance = daily_balances[day]
        assert balance is not None  # narrowed by the `known_days` filter above
        if previous_day is not None:
            assert previous_balance is not None
            window_start_day = _shift_iso_day(previous_day, 1)
            windows.append(
                _BalanceWindow(
                    window_start_day=window_start_day,
                    end_day=day,
                    delta=balance - previous_balance,
                    spans_hole=window_start_day != day,
                )
            )
        previous_day = day
        previous_balance = balance
    return tuple(windows)


def _proxy_lag_capacity_for_window(
    *,
    span_days: frozenset[str],
    scored_trials: Sequence[ScoredTrial],
    residual_settlements: Sequence[ResidualSettlement],
    residual_pending: Sequence[ResidualPending],
    report_bound_day: str | None,
) -> Decimal | None:
    """FU-13: the most this window's lag-eligible events could plausibly
    have paid out -- gates :data:`UNEXPLAINED_PROXY_LAG_LABEL` against the
    window's own ``|unexplained|`` so a bare calendar-day overlap (§6 D4 R3)
    is never sufficient by itself when the overlapping event is far too
    small to explain the breach (the live 2026-09-13 case: a ~$40 breach
    sharing a day with a ~$1 residual settlement, CFJ485874TMM).

    Returns ``None`` for "unbounded" -- a still-:class:`ResidualPending`
    event overlaps, whose eventual payout this reader has no field for yet
    (it has not settled: no ``qty``/payout is carried on that type), so it
    can never be ruled OUT as the explanation. This preserves the
    pre-existing, still-tested behaviour that an unresolved pending residual
    always reclassifies its window.

    "Maximum possible payout" for a bounded event is its OWN already-settled
    cash value -- never a bound over an unknown outcome, because both
    sources here are already scored/settled:

    - a lag-eligible :class:`ScoredTrial`: ``abs(settlement_payout(trial))``.
    - a :class:`ResidualSettlement`: ``abs(settlement.payout)``.
    """
    capacity = Decimal(0)
    for trial in scored_trials:
        lag = settlement_lag_days(trial)
        is_proxy_lag = lag > 1 or trial.settlement_basis == "venue_last_fair_price_fallback"
        if not is_proxy_lag:
            continue
        if trial.climate_day in span_days or proceeds_date(trial) in span_days:
            capacity += abs(settlement_payout(trial))
    for settlement in residual_settlements:
        release_day = _utc_day_of_ns(settlement.dated_at_ns)
        if release_day in span_days or _shift_iso_day(release_day, 1) in span_days:
            capacity += abs(settlement.payout)
    for pending in residual_pending:
        end_day = pending.release_day
        if report_bound_day is not None and report_bound_day > end_day:
            end_day = report_bound_day
        if set(_days_between_inclusive(pending.release_day, end_day)) & span_days:
            return None
    return capacity


def _classify_net(
    *,
    raw_classification: str,
    unexplained: Decimal | None,
    tolerance: Decimal,
    settlement_lag_days: int | None,
    window: WindowFlows,
    capacity_provider: Callable[[], Decimal | None],
) -> tuple[str, Decimal | None, Decimal | None]:
    """FU-13b AC6: the net-of-external-flow ladder, defined for EVERY raw
    label. Returns ``(net_classification, unexplained_net,
    external_flow_amount)`` -- ``external_flow_amount`` (dollars, signed) is
    the window's own counted flow sum, or `None` when there is nothing to
    report (BALANCE_UNKNOWN/NO_PRIOR_BALANCE, an uncovered window, or a
    covered window with zero counted flows and no unverifiable record --
    AC2/AC6: never EXPLAINED by inference).
    """
    if raw_classification in (BALANCE_UNKNOWN_LABEL, NO_PRIOR_BALANCE_LABEL):
        return raw_classification, None, None
    if not window.covered:
        return raw_classification, None, None
    if window.n_counted == 0 and not window.has_unverifiable:
        return raw_classification, None, None
    if window.has_unverifiable:
        return EXTERNAL_FLOW_UNVERIFIABLE_LABEL, None, window.counted_sum
    assert unexplained is not None  # narrowed: not BALANCE_UNKNOWN/NO_PRIOR_BALANCE above
    unexplained_net = unexplained - window.counted_sum
    if abs(unexplained_net) <= tolerance:
        return EXPLAINED_EXTERNAL_FLOW_LABEL, unexplained_net, window.counted_sum
    if settlement_lag_days is not None:
        capacity = capacity_provider()
        if capacity is None or capacity >= abs(unexplained_net) - tolerance:
            return UNEXPLAINED_PROXY_LAG_LABEL, unexplained_net, window.counted_sum
    return EXTERNAL_FLOW_MISMATCH_LABEL, unexplained_net, window.counted_sum


def reconcile_daily(
    *,
    fills: Sequence[DurableFillRecord],
    scored_trials: Sequence[ScoredTrial],
    daily_balances: Mapping[str, Decimal | None],
    balance_timestamps_ns: Mapping[str, int] | None = None,
    residual_settlements: Sequence[ResidualSettlement] = (),
    residual_pending: Sequence[ResidualPending] = (),
    external_flows: ExternalFlowEvidence | None = None,
) -> tuple[DailyUnexplained, ...]:
    """The cash identity (§6 D4), one row per balance interval.

    FU-13b: ``external_flows`` (default `None`, meaning "never configured" --
    the same as passing a `NOT_CONFIGURED` evidence view) supplies AC5/AC6's
    net-of-external-flow ladder for every window row via :func:`_classify_net`
    -- never for a `BALANCE_UNKNOWN`/`NO_PRIOR_BALANCE` row, which passes
    through unchanged (AC6).

    An interval is ``(previous AccountState ts, this AccountState ts]``.
    Capital is the BUY fills whose ``ts_event`` falls in that interval;
    proceeds are the deduped scored trials whose ``scored_at_ns`` falls in
    it. The row's ``day`` is the closing snapshot's UTC day. A day-keyed
    balance with no entry in ``balance_timestamps_ns`` is stamped at the
    last nanosecond of that UTC day, which keeps a calendar-day fixture
    (event at midnight, balance already moved on that same day) on the
    day the fixture names.

    Quotes the identity verbatim: 'unexplained(D) = Delta_balance(D) -
    proceeds(D) + capital_deployed(D)'. Never nets a breach into ROI or into
    another day's figure -- each row is independent; only a caller's
    explicit cumulative sum (see :func:`cumulative_reconciliation`) combines
    them, and :class:`BALANCE_UNKNOWN_LABEL` rows never enter that sum.
    A balance jump with no fill and no settlement in the interval stays
    :data:`UNEXPLAINED_CAPITAL_FLOW_LABEL` at its full magnitude.

    FU-3b: ``residual_settlements``' payouts are folded into ``proceeds``
    (via :func:`_cash_between`) exactly like a scored trial's, and their
    ``dated_at_ns`` day (plus the following day, for ordinary venue
    processing lag) is folded into the proxy-lag day set alongside
    ``residual_pending``'s ``release_day`` through the latest day this call
    covers -- a residual with no settlement-grade record yet is never
    misclassified as an unexplained capital flow while it is still pending.
    """
    scored_trials, _n_duplicate = dedupe_scored_trials(tuple(scored_trials))
    capital_by_day = capital_deployed_by_day(fills)
    fills_opened_count = _fills_opened_count_by_day(fills)
    proceeds_totals = proceeds_by_day(scored_trials)
    proxy_lag_days = dict(_days_potentially_explained_by_proxy_lag(scored_trials))
    for settlement in residual_settlements:
        release_day = _utc_day_of_ns(settlement.dated_at_ns)
        for day in (release_day, _shift_iso_day(release_day, 1)):
            proxy_lag_days[day] = max(proxy_lag_days.get(day, 0), _RESIDUAL_PROXY_LAG_DAYS)
    # "Through today": bounded by the latest day this call's own
    # `daily_balances` covers (in a real run, the report's `period_end`) --
    # never unbounded, and never requiring a separate `now_ns` input. Also
    # feeds `_proxy_lag_capacity_for_window` below, regardless of whether
    # any `residual_pending` exists.
    report_bound_day = max(daily_balances) if daily_balances else None
    if residual_pending:
        for pending in residual_pending:
            end_day = pending.release_day
            if report_bound_day is not None and report_bound_day > end_day:
                end_day = report_bound_day
            for day in _days_between_inclusive(pending.release_day, end_day):
                proxy_lag_days[day] = max(proxy_lag_days.get(day, 0), _RESIDUAL_PROXY_LAG_DAYS)
    buy_fills = tuple(fill for fill in fills if fill_side_label(fill) == ORDER_SIDE_BUY)
    # FU-13b AC2: "never configured" reads identically to a `NOT_CONFIGURED`
    # evidence view -- `window_flows` already treats that status as uncovered.
    evidence = (
        external_flows
        if external_flows is not None
        else ExternalFlowEvidence(
            status=STATUS_NOT_CONFIGURED,
            flows=(),
            pulled_at_ns=None,
            covered_from_ns=None,
            newest_rejected_status=None,
        )
    )

    rows: list[DailyUnexplained] = []
    resolved_days: set[str] = set()

    windows = _balance_windows(daily_balances)
    for window in windows:
        span_days = _days_between_inclusive(window.window_start_day, window.end_day)
        previous_day = _shift_iso_day(window.window_start_day, -1)
        prev_ts = _snapshot_ts_ns(previous_day, balance_timestamps_ns)
        this_ts = _snapshot_ts_ns(window.end_day, balance_timestamps_ns)
        capital_deployed, proceeds, n_fills_in_span = _cash_between(
            buy_fills=buy_fills,
            scored_trials=scored_trials,
            after_ts=prev_ts,
            through_ts=this_ts,
            residual_settlements=residual_settlements,
        )
        unexplained = window.delta - proceeds + capital_deployed
        tolerance = per_day_tolerance(n_fills_in_span)
        breaches = abs(unexplained) > tolerance
        lag = max(
            (proxy_lag_days[day] for day in span_days if day in proxy_lag_days), default=None
        )
        if not breaches:
            classification = UNEXPLAINED_OK_LABEL
        elif lag is not None:
            capacity = _proxy_lag_capacity_for_window(
                span_days=frozenset(span_days),
                scored_trials=scored_trials,
                residual_settlements=residual_settlements,
                residual_pending=residual_pending,
                report_bound_day=report_bound_day,
            )
            # `None` = unbounded (an unresolved `ResidualPending` overlaps).
            # Otherwise the overlap must plausibly be ABLE to explain the
            # breach, not just share a calendar day with it (FU-13).
            if capacity is None or capacity >= abs(unexplained) - tolerance:
                classification = UNEXPLAINED_PROXY_LAG_LABEL
            else:
                classification = UNEXPLAINED_CAPITAL_FLOW_LABEL
        else:
            classification = UNEXPLAINED_CAPITAL_FLOW_LABEL
        proceeds_date_proxy = PROCEEDS_DATE_PROXY_LABEL if proceeds != Decimal(0) else None
        window_evidence_flows = window_flows(evidence, prev_ts, this_ts)

        def _capacity_provider(
            span_days: tuple[str, ...] = span_days,
        ) -> Decimal | None:
            return _proxy_lag_capacity_for_window(
                span_days=frozenset(span_days),
                scored_trials=scored_trials,
                residual_settlements=residual_settlements,
                residual_pending=residual_pending,
                report_bound_day=report_bound_day,
            )

        net_classification, unexplained_net, external_flow_amount = _classify_net(
            raw_classification=classification,
            unexplained=unexplained,
            tolerance=tolerance,
            settlement_lag_days=lag,
            window=window_evidence_flows,
            capacity_provider=_capacity_provider,
        )
        external_flow_cents = (
            None
            if external_flow_amount is None
            else int((external_flow_amount * 100).to_integral_value())
        )
        rows.append(
            DailyUnexplained(
                day=window.end_day,
                window_start_day=window.window_start_day,
                spans_hole=window.spans_hole,
                capital_deployed=capital_deployed,
                proceeds=proceeds,
                delta_balance=window.delta,
                unexplained=unexplained,
                tolerance=tolerance,
                breaches_tolerance=breaches,
                settlement_lag_days=lag,
                proceeds_date_proxy=proceeds_date_proxy,
                classification=classification,
                external_flow_window_covered=window_evidence_flows.covered,
                external_flow_cents=external_flow_cents,
                unexplained_net=unexplained_net,
                net_classification=net_classification,
            )
        )
        resolved_days.update(span_days)

    # G1: the earliest known-balance day in the series is never the END of
    # any window above (a window needs a PREVIOUS known day to diff
    # against) and its own balance IS known, so it is never picked up by
    # the BALANCE_UNKNOWN sweep below either -- without this row it is
    # silently dropped: its capital/proceeds are computed but land in no
    # row at all. Emitted with a distinct label, the capital/proceeds at
    # or before that opening snapshot for transparency, and
    # `unexplained=None` so it is
    # excluded from every cumulative sum exactly like a `BALANCE_UNKNOWN`
    # row (see `cumulative_reconciliation`'s `row.unexplained is not None`
    # filter).
    known_days = sorted(day for day, balance in daily_balances.items() if balance is not None)
    if known_days:
        earliest_known_day = known_days[0]
        resolved_end_days = {window.end_day for window in windows}
        if earliest_known_day not in resolved_end_days:
            first_ts = _snapshot_ts_ns(earliest_known_day, balance_timestamps_ns)
            capital_deployed, proceeds, n_opening_fills = _cash_between(
                buy_fills=buy_fills,
                scored_trials=scored_trials,
                after_ts=None,
                through_ts=first_ts,
                residual_settlements=residual_settlements,
            )
            rows.append(
                DailyUnexplained(
                    day=earliest_known_day,
                    window_start_day=earliest_known_day,
                    spans_hole=False,
                    capital_deployed=capital_deployed,
                    proceeds=proceeds,
                    delta_balance=None,
                    unexplained=None,
                    tolerance=per_day_tolerance(n_opening_fills),
                    breaches_tolerance=False,
                    settlement_lag_days=proxy_lag_days.get(earliest_known_day),
                    proceeds_date_proxy=(
                        PROCEEDS_DATE_PROXY_LABEL if proceeds != Decimal(0) else None
                    ),
                    classification=NO_PRIOR_BALANCE_LABEL,
                    net_classification=NO_PRIOR_BALANCE_LABEL,
                )
            )

    # F3: every day whose OWN balance is unknown -- whether or not it also
    # falls inside a resolving window above -- is separately named
    # BALANCE_UNKNOWN for visibility. Its capital/proceeds figures are shown
    # for transparency but this row never enters a cumulative sum (its
    # `unexplained` is `None`), so nothing is double-counted against the
    # window row that already reconciled the span.
    unknown_days = sorted(
        (set(capital_by_day) | set(proceeds_totals) | set(daily_balances))
        - {day for day, balance in daily_balances.items() if balance is not None}
    )
    for day in unknown_days:
        capital_deployed = capital_by_day.get(day, Decimal(0))
        proceeds = proceeds_totals.get(day, Decimal(0))
        rows.append(
            DailyUnexplained(
                day=day,
                window_start_day=day,
                spans_hole=False,
                capital_deployed=capital_deployed,
                proceeds=proceeds,
                delta_balance=None,
                unexplained=None,
                tolerance=per_day_tolerance(fills_opened_count.get(day, 0)),
                breaches_tolerance=False,
                settlement_lag_days=proxy_lag_days.get(day),
                proceeds_date_proxy=(
                    PROCEEDS_DATE_PROXY_LABEL if proceeds != Decimal(0) else None
                ),
                classification=BALANCE_UNKNOWN_LABEL,
                net_classification=BALANCE_UNKNOWN_LABEL,
            )
        )

    return tuple(sorted(rows, key=lambda row: row.day))


# --------------------------------------------------------------------------
# C1b -- the settled-through cutoff and its minimum-sample statistic (§6 D4
# R4/R5/R6)
# --------------------------------------------------------------------------

#: §6 D4 R5: "MIN_LAG_SAMPLE_N = 20. With lag_sample_n < MIN_LAG_SAMPLE_N,
#: the cutoff uses max(observed settlement_lag_days); at or above it,
#: p99(observed settlement_lag_days)."
MIN_LAG_SAMPLE_N: Final[int] = 20

#: §6 D4 R4: "the 7 floor is the structural fallback lag" -- restated from
#: `trial_scorer._SEVEN_DAYS_NS` as a whole number of days.
STRUCTURAL_FALLBACK_LAG_DAYS: Final[int] = 7


def _interpolated_percentile(sorted_values: Sequence[int], percentile: float) -> float:
    """Linear-interpolation percentile -- 'the common default, and the one
    an implementer reaches for' (§6 D4 R5), deliberately used ONLY at or
    above :data:`MIN_LAG_SAMPLE_N` by :func:`_observed_lag_statistic`."""
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (len(sorted_values) - 1) * (percentile / 100)
    lower_index = math.floor(rank)
    upper_index = math.ceil(rank)
    if lower_index == upper_index:
        return float(sorted_values[int(rank)])
    lower_weight = sorted_values[lower_index] * (upper_index - rank)
    upper_weight = sorted_values[upper_index] * (rank - lower_index)
    return lower_weight + upper_weight


def _observed_lag_statistic(lags: Sequence[int]) -> tuple[Literal["max", "p99"], int]:
    """Select and evaluate the lag statistic per §6 D4 R5's minimum-sample
    rule. An empty sample is treated as the ``max`` branch over zero
    observations -- :func:`compute_settled_through` then applies the bare
    structural floor, so this never narrows the cutoff (§6 D4 R5: 'the
    small-n branch can only WIDEN the cutoff, never narrow it')."""
    if not lags:
        return "max", 0
    sorted_lags = sorted(lags)
    if len(sorted_lags) < MIN_LAG_SAMPLE_N:
        return "max", max(sorted_lags)
    return "p99", math.ceil(_interpolated_percentile(sorted_lags, 99))


def compute_settled_through(
    *, now_day: str, lags: Sequence[int]
) -> tuple[str, Literal["max", "p99"], int]:
    """``(settled_through_day, statistic_name, lag_sample_n)`` (§6 D4 R4):
    'SETTLED_THROUGH = D_now - max(7, observed p99 settlement_lag_days)',
    with the statistic chosen by :func:`_observed_lag_statistic`."""
    statistic_name, observed_value = _observed_lag_statistic(lags)
    cutoff_days = max(STRUCTURAL_FALLBACK_LAG_DAYS, observed_value)
    settled_through_day = _shift_iso_day(now_day, -cutoff_days)
    return settled_through_day, statistic_name, len(lags)


def settled_through_statistic_label(*, statistic_name: str, lag_sample_n: int) -> str:
    """The header FRAGMENT §8 AC #12 requires; header assembly itself is a
    later stage. Quotes §6 D4 R5 verbatim:
    'settled_through_statistic=<max|p99> lag_sample_n=<n>'."""
    return f"settled_through_statistic={statistic_name} lag_sample_n={lag_sample_n}"


def apply_settled_through(
    rows: Sequence[DailyUnexplained], *, settled_through: str
) -> tuple[DailyUnexplained, ...]:
    """Mark every row whose day is AFTER ``settled_through`` as
    ``provisional`` (§6 D4 R4: labelled 'PROVISIONAL_IN_FLIGHT' and
    'excluded from the cumulative pass/fail determination'). Per-day
    tolerance, breach detection and classification are untouched."""
    return tuple(
        row if row.day <= settled_through else replace(row, provisional=True) for row in rows
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CumulativeReconciliation:
    """The settled-vs-provisional split of one reconciliation run (§6 D4
    R4/R5). ``settled_cumulative_passes`` gates only over
    ``D <= settled_through``; the provisional tail's own sum is printed
    beside it as an explicitly non-gating figure, never suppressed."""

    settled_through: str
    all_rows: tuple[DailyUnexplained, ...]
    settled_rows: tuple[DailyUnexplained, ...]
    provisional_rows: tuple[DailyUnexplained, ...]
    settled_cumulative_unexplained: Decimal
    provisional_cumulative_unexplained: Decimal
    settled_cumulative_passes: bool
    #: F3: count of `BALANCE_UNKNOWN_LABEL` rows -- excluded from both
    #: cumulative sums above, dimensionless, never a gating figure.
    n_balance_unknown_days: int
    #: G1: count of `NO_PRIOR_BALANCE_LABEL` rows -- excluded from both
    #: cumulative sums above, dimensionless, never a gating figure.
    n_no_prior_balance_days: int
    #: FU-13b: the net-of-external-flow settled/provisional sums and verdict.
    #: A row with `unexplained_net is None` (never covered by evidence)
    #: contributes its own raw `unexplained` instead -- fail-safe, never
    #: silently zeroed. BALANCE_UNKNOWN/NO_PRIOR_BALANCE rows are excluded
    #: from these sums exactly as they are from the raw ones above (both
    #: draw from the same `settled_rows`/`provisional_rows` filter).
    settled_cumulative_unexplained_net: Decimal
    provisional_cumulative_unexplained_net: Decimal
    settled_cumulative_passes_net: bool


def _unexplained_net_or_raw(row: DailyUnexplained) -> Decimal:
    """FU-13b: a row never covered by external-flow evidence contributes its
    own raw `unexplained` to the net sum -- fail-safe, never silently
    zeroed. Only called over `settled_rows`/`provisional_rows`, which are
    already filtered to `row.unexplained is not None`."""
    if row.unexplained_net is not None:
        return row.unexplained_net
    assert row.unexplained is not None
    return row.unexplained


def cumulative_reconciliation(
    *, daily_rows: Sequence[DailyUnexplained], settled_through: str
) -> CumulativeReconciliation:
    """Split ``daily_rows`` at ``settled_through`` and evaluate the
    cumulative pass/fail determination ONLY over the settled side (§8 AC
    #12: 'The cumulative Sum_D unexplained pass/fail determination applies
    ONLY to days D <= SETTLED_THROUGH').

    F3: a `BALANCE_UNKNOWN_LABEL` row's `unexplained` is `None` (its delta is
    genuinely unknown, never a known zero) and is EXCLUDED from both
    cumulative sums -- counted instead in `n_balance_unknown_days`.
    """
    all_rows = apply_settled_through(daily_rows, settled_through=settled_through)
    settled_rows = tuple(
        row for row in all_rows if not row.provisional and row.unexplained is not None
    )
    provisional_rows = tuple(
        row for row in all_rows if row.provisional and row.unexplained is not None
    )
    settled_cumulative = sum(
        (row.unexplained for row in settled_rows if row.unexplained is not None),
        start=Decimal(0),
    )
    provisional_cumulative = sum(
        (row.unexplained for row in provisional_rows if row.unexplained is not None),
        start=Decimal(0),
    )
    settled_tolerance = sum((row.tolerance for row in settled_rows), start=Decimal(0))
    settled_cumulative_net = sum(
        (_unexplained_net_or_raw(row) for row in settled_rows), start=Decimal(0)
    )
    provisional_cumulative_net = sum(
        (_unexplained_net_or_raw(row) for row in provisional_rows), start=Decimal(0)
    )
    n_balance_unknown_days = sum(
        1 for row in all_rows if row.classification == BALANCE_UNKNOWN_LABEL
    )
    n_no_prior_balance_days = sum(
        1 for row in all_rows if row.classification == NO_PRIOR_BALANCE_LABEL
    )
    return CumulativeReconciliation(
        settled_through=settled_through,
        all_rows=all_rows,
        settled_rows=settled_rows,
        provisional_rows=provisional_rows,
        settled_cumulative_unexplained=settled_cumulative,
        provisional_cumulative_unexplained=provisional_cumulative,
        settled_cumulative_passes=abs(settled_cumulative) <= settled_tolerance,
        n_balance_unknown_days=n_balance_unknown_days,
        n_no_prior_balance_days=n_no_prior_balance_days,
        settled_cumulative_unexplained_net=settled_cumulative_net,
        provisional_cumulative_unexplained_net=provisional_cumulative_net,
        settled_cumulative_passes_net=abs(settled_cumulative_net) <= settled_tolerance,
    )


# --------------------------------------------------------------------------
# C1b -- D9's pure core: the permanently-unsettled left-anti-join detector
# --------------------------------------------------------------------------

#: §6 D9: "SETTLEMENT_HORIZON_GRACE_DAYS = 3" -- the scorer's own nightly
#: cadence margin on top of the structural fallback bound.
SETTLEMENT_HORIZON_GRACE_DAYS: Final[int] = 3
_SETTLEMENT_HORIZON_GRACE_NS: Final[int] = SETTLEMENT_HORIZON_GRACE_DAYS * _NS_PER_DAY


def max_settlement_horizon_ns(scheduled_release_at_ns: int) -> int:
    """§6 D9: 'MAX_SETTLEMENT_HORIZON_NS = trial.scheduled_release_at_ns +
    _SEVEN_DAYS_NS + SETTLEMENT_HORIZON_GRACE_NS'."""
    return scheduled_release_at_ns + _SEVEN_DAYS_NS + _SETTLEMENT_HORIZON_GRACE_NS


@dataclass(frozen=True, slots=True, kw_only=True)
class PermanentlyUnsettledTrial:
    """One `FilledTrial` past its settlement horizon with no matching
    `ScoredTrial` (§6 D9's left-anti-join on `trial_id`)."""

    trial_id: str
    scheduled_release_at_ns: int
    days_past_horizon: int


def permanently_unsettled_trials(
    filled_trials: Iterable[FilledTrial],
    *,
    scored_trial_ids: frozenset[str],
    now_ns: int,
) -> tuple[PermanentlyUnsettledTrial, ...]:
    """§6 D9: 'the left-anti-join of FilledTrial on ScoredTrial by trial_id',
    flagging every row past :func:`max_settlement_horizon_ns`.

    Pure core only, this stage: the caller is responsible for the
    `roi_status`/`UnsettledCapitalRoiError` gating (D7, out of this stage's
    touch-set) and the `PORTFOLIO_ROI_POSITION_PERMANENTLY_UNSETTLED` alert
    (D8's shared `alert_ladder`, a separate concurrent stage). A trial
    inside its horizon is never flagged (§6 D9's negative half: 'the
    detector cannot be satisfied by flagging every open position').
    """
    flagged: list[PermanentlyUnsettledTrial] = []
    for trial in filled_trials:
        if trial.trial_id in scored_trial_ids:
            continue
        horizon_ns = max_settlement_horizon_ns(trial.scheduled_release_at_ns)
        if now_ns <= horizon_ns:
            continue
        days_past_horizon = (now_ns - horizon_ns) // _NS_PER_DAY
        flagged.append(
            PermanentlyUnsettledTrial(
                trial_id=trial.trial_id,
                scheduled_release_at_ns=trial.scheduled_release_at_ns,
                days_past_horizon=int(days_past_horizon),
            )
        )
    return tuple(flagged)


# --------------------------------------------------------------------------
# C1b -- ROI vs the two registered baselines (§6 D5)
# --------------------------------------------------------------------------

#: §6 D5: "B0 -- cash. 0.00 return on the same deployed capital over the
#: same period."
BASELINE_B0_CASH: Final[Decimal] = Decimal(0)


def roi(*, total_realised_pnl: Decimal, total_capital_deployed: Decimal) -> Decimal:
    """Realised P&L over capital deployed. ``0`` on zero deployed capital --
    never a division error over an empty/quiet record."""
    if total_capital_deployed == Decimal(0):
        return Decimal(0)
    return total_realised_pnl / total_capital_deployed


def baseline_b1_fee_drag(fills: Iterable[DurableFillRecord]) -> Decimal:
    """§6 D5: 'B1 -- fee-drag null. Under H0 "the quoted ask is fair",
    E[pnl_i] = -fee_i, so ROI_B1 = -Sum fee_i / Sum cost_i.'"""
    materialised = tuple(fills)
    total_fee = sum((fill.cumulative_fee for fill in materialised), start=Decimal(0))
    total_cost = sum((fill.cumulative_cost for fill in materialised), start=Decimal(0))
    if total_cost == Decimal(0):
        return Decimal(0)
    return -total_fee / total_cost


@dataclass(frozen=True, slots=True, kw_only=True)
class RoiAgainstBaselines:
    """§6 D5: 'both figures printed with equal prominence, so no reader
    depends on which one was nominated' -- B0 the headline, B1 the
    diagnostic (§12 registers the choice; not repeated here)."""

    roi: Decimal
    baseline_b0: Decimal
    baseline_b1: Decimal
    roi_minus_b0: Decimal
    roi_minus_b1: Decimal


def roi_against_baselines(
    *,
    total_realised_pnl: Decimal,
    total_capital_deployed: Decimal,
    fills: Iterable[DurableFillRecord],
) -> RoiAgainstBaselines:
    """Assemble :class:`RoiAgainstBaselines` (§6 D5); ROI vs the PREREG
    sequential verdict or any market-index figure is explicitly NOT computed
    here (§6 D5: 'Explicitly NOT a baseline')."""
    computed_roi = roi(
        total_realised_pnl=total_realised_pnl, total_capital_deployed=total_capital_deployed
    )
    baseline_b1 = baseline_b1_fee_drag(fills)
    return RoiAgainstBaselines(
        roi=computed_roi,
        baseline_b0=BASELINE_B0_CASH,
        baseline_b1=baseline_b1,
        roi_minus_b0=computed_roi - BASELINE_B0_CASH,
        roi_minus_b1=computed_roi - baseline_b1,
    )


# --------------------------------------------------------------------------
# C2 -- D7: the versioned JSON schema and its sanctioned reader
# --------------------------------------------------------------------------

#: §6 D7: '"schema_version": 1" as a top-level integer ... additive-only
#: within a major version; any removal or semantic change increments it.'
#: Stage C3 bumped this to 2 for `trial_rows` (see the module docstring's
#: "Stage C3 adds" paragraph for why THIS field bumps the version rather
#: than landing as another additive-within-1 key). FU-3c bumps it again to 3:
#: `roi`/`roi_minus_b0`/`roi_minus_b1` now fold `realised_pnl_residual_total`
#: into their numerator (Decision 2/R1) -- a semantic change to an existing
#: field, not an additive-only one, so D7 requires the bump.
PORTFOLIO_ROI_SCHEMA_VERSION: Final[int] = 3

#: The version `trial_rows` was introduced at -- every `schema_version` at
#: or above this REQUIRES the key (see `_require_trial_rows`); below it,
#: the field's total absence is simply "predates it" (`None`).
_MIN_SCHEMA_VERSION_WITH_TRIAL_ROWS: Final[int] = 2

#: Every `schema_version` this reader accepts -- `PORTFOLIO_ROI_SCHEMA_VERSION`
#: (the current, writer-stamped version) plus every prior version this
#: module still reads. Anything else raises `UnknownPortfolioRoiSchemaError`.
_KNOWN_PORTFOLIO_ROI_SCHEMA_VERSIONS: Final[frozenset[int]] = frozenset({1, 2, 3})

#: §6 D9: 'roi_status: "GATED_UNSETTLED_CAPITAL"'.
ROI_STATUS_OK: Final[str] = "OK"
ROI_STATUS_GATED_UNSETTLED_CAPITAL: Final[str] = "GATED_UNSETTLED_CAPITAL"


class UnknownPortfolioRoiSchemaError(Exception):
    """§6 D7: 'a `read_portfolio_roi_report()` helper ... raises
    `UnknownPortfolioRoiSchemaError` on any version it does not know.'"""


class UnsettledCapitalRoiError(Exception):
    """§6 D9: 'the D7 sanctioned reader `read_portfolio_roi_report()` raises
    `UnsettledCapitalRoiError` when a consumer reads `roi` / `roi_minus_b0` /
    `roi_minus_b1` while gated.'"""


class PortfolioRoiReportMalformedFieldError(Exception):
    """F9: a field in the versioned JSON has the wrong type. Mirrors
    ``alert_ladder.read_latch_state``'s strictness -- a wrong-typed field
    raises a clear, field-named error rather than a bare `KeyError`/
    `TypeError`/`decimal.InvalidOperation` surfacing from a raw dict access.
    """


def _atomic_write_bytes(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    """F7: durable, atomic write (temp file + fsync + ``os.replace``),
    mirroring the exact idiom ``alert_ladder.write_latch_state`` already
    uses. A failure mid-write leaves no partial file at ``path`` and never
    disturbs a pre-existing report there -- the temp file is removed on any
    exception, and ``path`` itself is only ever touched by the final atomic
    rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".portfolio-roi-", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        os.chmod(tmp_path, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _require_int(raw: Mapping[str, object], field: str) -> int:
    """F9: strict int extraction -- raises
    :class:`PortfolioRoiReportMalformedFieldError` naming the field on any
    non-int (bools are excluded: ``isinstance(True, int)`` is `True` in
    Python, and a boolean here is always a data error)."""
    value = raw.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise PortfolioRoiReportMalformedFieldError(
            f"portfolio ROI report field {field!r} must be an int, got "
            f"{type(value).__name__}"
        )
    return value


def _require_str(raw: Mapping[str, object], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str):
        raise PortfolioRoiReportMalformedFieldError(
            f"portfolio ROI report field {field!r} must be a str, got "
            f"{type(value).__name__}"
        )
    return value


def _require_bool(raw: Mapping[str, object], field: str) -> bool:
    value = raw.get(field)
    if not isinstance(value, bool):
        raise PortfolioRoiReportMalformedFieldError(
            f"portfolio ROI report field {field!r} must be a bool, got "
            f"{type(value).__name__}"
        )
    return value


def _optional_str(row: Mapping[str, object], field: str) -> str | None:
    """FU-13b AC4: `field` absent -> `None` (D7 additive-only); present but
    not a str raises, mirroring `_require_str`'s strictness."""
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PortfolioRoiReportMalformedFieldError(
            f"portfolio ROI report field {field!r} must be a str, got {type(value).__name__}"
        )
    return value


def _optional_int(row: Mapping[str, object], field: str) -> int | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise PortfolioRoiReportMalformedFieldError(
            f"portfolio ROI report field {field!r} must be an int, got {type(value).__name__}"
        )
    return value


def _require_daily_reconciliation_rows(
    raw: Mapping[str, object],
) -> tuple[DailyUnexplainedSummaryRow, ...]:
    """G2: strict extraction of ``daily_reconciliation`` -- absent (an old
    JSON sibling predating this field) reads as ``()``, the only tolerated
    absence (D7's additive-only rule); present-but-malformed raises
    :class:`PortfolioRoiReportMalformedFieldError`, mirroring every other
    strict field reader here rather than a bare `KeyError`/`TypeError`."""
    if "daily_reconciliation" not in raw:
        return ()
    rows = raw.get("daily_reconciliation")
    if not isinstance(rows, list):
        raise PortfolioRoiReportMalformedFieldError(
            "portfolio ROI report field 'daily_reconciliation' must be a list, got "
            f"{type(rows).__name__}"
        )
    parsed: list[DailyUnexplainedSummaryRow] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PortfolioRoiReportMalformedFieldError(
                f"portfolio ROI report field 'daily_reconciliation[{index}]' must be an "
                f"object, got {type(row).__name__}"
            )
        parsed.append(
            DailyUnexplainedSummaryRow(
                day=_require_str(row, "day"),
                classification=_require_str(row, "classification"),
                magnitude_cents=_require_int(row, "magnitude_cents"),
                provisional=_require_bool(row, "provisional"),
            )
        )
    return tuple(parsed)


@dataclass(frozen=True, slots=True, kw_only=True)
class NetReconciliationRow:
    """FU-13b: one day's net-of-external-flow verdict, keyed by `day` --
    kept as a SIBLING of `daily_reconciliation` (never widening that
    pre-existing, golden-tested row shape) so the raw D4 identity's own JSON
    representation is untouched (AC3)."""

    day: str
    net_classification: str | None
    external_flow_cents: int | None


def _require_net_reconciliation_rows(
    raw: Mapping[str, object],
) -> tuple[NetReconciliationRow, ...]:
    """FU-13b, additive/optional (AC4): absent on a report predating this
    field reads as `()`; present-but-wrong-typed raises, mirroring
    :func:`_require_daily_reconciliation_rows`."""
    if "net_reconciliation" not in raw:
        return ()
    rows = raw.get("net_reconciliation")
    if not isinstance(rows, list):
        raise PortfolioRoiReportMalformedFieldError(
            "portfolio ROI report field 'net_reconciliation' must be a list, got "
            f"{type(rows).__name__}"
        )
    parsed: list[NetReconciliationRow] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PortfolioRoiReportMalformedFieldError(
                f"portfolio ROI report field 'net_reconciliation[{index}]' must be an "
                f"object, got {type(row).__name__}"
            )
        parsed.append(
            NetReconciliationRow(
                day=_require_str(row, "day"),
                net_classification=_optional_str(row, "net_classification"),
                external_flow_cents=_optional_int(row, "external_flow_cents"),
            )
        )
    return tuple(parsed)


def _require_trial_rows(raw: Mapping[str, object]) -> tuple[PortfolioRoiTrialRow, ...]:
    """Strict extraction of ``trial_rows`` (Stage C3, schema_version=2).

    Unlike :func:`_require_daily_reconciliation_rows`, this key is
    REQUIRED here: a document already claiming ``schema_version >=
    _MIN_SCHEMA_VERSION_WITH_TRIAL_ROWS`` but missing the very field that
    version introduced is corruption, not merely old -- every real
    ``schema_version=2`` writer (:func:`write_portfolio_roi_json`) always
    emits it, so its absence at that version means the document was hand-
    edited or truncated. A genuinely old (``schema_version=1``) document
    never reaches this function at all (:func:`read_portfolio_roi_report`
    surfaces ``trial_rows=None`` for it directly, from the version check
    alone). Any caller that constructs a ``schema_version=2`` payload by
    hand (e.g. a test fixture) must include this key -- see
    ``_write_minimal_aud04_report`` in
    ``tests/unit/test_current_rung_hold_exit_window_study.py`` for the
    precedent.
    """
    if "trial_rows" not in raw:
        raise PortfolioRoiReportMalformedFieldError(
            "portfolio ROI report is missing required field 'trial_rows' at "
            f"schema_version={raw.get('schema_version')!r}"
        )
    rows = raw["trial_rows"]
    if not isinstance(rows, list):
        raise PortfolioRoiReportMalformedFieldError(
            f"portfolio ROI report field 'trial_rows' must be a list, got {type(rows).__name__}"
        )
    parsed: list[PortfolioRoiTrialRow] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PortfolioRoiReportMalformedFieldError(
                f"portfolio ROI report field 'trial_rows[{index}]' must be an object, got "
                f"{type(row).__name__}"
            )
        parsed.append(
            PortfolioRoiTrialRow(
                trial_id=_require_str(row, "trial_id"),
                family_id=_require_str(row, "family_id"),
                climate_day=_require_str(row, "climate_day"),
                side=_require_str(row, "side"),
                pnl=_require_decimal_str(row, "pnl"),
                settlement_basis=_require_str(row, "settlement_basis"),
            )
        )
    return tuple(parsed)


def _require_decimal_str(raw: Mapping[str, object], field: str) -> Decimal:
    value = raw.get(field)
    if not isinstance(value, str):
        raise PortfolioRoiReportMalformedFieldError(
            f"portfolio ROI report field {field!r} must be a decimal-shaped "
            f"str, got {type(value).__name__}"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise PortfolioRoiReportMalformedFieldError(
            f"portfolio ROI report field {field!r} is not a valid decimal "
            f"string: {value!r}"
        ) from exc


@dataclass(frozen=True, slots=True, kw_only=True)
class DailyUnexplainedSummaryRow:
    """One :class:`DailyUnexplained` row, reduced to the JSON/Markdown-safe
    shape (F1): a dollar figure never appears in this row directly -- only
    the pre-rounded ``magnitude_cents`` integer, since this row IS destined
    for the currency-carrying PRIVATE artefact (§6 D6), never the journal."""

    day: str
    classification: str
    magnitude_cents: int
    provisional: bool


def _summary_row_of(row: DailyUnexplained) -> DailyUnexplainedSummaryRow:
    magnitude_cents = (
        0 if row.unexplained is None else int((abs(row.unexplained) * 100).to_integral_value())
    )
    return DailyUnexplainedSummaryRow(
        day=row.day,
        classification=row.classification,
        magnitude_cents=magnitude_cents,
        provisional=row.provisional,
    )


def _net_reconciliation_row_of(row: DailyUnexplained) -> NetReconciliationRow:
    """FU-13b: the SIBLING per-day net verdict (see
    :class:`NetReconciliationRow`'s own docstring for why this is not folded
    into :func:`_summary_row_of`'s pre-existing, golden-tested shape)."""
    return NetReconciliationRow(
        day=row.day,
        net_classification=row.net_classification,
        external_flow_cents=row.external_flow_cents,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PortfolioRoiTrialRow:
    """One settled trial's own P&L (Stage C3, schema_version=2) -- the
    per-trial breakdown a caller (e.g. an AUD-07-style exit-side
    reconciliation) can join on ``trial_id`` to catch an equal-and-opposite
    per-trial error a report-level total alone cannot reveal."""

    trial_id: str
    family_id: str
    climate_day: str
    side: str
    pnl: Decimal
    settlement_basis: str


def trial_rows_of(
    scored_trials: Iterable[ScoredTrial],
    *,
    registered_manifests: Sequence[FamilyManifest] = (),
) -> tuple[PortfolioRoiTrialRow, ...]:
    """One :class:`PortfolioRoiTrialRow` per given ``scored_trials`` row --
    never a re-aggregation, so ``sum(row.pnl for row in
    trial_rows_of(scored_trials, ...)) ==
    total_realised_pnl_all_settled(scored_trials)`` holds by construction
    (same input, same ``.pnl`` field, no filtering, no dedup performed
    here -- callers pass the already-deduped rows). Sorted by ``trial_id``
    (unique post-``dedupe_scored_trials``) for a deterministic,
    diff-friendly JSON encoding.

    ``family_id`` is resolved by :func:`_family_id_of_trial` from
    ``registered_manifests`` -- a REGISTERED family's declared
    ``trial_id_prefix`` and ``d0_climate_day..terminal_climate_day`` window,
    never by which scored-trial-store subdirectory happened to be read last
    (that approach silently mislabelled a shared-prefix collision; see this
    function's own review history). A trial this resolution can't bind to
    exactly one family reports :data:`UNKNOWN_TRIAL_FAMILY_LABEL`, never a
    guess -- a diagnostic breakdown column only, never a value the sum
    invariant depends on.
    """
    rows = tuple(
        PortfolioRoiTrialRow(
            trial_id=trial.trial_id,
            family_id=_family_id_of_trial(trial, registered_manifests),
            climate_day=trial.climate_day,
            side=leg_of_scored_trial(trial),
            pnl=trial.pnl,
            settlement_basis=trial.settlement_basis,
        )
        for trial in scored_trials
    )
    return tuple(sorted(rows, key=lambda row: row.trial_id))


@dataclass(frozen=True, slots=True, kw_only=True)
class PortfolioRoiReportData:
    """Every field the D7 JSON sibling carries (§11's evaluation-path
    table), assembled by :func:`build_portfolio_roi_report_data`. All
    Decimal fields are serialised as strings (never float) by
    :func:`write_portfolio_roi_json`.
    """

    period_start: str
    period_end: str
    n_fills: int
    n_scored: int
    n_residual: int
    n_unreconciled: int
    power_caveat: str
    realised_pnl_after_fees_total: Decimal
    capital_deployed_total: Decimal
    roi: Decimal
    roi_minus_b0: Decimal
    roi_minus_b1: Decimal
    unexplained_flow_days: int
    settled_through: str
    settled_through_statistic: str
    lag_sample_n: int
    roi_status: str
    unsettled_capital_positions: int
    max_days_past_horizon: int
    n_family_station_refusals: int = 0
    # -- F1: the settled-window cash-identity verdict, now reaching the
    # artefact (was computed by `cumulative_reconciliation` and dropped).
    settled_cumulative_unexplained: Decimal = Decimal(0)
    provisional_cumulative_unexplained: Decimal = Decimal(0)
    settled_cumulative_passes: bool = True
    daily_reconciliation: tuple[DailyUnexplainedSummaryRow, ...] = ()
    # -- F2: `unexplained_flow_days` (kept, additive-only/D7) conflated
    # UNEXPLAINED_CAPITAL_FLOW and UNEXPLAINED_PROXY_LAG days; split here.
    n_unexplained_capital_flow_days: int = 0
    n_unexplained_proxy_lag_days: int = 0
    # -- F3: hole days, dimensionless, excluded from both cumulative sums.
    n_balance_unknown_days: int = 0
    # -- G1: opening days with no prior balance to diff against,
    # dimensionless, excluded from both cumulative sums.
    n_no_prior_balance_days: int = 0
    # -- F4: the raw/decoded/undecodable ledger-row counts the partition
    # assertion is checked against (never derived from the buckets alone).
    n_ledger_rows: int = 0
    n_undecodable_ledger_rows: int = 0
    # -- F5: SELL exits, excluded from capital_deployed/ROI (see
    # `exit_label_for_fill`), visible only as this dimensionless count.
    n_exit_fills: int = 0
    # Rows dropped before proceeds: same trial_id in more than one family
    # store. Latest scored_at_ns is kept. Dimensionless.
    n_duplicate_scored_trials: int = 0
    # -- FU-3b: residual-fill settlement payout reconciliation, counts only
    # (never an amount -- the payouts themselves stay cash-identity-only,
    # never reaching the journal per D6). `n_residual_unresolved` must be
    # visible here: an unresolved residual is a silent gap in the cash
    # identity otherwise.
    n_residual_settlements: int = 0
    n_residual_pending: int = 0
    n_residual_unresolved: int = 0
    # -- FU-3c (schema_version=3): the residual numerator term AUD-04 I3
    # required but never had. `realised_pnl_residual_total` is qty-scaled
    # (`realised_pnl_after_fees_total` is per-contract, and per-fill because
    # both scored-store writers admit qty==1 fills only, ruling Q1 + FU-3d);
    # `realised_pnl_portfolio_total` is their sum and is the
    # figure `roi`/`roi_minus_b0`/`roi_minus_b1` are actually computed
    # against (AC2). Neither ever reaches `trial_rows`/`n_scored` (AC5).
    realised_pnl_residual_total: Decimal = Decimal(0)
    realised_pnl_portfolio_total: Decimal = Decimal(0)
    # -- Stage C3: the per-trial P&L breakdown (schema_version=2). Empty by
    # default only for a caller (e.g. a test) that never supplies scored
    # trials -- `build_portfolio_roi_report_data` always populates this from
    # its own `scored_trials` argument.
    trial_rows: tuple[PortfolioRoiTrialRow, ...] = ()
    # -- FU-13b: net-of-external-flow reconciliation (v3-additive, no schema
    # bump -- see the module's D7 versioning note above). Always emitted
    # (AC2): `NOT_CONFIGURED` is the honest default for a report predating
    # this feature or run with no puller configured.
    external_flow_evidence_status: str = STATUS_NOT_CONFIGURED
    external_flow_pulled_at_ns: int | None = None
    external_flow_newest_rejected_status: str | None = None
    n_external_flow_records: int = 0
    n_windows_not_covered: int = 0
    n_explained_external_flow_days: int = 0
    n_external_flow_mismatch_days: int = 0
    n_external_flow_unverifiable_days: int = 0
    settled_cumulative_unexplained_net: Decimal = Decimal(0)
    provisional_cumulative_unexplained_net: Decimal = Decimal(0)
    settled_cumulative_passes_net: bool = True
    #: The per-day net verdict, keyed by `day` -- a SIBLING of
    #: `daily_reconciliation` (see `NetReconciliationRow`'s docstring).
    net_reconciliation: tuple[NetReconciliationRow, ...] = ()


def power_caveat(*, n_ledger_fills: int, n_scored: int, days: int) -> str:
    """F6: the header line names ledger fills and SCORED (settled) fills as
    two separate, correctly labelled numbers -- the pre-fix wording called
    ``n_scored + n_residual + n_unreconciled`` (i.e. every ledger fill,
    settled or not) "settled fills", which is false for a residual or
    unreconciled row.
    """
    return (
        f"n_ledger_fills={n_ledger_fills} n_scored_settled_fills={n_scored} over "
        f"{days} days; NOT a statistically powered estimate of improvement "
        "over B0 or B1 at this sample size."
    )


def build_portfolio_roi_report_data(
    *,
    period_start: str,
    period_end: str,
    fill_buckets: Mapping[FillBucket, tuple[AttributedFill, ...]],
    total_realised_pnl: Decimal,
    total_capital_deployed: Decimal,
    baselines: RoiAgainstBaselines,
    cumulative: CumulativeReconciliation,
    settled_through_statistic: str,
    lag_sample_n: int,
    permanently_unsettled: tuple[PermanentlyUnsettledTrial, ...],
    n_family_station_refusals: int = 0,
    n_ledger_rows: int = 0,
    n_undecodable_ledger_rows: int = 0,
    n_exit_fills: int = 0,
    n_duplicate_scored_trials: int = 0,
    n_residual_settlements: int = 0,
    n_residual_pending: int = 0,
    n_residual_unresolved: int = 0,
    realised_pnl_residual_total: Decimal = Decimal(0),
    scored_trials: Iterable[ScoredTrial] = (),
    registered_manifests: Sequence[FamilyManifest] = (),
    external_flow_evidence_status: str = STATUS_NOT_CONFIGURED,
    external_flow_pulled_at_ns: int | None = None,
    external_flow_newest_rejected_status: str | None = None,
    n_external_flow_records: int = 0,
) -> PortfolioRoiReportData:
    """Assemble the one :class:`PortfolioRoiReportData` this run produces.

    §6 D9: 'a `roi_status: "GATED_UNSETTLED_CAPITAL"` ... whenever k > 0' --
    gating is decided here, once, from ``len(permanently_unsettled)``.
    """
    n_fills = sum(len(rows) for rows in fill_buckets.values())
    n_scored = len(fill_buckets.get(FillBucket.SCORED, ()))
    unsettled_count = len(permanently_unsettled)
    max_days_past_horizon = (
        max((row.days_past_horizon for row in permanently_unsettled), default=0)
    )
    non_provisional_rows = tuple(row for row in cumulative.all_rows if not row.provisional)
    unexplained_flow_days = sum(1 for row in non_provisional_rows if row.breaches_tolerance)
    n_unexplained_capital_flow_days = sum(
        1
        for row in non_provisional_rows
        if row.classification == UNEXPLAINED_CAPITAL_FLOW_LABEL
    )
    n_unexplained_proxy_lag_days = sum(
        1 for row in non_provisional_rows if row.classification == UNEXPLAINED_PROXY_LAG_LABEL
    )
    # -- FU-13b: aggregated over the SAME `non_provisional_rows` the two
    # counts above already use; BALANCE_UNKNOWN/NO_PRIOR_BALANCE rows are
    # never "windows" for this purpose (their `external_flow_window_covered`
    # default of `False` would otherwise wrongly count them as uncovered).
    n_windows_not_covered = sum(
        1
        for row in non_provisional_rows
        if row.classification not in (BALANCE_UNKNOWN_LABEL, NO_PRIOR_BALANCE_LABEL)
        and not row.external_flow_window_covered
    )
    n_explained_external_flow_days = sum(
        1 for row in non_provisional_rows if row.net_classification == EXPLAINED_EXTERNAL_FLOW_LABEL
    )
    n_external_flow_mismatch_days = sum(
        1 for row in non_provisional_rows if row.net_classification == EXTERNAL_FLOW_MISMATCH_LABEL
    )
    n_external_flow_unverifiable_days = sum(
        1
        for row in non_provisional_rows
        if row.net_classification == EXTERNAL_FLOW_UNVERIFIABLE_LABEL
    )
    return PortfolioRoiReportData(
        period_start=period_start,
        period_end=period_end,
        n_fills=n_fills,
        n_scored=n_scored,
        n_residual=len(fill_buckets.get(FillBucket.RESIDUAL, ())),
        n_unreconciled=len(fill_buckets.get(FillBucket.UNRECONCILED, ())),
        power_caveat=power_caveat(
            n_ledger_fills=n_fills, n_scored=n_scored, days=_days_between(period_start, period_end)
        ),
        realised_pnl_after_fees_total=total_realised_pnl,
        capital_deployed_total=total_capital_deployed,
        roi=baselines.roi,
        roi_minus_b0=baselines.roi_minus_b0,
        roi_minus_b1=baselines.roi_minus_b1,
        unexplained_flow_days=unexplained_flow_days,
        settled_through=cumulative.settled_through,
        settled_through_statistic=settled_through_statistic,
        lag_sample_n=lag_sample_n,
        roi_status=(
            ROI_STATUS_GATED_UNSETTLED_CAPITAL if unsettled_count > 0 else ROI_STATUS_OK
        ),
        unsettled_capital_positions=unsettled_count,
        max_days_past_horizon=max_days_past_horizon,
        n_family_station_refusals=n_family_station_refusals,
        settled_cumulative_unexplained=cumulative.settled_cumulative_unexplained,
        provisional_cumulative_unexplained=cumulative.provisional_cumulative_unexplained,
        settled_cumulative_passes=cumulative.settled_cumulative_passes,
        daily_reconciliation=tuple(_summary_row_of(row) for row in cumulative.all_rows),
        net_reconciliation=tuple(
            _net_reconciliation_row_of(row) for row in cumulative.all_rows
        ),
        n_unexplained_capital_flow_days=n_unexplained_capital_flow_days,
        n_unexplained_proxy_lag_days=n_unexplained_proxy_lag_days,
        n_balance_unknown_days=cumulative.n_balance_unknown_days,
        n_no_prior_balance_days=cumulative.n_no_prior_balance_days,
        n_ledger_rows=n_ledger_rows,
        n_undecodable_ledger_rows=n_undecodable_ledger_rows,
        n_exit_fills=n_exit_fills,
        n_duplicate_scored_trials=n_duplicate_scored_trials,
        n_residual_settlements=n_residual_settlements,
        n_residual_pending=n_residual_pending,
        n_residual_unresolved=n_residual_unresolved,
        realised_pnl_residual_total=realised_pnl_residual_total,
        realised_pnl_portfolio_total=total_realised_pnl + realised_pnl_residual_total,
        trial_rows=trial_rows_of(scored_trials, registered_manifests=registered_manifests),
        external_flow_evidence_status=external_flow_evidence_status,
        external_flow_pulled_at_ns=external_flow_pulled_at_ns,
        external_flow_newest_rejected_status=external_flow_newest_rejected_status,
        n_external_flow_records=n_external_flow_records,
        n_windows_not_covered=n_windows_not_covered,
        n_explained_external_flow_days=n_explained_external_flow_days,
        n_external_flow_mismatch_days=n_external_flow_mismatch_days,
        n_external_flow_unverifiable_days=n_external_flow_unverifiable_days,
        settled_cumulative_unexplained_net=cumulative.settled_cumulative_unexplained_net,
        provisional_cumulative_unexplained_net=cumulative.provisional_cumulative_unexplained_net,
        settled_cumulative_passes_net=cumulative.settled_cumulative_passes_net,
    )


def _days_between(start_day: str, end_day: str) -> int:
    return (date.fromisoformat(end_day) - date.fromisoformat(start_day)).days + 1


def _portfolio_roi_json_dict(data: PortfolioRoiReportData) -> dict[str, object]:
    return {
        "schema_version": PORTFOLIO_ROI_SCHEMA_VERSION,
        "period_start": data.period_start,
        "period_end": data.period_end,
        "n_fills": data.n_fills,
        "n_scored": data.n_scored,
        "n_residual": data.n_residual,
        "n_unreconciled": data.n_unreconciled,
        "power_caveat": data.power_caveat,
        "realised_pnl_after_fees_total": str(data.realised_pnl_after_fees_total),
        "realised_pnl_residual_total": str(data.realised_pnl_residual_total),
        "realised_pnl_portfolio_total": str(data.realised_pnl_portfolio_total),
        "capital_deployed_total": str(data.capital_deployed_total),
        "roi": str(data.roi),
        "roi_minus_b0": str(data.roi_minus_b0),
        "roi_minus_b1": str(data.roi_minus_b1),
        "unexplained_flow_days": data.unexplained_flow_days,
        "settled_through": data.settled_through,
        "settled_through_statistic": data.settled_through_statistic,
        "lag_sample_n": data.lag_sample_n,
        "roi_status": data.roi_status,
        "unsettled_capital_positions": data.unsettled_capital_positions,
        "max_days_past_horizon": data.max_days_past_horizon,
        "n_family_station_refusals": data.n_family_station_refusals,
        "settled_cumulative_unexplained": str(data.settled_cumulative_unexplained),
        "provisional_cumulative_unexplained": str(data.provisional_cumulative_unexplained),
        "settled_cumulative_passes": data.settled_cumulative_passes,
        # AC3 (golden): the pre-existing `daily_reconciliation` row shape is
        # NEVER widened -- an existing exact-equality golden test pins it to
        # exactly these four keys. FU-13b's per-row net fields live in the
        # SIBLING `net_reconciliation` array below instead.
        "daily_reconciliation": [
            {
                "day": row.day,
                "classification": row.classification,
                "magnitude_cents": row.magnitude_cents,
                "provisional": row.provisional,
            }
            for row in data.daily_reconciliation
        ],
        "net_reconciliation": [
            {
                "day": row.day,
                "net_classification": row.net_classification,
                "external_flow_cents": row.external_flow_cents,
            }
            for row in data.net_reconciliation
        ],
        "n_unexplained_capital_flow_days": data.n_unexplained_capital_flow_days,
        "n_unexplained_proxy_lag_days": data.n_unexplained_proxy_lag_days,
        "n_balance_unknown_days": data.n_balance_unknown_days,
        "n_no_prior_balance_days": data.n_no_prior_balance_days,
        "n_ledger_rows": data.n_ledger_rows,
        "n_undecodable_ledger_rows": data.n_undecodable_ledger_rows,
        "n_exit_fills": data.n_exit_fills,
        "n_duplicate_scored_trials": data.n_duplicate_scored_trials,
        "n_residual_settlements": data.n_residual_settlements,
        "n_residual_pending": data.n_residual_pending,
        "n_residual_unresolved": data.n_residual_unresolved,
        "trial_rows": [
            {
                "trial_id": row.trial_id,
                "family_id": row.family_id,
                "climate_day": row.climate_day,
                "side": row.side,
                "pnl": str(row.pnl),
                "settlement_basis": row.settlement_basis,
            }
            for row in data.trial_rows
        ],
        "external_flow_evidence_status": data.external_flow_evidence_status,
        "external_flow_pulled_at_ns": data.external_flow_pulled_at_ns,
        "external_flow_newest_rejected_status": data.external_flow_newest_rejected_status,
        "n_external_flow_records": data.n_external_flow_records,
        "n_windows_not_covered": data.n_windows_not_covered,
        "n_explained_external_flow_days": data.n_explained_external_flow_days,
        "n_external_flow_mismatch_days": data.n_external_flow_mismatch_days,
        "n_external_flow_unverifiable_days": data.n_external_flow_unverifiable_days,
        "settled_cumulative_unexplained_net": str(data.settled_cumulative_unexplained_net),
        "provisional_cumulative_unexplained_net": str(
            data.provisional_cumulative_unexplained_net
        ),
        "settled_cumulative_passes_net": data.settled_cumulative_passes_net,
    }


def write_portfolio_roi_json(path: Path, data: PortfolioRoiReportData) -> None:
    """Write the D7 versioned JSON sibling, mode 0600 (§6 D6: PRIVATE_
    convention -- every currency-denominated figure lives only here and in
    the sibling Markdown). F7: atomic (tempfile + fsync + `os.replace`),
    mirroring ``alert_ladder.write_latch_state`` -- a failure mid-write
    leaves no partial file and never touches a pre-existing report."""
    _atomic_write_bytes(
        path,
        (json.dumps(_portfolio_roi_json_dict(data), sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        ),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PortfolioRoiReportView:
    """The ONE sanctioned reader's return shape (§6 D7). Every non-ROI field
    is always readable; ``roi``/``roi_minus_b0``/``roi_minus_b1`` raise
    :class:`UnsettledCapitalRoiError` while ``roi_status ==
    "GATED_UNSETTLED_CAPITAL"` (§6 D9)."""

    schema_version: int
    period_start: str
    period_end: str
    n_fills: int
    n_scored: int
    n_residual: int
    n_unreconciled: int
    power_caveat: str
    realised_pnl_after_fees_total: Decimal
    #: FU-3c, absent on v1/v2 -- `None` means "this report predates the
    #: field", never `Decimal(0)` (which would misreport a report that KNOWS
    #: the field and genuinely settled zero residuals).
    realised_pnl_residual_total: Decimal | None
    realised_pnl_portfolio_total: Decimal | None
    capital_deployed_total: Decimal
    unexplained_flow_days: int
    settled_through: str
    settled_through_statistic: str
    lag_sample_n: int
    roi_status: str
    unsettled_capital_positions: int
    max_days_past_horizon: int
    n_family_station_refusals: int
    settled_cumulative_unexplained: Decimal
    provisional_cumulative_unexplained: Decimal
    settled_cumulative_passes: bool
    n_unexplained_capital_flow_days: int
    n_unexplained_proxy_lag_days: int
    n_balance_unknown_days: int
    n_no_prior_balance_days: int
    n_ledger_rows: int
    n_undecodable_ledger_rows: int
    n_exit_fills: int
    n_duplicate_scored_trials: int
    n_residual_settlements: int
    n_residual_pending: int
    n_residual_unresolved: int
    #: G2: the per-day table, typed/validated the same way as every other
    #: field (never a raw list of dicts) -- absent on an old JSON sibling
    #: (schema_version=1 predates this field) reads as `()`, the only
    #: tolerated absence (D7's additive-only rule).
    daily_reconciliation: tuple[DailyUnexplainedSummaryRow, ...]
    #: Stage C3, schema_version=2: one row per settled trial. `None` means
    #: "this report predates the field" (`schema_version=1`) -- NEVER
    #: confused with `()`, which means "this report knows the field and
    #: genuinely settled zero trials this run" (see the module docstring's
    #: "Stage C3 adds" paragraph).
    trial_rows: tuple[PortfolioRoiTrialRow, ...] | None
    #: FU-13b: always present on a report written by this module (default
    #: `NOT_CONFIGURED` for a report predating the field -- honestly true).
    external_flow_evidence_status: str
    external_flow_pulled_at_ns: int | None
    external_flow_newest_rejected_status: str | None
    n_external_flow_records: int
    n_windows_not_covered: int
    n_explained_external_flow_days: int
    n_external_flow_mismatch_days: int
    n_external_flow_unverifiable_days: int
    settled_cumulative_unexplained_net: Decimal
    provisional_cumulative_unexplained_net: Decimal
    settled_cumulative_passes_net: bool
    net_reconciliation: tuple[NetReconciliationRow, ...]
    _roi: Decimal
    _roi_minus_b0: Decimal
    _roi_minus_b1: Decimal

    def _raise_if_gated(self) -> None:
        if self.roi_status == ROI_STATUS_GATED_UNSETTLED_CAPITAL:
            raise UnsettledCapitalRoiError(
                "portfolio ROI is gated: "
                f"{self.unsettled_capital_positions} position(s) past "
                "MAX_SETTLEMENT_HORIZON_NS with no matching ScoredTrial "
                "(see PERMANENTLY_UNSETTLED); consult capital_deployed_total "
                "and n_fills instead of any ROI field"
            )

    @property
    def roi(self) -> Decimal:
        self._raise_if_gated()
        return self._roi

    @property
    def roi_minus_b0(self) -> Decimal:
        self._raise_if_gated()
        return self._roi_minus_b0

    @property
    def roi_minus_b1(self) -> Decimal:
        self._raise_if_gated()
        return self._roi_minus_b1


def read_portfolio_roi_report(path: Path) -> PortfolioRoiReportView:
    """The ONE sanctioned reader (§6 D7). Raises
    :class:`UnknownPortfolioRoiSchemaError` on any `schema_version` this
    module does not know -- never a best-effort parse of an unknown shape.

    F9: every field is type-checked (via `_require_int`/`_require_str`/
    `_require_bool`/`_require_decimal_str`), mirroring
    ``alert_ladder.read_latch_state``'s strictness -- a wrong-typed field
    raises :class:`PortfolioRoiReportMalformedFieldError` naming the field,
    never a bare `KeyError`/`TypeError` from a raw dict access. Fields added
    after `schema_version=1` shipped stay optional-on-read with a default
    (D7's additive-only rule) and are NOT type-checked when absent.

    Accepts every version in :data:`_KNOWN_PORTFOLIO_ROI_SCHEMA_VERSIONS`
    (currently 1 and 2), refusing anything else exactly as before. `trial_id`
    is `None` at `schema_version=1` (the field did not exist yet) and a
    strictly-typed tuple (possibly empty) at `schema_version=2` (see
    `PortfolioRoiReportView.trial_rows`'s own docstring).
    """
    raw = json.loads(path.read_text())
    version = raw.get("schema_version")
    if version not in _KNOWN_PORTFOLIO_ROI_SCHEMA_VERSIONS:
        raise UnknownPortfolioRoiSchemaError(
            f"unknown portfolio ROI schema_version={version!r}; this reader "
            f"only knows schema_version in "
            f"{sorted(_KNOWN_PORTFOLIO_ROI_SCHEMA_VERSIONS)!r}"
        )
    return PortfolioRoiReportView(
        schema_version=version,
        period_start=_require_str(raw, "period_start"),
        period_end=_require_str(raw, "period_end"),
        n_fills=_require_int(raw, "n_fills"),
        n_scored=_require_int(raw, "n_scored"),
        n_residual=_require_int(raw, "n_residual"),
        n_unreconciled=_require_int(raw, "n_unreconciled"),
        power_caveat=_require_str(raw, "power_caveat"),
        realised_pnl_after_fees_total=_require_decimal_str(
            raw, "realised_pnl_after_fees_total"
        ),
        realised_pnl_residual_total=(
            _require_decimal_str(raw, "realised_pnl_residual_total")
            if "realised_pnl_residual_total" in raw
            else None
        ),
        realised_pnl_portfolio_total=(
            _require_decimal_str(raw, "realised_pnl_portfolio_total")
            if "realised_pnl_portfolio_total" in raw
            else None
        ),
        capital_deployed_total=_require_decimal_str(raw, "capital_deployed_total"),
        unexplained_flow_days=_require_int(raw, "unexplained_flow_days"),
        settled_through=_require_str(raw, "settled_through"),
        settled_through_statistic=_require_str(raw, "settled_through_statistic"),
        lag_sample_n=_require_int(raw, "lag_sample_n"),
        roi_status=_require_str(raw, "roi_status"),
        unsettled_capital_positions=_require_int(raw, "unsettled_capital_positions"),
        max_days_past_horizon=_require_int(raw, "max_days_past_horizon"),
        # Additive fields (§6 D7: "additive-only within a major version"): a
        # JSON sibling written before a field existed has no such key, and
        # reads as its default rather than refusing the whole
        # schema_version=1 document over one new, purely diagnostic field --
        # only type-CHECKED when present.
        n_family_station_refusals=(
            _require_int(raw, "n_family_station_refusals")
            if "n_family_station_refusals" in raw
            else 0
        ),
        settled_cumulative_unexplained=(
            _require_decimal_str(raw, "settled_cumulative_unexplained")
            if "settled_cumulative_unexplained" in raw
            else Decimal(0)
        ),
        provisional_cumulative_unexplained=(
            _require_decimal_str(raw, "provisional_cumulative_unexplained")
            if "provisional_cumulative_unexplained" in raw
            else Decimal(0)
        ),
        settled_cumulative_passes=(
            _require_bool(raw, "settled_cumulative_passes")
            if "settled_cumulative_passes" in raw
            else True
        ),
        n_unexplained_capital_flow_days=(
            _require_int(raw, "n_unexplained_capital_flow_days")
            if "n_unexplained_capital_flow_days" in raw
            else 0
        ),
        n_unexplained_proxy_lag_days=(
            _require_int(raw, "n_unexplained_proxy_lag_days")
            if "n_unexplained_proxy_lag_days" in raw
            else 0
        ),
        n_balance_unknown_days=(
            _require_int(raw, "n_balance_unknown_days")
            if "n_balance_unknown_days" in raw
            else 0
        ),
        n_no_prior_balance_days=(
            _require_int(raw, "n_no_prior_balance_days")
            if "n_no_prior_balance_days" in raw
            else 0
        ),
        daily_reconciliation=_require_daily_reconciliation_rows(raw),
        n_ledger_rows=_require_int(raw, "n_ledger_rows") if "n_ledger_rows" in raw else 0,
        n_undecodable_ledger_rows=(
            _require_int(raw, "n_undecodable_ledger_rows")
            if "n_undecodable_ledger_rows" in raw
            else 0
        ),
        n_exit_fills=_require_int(raw, "n_exit_fills") if "n_exit_fills" in raw else 0,
        n_duplicate_scored_trials=(
            _require_int(raw, "n_duplicate_scored_trials")
            if "n_duplicate_scored_trials" in raw
            else 0
        ),
        n_residual_settlements=(
            _require_int(raw, "n_residual_settlements")
            if "n_residual_settlements" in raw
            else 0
        ),
        n_residual_pending=(
            _require_int(raw, "n_residual_pending") if "n_residual_pending" in raw else 0
        ),
        n_residual_unresolved=(
            _require_int(raw, "n_residual_unresolved")
            if "n_residual_unresolved" in raw
            else 0
        ),
        trial_rows=(
            _require_trial_rows(raw)
            if version >= _MIN_SCHEMA_VERSION_WITH_TRIAL_ROWS
            else None
        ),
        # -- FU-13b: additive-only; absent means "predates the field",
        # honestly reported as NOT_CONFIGURED (an old report ran with no
        # puller either).
        external_flow_evidence_status=(
            _require_str(raw, "external_flow_evidence_status")
            if "external_flow_evidence_status" in raw
            else STATUS_NOT_CONFIGURED
        ),
        external_flow_pulled_at_ns=_optional_int(raw, "external_flow_pulled_at_ns"),
        external_flow_newest_rejected_status=_optional_str(
            raw, "external_flow_newest_rejected_status"
        ),
        n_external_flow_records=(
            _require_int(raw, "n_external_flow_records")
            if "n_external_flow_records" in raw
            else 0
        ),
        n_windows_not_covered=(
            _require_int(raw, "n_windows_not_covered") if "n_windows_not_covered" in raw else 0
        ),
        n_explained_external_flow_days=(
            _require_int(raw, "n_explained_external_flow_days")
            if "n_explained_external_flow_days" in raw
            else 0
        ),
        n_external_flow_mismatch_days=(
            _require_int(raw, "n_external_flow_mismatch_days")
            if "n_external_flow_mismatch_days" in raw
            else 0
        ),
        n_external_flow_unverifiable_days=(
            _require_int(raw, "n_external_flow_unverifiable_days")
            if "n_external_flow_unverifiable_days" in raw
            else 0
        ),
        settled_cumulative_unexplained_net=(
            _require_decimal_str(raw, "settled_cumulative_unexplained_net")
            if "settled_cumulative_unexplained_net" in raw
            else Decimal(0)
        ),
        provisional_cumulative_unexplained_net=(
            _require_decimal_str(raw, "provisional_cumulative_unexplained_net")
            if "provisional_cumulative_unexplained_net" in raw
            else Decimal(0)
        ),
        settled_cumulative_passes_net=(
            _require_bool(raw, "settled_cumulative_passes_net")
            if "settled_cumulative_passes_net" in raw
            else True
        ),
        net_reconciliation=_require_net_reconciliation_rows(raw),
        _roi=_require_decimal_str(raw, "roi"),
        _roi_minus_b0=_require_decimal_str(raw, "roi_minus_b0"),
        _roi_minus_b1=_require_decimal_str(raw, "roi_minus_b1"),
    )


# --------------------------------------------------------------------------
# C2 -- the PRIVATE Markdown report (§7 step 3)
# --------------------------------------------------------------------------


def _roi_or_gated(data: PortfolioRoiReportData, value: Decimal) -> str:
    return str(value) if data.roi_status == ROI_STATUS_OK else "GATED -- see roi_status"


def _fee_unverified_disclosure_line(fee_unverified: FeeUnverifiedResidualDisclosure) -> str:
    return (
        "- fee_unverified residuals (FU-3d, modelled, never booked): "
        f"n={fee_unverified.n_fee_unverified_settled}, "
        f"model minus recorded fee={fee_unverified.model_minus_recorded_fee} "
        f"(n unmodelled, θ unresolved: {fee_unverified.n_fee_unverified_unmodelled}); "
        "positive ⇒ residual P&L likely overstated by ≈ this, negative "
        "⇒ understated; per-fill rounding, error either direction."
    )


def render_markdown_report(
    data: PortfolioRoiReportData,
    *,
    fee_unverified: FeeUnverifiedResidualDisclosure | None = None,
) -> str:
    """The PRIVATE Markdown sibling. Every currency figure lives ONLY here
    and in the JSON sibling (§6 D6) -- never in the journal line or an
    alert. `fee_unverified` (FU-3d AC4) is optional and Markdown-only: it
    never reaches `PortfolioRoiReportData`/the JSON sibling; omitted
    (`None`) callers render byte-identical to before this parameter
    existed."""
    lines = [
        "# Portfolio ROI Report (AUD-04, PRIVATE -- do not share outside the operator)",
        "",
        f"Period: {data.period_start} .. {data.period_end}",
        (
            f"n={data.n_fills} settled fills over "
            f"{_days_between(data.period_start, data.period_end)} days; NOT a "
            "statistically powered estimate of improvement over B0 or B1 at "
            "this sample size."
        ),
        f"{data.power_caveat}",
        (
            f"settled_through={data.settled_through} "
            f"settled_through_statistic={data.settled_through_statistic} "
            f"lag_sample_n={data.lag_sample_n}"
        ),
        (
            "Balance series semantics: venue currentBalance (cash or "
            "cash+positions -- UNVERIFIED); this report treats it as CASH."
        ),
        "",
        "## Partition (§8 AC #2)",
        f"- scored: {data.n_scored}",
        f"- residual: {data.n_residual}",
        f"- unreconciled: {data.n_unreconciled}",
        f"- total: {data.n_fills}",
        f"- n_ledger_rows (raw, F4): {data.n_ledger_rows}",
        f"- n_undecodable_ledger_rows (F4): {data.n_undecodable_ledger_rows}",
        (
            f"- n_exit_fills ({UNRECONCILED_EXIT_LABEL}, F5, excluded from capital "
            f"deployed and ROI): {data.n_exit_fills}"
        ),
        "",
        "## Totals",
        f"- realised P&L after fees (total): {data.realised_pnl_after_fees_total}",
        f"- realised P&L residual fills (total, FU-3c): {data.realised_pnl_residual_total}",
        f"- realised P&L portfolio (scored + residual, FU-3c): {data.realised_pnl_portfolio_total}",
        (
            "  (residual P&L is qty-scaled; scored P&L is per-fill = "
            "per-contract: both scored-store writers admit qty==1 fills "
            "only, ruling Q1 + FU-3d guard)"
        ),
        *([_fee_unverified_disclosure_line(fee_unverified)] if fee_unverified is not None else []),
        f"- capital deployed (total, leg-summed, never netted): {data.capital_deployed_total}",
        f"- ROI: {_roi_or_gated(data, data.roi)}",
        f"- ROI - B0 (cash): {_roi_or_gated(data, data.roi_minus_b0)}",
        f"- ROI - B1 (fee-drag null): {_roi_or_gated(data, data.roi_minus_b1)}",
        f"- roi_status: {data.roi_status}",
        "",
        "## Integrity",
        f"- unexplained_flow_days (settled window only): {data.unexplained_flow_days}",
        f"- n_unexplained_capital_flow_days (F2): {data.n_unexplained_capital_flow_days}",
        f"- n_unexplained_proxy_lag_days (F2): {data.n_unexplained_proxy_lag_days}",
        (
            f"- n_balance_unknown_days (F3, excluded from cumulative sums): "
            f"{data.n_balance_unknown_days}"
        ),
        (
            f"- n_no_prior_balance_days (G1, excluded from cumulative sums): "
            f"{data.n_no_prior_balance_days}"
        ),
        f"- unsettled_capital_positions: {data.unsettled_capital_positions}",
        f"- max_days_past_horizon: {data.max_days_past_horizon}",
        f"- n_family_station_refusals: {data.n_family_station_refusals}",
        f"- n_duplicate_scored_trials: {data.n_duplicate_scored_trials}",
        f"- n_residual_settlements (FU-3b): {data.n_residual_settlements}",
        f"- n_residual_pending (FU-3b): {data.n_residual_pending}",
        f"- n_residual_unresolved (FU-3b): {data.n_residual_unresolved}",
        "",
        "## Settled-window cash-identity verdict (F1, §6 D4)",
        f"- settled_cumulative_unexplained: {data.settled_cumulative_unexplained}",
        (
            f"- provisional_cumulative_unexplained (non-gating): "
            f"{data.provisional_cumulative_unexplained}"
        ),
        f"- settled_cumulative_passes: {data.settled_cumulative_passes}",
        "",
        "### Per-day reconciliation",
    ]
    for row in data.daily_reconciliation:
        provisional_suffix = " (PROVISIONAL_IN_FLIGHT)" if row.provisional else ""
        lines.append(
            f"{row.classification} day={row.day} magnitude_cents="
            f"{row.magnitude_cents}{provisional_suffix}"
        )
    if data.roi_status == ROI_STATUS_GATED_UNSETTLED_CAPITAL:
        lines.append(
            "\n**GATED_UNSETTLED_CAPITAL:** at least one position has aged past its "
            "settlement horizon with no matching ScoredTrial. ROI fields above are "
            "gated for every downstream consumer via `read_portfolio_roi_report()`. "
            "Its capital stays in capital_deployed_total (never dropped)."
        )
    # -- FU-13b: APPENDED at the end, after every pre-existing line above --
    # never inserted earlier and never altering an existing line (AC12).
    lines.extend(
        [
            "",
            "## External capital flows (FU-13b, net-of-flow reconciliation)",
            f"- external_flow_evidence_status: {data.external_flow_evidence_status}",
            (
                "- external_flow_newest_rejected_status: "
                f"{data.external_flow_newest_rejected_status}"
            ),
            f"- n_external_flow_records: {data.n_external_flow_records}",
            f"- n_windows_not_covered: {data.n_windows_not_covered}",
            f"- n_explained_external_flow_days: {data.n_explained_external_flow_days}",
            f"- n_external_flow_mismatch_days: {data.n_external_flow_mismatch_days}",
            f"- n_external_flow_unverifiable_days: {data.n_external_flow_unverifiable_days}",
            f"- settled_cumulative_unexplained_net: {data.settled_cumulative_unexplained_net}",
            f"- settled_cumulative_passes_net: {data.settled_cumulative_passes_net}",
            "",
            "### Per-day net classification",
            *(
                f"{row.net_classification} day={row.day} "
                f"external_flow_cents={row.external_flow_cents}"
                for row in data.net_reconciliation
                if row.net_classification is not None
            ),
        ]
    )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# C2 -- D6: the no-currency journal line
# --------------------------------------------------------------------------


def journal_line(data: PortfolioRoiReportData) -> str:
    """§6 D6: 'the journal line ... carr[ies] only dimensionless ratios and
    counts.' Every field below is an integer count, a boolean, a date, or an
    enum label -- never a Decimal/currency figure.

    F1: carries the settled-window cash-identity VERDICT
    (`settled_reconciliation_passes`) as a boolean label, never a magnitude
    -- the per-day `UNEXPLAINED_CAPITAL_FLOW day=<d> magnitude_cents=<...>`
    lines and the cumulative Decimal figures stay PRIVATE-artefact-only
    (Markdown/JSON), per D6.
    """
    return (
        f"PORTFOLIO_ROI period={data.period_start}..{data.period_end} "
        f"n_fills={data.n_fills} n_scored={data.n_scored} "
        f"n_duplicate_scored_trials={data.n_duplicate_scored_trials} "
        f"n_residual={data.n_residual} n_unreconciled={data.n_unreconciled} "
        f"n_ledger_rows={data.n_ledger_rows} "
        f"n_undecodable_ledger_rows={data.n_undecodable_ledger_rows} "
        f"n_exit_fills={data.n_exit_fills} "
        f"roi_status={data.roi_status} "
        f"settled_reconciliation_passes={data.settled_cumulative_passes} "
        f"unexplained_flow_days={data.unexplained_flow_days} "
        f"n_unexplained_capital_flow_days={data.n_unexplained_capital_flow_days} "
        f"n_unexplained_proxy_lag_days={data.n_unexplained_proxy_lag_days} "
        f"n_balance_unknown_days={data.n_balance_unknown_days} "
        f"n_no_prior_balance_days={data.n_no_prior_balance_days} "
        f"unsettled_capital_positions={data.unsettled_capital_positions} "
        f"settled_through_statistic={data.settled_through_statistic} "
        f"lag_sample_n={data.lag_sample_n} "
        f"n_family_station_refusals={data.n_family_station_refusals} "
        f"n_residual_settlements={data.n_residual_settlements} "
        f"n_residual_pending={data.n_residual_pending} "
        f"n_residual_unresolved={data.n_residual_unresolved} "
        # -- FU-13b: appended tokens, dimensionless only (AC9: never trips
        # the currency-withhold regex at deploy/systemd/portfolio-roi-run.sh:114).
        f"external_flow_evidence_status={data.external_flow_evidence_status} "
        f"n_windows_not_covered={data.n_windows_not_covered} "
        f"n_explained_external_flow_days={data.n_explained_external_flow_days} "
        f"n_external_flow_mismatch_days={data.n_external_flow_mismatch_days} "
        f"n_external_flow_unverifiable_days={data.n_external_flow_unverifiable_days} "
        f"settled_reconciliation_passes_net={data.settled_cumulative_passes_net}"
    )


# --------------------------------------------------------------------------
# C2 -- D8/D9: the shared alert-ladder wiring
# --------------------------------------------------------------------------

FROZEN_INPUTS_EVENT: Final[str] = "PORTFOLIO_ROI_INPUTS_FROZEN"
FROZEN_INPUTS_CLEARED_EVENT: Final[str] = "PORTFOLIO_ROI_INPUTS_FROZEN_CLEARED"
PERMANENTLY_UNSETTLED_EVENT: Final[str] = "PORTFOLIO_ROI_POSITION_PERMANENTLY_UNSETTLED"

#: §6 D8: 'days_since_newest_input > 3'.
STALE_INPUT_THRESHOLD_DAYS: Final[int] = 3

INPUT_FRESHNESS_LATCH_FILENAME: Final[str] = ".input_freshness.json"
UNSETTLED_POSITIONS_LATCH_FILENAME: Final[str] = ".unsettled_positions.json"


def is_input_fresh(days_since_newest_input: int | None) -> bool:
    """§6 D8's clear condition: 'days_since_newest_input <= 3 on any run
    resets streak to 0.' `None` (no input has ever been observed) is
    fail-closed as STALE, never as fresh."""
    if days_since_newest_input is None:
        return False
    return days_since_newest_input <= STALE_INPUT_THRESHOLD_DAYS


def days_since_newest_input(
    *, newest_ledger_fill_ts: int | None, newest_scored_trial_ts: int | None, now_ns: int
) -> int | None:
    """The larger (more recent) of the two input timestamps, expressed as
    whole days before `now_ns`; `None` when BOTH inputs have never produced
    a timestamp (fail-closed, never zero -- an empty/never-started pipeline
    reads identically to a genuinely frozen one, which is D8's own honest
    limitation, stated in the artefact)."""
    candidates = [ts for ts in (newest_ledger_fill_ts, newest_scored_trial_ts) if ts is not None]
    if not candidates:
        return None
    newest_ts = max(candidates)
    return max(0, (now_ns - newest_ts) // _NS_PER_DAY)


@dataclass(frozen=True, slots=True, kw_only=True)
class FreshnessAlertDecision:
    """One ladder verdict, already carrying the event name and a
    dimensionless `detail` string -- ready to hand to :class:`AlertPayload`
    unchanged."""

    should_alert: bool
    severity: str | None
    event: str | None
    detail: str


def _apply_ladder(
    *,
    is_fresh: bool,
    latch: alert_ladder.LatchState,
    now_ns: int,
    stale_event: str,
    cleared_event: str,
    stale_detail: str,
    cleared_detail: str,
) -> tuple[alert_ladder.LatchState, FreshnessAlertDecision]:
    """Shared plumbing behind :func:`apply_freshness_ladder` and
    :func:`apply_unsettled_positions_ladder`: drives
    ``breezy.runtime.alert_ladder``'s pure state machine (D8's OWNERSHIP
    rule -- one implementation, two consumers, two latch files, two event
    sets) and returns the next latch state plus this run's decision."""
    previous_streak = latch.streak
    streak = alert_ladder.next_streak(is_fresh=is_fresh, previous_streak=previous_streak)

    if is_fresh:
        new_latch = alert_ladder.LatchState(
            schema_version=alert_ladder.LATCH_SCHEMA_VERSION,
            streak=0,
            last_alert_severity=None,
            last_alert_period_key=None,
        )
        if previous_streak >= alert_ladder.WARN_STREAK_THRESHOLD:
            return new_latch, FreshnessAlertDecision(
                should_alert=True, severity="INFO", event=cleared_event, detail=cleared_detail
            )
        return new_latch, FreshnessAlertDecision(
            should_alert=False, severity=None, event=None, detail=""
        )

    decision = alert_ladder.evaluate_streak(
        streak=streak,
        last_alert_severity=latch.last_alert_severity,
        last_alert_period_key=latch.last_alert_period_key,
        now_ns=now_ns,
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
        return new_latch, FreshnessAlertDecision(
            should_alert=False, severity=None, event=None, detail=""
        )
    return new_latch, FreshnessAlertDecision(
        should_alert=True, severity=decision.severity, event=stale_event, detail=stale_detail
    )


def apply_freshness_ladder(
    *, days_since_newest_input: int | None, latch: alert_ladder.LatchState, now_ns: int
) -> tuple[alert_ladder.LatchState, FreshnessAlertDecision]:
    """D8's own re-alert ladder over ``.input_freshness.json``. `detail` is
    dimensionless (`streak`, `days_since_newest_input`), never a currency
    figure (§6 D6)."""
    previous_streak = latch.streak
    return _apply_ladder(
        is_fresh=is_input_fresh(days_since_newest_input),
        latch=latch,
        now_ns=now_ns,
        stale_event=FROZEN_INPUTS_EVENT,
        cleared_event=FROZEN_INPUTS_CLEARED_EVENT,
        stale_detail=(
            f"streak={previous_streak + 1} days_since_newest_input={days_since_newest_input}"
        ),
        cleared_detail=f"streak_len={previous_streak}",
    )


def apply_unsettled_positions_ladder(
    *,
    unsettled_count: int,
    max_days_past_horizon: int,
    latch: alert_ladder.LatchState,
    now_ns: int,
) -> tuple[alert_ladder.LatchState, FreshnessAlertDecision]:
    """D9's alert over its OWN latch, ``.unsettled_positions.json`` --
    driven by the SAME shared `alert_ladder` state machine (D8's ownership
    rule), never a second implementation. 'Fresh' here means
    `unsettled_count == 0`."""
    return _apply_ladder(
        is_fresh=unsettled_count == 0,
        latch=latch,
        now_ns=now_ns,
        stale_event=PERMANENTLY_UNSETTLED_EVENT,
        cleared_event=PERMANENTLY_UNSETTLED_EVENT + "_CLEARED",
        stale_detail=f"count={unsettled_count} max_days_past_horizon={max_days_past_horizon}",
        cleared_detail="count=0",
    )


def _emit_ladder_decision(sink: AlertSink, site: str, decision: FreshnessAlertDecision) -> None:
    if not decision.should_alert:
        return
    assert decision.severity is not None
    assert decision.event is not None
    emit_alert(
        sink,
        AlertPayload(
            severity=decision.severity, event=decision.event, site=site, detail=decision.detail
        ),
    )


# --------------------------------------------------------------------------
# C2 -- the fill -> trial_id join (I/O shell only; the pure core stays
# untouched above)
# --------------------------------------------------------------------------


def _default_exec_state_db_path() -> Path:
    override = os.environ.get(EXEC_STATE_DB_ENV_VAR, "").strip()
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "breezy" / "state" / "exec_polymarket_us.sqlite"


def _default_scored_trials_dir() -> Path:
    override = os.environ.get("BREEZY_SCORED_TRIALS_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "breezy" / "derived" / "scored_trials"


def _default_logs_dir() -> Path:
    return Path.home() / ".local" / "share" / "breezy" / "logs"


def _default_output_dir() -> Path:
    override = os.environ.get("BREEZY_LIVE_TALLY_OUTPUT_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "breezy" / "derived"


def _default_families_dir() -> Path:
    override = os.environ.get("BREEZY_SCORE_LIVE_TRIALS_FAMILIES_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "deploy" / "families"


def _default_catalog_base() -> Path:
    """FU-3b: the NWS catalog root residual settlement resolution reads
    settlement truth from -- same env-var-or-literal-default convention as
    every other `_default_*` here, defaulting to
    `score_live_trials.DEFAULT_NWS_CATALOG_BASE` (the same root
    `score_live_trials.py` itself resolves to when no override is set)."""
    override = os.environ.get("BREEZY_NWS_CATALOG_BASE", "").strip()
    if override:
        return Path(override)
    return DEFAULT_NWS_CATALOG_BASE


@dataclass(frozen=True, slots=True, kw_only=True)
class FamilyManifestAttribution:
    """:func:`attribute_fills_via_family_manifests`'s return shape:
    ``attributed_fills`` alongside ``n_family_station_refusals``."""

    attributed_fills: tuple[AttributedFill, ...]
    n_family_station_refusals: int


@dataclass(frozen=True, slots=True, kw_only=True)
class FamilyStationResult:
    """F8: one successful ``read_filled_trials_state_db`` call for one
    (REGISTERED ``polymarket_us`` family manifest, station) pair, as
    returned by :func:`enumerate_family_station_pairs`. ``trials`` already
    has :func:`_with_scheduled_release_at_ns` applied (defect 2's fix)."""

    family_id: str
    station: str
    trials: tuple[FilledTrial, ...]
    fee_reconciled_by_trial_id: Mapping[str, tuple[bool, str, bool]]


def enumerate_family_station_pairs(
    *, families_dir: Path, exec_state_db_path: Path
) -> tuple[tuple[FamilyStationResult, ...], int]:
    """F8: the ONE shared enumeration of every (registered ``polymarket_us``
    family manifest, station) pair via
    ``score_live_trials.read_filled_trials_state_db`` -- the SAME loop
    ``deploy/systemd/score-live-trials-run.sh`` already drives (its ``CITY``
    variable is the station code, confirmed at that script's per-city loop).

    Pre-fix, this glob-manifest-load-per-station-read loop was duplicated
    verbatim in :func:`attribute_fills_via_family_manifests` AND in `_run`'s
    own D9 scan, with each copy counting its OWN refusals -- so a single
    genuinely broken (family, station) pair was refused (and counted) TWICE
    per run. This function is now the only place that glob/load/read loop
    exists; both the attribution join (via
    :func:`build_attribution_from_results`) and the D9 left-anti-join scan
    consume the SAME single pass's results, so a refusal is counted once.

    Best-effort per (family, station) pair: any read/registry error for one
    pair is skipped (logged with the type name and family/station -- never
    the exception's own message, which may carry a path/detail) so a single
    bad manifest or an unlisted station never aborts the whole report --
    the ledger itself is what this report is fail-closed on
    (`read_ledger_fills_with_counts`), not this join.
    """
    results: list[FamilyStationResult] = []
    n_refusals = 0
    for manifest_path in sorted(families_dir.glob("*.json")):
        try:
            manifest = load_family_manifest(manifest_path, allow_draft=True)
        except FamilyManifestError:
            continue
        if manifest.venue != "polymarket_us":
            continue
        if manifest.status == "DRAFT_NOT_REGISTERED":
            # FU-9: a family that never armed anything cannot refuse a
            # (family, station) scan either -- pre-fix, every draft was
            # scanned via `allow_draft=True` and its permanently-empty
            # store's `StorePositiveControlFailedError` was folded into
            # `n_family_station_refusals` as a permanent, misleading
            # baseline. `!= "REGISTERED"` is deliberately NOT used here: a
            # future RETIRED/superseded family that actually traded must
            # still be scanned so its fills count.
            logger.info(
                "portfolio_roi_report: skipping DRAFT_NOT_REGISTERED family manifest family=%s",
                manifest.family_id,
            )
            continue
        for station in manifest.stations:
            try:
                site = default_registry().settlement_site(manifest.venue, station)
                cli_location = site.cli_location
                trials, _exclusions, fee_reconciled_by_trial_id, _no_side = (
                    read_filled_trials_state_db(
                        exec_state_db_path,
                        family_prefix=manifest.trial_id_prefix,
                        city=station,
                        cli_location=cli_location,
                        since_climate_day=manifest.d0_climate_day,
                        stations=manifest.stations,
                    )
                )
            except (
                SiteNotFoundError,
                FillSourceUnreadableError,
                StorePositiveControlFailedError,
            ) as exc:
                n_refusals += 1
                logger.warning(
                    "portfolio_roi_report: family/station scan skipped family=%s station=%s: %s",
                    manifest.family_id,
                    station,
                    type(exc).__name__,
                )
                continue
            # defect 2 fix: `read_filled_trials_state_db` returns
            # `FilledTrial`s whose `scheduled_release_at_ns` is a documented
            # PLACEHOLDER 0; every real caller (`score_live_trials.py`'s own
            # `score_live_trials` function) replaces it via
            # `_with_scheduled_release_at_ns` before using the trial for
            # anything horizon-related.
            resolved_trials = tuple(
                _with_scheduled_release_at_ns(trial, venue=manifest.venue, city=station)
                for trial in trials
            )
            results.append(
                FamilyStationResult(
                    family_id=manifest.family_id,
                    station=station,
                    trials=resolved_trials,
                    fee_reconciled_by_trial_id=fee_reconciled_by_trial_id,
                )
            )
    return tuple(results), n_refusals


def build_attribution_from_results(
    fills: Sequence[DurableFillRecord], results: Sequence[FamilyStationResult]
) -> tuple[AttributedFill, ...]:
    """venue_order_id -> trial_id, from an already-enumerated
    :func:`enumerate_family_station_pairs` result set (F8). Family-agnostic
    (§6 D3): every result is folded in, never filtered to one prefix. A
    `venue_order_id` two DIFFERENT (family, station) pairs attribute to two
    different `trial_id`s is left unattributed (`trial_id=None`) rather than
    guessed (§9: 'attribution column is AMBIGUOUS_FAMILY, never a guess' --
    this stage represents that as `None`, which `bucket_for_fill` already
    buckets UNRECONCILED).
    """
    trial_id_by_venue_order_id: dict[str, str] = {}
    ambiguous_venue_order_ids: set[str] = set()
    for result in results:
        for trial_id, (
            _fee_reconciled,
            venue_order_id,
            _skip_ask_guard,
        ) in result.fee_reconciled_by_trial_id.items():
            if not venue_order_id:
                continue
            existing = trial_id_by_venue_order_id.get(venue_order_id)
            if existing is not None and existing != trial_id:
                ambiguous_venue_order_ids.add(venue_order_id)
                continue
            trial_id_by_venue_order_id[venue_order_id] = trial_id

    attributed: list[AttributedFill] = []
    for fill in fills:
        if fill.venue_order_id in ambiguous_venue_order_ids:
            attributed.append(AttributedFill(fill=fill, trial_id=None))
        else:
            attributed.append(
                AttributedFill(
                    fill=fill, trial_id=trial_id_by_venue_order_id.get(fill.venue_order_id)
                )
            )
    return tuple(attributed)


def attribute_fills_via_family_manifests(
    fills: Sequence[DurableFillRecord],
    *,
    exec_state_db_path: Path,
    families_dir: Path,
) -> FamilyManifestAttribution:
    """Standalone convenience wrapper (kept for direct/test use): performs
    its OWN single call to :func:`enumerate_family_station_pairs`. `_run`
    does NOT call this function -- it calls the enumerator once itself and
    shares the same result set with the D9 scan (F8), so a real run performs
    exactly one enumeration pass, not two.
    """
    results, n_refusals = enumerate_family_station_pairs(
        families_dir=families_dir, exec_state_db_path=exec_state_db_path
    )
    attributed = build_attribution_from_results(fills, results)
    return FamilyManifestAttribution(
        attributed_fills=attributed, n_family_station_refusals=n_refusals
    )


# --------------------------------------------------------------------------
# FU-3b -- residual-fill settlement payout resolution shell
# --------------------------------------------------------------------------

#: Closed, named exception tuple for :func:`_resolve_residual_settlements`
#: (modelled on `station_candidate_register._READ_ERRORS`) -- never a broad
#: `except Exception`. :class:`CatalogPathError` covers an unsafe/symlinked
#: catalog path; `OSError` covers a filesystem failure opening or reading a
#: station's NWS catalog.
_RESIDUAL_SETTLEMENT_READ_ERRORS: Final[tuple[type[Exception], ...]] = (
    OSError,
    CatalogPathError,
)


def _resolve_residual_settlements(
    filled_trials: Sequence[FilledTrial],
    *,
    residual_trial_ids: frozenset[str],
    station_by_trial_id: Mapping[str, str],
    catalog_base: Path,
    venue: str,
    now_ns: int,
) -> tuple[tuple[ResidualSettlement, ...], tuple[ResidualPending, ...], int]:
    """Resolve every RESIDUAL-bucket trial's cash settlement, best-effort.

    Deduplicated by `trial_id` -- `filled_trials` is the flattened union of
    every (family, station) pair's own trials (F8's shared enumeration), and
    two families can legitimately enumerate the same residual trial_id.
    Only trials in `residual_trial_ids` are considered; a caller that has
    already removed any trial_id that is ALSO a scored row (the scored row
    already pays it) passes the narrowed set.

    Rung resolution mirrors `score_live_trials.score_live_trials`'s own
    precedent exactly: a trial's own `bucket` wins if already resolved,
    else the persisted instrument definition
    (`_read_bucket_facts_by_instrument_id`, cached per station), else the
    instrument id's own slug grammar (`_bucket_facts_from_instrument_id`).

    Best-effort per trial: a trial this function cannot resolve -- no known
    station, no resolvable rung, or a read failure opening/reading its
    station's NWS catalog -- increments the returned unresolved count and is
    logged by `trial_id`, the exception's type name and message (never an
    amount) when an exception is the cause.
    """
    settlements: list[ResidualSettlement] = []
    pending: list[ResidualPending] = []
    n_unresolved = 0
    seen: set[str] = set()
    bucket_facts_by_station: dict[str, dict[str, WeatherBucketFacts]] = {}

    for trial in filled_trials:
        if trial.trial_id not in residual_trial_ids or trial.trial_id in seen:
            continue
        seen.add(trial.trial_id)

        station = station_by_trial_id.get(trial.trial_id)
        if station is None:
            n_unresolved += 1
            logger.warning(
                "portfolio_roi_report: residual settlement unresolved "
                "trial_id=%s: no attributed station",
                trial.trial_id,
            )
            continue

        try:
            resolved_bucket = trial.bucket
            if resolved_bucket is None:
                by_instrument = bucket_facts_by_station.get(station)
                if by_instrument is None:
                    by_instrument = _read_bucket_facts_by_instrument_id(
                        catalog_base, venue=venue, city=station
                    )
                    bucket_facts_by_station[station] = by_instrument
                resolved_bucket = by_instrument.get(trial.instrument_id)
                if resolved_bucket is None:
                    resolved_bucket = _bucket_facts_from_instrument_id(trial.instrument_id)
            if resolved_bucket is None:
                n_unresolved += 1
                logger.warning(
                    "portfolio_roi_report: residual settlement unresolved "
                    "trial_id=%s: rung_unresolved",
                    trial.trial_id,
                )
                continue
            resolved_trial = trial if trial.bucket is not None else replace(
                trial, bucket=resolved_bucket
            )
            catalog = open_station_catalog(catalog_base, venue, station)
            record = read_climate_day_including_corrections(
                catalog,
                station=trial.station,
                climate_day=date.fromisoformat(trial.climate_day),
            )
        except _RESIDUAL_SETTLEMENT_READ_ERRORS as exc:
            n_unresolved += 1
            logger.warning(
                "portfolio_roi_report: residual settlement lookup failed "
                "trial_id=%s type=%s: %s",
                trial.trial_id,
                type(exc).__name__,
                exc,
            )
            continue

        result = residual_settlement(resolved_trial, record, now_ns=now_ns)
        if isinstance(result, ResidualSettlement):
            settlements.append(result)
        else:
            pending.append(result)

    return tuple(settlements), tuple(pending), n_unresolved


# --------------------------------------------------------------------------
# C2 -- CLI (`main`, argv=None-friendly per the wrapper's no-args contract)
# --------------------------------------------------------------------------


def _run(
    *,
    exec_state_db_path: Path,
    scored_trials_dir: Path,
    logs_dir: Path,
    output_dir: Path,
    families_dir: Path,
    now_ns: int,
    sink: AlertSink,
    catalog_base: Path = DEFAULT_NWS_CATALOG_BASE,
    capital_flows_dir: Path | None = None,
) -> int:
    """The I/O shell's actual work, factored out of `main()` as an explicit
    test seam (never a CLI flag -- mirrors `score_live_trials.main`'s own
    `proc_root` keyword-only seam): every path `main()` would otherwise
    resolve from an env-var-or-literal-default is passed in directly, so a
    test can drive the exact same code `main()` runs against a `tmp_path`
    layout without touching `~/.local/share` or any environment variable
    `main()` reads. `main([])`'s own no-argument CLI contract (pinned by
    `deploy/systemd/portfolio-roi-run.sh` and
    `tests/unit/test_portfolio_roi_deploy.py`) is unchanged by this split.

    `catalog_base` (FU-3b) is only ever read when at least one residual
    trial_id needs resolving (`_resolve_residual_settlements`) -- a run with
    no residual fills touches no catalog path, so the default is safe for
    every pre-existing caller/test that never writes one.
    """
    ledger_result = read_ledger_fills_with_counts(exec_state_db_path)
    if ledger_result is None:
        print(
            "portfolio_roi_report: ledger absent/unreadable at "
            f"{exec_state_db_path} -- refusing to report a fabricated zero",
            file=sys.stderr,
        )
        return 1
    fills = ledger_result.fills

    # defect 1 fix: `scored_trials_*.parquet` and `excluded_fills.jsonl`
    # live per-family, under `<scored_trials_dir>/<family_id>/` (L-38,
    # `scored_trial_store.py:144-163`) -- every production caller
    # (`family_tally_v2.py`'s `--store-dir`, `live_family_tally.py`) reads
    # ONE family's subdirectory at a time. `read_scored_trials_pooled`
    # already unions every subdirectory (plus any legacy top-level rows,
    # `scored_trial_store.py:170-192`); `residual_trial_ids_pooled` mirrors
    # that iteration for the residual sidecar, without a legacy top-level
    # union (see its own docstring for why). Calling the single-directory
    # `read_scored_trials`/`residual_trial_ids` on the family-agnostic
    # parent directory (as this module previously did) always returns
    # nothing, because neither reader recurses.
    # A trial_id shared by two economically-different rows is a data-
    # integrity violation, not a routine event: fail-loud exactly like the
    # ledger-partition and unknown-order-side checks below -- one clear
    # stderr line naming the error type and the offending trial_id (never
    # an amount), non-zero exit, no report written for this run.
    try:
        scored_trials, n_duplicate_scored_trials = dedupe_scored_trials(
            read_scored_trials_pooled(scored_trials_dir).rows
        )
    except DuplicateScoredTrialEconomicsMismatchError as exc:
        print(
            f"portfolio_roi_report: DUPLICATE_SCORED_TRIAL_ECONOMICS_MISMATCH: {exc}",
            file=sys.stderr,
        )
        return 1
    # Stage C3 (review fix): the per-trial P&L breakdown's `family_id`
    # column resolves against every REGISTERED family's declared date
    # window (`_family_id_of_trial`/`resolve_trial_family`) -- never by
    # which scored-trial-store subdirectory a trial happened to be read
    # from (`PooledScoredTrials.rows` doesn't carry that provenance anyway).
    registered_manifests = _load_registered_family_manifests(families_dir)
    residual_ids = residual_trial_ids_pooled(scored_trials_dir)
    scored_ids = scored_trial_ids_of(scored_trials)

    # F8: ONE shared enumeration of every (family, station) pair, consumed
    # by BOTH the attribution join and the D9 scan below -- a refusal is
    # counted once, not twice.
    family_station_results, n_family_station_refusals = enumerate_family_station_pairs(
        families_dir=families_dir, exec_state_db_path=exec_state_db_path
    )
    attributed_fills = build_attribution_from_results(fills, family_station_results)
    buckets = bucket_ledger_fills(
        attributed_fills, scored_trial_ids=scored_ids, residual_trial_ids=residual_ids
    )

    # F4/§8 AC #2: the partition is asserted against the RAW ledger-row
    # counts, non-bypassably -- a violation is fail-loud: non-zero exit, a
    # clear stderr line, and no report written for this run.
    try:
        assert_ledger_partition(ledger_result=ledger_result, buckets=buckets)
    except LedgerPartitionViolationError as exc:
        print(f"portfolio_roi_report: PARTITION VIOLATION: {exc}", file=sys.stderr)
        return 1

    if fills:
        period_start = min(_utc_day_of_fill(f) for f in fills)
    else:
        period_start = _utc_day_of_ns(now_ns)
    period_end = _utc_day_of_ns(now_ns)

    # G3: a fill's `order_side` outside {BUY, SELL} fails loud (F5,
    # `UnknownOrderSideError`) from any of `total_capital_deployed`,
    # `reconcile_daily` (via `capital_deployed_by_day`) or
    # `count_exit_fills` below. Handled exactly like the ledger-partition
    # violation above: one clear stderr line naming the error type and the
    # offending `venue_order_id` (never an amount), non-zero exit, and no
    # report written for this run.
    try:
        # AC3: scored-only, unchanged by FU-3c -- `realised_pnl_after_fees_
        # total` and `trial_rows` must stay exactly this figure.
        total_pnl = total_realised_pnl_all_settled(scored_trials)
        total_capital = total_capital_deployed(fills)

        lags = [settlement_lag_days(trial) for trial in scored_trials]
        now_day = _utc_day_of_ns(now_ns)
        settled_through, statistic_name, lag_sample_n = compute_settled_through(
            now_day=now_day, lags=lags
        )

        period_days_count = _days_between(period_start, period_end)
        days = [_shift_iso_day(period_start, delta) for delta in range(period_days_count)]
        balance_lines: list[str] = []
        if logs_dir.is_dir():
            for log_path in sorted(logs_dir.glob("breezy-trade-*.log")):
                try:
                    balance_lines.extend(log_path.read_text(errors="replace").splitlines())
                except OSError:
                    continue
        balance_series = daily_balance_series(balance_lines, days=days)
        daily_balances = {
            day: (point.total_usd if point is not None else None)
            for day, point in balance_series.items()
        }
        balance_timestamps_ns: dict[str, int] = {
            day: balance_point_ts_ns(point.ts_iso)
            for day, point in balance_series.items()
            if point is not None
        }

        # G1: the earliest known-balance day in `daily_balances` has no
        # PRIOR balance within the report period to diff against. Look
        # further back in the SAME log lines (bounded,
        # `OPENING_BALANCE_LOOKBACK_DAYS`) for a genuine earlier
        # `AccountState(` point -- e.g. the node was already running
        # before the first fill -- so that day reconciles normally instead
        # of falling back to an explicit `NO_PRIOR_BALANCE` row.
        known_days_in_period = sorted(
            day for day, balance in daily_balances.items() if balance is not None
        )
        if known_days_in_period:
            lookback_point = _latest_balance_before(
                balance_lines,
                before_day=known_days_in_period[0],
                max_lookback_days=OPENING_BALANCE_LOOKBACK_DAYS,
            )
            if lookback_point is not None:
                lookback_day = lookback_point.ts_iso[:10]
                daily_balances = {
                    **daily_balances,
                    lookback_day: lookback_point.total_usd,
                }
                balance_timestamps_ns[lookback_day] = balance_point_ts_ns(lookback_point.ts_iso)

        # D9's own list, materialized here (rather than just before its use
        # below) because FU-3b's residual settlement resolution -- which
        # must feed `reconcile_daily` -- needs it too: both consume the SAME
        # `family_station_results` the attribution join above already
        # gathered (F8), no second `read_filled_trials_state_db` pass.
        filled_trials: list[FilledTrial] = [
            trial for result in family_station_results for trial in result.trials
        ]

        # FU-3b: a residual fill's cost is already counted in
        # `capital_deployed` (it is a real ledger fill); absent this, its
        # payout was never counted anywhere. Resolved best-effort, over the
        # RESIDUAL-bucket trial_ids only -- a trial_id that is ALSO a scored
        # row is excluded here (the scored row already pays it, §8 AC
        # "both scored and residual pays once").
        station_by_trial_id = {
            trial.trial_id: result.station
            for result in family_station_results
            for trial in result.trials
        }
        residual_settlements, residual_pending, n_residual_unresolved = (
            _resolve_residual_settlements(
                filled_trials,
                residual_trial_ids=frozenset(residual_ids - scored_ids),
                station_by_trial_id=station_by_trial_id,
                catalog_base=catalog_base,
                venue="polymarket_us",
                now_ns=now_ns,
            )
        )

        # FU-3d AC4/AC5: the Markdown-only fee_unverified disclosure -- read-
        # only, over the SAME `family_station_results`/`filled_trials` F8
        # already gathered above, no second DB pass. Never folded into
        # `residual_pnl`/`total_pnl`/`baselines` below (AC2/AC6).
        fee_reconciled_by_trial_id_pooled: dict[str, tuple[bool, str, bool]] = {
            trial_id: value
            for result in family_station_results
            for trial_id, value in result.fee_reconciled_by_trial_id.items()
        }
        fee_unverified_disclosure = fee_unverified_residual_disclosure(
            fee_unverified_fills=_fee_unverified_fills_deduped(scored_trials_dir),
            filled_trials=filled_trials,
            fee_reconciled_by_trial_id=fee_reconciled_by_trial_id_pooled,
            residual_settlement_trial_ids=frozenset(s.trial_id for s in residual_settlements),
        )

        # FU-3c AC1/AC2: the residual numerator term, folded into `roi`'s
        # baseline computation only AFTER residual settlements are resolved
        # -- `total_pnl` above (AC3) is never touched. Stays inside this
        # SAME `UnknownOrderSideError` try block (Decision 2 file-by-file).
        residual_pnl = total_realised_pnl_residual(residual_settlements)
        baselines = roi_against_baselines(
            total_realised_pnl=total_pnl + residual_pnl,
            total_capital_deployed=total_capital,
            fills=fills,
        )

        # FU-13b: read-only, evidenced net-of-external-flow input. `None`
        # dir (the pre-FU-13b/no-puller-configured case) reads as
        # NOT_CONFIGURED (AC2) -- never inferred, never venue-called here.
        external_flow_evidence = load_evidence(capital_flows_dir)
        daily_rows = reconcile_daily(
            fills=fills,
            scored_trials=scored_trials,
            daily_balances=daily_balances,
            balance_timestamps_ns=balance_timestamps_ns,
            residual_settlements=residual_settlements,
            residual_pending=residual_pending,
            external_flows=external_flow_evidence,
        )
        # G1: a successful look-back above adds a day BEFORE `period_start`
        # into `daily_balances` purely as a window anchor -- it is never
        # itself a day this report covers, so if it has no prior balance of
        # its OWN (the bounded look-back has to stop somewhere), it must
        # not surface as a `NO_PRIOR_BALANCE` row outside the report
        # period. Every within-period day this row could have obscured is
        # still fully covered: the window it anchors resolves normally
        # (see the row for the period's own earliest known day), and no
        # fill/trial is ever dated before `period_start` by construction
        # (`period_start` is defined as the earliest fill's own day).
        daily_rows = tuple(row for row in daily_rows if row.day >= period_start)
        cumulative = cumulative_reconciliation(
            daily_rows=daily_rows, settled_through=settled_through
        )

        # D9: the permanently-unsettled left-anti-join, over the SAME
        # `family_station_results`/`filled_trials` gathered above (F8) -- no
        # second `read_filled_trials_state_db` pass.
        # FU-3c AC4: "settled" for D9 means scored OR resolved-residual --
        # `permanently_unsettled_trials` itself (Decision 3) is unchanged;
        # only the union it is called with grows. A pending/unresolved
        # residual contributes no trial_id here, so it stays flagged past
        # its horizon exactly as before (the negative half stays fail-closed).
        permanently_unsettled = permanently_unsettled_trials(
            filled_trials,
            scored_trial_ids=scored_ids | frozenset(s.trial_id for s in residual_settlements),
            now_ns=now_ns,
        )

        # F5: SELL exits, visible only as a dimensionless count -- see
        # `exit_label_for_fill`'s docstring for why this reader does not
        # guess their cash-proceeds semantics.
        n_exit_fills = count_exit_fills(fills)
    except UnknownOrderSideError as exc:
        print(f"portfolio_roi_report: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    report_data = build_portfolio_roi_report_data(
        period_start=period_start,
        period_end=period_end,
        fill_buckets=buckets,
        total_realised_pnl=total_pnl,
        total_capital_deployed=total_capital,
        baselines=baselines,
        cumulative=cumulative,
        settled_through_statistic=statistic_name,
        lag_sample_n=lag_sample_n,
        permanently_unsettled=permanently_unsettled,
        n_family_station_refusals=n_family_station_refusals,
        n_ledger_rows=ledger_result.n_ledger_rows,
        n_undecodable_ledger_rows=ledger_result.n_undecodable_ledger_rows,
        n_exit_fills=n_exit_fills,
        n_duplicate_scored_trials=n_duplicate_scored_trials,
        n_residual_settlements=len(residual_settlements),
        n_residual_pending=len(residual_pending),
        n_residual_unresolved=n_residual_unresolved,
        realised_pnl_residual_total=residual_pnl,
        scored_trials=scored_trials,
        registered_manifests=registered_manifests,
        external_flow_evidence_status=external_flow_evidence.status,
        external_flow_pulled_at_ns=external_flow_evidence.pulled_at_ns,
        external_flow_newest_rejected_status=external_flow_evidence.newest_rejected_status,
        n_external_flow_records=len(external_flow_evidence.flows),
    )

    # F7/F9: atomic writes -- the directory is created by
    # `_atomic_write_bytes` itself, so no redundant explicit `mkdir` here.
    stamp = now_day
    json_path = output_dir / f"PRIVATE_portfolio_roi_{stamp}.json"
    md_path = output_dir / f"PRIVATE_portfolio_roi_{stamp}.md"
    write_portfolio_roi_json(json_path, report_data)
    _atomic_write_bytes(
        md_path,
        render_markdown_report(report_data, fee_unverified=fee_unverified_disclosure).encode(
            "utf-8"
        ),
    )

    print(journal_line(report_data))

    # D8 -- frozen-input detector.
    newest_ledger_fill_ts = max((f.ts_event for f in fills), default=None)
    newest_scored_trial_ts = max((t.scored_at_ns for t in scored_trials), default=None)
    freshness_days = days_since_newest_input(
        newest_ledger_fill_ts=newest_ledger_fill_ts,
        newest_scored_trial_ts=newest_scored_trial_ts,
        now_ns=now_ns,
    )
    freshness_latch_path = output_dir / "portfolio_roi" / INPUT_FRESHNESS_LATCH_FILENAME
    freshness_latch = alert_ladder.read_latch_state(freshness_latch_path)
    new_freshness_latch, freshness_decision = apply_freshness_ladder(
        days_since_newest_input=freshness_days, latch=freshness_latch, now_ns=now_ns
    )
    alert_ladder.write_latch_state(freshness_latch_path, new_freshness_latch)
    _emit_ladder_decision(sink, "portfolio_roi_report", freshness_decision)

    # D9 -- open-position staleness alert.
    unsettled_latch_path = output_dir / "portfolio_roi" / UNSETTLED_POSITIONS_LATCH_FILENAME
    unsettled_latch = alert_ladder.read_latch_state(unsettled_latch_path)
    new_unsettled_latch, unsettled_decision = apply_unsettled_positions_ladder(
        unsettled_count=len(permanently_unsettled),
        max_days_past_horizon=report_data.max_days_past_horizon,
        latch=unsettled_latch,
        now_ns=now_ns,
    )
    alert_ladder.write_latch_state(unsettled_latch_path, new_unsettled_latch)
    _emit_ladder_decision(sink, "portfolio_roi_report", unsettled_decision)

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Thin I/O shell over `_run()`. `argv` is accepted (and ignored, beyond
    its emptiness) so this matches the deployed wrapper's contract of
    invoking the script with NO ARGUMENTS -- every input/output path is
    resolved from the same env-var-or-literal-default convention every
    sibling study wrapper already uses (see the `_default_*` functions
    above). Never assigns or reads an operator-reserved control.
    """
    del argv  # accepted for CLI-shape symmetry with sibling scripts; unused

    log_alert_egress_status(os.environ, component="portfolio_roi_report")
    return _run(
        exec_state_db_path=_default_exec_state_db_path(),
        scored_trials_dir=_default_scored_trials_dir(),
        logs_dir=_default_logs_dir(),
        output_dir=_default_output_dir(),
        families_dir=_default_families_dir(),
        now_ns=time.time_ns(),
        sink=resolve_alert_sink(os.environ),
        catalog_base=_default_catalog_base(),
        # FU-13b: same `_default_output_dir()` root the wrapper argv never
        # changes -- the puller (stage S2) writes snapshots to this same
        # subdirectory.
        capital_flows_dir=_default_output_dir() / "capital_flows",
    )


if __name__ == "__main__":
    raise SystemExit(main())
