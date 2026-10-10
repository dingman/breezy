"""EXEC-PAR WP4: K=1 behaves exactly as before, except the enumerated deltas.

The golden (``golden_exec_par_wp4_k1.json``) was captured from the exec client
BEFORE any WP4 change. ``test_k1_differential_replay_identical_outputs``
replays the same scenarios on the current tree and demands byte-identical
observable output (events, denial reasons, durable write sequence, latched
refusals, permit and ledger), after dropping only the context blob's
``wireQuantity`` key (delta D6). None of D1-D5 is reachable by these scenarios,
which is part of the claim: at K=1 an ordinary day looks the same.

E14.7 (accepted, not a golden change): the duplicate detector also acts at K=1.
It examines only a no-id AMBIGUOUS intent older than the 300 s lag guard that
carries a holding baseline and a wire quantity, so none of these scenarios reach
it; it is strictly more conservative (it can only keep an intent AMBIGUOUS and
raise the sticky contradiction counter), so the golden is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.exec_par_k1_scenarios import SCENARIOS, run_k1_scenarios
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)

GOLDEN = Path(__file__).with_name("golden_exec_par_wp4_k1.json")


def test_golden_covers_every_scenario() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert sorted(golden) == sorted(SCENARIOS)


@pytest.mark.asyncio
async def test_k1_differential_replay_identical_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    actual = await run_k1_scenarios(tmp_path, monkeypatch)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for name in sorted(golden):
        assert actual[name] == golden[name], f"K=1 output drifted in scenario {name!r}"
