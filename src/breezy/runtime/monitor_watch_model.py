"""Pure model of the AUT-6 meta-detectors (plan r15 sections 3.9-3.11; WP3 S5).

Types, the ``deploy/systemd`` reader, the ``OnCalendar`` expander and the parsers of the bus
snapshot's inventory reads. No systemd call and no network: every input is a file under the
repo's ``deploy/systemd`` or the text of a read the S2 bus snapshot already took.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

from breezy.runtime.unit_health_daemons import parse_systemd_timestamp

SEVERITY_CRITICAL: Final = "CRITICAL"
SEVERITY_WARNING: Final = "WARNING"
NS: Final = 1_000_000_000
DAY_S: Final = 86_400
_MINUTES_PER_DAY: Final = 1440
#: ``AccuracySec`` of a timer that does not declare one (the manager default).
DEFAULT_ACCURACY_S: Final = 60
_ZERO_TIMES: Final = frozenset({"", "n/a", "0", "infinity"})
_UNITS_SUFFIXES: Final = (".service", ".timer")
_MONOTONIC_KEYS: Final = (
    "OnBootSec",
    "OnStartupSec",
    "OnActiveSec",
    "OnUnitActiveSec",
    "OnUnitInactiveSec",
)
_ACCURACY_RE: Final = re.compile(r"(\d+)\s*(us|ms|sec|s|min|m|h)")
_ACCURACY_S: Final[Mapping[str, float]] = {
    "us": 1e-6,
    "ms": 1e-3,
    "sec": 1.0,
    "s": 1.0,
    "min": 60.0,
    "m": 60.0,
    "h": 3600.0,
}
_FIELD_PART_RE: Final = re.compile(r"(\*|\d+)(?:\.\.(\d+))?(?:/(\d+))?")


class Outcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class WatchFinding:
    """One page-worthy condition. ``key`` is unique per day and subject (``commit_finding``)."""

    detector: str
    kind: str
    subject: str
    severity: str
    key: str
    detail: str
    metrics: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DetectorResult:
    """One detector's verdict. ``unknown_reasons`` make the whole pass UNKNOWN (never a pass)."""

    detector: str
    outcome: Outcome
    findings: tuple[WatchFinding, ...] = ()
    metrics: Mapping[str, str] = field(default_factory=dict)
    unknown_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WatchResult:
    results: tuple[DetectorResult, ...]
    #: Unit names read INCONCLUSIVE(not_deployed): listed in the day rollup, never paged.
    not_deployed: tuple[str, ...]

    @property
    def findings(self) -> tuple[WatchFinding, ...]:
        return tuple(f for r in self.results for f in r.findings)

    @property
    def unknown_reasons(self) -> tuple[str, ...]:
        return tuple(x for r in self.results for x in r.unknown_reasons)

    def by_detector(self, detector: str) -> DetectorResult:
        return next(r for r in self.results if r.detector == detector)


# --------------------------------------------------------------------------- time values


def timestamp_or_zero(text: str) -> tuple[bool, int | None]:
    """``(readable, ns)``: ``(True, None)`` for an unset value, ``(False, None)`` for garbage."""
    value = text.strip()
    if value in _ZERO_TIMES:
        return True, None
    parsed = parse_systemd_timestamp(value)
    return (parsed is not None), parsed


def parse_accuracy_s(text: str) -> float | None:
    """An ``AccuracySec=`` value (``1min``, ``30sec``, ``1s``) in seconds; else ``None``."""
    value = text.strip()
    parts = _ACCURACY_RE.findall(value)
    if not parts or _ACCURACY_RE.sub("", value).strip():
        return None
    return sum(int(n) * _ACCURACY_S[u] for n, u in parts)


# --------------------------------------------------------------------------- the inventory


@dataclass(frozen=True, slots=True)
class Inventory:
    """What the snapshot's reads say is on the host: files, loaded units, show blocks."""

    files: Mapping[str, str]
    loaded: Mapping[str, str]
    blocks: Mapping[str, Mapping[str, str]]

    def link_state(self, name: str) -> str:
        """``present``, ``broken`` (listed but pointing nowhere) or ``absent``."""
        block = self.blocks.get(name, {})
        load = block.get("LoadState") or self.loaded.get(name, "")
        state = self.files.get(name)
        if state == "bad" or (state is not None and load == "not-found"):
            return "broken"
        if state is not None or load == "loaded":
            return "present"
        return "absent"


def parse_inventory(
    units_inventory: str, unit_files: str, blocks: Mapping[str, Mapping[str, str]]
) -> Inventory:
    files: dict[str, str] = {}
    for line in unit_files.splitlines():
        tokens = line.split()
        if len(tokens) >= 2:
            files[tokens[0]] = tokens[1]
    loaded: dict[str, str] = {}
    for line in units_inventory.splitlines():
        tokens = [t for t in line.split() if t not in {"●", "*", "×"}]
        if len(tokens) >= 2:
            loaded[tokens[0]] = tokens[1]
    return Inventory(files, loaded, blocks)


def instances_of(template: str, inventory: Inventory) -> tuple[str, ...]:
    """Enabled instances of ``x@.timer``: names ``x@<id>.timer`` the host knows about."""
    stem, _, suffix = template.partition("@")
    found: set[str] = set()
    for name in (*inventory.files, *inventory.loaded, *inventory.blocks):
        if not (name.startswith(f"{stem}@") and name.endswith(suffix) and name != template):
            continue
        state = inventory.blocks.get(name, {}).get("UnitFileState") or inventory.files.get(name, "")
        if state.startswith("enabled"):
            found.add(name)
    return tuple(sorted(found))


# --------------------------------------------------------------------------- deploy/systemd


