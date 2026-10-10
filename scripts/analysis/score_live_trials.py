"""6c driver: score filled trials against settlement truth, write parquet.

`docs/plans/SCORER_TALLY_BCA_BRIEF_2026-09-04.md` section 6c. Thin glue only
-- all scoring logic lives in `breezy.settlement.trial_scorer` (pure); this
module's only job is I/O: read fills, resolve each fill's rung and
settlement record, score, write.

FILL SOURCE DECISION (stated per the task, since neither the trial latch nor
a live exec client exists yet -- see `trial_scorer.py`'s module docstring):
this driver reads `FilledTrial` inputs from a JSONL file, one object per
line, with exactly `FilledTrial`'s fields (`climate_day` as an ISO date
string, Decimal fields as strings). This is a narrow, explicit placeholder
input reader -- NOT the `OrderFilled` -> `FilledTrial` adapter (that lands
with R-7/R-8) -- and is expected to be replaced wholesale once a real fill
source exists; nothing downstream of `read_filled_trials_jsonl` depends on
its shape.

LIVE FILL SOURCE (`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md`, I2):
`read_filled_trials_state_db` reads real fills straight from the exec
`SqliteStateStore` (`--fill-source`, else `POLYMARKET_US_EXEC_STATE_DB`),
joined to each trial's `current_rung_hold/trial/{station}/{climate_day}`
latch by `instrument_id`. `--fills` (JSONL) and the state-DB source are
mutually exclusive; exactly one is used per invocation. `--family-manifest`
is REQUIRED on both, and supplies `since_climate_day` (`d0_climate_day`) and
`stations` (the positive-control census) for the state-DB source.

Instrument lookup (review item 7): `_read_bucket_facts_by_instrument_id`
reads every instrument definition from the station's catalog via the native,
UNFILTERED `catalog.instruments()` -- per `252918a`'s pinned layout note, a
BinaryOption identifier-filtered query does not see the flat files the
native per-file converter wrote, so this driver never filters by identifier.

Re-score discipline (review item 1): once a trial's LATEST stored row
carries `settlement_basis="venue_last_fair_price_fallback"`, this driver
must not re-score that trial against a later-arriving FINAL -- `_due_for_scoring`
enforces that by skipping any trial whose latest stored score is already a
fallback score.

Re-score-only-on-change (review item 3): before re-scoring a trial against a
resolved `nws_final` record, `_unchanged_since_last_score` compares that
record's `(raw_sha256, revision_seq)` against the latest stored row for the
same `trial_id`; an unchanged pair means the prior run already scored this
exact settlement value, so the trial is skipped and no duplicate row is
appended. A corrected record (different `raw_sha256`/`revision_seq`)
re-scores and appends `score_seq + 1`, same as today.

Malformed input (review item 2): a malformed JSONL row (invalid JSON, a
missing/mistyped field, an unparseable Decimal, a `climate_day` that is not a
real ISO date) never aborts the batch. It is converted to a
`ScoreRefusal(reason="malformed_input")` for that one row/trial and scoring
continues with the rest. `FilledTrial.climate_day` itself stays a plain `str`
(the settlement-package purity guard forbids `datetime` under
`breezy.settlement`); this script is the boundary that validates it really is
an ISO date before the value is ever used to look up a settlement record.

JSONL input schema (review item 7): one `FilledTrial`-shaped JSON object per
line --

    trial_id: str
    station: str                       # e.g. "LAX"
    climate_day: str                   # ISO-8601 date, e.g. "2026-08-31"
    instrument_id: str
    fill_px: str                       # Decimal, e.g. "0.42"
    fee: str                           # Decimal, per-contract entry fee
    qty: str                           # Decimal
    filled_at_ns: int
    entry_ask: str                     # Decimal, decision-time ask
    scheduled_release_at_ns: int
    venue_settlement_tmax_f: int | null   # optional, venue fallback only
    bucket: {                          # optional; omit to resolve via the
        "station": str,                # persisted instrument definition
        "climate_day": str,
        "lower_f": int | null,
        "upper_f": int | null,
    } | null

Example line::

    {"trial_id": "t1", "station": "LAX", "climate_day": "2026-08-31", \
"instrument_id": "LAX-2026-08-31-gte78lt80f", "fill_px": "0.42", "fee": \
"0.01", "qty": "10", "filled_at_ns": 1, "entry_ask": "0.40", \
"scheduled_release_at_ns": 1, "venue_settlement_tmax_f": null, "bucket": null}
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sqlite3
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError
from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.analysis.labeling.instrument_facts import (
    bucket_facts_from_instrument_id as _bucket_facts_from_instrument_id,
)
from breezy.analysis.labeling.instrument_facts import (
    read_bucket_facts_by_instrument_id as _read_bucket_facts_by_instrument_id,
)

# R2.2: definitions live in breezy.analysis.prereg_admission. Bound here so
# script-local calls and `from score_live_trials import ...` keep resolving.
# A monkeypatch of these names on this module still reaches script call sites;
# it does not retarget lookups inside the moved bodies.
from breezy.analysis.prereg_admission import (
    _TICK,  # noqa: F401
    FillExclusion,
    FillSourceUnreadableError,
    StorePositiveControlFailedError,
    _admit_fill,
    _admit_one_fill,  # noqa: F401
    compute_residual,  # noqa: F401
    read_filled_trials_state_db,
)
from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.weather_bucket_facts import (
    Measure,
    WeatherBucketFacts,
)
from breezy.persistence.catalog import open_station_catalog, read_climate_day_including_corrections
from breezy.persistence.family_manifest import FamilyManifestError, load_family_manifest

# Re-exported unchanged (WP-31): `from score_live_trials import RESIDUAL_EXCLUSION_REASONS`.
from breezy.persistence.residual_fills import (  # noqa: F401
    RESIDUAL_EXCLUSION_REASONS,
)
from breezy.persistence.scored_trial_store import read_scored_trials, write_scored_trials
from breezy.registry.settlement_clock import settlement_deadline_ns
from breezy.registry.sites import default_registry
from breezy.runtime.exec_state_db_path import (
    ExecStateDbNotConfiguredError,
    node_store_path_check,
    resolve_store_path,
)
from breezy.settlement.trial_scorer import (
    BucketSource,
    FilledTrial,
    ScoredTrial,
    ScoreRefusal,
    assert_scored_pairs_are_unit_qty,
    score_trials,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    TAKEN_FROM_FILL_WALK_REASON,  # noqa: F401
    TrialDayRecord,
    TrialDayRecordCorrupt,
    trial_id_for,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fill_time_count import _open_readonly  # ONE implementation, reused (I2)

DEFAULT_NWS_CATALOG_BASE: Path = Path.home() / ".local/share/breezy/catalog"
DEFAULT_DERIVED_DIR: Path = Path.home() / ".local/share/breezy/derived/scored_trials"

#: Excluded-fills artefact (I2 3.0(c)/(f)): one JSON object per exclusion,
#: exactly 8 keys, idempotent on `(venue_order_id, reason)`. Lives in
#: `--derived-dir`, alongside the scored-trial store (3.0 (f)).
_EXCLUDED_FILLS_ARTEFACT_NAME = "excluded_fills.jsonl"

#: Unresolved-takes artefact (I4 defect fix, `LIVE_FILL_SCORING_CHAIN_2026-
#: 09-05.md` -- first live order, 2026-09-05 SFO): visibility only, sits
#: beside `excluded_fills.jsonl` in `--derived-dir`. A row here is NEVER
#: scored, counted, or tallied (PREREG v2 rules unchanged) -- it exists
#: solely so a `TrialDayRecord(reason="taken")` with no matching
#: `DurableFillRecord` anywhere in the store is never silently invisible to
#: both `scored_trials` and `excluded_fills.jsonl`.
_UNRESOLVED_TAKES_ARTEFACT_NAME = "unresolved_takes.jsonl"

# The one non-refusal `TrialDayRecord.reason` value. Single source shared
# with `prereg_admission` (R2.2 review M2); never redefine it locally.
from breezy.analysis.fill_time_count import _TAKEN_REASON

#: Duplicated literal (never imported, C10): identical to
#: `breezy.runtime.submit_intent.CURRENT_INTENT_KEY`. This module reads the
#: account-wide submit-intent singleton's raw store value for VISIBILITY
#: only (`find_unresolved_takes`'s `intent_state` sidecar field) through the
#: same generic read-only store access already used for `TrialDayRecord`/
#: `DurableFillRecord` -- it deliberately does not import `submit_intent`
#: (C10's exact-set import pin covers `src`/`scripts`, not this literal).
_CURRENT_INTENT_KEY = "exec/polymarket_us/intent/current"

#: The `SubmitIntent.state` values this module recognizes when it decodes
#: the raw intent JSON itself (mirrors `SubmitIntentState`'s members without
#: importing the enum).
_KNOWN_INTENT_STATES = frozenset({"OPEN", "RETIRED"})

#: Duplicated literal (never imported, C10): the EXEC-PAR slot table's `"v"`.
_SLOT_TABLE_VERSION = 2


class NodeStorePreflightRefused(Exception):
    """`node_store_path_check` returned MISMATCH or DISCOVERY_FAILED
    (REVISE-1/REVISE-4): `self.reason` is `node_store_mismatch` or
    `node_store_discovery_failed`, never the compared path or value."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


