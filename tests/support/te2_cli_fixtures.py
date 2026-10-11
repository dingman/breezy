"""Synthetic world for the TE-2 Phase A CLI tests (plan S0-D, S0-G, S0-H). Offline.

Builds, under one tmp dir: the 34-fill durable store, nine boot logs (Take / OrderInitialized /
OrderFilled / Refuse / NBM_NBP_PUBLISHED lines), a derived NBP store written by the REAL
``write_partition``, a tmp git repo holding the real calibration artefact, and a reflog snapshot
that pins every boot to that repo's commit. The logged p-hat of each fill is computed by an
independent path (``load_live_calibration`` plus the bounds provider on a complement ladder),
never by the reconstruction module under test.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.persistence.nbp_derived_store import DerivedNbpRow, partition_path, write_partition
from breezy.strategy.forecast_quantile_ladder.artefact_bounds import ArtefactBoundsProvider
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import load_live_calibration
from breezy.strategy.ladder_ev.quantile_density import Percentiles, Rung
from tests.support.aut2_fixtures import seed_fills
from tests.support.te2_fixtures import (
    fq_durable_fills,
    fq_september_fills,
    fq_station_days_per_fill,
    git_cmd,
)

REPO = Path(__file__).resolve().parents[2]
ARTEFACT_REL = "deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json"
MANIFEST_REL = "deploy/families/pm_us_crh_fq_v1.json"
REAL_ARTEFACT = REPO / ARTEFACT_REL
ICAO = {"LAX": "KLAX", "MDW": "KMDW", "MIA": "KMIA", "SFO": "KSFO"}
OFFSET = {"LAX": -8.0, "MDW": -6.0, "MIA": -5.0, "SFO": -8.0}
LATITUDE = {"LAX": 33.93806, "MDW": 41.78417, "MIA": 25.79056, "SFO": 37.61961}
BOOT_STAMPS = (
    "20261001T151202", "20261001T160158", "20261001T165011", "20261002T165039",
    "20261002T200526", "20261002T205521", "20261003T165045", "20261004T165012",
    "20261005T165040",
)  # fmt: skip
VARIABLES = ("TXN_Q10", "TXN_Q25", "TXN_Q50", "TXN_Q75", "TXN_Q90", "TXN_MEAN", "TXN_SD")
_BRAND = "BREEZY-L001.FORECAST-QUANTILE-LADDER"
_HOUR_NS = 3600 * 10**9
_PERTURB_F = 1.5


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(ns: int) -> str:
    moment = dt.datetime.fromtimestamp(ns // 10**9, tz=dt.UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ns % 10**9:09d}Z"


def utc_ns(day: dt.date, hour: float) -> int:
    base = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)
    return int(base.timestamp()) * 10**9 + int(hour * _HOUR_NS)


def vector_values(station: str, day: dt.date, shift: float = 0.0) -> dict[str, float]:
    q50 = 70.0 + 3 * list(ICAO).index(station) + day.day + shift
    return {
        "TXN_Q10": q50 - 6, "TXN_Q25": q50 - 3, "TXN_Q50": q50, "TXN_Q75": q50 + 3,
        "TXN_Q90": q50 + 6, "TXN_MEAN": q50, "TXN_SD": 4.0,
    }  # fmt: skip


def expected_p_hat(station: str, day: dt.date, instrument_id: str, shift: float = 0.0) -> float:
    """The independent expectation: real artefact, v5.0 draws, a complement ladder."""
    facts = bucket_facts_from_instrument_id(instrument_id)
    assert facts is not None
    calibration = load_live_calibration(
        str(REAL_ARTEFACT), expected_sha256=sha256_file(REAL_ARTEFACT)
    )
    values = vector_values(station, day, shift)
    percentiles = Percentiles(
        q10=values["TXN_Q10"], q25=values["TXN_Q25"], q50=values["TXN_Q50"],
        q75=values["TXN_Q75"], q90=values["TXN_Q90"], mean=values["TXN_MEAN"], sd=values["TXN_SD"],
    )  # fmt: skip
    lo, hi = facts.lower_f, facts.upper_f
    rungs = [Rung("target", lo, hi)]
    if lo is not None:
        rungs.append(Rung("below", None, lo - 1))
    if hi is not None:
        rungs.append(Rung("above", hi + 1, None))
    resolved = calibration.resolve("v5.0", latitude_deg=LATITUDE[station], climate_day=day)
    bounds = ArtefactBoundsProvider(cdf_method=calibration.cdf_method)(
        percentiles=percentiles, draws=resolved.draws, ladder=rungs, rung_id="target"
    )
    return bounds.p_hat


@dataclass(frozen=True)
class FillCase:
    station: str
    climate_day: dt.date
    instrument_id: str
    decision_ns: int
    p_hat: float
    boot_number: int


@dataclass(frozen=True)
class World:
    root: Path
    fills_db: Path
    logs: tuple[Path, ...]
    data_root: Path
    snapshot: Path
    snapshot_sha256: str
    repo_root: Path
    derived_root: Path
    archive_root: Path
    commit: str
    first_commit: str
    cases: tuple[FillCase, ...]
    cycle_ns_by_day: dict[dt.date, int]

    def phase_a_argv(self, out: Path, *, extra: Sequence[str] = ()) -> list[str]:
        return [
            "phase-a", "--fills-db", str(self.fills_db), "--output-dir", str(out),
            "--repo-root", str(self.repo_root), "--logs", *map(str, self.logs),
            "--data-root", str(self.data_root), "--reflog-snapshot", str(self.snapshot),
            "--reflog-snapshot-sha256", self.snapshot_sha256,
            "--derived-store", str(self.derived_root), "--archive-root", str(self.archive_root),
            *extra,
        ]  # fmt: skip


def _boot_number(decision_ns: int) -> int:
    times = [
        int(dt.datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=dt.UTC).timestamp()) * 10**9
        for s in BOOT_STAMPS
    ]
    return max(i + 1 for i, t in enumerate(times) if t <= decision_ns)


def _rung_id(instrument_id: str) -> str:
    facts = bucket_facts_from_instrument_id(instrument_id)
    assert facts is not None
    lo = facts.lower_f if facts.lower_f is not None else "lt"
    hi = facts.upper_f if facts.upper_f is not None else "gte"
    return f"{lo}_{hi}"


def _take_line(case: FillCase) -> str:
    day = case.climate_day
    return (
        f"{stamp(case.decision_ns)} [INFO] {_BRAND}: SHADOW_DECISION {{'now_ns': "
        f"{case.decision_ns}, 'station': '{case.station}', 'climate_day': "
        f"datetime.date({day.year}, {day.month}, {day.day}), 'rung_id': "
        f"'{_rung_id(case.instrument_id)}', 'side': 'yes', 'instrument_id': "
        f"'{case.instrument_id}', 'kind': 'Take', 'qty': 1, 'ev_net': 0.09, "
        f"'p_hat': {case.p_hat!r}, 'p_lower': 0.1, 'p_upper': 0.5}}"
    )


def _refuse_line(station: str, day: dt.date, rung_id: str, ns: int) -> str:
    return (
        f"{stamp(ns)} [INFO] {_BRAND}: SHADOW_DECISION {{'now_ns': {ns}, 'station': '{station}', "
        f"'climate_day': datetime.date({day.year}, {day.month}, {day.day}), 'rung_id': "
        f"'{rung_id}', 'side': 'yes', 'instrument_id': 'x', 'kind': 'Refuse', "
        f"'reason': 'below_margin'}}"
    )


def _order_lines(case: FillCase, client: str, trade: str) -> list[tuple[int, str]]:
    iid = case.instrument_id
    init = (
        f"{stamp(case.decision_ns + 10**9)} [INFO] {_BRAND}: <--[EVT] OrderInitialized("
        f"instrument_id={iid}, client_order_id={client}, side=BUY, type=LIMIT, "
        "quantity=1.00, time_in_force=IOC)"
    )
    filled = (
        f"{stamp(case.decision_ns + 2 * 10**9)} [INFO] {_BRAND}: <--[EVT] OrderFilled("
        f"instrument_id={iid}, client_order_id={client}, venue_order_id=V1, account_id=A, "
        f"trade_id={trade}, order_side=BUY, last_qty=1.00, last_px=0.40 USD)"
    )
    return [(case.decision_ns + 10**9, init), (case.decision_ns + 2 * 10**9, filled)]


def _derived_rows(
    day: dt.date, cycle_ns: int, visible_ns: int, shifts: dict[str, float]
) -> list[DerivedNbpRow]:
    rows = []
    sha = hashlib.sha256(f"bulletin-{day}".encode()).hexdigest()
    for station, icao in ICAO.items():
        for offset_days, bump in ((0, 0.0), (1, 20.0)):  # D+1 window first, a later D+2 window
            end_day = day + dt.timedelta(days=offset_days)
            valid_end = utc_ns(end_day, 12.0 - OFFSET[station])
            values = vector_values(station, day, shifts.get(station, 0.0) + bump)
            for variable in VARIABLES:
                rows.append(
                    DerivedNbpRow(
                        station=icao, variable=variable, cycle_runtime_ns=cycle_ns,
                        valid_start_ns=valid_end - 12 * _HOUR_NS + offset_days,
                        valid_end_ns=valid_end, value_f=values[variable], absence_reason=None,
                        header_model_version="5.0", nbm_version_era="v5.0",
                        version_break_mismatch=False, available_at_ns=visible_ns - 60 * 10**9,
                        last_modified=None, source_host="s3.example", raw_sha256=sha,
                        fetched_at_ns=visible_ns + 10**9,
                    )
                )  # fmt: skip
    return rows


def _init_repo(root: Path) -> tuple[str, str]:
    root.mkdir(parents=True)
    git_cmd(root, "init", "-q", "-b", "main")
    (root / "README").write_text("r\n")
    git_cmd(root, "add", "README")
    git_cmd(root, "commit", "-q", "-m", "c0")
    first = git_cmd(root, "rev-parse", "HEAD")
    (root / ARTEFACT_REL).parent.mkdir(parents=True)
    (root / ARTEFACT_REL).write_bytes(REAL_ARTEFACT.read_bytes())
    manifest = {
        "family_id": "pm_us_crh_fq_v1", "density_artefact_path": ARTEFACT_REL,
        "density_artefact_sha256": sha256_file(REAL_ARTEFACT), "taker_fee_coefficient": "0.0695",
    }  # fmt: skip
    (root / MANIFEST_REL).write_text(json.dumps(manifest, indent=2) + "\n")
    git_cmd(root, "add", MANIFEST_REL, ARTEFACT_REL)
    git_cmd(root, "commit", "-q", "-m", "c1")
    return first, git_cmd(root, "rev-parse", "HEAD")


def build_world(
    tmp: Path,
    *,
    perturb: Sequence[tuple[str, dt.date]] = (),
    drop_cycle: dt.date | None = None,
    reissue: dt.date | None = None,
) -> World:
    first, commit = _init_repo(tmp / "repo")
    repo = tmp / "repo"
    snapshot_body = f"2026-09-30T00:00:00+00:00 old={'0' * 12} new={commit} commit: c1\n"
    snapshot_text = (
        f"# Captured\n# source: .git/logs/HEAD\n{snapshot_body}"
        f"# source: .git/logs/refs/heads/main\n{snapshot_body}"
    )
    snapshot = tmp / "reflog.txt"
    snapshot.write_text(snapshot_text)
    fills = fq_durable_fills()
    keys = fq_station_days_per_fill()
    cases: list[FillCase] = []
    for fill, (station, day) in zip(fills, keys, strict=True):
        decision_ns = utc_ns(day - dt.timedelta(days=1), 18.0)
        cases.append(
            FillCase(station, day, fill.instrument_id, decision_ns,
                     expected_p_hat(station, day, fill.instrument_id),
                     _boot_number(decision_ns))
        )  # fmt: skip
    store = tmp / "exec.db"
    seed_fills(store, [*fills, *fq_september_fills()])
    boot_times = [
        int(dt.datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=dt.UTC).timestamp()) * 10**9
        for s in BOOT_STAMPS
    ]
    lines: list[list[tuple[int, str]]] = [[] for _ in BOOT_STAMPS]

    def emit(ns: int, text: str) -> None:
        lines[max(i for i, t in enumerate(boot_times) if t <= ns)].append((ns, text))

    for case, fill in zip(cases, fills, strict=True):
        emit(case.decision_ns, _take_line(case))
        for ns, text in _order_lines(case, fill.client_order_id, str(fill.trade_id)):
            emit(ns, text)
    first_day = cases[0].climate_day
    refuse_ns = utc_ns(first_day - dt.timedelta(days=1), 17.5)
    emit(refuse_ns, _refuse_line("LAX", first_day, "70_99", refuse_ns))
    derived = tmp / "derived"
    cycle_ns_by_day: dict[dt.date, int] = {}
    for day in sorted({c.climate_day for c in cases}):
        cycle_ns = utc_ns(day - dt.timedelta(days=1), 13.0)
        visible_ns = utc_ns(day - dt.timedelta(days=1), 17.0)
        cycle_ns_by_day[day] = cycle_ns
        emit(visible_ns,
             f"{stamp(visible_ns)} [INFO] nbm_quantile_actor: NBM_NBP_PUBLISHED "
             f"cycle_ns={cycle_ns} stations=4 points=56 model_version=5.0")  # fmt: skip
        if day == drop_cycle:
            continue
        shift = {s: _PERTURB_F for s, d in perturb if d == day}
        if day == reissue:
            shift = dict.fromkeys(ICAO, _PERTURB_F)
        rows = _derived_rows(day, cycle_ns, visible_ns, shift)
        if day == reissue:  # the re-fetched Last-Modified is after the live publication
            rows = [_reissued(r, visible_ns) for r in rows]
        cycle_date = dt.datetime.fromtimestamp(cycle_ns // 10**9, tz=dt.UTC).date()
        write_partition(rows, partition_path(derived, cycle_date, 13))
    manifest_sha = sha256_file(repo / MANIFEST_REL)
    artefact_sha = sha256_file(REAL_ARTEFACT)
    logs = []
    for index, boot in enumerate(BOOT_STAMPS):
        path = tmp / f"breezy-trade-{boot}Z.log"
        header = (
            f"{stamp(boot_times[index])} [INFO] boot: manifest_sha256={manifest_sha} "
            f"calibration_sha256={artefact_sha}"
        )
        body = [text for _ns, text in sorted(lines[index])]
        path.write_text("\n".join([header, *body]) + "\n")
        logs.append(path)
    data_root = tmp / "data_root"
    data_root.mkdir()
    archive = tmp / "us_source_archive"
    (archive / "metar-routine" / "KLAX").mkdir(parents=True)
    (archive / "metar-routine" / "KLAX" / "2026.csv").write_text(
        "station,valid_utc,tmpf,tgroup_c,report_type,tmpf_source,metar\n"
        "KLAX,2026-06-30T23:53Z,68,20.0,3,tgroup,KLAX 302353Z\n"
    )
    return World(
        root=tmp, fills_db=store, logs=tuple(logs), data_root=data_root, snapshot=snapshot,
        snapshot_sha256=hashlib.sha256(snapshot_text.encode()).hexdigest(), repo_root=repo,
        derived_root=derived, archive_root=archive, commit=commit, first_commit=first,
        cases=tuple(cases), cycle_ns_by_day=cycle_ns_by_day,
    )  # fmt: skip


def _reissued(row: DerivedNbpRow, visible_ns: int) -> DerivedNbpRow:
    values = {f: getattr(row, f) for f in DerivedNbpRow.__dataclass_fields__}
    values["available_at_ns"] = visible_ns + 3600 * 10**9
    return DerivedNbpRow(**values)
