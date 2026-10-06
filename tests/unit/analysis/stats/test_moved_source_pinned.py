"""F7a WP1s (G36 move, stats-only): the moved statistics are byte-identical to the base source
and the scripts delegate to them.

PINS are the sha256 of each definition's source (decorators through the last line), measured from
the scripts at base sha 8bdb5ef1 BEFORE the move. Re-verify with a real reviewer before ever
updating a pin: a changed pin means the statistics changed, not that the move was wrong.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_STATS_DIR = _REPO_ROOT / "src" / "breezy" / "analysis" / "stats"
_SCRIPTS_DIR = _REPO_ROOT / "scripts" / "analysis"

#: module -> {name: sha256 of the definition's source at base sha 8bdb5ef1}
PINS: dict[str, dict[str, str]] = {
    "sequential_looks": {
        "LOSS_STOP_PNL": ("fd78925346ae2b0a6d176bceb2d348729744faa94be538a0c9a55b5a22ad48ce"),
        "LookRecord": ("8427a8baced4be7a1553f7e409ae40082e554d8d890e47760758c318089e63fa"),
        "_BoundaryFn": ("a5b73593dc86125da357c3b3992b5d674f093028c18c63a55d82ab2bf376feae"),
        "run_sequential_looks": (
            "63f4fcb14cd3b743412734f228c979687eb535da1d4122759ae616685b896bee"
        ),
        "StreamingBoundary": ("392aac73a442a466bb99c578d53099e45eeb9fe6224ececa9f37ddfa59a6ff8b"),
    },
    "group_sequential_boundaries": {
        "DEFAULT_ALPHA": ("3535479fe1cb2cc343c80c514c95fe0ce58ff89186a9ea862f6688f2e117afcb"),
        "GRID_NPTS": ("3952f9a5cede8541cfa1ee162155e9ace719a8af5ee2bdf27f354e19e0427dec"),
        "GRID_HALFWIDTH_SD": ("d19bb1e556253e7eae29ca34a1205cc68616a6bf0b4b57b0c0dc4dd32f34d8c0"),
        "BRENTQ_XTOL": ("3fabc793658d82e96dab97e7349474338e07170f4af0fb68a3513bb9afe7e868"),
        "one_sided_z_half": ("c5f87f9946048bdc77df51211d4c60ba6b99276d1778a5c52413e6167e00c2f8"),
        "one_sided_spend": ("8bb702e1362a661430a288a161a38b1c915c8f92953b833a22767902016e607d"),
        "i_max_for": ("e4890bd0c207253b76963d4fba480bd05a6165b735075385d2c8a97ec139993b"),
        "_convolve_density": ("3add30248cb8063f5349291035fe68a088dfafb395df89c3df53cf5b3d39c796"),
        "_tail_probs": ("4f1731edfc93b9a3f85e60c2515d4de67908bfd203c3955e1be2db5a91a257d6"),
        "_look_step": ("4662463532859d584d3e7a1c5955f8a3fe0e280485fd376b5895d43d1576272c"),
        "_iter_boundary_looks": (
            "7ebcb6b55730c646c8bd3b6ee953994307714b73461bdfd976976c87927cea8f"
        ),
        "boundary_for": ("f77cf9baab352abc0d829a8cbc7183d4adb4f5c1d4c62608f3b310703e79a937"),
        "LookRow": ("393cf04c386584caf1f7a4ae55d209baac42c7e9d61c7b441cd0d31c23196d98"),
        "build_reference_table": (
            "52cce75fdfa96906b0c09d60c3d4d7a8e1ce27a09a3e51111931820f4882d1de"
        ),
    },
    "scoring_core": {
        "BOOTSTRAP_ITERATIONS": (
            "f6a1df3029e14554946ffffc69eafd1647f4467df926a199c9b790f48294781e"
        ),
        "BOOTSTRAP_SEED": ("82e26f0e213a4a53859ce55f8e7acc82f22f0f5630d98914600d95798cc82ac0"),
        "BOOTSTRAP_ALPHA": ("14d5dc7bd16c5cc373a7bbedf78d54ac4c6dae0207115db2e0a08673db1cfafa"),
        "RELIABILITY_BUCKET_EDGES": (
            "033f2333092ba2e1cadf7869339ce1b6cd09b85636a0d239e66247ccee22e0bf"
        ),
        "LeakageError": ("95758541c8289bba10a5fcec1ca48972dc72044579ac310fe304b5a490c57eac"),
        "MODEL_FORECAST": ("6dd9f49b809ab670ede706b8ebfea57fe1da4ef39792be8164ff70da33b66606"),
        "MODEL_PERSISTENCE": ("3aa6cf9c8aa86c69956789a2de04e06fe3477d1ac5418ecc42cb00eee0b15b53"),
        "MODEL_CLIMATOLOGY": ("faaff3a8510454612780119a9e5e9b004a7dc23700fd4a56caeb1fe015f21a2b"),
        "MODEL_CONSTANT": ("16cc837f9b2cefce6e4ba8239c4f63b5ece4aa850c5e2ca48cf248ab4b95ba9c"),
        "MODEL_KEYS": ("c2de7abb5e912dcda9b20acb7c7bf70def5442c32df9b56610f99a7a30fca69f"),
        "CLUSTER_STATION_DAY": ("28f55f93e47452bda39e4b38d7345738f9729a38f306fd7c3a164062a4b91b53"),
        "CLUSTER_DATE": ("4d592219eeb3b57515d4519e0bab3610b4a0562c7b69a1066c934777ad012c6e"),
        "CLUSTER_STATION": ("41243af5c750d6a2016908ba248c02adb532bb69e4fc11c182d64c642b93c02d"),
        "PERSISTENCE_HORIZON_HOURS": (
            "3526d2a389cf58efae73536d78f61f4629e2d0187891e7bcb6035ffe5461c86c"
        ),
        "RELIABILITY_EPSILON": ("f7b6ecad5d71cf95edfe05cb9db3826aebbc893b3b0441eeea9ed17e81bb3635"),
        "LEG_PASS": ("e78f13989cf885766fd29f5c4366a9035a63556400f1fe9e3b2946d34ec964a2"),
        "LEG_FAIL": ("753d5dba1a41658165f3d60f346503895c953c5ef511c6fe339a133fcbae0d6a"),
        "Trial": ("53e14fca16277057caf7f641bedce4c996050a838b2333384e3a1e85ced13f25"),
        "brier": ("6dc4a5d8b527dde47b5b80346ca7e659ffa456e478a9769b902999456f4da6ef"),
        "ReliabilityBucket": ("ae67acd8bb2d522efd66567feb202ec5186908057a250c6e66d7d9ce9592ee7f"),
        "reliability": ("56b74db843e4af64ed8ffda1b7c9346cbca564a7554feb8875431ec820f349d1"),
        "ClusterCI": ("6a1f8600a92d7273076cce225b1f2342a7c90d4c182509a5cdee9fdd52054a00"),
        "SupportsClusterKey": ("6f12cddaa651d3d332356c5b6048997b682952b984ef580c26c4428bb0d5a27b"),
        "_clusters": ("7a35042564fe5880809bcf83eaf264d7db45ca799dab48a65c792d41318ffed9"),
        "bootstrap_cluster_draws": (
            "505d9715a56faac2a2b7716cea6bad91eecdd294460aa032c0cdd35b6dbf2f69"
        ),
        "percentile_interval": ("0cee3305d11144f1bc23a20c226fc17f37c4bb5351682bcd3b6d9b8a015ca72f"),
        "assert_nondegenerate_clustering": (
            "a644c662243372463254220c8d750d7195a6394a2bd45e9a965625a16abbb114"
        ),
        "bootstrap_brier_difference_ci": (
            "ffdd2ef601c51415503b8fb9a0b6cb3a1628abacc34a49c9b1bf159252948786"
        ),
        "brier_skill_score": ("ef8a41e37808544f84ecc0d41c5f0da73fbb6818f90bd72bb3631f0dcbd4ba8a"),
        "CalibrationLeg": ("d25f8cee7880bc1bc2ec79fd6c767a7a5e5029a1a6f09374ac409eb8576f2308"),
        "evaluate_calibration_leg": (
            "60fd9741bc976b6c0562acd350ac58d67cd4a2c9225e294d88fbdf6a89d99b4e"
        ),
        "underconfidence_signal": (
            "4eed10edd1bcecaf658e3cb8fadb0714964de2e101b2571ba41c6c0a1f82f17c"
        ),
    },
}

#: (stats module, script file) -> names the script must re-export by identity
WRAPPERS: dict[tuple[str, str], tuple[str, ...]] = {
    ("sequential_looks", "family_tally_v2.py"): (
        "LOSS_STOP_PNL",
        "LookRecord",
        "_BoundaryFn",
        "run_sequential_looks",
    ),
    ("sequential_looks", "aud07_live_rule_crossing_sim.py"): ("StreamingBoundary",),
    ("group_sequential_boundaries", "crh_group_sequential_boundaries.py"): (
        "DEFAULT_ALPHA",
        "GRID_NPTS",
        "GRID_HALFWIDTH_SD",
        "BRENTQ_XTOL",
        "one_sided_z_half",
        "one_sided_spend",
        "i_max_for",
        "_convolve_density",
        "_tail_probs",
        "_look_step",
        "_iter_boundary_looks",
        "boundary_for",
        "LookRow",
        "build_reference_table",
    ),
    ("scoring_core", "forecast_conditional_corpus.py"): (
        "BOOTSTRAP_ITERATIONS",
        "BOOTSTRAP_SEED",
        "BOOTSTRAP_ALPHA",
        "RELIABILITY_BUCKET_EDGES",
        "LeakageError",
    ),
    ("scoring_core", "forecast_conditional_scoring.py"): (
        "MODEL_FORECAST",
        "MODEL_PERSISTENCE",
        "MODEL_CLIMATOLOGY",
        "MODEL_CONSTANT",
        "MODEL_KEYS",
        "CLUSTER_STATION_DAY",
        "CLUSTER_DATE",
        "CLUSTER_STATION",
        "PERSISTENCE_HORIZON_HOURS",
        "RELIABILITY_EPSILON",
        "LEG_PASS",
        "LEG_FAIL",
        "Trial",
        "brier",
        "ReliabilityBucket",
        "reliability",
        "ClusterCI",
        "SupportsClusterKey",
        "_clusters",
        "bootstrap_cluster_draws",
        "percentile_interval",
        "assert_nondegenerate_clustering",
        "bootstrap_brier_difference_ci",
        "brier_skill_score",
        "CalibrationLeg",
        "evaluate_calibration_leg",
        "underconfidence_signal",
    ),
}

#: Modules the verify-first measurement found clean; none may reach these in a fresh process.
FORBIDDEN_PREFIXES = ("breezy.runtime", "breezy.strategy", "nautilus_trader")


def _segment_sha(path: Path, name: str) -> str:
    source = path.read_text()
    lines = source.split("\n")
    for node in ast.parse(source).body:
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if name in names:
            first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            code = "\n".join(lines[first - 1 : node.end_lineno])
            return hashlib.sha256(code.encode()).hexdigest()
    raise AssertionError(f"{name} is not defined at the top level of {path}")


def _top_level_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


_PIN_CASES = [(m, n, h) for m, d in PINS.items() for n, h in d.items()]


@pytest.mark.parametrize(
    ("module", "name", "sha"), _PIN_CASES, ids=[f"{m}.{n}" for m, n, _ in _PIN_CASES]
)
def test_moved_functions_byte_identical(module: str, name: str, sha: str) -> None:
    path = _STATS_DIR / f"{module}.py"
    assert path.is_file(), f"{path} does not exist"
    assert _segment_sha(path, name) == sha, (
        f"{module}.{name} differs from the base-sha source; a G36 move is byte-identical. "
        "Re-verify with a real reviewer before ever updating this pin."
    )


def _load_script(filename: str) -> ModuleType:
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    path = _SCRIPTS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"_f7a_wrapper_{path.stem}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


_WRAPPER_CASES = [(m, f, names) for (m, f), names in WRAPPERS.items()]


@pytest.mark.parametrize(
    ("module", "script", "names"), _WRAPPER_CASES, ids=[f"{m}<-{f}" for m, f, _ in _WRAPPER_CASES]
)
def test_script_wrappers_delegate(module: str, script: str, names: tuple[str, ...]) -> None:
    stats = importlib.import_module(f"breezy.analysis.stats.{module}")
    wrapper = _load_script(script)
    redefined = _top_level_names(_SCRIPTS_DIR / script) & set(names)
    # A moved name may be imported into the script but never defined there.
    for name in names:
        assert getattr(wrapper, name) is getattr(stats, name), (
            f"{script}:{name} is not the stats object"
        )
    assert not redefined or all(getattr(wrapper, n) is getattr(stats, n) for n in redefined), (
        "script redefines a moved name"
    )
    defined_here = {
        n.name
        for n in ast.parse((_SCRIPTS_DIR / script).read_text()).body
        if isinstance(n, (ast.FunctionDef, ast.ClassDef))
    } & set(names)
    assert not defined_here, f"{script} still defines moved definitions: {sorted(defined_here)}"


@pytest.mark.parametrize("module", sorted(PINS))
def test_stats_module_closure_is_clean_in_a_fresh_process(module: str) -> None:
    code = (
        f"import sys; import breezy.analysis.stats.{module}; "
        f"bad = sorted(m for m in sys.modules if m.startswith({FORBIDDEN_PREFIXES!r})); "
        "print(','.join(bad)); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, (
        f"forbidden modules reached: {proc.stdout.strip()} {proc.stderr[-400:]}"
    )