def deploy_unit_names(deploy_dir: Path) -> tuple[str, ...]:
    """Every ``*.service`` and ``*.timer`` file name under ``deploy_dir`` (templates included)."""
    try:
        return tuple(
            sorted(
                p.name
                for p in deploy_dir.iterdir()
                if p.is_file() and p.name.endswith(_UNITS_SUFFIXES)
            )
        )
    except OSError:
        return ()


def _sources(deploy_dir: Path, name: str) -> list[Path]:
    paths = [deploy_dir / name]
    if "@" in name:
        stem, _, rest = name.partition("@")
        if not rest.startswith("."):
            template = f"{stem}@.{rest.rsplit('.', 1)[-1]}"
            paths = [deploy_dir / template, deploy_dir / f"{template}.d"]
    paths.append(deploy_dir / f"{name}.d")
    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            out.extend(sorted(path.glob("*.conf")))
        elif path.is_file():
            out.append(path)
    return out


def logical_lines(text: str) -> list[str]:
    """Non-comment lines with backslash continuations joined."""
    joined: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not pending and (not line or line.startswith(("#", ";"))):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        joined.append((pending + line).strip())
        pending = ""
    if pending:
        joined.append(pending.strip())
    return joined


def directive_values(deploy_dir: Path, name: str, key: str) -> list[str]:
    """Values of ``key=`` for ``name`` in file order, an empty assignment clearing the list."""
    values: list[str] = []
    prefix = f"{key}="
    for path in _sources(deploy_dir, name):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in logical_lines(text):
            if line.startswith(prefix):
                value = line[len(prefix) :].strip()
                if value:
                    values.append(value)
                else:
                    values.clear()
    return values


def is_monotonic_timer(deploy_dir: Path, name: str, block: Mapping[str, str]) -> bool:
    """A timer with a non-empty ``TimersMonotonic`` (the block says so, else its unit files)."""
    if "TimersMonotonic" in block:
        return bool(block["TimersMonotonic"].strip())
    return any(directive_values(deploy_dir, name, key) for key in _MONOTONIC_KEYS)


def timer_accuracy_s(deploy_dir: Path, name: str) -> float | None:
    values = directive_values(deploy_dir, name, "AccuracySec")
    if not values:
        return float(DEFAULT_ACCURACY_S)
    return parse_accuracy_s(values[-1])


# --------------------------------------------------------------------------- OnCalendar


def _expand_field(text: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in text.split(","):
        match = _FIELD_PART_RE.fullmatch(part)
        if match is None:
            raise ValueError(f"unsupported calendar field {part!r}")
        head, tail, step_text = match.groups()
        start = low if head == "*" else int(head)
        stop = int(tail) if tail else (high if (head == "*" or step_text) else start)
        step = int(step_text) if step_text else 1
        if step < 1 or start < low or stop > high or start > stop:
            raise ValueError(f"calendar field out of range {part!r}")
        values.update(range(start, stop + 1, step))
    return values


def firing_minutes(spec: str) -> frozenset[int]:
    """Minutes of the UTC day (0-1439) at which ``spec`` fires.

    Only the shapes the deploy timers use: ``[*-*-*] HOURS:MINUTES[:SECONDS] [UTC]`` with ``*``,
    lists, ``a..b`` ranges and ``/step``. Anything else raises ``ValueError`` (never guessed).
    """
    tokens = spec.split()
    if tokens and tokens[-1] == "UTC":
        tokens = tokens[:-1]
    if not tokens or len(tokens) > 2 or (len(tokens) == 2 and tokens[0] != "*-*-*"):
        raise ValueError(f"unsupported calendar spec {spec!r}")
    clock = tokens[-1].split(":")
    if len(clock) not in {2, 3}:
        raise ValueError(f"unsupported calendar spec {spec!r}")
    hours = _expand_field(clock[0], 0, 23)
    minutes = _expand_field(clock[1], 0, 59)
    return frozenset(h * 60 + m for h in hours for m in minutes)


def max_gap_s(deploy_dir: Path, name: str) -> int | None:
    """The longest wait between two firings (circular over a day) of a calendar timer."""
    minutes: set[int] = set()
    for spec in directive_values(deploy_dir, name, "OnCalendar"):
        minutes |= firing_minutes(spec)
    if not minutes:
        return None
    ordered = sorted(minutes)
    if len(ordered) == 1:
        return _MINUTES_PER_DAY * 60
    gaps = [
        (ordered[(i + 1) % len(ordered)] - ordered[i]) % _MINUTES_PER_DAY
        for i in range(len(ordered))
    ]
    return max(gaps) * 60


def firing_minutes_of(deploy_dir: Path, name: str) -> frozenset[int]:
    minutes: set[int] = set()
    for spec in directive_values(deploy_dir, name, "OnCalendar"):
        minutes |= firing_minutes(spec)
    return frozenset(minutes)


def timer_target(deploy_dir: Path, timer: str) -> str:
    """The service a timer starts (``Unit=`` or the same stem)."""
    values = directive_values(deploy_dir, timer, "Unit")
    return values[-1] if values else timer.removesuffix(".timer") + ".service"


def names_matching(names: Sequence[str], suffix: str) -> tuple[str, ...]:
    return tuple(n for n in names if n.endswith(suffix))


# --------------------------------------------------------------------------- deployment state


@dataclass(frozen=True, slots=True)
class Deployment:
    """How a unit stands (decision X-8). ``state`` is ``deployed``, ``not_deployed`` (listed,
    before its deadline, no unit, no artifact: INCONCLUSIVE, never paged) or ``finding``."""

    state: str
    kind: str = ""
    severity: str = ""


DEPLOYED: Final = Deployment("deployed")
NOT_DEPLOYED: Final = Deployment("not_deployed")
