"""Containment for read-only endpoint probes: budget, transport, evidence.

Authority: ``docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`` section 4.P2 and
finding R15.

WHY THIS EXISTS
---------------
``docs/evidence/forecast_endpoint_probe_2026-08-29.md:27-39`` records a probe
that over-spent its approved request budget -- 23 against ~20 -- because a
hand-rolled ``curl`` invocation silently followed redirects. R15's verdict is
that the defect is *structural*: a request counter bolted onto a raw HTTP
client counts the requests the caller meant to make, while the redirect chain
decides how many actually go out.

So :class:`ProbeTransport` **subclasses** :class:`breezy.ingest.http.HttpTransport`
rather than reimplementing it. It inherits, unchanged and unforked:

* the HTTPS-only host allowlist, checked before a socket opens
  (``http.py`` ``_validate_url``);
* ``follow_redirects=False`` on the client (``_build_client``);
* 3xx-as-integrity-alarm (``_raise_for_status``);
* the body cap enforced *during* streaming (``_read_capped_body``).

It adds exactly two things:

1. **A hard request budget**, consumed inside the overridden ``_fetch`` --
   i.e. at the single dispatch point every request in this class must pass
   through -- so "one authorised request" and "one socket exchange" cannot
   diverge. The (N+1)th raises :class:`RequestBudgetExceededError` and aborts
   the run.
2. **A GET-only probe surface** taking a *path plus a query mapping*, both
   shape-checked, never a caller-supplied URL.

It also **closes** the two inherited NWS endpoint methods and refuses to be
constructed against the settlement host at all. Spending UA-trap exposure
against ``api.weather.gov`` is explicitly out of scope for P2, and "out of
scope" is worth more as a constructor that raises than as a sentence.

The budget is charged **pessimistically, at authorisation** -- before the
allowlist check, before the socket. An attempt that is refused downstream
still counts, exactly as the 2026-08-29 accounting counted its discarded
attempt. Over-counting can only under-spend; the converse is what this module
exists to prevent.

EVIDENCE DISCIPLINE
-------------------
:class:`ProbeEvidenceWriter` writes payloads under a suffix
(:data:`PROBE_PAYLOAD_SUFFIX`) that no production loader reads, plus a
``request_manifest.tsv`` recording every dispatched exchange -- successes,
error statuses and refused redirects alike. It takes its destination as an
argument and names no evidence path itself, so ``docs/evidence`` never becomes
a runtime value inside ``src/``.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from breezy.ingest.http import (
    DEFAULT_BASE_URL,
    FetchResult,
    HttpTransport,
    RedirectError,
    TransportError,
)

__all__ = [
    "MANIFEST_COLUMNS",
    "MANIFEST_FILENAME",
    "PROBE_PAYLOAD_SUFFIX",
    "SETTLEMENT_HOSTS",
    "ProbeEvidenceWriter",
    "ProbeExchange",
    "ProbeTransport",
    "RequestBudget",
    "RequestBudgetExceededError",
    "SettlementHostForbiddenError",
]

#: The payload suffix. Deliberately not ``.json``: nothing in the production
#: catalog or any loader matches it, so a captured probe payload cannot be
#: picked up by a glob and ingested under a plausible retrieval timestamp.
PROBE_PAYLOAD_SUFFIX: str = ".probe.json"

MANIFEST_FILENAME: str = "request_manifest.tsv"

MANIFEST_COLUMNS: tuple[str, ...] = (
    "ordinal",
    "requested_at_utc",
    "label",
    "url",
    "status",
    "bytes",
    "content_type",
    "outcome",
    "sha256",
)

#: The settlement origin, DERIVED from the shipped default rather than
#: restated, so a second literal cannot drift away from the first.
SETTLEMENT_HOSTS: frozenset[str] = frozenset({(urlsplit(DEFAULT_BASE_URL).hostname or "").lower()})

_EVIDENCE_README = f"""# EVIDENCE ONLY - NEVER INGEST

Every file in this directory is a read-only probe capture. It must **NEVER**
be ingested into any production catalog under any circumstance. Backfilling
these payloads under a plausible retrieval timestamp would be backdating, and
would destroy the point-in-time property the forecast design depends on.

