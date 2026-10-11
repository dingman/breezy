"""EXEC-PAR D-PREREG r4.5 O3: the hard K=2 ceiling until an O2 promotion pass.

A configured K above 2 is admitted only while the LATEST promotion-time record for the
stage being promoted from is a sha-pinned PASS with ``icc_v`` >= the G6 floor. The
validator is pure (reads only under ``repo_root``); BG-3 applies it at boot
(:func:`apply_promo_guard`) and BG-9 applies it to the committed config.

Record: ``docs/evidence/exec_par/exec_par_bg10_promo_<stage>_<YYYY-MM-DD>.json``; fields in
``EXEC-PAR-BG-integration-notes.md`` item 9. The pin is a standalone line
``bg10_promo_record_sha256: <hex>`` in a sha-valid frozen amendment.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Final, Protocol

from breezy.runtime.exec_par_boot_flag import list_amendments, read_sha_valid_amendment
from breezy.runtime.health import AlertPayload, AlertSink, emit_alert

__all__ = [
    "ICC_V_FLOOR",
    "PROMO_RECORD_DIR",
    "PromoGuardDetail",
    "apply_promo_guard",
    "promo_record_problems",
    "required_stage",
]

_LOG = logging.getLogger(__name__)

PROMO_RECORD_DIR: Final[Path] = Path("docs/evidence/exec_par")
#: Highest K reachable without a record (O3 ceiling).
UNGUARDED_K_CEILING: Final[int] = 2
ICC_V_FLOOR: Final[float] = 0.4147
UNRAMPED: Final[str] = "UNRAMPED"
#: Ramp 1 -> 2 -> 4 -> 6: the stage a configured K promotes FROM.
_STAGE_FOR_K_CEILING: Final[tuple[tuple[int, str], ...]] = ((4, "S1"), (6, "S2"))
_PIN_KEY: Final[str] = "bg10_promo_record_sha256"
_NAME: Final[re.Pattern[str]] = re.compile(
    r"exec_par_bg10_promo_([A-Za-z0-9]+)_(\d{4}-\d{2}-\d{2})\.json"
)
_HEX64: Final[re.Pattern[str]] = re.compile(r"[0-9a-fA-F]{64}")
_BOUND_LEVELS: Final[frozenset[int]] = frozenset({90, 95})
_FIELDS: Final[tuple[str, ...]] = (
    "stage",
    "look_date",
    "verdict",
    "v1",
    "v2",
    "v3",
    "icc_v",
    "bound_level",
    "input_snapshot_sha256",
    "created_ts_ns",
)
_ALERT_SITE: Final[str] = "exec_par/boot"


class PromoGuardDetail(str, Enum):
    """Closed ``detail`` set for this module's alerts (never raw record text)."""

    PROMO_RECORD_INVALID = "EXEC_PAR_PROMO_RECORD_INVALID"
    PROMO_CHECK_FAILED = "EXEC_PAR_PROMO_CHECK_FAILED"


def required_stage(k: int) -> str | None:
    """The stage whose record a configured K requires; ``None`` at K<=2; ``UNRAMPED`` above 6."""
    if k <= UNGUARDED_K_CEILING:
        return None
    for ceiling, stage in _STAGE_FOR_K_CEILING:
        if k <= ceiling:
            return stage
    return UNRAMPED


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _shape_problems(rec: object, stage: str, day: str) -> list[str]:
    if not isinstance(rec, dict):
        return ["record is not a JSON object"]
    problems = [f"field {f} missing" for f in _FIELDS if f not in rec]
    if problems:
        return problems
    if rec["stage"] != stage or rec["look_date"] != day:
        problems.append("stage/look_date do not match the file name")
    if rec["verdict"] != "PASS":
        problems.append(f"verdict is {rec['verdict']!r}, not PASS")
    problems.extend(f"{v} is not PASS" for v in ("v1", "v2", "v3") if rec[v] != "PASS")
    icc = rec["icc_v"]
    if isinstance(icc, bool) or not isinstance(icc, (int, float)) or not math.isfinite(icc):
        problems.append("icc_v is not a finite number")
    elif icc < ICC_V_FLOOR:
        problems.append(f"icc_v {icc} below the {ICC_V_FLOOR} floor")
    if not _is_int(rec["bound_level"]) or rec["bound_level"] not in _BOUND_LEVELS:
        problems.append("bound_level not in {90, 95}")
    snap = rec["input_snapshot_sha256"]
    if not isinstance(snap, str) or _HEX64.fullmatch(snap) is None:
        problems.append("input_snapshot_sha256 is not a sha256 hex")
    ts = rec["created_ts_ns"]
    if not _is_int(ts) or ts <= 0:
        problems.append("created_ts_ns is not a positive integer")
    return problems


