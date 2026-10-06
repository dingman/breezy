"""F13-C1 S2: the MDL/NOMADS LAMP transport (H1, H2, M8, LOW).

Every exchange is an ``httpx.MockTransport`` installed by
``tests.support.mock_http``; no socket is ever opened.
"""

from __future__ import annotations

import ast
import datetime as dt
import gzip
import hashlib
import io
import random
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from breezy.ingest import mdl_lamp_transport as mod
from breezy.ingest.http import (
    ContentEncodingError,
    DecodeError,
    DisallowedHostError,
    ForbiddenError,
    OversizeBodyError,
    ProxyEnvironmentError,
    RateLimitedError,
    RedirectError,
    ServerError,
    TransportError,
    UserAgentConfigurationError,
)
from breezy.ingest.mdl_lamp_transport import (
    LAMP_ALLOWED_HOSTS,
    LAMP_MDL_HOST,
    LAMP_NOMADS_HOST,
    LampArchiveIntegrityError,
    LampArchiveLimits,
    LampNotPublishedError,
    MdlLampTransport,
    build_mdl_lamp_transport,
)
from breezy.ingest.routing import TRANSPORT_ERROR_ROUTES
from tests.support.mock_http import MockHttp, install_mock_http

FROZEN_NS = 1_789_000_000_000_000_000
RUN_DATE = dt.date(2026, 10, 6)
LAST_MODIFIED = "Tue, 06 Oct 2026 01:36:05 GMT"
REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src/breezy/ingest/mdl_lamp_transport.py"

NOMADS_BULLETIN_URL = (
    f"https://{LAMP_NOMADS_HOST}/pub/data/nccf/com/lmp/prod/lmp.20261006/lmp.t0130z.lavtxt.ascii"
)
MDL_MONTH_URL = f"https://{LAMP_MDL_HOST}/lamp/Data/archives/lmp_lavtxt.202609.0130z.gz"
MDL_YEAR_URL = f"https://{LAMP_MDL_HOST}/lamp/Data/archives/lmp_lavtxt.2025.tar"


def _clock() -> int:
    return FROZEN_NS


def _transport(**kwargs: Any) -> MdlLampTransport:
    return MdlLampTransport(clock=_clock, check_proxy_env=False, **kwargs)


def _block(station: str, *, rows: int = 2, rng: random.Random | None = None) -> str:
    header = f"{station}   GFS LAMP GUIDANCE  10/06/2026  0130 UTC\n"
    body = ""
    for i in range(rows):
        digits = "".join(str(rng.randrange(10)) for _ in range(120)) if rng is not None else "59 57"
        body += f" TMP{i} {digits}\n"
    return header + body


def _bulletin_text() -> str:
    return "".join(_block(s) for s in ("KNYC", "KMIA", "KMDW", "KLAX", "KSFO", "KJFK"))


def _gz(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"))


def _tar(members: list[tuple[str, bytes]], extra: list[tarfile.TarInfo] | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, payload in members:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        for info in extra or []:
            archive.addfile(info)
    return buffer.getvalue()


def _ok(body: bytes, **headers: str) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"Last-Modified": LAST_MODIFIED, **headers})


def _serve(monkeypatch: pytest.MonkeyPatch, body: bytes, **headers: str) -> MockHttp:
    return install_mock_http(monkeypatch, lambda _request: _ok(body, **headers))


# ---------------------------------------------------------------------------
# Allowlist, M8 host-to-path-prefix binding
# ---------------------------------------------------------------------------


def test_allowlist_is_exactly_nomads_and_mdl() -> None:
    assert frozenset({"nomads.ncep.noaa.gov", "lamp.mdl.nws.noaa.gov"}) == LAMP_ALLOWED_HOSTS
    assert _transport()._allowed_hosts == LAMP_ALLOWED_HOSTS


