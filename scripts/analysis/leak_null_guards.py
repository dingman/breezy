"""Fail-closed I/O, freeze and code-provenance guards for LEAK-NULL."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from scipy import special

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from breezy.analysis.leak_null_decide import THRESHOLDS
from scripts.analysis import multisource_blend_skill as skill
from scripts.analysis.multisource_blend_pin_guards import check_not_refrozen
from scripts.analysis.prereg_precommit_check import check_frozen_blob

Refusal = skill.Refusal

# Frozen literal; asserted equal to leak_null_decide.THRESHOLDS immediately below.
FROZEN_THRESHOLDS: Final[dict[str, float | int]] = {
    "lb_gt": 0.0,
    "leak_mean_min": 0.005,
    "fluke_count_max": 2,
    "benign_n2_ratio_max": 0.25,
    "benign_n3_ratio_min": 0.5,
    "invariant_tol": 1e-9,
    "max_failed_seeds": 2,
    "min_moved_fraction": 0.5,
    "k": 20,
    "pc_k": 5,
    "t_crit_k20": 2.093,
    "t_crit_pc5": 2.776,
    "plant_noise_sd_f": 1.0,
}
if FROZEN_THRESHOLDS != asdict(THRESHOLDS):
    raise RuntimeError("FROZEN_THRESHOLDS drifted from leak_null_decide.THRESHOLDS")
PINNED_BLOBS: Final[tuple[str, ...]] = (
    "src/breezy/analysis/leak_null.py",
    "src/breezy/analysis/leak_null_decide.py",
    "src/breezy/analysis/multisource_blend_fit.py",
    "src/breezy/analysis/multisource_blend_folds.py",
    "src/breezy/analysis/multisource_blend_stats.py",
    "src/breezy/analysis/multisource_blend_features.py",
    "src/breezy/analysis/multisource_blend.py",
    "scripts/analysis/leak_null_guards.py",
    "scripts/analysis/leak_null_study.py",
    "scripts/analysis/multisource_blend_skill.py",
)
INPUT_ROLES: Final = frozenset(("f13_prereg", "features", "lag_features", "c1_evidence"))
FORBIDDEN_BASENAMES: Final = frozenset(
    ("result.json", "murphy.json", "stage_a.json", "oof_rows.jsonl")
)
_CODE_SHA: Final = re.compile(r"[0-9a-f]{40}")
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_OUT_NAME: Final = re.compile(r"leak_null_\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class LeakNullDesign:
    prereg_path: Path
    prereg_sha256: str
    frozen_sha: str
    code_sha: str
    pinned_blobs: tuple[str, ...]
    inputs: Mapping[str, Mapping[str, Any]]
    seeds: tuple[int, ...]
    probe_seed: int
    thresholds: Mapping[str, float | int]
    f13_record: Mapping[str, Any]
    out_root: Path

    @property
    def pc_seeds(self) -> tuple[int, ...]:
        return self.seeds[:5]


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise Refusal(f"cannot read {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError as exc:
        raise Refusal(f"cannot hash {path}: {exc}") from exc


def _object(payload: bytes, label: object) -> dict[str, Any]:
    try:
        raw = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise Refusal(f"{label}: invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise Refusal(f"{label}: must be a JSON object")
    return raw


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _check_seeds(raw: Mapping[str, Any]) -> tuple[int, ...]:
    seeds, probe = raw.get("seeds"), raw.get("probe_seed")
    if not isinstance(seeds, list) or len(seeds) != 20:
        raise Refusal("seeds: K must equal 20 exactly")
    if type(probe) is not int or probe == 20261006:
        raise Refusal("probe_seed must be an int other than the F13 seed")
    if any(type(s) is not int for s in seeds):
        raise Refusal("seeds must be ints (not bools)")
    if len(set(seeds)) != 20 or {20261006, probe}.intersection(seeds):
        raise Refusal("seeds must be distinct and exclude 20261006 and probe_seed")
    return tuple(seeds)


def _check_thresholds(raw: object) -> Mapping[str, float | int]:
    if not isinstance(raw, dict) or set(raw) - {"source"} != set(FROZEN_THRESHOLDS):
        raise Refusal("thresholds must contain exactly the frozen threshold pins")
    for key, expected in FROZEN_THRESHOLDS.items():
        value = raw[key]
        if not _number(value) or value != expected:
            raise Refusal(f"thresholds.{key} differs from the frozen threshold")
        if type(expected) is int and type(value) is not int:
            raise Refusal(f"thresholds.{key} must be an int")
    for n, key in ((20, "t_crit_k20"), (5, "t_crit_pc5")):
        actual = float(special.stdtrit(n - 1, 0.975))
        if not math.isfinite(actual) or abs(actual - raw[key]) >= 5e-4:
            raise Refusal(f"t-pin {key} differs from scipy.special.stdtrit")
    return MappingProxyType({key: raw[key] for key in FROZEN_THRESHOLDS})


def _check_f13(raw: object) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise Refusal("f13_record must be an object")
    for key in ("m0p_vs_m3_mean", "m0p_vs_m3_lb"):
        if not _number(raw.get(key)):
            raise Refusal(f"f13_record.{key} must be finite")
    if "floor" not in raw or (
        raw["floor"] is not None and (not _number(raw["floor"]) or raw["floor"] < 0)
    ):
        raise Refusal("f13_record.floor must be null or finite and non-negative")
    if not isinstance(raw.get("source"), str) or not raw["source"].strip():
        raise Refusal("f13_record.source must name the transcribed evidence")
    record = dict(raw)
    record["floor_check"] = "unavailable" if raw["floor"] is None else "available"
    return MappingProxyType(record)


def _check_inputs(raw: object) -> Mapping[str, Mapping[str, Any]]:
    if not isinstance(raw, dict) or set(raw) != INPUT_ROLES:
        raise Refusal(f"inputs must pin exactly {sorted(INPUT_ROLES)}")
    for role, spec in raw.items():
        if (
            not isinstance(spec, Mapping)
            or not isinstance(spec.get("path"), str)
            or not spec["path"]
        ):
            raise Refusal(f"inputs.{role} must pin a path")
        keys = {"sha256", "content_sha256"}.intersection(spec)
        if not keys or (role != "f13_prereg" and "sha256" not in keys):
            raise Refusal(f"inputs.{role} must pin sha256")
        if any(not isinstance(spec[k], str) or not _SHA256.fullmatch(spec[k]) for k in keys):
            raise Refusal(f"inputs.{role}: invalid sha256")
    return MappingProxyType({role: MappingProxyType(dict(spec)) for role, spec in raw.items()})


def _check_freeze(path: Path, raw: Mapping[str, Any], allow_unfrozen: bool) -> None:
    if raw.get("frozen_sha") == skill.UNFROZEN:
        if allow_unfrozen:
            return
        raise Refusal("frozen_sha is UNFROZEN; only the timing probe permits a draft")
    defects = check_frozen_blob(path, raw)
    if defects:
        raise Refusal("; ".join(f"[{d.code}] {d.message}" for d in defects))
    check_not_refrozen(path)


def load_leak_prereg(path: Path, *, allow_unfrozen: bool = False) -> LeakNullDesign:
    """Validate the frozen design; a draft is admissible only for a timing probe."""
    path = path.resolve()
    payload = _read(path)
    raw = _object(payload, path)
    seeds = _check_seeds(raw)
    thresholds = _check_thresholds(raw.get("thresholds"))
    record = _check_f13(raw.get("f13_record"))
    inputs = _check_inputs(raw.get("inputs"))
    code_sha, paths = raw.get("code_sha"), raw.get("pinned_blobs")
    if not isinstance(code_sha, str) or not _CODE_SHA.fullmatch(code_sha):
        raise Refusal("code_sha must be a full lowercase git SHA")
    if (
        not isinstance(paths, list)
        or any(not isinstance(p, str) for p in paths)
        or len(paths) != len(PINNED_BLOBS)
        or set(paths) != set(PINNED_BLOBS)
    ):
        raise Refusal("pinned_blobs must name all ten frozen repo-relative modules exactly once")
    if not isinstance(raw.get("out_root"), str) or not raw["out_root"]:
        raise Refusal("out_root must be a path")
    _check_freeze(path, raw, allow_unfrozen)
    return LeakNullDesign(
        prereg_path=path,
        prereg_sha256=hashlib.sha256(payload).hexdigest(),
        frozen_sha=raw["frozen_sha"],
        code_sha=code_sha,
        pinned_blobs=tuple(paths),
        inputs=inputs,
        seeds=seeds,
        probe_seed=raw["probe_seed"],
        thresholds=thresholds,
        f13_record=record,
        out_root=Path(raw["out_root"]).expanduser().resolve(),
    )


def guard_out_dir(path: Path, out_root: Path) -> Path:
    """Check both lexical and resolved paths before creating any output."""
    raw = path.expanduser().absolute()
    resolved = raw.resolve()
    live = Path.home() / ".local/share/breezy"
    for candidate in (raw, resolved):
        if any(part.startswith("gap1_j3_") for part in candidate.parts):
            raise Refusal("out dir contains a forbidden gap1_j3_* component")
        if candidate.is_relative_to(live) or candidate.is_relative_to(live.resolve()):
            raise Refusal("out dir is under the live data root")
    if not _OUT_NAME.fullmatch(raw.name) or not _OUT_NAME.fullmatch(resolved.name):
        raise Refusal("out dir basename must match leak_null_YYYY-MM-DD")
    if not resolved.is_relative_to(out_root.expanduser().resolve()):
        raise Refusal("out dir must be inside out_root")
    return resolved


def guard_probe_parent(path: Path, out_root: Path) -> Path:
    """The temporary timing context must remain outside the study output tree."""
    resolved = path.expanduser().resolve()
    if resolved.is_relative_to(out_root.expanduser().resolve()):
        raise Refusal("probe_parent must be outside out_root")
    if not resolved.is_dir():
        raise Refusal(f"probe_parent must be an existing directory: {resolved}")
    return resolved


def _input_path(spec: Mapping[str, Any]) -> Path:
    raw = Path(spec["path"]).expanduser()
    path = raw if raw.is_absolute() else ROOT / raw
    if raw.name in FORBIDDEN_BASENAMES or path.resolve().name in FORBIDDEN_BASENAMES:
        raise Refusal(f"forbidden input basename: {raw}")
    return path


def verify_inputs(design: LeakNullDesign) -> dict[str, str]:
    """Open only pinned inputs, rejecting sealed basenames before any read."""
    specs = _check_inputs(dict(design.inputs))
    paths = {role: _input_path(spec) for role, spec in specs.items()}
    shas = {}
    for role, spec in specs.items():
        digest = _sha256(paths[role])
        if "sha256" in spec and digest != spec["sha256"]:
            raise Refusal(f"inputs.{role}: sha256 mismatch")
        if "content_sha256" in spec or "frozen_sha" in spec:
            raw = _object(_read(paths[role]), paths[role])
            if "content_sha256" in spec and skill.content_digest(raw) != spec["content_sha256"]:
                raise Refusal(f"inputs.{role}: content_sha256 mismatch")
            if "frozen_sha" in spec and raw.get("frozen_sha") != spec["frozen_sha"]:
                raise Refusal(f"inputs.{role}: frozen_sha mismatch")
        shas[role] = digest
    return shas


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refusal(f"code pin: git failed: {exc}") from exc


def _git_value(repo: Path, *args: str) -> str:
    done = _git(repo, *args)
    if done.returncode != 0:
        raise Refusal(f"code pin: cannot verify blob/commit ({' '.join(args)})")
    return done.stdout.strip()


def code_ok(repo: Path, older: str, newer: str) -> bool:
    """Equal, or older is an ancestor of newer; only full lowercase SHAs count."""
    if not (_CODE_SHA.fullmatch(older) and _CODE_SHA.fullmatch(newer)):
        return False
    if older == newer:
        return True
    return _git(repo, "merge-base", "--is-ancestor", older, newer).returncode == 0


def _pinned_path(repo: Path, name: str) -> Path:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != name or not name:
        raise Refusal(f"pinned blob must be repo-relative: {name}")
    resolved = (repo / path).resolve()
    if not resolved.is_relative_to(repo.resolve()):
        raise Refusal(f"pinned blob escapes repo-relative root: {name}")
    return resolved


def _check_loaded_module(name: str, expected: Path) -> str | None:
    """Refuse a module loaded from outside the repo; note (not fail) one not loaded."""
    parts = Path(name).with_suffix("").parts
    module_name = ".".join(parts[1:] if parts[0] == "src" else parts)
    module = sys.modules.get(module_name)
    if module is None:
        return f"pinned module {module_name} not loaded; origin check skipped"
    loaded = getattr(module, "__file__", None)
    if not isinstance(loaded, str) or Path(loaded).resolve() != expected:
        raise Refusal(f"pinned module {module_name} loaded from outside repo: {loaded}")
    return None


def check_code_pin(repo: Path, code_sha: str, paths: Sequence[str]) -> list[str]:
    """Check ancestry, worktree/HEAD blobs, and already-loaded module origins.

    Returns notes for pinned modules whose origin check was skipped (not loaded).
    """
    head = _git_value(repo, "rev-parse", "HEAD")
    if not code_ok(repo, code_sha, head):
        raise Refusal("code_sha is not HEAD or an ancestor of HEAD")
    if not paths:
        raise Refusal("code pin has no pinned blobs")
    notes: list[str] = []
    for name in paths:
        expected_path = _pinned_path(repo, name)
        expected = _git_value(repo, "rev-parse", f"{code_sha}:{name}")
        current = _git_value(repo, "hash-object", "--", name)
        committed = _git_value(repo, "rev-parse", f"HEAD:{name}")
        if current != expected or committed != expected:
            raise Refusal(f"code pin blob drift: {name}")
        note = _check_loaded_module(name, expected_path)
        if note:
            notes.append(note)
    return notes


def _provenance(design: LeakNullDesign, shas: Mapping[str, str]) -> dict[str, Any]:
    return {
        "prereg_sha256": design.prereg_sha256,
        "frozen_sha": design.frozen_sha,
        "code_sha": design.code_sha,
        "input_shas": dict(shas),
    }


def _check_provenance(path: Path, expected: Mapping[str, Any]) -> None:
    if path.is_symlink() or _object(_read(path), "provenance") != expected:
        raise Refusal("provenance differs from the write-once record")


def record_provenance(out: Path, design: LeakNullDesign, shas: Mapping[str, str]) -> None:
    """Create exclusively, or verify an identical record without rewriting it."""
    if hashlib.sha256(_read(design.prereg_path)).hexdigest() != design.prereg_sha256:
        raise Refusal("prereg digest changed before recording provenance")
    if dict(shas) != verify_inputs(design):
        raise Refusal("provenance input sha256 mismatch")
    expected = _provenance(design, shas)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "provenance.json"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(expected, sort_keys=True, indent=2) + "\n")
    except FileExistsError:
        _check_provenance(path, expected)
    except OSError as exc:
        raise Refusal(f"cannot write provenance: {exc}") from exc


def assert_unchanged(out: Path, prereg_path: Path, design: LeakNullDesign, repo: Path) -> None:
    """Revalidate the frozen prereg, inputs, provenance and code before a result."""
    again = load_leak_prereg(prereg_path, allow_unfrozen=False)
    if again.prereg_path != design.prereg_path or again.prereg_sha256 != design.prereg_sha256:
        raise Refusal("prereg digest changed; the result must not be written")
    _check_provenance(out / "provenance.json", _provenance(design, verify_inputs(again)))
    check_code_pin(repo, design.code_sha, design.pinned_blobs)
