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
* ``MAKER-POLL`` native timer (30 s): entry-veto check (cancels everything on a veto),
  ``query_order`` of every accepted rest, instrument re-resolution from the cache.
* ``MAKER-HARD:<station>:<day>`` time alert at D 09:00 LST (``hard_cancel_ns``): a harmless
  backstop only -- it falls after the permit window (R10-ERRATUM) -- that cancels the station's
  rests and stops posting.
* GTD expiry is Nautilus' managed timer (``manage_gtd_expiry=True``); ``expire_time`` is the
  core's ``gtd_expire_ns``. A price change is cancel, then a re-post decided on ``OrderCanceled``.
* ``on_stop``: ``cancel_all_orders`` for every instrument of every ladder.

``obs_cancel`` is NOT ported: the sharp arm never fed observation events (the design driver has no
call site), so the strategy cancels on forecast, price, hard-cancel and veto only -- the same
behaviour the sim measured.

Live sending is off unless ``config.shadow_only`` is False; a shadow strategy keeps virtual rests
and logs ``MAKER_WOULD_POST`` / ``MAKER_WOULD_CANCEL`` instead of ordering.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter
from collections.abc import Callable
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol

import pandas as pd
from nautilus_trader.core.data import Data
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import (
    OrderAccepted,
    OrderCanceled,
    OrderDenied,
    OrderExpired,
    OrderFilled,
    OrderRejected,
)
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
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
from breezy.strategy.no_ladder_maker.config import NoLadderMakerConfig
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
    ) -> None:
        super().__init__(config)
        self._params = params
        self._theta = theta
        self._permit = order_submission_permit
        self._submit_veto = submit_veto
        self._fee_verified = fee_verified
        self._max_depth_subscriptions = max_depth_subscriptions
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
        self._veto_latched: str | None = None
        self._tracker = WantTracker()
        self.counters: Counter[str] = Counter()

    def _log_failure(self, message: str, exc: Exception) -> None:
        """L-16: a handler never raises; the failure is logged with its traceback."""
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
            if name.startswith((_POLL_TIMER, _HARD_PREFIX, _NBP_PREFIX)):
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

    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        try:
            self._on_depth(depth)
        except Exception as exc:  # noqa: BLE001 - L-16: a handler must never raise
            self._log_failure(f"{_CLASS_NAME}: depth handler failed for {depth.instrument_id}", exc)

    def _on_depth(self, depth: OrderBookDepth10) -> None:
        key_rung = self._by_yes.get(str(depth.instrument_id))
        if key_rung is None:
            return
        key, rung_id = key_rung
        ladder = self.ladders[key]
        ladder.books[rung_id] = frame_from_levels(rung_id, depth.ts_event, depth.bids, depth.asks)
        self._decide(ladder)

    def on_data(self, data: Data) -> None:
        if not isinstance(data, ForecastPoint):
            return
        try:
            outcome = self._feed.push(data, arrival_ns=self.clock.timestamp_ns())
            if outcome.accepted:
                self._schedule_nbp_release(data.station)
        except Exception as exc:  # noqa: BLE001 - L-16: a handler must never raise
            self._log_failure(f"{_CLASS_NAME}: forecast handler failed", exc)

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

    def _decide(self, ladder: Ladder) -> None:
        try:
            self._decide_unsafe(ladder)
        except Exception as exc:  # noqa: BLE001 - L-16: a handler must never raise
            self._log_failure(
                f"{_CLASS_NAME}: decision failed station={ladder.station} day={ladder.day}", exc
            )

    def _decide_unsafe(self, ladder: Ladder) -> None:
        now = self.clock.timestamp_ns()
        if self._stopping or ladder.hard_cancelled or self._check_veto() is not None:
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

    # -- guards ------------------------------------------------------------------------------

    def _check_veto(self) -> str | None:
        """The entry veto (family halt / harm stop); cancels everything when it first appears."""
        if self._submit_veto is None:
            return None
        try:
            reason = self._submit_veto()
        except Exception as exc:  # noqa: BLE001 - a raising veto refuses (fail closed)
            self._log_failure(f"{_CLASS_NAME}: submit veto raised", exc)
            reason = "veto_unreadable"
        if reason is not None and self._veto_latched != reason:
            self._veto_latched = reason
            self.log.error(f"{_CLASS_NAME}: entries vetoed reason={reason}; cancelling all rests")
            self._cancel_everything(f"veto:{reason}")
        elif reason is None:
            self._veto_latched = None
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
            return
        rest.state = RestState.CANCELING
        self.cancel_order(order)
        self.log.info(
            f"MAKER_CANCEL station={ladder.station} rung={cancel.rung_id} reason={cancel.reason}"
        )

    def _cancel_everything(self, reason: str) -> None:
        """``cancel_all_orders`` for every instrument of every ladder (family halt, stop)."""
        for ladder in self.ladders.values():
            for rung in ladder.rungs.values():
                self.cancel_all_orders(rung.no_id)
            for rest in ladder.rests.values():
                rest.state = (
                    RestState.SHADOW if rest.state is RestState.SHADOW else RestState.CANCELING
                )
            ladder.rests = {
                r: x for r, x in ladder.rests.items() if x.state is not RestState.SHADOW
            }
        self.counters[f"cancel_everything_{reason.split(':')[0]}"] += 1

    # -- timers ------------------------------------------------------------------------------

    def _on_poll(self, event: Any) -> None:
        try:
            self._check_veto()
            self._resolve_instruments()
            self._poll_open_orders()
        except Exception as exc:  # noqa: BLE001 - L-16: a handler must never raise
            self._log_failure(f"{_CLASS_NAME}: poll timer failed", exc)

    def _poll_open_orders(self) -> None:
        for ladder in self.ladders.values():
            for rest in ladder.rests.values():
                if rest.state is not RestState.ACCEPTED or rest.client_order_id is None:
                    continue
                order = self.cache.order(rest.client_order_id)
                if order is not None and not order.is_closed:
                    self.query_order(order)

    def _on_hard_alert(self, event: Any) -> None:
        """D 09:00 LST. Falls after the permit window; a harmless backstop (R10-ERRATUM)."""
        _, station, day_text = str(event.name).split(":")
        ladder = self.ladders.get((station, dt.date.fromisoformat(day_text)))
        if ladder is None:
            return
        ladder.hard_cancelled = True
        for rung in ladder.rungs.values():
            self.cancel_all_orders(rung.no_id)
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

    def on_order_accepted(self, event: OrderAccepted) -> None:
        found = self._rest_for(event.client_order_id)
        if found is not None and found[2].state is RestState.SUBMITTED:
            found[2].state = RestState.ACCEPTED

    def on_order_canceled(self, event: OrderCanceled) -> None:
        self._close_rest(event.client_order_id, redecide=True)

    def on_order_expired(self, event: OrderExpired) -> None:
        self._close_rest(event.client_order_id, redecide=True)
        self._alert("MAKER_ORDER_EXPIRED", event.instrument_id, event.client_order_id, "INFO")

    def on_order_filled(self, event: OrderFilled) -> None:
        found = self._rest_for(event.client_order_id)
        if found is not None:
            ladder, rung_id, _ = found
            ladder.held.add(rung_id)
            del ladder.rests[rung_id]
        self._alert("MAKER_ORDER_FILLED", event.instrument_id, event.client_order_id, "INFO")

    def on_order_denied(self, event: OrderDenied) -> None:
        self._close_rest(event.client_order_id, redecide=False, backoff=True)
        self._alert("MAKER_ORDER_DENIED", event.instrument_id, event.client_order_id, "WARN")

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
