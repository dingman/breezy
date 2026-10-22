"""ARM maker-sharp plan r2 delta D1 / r3 R6: FREEZE the fill-record selector the harm stop reads.

The harm stop (WP-D1, a later producer) judges the maker family on its BOOKED MAKER fills.
It reads ``DurableFillRecord`` rows, which cannot gain a key (S4 r4 row K1: the exact key set
and ``golden_exec_par_wp4_k1.json`` stay unedited), so the selector must be expressible on the
keys that exist. This file freezes it at the FIXTURE level, with no D1 producer code:

* the MAKER MARKER is the ``trade_id`` prefix ``POLL-``
  (``submit_chain.MAKER_POLL_TRADE_ID_PREFIX``, ``submit_chain.is_maker_poll_fill``):
  the resting-order poll is the ONLY writer of that prefix. The create path stores the
  venue's own trade id and the resolver stores ``GET-<id>`` (both TAKER, "counted
  separately", never in the maker win rate);
* the FAMILY is the set of base slugs / stations the family trades. The durable record has no
  family key; the family is a SCOPE the D1 caller supplies (from the family manifest) and applies
  to ``instrument_id``'s base slug. The selector is therefore ``marker AND side == BUY AND
  base slug in family scope``.

Any change to the marker, to who may write it, or to the record keys the selector reads is a
red here, in the commit that makes it, which is the point of freezing the selector with B6.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import textwrap
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.model.identifiers import InstrumentId

from breezy.adapters.polymarket_us.fees import taker_fee_at_fill
from tests.unit.ambig_latch_rig import (
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.test_polymarket_us_resting_cancel import _payload, _rig
from tests.unit.test_polymarket_us_resting_query import _fill, _query, _records, _rested
from tests.unit.test_polymarket_us_resting_submit import _id_n

FAMILY_STATIONS: Final[frozenset[str]] = frozenset({"nyc"})
SLUG_TEMPLATE: Final[str] = "tc-temp-{city}high-2026-08-25-lt79f"
GOLDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "venueOrderId",
        "clientOrderId",
        "instrumentId",
        "orderSide",
        "cumulativeQty",
        "cumulativeCost",
        "cumulativeFee",
        "feeReconciled",
        "tsEvent",
        "venueFeeRaw",
        "tradeId",
        "orderQty",
        "feeCoefficientAtFill",
        "feeSource",
    }
)


def _station_of(instrument_id: str) -> str:
    """The station (city) segment of a daily-high slug: ``tc-temp-<city>high-...``."""
    slug = str(InstrumentId.from_str(instrument_id).symbol.value).removesuffix("^no")
    return str(slug.split("-")[2]).removesuffix("high")


def select_maker_fills(records: list[Any], *, family_stations: frozenset[str]) -> list[Any]:
    """THE FROZEN SELECTOR (fixture-level reference; D1 must reproduce it exactly)."""
    return [
        r
        for r in records
        if submit_chain.is_maker_poll_fill(r.trade_id)
        and r.order_side == client_module.LONG_ONLY_SIDE
        and _station_of(r.instrument_id) in family_stations
    ]


RESOLVER_TRADE_ID_PREFIX: Final[str] = "GET-"
#: The per-fill allowance the win/harm cost adds on top of fill and fee (design: one cent).
D1_COST_ALLOWANCE: Final[Decimal] = Decimal("0.01")


@dataclasses.dataclass(frozen=True)
class FamilyFillClassification:
    """What D1 may know about the family's durable fills (pure, fixture-level reference)."""

    #: the family's POLL- maker-booked BUY fills (the frozen selector's result)
    maker_fills: tuple[Any, ...]
    #: the family's OWN resolver-booked fills (``GET-`` trade id, TAKER-booked) on family slugs
    get_fills: tuple[Any, ...]
    #: any open AMBIGUOUS intent on a family slug (it may be a fill the poll never sees)
    open_ambiguous_family_intent: bool


def _station_of_slug(slug: str) -> str:
    return str(slug.removesuffix("^no").split("-")[2]).removesuffix("high")


