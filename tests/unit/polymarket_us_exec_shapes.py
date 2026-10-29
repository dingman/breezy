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

from breezy.adapters.polymarket_us.parsing import parse_binary_option, parse_binary_option_pair
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
RAW: Final[Path] = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
EXEC_DIR: Final[Path] = (
    REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us" / "exec"
)

EXEC_MODULES: Final[tuple[str, ...]] = (
    "client.py",
    "endpoints.py",
    # EXEC SPINE R-6d. Listed so the `float(` ban and the
    # no-parallel-report-class scan in `test_polymarket_us_exec_endpoints.py`
    # cover the refusal classifier too; an inventory that lags the
    # directory silently exempts whatever was added last.
    "refusals.py",
    "reports.py",
    "submit_chain.py",
)

TS_INIT: Final[int] = 1_787_617_213_000_000_000
TS_EVENT_TEXT: Final[str] = "2026-08-25T00:19:48.120237895Z"
TS_EVENT_NANOS: Final[int] = 1_787_617_188_120_237_895

ACCOUNT_ID: Final[AccountId] = AccountId("POLYMARKET_US-001")
CLIENT_ID: Final[ClientId] = ClientId("POLYMARKET_US")
REPORT_ID: Final[UUID4] = UUID4()

#: EXEC-FOREIGN-POS. Real slug spellings; every other field on the builders below is synthetic.
CROSSD: Final[str] = "crossd-ba05d7244fbd670a"
ASTATC: Final[str] = "astatc-nba-gs-min-2026-10-28-ast-ayodos-gte10"
AEC: Final[str] = "aec-nfl-lar-den-2026-09-27"
UNLOADED: Final[str] = "tc-temp-laxhigh-2026-08-24-gte80lt81f"
UNPARSEABLE_W: Final[str] = "tc-temp-lax-2026-08-25-gte70lt71f"
FRGN: Final[str] = "FRGN00000001"  # Stage B uses this synthetic venue order id


def build_instrument() -> BinaryOption:
    """The instrument every exec suite maps onto, from a real captured market."""
    market: dict[str, Any] = json.loads(
        (RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8")
    )
    return parse_binary_option(market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def build_no_leg_instrument() -> BinaryOption:
    """The NO leg of :func:`build_instrument`'s SAME market (FU-8).

    Built through `parse_binary_option_pair`'s ONE bijection
    (`symbology.no_leg_instrument_id`), so this is guaranteed the true
    sibling of `build_instrument()`'s YES leg -- never an independently
    parsed pair that only coincidentally shares a slug.
    """
    market: dict[str, Any] = json.loads(
        (RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8")
    )
    _yes, no_instrument = parse_binary_option_pair(
        market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT,
    )
    assert no_instrument is not None
    return no_instrument


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
        # Rev 5 (E5-2): the venue always echoes `intent` on an Order; the YES
        # leg's own values (`assert_echo_matches_leg`), matching the default
        # `side` above. Every pre-existing caller of this fixture drives a
        # YES-leg instrument, so this is additive, not a behaviour change.
        "intent": "ORDER_INTENT_BUY_LONG",
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


def _combo_leg(label: str) -> dict[str, Any]:
    """One synthetic parlay leg: the 17 observed keys, including ``team``."""
    team: dict[str, Any] = {
        "abbreviation": "syn",
        "alias": "syn",
        "awayIcon": "syn-away",
        "color": {"dark": "000000", "light": "ffffff"},
        "colorPrimary": "000000",
        "displayAbbreviation": "SYN",
        "homeIcon": "syn-home",
        "id": 1,
        "imageDisplayType": "SYNTHETIC",
        "league": "syn",
        "logo": "syn-logo",
        "longIcon": "syn-long",
        "longIconDark": "syn-long-dark",
        "name": "Synthetic",
        "ordering": "home",
        "providerId": 1,
        "providerIds": [{"provider": "synthetic", "providerId": "p1"}],
        "record": "0-0",
        "safeName": "synthetic",
        "shortIcon": "syn-short",
        "shortIconDark": "syn-short-dark",
    }
    return {
        "eventGroupTitle": "Synthetic event",
        "eventId": "evt-synthetic",
        "eventSlug": "evt-synthetic",
        "eventStartTime": TS_EVENT_TEXT,
        "icon": "syn-icon",
        "indicativePrice": {"currency": "USD", "value": "0.50"},
        "label": label,
        "live": False,
        "outcome": "Yes",
        "outcomeSide": "OUTCOME_SIDE_YES",
        "pick": "yes",
        "showNoBadge": False,
        "slug": f"syn-leg-{label}",
        "state": "MARKET_STATE_OPEN",
        "team": team,
        "teamId": 1,
        "title": "Synthetic leg",
    }


def build_combo_position(slug: str) -> dict[str, Any]:
    """A synthetic parlay ``UserPosition``: 22 top-level keys, self-naming metadata.

    The key tree matches the 2026-10-28 parlay row. Every value is synthetic.
    ``netPosition`` is ``"963"`` and ``expired`` is false. The foreign path
    never parses this row; a row that does not name itself still refuses
    before the strict mapper.
    """
    money = {"currency": "USD", "value": "1.00"}
    return {
        "avgPx": dict(money),
        "baseCost": None,
        "bodPosition": "0",
        "bodPositionDecimal": "0.0000",
        "cashValue": dict(money),
        "comboLegDetails": [_combo_leg("a"), _combo_leg("b")],
        "cost": dict(money),
        "costPerShare": None,
        "expired": False,
        "fees": None,
        "marketMetadata": {
            "eventId": "evt-synthetic",
            "eventSlug": "evt-synthetic",
            "icon": "syn-icon",
            "outcome": "Yes",
            "slug": slug,
            "title": "Synthetic parlay",
        },
        "netPosition": "963",
        "netPositionDecimal": "963.0000",
        "positionId": "00000000-0000-4000-8000-000000000001",
        "qtyAvailable": "963",
        "qtyAvailableDecimal": "963.0000",
        "qtyBought": "963",
        "qtyBoughtDecimal": "963.0000",
        "qtySold": "0",
        "qtySoldDecimal": "0.0000",
        "realized": dict(money),
        "updateTime": TS_EVENT_TEXT,
    }


def build_non_weather_instrument(slug: str) -> BinaryOption:
    """The 510636 capture with the slug, side identifiers and category replaced.

    ``category`` is not climate and the slug does not parse as weather, so
    ``parse_binary_option`` records UNKNOWN weather facts (parsing.py:1316-1325)
    and still builds an instrument. No parser change.
    """
    payload: dict[str, Any] = json.loads(
        (RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8")
    )
    market: dict[str, Any] = payload["market"]
    market["slug"] = slug
    market["category"] = "sports"
    for side in market["marketSides"]:
        side["identifier"] = slug
    return parse_binary_option(payload, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


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
