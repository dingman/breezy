"""SL-3: the NBM NBP quantile bulletin transport -- streaming, station-filtered.

The probabilistic percentile bulletin (``blend_nbptx``) is the LIVE PRIMARY
source for the probabilistic-forecast family (``docs/plans/
FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md`` S1 SL-3). It differs
from the already-shipped :class:`breezy.ingest.nbm_forecast_transport.
NbmForecastTransport` (the deterministic NBS product) in two ways that this
module exists to handle:

1. **Two hosts, not one.** AWS S3 (``noaa-nbm-grib2-pds``) is PRIMARY;
   NOMADS is the FALLBACK, tried only when the primary request fails.
2. **Streaming, station-filtered, not buffer-then-cap.** The full collective
   bulletin measured 34,714,882 bytes for the 2026-09-28 13Z cycle (every
   NBM point station -- about 9,580 station blocks for that cycle). This
   transport keeps memory bounded to the handful of stations actually
   requested (L-53): it never materialises the whole body, only the header
   preamble plus the wanted station blocks, filtered incrementally as bytes
   arrive.

It does **not** parse the forecast values inside a kept block -- that is a
separate slice (SL-2's per-product analogue). It returns the filtered text
verbatim, plus fetch provenance (source host, Last-Modified, fetch time, and
the sha256 of the FULL, UNFILTERED raw stream -- the provenance anchor for a
bit-identical re-download check, even though the filtered text alone cannot
reproduce it).

Station blocks are headed by a line shaped like::

    KLAX    NBM V5.0 NBP GUIDANCE    9/28/2026  1300 UTC

verified live on 2026-09-28/29 against the real bulletin. The station token
is **not always an ICAO call sign** -- the same discovery already recorded in
``nbm_forecast_parse.py``'s ``_STATION_HEADER_RE`` docstring for the sibling
NBS product: the first several thousand blocks in the file (sorted by an
internal NBM station index, not alphabetically) carry a bare numeric site id
(e.g. ``086092``), and only later does the file reach the ICAO-lettered
CONUS airport stations. ``KLAX``/``KMDW``/``KMIA``/``KSFO`` were each
confirmed present in the 2026-09-28 13Z cycle with a plain ICAO header, so
they are safe as the DEFAULT station set here; the header-matching pattern
itself stays general over both token shapes so a differently-tokened station
can be requested without a transport change.

GET-only, HTTPS-only, host-allowlisted, no redirects followed, proxy/TLS
environment asserted clean before the first request: the same hardening
posture as :mod:`breezy.ingest.http`, reimplemented rather than inherited,
because the two-host fallback and the streaming filter are not shapes
:class:`~breezy.ingest.http.HttpTransport` (single host, buffer-then-cap)
supports without forking its own hardened ``_fetch``.
"""

from __future__ import annotations

import codecs
import datetime as dt
import hashlib
import os
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import httpx

from breezy.ingest.http import (
    USER_AGENT_ENV_VAR,
    DecodeError,
    DisallowedHostError,
    ForbiddenError,
    OversizeBodyError,
    RateLimitedError,
    RedirectError,
    ServerError,
    TransportError,
    TransportTimeoutError,
    UserAgentConfigurationError,
    assert_clean_proxy_env,
    redact_url,
)

__all__ = [
    "DEFAULT_NBM_QUANTILE_MAX_BODY_BYTES",
    "DEFAULT_NBM_QUANTILE_STATIONS",
    "MEASURED_MAX_QUANTILE_BULLETIN_BYTES",
    "NBM_QUANTILE_ALLOWED_HOSTS",
    "NOMADS_QUANTILE_HOST",
    "S3_QUANTILE_HOST",
    "BothHostsFailedError",
    "NbmQuantileFetchError",
    "NbmQuantileFetchResult",
    "NbmQuantileTransport",
    "build_nbm_quantile_transport",
]

#: PRIMARY. Unauthenticated, public read-only S3 bucket (verified live
#: 2026-09-28/29): `GET /blend.{YYYYMMDD}/{HH}/text/blend_nbptx.t{HH}z`.
S3_QUANTILE_HOST: Final[str] = "noaa-nbm-grib2-pds.s3.amazonaws.com"
S3_QUANTILE_BASE_URL: Final[str] = f"https://{S3_QUANTILE_HOST}"

