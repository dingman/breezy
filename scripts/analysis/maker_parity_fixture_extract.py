"""ARM C3: extract the compact parity fixture for the unwired `no_ladder_maker` package.

For each requested station-day this reads the recorded quote tape, the pinned NBP rows and the
census listing instant (read-only; no network), replays the design driver's ``sharp`` arm over the
FULL tape at recorder offsets 0 and +-600 s, and writes ``<out>`` (gzip JSON) holding:

* the simulator's input events REDUCED to the rungs the rule can price (a rung whose p_NO never
  comes within ``ELIGIBILITY_MARGIN`` of P_MIN, and that the driver never attempted, cannot change
  any decision: ``decide_bid`` stops at the P_MIN test before it reads that rung's book);
* the pinned NBP rows of the station-day and the driver's episodes (the expected side).

Nothing is trusted: the reduced events are decoded back, replayed through the driver's own
``_replay_arm`` / ``replay_station_day`` and must reproduce the full-tape episodes exactly, at all
three offsets, or the extractor refuses to write. No settlement or truth value is read or stored.

Evidence fence (refused BEFORE any input path is opened): maker stations only, climate days on or
before ``LAST_ALLOWED_DAY``, never ``SEALED_DAY``. The second-look block is unreachable.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import shutil
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Final, cast

from breezy.persistence.nbp_derived_store import DerivedNbpRow, partition_path, write_partition
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    LiveCalibration,
    load_live_calibration,
)
from scripts.analysis import maker_design_nobid as driver
from scripts.analysis.maker_design_config import ARMS, Arm, DesignConfig, read_plan_cache
from scripts.analysis.maker_stage0_adapter import WantTracker
from scripts.analysis.maker_stage0_catalog_read import CatalogSession, StationDayPlan
from scripts.analysis.maker_stage0_events_build import DataEvents, clock_events, replay_station_day
from scripts.analysis.maker_stage0_fill_events import (
    DepthFrame,
    Episode,
    Event,
    GapMark,
    Kind,
    Print,
)
from scripts.analysis.maker_stage0_frozen import LAST_ALLOWED_DAY, SEALED_DAY
from scripts.analysis.maker_stage0_inputs import MAKER_STATIONS, load_trade_unit
from scripts.analysis.maker_stage0_pno_store import PNoStore, read_pinned, site
from scripts.analysis.maker_stage0_runio import theta_for_day
from scripts.analysis.maker_stage0_schedule import primary_schedule
from scripts.analysis.maker_stage0_station_loop import (
    LoopContext,
    LoopOutput,
    _cut_specs,
    _data,
    _ladder,
    _prepare,
    _Prepared,
    _selector_for,
    _vectors,
)

__all__ = [
    "DELTAS_NS",
    "MAX_FIXTURE_BYTES",
    "FenceRefused",
    "check_cases",
    "check_fence",
    "load_fixture",
    "main",
    "parse_case",
]

SCHEMA: Final[int] = 1
MAX_FIXTURE_BYTES: Final[int] = 200_000
NS: Final[int] = 10**9
DELTAS_NS: Final[tuple[int, ...]] = (0, 600 * NS, -600 * NS)
#: a rung is kept if 1 - p_yes comes within this of the arm's P_MIN at any release in force
ELIGIBILITY_MARGIN: Final[float] = 0.02
ROLES: Final[frozenset[str]] = frozenset({"fill_day", "late_listed", "spans_hard_cancel"})
DEFAULT_SHA: Final[str] = "9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e"
_KIND_GAP_START: Final[int] = int(Kind.GAP_START)
_KIND_GAP_END: Final[int] = int(Kind.GAP_END)


class FenceRefused(ValueError):
    """A request outside the evidence fence (or malformed); nothing was read."""


@dataclass(frozen=True)
class CaseRequest:
    station: str
    day: dt.date
    roles: tuple[str, ...]


# --- the fence ---------------------------------------------------------------------------


def check_fence(station: str, day: dt.date) -> None:
    if station not in MAKER_STATIONS:
        raise FenceRefused(f"station {station!r} is not one of {MAKER_STATIONS}")
    if day > LAST_ALLOWED_DAY:
        raise FenceRefused(f"{day.isoformat()} is after {LAST_ALLOWED_DAY} (second-look block)")
    if day == SEALED_DAY:
        raise FenceRefused(f"{day.isoformat()} is the sealed holdout day")


def parse_case(text: str) -> CaseRequest:
    """``STATION:YYYY-MM-DD[:role,role]``."""
    parts = text.split(":")
    if len(parts) not in (2, 3) or not parts[0]:
        raise FenceRefused(f"case {text!r} is not STATION:YYYY-MM-DD[:roles]")
    try:
        day = dt.date.fromisoformat(parts[1])
    except ValueError as exc:
        raise FenceRefused(f"case {text!r} has no ISO date") from exc
    roles = tuple(r for r in (parts[2].split(",") if len(parts) == 3 else []) if r)
    if not set(roles) <= ROLES:
        raise FenceRefused(f"case {text!r} names roles outside {sorted(ROLES)}")
    return CaseRequest(parts[0], day, roles)


def check_cases(cases: Iterable[CaseRequest]) -> None:
    for case in cases:
        check_fence(case.station, case.day)


# --- encode / decode (shared with the parity test) ---------------------------------------


def _level_list(levels: Sequence[tuple[int, int]]) -> list[list[int]]:
    return [[price, size] for price, size in levels]


def _encode_events(events: Sequence[Event], instruments: Sequence[str]) -> dict[str, Any]:
    rung_index = {r: i for i, r in enumerate(instruments)}
    instances: dict[str, int] = {}
    states: dict[str, int] = {}
    state_rows: list[Any] = []
    cols: dict[str, list[int]] = {k: [] for k in ("ts", "seq", "rung", "state", "inst")}
    prints: list[list[Any]] = []
    gaps: list[list[int]] = []
    prev_ts = prev_seq = 0
    for ev in events:
        pl = ev.payload
        if isinstance(pl, DepthFrame):
            inst = instances.setdefault(pl.instance_id, len(instances))
            body = [_level_list(pl.yes_bids), _level_list(pl.yes_asks), pl.asks_truncated,
                    pl.bids_truncated]  # fmt: skip
            key = json.dumps(body, separators=(",", ":"))
            if key not in states:
                states[key] = len(state_rows)
                state_rows.append(body)
            cols["ts"].append(ev.ts_ns - prev_ts)
            cols["seq"].append(ev.seq - prev_seq)
            prev_ts, prev_seq = ev.ts_ns, ev.seq
            cols["rung"].append(rung_index[pl.rung_id])
            cols["state"].append(states[key])
            cols["inst"].append(inst)
        elif isinstance(pl, Print):
            inst = instances.setdefault(pl.instance_id, len(instances))
            prints.append([ev.ts_ns, ev.seq, rung_index[pl.rung_id], pl.yes_price_cents, pl.size,
                           pl.aggressor, inst])  # fmt: skip
        elif isinstance(pl, GapMark):
            rung = -1 if pl.rung_id is None else rung_index[pl.rung_id]
            gaps.append([ev.ts_ns, ev.seq, int(ev.kind), rung])
        else:
            raise TypeError(f"unexpected data event payload {type(pl).__name__}")
    return {
        "frames": cols, "states": state_rows, "prints": prints, "gaps": gaps,
        "instances": sorted(instances, key=lambda k: instances[k]),
    }  # fmt: skip


def case_events(case: Mapping[str, Any]) -> tuple[Event, ...]:
    """Decode a fixture case's data events back into the simulator's ordered stream."""
    names: list[str] = case["instruments"]
    instances: list[str] = case["events"]["instances"]
    states = [
        (
            tuple((int(p), int(s)) for p, s in bids),
            tuple((int(p), int(s)) for p, s in asks),
            bool(at),
            bool(bt),
        )
        for bids, asks, at, bt in case["events"]["states"]
    ]
    out: list[Event] = []
    cols = case["events"]["frames"]
    ts = seq = 0
    for d_ts, d_seq, rung, state, inst in zip(
        cols["ts"], cols["seq"], cols["rung"], cols["state"], cols["inst"], strict=True
    ):
        ts, seq = ts + d_ts, seq + d_seq
        bids, asks, at, bt = states[state]
        frame = DepthFrame(
            rung_id=names[rung], ts_ns=ts, yes_bids=bids, yes_asks=asks,
            asks_truncated=at, bids_truncated=bt, instance_id=instances[inst],
        )  # fmt: skip
        out.append(Event(ts, Kind.DEPTH, seq, frame))
    for ts, seq, rung, cents, size, aggressor, inst in case["events"]["prints"]:
        pr = Print(names[rung], cents, size, aggressor, instances[inst])
        out.append(Event(ts, Kind.PRINT, seq, pr))
    for ts, seq, kind, rung in case["events"]["gaps"]:
        mark = GapMark(None if rung < 0 else names[rung])
        out.append(Event(ts, Kind(kind), seq, mark))
    return tuple(sorted(out))


_ROW_FIELDS: Final[tuple[str, ...]] = tuple(f.name for f in fields(DerivedNbpRow))


def case_rows(case: Mapping[str, Any]) -> tuple[DerivedNbpRow, ...]:
    return tuple(
        DerivedNbpRow(**dict(zip(_ROW_FIELDS, r, strict=True))) for r in case["nbp"]["rows"]
    )


def load_fixture(path: Path) -> dict[str, Any]:
    doc = json.loads(gzip.decompress(path.read_bytes()))
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ValueError(f"{path} is not a schema-{SCHEMA} parity fixture")
    return doc


def _write_doc(path: Path, doc: Mapping[str, Any]) -> bytes:
    body = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    blob = gzip.compress(body, compresslevel=9, mtime=0)
    if len(blob) >= MAX_FIXTURE_BYTES:
        raise ValueError(f"fixture is {len(blob)} bytes, the limit is {MAX_FIXTURE_BYTES}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    return blob


# --- inputs (read-only) ------------------------------------------------------------------


def read_census_row(path: Path, station: str, day: dt.date) -> Mapping[str, Any]:
    """The one census row of ``station``/``day``; every other line is only substring-tested."""
    want_day, want_station = f'"climate_day":"{day.isoformat()}"', f'"station":"{station}"'
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if want_day in line and want_station in line:
                row = json.loads(line)
                if isinstance(row, dict):
                    return row
    raise FenceRefused(f"no census row for {station} {day.isoformat()}")


@dataclass(frozen=True)
class Inputs:
    catalog_root: Path
    nbp_root: Path
    plan_cache: Path
    census_days: Path
    trade_unit: Path
    calibration: Path
    calibration_sha256: str
    work_root: Path


def _arm_episodes(
    prep: _Prepared, data: DataEvents, key: tuple[str, dt.date], unit: str, live_from: int,
    delta_ns: int, arm: Arm,
) -> tuple[Episode, ...]:  # fmt: skip
    """The driver's ``_replay_arm`` at delta 0; the same wiring with the offset otherwise."""
    if delta_ns == 0:
        job = driver.DayJob(cast(DesignConfig, None), key, StationDayPlan((), (), 0), False)
        return driver._replay_arm(arm, prep, data, unit, job, live_from).episodes
    station, day = key
    tracker = WantTracker()
    clock = clock_events(_cut_specs(primary_schedule(day), station, day), prep.vectors["none"])
    with driver.rule_override(
        arm.b_cap, arm.max_rungs, p_min=arm.p_min, e_min=arm.e_min, b_floor=arm.b_floor
    ):
        replay = replay_station_day(
            data, clock, selector=_selector_for(prep, key, "none", delta_ns, tracker),
            tracker=tracker, station=station, day=day, unit_hypothesis=unit,
            live_from_ns=live_from, delta_ns=delta_ns,
        )  # fmt: skip
    return replay.result.episodes


