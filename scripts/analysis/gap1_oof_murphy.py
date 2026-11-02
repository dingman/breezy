"""GAP-1 S1/S2: offline OOF Murphy reader; never fit, fetch, or open a catalog.

Conservative conventions where the freeze specifies no wire format: no overall
PASS/KILL without D1. D1 is absent
unless d1.json records granted=true and this prereg's frozen_sha. Successor evidence
is successor_evidence.json (schema gap1_successor_evidence_v1), with an infra_journal
relative path and primary/successor snapshots of prereg_sha256, code_sha, c1_sha256,
and feature_sha256 (primary/lag).

Run-time provenance: each run records prereg_sha256, c1_sha256 and code_sha when it
starts (--record-provenance RUNDIR -> run_provenance.json, write-once; build.json holds
no code sha). The successor check compares those RECORDED values, never a recomputation
of the current state against itself. Rule: prereg and C1 digests must be equal across
primary, successor and the current prereg/C1; code must be equal or a git ancestor
(primary <= successor <= HEAD); feature digests (primary/lag) are verified against each
run's f.jsonl/fl.jsonl and build.json and must be equal. Missing evidence refuses.
The primary stage_a.json is never opened.
Only upward resource changes are admissible; envelopes in the evidence must contain the
three named limits.

Coarse Murphy bins require W-C for exact Brier reconstruction; report those terms
alongside the unmodified library REL/RES/UNC. Empty or zero-sigma cells cannot PASS.
Counts inspect only the frozen allowlist, deduplicate station-days, and include
missing-source candidates. CLI outputs are exclusive, deterministic JSON. Pure
evaluate/count_cells do not read files or consult HEAD; the writer records HEAD.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import statistics
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Any

from breezy.analysis.brier_decomposition import murphy_decomposition
from breezy.analysis.multisource_blend_features import ARM_NAMES, HORIZONS
from breezy.analysis.multisource_blend_fit import student_t_cdf
from breezy.analysis.multisource_blend_folds import ChampionSpec, ScoredRow, blend_cdf, champion_cdf
from breezy.analysis.multisource_blend_io import scored_row_from_json

# Frozen module __all__ omits these two identical brier_decomposition objects.
from breezy.analysis.nbp_calibration import (  # type: ignore[attr-defined]
    G22_TARGET_DIFFERENCE_X,
    RELIABILITY_BUCKET_EDGES,
    Z_POWER_080,
    bin_by_edges,
    cluster_bootstrap_draws,
    compute_n_min,
    percentile_interval,
    resolution_difference,
)
from breezy.domain.quantile_density import Rung, rung_probabilities

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # Also support python scripts/analysis/gap1_oof_murphy.py.
BINS = bin_by_edges(RELIABILITY_BUCKET_EDGES)
# The frozen prereg carries the cutoff (inclusion.cutoff) but no start date; the start of
# the registered OOF window is therefore the one date constant that stays here.
START_DATE = dt.date(2021, 1, 1)
CUTOFF_PATTERN = re.compile(r"<\s*(\d{4}-\d{2}-\d{2})")
PROVENANCE_FILE = "run_provenance.json"
PROVENANCE_SCHEMA = "gap1_run_provenance_v1"
DEFAULT_PREREG = (
    ROOT / "docs/plans/backlog/GAPS_2026-11-01/gap1_source_resolution/PREREG_GAP1_2026-11-02.json"
)
UNKNOWN = "UNKNOWN"
GIT_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class EventRow:
    station: str
    climate_day: str
    horizon: str
    version: str
    probabilities: Mapping[str, tuple[float, ...]]
    outcomes: tuple[bool, ...]
    fell_back: tuple[str, ...]
    lamp_missing: bool
    lamp_unknown: bool = False


def forecast_centered_ladder(center_f: int) -> tuple[Rung, ...]:
    return (
        Rung("lt", None, center_f - 1),
        Rung("mid", center_f, center_f + 1),
        Rung("gte", center_f + 2, None),
    )


def rung_outcome(rung: Rung, observed_f: float) -> bool:
    return (rung.lo is None or rung.lo <= observed_f) and (rung.hi is None or observed_f <= rung.hi)


def m0t_parameters(spec: ChampionSpec) -> tuple[float, float]:
    if spec.method != "NORMAL":
        raise ValueError("champion.method must be NORMAL")
    p = spec.percentiles
    if p.sd <= 0 or not all(
        math.isfinite(x) for x in (p.sd, p.q50, p.mean, spec.a, spec.gamma, spec.delta)
    ):
        raise ValueError("non-finite champion parameters or non-positive sd")
    try:
        s = math.exp(spec.gamma + spec.delta * math.log(p.sd))
    except OverflowError as exc:
        raise ValueError("non-finite M0t scale") from exc
    m_star = p.q50 + spec.a - s * (p.q50 - p.mean) / p.sd
    if s <= 0 or not all(math.isfinite(x) for x in (m_star, s)):
        raise ValueError("non-positive or non-finite M0t scale/location")
    return m_star, s


def _cutoff(prereg: Mapping[str, Any]) -> dt.date:
    match = CUTOFF_PATTERN.search(str(prereg["inclusion"]["cutoff"]))
    if match is None:
        raise ValueError("prereg inclusion.cutoff has no 'climate_day < YYYY-MM-DD' date")
    return dt.date.fromisoformat(match.group(1))


def _day(value: str, prereg: Mapping[str, Any]) -> str:
    day, cutoff = dt.date.fromisoformat(value), _cutoff(prereg)
    if day >= cutoff or day < START_DATE:
        raise ValueError(f"climate_day outside pre-cutoff {START_DATE}..{cutoff} (exclusive)")
    return day.isoformat()


def _alpha(prereg: Mapping[str, Any]) -> float:
    numerator, _, denominator = str(prereg["ci"]["alpha"]).partition("/")
    return float(numerator) / float(denominator or 1)


def _row_contract(row: ScoredRow, prereg: Mapping[str, Any]) -> None:
    _day(row.climate_day.isoformat(), prereg)
    if row.horizon not in (*HORIZONS, "D0_sensitivity"):
        raise ValueError("unregistered horizon")
    if set(row.arm_predictions) != set(ARM_NAMES):
        raise ValueError("arm key set differs from ARM_NAMES")
    if any(p.nu != prereg["nu"] for p in row.arm_predictions.values()):
        raise ValueError("arm nu differs from prereg nu")
    if not math.isfinite(row.observed_f) or row.observed_f != round(row.observed_f):
        raise ValueError("observed_f must be finite and integral")
    if row.champion is not None:
        m0t_parameters(row.champion)


def _events(row: ScoredRow, missing: bool, unknown: bool, prereg: Mapping[str, Any]) -> EventRow:
    assert row.champion is not None
    m_star, s = m0t_parameters(row.champion)
    ladder = forecast_centered_ladder(round(row.champion.percentiles.q50))
    cdfs = {a: blend_cdf(p) for a, p in row.arm_predictions.items()}
    cdfs.update(M0t=student_t_cdf(m_star, s, prereg["nu"]), M0n=champion_cdf(row.champion))
    probabilities = {a: tuple(rung_probabilities(cdf, ladder).values()) for a, cdf in cdfs.items()}
    return EventRow(
        row.station,
        row.climate_day.isoformat(),
        row.horizon,
        row.version,
        probabilities,
        tuple(rung_outcome(r, row.observed_f) for r in ladder),
        row.fell_back,
        missing,
        unknown,
    )


def _included(
    rows: Iterable[Mapping[str, Any] | ScoredRow], prereg: Mapping[str, Any]
) -> tuple[list[EventRow], dict[str, int]]:
    events, excluded = [], {"champion_none": 0, "fold_id_none": 0}
    seen: set[tuple[str, str, str, str]] = set()
    for raw in rows:
        row = scored_row_from_json(raw) if isinstance(raw, Mapping) else raw
        _row_contract(row, prereg)
        if row.champion is None or row.fold_id is None:
            excluded["champion_none"] += int(row.champion is None)
            excluded["fold_id_none"] += int(row.fold_id is None)
            continue
        key = (row.station, row.climate_day.isoformat(), row.horizon, row.version)
        if key in seen:
            raise ValueError("duplicate OOF row")
        seen.add(key)
        flag = raw["lamp_missing"] if isinstance(raw, Mapping) and "lamp_missing" in raw else False
        unknown = flag == UNKNOWN
        events.append(_events(row, False if unknown else bool(flag), unknown, prereg))
    return sorted(events, key=lambda r: (r.horizon, r.station, r.climate_day, r.version)), excluded


def _flat(rows: Sequence[EventRow], arm: str) -> tuple[list[float], list[bool]]:
    return ([p for r in rows for p in r.probabilities[arm]], [o for r in rows for o in r.outcomes])


def _delta(rows: Sequence[EventRow], arm: str, baseline: str = "M0t") -> float:
    p, o = _flat(rows, arm)
    return resolution_difference(p, _flat(rows, baseline)[0], o, BINS)


def _decompositions(rows: Sequence[EventRow], arm: str) -> dict[str, Any]:
    result = {}
    for name in (arm, "M0t", "M0n", "M0prime"):
        p, o = _flat(rows, name)
        d = murphy_decomposition(p, o, BINS)
        result[name] = {
            "REL": d.reliability,
            "RES": d.resolution,
            "UNC": d.uncertainty,
            "Brier": d.brier,
            "W": d.within_bin_forecast_variance,
            "C": d.within_bin_covariance,
        }
    if len({d["UNC"] for d in result.values()}) != 1:
        raise ValueError("UNC differs across arms in a cell")
    return result


def adjusted_n_min(sigma: float, prereg: Mapping[str, Any]) -> int:
    z_b = float(prereg["power"]["z_b"])
    return math.ceil(((z_b + Z_POWER_080) * sigma / G22_TARGET_DIFFERENCE_X) ** 2)


def _power(rows: Sequence[EventRow], arm: str, prereg: Mapping[str, Any]) -> dict[str, Any]:
    clusters: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        differences = [
            (p - o) ** 2 - (b - o) ** 2
            for p, b, o in zip(
                r.probabilities[arm], r.probabilities["M0t"], r.outcomes, strict=True
            )
        ]
        clusters.setdefault((r.station, r.climate_day), []).extend(differences)
    sigma = statistics.pstdev(statistics.mean(v) for v in clusters.values()) if clusters else 0.0
    return {
        "n": len(clusters),
        "sigma_d": sigma,
        "n_min_adj": adjusted_n_min(sigma, prereg),
        "compute_n_min": compute_n_min(sigma).n_min if sigma > 0 else None,
    }


def cell_outcome(
    horizon: str,
    n: int,
    sigma: float,
    n_min: int,
    lower: float,
    point: float,
    rel: float,
    baseline_rel: float,
    prime_delta: float,
) -> str:
    if n == 0 or sigma == 0 or n < n_min:
        return "UNDERPOWERED"
    if lower <= 0 or point < G22_TARGET_DIFFERENCE_X:
        return "FAIL"
    if rel > baseline_rel:
        return "RES_ONLY_MISCALIBRATED"
    if horizon == "D0" and prime_delta <= 0:
        return "OBS_DRIVEN"
    return "PASS"


@dataclass(frozen=True)
class _Item:
    """Cluster-keyed handle onto one row's precomputed probabilities and outcomes."""

    station: str
    climate_day: str
    index: int