def classify_family_fills(
    records: list[Any],
    *,
    family_stations: frozenset[str],
    open_ambiguous_slugs: Iterable[str],
) -> FamilyFillClassification:
    """THE FROZEN CLASSIFIER (fixture-level reference; D1 must reproduce it exactly).

    ``maker_fills`` is :func:`select_maker_fills`; ``get_fills`` are the family's BUY fills
    whose ``trade_id`` is the resolver's ``GET-`` synthetic id; the flag is true iff any open
    AMBIGUOUS intent sits on a family slug. It never reads ``fee_reconciled`` (M1)."""
    get_fills = tuple(
        r
        for r in records
        if isinstance(r.trade_id, str)
        and r.trade_id.startswith(RESOLVER_TRADE_ID_PREFIX)
        and r.order_side == client_module.LONG_ONLY_SIDE
        and _station_of(r.instrument_id) in family_stations
    )
    return FamilyFillClassification(
        maker_fills=tuple(select_maker_fills(records, family_stations=family_stations)),
        get_fills=get_fills,
        open_ambiguous_family_intent=any(
            _station_of_slug(slug) in family_stations for slug in open_ambiguous_slugs
        ),
    )


def d1_fail_closed(classification: FamilyFillClassification) -> bool:
    """D1 must fail closed (never PASS) while the maker tally may be missing family fills."""
    return bool(classification.get_fills) or classification.open_ambiguous_family_intent


def d1_verdict(classification: FamilyFillClassification, *, criterion_met: bool) -> str:
    """``HOLD`` while failing closed, else ``PASS`` / ``CONTINUE`` by the criterion."""
    if d1_fail_closed(classification):
        return "HOLD"
    return "PASS" if criterion_met else "CONTINUE"


def d1_fill_cost(record: Any) -> Decimal:
    """Per-fill cost for the win/harm criterion (M2): ``fill + max(booked fee, taker cent
    fee) + D1_COST_ALLOWANCE``. The booked fee is ``cumulative_fee`` (never the raw venue
    string, which may be a clamped rebate); the taker cent fee is the modelled TAKER fee of the
    same fill. Raises ``ValueError`` when no taker fee can be modelled (fail closed)."""
    taker = taker_fee_at_fill(
        quantity=record.cumulative_qty,
        price=record.cumulative_cost / record.cumulative_qty,
        ts_event_ns=record.ts_event,
        fee_coefficient_at_fill=record.fee_coefficient_at_fill,
    )
    if taker is None:
        raise ValueError("no taker fee can be modelled for this fill; the cost is unknown")
    booked: Decimal = record.cumulative_cost
    fee: Decimal = max(record.cumulative_fee, taker.as_decimal())
    return booked + fee + D1_COST_ALLOWANCE


def _record(
    venue_order_id: str, *, trade_id: str | None, city: str = "nyc", side: str = "BUY"
) -> Any:
    return client_module.DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"O-{venue_order_id}",
        instrument_id=f"{SLUG_TEMPLATE.format(city=city)}^no.POLYMARKET_US",
        order_side=side,
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal("0.40"),
        cumulative_fee=Decimal("0.01"),
        fee_reconciled=True,
        ts_event=1_800_000_000_000_000_000,
        venue_fee_raw="0.01",
        trade_id=trade_id,
        order_qty=Decimal(1),
    )


def test_the_maker_marker_is_the_poll_trade_id_prefix() -> None:
    assert submit_chain.MAKER_POLL_TRADE_ID_PREFIX == "POLL-"
    assert submit_chain.is_maker_poll_fill("POLL-ABC123")
    for not_maker in (None, "", "GET-ABC123", "7d9a1c52-venue-trade-id", "poll-ABC123", " POLL-1"):
        assert not submit_chain.is_maker_poll_fill(not_maker), not_maker


def test_the_poll_trade_id_is_deterministic_visibly_synthetic_and_fits_a_native_trade_id() -> None:
    short = submit_chain.maker_poll_trade_id("ABCDEF123456")
    assert short == "POLL-ABCDEF123456"
    long_id = "A" * 64
    first = submit_chain.maker_poll_trade_id(long_id)
    assert first == submit_chain.maker_poll_trade_id(long_id), "same input, same output"
    assert first != submit_chain.maker_poll_trade_id("B" * 64)
    assert len(first) <= 36 and submit_chain.is_maker_poll_fill(first)


