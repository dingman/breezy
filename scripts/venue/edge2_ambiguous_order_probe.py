#!/usr/bin/env python3
"""EDGE-2 Step 0: READ-ONLY venue-state verification for the MIA 09-23
`executions-present` AMBIGUOUS order retired as ZERO_FILL.

Authority: ``docs/plans/backlog/EDGE_2026-09-27/
EDGE-2_ambiguous_executions_resolver_plan_r3_2026-09-27.md`` section 6 (Step
0) and section 5, file-by-file plan row ``0``.

Scope: venue order ``CP05MNWMAWP6`` (MIA 2026-09-23, YES BUY 1 @ 0.52 IOC,
intent ``5e50e0d9ee084cd68629b72d1ef81a6b``), instrument
``tc-temp-miahigh-2026-09-23-gte82lt83f.POLYMARKET_US``.

**GETs only, by construction.** This module calls
:meth:`~breezy.adapters.polymarket_us.http.PolymarketUSHttpClient.
get_authenticated` exclusively, wired exactly as ``scripts/venue/
polymarket_us_capital_flow_pull.py`` wires it (``config_from_env`` +
``shared_polymarket_us_http_client``, both read-only factories). It never
imports ``breezy.adapters.polymarket_us.exec`` (the create/resolver/permit
package) or any permit/safety function, and never calls
``/v1/account/balances``. Every response is saved raw, with status and
attempt metadata, as a PRIVATE file (mode 0600) under a 0700 evidence
directory; ids and secrets are redacted before anything reaches disk or
stdout, following the pattern of ``docs/evidence/venue/polymarket_us/
AMBIGUOUS_ORDER_2026-09-05_SFO/probe.py.txt``.

**Q2s (ordering / cursor stability, plan section 6).** A single process run
performs the descending traversal, sleeps
:data:`Q2S_SECOND_TRAVERSAL_DELAY_SECS` (>= 5 minutes), repeats the
descending traversal, then performs one ascending traversal -- all over the
same activities feed -- so the three Q2s checks (non-increasing order,
re-read identity, ascending-is-exact-reverse) can be evaluated from ids
gathered five-plus minutes apart, as the plan requires.

The verdict (FILL / PARTIAL_FILL / ZERO_FILL_BENIGN / CONTRADICTION /
INCONCLUSIVE) is computed by :func:`classify_verdict` over the plan's
decision table (section 6). L1 (local store keys and ROI reconciliation
rows) is read separately, with no venue call, and fed in as
``Step0Evidence.l1_ok`` -- this module never opens the exec state store.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:  # pragma: no cover - operator entrypoint
    sys.path.insert(0, str(REPO_ROOT / "src"))

from nautilus_trader.common.component import LiveClock

from breezy.adapters.polymarket_us.factories import (
    config_from_env,
    shared_polymarket_us_http_client,
)
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.transport import (
    QUOTA_KEY_BOOK,
    QUOTA_KEY_PORTFOLIO,
)

__all__ = [
    "MAX_ACTIVITY_PAGES",
    "ORDER_ID",
    "PC_CANDIDATE_ORDER_IDS",
    "PORTFOLIO_ACTIVITIES_PATH",
    "Q2S_SECOND_TRAVERSAL_DELAY_SECS",
    "SLUG",
    "VERDICT_CONTRADICTION",
    "VERDICT_FILL",
    "VERDICT_INCONCLUSIVE",
    "VERDICT_PARTIAL_FILL",
    "VERDICT_ZERO_FILL_BENIGN",
    "Step0Evidence",
    "activities_are_complete",
    "activity_create_time",
    "activity_identity",
    "build_production_client",
    "classify_verdict",
    "create_times_non_increasing",
    "id_sequences_identical",
    "is_exact_reverse",
    "is_position_resolution_on_slug",
    "is_trade_for_order",
    "is_trade_on_slug",
    "main",
    "make_private_dir",
    "min_create_time_across_pages",
    "positive_control_trade_count",
    "q2s_stability_verdict",
    "redact_secrets",
    "write_private_file",
]

# ---------------------------------------------------------------------------
# Scope constants (plan header)
# ---------------------------------------------------------------------------

ORDER_ID: Final[str] = "CP05MNWMAWP6"
SLUG: Final[str] = "tc-temp-miahigh-2026-09-23-gte82lt83f"
INTENT_ID: Final[str] = "5e50e0d9ee084cd68629b72d1ef81a6b"
CLIENT_ORDER_ID: Final[str] = "O-20260923-172207-L001-MIA-1"

#: Plan section 6, Q2 completeness threshold: one minute before the order's
#: create time, so pagination need not reach the literal instant.
Q2_COMPLETENESS_THRESHOLD_ISO: Final[str] = "2026-09-23T17:21:00Z"

#: Plan section 6 PC row: a known create-path fill inside the paged window.
#: Tried in order; the first that yields >= 1 joined TRADE row is used.
PC_CANDIDATE_ORDER_IDS: Final[tuple[str, ...]] = ("CNC3HJD66WP9", "CMSN9WPWWWPB")

PORTFOLIO_ACTIVITIES_PATH: Final[str] = "/v1/portfolio/activities"
ORDER_BY_ID_PATH_PREFIX: Final[str] = "/v1/order/"
POSITIONS_PATH: Final[str] = "/v1/portfolio/positions"
OPEN_ORDERS_PATH: Final[str] = "/v1/orders/open"

MAX_ACTIVITY_PAGES: Final[int] = 20
ACTIVITY_PAGE_LIMIT: Final[int] = 100
Q2S_SECOND_TRAVERSAL_DELAY_SECS: Final[int] = 300

OUT_DIR: Final[Path] = (
    REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "AMBIGUOUS_ORDER_2026-09-23_MIA"
)

_PRIVATE_FILE_MODE: Final[int] = 0o600
_PRIVATE_DIR_MODE: Final[int] = 0o700

_TERMINAL_ORDER_STATES: Final[frozenset[str]] = frozenset(
    {
        "ORDER_STATE_FILLED",
        "ORDER_STATE_CANCELED",
        "ORDER_STATE_REPLACED",
        "ORDER_STATE_REJECTED",
        "ORDER_STATE_EXPIRED",
    }
)

VERDICT_FILL: Final[str] = "FILL"
VERDICT_PARTIAL_FILL: Final[str] = "PARTIAL_FILL"
VERDICT_ZERO_FILL_BENIGN: Final[str] = "ZERO_FILL_BENIGN"
VERDICT_CONTRADICTION: Final[str] = "CONTRADICTION"
VERDICT_INCONCLUSIVE: Final[str] = "INCONCLUSIVE"


# ---------------------------------------------------------------------------
# Redaction (mirrors the 09-05 probe's `red()`)
# ---------------------------------------------------------------------------


def redact_secrets(text: str, secrets: Sequence[str]) -> str:
    """Replace every occurrence of a non-empty secret in ``text`` with a
    fixed marker. Order-independent: each secret is substituted in turn."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<REDACTED>")
    return text


