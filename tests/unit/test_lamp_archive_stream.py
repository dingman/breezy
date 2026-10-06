"""Hardening of the streamed LAMP archive handlers (review round 1)."""

from __future__ import annotations

import ast
import gzip
import io
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from breezy.ingest import lamp_archive_stream as stream_mod
from breezy.ingest import mdl_lamp_transport as mdl_mod
from breezy.ingest.http import (
    DisallowedHostError,
    OversizeBodyError,
    TransportError,
    TransportTimeoutError,
)
from breezy.ingest.mdl_lamp_transport import (
    LAMP_MDL_HOST,
    LAMP_NOMADS_HOST,
    LampArchiveIntegrityError,
    LampArchiveLimits,
    MdlLampTransport,
)
from tests.support.mock_http import install_mock_http

REPO_ROOT = Path(__file__).resolve().parents[2]


def _clock() -> int:
    return 1_789_000_000_000_000_000


def _transport(**kwargs: Any) -> MdlLampTransport:
    return MdlLampTransport(clock=_clock, check_proxy_env=False, **kwargs)


def _block(station: str, rows: int = 2) -> str:
    return f"{station}   GFS LAMP GUIDANCE  10/06/2026  0130 UTC\n" + " TMP 59 57\n" * rows


def _gz(text: str) -> bytes:
    return gzip.compress(text.encode())


def _tar(
    members: list[tuple[str, bytes]],
    extra: list[tarfile.TarInfo] | None = None,
    fmt: int = tarfile.GNU_FORMAT,
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=fmt) as archive:
        for name, payload in members:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        for info in extra or []:
            archive.addfile(info, io.BytesIO(b"\0" * info.size) if info.size else None)
    return buffer.getvalue()


def _serve(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    install_mock_http(monkeypatch, lambda _r: httpx.Response(200, content=body))


def _limits(**override: int) -> LampArchiveLimits:
    base = {
        "max_compressed_bytes": 10**9,
        "max_members": 10,
        "max_member_bytes": 10**9,
        "max_member_decompressed_bytes": 10**9,
        "max_total_decompressed_bytes": 10**9,
    }
    return LampArchiveLimits(**{**base, **override})


# -- blocker: sha256 is gated on a completion flag, not on network EOF --------------


def test_month_sha256_unavailable_after_last_chunk_pulled_but_before_generator_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, _gz(_block("KNYC") + _block("KMIA")))
    with _transport().fetch_lamp_archive_month("202609", "0130") as stream:
        lines = stream.lines()
        next(lines)  # a small body: every network chunk is already pulled
        with pytest.raises(RuntimeError):
            _ = stream.sha256
        list(lines)
        assert len(stream.sha256) == 64


def test_month_sha256_unavailable_after_truncated_gzip(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _gz(_block("KNYC") * 50)[:-12])
    with (
        _transport().fetch_lamp_archive_month("202609", "0130") as stream,
        pytest.raises(TransportError),
    ):
        list(stream.lines())
        with pytest.raises(RuntimeError):
            _ = stream.sha256


def test_month_sha256_unavailable_after_utf8_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, gzip.compress(b"KNYC \xff\xfe\n"))
    with (
        _transport().fetch_lamp_archive_month("202609", "0130") as stream,
        pytest.raises(TransportError),
    ):
        list(stream.lines())
        with pytest.raises(RuntimeError):
            _ = stream.sha256


def test_year_sha256_unavailable_before_members_finishes_and_after_truncated_tar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _tar([("lmp_lavtxt.202501.0000z.gz", _gz(_block("KNYC") * 400))])
    _serve(monkeypatch, archive)
    with _transport().fetch_lamp_archive_year(2025) as stream:
        members = stream.members()
        next(members)
        with pytest.raises(RuntimeError):
            _ = stream.sha256
    _serve(monkeypatch, archive[:600])
    with _transport().fetch_lamp_archive_year(2025) as stream:
        with pytest.raises(LampArchiveIntegrityError):
            for member in stream.members():
                list(member.lines())
        with pytest.raises(RuntimeError):
            _ = stream.sha256


# -- single-use streams -------------------------------------------------------------


def test_month_lines_is_single_use(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _gz(_block("KNYC")))
    with _transport().fetch_lamp_archive_month("202609", "0130") as stream:
        list(stream.lines())
        with pytest.raises(RuntimeError):
            stream.lines()


def test_year_members_is_single_use_and_stale_member_lines_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = ["lmp_lavtxt.202501.0000z.gz", "lmp_lavtxt.202502.0000z.gz"]
    _serve(monkeypatch, _tar([(n, _gz(_block("KNYC"))) for n in names]))
    with _transport().fetch_lamp_archive_year(2025) as stream:
        members = stream.members()
        first = next(members)
        second = next(members)
        with pytest.raises(RuntimeError):
            first.lines()  # the tar has advanced past it
        assert "".join(second.lines()) == _block("KNYC")
        with pytest.raises(RuntimeError):
            second.lines()  # already consumed
        with pytest.raises(RuntimeError):
            stream.members()


# -- line length cap ------------------------------------------------------------------


def test_month_refuses_a_line_over_the_cap_without_a_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, gzip.compress(b"A" * 200_000))
    with (
        _transport().fetch_lamp_archive_month("202609", "0130") as stream,
        pytest.raises(OversizeBodyError),
    ):
        list(stream.lines())


