"""``NoLadderMakerStrategy`` -- the maker-sharp v1 live strategy (ARM C2).

Posts resting BUY NO GTD limit orders (qty 1, non-post-only) on the HIGH ladders of LAX, MDW, MIA
and SFO for climate day D+1. It decides nothing itself: every price and rung choice is the ported
core's (``selector.build_selector`` over ``rule``/``pno``/``pno_store`` under ``SHARP_V1``, proven
equal to the design driver by C3). This class only maps events to decision instants and decisions
to Nautilus commands.

Events and timers
-----------------
* ``on_order_book_depth`` (YES instrument of each rung): update that rung's book, re-decide the
  ladder.
* ``on_data(ForecastPoint)``: feed ``LiveNbpFeed``; when a row is accepted, a 1 ns native time
  alert re-decides every ladder of the station strictly after the vector's availability (the
  look-ahead guard of ``classify_p_no``): the NBP release alert.
* ``MAKER-POLL`` native timer (30 s): entry-veto check (re-sweeps every poll while a veto is
  latched), ``query_order`` of every live rest, the cancel deadline (a CANCELING rest not
  acknowledged in ``CANCEL_DEADLINE_S`` is re-issued), reconciliation of a rest whose order the
  cache already shows closed, instrument re-resolution from the cache.
* ``MAKER-HARD:<station>:<day>`` time alert at D 09:00 LST (``hard_cancel_ns``): a harmless
  backstop only -- it falls after the permit window (R10-ERRATUM) -- that cancels the station's
  rests and stops posting. ``_decide`` repeats the check against the clock, so a lost alert cannot
  leave a ladder posting past its window.
* GTD expiry is Nautilus' managed timer (``manage_gtd_expiry=True``); ``expire_time`` is the
  core's ``gtd_expire_ns``. A price change is cancel, then a re-post decided on ``OrderCanceled``.
  A shadow rest expires on its own alert at ``expire_ns``, so shadow mirrors live.
* ``on_stop``, a veto and the hard cancel cancel PER ORDER from the cache (open AND in flight):
  ``Strategy.cancel_all_orders`` only moves open orders to PENDING_CANCEL and the execution client
  cancels ledger-bound rests only, so an in-flight order (no venue id yet) would be orphaned.
  A cancel the venue refuses (``OrderCancelRejected``) or never acknowledges is re-issued by the
  poll; an order accepted while its cancel is pending, or while vetoed, is cancelled on acceptance.

Ladder day (V3/W4). A ladder's day D is frozen at ``on_start`` (tomorrow in the station's standard
time). That is correct, not a rollover bug: the supervisor relaunches daily (16:40Z stop, 16:50Z
launch), the posting window [D-1 16:50Z, D 02:50Z) lies wholly inside one session, and local
midnight (the instant a re-derived day would change) is later than the window at every station.
``test_a_session_posting_window_never_spans_two_ladder_days`` pins it.

Restart (W2). Orders of this strategy already in the cache (open or in flight) are adopted as
tracked rests when their rung registers, so a restart never double-posts; extras on a rung are
cancelled. The order is non-post-only (venue discovery, plan): the stale-book guard
(``STALE_BOOK_S``) and the truncation refusal are what keep a rest from taking.

``obs_cancel`` is NOT ported: the sharp arm never fed observation events (the design driver has no
call site), so the strategy cancels on forecast, price, hard-cancel and veto only -- the same
behaviour the sim measured.

Live sending is off unless ``config.shadow_only`` is False; a shadow strategy keeps virtual rests
and logs ``MAKER_WOULD_POST`` / ``MAKER_WOULD_CANCEL`` instead of ordering.
"""

from __future__ import annotations

import datetime as dt
import functools
import logging
from collections import Counter
from collections.abc import Callable
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol, cast

import pandas as pd
from nautilus_trader.core.data import Data
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import (
    OrderAccepted,
    OrderCanceled,
    OrderCancelRejected,
    OrderDenied,
    OrderExpired,
    OrderFilled,
    OrderRejected,
)
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.orders import Order
from nautilus_trader.trading.strategy import Strategy

