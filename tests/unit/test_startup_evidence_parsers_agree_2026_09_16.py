"""Regression test pinning agreement between Breezy's two independent
startup-evidence parsers, flagged by the 2026-09-16 review of commit
``bfcf53d``:

* :meth:`StartupPositionEvidence.from_bytes`
  (``breezy.adapters.polymarket_us.exec.client``) -- decodes the durable
  on-disk record into a dataclass.
* :func:`startup_evidence_refusal_reason`
  (``breezy.strategy.current_rung_hold.trial_day_latch``) -- decides,
  straight off the parsed JSON dict, whether that same record permits
  arming.

Both parse the identical on-disk schema independently, and nothing in the
source ties them together -- a change to one that is not mirrored in the
other would silently diverge. This module enumerates the full field-
combination space the dataclass can produce, round-trips each combination
through ``to_bytes`` -> ``json.loads`` (and, separately, through the real
``from_bytes``), and asserts the two parsers agree on:

(a) whether the record permits arming;
(b) which field is the FIRST one to refuse, in the documented token order
    (``evidence_absent`` | ``schema_version`` | ``position_read_refused`` |
    ``not_eof_complete`` | ``fill_walk_incomplete`` |
    ``open_orders_read_refused`` | ``open_orders_malformed`` |
    ``startup_open_orders_present``);
(c) that a legacy blob missing the RESTING_BID_HUNT Rev 2 open-order keys is
    refused by BOTH parsers, with the identical reason.

If this test ever surfaces a real disagreement between the two parsers, that
is the finding -- the test's job is to say so, not to be adjusted to hide it.
"""

from __future__ import annotations

import itertools
import json
from typing import Final

import pytest

from breezy.adapters.polymarket_us.exec.client import (
    StartupOpenOrderSnapshot,
    StartupPositionEvidence,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    STARTUP_OPEN_ORDERS_PRESENT_REASON,
    startup_evidence_permits_arm,
    startup_evidence_refusal_reason,
)

NOW_NS: Final[int] = 1_700_000_000_000_000_000

_OPEN_ORDER: Final[StartupOpenOrderSnapshot] = StartupOpenOrderSnapshot(
    venue_order_id="RESTING0001A",
    market_slug="tc-temp-nyc-h-2026-09-16-70-72",
    state="ORDER_STATE_NEW",
)

_BOOL_AXIS: Final[tuple[bool, bool]] = (False, True)
_OPEN_ORDERS_AXIS: Final[dict[str, tuple[StartupOpenOrderSnapshot, ...]]] = {
    "empty": (),
    "one": (_OPEN_ORDER,),
}
_SCHEMA_AXIS: Final[tuple[str, str]] = ("current", "legacy")

_Combo = tuple[bool, bool, bool, bool, str, str]

_COMBOS: Final[list[_Combo]] = list(
    itertools.product(
        _BOOL_AXIS,  # position_read_refused
        _BOOL_AXIS,  # eof_complete
        _BOOL_AXIS,  # fill_walk_complete
        _BOOL_AXIS,  # open_orders_read_refused
        tuple(_OPEN_ORDERS_AXIS),  # "empty" | "one"
        _SCHEMA_AXIS,  # "current" | "legacy"
    ),
)


def _combo_id(combo: _Combo) -> str:
    position_read_refused, eof_complete, fill_walk_complete, open_orders_read_refused, \
        open_orders_key, schema = combo
    return (
        f"pr={position_read_refused},eof={eof_complete},fw={fill_walk_complete},"
        f"oor={open_orders_read_refused},open_orders={open_orders_key},schema={schema}"
    )


