"""Binding-run inputs for the maker S3 floor: S2 artifact, S1 census, S5 cap pin.

The plan fixes the S2 fields (r3 §2 item 1) but not a file format, so this module
defines a minimal JSON schema; WP4 step 3a checks it against the real artifacts.

S2 artifact (JSON object)::

    {"verdict": "NOT-KILLED" | "NOT-KILLED-UNSCREENED" | "NO-GO",
     "fill_rate_2x": {"point": f_kill, "lower95": f_pass},          # any-rung station-day rate
     "fill_rate_2x_lowest_rung": {"point": ..., "lower95": ...},    # MAX_RUNGS = 1 rate (k = 1)
     "fill_rate_base": {"point": ...},                              # context only
     "two_fill_share": p2, "bid_bearing_share": beta, "fill_icc": icc, "n0": int,
     "realised_bid_iqr": [lo, hi] | null, "realised_bid_median": b}

S1 census: ``censused_days.jsonl``, one ``CensusedDay.to_dict()`` per line (uses ``station``,
``climate_day``, ``reason``, ``first_seen_ns``).
S5 cap pin (JSON object): ``{"holdout_start_date": "YYYY-MM-DD",
"calendar_cap_date": "YYYY-MM-DD"}``.

Every reader refuses with ``MakerRefusal`` (``main`` prints ``REFUSED: ...``, exit 2) on a malformed
file; S1 rows are schema-checked per line, the IQR must be numeric, in [0, 1] and contain the
median, and ``f_pass <= f_kill`` for both rung classes.

Deviation from plan r4 delta (g): ``unknown_share`` is UNKNOWN / (four-station non-PRE_TRADE
rows), not UNKNOWN / (all non-PRE_TRADE rows). The listing rate it guards is the four-station
rate, so numerator and denominator are the same population. The all-rows figure is computed as
``unknown_share_all_rows`` and recorded in the artifact, with ``unknown_share_basis``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from breezy.analysis.maker_tape_census import REASONS
from scripts.analysis.fq_loss_floor_mc_gate import inclusive_days
from scripts.analysis.fq_loss_floor_mc_maker_templates import (
    B_CAP,
    B_FLOOR,
    FILL_ICC,
    GRID_BIDS,
    LISTING,
    STATIONS,
    MakerMix,
    MakerRefusal,
)

__all__ = [
    "UNKNOWN_SHARE_BASIS",
    "UNKNOWN_SHARE_MAX",
    "BindingCell",
    "CapPin",
    "ListingRate",
    "S2Inputs",
    "binding_cells",
    "check_bid_range",
    "listing_rate_4stn",
    "load_s1",
    "load_s2",
    "load_s5_cap_pin",
    "mix_for",
]

UNKNOWN_SHARE_BASIS: Final = (
    "four_station_non_pre_trade_rows (plan r4 (g) says all non-PRE_TRADE rows; see "
    "unknown_share_all_rows)"
)
UNKNOWN_SHARE_MAX: Final = 0.20
_VERDICTS: Final = ("NOT-KILLED", "NOT-KILLED-UNSCREENED")
_TOL: Final = 1e-9


@dataclass(frozen=True, slots=True)
class S2Inputs:
    verdict: str
    f_kill: float
    f_pass: float
    f_kill_k1: float
    f_pass_k1: float
    f_base: float
    two_fill_share: float
    bid_bearing: float
    fill_icc: float
    fill_icc_raw: float
    n0: int
    bid_iqr: tuple[float, float] | None
    b_median: float
    sha256: str
    lines: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class BindingCell:
    k: int
    b: float
    f_kill: float
    f_pass: float


@dataclass(frozen=True, slots=True)
class CapPin:
    holdout_start: date
    cap_date: date
    l_cap: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ListingRate:
    listing_rate: float
    unknown_share: float
    listed: int
    unlisted: int
    unknown: int
    rows: int = 0
    unknown_share_all_rows: float = 0.0


def _read(path: Path) -> tuple[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MakerRefusal(f"cannot read {path}: {exc}") from exc
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(path: Path) -> tuple[Mapping[str, Any], str, str]:
    text, sha = _read(path)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MakerRefusal(f"{path} is not JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise MakerRefusal(f"{path} must hold a JSON object")
    return doc, text, sha


def _get(doc: Mapping[str, Any], dotted: str) -> Any:
    node: Any = doc
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node or node[part] is None:
            raise MakerRefusal(f"S2 artifact is missing field {dotted}")
        node = node[part]
    return node


def _number(doc: Mapping[str, Any], dotted: str, *, low: float = 0.0, high: float = 1.0) -> float:
    value = _get(doc, dotted)
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
        raise MakerRefusal(f"S2 field {dotted} must be a number in [{low}, {high}], got {value!r}")
    return float(value)


def _line(text: str, dotted: str) -> int:
    """1-based line of the dotted key path: each part is searched after the previous one."""
    pos = 0
    for part in dotted.split("."):
        match = re.compile(rf'"{re.escape(part)}"\s*:').search(text, pos)
        if match is None:
            return 0
        pos = match.end()
        start = match.start()
    return text.count("\n", 0, start) + 1


def check_bid_range(b: float) -> None:
    """Refuse a bid outside ``[B_FLOOR, B_CAP]``."""
    if not B_FLOOR - _TOL <= b <= B_CAP + _TOL:
        raise MakerRefusal(
            f"realised bid {b!r} is outside [B_FLOOR {B_FLOOR}, B_CAP {B_CAP}]: refused"
        )


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _iqr(raw: Any, median: float) -> tuple[float, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) != 2 or not all(_is_number(v) for v in raw):
        raise MakerRefusal("S2 realised_bid_iqr must be [lo, hi] (two numbers) or null")
    low, high = float(raw[0]), float(raw[1])
    if not 0.0 <= low <= high <= 1.0:
        raise MakerRefusal(f"S2 realised_bid_iqr {raw!r} must satisfy 0 <= lo <= hi <= 1")
    if not low - _TOL <= median <= high + _TOL:
        raise MakerRefusal(f"S2 realised_bid_iqr {raw!r} does not contain the median {median}")
    return (low, high)


def load_s2(path: Path) -> S2Inputs:
    doc, text, sha = _json(path)
    verdict = _get(doc, "verdict")
    if verdict == "NO-GO":
        raise MakerRefusal("S2 verdict is NO-GO: the binding run is not run (STOP 1)")
    if verdict not in _VERDICTS:
        raise MakerRefusal(f"S2 verdict {verdict!r} is not one of {_VERDICTS}")
    fields = {
        name: _number(doc, name)
        for name in (
            "fill_rate_2x.point",
            "fill_rate_2x.lower95",
            "fill_rate_2x_lowest_rung.point",
            "fill_rate_2x_lowest_rung.lower95",
            "fill_rate_base.point",
            "two_fill_share",
            "bid_bearing_share",
            "fill_icc",
            "realised_bid_median",
        )
    }
    n0 = _number(doc, "n0", high=1e9)
    median = fields["realised_bid_median"]
    check_bid_range(median)
    iqr = _iqr(doc.get("realised_bid_iqr"), median)
    for point, lower in (
        ("fill_rate_2x.point", "fill_rate_2x.lower95"),
        ("fill_rate_2x_lowest_rung.point", "fill_rate_2x_lowest_rung.lower95"),
    ):
        if fields[lower] > fields[point] + _TOL:
            raise MakerRefusal(
                f"S2 {lower} (f_pass {fields[lower]}) exceeds {point} (f_kill {fields[point]}): "
                "the KILL and PASS roles are swapped"
            )
    lines = {name: _line(text, name) for name in (*fields, "n0", "verdict")}
    return S2Inputs(
        verdict=verdict,
        f_kill=fields["fill_rate_2x.point"],
        f_pass=fields["fill_rate_2x.lower95"],
        f_kill_k1=fields["fill_rate_2x_lowest_rung.point"],
        f_pass_k1=fields["fill_rate_2x_lowest_rung.lower95"],
        f_base=fields["fill_rate_base.point"],
        two_fill_share=fields["two_fill_share"],
        bid_bearing=fields["bid_bearing_share"],
        fill_icc=max(fields["fill_icc"], FILL_ICC),
        fill_icc_raw=fields["fill_icc"],
        n0=int(n0),
        bid_iqr=iqr,
        b_median=median,
        sha256=sha,
        lines=lines,
    )


def binding_cells(s2: S2Inputs, admitted_k: int | None = None) -> list[BindingCell]:
    """k x bids in S2's IQR rounded outward to the grid (all three when there is no IQR)."""
    bids: tuple[float, ...]
    if s2.bid_iqr is None:
        bids = GRID_BIDS
    else:
        low = max((g for g in GRID_BIDS if g <= s2.bid_iqr[0] + _TOL), default=GRID_BIDS[0])
        high = min((g for g in GRID_BIDS if g >= s2.bid_iqr[1] - _TOL), default=GRID_BIDS[-1])
        bids = tuple(g for g in GRID_BIDS if low <= g <= high)
    ks = (admitted_k,) if admitted_k else (2, 1)
    return [
        BindingCell(
            k,
            b,
            s2.f_kill if k == 2 else s2.f_kill_k1,
            s2.f_pass if k == 2 else s2.f_pass_k1,
        )
        for k in ks
        for b in bids
    ]