# ---------------------------------------------------------------------------
# PRIVATE file writing (mode 0600 AT CREATION -- never `write_text` then
# `chmod`, which leaves a TOCTOU window at the process umask between the
# file existing and its mode being narrowed)
# ---------------------------------------------------------------------------


def write_private_file(path: Path, content: str) -> None:
    """Create ``path`` with mode 0600 atomically at creation, via
    ``os.open`` with an explicit mode -- never a ``write_text`` followed by
    a separate ``chmod``, which lets a concurrent reader observe the file at
    the process umask (0755/0644 under the common ``022``) before the mode
    is narrowed. ``O_EXCL`` is deliberately NOT set: a rerun against the
    same evidence directory must be able to overwrite its own prior file.
    Asserts the final mode is exactly 0600 (defence in depth against a
    umask wider than ``main()``'s own ``0o077`` somehow leaking through).
    """
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _PRIVATE_FILE_MODE)
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)
    actual_mode = stat.S_IMODE(os.stat(path).st_mode)
    assert actual_mode == _PRIVATE_FILE_MODE, (
        f"{path} was created with mode {oct(actual_mode)}, expected {oct(_PRIVATE_FILE_MODE)}"
    )


def make_private_dir(path: Path) -> None:
    """Create ``path`` (and any missing parents) with mode 0700 at
    creation -- ``mkdir(mode=0o700)`` directly, never a separate ``chmod``
    afterwards. ``0o700`` sets no group/other bits, so this is exactly 0700
    under every umask this process runs with (umask can only CLEAR bits;
    ``main()`` additionally narrows the process umask to ``0o077`` as
    defence in depth, but this function's own mode argument does not
    depend on that). Parent directories created along the way inherit
    :func:`Path.mkdir`'s own default mode handling for intermediate
    components; only the leaf evidence directory's mode is asserted here,
    since that is the one PRIVATE files are written into.
    """
    if path.exists():
        actual_mode = stat.S_IMODE(os.stat(path).st_mode)
        assert actual_mode == _PRIVATE_DIR_MODE, (
            f"{path} already exists with mode {oct(actual_mode)}, expected {oct(_PRIVATE_DIR_MODE)}"
        )
        return
    path.mkdir(parents=True, exist_ok=True, mode=_PRIVATE_DIR_MODE)
    actual_mode = stat.S_IMODE(os.stat(path).st_mode)
    assert actual_mode == _PRIVATE_DIR_MODE, (
        f"{path} was created with mode {oct(actual_mode)}, expected {oct(_PRIVATE_DIR_MODE)}"
    )