def test_tar_member_refuses_a_line_over_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    long_line = ("B" * 200_000) + "\n"
    _serve(monkeypatch, _tar([("lmp_lavtxt.202501.0000z.gz", _gz(long_line))]))
    with _transport().fetch_lamp_archive_year(2025) as stream, pytest.raises(OversizeBodyError):
        for member in stream.members():
            list(member.lines())


def test_a_line_exactly_at_the_cap_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    line = "C" * (stream_mod.DEFAULT_MAX_LINE_CHARS - 1) + "\n"
    _serve(monkeypatch, _gz(line))
    with _transport().fetch_lamp_archive_month("202609", "0130") as stream:
        assert "".join(stream.lines()) == line


# -- tar member guards -------------------------------------------------------------------


def test_tar_rejects_gnu_sparse_member(monkeypatch: pytest.MonkeyPatch) -> None:
    info = tarfile.TarInfo("lmp_lavtxt.202501.0000z.gz")
    info.type = tarfile.GNUTYPE_SPARSE
    info.size = 0
    _serve(monkeypatch, _tar([], extra=[info]))
    with (
        _transport().fetch_lamp_archive_year(2025) as stream,
        pytest.raises(LampArchiveIntegrityError),
    ):
        list(stream.members())


def test_tar_rejects_overlong_member_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _tar([("a" * 300 + ".gz", _gz(_block("KNYC")))]))
    with (
        _transport().fetch_lamp_archive_year(2025) as stream,
        pytest.raises(LampArchiveIntegrityError),
    ):
        list(stream.members())


def test_tar_rejects_oversize_pax_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    info = tarfile.TarInfo("lmp_lavtxt.202501.0000z.gz")
    payload = _gz(_block("KNYC"))
    info.size = len(payload)
    info.pax_headers = {"comment": "x" * 70_000}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        archive.addfile(info, io.BytesIO(payload))
    _serve(monkeypatch, buffer.getvalue())
    with (
        _transport().fetch_lamp_archive_year(2025) as stream,
        pytest.raises(LampArchiveIntegrityError),
    ):
        list(stream.members())


# -- Retry-After parsing, URL gate -----------------------------------------------------


@pytest.mark.parametrize("value", ["٣", "١٢", "00012", "12345", " 7 x", "7.5", ""])
def test_retry_after_requires_short_ascii_digits(value: str) -> None:
    assert mdl_mod._retry_delay(value) is None


def test_retry_after_accepts_short_ascii_digits() -> None:
    assert mdl_mod._retry_delay("7") == 7.0
    assert mdl_mod._retry_delay(" 120 ") == 120.0


@pytest.mark.parametrize(
    "url",
    [
        f"https://{LAMP_NOMADS_HOST}/pub/data/nccf/com/lmp/prod/lmp.20261006/x?a=b",
        f"https://{LAMP_MDL_HOST}/lamp/Data/archives/lmp_lavtxt.2025.tar?",
        f"https://{LAMP_MDL_HOST}/lamp/Data/archives/lmp_lavtxt.2025.tar#frag",
    ],
)
def test_lamp_urls_with_a_query_or_fragment_are_refused(url: str) -> None:
    with pytest.raises(DisallowedHostError):
        _transport()._validate_url(url)


# -- wall-clock deadline ---------------------------------------------------------------


def test_default_deadlines_are_pinned() -> None:
    assert mdl_mod.DEFAULT_LAMP_YEAR_LIMITS.max_wall_seconds == 2 * 3600
    assert mdl_mod.DEFAULT_LAMP_MONTH_LIMITS.max_wall_seconds == 30 * 60


def test_stream_deadline_is_checked_per_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter(range(0, 10_000, 10))

    archive = _tar([("lmp_lavtxt.202501.0000z.gz", b"z" * 400_000)])

    def body() -> Iterator[bytes]:
        for start in range(0, len(archive), 64 * 1024):
            yield archive[start : start + 64 * 1024]

    install_mock_http(monkeypatch, lambda _r: httpx.Response(200, content=body()))
    transport = _transport(
        year_limits=_limits(max_wall_seconds=25), monotonic=lambda: float(next(ticks))
    )
    with transport.fetch_lamp_archive_year(2025) as stream, pytest.raises(TransportTimeoutError):
        list(stream.members())


# -- module split ----------------------------------------------------------------------


def test_stream_module_defines_no_transport_error_and_never_extracts() -> None:
    path = REPO_ROOT / "src/breezy/ingest/lamp_archive_stream.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            assert not any(
                getattr(base, "id", "") in {"TransportError", "ValueError"}
                or getattr(base, "attr", "") == "TransportError"
                for base in node.bases
            ), node.name
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"extract", "extractall"}
    assert 'mode="r|"' in path.read_text(encoding="utf-8")
    assert not any(
        isinstance(v, type)
        and issubclass(v, TransportError)
        and v.__module__ == stream_mod.__name__
        for v in vars(stream_mod).values()
    )
    assert (REPO_ROOT / "src/breezy/ingest/mdl_lamp_transport.py").read_text().count("\n") < 450


def test_mock_http_clients_are_real_client_subclasses(monkeypatch: pytest.MonkeyPatch) -> None:
    install_mock_http(monkeypatch, lambda _r: httpx.Response(200))
    assert isinstance(httpx.AsyncClient(), httpx.AsyncClient)
    assert isinstance(httpx.Client(), httpx.Client)
