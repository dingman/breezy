"""ARM D1: render and atomically write the ``loss_stop/v1`` artefact ``LossStopProbe`` reads.

The probe is NOT forked: this writes exactly its file format (``loss_stop_probe.SCHEMA``, the
same digest, a ``PASS``/``FAIL`` verdict only) at the maker family's own path. The probe accepts no
third verdict, so HOLD writes no file -- an absent file is the probe's UNKNOWN, which vetoes. A
FAIL is STICKY: D5 says "Restart needs a new dated ruling citing the loss evidence", so a later
run never replaces a FAIL file, and a HOLD never removes one.
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import SCHEMA, compute_digest
from breezy.strategy.no_ladder_maker.harm_stop import HarmStopResult, HarmVerdict

FAMILY_ID: Final[str] = "pm_us_no_maker_sharp_v1"
_DIR_MODE: Final[int] = 0o755
_FILE_MODE: Final[int] = 0o600
_MAX_READ_BYTES: Final[int] = 1 << 20

Action = Literal["written", "removed", "nothing_to_remove", "sticky_fail_kept"]
ACTION_WRITTEN: Final[Action] = "written"
ACTION_REMOVED: Final[Action] = "removed"
ACTION_NOTHING: Final[Action] = "nothing_to_remove"
ACTION_STICKY: Final[Action] = "sticky_fail_kept"

#: ``existing_verdict`` for a standing file that is present but not a readable ``loss_stop/v1``
#: PASS/FAIL: treated as sticky.
UNREADABLE: Final[str] = "UNREADABLE"


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z")


def render_artefact(
    result: HarmStopResult, *, as_of: datetime, c2_hwm: str, truth_sha: str
) -> dict[str, Any]:
    """The probe's six keys plus informational counts the probe ignores (not in the digest)."""
    if result.verdict is HarmVerdict.HOLD:
        raise ValueError("a HOLD has no artefact: the probe accepts PASS or FAIL only")
    verdict = result.verdict.value
    as_of_text = _stamp(as_of)
    return {
        "schema": SCHEMA,
        "verdict": verdict,
        "as_of": as_of_text,
        "c2_hwm": c2_hwm,
        "truth_sha": truth_sha,
        "digest": compute_digest(
            verdict=verdict, as_of=as_of_text, c2_hwm=c2_hwm, truth_sha=truth_sha
        ),
        "family": FAMILY_ID,
        "triggers": list(result.triggers),
        "counts": {
            "fills": result.fills,
            "wins": result.wins,
            "losses": result.losses,
            "n": result.n,
            "unresolved": result.unresolved,
            "pending": result.pending,
        },
        "w_star": None if result.w_star is None else str(result.w_star),
        "cum_pnl": str(result.cum_pnl),
        "cp_upper": result.cp_upper,
    }


def existing_verdict(path: Path) -> str | None:
    """``PASS``/``FAIL`` of the file now at ``path``; ``None`` only if there is no file.

    Anything else that stands there (unreadable, corrupt, foreign, an unknown verdict, a symlink or
    other non-regular file) is :data:`UNREADABLE`: it may hide a FAIL, so the caller keeps it."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError:
        return UNREADABLE
    try:
        raw = os.read(fd, _MAX_READ_BYTES)
    except OSError:
        return UNREADABLE
    finally:
        os.close(fd)
    try:
        body = json.loads(raw.decode())
    except ValueError:  # includes UnicodeDecodeError and JSONDecodeError
        return UNREADABLE
    if not isinstance(body, dict) or body.get("schema") != SCHEMA:
        return UNREADABLE
    verdict = body.get("verdict")
    if verdict not in (HarmVerdict.PASS.value, HarmVerdict.FAIL.value):
        return UNREADABLE
    return str(verdict)


def _fsync_dir(directory: Path) -> None:
    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _ensure_dir(directory: Path) -> None:
    """Create ``directory`` 0755 whatever the umask (the probe refuses a group-writable one)."""
    created = not directory.exists()
    directory.mkdir(parents=True, exist_ok=True)
    if created or directory.stat().st_mode & 0o022:
        directory.chmod(_DIR_MODE)


def _write_atomic(path: Path, body: dict[str, Any], *, when: datetime) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, _FILE_MODE)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(body, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
        os.utime(tmp, (when.timestamp(), when.timestamp()))
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    _fsync_dir(path.parent)


@dataclass(frozen=True, slots=True)
class PublishOutcome:
    action: Action


def publish(
    path: Path, result: HarmStopResult, *, as_of: datetime, c2_hwm: str, truth_sha: str
) -> PublishOutcome:
    """PASS/FAIL write atomically; HOLD removes a standing PASS; FAIL or unreadable stays."""
    if existing_verdict(path) in (HarmVerdict.FAIL.value, UNREADABLE):
        return PublishOutcome(ACTION_STICKY)
    if result.verdict is HarmVerdict.HOLD:
        try:
            path.unlink()
        except FileNotFoundError:
            return PublishOutcome(ACTION_NOTHING)
        _fsync_dir(path.parent)
        return PublishOutcome(ACTION_REMOVED)
    body = render_artefact(result, as_of=as_of, c2_hwm=c2_hwm, truth_sha=truth_sha)
    _write_atomic(path, body, when=as_of)
    return PublishOutcome(ACTION_WRITTEN)