def mix_for(cell: BindingCell, s2: S2Inputs, *, f: float, theta: float) -> MakerMix:
    share = s2.two_fill_share if cell.k == 2 else 0.0
    return MakerMix(f, cell.b, cell.k, s2.bid_bearing, share, s2.fill_icc, theta)  # type: ignore[arg-type]


def load_s5_cap_pin(path: Path) -> CapPin:
    doc, _text, sha = _json(path)
    parsed: dict[str, date] = {}
    for key in ("holdout_start_date", "calendar_cap_date"):
        if key not in doc:
            raise MakerRefusal(f"S5 cap pin is missing {key}")
        try:
            parsed[key] = date.fromisoformat(str(doc[key]))
        except ValueError as exc:
            raise MakerRefusal(f"S5 cap pin {key} is not an ISO date: {exc}") from exc
    start, cap = parsed["holdout_start_date"], parsed["calendar_cap_date"]
    l_cap = inclusive_days(start, cap)
    if l_cap < 1:
        raise MakerRefusal(f"L_cap {l_cap} < 1: calendar_cap_date precedes holdout_start_date")
    return CapPin(start, cap, l_cap, sha)


def _classify(row: Mapping[str, Any], seen: Mapping[str, bool]) -> str:
    if row["reason"] != "NEVER_LISTED":
        return "listed"
    return "unlisted" if seen[str(row["climate_day"])] else "unknown"


