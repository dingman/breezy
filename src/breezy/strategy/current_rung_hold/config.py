"""Configuration for the ``current_rung_hold`` strategy (build in progress;
see ``docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md``, build order
step 4).

Every field here is a BUILD-side decision pinned by the peer-reviewed
blueprint and the Grok live-small spec rev 2
(``docs/evidence/grok_live_small_spec_rev2_2026-09-04.md`` §5), not an
operator knob -- see the module-level docstring section "NOT operator
controls" below. Unlike ``RunningExtremeLockConfig`` and
``CliSettlementPrintLockConfig`` (which defer their construction-time
refusals to the owning ``Strategy.__init__``), this config validates itself
in ``__post_init__``: every value fixed here is a STATIC property of the
package, not something a wiring site could legitimately vary, so there is no
reason to let an invalid value survive past construction.

Station allow-list (A14)
-------------------------

``SUPPORTED_STATIONS`` is exactly the four dense stations the archive study
(``archive_table.py``) was measured on. NYC/KNYC is deliberately excluded:
it is an HOURLY-only station (no 5-minute NWS feed), so the
``stale_observation_hours`` bound this package pins (0.75h / 45min, the
spec's measured value for the five-minute-feed stations) is miscalibrated
for it -- see the spec's ``stale_observation_hours`` table, which gives KNYC
its own, larger, NOT-YET-ADOPTED bound and states "Not this package".
Constructing with any station outside the allow-list is refused loudly
(:class:`UnsupportedStationError`) rather than silently ignored -- a
mis-wired KNYC must fail at startup, not trade on a stale-declared-fresh
observation forever.

``required_fee_coefficient`` / ``executable_ask_lower`` / ``executable_ask_upper``
-------------------------------------------------------------------------------------

These three are validated for TYPE/PRESENCE only here. The actual
enforcement -- refusing an instrument whose real fee coefficient does not
equal ``required_fee_coefficient`` (``fee_schedule_mismatch``), and the
strict-inequality executable-ask band check -- happens in ``decision.py`` at
decision time, against the market's live venue facts, not here. This config
only carries the constants decision time reads.

NOT operator controls
----------------------

The two operator-reserved caps (maximum daily trading budget; maximum
notional per position) are deliberately absent from this config. They are
supplied by ``operator_controls`` at runtime, exactly as every other weather
strategy in this repo leaves them unset in its own ``StrategyConfig`` --- see
``breezy.strategy.weather_common.risk.RiskLimits`` and the sibling configs'
docstrings ("the two operator-reserved dollar controls ... stay unset here").
``test_current_rung_hold_config.py::test_config_has_no_operator_reserved_field_name``
asserts no field name here even mentions one.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from nautilus_trader.trading.config import StrategyConfig

from breezy.strategy.current_rung_hold.archive_table import CORPUS_SHA256

__all__ = [
    "SUPPORTED_STATIONS",
    "AllowShortNotPermittedError",
    "ArchiveTablePinMismatchError",
    "CurrentRungHoldConfig",
    "InvalidOrderQuantityError",
    "UnsupportedStationError",
]

#: The four dense stations the frozen archive table (``archive_table.py``)
#: was measured on. NYC/KNYC is excluded -- see the module docstring.
SUPPORTED_STATIONS: Final[tuple[str, ...]] = ("LAX", "MDW", "MIA", "SFO")


class UnsupportedStationError(ValueError):
    """Raised when ``stations`` names anything outside :data:`SUPPORTED_STATIONS`.

    NYC/KNYC is the station this exists to catch (A14, hourly-only feed,
    ``0.75h`` staleness bound miscalibrated) but the check is a plain
    allow-list, not an NYC-specific carve-out -- any unmeasured sixth
    station is refused the same way.
    """


class InvalidOrderQuantityError(ValueError):
    """Raised when ``order_quantity`` is not exactly 1.

    The live-small spec is one contract, full stop (§5 /
    ``mb_current_rung_edge_study.py:632-644``'s taken test is applied to a
    single candidate). A different quantity is not a smaller or larger
    version of the same strategy; it is untested sizing with no archive
    backing, so it is refused rather than accepted and silently mispriced.
    """


class AllowShortNotPermittedError(ValueError):
    """Raised when ``allow_short`` is constructed ``True``.

    Mirrors every other weather strategy's ``allow_short: bool = False``
    pin (``RunningExtremeLockConfig``, ``CliSettlementPrintLockConfig``):
    LONG_YES only, and this is the only naked-short control in the system
    regardless (``breezy.strategy.weather_common.risk.RiskLimits.allow_short``).
    Unlike those configs, which rely on the default never being flipped,
    this one refuses the flip outright -- see L-22 in
    ``docs/core/LESSONS.md``: a safety primitive's exclusion must be
    unforgeable, not merely offered as a default.
    """


class ArchiveTablePinMismatchError(ValueError):
    """Raised when ``archive_table_pin`` does not equal
    ``archive_table.CORPUS_SHA256``.

    This config carries its own copy of the pin (rather than reading the
    module constant directly at every call site) so a construction call
    that explicitly names the WRONG corpus fails loudly instead of silently
    picking up whatever ``archive_table.py`` happens to ship. The default
    always tracks the real constant; only an explicit override can trigger
    this.
    """


class CurrentRungHoldConfig(StrategyConfig, frozen=True):
    """Configuration for the (not yet built) ``CurrentRungHoldStrategy``.

    Parameters
    ----------
    stations : tuple[str, ...]
        Every station this instance may trade. Must be a subset of
        :data:`SUPPORTED_STATIONS`; NYC/KNYC and any other unmeasured
        station raise :class:`UnsupportedStationError` at construction.
    stale_observation_hours : float
        The observation-liveness bound (age = measurement/issuance time,
        never ingest time). Pinned at 0.75h (45 min) for the five-minute-feed
        stations this package trades -- see the spec's
        ``stale_observation_hours`` table. Unlike
        ``RunningExtremeLockConfig``'s field of the same name, this one is
        NOT ``float | None`` with no default: the spec gives one number for
        every supported station, so there is nothing for a call site to
        legitimately override.
    required_fee_coefficient : Decimal
        The fee coefficient the archive selector's break-even constant
        (``FEE_THETA_FOR_BE``) was computed against. ``decision.py`` refuses
        a traded instrument whose real fee coefficient does not equal this
        value (``fee_schedule_mismatch``, counted) -- checked at decision
        time, not here.
    executable_ask_lower, executable_ask_upper : Decimal
        The open executable-ask band; ``decision.py`` requires
        ``executable_ask_lower < ask < executable_ask_upper`` (strict) on a
        quote with size at least ``minimum_displayed_size`` before that
        quote can be the day's candidate.
    minimum_displayed_size : int
        Minimum displayed depth (in contracts) an ask must carry to be
        considered executable.
    order_quantity : int
        Contracts per order. Must be exactly 1
        (:class:`InvalidOrderQuantityError` otherwise) -- the live-small
        spec is one contract.
    allow_short : bool
        Must stay ``False``; constructing ``True`` raises
        :class:`AllowShortNotPermittedError`. See that error's docstring.
    archive_table_pin : str
        Must equal ``archive_table.CORPUS_SHA256``
        (:class:`ArchiveTablePinMismatchError` otherwise) -- this config can
        only ever point at the one frozen corpus the archive table was
        actually generated from.
    entry_only_halt : bool
        Fixed ``True``. The settlement halt applies only to NEW entries
        (never a flatten/close path -- this strategy holds to settlement by
        design, see the blueprint's "Hold-to-settlement" row).

    Not present: the two operator-reserved dollar controls (maximum daily
    trading budget; maximum notional per position). See the module
    docstring's "NOT operator controls" section.
    """

    stations: tuple[str, ...] = ("LAX", "MDW", "MIA", "SFO")
    stale_observation_hours: float = 0.75
    required_fee_coefficient: Decimal = Decimal("0.06")
    executable_ask_lower: Decimal = Decimal("0.05")
    executable_ask_upper: Decimal = Decimal("0.95")
    minimum_displayed_size: int = 1
    order_quantity: int = 1
    allow_short: bool = False
    archive_table_pin: str = CORPUS_SHA256
    #: Fixed. See the field's docstring above.
    entry_only_halt: bool = True

    def __post_init__(self) -> None:
        unsupported = [station for station in self.stations if station not in SUPPORTED_STATIONS]
        if unsupported:
            raise UnsupportedStationError(
                "stations must be a subset of "
                f"{SUPPORTED_STATIONS!r}; unsupported: {unsupported!r} "
                "(NYC/KNYC is hourly-only and excluded, see the module "
                "docstring)"
            )
        if self.order_quantity != 1:
            raise InvalidOrderQuantityError(
                f"order_quantity must be exactly 1, was {self.order_quantity!r}"
            )
        if self.allow_short:
            raise AllowShortNotPermittedError(
                "allow_short must stay False; this package is LONG_YES only"
            )
        if self.archive_table_pin != CORPUS_SHA256:
            raise ArchiveTablePinMismatchError(
                "archive_table_pin must equal archive_table.CORPUS_SHA256 "
                f"({CORPUS_SHA256!r}), was {self.archive_table_pin!r}"
            )
