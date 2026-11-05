"""The memory budget, ``#31 aut6.memory_budget`` (plan r15 section 3.10.1; V14, F10, F11; WP3 S5).

Reads the EFFECTIVE ``MemoryMax``, ``MemoryHigh`` and ``MemoryPeak`` of every ``deploy/systemd``
unit from the bus snapshot (drop-ins included; a unit the snapshot does not hold falls back to its
committed file) and judges seven conditions, each named in ``metrics.violations``. An absent limit
or ``infinity`` is +infinity, never skipped. WARNING until ``critical_from``, CRITICAL from it.

Studies-flock holders come from a static scan: a unit is a holder iff a non-comment line of its
``ExecStart=`` command, or of a ``deploy/systemd/*.sh`` that command names, takes
``breezy-studies.lock``. In-process takers are the table rows with ``studies_lock=True``
(``IN_PROCESS_STUDIES_LOCK_UNITS``, E-7e), kept honest by an AST test over ``src/``.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Final

from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE
from breezy.runtime.monitor_watch_model import (
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    DetectorResult,
    Outcome,
    WatchFinding,
    deploy_unit_names,
    directive_values,
    firing_minutes_of,
    logical_lines,
)
from breezy.runtime.unit_health_store import MEMAVAIL_INSUFFICIENT, MemAvailWindow

DETECTOR_MEMORY: Final = "aut6.memory_budget"
#: Row #31: WARNING until this date, CRITICAL from it (``detector_catalog`` row 31).
MEMORY_CRITICAL_FROM: Final = "2026-10-16"
STUDIES_LOCK: Final = "breezy-studies.lock"
INGEST_UNIT: Final = "breezy-quote-tape-ingest.service"
RECORDER_UNIT: Final = "breezy-quote-tape.service"
NODE_UNIT: Final = "breezy-trade-supervisor.service"
GIB: Final = 2**30
HOLDER_MAX_BYTES: Final = 14 * GIB
HOLDER_HIGH_BYTES: Final = 12 * GIB
RAISED_CAP_MAX_BYTES: Final = 16 * GIB
OWN_LOCK_SUM_BYTES: Final = 4 * GIB
HEAVY_BYTES: Final = 4 * GIB
#: Minutes of the UTC day: the decision window with its tail, and the nightly study window.
RAISED_FORBIDDEN_MINUTES: Final = frozenset(range(16 * 60 + 30, 24 * 60)) | frozenset(
    range(60 + 15)
)
HEAVY_FORBIDDEN_MINUTES: Final = frozenset(range(1 * 60, 4 * 60 + 30))
#: Named raised caps (a studies holder allowed over 14G / 12G): unit to its declared cap in bytes.
#: Empty today: the 16G incident floor of 2026-09-11 was removed from every unit.
NAMED_RAISED_CAPS: Final[Mapping[str, int]] = {}
#: Units whose resident memory is added back to ``MemAvailable`` regardless of the scan.
STATIC_ADDBACK_UNITS: Final = frozenset({INGEST_UNIT, RECORDER_UNIT, NODE_UNIT})
IN_PROCESS_STUDIES_LOCK_UNITS: Final[frozenset[str]] = frozenset(
    unit
    for row in AUTONOMY_BWRAP_TABLE.values()
    if row.studies_lock and not row.name.startswith("breezy-autonomy-selftest")
    for unit in row.units
)
_SIZE_RE: Final = re.compile(r"(\d+(?:\.\d+)?)\s*([KMGT]?)(?:i?B)?")
_SIZE_MUL: Final[Mapping[str, int]] = {"": 1, "K": 2**10, "M": 2**20, "G": 2**30, "T": 2**40}
_SCRIPT_RE: Final = re.compile(r"[\w./-]*deploy/systemd/([\w.@-]+\.sh)")
_MEMORY_UNSET_FROM: Final = 2**63
_INF: Final = math.inf


def parse_size(text: str) -> float | None:
    """Bytes of a size (``14G``, ``2147483648``); ``infinity`` is +inf; garbage is ``None``."""
    value = text.strip()
    if value == "infinity":
        return _INF
    match = _SIZE_RE.fullmatch(value)
    if match is None:
        return None
    number = float(match.group(1)) * _SIZE_MUL[match.group(2)]
    return _INF if number >= _MEMORY_UNSET_FROM else number


# --------------------------------------------------------------------------- the static scan


def _script_lines(deploy_dir: Path, unit_text: str) -> list[str]:
    lines = [ln for ln in logical_lines(unit_text) if ln.startswith("ExecStart=")]
    for command in list(lines):
        for match in _SCRIPT_RE.finditer(command):
            try:
                body = (deploy_dir / match.group(1)).read_text(encoding="utf-8")
            except OSError:
                continue
            lines.extend(logical_lines(body))
    return lines


def studies_lock_holders(deploy_dir: Path) -> frozenset[str]:
    """Services whose non-comment ExecStart (or named script) takes ``breezy-studies.lock``."""
    holders: set[str] = set()
    for name in deploy_unit_names(deploy_dir):
        if not name.endswith(".service"):
            continue
        try:
            text = (deploy_dir / name).read_text(encoding="utf-8")
        except OSError:
            continue
        if any(STUDIES_LOCK in line for line in _script_lines(deploy_dir, text)):
            holders.add(name)
    return frozenset(holders | (IN_PROCESS_STUDIES_LOCK_UNITS & _service_names(deploy_dir)))


def _service_names(deploy_dir: Path) -> set[str]:
    return {n for n in deploy_unit_names(deploy_dir) if n.endswith(".service")}


def own_lock_units(deploy_dir: Path, holders: Collection[str]) -> frozenset[str]:
    """Autonomy units that take their own lock: ``breezy-autonomy-*`` services and table rows
    without the studies lock, as far as ``deploy/systemd`` holds their file."""
    names = _service_names(deploy_dir)
    row_units = {
        unit
        for row in AUTONOMY_BWRAP_TABLE.values()
        if not row.studies_lock
        and not row.name.startswith("breezy-autonomy-selftest")
        and not {".", "#"} & set(row.name)  # a sub-row (the recorder's stop hook) owns no lock
        for unit in row.units
    }
    chosen = {n for n in names if n.startswith("breezy-autonomy-") and "@" not in n}
    return frozenset((chosen | (row_units & names)) - set(holders))


def addback_units(deploy_dir: Path) -> frozenset[str]:
    """Units whose ``MemoryCurrent`` is added back to ``MemAvailable`` (3.10.1 item 6)."""
    holders = studies_lock_holders(deploy_dir)
    return STATIC_ADDBACK_UNITS | holders | own_lock_units(deploy_dir, holders)


# --------------------------------------------------------------------------- effective limits


class Limits:
    """Effective limits from the snapshot's blocks, falling back to the committed files."""

    def __init__(self, deploy_dir: Path, blocks: Mapping[str, Mapping[str, str]]) -> None:
        self.deploy_dir = deploy_dir
        self.blocks = blocks

    def _blocks_of(self, unit: str) -> list[Mapping[str, str]]:
        if "@." not in unit:
            block = self.blocks.get(unit)
            return [block] if block is not None else []
        stem, _, suffix = unit.partition("@.")
        return [
            b
            for n, b in self.blocks.items()
            if n.startswith(f"{stem}@") and n.endswith(suffix) and n != unit
        ]

    def limit(self, unit: str, key: str) -> float:
        """``MemoryMax`` or ``MemoryHigh`` in bytes; absent or unreadable is +inf."""
        values: list[float] = []
        for block in self._blocks_of(unit):
            if key in block:
                parsed = parse_size(block[key])
                values.append(_INF if parsed is None else parsed)
        if values:
            return max(values)
        static = directive_values(self.deploy_dir, unit, key)
        parsed_static = parse_size(static[-1]) if static else None
        return _INF if parsed_static is None else parsed_static

    def peak(self, unit: str) -> float | None:
        values = [
            parse_size(block["MemoryPeak"])
            for block in self._blocks_of(unit)
            if "MemoryPeak" in block
        ]
        known = [v for v in values if v is not None and v != _INF]
        return max(known) if known else None