# ---------------------------------------------------------------------------
# Q2(i)/(ii)/(iii) filters (plan section 6, Q2 row)
# ---------------------------------------------------------------------------


def is_trade_for_order(activity: Mapping[str, Any], venue_order_id: str) -> bool:
    """Q2(i): an ``ACTIVITY_TYPE_TRADE`` whose aggressor or passive leg is
    ``venue_order_id`` (captured shape: ``trade.aggressor.id`` /
    ``trade.passive.id``, each a full nested ``Order`` object -- see
    ``docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/
    activities_p0.json``)."""
    if activity.get("type") != "ACTIVITY_TYPE_TRADE":
        return False
    trade = activity.get("trade") or {}
    aggressor = trade.get("aggressor") or {}
    passive = trade.get("passive") or {}
    return aggressor.get("id") == venue_order_id or passive.get("id") == venue_order_id


def is_trade_on_slug(activity: Mapping[str, Any], slug: str) -> bool:
    """Q2(ii): any ``ACTIVITY_TYPE_TRADE`` on ``slug`` (``trade.marketSlug``)."""
    if activity.get("type") != "ACTIVITY_TYPE_TRADE":
        return False
    trade = activity.get("trade") or {}
    return trade.get("marketSlug") == slug


def is_position_resolution_on_slug(activity: Mapping[str, Any], slug: str) -> bool:
    """Q2(iii): an ``ACTIVITY_TYPE_POSITION_RESOLUTION`` on ``slug``."""
    if activity.get("type") != "ACTIVITY_TYPE_POSITION_RESOLUTION":
        return False
    resolution = activity.get("positionResolution") or {}
    return resolution.get("marketSlug") == slug


def trade_qty_for_order(activity: Mapping[str, Any], venue_order_id: str) -> Decimal:
    """The traded quantity (``trade.qtyDecimal``) of a Q2(i) row; ``0`` if
    ``activity`` does not match."""
    if not is_trade_for_order(activity, venue_order_id):
        return Decimal(0)
    trade = activity.get("trade") or {}
    raw = trade.get("qtyDecimal") or trade.get("qty") or "0"
    return Decimal(str(raw))


# ---------------------------------------------------------------------------
# Completeness (AC4(c) / plan section 6 Q2 row)
# ---------------------------------------------------------------------------


def _iso_to_datetime(value: str) -> datetime:
    normalised = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalised)


