"""LIVE execution of P2 Probe B against the real ``mesonet.agron.iastate.edu``.

Authority: ``docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`` section 4.P2.

**Deselected by default**, exactly as the Probe A live module is -- see that
module's header for the full gating chain. ``tests/unit/test_probe_containment.py``
proves the deselection by collecting this file under the default options.

This module executes the probe and then asserts the ACCOUNTING and the
VERDICT MECHANICS -- never the verdict's value. Whether AFOS clears the
pre-registered bar is the finding; a test that asserted PASS would be a test
that had to be edited when the evidence came back the other way, which is how
a pre-registered bar stops being pre-registered.
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
from breezy.registry.sites import default_registry

pytestmark = [pytest.mark.live, pytest.mark.venue_live, pytest.mark.allow_socket]

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "scripts/venue/iem_afos_forecast_pil_probe.py"


def _load_probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("breezy_iem_afos_probe", PROBE_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise ImportError(f"cannot load {PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_probe_b_runs_within_budget_and_computes_a_verdict(tmp_path: Path) -> None:
    probe = _load_probe()
    user_agent = os.environ.get("BREEZY_USER_AGENT")
    if not user_agent:
        pytest.skip("BREEZY_USER_AGENT must name a monitored contact for a live probe")

    registry = default_registry()
    plan = probe.build_request_plan()
    budget = RequestBudget(limit=probe.REQUEST_BUDGET)
    transport = ProbeTransport(
        base_url=probe.BASE_URL,
        allowed_hosts=probe.ALLOWED_HOSTS,
        budget=budget,
        max_body_bytes=probe.MAX_BODY_BYTES,
        user_agent=user_agent,
        accept="text/plain",
        clock=time.time_ns,
    )
    writer = ProbeEvidenceWriter(tmp_path)

    execution = await probe.execute(transport, writer, plan)

    assert budget.spent <= budget.limit
    rows = (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(rows) - 1 == len(execution.exchanges)
    # An abort is a legitimate OUTCOME (a failed baseline stops the run rather
    # than re-spending the budget), so its accounting is asserted, not its
    # absence: aborting must always name the steps it skipped.
    if execution.aborted is None:
        assert execution.skipped == ()
        assert len(execution.exchanges) == len(plan)
    else:
        assert len(execution.exchanges) + len(execution.skipped) <= len(plan)

    offices = {
        city: registry.settlement_site(probe.VENUE, city).issuing_office
        for city in probe.PROBE_CITIES
    }
    census = probe.census_from_outcomes(execution.outcomes, offices)
    verdict = probe.evaluate_verdict(census)
    # The VALUE of the verdict is the finding, not an assertion. Only its
    # internal consistency is asserted here.
    assert verdict.passed is (verdict.failures == ())
