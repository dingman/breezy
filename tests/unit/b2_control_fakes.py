"""Offline doubles for the ARM B2 maker positive-control script (no venue contact).

``FakeVenue`` is a small in-memory state machine for the order lifecycle the control drives:
create (async rest), get-by-id, unfiltered open-orders list, per-order cancel, slug-scoped
cancel-all, GTD expiry on a fake clock, and the activities feed. The read double and the
write double are the project's own transports' protocols (``get`` / ``post``), so the real
``PolymarketUSHttpClient`` and ``PolymarketUSWriteTransport`` run over them unmodified.

Sentinel credential strings let tests prove the evidence never carries them.
"""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import re
import sys
import zlib
from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, cast

from breezy.adapters.polymarket_us.config import PolymarketUSMarketDiscoveryConfig
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.adapters.polymarket_us.write_transport import PolymarketUSWriteTransport

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"

API: Final[str] = "https://api.example.invalid"
GATEWAY: Final[str] = "https://gateway.example.invalid"
KEY_ID_SENTINEL: Final[str] = "KEYID-SENTINEL-0f3a9c1e-77aa-4b1b-9c0d-5e5e5e5e5e5e"
SIGNATURE_SENTINEL: Final[str] = ("SIGNATURESENTINEL" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789" * 2)[
    :86
] + "=="
NS: Final[int] = 1_000_000_000
START_NS: Final[int] = 1_792_000_000 * NS  # a fixed instant in 2026-10
START_NS_RUN_DAY: Final[int] = 1792627200 * NS  # 2026-10-22T00:00:00Z, the run date of the tests

SLUG_X: Final[str] = "tc-temp-nychigh-2026-10-22-lt56f"
SLUG_Y: Final[str] = "tc-temp-nychigh-2026-10-22-gte56lt57f"
SLUG_Z: Final[str] = "tc-temp-miahigh-2026-10-22-lt76f"
SLUG_LOW: Final[str] = "tc-temp-nyclow-2026-10-22-lt40f"
SLUG_CLOSED: Final[str] = "tc-temp-laxhigh-2026-10-20-gte64lt65f"
_TEMPLATE_DATE: Final[str] = "2026-04-22"
_SLUG_TAIL = re.compile(r"tc-temp-[a-z]{3}(?:high|low)-\d{4}-\d{2}-\d{2}-(?P<tail>.+)")


def _templates() -> dict[tuple[str, str], dict[str, Any]]:
    """Recorded climate markets keyed by (station, bounds tail): the wording corroborates bounds."""
    page = json.loads((RAW / "markets_categories_climate.json").read_text(encoding="utf-8"))
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for market in page["markets"]:
        match = _SLUG_TAIL.fullmatch(market["slug"])
        if match is not None:
            found.setdefault((market["slug"][8:11], match.group("tail")), market)
    return found


def market_payload(slug: str, *, closed: bool = False) -> dict[str, Any]:
    """A recorded market re-dated to the slug's date and re-opened (or closed)."""
    match = _SLUG_TAIL.fullmatch(slug)
    assert match is not None
    template = _templates().get((slug[8:11], match.group("tail")))
    if template is None:  # slugs the parser never sees (LOW / closed): any template will do
        template = next(iter(_templates().values()))
    market = copy.deepcopy(template)
    date = re.search(r"\d{4}-\d{2}-\d{2}", slug)
    assert date is not None
    market["slug"] = slug
    market["id"] = str(zlib.crc32(slug.encode("ascii")) % 10**6)
    market["description"] = market["description"].replace(_TEMPLATE_DATE, date.group(0))
    for side in market["marketSides"]:
        side["identifier"] = slug
    market.update(
        {
            "endDate": f"{_next_day(date.group(0))}T05:00:00Z",
            "closed": closed,
            "archived": False,
            "active": not closed,
            "status": "MARKET_STATUS_CLOSED" if closed else "MARKET_STATUS_OPEN",
            "ep3Status": "CLOSED" if closed else "OPEN",
            "orderPriceMinTickSize": 0.01,
            "minimumTradeQty": 0.01,
        }
    )
    return market


