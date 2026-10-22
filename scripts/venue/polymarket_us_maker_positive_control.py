"""ARM B2 -- the Polymarket.us positive control for the RESTING-order path.

Authority: ``docs/plans/backlog/ARM_MAKER_SHARP_2026-10-21/plan_r1.md`` row B2,
``plan_r2_delta.md`` D3, ``plan_r3_delta.md`` R7 + R13 and
``MAKER_2026-10-12/S4_exec_resting_order_path_plan_r4_delta.md`` section 2 WP6.

**What it answers.** Whether the venue honours (S-1) a non-post-only GTD rest and a per-order
cancel that is GET-confirmed terminal, (S-2) a SLUG-SCOPED cancel-all that cancels the order on
slug X and leaves the order on slug Y alive, and (S-6) a short ``goodTillTime`` lapsing to
``ORDER_STATE_EXPIRED``. It also records the key names of the async rest response and the first
GET, and the shape (key names and enum values only) of the activities feed for the D1 work.

**It does NOT flip any ``*_VERIFIED`` constant.** A separate reviewed commit does that from the
evidence file this run writes under ``docs/evidence/b2/``.

**One-shot.** ``--run-date YYYY-MM-DD`` must equal today (UTC); there is no timer. Every
precondition below refuses (exit 2) before any write:

1. the run date equals today (UTC);
2. credentials come ONLY from ``~/.config/breezy`` (the env file, mode 0600, and the secret key
   file it names must both live there; the process environment is never consulted for them);
3. no ``breezy-trade-*`` unit other than the supervisor is active (R13);
4. an unfiltered open-orders GET is 200 and shows zero orders;
5. the budget constants are enforced in code (:class:`Budget`).

**Bodies** are built ONLY by ``submit_chain.build_resting_order_body`` (BUY NO, qty 1, price
0.01, GTD at most ten minutes ahead, re-checked at send time). Every write goes through the
shipped :class:`PolymarketUSWriteTransport` methods; this file builds no write request by hand.
The slug-scoped cancel-all is reachable only through :meth:`ControlSession.cancel_slugs`, which
refuses an empty, duplicated or malformed slug list before anything is signed or sent: the venue
reads an empty list as "cancel the whole account", so that body is unconstructible here.

**Evidence** carries key names, status codes, our own order ids and this script's constants
only: no headers, signatures, key id, raw bodies, amounts or other accounts' ids. URLs go
through ``redact_url``. Files are ``0600``.

Exit codes: 0 all steps ran and the account is clean; 1 a step failed (own orders were cancelled
by id first) or the account was not clean at the end; 2 a precondition refused.
"""

from __future__ import annotations

import asyncio
import resource
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import StrategyId, TraderId
from nautilus_trader.model.objects import Price, Quantity

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_DIRECTORY = Path(__file__).resolve().parent
for _entry in (REPO_ROOT / "src", _SCRIPT_DIRECTORY):  # pragma: no cover - bootstrap
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from _maker_control_core import (  # type: ignore[import-not-found]
    CONFIG_DIR,
    CONFIRM_INTERVAL_S,
    CONFIRM_POLLS,
    ENV_FILE_NAME,
    EVIDENCE_DIR,
    EXPIRY_INTERVAL_S,
    EXPIRY_POLLS,
    FILL_STATES,
    GTD_CEILING_SECS,
    NS_PER_S,
    PROBE_PRICE,
    PROBE_QUANTITY,
    REST_GTD_SECS,
    SHORT_GTD_SECS,
    STATE_CANCELED,
    STATE_EXPIRED,
    STATE_NEW,
    TERMINAL_STATES,
    VERDICT_FAIL,
    VERDICT_NOT_RUN,
    VERDICT_PASS,
    VERDICT_SKIPPED,
    Budget,
    BudgetExhausted,
    ControlResult,
    Deps,
    Observation,
    OwnOrder,
    PostResult,
    ProbeSlugs,
    QuietLog,
    Reading,
    Refusal,
    RunState,
    StatusTap,
    StepFailed,
    assert_gtd_within_ceiling,
    assert_no_trade_node,
    capture_activity_shape,
    enum_token,
    gtd_echoed,
    key_paths,
    list_units_via_systemctl,
    load_env_file,
    markets_by_slug,
    open_order_ids,
    parse_args,
    parse_json,
    parse_utc_ns,
    require_run_date,
    write_evidence,
)
from _maker_control_core import (
    select_probe_slugs as select_slugs,
)
from _write_sequence import market_list_query  # type: ignore[import-not-found]

