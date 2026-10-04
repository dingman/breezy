"""Fixtures for the audit's I/O and orchestration tests (AUT-1 WP5 stage 2b, W3).

Everything here builds a REAL on-disk data root under ``tmp_path`` and nothing fakes a format:
node logs are written from the retained-line fixtures, streams by the real ``CaptureStreamWriter``,
the exec store through the real ``DurableFillRecord.to_bytes`` into a real SQLite file, the tape as
real Parquet in the recorder's catalog layout, the bus snapshot in seam B's document shape. The only
fakes are the two W2 sinks (a stub replay and a stub marker collector) and the process boundary
(``journalctl``), which are patched in by ``install``.
"""

import datetime as dt
import json
import os
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pyarrow as pa
import pyarrow.parquet as pq

from breezy.adapters.polymarket_us.exec import client as exec_client
from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis import capture_audit as audit
from breezy.analysis import capture_audit_host as host
from breezy.analysis import capture_audit_inputs as inputs
from breezy.analysis.capture_audit_input_types import LogMarkers, ReplayResult
from breezy.analysis.capture_audit_model import (
    AuditInputError,
    Finding,
    Leg,
    LegOutcome,
    LegResult,
)
from breezy.analysis.capture_node_log import scan_node_log
from breezy.domain.exec_intent import (
    FILL_BY_DAY_KEY_PREFIX,
    FILL_KEY_PREFIX,
    VENUE_ORDER_ID_KEY_PREFIX,
    utc_day_for_ns,
)
from breezy.persistence.autonomy.capture_epoch import write_epoch_once
from breezy.persistence.autonomy.capture_records import CaptureHeartbeat, make_record
from breezy.persistence.autonomy.capture_stream import capture_root
from breezy.runtime.autonomy_sandbox.table import (
    SYSTEMCTL,
    BusRead,
    BwrapRow,
)
from breezy.runtime.autonomy_sandbox.wal_snapshot import EXEC_STORE_FILENAME
from tests.support.capture_node_log_fixtures import (
    ANSI_OFF,
    ANSI_ON,
    CONSTRUCTED_EPOCH_START,
    REAL_SUP_LAUNCHED,
    REAL_TAKE,
    write_log,
)
from tests.unit.capture_reader_support import decision, open_stream, write_all

NS: Final[int] = 1_000_000_000
DAY: Final[dt.date] = dt.date(2026, 10, 3)
FAMILY: Final[str] = "pm_us_fq_test"
INSTANCE: Final[str] = "01cea9fc-cf7d-4efa-b132-cbbaf5d0bde4"
OTHER_INSTANCE: Final[str] = "7a1b2c3d-0000-4000-8000-000000000001"
LOG_STAMP: Final[str] = "20261003T165045Z"
INSTRUMENT: Final[str] = "tc-temp-laxhigh-2026-10-04-gte93lt94f.POLYMARKET_US"
INVOCATION: Final[str] = "0123456789abcdef0123456789abcdef"
SNAP_BIND: Final[str] = "cache/capture_audit_bus"
VENUE: Final[str] = "polymarket_us"
#: The wall clock every gather in the tests runs at: 14:00Z on D+1 (the audit's own morning).
NOW_NS: Final[int] = int(dt.datetime(2026, 10, 4, 14, 0, tzinfo=dt.UTC).timestamp()) * NS


def day_ns(day: dt.date, hour: int = 0, minute: int = 0) -> int:
    return (
        int(dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC).timestamp()) * NS
    )


# -- the data root -------------------------------------------------------------------------------


