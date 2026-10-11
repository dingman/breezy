"""Synthetic, offline fixtures for the TE-2 FQ loss taxonomy tests (plan r3.2 P6, P16, WP0).

The 25-fill grid reproduces the verified October counts: 14 station-days, 7 station-event
clusters, 6 open-ended bands, 5 fills on climate day 10-06 (LAX 1, MDW 2, SFO 2), and two wins
(MIA 10-03 ``gte86lt87`` tmax 87 and MIA 10-05 ``gte89lt90`` tmax 90, the inclusive upper edge).
Per-fill cost plus fee sums to 4.17, so the net is exactly 2 - 4.17 = -2.17.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import subprocess
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from breezy.analysis.labeling.fill_source import FillRead
from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from tests.support.aut2_fixtures import DurableFillRecord, durable_fill

__all__ = [
    "FQ_TMAX",
    "SEP_TMAX",
    "fill_read",
    "fq_durable_fills",
    "fq_instrument_ids",
    "fq_out_of_scope_fill",
    "fq_september_fills",
    "fq_settlement_records",
    "fq_station_days_per_fill",
    "git_cmd",
    "log_filled",
    "log_init",
    "log_refuse",
    "log_take",
    "nws_record",
    "sha256_text",
    "tmp_git_repo",
]

_VENUE = "POLYMARKET_US"
_RAW_SHA = "a" * 64


def _d(day: int) -> dt.date:
    return dt.date(2026, 10, day)


#: (CLI station, climate day) -> bands bought (the venue slug tail, before the trailing ``f``).
_RUNGS: dict[tuple[str, dt.date], list[str]] = {
    ("LAX", _d(2)): ["lt70", "gte100"],
    ("LAX", _d(3)): ["gte80lt81", "gte82lt83"],
    ("LAX", _d(4)): ["lt60"],
    ("LAX", _d(5)): ["gte86lt87", "gte88lt89"],
    ("LAX", _d(6)): ["gte90lt91"],
    ("MDW", _d(2)): ["gte60lt61", "gte62lt63"],
    ("MDW", _d(4)): ["lt50", "gte64lt65"],
    ("MDW", _d(5)): ["gte66lt67", "gte68lt69"],
    ("MDW", _d(6)): ["gte70lt71", "gte72lt73"],
    ("MIA", _d(3)): ["gte86lt87", "gte84lt85"],
    ("MIA", _d(5)): ["gte89lt90", "gte91lt92"],
    ("SFO", _d(3)): ["gte72lt73", "gte74lt75"],
    ("SFO", _d(4)): ["gte105"],
    ("SFO", _d(6)): ["gte78lt79", "gte110"],
}

#: The settled high per station-day; only the two MIA days contain a bought band.
FQ_TMAX: Mapping[tuple[str, dt.date], int] = {
    **{key: 95 for key in _RUNGS if key[0] == "LAX"},
    **{key: 80 for key in _RUNGS if key[0] == "MDW"},
    **{key: 85 for key in _RUNGS if key[0] == "SFO"},
    ("MIA", _d(3)): 87,
    ("MIA", _d(5)): 90,
}


_SEP_RUNGS: dict[tuple[str, dt.date], list[str]] = {
    ("LAX", dt.date(2026, 9, 9)): ["gte80lt81", "gte82lt83", "gte84lt85", "gte86lt87", "gte88lt89"],
    ("SFO", dt.date(2026, 9, 9)): ["gte70lt71", "gte72lt73", "gte74lt75", "gte76lt77"],
}
#: September CRH fills: two wins ([80,81] holds 80; [70,71] holds 70), net 2 - 2.46 = -0.46.
SEP_TMAX: Mapping[tuple[str, dt.date], int] = {
    ("LAX", dt.date(2026, 9, 9)): 80,
    ("SFO", dt.date(2026, 9, 9)): 70,
}
_OCT_TS = int(dt.datetime(2026, 10, 2, 17, tzinfo=dt.UTC).timestamp()) * 10**9
_SEP_TS = int(dt.datetime(2026, 9, 9, 17, tzinfo=dt.UTC).timestamp()) * 10**9


def fq_station_days_per_fill() -> list[tuple[str, dt.date]]:
    """One ``(station, climate_day)`` per fill, in fixture order (25 entries)."""
    return [key for key, bands in _RUNGS.items() for _ in bands]


def fq_instrument_ids() -> list[str]:
    ids = []
    for (station, day), bands in _RUNGS.items():
        for band in bands:
            ids.append(f"tc-temp-{station.lower()}high-{day.isoformat()}-{band}f.{_VENUE}")
    return ids


def fq_durable_fills() -> list[DurableFillRecord]:
    """25 real ``DurableFillRecord`` s: 24 at 0.167 all-in, the last at 0.162 (sum 4.170)."""
    ids = fq_instrument_ids()
    fills = []
    for index, instrument_id in enumerate(ids):
        last = index == len(ids) - 1
        fills.append(
            durable_fill(
                venue_order_id=f"vo-{index}",
                client_order_id=f"O-{index}",
                trade_id=f"T-{index}",
                instrument_id=instrument_id,
                cost=Decimal("0.14") if last else Decimal("0.15"),
                fee=Decimal("0.022") if last else Decimal("0.017"),
                ts_event=_OCT_TS + index * 10_000_000_000,
            )
        )
    return fills


def fq_september_fills() -> list[DurableFillRecord]:
    """Nine September fills (all-in 0.27 each but the last at 0.30), the non-FQ remainder of 34."""
    ids = [
        f"tc-temp-{st.lower()}high-{day.isoformat()}-{band}f.{_VENUE}"
        for (st, day), bands in _SEP_RUNGS.items()
        for band in bands
    ]
    return [
        durable_fill(
            venue_order_id=f"sep-{i}",
            client_order_id=f"O-sep-{i}",
            trade_id=f"T-sep-{i}",
            instrument_id=instrument_id,
            cost=Decimal("0.27") if i == len(ids) - 1 else Decimal("0.25"),
            fee=Decimal("0.03") if i == len(ids) - 1 else Decimal("0.02"),
            ts_event=_SEP_TS + i * 10_000_000_000,
        )
        for i, instrument_id in enumerate(ids)
    ]


def fq_settlement_records() -> list[NwsClimateDay]:
    """One final record per fixture station-day (October and September)."""
    days = {**FQ_TMAX, **SEP_TMAX}
    return [nws_record(st, day, tmax) for (st, day), tmax in days.items()]


def nws_record(station: str, climate_day: dt.date, tmax_f: int, **overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": station,
        "climate_day": climate_day,
        "tmax_f": tmax_f,
        "tmin_f": tmax_f - 20,
        "tavg_f": tmax_f - 10,
        "tavg_flag": None,
        "tmax_flag": None,
        "tmin_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KXXX",
        "issuance_time_ns": 1_791_000_000_000_000_000,
        "retrieved_at_ns": 1_791_000_001_000_000_000,
        "parser_version": "test",
        "registry_version": "test",
        "raw_sha256": _RAW_SHA,
        "source_channel": "iem_afos_forecast",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": 1_791_000_000_000_000_000,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


_BASE = dt.datetime(2026, 10, 2, 16, 2, 5, tzinfo=dt.UTC)
_BRAND = "BREEZY-L001.FORECAST-QUANTILE-LADDER"


def _stamp(offset_s: float) -> str:
    moment = _BASE + dt.timedelta(seconds=offset_s)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond:06d}000Z"


def _ns(offset_s: float) -> int:
    delta = _BASE + dt.timedelta(seconds=offset_s) - dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
    return (delta.days * 86400 + delta.seconds) * 10**9 + delta.microseconds * 1000


def log_take(
    offset_s: float, instrument_id: str, *, station: str = "LAX", rung_id: str = "89_90"
) -> str:
    return (
        f"{_stamp(offset_s)} [INFO] {_BRAND}: SHADOW_DECISION {{'now_ns': {_ns(offset_s)}, "
        f"'station': '{station}', 'climate_day': datetime.date(2026, 10, 2), "
        f"'rung_id': '{rung_id}', 'side': 'yes', 'instrument_id': '{instrument_id}', "
        f"'kind': 'Take', 'qty': 1, 'ev_net': 0.09, 'p_hat': 0.38, 'p_lower': 0.34, "
        f"'p_upper': 0.42}}"
    )


def log_refuse(offset_s: float, instrument_id: str, *, station: str, rung_id: str) -> str:
    return (
        f"{_stamp(offset_s)} [INFO] {_BRAND}: SHADOW_DECISION {{'now_ns': {_ns(offset_s)}, "
        f"'station': '{station}', 'climate_day': datetime.date(2026, 10, 2), "
        f"'rung_id': '{rung_id}', 'side': 'yes', 'instrument_id': '{instrument_id}', "
        f"'kind': 'Refuse', 'reason': 'NoEdge'}}"
    )


def log_init(offset_s: float, client_order_id: str, instrument_id: str) -> str:
    return (
        f"{_stamp(offset_s)} [INFO] {_BRAND}: <--[EVT] OrderInitialized("
        f"instrument_id={instrument_id}, client_order_id={client_order_id}, side=BUY, "
        f"type=LIMIT, quantity=1.00, time_in_force=IOC)"
    )


def log_filled(offset_s: float, client_order_id: str, trade_id: str, instrument_id: str) -> str:
    return (
        f"{_stamp(offset_s)} [INFO] {_BRAND}: <--[EVT] OrderFilled("
        f"instrument_id={instrument_id}, client_order_id={client_order_id}, venue_order_id=V1, "
        f"account_id=A, trade_id={trade_id}, order_side=BUY, last_qty=1.00, last_px=0.40 USD)"
    )


def fill_read(fills: Sequence[DurableFillRecord]) -> FillRead:
    """A clean ``FillRead``, shaped like ``read_durable_fills(...).require_clean()``."""
    return FillRead(fills=tuple(fills), n_keys=len(fills), n_undecodable=0)


def fq_out_of_scope_fill() -> DurableFillRecord:
    """A LAX fill on climate day 10-07, past the 10-06 clip: it would win if it were scored."""
    return durable_fill(
        venue_order_id="oos-1",
        client_order_id="O-oos-1",
        trade_id="T-oos-1",
        instrument_id=f"tc-temp-laxhigh-2026-10-07-gte90lt91f.{_VENUE}",
        ts_event=_OCT_TS + 900_000_000_000,
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def git_cmd(root: Path, *args: str, date: str | None = None) -> str:
    """Run git hermetically in ``root`` (no global config, fixed identity, optional commit date)."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    if date is not None:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = date
    ident = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    done = subprocess.run(
        ["git", *ident, *args], cwd=root, env=env, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def tmp_git_repo(
    root: Path, versions: Sequence[str], dates: Sequence[str | None] | None = None
) -> list[str]:
    """A hermetic repo: ``manifest.json`` takes each content in turn; ``extra.py`` and
    ``other.txt`` are tracked from the first commit. Returns the commit shas."""
    root.mkdir(parents=True, exist_ok=True)
    git_cmd(root, "init", "-q", "-b", "main")
    (root / "extra.py").write_text("x = 1\n")
    (root / "other.txt").write_text("o\n")
    commits = []
    for index, content in enumerate(versions):
        (root / "manifest.json").write_text(content)
        git_cmd(root, "add", "manifest.json", "extra.py", "other.txt")
        date = dates[index] if dates else None
        git_cmd(root, "commit", "-q", "-m", f"v{index}", date=date)
        commits.append(git_cmd(root, "rev-parse", "HEAD"))
    return commits