#: FALLBACK, same path shape as the sibling NBS transport's NOMADS host.
NOMADS_QUANTILE_HOST: Final[str] = "nomads.ncep.noaa.gov"
NOMADS_QUANTILE_BASE_URL: Final[str] = f"https://{NOMADS_QUANTILE_HOST}"
_NOMADS_BLEND_ROOT: Final[str] = "/pub/data/nccf/com/blend/prod"

NBM_QUANTILE_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset(
    {S3_QUANTILE_HOST, NOMADS_QUANTILE_HOST}
)

#: The default station set (L-40's four traded PM.us stations). Each was
#: confirmed present with a plain ICAO header in the live 2026-09-28 13Z
#: cycle (see the module docstring); the filter itself does not assume ICAO.
DEFAULT_NBM_QUANTILE_STATIONS: Final[frozenset[str]] = frozenset({"KLAX", "KMDW", "KMIA", "KSFO"})

#: Measured live 2026-09-28 13Z cycle: 34,714,882 bytes, ~9,580 station
#: blocks. Pinned as evidence, not a remembered "~30 MB" (mirrors
#: `nbm_forecast_transport.MEASURED_MAX_BULLETIN_BYTES`).
MEASURED_MAX_QUANTILE_BULLETIN_BYTES: Final[int] = 34_714_882

#: 64 MiB is ~1.93x the measured maximum -- room for the bulletin to grow
#: (NBM gains stations over time) without weakening the cap as a control.
#: This still bounds one request's total TRANSFER regardless of how the
#: origin behaves; it is not the transport's memory bound, which is set by
#: streaming the body and keeping only the wanted station blocks (L-53).
DEFAULT_NBM_QUANTILE_MAX_BODY_BYTES: Final[int] = 64 * 1024 * 1024

#: Read in chunks well below one station block's typical size (~3.6 KiB
#: measured), so the filter never has to buffer more than a few chunks to
#: decide whether a line belongs to a wanted block.
_CHUNK_SIZE: Final[int] = 64 * 1024

#: The per-station header line. Mirrors `nbm_forecast_parse._STATION_HEADER_RE`
#: (NBS) with the product literal swapped to NBP; the station token is NOT
#: assumed to be an ICAO call sign (module docstring). Only the token itself
#: is captured -- date/cycle/version parsing is SL-2's job, not this
#: transport's.
_STATION_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ ]?(?P<station>[A-Z0-9]{4,6})\s+NBM\s+V\d+\.\d+\s+NBP\s+GUIDANCE\b"
)


class NbmQuantileFetchError(TransportError):
    """Base error for :class:`NbmQuantileTransport` fetch failures."""


class BothHostsFailedError(NbmQuantileFetchError):
    """Raised when both the AWS S3 primary and the NOMADS fallback fail."""

    def __init__(
        self, message: str, *, primary_error: Exception, fallback_error: Exception
    ) -> None:
        super().__init__(message)
        self.primary_error = primary_error
        self.fallback_error = fallback_error


@dataclass(frozen=True, slots=True)
class NbmQuantileFetchResult:
    """The filtered bulletin text plus fetch provenance.

    ``text`` holds the bulletin's leading preamble (everything before the
    first per-station header line) plus every requested station's block,
    verbatim. ``raw_sha256``/``raw_bytes`` describe the FULL, UNFILTERED
    stream as it arrived on the wire -- the provenance anchor -- even though
    the filtered ``text`` alone cannot reproduce that digest.
    """

    text: str
    source_host: str
    last_modified: str | None
    fetched_at_ns: int
    raw_sha256: str
    raw_bytes: int


