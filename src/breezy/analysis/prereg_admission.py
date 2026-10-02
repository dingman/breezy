"""PREREG fill-admission core.

Moved verbatim from ``scripts/analysis/score_live_trials.py`` (R2.2):
``_admit_fill``, ``_admit_one_fill``, ``compute_residual``,
``read_filled_trials_state_db``, and the exclusion types they construct.
No Nautilus import and no catalog walk -- ``catalog.instruments()`` stays
in the script. ``score_live_trials`` re-exports these names, so script-local
calls and ``from score_live_trials import ...`` keep resolving.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError
from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.adapters.polymarket_us.exec.no_side_keys import (
    NO_SIDE_FIRST_LIVE_ORDER_KEY,
    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,
)
from breezy.analysis.fill_time_count import _TAKEN_REASON, _open_readonly
from breezy.persistence.residual_fills import (
    RESIDUAL_EXCLUSION_REASONS,
    FillExclusionReason,
)
from breezy.settlement.trial_scorer import FilledTrial
from breezy.strategy.current_rung_hold.trial_day_latch import (
    TAKEN_FROM_FILL_WALK_REASON,
    TrialDayRecord,
    TrialDayRecordCorrupt,
    trial_id_for,
)

#: Fill-vs-ask guard tick (L-25): the venue's `orderPriceMinTickSize`, which
#: every observed PM.us market payload carries as `0.01`
#: (`docs/evidence/venue/polymarket_us/`) -- UNVERIFIED that this offline
#: reader's fixtures carry it, hence the pinned module constant rather than a
#: re-parse of `Instrument.price_increment`.
_TICK: Final[Decimal] = Decimal("0.01")


class FillSourceUnreadableError(Exception):
    """The state-DB fill source could not be opened read-only or read (A5).

    The caller (`main`) exits non-zero without printing the path; the
    wrapper (not this script) owns the missing-marker consequence.
    """


class StorePositiveControlFailedError(Exception):
    """No latch under `family_prefix` for any manifest station exists in this
    store at all (BLOCK-1.2): an openable but WRONG store must refuse, never
    silently score zero."""


#: Partial-fill admission gate (binding ruling,
#: `docs/evidence/grok_partial_fill_ruling_2026-09-04.md` Q1): the
#: registered v1 unit of observation is a 1-contract IOC filled Take. A fill
#: with `qty != 1` is excluded fail-closed here, BEFORE `score_trial` --
#: it enters neither the Wilson n/k nor the stop-rule sum(PnL). This is a
#: closed set, never extended ad hoc: `partial_fill` (0 < qty < 1) and
#: `multi_fill` (qty > 1) as a documented sibling for the over-fill case the
#: ruling's wording also covers ("qty != 1"). `qty <= 0` is a different,
#: malformed-input case (see `_validate_qty`) and is never a member of this
#: set -- a zero-fill (IOC miss) "is not a trial at all" per the ruling, so
#: it must never be silently scored NOR silently dropped; it is refused
#: loudly through the existing `ScoreRefusal(reason="malformed_input")`
#: channel instead, which the CLI already prints for every refusal.
#:
#: Widened old -> new (I2 BLOCK-3, `LIVE_FILL_SCORING_CHAIN_2026-09-05.md`
#: section 3.0(c)): `{"partial_fill", "multi_fill"}` -> plus
#: `"fill_below_ask"` (L-25, the fill-vs-ask guard), `"fee_unverified"` (the
#: venue's cumulative fee could not be reconciled to its legs), and the three
#: join-integrity reasons the state-DB reader alone can raise --
#: `"duplicate_fill_for_latch"`, `"no_taken_latch"`, `"ambiguous_latch"`.
#: Widened again (plan rev 6.1, Slice 4 item B2): `"duplicate_fill"` -- the
#: v3 continuous-rung-hold family's EXPLICIT signal (a genuine SECOND fill on
#: an already-consumed station-day, `TrialDayLatch.record_duplicate_fill`),
#: WP-31: the PREREG v3 §5 residual vocabulary is EXTRACTED to
#: `breezy.persistence.residual_fills` so `src/` consumers (which cannot
#: import a script) share this module's definition rather than copying it.
#: Re-exported from `scripts/analysis/score_live_trials` unchanged: every
#: existing `from score_live_trials import RESIDUAL_EXCLUSION_REASONS` import
#: site still resolves, and this module's own uses are byte-identical.

@dataclass(frozen=True, slots=True, kw_only=True)
class FillExclusion:
    """One fill admitted-but-excluded before scoring (ruling Q1).

    Never pooled into scoring, never written to the scored-trial store --
    `ScoredTrial.excluded_reason` is a different, scoring-time concept (the
    venue-fallback-without-NWS case). Reported in the CLI's exclusions
    table so operators see coverage, not just totals.

    `venue_order_id` and `filled_at_ns` (I2 BLOCK-3, defaulted so the three
    shipped construction sites -- `_admit_fill` and `test_score_live_trials.py`
    -- stay green): the state-DB path always supplies the real
    `venue_order_id`, so `(venue_order_id, reason)` idempotence
    (`excluded_fills.jsonl`, 3.0 (c)) holds for every LIVE line; the JSONL
    fixture path has no venue order id and keeps the `""` default.
    """

    trial_id: str
    station: str
    climate_day: str
    qty: str
    reason: FillExclusionReason
    detail: str
    venue_order_id: str = ""
    filled_at_ns: int = 0
    #: Slice 4 item B2 (plan rev 6.1): populated ONLY for a reason in
    #: `RESIDUAL_EXCLUSION_REASONS` -- `""` (the pre-existing default) for
    #: every other reason, so every pre-Slice-4 construction site (and every
    #: pinned test asserting on those) stays byte-identical.
    fill_px: str = ""
    fee: str = ""

def _admit_fill(
    trial: FilledTrial,
    *,
    fee_reconciled: bool = True,
    venue_order_id: str = "",
    tick: Decimal = _TICK,
    skip_ask_guard: bool = False,
    no_side_residual: bool = False,
) -> FillExclusion | None:
    """Ruling Q1 admission gate, widened by I2 (BLOCK-3/L-25). Assumes
    `trial.qty > 0` (call `_validate_qty` first). Returns `None` when the
    fill is admitted, else the `FillExclusion` to report.

    Order: `qty != 1` (ruling Q1) -> `fill_px < entry_ask - tick` (L-25,
    strict: exactly one tick better is scored, UNLESS `skip_ask_guard`) ->
    `fee_reconciled is False`. `fee_reconciled` and `venue_order_id` default
    to the JSONL fixture path's behaviour (`True`/`""`); the state-DB path
    always supplies both real values.

    `skip_ask_guard` (three-seam Slice 4 review item 3): `True` only for a
    v3 trial whose latch `reason` is `TAKEN_FROM_FILL_WALK_REASON` -- the
    never-arm fill walk has no decision-time ask to compare against (its
    `entry_ask` is derived from the fill itself, `cumulative_cost /
    cumulative_qty`), so comparing a fill price to itself would pass the
    guard VACUOUSLY rather than skip it. The guard is skipped BY REASON,
    never by an ask value that would make it inert by construction.
    """
    if trial.qty != 1:
        reason: FillExclusionReason = "partial_fill" if trial.qty < 1 else "multi_fill"
        return FillExclusion(
            trial_id=trial.trial_id,
            station=trial.station,
            climate_day=trial.climate_day,
            qty=str(trial.qty),
            reason=reason,
            detail=f"qty {trial.qty} != 1; v1 unit is a 1-contract IOC fill (ruling Q1)",
            venue_order_id=venue_order_id,
            filled_at_ns=trial.filled_at_ns,
            fill_px=str(trial.fill_px),
            fee=str(trial.fee),
        )
    if not skip_ask_guard and trial.fill_px < trial.entry_ask - tick:
        return FillExclusion(
            trial_id=trial.trial_id,
            station=trial.station,
            climate_day=trial.climate_day,
            qty=str(trial.qty),
            reason="fill_below_ask",
            detail=(
                f"fill_px {trial.fill_px} < entry_ask {trial.entry_ask} - tick "
                f"{tick} (L-25 defect signature)"
            ),
            venue_order_id=venue_order_id,
            filled_at_ns=trial.filled_at_ns,
        )
    if not fee_reconciled:
        return FillExclusion(
            trial_id=trial.trial_id,
            station=trial.station,
            climate_day=trial.climate_day,
            qty=str(trial.qty),
            reason="fee_unverified",
            detail="the venue's cumulative fee could not be reconciled to its fill-type legs",
            venue_order_id=venue_order_id,
            filled_at_ns=trial.filled_at_ns,
            fill_px=str(trial.fill_px),
            fee=str(trial.fee),
        )
    if no_side_residual:
        # NO-SIDE S5 (E2-1(iii)/E3-3): checked LAST -- an otherwise fully
        # admissible fill (qty==1, ask-respecting, fee-reconciled) is
        # excluded only because it is the FIRST live NO create-path trial,
        # marked by the durable first-order key while the bounded
        # containment window is open (PREREG amendment §8).
        return FillExclusion(
            trial_id=trial.trial_id,
            station=trial.station,
            climate_day=trial.climate_day,
            qty=str(trial.qty),
            reason="no_side_first_order_residual",
            detail=(
                "the first live NO create-path trial is residual while "
                "the bounded first-order containment window is open"
            ),
            venue_order_id=venue_order_id,
            filled_at_ns=trial.filled_at_ns,
            fill_px=str(trial.fill_px),
            fee=str(trial.fee),
        )
    return None


def compute_residual(exclusions: Sequence[FillExclusion]) -> Decimal:
    """Slice 4 item B2 (plan rev 6.1): the residual dollar sum -- every
    exclusion whose `reason` is in `RESIDUAL_EXCLUSION_REASONS` contributes
    `qty * (fill_px + fee)`; every other reason (`fill_below_ask`,
    `duplicate_fill_for_latch`, `no_taken_latch`, `ambiguous_latch`)
    contributes nothing. An exclusion with an empty `fill_px`/`fee` (every
    pre-Slice-4 construction site) is skipped, never coerced to `0` -- a
    missing value is not evidence of a zero dollar cost.
    """
    total = Decimal(0)
    for exclusion in exclusions:
        if exclusion.reason not in RESIDUAL_EXCLUSION_REASONS:
            continue
        if not exclusion.fill_px or not exclusion.fee:
            continue
        total += Decimal(exclusion.qty) * (Decimal(exclusion.fill_px) + Decimal(exclusion.fee))
    return total

def read_filled_trials_state_db(
    path: Path,
    *,
    family_prefix: str,
    city: str,
    cli_location: str,
    since_climate_day: str,
    stations: Sequence[str],
    until_climate_day: str | None = None,
) -> tuple[
    tuple[FilledTrial, ...],
    tuple[FillExclusion, ...],
    Mapping[str, tuple[bool, str, bool]],
    Mapping[str, bool],
]:
    """Read real fills from the live exec `SqliteStateStore`, joined to each
    trial's `current_rung_hold/trial/{station}/{climate_day}` latch by
    `instrument_id` (I2, `LIVE_FILL_SCORING_CHAIN_2026-09-05.md`).

    Opens `path` READ-ONLY via the shipped `fill_time_count._open_readonly`
    (`mode=ro` URI, no flock) -- ONE implementation, never a second
    read-only-connect. Raises `FillSourceUnreadableError` when the store
    cannot be opened or read; the caller (`main`) is the one that turns that
    into a non-zero exit (A5) -- this function never prints or logs the path.

    Store positive control (BLOCK-1.2), checked BEFORE any join: an openable
    but WRONG store must refuse, never silently score zero. Requires >= 1
    latch key under `family_prefix` whose CITY segment is any member of
    `stations` -- per-STORE, not per-city, deliberately (a station with no
    activity today must not refuse a correct store). Raises
    `StorePositiveControlFailedError` otherwise.

    Cross-city scoping (F1, security review of 5cd169a): the deployed
    wrapper runs this reader once per manifest station over ONE store
    SHARED by every city. Taken latches are indexed for EVERY city in the
    store (still `climate_day >= since_climate_day` and `family_prefix`),
    never filtered to this run's `city` up front -- filtering the latch
    index to `city` made every OTHER city's correctly-taken, correctly-filled
    trade look like this city's `no_taken_latch`, a false exclusion that is
    PERMANENT under the artefact's `(venue_order_id, reason)` idempotence
    key. Each fill's instrument is classified against the FULL cross-city
    index: (a) exactly one taken latch and its city == this run's `city` ->
    processed as today; (b) exactly one taken latch belonging to ANOTHER
    city -> silently SKIPPED (never scored, never excluded here -- it is
    that city's own invocation's fill to take); (c) no taken latch under
    ANY city -> `no_taken_latch`, with identical `reason`/`detail`/identity
    fields regardless of which city's invocation produced it, so every
    invocation agrees on the one artefact line; (d) more than one taken
    latch across any cities -> `ambiguous_latch`, unchanged.

    Join integrity events -- EXCLUSIONS, never `ScoreRefusal` (BLOCK-3):
    (i) `ambiguous_latch` (case d above); (ii) `no_taken_latch` (case c
    above), with `trial_id`/`station`/`climate_day` = `""` (allowed for this
    reason only); (iii) more than one fill record joining ONE latch excludes
    EACH fill as `duplicate_fill_for_latch`, one line per `venue_order_id`,
    both (or all) kept out of scoring. A `paper_replay/` latch key never
    matches `family_prefix` (plain `str.startswith`).

    Fail-closed on store corruption (F3, supersedes an earlier
    skip-and-count design): a latch record that raises `TrialDayRecordCorrupt`
    or a fill record that raises `ExecutionReportMappingError` on decode, or
    a decoded fill record with `cumulative_qty <= 0` (F1), each raise
    `FillSourceUnreadableError` instead of being joined, skipped, or
    excluded -- an undecodable or unscorable durable record is STORE
    corruption, never a per-fill exclusion, so it fails the whole run
    closed. The message names only the key prefix and the violated rule,
    never the key's content or the raw bytes.

    Returns `(trials, exclusions, fee_reconciled_by_trial_id,
    no_side_residual_by_trial_id)`; the third member maps `trial_id ->
    (fee_reconciled, venue_order_id, skip_ask_guard)` (three-seam Slice 4
    review item 3: `skip_ask_guard` is `True` only for a
    `TAKEN_FROM_FILL_WALK_REASON` latch) so the caller can pass both new
    keyword arguments into `_admit_fill`. `FilledTrial.scheduled_release_at_ns`
    is a placeholder `0` here -- this reader takes no `venue` (the signature
    above is frozen, Stage-0), so the caller resolves the real settlement
    instant via `_with_scheduled_release_at_ns`, the one place `venue` and
    `city` are both already in hand.

    NO-SIDE S5 (E2-1(iii)/E3-3): `no_side_residual_by_trial_id` maps
    `trial_id -> True` for the ONE trial whose fill instrument matches the
    `NO_SIDE_FIRST_LIVE_ORDER_KEY` payload's `instrumentId`, read from the
    SAME `rows` this function already fetched (never a second store read),
    while `NO_SIDE_POSITION_SHAPE_CAPTURED_KEY` is absent (the bounded
    containment window, `is_no_side_pending`). Every other trial is absent
    from the mapping (falsy default at the call site, exactly like
    `fee_reconciled_by_trial_id.get(...)`).
    """
    conn = _open_readonly(path)
    if conn is None:
        raise FillSourceUnreadableError("the fill source could not be opened read-only")
    try:
        rows = conn.execute("SELECT key, value FROM state").fetchall()
    except sqlite3.Error as exc:
        raise FillSourceUnreadableError("the fill source could not be read") from exc
    finally:
        conn.close()

    # NO-SIDE S5 (E2-1(iii)/E3-3): both durable keys, read from the SAME
    # `rows` fetch above -- never a second store read. `pending_instrument_id`
    # is `None` unless the containment window is genuinely open (first-order
    # present, captured absent).
    no_side_first_order_raw: bytes | None = None
    no_side_captured_present = False
    for key, value in rows:
        if key == NO_SIDE_FIRST_LIVE_ORDER_KEY:
            no_side_first_order_raw = value
        elif key == NO_SIDE_POSITION_SHAPE_CAPTURED_KEY:
            no_side_captured_present = True
    pending_instrument_id: str | None = None
    if no_side_first_order_raw is not None and not no_side_captured_present:
        try:
            pending_payload = json.loads(no_side_first_order_raw)
            pending_instrument_id = pending_payload.get("instrumentId")
        except (TypeError, ValueError):
            pending_instrument_id = None

    station_census = set(stations)
    has_census_latch = False
    for key, _value in rows:
        if not isinstance(key, str) or not key.startswith(family_prefix):
            continue
        parts = key[len(family_prefix) :].split("/")
        # v3 (plan S1, operator ruling 2026-09-14): an instrument-keyed
        # latch key is 3-part (`station/climate_day/instrument_id`, built by
        # `trial_day_latch._key`) -- the station segment is still `parts[0]`
        # either way, so the census check widens to `(2, 3)` rather than
        # gaining a second branch.
        if len(parts) in (2, 3) and parts[0] in station_census:
            has_census_latch = True
            break
    if not has_census_latch:
        # v3 Phase 0: a store with zero prefix keys is n=0, not a store failure.
        # v2 branch is unchanged (positive control still refuses).
        if family_prefix.startswith("continuous_rung_hold/"):
            return (), (), {}, {}
        raise StorePositiveControlFailedError("store_positive_control_failed")

    # instrument_id -> every TAKEN latch across ALL cities sharing this
    # store (F1 -- never filtered to this run's `city` up front), on or
    # after `since_climate_day` (ISO-8601 dates sort lexicographically).
    # Each entry also carries the latch's own `station` so a fill can be
    # classified below as this run's city, another city's, or no city's.
    # Slice 4 item B2 (plan rev 6.1): the tuple's LAST member is the latch's
    # own `venue_order_id` (`None` for a pre-Slice-4 v2 record, or any
    # record this family never populates it for) -- read-only, used ONLY by
    # the v3 (`continuous_rung_hold/`) duplicate-fill split below. The v2
    # branch never consults it, so a v2 store's behaviour is unaffected.
    latches_by_instrument: dict[
        str, list[tuple[str, str, Decimal, str, str | None, str]]
    ] = {}
    for key, value in rows:
        if not isinstance(key, str) or not key.startswith(family_prefix):
            continue
        parts = key[len(family_prefix) :].split("/")
        # v3 (plan S1, operator ruling 2026-09-14 -- "I never wanted a limit
        # of 1 contract per station"): `trial_day_latch._key` also writes a
        # 3-part `station/climate_day/instrument_id` shape. `key_instrument_id`
        # is `None` for the legacy 2-part shape (v2's only shape, unchanged
        # below) and the raw third segment for the 3-part shape.
        if len(parts) == 2:
            station, climate_day = parts
            key_instrument_id: str | None = None
        elif len(parts) == 3:
            station, climate_day, key_instrument_id = parts
        else:
            continue
        if climate_day < since_climate_day:
            continue
        # Inclusive upper bound, the mirror of `assert_family_only`: a closed
        # family's terminal day is kept; the next day is not scored here.
        # `None` is still open (AUD-05 D-G). No new CLI flag.
        if until_climate_day is not None and climate_day > until_climate_day:
            continue
        try:
            record = TrialDayRecord.from_bytes(value)
        except TrialDayRecordCorrupt as exc:
            # F3 (fail-closed): an undecodable latch record is store
            # corruption, never a silent skip -- never the key's content or
            # the raw bytes.
            raise FillSourceUnreadableError(
                f"a record under the {family_prefix!r} key prefix could not be decoded"
            ) from exc
        # Three-seam Slice 4 review item 3: a fill-walk-consumed record
        # (`TAKEN_FROM_FILL_WALK_REASON`) is STILL a genuine filled take --
        # it must reach scoring, just with the ask guard skipped by reason
        # (below), never dropped here as if it were a refusal.
        if record.reason not in (_TAKEN_REASON, TAKEN_FROM_FILL_WALK_REASON):
            continue
        if key_instrument_id is None:
            trial_id = key
        else:
            # The key's own instrument-id segment must agree with the
            # decoded record's `instrument_id` field -- compared through
            # `trial_id_for` (the latch's own public normalization wrapper,
            # never re-derived here) rather than a raw string compare, so a
            # dotted-vs-bare spelling difference is never mistaken for a
            # genuine disagreement. A real disagreement is store corruption
            # (F3's existing convention): fail the whole run closed, never a
            # silent join on the wrong identity.
            from_key = trial_id_for(family_prefix, station, climate_day, key_instrument_id)
            from_record = trial_id_for(family_prefix, station, climate_day, record.instrument_id)
            if from_key != from_record:
                raise FillSourceUnreadableError(
                    f"a record under the {family_prefix!r} key prefix has an "
                    "instrument-id key segment that disagrees with its own "
                    "record's instrument_id"
                )
            trial_id = from_record
        latches_by_instrument.setdefault(record.instrument_id, []).append(
            (trial_id, climate_day, record.ask, station, record.venue_order_id, record.reason)
        )

    fills_by_instrument: dict[str, list[DurableFillRecord]] = {}
    for key, value in rows:
        if not isinstance(key, str) or not key.startswith(FILL_KEY_PREFIX):
            continue
        try:
            fill = DurableFillRecord.from_bytes(value)
        except ExecutionReportMappingError as exc:
            # F3 (fail-closed): an undecodable fill record is store
            # corruption, never a silent skip -- never the key's content or
            # the raw bytes.
            raise FillSourceUnreadableError(
                f"a record under the {FILL_KEY_PREFIX!r} key prefix could not be decoded"
            ) from exc
        # F1: a record that DECODES but carries a non-positive cumulative_qty
        # is unscorable -- `fill_px`/`fee` below divide by it -- and that is
        # store corruption, not a fill-level exclusion (never a member of
        # `FillExclusionReason`). Fails the WHOLE run closed, mirroring the
        # open/read failures at the top of this function and the decode
        # failures just above -- never the actual value.
        if fill.cumulative_qty <= 0:
            raise FillSourceUnreadableError(
                "a durable fill record has a non-positive cumulative_qty"
            )
        fills_by_instrument.setdefault(fill.instrument_id, []).append(fill)

    trials: list[FilledTrial] = []
    exclusions: list[FillExclusion] = []
    fee_reconciled_by_trial_id: dict[str, tuple[bool, str, bool]] = {}

    for instrument_id, fills in fills_by_instrument.items():
        entries = latches_by_instrument.get(instrument_id, [])
        if not entries:
            # F1 (c): no taken latch under ANY city -- emitted identically
            # by every city's invocation (no city-specific text), so the
            # artefact's `(venue_order_id, reason)` idempotence key sees the
            # same content no matter which invocation writes first.
            for fill in fills:
                exclusions.append(
                    FillExclusion(
                        trial_id="",
                        station="",
                        climate_day="",
                        qty=str(fill.cumulative_qty),
                        reason="no_taken_latch",
                        detail=(
                            f"no taken latch under {family_prefix!r} matches "
                            f"instrument {instrument_id!r}"
                        ),
                        venue_order_id=fill.venue_order_id,
                        filled_at_ns=fill.ts_event,
                    )
                )
            continue
        # More than one latch (F1 (d), across any cities): report against
        # the FIRST-landed one, purely for diagnostics -- which latch is
        # "the" trial is exactly what is ambiguous, mirroring
        # `_read_bucket_facts_by_instrument_id`'s first-landed-stands idiom
        # elsewhere in this module.
        trial_id, climate_day, ask, latch_station, latch_venue_order_id, latch_reason = entries[0]
        skip_ask_guard = latch_reason == TAKEN_FROM_FILL_WALK_REASON
        if len(entries) > 1:
            for fill in fills:
                exclusions.append(
                    FillExclusion(
                        trial_id=trial_id,
                        station=cli_location,
                        climate_day=climate_day,
                        qty=str(fill.cumulative_qty),
                        reason="ambiguous_latch",
                        detail=(
                            f"instrument {instrument_id!r} matches {len(entries)} "
                            "taken latches; the fill cannot be joined unambiguously"
                        ),
                        venue_order_id=fill.venue_order_id,
                        filled_at_ns=fill.ts_event,
                    )
                )
            continue
        if latch_station != city:
            # F1 (b): this instrument's ONE taken latch belongs to another
            # city's invocation of this same shared store. That city's own
            # run takes (or excludes) this fill; silently skipping here --
            # never scoring, never excluding -- is what stops it becoming a
            # false, permanent `no_taken_latch` under THIS city's run.
            continue
        if len(fills) > 1:
            # Slice 4 item B2 (plan rev 6.1): the v3 continuous-rung-hold
            # family has an EXPLICIT signal for which of N fills on one
            # latch is the genuine trial -- the latch's own recorded
            # `venue_order_id` (item A1's writer). When exactly one of the
            # joined fills matches it, that one is admitted normally and
            # every OTHER fill is `duplicate_fill` residual, never
            # `duplicate_fill_for_latch`. Anything else (no venue_order_id
            # on the latch -- a pre-Slice-4 record -- or zero/more-than-one
            # match) falls back to v2's existing "pick none" behaviour
            # unchanged, so a v2 store's byte-identical output is preserved.
            primary_fills = (
                [f for f in fills if f.venue_order_id == latch_venue_order_id]
                if family_prefix.startswith("continuous_rung_hold/") and latch_venue_order_id
                else []
            )
            if len(primary_fills) == 1:
                primary = primary_fills[0]
                for fill in fills:
                    if fill is primary:
                        continue
                    exclusions.append(
                        FillExclusion(
                            trial_id=trial_id,
                            station=cli_location,
                            climate_day=climate_day,
                            qty=str(fill.cumulative_qty),
                            reason="duplicate_fill",
                            detail=(
                                f"a second genuine fill (venue_order_id="
                                f"{fill.venue_order_id!r}) joined latch {trial_id!r}, "
                                f"which already recorded venue_order_id="
                                f"{latch_venue_order_id!r}"
                            ),
                            venue_order_id=fill.venue_order_id,
                            filled_at_ns=fill.ts_event,
                            fill_px=str(fill.cumulative_cost / fill.cumulative_qty),
                            fee=str(fill.cumulative_fee / fill.cumulative_qty),
                        )
                    )
                _admit_one_fill(
                    trials,
                    fee_reconciled_by_trial_id,
                    trial_id=trial_id,
                    climate_day=climate_day,
                    ask=ask,
                    cli_location=cli_location,
                    instrument_id=instrument_id,
                    fill=primary,
                    skip_ask_guard=skip_ask_guard,
                )
                continue
            for fill in fills:
                exclusions.append(
                    FillExclusion(
                        trial_id=trial_id,
                        station=cli_location,
                        climate_day=climate_day,
                        qty=str(fill.cumulative_qty),
                        reason="duplicate_fill_for_latch",
                        detail=(
                            f"{len(fills)} fill records join latch {trial_id!r}; "
                            "none is picked, both stay out of n"
                        ),
                        venue_order_id=fill.venue_order_id,
                        filled_at_ns=fill.ts_event,
                    )
                )
            continue
        _admit_one_fill(
            trials,
            fee_reconciled_by_trial_id,
            trial_id=trial_id,
            climate_day=climate_day,
            ask=ask,
            cli_location=cli_location,
            instrument_id=instrument_id,
            fill=fills[0],
            skip_ask_guard=skip_ask_guard,
        )

    no_side_residual_by_trial_id: dict[str, bool] = {}
    if pending_instrument_id is not None:
        for trial in trials:
            if trial.instrument_id == pending_instrument_id:
                no_side_residual_by_trial_id[trial.trial_id] = True

    return (
        tuple(trials),
        tuple(exclusions),
        fee_reconciled_by_trial_id,
        no_side_residual_by_trial_id,
    )


def _admit_one_fill(
    trials: list[FilledTrial],
    fee_reconciled_by_trial_id: dict[str, tuple[bool, str, bool]],
    *,
    trial_id: str,
    climate_day: str,
    ask: Decimal,
    cli_location: str,
    instrument_id: str,
    fill: DurableFillRecord,
    skip_ask_guard: bool = False,
) -> None:
    """Append `fill` as the one genuine trial for `trial_id` -- shared by
    the single-fill path and Slice 4 item B2's duplicate-fill split.

    `skip_ask_guard` (three-seam Slice 4 review item 3) threads through to
    `fee_reconciled_by_trial_id`'s third element, read by the CLI's
    `_admit_fill` call so a fill-walk-consumed trial's `entry_ask` (derived
    from the fill itself, never a decision) never trips L-25's guard.
    """
    trials.append(
        FilledTrial(
            trial_id=trial_id,
            station=cli_location,
            climate_day=climate_day,
            instrument_id=instrument_id,
            bucket=None,
            fill_px=fill.cumulative_cost / fill.cumulative_qty,
            fee=fill.cumulative_fee / fill.cumulative_qty,
            qty=fill.cumulative_qty,
            filled_at_ns=fill.ts_event,
            entry_ask=ask,
            scheduled_release_at_ns=0,
            venue_settlement_tmax_f=None,
        )
    )
    fee_reconciled_by_trial_id[trial_id] = (
        fill.fee_reconciled, fill.venue_order_id, skip_ask_guard,
    )