#: B1 (v2-only live-provenance sidecar, ruling Q4
#: `docs/evidence/grok_partial_fill_ruling_2026-09-04.md`): the 17-column
#: `ScoredTrial` schema carries no provenance column and never will (v1 is
#: binding/immutable) -- v2's `family_tally_v2.py --store-dir` refusal
#: instead consults this directory-convention sidecar. Values are exactly
#: `{"live", "paper_replay"}`; this driver, the only LIVE writer, writes
#: (once) or asserts (every later run) `"live"` -- a paper-replay code path
#: never writes this file at all, so an unmarked or replay-marked store is
#: refused fail-closed by the v2 CLI, never silently admitted.
_PROVENANCE_SIDECAR_NAME = "provenance.json"
_LIVE_PROVENANCE_VALUE = "live"

#: B3 (v2-only look ordering by fill time): `ScoredTrial` carries no fill
#: timestamp, so this append-only sidecar records `(trial_id, score_seq) ->
#: filled_at_ns` for every fill this driver persists a score for --
#: `family_tally_v2.py` joins against it to order sequential looks
#: chronologically instead of by the `climate_day`/`trial_id` proxy.
_FILL_ORDER_SIDECAR_NAME = "fill_order.jsonl"


class ProvenanceConflict(Exception):
    """`<store_dir>/provenance.json` already declares a non-'live' provenance."""


def _write_or_assert_live_provenance_sidecar(store_dir: Path) -> None:
    """Write `provenance.json = {"provenance": "live"}` the first time this
    store directory is scored into; on every later run, assert the existing
    sidecar still says `"live"` -- refusing loudly (never silently
    overwriting) if it declares anything else (e.g. `"paper_replay"`)."""
    sidecar = store_dir / _PROVENANCE_SIDECAR_NAME
    if sidecar.exists():
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        existing = payload.get("provenance")
        if existing != _LIVE_PROVENANCE_VALUE:
            raise ProvenanceConflict(
                f"{sidecar}: already declares provenance={existing!r}; refusing to "
                f"write/assert {_LIVE_PROVENANCE_VALUE!r} over it"
            )
        return
    store_dir.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps({"provenance": _LIVE_PROVENANCE_VALUE}), encoding="utf-8")


