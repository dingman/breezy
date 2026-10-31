"""Card A one-look census. Called only from ``--census-only``, before ``collect``.

No network, no truth loader, no ``RungEvent``. Writes nothing except the two
artefacts, and only when not a dry-run and not a refusal.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Final, NoReturn, cast

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_ANALYSIS_DIR.parents[1]
for _entry in (str(_SCRIPTS_ANALYSIS_DIR), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from h4_preliminary_economic_read import parse_rung  # type: ignore[import-not-found]
from wp7b_market_as_forecaster import (  # type: ignore[import-not-found]
    IncompleteLadderError,
    SumAskRow,
    assert_complete_partition,
)

from breezy.domain.exec_intent import intent_fingerprint, utc_day_for_ns
from breezy.domain.instrument_leg import base_symbol_of, symbol_of_instrument_id
from breezy.runtime.exec_state_db_path import ExecStateDbNotConfiguredError, resolve_store_path
from breezy.strategy.current_rung_hold.decision import fee_on_ask

_NS: Final[int] = 1_000_000_000
_EPOCH: Final[dt.datetime] = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)

WINDOW_START: Final[dt.date] = dt.date(2026, 9, 21)
WINDOW_END: Final[dt.date] = dt.date(2026, 10, 30)
TARGET_CLOCK: Final[dt.time] = dt.time(18, 0, 0)
OFFSET_START: Final[dt.time] = dt.time(17, 30, 0)
OFFSET_END: Final[dt.time] = dt.time(18, 30, 0)
AGE_CAP_S: Final[int] = 60
FIRST_COMPLETE_LEAD_MIN: Final[int] = 60
FEE_COEFFICIENT: Final[Decimal] = Decimal("0.0695")
TICK: Final[Decimal] = Decimal("0.01")
HURDLE: Final[Decimal] = Decimal("0.01")
FLOOR_STATION_DAYS: Final[int] = 30
FLOOR_DATES: Final[int] = 7
Q_GRID: Final[tuple[int, ...]] = (1, 5, 10, 25)
NORMALIZER_DAYS: Final[int] = 30
WINDOW_DAYS: Final[int] = 40

_FROZEN: Final[tuple[object, ...]] = (
    WINDOW_START,
    WINDOW_END,
    TARGET_CLOCK,
    OFFSET_START,
    OFFSET_END,
    AGE_CAP_S,
    FIRST_COMPLETE_LEAD_MIN,
    FEE_COEFFICIENT,
    TICK,
    HURDLE,
    FLOOR_STATION_DAYS,
    FLOOR_DATES,
    Q_GRID,
    NORMALIZER_DAYS,
    WINDOW_DAYS,
)

_REPO: Final[Path] = Path(__file__).resolve().parents[2]
PREREG_PATH: Path = _REPO / "docs/plans/backlog/STRAT_DESIGN_2026-10-31/prereg_card_a.md"
FREEZE_PATH: Path = _REPO / "docs/evidence/STRAT_DESIGN_2026-10-31/FREEZE_card_a.txt"
OUTPUT_DIR: Path = _REPO / "docs/evidence/STRAT_DESIGN_2026-10-31"
CATALOG: Path = Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us"
LOG_DIR: Path = Path.home() / ".local/share/breezy/logs"
LOG_GLOB: Final[str] = "breezy-trade-*.log"

_FAMILY_FILES: Final[tuple[str, ...]] = (
    "pm_us_crh_cont.json",
    "pm_us_crh_exit_v4.json",
    "pm_us_crh_fq_v1.json",
    "pm_us_crh_v2.json",
    "pm_us_crh_v4.json",
    "pm_us_no_maker_sharp_v1.json",
)
_COLUMNS: Final[tuple[str, ...]] = ("station", "climate_day", "status", "leg1", "leg2")
_RAW_TOLERANCE: Final[Decimal] = Decimal("0.000001")
# Any timestamp pins theta: ``fee_coefficient_at_fill`` is always passed, so this is inert.
_FEE_PROBE_TS_NS: Final[int] = 1
_LOW_DIR: Final[re.Pattern[str]] = re.compile(r"^(tc-temp-[a-z]+)low(-\d{4}-\d{2}-\d{2}-.*)$")


class OffTickError(ValueError):
    """A quoted price is not on the tick. Rounding it would hide an off-tick quote."""


class OwnOrderError(Exception):
    """The own-order set cannot be built. The message is the one-line refusal."""

    def __init__(self, message: str, report: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.report = tuple(report)


@dataclass(frozen=True, slots=True)
class Quote:
    ts_ns: int
    ask: Decimal | None
    ask_size: Decimal
    bid: Decimal | None
    bid_size: Decimal


@dataclass(frozen=True, slots=True)
class FrameSelection:
    kind: str
    reason: str
    chosen: tuple[tuple[str, Quote], ...]


@dataclass(frozen=True, slots=True)
class BookEval:
    crossed: bool
    leg1_clear: bool
    leg2_clear: bool


@dataclass(frozen=True, slots=True)
class OwnSet:
    instrument_ids: tuple[str, ...]
    first_ns: Mapping[str, int]
    never_filled: int = 0
    report: tuple[str, ...] = field(default=(), compare=False)


@dataclass(frozen=True, slots=True)
class _Denom:
    day: dt.date
    asks: tuple[Decimal, ...]
    ask_sizes: tuple[Decimal, ...]
    bids: tuple[Decimal, ...]
    bid_sizes: tuple[Decimal, ...]
    leg1: bool
    leg2: bool


def refuse(reason: str) -> NoReturn:
    """Exit 2 with one stderr line. No write has happened yet on this path."""
    print(reason.replace("\n", " "), file=sys.stderr)
    raise SystemExit(2)


def assert_constants() -> None:
    """The frozen tuple is not a CLI flag. A drift refuses before any frame."""
    window_days = (WINDOW_END - WINDOW_START).days + 1
    actual: tuple[object, ...] = (
        WINDOW_START,
        WINDOW_END,
        TARGET_CLOCK,
        OFFSET_START,
        OFFSET_END,
        AGE_CAP_S,
        FIRST_COMPLETE_LEAD_MIN,
        FEE_COEFFICIENT,
        TICK,
        HURDLE,
        FLOOR_STATION_DAYS,
        FLOOR_DATES,
        Q_GRID,
        NORMALIZER_DAYS,
        window_days,
    )
    if actual != _FROZEN or window_days != WINDOW_DAYS:
        refuse("census constant mismatch")


def _ns_of(moment: dt.datetime) -> int:
    utc = moment.astimezone(dt.UTC)
    delta = utc - _EPOCH
    return delta.days * 86_400 * _NS + delta.seconds * _NS + delta.microseconds * 1_000


def _target_ns(climate_day: dt.date) -> int:
    moment = dt.datetime.combine(climate_day - dt.timedelta(days=1), TARGET_CLOCK, tzinfo=dt.UTC)
    return _ns_of(moment)


def _offset_bounds_ns(climate_day: dt.date) -> tuple[int, int]:
    day = climate_day - dt.timedelta(days=1)
    start = dt.datetime.combine(day, OFFSET_START, tzinfo=dt.UTC)
    end = dt.datetime.combine(day, OFFSET_END, tzinfo=dt.UTC)
    return _ns_of(start), _ns_of(end)


def _nearest(series: Sequence[Quote], target: int, start: int, end: int) -> Quote | None:
    cap = AGE_CAP_S * _NS
    qualifying = [
        quote for quote in series if start <= quote.ts_ns < end and abs(quote.ts_ns - target) <= cap
    ]
    if not qualifying:
        return None
    return min(qualifying, key=lambda quote: (abs(quote.ts_ns - target), quote.ts_ns))


def _is_crossed(quote: Quote) -> bool:
    return quote.ask is not None and quote.bid is not None and quote.bid >= quote.ask


def select_frame(*, climate_day: dt.date, quotes: Mapping[str, Sequence[Quote]]) -> FrameSelection:
    """Time-only nearest row per rung. Never the first row. Missing stays missing."""
    if not quotes:
        return FrameSelection("MISSING", "missing rung", ())
    target = _target_ns(climate_day)
    start, end = _offset_bounds_ns(climate_day)
    chosen: list[tuple[str, Quote]] = []
    firsts: list[int] = []
    for instrument_id, series in quotes.items():
        if not series:
            return FrameSelection("MISSING", "missing rung", ())
        firsts.append(min(quote.ts_ns for quote in series))
        pick = _nearest(series, target, start, end)
        if pick is None:
            return FrameSelection("MISSING", "missing rung", ())
        chosen.append((instrument_id, pick))
    try:
        assert_complete_partition([parse_rung(instrument_id) for instrument_id, _q in chosen])
    except (IncompleteLadderError, ValueError):
        return FrameSelection("MISSING", "partition check failed", ())
    frame_ns = max(quote.ts_ns for _instrument_id, quote in chosen)
    lead = FIRST_COMPLETE_LEAD_MIN * 60 * _NS
    if frame_ns < max(firsts) + lead:
        return FrameSelection(
            "MISSING",
            "frame is not 60 minutes after the first complete partition",
            (),
        )
    if any(_is_crossed(quote) for _instrument_id, quote in chosen):
        return FrameSelection("MISSING", "crossed rung", ())
    return FrameSelection("FRAME", "", tuple(chosen))


def _cents(amount: Decimal) -> int:
    """Fee cents: the venue rounds fees half-even, so this one rounds."""
    quantized = amount.quantize(TICK, rounding=ROUND_HALF_EVEN)
    return int(quantized * 100)


def _price_cents(price: Decimal) -> int:
    """Price cents. A price off the tick is refused, never rounded."""
    quantized = price.quantize(TICK, rounding=ROUND_HALF_EVEN)
    if quantized != price:
        raise OffTickError(f"price {price} is not on the {TICK} tick")
    return int(quantized * 100)


def rounded_fill_fee(price: Decimal, q: int) -> Decimal:
    """q=1 is ``fee_on_ask``. q>1 is one rounded fee for the whole fill, not q times it."""
    if q == 1:
        return fee_on_ask(price, FEE_COEFFICIENT)
    from breezy.adapters.polymarket_us.fees import taker_fee_at_fill

    money = taker_fee_at_fill(
        quantity=Decimal(q),
        price=price,
        ts_event_ns=_FEE_PROBE_TS_NS,
        fee_coefficient_at_fill=FEE_COEFFICIENT,
    )
    if money is None:
        raise RuntimeError("q-fill fee is unavailable")
    return cast(Decimal, money.as_decimal())


def leg1_slack_cents(asks: Sequence[Decimal]) -> int:
    """Integer cents: ``(100 - 2n) - (sum ask cents + sum fee cents)``. Clears at >= 0."""
    n = len(asks)
    total = sum(_price_cents(price) + _cents(fee_on_ask(price, FEE_COEFFICIENT)) for price in asks)
    return (100 - 2 * n) - total


def leg2_slack_cents(bids: Sequence[Decimal]) -> int:
    """Integer cents: bid cents minus fee_1(1-bid), against ``100 + 2n``."""
    n = len(bids)
    net = 0
    for bid in bids:
        net += _price_cents(bid) - _cents(fee_on_ask(Decimal(1) - bid, FEE_COEFFICIENT))
    return net - (100 + 2 * n)


def _slack_at_q(prices: Sequence[Decimal], q: int, *, side: str) -> int:
    """Whole-fill cents. Leg 1: ``q*(100-2n) - (q*sum ask + sum fee_q)``.

    Leg 2: ``(q*sum bid - sum fee_q on the NO price) - q*(100+2n)``. Clears at >= 0.
    """
    n = len(prices)
    price_cents = q * sum(_price_cents(price) for price in prices)
    if side == "ask":
        fees = sum(_cents(rounded_fill_fee(price, q)) for price in prices)
        return q * (100 - 2 * n) - (price_cents + fees)
    fees = sum(_cents(rounded_fill_fee(Decimal(1) - bid, q)) for bid in prices)
    return (price_cents - fees) - q * (100 + 2 * n)


def evaluate_book(
    rows: Sequence[tuple[Decimal | None, Decimal, Decimal | None, Decimal]],
) -> BookEval:
    """One hand-built partition. Empty is not a clear. A crossed rung clears neither leg."""
    if not rows:
        return BookEval(crossed=False, leg1_clear=False, leg2_clear=False)
    crossed = any(
        ask is not None and bid is not None and bid >= ask for ask, _asz, bid, _bsz in rows
    )
    if crossed:
        return BookEval(crossed=True, leg1_clear=False, leg2_clear=False)
    asks = [ask for ask, _asz, _bid, _bsz in rows if ask is not None]
    bids = [bid for _ask, _asz, bid, _bsz in rows if bid is not None]
    leg1 = (
        len(asks) == len(rows)
        and all(size >= 1 for _ask, size, _bid, _bsz in rows)
        and leg1_slack_cents(asks) >= 0
    )
    leg2 = (
        len(bids) == len(rows)
        and all(size >= 1 for _ask, _asz, _bid, size in rows)
        and leg2_slack_cents(bids) >= 0
    )
    return BookEval(crossed=False, leg1_clear=leg1, leg2_clear=leg2)


def frame_excluded(frame_ns: int, rung_ids: Sequence[str], first_ns: Mapping[str, int]) -> bool:
    """Drop the frame when any rung's base slug was ours at or before the frame time."""
    for rung_id in rung_ids:
        base = base_symbol_of(symbol_of_instrument_id(rung_id))
        started = first_ns.get(base)
        if started is not None and frame_ns >= started:
            return True
    return False


