"""S4 WP4 (ARM maker-sharp B5): the pure cancel-path helpers of ``submit_chain``.

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_order_path_plan_r4_delta.md``
section 5 (certification), section 6 (the cancel state machine) and section 9.

No client, no sender, no network: every function under test is pure. The module
is reached through ``tests/unit/ambig_latch_rig.py`` (barrier X1 pins by set
equality each test module that imports the ``exec`` package).
"""

from __future__ import annotations

from typing import Any, Final

import pytest

from tests.unit.ambig_latch_rig import submit_chain

NS: Final[int] = 1_000_000_000


def _order(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"id": "ABCDEF123456", "state": "ORDER_STATE_NEW", "cumQuantity": 0}
    body.update(overrides)
    return body


@pytest.mark.parametrize(
    ("state", "verdict"),
    [
        ("ORDER_STATE_CANCELED", "CANCELED"),
        ("ORDER_STATE_REJECTED", "CANCELED"),
        ("ORDER_STATE_EXPIRED", "EXPIRED"),
        ("ORDER_STATE_NEW", "OPEN"),
        ("ORDER_STATE_PENDING_CANCEL", "OPEN"),
        ("ORDER_STATE_PENDING_NEW", "OPEN"),
    ],
)
def test_cancel_read_verdict_zero_fill_states(state: str, verdict: str) -> None:
    assert submit_chain.cancel_read_verdict(_order(state=state)) == verdict


@pytest.mark.parametrize(
    "state",
    [
        "ORDER_STATE_FILLED",
        "ORDER_STATE_CANCELED",
        "ORDER_STATE_EXPIRED",
        "ORDER_STATE_REJECTED",
    ],
)
def test_any_cumulative_fill_on_a_terminal_order_routes_to_the_fill_path(state: str) -> None:
    """A fill (even on an order the venue then cancelled) is never a clean cancel."""
    assert submit_chain.cancel_read_verdict(_order(state=state, cumQuantity=1)) == "FILLED"


@pytest.mark.parametrize(
    "state",
    [
        "ORDER_STATE_NEW",
        "ORDER_STATE_PARTIALLY_FILLED",
        "ORDER_STATE_PENDING_CANCEL",
        "ORDER_STATE_PENDING_NEW",
    ],
)
def test_a_live_partial_fill_keeps_the_cancel_retrying(state: str) -> None:
    """B5 review G4: part of the order has filled but the rest still RESTS -- the cancel
    is not done, so the verdict is OPEN (never FILLED), whether or not the quantity echoes."""
    with_qty = _order(state=state, cumQuantity=1, quantity=10)
    assert submit_chain.cancel_read_verdict(with_qty) == "OPEN"
    assert submit_chain.cancel_read_verdict(_order(state=state, cumQuantity=1)) == "OPEN"
    odd_qty = _order(state=state, cumQuantity=1, quantity="n/a")
    assert submit_chain.cancel_read_verdict(odd_qty) == "OPEN"


@pytest.mark.parametrize("cum", [10, 11, "10", "10.0"])
def test_a_live_state_whose_cum_reaches_the_quantity_is_filled(cum: Any) -> None:
    """The state lags the fill: cum == quantity means nothing rests, so the fill path owns it."""
    body = _order(state="ORDER_STATE_PARTIALLY_FILLED", cumQuantity=cum, quantity=10)
    assert submit_chain.cancel_read_verdict(body) == "FILLED"


def test_a_fill_on_an_unrecognised_state_is_unreadable_not_filled() -> None:
    body = _order(state="ORDER_STATE_WEIRD", cumQuantity=1, quantity=10)
    assert submit_chain.cancel_read_verdict(body) == "UNREADABLE"


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "x",
        {},
        {"state": "ORDER_STATE_CANCELED"},  # no cumQuantity: zero-fill is unproven
        {"state": "ORDER_STATE_CANCELED", "cumQuantity": "n/a"},
        {"state": "ORDER_STATE_CANCELED", "cumQuantity": -1},
        {"state": "ORDER_STATE_WEIRD", "cumQuantity": 0},
        {"state": "ORDER_STATE_FILLED", "cumQuantity": 0},  # filled with nothing filled
        {"state": 5, "cumQuantity": 0},
    ],
)
def test_cancel_read_verdict_unreadable_is_fail_closed(body: Any) -> None:
    assert submit_chain.cancel_read_verdict(body) == "UNREADABLE"


