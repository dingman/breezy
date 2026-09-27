"""EDGE-6 6d (`docs/plans/backlog/EDGE_2026-09-27/EDGE-6_ops_reliability_
plan_r2_2026-09-27.md` AC-6d-1, section 4, file-by-file plan section 5, test
strategy section 6): pins the recorder-only discovery-reload override.

`data.py:1202-1204` (`_next_reload_delay_secs`) already treats an explicit
`instrument_reload_interval_mins` as an OPTIONAL operator override that wins
outright over the derived cadence; `factories.py:145,283-297,325`
(`config_from_env`) already reads that field from the environment variable
`POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS`, parses it as a positive
integer, and passes it through as-is (the adapter's own `_next_reload_delay_
secs` is what multiplies by 60 to get seconds). The capability is native;
6d adds ONE unit directive, no code.

The recorder (`breezy-quote-tape.service`) and the trade supervisor
(`breezy-trade-supervisor.service`) both load `EnvironmentFile=
/home/jon/.config/breezy/polymarket.env` (`breezy-quote-tape.service:81`,
`breezy-trade-supervisor.service:102`). Putting the override in that shared
file would change the LIVE NODE's cadence too, which is why the plan
requires an `Environment=` directive in the recorder unit only, and a test
guarding its absence from the supervisor unit (r2 section 2.4, "Placement").
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RECORDER_UNIT = _REPO_ROOT / "deploy" / "systemd" / "breezy-quote-tape.service"
_SUPERVISOR_UNIT = _REPO_ROOT / "deploy" / "systemd" / "breezy-trade-supervisor.service"

_DISCOVERY_RELOAD_ENV_VAR = "POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS"


def _directive_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _environment_directives(text: str) -> dict[str, str]:
    """Return every `Environment=NAME=VALUE` directive as a `{NAME: VALUE}`
    mapping. Deliberately excludes `EnvironmentFile=` -- that names a path,
    never a value, and this test's job is to check what THIS unit assigns
    directly, not what a shared, host-side file might contain (AM-3 covers
    that separately, out-of-repo)."""
    values: dict[str, str] = {}
    for line in _directive_lines(text):
        if not line.startswith("Environment="):
            continue
        assignment = line[len("Environment=") :]
        name, _, value = assignment.partition("=")
        values[name] = value
    return values


def test_recorder_unit_sets_discovery_reload_interval_to_15_minutes() -> None:
    values = _environment_directives(_RECORDER_UNIT.read_text())
    assert _DISCOVERY_RELOAD_ENV_VAR in values, (
        f"{_RECORDER_UNIT.name} must set {_DISCOVERY_RELOAD_ENV_VAR}= directly "
        "(EDGE-6 6d) so the recorder's discovery reload cadence is bounded "
        "to 15 minutes, independent of the derived cadence's own boundary "
        "targeting"
    )
    assert values[_DISCOVERY_RELOAD_ENV_VAR] == "15", values


def test_trade_supervisor_unit_does_not_set_discovery_reload_interval() -> None:
    """The live node must keep its DERIVED cadence. This unit never sets
    the override directly (`Environment=`); if the override ever leaked in
    here it would silently change the node's own reload cadence, which the
    plan explicitly forbids (r2 section 2.4, risk R4)."""
    values = _environment_directives(_SUPERVISOR_UNIT.read_text())
    assert _DISCOVERY_RELOAD_ENV_VAR not in values, values


def test_discovery_reload_env_var_name_matches_the_adapter_contract() -> None:
    """Guards against a silent rename drifting the unit and the adapter
    apart: the exact variable name the unit assigns must be the one
    `breezy.adapters.polymarket_us.factories.DISCOVERY_RELOAD_INTERVAL_ENV_VAR`
    reads (factories.py:145)."""
    from breezy.adapters.polymarket_us.factories import DISCOVERY_RELOAD_INTERVAL_ENV_VAR

    assert DISCOVERY_RELOAD_INTERVAL_ENV_VAR == _DISCOVERY_RELOAD_ENV_VAR
    values = _environment_directives(_RECORDER_UNIT.read_text())
    assert DISCOVERY_RELOAD_INTERVAL_ENV_VAR in values
