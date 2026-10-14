"""MAKER-S2 WP1: ``load_model``, the clean-tree assertion and ``pin_inputs`` (-> ``pins.json``).

Plan r3 WP1 + r4 delta (c)(g). Pins are content hashes of every mutable input; a verdict run that
cannot pin an input, or whose tree is dirty, does not start.

``load_model`` takes the artefact path and sha from the deploy manifest, then asserts against the
NBP validate evidence doc: its ``artefact_sha256`` (the bullet and the JSON block's
``artefact.sha256``) equals the loaded artefact's sha256, the v5.0 era's ``v5_fit_slice``
``last_climate_day`` equals ``DEFAULT_SPLITS.v5_fit_slice.end`` (2026-06-30), and no era's
``last_climate_day`` is later than that. Any failure, or an unparseable doc, refuses.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Final

from breezy.analysis.nbp_calibration import DEFAULT_SPLITS
from scripts.analysis.maker_stage0_inputs import sha256_bytes, sha256_file

__all__ = [
    "CLEAN_TREE_PATHSPECS",
    "FIT_WINDOW_END",
    "REQUIRED_PIN_KEYS",
    "CatalogSliceManifest",
    "DirtyTree",
    "ModelPin",
    "ModelRefused",
    "PinSources",
    "assert_clean_tree",
    "git_commit",
    "installed_packages",
    "load_model",
    "package_set_sha256",
    "pin_inputs",
    "seal_sidecars",
    "write_pins",
]

CLEAN_TREE_PATHSPECS: Final[tuple[str, ...]] = (
    "scripts/analysis",
    "src",
    "tests",
    "pyproject.toml",
    "uv.lock",
)
FIT_WINDOW_END: Final[dt.date] = dt.date(2026, 6, 30)
DEPLOY_MANIFEST_REL: Final[str] = "deploy/families/pm_us_crh_fq_v1.json"
EVIDENCE_DOC_REL: Final[str] = "docs/evidence/NBP_S2_VALIDATE_RESULT_2026-09-30.md"
UV_LOCK_REL: Final[str] = "uv.lock"
_V5_ERA: Final[str] = "v5.0"
_V5_SPLIT: Final[str] = "v5_fit_slice"
_BULLET_RE: Final[re.Pattern[str]] = re.compile(
    r"^- artefact_sha256: `([0-9a-f]{64})`", re.MULTILINE
)
_JSON_BLOCK_RE: Final[re.Pattern[str]] = re.compile(r"```json\n(.*?)\n```", re.DOTALL)
_CHUNK: Final[int] = 1 << 20

REQUIRED_PIN_KEYS: Final[tuple[str, ...]] = (
    "amendment_final",
    "amendment_final_sha256",
    "argv",
    "artefact",
    "catalog_slice_manifest",
    "census",
    "clean_tree",
    "deploy_manifest",
    "evidence_doc",
    "git_commit",
    "installed_package_set_sha256",
    "ledger_path",
    "model",
    "nbp_consumed",
    "nbp_manifest",
    "node_logs",
    "process_schedule",
    "sidecars",
    "spec",
    "theta_pin_site",
    "trade_unit",
    "truth_cross_check",
    "truth_csv",
    "truth_csv_sha256_frozen_block",
    "uv_lock",
)


class DirtyTree(RuntimeError):
    """``git status --porcelain`` over the declared scope is non-empty (or git is unusable)."""


class ModelRefused(ValueError):
    """The model artefact or its evidence doc failed an assertion."""


# --- git ----------------------------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> str:
    # GIT_CEILING_DIRECTORIES stops discovery above ``repo_root``: a plain directory must not
    # silently adopt an enclosing repository.
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(repo_root.parent)}
    done = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if done.returncode != 0:
        raise DirtyTree(f"git {args[0]} failed in {repo_root}: {done.stderr.strip()[:200]}")
    return done.stdout


def assert_clean_tree(repo_root: Path, pathspecs: Sequence[str] = CLEAN_TREE_PATHSPECS) -> None:
    """Refuse unless ``git status --porcelain -- <pathspecs>`` is empty (untracked included)."""
    dirty = _git(repo_root, "status", "--porcelain", "--", *pathspecs).strip()
    if dirty:
        raise DirtyTree(f"working tree is not clean over {list(pathspecs)}:\n{dirty}")


def git_commit(repo_root: Path) -> str:
    return _git(repo_root, "rev-parse", "HEAD").strip()


# --- package set --------------------------------------------------------------------------


def package_set_sha256(pairs: Iterable[tuple[str, str]]) -> str:
    """sha256 of the sorted ``name==version`` lines (names lower-cased)."""
    lines = sorted(f"{name.lower()}=={version}" for name, version in pairs)
    return sha256_bytes("\n".join(lines).encode())


def installed_packages() -> tuple[tuple[str, str], ...]:
    """The installed distributions, from ``importlib.metadata`` (the one interpreter in use)."""
    found = {
        (dist.metadata["Name"], dist.version)
        for dist in metadata.distributions()
        if dist.metadata["Name"]
    }
    return tuple(sorted(found))


# --- model --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ModelPin:
    family_id: str
    artefact_path: Path
    artefact_sha256: str
    manifest_path: Path
    manifest_sha256: str
    evidence_doc_path: Path
    evidence_doc_sha256: str
    fit_window_end: dt.date


def _parse_doc(text: str) -> tuple[str, str, Mapping[str, Any]]:
    try:
        bullet = _BULLET_RE.search(text)
        block = _JSON_BLOCK_RE.search(text)
        if bullet is None or block is None:
            raise ValueError("no artefact_sha256 bullet or JSON block")
        body = json.loads(block.group(1))
        return bullet.group(1), str(body["artefact"]["sha256"]), dict(body["fit_provenance"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ModelRefused(f"evidence doc unparseable: {type(exc).__name__}: {exc}") from exc


def _last_day(era: str, split: str, entry: Mapping[str, Any]) -> dt.date:
    try:
        return dt.date.fromisoformat(str(entry["last_climate_day"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise ModelRefused(f"evidence doc unparseable: {era} {split} last_climate_day") from exc


def _assert_fit_window(provenance: Mapping[str, Any]) -> None:
    era = provenance.get(_V5_ERA)
    v5 = era.get(_V5_SPLIT) if isinstance(era, dict) else None
    if v5 is None:
        raise ModelRefused(f"evidence doc has no {_V5_ERA} {_V5_SPLIT} entry")
    last = _last_day(_V5_ERA, _V5_SPLIT, v5)
    if last != DEFAULT_SPLITS.v5_fit_slice.end or last != FIT_WINDOW_END:
        raise ModelRefused(
            f"fit window mismatch: doc {last}, DEFAULT_SPLITS {DEFAULT_SPLITS.v5_fit_slice.end}, "
            f"pinned {FIT_WINDOW_END}"
        )
    for era_name, splits in provenance.items():
        for split, entry in dict(splits).items():
            day = _last_day(str(era_name), str(split), entry)
            if day > FIT_WINDOW_END:
                raise ModelRefused(
                    f"{era_name} {split} last_climate_day {day} is after {FIT_WINDOW_END}"
                )


def load_model(
    repo_root: Path,
    *,
    manifest_rel: str = DEPLOY_MANIFEST_REL,
    evidence_doc_rel: str = EVIDENCE_DOC_REL,
) -> ModelPin:
    """Artefact path and sha from the deploy manifest, asserted against the evidence doc."""
    manifest_path = repo_root / manifest_rel
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artefact_path = repo_root / str(manifest["density_artefact_path"])
        pinned = str(manifest["density_artefact_sha256"])
        family_id = str(manifest["family_id"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ModelRefused(f"deploy manifest unusable: {type(exc).__name__}") from exc
    loaded = sha256_file(artefact_path)
    if loaded != pinned:
        raise ModelRefused(f"manifest density_artefact_sha256 {pinned} != artefact bytes {loaded}")
    doc_path = repo_root / evidence_doc_rel
    doc_bytes = doc_path.read_bytes()
    bullet, block_sha, provenance = _parse_doc(doc_bytes.decode("utf-8"))
    if not bullet == block_sha == loaded:
        raise ModelRefused(
            f"evidence doc artefact_sha256 bullet {bullet} / block {block_sha} != loaded {loaded}"
        )
    _assert_fit_window(provenance)
    return ModelPin(
        family_id=family_id,
        artefact_path=artefact_path,
        artefact_sha256=loaded,
        manifest_path=manifest_path,
        manifest_sha256=sha256_file(manifest_path),
        evidence_doc_path=doc_path,
        evidence_doc_sha256=sha256_bytes(doc_bytes),
        fit_window_end=FIT_WINDOW_END,
    )


# --- catalog slice manifest ---------------------------------------------------------------


class CatalogSliceManifest:
    """path, size, mtime and sha256 of every consumed catalog parquet (streamed, 1 MiB chunks)."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, object]] = {}

    def add(self, path: Path) -> None:
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                digest.update(chunk)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f"{path} changed while it was hashed")
        entry: dict[str, object] = {
            "path": str(path),
            "size": after.st_size,
            "mtime_ns": after.st_mtime_ns,
            "sha256": digest.hexdigest(),
        }
        known = self._entries.get(str(path))
        if known is not None and known != entry:
            raise ValueError(f"{path} changed between reads")
        self._entries[str(path)] = entry

    def to_dict(self) -> dict[str, Any]:
        return {"files": [self._entries[key] for key in sorted(self._entries)]}

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return path