def _expected_reason_from_payload(payload: dict[str, object] | None) -> str | None:
    """The documented first-failing-field order, written independently from
    the ``startup_evidence_refusal_reason`` docstring/source (never by
    calling the function under test), so comparing against it below is a
    real cross-check rather than a tautology."""
    if payload is None:
        return "evidence_absent"
    if payload.get("v") != 1:
        return "schema_version"
    if payload.get("position_read_refused") is not False:
        return "position_read_refused"
    if payload.get("eof_complete") is not True:
        return "not_eof_complete"
    if payload.get("fill_walk_complete") is not True:
        return "fill_walk_incomplete"
    if payload.get("open_orders_read_refused") is not False:
        return "open_orders_read_refused"
    open_orders = payload.get("open_orders")
    if not isinstance(open_orders, list):
        return "open_orders_malformed"
    if open_orders:
        return STARTUP_OPEN_ORDERS_PRESENT_REASON
    return None


def _dataclass_permits_arm(evidence: StartupPositionEvidence) -> bool:
    """The arm-permission semantics documented on ``StartupPositionEvidence``
    itself: every flag exactly right, open-order list exactly empty."""
    return (
        evidence.position_read_refused is False
        and evidence.eof_complete is True
        and evidence.fill_walk_complete is True
        and evidence.open_orders_read_refused is False
        and len(evidence.open_orders) == 0
    )


def _dataclass_refusal_reason(evidence: StartupPositionEvidence) -> str | None:
    """Same first-failing-field order as :func:`_expected_reason_from_payload`,
    applied to an already-decoded dataclass instance instead of a raw dict.
    ``evidence_absent`` and ``schema_version`` have no analogue here: a
    successfully decoded instance always represents a present, current-
    schema record."""
    if evidence.position_read_refused is not False:
        return "position_read_refused"
    if evidence.eof_complete is not True:
        return "not_eof_complete"
    if evidence.fill_walk_complete is not True:
        return "fill_walk_incomplete"
    if evidence.open_orders_read_refused is not False:
        return "open_orders_read_refused"
    if evidence.open_orders:
        return STARTUP_OPEN_ORDERS_PRESENT_REASON
    return None


class TestStartupEvidenceParsersAgree:
    """Enumerates every field combination :class:`StartupPositionEvidence`
    can produce and checks the two independent parsers agree on all of it."""

    @pytest.mark.parametrize("combo", _COMBOS, ids=_combo_id)
    def test_parsers_agree_on_permit_and_reason(self, combo: _Combo) -> None:
        (
            position_read_refused,
            eof_complete,
            fill_walk_complete,
            open_orders_read_refused,
            open_orders_key,
            schema,
        ) = combo
        open_orders = _OPEN_ORDERS_AXIS[open_orders_key]

        evidence = StartupPositionEvidence(
            ts_ns=NOW_NS,
            eof_complete=eof_complete,
            position_read_refused=position_read_refused,
            fill_walk_complete=fill_walk_complete,
            positions=(),
            open_orders_read_refused=open_orders_read_refused,
            open_orders=open_orders,
        )
        raw = evidence.to_bytes()
        payload = json.loads(raw)
        assert isinstance(payload, dict)

        if schema == "legacy":
            del payload["open_orders_read_refused"]
            del payload["open_orders"]
            wire_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        else:
            wire_bytes = raw

        decoded = StartupPositionEvidence.from_bytes(wire_bytes)

        # Parser 2 (trial_day_latch) must be internally consistent: permits
        # arming exactly when its own reason function returns None.
        parser2_reason = startup_evidence_refusal_reason(payload)
        parser2_permits = startup_evidence_permits_arm(payload)
        assert parser2_permits == (parser2_reason is None)

        # (b) the reason token is the FIRST failing field in the documented
        # order, verified against an independently-written oracle.
        assert parser2_reason == _expected_reason_from_payload(payload)

        # (a) the two parsers' permit judgement must agree.
        parser1_permits = _dataclass_permits_arm(decoded)
        assert parser1_permits == parser2_permits, (
            f"parsers disagree on whether to permit arming for combo={combo}: "
            f"client.py dataclass says {parser1_permits}, "
            f"trial_day_latch dict parser says {parser2_permits}"
        )

        # The two parsers must also agree on WHICH field failed first.
        parser1_reason = _dataclass_refusal_reason(decoded)
        assert parser1_reason == parser2_reason, (
            f"parsers disagree on the refusal reason for combo={combo}: "
            f"client.py dataclass says {parser1_reason!r}, "
            f"trial_day_latch dict parser says {parser2_reason!r}"
        )