def listing_rate_4stn(rows: Sequence[Mapping[str, Any]]) -> ListingRate:
    """LISTED / (LISTED + UNLISTED) over LAX/MDW/MIA/SFO. PRE_TRADE_CAPTURE rows are dropped.

    A NEVER_LISTED row on a climate day where no row has ``first_seen_ns`` is a recorder
    outage (UNKNOWN), excluded from the rate; with a seen sibling it is UNLISTED.
    """
    kept = [row for row in rows if row["reason"] != "PRE_TRADE_CAPTURE"]
    seen: dict[str, bool] = defaultdict(bool)
    for row in kept:
        seen[str(row["climate_day"])] |= row["first_seen_ns"] is not None
    four = [row for row in kept if row["station"] in STATIONS]
    counts = Counter(_classify(row, seen) for row in four)
    unknown_all = sum(_classify(row, seen) == "unknown" for row in kept)
    listed, unlisted, unknown = counts["listed"], counts["unlisted"], counts["unknown"]
    if listed + unlisted == 0:
        raise MakerRefusal("S1 census has no LISTED or UNLISTED station-day for the four stations")
    return ListingRate(
        listed / (listed + unlisted),
        unknown / len(four),
        listed,
        unlisted,
        unknown,
        len(rows),
        unknown_all / len(kept),
    )


def _s1_row(path: Path, number: int, line: str) -> dict[str, Any]:
    where = f"S1 census {path}:{number}"
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise MakerRefusal(f"{where} is not JSON: {exc}") from exc
    if not isinstance(row, dict):
        raise MakerRefusal(f"{where} must be a JSON object, got {type(row).__name__}")
    for key in ("station", "climate_day", "reason", "first_seen_ns"):
        if key not in row:
            raise MakerRefusal(f"{where} is missing {key}")
    for key in ("station", "climate_day"):
        if not isinstance(row[key], str) or not row[key]:
            raise MakerRefusal(f"{where} {key} must be a non-empty string")
    if row["reason"] not in REASONS:
        raise MakerRefusal(f"{where} reason {row['reason']!r} is not one of {REASONS}")
    ns = row["first_seen_ns"]
    if ns is not None and (isinstance(ns, bool) or not isinstance(ns, int)):
        raise MakerRefusal(f"{where} first_seen_ns must be an integer or null, got {ns!r}")
    return row


def load_s1(path: Path) -> tuple[ListingRate, str]:
    text, sha = _read(path)
    rows = [
        _s1_row(path, number, line)
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    rate = listing_rate_4stn(rows)
    if rate.listing_rate < LISTING:
        raise MakerRefusal(f"listing_rate_4stn {rate.listing_rate:.4f} < pin {LISTING}")
    if rate.unknown_share > UNKNOWN_SHARE_MAX:
        raise MakerRefusal(f"unknown_share {rate.unknown_share:.4f} > {UNKNOWN_SHARE_MAX}")
    return rate, sha