# --- pins ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class PinSources:
    repo_root: Path
    census: Path
    trade_unit: Path
    truth_copy: Path
    truth_cross_check: Path
    truth_csv_sha256: str
    nbp_manifest: Path
    nbp_consumed: Sequence[tuple[str, str]]
    process_schedule: Path
    catalog_slice_manifest: Path
    amendment_final: Path
    ledger_path: Path
    node_logs: Sequence[Path]
    sidecar_names: Sequence[str]
    argv: Sequence[str]
    theta_pin_site: str
    spec: Path
    packages: Sequence[tuple[str, str]] | None = None
    deploy_manifest_rel: str = DEPLOY_MANIFEST_REL
    evidence_doc_rel: str = EVIDENCE_DOC_REL


def _file_pin(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256_file(path), "size": path.stat().st_size}


def _node_log_pin(path: Path) -> dict[str, Any]:
    pin = _file_pin(path)
    return {**pin, "byte_range": [0, pin["size"]]}


def _consumed_pin(consumed: Iterable[tuple[str, str]]) -> dict[str, Any]:
    cycles = sorted([cycle, raw_sha] for cycle, raw_sha in consumed)
    body = json.dumps(cycles, separators=(",", ":")).encode()
    return {"cycles": cycles, "sha256": sha256_bytes(body)}


