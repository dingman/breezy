"""Pure helpers for the historical PFM backfill: body-time placement and the refusal quarantine.

* ``body_issuance_utc``: every PFM product prints its issuance in LOCAL time with a full date
  ("1201 AM CST THU JAN 1 2021", "615 PM CST Thu Dec 31 2020") in the header block, before the
  first zone line. The WMO heading (``DDHHMM``) carries no month or year, so the body line is
  the unambiguous placement source and the WMO heading is cross-checked against it.
* ``wmo_instant_near``: the instant with the WMO day/hour/minute nearest an anchor.
* ``RefusalQuarantine``: writes each refused raw product plus a JSON line saying why.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Final

__all__ = [
    "BODY_WMO_TOLERANCE",
    "BodyTimeError",
    "RefusalQuarantine",
    "body_issuance_utc",
    "wmo_instant_near",
]

#: Body time and WMO heading are minutes apart (858 AM PDT vs 071559); more is a conflict.
BODY_WMO_TOLERANCE: Final[dt.timedelta] = dt.timedelta(hours=2)
_BODY_SCAN_LINES: Final[int] = 20
_BODY_ISSUED_RE: Final[re.Pattern[str]] = re.compile(
    r"^(\d{1,2})(\d{2}) ([AP]M) ([A-Z]{3,4}) ([A-Z]{3}) ([A-Z]{3}) (\d{1,2}) (\d{4})$",
    re.IGNORECASE,
)
#: A line that LOOKS like an issuance line ("615 PM CST ..."); if the strict form does not match
#: it, the product is refused rather than placed as though it had no body time.
_BODY_CANDIDATE_RE: Final[re.Pattern[str]] = re.compile(r"^\d{3,4}\s+[A-Z]M\b", re.IGNORECASE)
_WEEKDAYS: Final[tuple[str, ...]] = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
#: UTC offset in hours of each zone the closed five-office set prints.
_TZ_OFFSET_H: Final[dict[str, int]] = {
    "UTC": 0,
    "GMT": 0,
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
}
_MONTHS: Final[dict[str, int]] = {
    m: i
    for i, m in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1
    )
}
_MAX_HOUR_12: Final[int] = 12
_MAX_MINUTE: Final[int] = 59


class BodyTimeError(ValueError):
    """A body issuance line is present but unusable; ``reason`` is the refusal counted."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def _unparseable(line: str) -> BodyTimeError:
    return BodyTimeError(f"unparseable body issuance line {line!r}", "body_time_unparseable")


def body_issuance_utc(product: str) -> dt.datetime | None:
    """The UTC instant of the first local-time issuance line in the header block.

    None only when the header block has NO issuance line (the caller then uses cursor-relative
    placement). A line that is present but unusable (zone outside the table, impossible
    clock/date, typo) raises ``BodyTimeError("body_time_unparseable")``; a weekday token that
    contradicts the date raises ``BodyTimeError("body_weekday_mismatch")``. Never a guess.
    """
    for raw_line in product.splitlines()[:_BODY_SCAN_LINES]:
        line = raw_line.strip()
        match = _BODY_ISSUED_RE.match(line)
        if match is None:
            if _BODY_CANDIDATE_RE.match(line):
                raise _unparseable(line)
            continue
        hour12, minute, meridiem, zone, weekday, month_name, day, year = match.groups()
        offset = _TZ_OFFSET_H.get(zone.upper())
        month = _MONTHS.get(month_name.upper())
        hour, mins = int(hour12), int(minute)
        if offset is None or month is None or not 1 <= hour <= _MAX_HOUR_12 or mins > _MAX_MINUTE:
            raise _unparseable(line)
        hour = hour % _MAX_HOUR_12 + (_MAX_HOUR_12 if meridiem.upper() == "PM" else 0)
        try:
            local = dt.datetime(int(year), month, int(day), hour, mins, tzinfo=dt.UTC)
        except ValueError:
            raise _unparseable(line) from None
        if weekday.upper() not in _WEEKDAYS:
            raise _unparseable(line)
        if _WEEKDAYS[local.weekday()] != weekday.upper():
            raise BodyTimeError(
                f"body weekday {weekday} contradicts {local.date().isoformat()}",
                "body_weekday_mismatch",
            )
        return local - dt.timedelta(hours=offset)
    return None


def wmo_instant_near(day: int, hour: int, minute: int, anchor: dt.datetime) -> dt.datetime | None:
    """The instant with this day/hour/minute (month before/of/after `anchor`) nearest `anchor`."""
    best: dt.datetime | None = None
    for step in (-1, 0, 1):
        index = anchor.year * 12 + (anchor.month - 1) + step
        try:
            cand = dt.datetime(index // 12, index % 12 + 1, day, hour, minute, tzinfo=dt.UTC)
        except ValueError:
            continue
        if best is None or abs(cand - anchor) < abs(best - anchor):
            best = cand
    return best


class RefusalQuarantine:
    """Append-only record of refused products: ``<sha256>.raw`` plus ``refusals.jsonl`` lines."""

    LOG_NAME: Final[str] = "refusals.jsonl"

    def __init__(self, root: Path) -> None:
        self._root = root

    def record(
        self,
        *,
        reason: str,
        station: str,
        wfo: str,
        sdate: dt.datetime,
        issued: dt.datetime | None,
        raw: bytes,
    ) -> None:
        digest = hashlib.sha256(raw).hexdigest()
        raw_file = f"{digest}.raw"
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._root / raw_file
        if not target.exists():
            partial = self._root / f"{digest}.raw.tmp"
            partial.write_bytes(raw)
            os.replace(partial, target)
        line = {
            "reason": reason,
            "station": station,
            "wfo": wfo,
            "sdate": sdate.date().isoformat(),
            "sdate_instant": sdate.isoformat(),
            "issued": issued.isoformat() if issued is not None else None,
            "sha256": digest,
            "raw_file": raw_file,
        }
        with (self._root / self.LOG_NAME).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