def _next_day(day: str) -> str:
    from datetime import date as _date
    from datetime import timedelta

    return (_date.fromisoformat(day) + timedelta(days=1)).isoformat()


def markets_page(*slugs: str, closed: frozenset[str] = frozenset()) -> dict[str, Any]:
    return {"markets": [market_payload(s, closed=s in closed) for s in slugs]}


class FakeVenue:
    """The venue: orders, expiry, scoping, and a log of every request it received."""

    def __init__(
        self,
        *,
        markets: Mapping[str, Any] | None = None,
        start_ns: int = START_NS,
    ) -> None:
        self.now_ns: int = start_ns
        self.markets: Mapping[str, Any] = (
            markets if markets is not None else markets_page(SLUG_X, SLUG_Y, SLUG_Z)
        )
        self.orders: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str]] = []  # (METHOD, path-without-query)
        self.post_bodies: list[tuple[str, dict[str, Any]]] = []
        self.account_wide_cancel_attempts = 0
        self.cancel_all_bodies: list[dict[str, Any]] = []
        self._next = 0
        # behaviours
        self.leak_cancel_all = False  # slug-scoped cancel-all also cancels other slugs
        self.expiry_lag_s = 0
        self.never_expire = False
        self.fail_create_nth: int | None = None  # 1-based create ordinal that returns 500
        self.fail_cancel_all = False
        self.raise_on_cancel_all: BaseException | None = None
        self.activities_status = 200
        self.activities_page: dict[str, Any] = {"activities": [], "eof": True}
        self.foreign_after_creates: int | None = None
        self.open_orders_status = 200
        self.open_orders_body_override: bytes | None = None
        self.creates = 0
        # quote (public bbo) behaviour: per-slug payload overrides, scripted sequences, status
        self.quote_overrides: dict[str, Any] = {}
        self.quote_script: dict[str, list[Any]] = {}
        self.quote_status = 200
        self.quote_reads: list[str] = []
        # create behaviour: the venue books the order, then the client sees a failure
        self.create_then_500_nth: int | None = None
        self.create_then_raise_nth: int | None = None
        self.fail_cancel_one = False
        # order-echo behaviour
        self.echo_tif: str | None = None
        self.echo_gtd_skew_s = 0
        self.expire_early_s = 0
        self.fill_on_get: dict[int, tuple[int, str]] = {}  # create ordinal -> (nth GET, state)
        # activities paging
        self.activities_pages: list[Any] | None = None
        self.activity_urls: list[str] = []

    # ------------------------------------------------------------------ helpers
    def clock(self) -> int:
        return self.now_ns

    async def sleep(self, seconds: float) -> None:
        self.now_ns += int(seconds * NS)

    def add_foreign_order(self, slug: str = SLUG_Z) -> str:
        order_id = self._new_id("FOREIGN")
        self.orders[order_id] = self._order_row(order_id, slug, own=False)
        return order_id

    def _new_id(self, prefix: str = "OWNORDER") -> str:
        self._next += 1
        return f"{prefix}{self._next:04d}"[-12:].rjust(12, "0").upper()

    def _order_row(self, order_id: str, slug: str, *, own: bool) -> dict[str, Any]:
        return {
            "id": order_id,
            "marketSlug": slug,
            "state": "ORDER_STATE_NEW",
            "tif": "TIME_IN_FORCE_GOOD_TILL_DATE",
            "goodTillTime": "",
            "quantity": 1,
            "cumQuantity": 0,
            "price": {"value": "0.99", "currency": "USD"},
            "side": "ORDER_SIDE_SELL",
            "_own": own,
        }

    def _expire(self) -> None:
        if self.never_expire:
            return
        for row in self.orders.values():
            gtd = row.get("goodTillTime")
            if row["state"] == "ORDER_STATE_NEW" and gtd and row.get("_own"):
                expiry = _parse_utc(gtd) + (self.expiry_lag_s - self.expire_early_s) * NS
                if self.now_ns >= expiry:
                    row["state"] = "ORDER_STATE_EXPIRED"

    @staticmethod
    def _public(row: Mapping[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in row.items() if not k.startswith("_")}

    def alive_own(self) -> list[str]:
        self._expire()
        return [
            i for i, r in self.orders.items() if r.get("_own") and r["state"] == "ORDER_STATE_NEW"
        ]

    def alive_all(self) -> list[str]:
        self._expire()
        return [i for i, r in self.orders.items() if r["state"] == "ORDER_STATE_NEW"]

    # ---------------------------------------------------------------------- GET
    def handle_get(self, url: str) -> VenueResponse:
        path = url.split("?", 1)[0]
        for prefix in (API, GATEWAY):
            path = path.removeprefix(prefix)
        self.requests.append(("GET", path))
        if path == "/v1/orders/open":
            if self.open_orders_body_override is not None:
                return _resp(self.open_orders_status, self.open_orders_body_override)
            self._expire()
            rows = [
                self._public(r) for r in self.orders.values() if r["state"] == "ORDER_STATE_NEW"
            ]
            return _json(self.open_orders_status, {"orders": rows, "eof": True})
        match = re.fullmatch(r"/v1/order/([A-Z0-9]{12})", path)
        if match:
            row = self.orders.get(match.group(1))
            if row is None:
                return _json(404, {"code": 5, "message": "not found"})
            self._expire()
            return _json(200, {"order": self._echoed(row)})
        quote = re.fullmatch(r"/v1/markets/([^/]+)/bbo", path)
        if quote:
            return self._quote(quote.group(1))
        if path == "/v1/portfolio/activities":
            self.activity_urls.append(url)
            if self.activities_pages is not None:
                index = min(len(self.activity_urls) - 1, len(self.activities_pages) - 1)
                return _json(self.activities_status, self.activities_pages[index])
            return _json(self.activities_status, self.activities_page)
        if path == "/v1/markets":
            return _json(200, self.markets)
        return _json(404, {})

    def _echoed(self, row: dict[str, Any]) -> dict[str, Any]:
        """The order as the GET shows it, with the configured echo skew and fill flips."""
        row["_gets"] = row.get("_gets", 0) + 1
        flip = self.fill_on_get.get(row.get("_create_n", -1))
        if flip is not None and row["_gets"] >= flip[0]:
            row["state"] = flip[1]
        shown = self._public(row)
        if self.echo_tif is not None:
            shown["tif"] = self.echo_tif
        if self.echo_gtd_skew_s and shown.get("goodTillTime"):
            shown["goodTillTime"] = _format_utc(
                _parse_utc(shown["goodTillTime"]) + self.echo_gtd_skew_s * NS
            )
        return shown

    def _quote(self, slug: str) -> VenueResponse:
        self.quote_reads.append(slug)
        if self.quote_status != 200:
            return _json(self.quote_status, {})
        scripted = self.quote_script.get(slug)
        if scripted:
            payload = scripted.pop(0) if len(scripted) > 1 else scripted[0]
        elif slug in self.quote_overrides:
            payload = self.quote_overrides[slug]
        else:
            payload = quote_payload(slug)
        if isinstance(payload, bytes):
            return _resp(200, payload)
        return _json(200, payload)

    # --------------------------------------------------------------------- POST
    def handle_post(self, url: str, body: bytes) -> VenueResponse:
        path = url.removeprefix(API)
        self.requests.append(("POST", path))
        payload = json.loads(body)
        self.post_bodies.append((path, payload))
        if path == "/v1/orders":
            return self._create(payload)
        match = re.fullmatch(r"/v1/order/([A-Z0-9]{12})/cancel", path)
        if match:
            return self._cancel_one(match.group(1), payload)
        if path == "/v1/orders/open/cancel":
            return self._cancel_all(payload)
        return _json(404, {})

    def _create(self, payload: Mapping[str, Any]) -> VenueResponse:
        self.creates += 1
        if self.fail_create_nth == self.creates:
            return _json(500, {"code": 13, "message": "internal"})
        order_id = self._new_id()
        row = self._order_row(order_id, payload["marketSlug"], own=True)
        row["goodTillTime"] = payload["goodTillTime"]
        row["tif"] = "TIME_IN_FORCE_GOOD_TILL_DATE"
        row["_create_n"] = self.creates
        self.orders[order_id] = row
        if self.foreign_after_creates is not None and self.creates == self.foreign_after_creates:
            self.add_foreign_order()
        if self.create_then_500_nth == self.creates:
            return _json(500, {"code": 13, "message": "internal"})
        if self.create_then_raise_nth == self.creates:
            raise ConnectionError("connection reset")
        return _json(200, {"id": order_id})

    def _cancel_one(self, order_id: str, payload: Mapping[str, Any]) -> VenueResponse:
        row = self.orders.get(order_id)
        if (
            row is None
            or set(payload) != {"marketSlug"}
            or payload["marketSlug"] != row["marketSlug"]
        ):
            return _json(400, {"code": 3, "message": "bad cancel"})
        if self.fail_cancel_one:
            return _json(500, {"code": 13})
        if row["state"] == "ORDER_STATE_NEW":
            row["state"] = "ORDER_STATE_CANCELED"
        return _json(200, {})

    def _cancel_all(self, payload: Mapping[str, Any]) -> VenueResponse:
        if self.raise_on_cancel_all is not None:
            raise self.raise_on_cancel_all
        self.cancel_all_bodies.append(dict(payload))
        slugs = payload.get("slugs")
        if not slugs:
            self.account_wide_cancel_attempts += 1
            for row in self.orders.values():
                if row["state"] == "ORDER_STATE_NEW":
                    row["state"] = "ORDER_STATE_CANCELED"
            return _json(200, {"canceledOrderIds": []})
        if self.fail_cancel_all:
            return _json(500, {"code": 13})
        for row in self.orders.values():
            if row["state"] != "ORDER_STATE_NEW":
                continue
            if row["marketSlug"] in slugs or self.leak_cancel_all:
                row["state"] = "ORDER_STATE_CANCELED"
        return _json(200, {"canceledOrderIds": []})


def _parse_utc(text: str) -> int:
    from datetime import UTC, datetime

    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()) * NS


