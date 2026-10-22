"""ARM B2 -- the pure half of the maker positive control (no venue contact, no exec imports).

Constants, budget, key-name capture, the activities shape record, the R13 guards, credential-file
loading, the run state and the evidence writer for
``scripts/venue/polymarket_us_maker_positive_control.py``. Nothing here sends, signs, or imports
the order path, so it carries no write-egress exemption of its own.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- constants

#: Budget ceilings enforced in code (plan D3). They bound requests, not notional.
MAX_CREATES: Final[int] = 4
MAX_CANCELS: Final[int] = 3
MAX_GETS: Final[int] = 40

#: The probe order: BUY NO, one contract, one cent -- far from the touch, below any floor on
#: purpose (the probe is not the strategy).
PROBE_PRICE: Final[Decimal] = Decimal("0.01")
PROBE_QUANTITY: Final[int] = 1

#: R13: every probe order is GTD and expires no later than now + this many seconds.
GTD_CEILING_SECS: Final[int] = 600
#: A and A' rest this long (well inside the ceiling); B's lapse is what S-6 observes.
REST_GTD_SECS: Final[int] = 540
SHORT_GTD_SECS: Final[int] = 120

CONFIRM_POLLS: Final[int] = 3
CONFIRM_INTERVAL_S: Final[float] = 1.0
EXPIRY_POLLS: Final[int] = 14
EXPIRY_INTERVAL_S: Final[float] = 20.0

NS_PER_S: Final[int] = 1_000_000_000
GTD_ECHO_TOLERANCE_NS: Final[int] = NS_PER_S
_TIME_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%SZ"

SUPERVISOR_UNIT: Final[str] = "breezy-trade-supervisor.service"
_QUIET_UNIT_STATES: Final[frozenset[str]] = frozenset({"inactive", "failed"})

CONFIG_DIR: Final[Path] = Path.home() / ".config" / "breezy"
ENV_FILE_NAME: Final[str] = "polymarket.env"
SECRET_KEY_FILE_VAR: Final[str] = "POLYMARKET_US_SECRET_KEY_FILE"

EVIDENCE_DIR: Final[Path] = REPO_ROOT / "docs" / "evidence" / "b2"
EVIDENCE_SCHEMA: Final[str] = "breezy.arm_b2.positive_control.v1"
_EVIDENCE_FILE_PREFIX: Final[str] = "maker_positive_control_"

#: Venue enum tokens recorded by name (never an id, amount or free text).
_ENUM_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Z]+(?:_[A-Z]+)+", re.ASCII)
_ENUM_PREFIXES: Final[tuple[str, ...]] = (
    "ACTIVITY_",
    "ORDER_",
    "POSITION_",
    "MARKET_",
    "OUTCOME_",
    "TIME_IN_FORCE_",
    "EXECUTION_",
    "LIQUIDITY_",
    "SETTLEMENT_",
    "TRADE_",
    "ACCOUNT_",
)
_KEY_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}", re.ASCII)
_MAX_KEY_DEPTH: Final[int] = 4
_EVENT_KEY_RE: Final[re.Pattern[str]] = re.compile(r"(tc-temp-[a-z]{3}high-\d{4}-\d{2}-\d{2})-.+")
RUN_DATE_RE: Final[re.Pattern[str]] = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_STAMP_RE: Final[re.Pattern[str]] = re.compile(r"[0-9A-Za-z_-]{1,64}")
_ENV_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[A-Z][A-Z0-9_]*", re.ASCII)

#: Secret-shaped strings an evidence document must never contain (also pinned, independently,
#: by ``tests/unit/test_b2_evidence_redaction.py``).
_SECRET_SHAPES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"-----BEGIN"),
    re.compile(r"[A-Za-z0-9+/]{60,}={0,2}"),
    re.compile(r"\b[0-9a-fA-F]{64}\b"),
    re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
    re.compile(r"x-pm-", re.IGNORECASE),
    re.compile(r"authorization|bearer ", re.IGNORECASE),
    re.compile(r"\?|@"),
)

VERDICT_NOT_RUN: Final[str] = "NOT_RUN"
VERDICT_PASS: Final[str] = "PASS"
VERDICT_FAIL: Final[str] = "FAIL"
VERDICT_SKIPPED: Final[str] = "SKIPPED_FOREIGN_ORDER"

TIF_GTD_TOKEN: Final[str] = "TIME_IN_FORCE_GOOD_TILL_DATE"
STATE_NEW: Final[str] = "ORDER_STATE_NEW"
STATE_CANCELED: Final[str] = "ORDER_STATE_CANCELED"
STATE_EXPIRED: Final[str] = "ORDER_STATE_EXPIRED"
FILL_STATES: Final[frozenset[str]] = frozenset(
    {"ORDER_STATE_FILLED", "ORDER_STATE_PARTIALLY_FILLED"}
)
TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {STATE_CANCELED, STATE_EXPIRED, "ORDER_STATE_FILLED", "ORDER_STATE_REJECTED"}
)


# -------------------------------------------------------------------------- exceptions


class ControlError(Exception):
    """Base of this control's own signals (distinct from the venue adapter's error family)."""


class Refusal(ControlError):
    """A precondition refused; nothing was written. ``code`` is the value-free reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BudgetExhausted(ControlError):
    """A request ceiling was reached; the call that would exceed it was never made."""


