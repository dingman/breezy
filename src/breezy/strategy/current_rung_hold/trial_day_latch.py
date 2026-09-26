"""Trial-day latch for ``current_rung_hold``, over the SAME store as R-7's
submit-intent latch (``breezy.runtime.submit_intent``).

Why this is not a second store, a second flock, or a second opener
--------------------------------------------------------------------

``current_rung_hold``'s trial rule is: at most ONE trial per station-day.
The natural place to persist that is a durable, restart-surviving latch --
exactly the shape ``breezy.runtime.submit_intent.SubmitIntentLatch`` already
is. The peer-reviewed blueprint
(``docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md``, "Contradiction
resolved -- latch store: FOLD") rejected keeping these as two independent
SQLite files with two independent flocks: two locks leave crash windows that
do not align, so this module is a THIN API over the ONE store and ONE flock
an already-opened ``SubmitIntentLatch`` holds. :class:`TrialDayLatch` is
constructed only by :func:`open_trial_day_latch`, which takes that opened
latch and binds through its ``shared_state_binding()`` accessor -- never a
raw store path, never a second ``open_submit_intent_latch`` call. Every
public method here asserts the SAME flock is still held, mirroring
``SubmitIntentLatch``'s own ``_require_held`` (L-22: exclusion is
unforgeable, not offered).

Keys live in the namespace ``{key_prefix}{station}/{climate_day}``. The
default ``key_prefix`` is ``current_rung_hold/trial/`` -- byte-identical to
the v2 live family. A sibling family (continuous-rung-hold) passes
``continuous_rung_hold/trial/``. Both are disjoint from
``breezy.runtime.submit_intent.CURRENT_INTENT_KEY`` and its
``exec/polymarket_us/intent/...`` history keys, so both latches share one
SQLite file without key collision.

IN_FLIGHT is a **separate clearable key** in this same primitive (L-22),
keyed ``(station, climate_day)``, under ``{family}/inflight/{station}/{day}``
derived from the trial prefix. v2 never writes it.

Ordering rule (binding, peer review "Ordering rule (security, binding)")
--------------------------------------------------------------------------

``TrialDayLatch.consume`` MUST durably commit (the underlying
``SqliteStateStore.set`` call returns, which itself ``COMMIT``\\ s before
returning) STRICTLY BEFORE ``SubmitIntentLatch.arm()`` is called; ``arm()``
precedes the POST; the POST precedes ``retire()``. On restart, the trial
latch is authoritative for "may this station-day be evaluated again" --
checked first, unconditionally, before the submit-intent latch's own
``reconcile_at_startup`` (which answers a different question: "does an
in-flight order need reconciliation"). A consumed trial day with no intent
record is SAFE -- a lost trial, excluded from the day's tally, but no order
was ever sent. An OPEN intent with no trial-day record is the FORBIDDEN
state this ordering makes unreachable: nothing may call ``arm()`` before its
``consume()`` has already durably committed.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Final

from nautilus_trader.model.identifiers import InstrumentId, Symbol

from breezy.adapters.polymarket_us.exec.client import (
    BUDGET_EXHAUSTED_KEY_PREFIX,
    FILL_INDEX_KEY_PREFIX,
    FILL_KEY_PREFIX,
    STARTUP_OPEN_ORDERS_PRESENT_REASON,
    DurableFillRecord,
)
from breezy.adapters.polymarket_us.symbology import (
    POLYMARKET_US_VENUE,
    leg_of,
    sibling_instrument_id,
)
from breezy.runtime.submit_intent import (
    StateStore,
    SubmitIntent,
    SubmitIntentLatch,
    SubmitIntentLockNotHeld,
    _HeldSubmitIntentLock,
)
from breezy.strategy.current_rung_hold.decision import REFUSAL_REASONS

__all__ = [
    "ATTEMPT_COUNTER_KEY_PREFIX",
    "CONTINUOUS_TRIAL_KEY_PREFIX",
    "DEFAULT_TRIAL_KEY_PREFIX",
    "DUPLICATE_FILL_KEY_PREFIX",
    "FAMILY_HALT_KEY",
    "HALT_CLEARED_KEY_PREFIX",
    "LATCH_GATE_REFUSAL_REASONS",
    "NO_SIDE_FIRST_ORDER_PENDING_REASON",
    "SIBLING_LEG_TRADED_REASON",
    "STARTUP_EVIDENCE_KEY",
    "STARTUP_OPEN_ORDERS_PRESENT_REASON",
    "STATION_DAY_ADMISSION_REASON",
    "TAKEN_FROM_FILL_WALK_REASON",
    "Refusal",
    "TrialDayAlreadyConsumed",
    "TrialDayInvalidReason",
    "TrialDayLatch",
    "TrialDayLatchError",
    "TrialDayRecord",
    "TrialDayRecordCorrupt",
    "decode_family_halt",
    "open_trial_day_latch",
    "refuse_if_sibling_leg_traded",
    "startup_evidence_confirms_absent_flat",
    "startup_evidence_lists_slug",
    "startup_evidence_permits_arm",
    "startup_evidence_position_for",
    "startup_evidence_refusal_reason",
    "station_day_admission",
    "trial_id_for",
]

#: Default trial-key prefix -- byte-identical to the v2 live family.
DEFAULT_TRIAL_KEY_PREFIX: Final[str] = "current_rung_hold/trial/"
#: v3 continuous-rung-hold family prefix. Disjoint from the v2 default.
CONTINUOUS_TRIAL_KEY_PREFIX: Final[str] = "continuous_rung_hold/trial/"
_TRIAL_SUFFIX: Final[str] = "trial/"
_INFLIGHT_SUFFIX: Final[str] = "inflight/"
_INFLIGHT_OPEN: Final[bytes] = b'{"v":1,"state":"open"}'
_INFLIGHT_CLEARED: Final[bytes] = b'{"v":1,"state":"cleared"}'

#: The closed set of trial-day outcomes: every `decision.py` refusal reason
#: (`REFUSAL_REASONS`) the caller might record verbatim, plus `"taken"` for
#: a `Take`. Widening this set is a schema change to every already-written
#: record, so it is intentionally not exposed as a public constant callers
#: are invited to extend independently -- it derives from `REFUSAL_REASONS`
#: itself rather than duplicating it, so the two can never silently drift.
#:
#: There used to be a bare, collapsed `"not_taken"` outcome here. It had
#: zero production callers (no wiring site exists yet -- `strategy.py`,
#: build order step 6, is not built) and would have thrown away exactly the
#: fact an operator dashboard needs: WHICH `decision.py` rule refused the
#: trial. Recording the real reason string instead is the more honest
#: mapping, not a narrower one -- every `not_taken` caller this latch ever
#: had is still representable, now with the actual reason preserved.
#: Review item 3 (three-seam Slice 4 review): the never-arm fill walk
#: (`ContinuousRungHoldStrategy._consume_trial_from_fill_record`) has no
#: decision-time ask to record -- distinct from `"taken"` so the scorer's
#: L-25 `fill_below_ask` guard (`score_live_trials.py::_admit_fill`) can
#: skip it BY REASON, never by an ask value that would make the guard inert.
TAKEN_FROM_FILL_WALK_REASON: Final[str] = "taken_from_fill_walk"
_REASONS: Final[frozenset[str]] = frozenset(
    REFUSAL_REASONS | {"taken", TAKEN_FROM_FILL_WALK_REASON}
)
_SCHEMA_VERSION: Final[int] = 1

#: The closed set of ``TrialDayRecord.exit_reason`` values (INC-E3, PREREG
#: v4 §3b) -- the two registered exit rules, mirroring
#: ``exit_authorization.ExitRule``'s own two members. Declared locally
#: (never imported from ``exit_authorization.py``) for the same layering
#: reason that module gives for declaring its own ``Leg`` locally: this
#: module never imports the ``strategy``-layer exit types, only ever
#: receives their ``.value`` strings from the caller.
_EXIT_REASONS: Final[frozenset[str]] = frozenset({"R_THREAT", "R_DEAD"})

#: A ``TrialDayRecord.reason`` counting as "this leg actually traded" for
#: the two S4 gates below (plan NO_SIDE_EDGE_2026-09-14, N2-10/R3-7) --
#: ``"taken"`` and the never-arm fill walk's own reason. A record whose
#: reason is any OTHER member of ``_REASONS`` was merely EVALUATED and
#: refused, never filled, and must not count.
_FILLED_REASONS: Final[frozenset[str]] = frozenset({"taken", TAKEN_FROM_FILL_WALK_REASON})

#: N2-10: a same-rung YES/NO fill on the SAME instrument-day (the sibling
#: leg, `breezy.adapters.polymarket_us.symbology.sibling_instrument_id`,
#: already has a filled TRIAL record). Distinct from
#: `decision.REFUSAL_REASONS` -- `decision.py` is immutable per this
#: slice's hard invariants, and this gate runs before a quote ever reaches
#: `evaluate_decision`.
SIBLING_LEG_TRADED_REASON: Final[str] = "sibling_leg_traded"

#: R3-7: the arm-time Sigma-q admission gate -- summing `q_i` (`BE_i` for a
#: YES leg, `1 - BE_i` for a NO leg) over the station-day's existing filled
#: TRIAL records plus the candidate exceeds 1. Same name as
#: `breezy.settlement.current_rung_hold_v2.StationDayAdmissionRefusal`'s
#: TALLY-time defence-in-depth check (R3-7: "the tally gate stays as
#: defence in depth and must never fire on a day the arm-time gate
#: admitted") -- deliberately the SAME reason string for the SAME
#: violation, at an earlier point in time.
STATION_DAY_ADMISSION_REASON: Final[str] = "station_day_admission"

#: NO-SIDE S5 (E3-6/E4-6): the bounded first-order containment window
#: (PREREG amendment §8) -- while `NO_SIDE_FIRST_LIVE_ORDER_KEY` exists and
#: `NO_SIDE_POSITION_SHAPE_CAPTURED_KEY` does not, the strategy refuses to
#: ARM any further NO take account-wide. Distinct from
#: `decision.REFUSAL_REASONS` for the same reason as the two reasons above.
NO_SIDE_FIRST_ORDER_PENDING_REASON: Final[str] = "no_side_first_order_pending"

#: The closed set of reasons the two functions below (`Refusal`) may use.
#: Fixed and finite by construction, mirroring `decision.REFUSAL_REASONS`
#: and `risk.COUNTED_REFUSAL_REASONS` -- but a SEPARATE set, since
#: `decision.py` must stay untouched (hard invariant) and neither gate has
#: an analogue there.
#:
#: WIDENED (NO-SIDE S5, E3-6/E4-6), never relaxed (L-12): adds
#: `NO_SIDE_FIRST_ORDER_PENDING_REASON`, which is not raised via `Refusal`
#: (no gate function below constructs one for it yet) -- it lives here
#: because it is the closed set every OTHER NO-side latch-level gate reason
#: also lives in, per the plan's own instruction.
LATCH_GATE_REFUSAL_REASONS: Final[frozenset[str]] = frozenset(
    {SIBLING_LEG_TRADED_REASON, STATION_DAY_ADMISSION_REASON, NO_SIDE_FIRST_ORDER_PENDING_REASON}
)


@dataclass(frozen=True, slots=True)
class Refusal:
    """A refusal from one of the S4 latch-level gates below. ``reason`` is
    always a member of :data:`LATCH_GATE_REFUSAL_REASONS` -- never a
    ``decision.Refuse`` (that type validates against
    ``decision.REFUSAL_REASONS``, which these two reasons are not in)."""

    reason: str

    def __post_init__(self) -> None:
        if self.reason not in LATCH_GATE_REFUSAL_REASONS:
            raise ValueError(
                f"reason must be one of {sorted(LATCH_GATE_REFUSAL_REASONS)!r}, "
                f"was {self.reason!r}"
            )


def _leg_instrument_id(raw: str) -> InstrumentId:
    """Rebuild the Nautilus ``InstrumentId`` this latch's own
    ``key_instrument_id``/``TrialDayRecord.instrument_id`` string names --
    NEVER ``InstrumentId.from_str`` (that parser requires a ``.`` venue
    delimiter this latch's plain-slug and composite-``^no`` strings do not
    carry; both ``symbology.slug_to_instrument_id`` and
    ``no_leg_instrument_id`` build the SAME shape by wrapping ``Symbol`` +
    ``POLYMARKET_US_VENUE`` directly, never through ``from_str``)."""
    return InstrumentId(Symbol(raw), POLYMARKET_US_VENUE)


def _bare_symbol(raw: str) -> str:
    """The bare symbol portion of ``raw``, stripping a trailing
    ``.<VENUE>`` if present.

    Safety review finding 1 (2026-09-14, commit f2d33f4): real TRIAL
    writers (``continuous_strategy.py``'s ``iid = str(instrument_id)``,
    every ``key_instrument_id``/``TrialDayRecord.instrument_id`` in that
    module) key by the DOTTED ``str(InstrumentId)`` form
    (``"<symbol>.<venue>"``); ``_leg_instrument_id`` above needs the BARE
    symbol only. A market slug never contains ``.`` (``assert_valid_slug``),
    so splitting on the first ``.`` is unambiguous and idempotent on an
    already-bare input.
    """
    if "." in raw:
        return raw.split(".", 1)[0]
    return raw


def _dotted_key_id(raw: str) -> str:
    """Normalise ``raw`` (either the BARE symbol S4's own tests were
    originally written against, or the DOTTED ``str(InstrumentId)`` every
    real caller in ``continuous_strategy.py`` actually writes) to the
    dotted form every durable ``TrialDayRecord`` key/value is keyed and
    stamped under in production.

    Idempotent: a ``raw`` that already contains the reserved venue
    delimiter ``.`` is returned unchanged, so a caller migrated to the
    dotted convention (the only convention this module's OWN production
    callers ever write) never double-normalises.
    """
    if "." in raw:
        return raw
    return str(_leg_instrument_id(raw))


def _cell_probability(be: Decimal, side: str) -> Decimal:
    """``q_i = P(HIGH in r_i)`` under H0 (plan NO_SIDE_EDGE_2026-09-14 SS3):
    ``BE_i`` for a YES leg, ``1 - BE_i`` for a NO leg. Decimal throughout
    (money/probability sums stay Decimal, never float)."""
    return be if side == "yes" else Decimal(1) - be

#: Slice 4 item B1 (plan rev 6.1): v3-only, family-wide keys -- literal
#: strings, NOT derived from a `TrialDayLatch`'s own `_key_prefix` (v2 never
#: writes either of these; there is exactly one continuous-rung-hold family).
#:
#: WP-11b (active-family registry, cardinality-1, 2026-09-19): this key is
#: scoped by COMPOSITION KIND (every ``continuous_rung_hold`` family opens
#: its latch with `CONTINUOUS_TRIAL_KEY_PREFIX`, a fixed constant), never by
#: the manifest's own `family_id` -- under cardinality-1 at most one family
#: is ever the continuous-kind sender, so "halted" stays GLOBAL-equivalent
#: to "this node's only sender is halted" (F6) no matter which literal
#: family id currently occupies that slot. `trade_supervisor_core.
#: continuous_family_halt_key(sending_family_id)` duplicates this literal
#: (runtime must not import strategy) and is pinned against it byte-for-byte
#: in `tests/unit/test_trade_supervisor_cont_self_check.py`.
DUPLICATE_FILL_KEY_PREFIX: Final[str] = "continuous_rung_hold/duplicate_fill/"
FAMILY_HALT_KEY: Final[str] = "continuous_rung_hold/halt"
#: Audit trail for `breezy-clear-family-halt` (build-side clear only -- there
#: is no automated clear). One record per clear, keyed by the clearing
#: ts_ns so a family can be halted, cleared, and re-halted across restarts
#: without ever overwriting a prior audit entry.
HALT_CLEARED_KEY_PREFIX: Final[str] = "continuous_rung_hold/halt_cleared/"
#: Sentinel written over `FAMILY_HALT_KEY` by `clear_family_halt` -- the
#: store has no delete (`StateStore.set`/`get` only), so "cleared" is a
#: distinguishable value rather than an absent key, mirroring
#: `_INFLIGHT_CLEARED` above.
_HALT_CLEARED_MARKER: Final[bytes] = b'{"v":1,"state":"cleared"}'


def decode_family_halt(raw: bytes | None) -> bool:
    """Pure decode of a ``FAMILY_HALT_KEY`` store value: ``True`` iff present
    and not the ``_HALT_CLEARED_MARKER`` sentinel.

    No I/O, no lock, no ``TrialDayLatch`` instance required -- this is the
    SINGLE SOURCE OF TRUTH :meth:`TrialDayLatch.is_family_halted` itself
    calls after its own ``_require_held()`` check. A caller that does not
    (and must not) hold this family's exclusive submit-intent latch --
    ``scripts/analysis/decision_funnel_daily_digest.py``'s ``halt_enforced``
    field, reading the SAME key through its own separate, read-only sqlite
    connection -- calls this function directly instead of duplicating the
    two-line comparison.
    """
    return raw is not None and raw != _HALT_CLEARED_MARKER


def _decode_halt_payload(raw: bytes) -> dict[str, object]:
    """Best-effort decode of a halt record for the clear audit trail.

    Never raises: garbage bytes, invalid UTF-8, an empty value, or a
    non-dict/legacy-schema JSON body all fall back to a raw-bytes
    representation rather than blocking `clear_family_halt` -- a corrupt or
    unrecognised halt record is exactly the case the operator most needs to
    be able to clear, with the original bytes preserved (hex-encoded) in the
    audit record for later inspection.
    """
    try:
        decoded: object = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {"corrupt": True, "rawHex": raw.hex()}
    if not isinstance(decoded, dict):
        return {"corrupt": True, "rawHex": raw.hex()}
    return decoded

#: Slice 4 item A2 (plan rev 6.1): the exec client's durable startup/re-arm
#: evidence key -- written at the end of every connect and after each
#: resolver terminal-zero (client.py, another agent's seam; not written
#: here). Read-only from this module.
STARTUP_EVIDENCE_KEY: Final[str] = "exec/polymarket_us/startup_evidence"

#: Slice 4 item E1 (plan rev 6.1, Resolution F): per-station-day re-arm
#: attempt counter, v3-only.
ATTEMPT_COUNTER_KEY_PREFIX: Final[str] = "continuous_rung_hold/attempts/"


class TrialDayLatchError(Exception):
    """Base error for the trial-day latch."""


class TrialDayAlreadyConsumed(TrialDayLatchError):
    """Raised by a second ``consume`` for the same station-day.

    ``consume`` is idempotent-refusing, not idempotent-succeeding: a second
    call is a bug in the caller (evaluating a station-day twice in one
    process, or after a restart without checking ``is_consumed`` first), not
    a benign retry, so it fails loudly rather than silently keeping the
    first record.
    """

    def __init__(self, station: str, climate_day: str) -> None:
        self.station = station
        self.climate_day = climate_day
        super().__init__(f"trial day already consumed: {station}/{climate_day}")


class TrialDayInvalidReason(TrialDayLatchError):
    """Raised when ``consume`` is given a reason outside the closed set."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"trial day reason not in the closed set: {reason!r}")


