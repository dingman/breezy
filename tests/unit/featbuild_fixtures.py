"""Synthetic stores for the F13 Phase A feature-build tests, via the PRODUCTION writers (L-42).

Nothing here touches the live data root or the network. Every store is created under a pytest
``tmp_path`` through the same writer the real archive uses (``ArchiveCache``,
``UsSourceRevisionStore``, ``lamp_archive_runs.Manifest``, ``nbp_derived_store.write_partition``,
``settlement_truth_dataset.rows_to_table``).
"""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import pyarrow.parquet as pq

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "scripts" / "analysis")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from settlement_truth_dataset import (  # type: ignore[import-not-found]
    STATUS_FINAL,
    SettlementTruthRow,
    rows_to_table,
)

from breezy.persistence.archive_cache import ArchiveCache, ArchiveRequest, iem_asos_1min_request
from breezy.persistence.nbp_derived_store import DerivedNbpRow, partition_path, write_partition
from breezy.persistence.us_source_request import (
    US_LAMP_MDL_SOURCE,
    US_LAV_IEM_SOURCE,
    US_PFM_AFOS_SOURCE,
)
from breezy.persistence.us_source_revision_store import UsSourceRevisionStore
from scripts.archive.lamp_archive_runs import LampRun, Manifest, availability_row

NS = 10**9
HOUR_NS = 3_600 * NS
UTC = dt.UTC


class FixedClock:
    def __init__(self, now_ns: int = 1_900_000_000 * NS) -> None:
        self._now = now_ns

    def timestamp_ns(self) -> int:
        return self._now


def ns(when: dt.datetime) -> int:
    return int(when.timestamp()) * NS


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> dt.datetime:
    return dt.datetime(year, month, day, hour, minute, tzinfo=UTC)


# ------------------------------------------------------------------ ArchiveCache stores


def write_cache_entry(root: Path, request: ArchiveRequest, payload: bytes) -> None:
    """The production write path of every ``ArchiveCache`` source (ASOS 1-min, IEM MOS)."""
    ArchiveCache(root, fetch=lambda _r: payload, clock=FixedClock()).get_or_fetch(request)


def asos_1min_payload(rows: Iterable[tuple[dt.datetime, int | str]], station: str = "MIA") -> bytes:
    """``station,station_name,valid(UTC),tmpf,dwpf`` exactly as the real 1-min archive prints it."""
    lines = ["station,station_name,valid(UTC),tmpf,dwpf"]
    for when, tmpf in rows:
        lines.append(f"{station},TEST AIRPORT,{when:%Y-%m-%d %H:%M},{tmpf},50")
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_asos_year(root: Path, icao: str, year: int, payload: bytes) -> None:
    write_cache_entry(root, iem_asos_1min_request(icao, year), payload)


# ------------------------------------------------------------------ NBP derived store

TXN_VARIABLES = ("TXN_MEAN", "TXN_SD", "TXN_Q10", "TXN_Q25", "TXN_Q50", "TXN_Q75", "TXN_Q90")


def nbp_window_rows(
    *,
    station: str,
    cycle_runtime_ns: int,
    valid_ns: int,
    q50: float,
    available_at_ns: int,
    sd: float = 3.0,
    era: str = "v4.2",
) -> list[DerivedNbpRow]:
    values = {
        "TXN_MEAN": q50,
        "TXN_SD": sd,
        "TXN_Q10": q50 - 4.0,
        "TXN_Q25": q50 - 2.0,
        "TXN_Q50": q50,
        "TXN_Q75": q50 + 2.0,
        "TXN_Q90": q50 + 4.0,
    }
    return [
        DerivedNbpRow(
            station=station,
            variable=variable,
            cycle_runtime_ns=cycle_runtime_ns,
            valid_start_ns=valid_ns,
            valid_end_ns=valid_ns,
            value_f=value,
            absence_reason=None,
            header_model_version=era.lstrip("v"),
            nbm_version_era=era,
            version_break_mismatch=False,
            available_at_ns=available_at_ns,
            last_modified=None,
            source_host="test",
            raw_sha256="0" * 64,
            fetched_at_ns=available_at_ns,
        )
        for variable, value in values.items()
    ]


def write_nbp_cycle(
    root: Path,
    *,
    station: str,
    cycle_day: dt.date,
    cycle_hour: int,
    q50: float,
    available_after_ns: int = 2 * HOUR_NS,
    era: str = "v4.2",
) -> int:
    """Write one (day, cycle) partition whose window targets the cycle's explicit D+1.

    Returns the cycle runtime in ns. The valid 00Z column follows the real grid: 13Z/19Z cycles
    reach D+1 through the 00Z of day+2; the 01Z cycle through the 00Z of day+1.
    """
    cycle_ns = ns(utc(cycle_day.year, cycle_day.month, cycle_day.day, cycle_hour))
    valid_day = cycle_day + dt.timedelta(days=1 if cycle_hour == 1 else 2)
    valid_ns = ns(utc(valid_day.year, valid_day.month, valid_day.day))
    rows = nbp_window_rows(
        station=station,
        cycle_runtime_ns=cycle_ns,
        valid_ns=valid_ns,
        q50=q50,
        available_at_ns=cycle_ns + available_after_ns,
        era=era,
    )
    write_partition(rows, partition_path(root, cycle_day, cycle_hour))
    return cycle_ns


# ------------------------------------------------------------------ settlement truth