def test_the_selector_picks_only_in_family_poll_booked_buys() -> None:
    records = [
        _record("MAKER-NYC", trade_id="POLL-MAKER-NYC"),
        _record("MAKER-LAX", trade_id="POLL-MAKER-LAX", city="lax"),
        _record("RESOLVER-NYC", trade_id="GET-RESOLVER-NYC"),
        _record("CREATE-NYC", trade_id="7d9a1c52-0000-4000-8000-000000000001"),
        _record("LEGACY-NYC", trade_id=None),
        _record("SELL-NYC", trade_id="POLL-SELL-NYC", side="SELL"),
    ]
    chosen = select_maker_fills(records, family_stations=FAMILY_STATIONS)
    assert [r.venue_order_id for r in chosen] == ["MAKER-NYC"]
    both = select_maker_fills(records, family_stations=frozenset({"nyc", "lax"}))
    assert [r.venue_order_id for r in both] == ["MAKER-NYC", "MAKER-LAX"]
    assert select_maker_fills(records, family_stations=frozenset()) == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_real_poll_booked_fill_satisfies_the_frozen_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture selector is tied to the REAL writer: the record the poll booking stores is
    selected, with no key beyond the K1 set."""
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="0.01")
    await rig.client._query_order(_query(rig, command))
    records = list(_records(rig))
    assert [
        r.venue_order_id for r in select_maker_fills(records, family_stations=FAMILY_STATIONS)
    ] == [_id_n(0)]
    assert select_maker_fills(records, family_stations=frozenset({"lax"})) == []
    stored = rig.client._store_get(f"{client_module.FILL_KEY_PREFIX}{_id_n(0)}")
    assert stored is not None and set(json.loads(stored)) == GOLDEN_KEYS
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_fill_booked_by_the_cancel_path_or_the_sweep_carries_the_same_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every maker booking goes through the one winner, so the marker cannot depend on which
    path observed the fill first."""
    from tests.unit.test_polymarket_us_resting_cancel import _cancel_cmd
    from tests.unit.test_polymarket_us_resting_submit import _submit_rest

    rig = await _rig(tmp_path, monkeypatch)
    command = await _submit_rest(rig, 0)
    _fill(rig, 0)
    await rig.client._cancel_order(_cancel_cmd(rig, command))
    records = list(_records(rig))
    assert [
        r.venue_order_id for r in select_maker_fills(records, family_stations=FAMILY_STATIONS)
    ] == [_id_n(0)]
    await rig.client._disconnect()


def test_no_other_src_module_writes_the_maker_marker() -> None:
    """The marker has ONE writer: ``maker_poll_trade_id`` (called by the poll booking). A
    resolver or create-path record carrying ``POLL-`` would pollute the maker win rate."""
    repo = Path(__file__).resolve().parents[2]
    writers = sorted(
        path.relative_to(repo).as_posix()
        for path in (repo / "src").rglob("*.py")
        if "maker_poll_trade_id" in path.read_text(encoding="utf-8")
    )
    assert writers == [
        "src/breezy/adapters/polymarket_us/exec/client.py",
        "src/breezy/adapters/polymarket_us/exec/submit_chain.py",
    ]
    client_text = (repo / "src/breezy/adapters/polymarket_us/exec/client.py").read_text(
        encoding="utf-8"
    )
    # inside the client the marker is produced from the booking helpers only
    assert client_text.count("submit_chain.maker_poll_trade_id(") == 2


# ---------------------------------------------------------------------------
# B6 review H2 / M1 / M2: the selector as a pure classifier, fail-closed, fee-blind, cost-safe
# ---------------------------------------------------------------------------

OPEN_NYC_SLUGS: Final[tuple[str, ...]] = ("tc-temp-nychigh-2026-08-25-lt79f",)
OPEN_LAX_SLUGS: Final[tuple[str, ...]] = ("tc-temp-laxhigh-2026-08-25-lt79f",)


def _ids(records: tuple[Any, ...]) -> list[str]:
    return [r.venue_order_id for r in records]


