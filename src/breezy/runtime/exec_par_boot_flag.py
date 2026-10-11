"""EXEC-PAR BG-3: boot-time enforcement of the durable force-K1 flag (spec 1b, K3, N4).

Two independent causes pin the effective K to 1 at boot, both re-evaluated on
every boot (``SubmitIntentLatch.force_k1`` is process-local):

* the durable flag (``exec_par/force_k1``) reads SET or UNREADABLE -- an
  unreadable flag is treated as set;
* a ``cleanup_demotion`` record with ``to_k == 1`` that no hash-valid frozen
  amendment references (N4), at a configured K above 1.

The flag WRITER is not here (BG-1a owns it; BG-5/BG-6 call it).
"""

from __future__ import annotations

import hashlib
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Final, Protocol

from breezy.runtime.exec_par_records import CleanupDemotion, ForceK1Kind, ForceK1State
from breezy.runtime.health import AlertPayload, AlertSink, emit_alert

__all__ = [
    "AMENDMENT_DIR",
    "FLAG_SET_EVENT",
    "ForceK1BootDetail",
    "default_repo_root",
    "force_k1_at_boot",
    "has_valid_amendment_for",
]

_LOG = logging.getLogger(__name__)

#: Frozen amendments live beside the spec, repo-relative (the node's cwd is the repo root).
AMENDMENT_DIR: Final[Path] = Path("docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04")
_AMENDMENT_NAME: Final[re.Pattern[str]] = re.compile(r"EXEC-PAR-D-PREREG-A[0-9]+\.md")
_SHA256_HEX: Final[re.Pattern[str]] = re.compile(r"[0-9a-fA-F]{64}")

FLAG_SET_EVENT: Final[str] = "EXEC_PAR_FORCE_K1_FLAG_SET"
_ALERT_SITE: Final[str] = "exec_par/boot"
FLAG_REASON_PREFIX: Final[str] = "durable force-K1 flag"
DEMOTION_REASON: Final[str] = "cleanup_demotion to K=1 without a frozen amendment"


class ForceK1BootDetail(str, Enum):
    """Closed ``detail`` set for this module's alerts (own enum: the supervisor's
    ``AlertDetail`` is byte-pinned; WP5b precedent). Never a flag reason or any raw text."""

    FLAG_SET = "EXEC_PAR_FORCE_K1_FLAG_SET"


def default_repo_root() -> Path:
    """The repo root, anchored on this file (``<root>/src/breezy/runtime/``), never the cwd.

    The supervisor-launched node's working directory is not guaranteed to be the repo.
    """
    return Path(__file__).resolve().parents[3]


class _Latch(Protocol):
    """The slice of ``SubmitIntentLatch`` this module uses (structural: keeps the
    ``submit_intent`` importer set, which is exact-set pinned, unchanged)."""

    def read_force_k1_flag(self) -> ForceK1State: ...
    def read_latest_cleanup_demotion(self) -> CleanupDemotion | None: ...
    def max_slots(self) -> int: ...
    def force_k1(self, reason: str) -> None: ...


def _sibling_digest(path: Path) -> str | None:
    """The hex digest recorded in ``<path>.sha256`` (``<hex>  <name>``), else ``None``."""
    sidecar = path.with_name(path.name + ".sha256")
    tokens = sidecar.read_text(encoding="utf-8").split()
    if not tokens or _SHA256_HEX.fullmatch(tokens[0]) is None:
        return None
    return tokens[0].lower()


def _amendment_references(path: Path, ts_ns: int) -> bool:
    recorded = _sibling_digest(path)
    raw = path.read_bytes()
    if recorded is None or hashlib.sha256(raw).hexdigest() != recorded:
        return False
    pattern = rf"(?<![0-9]){ts_ns}(?![0-9])"
    return re.search(pattern, raw.decode("utf-8")) is not None


def has_valid_amendment_for(repo_root: Path, ts_ns: int) -> bool:
    """True iff a sha-valid ``EXEC-PAR-D-PREREG-A<n>.md`` references ``ts_ns``.

    Pure of side effects. ANY read error on a file (missing sibling, bad
    encoding, I/O) means that file is not a valid amendment; an unreadable
    directory means none exists.
    """
    try:
        candidates = sorted(
            p for p in (repo_root / AMENDMENT_DIR).iterdir() if _AMENDMENT_NAME.fullmatch(p.name)
        )
    except OSError:
        return False
    for path in candidates:
        try:
            if _amendment_references(path, ts_ns):
                return True
        except (OSError, ValueError):
            continue
    return False


def _flag_reason(latch: _Latch) -> tuple[str, bool] | None:
    """``(reason, is_set)`` when the flag forces K=1, else ``None`` (CLEARED)."""
    state = latch.read_force_k1_flag()
    if state.kind is ForceK1Kind.CLEARED:
        return None
    if state.kind is ForceK1Kind.SET and state.record is not None:
        return f"{FLAG_REASON_PREFIX} set: {state.record.reason}", True
    return f"{FLAG_REASON_PREFIX} unreadable (treated as set)", False


def _demotion_pause(latch: _Latch, repo_root: Path) -> bool:
    """N4: configured K > 1, latest demotion to K=1, no valid amendment. Fails closed."""
    if latch.max_slots() <= 1:
        return False
    try:
        record = latch.read_latest_cleanup_demotion()
    except Exception:  # noqa: BLE001 - an unreadable record keeps the pause (fail closed)
        _LOG.error("cleanup_demotion record unreadable at boot; holding K=1", exc_info=False)
        return True
    if record is None or record.to_k != 1:
        return False
    return not has_valid_amendment_for(repo_root, record.ts_ns)


def force_k1_at_boot(latch: _Latch, *, repo_root: Path, alert_sink: AlertSink) -> bool:
    """Pin K=1 for the durable flag and the N4 demotion pause. ``True`` iff K was forced."""
    forced = False
    flag = _flag_reason(latch)
    if flag is not None:
        reason, is_set = flag
        _LOG.error("EXEC-PAR boot: %s; forcing K=1", reason)
        latch.force_k1(reason)
        forced = True
        if is_set:
            emit_alert(
                alert_sink,
                AlertPayload(
                    severity="CRITICAL",
                    event=FLAG_SET_EVENT,
                    site=_ALERT_SITE,
                    detail=ForceK1BootDetail.FLAG_SET.value,
                ),
            )
    if _demotion_pause(latch, repo_root):
        _LOG.error("EXEC-PAR boot: %s; forcing K=1", DEMOTION_REASON)
        latch.force_k1(DEMOTION_REASON)
        forced = True
    return forced
