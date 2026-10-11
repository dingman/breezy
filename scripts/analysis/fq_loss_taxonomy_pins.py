"""TE-2 loss taxonomy: git port, reflog pin resolver, Phase B gates (I/O). WP0 stub.

Downstream code keys on ``BootPin.state``, never on ``commit is not None``: an UNTESTABLE pin may
still record the commit that was identified.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal, Protocol

NEAR_BOUNDARY_S: Final = 120


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
    """The production ``GitPort``: read-only git in ``repo_root`` with ``GIT_*`` env cleared."""

    def __init__(self, repo_root: Path) -> None:
        raise NotImplementedError

    def head_blob_sha256(self, path: str) -> str:
        raise NotImplementedError

    def porcelain_clean(self, paths: Sequence[str]) -> bool:
        raise NotImplementedError

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        raise NotImplementedError

    def blob_sha256(self, commit: str, path: str) -> str | None:
        raise NotImplementedError

    def tree_shas(self, commit: str, paths: Sequence[str]) -> tuple[str, ...]:
        raise NotImplementedError

    def log_commits(
        self, paths: Sequence[str], until: str, *, since: str | None = None
    ) -> tuple[str, ...]:
        raise NotImplementedError


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


def resolve_pins(
    snapshot_path: Path,
    expected_snapshot_sha256: str,
    boots: Sequence[Boot],
    git: GitPort,
    config: PinConfig,
    *,
    reproduces_under: Callable[[int, str], bool] | None = None,
) -> tuple[BootPin, ...]:
    raise NotImplementedError


def pin_label(
    git: GitPort, widened_paths: Sequence[str], since: str, until: str
) -> Literal["STABLE", "INFERRED"]:
    raise NotImplementedError


def phase_b_refusals(
    pinned_blob_sha256: dict[str, str], predeclaration_commit: str, git: GitPort
) -> tuple[RefusalReason, ...]:
    raise NotImplementedError


def refreeze_status(
    frozen: dict[str, str],
    head: dict[str, str],
    new_predeclaration_pins: dict[str, str] | None,
    *,
    old_pre_commit: str,
    new_pre_commit: str | None,
    git: GitPort,
) -> Literal["OK", "REFROZEN", "REFREEZE_REQUIRED"]:
    raise NotImplementedError


def post_hoc_violations(
    predeclaration_commit: str, artefact_commit: str, git: GitPort
) -> tuple[RefusalReason, ...]:
    raise NotImplementedError