from breezy.adapters.polymarket_us.symbology import (
    instrument_id_to_slug,
    leg_of,
    sibling_instrument_id,
)
from breezy.domain.forecast_point import ForecastPoint
from breezy.domain.weather_bucket_facts import (
    Measure,
    WeatherBucketFacts,
    WeatherFactsUnavailableError,
    read_weather_bucket_facts,
)
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from breezy.normalize.climate_day import local_standard_date
from breezy.registry.sites import default_registry
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID
from breezy.runtime.health import AlertPayload, emit_alert, resolve_alert_sink
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from breezy.strategy.ladder_ev.quantile_density import Rung as DensityRung
from breezy.strategy.no_ladder_maker import rule
from breezy.strategy.no_ladder_maker.config import (
    CANCEL_DEADLINE_S,
    STALE_BOOK_S,
    NoLadderMakerConfig,
)
from breezy.strategy.no_ladder_maker.ladder_state import (
    Ladder,
    Rest,
    RestState,
    Rung,
    book_refusal,
    frame_from_levels,
)
from breezy.strategy.no_ladder_maker.live_feed import LiveNbpFeed
from breezy.strategy.no_ladder_maker.params import SHARP_V1, MakerRuleParams
from breezy.strategy.no_ladder_maker.reconcile import Cancel, plan_actions
from breezy.strategy.no_ladder_maker.records import CENTS, Decision, DecisionContext, Desired
from breezy.strategy.no_ladder_maker.selector import SelectorConfig, WantTracker, build_selector

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.data import OrderBookDepth10

__all__ = [
    "MAX_DEPTH_SUBSCRIPTIONS",
    "REPOST_BACKOFF_S",
    "DepthSubscriptionBudgetError",
    "NoLadderMakerStrategy",
    "SupportsExpiresAtNs",
]

_log = logging.getLogger(__name__)
_CLASS_NAME: Final[str] = "NoLadderMakerStrategy"
_VENUE: Final[str] = "polymarket_us"
_NS: Final[int] = 10**9
_POLL_TIMER: Final[str] = "MAKER-POLL"
_HARD_PREFIX: Final[str] = "MAKER-HARD"
WINDOW_OPEN_UTC: Final[dt.time] = dt.time(16, 50)


def _window_open_ns(day: dt.date) -> int:
    """D-1 16:50Z, the instant the simulated posting window opens for ladder day ``day``."""
    opened = dt.datetime.combine(day - dt.timedelta(days=1), WINDOW_OPEN_UTC, tzinfo=dt.UTC)
    return int(opened.timestamp()) * 1_000_000_000


_NBP_PREFIX: Final[str] = "MAKER-NBP"
_SHADOW_PREFIX: Final[str] = "MAKER-SHADOW"
#: R15 (L-45) fail-closed bound on Depth10 subscriptions: four stations x ten rungs of ONE
#: (D+1) ladder each. The venue caps subscriptions per CONNECTION (10, shared with TRADE); the
#: pool shards across connections, and a boot that would exceed this bound refuses to subscribe
#: rather than silently losing coverage.
MAX_DEPTH_SUBSCRIPTIONS: Final[int] = 40
#: After a denied / rejected rest the rung is not re-posted for this long.
REPOST_BACKOFF_S: Final[int] = 60
_NO_PERMIT_EXPIRY_NS: Final[int] = 2**62

Veto = Callable[[], str | None]


class DepthSubscriptionBudgetError(RuntimeError):
    """The ladders to subscribe exceed :data:`MAX_DEPTH_SUBSCRIPTIONS` (R15, fail closed)."""


class SupportsExpiresAtNs(Protocol):
    """The narrow permit surface this strategy needs (a real ``OrderSubmissionPermit`` fits)."""

    @property
    def expires_at_ns(self) -> int: ...


def _expire_timestamp(expire_ns: int) -> pd.Timestamp:
    return pd.Timestamp(expire_ns, unit="ns", tz="UTC")


