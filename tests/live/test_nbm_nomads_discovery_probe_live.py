"""LIVE execution of the NOMADS/NBM discovery probe against nomads.ncep.noaa.gov.

Authority: FC-0a-3 plan. Mirrors ``tests/live/test_iem_afos_forecast_pil_probe_live.py``.

**Deselected by default.** ``tests/unit/test_probe_containment.py`` proves the
deselection by collecting this file under the default options.

This module executes the probe and then asserts the ACCOUNTING -- never the
verdict's value. Whether a candidate shape is ANSWERED, PARTIAL, or ABSENT
is the finding; a test that asserted ANSWERED would have to be edited when
the evidence came back the other way.
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
PROBE_PATH = REPO_ROOT / "scripts/venue/nbm_nomads_discovery_probe.py"


def _load_probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("breezy_nbm_nomads_probe", PROBE_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise ImportError(f"cannot load {PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_nbm_nomads_discovery_probe_runs_within_budget_and_records_questions(
    tmp_path: Path,
) -> None:
    probe = _load_probe()
    user_agent = os.environ.get("BREEZY_USER_AGENT")
    if not user_agent:
        pytest.skip("BREEZY_USER_AGENT must name a monitored contact for a live probe")

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

    execution = await probe.run_probe(transport, writer)

    assert budget.spent <= budget.limit
    rows = (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(rows) - 1 == len(execution.exchanges)
    if execution.aborted is None:
        assert len(execution.exchanges) + len(execution.skipped) <= len(
            probe.build_discovery_plan()
        )
    else:
        assert len(execution.exchanges) + len(execution.skipped) <= len(
            probe.build_discovery_plan()
        )
    questions = probe.evaluate_questions(
        probe.build_discovery_plan(), execution.outcomes
    )
    assert set(questions) == set(probe.QUESTIONS)
