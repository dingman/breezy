"""MAKER-S2 WP6 shared fixture world: a fake capture, NBP store, census, truth and amendment.

Everything lives in a caller-supplied directory. No real catalog, NBP store, truth CSV, node log
or network is ever touched. The replayed station-day is SFO 2026-09-29: five rungs, one resting
NO bid that a YES-BUYER print consumes. A second station-day (SFO 2026-09-18) carries the WP0
direction sample (420 prints) and the first print, which fixes the first replayable day.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nautilus_trader.model.enums import AggressorSide

from breezy.adapters.polymarket_us.tape_records import DepthTruncation
from tests.fixtures.maker_stage0 import make_census_fixture as fx
from tests.unit import test_maker_stage0_pno as pno_fx
from tests.unit.test_maker_stage0_probe import (
    _depth,
    _gap,
    _instrument,
    _ns,
    _slug,
    _trade,
    _write_instance,
)

DAY = dt.date(2026, 9, 29)
DIRECTION_DAY = dt.date(2026, 9, 18)
FIRST_DAY = dt.date(2026, 9, 18)
LAST_DAY = dt.date(2026, 10, 13)
SEALED = dt.date(2026, 10, 1)
STATION = "SFO"
TRUTH_TMAX_F = 70
N_DIRECTION = 210
RUNGS = ("lt80f", "gte80lt81f", "gte82lt83f", "gte84lt85f", "gte86f")
FILL_RUNG = "gte86f"
GAP_RUNG = "gte84lt85f"


def rule_days() -> list[dt.date]:
    span = (LAST_DAY - FIRST_DAY).days + 1
    return [d for d in (FIRST_DAY + dt.timedelta(days=i) for i in range(span)) if d != SEALED]


def _t(iso: str) -> int:
    return _ns(iso)


def build_capture(
    root: Path,
    *,
    inverted: bool = False,
    big_offset_s: int | None = None,
    extra_offsets: tuple[tuple[str, float], ...] = (),
    listed_iso: str = "2026-09-28T08:00:00",
    second_instance: bool = False,
) -> Path:
    """One CLEAN recorder instance; ``inverted`` flips the direction sample (S-2).

    ``listed_iso`` is when the replayed ladder was listed (after 2026-09-28T12:00Z the ladder is a
    listing abstention); ``second_instance`` adds ``inst-b`` holding the same ladder (LRU tests).
    """
    capture = root / "capture"
    listed = _t(listed_iso)
    rungs = {r: _instrument(_slug("sfo", r, DAY.isoformat()), listed) for r in RUNGS}
    dir_rung = _instrument(
        _slug("sfo", "gte60lt61f", DIRECTION_DAY.isoformat()), _t("2026-09-16T08:00:00")
    )
    records: list[Any] = []
    for ts in ("2026-09-28T17:00:00", "2026-09-28T20:30:00", "2026-09-28T22:30:00"):
        for inst in rungs.values():
            records.append(_depth(inst, "0.150", "0.250", _t(ts)))
    records.append(
        _gap(
            rungs[GAP_RUNG],
            start=_t("2026-09-28T18:00:00"),
            end=_t("2026-09-28T18:10:00"),
            resolved=True,
        )
    )
    records.append(
        _trade(rungs[FILL_RUNG], "fill-1", "0.250", AggressorSide.BUYER, _t("2026-09-28T21:00:00"))
    )
    records.append(_depth(dir_rung, "0.390", "0.410", _t("2026-09-17T13:00:00")))
    buyer_px, seller_px = ("0.350", "0.450") if inverted else ("0.450", "0.350")
    start = _t("2026-09-17T13:05:00")
    for i in range(N_DIRECTION):
        step = i * 1_000_000_000
        records.append(_trade(dir_rung, f"b{i}", buyer_px, AggressorSide.BUYER, start + step))
        records.append(
            _trade(dir_rung, f"s{i}", seller_px, AggressorSide.SELLER, start + 400 * 10**9 + step)
        )
    extra, defined = _scope_probes(rungs, listed)
    records.extend(extra)
    offsets = [
        (_t("2026-09-18T01:00:00"), 1 * 10**9),
        (_t("2026-09-29T01:00:00"), -5 * 10**9),
        (_t("2026-09-29T02:00:00"), 2 * 10**9),
    ]
    if big_offset_s is not None:
        offsets.append((_t("2026-09-29T01:30:00"), big_offset_s * 10**9))
    offsets.extend((_t(iso), round(seconds * 10**9)) for iso, seconds in extra_offsets)
    _write_instance(
        capture,
        "inst-a",
        instruments=[*rungs.values(), dir_rung, *defined],
        records=records,
        offsets=offsets,
    )
    if second_instance:
        later = [
            _depth(inst, "0.150", "0.250", _t("2026-09-28T23:30:00")) for inst in rungs.values()
        ]
        _write_instance(
            capture, "inst-b", instruments=list(rungs.values()), records=later, offsets=[]
        )
    return capture


def _scope_probes(rungs: dict[str, Any], listed: int) -> tuple[list[Any], list[Any]]:
    """Extra ``inst-a`` records that exercise the reader's rung scoping (S-5 review fixes).

    * ``sib``: a defined SFO same-day rung (so a PLANNED third sibling: the writer drops records
      of an undefined instrument, and a same-day YES-leg definition is always planned) with depth,
      a 22:00Z BUYER print (after the licensed 21:00Z one, so the first print is unchanged), an
      unresolved gap and a DepthTruncation. Rungs genuinely outside the plan are the 09-18
      direction rung and the NO leg below.
    * the NO leg (``^no``) of FILL_RUNG: never a planned rung, prints at 19:00Z.
    * a licensed-rung DepthTruncation and unresolved gap on a second planned rung.
    * ``sub``: an id that CONTAINS FILL_RUNG's id as a substring. Native identifier filtering is a
      substring match on the feather subdirectory name, so it is converted too; that over-inclusion
      is harmless because every reader re-filters by the exact rung id.
    """
    fill = rungs[FILL_RUNG]
    no_leg = _instrument(
        _slug("sfo", FILL_RUNG, DAY.isoformat()) + "^no", _t("2026-09-28T08:00:00")
    )
    sub = _instrument(_slug("sfo", FILL_RUNG, DAY.isoformat()) + "x", _t("2026-09-28T08:00:00"))
    mid = rungs["gte82lt83f"]
    sib = _instrument(_slug("sfo", "gte61lt62f", DAY.isoformat()), listed)
    records: list[Any] = [
        _depth(sib, "0.150", "0.250", _t("2026-09-28T20:00:00")),
        _trade(sib, "sib-1", "0.250", AggressorSide.BUYER, _t("2026-09-28T22:00:00")),
        _gap(sib, start=_t("2026-09-28T20:10:00"), end=_t("2026-09-28T20:20:00"), resolved=False),
        DepthTruncation(sib.id, 12, 14, 6, _t("2026-09-28T20:00:00"), _t("2026-09-28T20:00:00")),
        _depth(no_leg, "0.150", "0.250", _t("2026-09-28T20:00:00")),
        _trade(no_leg, "no-1", "0.250", AggressorSide.BUYER, _t("2026-09-28T19:00:00")),
        _depth(sub, "0.150", "0.250", _t("2026-09-28T20:00:00")),
        _trade(sub, "sub-1", "0.250", AggressorSide.BUYER, _t("2026-09-28T18:30:00")),
        _gap(sub, start=_t("2026-09-28T19:00:00"), end=_t("2026-09-28T19:05:00"), resolved=False),
        DepthTruncation(sub.id, 12, 14, 6, _t("2026-09-28T20:00:00"), _t("2026-09-28T20:00:00")),
        DepthTruncation(mid.id, 12, 14, 6, _t("2026-09-28T20:30:00"), _t("2026-09-28T20:30:00")),
        _gap(mid, start=_t("2026-09-28T21:30:00"), end=_t("2026-09-28T21:40:00"), resolved=False),
        _depth(fill, "0.150", "0.250", _t("2026-09-28T23:00:00")),
    ]
    return records, [no_leg, sub, sib]


def build_nbp(root: Path) -> Path:
    nbp = pno_fx._build_root(root)
    (nbp / "_manifest.json").write_text(json.dumps({"fixture": True}) + "\n")
    return nbp


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_truth(root: Path) -> tuple[Path, Path, str]:
    """(csv, cross-check parquet, csv sha) for SFO on every rule day."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    head = "station,climate_day,tmax_f,tmax_flag,correction_flag,product_sha256\n"
    body = "".join(f"{STATION},{d.isoformat()},{TRUTH_TMAX_F},,False,aa\n" for d in rule_days())
    csv_path = root / "truth.csv"
    csv_path.write_text(head + body)
    schema = pa.schema(
        [
            ("station", pa.string()),
            ("climate_day", pa.date32()),
            ("status", pa.string()),
            ("tmax_f", pa.int64()),
        ]
    )
    rows = [
        {"station": STATION, "climate_day": d, "status": "FINAL", "tmax_f": TRUTH_TMAX_F}
        for d in [*rule_days()[:3], DAY]
    ]
    cross = root / "cross.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), cross)
    return csv_path, cross, _sha(csv_path)