@pytest.mark.parametrize(
    "url",
    [
        "https://nomads.ncep.noaa.gov.evil.example/pub/data/nccf/com/lmp/prod/x",
        "https://evil.nomads.ncep.noaa.gov/pub/data/nccf/com/lmp/prod/x",
        "https://xlamp.mdl.nws.noaa.gov/lamp/Data/archives/x",
        "https://lamp.mdl.nws.noaa.gov.evil.example/lamp/Data/archives/x",
        "https://noaa-lamp-pds.s3.amazonaws.com/x",
        "https://s3.amazonaws.com/lamp/Data/archives/x",
    ],
)
def test_transport_refuses_non_exact_host_suffix_and_subdomain(url: str) -> None:
    with pytest.raises(DisallowedHostError):
        _transport()._validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        f"http://{LAMP_NOMADS_HOST}/pub/data/nccf/com/lmp/prod/x",
        f"https://{LAMP_NOMADS_HOST}:8443/pub/data/nccf/com/lmp/prod/x",
        f"https://user:pw@{LAMP_MDL_HOST}/lamp/Data/archives/x",
    ],
)
def test_transport_refuses_non_https_and_non_443(url: str) -> None:
    with pytest.raises(DisallowedHostError):
        _transport()._validate_url(url)


def test_host_is_bound_to_its_path_prefix_in_both_directions() -> None:
    transport = _transport()
    transport._validate_url(NOMADS_BULLETIN_URL)
    transport._validate_url(MDL_MONTH_URL)
    with pytest.raises(DisallowedHostError):
        transport._validate_url(
            f"https://{LAMP_NOMADS_HOST}/lamp/Data/archives/lmp_lavtxt.2025.tar"
        )
    with pytest.raises(DisallowedHostError):
        transport._validate_url(
            f"https://{LAMP_MDL_HOST}/pub/data/nccf/com/lmp/prod/lmp.20261006/x"
        )
    with pytest.raises(DisallowedHostError):
        transport._validate_url(f"https://{LAMP_NOMADS_HOST}/pub/data/nccf/com/blend/prod/x")


@pytest.mark.parametrize(
    "path",
    [
        "/pub/data/nccf/com/lmp/prod/../../../../etc/passwd",
        "/pub/data/nccf/com/lmp/prod/%2e%2e/x",
        "/pub/data/nccf/com/lmp/prod//x",
        "/pub/data/nccf/com/lmp/prodX/x",
    ],
)
def test_path_prefix_binding_refuses_traversal_and_lookalike_prefixes(path: str) -> None:
    with pytest.raises(DisallowedHostError):
        _transport()._validate_url(f"https://{LAMP_NOMADS_HOST}{path}")


@pytest.mark.asyncio
async def test_inherited_nws_endpoints_cannot_reach_the_lamp_hosts() -> None:
    transport = _transport()
    with pytest.raises(DisallowedHostError):
        await transport.fetch_product("00000000-0000-0000-0000-000000000000")
    with pytest.raises(DisallowedHostError):
        await transport.fetch_discovery_list("NYC")


# ---------------------------------------------------------------------------
# Hardened client, GET only, proxy env, no redirects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_is_http11_no_redirect_no_env_identity_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = _serve(monkeypatch, _bulletin_text().encode())
    await _transport().fetch_lamp_bulletin(RUN_DATE, 1)
    (kwargs,) = http.client_kwargs
    assert kwargs["http2"] is False
    assert kwargs["follow_redirects"] is False
    assert kwargs["trust_env"] is False
    assert kwargs["headers"]["Accept-Encoding"] == "identity"


def test_archive_client_is_http11_no_redirect_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    http = _serve(monkeypatch, _gz(_bulletin_text()))
    with _transport().fetch_lamp_archive_month("202609", "0130") as stream:
        list(stream.lines())
    (kwargs,) = http.client_kwargs
    assert kwargs["http2"] is False
    assert kwargs["follow_redirects"] is False
    assert kwargs["trust_env"] is False