from breezy.adapters.polymarket_us import provider as _provider
from breezy.adapters.polymarket_us.account_activity import PORTFOLIO_ACTIVITIES_PATH
from breezy.adapters.polymarket_us.config import (
    PolymarketUSDataClientConfig,
    PolymarketUSMarketDiscoveryConfig,
)
from breezy.adapters.polymarket_us.env import load_polymarket_us_credentials
from breezy.adapters.polymarket_us.errors import PolymarketUSError
from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.exec.endpoints import (
    OPEN_ORDERS_PATH,
    cancel_order_path,
    order_by_id_path,
    valid_venue_order_id,
)
from breezy.adapters.polymarket_us.exec.reports import ORDER_STATE_TO_ORDER_STATUS
from breezy.adapters.polymarket_us.factories import config_from_env
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.parsing import parse_binary_option_pair
from breezy.adapters.polymarket_us.provider import discovery_candidate_slugs
from breezy.adapters.polymarket_us.redaction import redact_url
from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner, SigningVariant
from breezy.adapters.polymarket_us.transport import (
    QUOTA_KEY_DISCOVERY,
    QUOTA_KEY_PORTFOLIO,
    NautilusHttpTransport,
    build_default_quota,
    build_keyed_quotas,
    build_shared_http_client,
)
from breezy.adapters.polymarket_us.write_transport import (
    CANCEL_ALL_PATH,
    ORDERS_PATH,
    PERMITTED_WRITE_METHODS,
    Ed25519WriteRequestSigner,
    PolymarketUSWriteTransport,
)

_WRITE_METHOD: Final[str] = next(iter(PERMITTED_WRITE_METHODS))
ACTIVITIES_PAGE_LIMIT: Final[int] = 100


def select_probe_slugs(
    payload: Mapping[str, Any], *, city_codes: tuple[str, ...]
) -> ProbeSlugs | None:
    """Two distinct, open daily-HIGH slugs (see :func:`_maker_control_core.select_probe_slugs`)."""
    try:
        candidates = discovery_candidate_slugs(payload, city_codes=city_codes)
    except (PolymarketUSError, TypeError, ValueError):
        return None
    return select_slugs(
        payload,
        candidates=candidates,
        is_daily_high=submit_chain.is_daily_high_slug,
        is_resolved=lambda market: _provider._resolved_reason(market) is not None,
    )


# ----------------------------------------------------------------------------- session