def _intervals(rows: Sequence[EventRow], arm: str, prereg: Mapping[str, Any]) -> dict[str, Any]:
    arm_p = [r.probabilities[arm] for r in rows]  # flattened once per cell, not per draw
    base_p = [r.probabilities["M0t"] for r in rows]
    outcomes = [r.outcomes for r in rows]
    items = [_Item(r.station, r.climate_day, i) for i, r in enumerate(rows)]

    def statistic(drawn: Sequence[_Item]) -> float:
        picks = [item.index for item in drawn]

        def gather(table: Sequence[tuple[Any, ...]]) -> list[Any]:
            return list(chain.from_iterable(map(table.__getitem__, picks)))

        return resolution_difference(gather(arm_p), gather(base_p), gather(outcomes), BINS)

    intervals: dict[str, Any] = {}
    sds = {}
    for name in ("station_day", "climate_day"):
        draws = cluster_bootstrap_draws(
            items,
            statistic=statistic,
            cluster_key=_station_day if name == "station_day" else _climate_day,
            seed=prereg["ci"]["seed"],
            iterations=prereg["ci"]["B"],
        )
        intervals[name] = list(percentile_interval(draws, alpha=_alpha(prereg)))
        sds[name] = statistics.pstdev(draws)
    intervals["gating"] = [min(intervals[k][0] for k in sds), max(intervals[k][1] for k in sds)]
    return {"CI": intervals, "bootstrap_dRES_sd": sds}