def _guarded[Handler: Callable[..., None]](handler: Handler) -> Handler:
    """L-16: an event / timer handler never raises; a failure is logged with its traceback.

    One decorator for every handler so no path can forget the guard (and a failure in one handler
    never aborts the Nautilus dispatch that called it).
    """

    @functools.wraps(handler)
    def wrapper(self: NoLadderMakerStrategy, *args: Any, **kwargs: Any) -> None:
        try:
            handler(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - the single place a handler failure is absorbed
            self._log_failure(f"{_CLASS_NAME}.{handler.__name__} failed", exc)

    return cast(Handler, wrapper)


class NoLadderMakerStrategy(Strategy):
    def __init__(
        self,
        config: NoLadderMakerConfig,
        *,
        calibration: LiveCalibration,
        theta: float,
        params: MakerRuleParams = SHARP_V1,
        order_submission_permit: SupportsExpiresAtNs | None = None,
        submit_veto: Veto | None = None,
        fee_verified: Callable[[int], bool] | None = None,
        max_depth_subscriptions: int = MAX_DEPTH_SUBSCRIPTIONS,
        stale_book_s: int = STALE_BOOK_S,
    ) -> None:
        super().__init__(config)
        self._params = params
        self._theta = theta
        self._permit = order_submission_permit
        self._submit_veto = submit_veto
        self._fee_verified = fee_verified
        self._max_depth_subscriptions = max_depth_subscriptions
        self._stale_book_ns = stale_book_s * _NS
        registry = default_registry()
        self._offsets = {
            s: registry.climate_day_window(_VENUE, s).std_utc_offset_hours for s in config.stations
        }
        self._station_by_icao = {
            registry.settlement_site(_VENUE, s).icao: s for s in config.stations
        }
        self._feed = LiveNbpFeed(
            calibration=calibration,
            icao_by_station={s: icao for icao, s in self._station_by_icao.items()},
        )
        self._stopping = False
        self.ladders: dict[tuple[str, dt.date], Ladder] = {}
        self._by_yes: dict[str, tuple[tuple[str, dt.date], str]] = {}
        self._order_index: dict[ClientOrderId, tuple[tuple[str, dt.date], str]] = {}
        self._nbp_pending: set[str] = set()
        self._nbp_alerts = 0
        self._shadow_alerts = 0
        self._veto_latched: str | None = None
        self._tracker = WantTracker()
        self.counters: Counter[str] = Counter()

    def _log_failure(self, message: str, exc: Exception) -> None:
        """Log a swallowed handler failure with its traceback (L-16)."""
        self.log.exception(message, exc)

    # -- lifecycle ---------------------------------------------------------------------------

    def on_start(self) -> None:
        now = self.clock.timestamp_ns()
        for station in self.config.stations:
            day = local_standard_date(now, self._offsets[station]) + dt.timedelta(days=1)
            hard = rule.hard_cancel_ns(day, int(self._offsets[station]), self._params)
            opens = _window_open_ns(day)
            self.ladders[(station, day)] = Ladder(station, day, hard, window_open_ns=opens)
            if hard > now:
                self.clock.set_time_alert_ns(
                    name=f"{_HARD_PREFIX}:{station}:{day.isoformat()}",
                    alert_time_ns=hard,
                    callback=self._on_hard_alert,
                )
        self.subscribe_data(nbm_forecast_point_data_type(), client_id=NWS_BACKTEST_CLIENT_ID)
        self._resolve_instruments()  # raises DepthSubscriptionBudgetError: refuse to start
        self.clock.set_timer(
            name=_POLL_TIMER,
            interval=dt.timedelta(seconds=self.config.poll_interval_s),
            callback=self._on_poll,
        )

    def on_stop(self) -> None:
        self._stopping = True
        for name in tuple(self.clock.timer_names):
            if name.startswith((_POLL_TIMER, _HARD_PREFIX, _NBP_PREFIX, _SHADOW_PREFIX)):
                self.clock.cancel_timer(name)
        self._cancel_everything("on_stop")

    # -- instrument resolution ---------------------------------------------------------------

    def _resolve_instruments(self) -> int:
        """Register every cached YES rung of each ladder's day; subscribe its Depth10."""
        added = 0
        for ladder in self.ladders.values():
            for instrument in self.cache.instruments():
                added += self._register_rung(ladder, instrument.id)
            self._publish_ladder(ladder)
        if added:  # the supervisor's COMPOSITION_KIND_SUBSCRIBED_MARKERS row
            self.log.info(f"{_CLASS_NAME} subscribed n={len(self._by_yes)}")
        return added

    def _register_rung(self, ladder: Ladder, yes_id: InstrumentId) -> int:
        rung_id = str(yes_id)
        if rung_id in ladder.rungs or leg_of(yes_id) != "yes":
            return 0
        facts = self._rung_facts(yes_id)
        if (
            facts is None
            or facts.measure is not Measure.HIGH
            or not facts.applies_to(ladder.station, ladder.day)
        ):
            return 0
        no_id = sibling_instrument_id(yes_id)
        if self.cache.instrument(no_id) is None:
            self.counters["no_leg_not_in_cache"] += 1
            return 0
        if len(self._by_yes) >= self._max_depth_subscriptions:
            raise DepthSubscriptionBudgetError(
                f"{_CLASS_NAME}: {len(self._by_yes) + 1} Depth10 subscriptions exceed "
                f"{self._max_depth_subscriptions}; refusing to subscribe {rung_id}"
            )
        edge = float("-inf") if facts.lower_f is None else float(facts.lower_f)
        ladder.rungs[rung_id] = Rung(rung_id, yes_id, no_id, edge, facts.lower_f, facts.upper_f)
        self._by_yes[rung_id] = ((ladder.station, ladder.day), rung_id)
        self.subscribe_order_book_depth(yes_id)
        self._seed_held(ladder, ladder.rungs[rung_id])
        self._adopt_existing(ladder, ladder.rungs[rung_id])
        self.log.info(f"{_CLASS_NAME} subscribed {yes_id}")
        return 1

    def _rung_facts(self, yes_id: InstrumentId) -> WeatherBucketFacts | None:
        """The rung's bucket facts from the instrument's own adapter-written ``info``.

        The adapter derives them with the same slug grammar the simulator's ladder uses
        (``symbology.parse_weather_slug`` + ``slug_closed_interval``); a cached instrument without
        known facts is not a rung.
        """
        instrument = self.cache.instrument(yes_id)
        if instrument is None:
            return None
        try:
            return read_weather_bucket_facts(instrument.info)
        except WeatherFactsUnavailableError:
            self.counters["rung_facts_unavailable"] += 1
            return None

    def _seed_held(self, ladder: Ladder, rung: Rung) -> None:
        """A NO position already open on this rung (a relaunch) counts toward MAX_RUNGS."""
        if self.cache.positions_open(instrument_id=rung.no_id):
            ladder.held.add(rung.rung_id)

    def _adopt_existing(self, ladder: Ladder, rung: Rung) -> None:
        """W2: orders of this strategy already live in the cache become tracked rests.

        A restart never double-posts: the adopted order is the rung's rest (repriced, cancelled
        or expired like any other). A second live order on one rung cannot be a rest of ours, so
        it is cancelled. Orders of other strategies (an operator's) are never in this query.
        """
        live = sorted(self._live_orders(rung.no_id), key=lambda order: order.ts_init)
        for position, order in enumerate(live):
            if position:
                self.counters["adopted_extra_cancelled"] += 1
                if not order.is_pending_cancel:
                    self.cancel_order(order)
                continue
            state = RestState.ACCEPTED
            if order.is_pending_cancel:
                state = RestState.CANCELING
            elif order.is_inflight:
                state = RestState.SUBMITTED
            rest = Rest(
                rung.rung_id,
                round(float(order.price) * CENTS),
                int(order.expire_time_ns),
                state,
                order.client_order_id,
            )
            if state is RestState.CANCELING:
                rest.cancel_deadline_ns = self.clock.timestamp_ns() + CANCEL_DEADLINE_S * _NS
            ladder.rests[rung.rung_id] = rest
            self._order_index[order.client_order_id] = ((ladder.station, ladder.day), rung.rung_id)
            self.counters["adopted_rests"] += 1
            self.log.info(
                f"MAKER_ADOPT station={ladder.station} day={ladder.day} rung={rung.rung_id} "
                f"state={state.value} client_order_id={order.client_order_id}"
            )

    def _publish_ladder(self, ladder: Ladder) -> None:
        if not ladder.rungs:
            return
        density = [
            DensityRung(rung_id=r.rung_id, lo=r.lower_f, hi=r.upper_f)
            for r in ladder.rungs.values()
        ]
        self._feed.set_ladder(
            ladder.station, ladder.day, density
        )  # a changed ladder drops its store

    def current_yes_instrument_slug(self) -> str | None:
        """The first resolved YES rung's market slug (the fee-drift probe's lazy ``slug_fn``)."""
        for ladder in self.ladders.values():
            for rung in ladder.rungs.values():
                return instrument_id_to_slug(rung.yes_id)
        return None

    # -- data --------------------------------------------------------------------------------

    @_guarded
    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        key_rung = self._by_yes.get(str(depth.instrument_id))
        if key_rung is None:
            return
        key, rung_id = key_rung
        ladder = self.ladders[key]
        ladder.books[rung_id] = frame_from_levels(rung_id, depth.ts_event, depth.bids, depth.asks)
        ladder.arrivals[rung_id] = self.clock.timestamp_ns()
        self._decide(ladder)

    @_guarded
    def on_data(self, data: Data) -> None:
        if not isinstance(data, ForecastPoint):
            return
        outcome = self._feed.push(data, arrival_ns=self.clock.timestamp_ns())
        if outcome.accepted:
            self._schedule_nbp_release(data.station)

    def _schedule_nbp_release(self, icao: str) -> None:
        """Re-decide the station strictly AFTER the vector's availability (look-ahead guard)."""
        station = self._station_by_icao.get(icao)
        if station is None or station in self._nbp_pending:
            return
        self._nbp_pending.add(station)
        self._nbp_alerts += 1
        self.clock.set_time_alert_ns(
            name=f"{_NBP_PREFIX}:{station}:{self._nbp_alerts}",
            alert_time_ns=self.clock.timestamp_ns() + 1,
            callback=self._on_nbp_alert,
        )

    @_guarded
    def _on_nbp_alert(self, event: Any) -> None:
        station = str(event.name).split(":")[1]
        self._nbp_pending.discard(station)
        for ladder in self.ladders.values():
            if ladder.station == station:
                self._decide(ladder)

    # -- decisions ---------------------------------------------------------------------------

    def _selector_for(self, ladder: Ladder) -> Callable[[DecisionContext], Decision] | None:
        store = self._feed.store(ladder.station, ladder.day)
        if store is None:
            return None
        if ladder.selector is None or ladder.selector_stamp is not store:
            edges = {r.rung_id: r.lower_edge_f for r in ladder.rungs.values()}
            ladder.selector = build_selector(
                SelectorConfig(
                    store=store,
                    station=ladder.station,
                    day=ladder.day,
                    stress="none",
                    delta_ns=0,
                    theta=self._theta,
                    lower_edges_f=edges,
                    params=self._params,
                ),
                self._tracker,
            )
            ladder.selector_stamp = store
        return ladder.selector

    @_guarded
    def _decide(self, ladder: Ladder) -> None:
        now = self.clock.timestamp_ns()
        if self._stopping or ladder.hard_cancelled or self._check_veto() is not None:
            return
        if now >= ladder.hard_cancel_ns:  # the hard-cancel alert never ran: do its job now
            self._end_window(ladder)
            return
        selector = self._selector_for(ladder)
        if selector is None:
            return
        ctx = DecisionContext(
            now_ns=now,
            books=MappingProxyType(dict(ladder.books)),
            live_bids=MappingProxyType({r: rest.bid_cents for r, rest in ladder.rests.items()}),
            held=frozenset(ladder.held),
        )
        decision = selector(ctx)
        plan = plan_actions(
            decision,
            live={r: rest.bid_cents for r, rest in ladder.rests.items()},
            cancelling=ladder.cancelling(),
            held=frozenset(ladder.held),
            booked=frozenset(ladder.books),
            max_rungs=self._params.max_rungs,
        )
        for cancel in plan.cancels:
            self._cancel_rest(ladder, cancel)
        for desired in plan.posts:
            self._post(ladder, desired, now)

    def _end_window(self, ladder: Ladder) -> None:
        """V3: the ladder's window is over -- stop posting and cancel, whatever the alert did."""
        self.counters["refused_after_window"] += 1
        ladder.hard_cancelled = True
        self._cancel_ladder(ladder)
        self.log.error(
            f"{_CLASS_NAME}: station={ladder.station} day={ladder.day} is past its window end; "
            "posting stopped and its rests cancelled"
        )

    # -- guards ------------------------------------------------------------------------------

    def _check_veto(self, *, resweep: bool = False) -> str | None:
        """The entry veto (family halt / harm stop); cancels everything when it first appears.

        ``resweep`` (the poll) repeats the cancel sweep while the veto stays latched, so an order
        that was in flight, or whose cancel was refused, cannot outlive the veto (W3/X2).
        """
        if self._submit_veto is None:
            return None
        try:
            reason = self._submit_veto()
        except Exception as exc:  # noqa: BLE001 - a raising veto refuses (fail closed)
            self._log_failure(f"{_CLASS_NAME}: submit veto raised", exc)
            reason = "veto_unreadable"
        if reason is None:
            self._veto_latched = None
            return None
        changed = self._veto_latched != reason
        if changed:
            self._veto_latched = reason
            self.log.error(f"{_CLASS_NAME}: entries vetoed reason={reason}; cancelling all rests")
        if changed or resweep:
            self._cancel_everything(f"veto:{reason}")
        return reason

    def _send_refusal(self, now_ns: int) -> str | None:
        if self._permit is None:
            return "phase0_permit_absent"
        if now_ns >= self._permit.expires_at_ns:
            return "permit_expired"
        if self._fee_verified is not None and not self._fee_verified(now_ns):
            return "fee_unverified"
        return None

    # -- orders ------------------------------------------------------------------------------

    def _post(self, ladder: Ladder, desired: Desired, now_ns: int) -> None:
        rung = ladder.rungs[desired.rung_id]
        if now_ns < ladder.window_open_ns:
            self.counters["refused_before_window"] += 1
            return
        if now_ns < ladder.backoff_until_ns.get(desired.rung_id, 0):
            self.counters["backoff"] += 1
            return
        if now_ns - ladder.arrivals.get(desired.rung_id, 0) > self._stale_book_ns:
            self.counters["refused_stale_book"] += 1  # post_only is False: a stale ask would take
            return
        refusal = book_refusal(ladder.books[desired.rung_id], desired.bid_cents)
        if refusal is not None:
            self.counters[f"refused_{refusal}"] += 1
            self.log.info(
                f"{_CLASS_NAME}: no post {rung.rung_id} bid={desired.bid_cents} {refusal}"
            )
            return
        permit_end = (
            _NO_PERMIT_EXPIRY_NS if self._permit is None else int(self._permit.expires_at_ns)
        )
        expire_ns = rule.gtd_expire_ns(now_ns, ladder.hard_cancel_ns, permit_end)
        if expire_ns <= now_ns:
            self.counters["refused_expired_window"] += 1
            return
        if self.config.shadow_only:
            ladder.rests[desired.rung_id] = Rest(
                desired.rung_id, desired.bid_cents, expire_ns, RestState.SHADOW
            )
            self._schedule_shadow_expiry(ladder, desired.rung_id, expire_ns)
            self.log.info(
                f"MAKER_WOULD_POST station={ladder.station} day={ladder.day} rung={rung.rung_id} "
                f"bid_cents={desired.bid_cents} expire_ns={expire_ns}"
            )
            return
        send_refusal = self._send_refusal(now_ns)
        if send_refusal is not None:
            self.counters[f"refused_{send_refusal}"] += 1
            self.log.info(f"{_CLASS_NAME}: no submit {rung.rung_id} reason={send_refusal}")
            return
        self._submit(ladder, rung, desired, expire_ns)

    def _submit(self, ladder: Ladder, rung: Rung, desired: Desired, expire_ns: int) -> None:
        instrument = self.cache.instrument(rung.no_id)
        if instrument is None:
            self.log.error(f"{_CLASS_NAME}: NO instrument vanished from cache: {rung.no_id}")
            return
        order = self.order_factory.limit(
            instrument_id=rung.no_id,
            order_side=OrderSide.BUY,
            quantity=instrument.make_qty(Decimal(1)),
            price=instrument.make_price(Decimal(desired.bid_cents) / Decimal(CENTS)),
            time_in_force=TimeInForce.GTD,
            expire_time=_expire_timestamp(expire_ns),
            post_only=False,
        )
        ladder.rests[desired.rung_id] = Rest(
            desired.rung_id,
            desired.bid_cents,
            expire_ns,
            RestState.SUBMITTED,
            order.client_order_id,
        )
        self._order_index[order.client_order_id] = ((ladder.station, ladder.day), desired.rung_id)
        self.submit_order(order)
        self.log.info(
            f"MAKER_POST station={ladder.station} day={ladder.day} rung={rung.rung_id} "
            f"bid_cents={desired.bid_cents} expire_ns={expire_ns} "
            f"client_order_id={order.client_order_id}"
        )

    # -- cancels -----------------------------------------------------------------------------

    def _cancel_rest(self, ladder: Ladder, cancel: Cancel) -> None:
        rest = ladder.rests[cancel.rung_id]
        if rest.state is RestState.SHADOW:
            del ladder.rests[cancel.rung_id]
            self.log.info(
                f"MAKER_WOULD_CANCEL station={ladder.station} rung={cancel.rung_id} "
                f"reason={cancel.reason}"
            )
            return
        order = self.cache.order(rest.client_order_id) if rest.client_order_id else None
        if order is None or order.is_closed:
            return  # the terminal event is in transit; the poll reconciles it if it never comes
        self._cancel_if_due(rest, order)
        self.log.info(
            f"MAKER_CANCEL station={ladder.station} rung={cancel.rung_id} reason={cancel.reason}"
        )

    def _live_orders(self, instrument_id: InstrumentId) -> list[Order]:
        """This strategy's open AND in-flight orders on an instrument (deduplicated).

        ``cache.orders_open`` alone misses an order still SUBMITTED (no venue id yet);
        ``cache.orders_inflight`` alone misses an ACCEPTED one. PENDING_CANCEL is in both.
        """
        found: dict[ClientOrderId, Order] = {}
        for order in (
            *self.cache.orders_open(instrument_id=instrument_id, strategy_id=self.id),
            *self.cache.orders_inflight(instrument_id=instrument_id, strategy_id=self.id),
        ):
            if not order.is_closed:
                found.setdefault(order.client_order_id, order)
        return list(found.values())

    def _request_cancel(self, rest: Rest, order: Order) -> None:
        """Send (or re-send) the cancel of one tracked order and stamp its deadline.

        ``Strategy.cancel_order`` sends nothing for an order already PENDING_CANCEL, so a re-issue
        of an unacknowledged cancel goes through ``cancel_all_orders`` (the native path that does
        accept PENDING_CANCEL); the execution client cancels ledger-bound rests only, so it can
        touch nothing but our own order on that instrument.
        """
        if rest.state is RestState.CANCELING:
            self.counters["cancel_reissued"] += 1
        rest.state = RestState.CANCELING
        rest.cancel_deadline_ns = self.clock.timestamp_ns() + CANCEL_DEADLINE_S * _NS
        if order.is_pending_cancel:
            self.cancel_all_orders(order.instrument_id)
        else:
            self.cancel_order(order)

    def _cancel_if_due(self, rest: Rest, order: Order) -> None:
        """Cancel ``order`` unless an earlier cancel of it is still inside its deadline."""
        if order.is_pending_cancel and self.clock.timestamp_ns() < rest.cancel_deadline_ns:
            return
        self._request_cancel(rest, order)

    def _cancel_ladder(self, ladder: Ladder) -> None:
        """Cancel every live order of the ladder, per order, and drop its shadow rests."""
        for rung in ladder.rungs.values():
            for order in self._live_orders(rung.no_id):
                located = self._order_index.get(order.client_order_id)
                rest = ladder.rests.get(located[1]) if located is not None else None
                if rest is None or rest.client_order_id != order.client_order_id:
                    if not order.is_pending_cancel:  # an order of ours with no rest record
                        self.cancel_order(order)
                    continue
                self._cancel_if_due(rest, order)
        for rung_id, rest in tuple(ladder.rests.items()):
            if rest.state is RestState.SHADOW:
                del ladder.rests[rung_id]
            elif rest.state is not RestState.CANCELING:
                rest.state = RestState.CANCELING  # no live order in the cache: the poll reconciles
                rest.cancel_deadline_ns = self.clock.timestamp_ns() + CANCEL_DEADLINE_S * _NS

    def _cancel_everything(self, reason: str) -> None:
        """Cancel every live order of every ladder (family halt, veto, stop)."""
        for ladder in self.ladders.values():
            self._cancel_ladder(ladder)
        self.counters[f"cancel_everything_{reason.split(':')[0]}"] += 1

    # -- shadow ------------------------------------------------------------------------------

    def _schedule_shadow_expiry(self, ladder: Ladder, rung_id: str, expire_ns: int) -> None:
        """V5: a shadow rest expires at ``expire_ns`` exactly as the live GTD order would."""
        self._shadow_alerts += 1
        key = (ladder.station, ladder.day)
        self.clock.set_time_alert_ns(
            name=f"{_SHADOW_PREFIX}:{self._shadow_alerts}",
            alert_time_ns=expire_ns,
            callback=lambda event: self._on_shadow_expiry(key, rung_id, expire_ns),
        )

    @_guarded
    def _on_shadow_expiry(self, key: tuple[str, dt.date], rung_id: str, expire_ns: int) -> None:
        ladder = self.ladders[key]
        rest = ladder.rests.get(rung_id)
        if rest is None or rest.state is not RestState.SHADOW or rest.expire_ns != expire_ns:
            return  # cancelled or replaced since: that rest's own alert, not this one
        del ladder.rests[rung_id]
        self.counters["shadow_expired"] += 1
        self.log.info(f"MAKER_WOULD_EXPIRE station={ladder.station} rung={rung_id}")
        self._decide(ladder)

    # -- timers ------------------------------------------------------------------------------

    @_guarded
    def _on_poll(self, event: Any) -> None:
        self._check_veto(resweep=True)
        self._resolve_instruments()
        self._poll_open_orders()

    def _poll_open_orders(self) -> None:
        """Query every live rest, enforce the cancel deadline, reconcile closed orders."""
        for ladder in self.ladders.values():
            closed = False
            for rung_id, rest in tuple(ladder.rests.items()):
                if rest.state is RestState.SHADOW:
                    continue
                order = self.cache.order(rest.client_order_id) if rest.client_order_id else None
                if order is None or order.is_closed:
                    self._reconcile_closed(ladder, rung_id, order)
                    closed = True
                    continue
                self.query_order(order)
                if rest.state is RestState.CANCELING:
                    self._cancel_if_due(rest, order)
            if closed:
                self._decide(ladder)

    def _reconcile_closed(self, ladder: Ladder, rung_id: str, order: Order | None) -> None:
        """A rest whose order the cache shows closed (or lacks): the event never reached us."""
        self.counters["rest_reconciled_from_cache"] += 1
        if order is not None and float(order.filled_qty) > 0:
            ladder.held.add(rung_id)
        del ladder.rests[rung_id]
        self.log.warning(
            f"{_CLASS_NAME}: rest reconciled from the cache station={ladder.station} "
            f"rung={rung_id} status={order.status_string() if order is not None else 'absent'}"
        )

    @_guarded
    def _on_hard_alert(self, event: Any) -> None:
        """D 09:00 LST. Falls after the permit window; a harmless backstop (R10-ERRATUM)."""
        _, station, day_text = str(event.name).split(":")
        ladder = self.ladders.get((station, dt.date.fromisoformat(day_text)))
        if ladder is None:
            return
        ladder.hard_cancelled = True
        self._cancel_ladder(ladder)
        self.log.info(f"MAKER_HARD_CANCEL station={station} day={day_text}")

    # -- order events ------------------------------------------------------------------------

    def _rest_for(self, client_order_id: ClientOrderId) -> tuple[Ladder, str, Rest] | None:
        located = self._order_index.get(client_order_id)
        if located is None:
            return None
        key, rung_id = located
        ladder = self.ladders[key]
        rest = ladder.rests.get(rung_id)
        if rest is None or rest.client_order_id != client_order_id:
            return None
        return ladder, rung_id, rest

    @_guarded
    def on_order_accepted(self, event: OrderAccepted) -> None:
        found = self._rest_for(event.client_order_id)
        if found is None:
            return
        ladder, _, rest = found
        if rest.state is RestState.SUBMITTED:
            rest.state = RestState.ACCEPTED
        # An order the venue acknowledged AFTER we asked to cancel it (or while entries are
        # vetoed / the window is over) is now cancellable: do it, never leave it resting (V2/X2).
        if (
            rest.state is RestState.CANCELING
            or ladder.hard_cancelled
            or self._stopping
            or self._check_veto() is not None
        ):
            order = self.cache.order(event.client_order_id)
            if order is not None and not order.is_closed:
                self._cancel_if_due(rest, order)

    @_guarded
    def on_order_canceled(self, event: OrderCanceled) -> None:
        self._close_rest(event.client_order_id, redecide=True)

    @_guarded
    def on_order_cancel_rejected(self, event: OrderCancelRejected) -> None:
        self.counters["cancel_rejected"] += 1
        found = self._rest_for(event.client_order_id)
        if found is None:
            return  # a late refusal for a rest already closed or filled
        found[2].cancel_deadline_ns = 0  # re-issue on the next poll (never a hot loop)
        self.log.warning(
            f"{_CLASS_NAME}: cancel rejected client_order_id={event.client_order_id} "
            f"reason={event.reason}"
        )
        self._alert("MAKER_CANCEL_REJECTED", event.instrument_id, event.client_order_id, "WARN")

    @_guarded
    def on_order_expired(self, event: OrderExpired) -> None:
        self._close_rest(event.client_order_id, redecide=True)
        self._alert("MAKER_ORDER_EXPIRED", event.instrument_id, event.client_order_id, "INFO")

    @_guarded
    def on_order_filled(self, event: OrderFilled) -> None:
        found = self._rest_for(event.client_order_id)
        if found is not None:
            ladder, rung_id, _ = found
            ladder.held.add(rung_id)
            del ladder.rests[rung_id]
        self._alert("MAKER_ORDER_FILLED", event.instrument_id, event.client_order_id, "INFO")

    @_guarded
    def on_order_denied(self, event: OrderDenied) -> None:
        self._close_rest(event.client_order_id, redecide=False, backoff=True)
        self._alert("MAKER_ORDER_DENIED", event.instrument_id, event.client_order_id, "WARN")

    @_guarded
    def on_order_rejected(self, event: OrderRejected) -> None:
        self._close_rest(event.client_order_id, redecide=False, backoff=True)
        self._alert("MAKER_ORDER_REJECTED", event.instrument_id, event.client_order_id, "WARN")

    def _close_rest(
        self, client_order_id: ClientOrderId, *, redecide: bool, backoff: bool = False
    ) -> None:
        found = self._rest_for(client_order_id)
        if found is None:
            return
        ladder, rung_id, _ = found
        del ladder.rests[rung_id]
        if backoff:
            ladder.backoff_until_ns[rung_id] = self.clock.timestamp_ns() + REPOST_BACKOFF_S * _NS
        if redecide:
            self._decide(ladder)

    @_guarded
    def _alert(
        self,
        event_name: str,
        instrument_id: object,
        client_order_id: object,
        severity: Literal["INFO", "WARN", "CRITICAL"],
    ) -> None:
        detail = f"instrument={instrument_id} client_order_id={client_order_id}"
        self.log.info(f"{event_name} {detail}")
        emit_alert(
            resolve_alert_sink(),
            AlertPayload(severity=severity, event=event_name, site=_CLASS_NAME, detail=detail),
        )