class TrialDayRecordCorrupt(TrialDayLatchError):
    """Raised when a stored record cannot be decoded. Fail closed."""

    def __init__(self) -> None:
        super().__init__("trial day record is corrupt")


def _inflight_prefix(trial_prefix: str) -> str:
    if not trial_prefix.endswith(_TRIAL_SUFFIX):
        raise ValueError(
            f"trial key prefix must end with {_TRIAL_SUFFIX!r}, was {trial_prefix!r}"
        )
    return trial_prefix[: -len(_TRIAL_SUFFIX)] + _INFLIGHT_SUFFIX


def _key(
    station: str,
    climate_day: str,
    *,
    key_prefix: str = DEFAULT_TRIAL_KEY_PREFIX,
    key_instrument_id: str | None = None,
) -> str:
    """Operator ruling 2026-09-14 / plan S1: v3's TRIAL/IN_FLIGHT/attempt
    keys are per ``(station, climate_day, instrument_id)`` -- "I never
    wanted a limit of 1 contract per station." ``key_instrument_id=None``
    (v2's only call shape, and this function's default) reproduces the
    ORIGINAL station-day key byte-for-byte; v2's PREREG is closed and never
    passes this parameter, so v2 is behaviourally untouched.

    ``key_instrument_id``, when given, is normalised via
    :func:`_dotted_key_id` BEFORE building the key (safety review finding
    1, 2026-09-14): every real TRIAL writer (``continuous_strategy.py``'s
    ``iid = str(instrument_id)``) passes the DOTTED ``str(InstrumentId)``
    form, while some existing callers (and ``refuse_if_sibling_leg_traded``/
    ``station_day_admission``'s own sibling computation) pass the BARE
    symbol -- normalising HERE, in this one shared TRIAL-key builder, is
    what makes a record written under either form found by a lookup under
    either form: both durably resolve to ONE canonical key.
    """
    base = f"{key_prefix}{station}/{climate_day}"
    if key_instrument_id is None:
        return base
    normalized = _dotted_key_id(key_instrument_id)
    if "/" in normalized:
        raise TrialDayLatchError(
            f"key_instrument_id must not contain '/': {key_instrument_id!r} -- a "
            "slash would corrupt the station/climate_day/instrument_id key "
            "boundary this function builds"
        )
    return f"{base}/{normalized}"