@pytest.mark.asyncio
async def test_transport_is_get_only(monkeypatch: pytest.MonkeyPatch) -> None:
    http = _serve(monkeypatch, _bulletin_text().encode())
    await _transport().fetch_lamp_bulletin(RUN_DATE, 1)
    assert [request.method for request in http.requests] == ["GET"]
    public = {name for name in dir(MdlLampTransport) if not name.startswith("_")}
    assert not public & {"post", "put", "delete", "patch", "request", "send"}


@pytest.mark.asyncio
@pytest.mark.parametrize("location_host", [LAMP_NOMADS_HOST, "evil.example"])
async def test_transport_refuses_3xx_to_allowed_and_disallowed_host(
    monkeypatch: pytest.MonkeyPatch, location_host: str
) -> None:
    http = install_mock_http(
        monkeypatch,
        lambda _r: httpx.Response(
            302, headers={"Location": f"https://{location_host}/pub/data/nccf/com/lmp/prod/x"}
        ),
    )
    with pytest.raises(RedirectError):
        await _transport().fetch_lamp_bulletin(RUN_DATE, 1)
    assert len(http.requests) == 1  # never followed


def test_archive_3xx_is_an_error_and_not_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    http = install_mock_http(
        monkeypatch, lambda _r: httpx.Response(301, headers={"Location": "https://evil.example/"})
    )
    with (
        pytest.raises(RedirectError),
        _transport().fetch_lamp_archive_month("202609", "0130"),
    ):
        pass
    assert len(http.requests) == 1


def test_transport_refuses_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    with pytest.raises(ProxyEnvironmentError):
        MdlLampTransport(clock=_clock)


@pytest.mark.asyncio
async def test_proxy_env_set_after_construction_is_caught_on_next_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    http = _serve(monkeypatch, _bulletin_text().encode())
    transport = MdlLampTransport(clock=_clock)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    with pytest.raises(ProxyEnvironmentError):
        await transport.fetch_lamp_bulletin(RUN_DATE, 1)
    with pytest.raises(ProxyEnvironmentError), transport.fetch_lamp_archive_year(2025):
        pass
    assert http.requests == []


# ---------------------------------------------------------------------------
# Hourly bulletin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulletin_fetch_returns_provenance_and_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _bulletin_text().encode()
    http = _serve(monkeypatch, raw)
    result = await _transport().fetch_lamp_bulletin(RUN_DATE, 1)
    assert str(http.requests[0].url) == NOMADS_BULLETIN_URL
    assert result.source_host == LAMP_NOMADS_HOST
    assert result.last_modified == LAST_MODIFIED
    assert result.sha256 == hashlib.sha256(raw).hexdigest()
    assert result.body == raw.decode()
    assert result.retrieved_at_ns == FROZEN_NS


@pytest.mark.asyncio
async def test_extended_bulletin_uses_the_lavtxt_ext_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = _serve(monkeypatch, b"x\n")
    await _transport().fetch_lamp_bulletin(RUN_DATE, 13, extended=True)
    assert http.requests[0].url.path == (
        "/pub/data/nccf/com/lmp/prod/lmp.20261006/lmp.t1330z.lavtxt_ext.ascii"
    )


@pytest.mark.asyncio
async def test_missing_last_modified_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    install_mock_http(monkeypatch, lambda _r: httpx.Response(200, content=b"x\n"))
    result = await _transport().fetch_lamp_bulletin(RUN_DATE, 1)
    assert result.last_modified is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("run_date", "run_hour", "error"),
    [
        ("2026-10-06", 1, TypeError),
        (dt.datetime(2026, 10, 6, 1, tzinfo=dt.UTC), 1, TypeError),
        (RUN_DATE, "01", TypeError),
        (RUN_DATE, True, TypeError),
        (RUN_DATE, 24, ValueError),
        (RUN_DATE, -1, ValueError),
        (None, 1, TypeError),
    ],
)
async def test_bulletin_arguments_are_validated_before_any_request(
    monkeypatch: pytest.MonkeyPatch, run_date: Any, run_hour: Any, error: type[Exception]
) -> None:
    http = _serve(monkeypatch, b"x")
    with pytest.raises(error):
        await _transport().fetch_lamp_bulletin(run_date, run_hour)
    assert http.requests == []


