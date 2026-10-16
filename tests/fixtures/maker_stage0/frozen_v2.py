"""MAKER-S2 second look (C2): a minimal v2 amendment text builder (fixture only, no real ruling)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Final, cast

BLOCK_FIRST: Final[dt.date] = dt.date(2026, 10, 14)
TRIGGER: Final[dt.date] = dt.date(2026, 11, 4)
SHA_TRUTH: Final[str] = "ab" * 32
SHA_TRIGGER: Final[str] = "cd" * 32
SHA_CENSUS: Final[str] = "ef" * 32
SHA_CROSS: Final[str] = "12" * 32
V2_KEYS: Final[tuple[str, ...]] = (
    "stations",
    "block_first_day",
    "trigger_day",
    "trigger_rows_path",
    "trigger_rows_sha256",
    "census_days_path",
    "census_days_sha256",
    "truth_csv_path",
    "truth_csv_sha256",
    "cross_check_path",
    "cross_check_sha256",
    "last_final_day",
)


def days(first: dt.date = BLOCK_FIRST, last: dt.date = TRIGGER) -> list[dt.date]:
    return [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]


def v2_fields(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "stations": "LAX MDW MIA SFO",
        "block_first_day": BLOCK_FIRST.isoformat(),
        "trigger_day": TRIGGER.isoformat(),
        "trigger_rows_path": "docs/evidence/trigger_rows.jsonl",
        "trigger_rows_sha256": SHA_TRIGGER,
        "census_days_path": "out/censused_days.jsonl",
        "census_days_sha256": SHA_CENSUS,
        "truth_csv_path": "out/truth_cli_finals.csv",
        "truth_csv_sha256": SHA_TRUTH,
        "cross_check_path": "out/cross_check.parquet",
        "cross_check_sha256": SHA_CROSS,
        "last_final_day": TRIGGER.isoformat(),
        "dates": days(),
    }
    base.update(over)
    return base


def v2_text(fields: Mapping[str, object], fence: str = "FROZEN_DATE_SET_V2") -> str:
    lines = [f"```{fence}"]
    lines += [f"{key}: {fields[key]}" for key in V2_KEYS]
    dates = fields["dates"]
    if isinstance(dates, str):
        lines.append(f"dates: {dates}")
    else:
        lines.append("dates:")
        lines.extend(d.isoformat() for d in cast("list[dt.date]", dates))
    lines.append("```")
    return "# second look\nStatus: **FINAL**\n\n" + "\n".join(lines) + "\n\ntrailer\n"
