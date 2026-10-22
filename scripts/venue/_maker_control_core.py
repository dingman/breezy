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
import signal
import subprocess
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
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
#: Verification and informational reads (public quote reads, the final per-order GETs, extra
#: activities pages). Separate from MAX_GETS so the account-state GET plan above is unchanged.
MAX_AUX_GETS: Final[int] = 20
#: At most this many public quote reads while choosing the two probe slugs.
QUOTE_SCAN_CAP: Final[int] = 6
#: Activities pages read while looking for a position-resolution row (the first is a MAX_GETS read).
ACTIVITIES_MAX_PAGES: Final[int] = 4

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

#: Q1: a probe order BUY NO 0.01 can only trade if the YES bid reaches 0.99; refuse well before.
QUOTE_PRICE_CEILING: Final[Decimal] = Decimal("0.97")
#: Q2: the market must still be open this long after the longest GTD (ceiling + 15 minutes).
CLOSE_MARGIN_SECS: Final[int] = 15 * 60

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
#: A valid identifier that is id-shaped: a 12-char venue id, a long hex run, or a long
#: alphanumeric run holding a digit.
_ID_SHAPED_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"[A-Z0-9]{12}|[0-9A-Fa-f]{16,}|(?=[A-Za-z]*[0-9])[A-Za-z0-9]{16,}", re.ASCII
)
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
#: S-2 held, but the two slugs were not siblings of one event: no SLUG_SCOPED flip licence.
VERDICT_PASS_NONSIBLING: Final[str] = "PASS_NONSIBLING"
_S2_ACCEPTED: Final[frozenset[str]] = frozenset(
    {VERDICT_PASS, VERDICT_PASS_NONSIBLING, VERDICT_SKIPPED}
)

QUOTE_OK: Final[str] = "OK"
QUOTE_HIGH_PRICE: Final[str] = "HIGH_PRICE"
QUOTE_UNREADABLE: Final[str] = "UNREADABLE"
QUOTE_HALTED: Final[str] = "HALTED"
_MARKET_OPEN_STATE: Final[str] = "MARKET_STATE_OPEN"
_MARKET_OPEN_STATUS: Final[str] = "MARKET_STATUS_OPEN"
_MARKET_OPEN_EP3: Final[str] = "OPEN"

#: Written into every evidence file: what each verdict does and does not license.
LICENCE_RULE: Final[str] = (
    "S-6 PASS (B echo of GTD within 1 s of sent and first EXPIRED not before sent minus 1 s) "
    "licenses the GTD expiry flip. S-2 PASS over siblings of one event licenses the slug scoped "
    "cancel-all flip; PASS_NONSIBLING and SKIPPED_FOREIGN_ORDER license nothing. The maker "
    "commission sign is never licensed by this run. All flips need outcome PASS."
)

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
    max_aux_gets: int = MAX_AUX_GETS
    creates: int = 0
    cancels: int = 0
    gets: int = 0
    aux_gets: int = 0

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

    def spend_aux_get(self) -> None:
        if self.aux_gets >= self.max_aux_gets:
            raise BudgetExhausted("auxiliary GET budget exhausted")
        self.aux_gets += 1


# ------------------------------------------------------------------------ pure helpers


def is_plain_key_name(raw_key: object) -> bool:
    """A recordable key name: an identifier that is not shaped like an id or a long token."""
    return (
        isinstance(raw_key, str)
        and _KEY_NAME_RE.fullmatch(raw_key) is not None
        and _ID_SHAPED_KEY_RE.fullmatch(raw_key) is None
    )


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
                name = raw_key if is_plain_key_name(raw_key) else "<key>"
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


_PR_TYPE: Final[str] = "ACTIVITY_TYPE_POSITION_RESOLUTION"
_MAX_ROW_SHAPES: Final[int] = 10


def sign_class(value: object) -> str | None:
    """``+``, ``0`` or ``-`` for a numeric leaf (a number or a numeric string); else ``None``."""
    number = _number(value)
    if number is None or not number.is_finite():
        return None
    return "+" if number > 0 else "-" if number < 0 else "0"


def _row_leaves(
    node: object, prefix: str, enums: dict[str, list[str]], signs: dict[str, set[str]]
) -> None:
    if isinstance(node, Mapping):
        for raw_key, child in node.items():
            if is_plain_key_name(raw_key):
                _row_leaves(child, f"{prefix}.{raw_key}" if prefix else raw_key, enums, signs)
    elif isinstance(node, list):
        for child in node:
            _row_leaves(child, prefix, enums, signs)
    elif prefix:
        token = enum_token(node)
        if token is not None:
            enums.setdefault(prefix, []).append(token)
            return
        klass = sign_class(node)
        if klass is not None:
            signs.setdefault(prefix, set()).add(klass)


