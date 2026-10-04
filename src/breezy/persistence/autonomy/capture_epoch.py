"""AUT-1 ``capture_epoch_start`` (ARCH C1 invariants (ii)-(iii); plan r12 section 3.4.5).

``evidence/capture/epoch/<family_id>.json`` is written once, on the first boot of a build that
composes the family with capture, and is only ever verified afterwards. The audit's epoch checks
(``epoch_missing``, ``epoch_rewritten``, ``epoch_unlogged``) read it through :func:`read_epoch`.

Writing goes through ``single_read.write_once`` (a temp file created ``O_CREAT|O_EXCL|O_NOFOLLOW``,
mode 0444, then ``os.link``: an existing file is never replaced), which is the sanctioned write
site of the one-writer gate, so this module adds none. An unreadable or unwritable epoch gives one
CRITICAL offer and an ``UNREADABLE`` outcome and never raises: the epoch matters only to the audit,
so there is no veto.
"""

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.paths import family_component
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    WriteOutcome,
    ensure_dir,
    open_root,
    read_once_at,
    walk_dirs,
    write_once,
)

__all__ = [
    "EPOCH_ALERT_EVENT",
    "EPOCH_FILE_MODE",
    "EPOCH_SCHEMA",
    "EpochOutcome",
    "EpochRecord",
    "EpochStatus",
    "EpochUnreadable",
    "epoch_relative_path",
    "read_epoch",
    "write_epoch_once",
]

EPOCH_SCHEMA: Final[str] = "capture_epoch/v1"
EPOCH_ALERT_EVENT: Final[str] = "CAPTURE_EPOCH_UNREADABLE"
EPOCH_FILE_MODE: Final[int] = 0o444
_EPOCH_DIR: Final[tuple[str, ...]] = ("evidence", "capture", "epoch")
_MAX_EPOCH_BYTES: Final[int] = 4096
_CRITICAL: Final[str] = "CRITICAL"
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

#: ``(event, severity, detail) -> delivered`` (the node outbox's ``offer``, duck-typed).
AlertOffer = Callable[[str, str, str], bool]


class EpochUnreadable(ValueError):
    """The epoch file exists but is not a valid ``capture_epoch/v1`` record for this family."""


class EpochStatus(StrEnum):
    WRITTEN = "written"
    VERIFIED = "verified"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class EpochRecord:
    family_id: str
    epoch_start_ns: int
    node_boot_id: str
    build_sha: str


@dataclass(frozen=True)
class EpochOutcome:
    """``epoch_start_ns`` is the file's value, or 0 when the status is ``UNREADABLE``.

    ``delivered`` is False when an alert was needed and the outbox did not accept it (no offer
    wired, an offer that raised, or one that returned False); ``alert_drops`` counts those.
    """

    status: EpochStatus
    epoch_start_ns: int
    delivered: bool = True
    alert_drops: int = 0


def epoch_relative_path(family_id: str) -> tuple[str, ...]:
    """Path parts below the data root; ``family_id`` is validated as a path component."""
    return (*_EPOCH_DIR, f"{family_component(family_id)}.json")


def _parse(raw: bytes, family_id: str) -> EpochRecord:
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise EpochUnreadable("not json") from exc
    if not isinstance(body, dict) or set(body) != {
        "schema",
        "family_id",
        "epoch_start_ns",
        "node_boot_id",
        "build_sha",
    }:
        raise EpochUnreadable("unexpected shape")
    if body["schema"] != EPOCH_SCHEMA or body["family_id"] != family_id:
        raise EpochUnreadable("wrong schema or family")
    start = body["epoch_start_ns"]
    if not isinstance(start, int) or isinstance(start, bool) or start < 0:
        raise EpochUnreadable("bad epoch_start_ns")
    if not isinstance(body["node_boot_id"], str) or not isinstance(body["build_sha"], str):
        raise EpochUnreadable("bad identity fields")
    return EpochRecord(family_id, start, body["node_boot_id"], body["build_sha"])


def read_epoch(data_root: Path, family_id: str) -> EpochRecord | None:
    """The family's epoch record, ``None`` when absent. Raises ``EpochUnreadable`` or
    ``SingleReadRefused`` (a symlink, a wrong owner, an oversize file) when it cannot be trusted."""
    *parent, name = epoch_relative_path(family_id)
    rootfd = open_root(data_root)
    try:
        try:
            dirfd = walk_dirs(rootfd, parent)
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return None
            raise
        try:
            raw = read_once_at(dirfd, name, max_bytes=_MAX_EPOCH_BYTES, policy=ReadPolicy.STRICT)
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return None
            raise
        finally:
            os.close(dirfd)
    finally:
        os.close(rootfd)
    return _parse(raw, family_id)


def _publish(data_root: Path, family_id: str, body: dict[str, object]) -> bool:
    """True when this call created the file; False when a concurrent first boot won the race."""
    parts = epoch_relative_path(family_id)
    rootfd = open_root(data_root)
    try:
        os.close(ensure_dir(rootfd, parts[:-1]))
    finally:
        os.close(rootfd)
    try:
        outcome = write_once(
            data_root.joinpath(*parts), canonical_json(body), root=data_root, mode=EPOCH_FILE_MODE
        )
    except SingleReadRefused as exc:
        if exc.reason is SingleReadReason.EXISTS_DIFFERENT:
            return False  # the winner's record is read back and verified below
        raise
    return outcome is WriteOutcome.WRITTEN


def _offer(offer: AlertOffer | None, family_id: str, cause: str) -> EpochOutcome:
    """The UNREADABLE outcome, after one ERROR log and one offer. Never silent, never raises: the
    epoch matters only to the audit, so an undeliverable alert is counted and reported, not a
    veto."""
    _LOGGER.error("%s family=%s cause=%s", EPOCH_ALERT_EVENT, family_id, cause)
    accepted = False
    if offer is not None:
        try:
            accepted = bool(
                offer(EPOCH_ALERT_EVENT, _CRITICAL, f"family={family_id} cause={cause}")
            )
        except Exception:  # noqa: BLE001 - an alert transport failure is never a capture veto
            accepted = False
    return EpochOutcome(
        EpochStatus.UNREADABLE, 0, delivered=accepted, alert_drops=int(not accepted)
    )


def write_epoch_once(
    data_root: Path,
    *,
    family_id: str,
    node_boot_id: str,
    build_sha: str,
    now_ns: int,
    alert_offer: AlertOffer | None = None,
) -> EpochOutcome:
    """Write the epoch on first boot; verify it on every later boot; never raise past a bad file.

    A malformed ``family_id`` raises (a programming error, refused before any I/O).
    """
    epoch_relative_path(family_id)
    try:
        existing = read_epoch(data_root, family_id)
        if existing is not None:
            return EpochOutcome(EpochStatus.VERIFIED, existing.epoch_start_ns)
        created = _publish(
            data_root,
            family_id,
            {
                "schema": EPOCH_SCHEMA,
                "family_id": family_id,
                "epoch_start_ns": now_ns,
                "node_boot_id": node_boot_id,
                "build_sha": build_sha,
            },
        )
        written = read_epoch(data_root, family_id)
    except (EpochUnreadable, SingleReadRefused, OSError) as exc:
        return _offer(alert_offer, family_id, type(exc).__name__)
    if written is None:
        return _offer(alert_offer, family_id, "absent_after_write")
    status = EpochStatus.WRITTEN if created else EpochStatus.VERIFIED
    return EpochOutcome(status, written.epoch_start_ns)