Payloads carry the `{PROBE_PAYLOAD_SUFFIX}` suffix, which no production loader reads.
`{MANIFEST_FILENAME}` records every request this probe dispatched, including
the ones that failed.
"""

#: A probe path: absolute, single-slash, printable ASCII, no dot segments and
#: no scheme. Checked before the URL is assembled, so a path can never
#: retarget the request at another origin the way a caller-supplied URL could.
_PROBE_PATH_PATTERN = re.compile(r"\A/(?!/)[A-Za-z0-9._~!$&'()*+,;=:@%/-]*\Z")

#: Query keys and values: printable US-ASCII only. Excludes CR, LF, NUL, HTAB
#: and every non-ASCII byte -- the header/URL injection charset.
_QUERY_CHARSET = re.compile(r"\A[\x20-\x7e]*\Z")

_NANOSECONDS_PER_SECOND = 1_000_000_000


class RequestBudgetExceededError(RuntimeError):
    """Raised when a probe attempts its (N+1)th request.

    A hard abort, not a warning. The 2026-08-29 over-spend was survivable
    because the origin was tolerant; the control that would have caught it is
    one that stops the run rather than logging and continuing.
    """


class SettlementHostForbiddenError(ValueError):
    """Raised when a probe transport is aimed at the settlement origin.

    P2's probes are on hosts that are deliberately **not**
    ``api.weather.gov``: zero UA-trap exposure against the host that
    determines real-money settlement. That scoping decision is enforced in the
    constructor rather than left to the caller's diligence.
    """


class RequestBudget:
    """A hard, monotonic ceiling on how many requests a probe run may spend.

    Not a rate limiter and not advisory: :meth:`consume` returns the ordinal
    of the request it authorised, and raises once the ceiling is reached. A
    refusal is terminal -- the counter is never rolled back, so a caller that
    swallows the error cannot retry its way past the limit.
    """

    __slots__ = ("_limit", "_spent")

    def __init__(self, *, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError(f"`limit` must be an int, was {type(limit).__name__}")
        if limit < 1:
            raise ValueError(f"`limit` must be a positive request count, was {limit}")
        self._limit = limit
        self._spent = 0

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def spent(self) -> int:
        return self._spent

    @property
    def remaining(self) -> int:
        return self._limit - self._spent

    def consume(self) -> int:
        """Authorise one request and return its 1-based ordinal, or raise."""
        if self._spent >= self._limit:
            raise RequestBudgetExceededError(
                f"Request budget of {self._limit} is exhausted ({self._spent} spent); "
                "the probe run is aborted rather than allowed to over-spend."
            )
        self._spent += 1
        return self._spent

    def __repr__(self) -> str:
        return f"RequestBudget(limit={self._limit}, spent={self._spent})"


@dataclass(frozen=True, slots=True)
class ProbeExchange:
    """One dispatched request and what came back, successful or not.

    Every dispatched request produces one of these, including the ones that
    ended in an error status or a refused redirect -- honest request
    accounting means the manifest has a row for the requests that failed, not
    only the ones that produced a payload.
    """

    ordinal: int
    requested_at_utc: str
    label: str
    url: str
    status_code: int
    body_bytes: int
    content_type: str
    outcome: str
    sha256: str | None
    text: str | None
    finding: str | None = None


class ProbeTransport(HttpTransport):
    """A budgeted, GET-only, settlement-host-free view of the hardened transport.

    Overrides nothing that hardens the request. The four controls R15 cites by
    line number are inherited verbatim from :class:`HttpTransport`; a test
    asserts this class does not shadow any of them.
    """

    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: frozenset[str],
        budget: RequestBudget,
        max_body_bytes: int,
        user_agent: str,
        accept: str,
        clock: Callable[[], int],
        connect_timeout: float = 5.0,
        read_timeout: float = 20.0,
    ) -> None:
        forbidden = {host.lower() for host in allowed_hosts} & SETTLEMENT_HOSTS
        base_host = (urlsplit(base_url).hostname or "").lower()
        if base_host in SETTLEMENT_HOSTS:
            forbidden.add(base_host)
        if forbidden:
            raise SettlementHostForbiddenError(
                f"A probe transport may not be aimed at the settlement origin(s) "
                f"{sorted(forbidden)}. P2's probes are scoped to hosts that are NOT "
                "api.weather.gov precisely so no UA-trap exposure is spent against "
                "the host that determines real-money settlement."
            )
        super().__init__(
            allowed_hosts=allowed_hosts,
            clock=clock,
            base_url=base_url,
            max_body_bytes=max_body_bytes,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            user_agent=user_agent,
            accept=accept,
        )
        self._budget = budget

    # -- the closed inherited surface --------------------------------------

    async def fetch_discovery_list(
        self,
        cli_location: str,
        *,
        if_none_match: str | None = None,
        if_modified_since: str | None = None,
    ) -> FetchResult:
        """Closed. This is an ``api.weather.gov`` endpoint; a probe has none."""
        raise NotImplementedError(
            "A ProbeTransport has no NWS discovery-list endpoint. This method is "
            "closed so the settlement path cannot be reached from a probe."
        )

    async def fetch_product(self, product_id: str) -> FetchResult:
        """Closed, for the same reason as :meth:`fetch_discovery_list`."""
        raise NotImplementedError(
            "A ProbeTransport has no NWS product endpoint. This method is closed "
            "so the settlement path cannot be reached from a probe."
        )

    # -- the probe surface --------------------------------------------------

    async def probe_get(
        self,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        label: str,
    ) -> ProbeExchange:
        """Dispatch one budgeted GET and RECORD the outcome, good or bad.

        A 3xx comes back as an exchange whose ``outcome`` is
        ``redirect_not_followed`` and whose ``finding`` carries the alarm --
        recorded as evidence, never chased. An error status likewise becomes a
        recorded exchange. :class:`RequestBudgetExceededError` is the one thing
        that is **not** caught: budget exhaustion aborts the run.
        """
        url = self._probe_url(path, query)
        try:
            result = await self._fetch(
                url,
                if_none_match=None,
                if_modified_since=None,
                allow_not_modified=False,
            )
        except RequestBudgetExceededError:
            raise
        except RedirectError as exc:
            return self._exchange_from_alarm(
                label=label,
                url=url,
                status_code=exc.status_code,
                outcome="redirect_not_followed",
                finding=(
                    f"Server answered {exc.status_code} with Location="
                    f"{exc.location!r}. Redirects are NOT followed: recorded as an "
                    "integrity finding, not a fetch step."
                ),
            )
        except TransportError as exc:
            return self._exchange_from_alarm(
                label=label,
                url=url,
                status_code=0,
                outcome=f"error:{type(exc).__name__}",
                finding=f"{type(exc).__name__}: {exc}",
            )
        return self._exchange_from_result(label=label, url=url, result=result)

    async def probe_get_strict(
        self,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
    ) -> FetchResult:
        """Dispatch one budgeted GET and let every inherited alarm propagate.

        The same budget and the same controls; used where a caller wants the
        typed exception rather than a recorded finding.
        """
        return await self._fetch(
            self._probe_url(path, query),
            if_none_match=None,
            if_modified_since=None,
            allow_not_modified=False,
        )

    # -- internals ----------------------------------------------------------

    async def _fetch(
        self,
        url: str,
        *,
        if_none_match: str | None,
        if_modified_since: str | None,
        allow_not_modified: bool,
    ) -> FetchResult:
        """Charge the budget, then delegate to the inherited implementation.

        The override is placed HERE, at the one dispatch point every request in
        the base class funnels through, rather than in the public methods: a
        counter on the public surface counts intentions, whereas this counts
        exchanges. Nothing that opens a socket on this object can skip it.
        """
        self._budget.consume()
        return await super()._fetch(
            url,
            if_none_match=if_none_match,
            if_modified_since=if_modified_since,
            allow_not_modified=allow_not_modified,
        )

    def _probe_url(self, path: str, query: Mapping[str, str] | None) -> str:
        """Assemble the URL from a validated path and validated query values.

        The caller supplies WHAT to fetch on the configured origin, never
        WHERE -- the same rule the settlement methods follow, expressed for an
        origin whose paths are not known in advance.
        """
        if _PROBE_PATH_PATTERN.match(path) is None:
            raise ValueError(
                "`path` must be an absolute single-slash path of printable "
                "URL characters (e.g. `/v1/previous-runs`); the supplied value "
                "does not match and is refused rather than sanitised. It is "
                "withheld from this message."
            )
        if ".." in path:
            raise ValueError("`path` must not contain a dot segment; it is refused.")
        if not query:
            return f"{self._base_url}{path}"
        for key, value in query.items():
            for label, item in (("key", key), ("value", value)):
                if _QUERY_CHARSET.match(item) is None:
                    raise ValueError(
                        f"A query {label} contains characters that are not printable "
                        "US-ASCII (CR/LF/control/non-ASCII); it is refused rather "
                        "than sanitised, and is withheld from this message."
                    )
        rendered = urlencode(sorted(query.items()), doseq=False)
        return f"{self._base_url}{path}?{rendered}"

    def _utc_stamp(self) -> str:
        seconds = self._clock() / _NANOSECONDS_PER_SECOND
        return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).isoformat(timespec="seconds")

    def _exchange_from_result(self, *, label: str, url: str, result: FetchResult) -> ProbeExchange:
        body = result.text or ""
        return ProbeExchange(
            ordinal=self._budget.spent,
            requested_at_utc=self._utc_stamp(),
            label=label,
            url=url,
            status_code=result.status_code,
            body_bytes=len(body.encode("utf-8")),
            content_type=result.headers.get("content-type", ""),
            outcome="ok",
            sha256=result.sha256,
            text=result.text,
        )

    def _exchange_from_alarm(
        self,
        *,
        label: str,
        url: str,
        status_code: int,
        outcome: str,
        finding: str,
    ) -> ProbeExchange:
        return ProbeExchange(
            ordinal=self._budget.spent,
            requested_at_utc=self._utc_stamp(),
            label=label,
            url=url,
            status_code=status_code,
            body_bytes=0,
            content_type="",
            outcome=outcome,
            sha256=None,
            text=None,
            finding=finding,
        )


class ProbeEvidenceWriter:
    """Writes probe payloads and the request manifest into one directory.

    Write-only by construction: this class holds its rows in memory and
    rewrites the manifest, so it never reads a capture back. That is asserted
    by test, and it is what keeps ``.probe.json`` a suffix nothing in this
    process is even capable of loading.

    The destination is an argument. No evidence path is named here, so
    ``docs/evidence`` never becomes a runtime value inside ``src/``.
    """

    __slots__ = ("_directory", "_rows")

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._directory = directory
        self._rows: list[tuple[str, ...]] = []
        (directory / "README.md").write_text(_EVIDENCE_README, encoding="utf-8")
        self._flush_manifest()

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def row_count(self) -> int:
        return len(self._rows)

    def record(self, name: str, exchange: ProbeExchange) -> None:
        """Append one manifest row and, when a body arrived, one payload file."""
        if exchange.text is not None:
            payload = {
                "label": exchange.label,
                "url": exchange.url,
                "status": exchange.status_code,
                "content_type": exchange.content_type,
                "requested_at_utc": exchange.requested_at_utc,
                "sha256": exchange.sha256,
                "bytes": exchange.body_bytes,
                "outcome": exchange.outcome,
                "finding": exchange.finding,
                "body": exchange.text,
            }
            target = self._directory / f"{name}{PROBE_PAYLOAD_SUFFIX}"
            target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self._rows.append(
            (
                str(exchange.ordinal),
                exchange.requested_at_utc,
                exchange.label,
                exchange.url,
                str(exchange.status_code),
                str(exchange.body_bytes),
                exchange.content_type,
                exchange.outcome,
                exchange.sha256 or "",
            )
        )
        self._flush_manifest()

    def write_report(self, name: str, text: str) -> Path:
        """Write one plain-text/Markdown artifact beside the payloads."""
        target = self._directory / name
        target.write_text(text, encoding="utf-8")
        return target

    def _flush_manifest(self) -> None:
        lines = ["\t".join(MANIFEST_COLUMNS)]
        lines.extend("\t".join(row) for row in self._rows)
        (self._directory / MANIFEST_FILENAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
