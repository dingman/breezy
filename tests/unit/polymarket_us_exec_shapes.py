"""The SDK-snapshot payload shapes the R-3 exec suites are built from.

NOT a test module (no ``test_`` prefix, so pytest does not collect it) and NOT
a conftest: the fixture names here -- ``order``, ``execution``, ``position`` --
are generic enough that publishing them into every ``tests/unit`` module would
be name pollution, so each suite defines its own thin fixture over the builders
below and states which shapes it needs.

WHY THE SHAPES ARE CENTRAL RATHER THAN COPIED
----------------------------------------------

These dictionaries ARE the venue contract as transcribed from
``docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/``.
No live capture exists to check them against -- all four authenticated smoke
runs recorded ``Connectivity verdict: FAIL`` -- so a second, drifting copy of
an ``Order`` or a ``UserPosition`` would be a suite that passes against a shape
the mappers no longer accept, with nothing to point at the divergence. One copy,
imported by every exec suite, keeps that impossible.

The suites that use these:

* ``test_polymarket_us_exec_endpoints.py`` -- the decode and the balances mapper
* ``test_polymarket_us_exec_reports.py``   -- the order and fill mappers
* ``test_polymarket_us_exec_positions.py`` -- the position mapper
* ``test_polymarket_us_exec_snapshot_drift.py`` -- the allowlists (shape-free)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.identifiers import AccountId, ClientId
from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
RAW: Final[Path] = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
EXEC_DIR: Final[Path] = (
    REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us" / "exec"
)

EXEC_MODULES: Final[tuple[str, ...]] = ("client.py", "endpoints.py", "reports.py")

TS_INIT: Final[int] = 1_787_617_213_000_000_000
TS_EVENT_TEXT: Final[str] = "2026-08-25T00:19:48.120237895Z"
TS_EVENT_NANOS: Final[int] = 1_787_617_188_120_237_895

ACCOUNT_ID: Final[AccountId] = AccountId("POLYMARKET_US-001")
CLIENT_ID: Final[ClientId] = ClientId("POLYMARKET_US")
REPORT_ID: Final[UUID4] = UUID4()


def build_instrument() -> BinaryOption:
    """The instrument every exec suite maps onto, from a real captured market."""
    market: dict[str, Any] = json.loads(
        (RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8")
    )
    return parse_binary_option(market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def build_second_instrument() -> BinaryOption:
    """A SECOND, distinct instrument from a different captured market.

    Exists so a suite proving instrument-A-isolation (a corrupt record, a
    malformed payload) does not have to fabricate a synthetic slug: this is a
    real captured market, parsed the same way, with an ``InstrumentId``
    guaranteed distinct from :func:`build_instrument`'s.
    """
    market: dict[str, Any] = json.loads(
        (RAW / "market_closed_15806_by_slug.json").read_text(encoding="utf-8")
    )
    return parse_binary_option(market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def build_order(slug: str) -> dict[str, Any]:
    """An ``Order`` (``types/orders.py:70-92``), partially filled."""
    return {
        "id": "ord-7f3a",
        "marketSlug": slug,
        "side": "ORDER_SIDE_BUY",
        "type": "ORDER_TYPE_LIMIT",
        "price": {"value": "0.53", "currency": "USD"},
        "quantity": 10,
        "cumQuantity": 4,
        "leavesQuantity": 6,
        "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
        "state": "ORDER_STATE_PARTIALLY_FILLED",
        "avgPx": {"value": "0.52", "currency": "USD"},
        "createTime": TS_EVENT_TEXT,
        "insertTime": TS_EVENT_TEXT,
    }


def build_execution(order: dict[str, Any]) -> dict[str, Any]:
    """An ``Execution`` (``types/orders.py:95-108``) carrying a partial fill."""
    return {
        "id": "exe-11",
        "order": order,
        "lastShares": "4",
        "lastPx": {"value": "0.52", "currency": "USD"},
        "type": "EXECUTION_TYPE_PARTIAL_FILL",
        "transactTime": TS_EVENT_TEXT,
        "tradeId": "trd-902",
        "aggressor": True,
        "commissionNotionalCollected": {"value": "0.03", "currency": "USD"},
    }


def build_position(slug: str) -> dict[str, Any]:
    """A ``UserPosition`` (``types/portfolio.py:21-34``), long 4 and unsettled."""
    return {
        "netPosition": "4",
        "qtyBought": "4",
        "qtySold": "0",
        "cost": {"value": "2.08", "currency": "USD"},
        "realized": {"value": "0.00", "currency": "USD"},
        "bodPosition": "0",
        "expired": False,
        "updateTime": TS_EVENT_TEXT,
        "cashValue": {"value": "2.12", "currency": "USD"},
        "qtyAvailable": "4",
        "marketMetadata": {"slug": slug},
    }


def balances_body(literal: str) -> bytes:
    """A ``GetAccountBalancesResponse`` body with ``literal`` as a bare float."""
    return (
        b'{"balances": [{"currency": "USD", "currentBalance": '
        + literal.encode("ascii")
        + b', "buyingPower": '
        + literal.encode("ascii")
        + b', "lastUpdated": "'
        + TS_EVENT_TEXT.encode("ascii")
        + b'"}]}'
    )