def amendment_text(
    truth_sha: str, *, status: str = "FINAL", dates: list[dt.date] | None = None
) -> str:
    chosen = dates if dates is not None else rule_days()
    lines = [
        "```FROZEN_DATE_SET",
        "stations: LAX MDW MIA SFO",
        f"first_replayable_day: {FIRST_DAY.isoformat()}",
        "truth_csv_path: /x/truth_cli_finals.csv",
        f"truth_csv_sha256: {truth_sha}",
        f"last_final_day: {LAST_DAY.isoformat()}",
        "dates:",
        *(d.isoformat() for d in chosen),
        "```",
    ]
    return f"# ruling\nStatus: **{status}**\n\n" + "\n".join(lines) + "\n\ntrailer\n"


@dataclass(frozen=True)
class World:
    capture: Path
    nbp_root: Path
    census: Path
    unit: Path
    truth: Path
    cross_check: Path
    truth_sha: str
    amendment: Path
    amendment_sha: str
    node_log_dir: Path


OTHER_STATIONS = ("LAX", "MDW", "MIA")


def census_rows(**changes: Any) -> list[Any]:
    """SFO rows (the replayed station) plus never-listed rows for the other frozen stations."""
    days = [FIRST_DAY + dt.timedelta(days=i) for i in range((LAST_DAY - FIRST_DAY).days + 1)]
    rows = [fx.census_row(STATION, d, **changes) for d in days]
    rows += [
        fx.census_row(s, d, reason="NEVER_LISTED", covered_bidlive=False)
        for s in OTHER_STATIONS
        for d in days
    ]
    return rows


def build_world(
    root: Path,
    *,
    capture: Path | None = None,
    unit: str = "CONTRACTS",
    status: str = "FINAL",
    census_changes: dict[str, Any] | None = None,
) -> World:
    root.mkdir(parents=True, exist_ok=True)
    cap = capture if capture is not None else build_capture(root)
    csv_path, cross, truth_sha = write_truth(root)
    amendment = root / "amendment.md"
    amendment.write_text(amendment_text(truth_sha, status=status))
    census = fx.write_census_fixture(
        root / "censused_days.jsonl", census_rows(**(census_changes or {}))
    )
    unit_path = fx.write_unit_fixture(root / "unit.json", unit)
    logs = root / "node_logs"
    logs.mkdir(exist_ok=True)
    return World(
        capture=cap,
        nbp_root=build_nbp(root),
        census=census,
        unit=unit_path,
        truth=csv_path,
        cross_check=cross,
        truth_sha=truth_sha,
        amendment=amendment,
        amendment_sha=_sha(amendment),
        node_log_dir=logs,
    )
