"""AUD-09b producer: the `--asos-cache-csv` input file (base plan §6b.1).

`current_rung_hold_paper_replay.py` requires `--asos-cache-csv` (`required=True`,
`:1082`) and reads it verbatim with `read_asos_rows` (`:640-643`): `station,
valid,metar` rows, no price ever derived there. No producer existed for that
file; this module builds it, composed entirely from existing pieces rather
than duplicating any of them:

* `load_sites()` (`settlement_alignment_study.py`) resolves the station's IEM
  ASOS id (and its registered `std_utc_offset_hours`) through the same
  five-entry `IEM_ASOS_IDS` mapping every other analysis script uses.
* `load_recent_asos_rows()` (`cli_basis_offer_gate_scan.py`) reads every
  cached `.txt` file already sitting in the settlement-alignment cache and
  returns the rows for one IEM id, sorted by `valid`. It is explicit that
  this is CACHE-ONLY and ZERO-NETWORK: a missing directory or a station with
  nothing incidentally fetched returns `()`, never fabricated, never
  fetched. This module imports no HTTP client at all -- there is nothing
  here that could make a network call.
* `breezy.normalize.climate_day.standard_time_zone` gives the fixed
  (never-DST) standard-time offset `climate_day_utc_bounds` below composes
  with `load_sites()`'s offset, the identical pair
  `structural_dead_stop._afternoon_window_ns` composes -- except this bound
  is deliberately midnight-to-midnight, not the afternoon decision window:
  the replay driver's `load_replay_observations` consumes observations
  across the whole replayed day.

The upstream fetch that populates the settlement-alignment cache is already
scheduled from `asos_recent_refresh.py`; this module adds no new network step
and no new unit for it.

Refuses (`ASOS_CACHE_EMPTY`, non-zero exit, **no file written**) when zero
cached rows fall inside the target climate day's window: a zero-row CSV
would let the replay run and silently report a clean zero-trial day, the
"0 rows is not a quiet market" failure L-8 names.

Refuses (`ASOS_CACHE_UNPARSEABLE_ROWS`, a DIFFERENT non-zero exit, **no file
written**) when any cached row for the station has a `valid` field that does
not parse. Such a row cannot be placed inside or outside the target window at
all, so it is data the replay would silently lack rather than data correctly
excluded -- this module fails CLOSED rather than dropping it silently, and
counts it the same way `settlement_alignment_study.metar_temperatures` counts
its own `archive_parse_error` drops. Measured against the real archive
(2026-09-25): the whole-history SFO cache (574,679 rows) has zero
unparseable `valid` fields, so fail-closed costs nothing against real data.

The write itself is atomic: the CSV is built in a temp file next to `--out`
and moved into place with `os.replace`, so a reader of `--out` never
observes a partially-written file and a crash mid-write leaves nothing at
`--out` at all.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_offer_gate_scan import load_recent_asos_rows
from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
from settlement_alignment_study import SiteSpec, load_sites

from breezy.normalize.climate_day import standard_time_zone

__all__ = [
    "ASOS_CACHE_EMPTY",
    "ASOS_CACHE_UNPARSEABLE_ROWS",
    "CSV_FIELDNAMES",
    "AsosCacheCsvError",
    "WindowedAsosRows",
    "climate_day_utc_bounds",
    "main",
    "site_for_station",
    "windowed_asos_rows",
    "write_asos_cache_csv",
]

#: Exit reason for "zero cached rows fall inside the target window". The
#: runner (AUD-09b's separate `replay_daily_runner.py`, out of this item's
#: scope) hardcodes this same literal when it sees this module exit non-zero
#: -- it does not parse this module's stderr.
ASOS_CACHE_EMPTY: Final[str] = "ASOS_CACHE_EMPTY"

#: Exit reason for "at least one cached row for the station has a `valid`
#: field that does not parse". Distinct from `ASOS_CACHE_EMPTY`: this is a
#: data-quality refusal, not a "nothing in the window" verdict.
ASOS_CACHE_UNPARSEABLE_ROWS: Final[str] = "ASOS_CACHE_UNPARSEABLE_ROWS"

#: The `Counter` key `windowed_asos_rows` uses for an unparseable `valid`
#: field, mirroring `metar_temperatures`'s `archive_parse_error` drop key.
_UNPARSEABLE_VALID_DROP: Final[str] = "unparseable_valid"

#: The exact, and only, columns the replay driver's `read_asos_rows` expects.
CSV_FIELDNAMES: Final[tuple[str, str, str]] = ("station", "valid", "metar")

#: The IEM archive's own `valid` column format -- always UTC (`tz=Etc/UTC`
#: in `settlement_alignment_study.asos_url`), matching
#: `settlement_alignment_study.metar_temperatures`'s parse.
_VALID_FORMAT: Final[str] = "%Y-%m-%d %H:%M"


class AsosCacheCsvError(ValueError):
    """Raised for a `--station` value the settlement-site registry does not know."""


def site_for_station(station: str) -> SiteSpec:
    """The registered `SiteSpec` for `station`, or raise (never `None`)."""
    for spec in load_sites():
        if spec.city == station:
            return spec
    raise AsosCacheCsvError(f"unsupported station: {station!r}")


def _bounds_for_offset(std_utc_offset_hours: float, climate_day: dt.date) -> tuple[int, int]:
    """The pure half-open `[start_ns, end_ns)` bound, given an already-resolved offset."""
    tz = standard_time_zone(std_utc_offset_hours)
    start = dt.datetime.combine(climate_day, dt.time.min, tzinfo=tz)
    end = start + dt.timedelta(days=1)
    return (
        int(start.timestamp() * 1_000_000_000),
        int(end.timestamp() * 1_000_000_000),
    )


def climate_day_utc_bounds(*, station: str, climate_day: dt.date) -> tuple[int, int]:
    """Half-open `[start_ns, end_ns)` of `climate_day`, local standard time, in UTC ns.

    NEVER DST-aware, by construction of `standard_time_zone`: the climate day
    runs local-standard midnight to midnight all year, matching
    `ClimateDayWindow`'s own docstring.
    """
    spec = site_for_station(station)
    return _bounds_for_offset(spec.std_utc_offset_hours, climate_day)


def _row_ns(row: Mapping[str, str]) -> int | None:
    """The row's `valid` instant as UTC ns, or `None` for an unparseable row."""
    try:
        parsed = dt.datetime.strptime(row.get("valid", ""), _VALID_FORMAT).replace(
            tzinfo=dt.UTC
        )
    except ValueError:
        return None
    return int(parsed.timestamp() * 1_000_000_000)


