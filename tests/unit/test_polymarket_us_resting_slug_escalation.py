"""ARM post-B2: the slug-scoped cancel-all escalation with ``SLUG_SCOPED_CANCEL_ALL_VERIFIED``
at its PRODUCTION value (``True``, flipped by c9fb69e6 on S-2 PASS over sibling slugs).

Authority: ``S4_exec_resting_order_path_plan_r4_delta.md`` sections 5.3 (a no-id-only slug is
never cancel-all'd) and 5.4 (the boot sweep: unfiltered read, slug cancel-all, unfiltered
re-read), and the erratum added in c9fb69e6: with the pin True an UNBOUND (or foreign) order on
a LEDGER slug is cancelled by the slug cancel-all (spec 9.18: a manual order on a family slug is
cancelled), after a WARN naming it by id prefix.

The sibling suites pin the flag False (``_rig`` default) or cover one pin-True happy path each;
this module is the escalation matrix. Every sender and private read is a local double: no
network, no venue contact. No ``exec`` import here (barrier X1): everything goes through
``ambig_latch_rig`` and the sibling suites.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.adapters.polymarket_us import write_transport
from breezy.adapters.polymarket_us.safety import live_trading_budget_remaining
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_PORTFOLIO
from breezy.adapters.polymarket_us.write_transport import PolymarketUSWriteTransport
from tests.unit.ambig_latch_rig import (
    OPEN_ORDERS_PATH,
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.polymarket_us_exec_shapes import build_no_leg_instrument
from tests.unit.test_polymarket_us_resting_adopt import _no_id_rest
from tests.unit.test_polymarket_us_resting_cancel import (
    CancelSender,
    _cancel_cmd,
    _rig,
    _set_state,
)
from tests.unit.test_polymarket_us_resting_submit import _id_n, _Rig, _submit_rest
from tests.unit.test_polymarket_us_resting_sweep import (
    _cancel_posts,
    _open_row,
    _second_process,
    _set_state_on,
)
from tests.unit.test_polymarket_us_submit_order_chain import (  # noqa: F401  (fixture, late getfixturevalue)
    write_canonical_unverified,
)

_INDEX_KEY: Final[str] = client_module.RESTING_INDEX_KEY
_ROW_PREFIX: Final[str] = client_module.RESTING_KEY_PREFIX
_CANCELED: Final[str] = "ORDER_STATE_CANCELED"
_NEW: Final[str] = "ORDER_STATE_NEW"
#: A second valid daily-HIGH slug (a sibling market) for the two-slug matrix.
_SLUG_B: Final[str] = "tc-temp-sfohigh-2026-08-25-lt79f"
_FOREIGN_SLUG: Final[str] = "tc-temp-lax-2026-08-25-gte70lt71f"
_UNIT: Final[Decimal] = Decimal("0.40")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _slug_of(command: Any) -> str:
    slug: str = submit_chain.build_resting_order_body(command.order, build_no_leg_instrument())[
        "marketSlug"
    ]
    return slug


def _remaining(client: Any) -> tuple[Decimal, int]:
    notional, count = live_trading_budget_remaining(client._permit)
    return Decimal(notional), int(count)


def _spent(client: Any) -> Decimal:
    return Decimal(client._ledger.spent_today_usd(now_ns=client._clock.timestamp_ns()))


def _spy_settles(monkeypatch: pytest.MonkeyPatch, client: Any) -> list[str]:
    settles: list[str] = []
    ledger_type = type(client._ledger)
    real = ledger_type.settle

    def spy(self: Any, key: str, **kwargs: Any) -> Any:
        settles.append(key)
        return real(self, key, **kwargs)

    monkeypatch.setattr(ledger_type, "settle", spy)
    return settles


def _rebind_to_slug(client: Any, payloads: dict[str, Any], n: int, slug: str) -> None:
    """Move rest ``n`` (durable row AND the venue's GET) onto another ledger slug."""
    key = f"{_ROW_PREFIX}{_id_n(n)}"
    row = json.loads(client._store_get(key))
    row["slug"] = slug
    client._store_set(key, json.dumps(row, sort_keys=True).encode())
    payloads[submit_chain.order_by_id_path(_id_n(n))]["order"]["marketSlug"] = slug


class _TracedRead:
    """Wraps the private-read stub, writing every read into a shared ordered trace."""

    def __init__(self, inner: Any, trace: list[tuple[str, str]]) -> None:
        self._inner = inner
        self._trace = trace

    @property
    def _payloads(self) -> dict[str, Any]:
        payloads: dict[str, Any] = self._inner._payloads
        return payloads

    @property
    def paths(self) -> list[str]:
        paths: list[str] = self._inner.paths
        return paths

    async def __call__(self, path: str, query: Any = None) -> Any:
        self._trace.append(("read", path))
        return await self._inner(path, query)


class _TracingSender(CancelSender):
    """A CancelSender that records cancel verbs into the shared trace too."""

    def __init__(self, trace: list[tuple[str, str]]) -> None:
        super().__init__()
        self.trace = trace

    async def post_cancel_order(self, api_base_url: str, **kwargs: Any) -> Any:
        self.trace.append(("cancel", kwargs["order_id"]))
        return await super().post_cancel_order(api_base_url, **kwargs)

    async def post_cancel_all(self, api_base_url: str, *, headers: Any, slugs: list[str]) -> Any:
        self.trace.append(("cancel_all", ",".join(slugs)))
        return await super().post_cancel_all(api_base_url, headers=headers, slugs=slugs)


class _Sweep:
    """A restarted client over a one- or two-rest ledger, ready for ``_connect``."""

    def __init__(self, client: Any, sender: _TracingSender, book: dict[str, Any]) -> None:
        self.client = client
        self.sender = sender
        self.book = book
        self.trace: list[tuple[str, str]] = sender.trace


async def _sweep_rig(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    rests: int = 1,
    second_slug_for: int | None = None,
    foreign: tuple[tuple[int, dict[str, Any]], ...] = (),
) -> tuple[_Sweep, str]:
    """``rests`` bound rests persisted, then a second process (pin True) with a traced
    sender and private read. Rest ``second_slug_for`` (if any) sits on ``_SLUG_B``. ``foreign``
    (id number, row overrides) pairs are added to the open book as unbound orders. Returns
    (sweep, ledger slug A)."""
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    command = None
    for n in range(rests):
        command = await _submit_rest(rig, n)
    assert command is not None
    slug = _slug_of(command)
    src: dict[str, Any] = rig.client._private_read._payloads
    if second_slug_for is not None:
        _rebind_to_slug(rig.client, src, second_slug_for, _SLUG_B)
    trace: list[tuple[str, str]] = []
    sender = _TracingSender(trace)
    rows = [_open_row(command, n) for n in range(rests)]
    if second_slug_for is not None:
        rows[second_slug_for]["marketSlug"] = _SLUG_B
    book: dict[str, Any] = {
        "orders": [*rows, *(_open_row(command, n, **over) for n, over in foreign)]
    }
    payloads = {
        submit_chain.order_by_id_path(_id_n(n)): src[submit_chain.order_by_id_path(_id_n(n))]
        for n in range(rests)
    }
    payloads[OPEN_ORDERS_PATH] = book
    second = await _second_process(
        tmp_path, monkeypatch, rig.client, rig.client.latch_cm, sender=sender, payloads=payloads
    )
    second._private_read = _TracedRead(second._private_read, trace)
    return _Sweep(second, sender, book), slug


def _venue_honours_everything(sweep: _Sweep, rests: int) -> None:
    """The venue obeys every cancel verb: per-id cancels and a slug cancel-all (which removes
    every open order on the named slugs, ledger or not) both land."""
    client, book = sweep.client, sweep.book

    def on_cancel(oid: str) -> None:
        _set_state_on(client, int(oid[-1]), _CANCELED)

    def on_cancel_all(slugs: list[str]) -> None:
        book["orders"] = [r for r in book["orders"] if r["marketSlug"] not in slugs]
        for n in range(rests):
            path = submit_chain.order_by_id_path(_id_n(n))
            order = client._private_read._payloads[path]["order"]
            if order["marketSlug"] in slugs:
                _set_state_on(client, n, _CANCELED)

    sweep.sender.on_cancel = on_cancel
    sweep.sender.on_cancel_all = on_cancel_all


# ---------------------------------------------------------------------------
# the production flags
# ---------------------------------------------------------------------------


def test_the_module_flags_are_the_production_flags_under_test() -> None:
    """GTD True, slug True, commission sign False: the configuration these suites run in."""
    assert submit_chain.GTD_EXPIRY_VERIFIED is True
    assert submit_chain.SLUG_SCOPED_CANCEL_ALL_VERIFIED is True
    assert submit_chain.MAKER_COMMISSION_SIGN_VERIFIED is False


# ---------------------------------------------------------------------------
# 1. an unconfirmed per-order cancel escalates to ONE slug cancel-all
# ---------------------------------------------------------------------------


async def _escalate(
    rig: _Rig, command: Any, *, extra_passes_s: float = 0.05
) -> tuple[asyncio.Future[None], list[int]]:
    """Start the cancel of rest 0 against a venue that never cancels (each POST ages the clock
    400 s). Returns the running task and, per cancel-all, the latch count at its send."""
    client = rig.client
    latched_at_send: list[int] = []
    rig.sender.on_cancel = lambda _id: client.advance(400)  # the order stays open
    rig.sender.on_cancel_all = lambda _slugs: latched_at_send.append(len(client._trading_refusals))
    task = asyncio.ensure_future(client._cancel_order(_cancel_cmd(rig, command)))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if client._trading_refusals:
            break
    await asyncio.sleep(extra_passes_s)  # further cancel passes while latched
    return task, latched_at_send


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_an_unconfirmed_cancel_escalates_to_exactly_one_cancel_all_on_the_ledger_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    command = await _submit_rest(rig, 0)
    await _submit_rest(rig, 1)
    slug = _slug_of(command)
    # a foreign order on a slug the ledger does not hold sits in the book: never named
    client._private_read._payloads[OPEN_ORDERS_PATH] = {
        "orders": [{"id": "ZZZZZZZZZZZZ", "marketSlug": _FOREIGN_SLUG, "state": _NEW}]
    }
    settles = _spy_settles(monkeypatch, client)
    intent_0 = client._resting_bookings[_id_n(0)][0]
    remaining_before = _remaining(client)
    assert _spent(client) == _UNIT * 2

    task, latched_at_send = await _escalate(rig, command)

    assert [r.reason for r in client._trading_refusals] == [
        submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON
    ]
    assert rig.sender.cancel_alls == [[slug]], "exactly one cancel-all, on the ledger slug only"
    assert latched_at_send == [1], "sent AFTER the latch, never before the deadline"
    assert len(rig.sender.cancels) >= 3, "the per-order loop kept retrying after the escalation"
    assert {c["order_id"] for c in rig.sender.cancels} == {_id_n(0)}
    assert settles == [] and _spent(client) == _UNIT * 2 and _remaining(client) == remaining_before

    # a confirming GET retires the row exactly once and restores the permit (this process's id)
    _set_state(rig, 0, _CANCELED)
    await asyncio.wait_for(task, 2.0)
    assert rig.event_names().count("OrderCanceled") == 1
    assert settles == [intent_0]
    assert rig.sender.cancel_alls == [[slug]], "confirming the cancel sends nothing more"
    assert client._budget_was_restored(_id_n(0))
    assert _remaining(client) == (remaining_before[0] + _UNIT, remaining_before[1] + 1)
    assert _spent(client) == _UNIT, "only the surviving rest is still spent"
    assert json.loads(client._store_get(_INDEX_KEY)) == [_id_n(1)]
    assert client._trading_refusals == [] and client._cancel_in_flight == frozenset()
    # a repeated cancel of the retired id neither settles again nor escalates again
    assert await client._cancel_resting_order([_id_n(0)]) == frozenset()
    assert settles == [intent_0] and rig.sender.cancel_alls == [[slug]]
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_escalation_names_only_the_unconfirmed_orders_slug_when_the_ledger_has_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    command = await _submit_rest(rig, 0)
    await _submit_rest(rig, 1)
    src: dict[str, Any] = client._private_read._payloads
    _rebind_to_slug(client, src, 1, _SLUG_B)
    slug_a = _slug_of(command)
    assert slug_a != _SLUG_B

    task, _ = await _escalate(rig, command)
    assert rig.sender.cancel_alls == [[slug_a]], "the sibling ledger slug is not swept"
    _set_state(rig, 0, _CANCELED)
    await asyncio.wait_for(task, 2.0)
    assert rig.sender.cancel_alls == [[slug_a]]
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_rehydrated_ids_escalated_cancel_settles_once_and_restores_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    command = await _submit_rest(rig, 0)
    slug = _slug_of(command)
    # PRIVATE-STATE EDIT, deliberate: a real restart cannot be staged with the first order live
    # in this cache; this leaves the id out of the set THIS process armed, exactly as a
    # rehydrated id is (same edit as the lifecycle suite's M-7 note).
    client._this_process_resting_ids = client._this_process_resting_ids - {_id_n(0)}
    settles = _spy_settles(monkeypatch, client)
    intent_0 = client._resting_bookings[_id_n(0)][0]
    remaining_before = _remaining(client)

    task, _ = await _escalate(rig, command)
    assert rig.sender.cancel_alls == [[slug]]
    _set_state(rig, 0, _CANCELED)
    await asyncio.wait_for(task, 2.0)

    assert settles == [intent_0]
    assert rig.event_names().count("OrderCanceled") == 1
    assert not client._budget_was_restored(_id_n(0))
    assert _remaining(client) == remaining_before, "a rehydrated id never restores the permit"
    assert _spent(client) == 0
    assert rig.sender.cancel_alls == [[slug]]
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_failing_cancel_all_post_never_breaks_the_per_order_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    command = await _submit_rest(rig, 0)
    settles = _spy_settles(monkeypatch, client)
    intent_0 = client._resting_bookings[_id_n(0)][0]

    def boom(_slugs: list[str]) -> None:
        raise RuntimeError("cancel-all refused (bench)")

    task, _ = await _escalate(rig, command)
    # the escalation above already ran with the recording hook; replace it and prove the
    # failure path through the choke point directly
    rig.sender.on_cancel_all = boom
    assert await client._cancel_slug_orders(_slug_of(command)) == "POST_FAILED"
    assert client.log_lines("warning", "slug cancel-all failed")
    _set_state(rig, 0, _CANCELED)
    await asyncio.wait_for(task, 2.0)
    assert settles == [intent_0] and rig.event_names().count("OrderCanceled") == 1
    await client._disconnect()


# ---------------------------------------------------------------------------
# the choke point never sends an empty, off-ledger or foreign-only slug list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize(
    "bad",
    [
        "",
        None,
        _FOREIGN_SLUG,
        "tc-temp-nychigh-2026-08-25-lt79f\n",
        "TC-TEMP-NYCHIGH-2026-08-25-LT79F",
    ],
    ids=["empty", "none", "foreign-only", "newline", "case"],
)
async def test_the_choke_point_never_sends_for_an_empty_off_ledger_or_foreign_only_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: Any
) -> None:
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    command = await _submit_rest(rig, 0)
    # the foreign slug is OPEN on the account (a foreign-only slug), but not in the ledger
    client._private_read._payloads[OPEN_ORDERS_PATH] = {
        "orders": [{"id": "ZZZZZZZZZZZZ", "marketSlug": _FOREIGN_SLUG, "state": _NEW}]
    }
    assert await client._cancel_slug_orders(bad) == "REFUSED_OFF_LEDGER"
    assert rig.sender.cancel_alls == []
    assert await client._cancel_slug_orders(_slug_of(command)) == "POSTED"
    assert rig.sender.cancel_alls == [[_slug_of(command)]]
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_the_choke_point_sends_nothing_for_a_retired_ledger_slug_or_an_unreadable_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    command = await _submit_rest(rig, 0)
    slug = _slug_of(command)
    rig.sender.on_cancel = lambda oid: _set_state(rig, 0, _CANCELED)
    await client._cancel_order(_cancel_cmd(rig, command))
    assert json.loads(client._store_get(_INDEX_KEY)) == []
    assert await client._cancel_slug_orders(slug) == "REFUSED_OFF_LEDGER", "retired: off-ledger"
    client._store_set(_INDEX_KEY, b"{not json")
    assert await client._cancel_slug_orders(slug) == "REFUSED_OFF_LEDGER", "unreadable index"
    assert rig.sender.cancel_alls == []
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("cause", ["no_sender", "canonical_unverified"])
async def test_the_choke_point_sends_nothing_without_a_sender_or_a_verified_canonical_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest, cause: str
) -> None:
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    command = await _submit_rest(rig, 0)
    if cause == "no_sender":
        client._order_sender = None
    else:
        # The flag must be False only AFTER the rest is submitted (a False flag
        # refuses the submit itself), so the shared chain fixture is requested
        # late by name. This module never sets the attribute: the NO-SEND scan
        # set (test_polymarket_us_submit_order_chain) stays exactly one file.
        request.getfixturevalue("write_canonical_unverified")
    assert await client._cancel_slug_orders(_slug_of(command)) == "REFUSED_NO_SENDER"
    assert rig.sender.cancel_alls == []
    await client._disconnect()


