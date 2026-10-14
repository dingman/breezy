"""MAKER-S2 WP1: the replay's input loaders (census, trade unit, truth) and the V0 estimator.

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md WP1 and the r4 delta (a),
(e), (g). Every loader refuses (never guesses) on a malformed or inconsistent input.

* The census is S1's ``censused_days.jsonl`` read through S1's own ``read_censused_days``; NYC is
  filtered and counted, any other station outside the four is refused.
* The trade unit is S1's crosscheck result: ``RESOLVED(one)`` or ``BRACKETED_USD``; ``UNRESOLVED``
  (an S-2 STOP) is refused.
* Truth is the F2 finals CSV (schema ``fq_truth_cli/v1``): FINAL-grade rows only, copied into the
  run directory and sha-pinned, cross-checked against the stale settlement-truth parquet.
* ``n_eff_gov`` is S1's outcome-independent effective n, computed from S1's imported
  ``RHO_ASSUMED`` / ``N_EFF_FLOOR``; S1's private helper is neither imported nor aliased.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Self

from breezy.analysis.maker_tape_census import (
    N_EFF_FLOOR,
    RHO_ASSUMED,
    CensusedDay,
    read_censused_days,
)
from breezy.analysis.trade_quantity_unit import UNIT_HYPOTHESES, USD_BRACKET

__all__ = [
    "MAKER_STATIONS",
    "CensusLoad",
    "InputRefused",
    "TradeUnit",
    "TruthConflict",
    "TruthTable",
    "UnitHypothesis",
    "UnitRefused",
    "is_underpowered",
    "load_census_days",
    "load_trade_unit",
    "load_truth",
    "n_eff_gov",
    "per_date_counts",
    "sha256_bytes",
    "sha256_file",
]

MAKER_STATIONS: Final[tuple[str, ...]] = ("LAX", "MDW", "MIA", "SFO")
_EXCLUDED_STATION: Final[str] = "NYC"
BRACKETED_VERDICT: Final[str] = "BRACKETED_USD"
UNRESOLVED_VERDICT: Final[str] = "UNRESOLVED"
TRUTH_COPY_NAME: Final[str] = "truth_cli_finals.csv"
#: ``fq_truth_cli/v1`` columns this loader needs (any other column is ignored).
TRUTH_COLUMNS: Final[frozenset[str]] = frozenset(
    {"station", "climate_day", "tmax_f", "tmax_flag", "correction_flag", "product_sha256"}
)
_SELLER: Final[str] = "SELLER"
_BUYER: Final[str] = "BUYER"
_CHUNK: Final[int] = 1 << 20


class InputRefused(ValueError):
    """An input is missing, malformed or inconsistent; the run does not start."""


class UnitRefused(InputRefused):
    """The trade-print quantity unit is unresolved, inconsistent or misused."""


class TruthConflict(InputRefused):
    """Two truth sources (or two uncorrected rows) disagree about one station-day."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


# --- census -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CensusLoad:
    rows: tuple[CensusedDay, ...]
    nyc_filtered: int


def load_census_days(path: Path) -> CensusLoad:
    """Schema-asserted read (S1's reader refuses unknown keys/reasons/duplicates)."""
    rows = read_censused_days(path)
    kept: list[CensusedDay] = []
    nyc = 0
    for row in rows:
        if row.station == _EXCLUDED_STATION:
            nyc += 1
        elif row.station in MAKER_STATIONS:
            kept.append(row)
        else:
            raise InputRefused(f"census row for station {row.station!r} outside {MAKER_STATIONS}")
    return CensusLoad(rows=tuple(kept), nyc_filtered=nyc)


# --- V0 (r4 delta (a)) --------------------------------------------------------------------


def per_date_counts(rows: Iterable[CensusedDay]) -> dict[dt.date, int]:
    """``m_d``: how many of ``rows`` fall on each climate date."""
    counts: dict[dt.date, int] = defaultdict(int)
    for row in rows:
        counts[row.climate_day] += 1
    return dict(counts)


def n_eff_gov(per_date: Mapping[dt.date, int]) -> float:
    """``sum_d m_d / (1 + (m_d - 1) * RHO_ASSUMED)``: S1's outcome-independent form."""
    return sum(m / (1 + (m - 1) * RHO_ASSUMED) for m in per_date.values())


def is_underpowered(n_eff: float) -> bool:
    """V0: ``n_eff_gov < N_EFF_FLOOR`` (spec 6.0)."""
    return n_eff < N_EFF_FLOOR


# --- trade unit ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnitHypothesis:
    """One reading of a trade print's ``size``; converts it to contracts."""

    name: str

    def to_contracts(
        self, size: Decimal, yes_price: Decimal, aggressor: str | None = None
    ) -> Decimal:
        """Contracts behind a print of ``size`` at YES-frame ``yes_price``.

        ``USD_NOTIONAL_TAKER`` divides by the TAKER's per-contract cost, which depends on the
        aggressor: a BUYER pays ``yes_price``, a SELLER (a NO purchase) pays ``1 - yes_price``.
        """
        if not Decimal(0) < yes_price < Decimal(1):
            raise UnitRefused(f"yes price {yes_price} is outside (0, 1)")
        if self.name == "CONTRACTS":
            return size
        if self.name == "USD_NOTIONAL_YES":
            return size / yes_price
        return size / self._taker_price(yes_price, aggressor)

    def _taker_price(self, yes_price: Decimal, aggressor: str | None) -> Decimal:
        if aggressor == _BUYER:
            return yes_price
        if aggressor == _SELLER:
            return Decimal(1) - yes_price
        raise UnitRefused("USD_NOTIONAL_TAKER needs the print's aggressor side (BUYER or SELLER)")


