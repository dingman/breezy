"""Unit tests for the paced IEM MOS probe transport (FC-0a-1).

Every test here runs against fixtures. ``tests/conftest.py`` blocks real
sockets for anything not marked ``live``/``allow_socket``, and nothing here
carries either marker.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from breezy.ingest.http import FetchResult, HttpTransport, OversizeBodyError, RedirectError
from breezy.ingest.iem_mos_probe_transport import (
    IEM_BASE_URL,
    IEM_MIN_INTERVAL_NS,
    IemMosProbeTransport,
    IemPacer,
    exchange_from_alarm,
    exchange_from_result,
)
from breezy.ingest.probe_transport import (
    SETTLEMENT_HOSTS,
    RequestBudget,
    RequestBudgetExceededError,
    SettlementHostForbiddenError,
)

UA = "breezy-mos-probe-test (contact: ops@example.invalid)"
FROZEN_NS = 1_758_153_600_000_000_000  # 2026-09-18T00:00:00Z
_MODULE_PATH = Path(__file__).resolve().parents[2] / "src/breezy/ingest/iem_mos_probe_transport.py"


def _clock() -> int:
    return FROZEN_NS


async def _noop_sleep(_seconds: float) -> None:
    return None


def _pacer(
    *,
    clock: Callable[[], int] = _clock,
    sleeper: Callable[[float], Any] | None = None,
) -> IemPacer:
    return IemPacer(clock=clock, sleeper=sleeper or _noop_sleep)


def _transport(**overrides: object) -> IemMosProbeTransport:
    kwargs: dict[str, object] = {
        "budget": RequestBudget(limit=8),
        "pacer": _pacer(),
        "user_agent": UA,
        "clock": _clock,
        "check_proxy_env": False,
    }
    kwargs.update(overrides)
    return IemMosProbeTransport(**kwargs)  # type: ignore[arg-type]


def _result(
    text: str = "station,model,runtime\n", *, status: int = 200, url: str = ""
) -> FetchResult:
    return FetchResult(
        text=text,
        sha256="ab" * 32,
        status_code=status,
        headers=httpx.Headers({"content-type": "text/csv"}),
        url=url or f"{IEM_BASE_URL}/cgi-bin/request/mos.py",
        retrieved_at_ns=FROZEN_NS,
    )


def test_constructor_refuses_settlement_host() -> None:
    host = next(iter(SETTLEMENT_HOSTS))
    with pytest.raises(SettlementHostForbiddenError):
        _transport(allowed_hosts=frozenset({host}), base_url=f"https://{host}")


def test_constructor_refuses_non_mesonet_allowlist() -> None:
    with pytest.raises(ValueError):
        _transport(
            allowed_hosts=frozenset({"example.invalid"}),
            base_url="https://example.invalid",
        )
    with pytest.raises(ValueError):
        _transport(allowed_hosts=frozenset({"example.invalid"}))


@pytest.mark.asyncio
async def test_fetch_discovery_list_is_closed() -> None:
    with pytest.raises(NotImplementedError):
        await _transport().fetch_discovery_list("NYC")


@pytest.mark.asyncio
async def test_fetch_product_is_closed() -> None:
    with pytest.raises(NotImplementedError):
        await _transport().fetch_product("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_fetch_station_observations_is_closed() -> None:
    with pytest.raises(NotImplementedError):
        await _transport().fetch_station_observations("KMDW", limit=1)


def test_mos_url_rejects_knyc() -> None:
    with pytest.raises(ValueError):
        _transport()._mos_url("KNYC", "NBS", "2021-01-01T00:00Z", "2021-12-31T23:59Z")


def test_mos_url_rejects_nam() -> None:
    with pytest.raises(ValueError):
        _transport()._mos_url("KMDW", "NAM", "2021-01-01T00:00Z", "2021-12-31T23:59Z")


def test_mos_url_pin_format_csv() -> None:
    url = _transport()._mos_url("KMDW", "NBS", "2021-01-01T00:00Z", "2021-12-31T23:59Z")
    query = parse_qs(urlsplit(url).query)
    assert query["format"] == ["csv"]
    assert urlsplit(url).path == "/cgi-bin/request/mos.py"
    signature = inspect.signature(IemMosProbeTransport.fetch_mos_csv)
    assert "format" not in signature.parameters
    assert "url" not in signature.parameters


def test_mos_url_uses_urlencode_and_keeps_colon_in_sts_ets_values() -> None:
    sts = "2021-01-01T00:00Z"
    ets = "2021-12-31T23:59Z"
    url = _transport()._mos_url("KMDW", "NBS", sts, ets)
    assert "%3A" in url
    query = parse_qs(urlsplit(url).query)
    assert query["sts"] == [sts]
    assert query["ets"] == [ets]
    assert ":" in query["sts"][0]
    assert ":" in query["ets"][0]
    assert query["station"] == ["KMDW"]
    assert query["model"] == ["NBS"]


@respx.mock
@pytest.mark.asyncio
async def test_budget_n_plus_one_raises_before_socket() -> None:
    route = respx.get(url__startswith=IEM_BASE_URL).mock(
        return_value=httpx.Response(200, text="station,model,runtime\n")
    )
    transport = _transport(budget=RequestBudget(limit=1))
    await transport.fetch_mos_csv("KMDW", "NBS", "2021-01-01T00:00Z", "2021-12-31T23:59Z")
    assert route.call_count == 1
    with pytest.raises(RequestBudgetExceededError):
        await transport.fetch_mos_csv("KLAX", "NBS", "2021-01-01T00:00Z", "2021-12-31T23:59Z")
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_iem_pacer_enforces_one_second_minimum_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    async def sleeper(seconds: float) -> None:
        slept.append(seconds)

    now = [FROZEN_NS]

    def clock() -> int:
        return now[0]

    async def fake_fetch(
        self: HttpTransport,
        url: str,
        *,
        if_none_match: str | None,
        if_modified_since: str | None,
        allow_not_modified: bool,
    ) -> FetchResult:
        return _result(url=url)

    monkeypatch.setattr(HttpTransport, "_fetch", fake_fetch)
    transport = _transport(
        budget=RequestBudget(limit=3),
        pacer=_pacer(clock=clock, sleeper=sleeper),
        clock=clock,
    )
    await transport.fetch_mos_csv("KMDW", "NBS", "2021-01-01T00:00Z", "2021-12-31T23:59Z")
    assert slept == []
    now[0] = FROZEN_NS + 400_000_000
    await transport.fetch_mos_csv("KMDW", "NBS", "2022-01-01T00:00Z", "2022-12-31T23:59Z")
    assert len(slept) == 1
    assert slept[0] == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_iem_pacer_skips_sleep_when_interval_already_elapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    async def sleeper(seconds: float) -> None:
        slept.append(seconds)

    now = [FROZEN_NS]

    def clock() -> int:
        return now[0]

    async def fake_fetch(
        self: HttpTransport,
        url: str,
        *,
        if_none_match: str | None,
        if_modified_since: str | None,
        allow_not_modified: bool,
    ) -> FetchResult:
        return _result(url=url)

    monkeypatch.setattr(HttpTransport, "_fetch", fake_fetch)
    transport = _transport(
        budget=RequestBudget(limit=3),
        pacer=_pacer(clock=clock, sleeper=sleeper),
        clock=clock,
    )
    await transport.fetch_mos_csv("KMDW", "NBS", "2021-01-01T00:00Z", "2021-12-31T23:59Z")
    now[0] = FROZEN_NS + IEM_MIN_INTERVAL_NS
    await transport.fetch_mos_csv("KMDW", "NBS", "2022-01-01T00:00Z", "2022-12-31T23:59Z")
    assert slept == []


@pytest.mark.asyncio
async def test_fetch_mos_csv_calls__fetch_with_no_conditional_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_fetch(
        self: HttpTransport,
        url: str,
        *,
        if_none_match: str | None,
        if_modified_since: str | None,
        allow_not_modified: bool,
    ) -> FetchResult:
        captured["url"] = url
        captured["if_none_match"] = if_none_match
        captured["if_modified_since"] = if_modified_since
        captured["allow_not_modified"] = allow_not_modified
        return _result(url=url)

    monkeypatch.setattr(HttpTransport, "_fetch", fake_fetch)
    await _transport().fetch_mos_csv("KSFO", "GFS", "2023-01-01T00:00Z", "2023-12-31T23:59Z")
    assert captured["if_none_match"] is None
    assert captured["if_modified_since"] is None
    assert captured["allow_not_modified"] is False
    assert "/cgi-bin/request/mos.py" in str(captured["url"])


def test_exchange_from_result_non_2xx_never_outcome_ok() -> None:
    signature = inspect.signature(exchange_from_result)
    assert list(signature.parameters) == ["label", "url", "result", "ordinal", "requested_at_utc"]
    for name in signature.parameters.values():
        assert name.kind is inspect.Parameter.KEYWORD_ONLY
    url = f"{IEM_BASE_URL}/cgi-bin/request/mos.py"
    exchange = exchange_from_result(
        label="nbs_kmdw_2021",
        url=url,
        result=_result("nope", status=404, url=url),
        ordinal=3,
        requested_at_utc="2026-09-18T00:00:00+00:00",
    )
    assert exchange.outcome != "ok"
    assert exchange.outcome == "http_404"
    assert exchange.text is None
    assert exchange.ordinal == 3
    ok = exchange_from_result(
        label="nbs_kmdw_2021",
        url=url,
        result=_result(status=200, url=url),
        ordinal=1,
        requested_at_utc="2026-09-18T00:00:00+00:00",
    )
    assert ok.outcome == "ok"
    assert ok.text is None


def test_exchange_from_alarm_redirect_and_oversize() -> None:
    signature = inspect.signature(exchange_from_alarm)
    assert list(signature.parameters) == ["label", "url", "error", "ordinal", "requested_at_utc"]
    url = f"{IEM_BASE_URL}/cgi-bin/request/mos.py"
    redirected = exchange_from_alarm(
        label="nbs_kmdw_2021",
        url=url,
        error=RedirectError("moved", status_code=302, location="https://example.invalid/x"),
        ordinal=2,
        requested_at_utc="2026-09-18T00:00:00+00:00",
    )
    assert redirected.outcome == "redirect_not_followed"
    assert redirected.status_code == 302
    assert redirected.sha256 is None
    assert redirected.body_bytes == 0
    assert redirected.text is None
    oversize = exchange_from_alarm(
        label="nbs_kmdw_2021",
        url=url,
        error=OversizeBodyError("body exceeded cap"),
        ordinal=4,
        requested_at_utc="2026-09-18T00:00:00+00:00",
    )
    assert oversize.outcome == "error:OversizeBodyError"
    assert oversize.sha256 is None
    assert oversize.body_bytes == 0
    assert oversize.text is None


def test_module_does_not_import_httpx() -> None:
    source = _MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".")[0])
    assert "httpx" not in imported


def test_module_does_not_import_breezy_runtime() -> None:
    source = _MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("breezy.runtime")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("breezy.runtime")


def test_module_source_never_names_weather_gov() -> None:
    source = _MODULE_PATH.read_text(encoding="utf-8")
    assert "weather.gov" not in source