# ---------------------------------------------------------------------------
# 2. the boot sweep with the pin True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_boot_sweep_per_slug_reads_unfiltered_then_cancel_alls_then_rereads_unfiltered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sweep, slug_a = await _sweep_rig(tmp_path, monkeypatch, rests=2, second_slug_for=1)
    _venue_honours_everything(sweep, rests=2)
    second = sweep.client
    await second._connect()
    cancel_alls = [t for t in sweep.trace if t[0] == "cancel_all"]
    assert sorted(slug for _, slug in cancel_alls) == sorted([slug_a, _SLUG_B])
    assert len(cancel_alls) == 2, "each ledger slug is cancel-all'd exactly once"
    first_all = sweep.trace.index(cancel_alls[0])
    assert sweep.trace[first_all - 1] == ("read", OPEN_ORDERS_PATH), "unfiltered read first"
    last_all = max(i for i, t in enumerate(sweep.trace) if t[0] == "cancel_all")
    first_cancel = next(i for i, t in enumerate(sweep.trace) if t[0] == "cancel")
    assert last_all < first_cancel, "every slug cancel-all precedes the per-id pass"
    last_cancel = max(i for i, t in enumerate(sweep.trace) if t[0] == "cancel")
    reread = next(
        i for i, t in enumerate(sweep.trace) if i > last_cancel and t == ("read", OPEN_ORDERS_PATH)
    )
    assert reread > last_cancel, "the certifying unfiltered re-read follows the cancels"
    assert all(path == OPEN_ORDERS_PATH for kind, path in sweep.trace if "orders/open" in path)
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_boot_sweep_with_an_empty_reread_certifies_the_slug_and_retires_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sweep, slug = await _sweep_rig(tmp_path, monkeypatch, rests=1)
    _venue_honours_everything(sweep, rests=1)
    second = sweep.client
    settles = _spy_settles(monkeypatch, second)
    intent_0 = (
        second._resting_bookings[_id_n(0)][0] if _id_n(0) in second._resting_bookings else None
    )
    await second._connect()
    assert sweep.sender.cancel_alls == [[slug]]
    assert second._trading_refusals == []
    assert json.loads(second._store_get(_INDEX_KEY)) == []
    assert second._cancel_in_flight == frozenset()
    assert len(settles) == 1 and (intent_0 is None or settles == [intent_0]), "settled once"
    assert not second._budget_was_restored(_id_n(0)), "a rehydrated id restores nothing"
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("get_state", [_NEW, _CANCELED], ids=["get-open", "get-canceled"])
async def test_boot_sweep_latches_a_ledger_id_that_the_reread_still_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, get_state: str
) -> None:
    """The venue ignores the cancel-all and the book still lists the ledger id: nothing is
    certified. With the per-id GET also open the id is unresolved; with the GET terminal the
    listing contradicts it (B5 review G7). Both latch and retire nothing unread."""
    sweep, slug = await _sweep_rig(tmp_path, monkeypatch, rests=1)
    second = sweep.client
    if get_state == _CANCELED:
        sweep.sender.on_cancel = lambda oid: _set_state_on(second, 0, _CANCELED)
    await second._connect()
    assert sweep.sender.cancel_alls == [[slug]], "still exactly one cancel-all"
    assert [r.reason for r in second._trading_refusals] == [
        submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON
    ]
    assert second._swept_resting_intent_ids == frozenset()
    if get_state == _NEW:
        assert json.loads(second._store_get(_INDEX_KEY)) == [_id_n(0)], "no row deleted unread"
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_boot_sweep_cancels_an_unbound_order_on_a_ledger_slug_by_the_slug_cancel_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """r4 5.4 + the c9fb69e6 erratum (spec intent, per review): with the pin True an unbound
    order on a ledger slug is WARN-named by id prefix and removed by the slug cancel-all; it is
    NEVER cancelled per id, and its full id is never logged."""
    # an unbound order: same slug as the ledger, not in it
    sweep, slug = await _sweep_rig(tmp_path, monkeypatch, rests=1, foreign=((7, {}),))
    _venue_honours_everything(sweep, rests=1)
    second = sweep.client
    await second._connect()
    assert sweep.sender.cancel_alls == [[slug]]
    assert _cancel_posts(sweep.sender) == [_id_n(0)], "the unbound id is never POSTed per id"
    warned = second.log_lines("warning", "will be cancelled by the slug cancel-all")
    assert len(warned) == 1 and _id_n(7) not in warned[0] and slug in warned[0]
    assert not second.log_lines("warning", "is NOT cancelled"), "it was removed, not left"
    assert [o["id"] for o in sweep.book["orders"]] == []
    assert second._trading_refusals == []
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_boot_sweep_with_a_surviving_unbound_order_still_refuses_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The venue leaves the unbound order standing after the cancel-all: the ledger is
    certified (its own ids are gone) but the startup evidence keeps the arm gate shut."""
    sweep, slug = await _sweep_rig(tmp_path, monkeypatch, rests=1, foreign=((7, {}),))
    second = sweep.client
    sweep.sender.on_cancel = lambda oid: _set_state_on(second, 0, _CANCELED)
    sweep.sender.on_cancel_all = lambda slugs: sweep.book.update(
        orders=[r for r in sweep.book["orders"] if r["id"] != _id_n(0)]
    )
    await second._connect()
    assert sweep.sender.cancel_alls == [[slug]]
    assert _cancel_posts(sweep.sender) == [_id_n(0)]
    evidence = json.loads(second._store_get(client_module.STARTUP_EVIDENCE_KEY))
    assert [o["own_resting"] for o in evidence["open_orders"]] == [False]
    from breezy.strategy.current_rung_hold.trial_day_latch import startup_evidence_permits_arm

    assert not startup_evidence_permits_arm(evidence)
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_boot_sweep_never_cancel_alls_a_foreign_only_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sweep, slug = await _sweep_rig(
        tmp_path, monkeypatch, rests=1, foreign=((8, {"marketSlug": _FOREIGN_SLUG}),)
    )
    _venue_honours_everything(sweep, rests=1)
    await sweep.client._connect()
    assert sweep.sender.cancel_alls == [[slug]], "the foreign-only slug is never named"
    assert not sweep.client.log_lines("warning", "will be cancelled by the slug cancel-all")
    assert [o["id"] for o in sweep.book["orders"]] == [_id_n(8)], "the foreign order stands"
    await sweep.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_boot_sweep_never_cancel_alls_a_slug_held_only_by_a_no_id_context_even_when_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """r4 5.3: a no-id resting context is not a cancellable ledger entry. With the pin True and
    the slug reading EMPTY, nothing is cancel-all'd and the intent is certified swept (WP5
    alone retires it)."""
    client, current, _command = await _no_id_rest(tmp_path, monkeypatch)
    sender = CancelSender()
    second = await _second_process(
        tmp_path,
        monkeypatch,
        client,
        client.latch_cm,
        sender=sender,
        payloads={OPEN_ORDERS_PATH: {"orders": []}},
    )
    await second._connect()
    assert submit_chain.SLUG_SCOPED_CANCEL_ALL_VERIFIED is True
    assert sender.cancel_alls == [] and sender.cancels == []
    assert second._swept_resting_intent_ids == frozenset({current.intent_id})
    assert second._trading_refusals == []
    await second._disconnect()


# ---------------------------------------------------------------------------
# 3. budget and egress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_each_cancel_all_is_counted_and_spends_no_permit_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sweep, _slug = await _sweep_rig(tmp_path, monkeypatch, rests=2, second_slug_for=1)
    _venue_honours_everything(sweep, rests=2)
    second = sweep.client
    before = _remaining(second)
    await second._connect()
    assert len(sweep.sender.cancel_alls) == 2, "one counted wire call per ledger slug"
    assert len(sweep.sender.cancel_alls) == len(
        {s for body in sweep.sender.cancel_alls for s in body}
    )
    assert all(len(body) == 1 for body in sweep.sender.cancel_alls), "never a multi-slug body"
    assert _remaining(second) == before, "a cancel-all consumes no order slot or notional"
    await second._disconnect()


class _Http:
    """The transport's HTTP client double: records every dispatch."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})

        class _Resp:
            status = 200
            headers: dict[str, str] = {}  # noqa: RUF012
            body = b"{}"

        return _Resp()