def truth_row(*, station: str, climate_day: dt.date, tmax_f: int) -> SettlementTruthRow:
    return SettlementTruthRow(
        station=station,
        city=station,
        climate_day=climate_day,
        status=STATUS_FINAL,
        is_final=True,
        tmax_f=tmax_f,
        tmin_f=None,
        tavg_f=None,
        tmax_flag=None,
        had_correction=False,
        preliminary_tmax_f=None,
        preliminary_differed=None,
        preliminary_delta_f=None,
        total_issuance_count=1,
        final_issuance_count=1,
        final_tmax_revised=False,
        final_is_correction_bbb=False,
        correction_text_evidence=False,
        revision_seq=1,
        wmo_transmission_sequence=None,
        wmo_bbb=None,
        product_id=None,
        raw_sha256=None,
        issued_at_utc=None,
        source_zip=None,
        source_member=None,
        within_expected_window=True,
        interior_bucket_lower_even_f=None,
        interior_bucket_upper_even_f=None,
        interior_bucket_slug_even=None,
        interior_bucket_lower_odd_f=None,
        interior_bucket_upper_odd_f=None,
        interior_bucket_slug_odd=None,
        settlement_grade_within_window=True,
        settlement_grade_including_spillover=True,
    )


def write_truth(path: Path, rows: Sequence[SettlementTruthRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(rows_to_table(list(rows)), path)
    return path


# ------------------------------------------------------------------ US-source revision store


def lamp_block_text(station: str, run_at: dt.datetime, temps: Sequence[int | None]) -> str:
    """One closed-set station block in the archive layout (``UTC`` and ``TMP`` rows)."""
    first = run_at.replace(minute=0) + dt.timedelta(hours=1)
    utc_row = "".join(f" {(first + dt.timedelta(hours=i)).hour:02d}" for i in range(len(temps)))
    tmp_row = "".join("999" if t is None else f"{t:3d}" for t in temps)
    header = (
        f" {station}   GFS LAMP GUIDANCE   {run_at.month}/{run_at.day:02d}/{run_at.year}  "
        f"{run_at:%H%M} UTC"
    )
    return f"{header}\n UTC {utc_row}\n TMP {tmp_row}\n\n"


def write_mdl_run(
    root: Path,
    *,
    run_at: dt.datetime,
    temps_by_station: Mapping[str, Sequence[int | None]],
    sealed_in_manifest: bool | None = None,
    manifest_available_at_ns: int | None = None,
) -> None:
    """One ``us-lamp-mdl`` run through ``UsSourceRevisionStore`` plus its availability row."""
    blocks = {s: lamp_block_text(s, run_at, t) for s, t in temps_by_station.items()}
    payload = LampRun(run_at=run_at, blocks=blocks).payload()
    store = UsSourceRevisionStore(root, FixedClock())
    result = store.append_if_new(
        source=US_LAMP_MDL_SOURCE,
        station="ALL",
        run_ts_ns=ns(run_at),
        model=None,
        payload=payload,
    )
    row = availability_row(
        source=US_LAMP_MDL_SOURCE,
        station="ALL",
        run_at=run_at,
        sha256=result.sha256,
        revision=result.revision,
        leg="test",
        origin="test",
    )
    if sealed_in_manifest is not None:
        row["holdout_sealed"] = sealed_in_manifest
    if manifest_available_at_ns is not None:
        row["available_at_ns"] = manifest_available_at_ns
    Manifest(root, US_LAMP_MDL_SOURCE).record(row)


LAV_HEADER = (
    "runtime,ftime,model,n_x,tmp,dpt,cld,wdr,wsp,p06,p12,q06,q12,t06_1,t06_2,t12_1,t12_2,cig,vis,"
    "obv,station,t06,t12"
)


def lav_csv(station: str, run_at: dt.datetime, temps: Sequence[int | None]) -> bytes:
    """An IEM ``mos.py?model=LAV`` CSV in the real column layout: one row per forecast hour."""
    lines = [LAV_HEADER]
    for index, temp in enumerate(temps, start=1):
        ftime = run_at + dt.timedelta(hours=index)
        tmp = "" if temp is None else str(temp)
        lines.append(
            f"{run_at:%Y-%m-%d %H:%M:%S},{ftime:%Y-%m-%d %H:%M:%S},LAV,,{tmp},50,OV,200,4,,,,,,,,"
            f",8,7,N ,{station},,"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_lav_run(root: Path, *, station: str, run_at: dt.datetime, payload: bytes) -> None:
    store = UsSourceRevisionStore(root, FixedClock())
    result = store.append_if_new(
        source=US_LAV_IEM_SOURCE,
        station=station,
        run_ts_ns=ns(run_at),
        model="LAV",
        payload=payload,
    )
    Manifest(root, US_LAV_IEM_SOURCE).record(
        availability_row(
            source=US_LAV_IEM_SOURCE,
            station=station,
            run_at=run_at,
            sha256=result.sha256,
            revision=result.revision,
            leg="test",
            origin="test",
        )
    )


def write_pfm_product(
    root: Path,
    *,
    station: str,
    wfo: str,
    issued: dt.datetime,
    text: str,
    revision_texts: Sequence[str] = (),
    clock_steps_ns: Sequence[int] = (),
) -> None:
    """A PFM product, then any later revisions of it (each a different payload), first-seen first.

    ``clock_steps_ns[i]`` offsets the store clock of the i-th body (default 0): a negative step
    makes a later revision look FETCHED earlier than the first one.
    """
    for index, body in enumerate((text, *revision_texts)):
        step = clock_steps_ns[index] if index < len(clock_steps_ns) else 0
        UsSourceRevisionStore(root, FixedClock(1_900_000_000 * NS + step)).append_if_new(
            source=US_PFM_AFOS_SOURCE,
            station=station,
            run_ts_ns=ns(issued),
            model=wfo,
            payload=body.encode("utf-8"),
        )