def _station_day(item: _Item) -> tuple[str, str]:
    return item.station, item.climate_day


def _climate_day(item: _Item) -> str:
    return item.climate_day


def _cell(
    rows: Sequence[EventRow], arm: str, horizon: str, prereg: Mapping[str, Any]
) -> dict[str, Any]:
    result = _power(rows, arm, prereg)
    result.update(
        decompositions={},
        dRES=None,
        dRES_M0n=None,
        dRES_M0prime=None,
        M0prime_dRES=None,
        CI={},
        bootstrap_dRES_sd={},
        outcome="UNDERPOWERED",
        label=None,
    )
    result.update(_coverage(rows, arm, prereg))
    if not rows:
        return result
    result.update(_intervals(rows, arm, prereg))
    result["decompositions"] = d = _decompositions(rows, arm)
    result.update(
        dRES=_delta(rows, arm),
        dRES_M0n=_delta(rows, arm, "M0n"),
        dRES_M0prime=_delta(rows, arm, "M0prime"),
        M0prime_dRES=_delta(rows, "M0prime"),
    )
    result["outcome"] = cell_outcome(
        horizon,
        result["n"],
        result["sigma_d"],
        result["n_min_adj"],
        result["CI"]["gating"][0],
        result["dRES"],
        d[arm]["REL"],
        d["M0t"]["REL"],
        result["dRES_M0prime"],
    )
    if result["outcome"] == "PASS":
        threshold = prereg["overall"]["pass_labels"]["threshold"]
        result["label"] = (
            "beats ask (indicative)" if result["CI"]["gating"][0] > threshold else "beats NBP"
        )
    return result