def trial_id_for(
    key_prefix: str, station: str, climate_day: str, instrument_id: str,
) -> str:
    """The canonical ``trial_id`` string for one (station, climate_day,
    instrument_id) trial under ``key_prefix`` -- a public, read-only wrapper
    around this module's own private :func:`_key`, so a second caller
    (``position_monitor.py``, INC-5/A1) can derive the SAME string
    ``score_live_trials.py`` reads back verbatim from the durable store's
    own key, WITHOUT re-deriving the key-building rule inline and risking
    silent drift between the two.

    No behaviour change: ``_key(station, climate_day, key_prefix=key_prefix,
    key_instrument_id=instrument_id)`` is exactly what a v3 (instrument-
    keyed) ``TrialDayRecord`` is written and read under today.
    """
    return _key(station, climate_day, key_prefix=key_prefix, key_instrument_id=instrument_id)


@dataclass(frozen=True, slots=True)
class TrialDayRecord:
    """The durable outcome of one station-day's single trial.

    ``ask`` is serialised as ``str(Decimal)`` and parsed back through
    ``Decimal(...)`` so money never round-trips through binary float.
    """

    latched_at_ns: int
    instrument_id: str
    ask: Decimal
    reason: str
    #: Slice 4 item A (plan rev 6.1): the venue order id whose durable fill
    #: consumed this station-day's trial, when known. TRAILING and OPTIONAL
    #: per the binding schema-compat rule (finding_trialrecord_compat.md):
    #: no ``_SCHEMA_VERSION`` bump (the exact-pin gate would corrupt every
    #: existing v1 row), read via ``payload.get`` so a pre-slice-4 record
    #: missing the key decodes as ``None`` -- mirrors
    #: ``DurableFillRecord.venue_fee_raw`` (client.py) exactly.
    venue_order_id: str | None = None
    #: Plan NO_SIDE_EDGE_2026-09-14 S4 (R3-7): the venue fee paid on this
    #: leg's own ask, when known -- ``BE = ask + fee``. TRAILING and
    #: OPTIONAL, same compat pattern as ``venue_order_id`` immediately
    #: above: no ``_SCHEMA_VERSION`` bump, read via ``payload.get`` so a
    #: pre-slice-4 record missing the key decodes as ``None`` ("q unknown"
    #: -- :func:`station_day_admission` refuses rather than guessing).
    fee: Decimal | None = None
    #: INC-E3 (plan §3, PREREG v4 §5b/§10): the registered rule
    #: (``"R_THREAT"``/``"R_DEAD"``) an exit fill on THIS trial was decided
    #: under, when this station-day's position was exited mid-day. TRAILING
    #: and OPTIONAL, same compat pattern as ``fee`` immediately above --
    #: written only by :meth:`TrialDayLatch.record_exit`, ``None`` for every
    #: trial never exited (which is every v2/v3 trial, and every v4 trial
    #: that settles by holding).
    exit_reason: str | None = None
    #: The exit fill's own price, in the held leg's own price domain
    #: (mirrors ``ask``'s convention) -- ``None`` unless ``exit_reason`` is set.
    exit_px: Decimal | None = None
    #: The exit fill's own per-contract fee -- ``None`` unless ``exit_reason``
    #: is set.
    exit_fee: Decimal | None = None
    #: The exit fill's ``ts_event`` (ns) -- ``None`` unless ``exit_reason`` is set.
    exit_at_ns: int | None = None

    def to_bytes(self) -> bytes:
        payload = {
            "v": _SCHEMA_VERSION,
            "latched_at_ns": self.latched_at_ns,
            "instrument_id": self.instrument_id,
            "ask": str(self.ask),
            "reason": self.reason,
            "venueOrderId": self.venue_order_id,
            "fee": str(self.fee) if self.fee is not None else None,
            "exitReason": self.exit_reason,
            "exitPx": str(self.exit_px) if self.exit_px is not None else None,
            "exitFee": str(self.exit_fee) if self.exit_fee is not None else None,
            "exitAtNs": self.exit_at_ns,
        }
        return json.dumps(payload, sort_keys=True).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> TrialDayRecord:
        try:
            decoded: object = json.loads(raw.decode("utf-8"))
        except ValueError:
            decoded = None
        if not isinstance(decoded, dict):
            raise TrialDayRecordCorrupt()
        payload: dict[str, object] = decoded
        try:
            version = payload["v"]
            latched_at_ns = payload["latched_at_ns"]
            instrument_id = payload["instrument_id"]
            ask_raw = payload["ask"]
            reason = payload["reason"]
        except KeyError:
            raise TrialDayRecordCorrupt() from None
        if version != _SCHEMA_VERSION:
            raise TrialDayRecordCorrupt()
        if isinstance(latched_at_ns, bool) or not isinstance(latched_at_ns, int):
            raise TrialDayRecordCorrupt()
        if not isinstance(instrument_id, str) or not isinstance(ask_raw, str):
            raise TrialDayRecordCorrupt()
        if not isinstance(reason, str) or reason not in _REASONS:
            raise TrialDayRecordCorrupt()
        try:
            ask = Decimal(ask_raw)
        except InvalidOperation:
            raise TrialDayRecordCorrupt() from None
        # Optional-on-read (missing key -> None, same as JSON null); a
        # PRESENT non-string value is still a mapping error.
        venue_order_id_raw = payload.get("venueOrderId")
        if venue_order_id_raw is not None and not isinstance(venue_order_id_raw, str):
            raise TrialDayRecordCorrupt()
        # Optional-on-read, same pattern as venueOrderId immediately above.
        fee_raw = payload.get("fee")
        if fee_raw is not None and not isinstance(fee_raw, str):
            raise TrialDayRecordCorrupt()
        fee: Decimal | None
        if fee_raw is None:
            fee = None
        else:
            try:
                fee = Decimal(fee_raw)
            except InvalidOperation:
                raise TrialDayRecordCorrupt() from None
        # INC-E3: optional-on-read, same pattern as `fee`/`venueOrderId` above.
        exit_reason_raw = payload.get("exitReason")
        if exit_reason_raw is not None and not isinstance(exit_reason_raw, str):
            raise TrialDayRecordCorrupt()
        exit_px_raw = payload.get("exitPx")
        if exit_px_raw is not None and not isinstance(exit_px_raw, str):
            raise TrialDayRecordCorrupt()
        exit_px: Decimal | None
        if exit_px_raw is None:
            exit_px = None
        else:
            try:
                exit_px = Decimal(exit_px_raw)
            except InvalidOperation:
                raise TrialDayRecordCorrupt() from None
        exit_fee_raw = payload.get("exitFee")
        if exit_fee_raw is not None and not isinstance(exit_fee_raw, str):
            raise TrialDayRecordCorrupt()
        exit_fee: Decimal | None
        if exit_fee_raw is None:
            exit_fee = None
        else:
            try:
                exit_fee = Decimal(exit_fee_raw)
            except InvalidOperation:
                raise TrialDayRecordCorrupt() from None
        exit_at_ns_raw = payload.get("exitAtNs")
        if exit_at_ns_raw is not None and (
            isinstance(exit_at_ns_raw, bool) or not isinstance(exit_at_ns_raw, int)
        ):
            raise TrialDayRecordCorrupt()
        return cls(
            latched_at_ns=latched_at_ns,
            instrument_id=instrument_id,
            ask=ask,
            reason=reason,
            venue_order_id=venue_order_id_raw,
            fee=fee,
            exit_reason=exit_reason_raw,
            exit_px=exit_px,
            exit_fee=exit_fee,
            exit_at_ns=exit_at_ns_raw,
        )


