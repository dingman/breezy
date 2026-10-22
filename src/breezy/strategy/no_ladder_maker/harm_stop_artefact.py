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
from typing import Any, Final

from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import SCHEMA, compute_digest
from breezy.strategy.no_ladder_maker.harm_stop import HarmStopResult, HarmVerdict

FAMILY_ID: Final[str] = "pm_us_no_maker_sharp_v1"
_DIR_MODE: Final[int] = 0o755
_FILE_MODE: Final[int] = 0o600
_MAX_READ_BYTES: Final[int] = 1 << 20

ACTION_WRITTEN: Final[str] = "written"
ACTION_REMOVED: Final[str] = "removed"
ACTION_NOTHING: Final[str] = "nothing_to_remove"
ACTION_STICKY: Final[str] = "sticky_fail_kept"


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
        },
        "w_star": None if result.w_star is None else str(result.w_star),
        "cum_pnl": str(result.cum_pnl),
        "cp_upper": result.cp_upper,
    }


def existing_verdict(path: Path) -> str | None:
    """The verdict of the file now at ``path``, or ``None`` if absent/unreadable/not ours."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        raw = os.read(fd, _MAX_READ_BYTES)
    finally:
        os.close(fd)
    try:
        body = json.loads(raw.decode())
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("schema") != SCHEMA:
        return None
    verdict = body.get("verdict")
    return verdict if isinstance(verdict, str) else None


def _write_atomic(path: Path, body: dict[str, Any], *, when: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(_DIR_MODE)  # the probe refuses a group/other-writable directory
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
    dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


@dataclass(frozen=True, slots=True)
class PublishOutcome:
    action: str


def publish(
    path: Path, result: HarmStopResult, *, as_of: datetime, c2_hwm: str, truth_sha: str
) -> PublishOutcome:
    """PASS/FAIL write atomically; HOLD removes a standing PASS; a standing FAIL is never moved."""
    if existing_verdict(path) == HarmVerdict.FAIL.value:
        return PublishOutcome(ACTION_STICKY)
    if result.verdict is HarmVerdict.HOLD:
        try:
            path.unlink()
        except FileNotFoundError:
            return PublishOutcome(ACTION_NOTHING)
        return PublishOutcome(ACTION_REMOVED)
    body = render_artefact(result, as_of=as_of, c2_hwm=c2_hwm, truth_sha=truth_sha)
    _write_atomic(path, body, when=as_of)
    return PublishOutcome(ACTION_WRITTEN)
