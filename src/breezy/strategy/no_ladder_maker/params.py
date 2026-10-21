"""Rule constants as one frozen value, injected into every decision function.

`SHARP_V1` matches `scripts/analysis/maker_design_config.py` Arm("sharp"); `CONTROL_V1` is the
shipped Stage 0 rule (`maker_stage0_rule` module constants). Nothing here is a module global
that a decision function reads implicitly.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class MakerRuleParams:
    p_min: float
    e_min: float
    b_floor: float
    b_cap: float
    max_rungs: int
    stale_h: int
    cancel_lst: dt.time
    abstain_unlisted: bool
    max_simultaneous: int

    def __post_init__(self) -> None:
        if not 0.0 <= self.b_floor <= self.b_cap <= 1.0:
            raise ValueError(f"need 0 <= b_floor <= b_cap <= 1, got {self.b_floor}, {self.b_cap}")
        if not 0.0 <= self.p_min <= 1.0 or self.e_min < 0.0:
            raise ValueError("p_min must be in [0, 1] and e_min >= 0")
        if self.max_rungs < 1 or self.max_simultaneous < 1 or self.stale_h < 1:
            raise ValueError("max_rungs, max_simultaneous and stale_h must be >= 1")


SHARP_V1: Final = MakerRuleParams(
    p_min=0.97,
    e_min=0.04,
    b_floor=0.75,
    b_cap=0.89,
    max_rungs=2,
    stale_h=8,
    cancel_lst=dt.time(9, 0),
    abstain_unlisted=False,
    max_simultaneous=8,
)

CONTROL_V1: Final = MakerRuleParams(
    p_min=0.94,
    e_min=0.10,
    b_floor=0.70,
    b_cap=0.80,
    max_rungs=2,
    stale_h=8,
    cancel_lst=dt.time(9, 0),
    abstain_unlisted=True,
    max_simultaneous=8,
)
