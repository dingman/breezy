"""TE-2 pre-freeze: the pins must bind the code that RUNS and the tree that is COMMITTED (I/O).

``TE2_PINS.json`` pins HEAD blob sha256 for the family modules (``head_blob_sha256``) and for the
src/ files Phase B's semantics depend on (``src_dependency_sha256``). Phase B refuses unless, for
every pinned path: the HEAD blob equals the pin, the working file equals the pin, the path is
porcelain-clean and, for a Python module, the module that is actually imported is that very file
(a pin over a different checkout would otherwise prove nothing). The pins file is itself checked:
inside the repo, committed, clean and equal to its HEAD blob; ``predeclaration_commit`` is a full
lowercase sha. ``verify_artefact`` re-checks the same bindings at the artefact commit.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from scripts.analysis.fq_loss_taxonomy_pins import GitPort, RefusalReason, post_hoc_violations
from scripts.analysis.fq_loss_taxonomy_predecl import (
    ANALYSIS_DIR,
    CLI_MODULE,
    SRC_DEPENDENCIES,
    sha256_file,
    unpinned_src_dependencies,
)

CLI_PATH: Final = f"{ANALYSIS_DIR}/{CLI_MODULE}"
PREDECLARATION_PATH: Final = "docs/evidence/te2/TE2_PREDECLARATION.json"
BLOBS_KEY: Final = "head_blob_sha256"
DEPS_KEY: Final = "src_dependency_sha256"
COMMIT_KEY: Final = "predeclaration_commit"
_FULL_SHA: Final = re.compile(r"[0-9a-f]{40}")
#: ``locate(path) -> the file the named module actually runs from`` (``None`` = cannot tell).
ModuleLocator = Callable[[str], Path | None]
#: ``(family blobs, src dependency blobs, predeclaration commit)`` as read from a pins file.
Pinned = tuple[dict[str, str], dict[str, str], str]


# ---- the running module -------------------------------------------------------------------


def _module_names(path: str) -> tuple[str, ...]:
    if not path.endswith(".py"):
        return ()  # a data file (sites.toml) is not a module: only its bytes are bound
    parts = path[:-3].split("/")
    name = ".".join(parts[1:] if parts[0] == "src" else parts)
    return (name, "__main__") if path == CLI_PATH else (name,)


def locate_running(path: str) -> Path | None:
    """The file the imported module for repo-relative ``path`` runs from (``None`` = not loaded)."""
    names = _module_names(path)
    for name in names:
        file = getattr(sys.modules.get(name), "__file__", None)
        if file and (name != "__main__" or Path(file).name == Path(path).name):
            return Path(file).resolve()
    return None  # not imported: it cannot be the code that runs


def _running_refusals(
    repo_root: Path, paths: Mapping[str, str], locate: ModuleLocator
) -> list[str]:
    bad = []
    for path in sorted(paths):
        if not _module_names(path):
            continue
        found = locate(path)
        if found is None or found.resolve() != (repo_root / path).resolve():
            bad.append(path)
    return [f"{RefusalReason.RUNNING_MODULE_MISMATCH.value}: {bad}"] if bad else []


def _working_file_refusals(repo_root: Path, paths: Mapping[str, str]) -> list[str]:
    bad = []
    for path, pinned in sorted(paths.items()):
        try:
            if sha256_file(repo_root / path) != pinned:
                bad.append(path)
        except OSError:
            bad.append(path)
    return [f"{RefusalReason.WORKING_FILE_MISMATCH.value}: {bad}"] if bad else []


# ---- the pins file ------------------------------------------------------------------------


def _str_map(value: Any, what: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ValueError(f"{what} must be an object of strings")
    return dict(value)


def read_pins(pins_json: Path) -> Pinned:
    """Parse a pins file; every defect is an ``OSError`` / ``ValueError`` / ``KeyError``."""
    pins = json.loads(pins_json.read_text())
    if not isinstance(pins, dict):
        raise ValueError("pins file is not a JSON object")  # noqa: TRY004
    commit = pins[COMMIT_KEY]
    if not isinstance(commit, str):
        raise ValueError(f"{COMMIT_KEY} must be a string")  # noqa: TRY004
    return _str_map(pins[BLOBS_KEY], BLOBS_KEY), _str_map(pins[DEPS_KEY], DEPS_KEY), commit


def _relative(repo_root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return None


def pins_file_refusals(repo_root: Path, pins_json: Path, git: GitPort) -> list[str]:
    """The pins file is inside the repo, committed, clean and equal to its HEAD blob."""
    rel = _relative(repo_root, pins_json)
    if rel is None:
        return [RefusalReason.PINS_JSON_OUTSIDE_REPO.value]
    committed = git.blob_sha256("HEAD", rel)
    if committed != sha256_file(pins_json) or not git.porcelain_clean([rel]):
        return [RefusalReason.PINS_JSON_UNCOMMITTED.value]
    return []


def commit_refusals(commit: str) -> list[str]:
    if _FULL_SHA.fullmatch(commit):
        return []
    return [f"{RefusalReason.PREDECLARATION_COMMIT_INVALID.value}: {commit!r}"]


def provenance_refusals(
    repo_root: Path, pins_json: Path, pinned: Pinned, git: GitPort, locate: ModuleLocator
) -> list[str]:
    """Every pins/tree/running-code defect Phase B must refuse on (all checks run)."""
    blobs, deps, commit = pinned
    tracked = {**blobs, **deps}
    reasons = pins_file_refusals(repo_root, pins_json, git) + commit_refusals(commit)
    missing = unpinned_src_dependencies(deps)
    if missing:
        reasons.append(f"{RefusalReason.UNPINNED_SRC_DEPENDENCY.value}: {list(missing)}")
    reasons += _working_file_refusals(repo_root, tracked)
    reasons += _running_refusals(repo_root, tracked, locate)
    return reasons


def generate_src_dependency_sha256(git: GitPort) -> dict[str, str]:
    """``{path: HEAD blob sha256}`` for ``SRC_DEPENDENCIES`` (the pins file's map, regenerated)."""
    return {path: git.head_blob_sha256(path) for path in SRC_DEPENDENCIES}


# ---- the post-hoc verifier ----------------------------------------------------------------


def _committed_clean(git: GitPort, rel: str) -> bool:
    return bool(git.log_commits([rel], "HEAD")) and git.porcelain_clean([rel])


def _provenance_mismatches(
    payload: Mapping[str, Any], pinned: Pinned, pins_blob: str | None, git: GitPort, at: str
) -> list[str]:
    blobs, _deps, commit = pinned
    declared = payload["predeclaration"]
    prov = payload["provenance"]
    pre_blobs = {
        git.blob_sha256(at, PREDECLARATION_PATH),
        git.blob_sha256(commit, PREDECLARATION_PATH),
    }
    expected = {
        "pins_json_sha256": (prov["pins_json_sha256"], {pins_blob}),
        "predeclaration.sha256": (declared["sha256"], pre_blobs),
        "script_sha256": (prov["script_sha256"], {blobs.get(CLI_PATH)}),
    }
    bad = [name for name, (got, want) in expected.items() if want != {got} or got is None]
    if declared["commit"] != commit:
        bad.append("predeclaration.commit")
    return bad


def _artefact_provenance(
    repo_root: Path, pins_json: Path, artefact: Path, pinned: Pinned, git: GitPort, at: str
) -> list[str]:
    try:
        payload = json.loads(artefact.read_text())
        rel = _relative(repo_root, pins_json)
        pins_blob = None if rel is None else git.blob_sha256(at, rel)
        bad = _provenance_mismatches(payload, pinned, pins_blob, git, at)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return [f"{RefusalReason.ARTEFACT_PROVENANCE_MISMATCH.value}: unreadable ({exc!r})"]
    return [f"{RefusalReason.ARTEFACT_PROVENANCE_MISMATCH.value}: {bad}"] if bad else []


def _verify(
    repo_root: Path, pins_json: Path, artefact: Path, pinned: Pinned, git: GitPort
) -> list[str]:
    blobs, deps, commit = pinned
    reasons = commit_refusals(commit)
    rel = _relative(repo_root, artefact)
    if rel is None:
        return [*reasons, "artefact_outside_repo"]
    commits = git.log_commits([rel], "HEAD")
    if not commits or not git.porcelain_clean([rel]):
        return [*reasons, RefusalReason.ARTEFACT_UNCOMMITTED.value]
    at = commits[-1]
    if not reasons:
        reasons += [r.value for r in post_hoc_violations(commit, at, git)]
    changed = [p for p, sha in {**blobs, **deps}.items() if git.blob_sha256(at, p) != sha]
    if changed:
        reasons.append(f"{RefusalReason.PINNED_BLOB_CHANGED_AT_ARTEFACT.value}: {sorted(changed)}")
    missing = unpinned_src_dependencies(deps)
    if missing:
        reasons.append(f"{RefusalReason.UNPINNED_SRC_DEPENDENCY.value}: {list(missing)}")
    siblings = [artefact.with_suffix(".md"), artefact.parent / "phase_b_audit.json"]
    loose = [
        str(p.name)
        for p in siblings
        if (r := _relative(repo_root, p)) is None or not _committed_clean(git, r)
    ]
    if loose:
        reasons.append(f"{RefusalReason.ARTEFACT_SIBLING_UNCOMMITTED.value}: {loose}")
    return reasons + _artefact_provenance(repo_root, pins_json, artefact, pinned, git, at)


def verify_artefact(
    repo_root: Path, pins_json: Path, artefact: Path, git: GitPort
) -> tuple[str, ...]:
    """Post-hoc check (returns the violations; empty = OK, never a traceback): the artefact, its
    ``.md`` and ``phase_b_audit.json`` are committed and clean in a STRICT descendant of the
    predeclaration commit; every pinned blob is unchanged at the artefact commit; the artefact's
    provenance equals the committed pins, predeclaration and script blobs."""
    try:
        pinned = read_pins(pins_json)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return (f"{RefusalReason.PINS_UNUSABLE.value}: {type(exc).__name__}: {exc}",)
    try:
        return tuple(_verify(repo_root, pins_json, artefact, pinned, git))
    except RuntimeError as exc:
        return (f"git_failed: {exc}",)