def _is_pinned(repo_root: Path, digest: str) -> bool:
    pattern = re.compile(rf"^{_PIN_KEY}:[ \t]*{digest}[ \t]*\r?$", re.MULTILINE | re.IGNORECASE)
    try:
        amendments = list_amendments(repo_root)
    except OSError:
        return False
    for path in amendments:
        try:
            text = read_sha_valid_amendment(path)
        except (OSError, ValueError):
            continue
        if text is not None and pattern.search(text) is not None:
            return True
    return False


def _latest_record(repo_root: Path, stage: str) -> tuple[Path, str] | None:
    try:
        names = list((repo_root / PROMO_RECORD_DIR).iterdir())
    except OSError:
        return None
    found: list[tuple[str, Path]] = []
    for path in names:
        match = _NAME.fullmatch(path.name)
        if match is None or match.group(1) != stage:
            continue
        try:
            date.fromisoformat(match.group(2))
        except ValueError:
            continue
        found.append((match.group(2), path))
    if not found:
        return None
    day, path = max(found)
    return path, day


def promo_record_problems(repo_root: Path, k: int) -> list[str]:
    """Every reason the O3 record for configured ``k`` is not valid; ``[]`` at K<=2 (no reads)."""
    stage = required_stage(k)
    if stage is None:
        return []
    if stage == UNRAMPED:
        return [f"configured K={k} is above the 1->2->4->6 ramp"]
    latest = _latest_record(repo_root, stage)
    if latest is None:
        return [f"no record for stage {stage} under {PROMO_RECORD_DIR}"]
    path, day = latest
    try:
        raw = path.read_bytes()
        rec = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return [f"latest {stage} record {path.name} is unreadable or not JSON"]
    problems = _shape_problems(rec, stage, day)
    if not _is_pinned(repo_root, hashlib.sha256(raw).hexdigest()):
        problems.append(f"record {path.name} is not sha-pinned by a frozen amendment")
    return problems


class _Latch(Protocol):
    def max_slots(self) -> int: ...
    def force_k1(self, reason: str) -> None: ...


def _alert(sink: AlertSink, detail: PromoGuardDetail) -> None:
    emit_alert(
        sink,
        AlertPayload(
            severity="CRITICAL", event=detail.value, site=_ALERT_SITE, detail=detail.value
        ),
    )


def apply_promo_guard(latch: _Latch, *, repo_root: Path, alert_sink: AlertSink) -> bool:
    """BG-3 O3: configured K>2 without a valid record forces K=1 and alerts CRITICAL.

    A raising check forces first, alerts, then re-raises. ``True`` iff K was forced.
    """
    k = latch.max_slots()
    if k <= UNGUARDED_K_CEILING:
        return False
    try:
        problems = promo_record_problems(repo_root, k)
    except Exception:
        latch.force_k1("O3 promotion-record check failed")
        _alert(alert_sink, PromoGuardDetail.PROMO_CHECK_FAILED)
        raise
    if not problems:
        return False
    _LOG.error("EXEC-PAR boot: O3 promotion record invalid at K=%d: %s; forcing K=1", k, problems)
    latch.force_k1("O3 promotion record missing or invalid at K>2")
    _alert(alert_sink, PromoGuardDetail.PROMO_RECORD_INVALID)
    return True