def _episode_row(ep: Episode, index: Mapping[str, int]) -> list[Any]:
    return [ep.t0_ns, index[ep.rung_id], ep.bid_cents, ep.end_ns, ep.end_reason,
            ep.refused_reason, ep.filled_ns_base, ep.filled_ns_stress]  # fmt: skip


def _eligible(prep: _Prepared, episodes: Iterable[Episode], arm: Arm) -> set[str]:
    p_min = 0.0 if arm.p_min is None else arm.p_min
    keep = {e.rung_id for e in episodes}
    for vector in prep.vectors["none"]:
        keep |= {r for r, p in vector.p_yes_point.items() if 1.0 - p >= p_min - ELIGIBILITY_MARGIN}
    return keep


def _reduce(data: DataEvents, keep: set[str]) -> tuple[Event, ...]:
    def wanted(ev: Event) -> bool:
        pl = ev.payload
        if isinstance(pl, DepthFrame | Print):
            return pl.rung_id in keep
        return isinstance(pl, GapMark) and (pl.rung_id is None or pl.rung_id in keep)

    return tuple(ev for ev in data.events if wanted(ev))


def _nbp_block(nbp_root: Path, station: str, day: dt.date) -> dict[str, Any]:
    read = read_pinned(nbp_root, site(station).icao, day)
    pinned = {(day - dt.timedelta(days=1), 13), (day - dt.timedelta(days=1), 19), (day, 1)}
    present = sorted(pinned - set(read.missing))
    return {
        "partitions": [[d.isoformat(), h] for d, h in present],
        "rows": [[getattr(r, name) for name in _ROW_FIELDS] for r in read.rows],
    }