class ControlSession:
    """Every venue call of the control, budget-counted and trace-recorded.

    Reads go through :class:`PolymarketUSHttpClient` (GET only); writes go through the shipped
    :class:`PolymarketUSWriteTransport` methods. Each call records one trace step: operation
    label, redacted URL, status, and the response's key paths.
    """

    def __init__(
        self,
        *,
        read_client: PolymarketUSHttpClient,
        tap: StatusTap,
        write_transport: PolymarketUSWriteTransport,
        write_signer: Any,
        api_base_url: str,
        gateway_base_url: str,
        discovery: PolymarketUSMarketDiscoveryConfig,
        now_ns: Callable[[], int],
        budget: Budget,
    ) -> None:
        self._read = read_client
        self._tap = tap
        self._write = write_transport
        self._signer = write_signer
        self._api_base = str(api_base_url).rstrip("/")
        self._gateway_base = str(gateway_base_url).rstrip("/")
        self._discovery = discovery
        self._now_ns = now_ns
        self.budget = budget
        self.trace: list[dict[str, Any]] = []
        self._markets: dict[str, Mapping[str, Any]] = {}
        self._factory = OrderFactory(
            trader_id=TraderId("BREEZY-B2-001"),
            strategy_id=StrategyId("B2CONTROL-001"),
            clock=LiveClock(),
        )

    @property
    def discovery(self) -> PolymarketUSMarketDiscoveryConfig:
        return self._discovery

    def now_ns(self) -> int:
        return self._now_ns()

    def _record(self, op: str, url: str, status: int | None, payload: object) -> None:
        self.trace.append(
            {
                "n": len(self.trace) + 1,
                "op": op,
                "url": redact_url(url),
                "status": status,
                "keys": key_paths(payload),
            }
        )

    async def _get(
        self,
        op: str,
        path: str,
        *,
        public: bool = False,
        query: Mapping[str, object] | None = None,
        quota_key: str = QUOTA_KEY_PORTFOLIO,
    ) -> Reading:
        self.budget.spend_get()
        self._tap.last_status = None
        payload: Any = None
        try:
            if public:
                payload = await self._read.get_public(path, query=query, quota_key=quota_key)
            else:
                payload = await self._read.get_authenticated(path, query=query, quota_key=quota_key)
        except PolymarketUSError:
            payload = None
        base = self._gateway_base if public else self._api_base
        self._record(op, f"{base}{path}", self._tap.last_status, payload)
        return Reading(self._tap.last_status, payload)

    async def get_open_orders(self, op: str = "get_open_orders") -> Reading:
        return await self._get(op, OPEN_ORDERS_PATH)

    async def get_order(self, order_id: str, op: str = "get_order") -> Reading:
        return await self._get(op, order_by_id_path(order_id))

    async def get_activities(self) -> Reading:
        return await self._get(
            "get_activities",
            PORTFOLIO_ACTIVITIES_PATH,
            query={"limit": ACTIVITIES_PAGE_LIMIT},
        )

    async def list_markets(self) -> Reading:
        reading = await self._get(
            "list_markets",
            "/v1/markets",
            public=True,
            query=market_list_query(self._discovery),
            quota_key=QUOTA_KEY_DISCOVERY,
        )
        if isinstance(reading.payload, Mapping):
            self._markets = markets_by_slug(reading.payload)
        return reading

    def _build_resting_body(self, slug: str, gtd_secs: int) -> dict[str, Any]:
        if not 0 < gtd_secs <= GTD_CEILING_SECS:
            raise ValueError(f"GTD must be within (0, {GTD_CEILING_SECS}] seconds")
        market = self._markets.get(slug)
        if market is None:
            raise ValueError("slug is not in the listed markets")
        now_ns = self._now_ns()
        _yes, no_leg = parse_binary_option_pair({"market": market}, ts_init=now_ns)
        if no_leg is None:
            raise ValueError("market has no NO leg")
        order = self._factory.limit(
            instrument_id=no_leg.id,
            order_side=OrderSide.BUY,
            quantity=Quantity(PROBE_QUANTITY, no_leg.size_precision),
            price=Price.from_str(str(PROBE_PRICE)),
            time_in_force=TimeInForce.GTD,
            expire_time=pd.Timestamp(now_ns + gtd_secs * NS_PER_S, unit="ns", tz="UTC"),
        )
        return submit_chain.build_resting_order_body(order, no_leg)

    async def rest(self, label: str, slug: str, gtd_secs: int) -> PostResult:
        """Rest one probe order. The body is ``build_resting_order_body``'s, nothing else."""
        body = self._build_resting_body(slug, gtd_secs)
        assert_gtd_within_ceiling(body, now_ns=self._now_ns())
        encoded = submit_chain.encode_order_body(body)
        self.budget.spend_create()
        headers = self._signer.sign_headers(_WRITE_METHOD, ORDERS_PATH)
        op = f"rest_{label}"
        url = f"{self._api_base}{ORDERS_PATH}"
        try:
            response = await self._write.post_order(self._api_base, headers=headers, body=encoded)
        except PolymarketUSError:
            self._record(op, url, None, None)
            raise
        payload = parse_json(response.body)
        self._record(op, url, int(response.status), payload)
        raw_id = payload.get("id") if isinstance(payload, Mapping) else None
        order_id = raw_id if valid_venue_order_id(raw_id) else None
        sent_gtd_ns = parse_utc_ns(body["goodTillTime"])
        return PostResult(int(response.status), payload, order_id, sent_gtd_ns)

    async def retract_order(self, order_id: str, slug: str, op: str = "cancel_order") -> PostResult:
        path = cancel_order_path(order_id)  # ValueError on an invalid id
        self.budget.spend_cancel()
        headers = self._signer.sign_headers(_WRITE_METHOD, path)
        url = f"{self._api_base}{path}"
        try:
            response = await self._write.post_cancel_order(
                self._api_base, headers=headers, order_id=order_id, market_slug=slug
            )
        except PolymarketUSError:
            self._record(op, url, None, None)
            raise
        payload = parse_json(response.body)
        self._record(op, url, int(response.status), payload)
        return PostResult(int(response.status), payload)

    async def cancel_slugs(self, slugs: Sequence[str]) -> PostResult:
        """The slug-scoped cancel-all. An empty or malformed list is refused before signing."""
        if isinstance(slugs, (str, bytes)) or not isinstance(slugs, (list, tuple)):
            raise TypeError("slugs must be a list or tuple of market slugs")
        checked = list(slugs)
        if not checked:
            raise ValueError("slugs must be non-empty: an empty list cancels the whole account")
        if len(set(checked)) != len(checked):
            raise ValueError("slugs must not contain duplicates")
        if not all(submit_chain.is_daily_high_slug(s) for s in checked):
            raise ValueError("every slug must be a daily HIGH market slug")
        self.budget.spend_cancel()
        headers = self._signer.sign_headers(_WRITE_METHOD, CANCEL_ALL_PATH)
        url = f"{self._api_base}{CANCEL_ALL_PATH}"
        try:
            response = await self._write.post_cancel_all(
                self._api_base, headers=headers, slugs=checked
            )
        except PolymarketUSError:
            self._record("cancel_all", url, None, None)
            raise
        payload = parse_json(response.body)
        self._record("cancel_all", url, int(response.status), payload)
        return PostResult(int(response.status), payload)