def format_own_set(own: OwnSet) -> str:
    """Instrument ids and a count. Never an order id, intent id, or fingerprint."""
    lines = [f"own-order instrument count: {len(own.instrument_ids)}", *own.instrument_ids]
    return "\n".join(lines)


def _as_bytes(value: object) -> bytes:
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, bytes):
        return value
    raise OwnOrderError("own-order set cannot be built: unreadable slot row")


@contextmanager
def _ro(path: Path) -> Iterator[sqlite3.Connection]:
    """mode=ro plus query_only. Never ``SqliteStateStore`` (that one creates and commits)."""
    uri = f"{path.absolute().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        connection.execute("PRAGMA query_only=ON")
        yield connection
    finally:
        connection.close()


def _remember(first: dict[str, int], base: str, created_ns: int) -> None:
    previous = first.get(base)
    if previous is None or created_ns < previous:
        first[base] = created_ns


def _base_of(instrument_or_slug: str) -> str:
    return base_symbol_of(symbol_of_instrument_id(instrument_or_slug))


_FILL_INDEX_BROKEN: Final[str] = (
    "own-order set cannot be built: a fill_by_fingerprint index has no readable fill row"
)
_EMPTY_HISTORY: Final[str] = "own-order set cannot be built: intent history is empty"
_ANSI: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_SUBMIT_MARK: Final[str] = "[Risk] SubmitOrder("
_STAMP: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}T[0-9:.]+Z")
_HEAD: Final[str] = r"(?P<side>[A-Z_]+) (?P<qty>[0-9_.]+) (?P<iid>\S+) "
_TAIL: Final[str] = r", status=[^,]*, client_order_id=(?P<coid>[^,)\s]+)"
_LIMIT_SHAPE: Final[re.Pattern[str]] = re.compile(
    r"order=LimitOrder\("
    + _HEAD
    + r"LIMIT @ (?P<price>[0-9_.]+) (?P<tif>[A-Z_]+)(?: [^\s,]+)?"
    + _TAIL
)
_MARKET_SHAPE: Final[re.Pattern[str]] = re.compile(
    r"order=MarketOrder\(" + _HEAD + r"MARKET (?P<tif>[A-Z_]+)" + _TAIL
)


