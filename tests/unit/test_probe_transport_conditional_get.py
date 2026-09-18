"""Q3b: additive conditional-GET kwargs on ``ProbeTransport.probe_get_strict``.

T13 and T14 live here, next to the transport rather than in
``test_probe_containment.py``, so the containment public-surface assertion
body stays name-based and unedited. Defaults must reproduce today's
byte-for-byte behaviour: no validator is sent unless the caller opts in,
and an unsolicited 304 still raises.
"""

from __future__ import annotations

import inspect

import httpx
import pytest
import respx

from breezy.ingest.http import RedirectError
from breezy.ingest.probe_transport import ProbeTransport, RequestBudget

PROBE_UA = "breezy-probe (contact: ops@example.invalid)"
BASE_URL = "https://api.open-meteo.com"
PATH = "/v1/probe"
URL = f"{BASE_URL}{PATH}"


def _clock() -> int:
    return 1_700_000_000_000_000_000


def _transport(*, budget: RequestBudget | None = None) -> ProbeTransport:
    return ProbeTransport(
        base_url=BASE_URL,
        allowed_hosts=frozenset({"api.open-meteo.com"}),
        budget=budget if budget is not None else RequestBudget(limit=8),
        max_body_bytes=4096,
        user_agent=PROBE_UA,
        accept="application/json",
        clock=_clock,
    )


@respx.mock
@pytest.mark.asyncio
async def test_a_conditional_get_sends_the_validator_and_still_charges_the_budget() -> None:
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, json={"ok": True}, headers={"ETag": '"abc123"'}),
            httpx.Response(304, headers={"ETag": '"abc123"'}),
        ]
    )
    budget = RequestBudget(limit=3)
    transport = _transport(budget=budget)

    first = await transport.probe_get_strict(
        PATH,
        if_none_match='"abc123"',
        allow_not_modified=True,
    )
    assert first.status_code == 200
    assert route.calls[0].request.headers["If-None-Match"] == '"abc123"'
    assert budget.spent == 1

    second = await transport.probe_get_strict(
        PATH,
        if_none_match='"abc123"',
        if_modified_since="Sat, 22 Aug 2026 06:26:00 GMT",
        allow_not_modified=True,
    )
    assert second.status_code == 304
    assert second.text is None, "a 304 must not be misread as an empty body"
    assert second.sha256 is None
    sent = route.calls[1].request
    assert sent.headers["If-None-Match"] == '"abc123"'
    assert sent.headers["If-Modified-Since"] == "Sat, 22 Aug 2026 06:26:00 GMT"
    assert budget.spent == 2
    assert route.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_the_default_strict_get_is_unchanged_and_sends_no_validator() -> None:
    signature = inspect.signature(ProbeTransport.probe_get_strict)
    for name in ("if_none_match", "if_modified_since", "allow_not_modified"):
        assert name in signature.parameters, f"Q3b did not add {name!r} to probe_get_strict"
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["if_none_match"].default is None
    assert signature.parameters["if_modified_since"].default is None
    assert signature.parameters["allow_not_modified"].default is False

    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, json={"ok": True}),
            httpx.Response(304, headers={"ETag": '"abc123"'}),
        ]
    )
    transport = _transport()

    result = await transport.probe_get_strict(PATH)
    assert result.status_code == 200
    sent = route.calls[0].request
    assert "If-None-Match" not in sent.headers
    assert "If-Modified-Since" not in sent.headers

    with pytest.raises(RedirectError):
        await transport.probe_get_strict(PATH)
    assert route.call_count == 2
