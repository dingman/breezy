"""MAKER-S2 WP1: the ``FROZEN_DATE_SET`` block parser and the frozen-set rule (E5).

Plan r4 delta (b). The licensing amendment
(``docs/evidence/RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md``) carries one fenced
block; the driver parses it and FAILS CLOSED on: an unfilled ``<FILL...>`` placeholder, a date
outside the rule, 2026-10-01 (sealed holdout day), a date after 2026-10-13, an NYC row, a
(station, day) outside the set, a DRAFT amendment and an amendment sha mismatch.

The rule (mechanical, applied once after the S1 run): every day from the first replayable day to
``min(2026-10-13, last FINAL day of the pinned truth CSV)``, 2026-10-01 excluded.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.analysis.maker_tape_census import CensusedDay
from scripts.analysis.maker_stage0_inputs import MAKER_STATIONS, TruthTable, sha256_bytes

__all__ = [
    "FrozenDateSet",
    "FrozenSetRefused",
    "assert_in_frozen_set",
    "load_amendment",
    "parse_frozen_block",
    "rule_dates",
    "verify_set_matches_rule",
]

SEALED_DAY: Final[dt.date] = dt.date(2026, 10, 1)
LAST_ALLOWED_DAY: Final[dt.date] = dt.date(2026, 10, 13)
FIRST_REPLAYABLE_CHOICES: Final[tuple[dt.date, ...]] = (dt.date(2026, 9, 18), dt.date(2026, 9, 19))
_FIELDS: Final[tuple[str, ...]] = (
    "stations",
    "first_replayable_day",
    "truth_csv_path",
    "truth_csv_sha256",
    "last_final_day",
    "dates",
)
_BLOCK_RE: Final[re.Pattern[str]] = re.compile(r"```FROZEN_DATE_SET[ \t]*\n(.*?)\n```", re.DOTALL)
_OPEN_FENCE: Final[str] = "```FROZEN_DATE_SET"
_SHA_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}")
_DRAFT_RE: Final[re.Pattern[str]] = re.compile(r"^Status:\s*\*{0,2}\s*DRAFT", re.MULTILINE)
_FINAL_RE: Final[re.Pattern[str]] = re.compile(r"^Status:\s*\*{0,2}\s*FINAL\b", re.MULTILINE)
_PLACEHOLDER: Final[str] = "<FILL"
_NYC: Final[str] = "NYC"


class FrozenSetRefused(ValueError):
    """The frozen replay set is unusable; the run does not start."""


@dataclass(frozen=True, slots=True)
class FrozenDateSet:
    stations: tuple[str, ...]
    first_replayable_day: dt.date
    truth_csv_path: str
    truth_csv_sha256: str
    last_final_day: dt.date
    dates: tuple[dt.date, ...]


def rule_dates(first_replayable_day: dt.date, last_final_day: dt.date) -> tuple[dt.date, ...]:
    """The mechanical rule: first .. min(2026-10-13, last FINAL day), minus 2026-10-01."""
    last = min(LAST_ALLOWED_DAY, last_final_day)
    span = (last - first_replayable_day).days + 1
    days = (first_replayable_day + dt.timedelta(days=i) for i in range(max(span, 0)))
    return tuple(d for d in days if d != SEALED_DAY)


def _read_fields(body: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        key, sep, rest = line.partition(":")
        if sep and key in _FIELDS and not line.startswith(" "):
            if key in fields:
                raise FrozenSetRefused(f"field {key!r} appears twice")
            current = key
            fields[key] = [rest.strip()] if rest.strip() else []
        elif current == "dates" and line.strip():
            fields["dates"].append(line.strip())
        else:
            raise FrozenSetRefused(f"frozen block fields: unrecognised line {line!r}")
    if set(fields) != set(_FIELDS):
        raise FrozenSetRefused(f"frozen block fields {sorted(fields)} != {sorted(_FIELDS)}")
    return fields


def _iso(text: str, what: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise FrozenSetRefused(f"{what} {text!r} is not an ISO date") from exc


def _single(fields: dict[str, list[str]], key: str) -> str:
    values = fields[key]
    if len(values) != 1:
        raise FrozenSetRefused(f"field {key!r} needs exactly one value")
    return values[0]


def _stations(text: str) -> tuple[str, ...]:
    stations = tuple(text.split())
    if _NYC in stations:
        raise FrozenSetRefused("NYC is excluded from the frozen set")
    if stations != MAKER_STATIONS:
        raise FrozenSetRefused(f"stations {stations} != {MAKER_STATIONS}")
    return stations


def _check_dates(
    dates: Sequence[dt.date], first: dt.date, last_final: dt.date
) -> tuple[dt.date, ...]:
    ceiling = min(LAST_ALLOWED_DAY, last_final)
    for day in dates:
        if day == SEALED_DAY:
            raise FrozenSetRefused(f"{day} is the sealed holdout day")
        if day > LAST_ALLOWED_DAY:
            raise FrozenSetRefused(f"{day} is after {LAST_ALLOWED_DAY}")
        if not first <= day <= ceiling:
            raise FrozenSetRefused(f"{day} is outside the rule [{first}, {ceiling}]")
    if list(dates) != sorted(set(dates)):
        raise FrozenSetRefused("dates must be strictly ascending, one per line, no duplicates")
    if not dates:
        raise FrozenSetRefused("the frozen block holds no dates")
    return tuple(dates)


def parse_frozen_block(text: str) -> FrozenDateSet:
    """Parse the one fenced ``FROZEN_DATE_SET`` block of the amendment text."""
    if text.count(_OPEN_FENCE) != 1 or len(_BLOCK_RE.findall(text)) != 1:
        raise FrozenSetRefused("the amendment must hold exactly one FROZEN_DATE_SET block")
    body = _BLOCK_RE.findall(text)[0]
    if _PLACEHOLDER in body:
        raise FrozenSetRefused("the frozen block still holds an unfilled <FILL placeholder")
    fields = _read_fields(body)
    sha = _single(fields, "truth_csv_sha256")
    if _SHA_RE.fullmatch(sha) is None:
        raise FrozenSetRefused(f"truth_csv_sha256 {sha!r} is not a lowercase sha256")
    first = _iso(_single(fields, "first_replayable_day"), "first_replayable_day")
    if first not in FIRST_REPLAYABLE_CHOICES:
        raise FrozenSetRefused(f"first_replayable_day {first} not in {FIRST_REPLAYABLE_CHOICES}")
    last_final = _iso(_single(fields, "last_final_day"), "last_final_day")
    dates = [_iso(item, "date") for item in fields["dates"]]
    return FrozenDateSet(
        stations=_stations(_single(fields, "stations")),
        first_replayable_day=first,
        truth_csv_path=_single(fields, "truth_csv_path"),
        truth_csv_sha256=sha,
        last_final_day=last_final,
        dates=_check_dates(dates, first, last_final),
    )


def load_amendment(path: Path, expected_sha: str) -> FrozenDateSet:
    """Read the FINAL amendment, check its sha256 against the pinned one, parse its block."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FrozenSetRefused(f"amendment {path.name} unreadable ({type(exc).__name__})") from exc
    digest = sha256_bytes(data)
    if digest != expected_sha:
        raise FrozenSetRefused(f"amendment sha {digest} != pinned {expected_sha}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FrozenSetRefused(f"amendment {path.name} is not utf-8") from exc
    if _DRAFT_RE.search(text):
        raise FrozenSetRefused("the amendment is still DRAFT; only FINAL bytes license the reads")
    if _FINAL_RE.search(text) is None:
        raise FrozenSetRefused("the amendment has no positive 'Status: FINAL' line")
    return parse_frozen_block(text)


def assert_in_frozen_set(fs: FrozenDateSet, station: str, day: dt.date) -> None:
    """Refuse any (station, day) the replay is not licensed to read."""
    if station == _NYC:
        raise FrozenSetRefused("NYC is excluded from every read")
    if day == SEALED_DAY:
        raise FrozenSetRefused(f"{day} is the sealed holdout day")
    if station not in fs.stations or day not in fs.dates:
        raise FrozenSetRefused(f"({station}, {day}) is not in the frozen set")


def verify_set_matches_rule(
    fs: FrozenDateSet, census: Iterable[CensusedDay], truth: TruthTable
) -> None:
    """The block equals the rule applied to the pinned truth CSV and the census."""
    if truth.csv_sha256 != fs.truth_csv_sha256:
        raise FrozenSetRefused(
            f"truth csv sha256 {truth.csv_sha256} != the block's {fs.truth_csv_sha256}"
        )
    last_final = max((day for _, day in truth.finals), default=None)
    if last_final is None or min(last_final, LAST_ALLOWED_DAY) != min(
        fs.last_final_day, LAST_ALLOWED_DAY
    ):
        raise FrozenSetRefused(
            f"last_final_day {fs.last_final_day} != the truth CSV's last FINAL day {last_final}"
        )
    expected = rule_dates(fs.first_replayable_day, fs.last_final_day)
    if fs.dates != expected:
        missing = sorted(d.isoformat() for d in set(expected) - set(fs.dates))
        extra = sorted(d.isoformat() for d in set(fs.dates) - set(expected))
        raise FrozenSetRefused(f"frozen set differs from the rule: missing {missing} extra {extra}")
    census_days = {row.climate_day for row in census}
    absent = sorted(set(fs.dates) - census_days)
    if absent:
        raise FrozenSetRefused(f"the census holds no rows for set dates {absent}")