def _append_fill_order_entries(store_dir: Path, entries: Sequence[Mapping[str, Any]]) -> None:
    """Append-only, idempotent for a re-scored `(trial_id, score_seq)`: an
    entry whose `(trial_id, score_seq)` key already exists in the sidecar is
    never duplicated -- so re-running this driver against an already-scored
    trial (review item 3's unchanged-record skip, or a genuine re-score) is
    always safe to call again."""
    path = store_dir / _FILL_ORDER_SIDECAR_NAME
    existing_keys: set[tuple[str, int]] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            existing_keys.add((row["trial_id"], row["score_seq"]))
    new_lines: list[str] = []
    for entry in entries:
        key = (entry["trial_id"], entry["score_seq"])
        if key in existing_keys:
            continue
        existing_keys.add(key)
        new_lines.append(json.dumps(dict(entry)))
    if not new_lines:
        return
    store_dir.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for line in new_lines:
            fh.write(line + "\n")


#: Exceptions a malformed JSONL row or a malformed `FilledTrial` field can
#: raise while being parsed -- review item 2's per-row guard.
_MALFORMED_ROW_ERRORS: tuple[type[Exception], ...] = (
    KeyError,
    ValueError,
    TypeError,
    InvalidOperation,
)


def _validate_qty(trial: FilledTrial) -> ScoreRefusal | None:
    """`qty <= 0` is not a real fill and must never be silently scored or
    silently dropped (ruling Q1: a zero-fill IOC miss "is not a trial at
    all"). Refused loudly through the same `malformed_input` channel a
    malformed JSONL row uses, so it always appears in the printed refusal
    list. Returns `None` when `qty` is usable."""
    if trial.qty <= 0:
        return ScoreRefusal(
            trial_id=trial.trial_id,
            reason="malformed_input",
            detail=f"qty must be positive, got {trial.qty!r}",
        )
    return None


def read_filled_trials_jsonl(
    path: Path,
) -> tuple[tuple[FilledTrial, ...], tuple[ScoreRefusal, ...]]:
    """Read `FilledTrial` records from a JSONL placeholder fill source.

    See the module docstring: this is an explicit stand-in until a real
    `OrderFilled` -> `FilledTrial` adapter lands (R-7/R-8), not the adapter
    itself. A malformed line never aborts the read (review item 2): it is
    converted to a `ScoreRefusal(reason="malformed_input")` and the remaining
    lines are still read.
    """
    trials: list[FilledTrial] = []
    refusals: list[ScoreRefusal] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            refusals.append(
                ScoreRefusal(
                    trial_id=f"<malformed line {line_no}>",
                    reason="malformed_input",
                    detail=f"invalid JSON on line {line_no}: {exc}",
                )
            )
            continue
        try:
            trials.append(_filled_trial_from_json(row))
        except _MALFORMED_ROW_ERRORS as exc:
            trial_id = row.get("trial_id") if isinstance(row, Mapping) else None
            fallback_id = f"<malformed line {line_no}>"
            refusals.append(
                ScoreRefusal(
                    trial_id=str(trial_id) if trial_id is not None else fallback_id,
                    reason="malformed_input",
                    detail=f"malformed FilledTrial on line {line_no}: {exc}",
                )
            )
    return tuple(trials), tuple(refusals)


