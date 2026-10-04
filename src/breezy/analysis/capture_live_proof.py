"""AUT-1 WP5 stage 3a STUB: the live-proof roll-up (design r3 D8; plan r12 sections 3.11.5, 6).

Per family: the qualifying days, the stale-INCONCLUSIVE break, the heal pairing and the NBP-heal
alternative. Stage 3 stream S2 fills it in; until then ``build_live_proof`` raises
``NotImplementedError``.
"""

import datetime as dt
from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = ["build_live_proof"]


def build_live_proof(data_root: Path, family_id: str, asof: dt.date) -> Mapping[str, Any]:
    """The roll-up of ``family_id`` as of ``asof`` (stage 3 S2)."""
    raise NotImplementedError("stage 3 S2: the live-proof roll-up")
