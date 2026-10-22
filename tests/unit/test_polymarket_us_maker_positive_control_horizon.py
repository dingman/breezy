"""P3 horizon probe — offline tests over the B2 fakes (no venue contact).

Authority: ``docs/plans/backlog/AUDIT_PATH_2026-10-22/P3_plan_r2.md`` steps 1–3,
including the r2.1 amendments. The unflagged 600 s path is not relaxed.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.unit import b2_control_fakes as fk

_LICENSES_ALL_FALSE = {
    "GTD_EXPIRY": False,
    "SLUG_SCOPED_CANCEL_ALL": False,
    "MAKER_COMMISSION_SIGN": False,
}


@pytest.fixture(scope="module")
def ctl() -> Any:
    return fk.load_control()


def _horizon_rig(ctl: Any, venue: fk.FakeVenue | None = None) -> fk.Rig:
    rig = fk.Rig(ctl, venue, budget=ctl.Budget(max_creates=1, max_cancels=3))
    rig.session.horizon = True
    rig.session.ceiling_secs = ctl.HORIZON_GTD_SECS
    return rig


def test_unflagged_601s_gtd_is_still_refused(ctl: Any) -> None:
    """Without --horizon, a GTD of 601 s is refused before any sign or POST."""
    assert ctl.GTD_CEILING_SECS == 600
    assert (ctl.MAX_CREATES, ctl.MAX_CANCELS, ctl.MAX_GETS, ctl.MAX_AUX_GETS) == (4, 3, 40, 20)
    rig = fk.Rig(ctl)
    assert rig.session.horizon is False
    assert rig.session.ceiling_secs == 600
    asyncio.run(rig.session.list_markets())
    with pytest.raises(ValueError, match="GTD"):
        asyncio.run(rig.session.rest("A", fk.SLUG_X, 601))
    assert rig.post_client.calls == []
    assert rig.write_signer.signed == []


def test_horizon_refuses_one_second_past_h_before_signing(ctl: Any) -> None:
    """In horizon mode, a GTD of H+1 s is refused before the body is signed."""
    assert ctl.HORIZON_GTD_SECS == 14_400
    rig = _horizon_rig(ctl)
    asyncio.run(rig.session.list_markets())
    with pytest.raises(ValueError, match="GTD"):
        asyncio.run(rig.session.rest("B", fk.SLUG_X, ctl.HORIZON_GTD_SECS + 1))
    assert rig.post_client.calls == []
    assert rig.write_signer.signed == []


def test_horizon_pass_when_the_order_expires_in_the_window(ctl: Any) -> None:
    """PASS: echo within 1 s, NEW through G−30 s, EXPIRED on the G+60 s read."""
    rig = _horizon_rig(ctl)
    result = rig.run()
    document = result.document
    assert result.exit_code == 0
    assert document["outcome"] == "PASS"
    assert document["verdicts"]["P3"] == "PASS"
    assert document["failure"] is None
    assert document["licenses"] == _LICENSES_ALL_FALSE
    assert document["final_account_clean"] is True
    assert document["fill_detected"] is False
    assert document["cleanup"]["leftover"] == []
    assert rig.budget.creates == 1
    assert rig.budget.cancels == 0
    creates = [body for path, body in rig.posts() if path == "/v1/orders"]
    assert len(creates) == 1
    assert not any(path == "/v1/portfolio/activities" for _method, path in rig.venue.requests)
    assert rig.venue.alive_all() == []
    assert set(document["order_ids"]) == {"B"}


def test_horizon_late_cancels_the_order_by_id(ctl: Any) -> None:
    """LATE: still NEW at G+60 s, then one cancel by id, and the order is CANCELED."""
    venue = fk.FakeVenue()
    venue.never_expire = True
    rig = _horizon_rig(ctl, venue)
    result = rig.run()
    document = result.document
    assert result.exit_code != 0
    assert document["outcome"] == "FAIL"
    assert document["failure"] == "LATE"
    assert document["verdicts"]["P3"] == "FAIL"
    assert document["licenses"] == _LICENSES_ALL_FALSE
    order_id = document["order_ids"]["B"]
    cancels = [path for path, _body in rig.posts() if path.endswith("/cancel")]
    assert cancels == [f"/v1/order/{order_id}/cancel"]
    assert rig.venue.orders[order_id]["state"] == "ORDER_STATE_CANCELED"
    assert rig.venue.alive_all() == []


#: Not a venue string. Proves a code/message-field match can FAIL. Production pins are empty.
_SENTINEL_GTD_REJECTION: str = "GTD_EXPIRY_NOT_HONOURED"
_GENERIC_VENUE_MESSAGE: str = "The server was unable to process your request."


class _CreateStatus(fk.FakeVenue):
    """Create returns one fixed status and body, and books nothing."""

    def __init__(self, status: int, payload: Mapping[str, Any]) -> None:
        super().__init__()
        self._status = status
        self._payload = dict(payload)

    def _create(self, payload: Mapping[str, Any]) -> Any:
        self.creates += 1
        return fk._json(self._status, self._payload)


class _ListingSkew(fk.FakeVenue):
    """Books the create, answers 500, and shifts the listed goodTillTime by ``skew_s``."""

    def __init__(self, skew_s: int) -> None:
        super().__init__()
        self.skew_s = skew_s
        self.create_then_500_nth = 1

    def _create(self, payload: Mapping[str, Any]) -> Any:
        response = super()._create(payload)
        for row in self.orders.values():
            text = row.get("goodTillTime")
            if row.get("_own") and isinstance(text, str) and text:
                row["goodTillTime"] = _shift_gtd(text, self.skew_s)
        return response


def _shift_gtd(text: str, seconds: int) -> str:
    fraction = ""
    stamp = text.removesuffix("Z")
    if "." in stamp:
        stamp, fraction = stamp.split(".", 1)
        fraction = "." + fraction
    parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    shifted = parsed + timedelta(seconds=seconds)
    return shifted.strftime("%Y-%m-%dT%H:%M:%S") + fraction + "Z"


def _horizon_document(ctl: Any, venue: fk.FakeVenue) -> dict[str, Any]:
    rig = _horizon_rig(ctl, venue)
    result = rig.run()
    return result.document


def test_horizon_4xx_explicit_rejection_is_fail(ctl: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A documented code or message on the error field is FAIL. The echo is not that field."""
    core = sys.modules["_maker_control_core"]
    if hasattr(core, "DOCUMENTED_GTD_REJECTION_MESSAGES"):
        monkeypatch.setattr(
            core,
            "DOCUMENTED_GTD_REJECTION_MESSAGES",
            frozenset({_SENTINEL_GTD_REJECTION}),
        )
    document = _horizon_document(
        ctl,
        _CreateStatus(400, {"code": 3, "message": _SENTINEL_GTD_REJECTION, "details": []}),
    )
    assert document["outcome"] == "FAIL"
    assert document["failure"] == "GTD_REJECTED"