def capture_activity_pages(pages: Sequence[object]) -> dict[str, Any]:
    """The D1 record of the activities pages read: names, enum tokens and sign classes. No values.

    For ``ACTIVITY_TYPE_POSITION_RESOLUTION`` rows only: the union and the per-row-shape key
    paths, per-path enum tokens (listed and counted), and per-path sign class of numeric leaves
    (``+``/``0``/``-``). Amounts, ids, slugs, timestamps and cursors are structurally
    unreachable: only identifier-shaped keys and ``UPPER_SNAKE`` venue enums with a known prefix
    are recorded, and a numeric leaf contributes its sign class and nothing else.
    """
    readable = [page for page in pages if isinstance(page, Mapping)]
    types_seen: set[str] = set()
    top: set[str] = set()
    pr_paths: set[str] = set()
    pr_enums: dict[str, dict[str, int]] = {}
    pr_signs: dict[str, set[str]] = {}
    shapes: dict[tuple[str, ...], int] = {}
    pr_rows = 0
    for page in readable:
        top.update(k if is_plain_key_name(k) else "<key>" for k in page if isinstance(k, str))
        rows = page.get("activities")
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            token = enum_token(row.get("type"))
            if token is not None:
                types_seen.add(token)
            if token != _PR_TYPE:
                continue
            pr_rows += 1
            paths = tuple(key_paths(row))
            pr_paths.update(paths)
            shapes[paths] = shapes.get(paths, 0) + 1
            enums: dict[str, list[str]] = {}
            _row_leaves(row, "", enums, pr_signs)
            for path, tokens in enums.items():
                counts = pr_enums.setdefault(path, {})
                for found in tokens:
                    counts[found] = counts.get(found, 0) + 1
    ordered_shapes = sorted(shapes.items(), key=lambda item: (-item[1], item[0]))
    return {
        "status": "OK" if readable else "UNREADABLE",
        "top_level_keys": sorted(top),
        "activity_types_seen": sorted(types_seen),
        "position_resolution": {
            "rows": pr_rows,
            "key_paths": sorted(pr_paths),
            "enum_values": {path: sorted(c) for path, c in sorted(pr_enums.items())},
            "enum_counts": {path: dict(sorted(c.items())) for path, c in sorted(pr_enums.items())},
            "sign_classes": {path: sorted(v) for path, v in sorted(pr_signs.items())},
            "row_path_sets": [
                {"count": count, "key_paths": list(paths)}
                for paths, count in ordered_shapes[:_MAX_ROW_SHAPES]
            ],
        },
        "d1_cases_found": pr_rows,
        "no_position_resolution_rows": pr_rows == 0,
    }


def capture_activity_shape(page: object) -> dict[str, Any]:
    """:func:`capture_activity_pages` for a single page."""
    return capture_activity_pages([page])


def has_position_resolution_row(page: object) -> bool:
    rows = page.get("activities") if isinstance(page, Mapping) else None
    return isinstance(rows, list) and any(
        isinstance(row, Mapping) and row.get("type") == _PR_TYPE for row in rows
    )


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


_NODE_UNIT_PREFIXES: Final[tuple[str, ...]] = ("breezy-node-", "breezy-trade-")
#: Never equals a real store path, so the shared /proc scan reports ``MISMATCH`` for any node.
_NODE_PROBE_SENTINEL: Final[Path] = Path("/nonexistent/b2-node-probe.db")
TRADE_ENV_FILE_NAME: Final[str] = "breezy-trade.env"
PROC_LOCKS_PATH: Final[Path] = Path("/proc/locks")


def assert_no_node_units(listing: str) -> None:
    """R1: refuse if any ``breezy-node-*`` or non-supervisor ``breezy-trade-*`` unit is live.

    The hand relaunch is ``systemd-run --user --scope --unit=breezy-node-handrelaunch-<ts>``, so
    the listing is of ``breezy-node-*`` and ``*.scope``; scopes with other names are not ours to
    judge (the process scan covers a node wherever it runs). An unparseable line fails closed.
    """
    for line in listing.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 3:
            raise Refusal("UNIT_LISTING_UNPARSEABLE")
        unit, active = parts[0], parts[2]
        if unit == SUPERVISOR_UNIT or not unit.startswith(_NODE_UNIT_PREFIXES):
            continue
        if active not in _QUIET_UNIT_STATES:
            raise Refusal("TRADE_NODE_UNIT_ACTIVE")