def _observe(reading: Reading) -> Observation:
    payload = reading.payload
    order = payload.get("order") if isinstance(payload, Mapping) else None
    if not isinstance(order, Mapping):
        return Observation(reading.status, None, None, None, True)
    state = order.get("state")
    tif = order.get("tif")
    try:
        gtd_ns: int | None = parse_utc_ns(order.get("goodTillTime"))
    except ValueError:
        gtd_ns = None
    return Observation(
        reading.status,
        state if isinstance(state, str) and state in ORDER_STATE_TO_ORDER_STATUS else None,
        tif if isinstance(tif, str) and enum_token(tif) else None,
        gtd_ns,
        False,
    )


async def _await_state(
    session: ControlSession,
    own: OwnOrder,
    *,
    tag: str,
    want: frozenset[str],
    polls: int,
    interval_s: float,
    sleep: Callable[[float], Awaitable[None]],
) -> Observation | None:
    """Poll the order-by-id read until its state is in ``want``; ``None`` if it never is.

    A fill raises :class:`StepFailed` at once (a probe order resting at a cent should not
    fill; if it did, stop and clean up). A 404 or unreadable GET just polls again.
    """
    assert own.order_id is not None
    last: Observation | None = None
    for attempt in range(1, polls + 1):
        if attempt > 1:
            await sleep(interval_s)
        last = _observe(await session.get_order(own.order_id, f"get_{tag}_{attempt}"))
        if last.state in FILL_STATES:
            own.terminal = True
            raise StepFailed("ORDER_FILLED")
        if last.state in want:
            if last.state in TERMINAL_STATES:
                own.terminal = True
            return last
        if last.state in TERMINAL_STATES:
            own.terminal = True
            return None
    return None


async def _rest(
    session: ControlSession, state: RunState, label: str, slug: str, gtd: int
) -> OwnOrder:
    own = OwnOrder(label=label, slug=slug, gtd_secs=gtd)
    state.orders[label] = own
    result = await session.rest(label, slug, gtd)
    if result.status != 200:
        raise StepFailed("CREATE_REFUSED")
    if result.order_id is None:
        state.unknown_create = True
        raise StepFailed("CREATE_NO_VALID_ID")
    own.order_id = result.order_id
    own.sent_gtd_ns = result.sent_gtd_ns
    return own


async def _confirm_new(
    session: ControlSession,
    own: OwnOrder,
    sleep: Callable[[float], Awaitable[None]],
    *,
    tag: str,
) -> Observation:
    obs = await _await_state(
        session,
        own,
        tag=tag,
        want=frozenset({STATE_NEW}),
        polls=CONFIRM_POLLS,
        interval_s=CONFIRM_INTERVAL_S,
        sleep=sleep,
    )
    if obs is None:
        raise StepFailed("NEW_NOT_CONFIRMED")
    return obs


# -------------------------------------------------------------------------- sequence