# --------------------------------------------------------------------------- the check


def _violations(
    limits: Limits,
    *,
    deploy_dir: Path,
    blocks: Mapping[str, Mapping[str, str]],
    raised: Mapping[str, int],
) -> tuple[list[str], dict[str, float], list[str]]:
    out: list[str] = []
    unknown: list[str] = []
    holders = studies_lock_holders(deploy_dir)
    own = own_lock_units(deploy_dir, holders)
    services = [n for n in deploy_unit_names(deploy_dir) if n.endswith(".service")]
    timers = {
        n.removesuffix(".timer"): n for n in deploy_unit_names(deploy_dir) if n.endswith(".timer")
    }
    heavy_minutes: dict[str, frozenset[int]] = {}
    for service in services:
        timer = timers.get(service.removesuffix(".service"))
        if timer is None:
            continue
        try:
            heavy_minutes[service] = firing_minutes_of(deploy_dir, timer)
        except ValueError:
            unknown.append(f"calendar_unsupported:{timer}")
    # 1 and 2
    holder_max = 0.0
    for unit in sorted(holders):
        cap, high = limits.limit(unit, "MemoryMax"), limits.limit(unit, "MemoryHigh")
        holder_max = max(holder_max, cap)
        if unit in raised:
            continue
        if cap == _INF:
            out.append(f"holder_memory_max_infinity:{unit}")
        elif cap > HOLDER_MAX_BYTES:
            out.append(f"holder_memory_max_over_14g:{unit}")
        if high != _INF and high > HOLDER_HIGH_BYTES:
            out.append(f"holder_memory_high_over_12g:{unit}")
    heavy = {
        u for u in services if limits.limit(u, "MemoryMax") > HEAVY_BYTES and u in heavy_minutes
    }
    for unit in sorted(raised):
        if limits.limit(unit, "MemoryMax") > RAISED_CAP_MAX_BYTES:
            out.append(f"raised_cap_over_16g:{unit}")
        minutes = heavy_minutes.get(unit, frozenset())
        if minutes & RAISED_FORBIDDEN_MINUTES:
            out.append(f"raised_cap_in_window:{unit}")
        if any(minutes & heavy_minutes[other] for other in heavy if other != unit):
            out.append(f"raised_cap_shares_slot:{unit}")
    # 3: a scheduled study whose last peak reached its MemoryHigh
    for unit in sorted(heavy_minutes):
        high, peak = limits.limit(unit, "MemoryHigh"), limits.peak(unit)
        if peak is not None and high != _INF and peak >= high:
            out.append(f"study_peak_at_memory_high:{unit}")
    # 4
    own_sum = 0.0
    for unit in sorted(own):
        cap = limits.limit(unit, "MemoryMax")
        if cap == _INF:
            out.append(f"own_lock_memory_max_infinity:{unit}")
        own_sum += cap
    if own_sum != _INF and own_sum > OWN_LOCK_SUM_BYTES:
        out.append("own_lock_sum_over_4g")
    # 5
    ingest_block = blocks.get(INGEST_UNIT, {})
    if "TEMPORARY" in ingest_block.get("DropInPaths", ""):
        out.append("ingest_temporary_dropin_stands")
    # 7
    for unit in sorted(heavy):
        if heavy_minutes[unit] & HEAVY_FORBIDDEN_MINUTES:
            out.append(f"heavy_unit_firing_0100_0430:{unit}")
    terms = {
        "holder": holder_max,
        "own": own_sum,
        "ingest": limits.limit(INGEST_UNIT, "MemoryMax"),
    }
    return out, terms, unknown