def list_node_units_via_systemctl() -> str:
    try:
        completed = subprocess.run(
            [
                "systemctl",
                "--user",
                "list-units",
                "breezy-node-*",
                "*.scope",
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


def probe_trade_node(
    *,
    list_node_units: Callable[[], str],
    proc_root: Path = Path("/proc"),
    locks_path: Path = PROC_LOCKS_PATH,
    trade_env: Path | None = None,
) -> None:
    """R1: refuse unless no trade-node unit, process or intent-flock holder exists.

    The node is a ``Popen`` child of the supervisor (or a hand relaunch in a transient scope),
    so a unit listing cannot see it. Three independent probes, any error refuses:

    1. unit/scope listing (:func:`assert_no_node_units`);
    2. the runtime's own ``/proc`` scan for the ``breezy-trade`` entry argv
       (``node_store_path_check``; the supervisor's ``breezy-trade-supervisor-daily`` argv never
       matches), where anything but ``NO_NODE`` refuses;
    3. the node's exclusive intent flock, read from ``/proc/locks`` for the store path named in
       ``breezy-trade.env`` (the supervisor's own derivation and holder lookup).
    """
    from breezy.runtime.exec_state_db_path import node_store_path_check, resolve_store_path
    from breezy.runtime.trade_supervisor import intent_lock_path, resolve_lock_holder_pid

    env_file = trade_env if trade_env is not None else CONFIG_DIR / TRADE_ENV_FILE_NAME
    try:
        assert_no_node_units(list_node_units())
        verdict = node_store_path_check(_NODE_PROBE_SENTINEL, proc_root=proc_root)
        if verdict == "DISCOVERY_FAILED":
            raise Refusal("NODE_PROBE_ERROR")
        if verdict != "NO_NODE":
            raise Refusal("TRADE_NODE_PROCESS_PRESENT")
        store = resolve_store_path(parse_env_text(env_file.read_text(encoding="utf-8")))
        locks_path.read_text(encoding="utf-8")  # an unreadable table must refuse, not pass
        if resolve_lock_holder_pid(intent_lock_path(store), locks_path=locks_path) is not None:
            raise Refusal("TRADE_NODE_LOCK_HELD")
    except Refusal:
        raise
    except Exception:  # noqa: BLE001 - any probe error refuses; the class name is not needed
        raise Refusal("NODE_PROBE_ERROR") from None


def probe_production_node() -> None:
    probe_trade_node(list_node_units=list_node_units_via_systemctl)


def _raise_interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def install_termination_handlers() -> dict[signal.Signals, Any]:
    """R3: SIGTERM and SIGHUP raise ``KeyboardInterrupt`` so cleanup and evidence still run."""
    previous: dict[signal.Signals, Any] = {}
    for sig in (signal.SIGTERM, signal.SIGHUP):
        previous[sig] = signal.signal(sig, _raise_interrupt)
    return previous


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
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
    return values


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
    values = parse_env_text(resolved.read_text(encoding="utf-8"))
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


#: The open-orders envelope keys the exec client knows
#: (``submit_chain._OPEN_ORDERS_KNOWN_ENVELOPE_KEYS``, S4 r4 section 5.5).
#: Mirrored, not imported: the exec module drags the write paths into this pure core.
#: ``nextCursor`` is deliberately NOT known, so a paginated reply refuses.
OPEN_ORDERS_KNOWN_ENVELOPE_KEYS: Final[frozenset[str]] = frozenset({"orders", "eof"})


def open_orders_rows(payload: object) -> list[Any] | None:
    """The ``orders`` rows of a COMPLETE open-orders reply, else ``None`` (unreadable).

    Exactly the exec client's rule (``submit_chain.open_orders_envelope_is_known`` plus
    ``reports.parse_open_orders``): a mapping with an ``orders`` list; ``eof`` absent or ``True``
    is complete, any other ``eof`` is incomplete; any envelope key outside
    :data:`OPEN_ORDERS_KNOWN_ENVELOPE_KEYS` (``nextCursor`` included) refuses.
    """
    if not isinstance(payload, Mapping) or not set(payload) <= OPEN_ORDERS_KNOWN_ENVELOPE_KEYS:
        return None
    orders = payload.get("orders")
    if not isinstance(orders, list):
        return None
    if "eof" in payload and payload["eof"] is not True:
        return None
    return orders


def open_order_ids(payload: object) -> frozenset[str] | None:
    """Ids in a complete open-orders reply (see :func:`open_orders_rows`), else ``None``."""
    rows = open_orders_rows(payload)
    if rows is None:
        return None
    ids: set[str] = set()
    for order in rows:
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
    filled: bool = False


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
            "s6_b_gtd_echoed": None,
            "s6_expiry_not_early": None,
            "licence_rule": LICENCE_RULE,
        }
    )
    activities: dict[str, Any] = field(default_factory=dict)
    quote_guard: dict[str, Any] = field(
        default_factory=lambda: {
            "scanned": 0,
            "excluded": {QUOTE_HIGH_PRICE: 0, QUOTE_UNREADABLE: 0, QUOTE_HALTED: 0},
            "market_excluded": {},
            "rechecks": {},
        }
    )
    cleanup: dict[str, Any] = field(
        default_factory=lambda: {
            "cancelled": [],
            "left_to_gtd": [],
            "errors": [],
            "leftover": [],
        }
    )
    final_open_ids: frozenset[str] = frozenset()
    final_account_clean: bool | None = None
    failure: str | None = None
    phase: str = "setup"
    unknown_create: bool = False

    @property
    def filled_orders(self) -> list[OwnOrder]:
        return [own for own in self.orders.values() if own.filled]

    def collect_leftover(self) -> list[str]:
        """Order ids that may still rest: own orders not known terminal, plus the final listing."""
        own_open = {o.order_id for o in self.orders.values() if o.order_id and not o.terminal}
        leftover = sorted(own_open | set(self.final_open_ids))
        self.cleanup["leftover"] = leftover
        return leftover

    def _unmet(self, passed: bool) -> str | None:
        if passed:
            return None
        if self.filled_orders:
            return "ORDER_FILLED_DETECTED"
        if self.final_account_clean is False:
            return "ACCOUNT_NOT_CLEAN"
        if self.final_account_clean is None:
            return "ACCOUNT_CLEAN_UNKNOWN"
        if self.cleanup["leftover"]:
            return "LEFTOVER_ORDER"
        return "VERDICT_NOT_PASS"

    def document(self, session: Any) -> dict[str, Any]:
        """Build the evidence document. ``session`` supplies ``budget``, ``trace``, ``now_ns()``."""
        budget = session.budget
        verdicts_ok = (
            self.verdicts["S-1"] == VERDICT_PASS
            and self.verdicts["S-6"] == VERDICT_PASS
            and self.verdicts["S-2"] in _S2_ACCEPTED
        )
        passed = (
            self.failure is None
            and verdicts_ok
            and self.final_account_clean is True
            and not self.filled_orders
            and not self.cleanup["leftover"]
        )
        return {
            "schema": EVIDENCE_SCHEMA,
            "run_date": self.run_date,
            "started_at": iso_utc(self.started_ns),
            "finished_at": iso_utc(session.now_ns()),
            "constants": {
                "max_creates": MAX_CREATES,
                "max_cancels": MAX_CANCELS,
                "max_gets": MAX_GETS,
                "max_aux_gets": MAX_AUX_GETS,
                "quote_price_ceiling": str(QUOTE_PRICE_CEILING),
                "close_margin_secs": CLOSE_MARGIN_SECS,
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
                "aux_gets": budget.aux_gets,
            },
            "slugs": list(self.slugs),
            "slugs_share_event": self.share_event,
            "order_ids": {o.label: o.order_id for o in self.orders.values() if o.order_id},
            "steps": [dict(step) for step in session.trace],
            "quote_guard": json.loads(json.dumps(self.quote_guard)),
            "licenses": {
                "GTD_EXPIRY": passed and self.verdicts["S-6"] == VERDICT_PASS,
                "SLUG_SCOPED_CANCEL_ALL": passed and self.verdicts["S-2"] == VERDICT_PASS,
                "MAKER_COMMISSION_SIGN": False,
            },
            "fill_detected": bool(self.filled_orders),
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
        "quote_guard",
        "licenses",
        "fill_detected",
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
    probe_node: Callable[[], None]
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


_EVENT_SPLIT_RE: Final[re.Pattern[str]] = re.compile(
    r"(tc-temp-[a-z]{3}high-(\d{4}-\d{2}-\d{2}))-(.+)"
)
_RUNG_RE: Final[re.Pattern[str]] = re.compile(r"(?:gte(\d+))?(?:lt(\d+))?f", re.ASCII)
_LOW_TAIL_RANK: Final[int] = -1
_HIGH_TAIL_RANK: Final[int] = 10**6


def market_exclusion(market: Mapping[str, Any], *, now_ns: int) -> str | None:
    """Q2: why this market is unfit to rest on (open, and closing well after the longest GTD).

    Fails closed: a status that is not plainly open, or a missing or unreadable ``endDate``,
    excludes. The market must close at least GTD ceiling + 15 minutes after ``now_ns``.
    """
    if market.get("status") != _MARKET_OPEN_STATUS:
        return "NOT_OPEN"
    ep3 = market.get("ep3Status")
    if ep3 is not None and ep3 != _MARKET_OPEN_EP3:
        return "NOT_OPEN"
    try:
        close_ns = parse_utc_ns(market.get("endDate"))
    except ValueError:
        return "CLOSE_UNREADABLE"
    if close_ns < now_ns + (GTD_CEILING_SECS + CLOSE_MARGIN_SECS) * NS_PER_S:
        return "CLOSE_TOO_SOON"
    return None


def eligible_probe_slugs(
    payload: Mapping[str, Any],
    *,
    candidates: Sequence[str],
    is_daily_high: Callable[[str], bool],
    is_resolved: Callable[[Mapping[str, Any]], bool],
    now_ns: int,
) -> tuple[list[str], dict[str, int]]:
    """Listed, open, far-from-close daily-HIGH slugs (sorted), and counts of Q2 exclusions.

    Eligibility: daily HIGH, not archived/closed/resolved/inactive/hidden, tick $0.01, minimum
    quantity <= 1, plainly open, and :func:`market_exclusion` clear. The predicates are the
    caller's (the exec package's grammar and the provider's resolved test).
    """
    markets = markets_by_slug(payload)
    eligible: list[str] = []
    excluded: dict[str, int] = {}
    for slug in sorted(set(candidates)):
        market = markets.get(slug)
        if market is None or not is_daily_high(slug) or is_resolved(market):
            continue
        if market.get("active") is False or market.get("hidden") is True:
            continue
        if _number(market.get("orderPriceMinTickSize")) != PROBE_PRICE:
            continue
        min_qty = _number(market.get("minimumTradeQty"))
        if min_qty is None or min_qty > PROBE_QUANTITY:
            continue
        reason = market_exclusion(market, now_ns=now_ns)
        if reason is not None:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        eligible.append(slug)
    return eligible, excluded


def _rung_rank(slug: str) -> int:
    match = _EVENT_SPLIT_RE.fullmatch(slug)
    rung = _RUNG_RE.fullmatch(match.group(3)) if match is not None else None
    if rung is None:
        return _HIGH_TAIL_RANK + 1
    low, high = rung.group(1), rung.group(2)
    if low and high:
        return int(low)
    return _LOW_TAIL_RANK if high else _HIGH_TAIL_RANK


def _middle_out(members: Sequence[str]) -> list[str]:
    ordered = sorted(members, key=lambda slug: (_rung_rank(slug), slug))
    centre = (len(ordered) - 1) / 2
    return [ordered[i] for i in sorted(range(len(ordered)), key=lambda i: (abs(i - centre), i))]


def rank_probe_slugs(eligible: Sequence[str], *, now_ns: int) -> list[str]:
    """Preference order: siblings of one event first, next-day events first, middle rungs first.

    A sibling pair is the stricter S-2 test. A market that resolves tomorrow or later has a
    price far from 0 or 1 (D+1 first); within an event the middle rungs come before the tails,
    which are the ones that run to a near-certain price.
    """
    today = iso_utc(now_ns)[:10]
    groups: dict[str, list[str]] = {}
    for slug in eligible:
        match = _EVENT_SPLIT_RE.fullmatch(slug)
        groups.setdefault(match.group(1) if match is not None else slug, []).append(slug)

    def group_order(key: str) -> tuple[int, int, str, str]:
        match = _EVENT_SPLIT_RE.fullmatch(f"{key}-x")
        day = match.group(2) if match is not None else ""
        return (0 if len(groups[key]) >= 2 else 1, 0 if day > today else 1, day, key)

    ranked: list[str] = []
    for key in sorted(groups, key=group_order):
        ranked.extend(_middle_out(groups[key]))
    return ranked


def pick_pair(ranked: Sequence[str], qualified: Collection[str]) -> ProbeSlugs | None:
    """Two qualified slugs: siblings of one event when possible, else the best two overall."""
    wanted = [slug for slug in ranked if slug in qualified]
    by_event: dict[str, list[str]] = {}
    for slug in wanted:
        match = _EVENT_KEY_RE.fullmatch(slug)
        if match is not None:
            by_event.setdefault(match.group(1), []).append(slug)
    for slug in wanted:
        match = _EVENT_KEY_RE.fullmatch(slug)
        siblings = by_event.get(match.group(1), []) if match is not None else []
        if len(siblings) >= 2:
            return ProbeSlugs(slugs=(siblings[0], siblings[1]), share_event=True)
    if len(wanted) >= 2:
        return ProbeSlugs(slugs=(wanted[0], wanted[1]), share_event=False)
    return None


def select_probe_slugs(
    payload: Mapping[str, Any],
    *,
    candidates: Sequence[str],
    is_daily_high: Callable[[str], bool],
    is_resolved: Callable[[Mapping[str, Any]], bool],
    now_ns: int,
) -> ProbeSlugs | None:
    """The market-level choice before any quote read: :func:`pick_pair` over all eligible slugs."""
    eligible, _ = eligible_probe_slugs(
        payload,
        candidates=candidates,
        is_daily_high=is_daily_high,
        is_resolved=is_resolved,
        now_ns=now_ns,
    )
    return pick_pair(rank_probe_slugs(eligible, now_ns=now_ns), eligible)


def _price_value(node: object) -> Decimal | None:
    return _number(node.get("value") if isinstance(node, Mapping) else node)


_QUOTE_GUARD_FIELDS: Final[tuple[str, ...]] = (
    "bestBid",
    "lastTradePx",
    "currentPx",
    "settlementPx",
)


def quote_verdict(payload: object, *, slug: str) -> str:
    """Q1: classify a public ``bbo`` body for ``slug``; only ``OK`` may be rested on.

    ``UNREADABLE`` (not a ``marketData`` body for this slug, a guard price present but not a
    number, or no guard price at all), ``HALTED`` (a ``state`` other than open) and
    ``HIGH_PRICE`` (the YES bid, last trade, current or settlement price at or above 0.97, where
    a BUY NO at one cent could trade) all exclude. Values are never returned.
    """
    data = payload.get("marketData") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping) or data.get("marketSlug") != slug:
        return QUOTE_UNREADABLE
    prices: list[Decimal] = []
    for name in _QUOTE_GUARD_FIELDS:
        raw = data.get(name)
        if raw is None:
            continue
        price = _price_value(raw)
        if price is None or not price.is_finite():
            return QUOTE_UNREADABLE
        prices.append(price)
    if not prices:
        return QUOTE_UNREADABLE
    state = data.get("state")
    if state is not None and state != _MARKET_OPEN_STATE:
        return QUOTE_HALTED
    if any(price >= QUOTE_PRICE_CEILING for price in prices):
        return QUOTE_HIGH_PRICE
    return QUOTE_OK