def test_the_classifier_returns_poll_maker_fills_and_the_familys_own_get_fills_separately() -> None:
    records = [
        _record("MAKER-NYC", trade_id="POLL-MAKER-NYC"),
        _record("MAKER-LAX", trade_id="POLL-MAKER-LAX", city="lax"),
        _record("RESOLVED-NYC", trade_id="GET-RESOLVED-NYC"),
        _record("RESOLVED-LAX", trade_id="GET-RESOLVED-LAX", city="lax"),
        _record("CREATE-NYC", trade_id="7d9a1c52-0000-4000-8000-000000000001"),
        _record("LEGACY-NYC", trade_id=None),
        _record("SELL-NYC", trade_id="POLL-SELL-NYC", side="SELL"),
    ]
    result = classify_family_fills(
        records, family_stations=FAMILY_STATIONS, open_ambiguous_slugs=()
    )
    assert _ids(result.maker_fills) == ["MAKER-NYC"]
    assert _ids(result.get_fills) == ["RESOLVED-NYC"], "GET- fills on family slugs only"
    assert result.open_ambiguous_family_intent is False
    # the maker list is exactly the frozen selector's
    assert _ids(result.maker_fills) == _ids(
        tuple(select_maker_fills(records, family_stations=FAMILY_STATIONS))
    )


@pytest.mark.parametrize(
    ("slugs", "stations", "expected"),
    [
        (OPEN_NYC_SLUGS, frozenset({"nyc"}), True),
        (OPEN_LAX_SLUGS, frozenset({"nyc"}), False),
        ((), frozenset({"nyc"}), False),
        (OPEN_NYC_SLUGS + OPEN_LAX_SLUGS, frozenset({"nyc"}), True),
        (OPEN_NYC_SLUGS, frozenset(), False),
    ],
)
def test_the_classifier_flags_an_open_ambiguous_intent_on_a_family_slug(
    slugs: tuple[str, ...], stations: frozenset[str], expected: bool
) -> None:
    result = classify_family_fills([], family_stations=stations, open_ambiguous_slugs=slugs)
    assert result.open_ambiguous_family_intent is expected


def test_d1_fails_closed_while_a_get_family_fill_or_an_open_ambiguous_intent_exists() -> None:
    """D1 must never report PASS while the resolver-booked (TAKER) family fills or an open
    AMBIGUOUS family intent mean the maker tally may be missing the family's real fills."""
    maker = [_record("MAKER-NYC", trade_id="POLL-MAKER-NYC")]
    get_fill = [*maker, _record("RESOLVED-NYC", trade_id="GET-RESOLVED-NYC")]
    clean = classify_family_fills(maker, family_stations=FAMILY_STATIONS, open_ambiguous_slugs=())
    with_get = classify_family_fills(
        get_fill, family_stations=FAMILY_STATIONS, open_ambiguous_slugs=()
    )
    with_open = classify_family_fills(
        maker, family_stations=FAMILY_STATIONS, open_ambiguous_slugs=OPEN_NYC_SLUGS
    )
    assert d1_verdict(clean, criterion_met=True) == "PASS"
    assert d1_verdict(clean, criterion_met=False) == "CONTINUE"
    for blocked in (with_get, with_open):
        assert d1_fail_closed(blocked) is True
        assert d1_verdict(blocked, criterion_met=True) == "HOLD", "never PASS while blocked"
        assert d1_verdict(blocked, criterion_met=False) == "HOLD"
    # an out-of-family GET- fill or open intent does not block the family
    foreign = classify_family_fills(
        [*maker, _record("RESOLVED-LAX", trade_id="GET-RESOLVED-LAX", city="lax")],
        family_stations=FAMILY_STATIONS,
        open_ambiguous_slugs=OPEN_LAX_SLUGS,
    )
    assert d1_fail_closed(foreign) is False