def _model_pin(model: ModelPin) -> dict[str, Any]:
    return {
        "family_id": model.family_id,
        "artefact_sha256": model.artefact_sha256,
        "manifest_sha256": model.manifest_sha256,
        "evidence_doc_sha256": model.evidence_doc_sha256,
        "fit_window_end": model.fit_window_end.isoformat(),
    }


def pin_inputs(src: PinSources) -> dict[str, Any]:
    """Hash every mutable input; refuses a dirty tree, a bad model or an unreadable input."""
    root = src.repo_root
    assert_clean_tree(root)
    model = load_model(
        root, manifest_rel=src.deploy_manifest_rel, evidence_doc_rel=src.evidence_doc_rel
    )
    packages = installed_packages() if src.packages is None else src.packages
    amendment = _file_pin(src.amendment_final)
    return {
        "amendment_final": amendment,
        "amendment_final_sha256": amendment["sha256"],
        "argv": list(src.argv),
        "artefact": _file_pin(model.artefact_path),
        "catalog_slice_manifest": _file_pin(src.catalog_slice_manifest),
        "census": _file_pin(src.census),
        "clean_tree": {"clean": True, "pathspecs": list(CLEAN_TREE_PATHSPECS)},
        "deploy_manifest": _file_pin(model.manifest_path),
        "evidence_doc": _file_pin(model.evidence_doc_path),
        "git_commit": git_commit(root),
        "installed_package_set_sha256": package_set_sha256(packages),
        "ledger_path": str(src.ledger_path),
        "model": _model_pin(model),
        "nbp_consumed": _consumed_pin(src.nbp_consumed),
        "nbp_manifest": _file_pin(src.nbp_manifest),
        "node_logs": [_node_log_pin(path) for path in src.node_logs],
        "process_schedule": _file_pin(src.process_schedule),
        "sidecars": {name: {"run_time_only": True, "sha256": None} for name in src.sidecar_names},
        "spec": _file_pin(src.spec),
        "theta_pin_site": src.theta_pin_site,
        "trade_unit": _file_pin(src.trade_unit),
        "truth_cross_check": _file_pin(src.truth_cross_check),
        "truth_csv": _file_pin(src.truth_copy),
        "truth_csv_sha256_frozen_block": src.truth_csv_sha256,
        "uv_lock": _file_pin(root / UV_LOCK_REL),
    }


def write_pins(run_dir: Path, pins: Mapping[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "pins.json"
    out.write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def seal_sidecars(pins: Mapping[str, Any], run_dir: Path) -> dict[str, Any]:
    """Fill each run-time-only sidecar's sha256 from ``run_dir`` (returns a new mapping)."""
    sealed = {
        name: {"run_time_only": True, "sha256": sha256_file(run_dir / name)}
        for name in pins["sidecars"]
    }
    return {**pins, "sidecars": sealed}