@pytest.mark.asyncio
async def test_404_is_a_not_yet_published_error_not_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_mock_http(monkeypatch, lambda _r: httpx.Response(404, content=b"nope"))
    with pytest.raises(LampNotPublishedError) as caught:
        await _transport().fetch_lamp_bulletin(RUN_DATE, 1)
    assert caught.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error"),
    [(403, ForbiddenError), (503, ServerError), (418, TransportError)],
)
async def test_other_statuses_raise_existing_http_errors(
    monkeypatch: pytest.MonkeyPatch, status: int, error: type[Exception]
) -> None:
    install_mock_http(monkeypatch, lambda _r: httpx.Response(status, content=b"x"))
    with pytest.raises(error):
        await _transport().fetch_lamp_bulletin(RUN_DATE, 1)


@pytest.mark.asyncio
async def test_oversize_body_refused_by_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, b"A" * 2048)
    with pytest.raises(OversizeBodyError):
        await _transport(max_bulletin_bytes=1024).fetch_lamp_bulletin(RUN_DATE, 1)


def test_per_method_byte_caps_are_distinct_and_pinned() -> None:
    assert mod.DEFAULT_LAMP_BULLETIN_MAX_BYTES == 16 * 1024 * 1024
    assert mod.DEFAULT_LAMP_MONTH_LIMITS.max_compressed_bytes == 64 * 1024 * 1024
    assert mod.DEFAULT_LAMP_YEAR_LIMITS.max_compressed_bytes == 6 * 1024**3
    assert mod.DEFAULT_LAMP_BULLETIN_MAX_BYTES < mod.DEFAULT_LAMP_MONTH_LIMITS.max_compressed_bytes
    assert (
        mod.DEFAULT_LAMP_MONTH_LIMITS.max_compressed_bytes
        < mod.DEFAULT_LAMP_YEAR_LIMITS.max_compressed_bytes
    )


@pytest.mark.asyncio
async def test_non_utf8_bulletin_is_a_decode_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, b"KNYC \xff\xfe\n")
    with pytest.raises(DecodeError):
        await _transport().fetch_lamp_bulletin(RUN_DATE, 1)


# ---------------------------------------------------------------------------
# 429 and Retry-After
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_429_backoff_respects_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    responses: Iterator[httpx.Response] = iter(
        [httpx.Response(429, headers={"Retry-After": "7"}), _ok(b"KNYC ok\n")]
    )
    http = install_mock_http(monkeypatch, lambda _r: next(responses))
    result = await _transport(async_sleep=fake_sleep).fetch_lamp_bulletin(RUN_DATE, 1)
    assert slept == [7.0]
    assert len(http.requests) == 2
    assert result.body == "KNYC ok\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "retry_after", [None, "soon", "-5", "Wed, 21 Oct 2026 07:28:00 GMT", "9999"]
)
async def test_429_without_a_usable_retry_after_is_raised_not_guessed(
    monkeypatch: pytest.MonkeyPatch, retry_after: str | None
) -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    headers = {} if retry_after is None else {"Retry-After": retry_after}
    http = install_mock_http(monkeypatch, lambda _r: httpx.Response(429, headers=headers))
    with pytest.raises(RateLimitedError) as caught:
        await _transport(async_sleep=fake_sleep).fetch_lamp_bulletin(RUN_DATE, 1)
    assert caught.value.retry_after == retry_after
    assert slept == []
    assert len(http.requests) == 1