def _resolve_user_agent(explicit: str | None) -> str:
    value = os.environ.get(USER_AGENT_ENV_VAR) if explicit is None else explicit
    if value is None or not value.strip():
        raise UserAgentConfigurationError(
            f"{USER_AGENT_ENV_VAR} is required and was not set; configure a "
            "monitored contact User-Agent before fetching the NBP bulletin."
        )
    if value != value.strip():
        raise UserAgentConfigurationError(
            f"{USER_AGENT_ENV_VAR} must not carry leading or trailing whitespace."
        )
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise UserAgentConfigurationError(
            f"{USER_AGENT_ENV_VAR} must not contain control characters."
        )
    return value


def _build_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _consume_lines(pending: str, decoded: str, on_line: Callable[[str], None]) -> str:
    """Feed every COMPLETE line in `pending + decoded` to `on_line`.

    Returns the trailing partial line (if any) to carry into the next chunk.
    Never materialises more than one chunk's worth of extra text.
    """
    combined = pending + decoded
    if not combined:
        return ""
    parts = combined.splitlines(keepends=True)
    if parts and not parts[-1].endswith(("\n", "\r")):
        tail = parts.pop()
    else:
        tail = ""
    for line in parts:
        on_line(line)
    return tail


class _StationBlockFilter:
    """Incrementally keep the bulletin preamble plus wanted station blocks.

    Fed one line at a time, in stream order. Never sees or holds a line from
    an unwanted block -- the discard happens at `feed_line`, not after the
    fact, which is what keeps peak memory bounded on a ~30+ MB stream (L-53).
    """

    __slots__ = ("_keep_current_block", "_kept", "_seen_header", "_stations")

    def __init__(self, stations: frozenset[str]) -> None:
        self._stations = stations
        self._seen_header = False
        self._keep_current_block = True
        self._kept: list[str] = []

    def feed_line(self, line: str) -> None:
        match = _STATION_HEADER_RE.match(line)
        if match is not None:
            self._seen_header = True
            self._keep_current_block = match.group("station") in self._stations
        if not self._seen_header or self._keep_current_block:
            self._kept.append(line)

    def text(self) -> str:
        return "".join(self._kept)


