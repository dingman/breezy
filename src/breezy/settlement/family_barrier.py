"""Family-scope barrier: refuse a tally that mixes rows across families (6f).

PURE module (settlement purity guard D1: no `datetime`, `os`, `pathlib`,
`time`, or similar side-effecting/non-deterministic imports). It imports
only `ScoredTrial` (`settlement/trial_scorer.py`, same package) and a
structural `FamilyIdentity` protocol defined here -- never
`breezy.persistence.family_manifest.FamilyManifest` directly. The layer
contract (`pyproject.toml` `[tool.importlinter]`) places `persistence`
ABOVE `settlement` (the direction `scored_trial_store.py` already uses:
`persistence` imports `settlement`, never the reverse), so `settlement`
importing a `persistence` dataclass would invert the graph. `FamilyManifest`
satisfies `FamilyIdentity` structurally -- same attribute names and types --
without either module importing the other.

Blueprint "v1-rows-through-v2 refusal": a family shares its trial-id prefix
with an older sibling on the same latch (PM v1 and v2 both mint
`current_rung_hold/trial/...`), so the prefix alone cannot separate them.
The manifest's registered `d0_climate_day` is the second, symmetric
discriminant. `climate_day` is the trial's LST station-day (the latch key,
never DST -- `trial_day_latch.py`, `climate_day.py`), and is compared as a
plain ISO-8601 string: lexicographic order matches calendar order for
zero-padded `YYYY-MM-DD` dates, so no date-parsing import is needed here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from breezy.settlement.trial_scorer import ScoredTrial

__all__ = ["FamilyBarrierRefusal", "FamilyIdentity", "assert_family_only"]


class FamilyIdentity(Protocol):
    """Structural shape `assert_family_only` needs from a family manifest."""

    trial_id_prefix: str
    d0_climate_day: str
    stations: tuple[str, ...]


class FamilyBarrierRefusal(Exception):
    """A scored-trial row does not belong to the family this manifest declares."""


def assert_family_only(rows: Sequence[ScoredTrial], manifest: FamilyIdentity) -> None:
    """Refuse the whole tally if any row is out of `manifest`'s family scope.

    Three independent checks, any of which refuses the ENTIRE batch -- never
    a silent per-row drop: the trial-id must start with the family's own
    prefix, `climate_day` must not precede the family's registered
    `d0_climate_day`, and `station` must be in the family's registered
    `stations` census (B2: a family manifest may deliberately exclude a
    station -- e.g. `pm_us_crh_v2.json` excludes NYC -- and a row from an
    excluded station must never be silently pooled into strata). Symmetric
    by construction: swapping which manifest is checked against which rows
    still refuses the mismatch.
    """
    for row in rows:
        if not row.trial_id.startswith(manifest.trial_id_prefix):
            raise FamilyBarrierRefusal(
                f"{row.trial_id!r} does not start with family prefix {manifest.trial_id_prefix!r}"
            )
        if row.climate_day < manifest.d0_climate_day:
            raise FamilyBarrierRefusal(
                f"{row.trial_id!r}: climate_day {row.climate_day!r} precedes "
                f"family D0 {manifest.d0_climate_day!r}"
            )
        if row.station not in manifest.stations:
            raise FamilyBarrierRefusal(
                f"{row.trial_id!r}: station {row.station!r} is not in the "
                f"family's registered station census {manifest.stations!r}"
            )