@pytest.mark.asyncio
async def test_429_retries_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    http = install_mock_http(
        monkeypatch, lambda _r: httpx.Response(429, headers={"Retry-After": "1"})
    )
    with pytest.raises(RateLimitedError):
        await _transport(async_sleep=fake_sleep, max_429_retries=2).fetch_lamp_bulletin(RUN_DATE, 1)
    assert len(http.requests) == 3
    assert slept == [1.0, 1.0]


def test_archive_429_honours_retry_after_with_the_sync_sleeper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    responses: Iterator[httpx.Response] = iter(
        [httpx.Response(429, headers={"Retry-After": "3"}), _ok(_gz(_bulletin_text()))]
    )
    install_mock_http(monkeypatch, lambda _r: next(responses))
    with _transport(sleep=slept.append).fetch_lamp_archive_month("202609", "0130") as stream:
        assert list(stream.lines())
    assert slept == [3.0]


# ---------------------------------------------------------------------------
# Monthly archive (streamed gzip line reader)
# ---------------------------------------------------------------------------


def test_month_archive_streams_lines_with_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    text = _bulletin_text()
    compressed = _gz(text)
    http = _serve(monkeypatch, compressed)
    with _transport().fetch_lamp_archive_month("202609", "0130") as stream:
        assert str(http.requests[0].url) == MDL_MONTH_URL
        assert stream.source_host == LAMP_MDL_HOST
        assert stream.last_modified == LAST_MODIFIED
        assert "".join(stream.lines()) == text
        assert stream.sha256 == hashlib.sha256(compressed).hexdigest()


def test_month_sha256_is_unavailable_until_the_stream_is_consumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, _gz(_bulletin_text()))
    with (
        _transport().fetch_lamp_archive_month("202609", "0130") as stream,
        pytest.raises(RuntimeError),
    ):
        _ = stream.sha256


def test_month_stream_filters_stations(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _gz(_bulletin_text()))
    with _transport().fetch_lamp_archive_month("202609", "0130") as stream:
        kept = "".join(stream.lines(stations=frozenset({"KMDW", "KNYC"})))
    assert kept == _block("KNYC") + _block("KMDW")


def test_month_handles_concatenated_gzip_members(monkeypatch: pytest.MonkeyPatch) -> None:
    text = _block("KNYC") + _block("KMIA")
    _serve(monkeypatch, _gz(_block("KNYC")) + _gz(_block("KMIA")))
    with _transport().fetch_lamp_archive_month("202609", "0130") as stream:
        assert "".join(stream.lines()) == text


@pytest.mark.parametrize(
    ("yyyymm", "hhmm", "error"),
    [
        ("2026-9", "0130", ValueError),
        ("202613", "0130", ValueError),
        ("202600", "0130", ValueError),
        ("200501", "0130", ValueError),
        ("202609", "0107", ValueError),
        ("202609", "2400", ValueError),
        ("202609", "130", ValueError),
        (202609, "0130", TypeError),
        ("202609", 130, TypeError),
    ],
)
def test_month_arguments_are_closed(
    monkeypatch: pytest.MonkeyPatch, yyyymm: Any, hhmm: Any, error: type[Exception]
) -> None:
    http = _serve(monkeypatch, b"x")
    with pytest.raises(error), _transport().fetch_lamp_archive_month(yyyymm, hhmm):
        pass
    assert http.requests == []


def test_month_refuses_content_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _gz("x\n"), **{"Content-Encoding": "gzip"})
    with (
        pytest.raises(ContentEncodingError),
        _transport().fetch_lamp_archive_month("202609", "0130"),
    ):
        pass


def test_month_truncated_gzip_is_a_decode_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _gz(_bulletin_text())[:-12])
    with (
        pytest.raises(DecodeError),
        _transport().fetch_lamp_archive_month("202609", "0130") as stream,
    ):
        list(stream.lines())


def test_month_non_utf8_payload_is_a_decode_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, gzip.compress(b"KNYC \xff\xfe\n"))
    with (
        pytest.raises(DecodeError),
        _transport().fetch_lamp_archive_month("202609", "0130") as stream,
    ):
        list(stream.lines())