def _coverage(rows: Sequence[EventRow], arm: str, prereg: Mapping[str, Any]) -> dict[str, Any]:
    sensitivity = [
        r for r in rows if arm not in r.fell_back and not r.lamp_missing and not r.lamp_unknown
    ]
    versions = sorted({r.version for r in rows})
    return {
        "fell_back": {a: sum(a in r.fell_back for r in rows) for a in ARM_NAMES},
        "lamp_missing": {a: sum(r.lamp_missing for r in rows) for a in ARM_NAMES},
        "overlap": {a: sum(r.lamp_missing and a in r.fell_back for r in rows) for a in ARM_NAMES},
        "sensitivity": {
            **_power(sensitivity, arm, prereg),
            "dRES": _delta(sensitivity, arm) if sensitivity else None,
            "by_version": {v: sum(r.version == v for r in sensitivity) for v in versions},
            "excluded_by_version": {
                v: sum(
                    r.version == v and (arm in r.fell_back or r.lamp_missing or r.lamp_unknown)
                    for r in rows
                )
                for v in versions
            },
            "decompositions": _decompositions(sensitivity, arm) if sensitivity else {},
        },
    }


def _report_cell(rows: Sequence[EventRow], arm: str, prereg: Mapping[str, Any]) -> dict[str, Any]:
    cell = _cell(rows, arm, "D0", prereg)
    cell["lamp_unknown"] = sum(r.lamp_unknown for r in rows)  # no matching J2 feature row
    return cell