def test_horizon_4xx_echoed_request_is_invalid(ctl: Any) -> None:
    """goodTillTime echoed beside a generic error is INVALID, not a GTD rejection."""
    core = sys.modules["_maker_control_core"]
    document = _horizon_document(
        ctl,
        _CreateStatus(
            400,
            {
                "code": 3,
                "message": _GENERIC_VENUE_MESSAGE,
                "details": [
                    {
                        "request": {
                            "goodTillTime": "2026-10-22T18:00:00Z",
                            "tif": "TIME_IN_FORCE_GOOD_TILL_DATE",
                        }
                    }
                ],
            },
        ),
    )
    assert document["outcome"] == "INVALID"
    assert document["failure"] == "CREATE_4XX"
    assert core.DOCUMENTED_GTD_REJECTION_CODES == frozenset()
    assert core.DOCUMENTED_GTD_REJECTION_MESSAGES == frozenset()


def test_horizon_in_doubt_listing_cancels_g_within_one_second(ctl: Any) -> None:
    """A 5xx after the book keeps the order; listing cleanup cancels it when G is 1 s off."""
    venue = _ListingSkew(1)
    document = _horizon_document(ctl, venue)
    assert document["failure"] == "CREATE_REFUSED"
    assert "cleanup_listing" in [step["op"] for step in document["steps"]]
    cancels = [path for path, _body in venue.post_bodies if path.endswith("/cancel")]
    assert len(cancels) == 1
    assert venue.alive_own() == []


def test_horizon_in_doubt_listing_leaves_g_two_seconds_off(ctl: Any) -> None:
    """The same in-doubt listing does not cancel an order whose G is 2 s off the stored one."""
    venue = _ListingSkew(2)
    document = _horizon_document(ctl, venue)
    assert "cleanup_listing" in [step["op"] for step in document["steps"]]
    cancels = [path for path, _body in venue.post_bodies if path.endswith("/cancel")]
    assert cancels == []
    assert len(venue.alive_own()) == 1


def test_horizon_sigterm_cancels_the_resting_order_by_id(ctl: Any) -> None:
    """SIGTERM becomes KeyboardInterrupt; cleanup cancels the resting order by id."""
    rig = _horizon_rig(ctl)

    async def sleep_then_term(seconds: float) -> None:
        await rig.venue.sleep(seconds)
        signal.raise_signal(signal.SIGTERM)

    previous = ctl.install_termination_handlers()
    try:
        with pytest.raises(KeyboardInterrupt):
            asyncio.run(
                ctl.run_control(rig.session, sleep=sleep_then_term, run_date=fk.RUN_DATE)
            )
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    cancels = [path for path, _body in rig.posts() if path.endswith("/cancel")]
    assert len(cancels) == 1
    order_id = cancels[0].split("/")[3]
    assert rig.venue.orders[order_id]["state"] == "ORDER_STATE_CANCELED"
    assert rig.venue.alive_own() == []


def test_horizon_left_to_gtd_warns_order_not_lapsed(
    ctl: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """No cancel budget: the horizon order is left, named LEFT_ORDER_NOT_LAPSED, and warned."""
    venue = fk.FakeVenue()
    rig = fk.Rig(ctl, venue, budget=ctl.Budget(max_creates=1, max_cancels=0))
    rig.session.horizon = True
    rig.session.ceiling_secs = ctl.HORIZON_GTD_SECS
    state = ctl.RunState(run_date=fk.RUN_DATE, started_ns=venue.now_ns)

    async def sleep_then_interrupt(seconds: float) -> None:
        await venue.sleep(seconds)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(
            ctl.run_control(
                rig.session, sleep=sleep_then_interrupt, run_date=fk.RUN_DATE, state=state
            )
        )
    assert "LEFT_ORDER_NOT_LAPSED" in state.cleanup["errors"]
    assert state.cleanup["left_to_gtd"] == ["B"]
    order_id = next(iter(venue.orders))
    assert venue.orders[order_id]["state"] == "ORDER_STATE_NEW"
    err = capsys.readouterr().err
    assert f"order {order_id} may rest until" in err
    assert "cancel by hand" in err