@dataclass(frozen=True, slots=True)
class _PrintedOrder:
    """The six attributes ``intent_fingerprint`` reads, already in their ``str()`` forms."""

    instrument_id: str
    side: str
    quantity: str
    price: str
    time_in_force: str
    client_order_id: str


@dataclass(slots=True)
class _LogScan:
    bases_by_digest: dict[str, set[str]] = field(default_factory=dict)
    files: int = 0
    symlinks: int = 0
    first_stamp: str = ""
    last_stamp: str = ""


def parse_submit_order(raw_line: str) -> tuple[str, str] | None:
    """(instrument_id, fingerprint digest) of a ``[Risk] SubmitOrder(`` line, else None.

    An unknown order shape, or a side / time-in-force name outside Nautilus' closed member set,
    is a refusal (the existing membership-guarded ``_enum_forms`` raises before the native
    parser can abort the interpreter).
    """
    from breezy.persistence.autonomy.capture_reader import (
        CaptureProjectionError,
        _enum_forms,
    )

    text = _ANSI.sub("", raw_line)
    at = text.find(_SUBMIT_MARK)
    if at < 0:
        return None
    body = text[at + len(_SUBMIT_MARK) :]
    found = _LIMIT_SHAPE.match(body) or _MARKET_SHAPE.match(body)
    if found is None:
        raise OwnOrderError("own-order set cannot be built: unknown SubmitOrder shape in a log")
    fields_ = found.groupdict()
    try:
        side, tif = _enum_forms({"order_side": fields_["side"], "time_in_force": fields_["tif"]})
    except CaptureProjectionError:
        raise OwnOrderError(
            "own-order set cannot be built: unknown side or time in force in a log"
        ) from None
    printed = _PrintedOrder(
        instrument_id=fields_["iid"],
        side=side,
        quantity=fields_["qty"].replace("_", ""),
        price=fields_.get("price", "").replace("_", ""),
        time_in_force=tif,
        client_order_id=fields_["coid"],
    )
    return printed.instrument_id, intent_fingerprint(printed)