async def _sequence(
    session: ControlSession,
    state: RunState,
    sleep: Callable[[float], Awaitable[None]],
) -> None:
    # D1: one activities page, key names only. Informational: never gates the run.
    reading = await session.get_activities()
    state.activities = {"http_status": reading.status, **capture_activity_shape(reading.payload)}

    markets = await session.list_markets()
    chosen = (
        select_probe_slugs(markets.payload, city_codes=session.discovery.city_codes)
        if isinstance(markets.payload, Mapping)
        else None
    )
    if chosen is None:
        raise StepFailed("NO_ELIGIBLE_SLUGS")
    slug_x, slug_y = chosen.slugs
    state.slugs = chosen.slugs
    state.share_event = chosen.share_event

    # --- S-1: rest A, GET-confirm NEW, per-order cancel, GET-confirm terminal ----------
    state.phase = "S-1"
    order_a = await _rest(session, state, "A", slug_x, REST_GTD_SECS)
    obs = await _confirm_new(session, order_a, sleep, tag="A")
    state.details["gtd_tif_echoed"] = gtd_echoed(obs, order_a)
    cancel_a = await session.retract_order(order_a.order_id or "", slug_x, "cancel_A")
    state.details["per_order_cancel_status"] = cancel_a.status
    if cancel_a.status != 200:
        raise StepFailed("PER_ORDER_CANCEL_REFUSED")
    terminal = await _await_state(
        session,
        order_a,
        tag="A_cancel",
        want=frozenset({STATE_CANCELED}),
        polls=CONFIRM_POLLS,
        interval_s=CONFIRM_INTERVAL_S,
        sleep=sleep,
    )
    if terminal is None:
        raise StepFailed("CANCEL_NOT_TERMINAL")
    state.verdicts["S-1"] = VERDICT_PASS

    # --- set-up for S-2: A' on X, B on Y (short GTD) -----------------------------------
    state.phase = "setup"
    order_ap = await _rest(session, state, "A_prime", slug_x, REST_GTD_SECS)
    await _confirm_new(session, order_ap, sleep, tag="A_prime")
    order_b = await _rest(session, state, "B", slug_y, SHORT_GTD_SECS)
    await _confirm_new(session, order_b, sleep, tag="B")

    # --- S-2: only if the account holds nothing but our own two orders -------------------
    state.phase = "S-2"
    listing = await session.get_open_orders("foreign_check")
    ids = open_order_ids(listing.payload) if listing.status == 200 else None
    own_ids = {order_ap.order_id, order_b.order_id}
    if ids is None or not ids <= own_ids:
        state.verdicts["S-2"] = VERDICT_SKIPPED
        cancelled = await session.retract_order(order_ap.order_id or "", slug_x, "cancel_A_prime")
        if cancelled.status != 200:
            raise StepFailed("PER_ORDER_CANCEL_REFUSED")
        if (
            await _await_state(
                session,
                order_ap,
                tag="A_prime_cancel",
                want=frozenset({STATE_CANCELED}),
                polls=CONFIRM_POLLS,
                interval_s=CONFIRM_INTERVAL_S,
                sleep=sleep,
            )
            is None
        ):
            raise StepFailed("CANCEL_NOT_TERMINAL")
    else:
        sent = await session.cancel_slugs([slug_x])
        state.details["cancel_all_status"] = sent.status
        if sent.status != 200:
            state.verdicts["S-2"] = VERDICT_FAIL
            raise StepFailed("CANCEL_ALL_REFUSED")
        a_obs = await _await_state(
            session,
            order_ap,
            tag="A_prime_after_cancel_all",
            want=frozenset({STATE_CANCELED}),
            polls=CONFIRM_POLLS,
            interval_s=CONFIRM_INTERVAL_S,
            sleep=sleep,
        )
        state.details["s2_a_prime_state"] = None if a_obs is None else a_obs.state
        b_obs = _observe(await session.get_order(order_b.order_id or "", "get_B_after_cancel_all"))
        state.details["s2_b_state_after_cancel_all"] = b_obs.state
        if b_obs.state in TERMINAL_STATES:
            order_b.terminal = True
        if a_obs is None or b_obs.state != STATE_NEW:
            state.verdicts["S-2"] = VERDICT_FAIL
            raise StepFailed("S2_SCOPE_MISMATCH")
        state.verdicts["S-2"] = VERDICT_PASS

    # --- S-6: B's short GTD lapses ---------------------------------------------------------
    state.phase = "S-6"
    expired = await _await_state(
        session,
        order_b,
        tag="B_expiry",
        want=frozenset({STATE_EXPIRED}),
        polls=EXPIRY_POLLS,
        interval_s=EXPIRY_INTERVAL_S,
        sleep=sleep,
    )
    state.details["s6_final_state"] = None if expired is None else expired.state
    if expired is None:
        raise StepFailed("S6_NOT_EXPIRED")
    state.verdicts["S-6"] = VERDICT_PASS

    await _final_clean_check(session, state)