def _filled_trial_from_json(row: Mapping[str, Any]) -> FilledTrial:
    bucket: WeatherBucketFacts | None = None
    if row.get("bucket") is not None:
        b = row["bucket"]
        bucket = WeatherBucketFacts(
            settlement_station=row["station"],
            climate_day=dt.date.fromisoformat(row["climate_day"]),
            measure=Measure.HIGH,
            lower_f=b.get("lower_f"),
            upper_f=b.get("upper_f"),
        )
    return FilledTrial(
        trial_id=row["trial_id"],
        station=row["station"],
        climate_day=row["climate_day"],
        instrument_id=row["instrument_id"],
        bucket=bucket,
        fill_px=Decimal(row["fill_px"]),
        fee=Decimal(row["fee"]),
        qty=Decimal(row["qty"]),
        filled_at_ns=int(row["filled_at_ns"]),
        entry_ask=Decimal(row["entry_ask"]),
        scheduled_release_at_ns=int(row["scheduled_release_at_ns"]),
        venue_settlement_tmax_f=row.get("venue_settlement_tmax_f"),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class UnresolvedTake:
    """A `TrialDayRecord` latched `reason="taken"` with no matching
    `DurableFillRecord` anywhere in the shared store (I4 defect: first live
    order, 2026-09-05 SFO -- the trial-day latch said TAKEN, the
    account-wide submit intent was OPEN (an ambiguous create-order
    outcome), and no fill record existed at all).

    Reported for VISIBILITY only -- never scored, never counted, never
    tallied; PREREG v2 rules and the six-key counter are untouched by this
    dataclass. `intent_state` is the account-wide
    `exec/polymarket_us/intent/current` singleton's raw JSON `"state"` field
    ("OPEN"/"RETIRED"), read directly off the store value without importing
    `breezy.runtime.submit_intent` (C10), or `"absent"` when the key is
    missing or the value does not decode.
    """

    station: str
    climate_day: str
    trial: str
    ask: str
    intent_state: str


def _decode_intent_state(value: object) -> str:
    """Decode the raw `_CURRENT_INTENT_KEY` store value's `"state"` field
    without importing `breezy.runtime.submit_intent` (C10): parses the same
    JSON shape `SubmitIntent.to_bytes` writes, by hand, and degrades to
    `"absent"` on anything that doesn't decode to a known state -- this is a
    visibility-only sidecar field, never a refusal path (see
    `find_unresolved_takes`)."""
    raw = value.decode("utf-8") if isinstance(value, bytes | bytearray) else value
    if not isinstance(raw, str):
        return "absent"
    try:
        payload: object = json.loads(raw)
    except ValueError:
        return "absent"
    if not isinstance(payload, dict):
        return "absent"
    if payload.get("v") == _SLOT_TABLE_VERSION:
        # An EXEC-PAR v2 table holds only open (or unreadable, hence open)
        # slots and has no top-level "state": it is never "absent".
        return "OPEN"
    state = payload.get("state")
    if isinstance(state, str) and state in _KNOWN_INTENT_STATES:
        return state
    return "absent"


def find_unresolved_takes(
    path: Path,
    *,
    family_prefix: str,
    city: str,
    since_climate_day: str,
) -> tuple[UnresolvedTake, ...]:
    """Every `{family_prefix}{city}/{climate_day}` (v2) or
    `{family_prefix}{city}/{climate_day}/{instrument_id}` (v3,
    instrument-keyed, `trial_day_latch._key`) latch with `reason="taken"`
    (on or after `since_climate_day`) that has no matching
    `DurableFillRecord` anywhere in the store (I4 defect fix). `.trial` is
    the raw key for a v2 (2-part) latch, or the canonical
    `trial_id_for(...)` string for a v3 (3-part) latch -- exactly
    `read_filled_trials_state_db`'s own `trial_id` convention.

    Restricted to THIS run's own `city` (mirrors `read_filled_trials_state_db`'s
    cross-city convention, F1): a shared store's other cities' own taken
    latches are that city's own invocation's to report, never duplicated
    here. Called only from the state-DB path of `score_live_trials`, after
    `read_filled_trials_state_db` has already validated the store opens
    read-only and passes the positive control -- this function repeats that
    open (a second short-lived read-only connection) rather than widening
    the frozen `read_filled_trials_state_db` return signature that 18+
    existing call sites already unpack as a 3-tuple.

    Fail-closed on the SAME latch/fill corruption as
    `read_filled_trials_state_db` (F3): an undecodable `TrialDayRecord` or
    `DurableFillRecord` is store corruption, never a silent skip -- including
    a v3 latch key's instrument-id segment disagreeing with its own
    record's `instrument_id` (compared via `trial_id_for`, mirroring
    `read_filled_trials_state_db` exactly). The account-wide submit-intent
    singleton is the one exception -- it is read-only diagnostic context
    for the sidecar row only, so a missing or undecodable intent record
    degrades to `intent_state="absent"` rather than failing this
    visibility-only reader closed.
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

    taken_latches: list[tuple[str, str, str, Decimal]] = []
    for key, value in rows:
        if not isinstance(key, str) or not key.startswith(family_prefix):
            continue
        parts = key[len(family_prefix) :].split("/")
        # v3 (plan S1, operator ruling 2026-09-14): an instrument-keyed
        # latch key is 3-part (`station/climate_day/instrument_id`, built by
        # `trial_day_latch._key`) -- mirrors `read_filled_trials_state_db`'s
        # own `(2, 3)` widening exactly, so a v3 TAKEN-but-unfilled latch is
        # no longer invisible to this visibility-only census.
        if len(parts) == 2:
            station, climate_day = parts
            key_instrument_id: str | None = None
        elif len(parts) == 3:
            station, climate_day, key_instrument_id = parts
        else:
            continue
        if station != city or climate_day < since_climate_day:
            continue
        try:
            record = TrialDayRecord.from_bytes(value)
        except TrialDayRecordCorrupt as exc:
            raise FillSourceUnreadableError(
                f"a record under the {family_prefix!r} key prefix could not be decoded"
            ) from exc
        if record.reason != _TAKEN_REASON:
            continue
        if key_instrument_id is None:
            trial_id = key
        else:
            # Mirrors `read_filled_trials_state_db`'s own mismatch refusal
            # (F3): the key's instrument-id segment must agree with the
            # decoded record's `instrument_id`, compared through
            # `trial_id_for` (never a raw string compare) so a
            # dotted-vs-bare spelling difference is never mistaken for a
            # genuine disagreement. A real disagreement is store
            # corruption: fail the whole run closed, never a silent join
            # on the wrong identity.
            from_key = trial_id_for(family_prefix, station, climate_day, key_instrument_id)
            from_record = trial_id_for(family_prefix, station, climate_day, record.instrument_id)
            if from_key != from_record:
                raise FillSourceUnreadableError(
                    f"a record under the {family_prefix!r} key prefix has an "
                    "instrument-id key segment that disagrees with its own "
                    "record's instrument_id"
                )
            trial_id = from_record
        taken_latches.append((trial_id, climate_day, record.instrument_id, record.ask))

    if not taken_latches:
        return ()

    filled_instrument_ids: set[str] = set()
    for key, value in rows:
        if not isinstance(key, str) or not key.startswith(FILL_KEY_PREFIX):
            continue
        try:
            fill = DurableFillRecord.from_bytes(value)
        except ExecutionReportMappingError as exc:
            raise FillSourceUnreadableError(
                f"a record under the {FILL_KEY_PREFIX!r} key prefix could not be decoded"
            ) from exc
        filled_instrument_ids.add(fill.instrument_id)

    intent_state = "absent"
    for key, value in rows:
        if key != _CURRENT_INTENT_KEY:
            continue
        intent_state = _decode_intent_state(value)
        break

    return tuple(
        UnresolvedTake(
            station=city,
            climate_day=climate_day,
            trial=latch_key,
            ask=str(ask),
            intent_state=intent_state,
        )
        for latch_key, climate_day, instrument_id, ask in taken_latches
        if instrument_id not in filled_instrument_ids
    )


def _with_scheduled_release_at_ns(trial: FilledTrial, *, venue: str, city: str) -> FilledTrial:
    """Replace the reader's placeholder `scheduled_release_at_ns` with the
    venue's real settlement instant for `trial.climate_day` -- `climate_day +
    1` at the venue's settlement wall-clock, via the promoted
    `breezy.registry.settlement_clock.settlement_deadline_ns` helper (never
    midnight UTC, never a second copy of the arithmetic `nws_actor.py` also
    uses). Runs as a driver-level step because `read_filled_trials_state_db`
    takes no `venue` -- its signature is frozen (Stage-0) -- and `venue` and
    `city` are both already in hand here.
    """
    deadline = default_registry().settlement_deadline(venue, city)
    climate_day = dt.date.fromisoformat(trial.climate_day)
    release_ns = settlement_deadline_ns(deadline, climate_day)
    return FilledTrial(
        trial_id=trial.trial_id,
        station=trial.station,
        climate_day=trial.climate_day,
        instrument_id=trial.instrument_id,
        bucket=trial.bucket,
        fill_px=trial.fill_px,
        fee=trial.fee,
        qty=trial.qty,
        filled_at_ns=trial.filled_at_ns,
        entry_ask=trial.entry_ask,
        scheduled_release_at_ns=release_ns,
        venue_settlement_tmax_f=trial.venue_settlement_tmax_f,
    )


def _latest_stored_row(derived_dir: Path, trial_id: str) -> ScoredTrial | None:
    """The highest-`score_seq` stored row for `trial_id`, or `None` if none
    has ever been scored."""
    latest: ScoredTrial | None = None
    for row in read_scored_trials(derived_dir):
        if row.trial_id == trial_id and (latest is None or row.score_seq > latest.score_seq):
            latest = row
    return latest


def _already_fallback_scored(derived_dir: Path, trial_id: str) -> bool:
    latest = _latest_stored_row(derived_dir, trial_id)
    return latest is not None and latest.settlement_basis == "venue_last_fair_price_fallback"


def _next_score_seq(derived_dir: Path, trial_id: str) -> int:
    latest = _latest_stored_row(derived_dir, trial_id)
    return 0 if latest is None else latest.score_seq + 1


def _unchanged_since_last_score(
    derived_dir: Path, trial_id: str, record: NwsClimateDay | None
) -> bool:
    """Review item 3: skip re-scoring an `nws_final` row when the resolved
    record's `(raw_sha256, revision_seq)` matches the latest stored row for
    `trial_id`. A `None` record, or a latest row that is not itself
    `nws_final`, is never "unchanged" -- only a genuine repeat of the same
    settlement value is."""
    if record is None:
        return False
    latest = _latest_stored_row(derived_dir, trial_id)
    if latest is None or latest.settlement_basis != "nws_final":
        return False
    return latest.raw_sha256 == record.raw_sha256 and latest.revision_seq == record.revision_seq


def score_live_trials(
    *,
    fills_path: Path | None = None,
    fill_source_path: Path | None = None,
    family_prefix: str | None = None,
    since_climate_day: str | None = None,
    until_climate_day: str | None = None,
    stations: Sequence[str] | None = None,
    catalog_base: Path,
    venue: str,
    city: str,
    derived_dir: Path,
    now_ns: int,
    proc_root: Path = Path("/proc"),
) -> tuple[tuple[ScoredTrial, ...], tuple[ScoreRefusal, ...], tuple[FillExclusion, ...]]:
    """Read fills, join to settlement truth, score, and write the parquet run.

    Exactly one fill source: `fills_path` (JSONL fixture/replay) or
    `fill_source_path` (the live exec state DB, I2) -- the caller (`main`)
    enforces that exclusivity and resolves `fill_source_path` from
    `--fill-source` or `POLYMARKET_US_EXEC_STATE_DB` when omitted. When
    reading from the state DB, `family_prefix`/`since_climate_day`/`stations`
    (from the required `--family-manifest`) are also required.

    State-DB path only: runs the REVISE-1 node-env pre-flight first
    (`node_store_path_check`, `proc_root` injectable for tests) -- MISMATCH
    or DISCOVERY_FAILED raises `NodeStorePreflightRefused`; NO_NODE warns
    once and continues (schedule premise, NOTE-8); MATCH continues silently.
    Then `read_filled_trials_state_db` (BLOCK-1.2's positive control, BLOCK-3's
    join exclusions) and `_with_scheduled_release_at_ns` (the venue's real
    settlement instant, never midnight UTC) run before the shared join below.

    The partial-fill admission gate (ruling Q1, widened by L-25/I2) runs
    first, between reading fills and scoring: `qty <= 0` becomes a loud
    `malformed_input` refusal; `qty != 1`, `fill_px < entry_ask - tick` or
    `fee_reconciled is False` becomes a `FillExclusion`, reported separately
    and never passed to `score_trial`.
    """
    reader_exclusions: tuple[FillExclusion, ...] = ()
    fee_reconciled_by_trial_id: Mapping[str, tuple[bool, str, bool]] = {}
    no_side_residual_by_trial_id: Mapping[str, bool] = {}
    unresolved_takes: tuple[UnresolvedTake, ...] = ()

    if fills_path is not None:
        filled_trials, jsonl_refusals = read_filled_trials_jsonl(fills_path)
    else:
        missing_state_db_args = (
            fill_source_path is None
            or family_prefix is None
            or since_climate_day is None
            or stations is None
        )
        if missing_state_db_args:
            raise ValueError(
                "fill_source_path, family_prefix, since_climate_day and stations "
                "are all required when fills_path is not given"
            )
        preflight = node_store_path_check(fill_source_path, proc_root=proc_root)
        if preflight == "MISMATCH":
            raise NodeStorePreflightRefused("node_store_mismatch")
        elif preflight == "DISCOVERY_FAILED":
            raise NodeStorePreflightRefused("node_store_discovery_failed")
        elif preflight == "NO_NODE":
            logging.getLogger(__name__).warning(
                "no anchored breezy-trade node found while checking the "
                "fill-source store binding; continuing (schedule premise, NOTE-8)"
            )
        elif preflight == "MATCH":
            pass  # continues silently, per the module docstring
        else:
            # F2: `node_store_path_check`'s declared return type is the
            # closed `NodeStorePathCheckResult` enum, but this is a runtime
            # boundary crossing a module import, not a type-checked call --
            # an unexpected token must fail closed rather than silently fall
            # through as MATCH. Never the actual token (value-free, A5).
            raise NodeStorePreflightRefused("node_store_preflight_unknown_result")
        cli_location = default_registry().settlement_site(venue, city).cli_location
        (
            raw_trials,
            reader_exclusions,
            fee_reconciled_by_trial_id,
            no_side_residual_by_trial_id,
        ) = read_filled_trials_state_db(
            fill_source_path,
            family_prefix=family_prefix,
            city=city,
            cli_location=cli_location,
            since_climate_day=since_climate_day,
            until_climate_day=until_climate_day,
            stations=stations,
        )
        filled_trials = tuple(
            _with_scheduled_release_at_ns(trial, venue=venue, city=city) for trial in raw_trials
        )
        jsonl_refusals = ()
        # I4 defect fix: visibility only -- never scored, counted, or
        # tallied. Logged once per unresolved trial, then appended to the
        # `unresolved_takes.jsonl` sidecar below, alongside `excluded_fills`.
        # The asserts below are pure type-narrowing (mirroring
        # `missing_state_db_args` above, which already proved these
        # non-None at runtime) -- never a new runtime behaviour.
        assert fill_source_path is not None
        assert family_prefix is not None
        assert since_climate_day is not None
        unresolved_takes = find_unresolved_takes(
            fill_source_path,
            family_prefix=family_prefix,
            city=city,
            since_climate_day=since_climate_day,
        )
        for take in unresolved_takes:
            logging.getLogger(__name__).warning(
                "UNRESOLVED TAKE: %s %s intent=%s — not scored, not tallied; "
                "resolve via breezy-clear-submit-intent",
                take.station,
                take.climate_day,
                take.intent_state,
            )

    bucket_by_instrument = _read_bucket_facts_by_instrument_id(catalog_base, venue=venue, city=city)
    catalog = open_station_catalog(catalog_base, venue, city)

    pairs: list[tuple[FilledTrial, NwsClimateDay | None]] = []
    extra_refusals: list[ScoreRefusal] = list(jsonl_refusals)
    excluded_fills: list[FillExclusion] = list(reader_exclusions)
    #: Set only for a trial resolved via `_bucket_facts_from_instrument_id`
    #: (the catalog default is the `ScoredTrial.bucket_source` field's own
    #: default, applied by the re-stamping step below) -- read back there so
    #: the tally can see, per row, which source supplied the rung.
    bucket_source_by_trial_id: dict[str, BucketSource] = {}
    for trial in filled_trials:
        malformed_qty = _validate_qty(trial)
        if malformed_qty is not None:
            extra_refusals.append(malformed_qty)
            continue
        fee_reconciled, venue_order_id, skip_ask_guard = fee_reconciled_by_trial_id.get(
            trial.trial_id,
            (True, "", False),
        )
        no_side_residual = no_side_residual_by_trial_id.get(trial.trial_id, False)
        exclusion = _admit_fill(
            trial,
            fee_reconciled=fee_reconciled,
            venue_order_id=venue_order_id,
            skip_ask_guard=skip_ask_guard,
            no_side_residual=no_side_residual,
        )
        if exclusion is not None:
            excluded_fills.append(exclusion)
            continue
        if _already_fallback_scored(derived_dir, trial.trial_id):
            continue
        resolved_bucket: WeatherBucketFacts | None = trial.bucket
        if resolved_bucket is None:
            resolved_bucket = bucket_by_instrument.get(trial.instrument_id)
            if resolved_bucket is None:
                # Catalog absence: fall back to deriving the rung straight
                # from the instrument id's own slug grammar (measured
                # 2026-09-16, ING-1) before refusing. Only THIS trial's
                # provenance is marked "slug" -- a sibling trial that
                # resolved from the catalog stays "catalog".
                resolved_bucket = _bucket_facts_from_instrument_id(trial.instrument_id)
                if resolved_bucket is not None:
                    bucket_source_by_trial_id[trial.trial_id] = "slug"
            if resolved_bucket is None:
                extra_refusals.append(
                    ScoreRefusal(
                        trial_id=trial.trial_id,
                        reason="instrument_unavailable",
                        detail=f"no persisted instrument definition for {trial.instrument_id!r}",
                    )
                )
                continue
        resolved_trial = trial
        if trial.bucket is None:
            resolved_trial = FilledTrial(
                trial_id=trial.trial_id,
                station=trial.station,
                climate_day=trial.climate_day,
                instrument_id=trial.instrument_id,
                bucket=resolved_bucket,
                fill_px=trial.fill_px,
                fee=trial.fee,
                qty=trial.qty,
                filled_at_ns=trial.filled_at_ns,
                entry_ask=trial.entry_ask,
                scheduled_release_at_ns=trial.scheduled_release_at_ns,
                venue_settlement_tmax_f=trial.venue_settlement_tmax_f,
            )
        try:
            climate_day = dt.date.fromisoformat(trial.climate_day)
        except ValueError as exc:
            extra_refusals.append(
                ScoreRefusal(
                    trial_id=trial.trial_id,
                    reason="malformed_input",
                    detail=f"climate_day {trial.climate_day!r} is not a valid ISO date: {exc}",
                )
            )
            continue
        record = read_climate_day_including_corrections(
            catalog, station=trial.station, climate_day=climate_day
        )
        if _unchanged_since_last_score(derived_dir, trial.trial_id, record):
            continue
        pairs.append((resolved_trial, record))

    filled_at_ns_by_trial_id = {trial.trial_id: trial.filled_at_ns for trial, _record in pairs}

    # FU-3d AC1a: fail-closed before any scored-store write -- a regressed
    # admission gate that let a qty!=1 fill reach here must refuse the whole
    # run, never persist a parquet row, fill-order entry or provenance
    # sidecar for it.
    assert_scored_pairs_are_unit_qty(pairs)
    scored, refused = score_trials(pairs, now_ns=now_ns)
    refused = refused + tuple(extra_refusals)

    stamped_scored = tuple(
        ScoredTrial(
            trial_id=row.trial_id,
            station=row.station,
            climate_day=row.climate_day,
            instrument_id=row.instrument_id,
            settlement_tmax_f=row.settlement_tmax_f,
            held=row.held,
            pnl=row.pnl,
            revision_seq=row.revision_seq,
            raw_sha256=row.raw_sha256,
            scored_at_ns=row.scored_at_ns,
            score_seq=_next_score_seq(derived_dir, row.trial_id),
            settlement_basis=row.settlement_basis,
            excluded_reason=row.excluded_reason,
            slippage=row.slippage,
            entry_ask=row.entry_ask,
            fill_px=row.fill_px,
            fee=row.fee,
            bucket_source=bucket_source_by_trial_id.get(row.trial_id, "catalog"),
        )
        for row in scored
    )
    # R2(a): write/assert the live-provenance sidecar every time this
    # driver runs against its derived store, even with zero admitted rows
    # -- a fresh live node with no fills yet must not make family_tally_v2.py
    # refuse the nightly tally for want of a sidecar (idempotent; a genuine
    # provenance conflict still refuses regardless of row count).
    _write_or_assert_live_provenance_sidecar(derived_dir)
    if stamped_scored:
        _append_fill_order_entries(
            derived_dir,
            [
                {
                    "trial_id": row.trial_id,
                    "score_seq": row.score_seq,
                    "filled_at_ns": filled_at_ns_by_trial_id[row.trial_id],
                }
                for row in stamped_scored
            ],
        )
        write_scored_trials(derived_dir, stamped_scored, now_ns=now_ns)
    # I4 defect fix: written unconditionally (idempotent, empty-safe, mirrors
    # `_write_or_assert_live_provenance_sidecar` above) so an unresolved take
    # is visible from THIS run, never deferred to `main()`'s separate
    # `excluded_fills.jsonl` write site -- `unresolved_takes` has no
    # `FillExclusion`-shaped identity (no venue_order_id at all: there is no
    # fill), so it is never folded into that artefact or its reason enum.
    _append_unresolved_takes(derived_dir, unresolved_takes, scored_run_utc=_scored_run_utc(now_ns))
    return stamped_scored, refused, tuple(excluded_fills)


def _append_excluded_fills(
    derived_dir: Path, exclusions: Sequence[FillExclusion], *, scored_run_utc: str
) -> None:
    """Append-only, idempotent on `(venue_order_id, reason)` (I2 3.0(c)).

    `main()` is the SOLE appender (BLOCK-3): `score_live_trials()` returns
    ONE merged exclusion tuple (the reader's join exclusions plus
    `_admit_fill`'s), and this is the ONE write site for it.

    F2 (security review of 5cd169a): the read-back of this artefact's OWN
    prior content, used only to build the idempotence set, must never crash
    this run -- a truncated trailing line left by a killed prior append is
    expected, not exceptional. A line that fails `json.loads` or lacks the
    `venue_order_id`/`reason` keys is skipped for the idempotence set and
    logged once per malformed line, naming only the artefact path and the
    1-based line number (never the line's content). The file is NEVER
    rewritten -- the malformed line is left exactly as found. If the file's
    existing content does not end with `\n` (the truncation case), a
    leading `\n` is written before any new line so the next append never
    concatenates onto a partial line.
    """
    if not exclusions:
        return
    path = derived_dir / _EXCLUDED_FILLS_ARTEFACT_NAME
    existing_keys: set[tuple[str, str]] = set()
    needs_leading_newline = False
    if path.exists():
        text = path.read_text(encoding="utf-8")
        needs_leading_newline = bool(text) and not text.endswith("\n")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                key = (row["venue_order_id"], row["reason"])
            except (json.JSONDecodeError, KeyError, TypeError):
                logging.getLogger(__name__).warning(
                    "%s: line %d is malformed and was skipped for the "
                    "idempotence set; the file is never rewritten",
                    path,
                    lineno,
                )
                continue
            existing_keys.add(key)
    new_lines: list[str] = []
    for fill in exclusions:
        key = (fill.venue_order_id, fill.reason)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        new_lines.append(
            json.dumps(
                {
                    "trial_id": fill.trial_id,
                    "station": fill.station,
                    "climate_day": fill.climate_day,
                    "venue_order_id": fill.venue_order_id,
                    "qty": fill.qty,
                    "reason": fill.reason,
                    "filled_at_ns": fill.filled_at_ns,
                    "scored_run_utc": scored_run_utc,
                }
            )
        )
    if not new_lines:
        return
    derived_dir.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        if needs_leading_newline:
            fh.write("\n")
        for line in new_lines:
            fh.write(line + "\n")


def _append_unresolved_takes(
    derived_dir: Path, unresolved: Sequence[UnresolvedTake], *, scored_run_utc: str
) -> None:
    """Append-only, idempotent on `(trial, intent_state)` (I4 defect fix).

    Mirrors `_append_excluded_fills`'s idempotence/never-rewrite/truncation
    handling exactly, over a SEPARATE artefact
    (`unresolved_takes.jsonl`) -- an unresolved take has no
    `FillExclusion`-shaped identity (there is no fill, so no
    `venue_order_id`), and `FillExclusionReason` is a closed set never
    extended ad hoc, so this is a new sidecar rather than a new member of
    that enum. `score_live_trials` is the sole appender. VISIBILITY ONLY:
    never read by scoring or tally logic anywhere in this module.
    """
    if not unresolved:
        return
    path = derived_dir / _UNRESOLVED_TAKES_ARTEFACT_NAME
    existing_keys: set[tuple[str, str]] = set()
    needs_leading_newline = False
    if path.exists():
        text = path.read_text(encoding="utf-8")
        needs_leading_newline = bool(text) and not text.endswith("\n")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                key = (row["trial"], row["intent_state"])
            except (json.JSONDecodeError, KeyError, TypeError):
                logging.getLogger(__name__).warning(
                    "%s: line %d is malformed and was skipped for the "
                    "idempotence set; the file is never rewritten",
                    path,
                    lineno,
                )
                continue
            existing_keys.add(key)
    new_lines: list[str] = []
    for take in unresolved:
        key = (take.trial, take.intent_state)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        new_lines.append(
            json.dumps(
                {
                    "station": take.station,
                    "climate_day": take.climate_day,
                    "trial": take.trial,
                    "ask": take.ask,
                    "intent_state": take.intent_state,
                    "scored_run_utc": scored_run_utc,
                }
            )
        )
    if not new_lines:
        return
    derived_dir.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        if needs_leading_newline:
            fh.write("\n")
        for line in new_lines:
            fh.write(line + "\n")


def _scored_run_utc(now_ns: int) -> str:
    """The `scored_run_utc` stamp shared by `excluded_fills.jsonl` and
    `unresolved_takes.jsonl` -- ONE implementation, never a second copy of
    the formatting."""
    return dt.datetime.fromtimestamp(now_ns / 1_000_000_000, tz=dt.UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fills", type=Path, default=None, help="JSONL FilledTrial input path (fixture/replay)"
    )
    parser.add_argument(
        "--fill-source",
        type=Path,
        default=None,
        dest="fill_source",
        help="state-DB fill source path; else POLYMARKET_US_EXEC_STATE_DB",
    )
    parser.add_argument(
        "--family-manifest",
        type=Path,
        required=True,
        dest="family_manifest",
        help="strict family manifest (REGISTERED, no draft) -- required on both sources",
    )
    parser.add_argument("--venue", type=str, default="polymarket_us")
    parser.add_argument("--city", type=str, required=True)
    parser.add_argument("--catalog-base", type=Path, default=DEFAULT_NWS_CATALOG_BASE)
    parser.add_argument("--derived-dir", type=Path, default=DEFAULT_DERIVED_DIR)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, proc_root: Path = Path("/proc")) -> int:
    """`proc_root` is a keyword-only test seam (never a CLI flag, mirroring
    `breezy.runtime.exec_state_db_path.main`'s own parameter): production
    always scans the real `/proc`."""
    args = _parse_args(argv)
    log = logging.getLogger(__name__)

    if args.fills is not None and args.fill_source is not None:
        print(
            "score_live_trials: --fills and --fill-source are mutually exclusive",
            file=sys.stderr,
        )
        return 1

    try:
        manifest = load_family_manifest(args.family_manifest)
    except (FamilyManifestError, OSError) as exc:
        print(
            f"score_live_trials: could not load --family-manifest: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1

    fill_source_path: Path | None = None
    family_prefix: str | None = None
    since_climate_day: str | None = None
    until_climate_day: str | None = None
    stations: tuple[str, ...] | None = None
    if args.fills is None:
        if args.fill_source is not None:
            fill_source_path = args.fill_source
        else:
            try:
                fill_source_path = resolve_store_path(os.environ)
            except ExecStateDbNotConfiguredError as exc:
                print(f"score_live_trials: {exc}", file=sys.stderr)
                return 1
        # NOTE-3: the ONE rule for path logging -- a repo-pinned, non-secret
        # filesystem literal, logged exactly once per invocation. Never the
        # node-env pre-flight's compared values (those stay enum-only).
        log.info("resolved fill-source path: %s", fill_source_path)
        family_prefix = manifest.trial_id_prefix
        since_climate_day = manifest.d0_climate_day
        until_climate_day = manifest.terminal_climate_day
        stations = manifest.stations

    now_ns = time.time_ns()
    try:
        scored, refused, excluded = score_live_trials(
            fills_path=args.fills,
            fill_source_path=fill_source_path,
            family_prefix=family_prefix,
            since_climate_day=since_climate_day,
            until_climate_day=until_climate_day,
            stations=stations,
            catalog_base=args.catalog_base,
            venue=args.venue,
            city=args.city,
            derived_dir=args.derived_dir,
            now_ns=now_ns,
            proc_root=proc_root,
        )
    except (
        FillSourceUnreadableError,
        StorePositiveControlFailedError,
        NodeStorePreflightRefused,
    ) as exc:
        print(f"score_live_trials: refused: {exc}", file=sys.stderr)
        return 1

    print(
        f"scored {len(scored)} trial(s), refused {len(refused)} trial(s), "
        f"excluded {len(excluded)} fill(s)"
    )
    for refusal in refused:
        print(f"  refused {refusal.trial_id}: {refusal.reason} -- {refusal.detail}")
    if excluded:
        print("excluded fills (admitted-but-excluded before scoring, ruling Q1):")
        for fill in excluded:
            print(
                f"  excluded {fill.trial_id}: {fill.reason} qty={fill.qty} "
                f"station={fill.station} climate_day={fill.climate_day} -- {fill.detail}"
            )
    _append_excluded_fills(args.derived_dir, excluded, scored_run_utc=_scored_run_utc(now_ns))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