class StepFailed(ControlError):
    """A sequence step did not reach its expected state (``args[0]`` is the reason code)."""


# ----------------------------------------------------------------------------- budget


@dataclass
class Budget:
    """Request counters; the attempt is counted BEFORE the call so a failure still spends."""

    max_creates: int = MAX_CREATES
    max_cancels: int = MAX_CANCELS
    max_gets: int = MAX_GETS
    creates: int = 0
    cancels: int = 0
    gets: int = 0

    def spend_create(self) -> None:
        if self.creates >= self.max_creates:
            raise BudgetExhausted("create budget exhausted")
        self.creates += 1

    def spend_cancel(self) -> None:
        if self.cancels >= self.max_cancels:
            raise BudgetExhausted("cancel budget exhausted")
        self.cancels += 1

    def spend_get(self) -> None:
        if self.gets >= self.max_gets:
            raise BudgetExhausted("GET budget exhausted")
        self.gets += 1


# ------------------------------------------------------------------------ pure helpers


def key_paths(value: object) -> list[str]:
    """Dotted key paths of a JSON object, names only (never values), at most four deep.

    A list contributes ``<path>[]`` to its children. A key that is not a plain identifier
    (a venue dict keyed by a slug or an id, say) is replaced by ``<key>`` so a data-bearing
    key cannot leak through a key-name record.
    """
    found: set[str] = set()

    def walk(node: object, prefix: str, depth: int) -> None:
        if isinstance(node, Mapping):
            if depth >= _MAX_KEY_DEPTH:
                return
            for raw_key, child in node.items():
                name = (
                    raw_key
                    if isinstance(raw_key, str) and _KEY_NAME_RE.fullmatch(raw_key)
                    else "<key>"
                )
                path = f"{prefix}.{name}" if prefix else name
                found.add(path)
                walk(child, path, depth + 1)
        elif isinstance(node, list):
            for child in node:
                walk(child, f"{prefix}[]", depth)

    if isinstance(value, Mapping):
        walk(value, "", 0)
    return sorted(found)


def enum_token(value: object) -> str | None:
    if (
        isinstance(value, str)
        and len(value) <= 64
        and _ENUM_TOKEN_RE.fullmatch(value) is not None
        and value.startswith(_ENUM_PREFIXES)
    ):
        return value
    return None