def test_cancel_latch_deadline_is_the_later_of_expiry_grace_and_alert_plus_floor() -> None:
    first = 1_000 * NS
    far_expiry = first + 10_000 * NS
    assert submit_chain.cancel_latch_deadline_ns(first, far_expiry) == far_expiry + 120 * NS
    near_expiry = first + 5 * NS
    assert submit_chain.cancel_latch_deadline_ns(first, near_expiry) == first + (600 + 60) * NS


@pytest.mark.parametrize("expiry_offset_s", [-5_000, -1, 0, 1, 599, 600, 5_000, 40_000])
def test_alert_is_strictly_before_the_latch_for_every_input(expiry_offset_s: int) -> None:
    """Property: the alert age (from the first refused cancel) always precedes the latch."""
    first = 7_777 * NS
    deadline = submit_chain.cancel_latch_deadline_ns(first, first + expiry_offset_s * NS)
    assert first + submit_chain.RETRY_ALERT_AGE_S * NS < deadline


def test_envelope_is_known_only_for_orders_and_eof() -> None:
    assert submit_chain.open_orders_envelope_is_known({"orders": [], "eof": True})
    assert submit_chain.open_orders_envelope_is_known({"orders": []})  # missing eof = complete
    assert not submit_chain.open_orders_envelope_is_known({"orders": [], "nextCursor": "x"})
    assert not submit_chain.open_orders_envelope_is_known([])


def test_cancel_order_path_is_re_exported_and_signs_the_exact_path() -> None:
    assert submit_chain.cancel_order_path("ABCDEF123456") == "/v1/order/ABCDEF123456/cancel"
    with pytest.raises(ValueError, match="venue order id"):
        submit_chain.cancel_order_path("../x")


def test_unscoped_token_and_latch_reasons_are_stable_tokens() -> None:
    assert submit_chain.UNSCOPED_UNVERIFIED == "UNSCOPED_UNVERIFIED"
    assert submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON.startswith("resting_cancel_unconfirmed")
    assert submit_chain.RESTING_QUERY_UNREADABLE_REASON.startswith("resting_query_unreadable")
    assert submit_chain.SLUG_SCOPED_CANCEL_ALL_VERIFIED is False
    assert submit_chain.RESTING_POLL_FAILURE_LATCH_COUNT == 3


@pytest.mark.parametrize(
    ("pass_no", "seconds"), [(1, 5), (2, 10), (3, 20), (4, 40), (5, 60), (6, 60), (50, 60)]
)
def test_cancel_backoff_follows_the_table_and_repeats_the_last_value(
    pass_no: int, seconds: float
) -> None:
    assert submit_chain.cancel_backoff_s(pass_no) == seconds


def test_cancel_backoff_never_returns_zero_or_raises_for_a_nonpositive_pass() -> None:
    assert submit_chain.cancel_backoff_s(0) == 5
    assert submit_chain.cancel_backoff_s(-3) == 5


_SLUG: Final[str] = "tc-temp-nychigh-2026-08-25-lt79f"


def _echo(**overrides: Any) -> dict[str, Any]:
    return {**_order(state="ORDER_STATE_CANCELED", marketSlug=_SLUG), **overrides}


def test_the_verdict_accepts_an_echo_of_the_requested_id_and_slug() -> None:
    verdict = submit_chain.cancel_read_verdict(
        _echo(), expected_id="ABCDEF123456", expected_slug=_SLUG
    )
    assert verdict == "CANCELED"


@pytest.mark.parametrize(
    "body",
    [
        _echo(id="ZZZZZZZZZZZZ"),  # another order's terminal state must not settle ours
        _echo(marketSlug="tc-temp-nychigh-2026-08-26-lt79f"),
        _echo(id=None),
        _echo(id=123456),
        _echo(marketSlug=None),
        {k: v for k, v in _echo().items() if k != "id"},
        {k: v for k, v in _echo().items() if k != "marketSlug"},
    ],
)
def test_a_mismatched_or_missing_echo_is_unreadable_never_a_verdict(body: dict[str, Any]) -> None:
    """B5 review G15: the GET answers for the order we ASKED about, or it proves nothing."""
    verdict = submit_chain.cancel_read_verdict(
        body, expected_id="ABCDEF123456", expected_slug=_SLUG
    )
    assert verdict == "UNREADABLE"


def test_without_expectations_the_echo_is_not_checked() -> None:
    assert submit_chain.cancel_read_verdict(_echo(id="OTHER")) == "CANCELED"