@dataclass(frozen=True, slots=True)
class TradeUnit:
    verdict: str
    names: tuple[str, ...]

    @classmethod
    def from_result(cls, result: Mapping[str, object]) -> Self:
        """Validate S1's crosscheck result; refuse UNRESOLVED and any inconsistency."""
        verdict = str(result.get("verdict"))
        if verdict == UNRESOLVED_VERDICT or result.get("s2_stop") is True:
            raise UnitRefused(
                f"trade unit is {UNRESOLVED_VERDICT} (S-2 STOP): {result.get('reason')}"
            )
        surviving = result.get("surviving")
        if not isinstance(surviving, list) or not all(isinstance(s, str) for s in surviving):
            raise UnitRefused("trade unit result has no 'surviving' list")
        expected = _expected_names(verdict)
        if sorted(surviving) != sorted(expected):
            raise UnitRefused(f"surviving {sorted(surviving)} contradicts verdict {verdict!r}")
        return cls(verdict=verdict, names=tuple(sorted(expected)))

    def hypotheses(self) -> tuple[UnitHypothesis, ...]:
        """One converter when RESOLVED, two when BRACKETED (stage 0 runs under both)."""
        return tuple(UnitHypothesis(name) for name in self.names)


def _expected_names(verdict: str) -> tuple[str, ...]:
    if verdict in UNIT_HYPOTHESES:
        return (verdict,)
    if verdict == BRACKETED_VERDICT:
        return tuple(sorted(USD_BRACKET))
    raise UnitRefused(f"unknown trade-unit verdict {verdict!r}")


def load_trade_unit(path: Path) -> TradeUnit:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UnitRefused(f"trade-unit result unreadable: {type(exc).__name__}") from exc
    if not isinstance(result, dict):
        raise UnitRefused("trade-unit result is not a JSON object")
    return TradeUnit.from_result(result)


# --- truth --------------------------------------------------------------------------------

TruthKey = tuple[str, dt.date]


@dataclass(frozen=True, slots=True)
class TruthTable:
    finals: Mapping[TruthKey, int]
    csv_sha256: str
    run_copy: Path
    cross_check_sha256: str
    n_overlap: int


def _final_rows(text: str) -> dict[TruthKey, int]:
    reader = csv.DictReader(text.splitlines())
    if not TRUTH_COLUMNS <= set(reader.fieldnames or ()):
        raise InputRefused(f"truth csv lacks a required column: {sorted(TRUTH_COLUMNS)}")
    by_key: dict[TruthKey, list[tuple[bool, int]]] = defaultdict(list)
    for raw in reader:
        station = raw["station"]
        if station == _EXCLUDED_STATION or raw["tmax_f"] == "" or raw["tmax_flag"] != "":
            continue
        correction = _flag(raw["correction_flag"])
        key = (station, dt.date.fromisoformat(raw["climate_day"]))
        by_key[key].append((correction, int(raw["tmax_f"])))
    return {key: _revision(key, rows) for key, rows in by_key.items()}


def _flag(raw: str) -> bool:
    if raw not in ("True", "False"):
        raise InputRefused(f"correction_flag {raw!r} is not True/False")
    return raw == "True"


def _revision(key: TruthKey, rows: list[tuple[bool, int]]) -> int:
    """A correction takes the final revision; otherwise every row must agree."""
    corrected = {tmax for flag, tmax in rows if flag}
    pool = corrected or {tmax for _, tmax in rows}
    if len(pool) != 1:
        raise TruthConflict(f"conflicting truth rows for {key[0]} {key[1]}: {sorted(pool)}")
    return next(iter(pool))


def _cross_check_finals(path: Path) -> dict[TruthKey, int]:
    import pyarrow.parquet as pq  # deferred: the cheap entry import stays cheap

    table = pq.read_table(path, columns=["station", "climate_day", "status", "tmax_f"])
    finals: dict[TruthKey, int] = {}
    for record in table.to_pylist():
        if record["status"] != "FINAL" or record["tmax_f"] is None:
            continue
        finals[(record["station"], record["climate_day"])] = int(record["tmax_f"])
    return finals


def load_truth(
    csv_path: Path,
    cross_check: Path,
    run_dir: Path,
    *,
    expected_csv_sha256: str | None = None,
) -> TruthTable:
    """FINAL-grade truth; the CSV is copied into ``run_dir`` (from the bytes hashed) and pinned.

    The stale ``settlement_truth.parquet`` is an overlap cross-check only: on any shared
    station-day the two sources must agree on ``tmax_f`` or :class:`TruthConflict` is raised
    (before anything is written).
    """
    data = csv_path.read_bytes()
    digest = sha256_bytes(data)
    if expected_csv_sha256 is not None and digest != expected_csv_sha256:
        raise InputRefused(f"truth csv sha256 {digest} != pinned {expected_csv_sha256}")
    finals = _final_rows(data.decode("utf-8"))
    other = _cross_check_finals(cross_check)
    overlap = finals.keys() & other.keys()
    for key in sorted(overlap):
        if finals[key] != other[key]:
            raise TruthConflict(
                f"truth sources disagree for {key[0]} {key[1]}: csv {finals[key]} "
                f"vs parquet {other[key]}"
            )
    run_dir.mkdir(parents=True, exist_ok=True)
    copy = run_dir / TRUTH_COPY_NAME
    copy.write_bytes(data)
    return TruthTable(
        finals=finals,
        csv_sha256=digest,
        run_copy=copy,
        cross_check_sha256=sha256_file(cross_check),
        n_overlap=len(overlap),
    )