def evaluate(
    rows: Iterable[Mapping[str, Any] | ScoredRow], prereg: Mapping[str, Any]
) -> dict[str, Any]:
    events, excluded = _included(rows, prereg)
    cells = {
        f"{a}:{h}": _cell([r for r in events if r.horizon == h], a, h, prereg)
        for a in ARM_NAMES[1:]
        for h in HORIZONS
    }
    outcomes = [c["outcome"] for c in cells.values()]
    overall = "UNRESOLVED"
    if prereg.get("d1_granted") is True and "PASS" in outcomes:
        overall = "PASS"
    elif prereg.get("d1_granted") is True and all(o in ("FAIL", "OBS_DRIVEN") for o in outcomes):
        overall = "KILL"
    sensitivity_rows = [r for r in events if r.horizon == "D0_sensitivity"]
    report_only = {a: _report_cell(sensitivity_rows, a, prereg) for a in ARM_NAMES[1:]}
    report_only = report_only if sensitivity_rows else {}
    return {
        "schema": "gap1_oof_murphy_v1",
        "cells": cells,
        "overall": overall,
        "excluded": excluded,
        "D0_sensitivity": report_only,
        "f13_verdict": "NOT WRITTEN",
        "prereg_frozen_sha": prereg["frozen_sha"],
        "k_cum": prereg["k_cum"],
        "disclosures": prereg["disclosures"],
    }


def count_cells(
    row_mappings: Iterable[Mapping[str, Any]], prereg: Mapping[str, Any]
) -> dict[str, Any]:
    keys: dict[str, set[tuple[str, str]]] = {h: set() for h in HORIZONS}
    missing: dict[str, set[tuple[str, str]]] = {
        f"{a}:{h}": set() for a in ARM_NAMES[1:] for h in HORIZONS
    }
    versions: dict[str, int] = {}
    for row in row_mappings:
        h, day = row["horizon"], _day(row["climate_day"], prereg)
        if h == "D0_sensitivity":
            continue
        if h not in HORIZONS:
            raise ValueError("unregistered horizon")
        key = (row["station"], day)
        keys[h].add(key)
        v = row["version"]
        versions[v] = versions.get(v, 0) + 1
        prefix_missing = [
            bool(row["lamp"]["missing"]),
            row["pfm_mu_f"] is None,
            row["mos_mu_f"] is None,
        ]
        for i, a in enumerate(ARM_NAMES[1:]):
            if any(prefix_missing[: i + 1]):
                missing[f"{a}:{h}"].add(key)
    return {
        "schema": "gap1_counts_v1",
        "cells": {
            f"{a}:{h}": {"upper_bound": len(keys[h]), "missing_prefix": len(missing[f"{a}:{h}"])}
            for a in ARM_NAMES[1:]
            for h in HORIZONS
        },
        "versions": versions,
        "prior_floor": prereg["census_rule"]["prior_floor"],
    }