def test_month_refuses_oversize_compressed_download(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _gz(_bulletin_text() * 50))
    limits = LampArchiveLimits(
        max_compressed_bytes=64,
        max_members=1,
        max_member_bytes=1024,
        max_member_decompressed_bytes=10**9,
        max_total_decompressed_bytes=10**9,
    )
    with (
        pytest.raises(OversizeBodyError),
        _transport(month_limits=limits).fetch_lamp_archive_month("202609", "0130") as stream,
    ):
        list(stream.lines())


def test_month_counts_decompressed_bytes_and_refuses_bomb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bomb = gzip.compress(b"A" * (8 * 1024 * 1024))
    assert len(bomb) < 64 * 1024
    _serve(monkeypatch, bomb)
    limits = LampArchiveLimits(
        max_compressed_bytes=10**6,
        max_members=1,
        max_member_bytes=10**6,
        max_member_decompressed_bytes=256 * 1024,
        max_total_decompressed_bytes=256 * 1024,
    )
    seen = 0
    with (
        pytest.raises(OversizeBodyError),
        _transport(month_limits=limits).fetch_lamp_archive_month("202609", "0130") as stream,
    ):
        for line in stream.lines():
            seen += len(line)
    assert seen <= 256 * 1024  # tripped before more than the cap was handed out


# ---------------------------------------------------------------------------
# Yearly tar (H2)
# ---------------------------------------------------------------------------


def _year_members(stream: Any, stations: frozenset[str] | None = None) -> dict[str, str]:
    return {member.name: "".join(member.lines(stations=stations)) for member in stream.members()}


def test_year_tar_streams_members_and_gunzips_each(monkeypatch: pytest.MonkeyPatch) -> None:
    jan = _block("KNYC") + _block("KMIA")
    feb = _block("KSFO")
    archive = _tar(
        [("lmp_lavtxt.202501.0000z.gz", _gz(jan)), ("lmp_lavtxt.202502.0000z.gz", _gz(feb))]
    )
    http = _serve(monkeypatch, archive)
    with _transport().fetch_lamp_archive_year(2025) as stream:
        assert str(http.requests[0].url) == MDL_YEAR_URL
        assert stream.source_host == LAMP_MDL_HOST
        assert _year_members(stream) == {
            "lmp_lavtxt.202501.0000z.gz": jan,
            "lmp_lavtxt.202502.0000z.gz": feb,
        }
        assert stream.sha256 == hashlib.sha256(archive).hexdigest()


@pytest.mark.parametrize("name", ["../evil.gz", "a/../../evil.gz", "x/../y.gz"])
def test_tar_rejects_dotdot_member(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    _serve(monkeypatch, _tar([(name, _gz("x\n"))]))
    with (
        pytest.raises(LampArchiveIntegrityError),
        _transport().fetch_lamp_archive_year(2025) as stream,
    ):
        _year_members(stream)


@pytest.mark.parametrize("name", ["/etc/evil.gz", "/lmp_lavtxt.202501.0000z.gz"])
def test_tar_rejects_absolute_member(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    _serve(monkeypatch, _tar([(name, _gz("x\n"))]))
    with (
        pytest.raises(LampArchiveIntegrityError),
        _transport().fetch_lamp_archive_year(2025) as stream,
    ):
        _year_members(stream)


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE]
)
def test_tar_rejects_symlink_hardlink_and_other_non_regular_members(
    monkeypatch: pytest.MonkeyPatch, kind: bytes
) -> None:
    info = tarfile.TarInfo("lmp_lavtxt.202501.0000z.gz")
    info.type = kind
    info.linkname = "/etc/passwd" if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
    _serve(monkeypatch, _tar([], extra=[info]))
    with (
        pytest.raises(LampArchiveIntegrityError),
        _transport().fetch_lamp_archive_year(2025) as stream,
    ):
        _year_members(stream)


