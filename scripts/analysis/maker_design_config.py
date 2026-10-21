"""MAKER design config: the read fence, the arm table and the plan cache.

The fence is enforced, not trusted: climate days stop at ``LAST_ALLOWED_DAY`` (the first day of the
MAKER-S2 second-look block is never reachable), only the four maker stations are accepted, the
scratch and output roots must be children of the design locations (never a production Stage 0
work root, ledger, amendment or verdict directory), and every path is expanded here once.

The plan cache holds the result of ``CatalogSession.plan``: that walk byte-scans every recorder
instance and costs hours, so it is done once per catalog state and read back afterwards.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts.analysis import maker_design_score as score
from scripts.analysis import maker_stage0_rule as rule
from scripts.analysis.maker_stage0_catalog_read import StationDayPlan
from scripts.analysis.maker_stage0_frozen import LAST_ALLOWED_DAY
from scripts.analysis.maker_stage0_inputs import MAKER_STATIONS

__all__ = [
    "ARMS",
    "Arm",
    "DesignConfig",
    "DesignRefused",
    "Key",
    "check_out_dir",
    "load_config",
    "parse_config",
    "read_plan_cache",
    "write_plan_cache",
]

Key = tuple[str, dt.date]
WORK_BASE_REL: Final[str] = ".cache/breezy/maker_design_work"
OUT_BASE_REL: Final[str] = ".local/share/breezy/derived/replay/design"

_REQUIRED: Final[frozenset[str]] = frozenset(
    {
        "from", "to", "stations", "arms", "theta", "slip", "catalog_root", "nbp_root",
        "census_days", "trade_unit", "truth", "calibration", "calibration_sha256", "work_root",
    }
)  # fmt: skip
_KEYS: Final[frozenset[str]] = _REQUIRED | {"reference", "plan_cache", "workers"}
MAX_WORKERS: Final[int] = 4
#: no bid may reach NO >= 0.90: that population is the frozen M1-v3 read-once
NO_BID_CEILING: Final[float] = 0.90
_SHA256 = re.compile(r"[0-9a-f]{64}")


class DesignRefused(ValueError):
    """A config or output location outside the fence; nothing was read."""


@dataclass(frozen=True, slots=True)
class Arm:
    name: str
    b_cap: float
    max_rungs: int
    abstain: bool
    spike: bool = False
    p_min: float | None = None  # None: the shipped rule value
    e_min: float | None = None
    b_floor: float | None = None
    delta_ns: int = 0  # recorder clock offset handed to the simulator (it applies |delta|)


ARMS: Final[Mapping[str, Arm]] = {
    a.name: a
    for a in (
        Arm("control", rule.B_CAP, rule.MAX_RUNGS, True),
        Arm("control_noabst", rule.B_CAP, rule.MAX_RUNGS, False),
        Arm("nbp_deep", 0.84, 3, False),
        Arm("spike_bid", rule.B_CAP, rule.MAX_RUNGS, False, spike=True),
        Arm("sharp", 0.89, 2, False, p_min=0.97, e_min=0.04, b_floor=0.75),
        Arm("sharp_cap84", 0.84, 2, False, p_min=0.97, e_min=0.04, b_floor=0.75),
        Arm(
            "sharp_dp600",
            0.89,
            2,
            False,
            p_min=0.97,
            e_min=0.04,
            b_floor=0.75,
            delta_ns=600 * 10**9,
        ),
        Arm(
            "sharp_dm600",
            0.89,
            2,
            False,
            p_min=0.97,
            e_min=0.04,
            b_floor=0.75,
            delta_ns=-600 * 10**9,
        ),
        Arm("sharp_k1", 0.89, 1, False, p_min=0.97, e_min=0.04, b_floor=0.75),
    )
}


@dataclass(frozen=True, slots=True)
class DesignConfig:
    day_from: dt.date
    day_to: dt.date
    stations: tuple[str, ...]
    arms: tuple[str, ...]
    theta: tuple[float, ...]
    slip: tuple[float, ...]
    catalog_root: Path
    nbp_root: Path
    census_days: Path
    trade_unit: Path
    truth: Path
    calibration: Path
    calibration_sha256: str
    work_root: Path
    reference: Path | None = None
    plan_cache: Path | None = None
    workers: int = 1

    @property
    def grid(self) -> score.Grid:
        return score.Grid(self.theta, self.slip)


# --- config and fence ------------------------------------------------------------------------


def _day(raw: Mapping[str, object], key: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(raw[key]))
    except ValueError as exc:
        raise DesignRefused(f"{key!r} is not an ISO date: {raw[key]!r}") from exc


def _names(
    raw: Mapping[str, object], key: str, allowed: Collection[str], what: str
) -> tuple[str, ...]:
    value = raw[key]
    names = tuple(str(v) for v in value) if isinstance(value, list) else ()
    if not names or len(set(names)) != len(names) or not set(names) <= set(allowed):
        raise DesignRefused(f"{what} must be distinct and drawn from {sorted(allowed)}: {value!r}")
    return names


def _floats(raw: Mapping[str, object], key: str) -> tuple[float, ...]:
    value = raw[key]
    try:
        numbers = tuple(float(v) for v in value) if isinstance(value, list) else ()
    except (TypeError, ValueError):
        numbers = ()
    if len(numbers) < 2 or any(not math.isfinite(v) or v < 0 for v in numbers):
        raise DesignRefused(f"{key} needs a base and a stress value, finite and >= 0: {value!r}")
    return numbers


def _path(raw: Mapping[str, object], key: str) -> Path:
    return Path(str(raw[key])).expanduser()


def _under(path: Path, base: Path) -> bool:
    return base.resolve() in path.resolve().parents


def parse_config(raw: Mapping[str, object]) -> DesignConfig:
    unknown, missing = set(raw) - _KEYS, _REQUIRED - set(raw)
    if unknown or missing:
        raise DesignRefused(f"config keys: unknown {sorted(unknown)}, missing {sorted(missing)}")
    day_from, day_to = _day(raw, "from"), _day(raw, "to")
    if day_to > LAST_ALLOWED_DAY:
        raise DesignRefused(
            f"'to' {day_to} is past the fence {LAST_ALLOWED_DAY} (second-look block)"
        )
    if day_from > day_to:
        raise DesignRefused(f"empty range {day_from}..{day_to}")
    sha = str(raw["calibration_sha256"])
    if not _SHA256.fullmatch(sha):
        raise DesignRefused("calibration_sha256 must be 64 lowercase hex digits (a sha256)")
    work_root = _path(raw, "work_root")
    if not _under(work_root, Path.home() / WORK_BASE_REL):
        raise DesignRefused(f"work_root {work_root} must be a child of ~/{WORK_BASE_REL}")
    workers = raw.get("workers", 1)
    if not isinstance(workers, int) or isinstance(workers, bool) or not 1 <= workers <= MAX_WORKERS:
        raise DesignRefused(f"workers must be an integer in 1..{MAX_WORKERS}: {workers!r}")
    arms = _names(raw, "arms", tuple(ARMS), "arms")
    if any(ARMS[a].b_cap >= NO_BID_CEILING for a in arms):
        raise DesignRefused(f"an arm's B_CAP can reach NO >= {NO_BID_CEILING:.2f} (M1-v3 cell)")
    reference, cache = raw.get("reference"), raw.get("plan_cache")
    if cache is not None and not _under(_path(raw, "plan_cache"), Path.home() / WORK_BASE_REL):
        raise DesignRefused(f"plan_cache {cache} must be a file under ~/{WORK_BASE_REL}")
    return DesignConfig(
        day_from=day_from,
        day_to=day_to,
        stations=_names(raw, "stations", MAKER_STATIONS, "stations (maker stations only)"),
        arms=arms,
        theta=_floats(raw, "theta"),
        slip=_floats(raw, "slip"),
        catalog_root=_path(raw, "catalog_root"),
        nbp_root=_path(raw, "nbp_root"),
        census_days=_path(raw, "census_days"),
        trade_unit=_path(raw, "trade_unit"),
        truth=_path(raw, "truth"),
        calibration=_path(raw, "calibration"),
        calibration_sha256=sha,
        work_root=work_root,
        reference=None if reference is None else Path(str(reference)).expanduser(),
        plan_cache=None if cache is None else Path(str(cache)).expanduser(),
        workers=workers,
    )


def load_config(path: Path) -> DesignConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise DesignRefused(f"{path} is not a JSON object")
    return parse_config(raw)


def check_out_dir(path: Path) -> Path:
    """A fresh (or empty) child of the design output root: never a production Stage 0 location."""
    base = Path.home() / OUT_BASE_REL
    if not _under(path.expanduser(), base):
        raise DesignRefused(f"out_dir {path} must be a child of {base}")
    if path.exists() and any(path.iterdir()):
        raise DesignRefused(f"out_dir {path} is not empty")
    return path


# --- the plan (one slow catalog walk, then cached) ------------------------------------------

PLAN_CACHE_VERSION: Final[int] = 1


def write_plan_cache(
    path: Path, plans: Mapping[Key, StationDayPlan], skipped: Mapping[str, str]
) -> Path:
    """Persist a catalog walk: the walk byte-scans every recorder instance and costs hours."""
    body = {
        "version": PLAN_CACHE_VERSION,
        "plans": {
            f"{station}|{day.isoformat()}": {
                "instruments": list(plan.instruments),
                "instances": list(plan.instances),
                "catalog_bytes": plan.catalog_bytes,
            }
            for (station, day), plan in sorted(plans.items())
        },
        "skipped": dict(sorted(skipped.items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8")
    return path


def read_plan_cache(path: Path) -> tuple[dict[Key, StationDayPlan], dict[str, str]]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        if body["version"] != PLAN_CACHE_VERSION:
            raise ValueError(f"version {body['version']!r}")
        plans = {
            (str(k).split("|")[0], dt.date.fromisoformat(str(k).split("|")[1])): StationDayPlan(
                tuple(v["instruments"]), tuple(v["instances"]), int(v["catalog_bytes"])
            )
            for k, v in body["plans"].items()
        }
        return plans, {str(k): str(v) for k, v in body["skipped"].items()}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise DesignRefused(
            f"plan cache {path} is not a version-{PLAN_CACHE_VERSION} cache: {exc}"
        ) from exc