class TrialDayLatch:
    """At-most-one-trial-per-station-day latch by default (v2, no
    ``key_instrument_id``); at-most-one-trial-per-INSTRUMENT-day when
    ``key_instrument_id`` is supplied (v3, plan S1 -- "I never wanted a
    limit of 1 contract per station"), sharing R-7's submit-intent store
    and flock.

    Constructed only by :func:`open_trial_day_latch`, which binds this
    instance to the SAME ``StateStore`` and the SAME
    ``_HeldSubmitIntentLock`` an already-opened
    ``breezy.runtime.submit_intent.SubmitIntentLatch`` holds -- never a
    second store, never a second flock. Every public method asserts that
    flock is still held.
    """

    def __init__(
        self,
        store: StateStore,
        lock: _HeldSubmitIntentLock,
        *,
        key_prefix: str = DEFAULT_TRIAL_KEY_PREFIX,
        intent_latch: SubmitIntentLatch | None = None,
    ) -> None:
        self._store = store
        self._lock = lock
        self._key_prefix = key_prefix
        self._inflight_prefix = _inflight_prefix(key_prefix)
        #: Resolution B (plan rev 6.1): bound at construction by
        #: :func:`open_trial_day_latch`, never opened here. ``None`` for a
        #: ``TrialDayLatch`` built directly (existing test doubles) -- such
        #: an instance simply cannot call :meth:`is_intent_open`.
        self._intent_latch = intent_latch
        #: Slice 4 item A: the thread that constructed THIS instance,
        #: recorded here regardless of ``intent_latch`` -- mirrors
        #: ``SubmitIntentLatch.opening_thread_ident``. ``consume_if_absent``
        #: asserts against it: a read-then-write-if-absent is not atomic
        #: across threads even under the flock (the flock is process-wide,
        #: not a Python-level mutex against a second thread in THIS process).
        self._opening_thread_ident = threading.get_ident()

    def _require_held(self) -> None:
        if not self._lock.held:
            raise SubmitIntentLockNotHeld()

    def is_intent_open(self) -> bool:
        """Resolution B (plan rev 6.1): ``True`` while the account-wide
        submit-intent singleton is OPEN.

        A read-only pre-filter over the SAME store and flock ``arm()``/
        ``retire()`` already share -- delegates to
        ``SubmitIntentLatch.is_latched()`` on the ``intent_latch`` bound at
        construction. This is the cheap check ``_hunt_tick`` uses BEFORE
        ``set_inflight``/``_maybe_submit``: while OPEN (whether from a
        genuine in-flight sibling order or a stale/crash-left singleton no
        resolver has cleared yet), every station's tick is a WAIT, never a
        task hop that would only be denied later inside ``_submit_order``.
        """
        self._require_held()
        if self._intent_latch is None:
            raise TrialDayLatchError(
                "is_intent_open() requires a TrialDayLatch bound to an "
                "intent_latch at construction; see open_trial_day_latch"
            )
        return self._intent_latch.is_latched()

    def current_open_submit_intent(self) -> SubmitIntent | None:
        """Review finding B (``POSITION_EXIT_EXECUTION_2026-09-16.md``):
        the currently OPEN account-wide submit intent, or ``None`` -- the
        read-only surface ``exit_wiring.check_exit_intent_for_ambiguous_
        send`` needs to tell whether ITS OWN prior exit order is the one
        still stuck open, and for how long.

        A read-only pass-through over the SAME store and flock ``is_intent_
        open()`` already shares -- delegates to
        ``SubmitIntentLatch.current_open()`` on the ``intent_latch`` bound
        at construction. Never polls the venue: this is a local read of the
        durable singleton this process (or a sibling that shares the same
        store) already wrote.
        """
        self._require_held()
        if self._intent_latch is None:
            raise TrialDayLatchError(
                "current_open_submit_intent() requires a TrialDayLatch bound "
                "to an intent_latch at construction; see open_trial_day_latch"
            )
        return self._intent_latch.current_open()

    def _trial_key(
        self, station: str, climate_day: str, *, key_instrument_id: str | None = None,
    ) -> str:
        return _key(
            station, climate_day, key_prefix=self._key_prefix, key_instrument_id=key_instrument_id,
        )

    def _inflight_key(
        self, station: str, climate_day: str, *, key_instrument_id: str | None = None,
    ) -> str:
        base = f"{self._inflight_prefix}{station}/{climate_day}"
        if key_instrument_id is None:
            return base
        return f"{base}/{key_instrument_id}"

    def record(
        self, station: str, climate_day: str, *, key_instrument_id: str | None = None,
    ) -> TrialDayRecord | None:
        """Return the durable record for this station-day (or, when
        ``key_instrument_id`` is given, this instrument-day -- plan S1), or
        ``None``.
        """
        self._require_held()
        raw = self._store.get(
            self._trial_key(station, climate_day, key_instrument_id=key_instrument_id),
        )
        if raw is None:
            return None
        return TrialDayRecord.from_bytes(raw)

    def record_with_legacy_fallback(
        self, station: str, climate_day: str, *, key_instrument_id: str | None,
    ) -> TrialDayRecord | None:
        """Read-compat shim (operator ruling 2026-09-14 / plan S1): the
        instrument-day record if one exists, else a LEGACY station-day row
        IFF its own ``instrument_id`` field equals ``key_instrument_id`` --
        durable rows written before this slice live under the old key and
        the store has no delete. A legacy row for a DIFFERENT instrument is
        never returned (fail-closed direction: match only a real match,
        never a stranger). ``key_instrument_id=None`` is the plain v2 read,
        with no legacy fallback of its own (there is nothing to fall back
        from -- it IS the legacy key).
        """
        self._require_held()
        found = self.record(station, climate_day, key_instrument_id=key_instrument_id)
        if found is not None or key_instrument_id is None:
            return found
        legacy = self.record(station, climate_day)
        if legacy is not None and legacy.instrument_id == key_instrument_id:
            return legacy
        return None

    def is_consumed(
        self, station: str, climate_day: str, *, key_instrument_id: str | None = None,
    ) -> bool:
        """``True`` once this station-day's (or, keyed, this instrument-
        day's -- plan S1) single trial has been recorded. See
        :meth:`record_with_legacy_fallback` for the read-compat shim.
        """
        return (
            self.record_with_legacy_fallback(
                station, climate_day, key_instrument_id=key_instrument_id,
            )
            is not None
        )

    def consume(
        self,
        station: str,
        climate_day: str,
        *,
        latched_at_ns: int,
        instrument_id: str,
        ask: Decimal,
        reason: str,
        key_instrument_id: str | None = None,
        fee: Decimal | None = None,
    ) -> None:
        """Durably record this station-day's single trial.

        Returns only after the write has ``COMMIT``\\ ed (``StateStore.set``
        on the real ``SqliteStateStore`` commits before returning -- see its
        module docstring). Per the ordering rule, this MUST be called, and
        MUST return, before ``SubmitIntentLatch.arm()`` for any order this
        trial leads to.

        ``key_instrument_id`` (plan S1) keys the durable write by instrument
        as well as station-day. v2's only call shape never passes it and
        stays byte-identical.

        ``fee`` (plan NO_SIDE_EDGE_2026-09-14 S4, R3-7) is OPTIONAL and
        TRAILING, mirroring ``TrialDayRecord.fee`` -- v2's call shape never
        passes it and stays byte-identical.
        """
        self._require_held()
        if reason not in _REASONS:
            raise TrialDayInvalidReason(reason)
        if self.is_consumed(station, climate_day, key_instrument_id=key_instrument_id):
            raise TrialDayAlreadyConsumed(station, climate_day)
        record = TrialDayRecord(
            latched_at_ns=latched_at_ns,
            instrument_id=instrument_id,
            ask=ask,
            reason=reason,
            fee=fee,
        )
        self._store.set(
            self._trial_key(station, climate_day, key_instrument_id=key_instrument_id),
            record.to_bytes(),
        )

    def consume_if_absent(
        self,
        station: str,
        climate_day: str,
        record: TrialDayRecord,
        *,
        key_instrument_id: str | None = None,
    ) -> bool:
        """Slice 4 item A: durably record TRIAL for a fill, idempotently.

        Returns ``True`` iff THIS call wrote the record, ``False`` if one
        already existed -- unlike :meth:`consume`, this NEVER raises on an
        already-consumed station-day. That is the whole point: a
        recon-replayed duplicate ``OrderFilled`` for a station-day whose
        trial is already consumed must be a silent no-op here (Resolution
        B's duplicate-fill handling decides what to do with the SECOND
        fill; this method's only job is "don't crash, don't overwrite, and
        never claim TWO writers both wrote it").

        Two writers racing this SAME station-day (e.g. a live
        ``on_order_filled`` and the on_start durable-fill walk observing
        the same underlying fill) leave exactly ONE record: whichever
        holds the flock first at the read-check-write below wins, and the
        loser's own ``is_consumed`` check then observes it and returns
        ``False`` -- never a second write, never a raise.

        Asserts the flock is held and that this is the SAME thread that
        opened this ``TrialDayLatch`` -- a read-then-write-if-absent is not
        atomic against a second thread in this SAME process (the flock is
        process-wide, not a Python-level mutex).
        """
        self._require_held()
        assert threading.get_ident() == self._opening_thread_ident, (
            "consume_if_absent must run on the thread that opened this "
            "TrialDayLatch; a second thread racing the read-check-write "
            "below is not made safe by the process-wide flock alone"
        )
        if record.reason not in _REASONS:
            raise TrialDayInvalidReason(record.reason)
        if self.is_consumed(station, climate_day, key_instrument_id=key_instrument_id):
            return False
        self._store.set(
            self._trial_key(station, climate_day, key_instrument_id=key_instrument_id),
            record.to_bytes(),
        )
        return True

    def is_inflight(
        self, station: str, climate_day: str, *, key_instrument_id: str | None = None,
    ) -> bool:
        """``True`` while this station-day (or, keyed, instrument-day --
        plan S1) has a durable IN_FLIGHT marker."""
        self._require_held()
        raw = self._store.get(
            self._inflight_key(station, climate_day, key_instrument_id=key_instrument_id),
        )
        return raw == _INFLIGHT_OPEN

    def set_inflight(
        self, station: str, climate_day: str, *, key_instrument_id: str | None = None,
    ) -> None:
        """COMMIT the IN_FLIGHT marker for this station-day (or instrument-
        day -- plan S1). Must precede ``arm()``."""
        self._require_held()
        self._store.set(
            self._inflight_key(station, climate_day, key_instrument_id=key_instrument_id),
            _INFLIGHT_OPEN,
        )

    def clear_inflight(
        self, station: str, climate_day: str, *, key_instrument_id: str | None = None,
    ) -> None:
        """Clear the IN_FLIGHT marker (StateStore has no delete -- write cleared)."""
        self._require_held()
        self._store.set(
            self._inflight_key(station, climate_day, key_instrument_id=key_instrument_id),
            _INFLIGHT_CLEARED,
        )

    # -- Slice 4 item B1 (plan rev 6.1): duplicate-fill residual + family halt --

    def record_duplicate_fill(
        self,
        station: str,
        climate_day: str,
        *,
        venue_order_id: str,
        qty: Decimal,
        fill_px: Decimal,
        fee: Decimal,
        ts_ns: int,
    ) -> None:
        """Durably record a second genuine fill on an already-consumed
        instrument-day, and set the FAMILY-wide halt.

        Plan S1/S3 (operator ruling 2026-09-14): the TRIAL key this guards
        is now per ``(station, climate_day, instrument_id)`` -- a second
        genuine fill on a DIFFERENT rung of the same station-day is a
        second, independent trial (never a duplicate; see
        ``consume_if_absent``'s own instrument-day keying). This method
        only ever fires for a second fill on the SAME already-consumed
        instrument-day. Its BLAST RADIUS is unchanged by that re-keying:
        the halt it sets is family-wide (``FAMILY_HALT_KEY`` has no
        station/instrument component and never has), stopping every
        station and every rung, not just the offending instrument-day.

        Idempotent per ``venue_order_id``: a replayed call for the SAME
        duplicate fill (or the SAME id racing two writers) writes neither
        bucket a second time -- first writer wins, matching
        :meth:`consume_if_absent`'s own read-check-write discipline under
        this SAME flock.
        """
        self._require_held()
        bucket_key = f"{DUPLICATE_FILL_KEY_PREFIX}{venue_order_id}"
        if self._store.get(bucket_key) is None:
            payload = {
                "v": 1,
                "qty": str(qty),
                "fillPx": str(fill_px),
                "fee": str(fee),
                "tsNs": ts_ns,
                "station": station,
                "climateDay": climate_day,
            }
            self._store.set(bucket_key, json.dumps(payload, sort_keys=True).encode("utf-8"))
        if not self.is_family_halted():
            halt_payload = {
                "v": 1,
                "reason": "duplicate_fill",
                "tsNs": ts_ns,
                "venueOrderId": venue_order_id,
            }
            self._store.set(
                FAMILY_HALT_KEY, json.dumps(halt_payload, sort_keys=True).encode("utf-8"),
            )

    # -- INC-E3 (plan §3, PREREG v4 §3b/§5b): exit provenance + kill rule --

    def record_exit(
        self,
        station: str,
        climate_day: str,
        *,
        key_instrument_id: str,
        exit_reason: str,
        exit_px: Decimal,
        exit_fee: Decimal,
        exit_at_ns: int,
    ) -> None:
        """Durably attach exit provenance to an already-consumed trial.

        Unlike :meth:`consume`/:meth:`consume_if_absent` (which write a
        FRESH record), this OVERWRITES the existing ``TrialDayRecord`` for
        ``(station, climate_day, key_instrument_id)`` via
        ``dataclasses.replace`` -- the station-day's entry fields
        (``ask``/``reason``/``venue_order_id``/``fee``) are carried forward
        byte-identical; only the four ``exit_*`` fields change. Raises
        :class:`TrialDayLatchError` if no record exists yet for this
        station-day (an exit fill can only ever follow a genuine entry
        fill -- attaching exit provenance to a station-day with no trial at
        all is a caller defect, not a benign no-op) and
        :class:`TrialDayInvalidReason` if ``exit_reason`` is outside the
        closed :data:`_EXIT_REASONS` set.
        """
        self._require_held()
        if exit_reason not in _EXIT_REASONS:
            raise TrialDayInvalidReason(exit_reason)
        existing = self.record_with_legacy_fallback(
            station, climate_day, key_instrument_id=key_instrument_id,
        )
        if existing is None:
            raise TrialDayLatchError(
                f"record_exit: no trial-day record for {station}/{climate_day}/"
                f"{key_instrument_id!r} -- an exit fill must join an already-"
                "consumed trial"
            )
        updated = replace(
            existing,
            exit_reason=exit_reason,
            exit_px=exit_px,
            exit_fee=exit_fee,
            exit_at_ns=exit_at_ns,
        )
        self._store.set(
            self._trial_key(station, climate_day, key_instrument_id=key_instrument_id),
            updated.to_bytes(),
        )

    def record_ambiguous_exit(
        self,
        *,
        position_id: str,
        reason: str,
        ts_ns: int,
    ) -> None:
        """Durably set the FAMILY-wide halt for an AMBIGUOUS or rejected
        exit order (plan §5.4, PREREG v4 §5b).

        Writes the EXACT SAME durable state :meth:`record_duplicate_fill`
        writes and :meth:`is_family_halted` reads -- no new mechanism, so
        this is already enforced at every existing chokepoint
        (``composition.py``'s ``family_halt_submit_veto``,
        ``continuous_strategy.py``'s ``_hunt_tick``/``on_order_filled``) and
        cleared only by :meth:`clear_family_halt` via the operator CLI.
        Idempotent: if the family is already halted (by this or any other
        cause), the existing halt payload is left untouched -- first cause
        wins, mirroring :meth:`record_duplicate_fill`'s own idempotency.
        """
        self._require_held()
        if self.is_family_halted():
            return
        halt_payload = {
            "v": 1,
            "reason": "ambiguous_exit",
            "tsNs": ts_ns,
            "positionId": position_id,
            "detail": reason,
        }
        self._store.set(
            FAMILY_HALT_KEY, json.dumps(halt_payload, sort_keys=True).encode("utf-8"),
        )

    def record_policy_halt(
        self,
        *,
        reason: str,
        evidence_sha256: str,
        ts_ns: int,
    ) -> None:
        """Durably set the FAMILY-wide halt for a deliberate, evidenced
        POLICY decision (AUD-02b: enforce the A1 ruling,
        ``docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md``).

        Writes the EXACT SAME durable state :meth:`record_duplicate_fill` and
        :meth:`record_ambiguous_exit` already write and :meth:`is_family_halted`
        already reads -- no new mechanism, no new key, no new veto. Enforced at
        every existing chokepoint (``composition.py``'s
        ``family_halt_submit_veto``, ``exit_wiring.submit_exit``) with zero
        additional wiring. Cleared only by :meth:`clear_family_halt` via the
        operator CLI. Idempotent: if the family is already halted (by this or
        any other cause), the existing halt payload is left untouched -- first
        cause wins, mirroring :meth:`record_duplicate_fill`'s own idempotency.
        """
        self._require_held()
        if self.is_family_halted():
            return
        halt_payload = {
            "v": 1,
            "reason": "policy_halt",
            "tsNs": ts_ns,
            "detail": reason,
            "evidenceSha256": evidence_sha256,
        }
        self._store.set(
            FAMILY_HALT_KEY, json.dumps(halt_payload, sort_keys=True).encode("utf-8"),
        )

    def is_family_halted(self) -> bool:
        """``True`` once ANY of this latch's three ``FAMILY_HALT_KEY``
        writers has fired for THIS family and no ``breezy-clear-family-halt``
        run has cleared it since. Durable -- survives restart, unlike
        ``_trading_refusals``. The three writers, added across separate
        slices and unified here (AUD-02b, docstring-only note -- no code
        change on this read path): :meth:`record_duplicate_fill` (an
        automatic consequence of a second genuine fill on an
        already-consumed instrument-day), :meth:`record_ambiguous_exit` (an
        automatic consequence of an AMBIGUOUS or rejected exit order), and
        :meth:`record_policy_halt` (a deliberate, evidenced operator
        decision via ``breezy-set-family-halt`` -- AUD-02b: enforce the A1
        ruling). All three write the SAME payload shape and are read
        identically here; this method cannot and does not distinguish which
        one fired.

        The decode itself is :func:`decode_family_halt` -- see that
        function for the ``_HALT_CLEARED_MARKER`` rationale. This method
        only adds the ``_require_held()`` discipline every other method on
        this class carries; a caller with no legitimate held latch (AUD-03's
        daily digest, reading through its OWN read-only sqlite connection,
        never this latch's exclusive flock) calls :func:`decode_family_halt`
        directly instead.
        """
        self._require_held()
        return decode_family_halt(self._store.get(FAMILY_HALT_KEY))

    def is_day_budget_exhausted(self, utc_day: str) -> bool:
        """``True`` once the exec client has marked ``utc_day`` (a
        ``YYYY-MM-DD`` UTC calendar day) as spend-exhausted (operator ruling
        2026-09-14).

        Any value at the key means exhausted -- fail-closed, mirroring
        :meth:`is_family_halted`'s own shape. No ``try``/``except``: a store
        error here propagates and halts the tick, exactly like
        :meth:`is_family_halted`.
        """
        self._require_held()
        raw = self._store.get(f"{BUDGET_EXHAUSTED_KEY_PREFIX}{utc_day}")
        return raw is not None

    def clear_family_halt(
        self,
        *,
        reason: str,
        evidence_sha256: str,
        ts_ns: int,
    ) -> dict[str, object]:
        """Durably clear the family-wide halt. Build-side only -- there is
        no automated clear; this is the sole writer, invoked exclusively by
        the ``breezy-clear-family-halt`` operator CLI.

        Writes an audit record under ``HALT_CLEARED_KEY_PREFIX + ts_ns``
        containing the prior halt payload, ``reason``, ``evidence_sha256``
        and ``ts_ns`` BEFORE overwriting ``FAMILY_HALT_KEY`` with the
        cleared sentinel -- so a crash between the two writes leaves the
        halt still active (fail closed) with an orphaned audit record,
        never a cleared halt with no audit trail.

        Raises :class:`TrialDayLatchError` if the halt is not currently set
        (re-checked here under the SAME flock rather than trusting an
        earlier caller read, matching :meth:`consume_if_absent`'s own
        discipline). A halt payload that is garbage bytes, empty, or an
        unrecognised/legacy schema is still clearable -- :meth:`is_family_halted`
        fails CLOSED on any such value (a corrupt or legacy record is exactly
        the case an operator most needs to be able to clear WITH evidence),
        so this method never raises on undecodable content; it records the
        raw bytes (hex-encoded) in the audit trail instead of the parsed
        payload. Returns the prior halt payload actually written to the
        audit record (either the decoded dict, or the raw-bytes fallback).
        """
        self._require_held()
        raw = self._store.get(FAMILY_HALT_KEY)
        if raw is None or raw == _HALT_CLEARED_MARKER:
            raise TrialDayLatchError("no family halt is currently set; nothing to clear")
        prior_payload = _decode_halt_payload(raw)
        audit_payload = {
            "v": 1,
            "priorHalt": prior_payload,
            "reason": reason,
            "evidenceSha256": evidence_sha256,
            "tsNs": ts_ns,
        }
        self._store.set(
            f"{HALT_CLEARED_KEY_PREFIX}{ts_ns}",
            json.dumps(audit_payload, sort_keys=True).encode("utf-8"),
        )
        self._store.set(FAMILY_HALT_KEY, _HALT_CLEARED_MARKER)
        return prior_payload

    # -- Slice 4 item A2 (plan rev 6.1): never-arm startup evidence + fill walk --

    def read_startup_evidence(self) -> dict[str, object] | None:
        """The exec client's durable startup/re-arm evidence, read FRESH on
        every call -- never cached on this object.

        ``None`` for an absent OR malformed record: callers (the on-start
        never-arm walk, the re-arm gate) both fail closed on ``None``, so a
        corrupt record is indistinguishable here from "never written".
        """
        self._require_held()
        raw = self._store.get(STARTUP_EVIDENCE_KEY)
        if raw is None:
            return None
        try:
            decoded: object = json.loads(raw.decode("utf-8"))
        except ValueError:
            return None
        if not isinstance(decoded, dict):
            return None
        return decoded

    def iter_fill_records(self, instrument_ids: Iterable[str]) -> tuple[DurableFillRecord, ...]:
        """Every durable fill record reachable from ``instrument_ids``'s fill
        indices.

        The store has no prefix scan (see ``client.py::record_fill``'s own
        docstring), so this walks the SAME per-instrument
        ``FILL_INDEX_KEY_PREFIX`` index the exec client already maintains,
        rather than attempting one over ``FILL_KEY_PREFIX`` directly.

        Read-only. A missing index for one instrument is simply "no fills
        for it" (skipped); a PRESENT but malformed index or record RAISES --
        the on-start walk that calls this fails closed rather than silently
        under-counting a real fill.
        """
        self._require_held()
        records: list[DurableFillRecord] = []
        seen: set[str] = set()
        for instrument_id in instrument_ids:
            raw_index = self._store.get(f"{FILL_INDEX_KEY_PREFIX}{instrument_id}")
            if raw_index is None:
                continue
            try:
                decoded_index: object = json.loads(raw_index.decode("utf-8"))
            except ValueError:
                raise TrialDayRecordCorrupt() from None
            if not isinstance(decoded_index, list):
                raise TrialDayRecordCorrupt()
            for venue_order_id in decoded_index:
                if not isinstance(venue_order_id, str) or venue_order_id in seen:
                    continue
                seen.add(venue_order_id)
                raw = self._store.get(f"{FILL_KEY_PREFIX}{venue_order_id}")
                if raw is None:
                    raise TrialDayRecordCorrupt()
                records.append(DurableFillRecord.from_bytes(raw))
        return tuple(records)

    # -- Slice 4 item E1 (plan rev 6.1, Resolution F): re-arm attempt counter --

    def _attempt_key(
        self, station: str, climate_day: str, *, key_instrument_id: str | None = None,
    ) -> str:
        base = f"{ATTEMPT_COUNTER_KEY_PREFIX}{station}/{climate_day}"
        if key_instrument_id is None:
            return base
        return f"{base}/{key_instrument_id}"

    def attempt_state(
        self, station: str, climate_day: str, *, key_instrument_id: str | None = None,
    ) -> tuple[int, int | None]:
        """``(attempt_count, last_attempt_ts_ns)`` for this station-day's (or
        instrument-day's -- plan S1) re-arm counter -- ``(0, None)`` before
        the first attempt.

        A genuine fill freezes this counter by construction: once
        ``is_consumed`` is ``True`` for this station-day, `_hunt_tick`
        returns before this is ever consulted again.
        """
        self._require_held()
        raw = self._store.get(
            self._attempt_key(station, climate_day, key_instrument_id=key_instrument_id),
        )
        if raw is None:
            return 0, None
        try:
            payload: object = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise TrialDayRecordCorrupt() from None
        if not isinstance(payload, dict):
            raise TrialDayRecordCorrupt()
        count = payload.get("count")
        last_ns = payload.get("lastAttemptNs")
        if isinstance(count, bool) or not isinstance(count, int):
            raise TrialDayRecordCorrupt()
        if last_ns is not None and (isinstance(last_ns, bool) or not isinstance(last_ns, int)):
            raise TrialDayRecordCorrupt()
        return count, last_ns

    def record_attempt(
        self,
        station: str,
        climate_day: str,
        *,
        ts_ns: int,
        key_instrument_id: str | None = None,
    ) -> int:
        """Durably increment this station-day's (or instrument-day's -- plan
        S1) re-arm attempt counter.

        Returns the new count. Called once per genuine arm attempt (at
        `set_inflight` time), never on a re-arm-gate REFUSAL.
        """
        self._require_held()
        count, _ = self.attempt_state(station, climate_day, key_instrument_id=key_instrument_id)
        new_count = count + 1
        payload = {"v": 1, "count": new_count, "lastAttemptNs": ts_ns}
        self._store.set(
            self._attempt_key(station, climate_day, key_instrument_id=key_instrument_id),
            json.dumps(payload, sort_keys=True).encode("utf-8"),
        )
        return new_count