def test_tar_rejects_oversize_member_and_total_and_member_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    members = [
        (f"lmp_lavtxt.2025{m:02d}.0000z.gz", _gz(_block("KNYC", rows=40))) for m in (1, 2, 3)
    ]
    archive = _tar(members)
    one_member = len(members[0][1])
    base = {
        "max_compressed_bytes": 10**9,
        "max_members": 10,
        "max_member_bytes": 10**9,
        "max_member_decompressed_bytes": 10**9,
        "max_total_decompressed_bytes": 10**9,
    }
    decompressed = len(_block("KNYC", rows=40).encode())
    cases = {
        "member_count": {"max_members": 2},
        "member_size": {"max_member_bytes": one_member - 1},
        "member_decompressed": {"max_member_decompressed_bytes": decompressed - 1},
        "total_decompressed": {"max_total_decompressed_bytes": decompressed * 2 + 1},
    }
    for override in cases.values():
        _serve(monkeypatch, archive)
        limits = LampArchiveLimits(**{**base, **override})
        with (
            pytest.raises(OversizeBodyError),
            _transport(year_limits=limits).fetch_lamp_archive_year(2025) as stream,
        ):
            _year_members(stream)


def test_tar_refuses_oversize_compressed_download(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _tar([("lmp_lavtxt.202501.0000z.gz", _gz(_bulletin_text() * 20))]))
    limits = LampArchiveLimits(
        max_compressed_bytes=2048,
        max_members=10,
        max_member_bytes=10**9,
        max_member_decompressed_bytes=10**9,
        max_total_decompressed_bytes=10**9,
    )
    with (
        pytest.raises(OversizeBodyError),
        _transport(year_limits=limits).fetch_lamp_archive_year(2025) as stream,
    ):
        _year_members(stream)


def test_tar_counts_decompressed_bytes_while_streaming_and_refuses_bomb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bomb = gzip.compress(b"A" * (8 * 1024 * 1024))
    _serve(monkeypatch, _tar([("lmp_lavtxt.202501.0000z.gz", bomb)]))
    limits = LampArchiveLimits(
        max_compressed_bytes=10**6,
        max_members=10,
        max_member_bytes=10**6,
        max_member_decompressed_bytes=10**9,
        max_total_decompressed_bytes=128 * 1024,
    )
    handed_out = 0
    with (
        pytest.raises(OversizeBodyError),
        _transport(year_limits=limits).fetch_lamp_archive_year(2025) as stream,
    ):
        for member in stream.members():
            for line in member.lines():
                handed_out += len(line)
    assert handed_out <= 128 * 1024


def test_tar_stream_filters_stations_without_buffering_whole_tar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = random.Random(7)
    payloads = [
        (
            f"lmp_lavtxt.2025{m:02d}.0000z.gz",
            _gz(
                "".join(
                    _block("KNYC", rows=4, rng=rng) + _block("KJFK", rows=4, rng=rng)
                    for _ in range(80)
                )
            ),
        )
        for m in range(1, 13)
    ]
    archive = _tar(payloads)
    pulled = 0
    chunk = 32 * 1024

    def body() -> Iterator[bytes]:
        nonlocal pulled
        for start in range(0, len(archive), chunk):
            pulled += min(chunk, len(archive) - start)
            yield archive[start : start + chunk]

    install_mock_http(
        monkeypatch,
        lambda _r: httpx.Response(200, content=body(), headers={"Last-Modified": LAST_MODIFIED}),
    )
    with _transport().fetch_lamp_archive_year(2025) as stream:
        members = stream.members()
        first = next(members)
        first_line = next(iter(first.lines(stations=frozenset({"KNYC"}))))
        assert first_line.startswith("KNYC")
        assert pulled < len(archive) / 2, "the whole tar was buffered"
        kept = "".join(first.lines(stations=frozenset({"KNYC"})))
    assert "KJFK" not in kept