def is_own_probe_shape(order: object, *, slugs: Collection[str], now_ns: int) -> bool:
    """R5: an open order that looks exactly like one of this control's probes.

    On a probe slug, quantity one, GTD, a ``goodTillTime`` inside the ceiling window, and the
    one-cent price in either spelling (the BUY NO as sent, or the SELL YES complement the venue
    shows). Anything else on those slugs is somebody else's and is never cancelled.
    """
    if not isinstance(order, Mapping) or order.get("marketSlug") not in slugs:
        return False
    if _number(order.get("quantity")) != PROBE_QUANTITY or order.get("tif") != TIF_GTD_TOKEN:
        return False
    if _price_value(order.get("price")) not in (PROBE_PRICE, Decimal(1) - PROBE_PRICE):
        return False
    try:
        gtd_ns = parse_utc_ns(order.get("goodTillTime"))
    except ValueError:
        return False
    slack = 60 * NS_PER_S
    return now_ns - slack <= gtd_ns <= now_ns + GTD_CEILING_SECS * NS_PER_S + slack


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
    observed_ns: int | None = None


def gtd_echoed(obs: Observation, own: OwnOrder) -> bool:
    """The GET shows a GTD order whose ``goodTillTime`` is within 1 s of what was sent."""
    return bool(
        obs.tif == TIF_GTD_TOKEN
        and obs.gtd_ns is not None
        and own.sent_gtd_ns is not None
        and abs(obs.gtd_ns - own.sent_gtd_ns) <= GTD_ECHO_TOLERANCE_NS
    )
