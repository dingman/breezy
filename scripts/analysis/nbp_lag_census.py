#!/usr/bin/env python3
"""SL-3 TASK B: the NBM NBP publication-lag census.

Read-only, LISTING-ONLY: every request is an unauthenticated S3
``ListObjectsV2`` call against the public ``noaa-nbm-grib2-pds`` bucket
(``?list-type=2&prefix=...``). No object BODY is ever fetched -- the whole
point is to read ``LastModified`` off the listing, never the ~30+ MB
bulletin itself (see ``breezy.ingest.nbm_quantile_transport`` for the
station-filtered streaming fetch of the bulletin body).

Reproduces ``docs/evidence/NBP_LAG_CENSUS_2026-09-29.md``: 60 dates (the 30
days ending ``--today``, plus 30 fixed dates spread across 2021-2026,
bracketing every NBM version-era boundary) x the 6 cycles named in the plan
(00/01/07/12/13/19Z).

**Listing-only by default.** Running this script with no flags performs NO
network I/O -- it prints the planned request plan (dates x cycles) and
exits. A real run needs BOTH ``BREEZY_LIVE=1`` in the environment AND
``--live`` on the command line, mirroring every other network-touching
script in this repo (``LIVE_ENV_VAR``). Neither switch alone is enough.

This module imports nothing from ``breezy`` and nothing from
``nautilus_trader`` -- it is a standalone stdlib script, deliberately not
built on :mod:`breezy.ingest.http`'s hardened transport. Reusing that
hardening here (a single unauthenticated GET to one fixed public listing
endpoint, no credentials, no settlement path anywhere nearby) is a DRY
opportunity, not a safety requirement; it is explicitly deferred to its own
slice rather than folded into this evidence-reproduction fix.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

LIVE_ENV_VAR: Final[str] = "BREEZY_LIVE"
USER_AGENT: Final[str] = (
    "breezy-nbp-lag-census (contact: jon@gopoint.com; SL-3 evidence reproduction)"
)

BUCKET: Final[str] = "noaa-nbm-grib2-pds"
LIST_URL: Final[str] = f"https://{BUCKET}.s3.amazonaws.com/"
_S3_NAMESPACE: Final[str] = "http://s3.amazonaws.com/doc/2006-03-01/"

CYCLES: Final[tuple[int, ...]] = (0, 1, 7, 12, 13, 19)

#: (era name, first date it applies). Matches the plan/ruling's named NBM
#: version boundaries verbatim.
VERSION_BREAKS: Final[tuple[tuple[str, dt.date], ...]] = (
    ("v4.0", dt.date(2020, 9, 29)),
    ("v4.1", dt.date(2023, 1, 17)),
    ("v4.2", dt.date(2024, 5, 15)),
    ("v4.3", dt.date(2025, 5, 27)),
    ("v5.0", dt.date(2026, 5, 4)),
)

#: Fixed dates spread across every era, independent of `--today`, so a
#: re-run always samples the SAME historical points. Chosen to bracket each
#: version boundary (just before / just after).
_SPREAD_ANCHOR_DATES: Final[tuple[dt.date, ...]] = (
    dt.date(2021, 1, 15),
    dt.date(2021, 6, 15),
    dt.date(2021, 9, 29),
    dt.date(2021, 11, 15),
    dt.date(2022, 2, 15),
    dt.date(2022, 6, 15),
    dt.date(2022, 10, 15),
    dt.date(2023, 1, 10),  # just before v4.1
    dt.date(2023, 1, 20),  # just after v4.1
    dt.date(2023, 6, 15),
    dt.date(2023, 11, 15),
    dt.date(2024, 2, 15),
    dt.date(2024, 5, 10),  # just before v4.2
    dt.date(2024, 5, 20),  # just after v4.2
    dt.date(2024, 8, 15),
    dt.date(2024, 11, 15),
    dt.date(2025, 2, 15),
    dt.date(2025, 5, 20),  # just before v4.3
    dt.date(2025, 6, 1),  # just after v4.3
    dt.date(2025, 8, 15),
    dt.date(2025, 11, 15),
    dt.date(2026, 1, 15),
    dt.date(2026, 3, 15),
    dt.date(2026, 4, 28),  # just before v5.0
    dt.date(2026, 5, 10),  # just after v5.0
    dt.date(2026, 5, 20),
    dt.date(2026, 6, 15),
    dt.date(2026, 7, 15),
    dt.date(2026, 8, 1),
    dt.date(2026, 8, 15),
)

_LAST_N_DAYS: Final[int] = 30


def version_for(date: dt.date) -> str:
    """Return the NBM version era active on `date`."""
    version = VERSION_BREAKS[0][0]
    for name, start in VERSION_BREAKS:
        if date >= start:
            version = name
        else:
            break
    return version


def sample_dates(today: dt.date) -> list[dt.date]:
    """The 60-date census sample: the 30 days ending `today`, plus 30 fixed
    dates spread across every NBM version era (independent of `today`)."""
    dates: set[dt.date] = {today - dt.timedelta(days=offset) for offset in range(_LAST_N_DAYS)}
    dates.update(_SPREAD_ANCHOR_DATES)
    return sorted(dates)


@dataclass(frozen=True, slots=True)
class CensusRecord:
    """One (date, cycle) observation. JSON field names are stable -- this is
    the schema `docs/evidence/data/NBP_LAG_CENSUS_2026-09-29_records.json`
    was written in."""

    date: str
    cycle_hour: int
    version: str
    cycle_iso: str
    status: str
    last_modified: str | None = None
    lag_seconds: float | None = None
    lag_minutes: float | None = None

    def to_json(self) -> dict[str, str | int | float | None]:
        return dict(asdict(self))


def _prefix_for(date: dt.date, hour: int) -> str:
    return f"blend.{date:%Y%m%d}/{hour:02d}/text/blend_nbptx"


def parse_last_modified(raw_xml: str, *, hour: int) -> str | None:
    """Return the `LastModified` of the exact base product key, if listed.

    Pure and network-free -- the one piece of this module worth unit
    testing without a live socket. Prefers an exact
    `blend_nbptx.t{HH}z` key match over any sidecar (`.idx` etc.) the
    listing might also carry; falls back to the first entry if no exact
    match is present.
    """
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return None
    contents = root.findall(f"{{{_S3_NAMESPACE}}}Contents")
    if not contents:
        return None
    exact_suffix = f"blend_nbptx.t{hour:02d}z"
    chosen = None
    for element in contents:
        key = element.find(f"{{{_S3_NAMESPACE}}}Key")
        if key is not None and key.text is not None and key.text.endswith(exact_suffix):
            chosen = element
            break
    if chosen is None:
        chosen = contents[0]
    last_modified = chosen.find(f"{{{_S3_NAMESPACE}}}LastModified")
    if last_modified is None or last_modified.text is None:
        return None
    return last_modified.text


def _record_for(raw_xml: str | None, *, date: dt.date, hour: int) -> CensusRecord:
    version = version_for(date)
    cycle_dt = dt.datetime(date.year, date.month, date.day, hour, tzinfo=dt.UTC)
    last_modified = None if raw_xml is None else parse_last_modified(raw_xml, hour=hour)
    if last_modified is None:
        return CensusRecord(
            date=date.isoformat(),
            cycle_hour=hour,
            version=version,
            cycle_iso=cycle_dt.isoformat(),
            status="MISSING",
        )
    lm_dt = dt.datetime.strptime(last_modified, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.UTC)
    lag_seconds = (lm_dt - cycle_dt).total_seconds()
    return CensusRecord(
        date=date.isoformat(),
        cycle_hour=hour,
        version=version,
        cycle_iso=cycle_dt.isoformat(),
        status="OK",
        last_modified=last_modified,
        lag_seconds=lag_seconds,
        lag_minutes=lag_seconds / 60.0,
    )


def _fetch_listing(date: dt.date, hour: int, *, timeout: float) -> str | None:
    """One live, unauthenticated GET. Listing only -- no object body."""
    url = f"{LIST_URL}?list-type=2&prefix={_prefix_for(date, hour)}&max-keys=5"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body: bytes = response.read()
    except urllib.error.URLError:
        return None
    return body.decode("utf-8", errors="strict")


def _live_unlocked() -> bool:
    return os.environ.get(LIVE_ENV_VAR) == "1"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--today",
        type=dt.date.fromisoformat,
        default=dt.date(2026, 9, 29),
        help="Anchor date for the 'last 30 days' half of the sample (ISO, default 2026-09-29).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            f"Actually issue the S3 listing requests. Also requires "
            f"{LIVE_ENV_VAR}=1 in the environment. Without both, this script "
            "only prints the planned request count and exits 0."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/evidence/data/NBP_LAG_CENSUS_2026-09-29_records.json"),
        help="Where to write the derived records JSON (only with --live).",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("docs/evidence/data/nbp_lag_census_raw"),
        help="Where to write raw ListObjectsV2 XML, one file per request (only with --live).",
    )
    parser.add_argument(
        "--timeout", type=float, default=20.0, help="Per-request socket timeout, seconds."
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    dates = sample_dates(args.today)
    total = len(dates) * len(CYCLES)

    if not args.live or not _live_unlocked():
        print(
            f"[dry-run] {len(dates)} dates x {len(CYCLES)} cycles = {total} listing "
            f"requests planned. Pass --live with {LIVE_ENV_VAR}=1 to actually run them.",
            file=sys.stderr,
        )
        return 0

    args.raw_dir.mkdir(parents=True, exist_ok=True)
    records: list[CensusRecord] = []
    index = 0
    for date in dates:
        for hour in CYCLES:
            index += 1
            raw_xml = _fetch_listing(date, hour, timeout=args.timeout)
            raw_path = args.raw_dir / f"listing_{date:%Y%m%d}_{hour:02d}z_{index:04d}.xml"
            raw_path.write_text(raw_xml or "", encoding="utf-8")
            records.append(_record_for(raw_xml, date=date, hour=hour))
            time.sleep(0.05)
            if index % 25 == 0:
                print(f"...{index}/{total}", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps([r.to_json() for r in records], indent=2), encoding="utf-8")
    print(json.dumps({"total": len(records), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