def test_output_path_never_derived_from_member_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    odd = "lmp_lavtxt.é中 x;rm -rf y.gz"
    _serve(monkeypatch, _tar([(odd, _gz(_block("KNYC")))]))
    monkeypatch.chdir(tmp_path)
    with _transport().fetch_lamp_archive_year(2025) as stream:
        assert _year_members(stream) == {odd: _block("KNYC")}
    assert list(tmp_path.iterdir()) == []


def test_module_never_extracts_or_writes_files() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attributes & {"extract", "extractall", "write_bytes", "write_text", "mkdir"}
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "open" not in calls
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert 'mode="r|"' in source
    assert '"r:' not in source


def test_corrupt_tar_is_an_integrity_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, b"this is not a tar archive" * 100)
    with (
        pytest.raises(LampArchiveIntegrityError),
        _transport().fetch_lamp_archive_year(2025) as stream,
    ):
        _year_members(stream)


@pytest.mark.parametrize("year", [2005, 2100, "2025", True, None])
def test_year_argument_is_closed(monkeypatch: pytest.MonkeyPatch, year: Any) -> None:
    http = _serve(monkeypatch, b"x")
    with pytest.raises((TypeError, ValueError)), _transport().fetch_lamp_archive_year(year):
        pass
    assert http.requests == []


# ---------------------------------------------------------------------------
# LOW: user agent and redaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_agent_contains_project_alias_not_operator_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = _serve(monkeypatch, b"x\n")
    await build_mdl_lamp_transport(_clock, check_proxy_env=False).fetch_lamp_bulletin(RUN_DATE, 1)
    sent = http.requests[0].headers["user-agent"]
    assert "breezy" in sent.lower()
    assert "@" not in sent
    assert sent == mod.LAMP_DEFAULT_USER_AGENT


def test_a_user_agent_carrying_an_email_is_refused() -> None:
    with pytest.raises(UserAgentConfigurationError):
        _transport(user_agent="breezy (jon@gopoint.com)")


def test_the_env_user_agent_is_not_consulted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BREEZY_USER_AGENT", "someone@example.invalid")
    assert _transport()._user_agent == mod.LAMP_DEFAULT_USER_AGENT


def test_logged_urls_are_redacted() -> None:
    secret = "SECRETVALUE123"
    url = f"https://user:{secret}@evil.example/x?apikey={secret}&k=v"
    with pytest.raises(DisallowedHostError) as caught:
        _transport()._validate_url(url)
    assert secret not in str(caught.value)
    with pytest.raises(DisallowedHostError) as caught_path:
        _transport()._validate_url(f"https://{LAMP_NOMADS_HOST}/other/x?token={secret}")
    assert secret not in str(caught_path.value)


@pytest.mark.asyncio
async def test_error_messages_from_fetches_carry_no_query_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_mock_http(monkeypatch, lambda _r: httpx.Response(503, content=b"x"))
    with pytest.raises(ServerError) as caught:
        await _transport().fetch_lamp_bulletin(RUN_DATE, 1)
    assert "?" not in str(caught.value)


# ---------------------------------------------------------------------------
# R18: new TransportError subclasses are routed
# ---------------------------------------------------------------------------


def test_mdl_transport_error_has_route_constructor_and_contract_test_import() -> None:
    new_errors = {
        cls
        for cls in vars(mod).values()
        if isinstance(cls, type)
        and issubclass(cls, TransportError)
        and cls.__module__ == mod.__name__
    }
    assert {LampNotPublishedError, LampArchiveIntegrityError} <= new_errors
    contract_source = (
        REPO_ROOT / "tests/contract/test_transport_error_routing_contract.py"
    ).read_text(encoding="utf-8")
    for cls in new_errors:
        assert cls in TRANSPORT_ERROR_ROUTES, f"{cls.__name__} has no route"
        assert f"    {cls.__name__}," in contract_source, f"{cls.__name__} not imported"
        assert f"{cls.__name__}: lambda" in contract_source, f"{cls.__name__} has no recipe"