def _materialise(case: Mapping[str, Any], root: Path) -> None:
    by_cycle: dict[tuple[dt.date, int], list[DerivedNbpRow]] = {
        (dt.date.fromisoformat(d), int(h)): [] for d, h in case["nbp"]["partitions"]
    }
    for row in case_rows(case):
        stamp = dt.datetime.fromtimestamp(row.cycle_runtime_ns // NS, tz=dt.UTC)
        by_cycle[(stamp.date(), stamp.hour)].append(row)
    for (date, hour), rows in by_cycle.items():
        write_partition(rows, partition_path(root, date, hour))


def _prepared_from_fixture(
    case: Mapping[str, Any], root: Path, calibration: LiveCalibration
) -> tuple[_Prepared, DataEvents]:
    station, day = str(case["station"]), dt.date.fromisoformat(case["day"])
    _materialise(case, root)
    rungs, edges = _ladder(case["instruments"])
    store = PNoStore.from_root(
        root, stations=[station], days=[day], calibration=calibration,
        ladders={(station, day): rungs},
    )  # fmt: skip
    prep = _Prepared([], store, edges, {"none": _vectors(store, station, day, "none")})
    events = case_events(case)
    books = frozenset(e.payload.rung_id for e in events if isinstance(e.payload, DepthFrame))
    return prep, DataEvents(events, 0, books)


# --- one case ----------------------------------------------------------------------------


def extract_case(
    req: CaseRequest, inputs: Inputs, calibration: LiveCalibration, driver_episodes: Path | None
) -> dict[str, Any]:
    key = (req.station, req.day)
    arm = ARMS["sharp"]
    census = read_census_row(inputs.census_days, req.station, req.day)
    plans, _ = read_plan_cache(inputs.plan_cache)
    plan = plans[key]
    unit = load_trade_unit(inputs.trade_unit).hypotheses()[0]
    sched = primary_schedule(req.day)
    work = inputs.work_root / f"c3_{req.station}_{req.day.isoformat()}"
    session = CatalogSession(inputs.catalog_root, work)
    ctx = LoopContext(
        units=[unit], primary={req.day: sched}, overlay={}, statuses={}, census={}, deltas={},
        plans={key: plan}, session=session, nbp_root=inputs.nbp_root, calibration=calibration,
        sink=None, variants=("primary",),
    )  # fmt: skip
    try:
        prep = _prepare(ctx, key, LoopOutput())
        data = _data(prep, unit, key)
    finally:
        session.close()
        shutil.rmtree(work, ignore_errors=True)
    full = {
        d: _arm_episodes(prep, data, key, unit.name, sched.window_start_ns, d, arm)
        for d in DELTAS_NS
    }
    if driver_episodes is not None:
        _check_against_driver(driver_episodes, key, full[0])
    keep = _eligible(prep, (e for eps in full.values() for e in eps), arm)
    instruments = list(plan.instruments)
    index = {r: i for i, r in enumerate(instruments)}
    case: dict[str, Any] = {
        "id": f"{req.station}-{req.day.isoformat()}",
        "station": req.station, "day": req.day.isoformat(), "unit": unit.name,
        "theta": theta_for_day(req.day), "instruments": instruments,
        "live_from_ns": sched.window_start_ns, "permit_end_ns": sched.window_end_ns,
        "first_seen_ns": census.get("first_seen_ns"),
        "cuts": [[c.ts_ns, c.reason, c.resume] for c in _cut_specs(sched, *key)],
        "kept_rungs": sorted(keep), "n_events_full": data.n_events,
        "events": _encode_events(_reduce(data, keep), instruments),
        "nbp": _nbp_block(inputs.nbp_root, req.station, req.day),
        "expected": {str(d): [_episode_row(e, index) for e in eps] for d, eps in full.items()},
    }  # fmt: skip
    case["roles"] = _verified_roles(req, case, full[0])
    _verify_reduction(case, full, calibration, arm)
    return case


def _check_against_driver(
    path: Path, key: tuple[str, dt.date], episodes: Sequence[Episode]
) -> None:
    want_day, want_station = f'"climate_day": "{key[1].isoformat()}"', f'"station": "{key[0]}"'
    stored: list[tuple[Any, ...]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if want_day in line and want_station in line:
                row = json.loads(line)
                stored.append((row["t0_ns"], row["rung_id"], row["bid_cents"], row["end_ns"],
                               row["end_reason"]))  # fmt: skip
    mine = [(e.t0_ns, e.rung_id, e.bid_cents, e.end_ns, e.end_reason) for e in episodes]
    if sorted(stored) != sorted(mine):
        raise ValueError(f"{key}: the replay differs from the stored driver episodes {path}")


def _verified_roles(
    req: CaseRequest, case: Mapping[str, Any], base: Sequence[Episode]
) -> list[str]:
    """A claimed role must be mechanically true of the case; nothing else is recorded."""
    window_end = case["permit_end_ns"]
    facts = {
        "fill_day": any(e.refused_reason is None and e.filled_ns_base is not None for e in base),
        "late_listed": case["first_seen_ns"] is None
        or not _listed_in_time(case["first_seen_ns"], req.day),
        "spans_hard_cancel": any(c[1] == "CANCEL_HARD" and c[0] > 0 for c in case["cuts"])
        and window_end > case["live_from_ns"],
    }
    wrong = [r for r in req.roles if not facts[r]]
    if wrong:
        raise FenceRefused(f"{req.station} {req.day.isoformat()} is not {wrong}")
    return sorted(req.roles)


def _listed_in_time(first_seen_ns: int, day: dt.date) -> bool:
    deadline = dt.datetime.combine(day - dt.timedelta(days=1), dt.time(12), tzinfo=dt.UTC)
    return first_seen_ns <= int(deadline.timestamp()) * NS


def _verify_reduction(
    case: Mapping[str, Any], full: Mapping[int, Sequence[Episode]], cal: LiveCalibration, arm: Arm
) -> None:
    """The decoded fixture must give back the full-tape episodes at every offset."""
    key = (str(case["station"]), dt.date.fromisoformat(case["day"]))
    with tempfile.TemporaryDirectory(prefix="c3_verify_") as tmp:
        prep, data = _prepared_from_fixture(case, Path(tmp) / "nbp", cal)
        for delta, want in full.items():
            got = _arm_episodes(prep, data, key, case["unit"], case["live_from_ns"], delta, arm)
            if tuple(got) != tuple(want):
                raise ValueError(f"{key} delta {delta}: the reduced events change the episodes")


# --- CLI ---------------------------------------------------------------------------------


_HOME_DEFAULTS: Final[tuple[tuple[str, str], ...]] = (
    ("--catalog-root", ".local/share/breezy/catalog/quote_tape/polymarket_us"),
    ("--nbp-root", ".local/share/breezy/derived/nbp"),
    ("--plan-cache", ".cache/breezy/maker_design_work/plans/full_plan.json"),
    ("--census-days", ".local/share/breezy/derived/maker/s1/censused_days.jsonl"),
    ("--trade-unit", ".local/share/breezy/derived/maker/s1/trade_quantity_unit.json"),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ARM C3 parity fixture extractor (read-only)")
    parser.add_argument("--case", action="append", required=True, help="STATION:YYYY-MM-DD[:roles]")
    parser.add_argument("--out", type=Path, required=True)
    for flag, rel in _HOME_DEFAULTS:
        parser.add_argument(flag, type=Path, default=Path.home() / rel)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--calibration-sha256", default=DEFAULT_SHA)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument(
        "--driver-episodes",
        type=Path,
        help="the sharp arm's episodes.jsonl: Delta = 0 is cross-checked against it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        requests = [parse_case(text) for text in args.case]
        check_cases(requests)  # the fence runs before any input path is opened
    except FenceRefused as exc:
        sys.stderr.write(f"refused: {exc}\n")
        return 2
    inputs = Inputs(
        args.catalog_root, args.nbp_root, args.plan_cache, args.census_days, args.trade_unit,
        args.calibration, args.calibration_sha256, args.work_root,
    )  # fmt: skip
    calibration = load_live_calibration(
        str(args.calibration), expected_sha256=args.calibration_sha256
    )
    cases = [extract_case(r, inputs, calibration, args.driver_episodes) for r in requests]
    fence = {"last_allowed_day": LAST_ALLOWED_DAY.isoformat(), "sealed_day": SEALED_DAY.isoformat()}
    doc = {
        "schema": SCHEMA,
        "arm": "sharp",
        "fence": fence,
        "calibration_sha256": args.calibration_sha256,
        "cases": cases,
    }
    blob = _write_doc(args.out, doc)
    sys.stdout.write(f"{args.out} bytes={len(blob)} sha256={hashlib.sha256(blob).hexdigest()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