def _enum_leaves(node: object, prefix: str, out: dict[str, set[str]]) -> None:
    if isinstance(node, Mapping):
        for raw_key, child in node.items():
            if isinstance(raw_key, str) and _KEY_NAME_RE.fullmatch(raw_key):
                _enum_leaves(child, f"{prefix}.{raw_key}" if prefix else raw_key, out)
    elif isinstance(node, list):
        for child in node:
            _enum_leaves(child, prefix, out)
    else:
        token = enum_token(node)
        if token is not None and prefix:
            out.setdefault(prefix, set()).add(token)


def capture_activity_shape(page: object) -> dict[str, Any]:
    """The D1 record of one activities page: key names, key paths, enum tokens. No values.

    For ``ACTIVITY_TYPE_POSITION_RESOLUTION`` rows only: the union of their key paths and, per
    path, the enum-shaped tokens found there. Amounts, ids, slugs, timestamps and cursors are
    structurally unreachable: only identifiers-as-keys and ``UPPER_SNAKE`` venue enums with a
    known prefix are ever recorded.
    """
    empty_pr: dict[str, Any] = {"rows": 0, "key_paths": [], "enum_values": {}}
    if not isinstance(page, Mapping):
        return {
            "status": "UNREADABLE",
            "top_level_keys": [],
            "activity_types_seen": [],
            "position_resolution": empty_pr,
        }
    rows = page.get("activities")
    rows = rows if isinstance(rows, list) else []
    types_seen: set[str] = set()
    pr_paths: set[str] = set()
    pr_enums: dict[str, set[str]] = {}
    pr_rows = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        token = enum_token(row.get("type"))
        if token is not None:
            types_seen.add(token)
        if token == "ACTIVITY_TYPE_POSITION_RESOLUTION":
            pr_rows += 1
            pr_paths.update(key_paths(row))
            _enum_leaves(row, "", pr_enums)
    top = sorted(k if _KEY_NAME_RE.fullmatch(k) else "<key>" for k in page if isinstance(k, str))
    return {
        "status": "OK",
        "top_level_keys": top,
        "activity_types_seen": sorted(types_seen),
        "position_resolution": {
            "rows": pr_rows,
            "key_paths": sorted(pr_paths),
            "enum_values": {path: sorted(vals) for path, vals in sorted(pr_enums.items())},
        },
    }


_UTC_STAMP_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?Z", re.ASCII
)


def parse_utc_ns(value: object) -> int:
    """RFC 3339 UTC (``Z`` only, optional fraction up to nanoseconds) to UNIX nanoseconds."""
    match = _UTC_STAMP_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError("not an RFC 3339 UTC timestamp ending in 'Z'")
    year, month, day, hour, minute, second = (int(g) for g in match.groups()[:6])
    seconds = int(datetime(year, month, day, hour, minute, second, tzinfo=UTC).timestamp())
    return seconds * NS_PER_S + int((match.group(7) or "").ljust(9, "0"))


def assert_gtd_within_ceiling(body: Mapping[str, Any], *, now_ns: int) -> None:
    """R13: refuse a body whose ``goodTillTime`` is not in (now, now + GTD_CEILING_SECS]."""
    try:
        expire_ns = parse_utc_ns(body.get("goodTillTime"))
    except ValueError:
        raise ValueError("GTD missing or unreadable; refusing to send") from None
    if expire_ns <= now_ns:
        raise ValueError("GTD is not in the future; refusing to send")
    if expire_ns > now_ns + GTD_CEILING_SECS * NS_PER_S:
        raise ValueError(f"GTD is more than {GTD_CEILING_SECS}s ahead; refusing to send")


def assert_no_trade_node(listing: str) -> None:
    """R13: refuse unless no ``breezy-trade-*`` unit but the supervisor is live.

    ``listing`` is the output of ``systemctl --user list-units 'breezy-trade-*' --plain
    --no-legend`` (UNIT LOAD ACTIVE SUB DESCRIPTION). An unparseable line fails closed.
    """
    for line in listing.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 3:
            raise Refusal("UNIT_LISTING_UNPARSEABLE")
        unit, active = parts[0], parts[2]
        if unit == SUPERVISOR_UNIT:
            continue
        if active not in _QUIET_UNIT_STATES:
            raise Refusal("TRADE_NODE_ACTIVE")