def _format_utc(ns: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ns // NS, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def quote_payload(
    slug: str,
    *,
    bid: str = "0.4000",
    last: str = "0.4000",
    current: str = "0.4000",
    settlement: str = "0.4000",
    state: str = "MARKET_STATE_OPEN",
) -> dict[str, Any]:
    """A public ``bbo`` body (the recorded ``marketData`` envelope shape), values overridable."""

    def px(value: str) -> dict[str, str]:
        return {"value": value, "currency": "USD"}

    return {
        "marketData": {
            "marketSlug": slug,
            "currentPx": px(current),
            "lastTradePx": px(last),
            "settlementPx": px(settlement),
            "bestBid": px(bid),
            "bestAsk": px("0.4200"),
            "state": state,
        }
    }


def _resp(status: int, body: bytes) -> VenueResponse:
    return VenueResponse(status=status, headers={}, body=body)


def _json(status: int, payload: Any) -> VenueResponse:
    return _resp(status, json.dumps(payload).encode("utf-8"))


class FakeReadTransport:
    """A ``PolymarketUSReadTransport`` backed by the venue."""

    def __init__(self, venue: FakeVenue) -> None:
        self._venue = venue

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> VenueResponse:
        return self._venue.handle_get(url)


class _PostResponse:
    def __init__(self, response: VenueResponse) -> None:
        self.status = response.status
        self.headers = dict(response.headers)
        self.body = response.body