def evaluate_memory(
    *,
    deploy_dir: Path,
    blocks: Mapping[str, Mapping[str, str]],
    window: MemAvailWindow,
    node_rss_kib: int | None,
    recorder_rss_kib: int | None,
    today: str,
    raised: Mapping[str, int] = NAMED_RAISED_CAPS,
    critical_from: str = MEMORY_CRITICAL_FROM,
) -> DetectorResult:
    limits = Limits(deploy_dir, blocks)
    try:
        violations, terms, unknown = _violations(
            limits, deploy_dir=deploy_dir, blocks=blocks, raised=raised
        )
    except OSError:
        return DetectorResult(
            DETECTOR_MEMORY, Outcome.INCONCLUSIVE, (), {}, ("deploy_dir_unreadable",)
        )
    metrics: dict[str, str] = {"memavail_samples": str(window.count)}
    total = terms["holder"] + terms["own"] + terms["ingest"]
    if node_rss_kib is None or recorder_rss_kib is None:
        unknown.append("memory_rss_unreadable")
    elif total == _INF:
        violations.append("memory_sum_infinite")
    elif window.minimum_free_kib is not None:
        sum_kib = int(total // 1024) + node_rss_kib + recorder_rss_kib
        metrics["memory_sum_kib"] = str(sum_kib)
        metrics["memavail_min_free_kib"] = str(window.minimum_free_kib)
        if sum_kib > window.minimum_free_kib:
            violations.append("memory_sum_over_memavailable")
    inconclusive = window.minimum_free_kib is None and not violations and not unknown
    if violations:
        ordered = sorted(set(violations))
        metrics["violations"] = ",".join(ordered)
        digest = hashlib.sha256(metrics["violations"].encode()).hexdigest()[:8]
        severity = SEVERITY_CRITICAL if today >= critical_from else SEVERITY_WARNING
        finding = WatchFinding(
            DETECTOR_MEMORY,
            "memory_budget",
            "_host",
            severity,
            f"memory_budget-{today}-{digest}",
            f"violations={metrics['violations']}"[:480],
            metrics,
        )
        return DetectorResult(DETECTOR_MEMORY, Outcome.FAIL, (finding,), metrics, tuple(unknown))
    if inconclusive:
        metrics["unknown_reason"] = window.unknown_reason or MEMAVAIL_INSUFFICIENT
        return DetectorResult(DETECTOR_MEMORY, Outcome.INCONCLUSIVE, (), metrics, tuple(unknown))
    outcome = Outcome.PASS if not unknown else Outcome.INCONCLUSIVE
    return DetectorResult(DETECTOR_MEMORY, outcome, (), metrics, tuple(unknown))


def free_addback_kib(
    blocks: Mapping[str, Mapping[str, str]],
    units: Collection[str],
    *,
    node_kib: int,
    recorder_kib: int,
) -> int:
    """The free side's add-back (3.10.1 item 6): ``MemoryCurrent`` of every counted unit except
    the node and the recorder, whose resident set is the very ``VmRSS`` the sum side counts."""
    cgroup_units = set(units) - {NODE_UNIT, RECORDER_UNIT}
    return addback_kib(blocks, cgroup_units, node_kib + recorder_kib)


def addback_kib(
    blocks: Mapping[str, Mapping[str, str]], units: Collection[str], extra_kib: int = 0
) -> int:
    """The summed ``MemoryCurrent`` of ``units`` in KiB (an unset value is 2**64 - 1: skipped)."""
    total = 0
    for unit in set(units):
        current = blocks.get(unit, {}).get("MemoryCurrent", "")
        if current.isdigit() and int(current) < _MEMORY_UNSET_FROM:
            total += int(current) // 1024
    return total + extra_kib