async def _final_clean_check(session: ControlSession, state: RunState) -> None:
    try:
        reading = await session.get_open_orders("final_clean_check")
    except BudgetExhausted:
        state.final_account_clean = None
        return
    ids = open_order_ids(reading.payload) if reading.status == 200 else None
    state.final_account_clean = None if ids is None else len(ids) == 0


async def _cleanup(
    session: ControlSession,
    state: RunState,
    sleep: Callable[[float], Awaitable[None]],
) -> None:
    """Cancel every own order that is not known terminal, by id, longest GTD first.

    The cancel budget is NOT lifted: an order the budget refuses is left to its (short) GTD and
    polled until it reads EXPIRED, which is recorded as ``left_to_gtd``. Cancel-all is never used
    here.
    """
    pending = sorted(
        (o for o in state.orders.values() if o.order_id and not o.terminal),
        key=lambda o: -o.gtd_secs,
    )
    left: list[OwnOrder] = []
    for own in pending:
        try:
            result = await session.retract_order(
                own.order_id or "", own.slug, f"cleanup_{own.label}"
            )
        except BudgetExhausted:
            left.append(own)
            continue
        except Exception as exc:  # noqa: BLE001 - cleanup must try every order
            state.cleanup["errors"].append(type(exc).__name__)
            continue
        if result.status == 200:
            own.terminal = True
            state.cleanup["cancelled"].append(own.label)
        else:
            state.cleanup["errors"].append(f"HTTP_{result.status}")
    if state.unknown_create:
        await _cleanup_by_listing(session, state)
    for own in left:
        state.cleanup["left_to_gtd"].append(own.label)
        try:
            lapsed = await _await_state(
                session,
                own,
                tag=f"cleanup_{own.label}_lapse",
                want=frozenset({STATE_EXPIRED, STATE_CANCELED}),
                polls=EXPIRY_POLLS,
                interval_s=EXPIRY_INTERVAL_S,
                sleep=sleep,
            )
        except (PolymarketUSError, StepFailed) as exc:
            state.cleanup["errors"].append(type(exc).__name__)
            continue
        if lapsed is None:
            state.cleanup["errors"].append("LEFT_ORDER_NOT_LAPSED")
    await _final_clean_check(session, state)


async def _cleanup_by_listing(session: ControlSession, state: RunState) -> None:
    """A create answered 200 without a usable id: cancel what rests on our probe slugs."""
    try:
        listing = await session.get_open_orders("cleanup_listing")
    except BudgetExhausted:
        return
    payload = listing.payload
    orders = payload.get("orders") if isinstance(payload, Mapping) else None
    if not isinstance(orders, list):
        return
    for order in orders:
        if not isinstance(order, Mapping):
            continue
        order_id, slug = order.get("id"), order.get("marketSlug")
        if valid_venue_order_id(order_id) and slug in state.slugs:
            try:
                await session.retract_order(str(order_id), str(slug), "cleanup_by_listing")
            except Exception as exc:  # noqa: BLE001
                state.cleanup["errors"].append(type(exc).__name__)
            else:
                state.cleanup["cancelled"].append("listed")


async def run_control(
    session: ControlSession,
    *,
    sleep: Callable[[float], Awaitable[None]],
    run_date: str,
    state: RunState | None = None,
) -> ControlResult:
    """Run S-1, S-2, S-6 in order. Any failure cancels own orders by id and exits non-zero."""
    active = (
        state if state is not None else RunState(run_date=run_date, started_ns=session.now_ns())
    )
    try:
        await _sequence(session, active, sleep)
    except BaseException as exc:
        if isinstance(exc, StepFailed):
            active.failure = str(exc.args[0])
        else:
            active.failure = (
                "BUDGET_EXHAUSTED" if isinstance(exc, BudgetExhausted) else type(exc).__name__
            )
        if active.phase == "S-1" and active.verdicts["S-1"] == VERDICT_NOT_RUN:
            active.verdicts["S-1"] = VERDICT_FAIL
        elif active.phase == "S-6" and active.verdicts["S-6"] == VERDICT_NOT_RUN:
            active.verdicts["S-6"] = VERDICT_FAIL
        elif active.phase == "S-2" and active.verdicts["S-2"] == VERDICT_NOT_RUN:
            active.verdicts["S-2"] = VERDICT_FAIL
        await _cleanup(session, active, sleep)
        if not isinstance(exc, Exception):
            raise
    document = active.document(session)
    return ControlResult(document, 0 if document["outcome"] == VERDICT_PASS else 1)


