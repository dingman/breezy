"""GAP-1 S1/S2: synthetic, offline reader contracts (T3--T14)."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib
import importlib.util
import json
import math
import subprocess
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from statistics import NormalDist
from types import ModuleType
from typing import Any

import pytest

from breezy.analysis import nbp_calibration as nbp
from breezy.analysis.multisource_blend_io import scored_row_from_json
from tests.unit.test_gap1_prereg import PREREG, ROOT


@pytest.fixture
def reader() -> ModuleType:
    name = "scripts.analysis.gap1_oof_murphy"
    assert importlib.util.find_spec(name) is not None, "GAP-1 OOF Murphy reader is missing"
    return importlib.import_module(name)


@pytest.fixture
def prereg() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(PREREG.read_text())
    result["d1_granted"] = True  # synthetic grant; never edits the frozen prereg
    return result


def row(i: int = 0, horizon: str = "D-1") -> dict[str, Any]:
    return {
        "station": "KORD",
        "climate_day": (dt.date(2025, 1, 1) + dt.timedelta(days=i)).isoformat(),
        "version": "v4",
        "horizon": horizon,
        "fold_id": 0,
        "observed_f": 68 if i % 2 else 77,
        "crps": {},
        "levels": {},
        "fell_back": [],
        "lamp_missing": False,
        "champion": {
            "method": "NORMAL",
            "a": 0,
            "gamma": 0,
            "delta": 1,
            "percentiles": {
                "q10": 67,
                "q25": 70,
                "q50": 72,
                "q75": 75,
                "q90": 78,
                "mean": 72.5,
                "sd": 4,
            },
        },
        "arm_predictions": {
            "M0prime": {"mu": 72.5, "sigma": 4, "nu": 5},
            "M1": {"mu": 68 if i % 2 else 77, "sigma": 0.5 + i % 3 * 0.01, "nu": 5},
            "M2": {"mu": 72.5, "sigma": 4 + i % 3 * 0.001, "nu": 5},
            "M3": {"mu": 72.5, "sigma": 4 + i % 3 * 0.001, "nu": 5},
        },
    }


def fixture_j3(tmp_path: Path, p: dict[str, Any], rows: list[dict[str, Any]]) -> Path:
    p["root"] = str(tmp_path)
    j3 = tmp_path / str(p["run_id"]) / "j3"
    j3.mkdir(parents=True)
    p["j3_out_dir"] = str(j3)
    p["successor"]["only_dir"] = str(tmp_path / (p["run_id"] + "-s2") / "j3")
    (j3 / "oof_rows.jsonl").write_text(
        "\n".join(json.dumps(x) for x in [{"header": p["oof_header_expect"]}, *rows])
    )
    return j3


def test_t3_golden_and_write_once(
    reader: ModuleType, prereg: dict[str, Any], tmp_path: Path
) -> None:
    rows = [row(i, h) for h in ("D0", "D-1") for i in range(12)]
    j3 = fixture_j3(tmp_path, prereg, rows)
    loaded = reader.read_oof(j3 / "oof_rows.jsonl", prereg)
    result = reader.evaluate(loaded, prereg)
    assert result["cells"]["M1:D-1"]["outcome"] == "PASS"
    assert result["cells"]["M2:D-1"]["outcome"] == "FAIL"
    assert result["overall"] == "PASS"
    for name in ("a.json", "b.json"):
        reader.write_output(tmp_path / name, result)
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
    with pytest.raises(FileExistsError):
        reader.write_output(tmp_path / "a.json", result)
    assert reader.evaluate([], prereg)["overall"] == "UNRESOLVED"
    small = row()
    small["arm_predictions"]["M1"]["mu"] = 73
    assert reader.evaluate([small], prereg)["cells"]["M1:D-1"]["outcome"] == "UNDERPOWERED"


def test_t3_build_cli_and_f13_passthrough(
    reader: ModuleType, prereg: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [row(i, h) for h in ("D0", "D-1") for i in range(12)]
    j3 = fixture_j3(tmp_path, prereg, rows)
    features = [
        {
            "station": r["station"],
            "climate_day": r["climate_day"],
            "horizon": r["horizon"],
            "lamp": {"missing": False},
        }
        for r in rows
    ]
    f = j3.parent / "f.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in features))
    (j3.parent / "build.json").write_text(
        json.dumps({"output_sha256": {"primary": hashlib.sha256(f.read_bytes()).hexdigest()}})
    )
    f13_path = ROOT / prereg["f13_prereg"]["path"]
    verified = reader.load_prereg
    monkeypatch.setattr(
        reader, "load_prereg", lambda path: prereg if path == PREREG else verified(path)
    )
    (j3 / "result.json").write_text(json.dumps({"verdict": "NO_SKILL"}))
    (j3.parent / "d1.json").write_text(
        json.dumps({"granted": True, "prereg_frozen_sha": prereg["frozen_sha"]})
    )
    args = ["--prereg", str(PREREG), "--f13-prereg", str(f13_path), "--j3-dir", str(j3)]
    for name in ("cli-a.json", "cli-b.json"):
        assert reader.main([*args, "--out", str(tmp_path / name)]) == 0
    a = json.loads((tmp_path / "cli-a.json").read_text())
    assert a["overall"] == "PASS" and a["f13_verdict"] == "NO_SKILL"
    assert (
        a["git_sha"]
        == subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    )
    assert (tmp_path / "cli-a.json").read_bytes() == (tmp_path / "cli-b.json").read_bytes()


@pytest.mark.parametrize(
    "defect",
    ["cutoff", "method", "arms_missing", "arms_extra", "nu", "fraction", "nan", "sd", "scale"],
)
def test_t4_row_refusals(reader: ModuleType, prereg: dict[str, Any], defect: str) -> None:
    r = row()
    if defect == "cutoff":
        r["climate_day"] = "2026-07-01"
    elif defect == "method":
        r["champion"]["method"] = "SKEW_NORMAL"
    elif defect == "arms_missing":
        del r["arm_predictions"]["M3"]
    elif defect == "arms_extra":
        r["arm_predictions"]["M0"] = r["arm_predictions"]["M1"]
    elif defect == "nu":
        r["arm_predictions"]["M0prime"]["nu"] = 6
    elif defect == "fraction":
        r["observed_f"] = 72.5
    elif defect == "nan":
        r["observed_f"] = float("nan")
    elif defect == "sd":
        r["champion"]["percentiles"]["sd"] = 0
    elif defect == "scale":
        r["champion"]["gamma"] = 1000
    with pytest.raises((ValueError, RuntimeError)):
        reader.evaluate([r], prereg)


@pytest.mark.parametrize("key", ["schema", "frozen_sha", "content_sha256"])
def test_t4_header_refusal(
    reader: ModuleType, prereg: dict[str, Any], tmp_path: Path, key: str
) -> None:
    j3 = fixture_j3(tmp_path, prereg, [])
    bad = dict(prereg["oof_header_expect"], **{key: "wrong"})
    (j3 / "oof_rows.jsonl").write_text(json.dumps({"header": bad}))
    with pytest.raises(ValueError, match="header"):
        reader.read_oof(j3 / "oof_rows.jsonl", prereg)


def test_t4_unc_refusal(
    reader: ModuleType, prereg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    real = reader.murphy_decomposition
    calls = 0

    def inconsistent(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return replace(real(*args, **kwargs), uncertainty=0.1 if calls == 1 else 0.2)

    monkeypatch.setattr(reader, "murphy_decomposition", inconsistent)
    with pytest.raises(ValueError, match="UNC"):
        reader.evaluate([row()], prereg)


def test_t4_load_refuses_freeze_defects(reader: ModuleType, tmp_path: Path) -> None:
    assert reader.load_prereg(PREREG)["nu"] == 5
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"frozen_sha": "UNFROZEN"}))
    with pytest.raises(ValueError, match="BAD_frozen_sha"):
        reader.load_prereg(bad)


def test_t1_refreeze_refuses_without_traceback(
    reader: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.analysis import multisource_blend_pin_guards as guards
    from scripts.analysis.multisource_blend_refusal import Refusal

    def refrozen(path: Path) -> None:
        raise Refusal("the prereg was re-frozen")

    monkeypatch.setattr(guards, "check_not_refrozen", refrozen)
    with pytest.raises(ValueError, match="re-frozen"):
        reader.load_prereg(PREREG)


@pytest.mark.parametrize(
    "h,n,sigma,lower,point,rel,prime,want",
    [
        ("D0", 0, 0.0, -1.0, 0.0, 1.0, 0.0, "UNDERPOWERED"),
        ("D0", 1, 0.2, 1.0, 1.0, 0.0, 1.0, "UNDERPOWERED"),
        ("D0", 1000, 0.01, 0.0, 1.0, 1.0, 1.0, "FAIL"),
        ("D0", 1000, 0.01, 1.0, 0.0151, 0.0, 1.0, "FAIL"),
        ("D0", 1000, 0.01, 1.0, 1.0, 0.2, 0.0, "RES_ONLY_MISCALIBRATED"),
        ("D0", 1000, 0.01, 1.0, 1.0, 0.0, 0.0, "OBS_DRIVEN"),
        ("D-1", 1000, 0.01, 1.0, 1.0, 0.0, 0.0, "PASS"),
        ("D0", 1000, 0.01, 1.0, 0.0152, 0.1, 0.1, "PASS"),
    ],
)
def test_t5_precedence(
    reader: ModuleType,
    h: str,
    n: int,
    sigma: float,
    lower: float,
    point: float,
    rel: float,
    prime: float,
    want: str,
) -> None:
    assert reader.cell_outcome(h, n, sigma, 10, lower, point, rel, 0.1, prime) == want


@pytest.mark.parametrize(
    "outcome,grant,want",
    [
        ("PASS", True, "PASS"),
        ("PASS", False, "UNRESOLVED"),
        ("FAIL", True, "KILL"),
        ("OBS_DRIVEN", True, "KILL"),
        ("FAIL", False, "UNRESOLVED"),
        ("UNDERPOWERED", True, "UNRESOLVED"),
        ("RES_ONLY_MISCALIBRATED", True, "UNRESOLVED"),
    ],
)
def test_t5_overall(
    reader: ModuleType,
    prereg: dict[str, Any],
    outcome: str,
    grant: bool,
    want: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader, "_cell", lambda *args: {"outcome": outcome})
    prereg["d1_granted"] = grant
    assert reader.evaluate([], prereg)["overall"] == want


def test_t6_exact_brier_identity(reader: ModuleType, prereg: dict[str, Any]) -> None:
    r = row()
    for arm in r["arm_predictions"]:
        r["arm_predictions"][arm] = dict(r["arm_predictions"]["M0prime"])
    result = reader.evaluate([r], prereg)
    for cell in result["cells"].values():
        for d in cell["decompositions"].values():
            assert d["REL"] - d["RES"] + d["UNC"] == pytest.approx(d["Brier"], abs=1e-12)


def test_t6_coarse_bins_report_exact_corrections(
    reader: ModuleType, prereg: dict[str, Any]
) -> None:
    result = reader.evaluate([row(i) for i in range(3)], prereg)
    for cell in result["cells"].values():
        for d in cell["decompositions"].values():
            assert d["REL"] - d["RES"] + d["UNC"] + d["W"] - d["C"] == pytest.approx(
                d["Brier"], abs=1e-12
            )


def test_t7_bonferroni_and_prior(reader: ModuleType, prereg: dict[str, Any]) -> None:
    z = prereg["power"]["z_b"]
    assert z == pytest.approx(NormalDist().inv_cdf(1 - 0.05 / 12), abs=1e-12)
    draws = list(range(prereg["ci"]["B"]))
    assert (
        reader.percentile_interval(draws, alpha=0.05 / 6)[0]
        == math.floor(0.05 / 12 * len(draws))
        == 20
    )
    prior = (
        nbp.G22_TARGET_DIFFERENCE_X
        * math.sqrt(592)
        / (round(nbp.Z_ALPHA_TWO_SIDED_095, 6) + round(nbp.Z_POWER_080, 6))
    )
    assert reader.adjusted_n_min(prior, prereg) == 914


def test_t8_m0t_normal_closed_form_and_t8b_scipy(reader: ModuleType) -> None:
    from scipy.stats import t

    from breezy.analysis.multisource_blend_fit import student_t_cdf
    from breezy.analysis.multisource_blend_folds import champion_cdf

    r = row()
    r["champion"].update(a=0.7, gamma=0.2, delta=0.8)
    spec = scored_row_from_json(r).champion
    assert spec is not None
    m, s = reader.m0t_parameters(spec)
    for x in (71.5, 73.5):
        assert NormalDist(m, s).cdf(x) == pytest.approx(champion_cdf(spec)(x), abs=1e-12)
        assert student_t_cdf(m, s, 5)(x) == pytest.approx(t(df=5, loc=m, scale=s).cdf(x), abs=1e-12)
        assert student_t_cdf(m, s, 5)(x) != student_t_cdf(m, s, 9)(x)


def test_t9_wider_clustering(reader: ModuleType, prereg: dict[str, Any]) -> None:
    result = reader.evaluate([row(i) for i in range(3)], prereg)
    ci = result["cells"]["M1:D-1"]["CI"]
    assert ci["gating"] == [
        min(ci[k][0] for k in ("station_day", "climate_day")),
        max(ci[k][1] for k in ("station_day", "climate_day")),
    ]


def test_t9_opposite_tails_from_different_clusterings(
    reader: ModuleType, prereg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def draws(items: Any, *, cluster_key: Any, iterations: int, **kwargs: Any) -> list[float]:
        low, high = (0.1, 0.4) if isinstance(cluster_key(items[0]), tuple) else (-0.2, 0.3)
        return [low] * (iterations // 2) + [high] * (iterations - iterations // 2)

    monkeypatch.setattr(reader, "cluster_bootstrap_draws", draws)
    result = reader.evaluate([row()], prereg)
    assert result["cells"]["M1:D-1"]["CI"]["gating"] == [-0.2, 0.4]


def test_t10_ladder_parity_half_even_inclusive(reader: ModuleType) -> None:
    from scripts.analysis.nbp_skill_study import _forecast_centered_ladder

    assert round(72.5) == 72
    ladder = reader.forecast_centered_ladder(round(72.5))
    assert ladder == _forecast_centered_ladder(72)
    for y, expected in ((71, "lt"), (72, "mid"), (73, "mid"), (74, "gte")):
        assert [r.rung_id for r in ladder if reader.rung_outcome(r, y)] == [expected]


@pytest.mark.parametrize(
    "case",
    [
        "primary",
        "unknown",
        "second",
        "successor_missing_evidence",
        "successor_primary_oof",
        "primary_result",
        "primary_stage_a",
    ],
)
def test_t11_successor_matrix(
    reader: ModuleType, prereg: dict[str, Any], tmp_path: Path, case: str
) -> None:
    primary = fixture_j3(tmp_path, prereg, [])
    successor = Path(prereg["successor"]["only_dir"])
    if case == "primary":
        reader.validate_j3(primary, prereg)
        return
    successor.mkdir(parents=True)
    target = successor
    if case == "unknown":
        target = tmp_path / "other" / "j3"
        target.mkdir(parents=True)
    if case == "second":
        (successor / "result.json").write_text("{}")
    if case in ("successor_missing_evidence", "primary_stage_a", "primary_result"):
        (primary / "oof_rows.jsonl").unlink()
    if case == "primary_result":
        (primary / "result.json").write_text("{}")
    if case == "primary_stage_a":
        (primary / "stage_a.json").write_text("MUST NOT BE READ")
        with pytest.raises(ValueError, match="primary stage_a"):
            reader.safe_json(primary / "stage_a.json", prereg, successor=True)
    with pytest.raises(ValueError):
        reader.validate_j3(target, prereg)


def successor_evidence(
    reader: ModuleType, prereg: dict[str, Any], tmp_path: Path
) -> tuple[Path, Path]:
    primary = fixture_j3(tmp_path, prereg, [])
    (primary / "oof_rows.jsonl").unlink()
    successor = Path(prereg["successor"]["only_dir"])
    successor.mkdir(parents=True)
    for run in (primary.parent, successor.parent):
        (run / "f.jsonl").write_text("")
        (run / "fl.jsonl").write_text("")
        digest = hashlib.sha256(b"").hexdigest()
        (run / "build.json").write_text(
            json.dumps({"output_sha256": {"primary": digest, "lag": digest}})
        )
    limits = {"MemoryMax": 12, "RuntimeMaxSec": 14400, "--max-memory-gib": 3.5}
    evidence = {
        "schema": "gap1_successor_evidence_v1",
        "infra_journal": "infra.log",
        "primary": reader._snapshot(primary.parent, prereg),
        "successor": reader._snapshot(successor.parent, prereg),
        "envelopes": {"primary": limits, "successor": limits},
    }
    (successor.parent / "infra.log").write_text("MemoryError\n")
    path = successor.parent / "successor_evidence.json"
    path.write_text(json.dumps(evidence))
    (primary / "stage_a.json").write_text("POISON: primary truth, never read")
    return successor, path


@pytest.mark.parametrize(
    "defect", [None, "journal", "inputs", "code", "c1", "prereg", "envelope", "digest", "evidence"]
)
def test_t11_successor_evidence_checked(
    reader: ModuleType,
    prereg: dict[str, Any],
    tmp_path: Path,
    defect: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor, path = successor_evidence(reader, prereg, tmp_path)
    evidence = json.loads(path.read_text())
    if defect == "journal":
        (successor.parent / "infra.log").write_text("ordinary exit 1")
    elif defect == "inputs":
        (successor.parent / "f.jsonl").write_text("changed")
    elif defect in ("code", "c1", "prereg"):
        key = {"code": "code_sha", "c1": "c1_sha256", "prereg": "prereg_sha256"}[defect]
        evidence["primary"][key] = evidence["successor"][key] = "wrong"
    elif defect == "envelope":
        evidence["envelopes"]["successor"]["MemoryMax"] = 6
    elif defect == "digest":
        evidence["successor"]["feature_sha256"]["lag"] = "wrong"
    path.write_text(json.dumps(evidence))
    if defect == "evidence":
        path.unlink()
    real_read = Path.read_text

    def guarded_read(p: Path, *args: Any, **kwargs: Any) -> str:
        assert p.name != "stage_a.json", "successor read primary truth"
        return real_read(p, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    if defect is None:
        reader.validate_j3(successor, prereg)
    else:
        with pytest.raises(ValueError):
            reader.validate_j3(successor, prereg)


def test_t12_constant_identity_and_subprocess_import(reader: ModuleType) -> None:
    for name in ("RELIABILITY_BUCKET_EDGES", "percentile_interval", "cluster_bootstrap_draws"):
        assert getattr(reader, name) is getattr(nbp, name)
    probe = (
        "import sys; import scripts.analysis.gap1_oof_murphy; "
        "banned=['scripts.analysis.nbp_skill_study','breezy.analysis.scoring_core',"
        "'scripts.analysis.settlement_truth_dataset','settlement_truth_dataset',"
        "'breezy.persistence.archive_cache','breezy.persistence.nbp_derived_store',"
        "'breezy.adapters','breezy.ingest.http','breezy.runtime.health',"
        "'breezy.runtime.alert_delivery','breezy.runtime.alert_proof',"
        "'requests','httpx','aiohttp','urllib.request','http.client','urllib3','websockets']; "
        "bad=[n for n in sys.modules if any(n==b or n.startswith(b+'.') for b in banned) "
        "or 'catalog' in n or 'tape' in n]; assert not bad,bad; print(banned)"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_t13_inclusion_and_fallback(reader: ModuleType, prereg: dict[str, Any]) -> None:
    rows = [row(i) for i in range(3)]
    rows[0]["fell_back"] = ["M1"]
    rows[0]["lamp_missing"] = True
    rows[1]["champion"] = None
    rows[2]["fold_id"] = None
    result = reader.evaluate(rows, prereg)
    assert result["excluded"] == {"champion_none": 1, "fold_id_none": 1}
    cell = result["cells"]["M1:D-1"]
    assert cell["n"] == 1 and cell["fell_back"]["M1"] == 1
    assert cell["lamp_missing"]["M1"] == cell["overlap"]["M1"] == 1
    assert cell["sensitivity"]["n"] == 0


class BlindRow(Mapping[str, Any]):
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def __getitem__(self, key: str) -> Any:
        assert key in {
            "station",
            "climate_day",
            "version",
            "horizon",
            "lamp",
            "pfm_mu_f",
            "mos_mu_f",
        }, key
        return self.data[key]

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("must not enumerate outcome-bearing fields")

    def __len__(self) -> int:
        raise AssertionError("must not inspect unrelated fields")


def test_t14_counts_only_allowlist(reader: ModuleType) -> None:
    r: dict[str, Any] = {
        "station": "KORD",
        "climate_day": "2025-01-01",
        "version": "v4",
        "horizon": "D0",
        "lamp": {"missing": True},
        "pfm_mu_f": None,
        "mos_mu_f": None,
    }
    result = reader.count_cells([BlindRow(r), BlindRow(copy.deepcopy(r))])
    assert result["cells"]["M1:D0"]["upper_bound"] == 1
    assert result["cells"]["M3:D0"]["missing_prefix"] == 1


def test_t14_counts_cli_uses_only_mappings(
    reader: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("counts must never parse feature rows or scores")

    from breezy.analysis import multisource_blend_io as io

    monkeypatch.setattr(io, "feature_row_from_json", forbidden)
    monkeypatch.setattr(reader, "scored_row_from_json", forbidden)
    f, build_meta, out = (tmp_path / name for name in ("f.jsonl", "build.json", "counts.json"))
    f.write_text(
        json.dumps(
            {
                "station": "KORD",
                "climate_day": "2025-01-01",
                "version": "v4",
                "horizon": "D0",
                "lamp": {"missing": True},
                "pfm_mu_f": None,
                "mos_mu_f": None,
            }
        )
    )
    build_meta.write_text(
        json.dumps({"output_sha256": {"primary": hashlib.sha256(f.read_bytes()).hexdigest()}})
    )
    assert (
        reader.main(
            [
                "--counts-only",
                "--features",
                str(f),
                "--build-json",
                str(build_meta),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert json.loads(out.read_text())["cells"]["M1:D0"]["upper_bound"] == 1