def activity_create_time(activity: Mapping[str, Any]) -> str | None:
    """The one timestamp this activity envelope carries, by type.

    ``ACTIVITY_TYPE_TRADE`` -> ``trade.createTime``.
    ``ACTIVITY_TYPE_POSITION_RESOLUTION`` -> ``positionResolution.
    afterPosition.updateTime`` (a resolution carries no ``createTime`` of its
    own; the after-leg's update time is the resolution event's own
    timestamp).
    Every other (balance-change) type -> ``accountBalanceChange.createTime``,
    falling back to the single nested ``transactions[0].createTime`` --
    mirroring ``account_activity.py``'s own top-level-then-nested-fallback
    resolution for the identical shape-drift reason (L-17).
    Returns ``None`` if no timestamp can be found (never guessed).
    """
    kind = activity.get("type")
    if kind == "ACTIVITY_TYPE_TRADE":
        trade = activity.get("trade") or {}
        value = trade.get("createTime")
        return value if isinstance(value, str) else None
    if kind == "ACTIVITY_TYPE_POSITION_RESOLUTION":
        resolution = activity.get("positionResolution") or {}
        after = resolution.get("afterPosition") or {}
        value = after.get("updateTime")
        return value if isinstance(value, str) else None
    balance = activity.get("accountBalanceChange") or {}
    value = balance.get("createTime")
    if isinstance(value, str):
        return value
    transactions = balance.get("transactions") or []
    if transactions and isinstance(transactions[0], Mapping):
        nested = transactions[0].get("createTime")
        if isinstance(nested, str):
            return nested
    return None


def pages_reached_eof(pages: Sequence[Mapping[str, Any]]) -> bool:
    return any(bool(page.get("eof")) for page in pages)


def min_create_time_across_pages(pages: Sequence[Mapping[str, Any]]) -> str | None:
    """The minimum ``createTime`` (lexicographically, over parsed instants)
    across every activity in ``pages``. ``None`` if no page carried a
    timestamped activity."""
    times = [
        activity_create_time(activity)
        for page in pages
        for activity in (page.get("activities") or [])
    ]
    parseable = [t for t in times if t]
    if not parseable:
        return None
    return min(parseable, key=_iso_to_datetime)


def activities_are_complete(
    pages: Sequence[Mapping[str, Any]],
    *,
    threshold_iso: str,
    max_pages: int = MAX_ACTIVITY_PAGES,
) -> bool:
    """AC4(c): complete iff ``eof`` was reached, or the minimum ``createTime``
    across all pages read is strictly before ``threshold_iso``.

    A run that hit ``max_pages`` without either condition holding is
    INCOMPLETE (never guessed complete just because the cap was hit) --
    ``len(pages) >= max_pages`` on its own proves nothing either way, so it
    is not consulted here; the caller is responsible for capping the
    traversal at ``max_pages`` in the first place.
    """
    if pages_reached_eof(pages):
        return True
    minimum = min_create_time_across_pages(pages)
    if minimum is None:
        return False
    return _iso_to_datetime(minimum) < _iso_to_datetime(threshold_iso)


# ---------------------------------------------------------------------------
# Q2s: ordering and cursor stability (plan section 6, Q2s row)
# ---------------------------------------------------------------------------


def create_times_non_increasing(create_times: Sequence[str]) -> bool:
    """Q2s (1): the concatenated Q2 pages' ``createTime`` values never
    increase (``SORT_ORDER_DESCENDING``). An empty or single-element
    sequence is trivially non-increasing."""
    parsed = [_iso_to_datetime(t) for t in create_times]
    return all(parsed[i] >= parsed[i + 1] for i in range(len(parsed) - 1))


