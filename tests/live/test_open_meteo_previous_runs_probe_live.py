"""LIVE execution of P2 Probe A against the real ``api.open-meteo.com``.

Authority: ``docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`` section 4.P2.

**Deselected by default.** ``pyproject.toml``'s ``addopts`` runs
``-m 'not live and not venue_live and not real_money'``, and
``tests/conftest.py`` additionally SKIPs a ``live`` test that is selected
without ``BREEZY_LIVE=1`` and blocks real sockets for everything unmarked.
Nothing in a default ``pytest`` run reaches this module, and
``tests/unit/test_probe_containment.py`` proves that by collecting this file
under the default options and asserting nothing is selected.

The markers are doubled on purpose. ``live`` is the socket/BREEZY_LIVE gate;
``venue_live`` adds the second unlock pair (``BREEZY_VENUE_LIVE=1`` plus
``BREEZY_ALLOW_CREDENTIALED_PYTEST=1`` plus ``--venue-live``). A probe that
spends a third-party request budget should need at least as much deliberate
unlocking as one that reads the venue.

Every containment property is asserted in the UNIT suite against fixtures.
This module exists to execute the plan once the operator has reviewed those,
and to assert the *accounting* afterwards: the budget was not over-spent, and
every dispatched request has a manifest row.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

from breezy.ingest.probe_transport import (
    MANIFEST_FILENAME,
    ProbeEvidenceWriter,
    ProbeTransport,
    RequestBudget,
)

pytestmark = [pytest.mark.live, pytest.mark.venue_live, pytest.mark.allow_socket]

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "scripts/venue/open_meteo_previous_runs_probe.py"


def _load_probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("breezy_open_meteo_probe", PROBE_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise ImportError(f"cannot load {PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_probe_a_runs_within_its_hard_budget(tmp_path: Path) -> None:
    probe = _load_probe()
    user_agent = os.environ.get("BREEZY_USER_AGENT")
    if not user_agent:
        pytest.skip("BREEZY_USER_AGENT must name a monitored contact for a live probe")

    plan = probe.build_request_plan()
    budget = RequestBudget(limit=probe.REQUEST_BUDGET)
    transport = ProbeTransport(
        base_url=probe.BASE_URL,
        allowed_hosts=probe.ALLOWED_HOSTS,
        budget=budget,
        max_body_bytes=probe.MAX_BODY_BYTES,
        user_agent=user_agent,
        accept="application/json",
        clock=time.time_ns,
    )
    writer = ProbeEvidenceWriter(tmp_path)

    exchanges, aborted = await probe.execute(transport, writer, plan)

    assert aborted is None, aborted
    assert budget.spent <= budget.limit
    rows = (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(rows) - 1 == len(exchanges), "every dispatched request needs a manifest row"
