"""F13-C1: the GFS LAMP transport -- NOMADS hourly bulletins, MDL archives.

Two exact hosts, each bound to ONE path prefix (A0-R3, A0-R4, M8):

* ``nomads.ncep.noaa.gov`` under ``/pub/data/nccf/com/lmp/prod/`` -- the live
  hourly HH30 bulletin (``lavtxt.ascii`` and ``lavtxt_ext.ascii``). NOMADS
  fails over HTTP/2 (malformed content-length), so every client built here is
  HTTP/1.1 with ``http2=False`` stated explicitly.
* ``lamp.mdl.nws.noaa.gov`` under ``/lamp/Data/archives/`` -- the monthly
  ``lmp_lavtxt.YYYYMM.HHMMz.gz`` files (concatenated text, gzip) and the
  yearly ``lmp_lavtxt.YYYY.tar`` bundles of those monthly files.

The hourly bulletin goes through the inherited hardened ``_fetch`` (async,
buffered under a small cap, sha256 over the raw bytes). The archives are
large (a year is ~3.8 GB; a month is ~11 MB gzip, ~119 MB text), so they are
STREAMED and exposed as SYNCHRONOUS context managers: the stdlib ``tarfile``
stream reader is blocking, and the archive path is an offline backfill, never
the live collector loop. The H2 stream handling (tar ``r|`` only, plain
regular members, every cap, single-use streams, ``sha256`` only after a fully
validated pass) lives in :mod:`breezy.ingest.lamp_archive_stream`.

This module defines the only new ``TransportError`` subclasses of F13-C1
(R18); both are registered in ``breezy.ingest.routing`` and the routing
contract test. The stream module is handed ``LampArchiveIntegrityError`` as
its refusal factory, so it defines none of its own.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final
from urllib.parse import urlsplit

import httpx

from breezy.ingest.http import (
    DisallowedHostError,
    FetchResult,
    HttpTransport,
    RateLimitedError,
    TransportError,
    TransportTimeoutError,
    UserAgentConfigurationError,
    assert_clean_proxy_env,
    redact_url,
)
from breezy.ingest.lamp_archive_stream import (
    LampArchiveLimits,
    LampMonthStream,
    LampTarMember,
    LampYearStream,
    open_month_stream,
    open_year_stream,
)

__all__ = [
    "DEFAULT_LAMP_BULLETIN_MAX_BYTES",
    "DEFAULT_LAMP_MONTH_LIMITS",
    "DEFAULT_LAMP_YEAR_LIMITS",
    "LAMP_ALLOWED_HOSTS",
    "LAMP_DEFAULT_USER_AGENT",
    "LAMP_HOST_PATH_PREFIXES",
    "LAMP_MDL_HOST",
    "LAMP_NOMADS_HOST",
    "LampArchiveIntegrityError",
    "LampArchiveLimits",
    "LampBulletinResult",
    "LampMonthStream",
    "LampNotPublishedError",
    "LampTarMember",
    "LampYearStream",
    "MdlLampTransport",
    "build_mdl_lamp_transport",
]

LAMP_NOMADS_HOST: Final[str] = "nomads.ncep.noaa.gov"
LAMP_MDL_HOST: Final[str] = "lamp.mdl.nws.noaa.gov"
LAMP_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset({LAMP_NOMADS_HOST, LAMP_MDL_HOST})

#: M8: each host may be asked for ONE path prefix and nothing else.
LAMP_HOST_PATH_PREFIXES: Final[MappingProxyType[str, str]] = MappingProxyType(
    {
        LAMP_NOMADS_HOST: "/pub/data/nccf/com/lmp/prod/",
        LAMP_MDL_HOST: "/lamp/Data/archives/",
    }
)

#: A project alias, never an operator mailbox (LOW). The env var is not read.
LAMP_DEFAULT_USER_AGENT: Final[str] = "breezy-us-source-ingest/1 (project: breezy)"

#: Measured 4.3 MB for the HH30 lavtxt.ascii (A0); ~3.7x headroom.
DEFAULT_LAMP_BULLETIN_MAX_BYTES: Final[int] = 16 * 1024 * 1024

_MIB: Final[int] = 1024 * 1024
_GIB: Final[int] = 1024 * _MIB
_CHUNK_SIZE: Final[int] = 64 * 1024
_MAX_RETRY_AFTER_SECONDS: Final[float] = 120.0
_MAX_RETRY_AFTER_DIGITS: Final[int] = 4
_FIRST_ARCHIVE_YEAR: Final[int] = 2006
_LAST_ARCHIVE_YEAR: Final[int] = 2099
_YYYYMM_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A(?P<year>\d{4})(?P<month>\d{2})\Z")
_HHMM_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A(?P<hour>\d{2})(?P<minute>\d{2})\Z")
_VALID_MINUTES: Final[frozenset[int]] = frozenset({0, 15, 30, 45})


class LampNotPublishedError(TransportError):
    """The requested LAMP file is not (yet) there: HTTP 404.

    Routine while polling an hour that has not been published; the collector
    uses it to record an availability miss. It is never data.
    """

    def __init__(self, message: str, *, status_code: int = 404) -> None:
        super().__init__(message)
        self.status_code = status_code


class LampArchiveIntegrityError(TransportError):
    """An archive container is malformed or unsafe (H2).

    Raised for a corrupt tar, a non-regular member (symlink, hardlink,
    directory, device) and a traversal/absolute/NUL/backslash member name. An
    integrity alarm, not a network hiccup.
    """


#: A month: ~11 MB gzip / ~119 MB text measured (A0). One file, no members.
DEFAULT_LAMP_MONTH_LIMITS: Final[LampArchiveLimits] = LampArchiveLimits(
    max_compressed_bytes=64 * _MIB,
    max_members=1,
    max_member_bytes=64 * _MIB,
    max_member_decompressed_bytes=_GIB,
    max_total_decompressed_bytes=_GIB,
    max_wall_seconds=30 * 60,
)

#: A year: ~3.8 GB tar of <=1,152 monthly gz files of ~11 MB / ~119 MB each.
DEFAULT_LAMP_YEAR_LIMITS: Final[LampArchiveLimits] = LampArchiveLimits(
    max_compressed_bytes=6 * _GIB,
    max_members=1_500,
    max_member_bytes=64 * _MIB,
    max_member_decompressed_bytes=_GIB,
    max_total_decompressed_bytes=192 * _GIB,
    max_wall_seconds=2 * 3600,
)


@dataclass(frozen=True, slots=True)
class LampBulletinResult:
    """One hourly bulletin plus provenance (``sha256`` is over the raw bytes)."""

    body: str
    sha256: str
    source_host: str
    last_modified: str | None
    url: str
    retrieved_at_ns: int


# -- the transport ----------------------------------------------------------------


def _retry_delay(retry_after: str | None) -> float | None:
    """Seconds to wait, or None when the header is absent/unusable (never guessed)."""
    if retry_after is None:
        return None
    text = retry_after.strip()
    if not (text.isascii() and text.isdecimal() and len(text) <= _MAX_RETRY_AFTER_DIGITS):
        return None
    delay = float(int(text))
    return delay if delay <= _MAX_RETRY_AFTER_SECONDS else None


class MdlLampTransport(HttpTransport):
    """GET-only, exact-host, prefix-bound LAMP client. No caller-supplied URL."""

    def __init__(
        self,
        *,
        clock: Callable[[], int],
        user_agent: str | None = None,
        max_bulletin_bytes: int = DEFAULT_LAMP_BULLETIN_MAX_BYTES,
        month_limits: LampArchiveLimits = DEFAULT_LAMP_MONTH_LIMITS,
        year_limits: LampArchiveLimits = DEFAULT_LAMP_YEAR_LIMITS,
        max_429_retries: int = 2,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        async_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        check_proxy_env: bool = True,
        approved_proxy_env_vars: frozenset[str] | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 60.0,
    ) -> None:
        agent = LAMP_DEFAULT_USER_AGENT if user_agent is None else user_agent
        if "@" in agent:
            raise UserAgentConfigurationError(
                "the LAMP User-Agent must carry a project alias, not an email address."
            )
        super().__init__(
            allowed_hosts=LAMP_ALLOWED_HOSTS,
            clock=clock,
            base_url=f"https://{LAMP_NOMADS_HOST}",
            max_body_bytes=max_bulletin_bytes,
            chunk_size=_CHUNK_SIZE,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            user_agent=agent,
            accept="text/plain",
            check_proxy_env=check_proxy_env,
            approved_proxy_env_vars=approved_proxy_env_vars,
        )
        self._month_limits = month_limits
        self._year_limits = year_limits
        self._max_429_retries = max_429_retries
        self._monotonic = monotonic
        self._sleep = sleep
        self._async_sleep = async_sleep

    # -- URL gate ---------------------------------------------------------------

    def _validate_url(self, url: str) -> None:
        super()._validate_url(url)
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        prefix = LAMP_HOST_PATH_PREFIXES[host]
        path = parts.path
        segments = path.split("/")[1:]
        suspicious = (
            bool(parts.query or parts.fragment or "?" in url or "#" in url)
            or not path.startswith(prefix)
            or "%" in path
            or "" in segments[:-1]
            or ".." in segments
            or "." in segments
        )
        if suspicious:
            raise DisallowedHostError(
                f"Path is not under the {prefix!r} prefix bound to host "
                f"{host!r} (url={redact_url(url)})"
            )

    # -- client construction ------------------------------------------------------

    def _client_kwargs(self) -> dict[str, object]:
        return {
            "verify": self._ssl_context,
            "http2": False,  # NOMADS fails over HTTP/2 (A0); never negotiate it
            "follow_redirects": False,
            "trust_env": False,
            "timeout": self._timeouts.as_httpx_timeout(),
            "headers": {
                "User-Agent": self._user_agent,
                "Accept": self._accept,
                "Accept-Encoding": "identity",
            },
        }

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(**self._client_kwargs())  # type: ignore[arg-type]

    def _build_sync_client(self) -> httpx.Client:
        return httpx.Client(**self._client_kwargs())  # type: ignore[arg-type]

    # -- status handling ----------------------------------------------------------

    def _raise_for_status(self, response: httpx.Response, *, allow_not_modified: bool) -> None:
        super()._raise_for_status(response, allow_not_modified=allow_not_modified)
        status = response.status_code
        url = redact_url(str(response.url))
        if status == 404:
            raise LampNotPublishedError(f"404 Not Found for {url}.", status_code=status)
        if status != 200:
            raise TransportError(f"Unexpected status {status} from {url}.")

    # -- hourly bulletin ------------------------------------------------------------

    async def _fetch(
        self,
        url: str,
        *,
        if_none_match: str | None,
        if_modified_since: str | None,
        allow_not_modified: bool,
    ) -> FetchResult:
        attempts = 0
        while True:
            try:
                return await super()._fetch(
                    url,
                    if_none_match=if_none_match,
                    if_modified_since=if_modified_since,
                    allow_not_modified=allow_not_modified,
                )
            except RateLimitedError as exc:
                delay = _retry_delay(exc.retry_after)
                if delay is None or attempts >= self._max_429_retries:
                    raise
                attempts += 1
                await self._async_sleep(delay)

    async def fetch_lamp_bulletin(
        self, run_date: dt.date, run_hour: int, *, extended: bool = False
    ) -> LampBulletinResult:
        """The hourly HH30 ``lavtxt.ascii`` (or ``lavtxt_ext.ascii``) bulletin."""
        if not isinstance(run_date, dt.date) or isinstance(run_date, dt.datetime):
            raise TypeError(f"`run_date` must be a `datetime.date`, was {type(run_date).__name__}")
        if isinstance(run_hour, bool) or not isinstance(run_hour, int):
            raise TypeError(f"`run_hour` must be an int, was {type(run_hour).__name__}")
        if not 0 <= run_hour <= 23:
            raise ValueError(f"`run_hour` must be in 0..23, was {run_hour}")
        product = "lavtxt_ext" if extended else "lavtxt"
        url = (
            f"https://{LAMP_NOMADS_HOST}{LAMP_HOST_PATH_PREFIXES[LAMP_NOMADS_HOST]}"
            f"lmp.{run_date:%Y%m%d}/lmp.t{run_hour:02d}30z.{product}.ascii"
        )
        result = await self._fetch(
            url, if_none_match=None, if_modified_since=None, allow_not_modified=False
        )
        assert result.text is not None and result.sha256 is not None  # 200 always has a body
        return LampBulletinResult(
            body=result.text,
            sha256=result.sha256,
            source_host=LAMP_NOMADS_HOST,
            last_modified=result.headers.get("last-modified"),
            url=result.url,
            retrieved_at_ns=result.retrieved_at_ns,
        )

    # -- streamed archives ---------------------------------------------------------

    @contextmanager
    def _open_stream(self, url: str) -> Iterator[httpx.Response]:
        """Open a validated, status-checked streaming GET; honours Retry-After."""
        if self._check_proxy_env:
            assert_clean_proxy_env(self._approved_proxy_env_vars)
        self._validate_url(url)
        with ExitStack() as stack:
            stack.enter_context(_translated_httpx_errors(url))
            attempts = 0
            while True:
                attempt = ExitStack()
                try:
                    client = attempt.enter_context(self._build_sync_client())
                    response = attempt.enter_context(client.stream("GET", url))
                    self._raise_for_status(response, allow_not_modified=False)
                    self._reject_unexpected_content_encoding(response)
                except RateLimitedError as exc:
                    attempt.close()
                    delay = _retry_delay(exc.retry_after)
                    if delay is None or attempts >= self._max_429_retries:
                        raise
                    attempts += 1
                    self._sleep(delay)
                    continue
                except BaseException:
                    attempt.close()
                    raise
                stack.enter_context(attempt)
                break
            yield response

    @contextmanager
    def fetch_lamp_archive_month(self, yyyymm: str, hhmm: str) -> Iterator[LampMonthStream]:
        """Stream ``lmp_lavtxt.YYYYMM.HHMMz.gz`` as text lines."""
        match = _YYYYMM_PATTERN.match(_require_str("yyyymm", yyyymm))
        if match is None or not (
            _FIRST_ARCHIVE_YEAR <= int(match["year"]) <= _LAST_ARCHIVE_YEAR
            and 1 <= int(match["month"]) <= 12
        ):
            raise ValueError("`yyyymm` must be YYYYMM with a valid year and month")
        clock = _HHMM_PATTERN.match(_require_str("hhmm", hhmm))
        if clock is None or not (
            int(clock["hour"]) <= 23 and int(clock["minute"]) in _VALID_MINUTES
        ):
            raise ValueError("`hhmm` must be HHMM on a quarter hour")
        url = (
            f"https://{LAMP_MDL_HOST}{LAMP_HOST_PATH_PREFIXES[LAMP_MDL_HOST]}"
            f"lmp_lavtxt.{yyyymm}.{hhmm}z.gz"
        )
        with self._open_stream(url) as response:
            yield open_month_stream(
                _iter_response(response, url),
                limits=self._month_limits,
                monotonic=self._monotonic,
                source_host=LAMP_MDL_HOST,
                last_modified=response.headers.get("last-modified"),
                url=url,
                url_label=redact_url(url),
            )

    @contextmanager
    def fetch_lamp_archive_year(self, yyyy: int) -> Iterator[LampYearStream]:
        """Stream ``lmp_lavtxt.YYYY.tar`` member by member (never extracted)."""
        if isinstance(yyyy, bool) or not isinstance(yyyy, int):
            raise TypeError(f"`yyyy` must be an int, was {type(yyyy).__name__}")
        if not _FIRST_ARCHIVE_YEAR <= yyyy <= _LAST_ARCHIVE_YEAR:
            raise ValueError(f"`yyyy` must be in {_FIRST_ARCHIVE_YEAR}..{_LAST_ARCHIVE_YEAR}")
        url = (
            f"https://{LAMP_MDL_HOST}{LAMP_HOST_PATH_PREFIXES[LAMP_MDL_HOST]}lmp_lavtxt.{yyyy}.tar"
        )
        with self._open_stream(url) as response:
            yield open_year_stream(
                _iter_response(response, url),
                limits=self._year_limits,
                monotonic=self._monotonic,
                source_host=LAMP_MDL_HOST,
                last_modified=response.headers.get("last-modified"),
                url=url,
                url_label=redact_url(url),
                refuse=LampArchiveIntegrityError,
            )


def _require_str(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"`{name}` must be a str, was {type(value).__name__}")
    return value


@contextmanager
def _translated_httpx_errors(url: str) -> Iterator[None]:
    try:
        yield
    except httpx.TimeoutException as exc:
        raise TransportTimeoutError(f"Timed out fetching {redact_url(url)}: {exc}") from exc
    except httpx.TransportError as exc:
        raise TransportError(f"Transport failure fetching {redact_url(url)}: {exc}") from exc


def _iter_response(response: httpx.Response, url: str) -> Iterator[bytes]:
    with _translated_httpx_errors(url):
        yield from response.iter_bytes(_CHUNK_SIZE)


def build_mdl_lamp_transport(
    clock: Callable[[], int], *, check_proxy_env: bool = True
) -> MdlLampTransport:
    """The production factory: project-alias User-Agent, default caps."""
    return MdlLampTransport(clock=clock, check_proxy_env=check_proxy_env)