def make_root(tmp_path: Path) -> Path:
    """A fresh 0700 data root with the directories the audit reads."""
    root = tmp_path / "data"
    for rel in (
        "",
        "logs",
        "state",
        "catalog/quote_tape/decisions",
        "catalog/quote_tape/polymarket_us",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    for path in (root, root / "state", root / "logs"):
        path.chmod(0o700)
    return root


def _iso(ns: int) -> str:
    moment = dt.datetime.fromtimestamp(ns // NS, dt.UTC)
    return f"{moment:%Y-%m-%dT%H:%M:%S}.{ns % NS:09d}Z"


#: The ``now_ns`` and log time stamp of the recorded Take line in ``REAL_TAKE``.
_REAL_TAKE_NOW_NS: Final[int] = 1790972432790092624
_REAL_TAKE_LOG_NS: Final[int] = 1790972432924873907


def day_take(hour: int = 17, minute: int = 5) -> str:
    """``REAL_TAKE`` re-timed onto the audited day D (its real line is stamped the day before), so
    the log line, the Take's own clock and the day of the reducer's output all agree (S2-R25)."""
    at = day_ns(DAY, hour, minute)
    line = REAL_TAKE.replace(_iso(_REAL_TAKE_LOG_NS), _iso(at))
    return line.replace(str(_REAL_TAKE_NOW_NS), str(at - (_REAL_TAKE_LOG_NS - _REAL_TAKE_NOW_NS)))


def node_log_lines(
    instance_id: str = INSTANCE,
    *,
    start_ns: int | None = None,
    disposed_ns: int | None = None,
    decisions: Iterable[str] = (),
    epoch_start: bool = False,
) -> list[str]:
    start = day_ns(DAY, 16, 50) if start_ns is None else start_ns
    first = (
        f"{ANSI_ON}{_iso(start)}{ANSI_OFF} [INFO] BREEZY-L001.TradingNode: "
        f"instance_id: {instance_id}{ANSI_OFF}"
    )
    lines = [first]
    if epoch_start:
        lines.append(CONSTRUCTED_EPOCH_START)
    lines.extend(decisions)
    if disposed_ns is not None:
        lines.append(f"{_iso(disposed_ns)} [INFO] BREEZY-L001.TradingNode: DISPOSED")
    return lines


def write_node_log(
    root: Path,
    *,
    stamp: str = LOG_STAMP,
    instance_id: str = INSTANCE,
    start_ns: int | None = None,
    disposed_ns: int | None = None,
    mtime_ns: int | None = None,
    decisions: Iterable[str] = (),
    epoch_start: bool = False,
) -> Path:
    disposed = day_ns(DAY, 23, 0) if disposed_ns is None else disposed_ns
    path = write_log(
        root / "logs" / f"breezy-trade-{stamp}.log",
        *node_log_lines(
            instance_id,
            start_ns=start_ns,
            disposed_ns=disposed,
            decisions=decisions,
            epoch_start=epoch_start,
        ),
    )
    stamp_ns = disposed if mtime_ns is None else mtime_ns
    os.utime(path, ns=(stamp_ns, stamp_ns))
    return path


def supervisor_launched(ts: str = "2026-10-03T16:50:45Z") -> str:
    return REAL_SUP_LAUNCHED.replace("2026-10-03T16:50:45Z", ts)


def write_epoch(root: Path, *, epoch_ns: int | None = None, boot: str = INSTANCE) -> None:
    at = day_ns(DAY, 16, 50) if epoch_ns is None else epoch_ns
    write_epoch_once(root, family_id=FAMILY, node_boot_id=boot, build_sha="0" * 40, now_ns=at)


def write_stream(
    root: Path,
    instance_id: str = INSTANCE,
    *,
    source: str = "live",
    node_boot_id: str | None = None,
    with_decision: bool = True,
) -> None:
    """A real stream: one decision and one heartbeat, both naming ``node_boot_id``."""
    streams = capture_root(root, VENUE)
    streams.mkdir(parents=True, exist_ok=True)
    for directory in (root / "derived", root / "derived" / "capture_stream", streams):
        directory.chmod(0o700)
    stream = open_stream(streams, instance_id=instance_id, source=source)
    owner = node_boot_id if node_boot_id is not None else instance_id
    records: list[Any] = [heartbeat_for(owner)]
    if with_decision:
        records.append(decision(1, node_boot_id=owner, wall_ns=day_ns(DAY, 17, 0)))
    write_all(stream, records)
    stream.close()
    for feather in (streams / source / instance_id).iterdir():
        os.utime(feather, ns=(day_ns(DAY, 18), day_ns(DAY, 18)))


def heartbeat_for(owner: str) -> Any:
    return make_record(
        CaptureHeartbeat,
        ts_event=day_ns(DAY, 17, 0),
        ts_init=day_ns(DAY, 17, 0),
        schema="capture_heartbeat/v1",
        node_boot_id=owner,
        seq=1,
        health_ok=True,
    )


# -- the exec store ------------------------------------------------------------------------------


def fill_record(venue_order_id: str = "CVW455HKJYGE", **over: Any) -> DurableFillRecord:
    fields: dict[str, Any] = {
        "venue_order_id": venue_order_id,
        "client_order_id": "O-20261003-165052-L001-LAX-1",
        "instrument_id": INSTRUMENT,
        "order_side": "BUY",
        "cumulative_qty": Decimal(1),
        "cumulative_cost": Decimal("0.15"),
        "cumulative_fee": Decimal("0.01"),
        "fee_reconciled": True,
        "ts_event": day_ns(DAY, 17, 0),
        "trade_id": "CVWEANWH8YHR",
    }
    fields.update(over)
    return DurableFillRecord(**fields)


def write_exec_store(root: Path, rows: Mapping[str, bytes]) -> Path:
    db = root / "state" / EXEC_STORE_FILENAME
    conn = sqlite3.connect(db, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
        for key, value in rows.items():
            conn.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, value))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    return db


def standard_exec_rows(record: DurableFillRecord | None = None) -> dict[str, bytes]:
    fill = record or fill_record()
    day = utc_day_for_ns(fill.ts_event).isoformat()
    return {
        f"{FILL_KEY_PREFIX}{fill.venue_order_id}": fill.to_bytes(),
        f"{FILL_BY_DAY_KEY_PREFIX}{day}": json.dumps([fill.venue_order_id]).encode(),
        f"{VENUE_ORDER_ID_KEY_PREFIX}{fill.venue_order_id}": fill.client_order_id.encode(),
    }


# -- the tape ------------------------------------------------------------------------------------


def _fixed(value: str) -> bytes:
    return int(Decimal(value) * 10**16).to_bytes(16, "little", signed=True)


def _stamp(ns: int) -> str:
    moment = dt.datetime.fromtimestamp(ns // NS, dt.UTC)
    return f"{moment:%Y-%m-%dT%H-%M-%S}-{ns % NS:09d}Z"


def write_tape(
    root: Path,
    instrument: str = INSTRUMENT,
    *,
    quotes: Sequence[tuple[int, str, str]] = (),
    depths: Sequence[tuple[int, Sequence[tuple[str, str]]]] = (),
) -> None:
    """Real recorder-catalog Parquet: ``quotes`` are ``(ts_event, bid, ask)``, ``depths`` are
    ``(ts_event, [(ask_price, ask_size), ...])`` (bids empty)."""
    base = root / "catalog" / "quote_tape" / VENUE / "data"
    meta = {
        b"instrument_id": instrument.encode(),
        b"price_precision": b"2",
        b"size_precision": b"2",
    }
    fixed = pa.binary(16)
    if quotes:
        stamps = [q[0] for q in quotes]
        table = pa.table(
            {
                "bid_price": pa.array([_fixed(q[1]) for q in quotes], fixed),
                "ask_price": pa.array([_fixed(q[2]) for q in quotes], fixed),
                "bid_size": pa.array([_fixed("1") for _ in quotes], fixed),
                "ask_size": pa.array([_fixed("1") for _ in quotes], fixed),
                "ts_event": pa.array(stamps, pa.uint64()),
                "ts_init": pa.array(stamps, pa.uint64()),
            }
        ).replace_schema_metadata(meta)
        _put(base / "quote_tick" / instrument, table, min(stamps), max(stamps))
    if depths:
        stamps = [d[0] for d in depths]
        columns: dict[str, Any] = {}
        zero = _fixed("0")
        for k in range(10):
            for side in ("bid", "ask"):
                prices, sizes = [], []
                for _ts, asks in depths:
                    level = asks[k] if side == "ask" and k < len(asks) else None
                    prices.append(_fixed(level[0]) if level else zero)
                    sizes.append(_fixed(level[1]) if level else zero)
                columns[f"{side}_price_{k}"] = pa.array(prices, fixed)
                columns[f"{side}_size_{k}"] = pa.array(sizes, fixed)
        columns["ts_event"] = pa.array(stamps, pa.uint64())
        columns["ts_init"] = pa.array(stamps, pa.uint64())
        table = pa.table(columns).replace_schema_metadata(meta)
        _put(base / "order_book_depths" / instrument, table, min(stamps), max(stamps))


def _put(directory: Path, table: pa.Table, first: int, last: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, directory / f"{_stamp(first)}_{_stamp(last)}.parquet")


# -- the bus snapshot ----------------------------------------------------------------------------


def audit_row(*, budget_s: int = 10) -> BwrapRow:
    reads = tuple(
        BusRead(name, (SYSTEMCTL, "--user", "show", *tail))
        for name, tail in zip(host.AUDIT_BUS_READ_NAMES, host.AUDIT_BUS_READS, strict=True)
    )
    return BwrapRow(
        name=host.AUDIT_ROW_NAME,
        owner_plan="AUT-1",
        units=frozenset({f"{host.AUDIT_ROW_NAME}.service"}),
        binds=(SNAP_BIND, "cache/capture_audit"),
        entry_modules=("breezy.analysis.capture_audit_cli",),
        resolves_dns=True,
        bus_reads=reads,
        bus_snapshot_bind=SNAP_BIND,
        bus_snapshot_budget_s=budget_s,
    )


RECORDER_ARMED: Final[str] = "Type=notify\nNotifyAccess=all\nWatchdogUSec=10min\n"
INGEST_EXIT: Final[str] = "ExecMainExitTimestamp=Sun 2026-10-04 09:07:22 UTC\n"


def plant_snapshot(
    root: Path,
    *,
    recorder: str = RECORDER_ARMED,
    ingest: str = INGEST_EXIT,
    ts_ns: int | None = None,
    rc: int = 0,
) -> Path:
    snap = root / SNAP_BIND / ".bus_snapshot"
    snap.mkdir(parents=True, exist_ok=True, mode=0o700)
    for private in (root / "cache", root / SNAP_BIND, snap):
        private.chmod(0o700)
    row = audit_row()
    doc = {
        "schema": "bus_snapshot/v1",
        "invocation_id": INVOCATION,
        "unit": f"{host.AUDIT_ROW_NAME}.service",
        "ts_ns": NOW_NS - 5 * NS if ts_ns is None else ts_ns,
        "budget_s": 10,
        "reads": [
            {
                "name": read.name,
                "argv": list(read.argv),
                "rc": rc,
                "timed_out": False,
                "skipped": False,
                "oversize": False,
                "stdout": stdout,
            }
            for read, stdout in zip(row.bus_reads, (recorder, ingest), strict=True)
        ],
    }
    path = snap / f"{INVOCATION}.json"
    path.write_text(json.dumps(doc))
    return path


# -- the W2 sinks and the process boundary --------------------------------------------------------


class FakeReplay:
    """Stands in for W2's ``BootReplay``: results are whatever the test plants."""

    planted: Mapping[tuple[str, dt.date], ReplayResult] = {}

    def __init__(self) -> None:
        self.fed = 0

    def feed(self, event: object) -> None:
        self.fed += 1

    def results(self) -> Mapping[tuple[str, dt.date], ReplayResult]:
        return dict(type(self).planted)


class FakeMarkers:
    planted: Mapping[tuple[str, dt.date], LogMarkers] = {}

    def __init__(self) -> None:
        self.fed = 0

    def feed(self, event: object) -> None:
        self.fed += 1

    def markers(self) -> Mapping[tuple[str, dt.date], LogMarkers]:
        return dict(type(self).planted)


class JournalFake:
    """The fake ``run_journal``: one text per template, or an ``AuditInputError`` to raise."""

    def __init__(
        self, *, supervisor: str = "", ingest: str = "ingest: ok", recorder: str = "{}"
    ) -> None:
        self.texts = {
            host.SUPERVISOR_JOURNAL_ARGV: supervisor,
            host.INGEST_JOURNAL_ARGV: ingest,
            host.RECORDER_JOURNAL_ARGV: recorder,
        }
        self.calls: list[tuple[tuple[str, ...], str, str]] = []

    def __call__(self, template: Sequence[str], since: str, until: str, **_: Any) -> str:
        key = tuple(template)
        self.calls.append((key, since, until))
        text = self.texts[key]
        if not text.strip():
            raise AuditInputError("journal_failed", host.EMPTY_OUTPUT_DETAIL)
        return text


def install(
    monkeypatch: Any,
    root: Path,
    *,
    journal: JournalFake | None = None,
    snapshot: bool = True,
    scans: list[Path] | None = None,
) -> JournalFake:
    """Patch the process boundary and the W2 sinks; plant a good bus snapshot unless told not to."""
    fake = journal or JournalFake(supervisor=supervisor_launched())
    monkeypatch.setattr(inputs, "run_journal", fake)
    FakeReplay.planted, FakeMarkers.planted = {}, {}
    monkeypatch.setattr(inputs, "BootReplay", FakeReplay)
    monkeypatch.setattr(inputs, "MarkerParser", FakeMarkers)
    monkeypatch.setattr(host, "_audit_row", audit_row)
    monkeypatch.setattr(host, "_environment", lambda: {"INVOCATION_ID": INVOCATION})
    host._BUS_OUTCOMES.clear()
    if scans is not None:
        real = scan_node_log

        def counting(path: Path, **kw: Any) -> Any:
            scans.append(path)
            return real(path, **kw)

        monkeypatch.setattr(inputs, "scan_node_log", counting)
    if snapshot:
        plant_snapshot(root)
    return fake


def full_world(tmp_path: Path, monkeypatch: Any, **kw: Any) -> Path:
    """A complete, consistent D=2026-10-03 world: one boot with log, stream, epoch, fill, tape."""
    root = make_root(tmp_path)
    install(monkeypatch, root, **kw)
    write_node_log(root, decisions=[day_take()])
    write_stream(root)
    write_epoch(root, epoch_ns=day_ns(DAY - dt.timedelta(days=1), 16, 50))
    write_exec_store(root, standard_exec_rows())
    write_tape(
        root,
        quotes=[(day_ns(DAY, 17, 0), "0.01", "0.15")],
        depths=[(day_ns(DAY, 17, 0), [("0.15", "10.00")])],
    )
    return root


def gather(root: Path, **kw: Any) -> Any:
    return inputs.gather_inputs(root, FAMILY, DAY, now_ns=kw.pop("now_ns", NOW_NS))


# -- the legs (W1 and W2 are separate worktrees: the orchestration tests stub them) ---------------

_DAY_LEG_FUNCTIONS: Final[Mapping[str, str]] = {
    "R1": "leg_r1",
    "R2": "leg_r2",
    "R3": "leg_r3",
    "R4": "leg_r4",
    "R5": "leg_r5",
    "R6": "leg_r6",
    "R7": "leg_r7",
    "O": "leg_o",
    "F": "leg_f",
    "T": "leg_t",
    "N": "leg_n",
    "PC": "positive_control",
}


def leg_result(leg: str, outcome: str = "PASS", cause: str = "", **metrics: Any) -> LegResult:
    findings = () if not cause else (Finding(Leg(leg), LegOutcome(outcome), cause, "subject"),)
    return LegResult(Leg(leg), LegOutcome(outcome), findings, metrics)


def stub_legs(
    monkeypatch: Any,
    *,
    fills: Sequence[Any] = (),
    gaps: Sequence[Any] = (),
    marks: Sequence[Any] = (),
    **overrides: Any,
) -> None:
    """Replace every leg in ``capture_audit`` with a PASS (or the result given by leg id)."""
    for leg, name in _DAY_LEG_FUNCTIONS.items():
        result = overrides.get(leg, leg_result(leg))
        monkeypatch.setattr(audit, name, lambda inp, _r=result: _r)
    watchdog = overrides.get("W", leg_result("W"))
    monkeypatch.setattr(audit, "leg_w", lambda inp: (watchdog, tuple(gaps)))
    monkeypatch.setattr(audit, "audit_fills", lambda inp: tuple(fills))
    monkeypatch.setattr(audit, "tape_marks", lambda inp: tuple(marks))


def recording(sink: list[Any], result: Any = 0) -> Callable[..., Any]:
    """A stand-in that appends its first argument (or ``1``) to ``sink`` and returns ``result``."""

    def call(*args: Any, **_: Any) -> Any:
        sink.append(args[0] if args else 1)
        return result

    return call


def wrapping(sink: list[Any], real: Callable[..., Any]) -> Callable[..., Any]:
    """``real``, noting each call in ``sink`` first."""

    def call(*args: Any, **kwargs: Any) -> Any:
        sink.append(1)
        return real(*args, **kwargs)

    return call


def real_client_round_trip(record: DurableFillRecord) -> bool:
    """The REAL client's own decoder reads back what its encoder wrote (L-42). Kept here, not in a
    test module: X1 pins which test modules import the exec package."""
    return exec_client.DurableFillRecord.from_bytes(record.to_bytes()) == record


def client_key_constants() -> set[str]:
    """Every exec-store key prefix the real client defines."""
    found = {
        getattr(exec_client, name)
        for name in dir(exec_client)
        if name.endswith("_KEY_PREFIX") and isinstance(getattr(exec_client, name), str)
    }
    return found | {exec_client.STARTUP_EVIDENCE_KEY}