def startup_evidence_refusal_reason(evidence: dict[str, object] | None) -> str | None:
    """Why ``evidence`` does NOT permit arming, or ``None`` when it does.

    Slice 4 item A2 (plan rev 6.1) for the positions read, extended by
    RESTING_BID_HUNT Rev 2 section 4.3 for the open-order enumeration: the
    exec client's read must have SUCCEEDED (``open_orders_read_refused`` is
    exactly ``False``) AND returned an EMPTY list. A record predating those
    two keys, a refused read, a malformed list, or ANY open order -- on a
    configured market or a foreign one -- is a refusal. Fail closed: an
    enumeration error is never an assumed-empty book. Reasons are stable
    tokens; :data:`STARTUP_OPEN_ORDERS_PRESENT_REASON` is the one the exec
    client also logs at ERROR when it writes such a record.
    """
    if evidence is None:
        return "evidence_absent"
    if evidence.get("v") != 1:
        return "schema_version"
    if evidence.get("position_read_refused") is not False:
        return "position_read_refused"
    if evidence.get("eof_complete") is not True:
        return "not_eof_complete"
    if evidence.get("fill_walk_complete") is not True:
        return "fill_walk_incomplete"
    if evidence.get("open_orders_read_refused") is not False:
        return "open_orders_read_refused"
    open_orders = evidence.get("open_orders")
    if not isinstance(open_orders, list):
        return "open_orders_malformed"
    if open_orders:
        return STARTUP_OPEN_ORDERS_PRESENT_REASON
    return None