@dataclass(frozen=True, slots=True)
class WindowedAsosRows:
    """The in-window rows for a station-day, plus every drop counted by reason.

    Mirrors `settlement_alignment_study.metar_temperatures`'s `(values, Counter)`
    shape: a drop is never silent, even when the caller only reads `.rows`.
    """

    rows: tuple[Mapping[str, str], ...]
    drops: Counter[str]


def windowed_asos_rows(
    *, station: str, climate_day: dt.date, cache_dir: Path
) -> WindowedAsosRows:
    """Every cached ASOS row for `station` inside `climate_day`'s window.

    ZERO NETWORK: composed entirely from `load_recent_asos_rows`'s local-cache
    scan (`iem_asos_id`-filtered, so another station's rows never reach this
    function at all) and `_bounds_for_offset`'s pure window. `site_for_station`
    is resolved exactly once here (previously resolved a second time inside
    `climate_day_utc_bounds`).

    A row whose `valid` field will not parse is never silently folded into
    "outside the window": it is counted under `_UNPARSEABLE_VALID_DROP`, so a
    caller that only reads `.rows` still has the count available in `.drops`.
    """
    spec = site_for_station(station)
    start_ns, end_ns = _bounds_for_offset(spec.std_utc_offset_hours, climate_day)
    rows = load_recent_asos_rows(cache_dir, spec.iem_asos_id)
    kept: list[Mapping[str, str]] = []
    drops: Counter[str] = Counter()
    for row in rows:
        row_ns = _row_ns(row)
        if row_ns is None:
            drops[_UNPARSEABLE_VALID_DROP] += 1
            continue
        if start_ns <= row_ns < end_ns:
            kept.append(row)
    return WindowedAsosRows(rows=tuple(kept), drops=drops)


def write_asos_cache_csv(rows: Sequence[Mapping[str, str]], out: Path) -> None:
    """Atomic whole-file write of exactly `CSV_FIELDNAMES` for `rows` to `out`."""
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_name, out)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--station", required=True)
    parser.add_argument("--climate-day", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--cache-dir", type=Path, default=DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    try:
        result = windowed_asos_rows(
            station=args.station, climate_day=args.climate_day, cache_dir=args.cache_dir
        )
    except AsosCacheCsvError as exc:
        print(f"[asos-cache-csv] {exc}", file=sys.stderr)
        return 2

    unparseable = result.drops[_UNPARSEABLE_VALID_DROP]
    if unparseable:
        print(
            f"[asos-cache-csv] {ASOS_CACHE_UNPARSEABLE_ROWS}: {unparseable} cached row(s) "
            f"for {args.station} have an unparseable 'valid' field; such a row cannot be "
            "placed inside or outside the target window, so it is refused rather than "
            "silently dropped; writing no file",
            file=sys.stderr,
        )
        return 3

    if not result.rows:
        print(
            f"[asos-cache-csv] {ASOS_CACHE_EMPTY}: no cached ASOS rows for "
            f"{args.station} inside climate day {args.climate_day}; writing no file",
            file=sys.stderr,
        )
        return 2

    write_asos_cache_csv(result.rows, args.out)
    print(f"[asos-cache-csv] wrote {len(result.rows)} row(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
