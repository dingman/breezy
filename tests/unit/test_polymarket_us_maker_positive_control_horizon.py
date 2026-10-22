"""P3 horizon probe — offline tests over the B2 fakes (no venue contact).

Authority: ``docs/plans/backlog/AUDIT_PATH_2026-10-22/P3_plan_r2.md`` steps 1–3,
including the r2.1 amendments. The unflagged 600 s path is not relaxed.
"""

from __future__ import annotations

import asyncio
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
