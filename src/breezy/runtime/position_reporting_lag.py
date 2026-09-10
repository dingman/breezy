"""`PositionReportingLag` diagnostics record (Phase 0b artefact, record type only).

Authority: ``v3plan_rev6.md`` Resolution F, "Lag measurement (new Phase 0b
artefact)": ``(instrument_id, fill_ts_event, first_eof_read_ts_showing_long,
delta_ns)``, "emitted by the resolver whenever a GET-FILLED is later
confirmed on the book."

**Phase 0b ships ONLY this record type.** The emission plumbing belongs on
the ambiguous-intent resolver (``_resolve_ambiguous_intents``), which the
same plan places in Phase 1, gated on the live positions read
(``read_startup_position_evidence``, "Never-arm gate" section) -- neither
exists in ``src/`` yet (grep confirms zero hits for both names). Wiring this
record into a resolver that has not been built would be speculative; this
module has zero producers by design.

**Deliberately NOT under ``adapters/polymarket_us/exec/``.** That package is
a closed, egress-scanned set (``tests/unit/test_execution_egress_firewall_
guard.py``'s ``EXEC_PACKAGE_PATH_PREFIX`` pin) -- widening it for an inert
value object with no execution-path callers would be scope creep on a
safety/contract test, not a genuine requirement. This module is pure
(no I/O, no coroutines) and lives beside the other standalone runtime record
types instead; it can move into ``exec/`` in the same change that builds the
resolver, when there is an actual caller to justify widening that pin.

The measured quantity: how long after a fill's own ``ts_event`` a fresh
eof-complete positions read first confirms the resulting LONG.
``_REARM_MIN_DELAY_SECS=120`` stays UNVERIFIED against real values until a
live fill exists (n>=1) -- see the plan's PREREG note.
"""

from __future__ import annotations

from dataclasses import dataclass

from nautilus_trader.model.identifiers import InstrumentId

__all__ = ["PositionReportingLag"]


@dataclass(frozen=True, slots=True)
class PositionReportingLag:
    """One fill's confirmation lag: fill ``ts_event`` to the first eof-complete
    positions read that shows the resulting LONG.

    ``delta_ns`` is not free-standing derived state: it is asserted equal to
    ``first_eof_read_ts_showing_long - fill_ts_event`` at construction, so a
    caller cannot hand this record two timestamps and an inconsistent delta.
    """

    instrument_id: InstrumentId
    fill_ts_event: int
    first_eof_read_ts_showing_long: int
    delta_ns: int

    def __post_init__(self) -> None:
        if self.first_eof_read_ts_showing_long < self.fill_ts_event:
            raise ValueError(
                "PositionReportingLag: first_eof_read_ts_showing_long "
                f"({self.first_eof_read_ts_showing_long}) precedes fill_ts_event "
                f"({self.fill_ts_event}); the confirming read cannot be before the fill"
            )
        expected_delta_ns = self.first_eof_read_ts_showing_long - self.fill_ts_event
        if self.delta_ns != expected_delta_ns:
            raise ValueError(
                f"PositionReportingLag: delta_ns={self.delta_ns} does not equal "
                f"first_eof_read_ts_showing_long - fill_ts_event ({expected_delta_ns})"
            )