# ------------------------------------------------------------------------ entrypoint


async def _require_clean_account(session: ControlSession) -> None:
    reading = await session.get_open_orders("preflight_open_orders")
    if reading.status != 200:
        raise Refusal("PREFLIGHT_NOT_200")
    ids = open_order_ids(reading.payload)
    if ids is None:
        raise Refusal("PREFLIGHT_UNREADABLE")
    if ids:
        raise Refusal("PREFLIGHT_ACCOUNT_NOT_EMPTY")


async def run(run_date: str, deps: Deps) -> int:
    """Preconditions, then the control, then the evidence file. Returns the exit code."""
    try:
        require_run_date(run_date, deps.today_utc())
        env = deps.load_env()
        assert_no_trade_node(deps.list_units())
        session = deps.build_session(env)
        await _require_clean_account(session)
    except Refusal as exc:
        print(f"B2_CONTROL REFUSED code={exc.code}", file=sys.stderr)
        return 2
    except BudgetExhausted:
        print("B2_CONTROL REFUSED code=BUDGET_EXHAUSTED", file=sys.stderr)
        return 2
    state = RunState(run_date=run_date, started_ns=session.now_ns())
    try:
        result = await run_control(session, sleep=deps.sleep, run_date=run_date, state=state)
    except BaseException:
        write_evidence(state.document(session), deps.evidence_dir, stamp=deps.stamp())
        raise
    path = write_evidence(result.document, deps.evidence_dir, stamp=deps.stamp())
    verdicts = " ".join(f"{k}={v}" for k, v in result.document["verdicts"].items())
    print(f"B2_CONTROL outcome={result.document['outcome']} {verdicts} evidence={path}")
    exit_code: int = result.exit_code
    return exit_code


def _build_production_session(env: Mapping[str, str]) -> ControlSession:
    config: PolymarketUSDataClientConfig = config_from_env(env)
    credentials = load_polymarket_us_credentials(config.secrets, env=env)
    clock = LiveClock()
    client = build_shared_http_client(
        timeout_secs=config.http_timeout_secs,
        default_quota=build_default_quota(config.global_requests_per_second),
        keyed_quotas=build_keyed_quotas(
            discovery_requests_per_minute=config.discovery_requests_per_minute,
            instrument_requests_per_minute=config.instrument_requests_per_minute,
            book_requests_per_minute=config.book_requests_per_minute,
        ),
        default_headers={"User-Agent": str(config.user_agent)},
    )
    tap = StatusTap(inner=NautilusHttpTransport(client=client))
    read_client = PolymarketUSHttpClient(
        transport=tap,
        signer=Ed25519RequestSigner.for_variant(
            credentials, clock=clock, variant=SigningVariant(config.signing_variant)
        ),
        api_base_url=str(config.api_base_url),
        gateway_base_url=str(config.gateway_base_url),
        logger=QuietLog(),
    )
    return ControlSession(
        read_client=read_client,
        tap=tap,
        write_transport=PolymarketUSWriteTransport(client=client),
        write_signer=Ed25519WriteRequestSigner(credentials, clock=clock),
        api_base_url=str(config.api_base_url),
        gateway_base_url=str(config.gateway_base_url),
        discovery=PolymarketUSMarketDiscoveryConfig(),
        now_ns=time.time_ns,
        budget=Budget(),
    )


def _production_deps() -> Deps:
    return Deps(
        today_utc=lambda: datetime.now(UTC).date().isoformat(),
        list_units=list_units_via_systemctl,
        load_env=lambda: load_env_file(CONFIG_DIR / ENV_FILE_NAME),
        build_session=_build_production_session,
        sleep=asyncio.sleep,
        evidence_dir=EVIDENCE_DIR,
        stamp=lambda: datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        return asyncio.run(run(args.run_date, _production_deps()))
    except Exception as exc:  # noqa: BLE001 - the class name is the whole message
        print(f"B2_CONTROL ERROR error={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