class TestLegacyBlobRefusedByBothParsers:
    """(c): a legacy blob -- written before RESTING_BID_HUNT Rev 2 added the
    open-order keys -- carries neither ``open_orders_read_refused`` nor
    ``open_orders``. Both parsers must refuse arming, for the SAME reason,
    even though every other field is otherwise 'good'."""

    @staticmethod
    def _good_current_payload() -> dict[str, object]:
        evidence = StartupPositionEvidence(
            ts_ns=NOW_NS,
            eof_complete=True,
            position_read_refused=False,
            fill_walk_complete=True,
            positions=(),
            open_orders_read_refused=False,
            open_orders=(),
        )
        payload = json.loads(evidence.to_bytes())
        assert isinstance(payload, dict)
        return payload

    def test_legacy_blob_refuses_arming_on_both_parsers_with_the_same_reason(self) -> None:
        legacy_payload = self._good_current_payload()
        del legacy_payload["open_orders_read_refused"]
        del legacy_payload["open_orders"]
        legacy_bytes = json.dumps(legacy_payload, sort_keys=True).encode("utf-8")

        decoded = StartupPositionEvidence.from_bytes(legacy_bytes)
        # client.py's own fail-closed default (module docstring, section 4.3):
        # a legacy record decodes as REFUSED, never as "no open orders".
        assert decoded.open_orders_read_refused is True
        assert decoded.open_orders == ()

        parser1_reason = _dataclass_refusal_reason(decoded)
        parser2_reason = startup_evidence_refusal_reason(legacy_payload)

        assert parser1_reason == "open_orders_read_refused"
        assert parser2_reason == "open_orders_read_refused"
        assert parser1_reason == parser2_reason
        assert _dataclass_permits_arm(decoded) is False
        assert startup_evidence_permits_arm(legacy_payload) is False


def _good_payload() -> dict[str, object]:
    return {
        "v": 1,
        "ts_ns": NOW_NS,
        "position_read_refused": False,
        "eof_complete": True,
        "fill_walk_complete": True,
        "positions": [],
        "open_orders_read_refused": False,
        "open_orders": [],
    }


_DOCUMENTED_REASON_CASES: Final[list[tuple[dict[str, object] | None, str]]] = [
    (None, "evidence_absent"),
    ({**_good_payload(), "v": 2}, "schema_version"),
    ({**_good_payload(), "position_read_refused": True}, "position_read_refused"),
    ({**_good_payload(), "eof_complete": False}, "not_eof_complete"),
    ({**_good_payload(), "fill_walk_complete": False}, "fill_walk_incomplete"),
    ({**_good_payload(), "open_orders_read_refused": True}, "open_orders_read_refused"),
    ({**_good_payload(), "open_orders": "not-a-list"}, "open_orders_malformed"),
    (
        {**_good_payload(), "open_orders": [{"venue_order_id": "R1"}]},
        STARTUP_OPEN_ORDERS_PRESENT_REASON,
    ),
]


class TestDocumentedReasonOrderIsComplete:
    """(b), fully: exercises all EIGHT documented reason tokens directly
    against :func:`startup_evidence_refusal_reason`, including the three
    (``evidence_absent``, ``schema_version``, ``open_orders_malformed``) a
    real :class:`StartupPositionEvidence` round-trip can never produce, so
    the enumeration in :class:`TestStartupEvidenceParsersAgree` cannot reach
    them."""

    @pytest.mark.parametrize(
        ("payload", "expected_reason"),
        _DOCUMENTED_REASON_CASES,
        ids=[case[1] for case in _DOCUMENTED_REASON_CASES],
    )
    def test_every_documented_reason_token_is_reachable_and_first_wins(
        self,
        payload: dict[str, object] | None,
        expected_reason: str,
    ) -> None:
        assert startup_evidence_refusal_reason(payload) == expected_reason
        assert _expected_reason_from_payload(payload) == expected_reason
