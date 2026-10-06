"""F13-C1 S2: AFOS (PFM) and LAV methods on the paced IEM transport.

MockTransport only (``tests.support.mock_http``); no socket is opened.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import inspect
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from breezy.ingest import http as http_module
from breezy.ingest.http import (
    ForbiddenError,
    OversizeBodyError,
    RateLimitedError,
    RedirectError,
    ServerError,
    TransportError,
)
from breezy.ingest.probe_transport import RequestBudget, RequestBudgetExceededError
from tests.support.mock_http import install_mock_http

FROZEN_NS = 1_758_153_600_000_000_000
UA = "breezy-afos-lav-test (project alias)"
_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/venue/iem_mos_probe_transport.py"
THROTTLE_BODY = "Too many requests from your IP address, slow down."


def _load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"breezy_probe_afos_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


iem = _load_script(_MODULE_PATH)


def _clock() -> int:
    return FROZEN_NS


class _Sleeps:
    def __init__(self) -> None:
        self.seconds: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)


def _transport(*, sleeper: Any = None, budget: int = 8, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "budget": RequestBudget(limit=budget),
        "pacer": iem.IemPacer(clock=_clock, sleeper=sleeper or _Sleeps()),
        "user_agent": UA,
        "clock": _clock,
        "max_body_bytes": 32 * 1024 * 1024,
        "accept": "text/plain",
        "check_proxy_env": False,
    }
    kwargs.update(overrides)
    return iem.PacedIemTransport(**kwargs)


def _serve(monkeypatch: pytest.MonkeyPatch, body: bytes | str = "ok\n", status: int = 200) -> Any:
    content = body if isinstance(body, bytes) else body.encode()
    return install_mock_http(monkeypatch, lambda _r: httpx.Response(status, content=content))


async def _call_each(transport: Any) -> list[Any]:
    return [
        await transport.fetch_afos_pfm("LOT"),
        await transport.fetch_afos_list("PFMLOT", dt.date(2026, 10, 5)),
        await transport.fetch_lav("KNYC", "2026-10-05T00:00Z", "2026-10-06T00:00Z"),
    ]


# ---------------------------------------------------------------------------
# URL shapes and closed sets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_afos_pfm_latest_url_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    http = _serve(monkeypatch)
    await _transport().fetch_afos_pfm("LOT")
    url = urlsplit(str(http.requests[0].url))
    assert url.netloc == "mesonet.agron.iastate.edu"
    assert url.path == "/cgi-bin/afos/retrieve.py"
    assert parse_qs(url.query) == {"pil": ["PFMLOT"], "limit": ["1"], "fmt": ["text"]}


@pytest.mark.asyncio
async def test_afos_pfm_history_url_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    http = _serve(monkeypatch)
    await _transport().fetch_afos_pfm("OKX", sdate=dt.date(2021, 1, 1), limit=20)
    query = parse_qs(urlsplit(str(http.requests[0].url)).query)
    assert query == {
        "pil": ["PFMOKX"],
        "sdate": ["2021-01-01"],
        "order": ["asc"],
        "limit": ["20"],
        "fmt": ["text"],
    }


@pytest.mark.asyncio
async def test_afos_list_url_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    http = _serve(monkeypatch, "{}")
    await _transport().fetch_afos_list("PFMMFL", dt.date(2026, 10, 5))
    url = urlsplit(str(http.requests[0].url))
    assert url.path == "/api/1/nws/afos/list.json"
    assert parse_qs(url.query) == {"pil": ["PFMMFL"], "date": ["2026-10-05"]}


@pytest.mark.asyncio
async def test_lav_url_shape_never_uses_the_mos_model_set(monkeypatch: pytest.MonkeyPatch) -> None:
    http = _serve(monkeypatch)
    await _transport().fetch_lav("KNYC", "2026-10-05T00:00Z", "2026-10-06T00:00Z")
    url = urlsplit(str(http.requests[0].url))
    assert url.path == "/cgi-bin/request/mos.py"
    assert parse_qs(url.query) == {
        "station": ["KNYC"],
        "model": ["LAV"],
        "format": ["csv"],
        "sts": ["2026-10-05T00:00Z"],
        "ets": ["2026-10-06T00:00Z"],
    }
    assert "LAV" not in iem.IEM_MOS_MODELS  # MOS fetch stays closed to LAV


@pytest.mark.asyncio
async def test_afos_and_lav_refuse_station_or_path_outside_closed_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = _serve(monkeypatch)
    transport = _transport()
    assert iem.IEM_AFOS_WFOS == frozenset({"OKX", "LOX", "LOT", "MTR", "MFL"})
    for wfo in ("KLOT", "ORD", "lot", "LOT ", "", "OKX&pil=CLINYC", "../LOT"):
        with pytest.raises(ValueError):
            await transport.fetch_afos_pfm(wfo)
    for pil in ("CLINYC", "PFMJFK", "pfmlot", "PFM", "AFDLOT", "PFMLOT&x=1"):
        with pytest.raises(ValueError):
            await transport.fetch_afos_list(pil, dt.date(2026, 10, 5))
    for station in ("KJFK", "NYC", "knyc", "KNYC&x=1", ""):
        with pytest.raises(ValueError):
            await transport.fetch_lav(station, "2026-10-05T00:00Z", "2026-10-06T00:00Z")
    with pytest.raises(ValueError):
        await transport.fetch_lav("KNYC", "2026-10-05", "2026-10-06T00:00Z")
    for bad_limit in (0, 51, True):
        with pytest.raises((ValueError, TypeError)):
            await transport.fetch_afos_pfm("LOT", limit=bad_limit)
    with pytest.raises(TypeError):
        await transport.fetch_afos_pfm("LOT", sdate="2021-01-01")
    with pytest.raises(TypeError):
        await transport.fetch_afos_list("PFMLOT", "2026-10-05")
    assert http.requests == []


def test_afos_and_lav_methods_take_no_caller_supplied_url_or_path() -> None:
    for name in ("fetch_afos_pfm", "fetch_afos_list", "fetch_lav"):
        parameters = inspect.signature(getattr(iem.PacedIemTransport, name)).parameters
        assert not {"url", "path", "host", "base_url", "format", "model"} & set(parameters)


def test_new_path_constants_sit_beside_iem_mos_path() -> None:
    assert iem.IEM_AFOS_RETRIEVE_PATH == "/cgi-bin/afos/retrieve.py"
    assert iem.IEM_AFOS_LIST_PATH == "/api/1/nws/afos/list.json"
    assert iem.IEM_MOS_PATH == "/cgi-bin/request/mos.py"


# ---------------------------------------------------------------------------
# Per-method byte caps
# ---------------------------------------------------------------------------


def test_afos_and_lav_have_per_method_byte_caps() -> None:
    caps = {
        "pfm": iem.IEM_AFOS_PFM_MAX_BODY_BYTES,
        "list": iem.IEM_AFOS_LIST_MAX_BODY_BYTES,
        "lav": iem.IEM_LAV_MAX_BODY_BYTES,
    }
    assert caps == {"pfm": 2 * 1024 * 1024, "list": 1024 * 1024, "lav": 16 * 1024 * 1024}
    assert all(cap < iem.IEM_MOS_PROBE_MAX_BODY_BYTES for cap in caps.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["pfm", "list", "lav"])
async def test_each_method_enforces_its_own_cap_while_streaming(
    monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    cap = {
        "pfm": iem.IEM_AFOS_PFM_MAX_BODY_BYTES,
        "list": iem.IEM_AFOS_LIST_MAX_BODY_BYTES,
        "lav": iem.IEM_LAV_MAX_BODY_BYTES,
    }[which]
    _serve(monkeypatch, b"A" * (cap + 1))
    transport = _transport()
    calls = {
        "pfm": lambda: transport.fetch_afos_pfm("LOT"),
        "list": lambda: transport.fetch_afos_list("PFMLOT", dt.date(2026, 10, 5)),
        "lav": lambda: transport.fetch_lav("KNYC", "2026-10-05T00:00Z", "2026-10-06T00:00Z"),
    }
    with pytest.raises(OversizeBodyError):
        await calls[which]()
    assert transport._max_body_bytes == 32 * 1024 * 1024  # the shared cap is not mutated


@pytest.mark.asyncio
async def test_a_body_at_exactly_the_cap_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, b"A" * iem.IEM_AFOS_LIST_MAX_BODY_BYTES)
    result = await _transport().fetch_afos_list("PFMLOT", dt.date(2026, 10, 5))
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# Pacing (A0-R1) and the shared transport
# ---------------------------------------------------------------------------


def test_afos_lav_interval_is_at_least_four_seconds_and_mos_interval_unchanged() -> None:
    assert iem.IEM_AFOS_LAV_MIN_INTERVAL_NS >= 4_000_000_000
    assert iem.IEM_MIN_INTERVAL_NS == 1_000_000_000


@pytest.mark.asyncio
async def test_afos_and_lav_calls_are_spaced_by_the_four_second_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch)
    now = [FROZEN_NS]
    slept: list[float] = []

    async def advancing_sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += round(seconds * 1e9)

    transport = _transport(
        pacer=iem.IemPacer(clock=lambda: now[0], sleeper=advancing_sleep), clock=lambda: now[0]
    )
    await _call_each(transport)
    assert slept == [
        iem.IEM_AFOS_LAV_MIN_INTERVAL_NS / 1e9,
        iem.IEM_AFOS_LAV_MIN_INTERVAL_NS / 1e9,
    ]


@pytest.mark.asyncio
async def test_the_mos_fetch_keeps_its_one_second_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch)
    sleeps = _Sleeps()
    transport = iem.IemMosProbeTransport(
        budget=RequestBudget(limit=4),
        pacer=iem.IemPacer(clock=_clock, sleeper=sleeps),
        user_agent=UA,
        clock=_clock,
        check_proxy_env=False,
    )
    for _ in range(2):
        await transport.fetch_mos_csv("KNYC", "GFS", "2026-10-05T00:00Z", "2026-10-06T00:00Z")
    assert sleeps.seconds == [1.0]


@pytest.mark.asyncio
async def test_afos_and_lav_use_paced_iem_transport_not_a_second_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch)
    for name in ("fetch_afos_pfm", "fetch_afos_list", "fetch_lav"):
        assert name in vars(iem.PacedIemTransport)
    # Budget is charged by the one shared `_fetch`: the second call exhausts a limit of 1.
    transport = _transport(budget=1)
    await transport.fetch_afos_pfm("LOT")
    with pytest.raises(RequestBudgetExceededError):
        await transport.fetch_afos_list("PFMLOT", dt.date(2026, 10, 5))
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    http_subclasses = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(
            getattr(base, "id", "") in {"HttpTransport", "PacedIemTransport"} for base in node.bases
        )
    ]
    assert sorted(http_subclasses) == ["IemMosProbeTransport", "PacedIemTransport"]
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "AsyncClient" not in attrs
    assert "iem_mos_request" not in names  # LAV never goes through the MOS archive request


@pytest.mark.asyncio
async def test_default_user_agent_and_accept_are_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    http = _serve(monkeypatch)
    await _transport().fetch_afos_pfm("LOT")
    assert http.requests[0].headers["user-agent"] == UA
    assert http.requests[0].method == "GET"


# ---------------------------------------------------------------------------
# Throttle body and existing http errors only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 404, 503])
async def test_iem_throttle_body_is_refused_never_returned_as_data(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    _serve(monkeypatch, THROTTLE_BODY, status=status)
    transport = _transport()
    expected = ServerError if status == 503 else RateLimitedError
    with pytest.raises(expected):
        await transport.fetch_afos_pfm("LOT")
    if status != 503:
        with pytest.raises(RateLimitedError, match="Too many requests"):
            await transport.fetch_afos_list("PFMLOT", dt.date(2026, 10, 5))
        with pytest.raises(RateLimitedError):
            await transport.fetch_lav("KNYC", "2026-10-05T00:00Z", "2026-10-06T00:00Z")


@pytest.mark.asyncio
async def test_throttle_body_error_message_is_redacted_and_names_no_query_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, THROTTLE_BODY)
    with pytest.raises(RateLimitedError) as caught:
        await _transport().fetch_afos_pfm("LOT")
    assert "PFMLOT" not in str(caught.value)
    assert "REDACTED" in str(caught.value)


@pytest.mark.asyncio
async def test_a_normal_body_mentioning_requests_is_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, "FOUS53 KLOT 060156\nPFMLOT\n")
    result = await _transport().fetch_afos_pfm("LOT")
    assert result.text == "FOUS53 KLOT 060156\nPFMLOT\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(429, headers={"Retry-After": "9"}), RateLimitedError),
        (httpx.Response(403), ForbiddenError),
        (httpx.Response(503), ServerError),
        (httpx.Response(302, headers={"Location": "https://evil.example/"}), RedirectError),
    ],
)
async def test_afos_and_lav_raise_only_existing_http_errors(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response, error: type[TransportError]
) -> None:
    install_mock_http(monkeypatch, lambda _r: response)
    transport = _transport()
    calls: list[Callable[[], Awaitable[Any]]] = [
        lambda: transport.fetch_afos_pfm("LOT"),
        lambda: transport.fetch_afos_list("PFMLOT", dt.date(2026, 10, 5)),
        lambda: transport.fetch_lav("KNYC", "2026-10-05T00:00Z", "2026-10-06T00:00Z"),
    ]
    for call in calls:
        with pytest.raises(error) as caught:
            await call()
        assert type(caught.value).__module__ == http_module.__name__
        if isinstance(caught.value, RateLimitedError):
            assert caught.value.retry_after == "9"


def test_module_defines_no_new_transport_error_subclass() -> None:
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    raised = {
        getattr(node.exc.func, "id", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
    }
    local_classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert not (raised & local_classes)
    assert {"RateLimitedError"} <= raised


@pytest.mark.asyncio
async def test_afos_pfm_history_accepts_a_utc_instant_cursor_to_the_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = _serve(monkeypatch)
    cursor = dt.datetime(2026, 8, 25, 19, 1, 30, tzinfo=dt.UTC)
    await _transport().fetch_afos_pfm("LOT", sdate=cursor, limit=20)
    query = parse_qs(urlsplit(str(http.requests[0].url)).query)
    assert query["sdate"] == ["2026-08-25T19:01Z"]
    assert query["order"] == ["asc"]


@pytest.mark.asyncio
async def test_afos_pfm_refuses_a_naive_or_non_utc_instant_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = _serve(monkeypatch)
    offset = dt.timezone(dt.timedelta(hours=-7))
    naive = dt.datetime(2026, 8, 25, 19, 1)  # noqa: DTZ001 - the refused input under test
    for bad in (naive, dt.datetime(2026, 8, 25, 19, 1, tzinfo=offset)):
        with pytest.raises(ValueError):
            await _transport().fetch_afos_pfm("LOT", sdate=bad, limit=20)
    assert http.requests == []
