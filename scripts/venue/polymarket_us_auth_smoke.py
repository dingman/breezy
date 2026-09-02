#!/usr/bin/env python3
"""Operator connectivity proof for Polymarket.us -- read-only, GET-only.

Authority: ``docs/plans/archive/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
section 10 (``:1306-1352``), section 9 Step 15, controls S5, S8 and S15.

This script answers ONE operator question -- *are we actually connected to
Polymarket.us?* -- and leaves a dated, redacted artefact proving the answer.
It authenticates with real credentials, performs authenticated reads,
connects the markets WebSocket, and runs a minimal ``TradingNode`` so the
quotes it counts are quotes that reached the Nautilus ``DataEngine``, not
quotes our own parser happened to produce.

Read-only by construction
-------------------------
The only egress primitives reachable from here are
``PolymarketUSHttpClient.get_authenticated`` / ``get_public`` (barrier B1),
a signer that refuses to sign anything but ``GET`` (B2), and a transport that
keeps its pyo3 client out of attribute and bound-method ``__self__``
reachability (B3). The repo-wide AST barriers B4/B5 scan ``scripts/`` as well
as ``src/``, and classify anything under ``scripts/venue/`` as venue-touching,
so this file is inside their scope. TLS verification is left entirely to the
transport and is never weakened anywhere in this script.

Safety preconditions, in the order they are enforced
----------------------------------------------------
1. **Core dumps are disabled first.** ``SecureString`` cannot scrub the
   credential: ``clear()`` overwrites a ``bytearray`` mirror and then rebinds
   ``self._value = ""``, which cannot touch the memory of the original
   immutable ``str`` (plan ``:1374``). A crash during signing would therefore
   write the Ed25519 key into a core file. ``RLIMIT_CORE`` is zeroed --
   and the in-force limit VERIFIED to be ``(0, 0)`` -- before a single
   credential byte is read; anything else refuses the run. The script owns
   this property for its own process, so no shell prefix is required.
   ``ulimit -c 0`` / ``LimitCORE=0`` remain useful defence in depth for
   child processes only, which this process cannot cover.
2. **The run refuses unless explicitly enabled** (``BREEZY_VENUE_LIVE=1``),
   and refuses under ``BREEZY_LOG_LEVEL=DEBUG``/``TRACE`` because a
   header-logging run would print the signature (control S5).
3. Only then are credentials read.

Evidence
--------
``docs/evidence/venue/polymarket_us/READONLY_AUTH_SMOKE_<stamp>.md`` plus a
``.sha256`` sidecar. ``X-PM-Signature`` **and** ``X-PM-Access-Key`` are
redacted (SEC-4), and the writer refuses to emit the file at all if any
four-character window of any secret survives into the rendered text.

Usage::

    BREEZY_VENUE_LIVE=1 \\
    POLYMARKET_US_KEY_ID=... \\
    POLYMARKET_US_SECRET_KEY_FILE=/path/to/key \\
    POLYMARKET_US_API_BASE=https://api.polymarket.us \\
    POLYMARKET_US_GATEWAY_BASE=https://gateway.polymarket.us \\
    POLYMARKET_US_WS_URL=wss://api.polymarket.us \\
    POLYMARKET_US_MARKET_SLUGS=tc-temp-nychigh-2026-08-25-lt79f \\
    POLYMARKET_US_USER_AGENT='breezy-smoke/1.0 (+mailto:ops@example.com)' \\
    uv run python scripts/venue/polymarket_us_auth_smoke.py
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import hashlib
import json
import os
import resource
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:  # pragma: no cover - operator entrypoint
    sys.path.insert(0, str(REPO_ROOT / "src"))

from breezy.adapters.polymarket_us.credentials import (
    PolymarketUSCredentials,
)
from breezy.adapters.polymarket_us.env import (
    load_polymarket_us_credentials,
)
from breezy.adapters.polymarket_us.errors import (
    PolymarketUSError,
    SignatureClockSkewError,
)
from breezy.adapters.polymarket_us.factories import (
    POLYMARKET_US_CLIENT_NAME,
    config_from_env,
)
from breezy.adapters.polymarket_us.redaction import (
    REDACTED,
    redact_headers,
    redact_text,
    redact_url,
)
from breezy.adapters.polymarket_us.transport import (
    QUOTA_KEY_INSTRUMENTS,
    QUOTA_KEY_PORTFOLIO,
    PolymarketUSReadTransport,
    VenueResponse,
)

__all__ = [
    "EVIDENCE_DIRECTORY",
    "HTTP_METHOD",
    "SECRET_FRAGMENT_LENGTH",
    "SIGNING_CLOCK_SKEW_GUARD_MS",
    "VENUE_LIVE_ENV_VAR",
    "CredentialGuard",
    "EvidenceCheckpoint",
    "EvidenceLeakError",
    "Finding",
    "FrameSchema",
    "Prepared",
    "RequestRecord",
    "SmokeRefusal",
    "SmokeReport",
    "assert_host_clock_safe_for_signing",
    "assert_smoke_enabled",
    "build_safe_excepthook",
    "build_safe_loop_exception_handler",
    "classify_canonical_string_outcome",
    "describe_exception",
    "disable_core_dumps",
    "drain_node_task",
    "evidence_filename",
    "find_secret_leak_offsets",
    "main",
    "prepare",
    "render_evidence",
    "report_fatal",
    "secret_fragments",
    "verdict_reason_for",
    "write_evidence",
]

#: The ONLY HTTP method this script can issue. Named once so a reader can
#: verify read-onlyness without tracing every call site.
HTTP_METHOD: Final[str] = "GET"

VENUE_LIVE_ENV_VAR: Final[str] = "BREEZY_VENUE_LIVE"
LOG_LEVEL_ENV_VAR: Final[str] = "BREEZY_LOG_LEVEL"

#: Log levels at which a transport or framework may print request headers.
HEADER_LOGGING_LEVELS: Final[frozenset[str]] = frozenset({"DEBUG", "TRACE"})

EVIDENCE_DIRECTORY: Final[Path] = Path("docs/evidence/venue/polymarket_us")
EVIDENCE_PREFIX: Final[str] = "READONLY_AUTH_SMOKE_"

#: Window length for the fragment scan. Four is not arbitrary: it is exactly
#: what ``SecureString.get_redacted`` publishes from each end of a secret
#: (``nautilus_trader/common/secure.py:100-102``), i.e. the smallest leak the
#: repo already treats as material.
SECRET_FRAGMENT_LENGTH: Final[int] = 4

PORTFOLIO_PATH: Final[str] = "/v1/portfolio/positions"
MARKET_BY_SLUG_PATH: Final[str] = "/v1/market/slug/{slug}"

DEFAULT_QUOTE_WINDOW_SECS: Final[float] = 120.0
DEFAULT_WS_PROBE_SECS: Final[float] = 10.0
MAX_FRAME_SCHEMAS: Final[int] = 5
MAX_LOG_LINES: Final[int] = 60

#: How far outside the +/-30s window step D deliberately reaches.
STALE_TIMESTAMP_OFFSET_MS: Final[int] = 120_000

#: The docs define a +/-30s signing window. Refusing at half that window leaves
#: operational margin and surfaces clock drift before it looks like a generic
#: venue-side 401.
DOCUMENTED_SIGNING_WINDOW_MS: Final[int] = 30_000
SIGNING_CLOCK_SKEW_GUARD_FRACTION: Final[float] = 0.5
SIGNING_CLOCK_SKEW_GUARD_MS: Final[int] = int(
    DOCUMENTED_SIGNING_WINDOW_MS * SIGNING_CLOCK_SKEW_GUARD_FRACTION
)

TEARDOWN_OK: Final[str] = "OK"
TEARDOWN_NOT_RUN: Final[str] = "NOT_RUN"
TEARDOWN_FAILED: Final[str] = "FAILED"
KNOWN_BENIGN_NAUTILUS_LOOP_STOP: Final[str] = "KNOWN_BENIGN_NAUTILUS_LOOP_STOP"


class SmokeRefusal(RuntimeError):
    """The run was not explicitly enabled, or the host is unsafe for it."""


class EvidenceLeakError(RuntimeError):
    """Rendered evidence still carried secret-derived material.

    The message deliberately reports COUNTS and OFFSETS only. Echoing the
    offending fragment would reproduce the leak inside the traceback, the
    terminal scrollback, and any CI log that captured them.
    """


# ---------------------------------------------------------------------------
# S15 -- core dumps, first action of the process
# ---------------------------------------------------------------------------


def _scrubbed(exc: BaseException) -> str:
    """Describe ``exc`` by type and errno only.

    ``str(exc)`` on a resource error is usually harmless, but this runs on the
    path that guards a credential read; reporting only the type and errno
    means no future exception payload can smuggle host detail into stderr or
    a CI log.
    """
    errno = getattr(exc, "errno", None)
    return f"{type(exc).__name__}" + (f" (errno {errno})" if errno is not None else "")


def disable_core_dumps() -> tuple[int, int]:
    """Zero ``RLIMIT_CORE``, VERIFY it took effect, and return it.

    Both soft AND hard limits are set to zero: an unprivileged process cannot
    raise a hard limit afterwards, so this cannot be undone by anything the
    run goes on to do.

    Setting is not the control -- the limit actually *in force* is. A
    ``setrlimit`` that silently fails to take effect on some platform,
    filesystem or container configuration would otherwise leave the run
    signing with a real Ed25519 key while dumps stayed enabled, with the only
    trace a number in an artefact nobody reads until afterwards. So the
    in-force value is read back and anything other than ``(0, 0)`` raises
    :class:`SmokeRefusal`, as does ``setrlimit``/``getrlimit`` raising, and as
    does a platform with no ``RLIMIT_CORE`` at all.

    Refusing on platform absence is the deliberate choice: this script's
    documented safety property is "the key cannot reach a core file", and a
    host that cannot express that limit cannot prove it -- a warning would
    make an unprovable claim look green. (A host with no ``resource`` module
    at all fails at import, which is likewise fail-closed.)
    """
    which = getattr(resource, "RLIMIT_CORE", None)
    if which is None:
        raise SmokeRefusal(
            "Refusing to run: this platform has no RLIMIT_CORE, so core dumps "
            "cannot be disabled and a crash during signing could write the "
            "Ed25519 key to disk."
        )
    try:
        resource.setrlimit(which, (0, 0))
        soft, hard = resource.getrlimit(which)
    except (OSError, ValueError) as exc:
        raise SmokeRefusal(
            "Refusing to run: could not disable core dumps -- "
            f"RLIMIT_CORE call failed with {_scrubbed(exc)}."
        ) from None
    limit = (int(soft), int(hard))
    if limit != (0, 0):
        raise SmokeRefusal(
            "Refusing to run: RLIMIT_CORE is still "
            f"{limit} after being set to (0, 0), so a crash during signing "
            "could write the Ed25519 key to a core file."
        )
    return limit


def assert_smoke_enabled(env: Mapping[str, str]) -> None:
    """Refuse the run unless the operator enabled it explicitly.

    Only the exact string ``"1"`` counts, matching ``tests/conftest.py:113``.
    ``true``/``yes``/``on`` are rejected on purpose so a half-remembered
    convention cannot fire real signed requests at a production venue.
    """
    if env.get(VENUE_LIVE_ENV_VAR) != "1":
        if VENUE_LIVE_ENV_VAR in env:
            observed = f"{VENUE_LIVE_ENV_VAR}: {env[VENUE_LIVE_ENV_VAR]!r}"
        else:
            observed = f"{VENUE_LIVE_ENV_VAR}: absent"
        raise SmokeRefusal(
            f"Refusing to run: this script performs REAL authenticated reads "
            f"against a production venue. Set {VENUE_LIVE_ENV_VAR}=1 "
            "(exactly '1') to enable it. "
            f"Observed {observed}; pid={os.getpid()}; executable={sys.executable!r}."
        )
    level = env.get(LOG_LEVEL_ENV_VAR, "").strip().upper()
    if level in HEADER_LOGGING_LEVELS:
        raise SmokeRefusal(
            f"Refusing to run with {LOG_LEVEL_ENV_VAR}={level}: at that level a "
            "transport or framework may print request headers, which would "
            "publish the Ed25519 signature and the access key."
        )


# ---------------------------------------------------------------------------
# Secret-fragment detection
# ---------------------------------------------------------------------------


def secret_fragments(secret: str, length: int = SECRET_FRAGMENT_LENGTH) -> frozenset[str]:
    """Every contiguous ``length``-character window of ``secret``."""
    if not secret:
        return frozenset()
    if len(secret) <= length:
        return frozenset({secret})
    return frozenset(secret[i : i + length] for i in range(len(secret) - length + 1))


def find_secret_leak_offsets(text: str, secrets: Iterable[str]) -> tuple[int, ...]:
    """Return the offsets in ``text`` at which secret-derived material appears.

    Fail-closed by design, and deliberately over-sensitive: a four-character
    window of a base64 key can in principle coincide with ordinary document
    text, and when it does this refuses to write the artefact rather than
    reasoning about whether that particular coincidence was harmless. A
    refused evidence file costs one re-run; a published fragment cannot be
    un-published.
    """
    offsets: set[int] = set()
    for secret in secrets:
        if not secret:
            continue
        for fragment in secret_fragments(secret) | {secret}:
            start = text.find(fragment)
            while start != -1:
                offsets.add(start)
                start = text.find(fragment, start + 1)
    return tuple(sorted(offsets))


# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequestRecord:
    """One read, as it will appear in the evidence artefact."""

    step: str
    label: str
    path: str
    query_string: str
    status: int | None
    latency_ms: float
    sent_headers: Mapping[str, str]
    observed_headers: Mapping[str, str]
    note: str


@dataclass(frozen=True, slots=True)
class Finding:
    """One previously-open venue question, and what the live run showed."""

    key: str
    question: str
    answer: str


@dataclass(frozen=True, slots=True)
class FrameSchema:
    """The shape of one inbound WebSocket frame, values withheld.

    Captured because the market-slug field name in a market-data frame is
    currently a GUESS (``data.MARKET_SLUG_KEY == "marketSlug"``, the singular
    of the SDK's subscribe key). Only the live schema settles it.
    """

    frame_class: str
    keys: tuple[str, ...]
    structure_paths: tuple[str, ...]
    value_types: Mapping[str, str]
    safe_values: Mapping[str, str]
    slug_bearing_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SmokeReport:
    """Everything the evidence artefact renders."""

    started_at: str
    finished_at: str
    core_limit: tuple[int, int]
    key_file_device: int | None
    key_file_filesystem: str | None
    host_clock_offset_ms: int | None
    user_agent: str
    api_base_url: str
    gateway_base_url: str
    ws_url: str
    market_slugs: tuple[str, ...]
    requests: tuple[RequestRecord, ...]
    findings: tuple[Finding, ...]
    frame_schemas: tuple[FrameSchema, ...]
    frame_class_counts: Mapping[str, int]
    instrument_ids: tuple[str, ...]
    frames_received: int
    quotes_delivered: int
    quotes_per_slug: Mapping[str, int]
    log_excerpt: tuple[str, ...]
    write_requests_issued: int
    verdict: bool
    verdict_reason: str
    teardown_health: str = TEARDOWN_NOT_RUN
    teardown_error: str | None = None


@dataclass(frozen=True, slots=True)
class Prepared:
    """The result of the ordered, offline startup sequence."""

    core_limit: tuple[int, int]
    config: Any
    credentials: PolymarketUSCredentials


@dataclass(slots=True)
class CredentialGuard:
    """Whether this process has ENTERED code that reads an Ed25519 secret.

    Deliberately not a module-level flag. A module global is reachable (and
    resettable) from anywhere, including test code that could silently unarm
    it; an instance created in :func:`main` and handed to exactly two
    collaborators -- :func:`build_safe_excepthook` and :func:`prepare` -- makes
    the ownership visible in the signatures and keeps the "one guard, one
    process" property provable by test.

    It carries a BOOLEAN, never the secret itself. Holding the plaintext here
    so the hook could scrub against it would extend a credential's lifetime and
    reach far beyond :func:`main`'s frame, which is the opposite of the goal.

    The flag says "a credential read has BEGUN", not "a secret is resident",
    because that is the only claim the process can actually prove -- and it is
    the conservative direction: it arms BEFORE the read, so an exception raised
    by the read itself is already treated as credential-bearing.
    """

    _credential_read_begun: bool = False

    @property
    def credential_read_begun(self) -> bool:
        """``True`` once the credential read has started. Never goes back."""
        return self._credential_read_begun

    def mark_credential_read_begun(self) -> None:
        """Arm the guard. Idempotent, and one-way by construction."""
        self._credential_read_begun = True


def prepare(
    env: Mapping[str, str] | None = None,
    *,
    guard: CredentialGuard | None = None,
) -> Prepared:
    """Run the startup sequence in its safety-critical order.

    ``disable_core_dumps`` FIRST, the enablement guard SECOND, and only then
    the credential read. Nothing between the first and third step may touch a
    secret, and the ordering is pinned by test rather than by comment.

    ``guard`` is armed IMMEDIATELY BEFORE the credential read, not after it.
    Arming after would leave the read itself -- the one step whose exception
    payload could plausibly carry credential material -- reported under the
    permissive pre-credential branch of the excepthook.
    """
    source = os.environ if env is None else env
    core_limit = disable_core_dumps()
    assert_smoke_enabled(source)
    config = config_from_env(source)
    if guard is not None:
        guard.mark_credential_read_begun()
    credentials = load_polymarket_us_credentials(config.secrets, env=source)
    return Prepared(core_limit=core_limit, config=config, credentials=credentials)


# ---------------------------------------------------------------------------
# Evidence rendering
# ---------------------------------------------------------------------------


def evidence_filename(stamp: str) -> str:
    """Name of the evidence artefact for a run started at ``stamp``."""
    return f"{EVIDENCE_PREFIX}{stamp}.md"


def _stamp(started_at: str) -> str:
    return started_at.replace(":", "").replace("+00:00", "Z")


def _table(rows: Sequence[Sequence[str]], header: Sequence[str]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("|" + "|".join("---" for _ in header) + "|")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def render_evidence(report: SmokeReport, *, secrets: Iterable[str]) -> str:
    """Render the operator-facing artefact, redacting as it goes.

    Two independent layers: :func:`redact_headers` blanks every sensitive
    header by NAME (so a value is never formatted in the first place), and
    :func:`redact_text` then masks each supplied secret literally, covering
    anything a future field might carry through. :func:`write_evidence` adds
    the third, fail-closed layer.
    """
    secret_values = [s for s in secrets if s]
    lines: list[str] = [
        f"# Polymarket.us read-only authenticated smoke test -- {report.started_at}",
        "",
        (
            f"**Connectivity verdict: {'PASS' if report.verdict else 'FAIL'}** -- "
            "authenticated connectivity "
            f"{'proven' if report.verdict else 'NOT proven'}."
        ),
        f"**Teardown health: {report.teardown_health}**",
        "",
        report.verdict_reason,
    ]
    if report.teardown_error is not None:
        lines.extend(["", f"Teardown detail: {report.teardown_error}"])
    lines += ["", "## Run environment", ""]
    lines.extend(
        _table(
            [
                ["started (UTC)", report.started_at],
                ["finished (UTC)", report.finished_at],
                ["RLIMIT_CORE (soft, hard)", str(report.core_limit)],
                ["key-file st_dev", str(report.key_file_device)],
                ["key-file filesystem", str(report.key_file_filesystem)],
                [
                    "host clock offset vs venue Date header (ms)",
                    str(report.host_clock_offset_ms),
                ],
                ["User-Agent", report.user_agent],
                ["api base", redact_url(report.api_base_url)],
                ["gateway base", redact_url(report.gateway_base_url)],
                ["ws url", redact_url(report.ws_url)],
                ["market slugs", ", ".join(report.market_slugs)],
                ["HTTP methods issued", HTTP_METHOD],
                ["write requests issued", str(report.write_requests_issued)],
                ["teardown health", report.teardown_health],
                ["teardown error", report.teardown_error or "-"],
            ],
            ["field", "value"],
        )
    )

    lines += ["", "## Reads performed", ""]
    lines.extend(
        _table(
            [
                [
                    record.step,
                    record.label,
                    HTTP_METHOD,
                    f"`{redact_url(record.path)}`",
                    f"`{record.query_string}`" if record.query_string else "-",
                    str(record.status),
                    f"{record.latency_ms:.1f}",
                    record.note,
                ]
                for record in report.requests
            ],
            ["step", "read", "method", "path", "query", "status", "ms", "note"],
        )
    )

    lines += ["", "## Request headers sent (values redacted)", ""]
    header_rows: list[list[str]] = []
    seen: set[str] = set()
    for record in report.requests:
        for name, value in redact_headers(record.sent_headers).items():
            if name in seen:
                continue
            seen.add(name)
            header_rows.append([f"`{name}`", value])
    lines.extend(_table(header_rows, ["header", "value"]))
    lines += [
        "",
        (
            "`X-PM-Access-Key`, `X-PM-Timestamp` and `X-PM-Signature` render as "
            f"`{REDACTED}` by construction (SEC-4)."
        ),
        "",
        "## Response headers observed",
        "",
    ]
    observed_rows: list[list[str]] = []
    for record in report.requests:
        for name, value in redact_headers(record.observed_headers).items():
            observed_rows.append([record.step, f"`{name}`", value])
    lines.extend(_table(observed_rows or [["-", "-", "-"]], ["step", "header", "value"]))

    lines += ["", "## Findings -- previously open venue questions", ""]
    lines.extend(
        _table(
            [[f.key, f.question, f.answer] for f in report.findings],
            ["id", "question", "answer observed live"],
        )
    )

    lines += ["", "## Market-data frame classes", ""]
    lines.extend(
        _table(
            [
                [frame_class, str(count)]
                for frame_class, count in sorted(report.frame_class_counts.items())
            ]
            or [["-", "0"]],
            ["frame class", "count"],
        )
    )

    lines += ["", "## Market-data frame schema", ""]
    if report.frame_schemas:
        for index, schema in enumerate(report.frame_schemas, start=1):
            lines.append(f"Frame {index} class: `{schema.frame_class}`")
            lines.append(f"Frame {index} top-level keys: `{', '.join(schema.keys)}`")
            lines.append(f"Frame {index} structure paths: `{', '.join(schema.structure_paths)}`")
            lines.append("")
            lines.extend(
                _table(
                    [[f"`{key}`", value] for key, value in sorted(schema.value_types.items())],
                    ["key", "value type"],
                )
            )
            lines.append("")
            if schema.safe_values:
                lines.append("Safe scalar values:")
                lines.append("")
                lines.extend(
                    _table(
                        [[f"`{key}`", value] for key, value in sorted(schema.safe_values.items())],
                        ["key", "value"],
                    )
                )
                lines.append("")
            lines.append(
                "Keys whose value matched a configured market slug: "
                + (", ".join(f"`{k}`" for k in schema.slug_bearing_keys) or "none")
            )
            lines.append("")
    else:
        lines += ["No market-data frames were captured.", ""]

    lines += ["## Data reaching the Nautilus DataEngine", ""]
    lines.extend(
        _table(
            [
                ["instruments loaded", str(len(report.instrument_ids))],
                ["WebSocket frames received", str(report.frames_received)],
                ["QuoteTicks delivered", str(report.quotes_delivered)],
            ],
            ["metric", "count"],
        )
    )
    lines += ["", "Instrument ids:", ""]
    lines.extend(f"- `{identifier}`" for identifier in report.instrument_ids)
    lines += ["", "Quotes per slug:", ""]
    lines.extend(f"- `{slug}`: {count}" for slug, count in sorted(report.quotes_per_slug.items()))

    lines += ["", "## Log excerpt", "", "```"]
    lines.extend(report.log_excerpt)
    lines += ["```", ""]

    return redact_text("\n".join(lines) + "\n", secret_values)


#: Mode for the evidence artefact and its digest sidecar: owner read/write.
#:
#: The artefact is redacted, but "redacted" is a property of the current
#: renderer, and this runs on an operator workstation whose umask is unknown.
#: A world-readable artefact widens the blast radius of any future rendering
#: defect for free; 0600 costs nothing.
EVIDENCE_FILE_MODE: Final[int] = 0o600

#: Mode for the evidence directory: a permissive parent undoes a private file.
EVIDENCE_DIR_MODE: Final[int] = 0o700


def _write_private_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path``, owner-readable only, with no public window.

    ``write_text`` then ``chmod`` would leave the file world-readable for the
    interval between the two calls. ``os.open`` applies the mode at creation
    instead. The explicit ``chmod`` afterwards covers the two cases ``os.open``
    cannot: a pre-existing file (whose mode ``O_CREAT`` leaves untouched) and a
    umask that could only ever make the mode MORE restrictive, never less.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, EVIDENCE_FILE_MODE)
    try:
        handle = os.fdopen(fd, "w", encoding="utf-8")
    except BaseException:
        # Only reachable if `fdopen` itself failed; once it succeeds the file
        # object owns `fd` and closing it here would be a double close.
        os.close(fd)
        raise
    with handle:
        handle.write(text)
    os.chmod(path, EVIDENCE_FILE_MODE)


def write_evidence(
    report: SmokeReport,
    *,
    secrets: Iterable[str],
    directory: Path = EVIDENCE_DIRECTORY,
) -> Path:
    """Render, verify, then write the artefact and its digest sidecar.

    The verification runs on the FINAL text, after both redaction layers, and
    refuses to create any file when it fires. Nothing is written before the
    check, so a refused run leaves no partial artefact behind.
    """
    secret_values = [s for s in secrets if s]
    text = render_evidence(report, secrets=secret_values)
    offsets = find_secret_leak_offsets(text, secret_values)
    if offsets:
        raise EvidenceLeakError(
            f"Refusing to write evidence: {len(offsets)} occurrence(s) of "
            f"secret-derived material survived redaction, at text offsets "
            f"{offsets}. The offending value is deliberately not reproduced here."
        )

    directory.mkdir(parents=True, exist_ok=True)
    # `exist_ok=True` accepts whatever mode a pre-existing directory already
    # has, and `mode=` on `mkdir` is ignored for existing directories and
    # masked by the umask for new ones. Set it explicitly, unconditionally.
    directory.chmod(EVIDENCE_DIR_MODE)

    path = directory / evidence_filename(_stamp(report.started_at))
    _write_private_text(path, text)

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    sidecar = path.with_suffix(path.suffix + ".sha256")
    _write_private_text(sidecar, f"{digest}  {path.name}\n")
    return path


@dataclass(slots=True)
class EvidenceCheckpoint:
    """Durably rewrite the latest redacted evidence while the run progresses."""

    secrets: Sequence[str]
    directory: Path = EVIDENCE_DIRECTORY
    latest_report: SmokeReport | None = None
    latest_path: Path | None = None

    def write(self, report: SmokeReport) -> Path:
        path = write_evidence(report, secrets=self.secrets, directory=self.directory)
        self.latest_report = report
        self.latest_path = path
        return path

    def write_unexpected_failure(self, exc: BaseException) -> Path | None:
        report = self.latest_report
        if report is None:
            return None
        failure = describe_exception(exc, self.secrets)
        stamp = dt.datetime.now(tz=dt.UTC).strftime("%H:%M:%SZ")
        teardown_health = (
            KNOWN_BENIGN_NAUTILUS_LOOP_STOP
            if is_known_benign_nautilus_loop_stop(exc, report)
            else TEARDOWN_FAILED
        )
        failed_report = replace(
            report,
            finished_at=dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
            teardown_health=teardown_health,
            teardown_error=failure,
            log_excerpt=(*report.log_excerpt, f"{stamp} teardown FAILED: {failure}")[
                -MAX_LOG_LINES:
            ],
        )
        return self.write(failed_report)


# ---------------------------------------------------------------------------
# Live probing
# ---------------------------------------------------------------------------


@dataclass
class TransportEvent:
    """One attempted GET, recorded whether it returns or raises."""

    url: str
    headers: Mapping[str, str]
    response: VenueResponse | None
    elapsed_ms: float
    failure_type: str | None = None


@dataclass
class RecordingTransport:
    """Wraps the GET-only transport and records what actually went on the wire.

    Exists so the evidence reports the headers that were REALLY sent rather
    than a second, separately-computed set. Failed attempts are recorded as
    their own events before the exception is re-raised, so evidence cannot
    carry forward the previous successful request's status or headers. It has
    exactly one method, so the recorded ``write_requests`` counter is
    structurally pinned at zero.
    """

    inner: PolymarketUSReadTransport
    records: list[TransportEvent] = field(default_factory=list)
    write_requests: int = 0

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> VenueResponse:
        started = time.perf_counter()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        try:
            response = await self.inner.get(url, headers=headers, quota_key=quota_key)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.records.append(
                TransportEvent(
                    url=url,
                    headers=dict(headers),
                    response=None,
                    elapsed_ms=elapsed_ms,
                    failure_type=type(exc).__name__,
                )
            )
            raise
        else:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.records.append(
                TransportEvent(
                    url=url,
                    headers=dict(headers),
                    response=response,
                    elapsed_ms=elapsed_ms,
                )
            )
            return response

    def last(self) -> TransportEvent | None:
        return self.records[-1] if self.records else None


def _record_from(
    transport: RecordingTransport,
    *,
    step: str,
    label: str,
    path: str,
    query_string: str = "",
    note: str = "",
    status_override: int | None = None,
) -> RequestRecord:
    entry = transport.last()
    if entry is None:
        return RequestRecord(
            step=step,
            label=label,
            path=path,
            query_string=query_string,
            status=status_override,
            latency_ms=0.0,
            sent_headers={},
            observed_headers={},
            note=note or "no request reached the transport",
        )
    if entry.response is None:
        return RequestRecord(
            step=step,
            label=label,
            path=path,
            query_string=query_string,
            status=status_override,
            latency_ms=entry.elapsed_ms,
            sent_headers=entry.headers,
            observed_headers={},
            note=note or f"transport failure: {entry.failure_type}",
        )
    return RequestRecord(
        step=step,
        label=label,
        path=path,
        query_string=query_string,
        status=status_override if status_override is not None else entry.response.status,
        latency_ms=entry.elapsed_ms,
        sent_headers=entry.headers,
        observed_headers=entry.response.headers,
        note=note,
    )


def _clock_offset_ms(records: Sequence[RequestRecord], *, now_ms: int | None = None) -> int | None:
    """Host clock offset against the venue's ``Date`` response header."""
    for record in records:
        raw = {k.lower(): v for k, v in record.observed_headers.items()}.get("date")
        if not raw:
            continue
        try:
            # RFC 7231 `Date`. `email.utils` is the stdlib's own parser for it
            # and returns an AWARE datetime, unlike a hand-written strptime
            # format, which silently yields a naive one and would make this
            # offset wrong by the host's UTC offset.
            venue_time = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            continue
        if venue_time.tzinfo is None:
            venue_time = venue_time.replace(tzinfo=dt.UTC)
        venue_ms = int(venue_time.timestamp() * 1000)
        return (int(time.time() * 1000) if now_ms is None else now_ms) - venue_ms
    return None


def assert_host_clock_safe_for_signing(
    records: Sequence[RequestRecord], *, now_ms: int | None = None
) -> None:
    """Refuse before signing when the venue Date header shows unsafe skew."""
    offset_ms = _clock_offset_ms(records, now_ms=now_ms)
    if offset_ms is None:
        raise SignatureClockSkewError(
            "Refusing to sign authenticated Polymarket.us requests: no valid venue "
            "Date header was measured, so host clock offset cannot be proven within "
            f"+/-{SIGNING_CLOCK_SKEW_GUARD_MS} ms."
        )
    if abs(offset_ms) > SIGNING_CLOCK_SKEW_GUARD_MS:
        raise SignatureClockSkewError(
            "Refusing to sign authenticated Polymarket.us requests: host clock "
            f"offset vs venue Date header is {offset_ms} ms, exceeding the safe "
            f"+/-{SIGNING_CLOCK_SKEW_GUARD_MS} ms guard "
            f"({SIGNING_CLOCK_SKEW_GUARD_FRACTION:.0%} of the documented "
            f"+/-{DOCUMENTED_SIGNING_WINDOW_MS} ms signing window)."
        )


def _key_file_facts(env: Mapping[str, str]) -> tuple[int | None, str | None]:
    """``st_dev`` and filesystem type of the key file (plan section 6 residual)."""
    path = env.get("POLYMARKET_US_SECRET_KEY_FILE", "").strip()
    if not path:
        return (None, None)
    try:
        stat_result = os.stat(path)
    except OSError:
        return (None, None)
    filesystem: str | None = None
    try:
        with open("/proc/mounts", encoding="utf-8") as handle:
            best = ""
            for line in handle:
                parts = line.split()
                if len(parts) >= 3 and path.startswith(parts[1]) and len(parts[1]) > len(best):
                    best, filesystem = parts[1], parts[2]
    except OSError:  # pragma: no cover - non-Linux hosts
        filesystem = None
    return (int(stat_result.st_dev), filesystem)


def _frame_schema(raw: bytes, slugs: Sequence[str]) -> FrameSchema | None:
    """Describe one frame's shape without publishing nonscalar payloads."""
    from breezy.adapters.polymarket_us.data import diagnose_frame_payload

    try:
        decoded = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    diagnostic = diagnose_frame_payload(decoded, slugs)
    return FrameSchema(
        frame_class=diagnostic.frame_class,
        keys=diagnostic.keys,
        structure_paths=diagnostic.structure_paths,
        value_types=diagnostic.value_types,
        safe_values=diagnostic.safe_values,
        slug_bearing_keys=diagnostic.slug_bearing_keys,
    )


def _frame_schema_from_diagnostic(diagnostic: Any) -> FrameSchema:
    return FrameSchema(
        frame_class=diagnostic.frame_class,
        keys=tuple(diagnostic.keys),
        structure_paths=tuple(diagnostic.structure_paths),
        value_types=dict(diagnostic.value_types),
        safe_values=dict(diagnostic.safe_values),
        slug_bearing_keys=tuple(diagnostic.slug_bearing_keys),
    )


def _count_frame_classes(schemas: Sequence[FrameSchema]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for schema in schemas:
        counts[schema.frame_class] = counts.get(schema.frame_class, 0) + 1
    return counts


async def _probe_gateway(
    client: Any, transport: RecordingTransport, slug: str
) -> tuple[RequestRecord, Finding]:
    """Step A / G15: is the public gateway reachable from a headless host?"""
    path = MARKET_BY_SLUG_PATH.format(slug=slug)
    try:
        await client.get_public(path, quota_key=QUOTA_KEY_INSTRUMENTS)
        note = "accepted"
        answer = "YES -- the public gateway answered a non-browser client."
    except PolymarketUSError as exc:
        note = f"refused: {type(exc).__name__}"
        answer = f"NO -- {type(exc).__name__}; G15 has regressed for this host/User-Agent."
    record = _record_from(transport, step="A", label="public market read", path=path, note=note)
    return record, Finding(
        key="G15",
        question="Does gateway.polymarket.us answer a non-browser client?",
        answer=answer,
    )


async def _probe_authenticated(
    client: Any, transport: RecordingTransport
) -> tuple[RequestRecord, bool]:
    """Step B: end-to-end proof that Ed25519 signing is accepted."""
    try:
        await client.get_authenticated(PORTFOLIO_PATH, quota_key=QUOTA_KEY_PORTFOLIO)
        return (
            _record_from(
                transport,
                step="B",
                label="authenticated portfolio read",
                path=PORTFOLIO_PATH,
                note="accepted",
            ),
            True,
        )
    except PolymarketUSError as exc:
        return (
            _record_from(
                transport,
                step="B",
                label="authenticated portfolio read",
                path=PORTFOLIO_PATH,
                note=f"REJECTED: {type(exc).__name__}",
            ),
            False,
        )


def classify_canonical_string_outcome(*, path_only: int | None, path_with_query: int | None) -> str:
    """Reduce the two measured statuses to one of FOUR coded shapes.

    Total by construction: every pair of statuses -- including the pair where
    neither request reached the venue at all -- lands in exactly one named
    outcome. Extracted from :func:`_probe_canonical_string` so the same coded
    vocabulary can classify a measurement taken by the R-5R-0 runner, rather
    than being re-derived (and quietly re-worded) at a second call site.
    """
    if path_only == 200 and path_with_query != 200:
        return "Path ONLY is signed; the default builder is correct."
    if path_with_query == 200 and path_only != 200:
        return (
            "The query string IS part of the canonical string; switch "
            "signing_variant to path_with_query."
        )
    if path_only == 200 and path_with_query == 200:
        return "BOTH forms were accepted; the venue does not verify the query segment."
    return f"Inconclusive: path_only={path_only}, path_with_query={path_with_query}."


async def _probe_canonical_string(
    prepared: Prepared,
    transport: RecordingTransport,
    build_client: Any,
    *,
    path: str = PORTFOLIO_PATH,
) -> tuple[list[RequestRecord], Finding]:
    """Step C: is the query string part of the signed canonical string?

    Both builders ship. The default (path-only) is the evidence-backed
    hypothesis; this measures it rather than assuming it, and records BOTH
    outcomes so "they both work" is a recordable answer rather than a failure.

    ``path`` is a CALLER argument. It was pinned to :data:`PORTFOLIO_PATH`
    until R-5R-3, which made the probe unrunnable whenever that one endpoint
    was unavailable -- exactly the state measured on 2026-09-02, when the
    portfolio path returned 503 while another private path returned 200. The
    discriminator is about the SIGNATURE, not about any particular endpoint,
    so any private path that answers at all can carry it.
    """
    from breezy.adapters.polymarket_us.signing import SigningVariant

    records: list[RequestRecord] = []
    outcomes: dict[str, int | None] = {}
    query = {"limit": "1"}
    for variant in (SigningVariant.PATH_ONLY, SigningVariant.PATH_WITH_QUERY):
        client = build_client(variant)
        try:
            await client.get_authenticated(path, query=query, quota_key=QUOTA_KEY_PORTFOLIO)
            note = "accepted"
        except PolymarketUSError as exc:
            note = f"rejected: {type(exc).__name__}"
        record = _record_from(
            transport,
            step="C",
            label=f"query-bearing read signed {variant.value}",
            path=path,
            query_string="limit=1",
            note=note,
        )
        records.append(record)
        outcomes[variant.value] = record.status

    answer = classify_canonical_string_outcome(
        path_only=outcomes.get("path_only"),
        path_with_query=outcomes.get("path_with_query"),
    )
    return records, Finding(
        key="C",
        question="Is the query string part of the signed canonical string?",
        answer=answer,
    )


async def _probe_clock_window(
    prepared: Prepared, transport: RecordingTransport, api_base_url: str
) -> RequestRecord:
    """Step D: prove the +/-30s signing window is real, not assumed."""
    from nautilus_trader.common.component import LiveClock

    from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner

    clock = LiveClock()
    # A deliberately permissive local tolerance so OUR guard does not pre-empt
    # the venue's. This signer exists only for this one probe.
    permissive = Ed25519RequestSigner(
        prepared.credentials,
        clock=clock,
        skew_tolerance_ms=STALE_TIMESTAMP_OFFSET_MS * 10,
    )
    stale_ts = clock.timestamp_ms() - STALE_TIMESTAMP_OFFSET_MS
    headers = dict(permissive.sign_headers(HTTP_METHOD, PORTFOLIO_PATH, timestamp_ms=stale_ts))
    status: int | None = None
    note = ""
    try:
        response = await transport.get(
            f"{api_base_url.rstrip('/')}{PORTFOLIO_PATH}",
            headers=headers,
            quota_key=QUOTA_KEY_PORTFOLIO,
        )
        status = response.status
        note = "rejected as expected" if status >= 400 else "ACCEPTED -- window not enforced"
    except PolymarketUSError as exc:
        note = f"transport error: {type(exc).__name__}"
    return _record_from(
        transport,
        step="D",
        label="deliberately stale timestamp (-120s)",
        path=PORTFOLIO_PATH,
        note=note,
        status_override=status,
    )


async def _probe_rate_limits(
    client: Any, transport: RecordingTransport, slug: str
) -> tuple[list[RequestRecord], Finding]:
    """Step G: does retail silently apply per-endpoint minute windows?"""
    records: list[RequestRecord] = []
    statuses: list[int | None] = []
    path = MARKET_BY_SLUG_PATH.format(slug=slug)
    for index in range(8):
        try:
            await client.get_public(path, quota_key=QUOTA_KEY_INSTRUMENTS)
            note = "accepted"
        except PolymarketUSError as exc:
            note = f"refused: {type(exc).__name__}"
        record = _record_from(
            transport,
            step="G",
            label=f"instruments burst {index + 1}/8",
            path=path,
            note=note,
        )
        records.append(record)
        statuses.append(record.status)
    throttled = [s for s in statuses if s == 429]
    if throttled:
        answer = (
            f"429 observed after {statuses.index(429) + 1} instrument-class reads "
            "inside one minute; a per-endpoint window appears to apply."
        )
    else:
        answer = (
            "No 429 across 8 instrument-class reads in one minute; the documented "
            "global 20 req/s appears to be the only retail limit observed."
        )
    return records, Finding(
        key="G",
        question="What rate-limit behaviour is actually observed on retail?",
        answer=answer,
    )


class _QuoteCounter:
    """Counts frames and quotes without holding any trading opinion."""

    def __init__(self, slugs: Sequence[str]) -> None:
        self.slugs = tuple(slugs)
        self.frames: list[bytes] = []
        self.schemas: list[FrameSchema] = []
        self.log: list[str] = []

    def note(self, message: str) -> None:
        stamp = dt.datetime.now(tz=dt.UTC).strftime("%H:%M:%SZ")
        self.log.append(f"{stamp} {message}")

    def on_frame(self, raw: bytes) -> None:
        self.frames.append(raw)
        if len(self.schemas) < MAX_FRAME_SCHEMAS:
            schema = _frame_schema(raw, self.slugs)
            if schema is not None:
                self.schemas.append(schema)


async def _probe_public_websocket(
    config: Any, counter: _QuoteCounter, loop: asyncio.AbstractEventLoop
) -> Finding:
    """Step E1: does ``/v1/ws/markets`` require authentication at all?"""
    from nautilus_trader.common.component import Logger

    from breezy.adapters.polymarket_us.websocket import PolymarketUSMarketsWebSocket

    socket = PolymarketUSMarketsWebSocket(
        ws_url=str(config.ws_url),
        signer=None,
        handler=counter.on_frame,
        loop=loop,
        heartbeat_secs=config.ws_heartbeat_secs,
        idle_timeout_secs=config.ws_idle_timeout_secs,
        logger=Logger("smoke-ws-public"),
        reconnect_max_attempts=0,
    )
    try:
        await socket.connect()
    except Exception as exc:  # noqa: BLE001 - the outcome IS the measurement
        counter.note(f"unauthenticated markets WS connect failed: {type(exc).__name__}")
        return Finding(
            key="E1",
            question="Does /v1/ws/markets require authentication?",
            answer=(
                f"YES -- an unauthenticated connect failed with "
                f"{type(exc).__name__}. Breezy-owned reconnect (plan 5.3b) is required."
            ),
        )
    counter.note("unauthenticated markets WS connect succeeded")
    with contextlib.suppress(Exception):
        await socket.close()
    return Finding(
        key="E1",
        question="Does /v1/ws/markets require authentication?",
        answer=(
            "NO -- an unauthenticated connect succeeded. The native pyo3 reconnect "
            "can be left enabled and WS_MARKETS_REQUIRES_AUTH should be set False."
        ),
    )


def _slug_finding(schemas: Sequence[FrameSchema]) -> Finding:
    from breezy.adapters.polymarket_us.data import MARKET_SLUG_KEY

    if not schemas:
        answer = (
            "UNRESOLVED -- no market-data frame was captured, so the slug field "
            f"name remains the guess {MARKET_SLUG_KEY!r}."
        )
    else:
        observed = sorted({key for schema in schemas for key in schema.slug_bearing_keys})
        keys = sorted({key for schema in schemas for key in schema.keys})
        if observed:
            answer = (
                f"Slug-bearing key(s) observed: {', '.join(observed)}. "
                f"Current guess is {MARKET_SLUG_KEY!r}. Frame keys: {', '.join(keys)}."
            )
        else:
            answer = (
                "No frame field matched a configured slug verbatim. "
                f"Frame keys observed: {', '.join(keys)}. Current guess "
                f"{MARKET_SLUG_KEY!r} is unconfirmed."
            )
    return Finding(
        key="SLUG",
        question="What is the market-slug field name in a market-data frame?",
        answer=answer,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument(
        "--quote-window-secs",
        type=float,
        default=DEFAULT_QUOTE_WINDOW_SECS,
        help="How long to stream quotes through the TradingNode.",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=EVIDENCE_DIRECTORY,
        help="Where to write the evidence artefact.",
    )
    parser.add_argument(
        "--skip-rate-limit-probe",
        action="store_true",
        help="Skip step G (the deliberate read burst).",
    )
    parser.add_argument(
        "--canonical-probe-path",
        default=PORTFOLIO_PATH,
        help=(
            "Private path step C signs against (R-5R-3). Defaults to the "
            "portfolio path; re-point it at any private path that answers "
            "when that one does not."
        ),
    )
    return parser.parse_args(argv)


async def run_smoke(
    prepared: Prepared,
    args: argparse.Namespace,
    *,
    checkpoint: EvidenceCheckpoint | None = None,
) -> SmokeReport:
    """Execute steps A-G and build the report. GET-only throughout."""
    from nautilus_trader.common.component import LiveClock, Logger

    from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
    from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner, SigningVariant
    from breezy.adapters.polymarket_us.transport import (
        NautilusHttpTransport,
        build_default_quota,
        build_keyed_quotas,
    )

    config = prepared.config
    started_at = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
    loop = asyncio.get_running_loop()
    clock = LiveClock()
    counter = _QuoteCounter(config.market_slugs)
    counter.note("smoke run started")
    secrets = [
        prepared.credentials.secret_key.get_value(),
        prepared.credentials.key_id.get_value(),
    ]
    previous_loop_handler = loop.get_exception_handler()
    loop.set_exception_handler(build_safe_loop_exception_handler(counter, secrets))

    inner = NautilusHttpTransport(
        timeout_secs=config.http_timeout_secs,
        default_quota=build_default_quota(config.global_requests_per_second),
        keyed_quotas=build_keyed_quotas(
            instrument_requests_per_minute=config.instrument_requests_per_minute,
            book_requests_per_minute=config.book_requests_per_minute,
        ),
        default_headers={"User-Agent": str(config.user_agent)},
    )
    transport = RecordingTransport(inner=inner)

    def build_client(variant: SigningVariant) -> Any:
        return PolymarketUSHttpClient(
            transport=transport,
            signer=Ed25519RequestSigner.for_variant(
                prepared.credentials, clock=clock, variant=variant
            ),
            api_base_url=str(config.api_base_url),
            gateway_base_url=str(config.gateway_base_url),
            logger=Logger("smoke-http"),
        )

    client = build_client(SigningVariant(config.signing_variant))
    records: list[RequestRecord] = []
    findings: list[Finding] = []
    first_slug = config.market_slugs[0]
    authenticated_ok = False
    instrument_ids: list[str] = []
    quotes_per_slug: dict[str, int] = {slug: 0 for slug in config.market_slugs}
    node_failure: str | None = None
    node_frame_schemas: tuple[FrameSchema, ...] = ()
    node_frame_class_counts: dict[str, int] = {}

    def build_report(*, reason: str | None = None) -> SmokeReport:
        quotes_delivered = sum(quotes_per_slug.values())
        verdict = authenticated_ok and quotes_delivered > 0 and node_failure is None
        resolved_reason = reason or verdict_reason_for(
            authenticated_ok=authenticated_ok,
            quotes_delivered=quotes_delivered,
            node_failure=node_failure,
        )
        all_frame_schemas = (*counter.schemas, *node_frame_schemas)
        frame_counts = _count_frame_classes(all_frame_schemas)
        for frame_class, count in node_frame_class_counts.items():
            frame_counts[frame_class] = max(frame_counts.get(frame_class, 0), count)
        device, filesystem = _key_file_facts(os.environ)
        return SmokeReport(
            started_at=started_at,
            finished_at=dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
            core_limit=prepared.core_limit,
            key_file_device=device,
            key_file_filesystem=filesystem,
            host_clock_offset_ms=_clock_offset_ms(records),
            user_agent=str(config.user_agent),
            api_base_url=str(config.api_base_url),
            gateway_base_url=str(config.gateway_base_url),
            ws_url=str(config.ws_url),
            market_slugs=tuple(config.market_slugs),
            requests=tuple(records),
            findings=tuple(findings),
            frame_schemas=all_frame_schemas,
            frame_class_counts=frame_counts,
            instrument_ids=tuple(instrument_ids),
            frames_received=len(counter.frames) + len(node_frame_schemas),
            quotes_delivered=quotes_delivered,
            quotes_per_slug=quotes_per_slug,
            log_excerpt=tuple(counter.log[-MAX_LOG_LINES:]),
            write_requests_issued=transport.write_requests,
            verdict=verdict,
            verdict_reason=resolved_reason,
        )

    def checkpoint_now(reason: str) -> None:
        if checkpoint is not None:
            checkpoint.write(build_report(reason=reason))

    try:
        gateway_record, gateway_finding = await _probe_gateway(client, transport, first_slug)
        records.append(gateway_record)
        findings.append(gateway_finding)
        counter.note(f"step A gateway status={gateway_record.status}")
        checkpoint_now("Smoke run in progress: gateway reachability has been checkpointed.")
        assert_host_clock_safe_for_signing(records)
        counter.note(f"host clock offset accepted: {_clock_offset_ms(records)} ms")

        auth_record, authenticated_ok = await _probe_authenticated(client, transport)
        records.append(auth_record)
        counter.note(f"step B authenticated status={auth_record.status}")
        checkpoint_now("Smoke run in progress: authenticated read has been checkpointed.")

        canonical_records, canonical_finding = await _probe_canonical_string(
            prepared, transport, build_client, path=args.canonical_probe_path
        )
        records.extend(canonical_records)
        findings.append(canonical_finding)
        checkpoint_now("Smoke run in progress: canonical-string probe has been checkpointed.")

        records.append(await _probe_clock_window(prepared, transport, str(config.api_base_url)))
        counter.note("step D stale-timestamp probe complete")
        checkpoint_now("Smoke run in progress: stale-timestamp probe has been checkpointed.")

        findings.append(await _probe_public_websocket(config, counter, loop))
        checkpoint_now("Smoke run in progress: public WebSocket probe has been checkpointed.")

        def on_node_observation(
            observed_instruments: list[str],
            observed_quotes: dict[str, int],
            observed_failure: str | None,
            observed_frames: tuple[FrameSchema, ...],
            observed_counts: dict[str, int],
        ) -> None:
            nonlocal instrument_ids, quotes_per_slug, node_failure
            nonlocal node_frame_schemas, node_frame_class_counts
            instrument_ids = observed_instruments
            quotes_per_slug = observed_quotes
            node_failure = observed_failure
            node_frame_schemas = observed_frames
            node_frame_class_counts = observed_counts
            checkpoint_now("Smoke run in progress: node observation window has been checkpointed.")

        (
            instrument_ids,
            quotes_per_slug,
            node_failure,
            node_frame_schemas,
            node_frame_class_counts,
        ) = await _run_node(
            config,
            counter,
            args.quote_window_secs,
            secrets,
            on_observation=on_node_observation,
        )

        if not args.skip_rate_limit_probe:
            burst_records, burst_finding = await _probe_rate_limits(client, transport, first_slug)
            records.extend(burst_records)
            findings.append(burst_finding)
            checkpoint_now("Smoke run in progress: rate-limit probe has been checkpointed.")

        findings.append(_slug_finding((*counter.schemas, *node_frame_schemas)))

        final_report = build_report()
        counter.note(f"smoke run finished: {'PASS' if final_report.verdict else 'FAIL'}")
        final_report = replace(build_report(), teardown_health=TEARDOWN_OK)
        checkpoint_now(final_report.verdict_reason)
        return final_report
    finally:
        loop.set_exception_handler(previous_loop_handler)


def verdict_reason_for(
    *, authenticated_ok: bool, quotes_delivered: int, node_failure: str | None
) -> str:
    """Compose the verdict so the first-run failure modes stay distinguishable.

    "auth failed", "the node never started" and "no quotes arrived" all
    previously rendered as the same FAIL string, and the last two are also what
    a genuinely quiet market looks like. ``node_failure`` is checked FIRST
    because a node that died explains a zero quote count, and reporting the
    zero instead of the cause is what buried the diagnostic.
    """
    if node_failure is not None:
        return (
            "The Nautilus TradingNode did not survive the observation window, so "
            f"the quote count proves nothing. Underlying failure -- {node_failure}"
        )
    if not authenticated_ok:
        return (
            "The authenticated read was refused by the venue; signing is not "
            "yet proven. See step B and the clock-offset row."
        )
    if quotes_delivered == 0:
        return (
            "Ed25519 signing was accepted and the node ran cleanly, but no "
            "QuoteTick reached the DataEngine. Connectivity is authenticated "
            "but NOT proven end to end; the market may simply be quiet."
        )
    return (
        "An authenticated GET was accepted by api.polymarket.us and real "
        f"QuoteTicks ({quotes_delivered}) reached the Nautilus DataEngine."
    )


def describe_exception(exc: BaseException, secrets: Sequence[str]) -> str:
    """Render ``exc`` as ``TypeName: scrubbed message``.

    The one seam every diagnostic goes through, so scrubbing cannot be
    forgotten at a call site. Two layers, in order: :func:`redact_text` masks
    each known secret literally, then :func:`find_secret_leak_offsets` re-checks
    the RESULT for any four-character fragment. If anything survives, the
    message is dropped -- but the TYPE is always kept, because the type is what
    tells the operator *what* failed and it can never contain a secret.
    """
    scrubbed = redact_text(str(exc), secrets)
    if find_secret_leak_offsets(scrubbed, secrets):
        scrubbed = "<message withheld: secret-derived material survived redaction>"
    return f"{type(exc).__name__}: {scrubbed}"


def is_known_benign_nautilus_loop_stop(exc: BaseException, report: SmokeReport) -> bool:
    """Whether ``exc`` is the named Nautilus asyncio-run teardown race.

    This label is deliberately narrow: it only applies after connectivity has
    already been proven by the checkpointed report, and only to the exact loop
    stop RuntimeError observed from Nautilus 1.231.0 disposal under
    ``asyncio.run``.
    """
    return (
        report.verdict
        and type(exc) is RuntimeError
        and str(exc) == "Event loop stopped before Future completed."
    )


async def drain_node_task(
    task: asyncio.Task[None], counter: _QuoteCounter, secrets: Sequence[str]
) -> str | None:
    """Cancel the node task and return its failure, if it had one.

    ``node.run_async()`` is fire-and-forget, so without this nothing ever
    observes an exception raised inside it: the operator sees
    ``quotes_delivered == 0`` and a generic FAIL, which is indistinguishable
    from a quiet market. The operator's FIRST live run is the most likely place
    to hit exactly that, so the exception is captured, scrubbed, logged into
    the evidence excerpt, and returned for the verdict.

    A cancellation is NOT a failure: cancelling is how the observation window
    ends normally.
    """
    if not task.done():
        # Yield once first. A task that is ALREADY doomed but has not been
        # stepped yet would otherwise be cancelled before it could raise, and
        # its cancellation would then be misread as a clean shutdown -- turning
        # the exact failure this function exists to surface back into silence.
        await asyncio.sleep(0)
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return None
    except BaseException as exc:  # noqa: BLE001 - the whole point is to observe it
        failure = describe_exception(exc, secrets)
        counter.note(f"node task FAILED: {failure}")
        return failure
    return None


async def _run_node(
    config: Any,
    counter: _QuoteCounter,
    window_secs: float,
    secrets: Sequence[str],
    *,
    on_observation: Callable[
        [list[str], dict[str, int], str | None, tuple[FrameSchema, ...], dict[str, int]], None
    ]
    | None = None,
) -> tuple[list[str], dict[str, int], str | None, tuple[FrameSchema, ...], dict[str, int]]:
    """Steps E2 and F: run a minimal ``TradingNode`` and count real quotes.

    Counting inside an ``Actor`` is what makes this a proof: the tick has
    already traversed the client, the ``DataEngine`` and the ``MessageBus``
    by the time the counter sees it.
    """
    from nautilus_trader.common.actor import Actor
    from nautilus_trader.config import LoggingConfig, TradingNodeConfig
    from nautilus_trader.live.node import TradingNode
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.identifiers import ClientId, TraderId

    from breezy.adapters.polymarket_us.data import PolymarketUSDataClient, frame_class_counts
    from breezy.adapters.polymarket_us.factories import PolymarketUSLiveDataClientFactory
    from breezy.adapters.polymarket_us.symbology import slug_to_instrument_id

    per_slug: dict[str, int] = {slug: 0 for slug in config.market_slugs}
    frame_schemas: tuple[FrameSchema, ...] = ()
    class_counts: dict[str, int] = {}

    class QuoteWitness(Actor):
        def on_start(self) -> None:
            for slug in config.market_slugs:
                self.subscribe_quote_ticks(slug_to_instrument_id(slug))
            counter.note("witness subscribed to every configured slug")

        def on_quote_tick(self, tick: QuoteTick) -> None:
            slug = str(tick.instrument_id.symbol.value)
            per_slug[slug] = per_slug.get(slug, 0) + 1

    node_config = TradingNodeConfig(
        trader_id=TraderId("BREEZY-SMOKE-001"),
        logging=LoggingConfig(log_level="INFO"),
        data_clients={POLYMARKET_US_CLIENT_NAME: config},
    )
    node = TradingNode(config=node_config)
    node.add_data_client_factory(POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveDataClientFactory)
    node.build()
    node.trader.add_actor(QuoteWitness())

    instrument_ids: list[str] = []
    node_failure: str | None = None
    task = asyncio.create_task(node.run_async())
    try:
        await asyncio.sleep(window_secs)
        instrument_ids = [str(i.id) for i in node.kernel.cache.instruments()]
        counter.note(f"node observed {len(instrument_ids)} instrument(s)")
        client = node.kernel.data_engine._clients.get(ClientId(POLYMARKET_US_CLIENT_NAME))
        if isinstance(client, PolymarketUSDataClient):
            diagnostics = client.frame_diagnostics
            frame_schemas = tuple(_frame_schema_from_diagnostic(item) for item in diagnostics)
            class_counts = frame_class_counts(diagnostics)
            counter.note(f"node captured {len(frame_schemas)} authenticated frame diagnostic(s)")
        if on_observation is not None:
            on_observation(
                instrument_ids,
                dict(per_slug),
                node_failure,
                frame_schemas,
                class_counts,
            )
    except BaseException as exc:  # recorded, then re-raised below
        node_failure = describe_exception(exc, secrets)
        counter.note(f"observation window FAILED: {node_failure}")
        raise
    finally:
        # Shutdown errors are NOTED rather than suppressed. They were three
        # back-to-back `suppress(Exception)` blocks, which is exactly how a
        # real startup failure produced no diagnostic at all.
        try:
            await node.stop_async()
        except BaseException as exc:  # noqa: BLE001
            counter.note(f"node.stop_async() failed: {describe_exception(exc, secrets)}")

        drained = await drain_node_task(task, counter, secrets)
        node_failure = node_failure or drained

        try:
            node.dispose()
        except BaseException as exc:  # noqa: BLE001
            counter.note(f"node.dispose() failed: {describe_exception(exc, secrets)}")
        if on_observation is not None:
            on_observation(
                instrument_ids,
                dict(per_slug),
                node_failure,
                frame_schemas,
                class_counts,
            )
    return instrument_ids, per_slug, node_failure, frame_schemas, class_counts


#: Exit code for an unanticipated failure inside the live run.
EXIT_UNEXPECTED: Final[int] = 3

#: Connectivity was proven, but Nautilus 1.231.0 hit its known loop-stop
#: teardown race after evidence checkpointing.
EXIT_KNOWN_BENIGN_TEARDOWN: Final[int] = 4

#: Exit code for an operator interrupt (matches the shell's 128+SIGINT).
EXIT_INTERRUPTED: Final[int] = 130


#: Printed when the failure happened before any credential read began. The
#: reason is a fact about the process, not a guess.
PRE_CREDENTIAL_SUPPRESSION_NOTE: Final[str] = (
    "Stack trace suppressed; the message above is shown because this failure "
    "occurred before any credential read began. It was still scrubbed through "
    "the redaction seam."
)

#: Printed once a credential read has begun. "May hold" is deliberate: the
#: guard arms immediately BEFORE the read, so if the read itself is what
#: failed, no secret was ever successfully loaded -- and the sentence is still
#: true. The previous unconditional wording ("holds an Ed25519 secret in
#: memory") was false for every configuration-stage failure.
POST_CREDENTIAL_SUPPRESSION_NOTE: Final[str] = (
    "Message and traceback are suppressed because a credential read has begun "
    "and this process may hold an Ed25519 secret in memory."
)


def build_safe_excepthook(guard: CredentialGuard) -> Callable[..., None]:
    """Return a ``sys.excepthook`` replacement that can never print a secret.

    Belt-and-braces behind the catch-all in :func:`main`. It is installed
    BEFORE :func:`prepare` reads a credential -- at install time there is no
    secret list to scrub against, and a hook whose safety depends on state it
    may not have yet is not a guard. That reasoning is preserved. What changed
    is that the hook no longer has to GUESS which state it is in: ``guard``
    records whether a credential read has begun.

    * **Before** the read: the exception type AND its message are printed,
      routed through :func:`describe_exception` so the single redaction seam
      still applies. There is no secret in the process to leak, and the
      withheld detail -- typically which environment variable is unset -- is
      exactly what an operator needs on a first run.
    * **After** the read begins: type name only, unchanged. This is the
      conservative branch and it is deliberately not weakened.

    The traceback is suppressed in BOTH branches, because a rendered traceback
    carries every frame's locals in chained contexts -- and ``main``'s own
    frame holds the plaintext Ed25519 secret.

    ``guard`` is a required parameter on purpose: a default would let a call
    site silently obtain the permissive branch by omission.

    Covers only the main thread. A background thread raising through its own
    bootstrap goes to ``threading.excepthook``; the ``TradingNode`` task in this
    script is an asyncio task inside :func:`asyncio.run`, so its exception
    surfaces through the awaited task in :func:`main`'s try block, not here.
    """

    def _hook(
        exc_type: type[BaseException],
        exc: BaseException,
        traceback_obj: object,
    ) -> None:
        if guard.credential_read_begun:
            print(
                f"FATAL (uncaught): {exc_type.__name__}. {POST_CREDENTIAL_SUPPRESSION_NOTE}",
                file=sys.stderr,
            )
            return

        # No credential has been read, so there is no secret list -- and an
        # empty one is the honest argument. It still goes through
        # `describe_exception` rather than around it, so any future tightening
        # of the redaction policy reaches this path by construction.
        try:
            described = describe_exception(exc, ())
        except Exception:  # noqa: BLE001 - a broken __str__ must not blind us
            print(
                f"FATAL (uncaught): {exc_type.__name__}. The message could not "
                "be rendered; stack trace suppressed. No credential had been "
                "read.",
                file=sys.stderr,
            )
            return

        print(f"FATAL (uncaught): {described}", file=sys.stderr)
        print(PRE_CREDENTIAL_SUPPRESSION_NOTE, file=sys.stderr)

    return _hook


def build_safe_loop_exception_handler(
    counter: _QuoteCounter, secrets: Sequence[str]
) -> Callable[[asyncio.AbstractEventLoop, dict[str, Any]], None]:
    """Return an asyncio exception handler that records, but never tracebacks.

    The default asyncio handler prints the callback traceback directly. That
    bypasses :func:`build_safe_excepthook`, so after credentials are loaded it
    is another secret-bearing diagnostic surface and must be controlled here.
    """

    def _handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        del loop
        exc = context.get("exception")
        if isinstance(exc, BaseException):
            detail = describe_exception(exc, secrets)
        else:
            raw = str(context.get("message", "unhandled asyncio callback exception"))
            detail = redact_text(raw, secrets)
            if find_secret_leak_offsets(detail, secrets):
                detail = "<message withheld: secret-derived material survived redaction>"
        counter.note(f"asyncio loop exception: {detail}")

    return _handler


def report_fatal(exc: BaseException, secrets: Sequence[str]) -> None:
    """Print a scrubbed, traceback-free description of an unexpected failure.

    Two layers, in this order: :func:`redact_text` masks each known secret
    literally, then :func:`find_secret_leak_offsets` re-checks the RESULT for
    any four-character fragment. If anything survives, the message is dropped
    entirely rather than published -- the operator keeps the exception type,
    which is what actually identifies the fault, and loses only prose.
    """
    print(f"UNEXPECTED FAILURE: {describe_exception(exc, secrets)}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Operator entrypoint. Returns 0 only when connectivity is proven."""
    # Installed before ANY credential is read, so no window exists in which the
    # default traceback-printing hook is live while a secret is in memory. The
    # SAME guard instance is handed to `prepare()`, which arms it immediately
    # before the credential read -- so the hook's stated reason for suppressing
    # a message is a fact about this process, never an assumption.
    guard = CredentialGuard()
    sys.excepthook = build_safe_excepthook(guard)

    args = _parse_args(argv)
    try:
        prepared = prepare(guard=guard)
    except SmokeRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except PolymarketUSError as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        return 2

    secrets = [
        prepared.credentials.secret_key.get_value(),
        prepared.credentials.key_id.get_value(),
    ]

    # Everything below holds plaintext credentials in a live frame. `except
    # Exception` is not enough: `KeyboardInterrupt` and `SystemExit` derive
    # from `BaseException` and would otherwise unwind to the excepthook.
    checkpoint = EvidenceCheckpoint(secrets=secrets, directory=args.evidence_dir)

    try:
        report = asyncio.run(run_smoke(prepared, args, checkpoint=checkpoint))
        path = write_evidence(report, secrets=secrets, directory=args.evidence_dir)
    except KeyboardInterrupt:
        print("INTERRUPTED by operator; no evidence written.", file=sys.stderr)
        return EXIT_INTERRUPTED
    except SignatureClockSkewError as exc:
        print(f"REFUSED: {describe_exception(exc, secrets)}", file=sys.stderr)
        if checkpoint.latest_path is not None:
            print(f"Checkpoint evidence: {checkpoint.latest_path}", file=sys.stderr)
        return 2
    except BaseException as exc:  # noqa: BLE001 - deliberate last line of defence
        known_teardown = (
            checkpoint.latest_report is not None
            and is_known_benign_nautilus_loop_stop(exc, checkpoint.latest_report)
        )
        checkpoint_path = checkpoint.write_unexpected_failure(exc)
        if known_teardown:
            print(
                f"TEARDOWN HEALTH: {KNOWN_BENIGN_NAUTILUS_LOOP_STOP}: "
                f"{describe_exception(exc, secrets)}",
                file=sys.stderr,
            )
        else:
            report_fatal(exc, secrets)
        if checkpoint_path is not None:
            print(f"Checkpoint evidence: {checkpoint_path}", file=sys.stderr)
        return EXIT_KNOWN_BENIGN_TEARDOWN if known_teardown else EXIT_UNEXPECTED

    print()
    print("=" * 72)
    print(f"Polymarket.us authenticated connectivity: {'PASS' if report.verdict else 'FAIL'}")
    print(f"  {report.verdict_reason}")
    print()
    print("Findings (live-only questions):")
    for finding in report.findings:
        print(f"  [{finding.key}] {finding.question}")
        print(f"      -> {finding.answer}")
    print()
    print(f"Instruments loaded : {len(report.instrument_ids)}")
    print(f"Frames received    : {report.frames_received}")
    print(f"QuoteTicks         : {report.quotes_delivered}")
    print(f"Write requests     : {report.write_requests_issued}")
    print(f"Teardown health    : {report.teardown_health}")
    print(f"Evidence           : {path}")
    print("=" * 72)
    return 0 if report.verdict else 1


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