class _RealTransportSender(CancelSender):
    """cancel-all goes through the REAL transport (slug re-validation, body build, quota key)."""

    def __init__(self, http: _Http) -> None:
        super().__init__()
        self.transport = PolymarketUSWriteTransport(client=http)

    async def post_cancel_all(self, api_base_url: str, *, headers: Any, slugs: list[str]) -> Any:
        await super().post_cancel_all(api_base_url, headers=headers, slugs=slugs)
        return await self.transport.post_cancel_all(api_base_url, headers=headers, slugs=slugs)


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_the_only_cancel_all_wire_dispatch_is_one_slug_body_on_the_portfolio_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through the real transport, an escalation puts exactly one cancel-all on the wire, whose
    body is exactly ``{"slugs": [ledger slug]}`` charged to the portfolio quota key."""
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    http = _Http()
    sender = _RealTransportSender(http)
    rig.sender = sender
    client._order_sender = sender
    command = await _submit_rest(rig, 0)
    slug = _slug_of(command)
    task, _ = await _escalate(rig, command)
    wire = [c for c in http.calls if c["url"].endswith(write_transport.CANCEL_ALL_PATH)]
    assert len(wire) == 1 and sender.cancel_alls == [[slug]]
    assert json.loads(wire[0]["body"]) == {"slugs": [slug]}
    assert wire[0]["keys"] == [QUOTA_KEY_PORTFOLIO]
    _set_state(rig, 0, _CANCELED)
    await asyncio.wait_for(task, 2.0)
    assert len([c for c in http.calls if c["url"].endswith(write_transport.CANCEL_ALL_PATH)]) == 1
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_no_strategy_path_sends_a_cancel_all_with_the_pin_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strategy's cancel and cancel-all commands, a refused cancel that has not reached its
    deadline, and a terminal cancel never reach the venue cancel-all (the AST rows N2/N3/N5
    pin the same fact structurally; this is the behavioural twin with the pin True)."""
    from tests.unit.test_polymarket_us_resting_cancel import _auto_cancel, _cancel_all_cmd

    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    command = await _submit_rest(rig, 0)
    await _submit_rest(rig, 1)
    _auto_cancel(rig)
    await client._cancel_order(_cancel_cmd(rig, command))
    await client._cancel_all_orders(_cancel_all_cmd(rig, build_no_leg_instrument().id))
    assert rig.sender.cancel_alls == []
    assert rig.event_names().count("OrderCanceled") == 2
    await client._disconnect()
