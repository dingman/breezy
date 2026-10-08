"""Audit: in-process alert delivery for Breezy systemd units
(2026-09-25, backlog/units-alerts-env-2026-09-25).

`resolve_alert_sink(os.environ)` (breezy.runtime.health) needs
`BREEZY_ALERT_WEBHOOK_URL`, which units get only via
`EnvironmentFile=-%h/.config/breezy/alerts.env`. A UNIT-level failure is
always surfaced via `OnFailure=breezy-study-failed@%n.service` regardless of
this file, but a run that otherwise SUCCEEDS and alerts IN-PROCESS (calls
`resolve_alert_sink`/`emit_alert`/`alert_ladder` itself) degrades silently to
journal-only logging without it -- a detector without delivery.

This module parses `.service` files as text; it never runs systemctl.

Audit trace (ExecStart-reachable script traced for
resolve_alert_sink/emit_alert/alert_ladder calls):

    breezy-family-tally@.service
        YES -- scripts/analysis/family_tally_v2.py:109,1025
        (emit_family_tally_failure_alert; wired from
        deploy/systemd/family-tally-v2-run.sh:330)
    breezy-hypothesis-triage.service
        YES -- scripts/analysis/hypothesis_triage.py:61,433,446
        (resolve_alert_sink/emit_alert via deploy/systemd/
        hypothesis-triage-run.sh)
    breezy-decisions-retention.service
        NO -- scripts/ops/decisions_retention.py: no alert import
    breezy-live-tally.service
        NO -- scripts/analysis/live_family_tally.py: no alert import
        (retired; timer disabled)
    breezy-position-monitor-report.service
        NO -- scripts/analysis/position_monitor_nightly_report.py: no
        alert import. The AUD-07 EXIT_CORPUS_FROZEN /
        EXIT_PNL_RECONCILIATION_MISMATCH ladder lives in
        scripts/analysis/current_rung_hold_exit_window_study.py
        (src/breezy/runtime/alert_ladder.py), driven ONLY by
        breezy-exit-window-study.service -- excluded from this audit,
        fixed on another branch.
    breezy-quote-tape-ingest.service
        NO -- src/breezy/runtime/quote_tape_ingest_cli.py: no alert import
    breezy-quote-tape-rotate.service
        NO -- ExecStart is `systemctl --user try-restart
        breezy-quote-tape.service`: no Python invoked at all
    breezy-score-live-trials.service
        NO -- scripts/analysis/score_live_trials.py,
        scripts/analysis/structural_dead_stop.py: no alert import

Promoting a unit's script to alert in-process later: add its unit name to
`_ALERTS_IN_PROCESS` below (and update the audit trace above) -- this test
then requires `alerts.env` on it without any other change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"

_ALERTS_ENV_DIRECTIVE = "EnvironmentFile=-%h/.config/breezy/alerts.env"

# Declared set -- see the audit trace in this module's docstring. Every unit
# named here must carry `_ALERTS_ENV_DIRECTIVE`; every audited unit NOT named
# here must not.
_ALERTS_IN_PROCESS = frozenset(
    {
        "breezy-family-tally@.service",
        "breezy-hypothesis-triage.service",
        "breezy-autonomy-alert-redeliver.service",
        "breezy-autonomy-canary.service",
    }
)

_ALL_AUDITED_UNITS = frozenset(
    {
        "breezy-decisions-retention.service",
        "breezy-family-tally@.service",
        "breezy-hypothesis-triage.service",
        "breezy-live-tally.service",
        "breezy-position-monitor-report.service",
        "breezy-quote-tape-ingest.service",
        "breezy-quote-tape-rotate.service",
        "breezy-score-live-trials.service",
    }
)


def _directive_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if not line.strip().startswith("#")]


@pytest.mark.parametrize("unit_name", sorted(_ALERTS_IN_PROCESS))
def test_unit_that_alerts_in_process_loads_alerts_env(unit_name: str) -> None:
    service_path = _SYSTEMD_DIR / unit_name
    assert service_path.is_file(), f"{unit_name} not found under {_SYSTEMD_DIR}"
    lines = _directive_lines(service_path.read_text())
    assert _ALERTS_ENV_DIRECTIVE in lines, (
        f"{unit_name} can alert in-process (see this module's audit trace) "
        f"but does not load {_ALERTS_ENV_DIRECTIVE}"
    )


@pytest.mark.parametrize("unit_name", sorted(_ALL_AUDITED_UNITS - _ALERTS_IN_PROCESS))
def test_unit_that_never_alerts_in_process_has_no_alerts_env(unit_name: str) -> None:
    """Regression guard in the other direction: a unit audited NO must not
    silently gain `alerts.env` without updating the declared set (and the
    audit trace) above.
    """
    service_path = _SYSTEMD_DIR / unit_name
    assert service_path.is_file(), f"{unit_name} not found under {_SYSTEMD_DIR}"
    lines = _directive_lines(service_path.read_text())
    assert _ALERTS_ENV_DIRECTIVE not in lines