def test_the_selector_and_classifier_never_filter_on_fee_reconciled() -> None:
    """M1: rebate (clamped), out-of-envelope and unreadable-commission fills are exactly the
    UNRECONCILED ones; filtering them out would hide the family's worst fills from the stop."""
    unreconciled = [
        dataclasses.replace(
            _record(f"MAKER-{i}", trade_id=f"POLL-MAKER-{i}"),
            fee_reconciled=False,
            venue_fee_raw=raw,
        )
        for i, raw in enumerate(["-0.0125", "0.50", None])
    ]
    assert _ids(tuple(select_maker_fills(unreconciled, family_stations=FAMILY_STATIONS))) == [
        "MAKER-0",
        "MAKER-1",
        "MAKER-2",
    ]
    result = classify_family_fills(
        unreconciled, family_stations=FAMILY_STATIONS, open_ambiguous_slugs=()
    )
    assert _ids(result.maker_fills) == ["MAKER-0", "MAKER-1", "MAKER-2"]
    for fn in (select_maker_fills, classify_family_fills, d1_fail_closed, d1_verdict):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        reads = [
            n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "fee_reconciled"
        ]
        assert reads == [], fn.__name__


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_an_unreadable_commission_fill_is_still_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0)
    del _payload(rig, 0)["commissionNotionalTotalCollected"]
    await rig.client._query_order(_query(rig, command))
    (record,) = _records(rig)
    assert record.fee_reconciled is False
    result = classify_family_fills(
        [record], family_stations=FAMILY_STATIONS, open_ambiguous_slugs=()
    )
    assert _ids(result.maker_fills) == [_id_n(0)]
    await rig.client._disconnect()


def _costed(*, fee: str, raw: str | None, qty: str = "1", cost: str = "0.40") -> Any:
    return dataclasses.replace(
        _record("MAKER-NYC", trade_id="POLL-MAKER-NYC"),
        cumulative_qty=Decimal(qty),
        cumulative_cost=Decimal(cost),
        cumulative_fee=Decimal(fee),
        venue_fee_raw=raw,
        fee_reconciled=False,
        fee_coefficient_at_fill=Decimal("0.06"),
    )


@pytest.mark.parametrize(
    ("fee", "raw", "expected"),
    [
        # a clamped rebate books 0: the cost still carries the modelled taker cent fee (0.01)
        ("0", "-0.0125", "0.42"),
        # an unreadable commission books the taker fee already; same figure
        ("0.01", None, "0.42"),
        # a booked fee ABOVE the taker fee is the cost (never the lower modelled figure)
        ("0.50", "0.50", "0.91"),
        # booked fee equal to the taker cent fee
        ("0.01", "0.01", "0.42"),
    ],
)
def test_the_win_harm_cost_is_fill_plus_the_larger_fee_plus_a_cent(
    fee: str, raw: str | None, expected: str
) -> None:
    """M2: cost = fill + max(booked fee, taker cent fee) + 0.01, never the raw booked fee."""
    assert d1_fill_cost(_costed(fee=fee, raw=raw)) == Decimal(expected)


def test_the_win_harm_cost_scales_with_the_fill_and_ignores_the_raw_venue_string() -> None:
    base = d1_fill_cost(_costed(fee="0.01", raw="0.01"))
    assert d1_fill_cost(_costed(fee="0.01", raw="-99")) == base, "venue_fee_raw is never read"
    two = d1_fill_cost(_costed(fee="0.03", raw="0.03", qty="2", cost="0.80"))
    assert two == Decimal("0.80") + Decimal("0.03") + Decimal("0.01"), "taker fee at q=2 is 0.03"


def test_the_win_harm_cost_fails_closed_without_a_pinned_taker_fee() -> None:
    unpinned = dataclasses.replace(
        _costed(fee="0.01", raw="0.01"), fee_coefficient_at_fill=None, ts_event=1
    )
    with pytest.raises(ValueError, match="taker fee"):
        d1_fill_cost(unpinned)


def test_the_fee_reconciled_read_check_is_not_vacuous() -> None:
    """Non-vacuity: a selector that did filter on ``fee_reconciled`` is seen by the AST check."""
    planted = "def sel(records):\n    return [r for r in records if r.fee_reconciled]\n"
    reads = [
        n
        for n in ast.walk(ast.parse(planted))
        if isinstance(n, ast.Attribute) and n.attr == "fee_reconciled"
    ]
    assert len(reads) == 1