class FakePostClient:
    """A raw-pyo3-``HttpClient`` double exposing only ``post``; records every header set."""

    def __init__(self, venue: FakeVenue) -> None:
        self._venue = venue
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, *, headers: Any, body: bytes, keys: list[str]) -> Any:
        self.calls.append({"url": url, "headers": dict(headers), "body": body, "keys": list(keys)})
        return _PostResponse(self._venue.handle_post(url, body))


class FakeWriteSigner:
    """Stands in for ``Ed25519WriteRequestSigner``: records (method, path)."""

    def __init__(self) -> None:
        self.signed: list[tuple[str, str]] = []

    def sign_headers(self, method: str, path: str, **_: Any) -> list[tuple[str, str]]:
        self.signed.append((method, path))
        return [
            ("X-PM-Access-Key", KEY_ID_SENTINEL),
            ("X-PM-Timestamp", "1"),
            ("X-PM-Signature", SIGNATURE_SENTINEL),
        ]


class FakeReadSigner(FakeWriteSigner):
    pass


class QuietLog:
    def debug(self, message: str) -> None: ...
    def info(self, message: str) -> None: ...
    def warning(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...


Hook = Callable[[], None]


SCRIPT_PATH: Final[Path] = (
    REPO_ROOT / "scripts" / "venue" / "polymarket_us_maker_positive_control.py"
)


def load_control() -> Any:
    """The script's namespace merged over its pure sibling's (the script imports the sibling)."""
    spec = importlib.util.spec_from_file_location("breezy_b2_positive_control", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    core = sys.modules["_maker_control_core"]
    return SimpleNamespace(**{**vars(core), **vars(module)})


RUN_DATE: Final[str] = "2026-10-22"


class Rig:
    """One fake venue plus the real client stack over it."""

    def __init__(self, ctl: Any, venue: FakeVenue | None = None, budget: Any = None):
        self.ctl = ctl
        self.venue = venue or FakeVenue()
        self.post_client = FakePostClient(self.venue)
        self.write_signer = FakeWriteSigner()
        self.tap = ctl.StatusTap(inner=FakeReadTransport(self.venue))
        read_client = PolymarketUSHttpClient(
            transport=self.tap,
            signer=cast(Any, FakeReadSigner()),
            api_base_url=API,
            gateway_base_url=GATEWAY,
            logger=QuietLog(),
        )
        self.budget = budget if budget is not None else ctl.Budget()
        self.session = ctl.ControlSession(
            read_client=read_client,
            tap=self.tap,
            write_transport=PolymarketUSWriteTransport(client=self.post_client),
            write_signer=self.write_signer,
            api_base_url=API,
            gateway_base_url=GATEWAY,
            discovery=PolymarketUSMarketDiscoveryConfig(),
            now_ns=self.venue.clock,
            budget=self.budget,
        )

    def posts(self) -> list[tuple[str, dict[str, Any]]]:
        return self.venue.post_bodies

    def run(self) -> Any:
        return asyncio.run(
            self.ctl.run_control(self.session, sleep=self.venue.sleep, run_date=RUN_DATE)
        )


#: (payload, complete) open-orders replies under the exec client rule (S4 r4 section 5.5).
OPEN_ORDERS_ENVELOPES: list[tuple[Any, bool]] = [
    ({"orders": []}, True),  # eof absent counts complete (S4 r4 5.5)
    ({"orders": [], "eof": True}, True),
    ({"orders": [], "eof": False}, False),
    ({"orders": [], "eof": "true"}, False),
    ({"orders": [], "eof": None}, False),
    ({"orders": [], "nextCursor": "C"}, False),
    ({"orders": [], "eof": True, "nextCursor": "C"}, False),
    ({"orders": [], "surprise": 1}, False),
    ({"eof": True}, False),
    ({"orders": "x"}, False),
    ({"orders": [{"id": ""}]}, False),
    ({"orders": ["x"]}, False),
    ([], False),
    (None, False),
]
