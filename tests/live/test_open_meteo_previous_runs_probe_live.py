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

    budget = RequestBudget(limit=probe.REQUEST_BUDGET)
    writer = ProbeEvidenceWriter(tmp_path)

    def factory(shape: object) -> ProbeTransport:
        # ``probe`` is loaded from a path at runtime, so every attribute of it
        # is typed ``Any``. Narrow by ASSERTING the contract rather than
        # casting it away: a probe that handed back a bare ``httpx`` client --
        # no budget, no allowlist, redirects followed -- would fail here
        # instead of silently spending the run outside containment.
        transport = probe.build_transport(shape, budget=budget, user_agent=user_agent)
        assert isinstance(transport, ProbeTransport), (
            f"build_transport must return a contained ProbeTransport, got {type(transport)!r}"
        )
        return transport

    discovery, plan, execution, discovery_plan = await probe.run_probe(factory, writer)

    assert budget.spent <= budget.limit
    assert len(discovery.exchanges) <= probe.DISCOVERY_BUDGET
    rows = (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8").splitlines()
    dispatched = len(discovery.exchanges) + len(execution.exchanges)
    assert len(rows) - 1 == dispatched, "every dispatched request needs a manifest row"

    # A discovery failure must ABORT the plan rather than spend it re-learning
    # the same negative -- the 2026-08-31 defect this harness now guards.
    if discovery.shape is None:
        assert execution.exchanges == ()
        assert len(execution.skipped) == len(plan)

    questions = probe.evaluate_questions(
        (*discovery_plan, *plan), (*discovery.outcomes, *execution.outcomes)
    )
    verdict = probe.evaluate_verdict(questions, shape=discovery.shape, keyed=discovery.keyed)
    assert verdict.verdict in {
        probe.VERDICT_VIABLE,
        probe.VERDICT_NOT_VIABLE,
        probe.VERDICT_INCONCLUSIVE,
    }
    # No question may be answered by a step that did not return 2xx with data.
    answered = {outcome.question for outcome in questions if outcome.answered}
    dispatched_ok = {
        outcome.label
        for outcome in (*discovery.outcomes, *execution.outcomes)
        if outcome.succeeded and outcome.datum is not None
    }
    for outcome in questions:
        if outcome.question in answered:
            assert set(outcome.answered_by) <= dispatched_ok
