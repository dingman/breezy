"""Unit tests for ``scripts/analysis/capture_no_side_preview.py``'s CLOSE mode.

Authority: ``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md`` Section 4 step 1
(pin the closing-order echo table from a capture). CLOSE mode extends the
existing NO-side preview capture with a ``--close`` path that previews a
CLOSING order (``action=ORDER_ACTION_SELL``) against a held YES or NO leg.

These tests exercise the script's PURE functions and ``main()`` end to end
with the live-transport function replaced by a fake -- never real network
egress. The existing NO-side opening-buy modes are re-verified unchanged
here as a smoke check; their own byte-for-byte pins live in
``test_polymarket_us_readonly_guard.py``, ``test_polymarket_us_write_transport.py``
and ``test_cage_rule_constants_are_pinned.py``.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_SCRIPTS_ANALYSIS = (REPO_ROOT / "scripts" / "analysis").as_posix()
if _SCRIPTS_ANALYSIS not in sys.path:
    sys.path.insert(0, _SCRIPTS_ANALYSIS)

import capture_no_side_preview as ncp

# ---------------------------------------------------------------------------
# 1. dry-run body construction: YES close, identity price
# ---------------------------------------------------------------------------


def test_build_close_order_body_yes_outcome_uses_sell_action_and_identity_price() -> None:
    # Arrange
    slug = "tc-temp-mdwhigh-2026-09-15-gte80lt81f"
    price = Decimal("0.05")

    # Act
    body = ncp.build_close_order_body(slug=slug, price=price, outcome="yes", quantity=1)

    # Assert
    assert set(body) == ncp.ORDER_BODY_KEYS
    assert body["action"] == "ORDER_ACTION_SELL"
    assert body["outcomeSide"] == "OUTCOME_SIDE_YES"
    assert body["price"] == {"value": "0.05", "currency": "USD"}
    assert body["quantity"] == 1
    assert body["marketSlug"] == slug


# ---------------------------------------------------------------------------
# 2. dry-run body construction: NO close, complement price
# ---------------------------------------------------------------------------


def test_build_close_order_body_no_outcome_uses_complement_price() -> None:
    # Arrange
    slug = "tc-temp-miahigh-2026-09-15-gte92lt93f"
    price = Decimal("0.09")

    # Act
    body = ncp.build_close_order_body(slug=slug, price=price, outcome="no", quantity=1)

    # Assert
    assert body["outcomeSide"] == "OUTCOME_SIDE_NO"
    assert body["price"] == {"value": "0.91", "currency": "USD"}
    assert body["action"] == "ORDER_ACTION_SELL"


def test_build_close_order_body_rejects_an_unknown_outcome() -> None:
    with pytest.raises(ValueError, match="unknown outcome"):
        ncp.build_close_order_body(
            slug="tc-temp-miahigh-2026-09-15-gte92lt93f",
            price=Decimal("0.09"),
            outcome="maybe",
            quantity=1,
        )


def test_build_close_order_body_honours_an_explicit_quantity() -> None:
    body = ncp.build_close_order_body(
        slug="tc-temp-miahigh-2026-09-15-gte92lt93f",
        price=Decimal("0.09"),
        outcome="no",
        quantity=3,
    )
    assert body["quantity"] == 3


# ---------------------------------------------------------------------------
# 3. never any path but the preview path
# ---------------------------------------------------------------------------


def test_assert_preview_path_only_accepts_the_preview_path() -> None:
    ncp.assert_preview_path_only(ncp.PREVIEW_PATH)


@pytest.mark.parametrize(
    "path", ["/v1/orders", "/v1/order/abc123/cancel", "/v1/order/abc123/modify", ""]
)
def test_assert_preview_path_only_refuses_every_other_path(path: str) -> None:
    with pytest.raises(ValueError, match="only"):
        ncp.assert_preview_path_only(path)


# ---------------------------------------------------------------------------
# CLI wiring for --close
# ---------------------------------------------------------------------------


def test_parse_args_requires_outcome_when_close_is_set() -> None:
    with pytest.raises(SystemExit):
        ncp.parse_args(
            ["--close", "--slug", "tc-temp-miahigh-2026-09-15-gte92lt93f", "--price", "0.09"]
        )


def test_parse_args_rejects_outcome_without_close() -> None:
    with pytest.raises(SystemExit):
        ncp.parse_args(
            [
                "--slug",
                "tc-temp-miahigh-2026-09-15-gte92lt93f",
                "--price",
                "0.09",
                "--outcome",
                "no",
            ]
        )


def test_parse_args_accepts_a_well_formed_close_invocation() -> None:
    args = ncp.parse_args(
        [
            "--close",
            "--slug",
            "tc-temp-miahigh-2026-09-15-gte92lt93f",
            "--outcome",
            "no",
            "--price",
            "0.09",
        ]
    )
    assert args.close is True
    assert args.outcome == "no"
    assert args.quantity == 1


# ---------------------------------------------------------------------------
# 4. --execute writes the artefact with the echoed fields, redacted
# ---------------------------------------------------------------------------


def test_close_execute_writes_evidence_with_echoed_fields_and_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # A secret with no 4-char substring in common with any JSON field name or
    # value the document otherwise carries (notably not the literal "sign",
    # which would collide with the ever-present header NAME "x-pm-signature"
    # and produce a false positive in `_assert_no_secret_material`).
    fake_secret = "Zq7xW9mPfL3kRtN8vDsHcJ2yQb5F"

    async def _fake_capture_close_live(
        args: Any, envelope: Any
    ) -> dict[str, Any]:
        headers = {
            "x-pm-access-key": "AKFAKE123",
            "x-pm-signature": fake_secret,
            "x-pm-timestamp": "1700000000",
            "Content-Type": "application/json",
        }
        preview_record = {
            "request": ncp.request_record(
                method="POST",
                base_url="https://api.polymarket.us",
                path=ncp.PREVIEW_PATH,
                headers=headers,
                body=ncp.encode_body(envelope),
            ),
            "response": {
                "status": 200,
                "body": {
                    "order": {
                        "id": "order-close-001",
                        "side": "ORDER_SIDE_SELL",
                        "intent": "ORDER_INTENT_SELL_LONG",
                        "price": {"value": "0.91", "currency": "USD"},
                        "state": "ORDER_STATE_PENDING_NEW",
                    }
                },
            },
        }
        return {"preview": preview_record, "_secrets": [fake_secret]}

    monkeypatch.setattr(ncp, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ncp, "_capture_close_live", _fake_capture_close_live)
    monkeypatch.setattr(ncp, "utc_stamp", lambda now=None: "20260916T000000Z")

    # Act
    exit_code = ncp.main(
        [
            "--close",
            "--slug",
            "tc-temp-miahigh-2026-09-15-gte92lt93f",
            "--outcome",
            "no",
            "--price",
            "0.09",
            "--execute",
        ]
    )

    # Assert
    assert exit_code == 0
    expected_path = ncp.close_evidence_path("no", "20260916T000000Z")
    assert expected_path.exists()
    written_text = expected_path.read_text(encoding="utf-8")
    assert fake_secret not in written_text

    document = json.loads(written_text)
    assert document["schema"] == "breezy.close_preview_capture.v1"
    assert document["outcome"] == "no"
    assert document["echo"] == {
        "intent": "ORDER_INTENT_SELL_LONG",
        "side": "ORDER_SIDE_SELL",
        "outcomeSide": "OUTCOME_SIDE_NO",
        "price": {"value": "0.91", "currency": "USD"},
        "state": "ORDER_STATE_PENDING_NEW",
        "id": "order-close-001",
    }
    assert document["preview"]["request"]["headers"]["x-pm-signature"] == "<redacted>"
    assert document["preview"]["request"]["headers"]["x-pm-access-key"] == "<redacted>"


def test_close_dry_run_prints_the_body_without_executing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange / Act
    exit_code = ncp.main(
        [
            "--close",
            "--slug",
            "tc-temp-mdwhigh-2026-09-15-gte80lt81f",
            "--outcome",
            "yes",
            "--price",
            "0.05",
        ]
    )

    # Assert
    assert exit_code == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["mode"] == "DRY_RUN"
    assert stdout["close"] is True
    assert stdout["outcome"] == "yes"
    assert stdout["creates_orders"] is False
    assert stdout["preview_request"]["body"]["request"]["action"] == "ORDER_ACTION_SELL"


# ---------------------------------------------------------------------------
# 5. existing NO-side opening-buy modes stay byte-identical
# ---------------------------------------------------------------------------


def test_existing_no_side_dry_run_is_unaffected_by_close_mode() -> None:
    exit_code = ncp.main(
        [
            "--slug",
            "tc-temp-mdwhigh-2026-09-14-gte76lt77f",
            "--price",
            "0.05",
        ]
    )
    assert exit_code == 0


def test_build_preview_order_body_still_defaults_to_buy_action() -> None:
    body = ncp.build_preview_order_body(
        slug="tc-temp-mdwhigh-2026-09-14-gte76lt77f",
        price=Decimal("0.05"),
        outcome_side=ncp.OUTCOME_SIDE_NO,
    )
    assert body["action"] == "ORDER_ACTION_BUY"
    assert body["outcomeSide"] == "OUTCOME_SIDE_NO"
    assert set(body) == ncp.ORDER_BODY_KEYS


def test_extract_order_echo_returns_empty_mapping_on_an_unparsed_body() -> None:
    assert ncp.extract_order_echo({"response": {"status": None, "error_type": "HttpError"}}) == {}
    assert ncp.extract_order_echo({}) == {}
