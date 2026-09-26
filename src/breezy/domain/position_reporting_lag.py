"""`PositionReportingLag` diagnostics record (R-7-IMPL: record type + producer).

Authority: ``v3plan_rev6.md`` Resolution F, "Lag measurement (new Phase 0b
artefact)": ``(instrument_id, fill_ts_event, first_eof_read_ts_showing_long,
delta_ns)``. Where this record is emitted from was an OPEN ruling
(``docs/core/PROGRESS.md`` R-7) until
``docs/evidence/RULING_R-7_position_reporting_lag_2026-09-26.md`` decided it:
**KEEP-AND-WIRE on the create-path accept-fill branch**, never the resolver
path (the delta there comes out negative -- positions are read before
``now_ns`` is taken -- and the GET response carries no venue fill instant).
The producer lives in
:meth:`~breezy.adapters.polymarket_us.exec.client.PolymarketUSExecutionClient.
_match_position_lag`; this module still defines only the record shape and
performs no I/O of its own.

**Moved here (R-7-IMPL, ``git mv`` from ``breezy.runtime``) because
``breezy.adapters`` sits BELOW ``breezy.runtime`` in the import-linter layer
contract** (``pyproject.toml`` ``[tool.importlinter]``), so
``exec/client.py`` cannot import a ``breezy.runtime`` module. ``domain`` is
the BOTTOM layer -- every other layer, ``adapters`` included, may import it.

**Still deliberately NOT under ``adapters/polymarket_us/exec/``.** That
package is a closed, egress-scanned set (``tests/unit/test_execution_egress_
firewall_guard.py``'s ``EXEC_PACKAGE_PATH_PREFIX`` pin) -- widening it for an
inert value object with no execution-path callers of ITS OWN would be scope
creep on a safety/contract test, not a genuine requirement. This module is
pure (no I/O, no coroutines, no Nautilus clock access) and lives beside the
other standalone domain record types instead.

The measured quantity: how long after a fill's own venue-sourced
``ts_event`` a fresh eof-complete positions read first confirms the
resulting LONG. ``_REARM_MIN_DELAY_SECS=120`` stays UNVERIFIED against real
values until a live fill exists (n>=1) -- see the plan's PREREG Amendment A2
note.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from nautilus_trader.model.identifiers import InstrumentId

__all__ = ["PositionReportingLag"]

#: The ONE value :attr:`PositionReportingLag.fill_ts_event_source` may carry
#: (RULING R-7, adversary condition): the fill instant is always the venue's
#: own ``transactTime``, never a local-clock substitute. Naming the source on
#: the record, rather than assuming it, makes a future second producer that
#: DID fall back to local time fail construction instead of silently
#: contaminating the same diagnostic with poll-cadence noise.
FILL_TS_EVENT_SOURCE_VENUE_TRANSACT_TIME: Final[str] = "venue_transactTime"


@dataclass(frozen=True, slots=True)
class PositionReportingLag:
    """One fill's confirmation lag: fill ``ts_event`` to the first eof-complete
    positions read that shows the resulting LONG.

    ``delta_ns`` is not free-standing derived state: it is asserted equal to
    ``first_eof_read_ts_showing_long - fill_ts_event`` at construction, so a
    caller cannot hand this record two timestamps and an inconsistent delta.

    ``fill_ts_event_source`` is REQUIRED (RULING R-7) and must equal
    :data:`FILL_TS_EVENT_SOURCE_VENUE_TRANSACT_TIME` -- the adversary
    condition that closed the ruling: a producer that fell back to a local
    clock on a missing ``tsEvent`` would reintroduce poll-cadence
    contamination with nothing on the record to mark it. Refusing any other
    value is deliberate: this record can never be misread as measuring
    anything but the venue's own instant.
    """

    instrument_id: InstrumentId
    fill_ts_event: int
    first_eof_read_ts_showing_long: int
    delta_ns: int
    fill_ts_event_source: str

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
        if self.fill_ts_event_source != FILL_TS_EVENT_SOURCE_VENUE_TRANSACT_TIME:
            raise ValueError(
                "PositionReportingLag: fill_ts_event_source="
                f"{self.fill_ts_event_source!r} must equal "
                f"{FILL_TS_EVENT_SOURCE_VENUE_TRANSACT_TIME!r}; a local-clock "
                "fallback is exactly what RULING R-7 forbids"
            )