def _scan_node_logs(wanted: frozenset[str]) -> _LogScan:
    """Read every node log as bytes (symlinks followed by opening the path). Read-only."""
    scan = _LogScan()
    for path in sorted(LOG_DIR.glob(LOG_GLOB)):
        try:
            with path.open("rb") as handle:
                lines: Iterable[bytes] = handle
                for chunk in lines:
                    if b"SubmitOrder(" not in chunk:
                        continue
                    line = chunk.decode("utf-8", errors="replace")
                    parsed = parse_submit_order(line)
                    if parsed is None:
                        continue
                    stamp = _STAMP.match(_ANSI.sub("", line))
                    if stamp is not None:
                        moment = stamp.group(0)
                        scan.first_stamp = min(scan.first_stamp or moment, moment)
                        scan.last_stamp = max(scan.last_stamp, moment)
                    instrument_id, digest = parsed
                    if digest in wanted:
                        scan.bases_by_digest.setdefault(digest, set()).add(_base_of(instrument_id))
        except OSError:
            raise OwnOrderError("own-order set cannot be built: a node log is unreadable") from None
        scan.files += 1
        scan.symlinks += 1 if path.is_symlink() else 0
    return scan


def _resolve_by_logs(
    slugless: Sequence[tuple[str, int, str | None]],
) -> tuple[dict[str, str], _LogScan]:
    """fingerprint -> base slug by the node logs; two bases for one fingerprint refuse."""
    scan = _scan_node_logs(frozenset(fingerprint for fingerprint, _ns, _base in slugless))
    resolved: dict[str, str] = {}
    for digest, bases in scan.bases_by_digest.items():
        if len(bases) > 1:
            raise OwnOrderError("own-order set cannot be built: a fingerprint matches two slugs")
        resolved[digest] = next(iter(bases))
    return resolved, scan


def _d5_report(
    *,
    total: int,
    by_fill: int,
    by_log: int,
    control: tuple[int, int],
    unresolved: Counter[str],
    scan: _LogScan,
) -> tuple[str, ...]:
    """D5 counts only: never an id, a fingerprint or an order id."""
    per_day = ", ".join(f"{day}: {count}" for day, count in sorted(unresolved.items())) or "none"
    return (
        f"D5 intents total: {total}",
        f"D5 resolved by (i) fill_by_fingerprint: {by_fill}",
        f"D5 resolved by (ii) node log: {by_log}",
        f"D5 positive control matched/total: {control[0]}/{control[1]}",
        f"D5 unresolved: {sum(unresolved.values())}",
        f"D5 unresolved per UTC created day: {per_day}",
        f"D5 log files read: {scan.files}",
        f"D5 symlinks followed: {scan.symlinks}",
        f"D5 first log timestamp read: {scan.first_stamp or 'none'}",
        f"D5 last log timestamp read: {scan.last_stamp or 'none'}",
    )


