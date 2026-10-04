"""``drill_marker/v1``: the record and its directory-descriptor read (ARCH-0 AC 24; AUT-7 r5).

The marker is the single file ``registry/drill/marker.json``. This module owns the record and the
read; the writer and the stale-marker sweep belong to AUT-7. The read has three outcomes:

* ``DrillMarker``: the file parsed and every field is exact.
* ``MarkerAbsent``: ENOENT on the marker, inside a directory that is safe. The only clean state.
* ``MarkerError``: everything else, including ENOENT on the directory itself. It never reads as
  absent, so a detector cannot pass on a state it could not see.

The directory is opened ``O_DIRECTORY|O_NOFOLLOW`` and ``fstat``-checked (a directory, this uid,
mode exactly 0700); the marker is then ``openat``-ed ``O_NOFOLLOW`` and read once, at most
``MAX_MARKER_BYTES``. Binding the marker to an episode, a window or a root is the detector's job:
this module reports the bytes, and ``registry_root`` carries the root key. Error details are
closed codes, never paths.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Final, Self

from breezy.persistence.autonomy.canonical import sha256_hex
from breezy.persistence.autonomy.paths import (
    AutonomyPaths,
    ShadowPaths,
    family_component,
    venue_component,
)
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    open_root,
    read_once_at,
    walk_dirs,
)
from breezy.persistence.autonomy.wire import (
    WireRefusalReason,
    WireRefused,
    check_int,
    check_match,
    check_sha256,
    optional_sha256,
    parse_json_exact,
    require_enum,
    require_exact_keys,
    require_ns,
    require_sha256,
    require_str,
)

__all__ = [
    "MAX_MARKER_BYTES",
    "DrillDetector",
    "DrillMarker",
    "DrillStep",
    "MarkerAbsent",
    "MarkerError",
    "MarkerErrorReason",
    "read_marker",
    "read_marker_at",
]

DRILL_MARKER_SCHEMA: Final = "drill_marker/v1"
MAX_MARKER_BYTES: Final = 4096
#: Relative to the registry root; ``test_drill_marker_layout_matches_the_paths_builder`` pins both
#: to ``AutonomyPaths.drill_marker``.
MARKER_DIR_PARTS: Final = ("registry", "drill")
MARKER_NAME: Final = "marker.json"
_DIR_MODE: Final = 0o700
_EPISODE_RE: Final = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
_ROOT_RE: Final = re.compile(r"\A/[\x20-\x7e]{0,1023}\Z", re.ASCII)
_KEYS: Final = (
    "schema", "registry_root", "venue", "episode_id", "child_id", "detector", "step",
    "window_start_ns", "window_end_ns", "abort_record_sha256", "drill_clause_sha256", "ts_ns",
)  # fmt: skip


class DrillDetector(StrEnum):
    DRILL_INJECT = "DRILL_INJECT"
    DRILL_INJECT_HALT = "DRILL_INJECT_HALT"


class DrillStep(StrEnum):
    DEMOTE = "demote"
    HALT = "halt"
    ABORT_HALT = "abort_halt"


#: ``demote`` pairs only with ``DRILL_INJECT``; ``halt`` and ``abort_halt`` only with the HALT one.
_STEP_DETECTOR: Final = {
    DrillStep.DEMOTE: DrillDetector.DRILL_INJECT,
    DrillStep.HALT: DrillDetector.DRILL_INJECT_HALT,
    DrillStep.ABORT_HALT: DrillDetector.DRILL_INJECT_HALT,
}


def _bad(field: str) -> WireRefused:
    return WireRefused(WireRefusalReason.BAD_VALUE, field)


@dataclass(frozen=True, kw_only=True)
class DrillMarker:
    """``drill_marker/v1``: twelve keys, exact set."""

    registry_root: str
    venue: str
    episode_id: str
    child_id: str
    detector: DrillDetector
    step: DrillStep
    window_start_ns: int
    window_end_ns: int
    abort_record_sha256: str | None
    drill_clause_sha256: str
    ts_ns: int
    #: sha256 of the exact bytes the read returned (never a wire key; ignored by equality).
    raw_sha256: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        check_match(self.registry_root, _ROOT_RE, "registry_root")
        venue_component(self.venue)
        family_component(self.child_id)
        check_match(self.episode_id, _EPISODE_RE, "episode_id")
        for name, enum in (("detector", DrillDetector), ("step", DrillStep)):
            if not isinstance(getattr(self, name), enum):
                raise WireRefused(WireRefusalReason.WRONG_TYPE, name)
        if _STEP_DETECTOR[self.step] is not self.detector:
            raise _bad("detector")
        for name in ("window_start_ns", "window_end_ns", "ts_ns"):
            check_int(getattr(self, name), name)
        if self.window_end_ns <= self.window_start_ns:
            raise _bad("window_end_ns")
        check_sha256(self.drill_clause_sha256, "drill_clause_sha256")
        if self.abort_record_sha256 is not None:
            check_sha256(self.abort_record_sha256, "abort_record_sha256")
        if (self.abort_record_sha256 is not None) is not (self.step is DrillStep.ABORT_HALT):
            raise _bad("abort_record_sha256")  # named by an abort step, and only by one

    def to_wire(self) -> dict[str, object]:
        return {
            "schema": DRILL_MARKER_SCHEMA,
            "registry_root": self.registry_root,
            "venue": self.venue,
            "episode_id": self.episode_id,
            "child_id": self.child_id,
            "detector": self.detector.value,
            "step": self.step.value,
            "window_start_ns": self.window_start_ns,
            "window_end_ns": self.window_end_ns,
            "abort_record_sha256": self.abort_record_sha256,
            "drill_clause_sha256": self.drill_clause_sha256,
            "ts_ns": self.ts_ns,
        }

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(obj, required=_KEYS)
        require_enum(obj, "schema", allowed=(DRILL_MARKER_SCHEMA,))
        return cls(
            registry_root=require_str(obj, "registry_root"),
            venue=require_str(obj, "venue"),
            episode_id=require_str(obj, "episode_id"),
            child_id=require_str(obj, "child_id"),
            detector=DrillDetector(
                require_enum(obj, "detector", allowed=[d.value for d in DrillDetector])
            ),
            step=DrillStep(require_enum(obj, "step", allowed=[s.value for s in DrillStep])),
            window_start_ns=require_ns(obj, "window_start_ns"),
            window_end_ns=require_ns(obj, "window_end_ns"),
            abort_record_sha256=optional_sha256(obj, "abort_record_sha256"),
            drill_clause_sha256=require_sha256(obj, "drill_clause_sha256"),
            ts_ns=require_ns(obj, "ts_ns"),
        )


class MarkerErrorReason(StrEnum):
    DIR_MISSING = "dir_missing"
    DIR_UNSAFE = "dir_unsafe"
    FILE_UNSAFE = "file_unsafe"
    INVALID = "invalid"


@dataclass(frozen=True)
class MarkerAbsent:
    """ENOENT on the marker inside a safe directory."""


@dataclass(frozen=True)
class MarkerError:
    """Anything but a clean read or a clean absence; ``detail`` is a closed code, never a path."""

    reason: MarkerErrorReason
    detail: str


def _dir_error(exc: SingleReadRefused) -> MarkerError:
    if exc.reason is SingleReadReason.NOT_FOUND:
        return MarkerError(MarkerErrorReason.DIR_MISSING, exc.reason.value)
    return MarkerError(MarkerErrorReason.DIR_UNSAFE, exc.reason.value)


def read_marker_at(rootfd: int) -> DrillMarker | MarkerAbsent | MarkerError:
    """Read the marker under the registry root ``rootfd`` (the caller opens and closes it)."""
    try:
        dirfd = walk_dirs(rootfd, MARKER_DIR_PARTS)
    except SingleReadRefused as exc:
        return _dir_error(exc)
    except OSError:
        return MarkerError(MarkerErrorReason.DIR_UNSAFE, "io")
    try:
        try:
            dir_mode = stat.S_IMODE(os.fstat(dirfd).st_mode)
        except OSError:
            return MarkerError(MarkerErrorReason.DIR_UNSAFE, "io")
        if dir_mode != _DIR_MODE:
            return MarkerError(MarkerErrorReason.DIR_UNSAFE, "dir_mode")
        try:
            raw = read_once_at(
                dirfd, MARKER_NAME, max_bytes=MAX_MARKER_BYTES, policy=ReadPolicy.STRICT
            )
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return MarkerAbsent()
            return MarkerError(MarkerErrorReason.FILE_UNSAFE, exc.reason.value)
    finally:
        os.close(dirfd)
    try:
        marker = DrillMarker.from_wire(parse_json_exact(raw))
    except WireRefused as exc:
        return MarkerError(MarkerErrorReason.INVALID, exc.reason.value)
    return replace(marker, raw_sha256=sha256_hex(raw))


def read_marker(paths: AutonomyPaths | ShadowPaths) -> DrillMarker | MarkerAbsent | MarkerError:
    """``read_marker_at`` on ``paths.root``; a missing or unsafe root is an error."""
    try:
        rootfd = open_root(paths.root)
    except SingleReadRefused as exc:
        return _dir_error(exc)
    try:
        return read_marker_at(rootfd)
    finally:
        os.close(rootfd)
