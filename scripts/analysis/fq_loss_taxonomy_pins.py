"""TE-2 loss taxonomy: git port, reflog pin resolver, Phase B gates (I/O). Plan S0-D, S0-H.

Downstream code keys on ``BootPin.state``, never on ``commit is not None``: an UNTESTABLE pin may
still record the commit that was identified.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal, Protocol

NEAR_BOUNDARY_S: Final = 120
_ZERO_SHA: Final = "0" * 12
_ROW: Final = re.compile(r"^(\S+)\s+old=(\w+)\s+new=(\w+)\b")
_ABSENT: Final = "<absent>"
#: A closed environment: no inherited GIT_* variable (GIT_DIR, ...) can redirect git.
_GIT_ENV: Final = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C"}


class SnapshotShaMismatch(Exception):
    """The reflog snapshot's sha256 differs from the value pinned in TE2_PINS.json."""


class RefusalReason(StrEnum):
    HEAD_BLOB_MISMATCH = "head_blob_mismatch"
    DIRTY_PINNED_PATH = "dirty_pinned_path"
    PREDECLARATION_NOT_ANCESTOR = "predeclaration_not_ancestor"
    ARTEFACT_NOT_AFTER_PREDECLARATION = "artefact_not_after_predeclaration"


class PinReason(StrEnum):
    NO_PIN = "no_pin"
    CORROBORATION_FAILED = "corroboration_failed"
    NEAR_BOUNDARY_TREE_DIFFERS = "near_boundary_tree_differs"


class GitPort(Protocol):
    def head_blob_sha256(self, path: str) -> str: ...
    def porcelain_clean(self, paths: Sequence[str]) -> bool: ...
    def is_ancestor(self, ancestor: str, descendant: str) -> bool: ...
    def blob_sha256(self, commit: str, path: str) -> str | None: ...
    def tree_shas(self, commit: str, paths: Sequence[str]) -> tuple[str, ...]: ...
    def log_commits(
        self, paths: Sequence[str], until: str, *, since: str | None = None
    ) -> tuple[str, ...]:
        """Commits touching ``paths`` reachable from ``until`` and not from ``since``."""
        ...


class SubprocessGit:
    """The production ``GitPort``: read-only git in ``repo_root`` with a closed environment."""

    def __init__(self, repo_root: Path) -> None:
        self._root = repo_root

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        done = subprocess.run(
            ["git", *args], cwd=self._root, env=_GIT_ENV, capture_output=True, check=False
        )
        if check and done.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed: {done.stderr.decode(errors='replace')}"
            )
        return done

    def head_blob_sha256(self, path: str) -> str:
        return hashlib.sha256(self._run("cat-file", "blob", f"HEAD:{path}").stdout).hexdigest()

    def porcelain_clean(self, paths: Sequence[str]) -> bool:
        out = self._run("status", "--porcelain", "--untracked-files=all", "--", *paths).stdout
        return not out.strip()

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        done = self._run("merge-base", "--is-ancestor", ancestor, descendant, check=False)
        if done.returncode not in (0, 1):
            raise RuntimeError(f"git merge-base failed: {done.stderr.decode(errors='replace')}")
        return done.returncode == 0

    def blob_sha256(self, commit: str, path: str) -> str | None:
        done = self._run("cat-file", "blob", f"{commit}:{path}", check=False)
        return hashlib.sha256(done.stdout).hexdigest() if done.returncode == 0 else None

    def tree_shas(self, commit: str, paths: Sequence[str]) -> tuple[str, ...]:
        shas = []
        for path in paths:
            done = self._run("rev-parse", f"{commit}:{path}", check=False)
            shas.append(done.stdout.decode().strip() if done.returncode == 0 else _ABSENT)
        return tuple(shas)

    def log_commits(
        self, paths: Sequence[str], until: str, *, since: str | None = None
    ) -> tuple[str, ...]:
        span = f"{since}..{until}" if since else until
        out = self._run("log", "--format=%H", span, "--", *paths).stdout.decode()
        return tuple(out.split())


@dataclass(frozen=True)
class Boot:
    number: int
    boot_time: dt.datetime
    logged_manifest_sha256: str
    logged_artefact_sha256: str


@dataclass(frozen=True)
class BootPin:
    boot_number: int
    commit: str | None
    near_boundary: bool
    state: Literal["PINNED", "UNTESTABLE"]
    reason: PinReason | None


@dataclass(frozen=True)
class PinConfig:
    manifest_path: str
    artefact_path: str
    widened_paths: tuple[str, ...]
    near_boundary_s: int = NEAR_BOUNDARY_S


@dataclass(frozen=True)
class _Row:
    when: dt.datetime
    old: str
    new: str


def _parse_snapshot(text: str) -> tuple[list[_Row], list[_Row]]:
    """``(branch_rows, head_rows)`` in file order; ``# source:`` headers delimit sections."""
    branch: list[_Row] = []
    head: list[_Row] = []
    target: list[_Row] | None = None
    for line in text.splitlines():
        if line.startswith("# source:"):
            target = (
                branch if "refs/heads/" in line else head if line.endswith("logs/HEAD") else None
            )
            continue
        found = _ROW.match(line)
        if found is not None and target is not None:
            target.append(_Row(dt.datetime.fromisoformat(found[1]), found[2], found[3]))
    return branch, head