def _digest(design: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            {k: v for k, v in design.items() if k != "frozen_sha"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def load_prereg(path: Path) -> dict[str, Any]:
    from scripts.analysis.multisource_blend_pin_guards import check_not_refrozen
    from scripts.analysis.multisource_blend_refusal import Refusal
    from scripts.analysis.prereg_precommit_check import check_frozen_blob

    design = json.loads(path.read_text())
    if not isinstance(design, dict):
        raise TypeError("prereg must be an object")
    defects = check_frozen_blob(path, design)
    if defects:
        raise ValueError("; ".join(f"{d.code}: {d.message}" for d in defects))
    try:
        check_not_refrozen(path)
    except Refusal as exc:
        raise ValueError(str(exc)) from exc
    return design


def safe_json(path: Path, prereg: Mapping[str, Any], *, successor: bool = False) -> Any:
    primary = Path(prereg["j3_out_dir"]).expanduser().resolve()
    if successor and path.resolve() == primary / "stage_a.json":
        raise ValueError("successor refuses to open primary stage_a.json")
    return json.loads(path.read_text())


def read_oof(path: Path, prereg: Mapping[str, Any]) -> list[dict[str, Any]]:
    with path.open() as handle:
        header = json.loads(next(handle, "null"))
        if header != {"header": prereg["oof_header_expect"]}:
            raise ValueError("OOF header mismatch")
        return [json.loads(line) for line in handle if line.strip()]


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _code_ok(older: str, newer: str) -> bool:
    """Equal, or `older` is a git ancestor of `newer` (full lowercase shas only)."""
    if not (GIT_SHA.fullmatch(older) and GIT_SHA.fullmatch(newer)):
        return False
    if older == newer:
        return True
    done = subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    return done.returncode == 0


def _current_provenance(prereg: Mapping[str, Any]) -> dict[str, str]:
    return {
        "prereg_sha256": _digest(prereg),
        "c1_sha256": _sha(ROOT / prereg["c1_evidence"]["path"]),
        "code_sha": _git_sha(),
    }


def record_provenance(run: Path, prereg: Mapping[str, Any]) -> None:
    """Write-once run-time snapshot of the prereg, C1 and code the run starts under."""
    payload = {"schema": PROVENANCE_SCHEMA, **_current_provenance(prereg)}
    with (run / PROVENANCE_FILE).open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _recorded_provenance(run: Path, prereg: Mapping[str, Any]) -> dict[str, str]:
    data = safe_json(run / PROVENANCE_FILE, prereg, successor=True)
    if data["schema"] != PROVENANCE_SCHEMA:
        raise ValueError("run provenance schema")
    return {key: data[key] for key in ("prereg_sha256", "c1_sha256", "code_sha")}


def _feature_digests(run: Path, prereg: Mapping[str, Any], *, successor: bool) -> dict[str, str]:
    """Primary and lag feature digests, each verified against the run's build.json."""
    build_meta = safe_json(run / "build.json", prereg, successor=successor)
    features = {
        role: _sha(run / name) for role, name in (("primary", "f.jsonl"), ("lag", "fl.jsonl"))
    }
    if features != build_meta["output_sha256"]:
        raise ValueError("feature digests differ from build.json")
    return features


def _snapshot(run: Path, prereg: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "feature_sha256": _feature_digests(run, prereg, successor=True),
        **_recorded_provenance(run, prereg),
    }


def _successor_evidence(j3: Path, primary: Path, prereg: Mapping[str, Any]) -> None:
    evidence = safe_json(j3.parent / "successor_evidence.json", prereg, successor=True)
    if evidence["schema"] != "gap1_successor_evidence_v1":
        raise ValueError("successor evidence schema")
    journal = (j3.parent / evidence["infra_journal"]).resolve()
    if not journal.is_relative_to(j3.parent) or not any(
        token in journal.read_text() for token in ("OOM", "RuntimeMaxSec", "MemoryError")
    ):
        raise ValueError("missing infrastructure journal evidence")
    before, after = (_snapshot(run, prereg) for run in (primary.parent, j3.parent))
    now = _current_provenance(prereg)
    if (
        evidence["primary"] != before
        or evidence["successor"] != after
        or before["feature_sha256"] != after["feature_sha256"]
        or any(not before[k] == after[k] == now[k] for k in ("prereg_sha256", "c1_sha256"))
        or not (
            _code_ok(before["code_sha"], after["code_sha"])
            and _code_ok(after["code_sha"], now["code_sha"])
        )
    ):
        raise ValueError("unchanged-input evidence mismatch")
    _upward_envelopes(evidence)


def _upward_envelopes(evidence: Mapping[str, Any]) -> None:
    for key in ("MemoryMax", "RuntimeMaxSec", "--max-memory-gib"):
        before, after = (
            evidence["envelopes"]["primary"][key],
            evidence["envelopes"]["successor"][key],
        )
        floor = {"MemoryMax": 12, "RuntimeMaxSec": 14400, "--max-memory-gib": 3.5}[key]
        if (
            not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (before, after))
            or before < floor
            or after < before
        ):
            raise ValueError("successor resources must only increase (MemoryMax in GiB)")


def validate_j3(j3: Path, prereg: Mapping[str, Any]) -> None:
    root = Path(prereg["root"]).expanduser().resolve()
    primary = root / prereg["run_id"] / "j3"
    successor = root / (prereg["run_id"] + "-s2") / "j3"
    if (
        Path(prereg["j3_out_dir"]).expanduser().resolve() != primary
        or Path(prereg["successor"]["only_dir"]).expanduser().resolve() != successor
    ):
        raise ValueError("registered paths do not match root/run_id")
    j3 = j3.resolve()
    if j3 not in (primary, successor) or not j3.is_dir():
        raise ValueError("unregistered J3 directory")
    if any(p not in (primary, successor) for p in root.rglob("j3") if p.is_dir()):
        raise ValueError("unregistered J3 directory under root")
    completed = {p.parent for name in ("oof_rows.jsonl", "result.json") for p in root.rglob(name)}
    if len(completed) > 1:
        raise ValueError("more than one directory has OOF/result")
    if successor.exists() and (primary / "oof_rows.jsonl").exists():
        raise ValueError("successor exists while primary has OOF")
    if j3 == successor:
        if any((primary / name).exists() for name in ("oof_rows.jsonl", "result.json")):
            raise ValueError("primary already wrote OOF/result")
        try:
            _successor_evidence(j3, primary, prereg)
        except (OSError, KeyError, TypeError) as exc:
            raise ValueError("missing successor evidence") from exc


def _jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open() as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def build(prereg_path: Path, f13_path: Path, j3: Path) -> dict[str, Any]:
    prereg, f13 = load_prereg(prereg_path), load_prereg(f13_path)
    if (
        f13["frozen_sha"] != prereg["f13_prereg"]["frozen_sha"]
        or _digest(f13) != prereg["f13_prereg"]["content_sha256"]
        or f13["pins"]["student_t_nu"] != prereg["nu"]
    ):
        raise ValueError("F13 prereg mismatch")
    if _sha(ROOT / prereg["c1_evidence"]["path"]) != prereg["c1_evidence"]["sha256"]:
        raise ValueError("C1 digest mismatch")
    validate_j3(j3, prereg)
    rows = read_oof(j3 / "oof_rows.jsonl", prereg)
    _feature_digests(j3.parent, prereg, successor=False)  # primary and lag, as the successor path
    missing = {
        (r["station"], r["climate_day"], r["horizon"]): bool(r["lamp"]["missing"])
        for r in _jsonl(j3.parent / "f.jsonl")
    }
    for r in rows:
        key = (r["station"], r["climate_day"], r["horizon"])
        if key in missing:
            r["lamp_missing"] = missing[key]
        elif r["horizon"] == "D0_sensitivity":
            r["lamp_missing"] = UNKNOWN  # report-only row: never burn the one look on it
        else:
            raise ValueError(f"no matched J2 feature row for gating OOF row {key}")
    d1_path = j3.parent / "d1.json"
    d1 = safe_json(d1_path, prereg) if d1_path.exists() else {}
    scoring = dict(
        prereg,
        d1_granted=d1.get("granted") is True
        and d1.get("prereg_frozen_sha") == prereg["frozen_sha"],
    )
    result = evaluate(rows, scoring)
    f13_result = j3 / "result.json"
    result["f13_verdict"] = (
        safe_json(f13_result, prereg)["verdict"] if f13_result.exists() else "NOT WRITTEN"
    )
    if j3.resolve() == Path(prereg["successor"]["only_dir"]).expanduser().resolve():
        result["k_cum"] = dict(prereg["k_cum"], after=prereg["k_cum"]["after"] + 1)
    return result


def write_output(path: Path, payload: Mapping[str, Any]) -> None:
    content = json.dumps(
        dict(payload, git_sha=_git_sha()), indent=2, sort_keys=True, allow_nan=False
    )
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("prereg", "f13-prereg", "j3-dir", "features", "build-json", "out"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--record-provenance", type=Path, metavar="RUNDIR")
    parser.add_argument("--counts-only", action="store_true")
    args = parser.parse_args(argv)
    if args.out is None and args.record_provenance is None:
        parser.error("--out is required")
    try:
        if args.record_provenance is not None:
            if args.prereg is None:
                raise ValueError("--record-provenance requires --prereg")
            record_provenance(args.record_provenance, load_prereg(args.prereg))
            return 0
        if args.counts_only:
            if args.features is None or args.build_json is None:
                raise ValueError("counts-only requires --features and --build-json")
            meta = json.loads(args.build_json.read_text())
            if _sha(args.features) != meta["output_sha256"]["primary"]:
                raise ValueError("features digest differs from build.json")
            result = count_cells(_jsonl(args.features), load_prereg(args.prereg or DEFAULT_PREREG))
        else:
            if any(x is None for x in (args.prereg, args.f13_prereg, args.j3_dir)):
                raise ValueError("verdict requires --prereg --f13-prereg --j3-dir")
            result = build(args.prereg, args.f13_prereg, args.j3_dir)
        write_output(args.out, result)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"gap1_oof_murphy: REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
