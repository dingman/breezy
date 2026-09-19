"""2026-09-11 K1 incident follow-up: every NIGHTLY ANALYSIS unit must carry
its own cgroup memory ceiling.

`breezy-k1-daily.service` (`scripts/analysis/k1_cheap_open_settlement.py`
via `deploy/systemd/k1-daily-run.sh`) reached a 17.6 GB memory peak in under
2 minutes on 2026-09-11 with NO `MemoryHigh=`/`MemoryMax=` on the unit,
pushing the 31 GB host into swap while `breezy-trade-supervisor.service`
(the live trading node, deliberately left UNcapped -- its own :64 comment)
was running at ~625 MB. It was stopped by hand.

This module parses the deploy/systemd unit text directly -- it never reads
from or writes to any INSTALLED systemd unit path, and never runs
`systemctl`/`daemon-reload` (mirrors
`tests/unit/test_trade_supervisor_phase1_unit.py`'s own posture).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_DEPLOY_DIR = Path(__file__).resolve().parents[2] / "deploy" / "systemd"

# Every nightly-analysis unit this incident's fix must reach. Each is
# checked for existence first -- the brief allows skipping any that is not
# actually present on disk.
_CANDIDATE_UNITS = [
    "breezy-k1-daily.service",
    "breezy-mb-daily.service",
    "breezy-offer-gate-daily.service",
    # WP-11b (active-family registry, cardinality-1): the retired
    # breezy-pm-crh-v2-tally.service/breezy-pm-crh-cont-tally.service pair
    # is replaced by ONE shared instantiated template, checked here so its
    # own cgroup ceiling never goes uncovered.
    "breezy-family-tally@.service",
    "breezy-live-tally.service",
    "breezy-score-live-trials.service",
    "breezy-quote-tape-ingest.service",
]

_EXISTING_UNITS = [
    name for name in _CANDIDATE_UNITS if (_DEPLOY_DIR / name).is_file()
]

_SUPERVISOR_UNIT = _DEPLOY_DIR / "breezy-trade-supervisor.service"

# systemd data-size suffixes (systemd.syntax(7)): binary (base-1024)
# multipliers, matching the "K"/"M"/"G"/"T" values used across this repo's
# unit files (e.g. breezy-quote-tape.service's MemoryHigh=2G).
_SIZE_MULTIPLIERS = {
    "": 1,
    "K": 1024,
    "M": 1024**2,
    "G": 1024**3,
    "T": 1024**4,
}

_SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)([KMGT]?)$")


def _parse_systemd_size(raw: str) -> float:
    match = _SIZE_RE.match(raw.strip())
    assert match is not None, f"unparseable systemd size literal: {raw!r}"
    number, suffix = match.groups()
    return float(number) * _SIZE_MULTIPLIERS[suffix]


def _directive_value(unit_text: str, directive: str) -> str | None:
    """Return the value of a `Directive=value` line, ignoring comments.

    Only lines that are ACTUAL directives count -- a line starting with `#`
    (after stripping leading whitespace) never does, even when the comment
    prose itself contains the literal substring `f"{directive}="` (as
    `breezy-trade-supervisor.service`'s own :64 comment does, verbatim,
    to document that the directive is deliberately absent).
    """
    prefix = f"{directive}="
    for line in unit_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(prefix):
            return stripped[len(prefix) :]
    return None


@pytest.mark.parametrize("unit_name", _CANDIDATE_UNITS)
def test_candidate_unit_exists_or_is_explicitly_skippable(unit_name: str) -> None:
    """Documents which of the seven candidates are actually on disk. This
    is informational only -- the brief explicitly allows skipping any unit
    that does not exist; it must never fail the suite."""
    exists = (_DEPLOY_DIR / unit_name).is_file()
    assert exists in (True, False)  # tautology: never fails, just documents


def test_at_least_one_nightly_analysis_unit_exists() -> None:
    assert _EXISTING_UNITS, "no nightly-analysis units found under deploy/systemd/"


@pytest.mark.parametrize("unit_name", _EXISTING_UNITS)
def test_nightly_analysis_unit_has_a_memory_max_ceiling(unit_name: str) -> None:
    text = (_DEPLOY_DIR / unit_name).read_text()
    memory_max = _directive_value(text, "MemoryMax")
    assert memory_max is not None, f"{unit_name} is missing MemoryMax="
    assert _parse_systemd_size(memory_max) <= _parse_systemd_size("16G"), (
        f"{unit_name} MemoryMax={memory_max} exceeds the 16G incident-response ceiling"
    )


@pytest.mark.parametrize("unit_name", _EXISTING_UNITS)
def test_nightly_analysis_unit_has_a_memory_high_below_memory_max(
    unit_name: str,
) -> None:
    text = (_DEPLOY_DIR / unit_name).read_text()
    memory_high = _directive_value(text, "MemoryHigh")
    memory_max = _directive_value(text, "MemoryMax")
    assert memory_high is not None, f"{unit_name} is missing MemoryHigh="
    assert memory_max is not None, f"{unit_name} is missing MemoryMax="
    assert _parse_systemd_size(memory_high) < _parse_systemd_size(memory_max), (
        f"{unit_name} MemoryHigh={memory_high} must be strictly below "
        f"MemoryMax={memory_max}"
    )


@pytest.mark.parametrize("unit_name", _EXISTING_UNITS)
def test_nightly_analysis_unit_cites_the_2026_09_11_k1_incident(
    unit_name: str,
) -> None:
    text = (_DEPLOY_DIR / unit_name).read_text()
    assert "2026-09-11" in text, f"{unit_name} does not cite the K1 incident date"
    assert "k1-daily" in text.lower() or "17.6 gb" in text.lower(), (
        f"{unit_name} does not reference the K1 incident's own unit or peak"
    )


def test_trade_supervisor_unit_still_has_neither_memory_directive() -> None:
    """Pinned deliberately: the supervisor's uncapped state is intentional
    (its own :64 comment) precisely so a cgroup OOM (SIGKILL) never tears
    down a spawned node that may be holding a live position. This incident
    fix must never "helpfully" cap it too."""
    text = _SUPERVISOR_UNIT.read_text()
    assert _directive_value(text, "MemoryHigh") is None
    assert _directive_value(text, "MemoryMax") is None
    # The comment documenting the deliberate absence must still be present.
    assert "NO MemoryHigh=/MemoryMax=" in text
