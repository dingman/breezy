"""Shared F6 test helper: write a ``loss_stop/v1`` artefact (a valid, guarded one).

Used by the probe tests, the ``app.trade`` wiring tests and the CT-12 halt
test so the artefact shape lives in exactly one place.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import SCHEMA, compute_digest


def write_artefact(
    path: Path,
    *,
    verdict: str = "PASS",
    as_of: datetime | None = None,
    c2_hwm: str = "c2-100",
    truth_sha: str = "t" * 64,
    digest: str | None = None,
    schema: str = SCHEMA,
    mode: int = 0o600,
) -> None:
    """``as_of`` defaults to one hour before the real wall clock; mtime follows it."""
    when = as_of if as_of is not None else datetime.now(tz=UTC) - timedelta(hours=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o755)  # the probe refuses a group/other-writable directory (umask 002 hosts)
    as_of_text = when.isoformat().replace("+00:00", "Z")
    body = {
        "schema": schema,
        "verdict": verdict,
        "as_of": as_of_text,
        "c2_hwm": c2_hwm,
        "truth_sha": truth_sha,
        "digest": digest
        or compute_digest(verdict=verdict, as_of=as_of_text, c2_hwm=c2_hwm, truth_sha=truth_sha),
    }
    path.write_text(json.dumps(body))
    path.chmod(mode)
    os.utime(path, (when.timestamp(), when.timestamp()))