def startup_evidence_permits_arm(evidence: dict[str, object] | None) -> bool:
    """``True`` only when ``evidence`` proves a complete, non-refused startup
    positions read AND a successful, EMPTY open-order enumeration -- exactly
    :func:`startup_evidence_refusal_reason` returning ``None``. Any missing
    or wrong-typed field is a refusal to arm -- fail closed, not a partial
    read.
    """
    return startup_evidence_refusal_reason(evidence) is None


def startup_evidence_position_for(
    evidence: dict[str, object] | None, slug: str,
) -> Decimal | None:
    """The net position for ``slug`` out of ``evidence["positions"]``, when
    ``slug`` is LISTED on the page.

    ``None`` (UNKNOWN) when: ``evidence`` itself is absent/unreadable; the
    ``positions`` field is malformed; ``slug`` is absent from the list (see
    R-8, ``docs/core/PROGRESS.md`` -- for a *candidate* instrument this is
    now interpreted as confirmed-flat by :func:`startup_evidence_confirms_
    absent_flat`, not by this raw accessor); or the row's own
    ``net_position`` is JSON ``null`` (the client's explicit "this row was
    unreadable" signal) or any other non-numeric-string value. This
    function remains the raw, byte-unchanged accessor; interpretation of an
    ABSENT slug now lives in :func:`startup_evidence_lists_slug` and
    :func:`startup_evidence_confirms_absent_flat`.
    """
    if evidence is None:
        return None
    positions = evidence.get("positions")
    if not isinstance(positions, list):
        return None
    for row in positions:
        if not isinstance(row, dict) or row.get("slug") != slug:
            continue
        raw = row.get("net_position")
        if raw is None or not isinstance(raw, str):
            return None
        try:
            return Decimal(raw)
        except InvalidOperation:
            return None
    return None