class NbmQuantileTransport:
    """A hardened, GET-only, streaming, station-filtered NBP bulletin client.

    Not a general-purpose HTTP client: only one endpoint exists
    (:meth:`fetch_nbp_bulletin`), it never accepts an HTTP verb, it never
    follows a redirect, and it never reaches a settlement host -- both
    allowed hosts are forecast-source origins only.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], int],
        stations: frozenset[str] = DEFAULT_NBM_QUANTILE_STATIONS,
        allowed_hosts: frozenset[str] = NBM_QUANTILE_ALLOWED_HOSTS,
        s3_base_url: str = S3_QUANTILE_BASE_URL,
        nomads_base_url: str = NOMADS_QUANTILE_BASE_URL,
        max_body_bytes: int = DEFAULT_NBM_QUANTILE_MAX_BODY_BYTES,
        chunk_size: int = _CHUNK_SIZE,
        user_agent: str | None = None,
        check_proxy_env: bool = True,
        approved_proxy_env_vars: frozenset[str] | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 60.0,
    ) -> None:
        # The allowlist is NOT a caller knob, for the same reason
        # `NbmForecastTransport` fixes it: a transport that can be aimed
        # anywhere has its containment in review notes, not in code. Each
        # `*_base_url` stays retargetable so a test can exercise the
        # inherited-shape host check, which then refuses.
        if frozenset(host.lower() for host in allowed_hosts) != NBM_QUANTILE_ALLOWED_HOSTS:
            raise ValueError(
                "NbmQuantileTransport constructs only with NBM_QUANTILE_ALLOWED_HOSTS; "
                f"a quantile transport may not be allowlisted to {sorted(allowed_hosts)}"
            )
        if not stations:
            raise ValueError("`stations` must not be empty")
        self._stations = frozenset(station.upper() for station in stations)
        self._allowed_hosts = NBM_QUANTILE_ALLOWED_HOSTS
        self._s3_base_url = s3_base_url.rstrip("/")
        self._nomads_base_url = nomads_base_url.rstrip("/")
        self._s3_host = S3_QUANTILE_HOST
        self._nomads_host = NOMADS_QUANTILE_HOST
        self._max_body_bytes = max_body_bytes
        self._chunk_size = chunk_size
        self._clock = clock
        self._check_proxy_env = check_proxy_env
        self._approved_proxy_env_vars = approved_proxy_env_vars
        self._user_agent = _resolve_user_agent(user_agent)
        self._timeout = httpx.Timeout(
            connect=connect_timeout, read=read_timeout, write=5.0, pool=5.0
        )
        self._ssl_context = _build_ssl_context()

    # -- URL construction -----------------------------------------------

    def _cycle_path_parts(self, cycle_date: dt.date, cycle_hour: int) -> tuple[str, str]:
        if not isinstance(cycle_date, dt.date) or isinstance(cycle_date, dt.datetime):
            raise TypeError(
                f"`cycle_date` must be a `datetime.date`, was {type(cycle_date).__name__}; "
                "a string would let a caller place arbitrary text in the path"
            )
        if isinstance(cycle_hour, bool) or not isinstance(cycle_hour, int):
            raise TypeError(f"`cycle_hour` must be an int, was {type(cycle_hour).__name__}")
        if not 0 <= cycle_hour <= 23:
            raise ValueError(f"`cycle_hour` must be in 0..23, was {cycle_hour}")
        return f"{cycle_date:%Y%m%d}", f"{cycle_hour:02d}"

    def _s3_url(self, cycle_date: dt.date, cycle_hour: int) -> str:
        day, hour = self._cycle_path_parts(cycle_date, cycle_hour)
        return f"{self._s3_base_url}/blend.{day}/{hour}/text/blend_nbptx.t{hour}z"

    def _nomads_url(self, cycle_date: dt.date, cycle_hour: int) -> str:
        day, hour = self._cycle_path_parts(cycle_date, cycle_hour)
        return (
            f"{self._nomads_base_url}{_NOMADS_BLEND_ROOT}/blend.{day}/{hour}/text/"
            f"blend_nbptx.t{hour}z"
        )

    def _validate_url(self, url: str) -> None:
        parts = httpx.URL(url)
        if parts.scheme != "https":
            raise DisallowedHostError(
                f"Scheme {parts.scheme!r} is not allowed; only https:// is permitted "
                f"(url={redact_url(url)})"
            )
        if parts.username:
            raise DisallowedHostError(
                f"URL must not carry userinfo credentials (url={redact_url(url)})"
            )
        if parts.port not in (None, 443):
            raise DisallowedHostError(
                f"Port {parts.port} is not allowed; only the default HTTPS port (443) "
                f"is permitted (url={redact_url(url)})"
            )
        host = parts.host.lower()
        if host not in self._allowed_hosts:
            raise DisallowedHostError(
                f"Host {host!r} is not in the allowlist (url={redact_url(url)})"
            )

    # -- the one endpoint -------------------------------------------------

    async def fetch_nbp_bulletin(
        self, *, cycle_date: dt.date, cycle_hour: int
    ) -> NbmQuantileFetchResult:
        """Fetch the collective NBP text bulletin for ONE cycle, filtered.

        AWS S3 is tried first; NOMADS only if the S3 attempt fails. Neither
        attempt is made if the arguments themselves are invalid (validated
        before any URL is built) or the proxy/TLS environment is unclean.
        """
        if self._check_proxy_env:
            assert_clean_proxy_env(self._approved_proxy_env_vars)
        primary_url = self._s3_url(cycle_date, cycle_hour)
        try:
            return await self._fetch_one(primary_url, source_host=self._s3_host)
        except DisallowedHostError:
            raise
        except TransportError as primary_exc:
            fallback_url = self._nomads_url(cycle_date, cycle_hour)
            try:
                return await self._fetch_one(fallback_url, source_host=self._nomads_host)
            except DisallowedHostError:
                raise
            except TransportError as fallback_exc:
                raise BothHostsFailedError(
                    f"Both the AWS S3 primary ({redact_url(primary_url)}) and the "
                    f"NOMADS fallback ({redact_url(fallback_url)}) failed to fetch "
                    f"the NBP bulletin for cycle {cycle_date:%Y-%m-%d} {cycle_hour:02d}Z: "
                    f"primary={primary_exc!r} fallback={fallback_exc!r}",
                    primary_error=primary_exc,
                    fallback_error=fallback_exc,
                ) from fallback_exc

    async def _fetch_one(self, url: str, *, source_host: str) -> NbmQuantileFetchResult:
        self._validate_url(url)
        try:
            async with self._build_client() as client, client.stream("GET", url) as response:
                self._raise_for_status(response, url=url)
                last_modified = response.headers.get("last-modified")
                text, raw_sha256, raw_bytes = await self._stream_filtered_body(response)
        except httpx.TimeoutException as exc:
            raise TransportTimeoutError(f"Timed out fetching {redact_url(url)}: {exc}") from exc
        except httpx.TransportError as exc:
            raise TransportError(f"Transport failure fetching {redact_url(url)}: {exc}") from exc
        return NbmQuantileFetchResult(
            text=text,
            source_host=source_host,
            last_modified=last_modified,
            fetched_at_ns=self._clock(),
            raw_sha256=raw_sha256,
            raw_bytes=raw_bytes,
        )

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            verify=self._ssl_context,
            follow_redirects=False,
            trust_env=False,
            timeout=self._timeout,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "text/plain",
                "Accept-Encoding": "identity",
            },
        )

    def _raise_for_status(self, response: httpx.Response, *, url: str) -> None:
        status = response.status_code
        if 300 <= status < 400:
            raise RedirectError(
                f"Server returned redirect {status} for {redact_url(url)}; redirects "
                "are disabled and treated as an integrity alarm.",
                status_code=status,
                location=response.headers.get("location"),
            )
        if status == 403:
            raise ForbiddenError(
                f"403 Forbidden from {redact_url(url)} (check User-Agent contact / abuse block)."
            )
        if status == 429:
            raise RateLimitedError(
                f"429 Too Many Requests from {redact_url(url)}.",
                retry_after=response.headers.get("retry-after"),
            )
        if status >= 500:
            raise ServerError(f"{status} server error from {redact_url(url)}.", status_code=status)
        if status != 200:
            raise TransportError(f"Unexpected status {status} from {redact_url(url)}.")

    async def _stream_filtered_body(self, response: httpx.Response) -> tuple[str, str, int]:
        """Stream, digest and line-filter the body in ONE pass.

        The sha256 covers every raw byte as it arrives, before decode
        (mirrors `HttpTransport._fetch`'s digest-before-decode rule). Only
        the filtered subset (`_StationBlockFilter`) is retained -- the raw
        bytes themselves are never buffered beyond one chunk plus one
        pending partial line.
        """
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        digest = hashlib.sha256()
        block_filter = _StationBlockFilter(self._stations)
        raw_bytes = 0
        pending = ""
        async for chunk in response.aiter_bytes(self._chunk_size):
            raw_bytes += len(chunk)
            if raw_bytes > self._max_body_bytes:
                raise OversizeBodyError(
                    f"NBP body from {redact_url(str(response.url))} exceeded the "
                    f"{self._max_body_bytes}-byte cap during streaming."
                )
            digest.update(chunk)
            try:
                decoded = decoder.decode(chunk)
            except UnicodeDecodeError as exc:
                raise DecodeError(
                    f"NBP body from {redact_url(str(response.url))} is not valid UTF-8: {exc}"
                ) from exc
            pending = _consume_lines(pending, decoded, block_filter.feed_line)
        try:
            tail = decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise DecodeError(
                f"NBP body from {redact_url(str(response.url))} is not valid UTF-8 at EOF: {exc}"
            ) from exc
        pending = pending + tail
        if pending:
            block_filter.feed_line(pending)
        return block_filter.text(), digest.hexdigest(), raw_bytes


def build_nbm_quantile_transport(
    clock: Callable[[], int], *, check_proxy_env: bool = True
) -> NbmQuantileTransport:
    """The production `NbmQuantileTransport` factory. AWS S3 is the live PRIMARY."""
    return NbmQuantileTransport(clock=clock, check_proxy_env=check_proxy_env)
