"""MAKER-S2 WP1: ``load_model``, the clean-tree assertion and ``pin_inputs`` (-> ``pins.json``).

Plan r3 WP1 + r4 delta (c)(g). Pins are content hashes of every mutable input; a verdict run that
cannot pin an input, whose tree is dirty, whose truth copy is not the frozen block's file, or
whose canonical sidecar set is incomplete, does not start. ``load_model`` lives in
``maker_stage0_model``. Every file written here is written atomically (``.tmp`` + ``os.replace``).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Final

from scripts.analysis.maker_stage0_frozen import load_amendment
from scripts.analysis.maker_stage0_inputs import sha256_bytes, sha256_file, write_text_atomic
from scripts.analysis.maker_stage0_model import (
    DEPLOY_MANIFEST_REL,
    EVIDENCE_DOC_REL,
    ModelPin,
    load_model,
)

__all__ = [
    "CANONICAL_SIDECARS",
    "CLEAN_TREE_PATHSPECS",
    "REQUIRED_PIN_KEYS",
    "CatalogSliceManifest",
    "DirtyTree",
    "PinRefused",
    "PinSources",
    "assert_clean_tree",
    "git_commit",
    "installed_packages",
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
UV_LOCK_REL: Final[str] = "uv.lock"
GIT_TIMEOUT_S: Final[int] = 30
#: The run-time-only sidecars every verdict run must declare (sealed by ``seal_sidecars``).
CANONICAL_SIDECARS: Final[tuple[str, ...]] = (
    "overlay_station_days.csv",
    "process_schedule_overlay.json",
    "progress.jsonl",
    "stress_plus60_station_days.csv",
    "stress_poll_lag_station_days.csv",
    "wp0_agreement.json",
)
_PEP503_RE: Final[re.Pattern[str]] = re.compile(r"[-_.]+")

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


class PinRefused(ValueError):
    """An input cannot be pinned: it contradicts the frozen block or the canonical set."""


# --- git ----------------------------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> str:
    # GIT_CEILING_DIRECTORIES stops discovery above ``repo_root``: a plain directory must not
    # silently adopt an enclosing repository.
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(repo_root.parent)}
    try:
        done = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=GIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise DirtyTree(f"git {args[0]} timed out after {GIT_TIMEOUT_S} s in {repo_root}") from exc
    except OSError as exc:  # git absent / not executable
        raise DirtyTree(
            f"git {args[0]} could not run ({type(exc).__name__}) in {repo_root}"
        ) from exc
    if done.returncode != 0:
        raise DirtyTree(f"git {args[0]} failed in {repo_root}: {done.stderr.strip()[:200]}")
    return done.stdout


def assert_clean_tree(repo_root: Path, pathspecs: Sequence[str] = CLEAN_TREE_PATHSPECS) -> None:
    """Refuse unless ``git status --porcelain -- <pathspecs>`` is empty (untracked included).

    ``--untracked-files=all`` overrides ``status.showUntrackedFiles`` so a configured ``no``
    cannot hide a new file.
    """
    dirty = _git(
        repo_root, "status", "--porcelain", "--untracked-files=all", "--", *pathspecs
    ).strip()
    if dirty:
        raise DirtyTree(f"working tree is not clean over {list(pathspecs)}:\n{dirty}")


def git_commit(repo_root: Path) -> str:
    return _git(repo_root, "rev-parse", "HEAD").strip()


# --- package set --------------------------------------------------------------------------


def package_set_sha256(pairs: Iterable[tuple[str, str]]) -> str:
    """sha256 of the sorted ``name==version`` lines (names PEP 503-normalised)."""
    lines = sorted(f"{_PEP503_RE.sub('-', name).lower()}=={version}" for name, version in pairs)
    return sha256_bytes("\n".join(lines).encode())


def installed_packages() -> tuple[tuple[str, str], ...]:
    """The installed distributions, from ``importlib.metadata`` (the one interpreter in use)."""
    found = {
        (dist.metadata["Name"], dist.version)
        for dist in metadata.distributions()
        if dist.metadata["Name"]
    }
    return tuple(sorted(found))


# --- catalog slice manifest ---------------------------------------------------------------


class CatalogSliceManifest:
    """path, size, mtime and sha256 of every consumed catalog parquet (streamed, 1 MiB chunks)."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, object]] = {}
        self._stamps: dict[str, tuple[int, int]] = {}

    def add(self, path: Path) -> None:
        before = path.stat()
        digest = sha256_file(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f"{path} changed while it was hashed")
        entry: dict[str, object] = {
            "path": str(path),
            "size": after.st_size,
            "mtime_ns": after.st_mtime_ns,
            "sha256": digest,
        }
        known = self._entries.get(str(path))
        if known is not None and known != entry:
            raise ValueError(f"{path} changed between reads")
        self._entries[str(path)] = entry

    def add_capture_file(self, root: Path, path: Path) -> None:
        """Record a CAPTURE file by its path relative to ``root``: size and sha256 only.

        No mtime and no absolute path enter the manifest, so it is identical across runs, work
        roots and scratch re-conversions. A re-read of an unchanged file costs one ``stat``.
        """
        rel = path.relative_to(root).as_posix()
        before = path.stat()
        stamp = (before.st_size, before.st_mtime_ns)
        if self._stamps.get(rel) == stamp:
            return
        digest = sha256_file(path)
        after = path.stat()
        if (after.st_size, after.st_mtime_ns) != stamp:
            raise ValueError(f"{path} changed while it was hashed")
        entry: dict[str, object] = {"path": rel, "size": after.st_size, "sha256": digest}
        known = self._entries.get(rel)
        if known is not None and known != entry:
            raise ValueError(f"{path} changed between reads")
        self._entries[rel], self._stamps[rel] = entry, stamp

    def merge(self, other: CatalogSliceManifest) -> None:
        """Absorb another manifest's entries (a station-day child's); a differing entry is fatal."""
        for key, entry in other._entries.items():
            known = self._entries.get(key)
            if known is not None and known != entry:
                raise ValueError(f"{key} changed between reads")
            self._entries[key] = entry
            if key in other._stamps:
                self._stamps[key] = other._stamps[key]

    def to_dict(self) -> dict[str, Any]:
        return {"files": [self._entries[key] for key in sorted(self._entries)]}

    def write(self, path: Path) -> Path:
        return write_text_atomic(path, json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")


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


def _assert_canonical_sidecars(names: Sequence[str]) -> None:
    missing = sorted(set(CANONICAL_SIDECARS) - set(names))
    if missing:
        raise PinRefused(f"sidecars lack the canonical names {missing}")


def _assert_truth_matches_frozen_block(src: PinSources, amendment_sha: str, truth_sha: str) -> None:
    """Re-parse the FINAL amendment; the pinned truth copy must be the block's file."""
    block_sha = load_amendment(src.amendment_final, amendment_sha).truth_csv_sha256
    if not truth_sha == block_sha == src.truth_csv_sha256:
        raise PinRefused(
            f"truth copy sha {truth_sha} / frozen block {block_sha} / caller "
            f"{src.truth_csv_sha256} disagree"
        )


def pin_inputs(src: PinSources) -> dict[str, Any]:
    """Hash every mutable input; refuses a dirty tree, a bad model or an unreadable input."""
    root = src.repo_root
    assert_clean_tree(root)
    _assert_canonical_sidecars(src.sidecar_names)
    model = load_model(
        root, manifest_rel=src.deploy_manifest_rel, evidence_doc_rel=src.evidence_doc_rel
    )
    packages = installed_packages() if src.packages is None else src.packages
    amendment = _file_pin(src.amendment_final)
    truth = _file_pin(src.truth_copy)
    _assert_truth_matches_frozen_block(src, amendment["sha256"], truth["sha256"])
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
        "truth_csv": truth,
        "truth_csv_sha256_frozen_block": src.truth_csv_sha256,
        "uv_lock": _file_pin(root / UV_LOCK_REL),
    }


def write_pins(run_dir: Path, pins: Mapping[str, Any]) -> Path:
    return write_text_atomic(
        run_dir / "pins.json", json.dumps(pins, indent=2, sort_keys=True) + "\n"
    )


def seal_sidecars(pins: Mapping[str, Any], run_dir: Path) -> dict[str, Any]:
    """Fill each run-time-only sidecar's sha256 from ``run_dir`` (returns a new mapping)."""
    names = pins.get("sidecars")
    if not isinstance(names, Mapping):
        raise PinRefused("pins carry no 'sidecars' mapping to seal")
    sealed: dict[str, Any] = {}
    for name in names:
        try:
            sealed[name] = {"run_time_only": True, "sha256": sha256_file(run_dir / name)}
        except OSError as exc:
            raise PinRefused(
                f"sidecar {name} unreadable in {run_dir} ({type(exc).__name__})"
            ) from exc
    return {**pins, "sidecars": sealed}