def startup_evidence_lists_slug(evidence: dict[str, object] | None, slug: str) -> bool:
    """``True`` iff ``evidence["positions"]`` (read via ``.get``, HB4)
    contains a mapping whose ``"slug"`` equals ``slug``. Non-mapping rows
    are skipped while scanning, mirroring :func:`startup_evidence_position_
    for` exactly (HB1/E12) -- a garbage row elsewhere in the list must never
    stop a genuine match from being found on the PRESENT branch.

    ``False`` when ``evidence`` is ``None``, matching its two siblings
    :func:`startup_evidence_permits_arm` and :func:`startup_evidence_
    position_for` (N1).
    """
    if evidence is None:
        return False
    positions = evidence.get("positions")
    if not isinstance(positions, list):
        return False
    for row in positions:
        if isinstance(row, dict) and row.get("slug") == slug:
            return True
    return False


def startup_evidence_confirms_absent_flat(
    evidence: dict[str, object] | None,
    slug: str,
    *,
    now_ns: int,
    max_age_ns: int,
) -> bool:
    """R-8 (2026-09-12, ``docs/core/PROGRESS.md``): ``True`` only when a
    candidate ``slug`` ABSENT from the startup positions page is confirmed
    FLAT rather than UNKNOWN.

    The producer (``PolymarketUSExecutionClient._write_startup_position_
    evidence``, ``exec/client.py:2422-2456``) emits only slugs the venue's
    ``eof: true`` page names, so a never-traded candidate market is absent
    BY CONSTRUCTION -- three-seam Slice 4 review item 5's "ABSENT ⇒ UNKNOWN"
    reading made the PASS state unreachable for any first trade (a gate
    that cannot open is a stop, not a safety check). This is SUPERSEDED for
    candidate instruments; item 2's producer docstring ("the never-arm
    latch treats an ABSENT slug as a confirmed-flat zero",
    ``exec/client.py:2433-2438``) is the operative contract.

    Requires, in addition to :func:`startup_evidence_permits_arm`: the
    ``positions`` field is a list; NO element of it is a non-mapping row
    (the absent-branch scan must be exhaustive for an absence to mean
    anything -- a present-branch match is allowed to skip garbage rows,
    but the absent branch may not, E13); ``slug`` is genuinely absent, not
    merely unmatched because of a malformed row; and the record is FRESH.

    **Unit contract (R2-B1, L-2):** ``now_ns`` and the record's ``ts_ns``
    are BOTH wall-clock epoch nanoseconds. ``ts_ns`` is written by the exec
    client's own ``self._clock.timestamp_ns()`` (``exec/client.py:2465``).
    A caller that passes venue EVENT time here is a defect -- the
    subtraction would understate the age under feed lag and silently
    extend the ceiling (a fail-OPEN). ``now_ns`` and ``max_age_ns`` are
    required keyword-only with NO defaults (L-28): this helper is
    clock-free and measures nothing about its own caller's timing
    discipline by having one.
    """
    if not startup_evidence_permits_arm(evidence):
        return False
    assert evidence is not None  # narrowed by permits_arm above
    positions = evidence.get("positions")
    if not isinstance(positions, list):
        return False
    for row in positions:
        if not isinstance(row, dict):
            return False
    if startup_evidence_lists_slug(evidence, slug):
        return False
    ts = evidence.get("ts_ns")
    if not isinstance(ts, int) or isinstance(ts, bool):
        return False
    age_ns = now_ns - ts
    return 0 <= age_ns <= max_age_ns