def _entry_at(rows: Sequence[_Row], when: dt.datetime) -> _Row | None:
    """The last row (file order) stamped at or before ``when``."""
    eligible = [r for r in rows if r.when <= when]
    return eligible[-1] if eligible else None


def _no_pin(boot: Boot) -> BootPin:
    return BootPin(boot.number, None, False, "UNTESTABLE", PinReason.NO_PIN)


def _pin_boot(
    boot: Boot,
    row: _Row,
    git: GitPort,
    config: PinConfig,
    reproduces_under: Callable[[int, str], bool] | None,
) -> BootPin:
    commit = row.new
    near = (boot.boot_time - row.when).total_seconds() < config.near_boundary_s

    def pin(state: Literal["PINNED", "UNTESTABLE"], reason: PinReason | None = None) -> BootPin:
        return BootPin(boot.number, commit, near, state, reason)

    logged = (
        (config.manifest_path, boot.logged_manifest_sha256),
        (config.artefact_path, boot.logged_artefact_sha256),
    )
    if any(git.blob_sha256(commit, path) != sha for path, sha in logged):
        return pin("UNTESTABLE", PinReason.CORROBORATION_FAILED)
    if not near:
        return pin("PINNED")
    predecessor = row.old
    same_tree = predecessor != _ZERO_SHA and git.tree_shas(commit, config.widened_paths) == (
        git.tree_shas(predecessor, config.widened_paths)
    )
    both_reproduce = (
        reproduces_under is not None
        and reproduces_under(boot.number, commit)
        and reproduces_under(boot.number, predecessor)
    )
    if same_tree or both_reproduce:
        return pin("PINNED")
    return pin("UNTESTABLE", PinReason.NEAR_BOUNDARY_TREE_DIFFERS)


def resolve_pins(
    snapshot_path: Path,
    expected_snapshot_sha256: str,
    boots: Sequence[Boot],
    git: GitPort,
    config: PinConfig,
    *,
    reproduces_under: Callable[[int, str], bool] | None = None,
) -> tuple[BootPin, ...]:
    """Pin each boot to the last reflog entry at or before it (branch first, HEAD fallback).

    Reads only the committed snapshot (its sha256 must match), never the live reflog and never a
    committer time. Corroborates the manifest and artefact blob shas AT the pinned commit.
    """
    raw = snapshot_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_snapshot_sha256:
        raise SnapshotShaMismatch(f"{snapshot_path} does not match the pinned sha256")
    branch, head = _parse_snapshot(raw.decode("utf-8"))
    pins: list[BootPin] = []
    for boot in boots:
        row = _entry_at(branch, boot.boot_time) or _entry_at(head, boot.boot_time)
        pins.append(
            _no_pin(boot) if row is None else _pin_boot(boot, row, git, config, reproduces_under)
        )
    return tuple(pins)


def pin_label(
    git: GitPort, widened_paths: Sequence[str], since: str, until: str
) -> Literal["STABLE", "INFERRED"]:
    """STABLE iff no commit touched the widened path set in ``since..until``."""
    return "INFERRED" if git.log_commits(widened_paths, until, since=since) else "STABLE"


def phase_b_refusals(
    pinned_blob_sha256: dict[str, str], predeclaration_commit: str, git: GitPort
) -> tuple[RefusalReason, ...]:
    """Every reason Phase B must refuse (all three checks always run)."""
    refusals: list[RefusalReason] = []
    if any(git.head_blob_sha256(path) != sha for path, sha in pinned_blob_sha256.items()):
        refusals.append(RefusalReason.HEAD_BLOB_MISMATCH)
    if not git.porcelain_clean(tuple(pinned_blob_sha256)):
        refusals.append(RefusalReason.DIRTY_PINNED_PATH)
    if not git.is_ancestor(predeclaration_commit, "HEAD"):
        refusals.append(RefusalReason.PREDECLARATION_NOT_ANCESTOR)
    return tuple(refusals)


def refreeze_status(
    frozen: dict[str, str],
    head: dict[str, str],
    new_predeclaration_pins: dict[str, str] | None,
    *,
    old_pre_commit: str,
    new_pre_commit: str | None,
    git: GitPort,
) -> Literal["OK", "REFROZEN", "REFREEZE_REQUIRED"]:
    """A pinned blob that moved needs a NEW predeclaration commit, a strict descendant of the
    old one, whose pins equal the current blobs."""
    if head == frozen:
        return "OK"
    refrozen = (
        new_predeclaration_pins == head
        and new_pre_commit is not None
        and new_pre_commit != old_pre_commit
        and git.is_ancestor(old_pre_commit, new_pre_commit)
    )
    return "REFROZEN" if refrozen else "REFREEZE_REQUIRED"


def post_hoc_violations(
    predeclaration_commit: str, artefact_commit: str, git: GitPort
) -> tuple[RefusalReason, ...]:
    """The result artefact must land in a STRICT descendant of the predeclaration commit."""
    if predeclaration_commit == artefact_commit or not git.is_ancestor(
        predeclaration_commit, artefact_commit
    ):
        return (RefusalReason.ARTEFACT_NOT_AFTER_PREDECLARATION,)
    return ()
