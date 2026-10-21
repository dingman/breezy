"""ARM B1 -- slug-scoped cancel transport verbs and their validation plants.

Authority: ``docs/plans/backlog/ARM_MAKER_SHARP_2026-10-21/plan_r2_delta.md`` D2 and
``MAKER_2026-10-12/S4_exec_resting_order_path_plan_r4_delta.md`` rows T1-T3, P7, N5.

The venue treats an empty ``slugs`` list as "cancel every open order on the
account", so the transport must make an empty or malformed list unconstructible,
validating independently of the frozen ``symbology.parse_weather_slug``.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from breezy.adapters.polymarket_us.exec.endpoints import (
    CANCEL_ORDER_PATH_TEMPLATE,
    cancel_order_path,
    valid_venue_order_id,
)
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_PORTFOLIO
from breezy.adapters.polymarket_us.write_transport import PolymarketUSWriteTransport

REPO_ROOT = Path(__file__).resolve().parents[2]
_BASE = "https://api.example.invalid"
_HEADERS = {"X-PM-Access-Key": "k"}
_SLUG = "tc-temp-nychigh-2026-10-13-lt71f"
_SLUG_B = "tc-temp-sfohigh-2026-10-13-gte72lt73f"
_ORDER_ID = "ABCDEF123456"
_LEGACY_PROBE = "scripts/venue/polymarket_us_write_signing_probe.py"
_LEGACY_PROBE_SHA256 = "fbc925a7a09be883ccdd53d84307ee047c24aa6ad45c988f53091bc2af99043f"


class _Resp:
    status = 200
    headers: ClassVar[dict[str, str]] = {}
    body = b"{}"


class _Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> _Resp:
        self.calls.append({"url": url, **kwargs})
        return _Resp()


def _transport() -> tuple[PolymarketUSWriteTransport, _Client]:
    client = _Client()
    return PolymarketUSWriteTransport(client=client), client


_BAD_SLUGS = [
    pytest.param("", id="empty"),
    pytest.param(_SLUG + "\n", id="trailing-newline"),
    pytest.param("tc-temp-nychigh-2026-10-1３-lt71f", id="fullwidth-digit-in-date"),
    pytest.param("tc-temp-nychigh-2026-10-13-lt71f ", id="trailing-space"),
    pytest.param("TC-TEMP-NYCHIGH-2026-10-13-LT71F", id="uppercase"),
    pytest.param("tc-temp-nychigh-2026-10-13", id="no-bounds"),
    pytest.param("sports-nba-lal-bos-2026-10-13", id="non-weather"),
    pytest.param("tc-temp-sjc-dec-lt40", id="monthly-non-daily"),
]

_BAD_IDS = [
    pytest.param("", id="empty"),
    pytest.param("ID\n", id="newline"),
    pytest.param(_ORDER_ID + "\n", id="valid-plus-newline"),
    pytest.param(_ORDER_ID.lower(), id="lowercase"),
    pytest.param(_ORDER_ID[:11], id="11-chars"),
    pytest.param(_ORDER_ID + "7", id="13-chars"),
    pytest.param("ABCDEF12345٣", id="non-ascii-digit"),
    pytest.param("ABCDEF12345É", id="non-ascii-letter"),
    pytest.param("ABCDEF/23456", id="path-separator"),
]


# ---------------------------------------------------------------- order id / path


def test_valid_venue_order_id_accepts_the_observed_shape() -> None:
    assert valid_venue_order_id(_ORDER_ID) is True


@pytest.mark.parametrize("bad", _BAD_IDS)
def test_valid_venue_order_id_refuses_everything_outside_the_regex(bad: str) -> None:
    assert valid_venue_order_id(bad) is False


@pytest.mark.parametrize("bad", [None, 123, b"ABCDEF123456"])
def test_valid_venue_order_id_refuses_non_strings(bad: object) -> None:
    assert valid_venue_order_id(bad) is False


def test_cancel_order_path_is_the_literal_template_filled() -> None:
    assert CANCEL_ORDER_PATH_TEMPLATE == "/v1/order/{order_id}/cancel"
    assert cancel_order_path(_ORDER_ID) == f"/v1/order/{_ORDER_ID}/cancel"


@pytest.mark.parametrize("bad", _BAD_IDS)
def test_cancel_order_path_refuses_invalid_ids(bad: str) -> None:
    with pytest.raises(ValueError):
        cancel_order_path(bad)


# ---------------------------------------------------------------- T1 signatures


def test_cancel_verbs_take_no_method_query_or_caller_bytes() -> None:
    all_params = inspect.signature(PolymarketUSWriteTransport.post_cancel_all).parameters
    one_params = inspect.signature(PolymarketUSWriteTransport.post_cancel_order).parameters
    assert set(all_params) == {"self", "api_base_url", "headers", "slugs"}
    assert set(one_params) == {"self", "api_base_url", "headers", "order_id", "market_slug"}
    for params in (all_params, one_params):
        assert not {"method", "query", "params", "timeout_secs", "body"} & set(params)


# ---------------------------------------------------------------- post_cancel_order


@pytest.mark.asyncio
async def test_post_cancel_order_posts_body_to_the_literal_path() -> None:
    transport, client = _transport()
    response = await transport.post_cancel_order(
        _BASE + "/", headers=_HEADERS, order_id=_ORDER_ID, market_slug=_SLUG
    )
    assert response.status == 200
    assert len(client.calls) == 1
    call = client.calls[0]
    assert set(call) == {"url", "headers", "body", "keys"}
    assert call["url"] == f"{_BASE}/v1/order/{_ORDER_ID}/cancel"
    assert call["headers"] == _HEADERS
    assert call["keys"] == [QUOTA_KEY_PORTFOLIO]
    assert json.loads(call["body"]) == {"marketSlug": _SLUG}
    assert call["body"] == json.dumps({"marketSlug": _SLUG}).encode("ascii")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", _BAD_IDS)
async def test_post_cancel_order_refuses_bad_order_id_without_sending(bad: str) -> None:
    transport, client = _transport()
    with pytest.raises(ValueError):
        await transport.post_cancel_order(_BASE, headers=_HEADERS, order_id=bad, market_slug=_SLUG)
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", _BAD_SLUGS)
async def test_post_cancel_order_refuses_bad_slug_without_sending(bad: str) -> None:
    transport, client = _transport()
    with pytest.raises(ValueError):
        await transport.post_cancel_order(
            _BASE, headers=_HEADERS, order_id=_ORDER_ID, market_slug=bad
        )
    assert client.calls == []


# ---------------------------------------------------------------- post_cancel_all


@pytest.mark.asyncio
async def test_post_cancel_all_builds_and_sends_the_slugs_body() -> None:
    transport, client = _transport()
    await transport.post_cancel_all(_BASE, headers=_HEADERS, slugs=[_SLUG, _SLUG_B])
    call = client.calls[0]
    assert set(call) == {"url", "headers", "body", "keys"}
    assert call["url"] == f"{_BASE}/v1/orders/open/cancel"
    assert call["keys"] == [QUOTA_KEY_PORTFOLIO]
    assert call["body"] == json.dumps({"slugs": [_SLUG, _SLUG_B]}).encode("ascii")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_slugs",
    [
        pytest.param([], id="empty-list"),
        pytest.param([""], id="list-of-empty"),
        pytest.param([_SLUG, ""], id="valid-plus-empty"),
        pytest.param([_SLUG + "\n"], id="trailing-newline"),
        pytest.param(["tc-temp-nychigh-2026-10-1３-lt71f"], id="fullwidth-digit"),
        pytest.param([_SLUG, _SLUG], id="duplicate"),
        pytest.param(_SLUG, id="bare-string-not-a-list"),
        pytest.param(None, id="none"),
        pytest.param([None], id="none-element"),
        pytest.param([_SLUG.encode()], id="bytes-element"),
    ],
)
async def test_post_cancel_all_refuses_unsafe_slugs_without_sending(bad_slugs: Any) -> None:
    transport, client = _transport()
    with pytest.raises(ValueError):
        await transport.post_cancel_all(_BASE, headers=_HEADERS, slugs=bad_slugs)
    assert client.calls == []


@pytest.mark.asyncio
async def test_post_cancel_all_cannot_be_called_bodiless() -> None:
    transport, client = _transport()
    with pytest.raises(TypeError):
        await transport.post_cancel_all(_BASE, headers=_HEADERS)  # type: ignore[call-arg]
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", _BAD_SLUGS)
async def test_post_cancel_all_refuses_each_bad_slug_in_a_valid_list(bad: str) -> None:
    transport, client = _transport()
    with pytest.raises(ValueError):
        await transport.post_cancel_all(_BASE, headers=_HEADERS, slugs=[_SLUG, bad])
    assert client.calls == []


# ---------------------------------------------------------------- N5-style tree scan

_CANCEL_ALL_TOKENS = ("CANCEL_ALL_PATH", "_signed_post_cancel_all", "/v1/orders/open/cancel")
_OWNER = "src/breezy/adapters/polymarket_us/write_transport.py"


def _scan(tokens: tuple[str, ...], allowed: frozenset[str]) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for root in ("src", "scripts"):
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in allowed:
                continue
            text = path.read_text(encoding="utf-8")
            hits.extend((rel, t) for t in tokens if t in text)
    return hits


def test_legacy_probe_exemption_is_sha_pinned() -> None:
    digest = hashlib.sha256((REPO_ROOT / _LEGACY_PROBE).read_bytes()).hexdigest()
    assert digest == _LEGACY_PROBE_SHA256


def test_no_module_but_the_owner_and_the_pinned_probe_names_the_cancel_all_path() -> None:
    assert _scan(_CANCEL_ALL_TOKENS, frozenset({_OWNER, _LEGACY_PROBE})) == []


def test_scan_sees_a_planted_reference(tmp_path: Path) -> None:
    """Non-vacuity: the scanner flags a module that names the path or the helper."""
    planted = REPO_ROOT / "scripts" / "venue" / "_b1_planted_reference.py"
    planted.write_text("from x import _signed_post_cancel_all\n", encoding="utf-8")
    try:
        hits = _scan(_CANCEL_ALL_TOKENS, frozenset({_OWNER, _LEGACY_PROBE}))
    finally:
        planted.unlink()
    assert ("scripts/venue/_b1_planted_reference.py", "_signed_post_cancel_all") in hits


def test_no_module_imports_the_legacy_cancel_all_helper_beyond_the_probe() -> None:
    assert _scan(("_signed_post_cancel_all",), frozenset({_LEGACY_PROBE})) == []