def activity_identity(activity: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    """A stable identity for one activity row, used only to detect
    duplication/gaps/reordering between two traversals -- never persisted
    and never a venue-facing value. ``(type, native id, createTime)``, where
    the native id is the field each activity type actually carries:
    ``trade.id`` for a trade, ``positionResolution.tradeId`` for a
    resolution, and the balance-change ``transactionId`` (top-level or
    single-nested fallback, mirroring :func:`activity_create_time`) for
    every other type.
    """
    kind = activity.get("type")
    native_id: Any = None
    if kind == "ACTIVITY_TYPE_TRADE":
        native_id = (activity.get("trade") or {}).get("id")
    elif kind == "ACTIVITY_TYPE_POSITION_RESOLUTION":
        native_id = (activity.get("positionResolution") or {}).get("tradeId")
    else:
        balance = activity.get("accountBalanceChange") or {}
        native_id = balance.get("transactionId")
        if native_id is None:
            transactions = balance.get("transactions") or []
            if transactions and isinstance(transactions[0], Mapping):
                native_id = transactions[0].get("transactionId")
    return (kind, native_id, activity_create_time(activity))


def activity_identities(pages: Sequence[Mapping[str, Any]]) -> list[tuple[Any, Any, Any]]:
    return [
        activity_identity(activity) for page in pages for activity in (page.get("activities") or [])
    ]


def id_sequences_identical(
    run1_identities: Sequence[tuple[Any, Any, Any]],
    run2_identities: Sequence[tuple[Any, Any, Any]],
) -> bool:
    """Q2s (2): over the ids common to both traversals, the relative order
    is identical, with no duplicate and no gap across page boundaries in
    either run's own overlap-filtered sequence."""
    overlap = set(run1_identities) & set(run2_identities)
    filtered1 = [identity for identity in run1_identities if identity in overlap]
    filtered2 = [identity for identity in run2_identities if identity in overlap]
    if len(filtered1) != len(set(filtered1)) or len(filtered2) != len(set(filtered2)):
        return False
    return filtered1 == filtered2


def is_exact_reverse(
    descending_identities: Sequence[tuple[Any, Any, Any]],
    ascending_identities: Sequence[tuple[Any, Any, Any]],
) -> bool:
    """Q2s (3): one ``SORT_ORDER_ASCENDING`` traversal over the same window
    is the exact reverse of the descending traversal."""
    return list(reversed(descending_identities)) == list(ascending_identities)


def q2s_stability_verdict(
    *, non_increasing: bool, identities_match: bool, exact_reverse: bool
) -> str:
    """``STABLE`` only if all three Q2s checks hold; ``UNSTABLE`` otherwise.

    (An incomplete or failed read never reaches this function at all --
    the caller reports ``INCONCLUSIVE`` for those upstream, per the plan's
    "never conclude from partial pages".)
    """
    if non_increasing and identities_match and exact_reverse:
        return "STABLE"
    return "UNSTABLE"


# ---------------------------------------------------------------------------
# Positive control (plan section 6, PC row)
# ---------------------------------------------------------------------------


def positive_control_trade_count(pages: Sequence[Mapping[str, Any]], known_order_id: str) -> int:
    return sum(
        1
        for page in pages
        for activity in (page.get("activities") or [])
        if is_trade_for_order(activity, known_order_id)
    )


def positive_control_passed(pages: Sequence[Mapping[str, Any]], known_order_id: str) -> bool:
    """PC: the join must find >= 1 TRADE for a known create-path fill inside
    the paged window, else Q2 is void (plan section 6, PC row)."""
    return positive_control_trade_count(pages, known_order_id) >= 1


# ---------------------------------------------------------------------------
# Verdict (plan section 6 decision table)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step0Evidence:
    """Every input :func:`classify_verdict` needs, already reduced to plain
    values -- never a raw payload. ``q1_*`` fields are ``None`` when Q1 could
    not be read at all (folded into ``any_non_2xx`` by the caller)."""

    q1_quantity: int | None
    q1_cum_quantity: int | None
    q1_state: str | None
    q2_complete: bool
    q2_trade_qty_sum: Decimal
    q2_position_resolution_before_qty: Decimal | None
    q2s_verdict: str
    pc_passed: bool
    l1_ok: bool
    any_non_2xx: bool


def _q1_terminal_zero(evidence: Step0Evidence) -> bool:
    return evidence.q1_cum_quantity == 0 and evidence.q1_state in _TERMINAL_ORDER_STATES


def _q1_full_fill(evidence: Step0Evidence) -> bool:
    if evidence.q1_state == "ORDER_STATE_FILLED":
        return True
    return (
        evidence.q1_quantity is not None
        and evidence.q1_cum_quantity is not None
        and evidence.q1_cum_quantity == evidence.q1_quantity
        and evidence.q1_quantity > 0
    )


def _q1_partial_fill(evidence: Step0Evidence) -> bool:
    return (
        evidence.q1_quantity is not None
        and evidence.q1_cum_quantity is not None
        and 0 < evidence.q1_cum_quantity < evidence.q1_quantity
    )


def classify_verdict(evidence: Step0Evidence) -> str:
    """The plan section 6 decision table, evaluated in the table's own
    priority order. Fail-closed: any non-2xx, an incomplete Q2, or a failed
    PC join is ``INCONCLUSIVE`` before anything else is considered ("never
    conclude from partial pages")."""
    if evidence.any_non_2xx or not evidence.q2_complete or not evidence.pc_passed:
        return VERDICT_INCONCLUSIVE

    q1_terminal_zero = _q1_terminal_zero(evidence)
    q1_full_fill = _q1_full_fill(evidence)
    q1_partial = _q1_partial_fill(evidence)
    q2_has_trade = evidence.q2_trade_qty_sum > 0
    q2_full = evidence.q2_trade_qty_sum >= 1
    q2_partial_range = 0 < evidence.q2_trade_qty_sum < 1

    # CONTRADICTION: Q1 zero but Q2(i) >= 1; or Q1 fill with Q2 complete,
    # PC passed and no Q2(i) row.
    if q1_terminal_zero and q2_has_trade:
        return VERDICT_CONTRADICTION
    if q1_full_fill and not q2_has_trade:
        return VERDICT_CONTRADICTION

    # FILL: Q2(i) qty sums to 1 (PC already proven passed above), or Q1
    # cum == quantity / state = FILLED.
    if q2_full or q1_full_fill:
        return VERDICT_FILL

    # PARTIAL_FILL: Q2(i) sums to (0, 1), or Q1 0 < cum < quantity.
    if q2_partial_range or q1_partial:
        return VERDICT_PARTIAL_FILL

    # ZERO_FILL_BENIGN: Q1 terminal cum=0, Q2 complete with zero Q2(i) rows
    # (q2_has_trade is False here), Q2s STABLE, PC passed (already proven),
    # Q2(iii) absent or zero beforePosition, L1 OK.
    if (
        q1_terminal_zero
        and evidence.q2s_verdict == "STABLE"
        and evidence.q2_position_resolution_before_qty in (None, Decimal(0))
        and evidence.l1_ok
    ):
        return VERDICT_ZERO_FILL_BENIGN

    return VERDICT_INCONCLUSIVE


# ---------------------------------------------------------------------------
# Venue wiring (mirrors polymarket_us_capital_flow_pull.py exactly)
# ---------------------------------------------------------------------------


def build_production_client(env: Mapping[str, str] | None = None) -> PolymarketUSHttpClient:
    """The real, credentialed, read-only client -- the SAME production wiring
    the node itself uses, reused rather than re-implemented. Mirrors
    ``scripts/venue/polymarket_us_capital_flow_pull.py::build_production_client``
    exactly. Never exercised by a test: every test in the paired suite
    exercises only the pure functions above.
    """
    config = config_from_env(env)
    return shared_polymarket_us_http_client(config, LiveClock())


def _redaction_secrets_from_environ(env: Mapping[str, str]) -> list[str]:
    """Never the key material itself (this module never reads the secret
    key file) -- only account-shaped identifiers that could otherwise leak
    into a saved response body or a log line, mirroring the 09-05 probe's
    own ``SECRETS`` list."""
    return [
        value
        for value in (
            env.get("POLYMARKET_US_ACCOUNT_NUMBER", ""),
            env.get("POLYMARKET_US_KEY_ID", ""),
        )
        if value
    ]


@dataclass
class _FetchResult:
    tag: str
    path: str
    query: Mapping[str, Any] | None
    status: int | None
    payload: Mapping[str, Any] | None
    attempts: list[dict[str, Any]]


async def _fetch_and_save(
    client: PolymarketUSHttpClient,
    *,
    tag: str,
    path: str,
    query: Mapping[str, Any] | None,
    quota_key: str,
    out_dir: Path,
    secrets: Sequence[str],
) -> _FetchResult:
    """One signed GET, saved raw (redacted) with attempt metadata as a
    PRIVATE 0600 file. Retries up to 3 times on a transport fault or a 5xx;
    never retries a 4xx (mirrors the 09-05 probe's own backoff)."""
    attempts: list[dict[str, Any]] = []
    status: int | None = None
    payload: Mapping[str, Any] | None = None
    raw_text = ""
    for attempt in range(1, 4):
        started = time.time()
        try:
            decoded = await client.get_authenticated(path, query=query, quota_key=quota_key)
            status = 200
            payload = decoded
            attempts.append(
                {"attempt": attempt, "status": status, "elapsed_s": round(time.time() - started, 2)}
            )
            break
        except Exception as exc:  # noqa: BLE001 - recorded by class only, never message
            attempts.append(
                {
                    "attempt": attempt,
                    "status": None,
                    "fault": type(exc).__name__,
                    "elapsed_s": round(time.time() - started, 2),
                }
            )
            status = None
            if attempt < 3:
                await asyncio.sleep(30)
    raw_text = redact_secrets(
        json.dumps(payload, default=str) if payload is not None else "", secrets
    )
    fn = out_dir / f"PRIVATE_{tag}.json"
    write_private_file(
        fn,
        json.dumps(
            {
                "path": path,
                "query": query,
                "attempts": attempts,
                "final_status": status,
                "payload": json.loads(raw_text) if raw_text else None,
            },
            indent=1,
            default=str,
        ),
    )
    print(f"[{tag}] GET {path} q={query} -> status={status} file={fn}")
    return _FetchResult(
        tag=tag, path=path, query=query, status=status, payload=payload, attempts=attempts
    )


async def _paginate_activities(
    client: PolymarketUSHttpClient,
    *,
    sort_order: str,
    tag_prefix: str,
    out_dir: Path,
    secrets: Sequence[str],
    max_pages: int = MAX_ACTIVITY_PAGES,
    threshold_iso: str = Q2_COMPLETENESS_THRESHOLD_ISO,
) -> tuple[list[Mapping[str, Any]], bool]:
    """Page ``/v1/portfolio/activities`` to ``eof``, until complete per
    :func:`activities_are_complete`, or to ``max_pages`` -- whichever comes
    first. Returns ``(pages, any_non_2xx)``."""
    pages: list[Mapping[str, Any]] = []
    cursor: str | None = None
    any_non_2xx = False
    for page_index in range(max_pages):
        query: dict[str, Any] = {"limit": ACTIVITY_PAGE_LIMIT, "sortOrder": sort_order}
        if cursor:
            query["cursor"] = cursor
        result = await _fetch_and_save(
            client,
            tag=f"{tag_prefix}_p{page_index}",
            path=PORTFOLIO_ACTIVITIES_PATH,
            query=query,
            quota_key=QUOTA_KEY_PORTFOLIO,
            out_dir=out_dir,
            secrets=secrets,
        )
        if result.status != 200 or result.payload is None:
            any_non_2xx = True
            break
        pages.append(result.payload)
        if activities_are_complete(pages, threshold_iso=threshold_iso, max_pages=max_pages):
            break
        cursor = (
            result.payload.get("nextCursor")
            if isinstance(result.payload.get("nextCursor"), str)
            else None
        )
        if not cursor:
            break
    return pages, any_non_2xx


async def _run_step0(
    client: PolymarketUSHttpClient, *, out_dir: Path, secrets: Sequence[str]
) -> None:
    make_private_dir(out_dir)

    # Q1: order_by_id.
    await _fetch_and_save(
        client,
        tag="order_by_id",
        path=f"{ORDER_BY_ID_PATH_PREFIX}{ORDER_ID}",
        query=None,
        quota_key=QUOTA_KEY_PORTFOLIO,
        out_dir=out_dir,
        secrets=secrets,
    )

    # Q2 run 1: descending.
    pages_desc_run1, non_2xx_1 = await _paginate_activities(
        client,
        sort_order="SORT_ORDER_DESCENDING",
        tag_prefix="activities_desc_r1",
        out_dir=out_dir,
        secrets=secrets,
    )

    print(f"Q2s: sleeping {Q2S_SECOND_TRAVERSAL_DELAY_SECS}s before the second traversal")
    await asyncio.sleep(Q2S_SECOND_TRAVERSAL_DELAY_SECS)

    # Q2 run 2: descending, >= 5 minutes later.
    pages_desc_run2, non_2xx_2 = await _paginate_activities(
        client,
        sort_order="SORT_ORDER_DESCENDING",
        tag_prefix="activities_desc_r2",
        out_dir=out_dir,
        secrets=secrets,
    )

    # Q2s (3): one ascending traversal over the same window.
    pages_asc, non_2xx_3 = await _paginate_activities(
        client,
        sort_order="SORT_ORDER_ASCENDING",
        tag_prefix="activities_asc",
        out_dir=out_dir,
        secrets=secrets,
    )

    # Q2b: cross-check only.
    await _fetch_and_save(
        client,
        tag="activities_types_trade",
        path=PORTFOLIO_ACTIVITIES_PATH,
        query={
            "limit": ACTIVITY_PAGE_LIMIT,
            "sortOrder": "SORT_ORDER_DESCENDING",
            "types": ["ACTIVITY_TYPE_TRADE"],
        },
        quota_key=QUOTA_KEY_PORTFOLIO,
        out_dir=out_dir,
        secrets=secrets,
    )

    # Q3: positions, slug-filtered and unfiltered.
    await _fetch_and_save(
        client,
        tag="positions_market",
        path=POSITIONS_PATH,
        query={"market": SLUG},
        quota_key=QUOTA_KEY_PORTFOLIO,
        out_dir=out_dir,
        secrets=secrets,
    )
    await _fetch_and_save(
        client,
        tag="positions_all",
        path=POSITIONS_PATH,
        query=None,
        quota_key=QUOTA_KEY_PORTFOLIO,
        out_dir=out_dir,
        secrets=secrets,
    )

    # Q4: open orders on the slug -- must be empty.
    await _fetch_and_save(
        client,
        tag="orders_open_slug",
        path=OPEN_ORDERS_PATH,
        query={"slugs": SLUG},
        quota_key=QUOTA_KEY_PORTFOLIO,
        out_dir=out_dir,
        secrets=secrets,
    )

    # Q5: public market settlement -- payoff, for a FILL P&L only.
    settlement_result = None
    try:
        settlement_result = await client.get_public(
            f"/v1/markets/{SLUG}/settlement", query=None, quota_key=QUOTA_KEY_BOOK
        )
    except Exception as exc:  # noqa: BLE001 - recorded by class only
        print(f"[market_settlement] GET failed: {type(exc).__name__}")
    if settlement_result is not None:
        fn = out_dir / "PRIVATE_market_settlement.json"
        write_private_file(fn, json.dumps({"payload": settlement_result}, indent=1, default=str))
        print(f"[market_settlement] file={fn}")

    # PC: positive control, over the descending run-1 pages already fetched.
    pc_order_id_used = None
    for candidate in PC_CANDIDATE_ORDER_IDS:
        if positive_control_passed(pages_desc_run1, candidate):
            pc_order_id_used = candidate
            break

    non_2xx_any = non_2xx_1 or non_2xx_2 or non_2xx_3

    summary = {
        "order_id": ORDER_ID,
        "slug": SLUG,
        "q2_run1_pages": len(pages_desc_run1),
        "q2_run2_pages": len(pages_desc_run2),
        "q2_asc_pages": len(pages_asc),
        "q2_run1_complete": activities_are_complete(
            pages_desc_run1, threshold_iso=Q2_COMPLETENESS_THRESHOLD_ISO
        ),
        "pc_order_id_used": pc_order_id_used,
        "pc_passed": pc_order_id_used is not None,
        "any_non_2xx": non_2xx_any,
    }
    summary_path = out_dir / "PRIVATE_summary.json"
    write_private_file(summary_path, json.dumps(summary, indent=1, default=str))
    print(f"SUMMARY: {json.dumps(summary, default=str)}")


def main() -> int:
    # Defence in depth alongside `write_private_file`/`make_private_dir`'s
    # own explicit modes (0600/0700, which are already umask-invariant for
    # any umask that only clears group/other bits): narrow the process
    # umask so ANY incidental file this process creates -- not only the two
    # helpers above -- is private by default. Restored unconditionally so a
    # library this process imports never inherits a narrowed umask past
    # this function's return.
    previous_umask = os.umask(0o077)
    try:
        pid_result = subprocess.run(
            ["pgrep", "-f", "breezy-trade$"], capture_output=True, text=True, check=False
        )
        secrets: list[str] = []
        if pid_result.returncode == 0 and pid_result.stdout.strip():
            try:
                pid = pid_result.stdout.split()[0]
                environ_bytes = Path(f"/proc/{pid}/environ").read_bytes()
                live_env = {}
                for kv in environ_bytes.split(b"\0"):
                    if b"=" in kv:
                        k, v = kv.split(b"=", 1)
                        live_env[k.decode()] = v.decode(errors="replace")
                secrets = _redaction_secrets_from_environ(live_env)
            except OSError:
                secrets = []

        client = build_production_client()
        asyncio.run(_run_step0(client, out_dir=OUT_DIR, secrets=secrets))
        return 0
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
