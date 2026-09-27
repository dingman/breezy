"""Compose ``CurrentRungHoldStrategy`` instances for the trading process.

The composition ROOT (``breezy.app.trade``) is the sole opener of the
submit-intent latch for the process lifetime. This module never calls
``open_submit_intent_latch``. It binds each station strategy to the
already-opened latch via ``open_trial_day_latch`` (L-22: exclusion is
unforgeable, not offered).

Catalog-derived ids are advisory for the pre-build fast-fail only. The live
``PolymarketUSInstrumentProvider`` is authoritative; ``on_start`` re-resolves
from ``self.cache``. Per-station degradation (L-23): refuse to start only when
ALL stations resolve zero instruments; otherwise skip + count + log the rest.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.adapters.polymarket_us.errors import VenuePayloadError
from breezy.adapters.polymarket_us.symbology import (
    instrument_id_to_slug,
    leg_of,
    parse_weather_slug,
    sibling_instrument_id,
)
from breezy.domain.weather_bucket_facts import (
    Measure,
    WeatherFactsUnavailableError,
    read_weather_bucket_facts,
)
from breezy.runtime.build_sha import resolve_build_revision
from breezy.runtime.component_health_watch import COMPONENT_STATE_TOPIC
from breezy.runtime.health import AlertPayload, AlertState, emit_alert, resolve_alert_sink
from breezy.runtime.order_enablement import OrderSubmissionPermit
from breezy.runtime.settings import SettingsError
from breezy.runtime.submit_intent import SubmitIntentLatch
from breezy.runtime.trade_supervisor_core import (
    ZERO_INSTRUMENTS_REFUSAL_PREFIX,
    ZERO_INSTRUMENTS_REFUSAL_SUFFIX,
)
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_strategy import (
    ContinuousRungHoldStrategy,
    Phase0PermitForbiddenError,
)
from breezy.strategy.current_rung_hold.diagnostics_summary import DiagnosticsSummarySink
from breezy.strategy.current_rung_hold.exit_decider import decide_exit
from breezy.strategy.current_rung_hold.monitor_store import MarkBuffer
from breezy.strategy.current_rung_hold.monitor_wiring import build_monitor_callables
from breezy.strategy.current_rung_hold.offer_tape import OfferTape
from breezy.strategy.current_rung_hold.position_monitor import PositionMonitor
from breezy.strategy.current_rung_hold.strategy import CurrentRungHoldStrategy
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    DEFAULT_TRIAL_KEY_PREFIX,
    TrialDayLatch,
    open_trial_day_latch,
)
from breezy.strategy.weather_common.halt_detector import HaltDetector
from breezy.strategy.weather_common.refusals import RefusalAlerter

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.persistence.family_manifest import FamilyManifest

__all__ = [
    "InstrumentStationMismatchError",
    "NoTradableInstrumentsError",
    "OverlappingExternalOrderClaimsError",
    "build_continuous_rung_hold_strategies",
    "build_current_rung_hold_strategies",
    "family_halt_submit_veto",
    "install_current_rung_hold_refusal_watch",
    "make_trial_day_latch_factory",
    "phase1_sending_permit",
    "resolve_station_instrument_ids",
    "strategy_component_id",
]

logger = logging.getLogger(__name__)

_COMPONENT_ID_PREFIX: Final[str] = "CurrentRungHoldStrategy"
_CONTINUOUS_COMPONENT_ID_PREFIX: Final[str] = "ContinuousRungHoldStrategy"

#: INC-5 (intra-day position monitor, plan §2 "no new env var"). Sibling of
#: the quote-tape catalog root, NEVER nested under it (`monitor_store.py`'s
#: own docstring; the trader writes no tape of its own, `node_config.py:
#: 748-750`).
_MONITOR_CATALOG_DIRNAME: Final[str] = "monitor"
_MONITOR_SUMMARIES_DIRNAME: Final[str] = "summaries"
_NS_PER_MINUTE: Final[int] = 60_000_000_000
#: GAP fix 2026-09-15 (offer-tape postmortem observability): sibling of the
#: quote-tape catalog root, mirroring `_MONITOR_CATALOG_DIRNAME` above --
#: NEVER nested under the catalog. No env var (L-39): a build-side default,
#: never an operator control.
_DECISIONS_DIRNAME: Final[str] = "decisions"

#: Review finding 1: a WAIT-state diagnostic is not a refusal -- passed to
#: `RefusalAlerter`'s injectable vocabulary so its event name/detail never
#: assert an order was refused when none was ever formed. Never applied to
#: `strategy.refusals`' alerter, which keeps the unmodified refusal default.
_DIAGNOSTICS_VOCABULARY: Final[dict[str, str]] = {
    "event_suffix": "WAIT",
    "noun": "tick(s)",
    "verb": "observed",
    "detail_note": " (pre-decision WAIT, not a refusal)",
}

#: Review finding 2: `AlertState.DEFAULT_RENOTIFY_AFTER_NS` (24h) is longer
#: than the whole `[12:00,17:00)` LST decision window (~5h), so a diagnostic
#: alerted through the unmodified default would fire ONCE per process
#: lifetime -- never showing its count grow across a covered afternoon. The
#: refusal alerters keep the 24h default unchanged; diagnostics AND
#: position alerters share this shorter, intra-session cadence.
_DIAGNOSTICS_RENOTIFY_AFTER_NS: Final[int] = 15 * 60 * 1_000_000_000  # 15 minutes

#: O-1 log-only position observability. Never applied to `strategy.refusals`
#: or `strategy.diagnostics`. Event names land in the `..._POSITION` family
#: so a fill cannot be misread as a refusal.
_POSITION_VOCABULARY: Final[dict[str, str]] = {
    "event_suffix": "POSITION",
    "noun": "event(s)",
    "verb": "observed",
    "detail_note": " (log-only, never an order)",
}


class _AlerterBinding(NamedTuple):
    """One (counter, alerter-attr, vocabulary, renotify) row.

    Intra-module only: the three current_rung_hold alerters share this
    table so composition wiring and the strategy reporter stay in lockstep.
    Sibling strategy files keep their own copy-paste; that is a different
    axis and is left alone.
    """

    counter_attr: str
    alerter_attr: str
    vocabulary: dict[str, str]
    renotify_after_ns: int | None


_ALERTER_BINDINGS: Final[tuple[_AlerterBinding, ...]] = (
    _AlerterBinding("refusals", "refusal_alerter", {}, None),
    _AlerterBinding(
        "diagnostics",
        "diagnostics_alerter",
        _DIAGNOSTICS_VOCABULARY,
        _DIAGNOSTICS_RENOTIFY_AFTER_NS,
    ),
    _AlerterBinding(
        "position_events",
        "position_alerter",
        _POSITION_VOCABULARY,
        _DIAGNOSTICS_RENOTIFY_AFTER_NS,
    ),
)


class NoTradableInstrumentsError(SettingsError):
    """Raised when every supported station resolves zero instruments.

    A ``SettingsError`` subclass so the trading process exits 2 via the
    existing configuration-error path.
    """


class OverlappingExternalOrderClaimsError(SettingsError):
    """AUD-13c: two composed strategies claim the same instrument.

    Checked BEFORE ``Trader.add_strategy``, where Nautilus would otherwise
    raise ``InvalidConfiguration`` mid-assembly (``execution/engine.pyx:552-557``).
    A ``SettingsError`` so the process exits 2 via the configuration path.
    """


class InstrumentStationMismatchError(RuntimeError):
    """An id bucketed under one station re-parses to another -- the station
    pairing guard in :func:`resolve_station_instrument_ids`."""


def strategy_component_id(station: str) -> str:
    """Unique ``strategy_id`` per station -- ``Trader.add_strategy`` rejects a collision."""
    return f"{_COMPONENT_ID_PREFIX}-{station}"


def make_trial_day_latch_factory(
    intent_latch: SubmitIntentLatch,
    *,
    key_prefix: str = DEFAULT_TRIAL_KEY_PREFIX,
) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    """Return a factory that binds a ``TrialDayLatch`` to *intent_latch*.

    The factory's context manager does NOT close the intent latch: the
    composition root owns that flock for the process lifetime. Each strategy
    ``on_start`` enters this factory; ``on_stop`` exits it.

    ``key_prefix`` defaults to the v2 live prefix so existing callers stay
    byte-identical.
    """

    @contextmanager
    def _factory() -> Iterator[TrialDayLatch]:
        yield open_trial_day_latch(intent_latch, key_prefix=key_prefix)

    return _factory


def family_halt_submit_veto(trial_day_latch: TrialDayLatch) -> Callable[[], str | None]:
    """Item 4 (slice 4 review, plan rev 6.1): the exec client's synchronous
    submit-time family-halt veto.

    Returns a zero-argument callable matching the exec client's injected
    ``submit_veto: Callable[[], str | None]`` kwarg
    (``adapters/polymarket_us/exec/client.py`` -- consulted in
    ``_submit_order`` immediately before the permit spend, the SAME
    no-``await`` chokepoint shape as SAFETY C1's ``is_latched()`` re-check,
    so a non-None reason denies with zero money moved and no
    ``_trading_refusals`` entry). Every call is a synchronous, read-only
    ``TrialDayLatch.is_family_halted()`` under the SAME flock
    ``trial_day_latch`` already holds -- never a fresh open, never an await.

    INTEGRATION COMPLETE: ``PolymarketUSExecClientConfig.submit_veto``
    (``adapters/polymarket_us/config.py``) carries this callable through
    ``adapters/polymarket_us/factories.py`` (``config.submit_veto``) and
    ``runtime.node_config.build_trade_node_config`` (a ``submit_veto``
    parameter, forwarded the same way ``submit_intent_latch`` already was)
    into ``runtime.trade_cli.run``, which accepts its own ``submit_veto``
    parameter and threads it to the exec client config. ``app/trade.py::run``
    is the one caller that builds the callable -- via
    ``family_halt_submit_veto(family_halt_latch)`` at its v3 composition call
    site, where ``family_halt_latch`` is a ``TrialDayLatch`` opened directly
    against the process's already-opened intent latch -- and passes it to
    ``trade_cli.run(submit_veto=submit_veto, ...)``. Live end-to-end proof:
    ``tests/unit/test_current_rung_hold_ambiguous_resolver.py::
    test_a_family_halt_veto_denies_wait_class_and_spends_zero_permit_slots``.
    """

    def _veto() -> str | None:
        return "family_halt" if trial_day_latch.is_family_halted() else None

    return _veto


def phase1_sending_permit(
    *,
    sending_family_id: str,
    permit: OrderSubmissionPermit | None,
    phase0_shadow: bool = False,
) -> OrderSubmissionPermit | None:
    """WP-11b (active-family registry, cardinality-1): route the single
    sending family's permit.

    Replaces the retired two-family ``phase1_family_permits`` (a
    ``tuple[Permit, Permit]`` of exactly one non-``None`` slot) and the
    retired ``phase0_family_permits`` (kept for the Phase 0 shadow
    composition, folded in here). Cardinality-1 is now STRUCTURAL: this
    function's return type is a single ``OrderSubmissionPermit | None``, so
    it is not merely refused to express two sending permits -- there is no
    shape in which it COULD.

    ``sending_family_id`` must be non-empty (``app/trade.py::run`` only
    calls this once ``settings.sending_family_id is not None``; a caller
    that reaches here with a blank string is a bug in that caller, not a
    legitimate "no family" case -- that case never calls this function at
    all). ``phase0_shadow=True`` folds forward the retired
    ``phase0_family_permits``'s Phase 0 behaviour (composed, but the
    permit is deliberately withheld) -- the sending family still boots, but
    ``permit`` is never handed to it, matching the old "v3 never holds the
    Phase 0 permit" contract generalised to whichever single family is
    named. It can never, even under this hatch, cause a SECOND sending id
    to receive a permit -- there is only ever the one ``sending_family_id``
    argument.
    """
    if not sending_family_id:
        raise SettingsError(
            "phase1_sending_permit: sending_family_id must be non-empty"
        )
    if phase0_shadow:
        return None
    return permit


def _facts_from_instrument(instrument: object) -> tuple[str, dt.date, Measure] | None:
    info = getattr(instrument, "info", None)
    try:
        facts = read_weather_bucket_facts(info)
    except WeatherFactsUnavailableError:
        facts = None
    if facts is not None:
        return facts.settlement_station, facts.climate_day, facts.measure

    instrument_id = getattr(instrument, "id", None)
    if not isinstance(instrument_id, InstrumentId):
        return None
    try:
        slug = instrument_id_to_slug(instrument_id)
    except VenuePayloadError:
        return None
    parsed = parse_weather_slug(slug)
    if parsed is None:
        return None
    try:
        measure = Measure(parsed.measure)
        climate_day = dt.date.fromisoformat(parsed.climate_date)
    except ValueError:
        return None
    return parsed.city.upper(), climate_day, measure


def resolve_station_instrument_ids(
    catalog_root: Path,
    today_by_station: Mapping[str, dt.date],
) -> dict[str, tuple[InstrumentId, ...]]:
    """Read the catalog UNFILTERED and keep today's HIGH markets per station.

    Identifier-filtered ``catalog.instruments(instrument_ids=[...])`` silently
    omits every flat-written row -- always call ``instruments()`` with no ids.

    ``catalog.instruments()`` returns ONE ROW PER RECORDED DEFINITION: the
    quote-tape recorder re-emits an instrument's definition on every
    discovery cycle, so the same ``InstrumentId`` can appear many times.
    De-duplicated per station on ``id``, keeping first-seen order -- the same
    rule ``run_weather_strategy_backtests.py::_select_capture_instruments``
    already applies to the paper-replay driver -- so each id is subscribed to
    exactly once downstream in ``CurrentRungHoldStrategy.on_start``.
    """
    return _bucket_station_instrument_ids(_read_catalog_instruments(catalog_root), today_by_station)


def _read_catalog_instruments(catalog_root: Path) -> list[object]:
    raw = ParquetDataCatalog(str(catalog_root)).instruments()
    return list(raw) if raw is not None else []


def _bucket_station_instrument_ids(
    instruments: Sequence[object],
    today_by_station: Mapping[str, dt.date],
) -> dict[str, tuple[InstrumentId, ...]]:
    """``resolve_station_instrument_ids``'s bucketing over an already-read
    catalog, so one boot can bucket more than one day off ONE read."""
    buckets: dict[str, dict[InstrumentId, None]] = {
        station: {} for station in today_by_station
    }
    for instrument in instruments:
        parsed = _facts_from_instrument(instrument)
        if parsed is None:
            continue
        station, climate_day, measure = parsed
        if measure is not Measure.HIGH:
            continue
        if station not in today_by_station:
            continue
        if climate_day != today_by_station.get(station):
            continue
        instrument_id = getattr(instrument, "id", None)
        if not isinstance(instrument_id, InstrumentId):
            continue
        # NO-1/S2 review finding: `_facts_from_instrument` reads bucket facts
        # off `info`, which the NO leg shares byte-for-byte with its YES
        # sibling, so an unfiltered pass would admit BOTH legs into one
        # station's `instrument_ids` and double every rung. `leg_of` is
        # purely id-derived (never reads `info`), so a legacy instrument with
        # no composite suffix is still correctly admitted as YES. S3 lifts
        # this gate deliberately, once the decision layer is NO-aware.
        if leg_of(instrument_id) != "yes":
            continue
        # dict-as-ordered-set: de-duplicates on id while keeping the FIRST
        # recorded definition's position -- a plain `list` would re-append
        # every re-emitted duplicate.
        buckets[station].setdefault(instrument_id, None)

    # id -> re-parsed settlement station, built once (not per bucket) so the
    # pairing guard below costs one pass, not a rescan per id.
    station_by_id: dict[InstrumentId, str] = {}
    for instrument in instruments:
        instrument_id = getattr(instrument, "id", None)
        if not isinstance(instrument_id, InstrumentId) or instrument_id in station_by_id:
            continue
        parsed = _facts_from_instrument(instrument)
        if parsed is not None:
            station_by_id[instrument_id] = parsed[0]

    resolved = {station: tuple(ids) for station, ids in buckets.items()}
    for station, ids in resolved.items():
        # Pairing guard: every id this function hands to a station's
        # `CurrentRungHoldConfig.instrument_ids` must itself re-parse to
        # that same station -- a bucketing bug here would silently
        # subscribe one station's strategy to another station's market.
        for instrument_id in ids:
            reparsed_station = station_by_id.get(instrument_id)
            if reparsed_station != station:
                raise InstrumentStationMismatchError(
                    f"resolve_station_instrument_ids: {instrument_id} bucketed under "
                    f"{station!r} re-parses to {reparsed_station!r}"
                )
    return resolved


def _zero_instruments_message(
    resolved: Mapping[str, tuple[InstrumentId, ...]],
    today_by_station: Mapping[str, dt.date],
) -> str:
    dates = sorted({day.isoformat() for day in today_by_station.values()})
    date_part = dates[0] if len(dates) == 1 else ",".join(dates)
    counts = " ".join(f"{station}={len(resolved[station])}" for station in resolved)
    # [FU-17] Built from the shared marker constants (runtime, imported
    # downward -- see the layers contract) so the supervisor's boot-retry
    # classifier stays in lockstep with this message, byte-for-byte.
    return (
        f"{ZERO_INSTRUMENTS_REFUSAL_PREFIX} {date_part} "
        f"({counts}){ZERO_INSTRUMENTS_REFUSAL_SUFFIX}"
    )


def _station_claims(
    today: tuple[InstrumentId, ...],
    yesterday: tuple[InstrumentId, ...],
) -> tuple[InstrumentId, ...]:
    """AUD-13c (ruling R-2 = R2-B): the ids one continuous station strategy
    claims via the native ``StrategyConfig.external_order_claims``
    (``trading/config.py:91``, registered by ``Trader.add_strategy`` at
    ``trading/trader.py:435``). Without a claim, reconciliation books every
    report under ``StrategyId("EXTERNAL")``
    (``live/execution_engine.py:3551-3556``).

    Today and yesterday (a fill is reconciled at the next daily boot, before
    its market settles), YES and NO leg (a NO buy fills on the NO-leg id).
    Station-scoped by construction -- both inputs come from the same
    per-station bucketing -- so no two strategies claim one id (a double
    claim raises, ``execution/engine.pyx:552-557``). Older positions still
    reconcile EXTERNAL, exactly as before this item.
    """
    claims: dict[InstrumentId, None] = {}
    for instrument_id in (*today, *yesterday):
        claims.setdefault(instrument_id, None)
        claims.setdefault(sibling_instrument_id(instrument_id), None)
    return tuple(claims)


def _assert_disjoint_claims(strategies: Sequence[ContinuousRungHoldStrategy]) -> None:
    """Refuse two composed strategies claiming one instrument, BEFORE
    ``Trader.add_strategy`` -- naming the instrument and both strategies."""
    owner: dict[InstrumentId, str] = {}
    for strategy in strategies:
        for instrument_id in strategy.external_order_claims:
            first = owner.setdefault(instrument_id, str(strategy.id))
            if first != str(strategy.id):
                raise OverlappingExternalOrderClaimsError(
                    f"external_order_claims: {instrument_id} is claimed by both "
                    f"{first} and {strategy.id}; refusing to compose"
                )


def _station_config(
    *,
    instrument_ids: tuple[InstrumentId, ...],
    station: str,
    strategy_id: str,
    required_fee_coefficient: Decimal | None,
    external_order_claims: tuple[InstrumentId, ...] | None = None,
) -> CurrentRungHoldConfig:
    """One station's config, priced at the sending family's REGISTERED theta.

    ``required_fee_coefficient`` is the family manifest's own
    ``taker_fee_coefficient``, threaded down by the composition root
    (``app/trade.py``) -- never read from the environment and never a
    constant here. ``None`` means "no family opinion", and the config keeps
    its own pinned ``Decimal("0.06")`` default, so every pre-existing caller
    (tests, the backtest harness) is byte-identical to before.

    Nautilus sets ``Strategy.id`` to ``f"{strategy_id}-{order_id_tag}"``
    (``trading/strategy.pyx:148-149``). The prefix is the class name; the
    tag is the station, so both uniqueness checks at ``trader.py:400,416``
    pass.

    ``external_order_claims`` ``None`` (v2's builder) leaves the native
    default -- no claim.
    """
    claims = None if external_order_claims is None else list(external_order_claims)
    if required_fee_coefficient is None:
        return CurrentRungHoldConfig(
            instrument_ids=instrument_ids,
            stations=(station,),
            strategy_id=strategy_id,
            order_id_tag=station,
            external_order_claims=claims,
        )
    return CurrentRungHoldConfig(
        instrument_ids=instrument_ids,
        stations=(station,),
        strategy_id=strategy_id,
        order_id_tag=station,
        required_fee_coefficient=required_fee_coefficient,
        external_order_claims=claims,
    )


def build_current_rung_hold_strategies(
    *,
    catalog_root: Path,
    today_by_station: Mapping[str, dt.date],
    trial_day_latch_factory: Callable[[], AbstractContextManager[TrialDayLatch]],
    order_submission_permit: OrderSubmissionPermit | None = None,
    required_fee_coefficient: Decimal | None = None,
) -> tuple[CurrentRungHoldStrategy, ...]:
    """One strategy per supported station that resolved at least one instrument.

    ``orders_enabled`` is never passed: the config default is False and
    constructing True is refused. ``strategy_id`` / ``order_id_tag`` are set
    per station so ``Trader.add_strategy`` uniqueness checks both pass.

    ``order_submission_permit`` is the sealed capability minted by
    ``app/trade.py::main`` via ``OrderSubmissionPermit.issue`` -- ``None`` is
    the shadow default (no order path reachable), passed unchanged to every
    station's strategy instance.
    """
    resolved = resolve_station_instrument_ids(catalog_root, today_by_station)
    if all(len(ids) == 0 for ids in resolved.values()):
        raise NoTradableInstrumentsError(_zero_instruments_message(resolved, today_by_station))

    strategies: list[CurrentRungHoldStrategy] = []
    for station in today_by_station:
        instrument_ids = resolved[station]
        if not instrument_ids:
            logger.warning(
                "current_rung_hold: skipping %s; resolved 0 instruments for %s",
                station,
                today_by_station[station].isoformat(),
            )
            continue
        config = _station_config(
            instrument_ids=instrument_ids,
            station=station,
            strategy_id=_COMPONENT_ID_PREFIX,
            required_fee_coefficient=required_fee_coefficient,
        )
        strategies.append(
            CurrentRungHoldStrategy(
                config,
                trial_day_latch_factory=trial_day_latch_factory,
                order_submission_permit=order_submission_permit,
            )
        )
    return tuple(strategies)


def _decisions_dir(catalog_root: Path) -> Path:
    """F-2 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): the ONE `decisions/`
    directory `_default_offer_tape_path` and `_default_diagnostics_summary_
    path` both resolve under -- a sibling of the quote-tape catalog root,
    never nested under it, exactly as `_default_offer_tape_path` already
    resolved it inline before this extraction (pure DRY, no path change).
    """
    return catalog_root.parent / _DECISIONS_DIRNAME


def _default_offer_tape_path(catalog_root: Path, today_by_station: Mapping[str, dt.date]) -> Path:
    """GAP fix 2026-09-15: the live default JSONL sidecar for the shared
    `OfferTape` -- a sibling of the quote-tape catalog root (never nested
    under it, mirroring `monitor_root` above), one file per day. Naturally
    rotates: `today_by_station` changes at the next daily boot
    (`breezy-trade-supervisor`), so a fresh process always gets a fresh
    file. `min(...)` over `today_by_station.values()` is deterministic
    (stations share the same UTC calendar day in every real deployment) and
    never raises on an empty mapping in practice -- `build_continuous_rung_
    hold_strategies` already requires at least one resolved station above.
    """
    day = min(today_by_station.values())
    return _decisions_dir(catalog_root) / f"offer_tape_{day.isoformat()}.jsonl"


def _default_diagnostics_summary_path(
    catalog_root: Path, today_by_station: Mapping[str, dt.date]
) -> Path:
    """F-2: the live default JSONL sidecar for the shared
    `DiagnosticsSummarySink` -- same `decisions/` directory and the SAME
    boot-day naming convention as `_default_offer_tape_path`, so both
    sidecars rotate together at the next daily boot.
    """
    day = min(today_by_station.values())
    return _decisions_dir(catalog_root) / f"diagnostics_summary_{day.isoformat()}.jsonl"


def build_continuous_rung_hold_strategies(
    *,
    catalog_root: Path,
    today_by_station: Mapping[str, dt.date],
    trial_day_latch_factory: Callable[[], AbstractContextManager[TrialDayLatch]],
    order_submission_permit: OrderSubmissionPermit | None = None,
    offer_tape_path: Path | None = None,
    diagnostics_summary_path: Path | None = None,
    phase0_permit_guard: bool = True,
    enable_position_monitor: bool = True,
    exit_manifest: FamilyManifest | None = None,
    required_fee_coefficient: Decimal | None = None,
) -> tuple[ContinuousRungHoldStrategy, ...]:
    """One continuous-rung-hold strategy per supported station with instruments.

    Distinct ``strategy_id`` prefix so ``Trader.add_strategy`` uniqueness
    checks pass beside v2. ``phase0_permit_guard`` mirrors
    ``ContinuousRungHoldStrategy.__init__``'s own parameter exactly (and is
    forwarded to it, unchanged, for every station): ``True`` (default) keeps
    the Phase 0 seal -- a non-None ``order_submission_permit`` is refused
    HERE, before any instrument resolution or strategy construction, rather
    than only inside the first station's constructor. ``False`` is the
    Phase 1, continuous-only (no-shadow) opt-in a composition root passes
    when ``phase1_sending_permit`` has genuinely routed the single sending
    family's permit to this composition kind -- see ``app/trade.py::run``,
    the only caller that ever passes ``False``.

    ``enable_position_monitor`` (INC-5, D2/D3 SHADOW-ONLY -- never submits,
    modifies, or cancels an order): ``True`` by default in live composition.

    ``exit_manifest`` (INC-E4, ``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16
    .md`` §5.1, review finding A): ``None`` by default -- byte-identical to
    every increment before this one, since ``_build_position_monitor_for``
    then leaves every ``PositionMonitor`` exit kwarg at its own ``None``
    default (``_maybe_decide_exit`` stays a permanent no-op, exactly D3's
    pin). A caller (the composition ROOT, ``app/trade.py``, never this
    function itself -- it loads no file and opens no manifest) that passes
    the family's REAL, already-loaded :class:`FamilyManifest` opts every
    monitor-enabled station strategy into EVALUATING an exit on every
    ``THREATENED``/``DEAD_BY_OBSERVATION`` tick. This does not by itself let
    an order reach the venue: :func:`breezy.strategy.current_rung_hold.
    exit_decider.decide_exit` refuses with ``family_not_exit_registered``
    whenever :func:`breezy.persistence.exit_gate.family_declares_exit_rule`
    is ``False`` for the manifest handed in -- which is exactly the LIVE
    family's (``pm_us_crh_cont``) own manifest today (no ``exit_rule``
    declared), so passing it here produces persisted refusals and zero
    orders, never a live exit.
    A build-side switch, never an operator control and never a new env var
    (plan D1) -- tests that want the pre-INC-5 byte-identical strategy pass
    ``False``.
    """
    if phase0_permit_guard and order_submission_permit is not None:
        raise Phase0PermitForbiddenError(
            "build_continuous_rung_hold_strategies: Phase 0 forbids a non-None "
            "order_submission_permit"
        )
    catalog_instruments = _read_catalog_instruments(catalog_root)
    resolved = _bucket_station_instrument_ids(catalog_instruments, today_by_station)
    if all(len(ids) == 0 for ids in resolved.values()):
        raise NoTradableInstrumentsError(_zero_instruments_message(resolved, today_by_station))
    resolved_yesterday = _bucket_station_instrument_ids(
        catalog_instruments,
        {station: day - dt.timedelta(days=1) for station, day in today_by_station.items()},
    )

    # ONE OfferTape instance (its bounded deque, DEFAULT_OFFER_TAPE_MAXLEN=16384
    # slots) is shared by every per-station strategy below -- not one tape per
    # station. GAP fix 2026-09-15: an explicit `offer_tape_path` still wins
    # unconditionally (tests/the backtest harness keep working unedited);
    # `None` (the live default -- `app/trade.py` never passes this kwarg
    # today) now resolves to a real sidecar instead of in-memory-only, which
    # is exactly the gap a 2026-09-15 postmortem hit (no JSONL to read back).
    resolved_offer_tape_path = (
        offer_tape_path
        if offer_tape_path is not None
        else _default_offer_tape_path(catalog_root, today_by_station)
    )
    tape = OfferTape(resolved_offer_tape_path)
    # F-2 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): ONE shared
    # `DiagnosticsSummarySink`, mirroring the shared `OfferTape` above --
    # same `decisions/` directory, same boot-day rotation. `build_sha` is
    # resolved ONCE here (never per-station) via `resolve_build_revision`
    # (Rev 3.1 R8) -- the SAME identity `trade_supervisor`'s own
    # `supervisor_started.revision` resolves for this process tree.
    resolved_diagnostics_summary_path = (
        diagnostics_summary_path
        if diagnostics_summary_path is not None
        else _default_diagnostics_summary_path(catalog_root, today_by_station)
    )
    diagnostics_summary = DiagnosticsSummarySink(resolved_diagnostics_summary_path)
    build_sha = resolve_build_revision(os.environ)
    #: Sibling of the quote-tape catalog root (NEVER nested under it) --
    #: `catalog_root` here is `resolve_station_instrument_ids`'s own quote
    #: -tape root, so `monitor_root` is a directory beside it, one level up.
    monitor_root = catalog_root.parent / _MONITOR_CATALOG_DIRNAME
    strategies: list[ContinuousRungHoldStrategy] = []
    for station in today_by_station:
        instrument_ids = resolved[station]
        if not instrument_ids:
            logger.warning(
                "continuous_rung_hold: skipping %s; resolved 0 instruments for %s",
                station,
                today_by_station[station].isoformat(),
            )
            continue
        if not resolved_yesterday[station]:
            logger.warning(
                "continuous_rung_hold: %s resolved 0 instruments for yesterday %s; "
                "external order claim covers today only",
                station,
                (today_by_station[station] - dt.timedelta(days=1)).isoformat(),
            )
        config = _station_config(
            instrument_ids=instrument_ids,
            station=station,
            strategy_id=_CONTINUOUS_COMPONENT_ID_PREFIX,
            required_fee_coefficient=required_fee_coefficient,
            external_order_claims=_station_claims(instrument_ids, resolved_yesterday[station]),
        )
        strategy = ContinuousRungHoldStrategy(
            config,
            trial_day_latch_factory=trial_day_latch_factory,
            order_submission_permit=order_submission_permit,
            offer_tape=tape,
            phase0_permit_guard=phase0_permit_guard,
            diagnostics_summary=diagnostics_summary,
            build_sha=build_sha,
        )
        if enable_position_monitor:
            # Attribute assignment, not a constructor kwarg: the monitor's
            # own callables close over `strategy` (its cache/latch/facts are
            # only populated once `on_start` runs), so it can only be built
            # AFTER construction -- see `_build_position_monitor_for`.
            strategy._position_monitor = _build_position_monitor_for(
                strategy, monitor_root=monitor_root, exit_manifest=exit_manifest,
            )
        strategies.append(strategy)
    _assert_disjoint_claims(strategies)
    return tuple(strategies)


def _build_position_monitor_for(
    strategy: ContinuousRungHoldStrategy,
    *,
    monitor_root: Path,
    exit_manifest: FamilyManifest | None = None,
) -> PositionMonitor:
    """Wire a :class:`PositionMonitor` to ``strategy``.

    F1 DRY extraction: the eight read-only closures come from
    :func:`build_monitor_callables` (``monitor_wiring.py``) -- the SAME
    factory ``install_position_monitor`` (paper-replay) and the contract
    test's ``_wire_monitor`` also call, so the wiring can never drift
    between the three sites again. This function still owns everything
    site-specific -- the alert-sink ``report``, the live ``MarkBuffer()``,
    and the live monitor/summaries paths -- never a direct constructor
    reference to the strategy's own mutating surface (M7 D3 pin, plan §2).

    Review finding A (``POSITION_EXIT_EXECUTION_2026-09-16.md``): the five
    exit kwargs below are wired ONLY when ``exit_manifest`` is not ``None``
    -- ``exit_manifest is None`` (the caller's own default) leaves every one
    of them at ``PositionMonitor``'s own ``None`` default, so
    ``_maybe_decide_exit`` stays byte-identical to every increment before
    this one (module docstring's D3 pin). ``exit_family_id`` is read off the
    manifest itself (never a second, independently-suppliable id that could
    drift from it). ``exit_client_order_id_factory`` closes over ``strategy``
    lazily -- `order_factory` is `None` until Nautilus registers the
    strategy (`trading/strategy.pyx:173,298`), which runs AFTER this
    function returns, so the closure must defer the read to call time,
    exactly the laziness `build_monitor_callables`'s own docstring already
    requires of every closure here. ``submit_exit``/``record_exit_offer``
    reuse the strategy's OWN thin delegator (`continuous_strategy.py::
    submit_exit`) and its own `OfferTape.append` -- never a second exit-order
    construction path and never a second offer-tape sink.
    """
    sink = resolve_alert_sink()

    def _report(event: str, detail: Mapping[str, object]) -> None:
        emit_alert(
            sink,
            AlertPayload(
                severity="WARN", event=event, site=str(strategy.id), detail=str(dict(detail)),
            ),
        )

    def _exit_client_order_id_factory() -> str:
        return str(strategy.order_factory.generate_client_order_id().value)

    callables = build_monitor_callables(strategy)
    return PositionMonitor(
        clock_ns=strategy.clock.timestamp_ns,
        positions_open=callables.positions_open,
        accumulators=strategy._accumulators,
        latch_record=callables.latch_record,
        rung_geometry=callables.rung_geometry,
        fee_coefficient_for=callables.fee_coefficient_for,
        leg_for=callables.leg_for,
        station_for=callables.station_for,
        climate_day_for=callables.climate_day_for,
        hour_lst_for=callables.hour_lst_for,
        sibling_for=callables.sibling_for,
        stale_observation_bound_ns=strategy._config.stale_observation_minutes
        * _NS_PER_MINUTE,
        trial_id_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        buffer=MarkBuffer(),
        catalog_root=monitor_root,
        summaries_dir=monitor_root / _MONITOR_SUMMARIES_DIRNAME,
        report=_report,
        exit_decider=decide_exit if exit_manifest is not None else None,
        exit_manifest=exit_manifest,
        exit_family_id=None if exit_manifest is None else exit_manifest.family_id,
        exit_client_order_id_factory=(
            _exit_client_order_id_factory if exit_manifest is not None else None
        ),
        submit_exit=strategy.submit_exit if exit_manifest is not None else None,
        record_exit_offer=strategy.offer_tape.append if exit_manifest is not None else None,
        check_ambiguous_exit=(
            strategy.check_ambiguous_exit_intent if exit_manifest is not None else None
        ),
    )


def install_current_rung_hold_refusal_watch(
    node: object, strategies: Sequence[CurrentRungHoldStrategy | ContinuousRungHoldStrategy]
) -> None:
    """Wire per-station refusal AND diagnostics counts through the existing
    alert sink.

    PRIMARY path: attaches one ``RefusalAlerter`` per strategy to
    ``strategy.refusal_alerter``, so ``on_quote_tick`` reports its own
    updated count on the very tick that produced a refusal -- during a
    normal run, with no FSM degrade needed and no new ``LiveClock`` timer
    (L-16). Review fix: the previous wiring surfaced counts ONLY on
    ``COMPONENT_STATE_TOPIC``, which fires once at startup and otherwise
    only on a degrade transition, so per-station refusal counters never
    reached an operator during a normal live run.

    A SECOND ``RefusalAlerter`` per strategy, bound to
    ``strategy.diagnostics`` instead of ``strategy.refusals``, is wired onto
    ``strategy.diagnostics_alerter`` the same way -- the three WAIT-state
    diagnostics (``in_window_not_executable`` / ``in_window_no_running_max_yet``
    / ``in_window_rung_not_current``) were previously a write-only counter:
    incremented, never surfaced. Same mechanism, separate instance, so a
    diagnostic's count-change never raises a refusal alert condition.

    A THIRD ``RefusalAlerter`` per strategy, bound to
    ``strategy.position_events``, is wired onto ``strategy.position_alerter``
    the same way -- fill / position-open / ask-mark observations (O-1) are
    log-only and must never raise a refusal or WAIT condition.

    SECONDARY path (kept): every alerter -- refusal, diagnostics, and
    position alike -- is re-evaluated on ``COMPONENT_STATE_TOPIC`` too,
    catching a station that degrades without ever seeing a fresh quote. A
    missing ``msgbus`` used to make this whole function return silently; it
    now logs a WARNING and still wires the primary (per-tick) path, since
    that path needs no ``msgbus`` at all.
    """
    sink = resolve_alert_sink()
    wired: list[RefusalAlerter] = []
    for binding in _ALERTER_BINDINGS:
        for strategy in strategies:
            alerter = RefusalAlerter(
                getattr(strategy, binding.counter_attr),
                site=str(strategy.id),
                sink=sink,
                state=(
                    AlertState(renotify_after_ns=binding.renotify_after_ns)
                    if binding.renotify_after_ns is not None
                    else None
                ),
                **binding.vocabulary,
            )
            setattr(strategy, binding.alerter_attr, alerter)
            wired.append(alerter)

    # WP-R1: the halt detector, wired here rather than in a fourth
    # `_AlerterBinding`, because it is NOT a `RefusalAlerter` -- it consumes
    # the SAME cumulative `strategy.refusals` counter plus the take count and
    # answers a different question (is this family structurally unable to
    # trade?) through the same `AlertState`/`emit_alert` path. One instance
    # per strategy, NEVER added to `wired`: the `COMPONENT_STATE_TOPIC`
    # secondary path cannot say whether trading is expected right now, and
    # only the per-tick call site knows that.
    for strategy in strategies:
        strategy.halt_detector = HaltDetector(site=str(strategy.id), sink=sink)

    if not wired:
        return

    def _on_event(_event: object) -> None:
        now_ns = time.time_ns()
        for alerter in wired:
            try:
                alerter.report(now_ns=now_ns)
            except Exception:
                logger.exception("current_rung_hold refusal watch failed")

    msgbus = getattr(getattr(node, "kernel", None), "msgbus", None)
    if msgbus is None:
        logger.warning(
            "current_rung_hold refusal watch: no msgbus on node; the "
            "COMPONENT_STATE_TOPIC secondary refusal channel is disabled "
            "for this run (per-tick reporting via strategy.refusal_alerter "
            "is unaffected)"
        )
        return
    msgbus.subscribe(topic=COMPONENT_STATE_TOPIC, handler=_on_event)