def load_env_file(path: Path, *, config_dir: Path = CONFIG_DIR) -> dict[str, str]:
    """Parse the venue env file; the ONLY source of credential variables for this run.

    The file and the secret key file it names must both resolve inside ``config_dir``
    (``~/.config/breezy``), the env file must be mode 0600, and the process environment is
    never read here.
    """
    base = config_dir.resolve()
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise Refusal("ENV_FILE_MISSING") from None
    if resolved.parent != base or not resolved.is_file():
        raise Refusal("ENV_FILE_OUTSIDE_CONFIG_DIR")
    if resolved.stat().st_mode & 0o077:
        raise Refusal("ENV_FILE_MODE_NOT_0600")
    values: dict[str, str] = {}
    for raw in resolved.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        name, sep, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or _ENV_NAME_RE.fullmatch(name) is None:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    key_file = values.get(SECRET_KEY_FILE_VAR)
    if key_file:
        try:
            key_resolved = Path(key_file).resolve(strict=True)
        except OSError:
            raise Refusal("SECRET_KEY_FILE_MISSING") from None
        if base not in key_resolved.parents:
            raise Refusal("SECRET_KEY_FILE_OUTSIDE_CONFIG_DIR")
    return values


def parse_json(body: bytes | None) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None


def open_order_ids(payload: object) -> frozenset[str] | None:
    """Ids in an open-orders payload, or ``None`` if it is not a complete, readable list."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("orders"), list):
        return None
    if "eof" in payload and payload["eof"] is not True:
        return None
    ids: set[str] = set()
    for order in payload["orders"]:
        order_id = order.get("id") if isinstance(order, Mapping) else None
        if not isinstance(order_id, str) or not order_id:
            return None
        ids.add(order_id)
    return frozenset(ids)


# -------------------------------------------------------------------------- run state


@dataclass
class OwnOrder:
    label: str
    slug: str
    order_id: str | None = None
    terminal: bool = False
    gtd_secs: int = 0
    sent_gtd_ns: int | None = None


@dataclass
class RunState:
    run_date: str
    started_ns: int
    slugs: tuple[str, ...] = ()
    share_event: bool | None = None
    orders: dict[str, OwnOrder] = field(default_factory=dict)
    verdicts: dict[str, str] = field(
        default_factory=lambda: {
            "S-1": VERDICT_NOT_RUN,
            "S-2": VERDICT_NOT_RUN,
            "S-6": VERDICT_NOT_RUN,
        }
    )
    details: dict[str, Any] = field(
        default_factory=lambda: {
            "gtd_tif_echoed": None,
            "per_order_cancel_status": None,
            "cancel_all_status": None,
            "s2_a_prime_state": None,
            "s2_b_state_after_cancel_all": None,
            "s6_final_state": None,
        }
    )
    activities: dict[str, Any] = field(default_factory=dict)
    cleanup: dict[str, Any] = field(
        default_factory=lambda: {"cancelled": [], "left_to_gtd": [], "errors": []}
    )
    final_account_clean: bool | None = None
    failure: str | None = None
    phase: str = "setup"
    unknown_create: bool = False

    def _unmet(self, passed: bool) -> str | None:
        if passed:
            return None
        if self.final_account_clean is False:
            return "ACCOUNT_NOT_CLEAN"
        if self.final_account_clean is None:
            return "ACCOUNT_CLEAN_UNKNOWN"
        return "VERDICT_NOT_PASS"

    def document(self, session: Any) -> dict[str, Any]:
        """Build the evidence document. ``session`` supplies ``budget``, ``trace``, ``now_ns()``."""
        budget = session.budget
        verdicts_ok = (
            self.verdicts["S-1"] == VERDICT_PASS
            and self.verdicts["S-6"] == VERDICT_PASS
            and self.verdicts["S-2"] in (VERDICT_PASS, VERDICT_SKIPPED)
        )
        passed = self.failure is None and verdicts_ok and self.final_account_clean is True
        return {
            "schema": EVIDENCE_SCHEMA,
            "run_date": self.run_date,
            "started_at": iso_utc(self.started_ns),
            "finished_at": iso_utc(session.now_ns()),
            "constants": {
                "max_creates": MAX_CREATES,
                "max_cancels": MAX_CANCELS,
                "max_gets": MAX_GETS,
                "side": "BUY_NO",
                "price": str(PROBE_PRICE),
                "quantity": PROBE_QUANTITY,
                "gtd_ceiling_secs": GTD_CEILING_SECS,
                "rest_gtd_secs": REST_GTD_SECS,
                "short_gtd_secs": SHORT_GTD_SECS,
                "confirm_polls": CONFIRM_POLLS,
                "expiry_polls": EXPIRY_POLLS,
                "expiry_interval_s": EXPIRY_INTERVAL_S,
            },
            "counts": {
                "creates": budget.creates,
                "cancels": budget.cancels,
                "gets": budget.gets,
            },
            "slugs": list(self.slugs),
            "slugs_share_event": self.share_event,
            "order_ids": {o.label: o.order_id for o in self.orders.values() if o.order_id},
            "steps": [dict(step) for step in session.trace],
            "verdicts": dict(self.verdicts),
            "details": dict(self.details),
            "activities": dict(self.activities),
            "cleanup": {k: list(v) for k, v in self.cleanup.items()},
            "final_account_clean": self.final_account_clean,
            "outcome": VERDICT_PASS if passed else VERDICT_FAIL,
            "failure": self.failure if self.failure is not None else self._unmet(passed),
        }


@dataclass(frozen=True)
class ControlResult:
    document: dict[str, Any]
    exit_code: int


def iso_utc(ns: int) -> str:
    return datetime.fromtimestamp(ns // NS_PER_S, tz=UTC).strftime(_TIME_FORMAT)


# ---------------------------------------------------------------------------- evidence


def write_evidence(document: Mapping[str, Any], directory: Path, *, stamp: str) -> Path:
    """Write the evidence JSON exclusively at mode 0600 after a schema and secret-shape check."""
    if set(document) != _EVIDENCE_KEYS:
        raise ValueError("evidence document does not match the closed schema")
    if _STAMP_RE.fullmatch(stamp) is None:
        raise ValueError("stamp must be a plain token")
    text = json.dumps(document, indent=2, sort_keys=True)
    for shape in _SECRET_SHAPES:
        if shape.search(text):
            raise ValueError("evidence document matches a secret-shaped pattern; refusing to write")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_EVIDENCE_FILE_PREFIX}{stamp}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


_EVIDENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "run_date",
        "started_at",
        "finished_at",
        "constants",
        "counts",
        "slugs",
        "slugs_share_event",
        "order_ids",
        "steps",
        "verdicts",
        "details",
        "activities",
        "cleanup",
        "final_account_clean",
        "outcome",
        "failure",
    }
)


@dataclass(frozen=True)
class Deps:
    """Injection seam: production wiring in :func:`main`, doubles in the tests."""

    today_utc: Callable[[], str]
    list_units: Callable[[], str]
    load_env: Callable[[], Mapping[str, str]]
    build_session: Callable[[Mapping[str, str]], Any]
    sleep: Callable[[float], Awaitable[None]]
    evidence_dir: Path
    stamp: Callable[[], str]


def require_run_date(run_date: str, today: str) -> None:
    if RUN_DATE_RE.fullmatch(run_date) is None:
        raise Refusal("RUN_DATE_MALFORMED")
    if run_date != today:
        raise Refusal("RUN_DATE_NOT_TODAY")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ARM B2 venue positive control for the resting-order path (one-shot)."
    )
    parser.add_argument(
        "--run-date",
        required=True,
        help="today's UTC date, YYYY-MM-DD; any other value refuses before any I/O",
    )
    return parser.parse_args(argv)


def list_units_via_systemctl() -> str:
    try:
        completed = subprocess.run(
            [
                "systemctl",
                "--user",
                "list-units",
                "breezy-trade-*",
                "--all",
                "--no-legend",
                "--plain",
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise Refusal("SYSTEMCTL_FAILED") from None
    if completed.returncode != 0:
        raise Refusal("SYSTEMCTL_FAILED")
    return completed.stdout


class QuietLog:
    """The read client's logger: nothing is emitted (request headers must never print)."""

    def debug(self, message: str) -> None: ...
    def info(self, message: str) -> None: ...
    def warning(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...


@dataclass(frozen=True)
class ProbeSlugs:
    slugs: tuple[str, str]
    share_event: bool


def markets_by_slug(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    markets = payload.get("markets")
    found: dict[str, Mapping[str, Any]] = {}
    if isinstance(markets, list):
        for market in markets:
            if isinstance(market, Mapping) and isinstance(market.get("slug"), str):
                found[market["slug"]] = market
    return found


def _number(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


def select_probe_slugs(
    payload: Mapping[str, Any],
    *,
    candidates: Sequence[str],
    is_daily_high: Callable[[str], bool],
    is_resolved: Callable[[Mapping[str, Any]], bool],
) -> ProbeSlugs | None:
    """Two distinct, listed, open daily-HIGH slugs, siblings of one event when possible.

    Siblings are the stricter S-2 test (a cancel-all scoped by slug must not touch the
    neighbouring bucket of the same station-day). The predicates are the caller's (the exec
    package's daily-HIGH grammar and the provider's resolved test). Eligibility: daily HIGH, not
    archived/closed/resolved, tick $0.01, minimum quantity <= 1.
    """
    markets = markets_by_slug(payload)
    eligible: list[str] = []
    for slug in sorted(set(candidates)):
        market = markets.get(slug)
        if market is None or not is_daily_high(slug):
            continue
        if is_resolved(market):
            continue
        if market.get("active") is False or market.get("hidden") is True:
            continue
        if _number(market.get("orderPriceMinTickSize")) != PROBE_PRICE:
            continue
        min_qty = _number(market.get("minimumTradeQty"))
        if min_qty is None or min_qty > PROBE_QUANTITY:
            continue
        eligible.append(slug)
    groups: dict[str, list[str]] = {}
    for slug in eligible:
        match = _EVENT_KEY_RE.fullmatch(slug)
        if match is not None:
            groups.setdefault(match.group(1), []).append(slug)
    for key in sorted(groups):
        if len(groups[key]) >= 2:
            first, second = groups[key][0], groups[key][1]
            return ProbeSlugs(slugs=(first, second), share_event=True)
    if len(eligible) >= 2:
        return ProbeSlugs(slugs=(eligible[0], eligible[1]), share_event=False)
    return None


@dataclass
class StatusTap:
    """Wraps the read transport and remembers the last HTTP status (never a body)."""

    inner: Any
    last_status: int | None = None

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> Any:
        self.last_status = None
        response = await self.inner.get(url, headers=headers, quota_key=quota_key)
        self.last_status = int(response.status)
        return response


@dataclass(frozen=True)
class Reading:
    status: int | None
    payload: Any


@dataclass(frozen=True)
class PostResult:
    status: int
    payload: Any
    order_id: str | None = None
    sent_gtd_ns: int | None = None


@dataclass(frozen=True)
class Observation:
    status: int | None
    state: str | None
    tif: str | None
    gtd_ns: int | None
    unreadable: bool


def gtd_echoed(obs: Observation, own: OwnOrder) -> bool:
    """The GET shows a GTD order whose ``goodTillTime`` is within 1 s of what was sent."""
    return bool(
        obs.tif == TIF_GTD_TOKEN
        and obs.gtd_ns is not None
        and own.sent_gtd_ns is not None
        and abs(obs.gtd_ns - own.sent_gtd_ns) <= GTD_ECHO_TOLERANCE_NS
    )