def _base_by_fill(
    created_ns: int, fingerprint: str, get: Callable[[str], bytes | None]
) -> str | None:
    """Resolution (i): fill_by_fingerprint to fill to the base slug, or None."""
    from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
    from breezy.domain.exec_intent import FILL_BY_FINGERPRINT_KEY_PREFIX, FILL_KEY_PREFIX

    day = utc_day_for_ns(created_ns).isoformat()
    index = get(f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{day}:{fingerprint}")
    if index is None:
        return None
    try:
        vid = index.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise OwnOrderError(_FILL_INDEX_BROKEN) from None
    if not vid:
        raise OwnOrderError(_FILL_INDEX_BROKEN)
    fill_raw = get(f"{FILL_KEY_PREFIX}{vid}")
    if fill_raw is None or not fill_raw.strip():
        raise OwnOrderError(_FILL_INDEX_BROKEN)
    try:
        record = DurableFillRecord.from_bytes(fill_raw)
    except (ValueError, TypeError):
        raise OwnOrderError("own-order set cannot be built: unreadable fill record") from None
    return _base_of(record.instrument_id)


def read_own_orders(path: Path) -> OwnSet:
    """Scan intent history and the current slot table. Slug-less and unreadable refuse."""
    from breezy.runtime.exec_par_durable_sources import HISTORY_KEY_PREFIX
    from breezy.runtime.submit_intent import (
        CURRENT_INTENT_KEY,
        SubmitIntent,
        SubmitIntentCorrupt,
        decode_slot_table,
    )

    first: dict[str, int] = {}
    slugged = 0
    try:
        with _ro(path) as connection:
            history = connection.execute(
                "SELECT value FROM state WHERE substr(key, 1, ?) = ?",
                (len(HISTORY_KEY_PREFIX), HISTORY_KEY_PREFIX),
            ).fetchall()
            current = connection.execute(
                "SELECT value FROM state WHERE key = ?",
                (CURRENT_INTENT_KEY,),
            ).fetchone()
            intents: list[SubmitIntent] = []
            for (value,) in history:
                try:
                    intents.append(SubmitIntent.from_bytes(_as_bytes(value)))
                except (SubmitIntentCorrupt, ValueError, TypeError, OwnOrderError):
                    raise OwnOrderError(
                        "own-order set cannot be built: history row did not decode"
                    ) from None
            raw = None if current is None else _as_bytes(current[0])
            try:
                table = decode_slot_table(raw)
            except SubmitIntentCorrupt:
                raise OwnOrderError("own-order set cannot be built: unreadable slot row") from None
            if table.unreadable:
                raise OwnOrderError("own-order set cannot be built: unreadable slot row")
            intents.extend(table.open)
            if table.last is not None:
                intents.append(table.last)
            if not intents:
                raise OwnOrderError(_EMPTY_HISTORY)

            def _get(key: str) -> bytes | None:
                found = connection.execute(
                    "SELECT value FROM state WHERE key = ?", (key,)
                ).fetchone()
                return None if found is None else _as_bytes(found[0])

            slugless: list[tuple[str, int, str | None]] = []
            for intent in intents:
                if intent.slug:
                    slugged += 1
                    _remember(first, _base_of(intent.slug), intent.created_ns)
                    continue
                base = _base_by_fill(intent.created_ns, intent.fingerprint, _get)
                slugless.append((intent.fingerprint, intent.created_ns, base))
    except sqlite3.Error:
        raise OwnOrderError("own-order set cannot be built: store is unreadable") from None
    resolved, scan = _resolve_by_logs(slugless) if slugless else ({}, _LogScan())
    by_fill = by_log = matched = controls = 0
    unresolved: Counter[str] = Counter()
    for fingerprint, created_ns, fill_base in slugless:
        log_base = resolved.get(fingerprint)
        if fill_base is not None:
            by_fill += 1
            controls += 1
            matched += 1 if log_base == fill_base else 0
            _remember(first, fill_base, created_ns)
        elif log_base is not None:
            by_log += 1
            _remember(first, log_base, created_ns)
        else:
            unresolved[utc_day_for_ns(created_ns).isoformat()] += 1
    report = _d5_report(
        total=len(slugless) + slugged,
        by_fill=by_fill,
        by_log=by_log,
        control=(matched, controls),
        unresolved=unresolved,
        scan=scan,
    )
    if matched != controls:
        raise OwnOrderError(
            "own-order set cannot be built: positive control mismatch (fill path vs node log)",
            report,
        )
    if unresolved:
        raise OwnOrderError(
            f"own-order set cannot be built: {sum(unresolved.values())} slug-less intent(s) "
            "unresolved by fill and node log",
            report,
        )
    if controls == 0:
        raise OwnOrderError(
            "own-order set cannot be built: positive control has no intent resolved by fill",
            report,
        )
    return OwnSet(instrument_ids=tuple(sorted(first)), first_ns=first, report=report)


def _parse_freeze(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        refuse("freeze record unreadable")
    for line in text.splitlines():
        if not line.strip():
            continue
        key, _sep, value = line.partition(" ")
        fields[key] = value.strip()
    return fields


def _check_freeze(prereg_sha: str) -> None:
    if not FREEZE_PATH.is_file():
        refuse("freeze record missing")
    if not PREREG_PATH.is_file():
        refuse("prereg sha256 mismatch")
    fields = _parse_freeze(FREEZE_PATH)
    problems: list[str] = []
    status = fields.get("status", "").strip()
    if status != "FROZEN":
        problems.append(f"freeze status is {status or 'absent'}")
    if status == "FROZEN" and fields.get("looks_allowed", "").strip() != "1":
        problems.append("looks_allowed is not 1")
    try:
        live = hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()
    except OSError:
        refuse("prereg unreadable")
    recorded = fields.get("prereg_sha256", "").strip().lower()
    given = prereg_sha.strip().lower()
    if recorded != given or recorded != live or given != live:
        problems.append("prereg sha256 mismatch")
    if problems:
        refuse("; ".join(problems))


def _carries_sha(out: Path, sha: str) -> bool:
    """Either artefact carrying the sha is a prior look (a lone parquet is a half-emitted one)."""
    markdown = out / "card_a_census.md"
    parquet = out / "card_a_census.parquet"
    if markdown.is_file():
        try:
            text = markdown.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            refuse("existing census markdown is unreadable")
        header = "".join(text.splitlines(keepends=True)[:30])
        if f"prereg_sha256: {sha}" in header:
            return True
    if not parquet.is_file():
        return False
    try:
        import pyarrow.parquet as pq

        meta = pq.read_schema(parquet).metadata or {}
    except (OSError, ValueError):
        refuse("existing census parquet is unreadable")
    return meta.get(b"prereg_sha256") == sha.encode()


def emit_census(
    out: Path,
    markdown: str,
    records: Sequence[Mapping[str, object]],
    sha: str,
    dry_run: bool = False,
) -> None:
    """Temp files in ``out``, then ``os.replace``: parquet first, markdown LAST.

    A prior look with this sha refuses.
    """
    if dry_run:
        return
    if _carries_sha(out, sha):
        refuse("prior look already carries this prereg sha256")
    out.mkdir(parents=True, exist_ok=True)
    md_tmp = out / f".card_a_census.md.{os.getpid()}.tmp"
    pq_tmp = out / f".card_a_census.parquet.{os.getpid()}.tmp"
    try:
        _write_parquet(pq_tmp, records, sha)
        md_tmp.write_text(markdown, encoding="utf-8")
        os.replace(pq_tmp, out / "card_a_census.parquet")
        os.replace(md_tmp, out / "card_a_census.md")
    finally:
        md_tmp.unlink(missing_ok=True)
        pq_tmp.unlink(missing_ok=True)


def _write_parquet(path: Path, records: Sequence[Mapping[str, object]], sha: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    def _cell(row: Mapping[str, object], name: str) -> str:
        value = row.get(name, "")
        return "" if value is None else str(value)

    schema = pa.schema(
        [(name, pa.string()) for name in _COLUMNS],
        metadata={b"prereg_sha256": sha.encode("ascii")},
    )
    columns = {
        name: pa.array([_cell(row, name) for row in records], type=pa.string()) for name in _COLUMNS
    }
    pq.write_table(pa.table(columns, schema=schema), path)


def _label(clears: int, denominator: int, dates: int, unit_ok: bool) -> str:
    if not unit_ok or denominator < FLOOR_STATION_DAYS or dates < FLOOR_DATES:
        return "INCONCLUSIVE"
    if clears >= 1:
        return "PASS"
    return "KILL"


def _recover_unit(instants: Sequence[object], size_scalar: float) -> tuple[int | None, bool]:
    """First nonzero ``ask_size`` fixes the unit. A zero pad proves nothing.

    Returns ``(raw, failed)``: ``(None, False)`` when every size is zero.
    """
    for instant in instants:
        size = float(getattr(instant, "ask_size"))  # noqa: B009
        if size == 0:
            continue
        recovered = _recover_raw(size, size_scalar)
        return recovered, recovered is None
    return None, False


def scrub_legs_without_unit(
    records: Sequence[dict[str, str]], unit_ok: bool
) -> list[dict[str, str]]:
    """No per-record leg verdict is written when the unit line failed."""
    if unit_ok:
        return list(records)
    return [{**row, "leg1": "", "leg2": ""} for row in records]


def _recover_raw(scaled: float, size_scalar: float) -> int | None:
    product = Decimal(str(size_scalar)) * Decimal(str(scaled))
    nearest = product.to_integral_value(rounding=ROUND_HALF_EVEN)
    if abs(product - nearest) > _RAW_TOLERANCE:
        return None
    return int(nearest)


def bands_impossible(high_upper_f: int | None, low_lower_f: int | None) -> bool:
    """A high band that ends below a low band's floor cannot both settle."""
    if high_upper_f is None or low_lower_f is None:
        return False
    return high_upper_f < low_lower_f


def _family_lines() -> list[str]:
    lines = [
        "## Family manifest cross-check",
        "",
        "Manifests are a cross-check only. The store scan is the superset.",
    ]
    root = _REPO / "deploy" / "families"
    for name in _FAMILY_FILES:
        path = root / name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            lines.append(f"- {name}: unreadable")
            continue
        prefix = payload.get("trial_id_prefix") if isinstance(payload, dict) else None
        lines.append(f"- {name}: trial_id_prefix {prefix}")
    return lines


def _buyer_lines(catalog: Path) -> list[str]:
    """Count is not taken. ``CatalogSession.read`` mkdir's a scratch catalog (H3 forbids it)."""
    trade_root = catalog / "data" / "trade_tick"
    if not trade_root.is_dir():
        return [
            "## BUYER prints",
            "",
            (
                "trade_tick stream absent; CatalogSession not invoked "
                "because it writes a scratch catalog."
            ),
        ]
    return [
        "## BUYER prints",
        "",
        (
            "trade_tick stream present; CatalogSession not invoked "
            "because it writes a scratch catalog."
        ),
        "BUYER print counts were not taken.",
    ]


def _quote_from_instant(instant: object) -> Quote:
    from forecast_cheap_screen_wp7 import RungInstant  # type: ignore[import-not-found]

    if not isinstance(instant, RungInstant):
        raise TypeError("depth row is not a rung instant")
    return Quote(
        ts_ns=instant.ts_ns,
        ask=None if instant.ask is None else Decimal(str(instant.ask)),
        ask_size=Decimal(str(instant.ask_size)),
        bid=None if instant.bid is None else Decimal(str(instant.bid)),
        bid_size=Decimal(str(instant.bid_size)),
    )


def _fee_raw(fee_map: Mapping[str, str], instrument_id: str) -> str | None:
    raw = fee_map.get(instrument_id)
    if raw is None:
        raw = fee_map.get(symbol_of_instrument_id(instrument_id))
    return raw


def _fee_ok(fee_map: Mapping[str, str], instrument_id: str) -> bool:
    """A PRESENT coefficient equal to the frozen one. Absent or garbled never reaches here."""
    raw = _fee_raw(fee_map, instrument_id)
    return raw is not None and Decimal(raw) == FEE_COEFFICIENT


def _require_fee_entries(fee_map: Mapping[str, str], rung_ids: Iterable[str]) -> None:
    """Only a PRESENT coefficient that differs stays INCONCLUSIVE; absent or garbled refuses."""
    for instrument_id in rung_ids:
        raw = _fee_raw(fee_map, instrument_id)
        if raw is None:
            refuse("instrument fee entry missing for a listed rung")
        try:
            Decimal(raw)
        except ArithmeticError:
            refuse("instrument fee entry is not a number")


def _load_fee_map(catalog: Path) -> dict[str, str]:
    """Refuses (exit 2) when the instrument read fails. Constructing the catalog creates nothing."""
    try:
        from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

        found: dict[str, str] = {}
        for instrument in ParquetDataCatalog(str(catalog)).instruments():
            info = instrument.info
            if not isinstance(info, dict):
                continue
            raw = info.get("fee_coefficient")
            if raw is None:
                continue
            found[str(instrument.id)] = str(raw)
        return found
    except (OSError, RuntimeError, TypeError, ValueError, ImportError):
        refuse("instrument fee read failed")


def _walk_dirs(
    depth_root: Path, notes: list[str]
) -> tuple[dict[tuple[str, dt.date], list[Path]], int]:
    grouped: dict[tuple[str, dt.date], list[Path]] = {}
    highs: list[tuple[str, dt.date, int | None]] = []
    lows: list[tuple[str, dt.date, int | None]] = []
    if not depth_root.is_dir():
        refuse("order_book_depths directory is absent")
    for child in sorted(depth_root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        low_match = _LOW_DIR.match(name)
        if low_match is not None:
            alias = f"{low_match.group(1)}high{low_match.group(2)}"
            try:
                rung = parse_rung(alias)
            except ValueError:
                notes.append(f"skipped low dir (unparsed): {name}")
                continue
            notes.append(f"skipped low dir: {name}")
            lows.append((rung.city, rung.climate_day, rung.lower_f))
            continue
        try:
            rung = parse_rung(name)
        except ValueError:
            refuse("an unparsable catalog directory name was found")
        highs.append((rung.city, rung.climate_day, rung.upper_f))
        if WINDOW_START <= rung.climate_day <= WINDOW_END:
            grouped.setdefault((rung.city, rung.climate_day), []).append(child)
    if not highs or not grouped:
        refuse("no rung directory found in the census window")
    impossible = 0
    low_by: dict[tuple[str, dt.date], list[int | None]] = {}
    for city, day, lower in lows:
        low_by.setdefault((city, day), []).append(lower)
    for city, day, upper in highs:
        for lower in low_by.get((city, day), ()):
            if bands_impossible(upper, lower):
                impossible += 1
    return grouped, impossible


#: ``read_rung_tape`` only accepts a station key present in ``STATION_TIME_ZONES`` (the four
#: pool cities) and refuses to guess a zone. NYC is on the catalog but absent there. The census
#: reads only ts/ask/bid, never the local date or hour, so NYC borrows MIA's key: the same
#: IANA zone (America/New_York), and the reader's standard-offset cross-check still runs
#: against NYC's own registry offset.
_READER_KEY: Final[Mapping[str, str]] = {"NYC": "MIA"}


def reader_key(city: str) -> str:
    """The station key ``read_rung_tape`` accepts for a catalog city."""
    return _READER_KEY.get(city, city)


def _score(
    catalog: Path, own: OwnSet, *, frame_only: bool = False
) -> tuple[list[str], list[dict[str, str]], list[_Denom], bool, int, int]:
    """Returns notes, records, denominator frames, unit_ok, sum-ask count, impossible pairs."""
    notes: list[str] = []
    if not (catalog / "data").is_dir():
        refuse("catalog data directory is absent")
    from forecast_cheap_screen_wp7 import (
        _fixed_scalars,
        read_rung_tape,
    )
    from settlement_alignment_study import load_sites  # type: ignore[import-not-found]

    try:
        price_scalar, size_scalar = _fixed_scalars()
    except (OSError, RuntimeError, TypeError, ValueError, ImportError):
        refuse("unit scalars could not be read")
    try:
        offsets = {spec.city: float(spec.std_utc_offset_hours) for spec in load_sites()}
    except (OSError, RuntimeError, TypeError, ValueError, ImportError):
        refuse("site metadata could not be read")
    grouped, impossible = _walk_dirs(catalog / "data" / "order_book_depths", notes)
    if any(city not in offsets for city, _day in grouped):
        refuse("a listed station has no site metadata")
    fee_map = _load_fee_map(catalog)
    _require_fee_entries(fee_map, (path.name for paths in grouped.values() for path in paths))
    records: list[dict[str, str]] = []
    denoms: list[_Denom] = []
    unit_raw: int | None = None
    unit_failed = False
    sum_rows = 0
    for (city, day), paths in sorted(grouped.items()):
        offset = offsets[city]
        quotes: dict[str, tuple[Quote, ...]] = {}
        for path in sorted(paths, key=lambda item: item.name):
            try:
                instants, _nrows = read_rung_tape(
                    path,
                    std_utc_offset_hours=offset,
                    price_scalar=price_scalar,
                    size_scalar=size_scalar,
                    city=reader_key(city),
                )
            except (OSError, ValueError, KeyError):
                refuse(f"{city} {day.isoformat()}: tape read failed")
            if not instants:
                refuse(f"{city} {day.isoformat()}: a listed rung has no tape instants")
            if unit_raw is None and not unit_failed:
                unit_raw, unit_failed = _recover_unit(instants, size_scalar)
            quotes[path.name] = tuple(_quote_from_instant(instant) for instant in instants)
        frame = select_frame(climate_day=day, quotes=quotes)
        if frame.kind != "FRAME":
            records.append(
                {
                    "station": city,
                    "climate_day": day.isoformat(),
                    "status": "MISSING",
                    "leg1": "",
                    "leg2": "",
                }
            )
            continue
        rung_ids = [instrument_id for instrument_id, _quote in frame.chosen]
        frame_ns = max(quote.ts_ns for _instrument_id, quote in frame.chosen)
        if frame_excluded(frame_ns, rung_ids, own.first_ns):
            records.append(
                {
                    "station": city,
                    "climate_day": day.isoformat(),
                    "status": "EXCLUDED",
                    "leg1": "",
                    "leg2": "",
                }
            )
            continue
        fees_ok = all(_fee_ok(fee_map, instrument_id) for instrument_id in rung_ids)
        if not fees_ok:
            records.append(
                {
                    "station": city,
                    "climate_day": day.isoformat(),
                    "status": "INCONCLUSIVE",
                    "leg1": "",
                    "leg2": "",
                }
            )
            continue
        if frame_only:
            denoms.append(
                _Denom(
                    day=day, asks=(), ask_sizes=(), bids=(), bid_sizes=(), leg1=False, leg2=False
                )
            )
            continue
        rows = tuple(
            (quote.ask, quote.ask_size, quote.bid, quote.bid_size) for _iid, quote in frame.chosen
        )
        book = evaluate_book(rows)
        asks = tuple(quote.ask for _iid, quote in frame.chosen if quote.ask is not None)
        bids = tuple(quote.bid for _iid, quote in frame.chosen if quote.bid is not None)
        ask_sizes = tuple(quote.ask_size for _iid, quote in frame.chosen)
        bid_sizes = tuple(quote.bid_size for _iid, quote in frame.chosen)
        if book.leg1_clear and len(asks) == len(frame.chosen):
            SumAskRow(
                station=city,
                climate_day=day,
                n_rungs=len(asks),
                sum_ask=float(sum(asks, Decimal(0))),
                sum_fee=float(sum((fee_on_ask(ask, FEE_COEFFICIENT) for ask in asks), Decimal(0))),
                min_ask_size=float(min(ask_sizes)),
                total_ask_size=float(sum(ask_sizes, Decimal(0))),
            )
            sum_rows += 1
        denoms.append(
            _Denom(
                day=day,
                asks=asks,
                ask_sizes=ask_sizes,
                bids=bids,
                bid_sizes=bid_sizes,
                leg1=book.leg1_clear,
                leg2=book.leg2_clear,
            )
        )
        records.append(
            {
                "station": city,
                "climate_day": day.isoformat(),
                "status": "FRAME",
                "leg1": "clear" if book.leg1_clear else "no",
                "leg2": "clear" if book.leg2_clear else "no",
            }
        )
    if unit_failed:
        refuse("unit line could not be recovered from a nonzero ask size")
    unit_ok = unit_raw is not None
    records = list(scrub_legs_without_unit(records, unit_ok))
    notes.append(
        f"unit scalars price={price_scalar} size={size_scalar} raw_ask_size_0={unit_raw} contracts"
        if unit_ok
        else "unit line could not be printed"
    )
    notes.extend(_buyer_lines(catalog))
    return notes, records, denoms, unit_ok, sum_rows, impossible


def _prize_lines(label: str, frames: Sequence[_Denom], *, side: str) -> list[str]:
    if label != "PASS":
        return [f"prize not printed for this leg ({label}); a prize is not a PASS or a KILL."]
    lines: list[str] = []
    for q in Q_GRID:
        count = 0
        for frame in frames:
            prices = frame.asks if side == "ask" else frame.bids
            sizes = frame.ask_sizes if side == "ask" else frame.bid_sizes
            cleared = frame.leg1 if side == "ask" else frame.leg2
            if (
                cleared
                and prices
                and sizes
                and min(sizes) >= q
                and _slack_at_q(prices, q, side=side) >= 0
            ):
                count += 1
        normalized = Decimal(count) * Decimal(NORMALIZER_DAYS) / Decimal(WINDOW_DAYS)
        lines.append(f"q={q} frames={count} normalized_30d={format(normalized, 'f')}")
    return lines


def _assumptions() -> list[str]:
    return [
        (
            "Assumptions: full-size simultaneous taker fills; no leg risk; the two legs "
            "are never both executed; voids are out of scope; the executable NO price "
            "may differ from 1 minus the YES bid under the SELL or BUY_SHORT representation."
        ),
        (
            "The q grid is a report index, never an order quantity. "
            "No budget and no per-position size are read or set."
        ),
        "Two ticks per rung (one tick of slippage plus one tick of hurdle) are applied once.",
        "A q-fill fee is one rounded fee per fill, not q times the one-contract fee.",
        "A frame counts for q only when min L0 size is at least q and the margin still clears.",
        f"The 30-day normalizer is count * {NORMALIZER_DAYS}/{WINDOW_DAYS}.",
    ]


def _render(
    sha: str,
    own: OwnSet,
    *,
    notes: Sequence[str],
    denoms: Sequence[_Denom],
    sum_rows: int,
    impossible: int,
    leg1: str,
    leg2: str,
) -> str:
    dates = len({frame.day for frame in denoms})
    lines = [
        "# Card A census",
        "",
        f"prereg_sha256: {sha}",
        "",
        "## Constants",
        "",
        f"window {WINDOW_START.isoformat()}..{WINDOW_END.isoformat()} ({WINDOW_DAYS} dates)",
        (
            f"target {TARGET_CLOCK.isoformat()}Z "
            f"offset [{OFFSET_START.isoformat()}, {OFFSET_END.isoformat()})"
        ),
        f"age cap {AGE_CAP_S}s first-complete lead {FIRST_COMPLETE_LEAD_MIN} min",
        f"tick {TICK} hurdle {HURDLE} fee coefficient {FEE_COEFFICIENT}",
        f"floors {FLOOR_STATION_DAYS} station-days and {FLOOR_DATES} dates",
        f"q grid {Q_GRID} normalizer {NORMALIZER_DAYS} over {WINDOW_DAYS}",
        "No CLI override.",
        "",
        "## Unit line",
        "",
        next(
            (note for note in notes if note.startswith("unit ")),
            "unit line could not be printed",
        ),
        "",
        "## Own-order set",
        "",
        format_own_set(own),
        f"slug-less never-filled intents: {own.never_filled}",
        *own.report,
        "",
        "## Legs",
        "",
        f"leg 1: {leg1}",
        f"leg 2: {leg2}",
        f"denominator station-days: {len(denoms)}",
        f"distinct dates: {dates}",
        f"n_sum_ask_rows: {sum_rows}",
        "SumAskRow is counted and is not the comparator.",
        "",
        "## Prize",
        "",
        *_prize_lines(leg1, denoms, side="ask"),
        *_prize_lines(leg2, denoms, side="bid"),
        *_assumptions(),
        "",
        "## Impossible pairs",
        "",
        f"impossible pairs: {impossible}",
        "",
        "## Node journal",
        "",
        "node journal cross-check: not performed",
        "",
        *_family_lines(),
        "",
        "## Notes",
        "",
        *[note for note in notes if not note.startswith("unit ")],
        "",
    ]
    return "\n".join(lines)


def _dry_run_stop(own: OwnSet) -> int:
    """H7: D5 counts, final denominator and distinct dates ONLY. Never a leg, label or prize."""
    print("\n".join(own.report), flush=True)
    try:
        _notes, _records, denoms, _unit, _sums, _impossible = _score(CATALOG, own, frame_only=True)
    except OffTickError as exc:
        refuse(f"off-tick price refused: {exc}")
    print(f"final denominator station-days: {len(denoms)}")
    print(f"distinct dates: {len({frame.day for frame in denoms})}")
    return 0


def run_census(*, prereg_sha: str | None, tape_supplied: bool, dry_run: bool) -> int:
    """Freeze, own orders, then the catalog. Refusals exit 2 before any write."""
    assert_constants()
    if not prereg_sha:
        refuse("census mode requires --prereg-sha")
    if tape_supplied:
        refuse("--tape is refused with --census-only")
    _check_freeze(prereg_sha)
    sha = prereg_sha.strip().lower()
    if _carries_sha(OUTPUT_DIR, sha):
        refuse("prior look already carries this prereg sha256")
    try:
        store = resolve_store_path(os.environ)
    except ExecStateDbNotConfiguredError as exc:
        refuse(str(exc))
    if not store.is_file():
        refuse("own-order set cannot be built: store is unreadable")
    try:
        own = read_own_orders(store)
    except OwnOrderError as exc:
        print("\n".join(exc.report))
        refuse(str(exc))
    if dry_run:
        return _dry_run_stop(own)
    try:
        notes, records, denoms, unit_ok, sum_rows, impossible = _score(CATALOG, own)
    except OffTickError as exc:
        refuse(f"off-tick price refused: {exc}")
    dates = {frame.day for frame in denoms}
    leg1 = _label(sum(1 for frame in denoms if frame.leg1), len(denoms), len(dates), unit_ok)
    leg2 = _label(sum(1 for frame in denoms if frame.leg2), len(denoms), len(dates), unit_ok)
    markdown = _render(
        sha,
        own,
        notes=notes,
        denoms=denoms,
        sum_rows=sum_rows,
        impossible=impossible,
        leg1=leg1,
        leg2=leg2,
    )
    emit_census(OUTPUT_DIR, markdown, records, sha, dry_run=False)
    return 0