def open_trial_day_latch(
    intent_latch: SubmitIntentLatch,
    *,
    key_prefix: str = DEFAULT_TRIAL_KEY_PREFIX,
) -> TrialDayLatch:
    """Bind a :class:`TrialDayLatch` to an already-opened ``SubmitIntentLatch``.

    This is NOT a second opener: ``intent_latch.shared_state_binding()`` is
    the only path to a store and lock here, and it raises
    ``SubmitIntentLockNotHeld`` the moment the intent latch's own factory
    ``with`` has exited -- so a caller cannot construct a working
    ``TrialDayLatch`` from a latch it does not currently, genuinely hold.

    ``key_prefix`` defaults to the v2 live prefix so existing callers stay
    byte-identical.
    """
    store, lock = intent_latch.shared_state_binding()
    return TrialDayLatch(store, lock, key_prefix=key_prefix, intent_latch=intent_latch)


def refuse_if_sibling_leg_traded(
    store: StateStore,
    prefix: str,
    station: str,
    climate_day: str,
    instrument_id: str,
) -> Refusal | None:
    """N2-10: refuse iff the OTHER leg (YES<->NO) of the same market slug
    already has a filled TRIAL record for this station-day.

    Pure read over ``store`` -- no flock required, no ``TrialDayLatch``
    instance required (the latch's own flock-holding accessors are for
    callers that also need to WRITE; this gate only ever reads). A fresh
    process re-running this same read after a mid-day relaunch sees the
    SAME durable record (N2-10's relaunch-ordering requirement): nothing
    here is cached in memory.

    ``instrument_id`` is this candidate leg's id -- either the BARE symbol
    (a plain slug, for a YES candidate, or a composite ``<slug>^no`` id,
    for a NO candidate) or the DOTTED ``str(InstrumentId)`` every real
    caller in ``continuous_strategy.py`` actually writes (safety review
    finding 1, 2026-09-14): ``instrument_id`` is de-dotted via
    :func:`_bare_symbol` before the sibling computation (which needs the
    bare form); ``_key`` below re-normalises the computed sibling back to
    the dotted canonical form, so the lookup matches the SAME key the
    sibling's own TRIAL record was durably written under regardless of
    which form ITS writer used. The composite form survives ``_key``'s
    slash guard exactly like any other string, since the guard only bans
    ``/``.
    """
    sibling = str(sibling_instrument_id(_leg_instrument_id(_bare_symbol(instrument_id))).symbol)
    key = _key(station, climate_day, key_prefix=prefix, key_instrument_id=sibling)
    raw = store.get(key)
    if raw is None:
        return None
    record = TrialDayRecord.from_bytes(raw)
    if record.reason not in _FILLED_REASONS:
        # The sibling was evaluated and refused, never filled -- not a
        # trade, so this leg is not excluded.
        return None
    return Refusal(SIBLING_LEG_TRADED_REASON)


#: Immutable default for ``station_day_admission``'s ``pending_fills``
#: kwarg (ADM-1) -- never a mutable ``{}`` literal as a default value.
_NO_PENDING_FILLS: Final[Mapping[str, DurableFillRecord]] = MappingProxyType({})


def station_day_admission(
    store: StateStore,
    prefix: str,
    station: str,
    climate_day: str,
    candidate_side: str,
    candidate_be: Decimal,
    *,
    existing_instrument_ids: Iterable[str] = (),
    pending_fills: Mapping[str, DurableFillRecord] = _NO_PENDING_FILLS,
) -> Refusal | None:
    """R3-7: the arm-time Sigma-q admission gate.

    Sums ``q_i`` (``BE_i`` for a YES leg, ``1 - BE_i`` for a NO leg) over
    the station-day's existing FILLED TRIAL records named by
    ``existing_instrument_ids`` plus the candidate's own ``q``, and refuses
    if the total exceeds 1. This runs BEFORE any submit, as defence against
    R3-7's finding that :func:`breezy.settlement.current_rung_hold_v2.combine_station_day`
    only enforces the same gate at TALLY time, after fills have already
    spent capital.

    ``existing_instrument_ids`` is explicit (not discovered by scanning the
    store) because :class:`~breezy.runtime.submit_intent.StateStore` is a
    minimal get/set protocol with no key enumeration -- the same reason
    :meth:`TrialDayLatch.iter_fill_records` takes an explicit
    ``instrument_ids`` argument rather than scanning. An empty tuple (the
    default) is a lone-candidate day: admitted iff the candidate's own
    ``q`` alone is at most 1.

    A record with no ``fee`` (a pre-slice-4 legacy write, or corruption)
    makes that record's ``q`` UNKNOWN. This gate never guesses in that
    case -- it refuses the whole candidate rather than silently treating
    an unknown ``q`` as zero, which could admit a station-day that would
    actually breach Sigma-q > 1.

    A record whose ``reason`` is not in the filled set (merely evaluated
    and refused) is skipped, not counted -- it never spent capital and
    contributes no ``q`` to the sum.

    Mathematically, an all-YES day can never breach this gate under the
    edge rule (``Sum(BE_i) < Sum(p_lower_i) <= 1``, R3-7) -- this
    function's arithmetic simply cannot fire there once every leg's ``fee``
    is recorded; the "never refuse a YES-only day" requirement is a
    consequence of that identity, not a special case coded here.

    ``existing_instrument_ids`` accepts EITHER the bare symbol or the
    dotted ``str(InstrumentId)`` real callers write (safety review finding
    1, 2026-09-14) -- ``_key`` below normalises either to the dotted
    canonical form before the lookup, and the stored
    ``record.instrument_id`` is normalised via :func:`_bare_symbol` before
    ``leg_of``/``_leg_instrument_id`` (which require the bare form).

    ADM-1: the create path writes a leg's durable fill record, retires the
    intent, and only THEN emits ``OrderFilled`` -- whose processing (and
    with it the leg's TRIAL/TAKEN record via ``_consume_or_flag_duplicate``)
    is queued to a LATER engine turn. A sibling rung's depth frame landing
    inside that window finds no TRIAL record for the committed leg (``raw
    is None`` below) and, before this fix, contributed zero to Sigma-q --
    undercounting a leg that has already spent capital. ``pending_fills``
    (keyed by the SAME dotted-or-bare form as ``existing_instrument_ids``,
    normalised here via :func:`_dotted_key_id`) is consulted ONLY in that
    ``raw is None`` branch (r1.1 guard 2) -- a leg with a genuine TRIAL
    record is counted from that record alone, never doubled with its own
    fill. ``be`` is the realized per-contract cost,
    ``(cumulative_cost + cumulative_fee) / cumulative_qty`` (USD/contract,
    the same unit as a TRIAL record's ``ask + fee``) -- a materially
    different number from the TAKEN path's decision-time ``ask``, which is
    why a leg is never counted from both sources. ``cumulative_qty <= 0``
    means the average cannot be safely computed, so ``q`` is UNKNOWN and
    the whole candidate is refused (r1.1 guard 1) rather than dividing by
    zero or guessing.
    """
    total_q = _cell_probability(candidate_be, candidate_side)
    for instrument_id in existing_instrument_ids:
        key = _key(station, climate_day, key_prefix=prefix, key_instrument_id=instrument_id)
        raw = store.get(key)
        if raw is None:
            fill_record = pending_fills.get(_dotted_key_id(instrument_id))
            if fill_record is None:
                continue
            if fill_record.cumulative_qty <= 0:
                return Refusal(STATION_DAY_ADMISSION_REASON)
            fill_side = leg_of(_leg_instrument_id(_bare_symbol(fill_record.instrument_id)))
            fill_be = (
                fill_record.cumulative_cost + fill_record.cumulative_fee
            ) / fill_record.cumulative_qty
            total_q += _cell_probability(fill_be, fill_side)
            continue
        record = TrialDayRecord.from_bytes(raw)
        if record.reason not in _FILLED_REASONS:
            continue
        if record.fee is None:
            return Refusal(STATION_DAY_ADMISSION_REASON)
        side = leg_of(_leg_instrument_id(_bare_symbol(record.instrument_id)))
        be = record.ask + record.fee
        total_q += _cell_probability(be, side)
    if total_q > Decimal(1):
        return Refusal(STATION_DAY_ADMISSION_REASON)
    return None
